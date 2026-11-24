"""Pure material planning: weighted counts, plus frozen v1 inventory plans."""
from functools import lru_cache
import json
import math
from pathlib import Path

from core.game_catalog import HARD_DAILY_LIMIT

@lru_cache(maxsize=1)
def catalog():
    return json.loads((Path(__file__).resolve().parents[1]/'src/material_catalog.json').read_text('utf-8'))


def yield_estimate(rows):
    # A lower-bound quantity times public probability is an estimate, not a
    # measured mean for a ranged payout. Missing probability means source-only.
    if any(r.get('chance') is None for r in rows): return None
    return sum(r['amount'][0]*r['chance'] for r in rows)


def stock_limited(target):
    # Missing flag is an existing, explicit inventory goal, never unlimited.
    return target.get('stock_limit_enabled', True)

def stock_complete(target, completed):
    prefix = target['ref']+'@'
    return (prefix+target.get('version','') in completed or
            bool(target.get('legacy_version') and prefix+target['legacy_version'] in completed))


def active_targets(snapshot, observation, completed, rules, used):
    enabled = [t for t in snapshot['targets'] if t['enabled']]
    targets, waiting = {}, {}
    for rank, target in enumerate(enabled, 1):
        if snapshot.get('inventory_only') and not stock_limited(target): continue
        ref = target['ref']
        if stock_limited(target):
            if stock_complete(target,completed): continue
            count = observation.get('inventory', {}).get(ref)
            if type(count) is not int:
                waiting[ref] = '库存待同步'; continue
            if count >= target['amount']: continue
        cap = rules.get(ref, {}).get('max_runs')
        if cap is not None and used.get(ref, 0) >= cap:
            waiting[ref] = '本轮手动次数上限已用完'; continue
        targets[ref] = dict(target, weight=len(enabled)-rank+1, rank=rank)
    return targets, waiting


def source_refs(stage_id, targets, rules, data):
    drops = data['stages'][stage_id]['drops']
    return [ref for ref, target in targets.items() if ref in drops
            and any(row.get('chance') != 0 for row in drops[ref])
            and stage_id not in target.get('excluded', [])
            and (not rules.get(ref, {}).get('stage') or rules[ref]['stage'] == stage_id)]


def stage_order(stage):
    return tuple(map(int, stage.split(':')[1].split('-')))

def is_hard(stage):
    return stage.startswith('hard:')

def hard_allowance(state):
    remaining = state.get('remaining_attempts')
    return min(remaining,HARD_DAILY_LIMIT) if type(remaining) is int and remaining>=0 else None

def allowed_sources(data, target, rules):
    ref = target['ref']
    pinned = rules.get(ref,{}).get('stage')
    return [s for s in data['items'][ref]['sources']
            if s not in target.get('excluded',[]) and (not pinned or s==pinned)]

def unavailable_sources(sources, states):
    unknown = [s for s in sources if states.get(s,{}).get('status') not in ('unavailable','sweepable')
               or (is_hard(s) and states[s]['status']=='sweepable' and hard_allowance(states[s]) is None)]
    if any(is_hard(s) for s in unknown): return 'HARD 关卡或剩余次数待确认',True
    if any(is_hard(s) and hard_allowance(states.get(s,{}))==0 for s in sources):
        return '可扫的 HARD 来源今日次数已用完',bool(unknown)
    return '没有已确认可扫的来源',bool(unknown)


def _shares(budget, rows, data):
    # Proportional sweep counts, not proportional stamina. Round on a
    # spendable budget so an unusable stamina remainder cannot skew ties.
    costs = {data['stages'][row['stage_id']]['cost'] for row in rows}
    unit = math.gcd(*costs)
    usable = budget//unit*unit
    scale = usable / sum(row['weight']*data['stages'][row['stage_id']]['cost'] for row in rows)
    quotas = [scale*row['weight'] for row in rows]
    counts = [math.floor(q) for q in quotas]
    left = budget-sum(n*data['stages'][r['stage_id']]['cost'] for n,r in zip(counts,rows))
    order = sorted(range(len(rows)),key=lambda i:(-(quotas[i]-counts[i]),-rows[i]['weight'],stage_order(rows[i]['stage_id'])))
    while True:
        added = False
        for i in order:
            cost = data['stages'][rows[i]['stage_id']]['cost']
            if cost <= left:
                counts[i] += 1; left -= cost; added = True
        if not added: return counts


def weighted_plan(snapshot, observation, completed, rules=None, used=None, reserve=0, data=None):
    data = data or catalog()
    rules, planned = rules or {}, dict(used or {})
    targets, waiting = active_targets(snapshot,observation,completed,rules,planned)
    balance = observation.get('balance')
    budget = max(0,balance-reserve) if type(balance) is int else 0
    result = {'rows':[], 'waiting':waiting, 'budget':budget, 'waiting_data':False}
    if snapshot.get('catalog_version') != data['version']:
        result['waiting'].update({ref:'目录版本已变化，请结束旧轮次后重新开始' for ref in targets})
        result['waiting_data'] = bool(targets or waiting)
        return result
    states = observation.get('stages',{})
    if type(balance) is not int:
        for ref,target in targets.items():
            allowed = allowed_sources(data,target,rules)
            unavailable = all(states.get(s,{}).get('status')=='unavailable' or
                              (is_hard(s) and hard_allowance(states.get(s,{}))==0) for s in allowed)
            waiting[ref] = unavailable_sources(allowed,states)[0] if unavailable else '体力或可扫关卡待同步'
            result['waiting_data'] |= not unavailable
        result['waiting_data'] |= any(reason=='库存待同步' for reason in waiting.values())
        return result
    hard_left = {s:hard_allowance(v) or 0 for s,v in states.items() if is_hard(s)}
    available = {s for s,v in states.items() if v.get('status')=='sweepable' and s in data['stages']
                 and (not is_hard(s) or hard_left[s]>0)}
    output = {}
    while targets:
        candidates = {s:source_refs(s,targets,rules,data) for s in available
                      if data['stages'][s]['cost']<=budget and (not is_hard(s) or hard_left[s]>0)}
        selected, covered = [], set()
        for ref in targets:
            if ref in covered: continue
            options = [s for s,refs in candidates.items() if ref in refs]
            if not options: continue
            source = min(options,key=lambda s:(s not in selected,
                -sum(targets[r]['weight'] for r in candidates[s] if r not in covered),
                data['stages'][s]['cost'],stage_order(s)))
            if source not in selected: selected.append(source)
            covered.update(candidates[source])
        rows = [dict(stage_id=s,refs=candidates[s],weight=max(targets[r]['weight'] for r in candidates[s]),
                     priority=min(targets[r]['rank'] for r in candidates[s])) for s in selected]
        rows.sort(key=lambda r:(-r['weight'],stage_order(r['stage_id'])))
        if not rows: break
        changed = False
        for row, count in zip(rows,_shares(budget,rows,data)):
            refs, stage_id = row['refs'], row['stage_id']
            limits = [rules[r]['max_runs']-planned.get(r,0) for r in refs if rules.get(r,{}).get('max_runs') is not None]
            if limits: count = min(count,max(0,min(limits)))
            if count<=0: continue
            sources = [stage_id]
            if is_hard(stage_id):
                # Multiple origins of one memory share a weighted quota. A
                # second source spends that quota, not a second copy of its weight.
                sources += sorted((s for s,rs in candidates.items()
                                   if s!=stage_id and is_hard(s) and rs==refs),key=stage_order)
            for source in sources:
                if not count: break
                cost = data['stages'][source]['cost']
                runs = min(count,hard_left[source],budget//cost) if is_hard(source) else count
                if not runs: continue
                saved = output.setdefault(source,dict(row,stage_id=source,count=0,cost=0,estimated={},
                    manual=any(r in rules for r in refs),reason='按同关最高优先级分配次数'))
                saved['count'] += runs; saved['cost'] += runs*cost
                saved['refs'] = list(dict.fromkeys(saved['refs']+refs))
                budget -= runs*cost
                count -= runs
                if is_hard(source): hard_left[source] -= runs
                for ref in refs: planned[ref] = planned.get(ref,0)+runs
                changed = True
        if not changed: break
        targets, next_waiting = active_targets(snapshot,observation,completed,rules,planned)
        for ref in next_waiting:
            if rules.get(ref,{}).get('max_runs') is not None and (used or {}).get(ref,0)<rules[ref]['max_runs']:
                next_waiting[ref] = '本次安排受本轮手动次数上限限制'
        waiting.update(next_waiting)
    original, initial_waiting = active_targets(snapshot,observation,completed,rules,used or {})
    waiting.update(initial_waiting)
    for ref,target in original.items():
        allowed = allowed_sources(data,target,rules)
        if not any(s in available for s in allowed):
            waiting[ref],unknown = unavailable_sources(allowed,states)
            result['waiting_data'] |= unknown
        elif not any(ref in row['refs'] for row in output.values()) and ref not in waiting:
            waiting[ref] = '本次体力不足以分配次数' if not output else '本次按优先级未分配次数'
    result['waiting_data'] |= any(reason=='库存待同步' for reason in waiting.values())
    result['rows'] = list(output.values())
    if any(is_hard(s) for s in output):
        result['rows'].sort(key=lambda r:(-r['weight'],stage_order(r['stage_id'])))
    for row in result['rows']:
        limited = any(stock_limited(t) and t['enabled'] and t['ref'] in data['stages'][row['stage_id']]['drops']
                      and not stock_complete(t,completed) for t in snapshot['targets'])
        row['batch_count'] = 1 if limited else min(5,row['count'])
    return result


def plan(snapshot, observation, completed, rules=None, used=None, reserve=0, data=None):
    if snapshot.get('allocation_version') == 2:
        return weighted_plan(snapshot,observation,completed,rules,used,reserve,data)
    return inventory_plan(snapshot,observation,completed,rules,used,reserve,data)


def inventory_plan(snapshot, observation, completed, rules=None, used=None, reserve=0, data=None):
    data = data or catalog()
    rules, used = rules or {}, used or {}
    inventory = observation.get('inventory',{})
    stages = observation.get('stages',{})
    balance = observation.get('balance')
    targets, waiting = {}, {}
    for t in snapshot['targets']:
        ref = t['ref']
        if not t['enabled'] or stock_complete(t,completed): continue
        if type(inventory.get(ref)) is not int:
            waiting[ref] = '库存待同步'; continue
        gap = max(0,t['amount']-inventory[ref])
        if not gap: continue
        cap = rules.get(ref,{}).get('max_runs')
        if cap is not None and used.get(ref,0) >= cap:
            waiting[ref] = '本轮手动次数上限已用完'; continue
        targets[ref] = dict(t,gap=gap)
    if snapshot.get('catalog_version') != data['version']:
        return {'rows':[], 'waiting':{**waiting,**{r:'目录版本已变化，请结束旧轮次后重新开始' for r in targets}}}
    if type(balance) is not int:
        return {'rows':[], 'waiting':{**waiting,**{r:'体力待同步' for r in targets}}}
    budget = max(0,balance-reserve)
    remaining = {r:t['gap'] for r,t in targets.items()}
    planned = dict(used)
    rows, source_only_done = [], set()
    last = None
    # Counts are allocated as batches, never one iteration per requested item.
    while targets:
        candidates = []
        for stage_id, stage in data['stages'].items():
            if stages.get(stage_id,{}).get('status') != 'sweepable' or stage['cost'] > budget: continue
            refs = [r for r,t in targets.items() if r in stage['drops'] and remaining[r] > 0
                    and r not in source_only_done and stage_id not in t.get('excluded',[])
                    and (not rules.get(r,{}).get('stage') or rules[r]['stage']==stage_id)
                    and (rules.get(r,{}).get('max_runs') is None or planned.get(r,0)<rules[r]['max_runs'])]
            yields = {r:yield_estimate(stage['drops'][r]) for r in refs}
            refs = [r for r in refs if yields[r] is None or yields[r]>0]
            if not refs: continue
            yields = {r:yields[r] for r in refs}
            priority = max(targets[r]['priority'] for r in refs)
            top = [r for r in refs if targets[r]['priority']==priority]
            known = all(yields[r] is not None for r in top)
            score = sum(min(1,(yields[r] or 0)/remaining[r]) for r in top)/stage['cost'] if known else 0
            candidates.append((priority,known,score,stage_id==last,stage_id,refs,yields))
        if not candidates: break
        # Stable stage tie-break, with a small preference for staying on a stage.
        candidates.sort(key=lambda c:(-c[0],-int(c[1]),-c[2],-int(c[3]),c[4]))
        _,_,_,_,stage_id,refs,yields = candidates[0]
        stage = data['stages'][stage_id]
        known = all(v is not None and v > 0 for v in yields.values())
        count = max(1,min(math.ceil(remaining[r]/yields[r]) for r in refs)) if known else 1
        count = min(count,budget//stage['cost'])
        limits = [rules[r]['max_runs']-planned.get(r,0) for r in refs if rules.get(r,{}).get('max_runs') is not None]
        if limits: count = min(count,min(limits))
        if count <= 0: break
        estimated = {r:(None if yields[r] is None else round(yields[r]*count,3)) for r in refs}
        rows.append({'stage_id':stage_id,'refs':refs,'count':count,'cost':count*stage['cost'],
                     'estimated':estimated,'manual':any(r in rules for r in refs),
                     'batch_count':min(5,count) if known and all(remaining[r]>5*yields[r] for r in refs) else 1,
                     'reason':'同时补充多种目标素材' if len(refs)>1 else '当前可扫的目标来源'})
        budget -= count*stage['cost']
        for ref in refs:
            planned[ref] = planned.get(ref,0)+count
            if yields[ref] is None: source_only_done.add(ref)
        # Include incidental co-drops in this PREVIEW only. Runtime always rereads.
        for ref in remaining:
            if ref in stage['drops']:
                value = yield_estimate(stage['drops'][ref])
                if value is not None: remaining[ref] = max(0,remaining[ref]-value*count)
        last = stage_id
    for ref,gap in remaining.items():
        if gap <= 0: continue
        cap = rules.get(ref,{}).get('max_runs')
        available = [s for s in data['items'][ref]['sources'] if s not in targets[ref].get('excluded',[])
                     and (not rules.get(ref,{}).get('stage') or rules[ref]['stage']==s)]
        if cap is not None and planned.get(ref,0)>=cap: reason='其余缺口受本轮手动次数上限限制'
        elif ref in source_only_done: reason='仅确认来源，单次后复读库存再安排'
        elif not any(stages.get(s,{}).get('status')=='sweepable' for s in available): reason='没有已确认可扫的来源'
        else: reason='体力不足或已达到保留体力'
        waiting[ref] = reason
    return {'rows':rows,'waiting':waiting}
