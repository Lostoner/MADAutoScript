"""Small deterministic greedy planner. Estimates never mutate observed inventory."""
from functools import lru_cache
import json
import math
from pathlib import Path


@lru_cache(maxsize=1)
def catalog():
    return json.loads((Path(__file__).resolve().parents[1]/'src/material_catalog.json').read_text('utf-8'))


def yield_estimate(rows):
    # A lower-bound quantity times public probability is an estimate, not a
    # measured mean for a ranged payout. Missing probability means source-only.
    if any(r.get('chance') is None for r in rows): return None
    return sum(r['amount'][0]*r['chance'] for r in rows)


def plan(snapshot, observation, completed, rules=None, used=None, reserve=0, data=None):
    data = data or catalog()
    rules, used = rules or {}, used or {}
    inventory = observation.get('inventory',{})
    stages = observation.get('stages',{})
    balance = observation.get('balance')
    targets, waiting = {}, {}
    for t in snapshot['targets']:
        ref = t['ref']
        if not t['enabled'] or ref+'@'+t['version'] in completed: continue
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
