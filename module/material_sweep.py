"""Execute finite NORMAL quotas, with optional exact-stock stopping conditions."""
from copy import deepcopy
import re
import time
import cv2

from core.game_catalog import stage_options
from core.material_store import MaterialStore, TASK
from core.material_planner import catalog, plan, stock_limited, active_targets, source_refs, stage_order
from core.picture import co_detect
from module import sweep_utils as sweep
from module.normal_sweep import navigate


def exact_inventory(lines, name):
    clean = [re.sub(r'\s+','',s).lstrip('|丨') for s in lines]
    if re.sub(r'\s+','',name) not in clean: return None
    values = []
    for text in clean:
        match = re.fullmatch(r'拥有数量[:：]([0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)',text)
        if match: values.append(int(match[1].replace(',','')))
    return values[0] if len(values)==1 else None


class Observer:
    def __init__(self, worker):
        self.w = worker
        self.data = catalog()
        self.options = stage_options('mad.normal_sweep')
        self.blocked_zones = set()
        self.unavailable = set()
        self.snapshot = None

    def validate_version(self):
        w = self.w
        if w.config['game']['channel'] != self.data['channel']:
            raise RuntimeError('素材目录仅适配 ONEstore 渠道。')
        text = w.connection.shell(['dumpsys','package',w.connection.package])
        version = re.search(r'\bversionName=([^\s]+)',text)
        if not version or version[1] != self.data['game_version']:
            raise RuntimeError('游戏版本与素材目录不一致，请更新适配数据后再使用素材目标。')

    def select(self, stage_id):
        w = self.w
        option = self.options[stage_id]
        if option['zone'] in self.blocked_zones: return False
        w.sweep_page = 'normal_stage'
        sweep.enter(w,w.sweep_page)
        if not navigate(w,option,check_locked=True):
            self.blocked_zones.add(option['zone'])
            return False
        return sweep.select_stage(w,'mad.normal_sweep',stage_id)

    def stock_on_stage(self, refs):
        w = self.w
        values = {ref:None for ref in refs}
        w.click(1167,354,wait_over=True,rate=2)
        w.update_screenshot_array()
        details = w.scan((680,90,1195,690))
        if not any('详细信息' in r['text'] for r in details):
            raise RuntimeError('素材奖励详情未打开，停止读取。')
        try:
            monster = [r['point'][1] for r in details if '怪物' in r['text']]
            if len(monster)!=1: return values
            base = cv2.resize(w.latest_img_array,(1280,720))
            cells = []
            for cy in (224,316,408):
                if cy >= monster[0]-35: continue
                for cx in (729,821,913,1005,1097):
                    deviation = cv2.cvtColor(base[cy-33:cy+33,cx-33:cx+33],cv2.COLOR_BGR2GRAY).std()
                    if 12<=deviation<=20: return values
                    if deviation>20: cells.append((cx,cy))
            for cx,cy in cells:
                w.click(cx,cy,wait_over=True,rate=2)
                w.update_screenshot_array()
                lines = [r['text'] for r in w.scan((cx-384,cy-84,cx-18,cy+76))]
                for ref in refs:
                    value = exact_inventory(lines,self.data['items'][ref]['name'])
                    if value is not None: values[ref] = value
                w.click(300,600,wait_over=True)
                if all(v is not None for v in values.values()): break
        finally:
            # Neutral area closes an item tooltip first, then X closes details.
            w.click(300,600,wait_over=True)
            w.click(1178,97,wait_over=True)
            w.update_screenshot_array()
        return values

    def collect(self, snapshot):
        self.snapshot = snapshot
        if snapshot.get('allocation_version')==2: return self.collect_priority(snapshot)
        return self.collect_inventory(snapshot)

    def collect_inventory(self, snapshot):
        self.validate_version()
        w = self.w
        targets = {t['ref']:t for t in snapshot['targets'] if t['enabled']}
        observation = {'inventory':{r:None for r in targets},'stages':{},'balance':None,
                       'at':time.time(),'source':'game','game_version':self.data['game_version']}
        sources = sorted({s for r in targets for s in self.data['items'][r]['sources']},
                         key=lambda s:tuple(map(int,s.split(':')[1].split('-'))))
        for stage_id in sources:
            w.guard.check()
            related = [r for r,t in targets.items() if stage_id in self.data['items'][r]['sources']
                       and (observation['inventory'][r] is None or observation['inventory'][r]<t['amount'])]
            if not related: continue
            available = self.select(stage_id)
            observation['stages'][stage_id] = {'status':'sweepable' if available else 'unavailable',
                                               'reason':'' if available else '区域锁定、未三星或扫荡按钮不可用'}
            if not available: continue
            missing = [r for r in related if observation['inventory'][r] is None]
            if missing: observation['inventory'].update(self.stock_on_stage(missing))
            observation['balance'] = sweep.list_balance(w)
        return observation

    def reject_stage(self, stage_id):
        self.unavailable.add(stage_id)

    def read_stock(self, refs, observation):
        if not refs: return
        try: values = self.stock_on_stage(refs)
        except RuntimeError as error:
            values = dict.fromkeys(refs)
            observation.setdefault('inventory_errors',{}).update({r:str(error) for r in refs})
        observation['inventory'].update(values)
        observation.setdefault('inventory_at',{}).update({r:time.time() for r,v in values.items() if v is not None})

    def collect_priority(self, snapshot):
        self.validate_version()
        enabled = [t for t in snapshot['targets'] if t['enabled']]
        targets = {t['ref']:dict(t,weight=len(enabled)-i) for i,t in enumerate(enabled)
                   if not snapshot.get('inventory_only') or stock_limited(t)}
        rules = snapshot.get('rules',{}).get(getattr(self.w,'current_instance_id',None),{})
        observation = {'inventory':{},'inventory_at':{},'stages':{},'balance':None,
                       'at':time.time(),'source':'game','game_version':self.data['game_version']}
        for stage in self.unavailable: observation['stages'][stage] = {'status':'unavailable','reason':'本次已确认不可扫'}
        uncovered = set(targets)
        candidates = {s:source_refs(s,targets,rules,self.data) for s in self.data['stages'] if s not in self.unavailable}
        for ref in targets:
            while ref in uncovered:
                options = [s for s,refs in candidates.items() if ref in refs]
                if not options: break
                stage = min(options,key=lambda s:(-sum(targets[r]['weight'] for r in candidates[s] if r in uncovered),
                    self.data['stages'][s]['cost'],stage_order(s)))
                related = candidates.pop(stage)
                self.w.guard.check()
                available = self.select(stage)
                observation['stages'][stage] = {'status':'sweepable' if available else 'unavailable',
                    'reason':'' if available else '区域锁定、未三星或扫荡按钮不可用'}
                if not available: continue
                self.read_stock([r for r in related if stock_limited(targets[r]) and r not in observation['inventory']],observation)
                observation['balance'] = sweep.list_balance(self.w)
                uncovered.difference_update(related)
        return observation

    def after_batch(self, observation, stage_id, batch):
        refs = [r for r in observation['inventory'] if r in self.data['stages'][stage_id]['drops']]
        updated = deepcopy(observation)
        if self.snapshot and self.snapshot.get('allocation_version')==2:
            refs = [t['ref'] for t in self.snapshot['targets'] if t['enabled'] and stock_limited(t)
                    and t['ref'] in self.data['stages'][stage_id]['drops']]
            self.read_stock(refs,updated)
        else: updated['inventory'].update(self.stock_on_stage(refs))
        updated['balance'] = sweep.list_balance(self.w)
        if updated['balance'] is None: updated['balance'] = batch.balance_after
        updated['at'] = time.time()
        return updated


def sync(worker):
    store = MaterialStore(worker.material_repository)
    snapshot = {'targets':store.definitions()['targets'],'catalog_version':catalog()['version'],'rules':{},'allocation_version':2}
    if store.state()['pending'] and store.state()['pending']['phase']=='confirming':
        raise RuntimeError('上批素材消费结果待核对，请先在素材目标窗口处理。')
    obs = Observer(worker).collect(snapshot)
    store.observe(obs,snapshot)
    worker.note('可扫关卡与体力已刷新；已开启的库存条件同步读取，未执行扫荡。',status='SUCCESS')
    return True


def execute(worker, store, context, observer):
    if store.state()['rounds'][context]['snapshot'].get('allocation_version')==2:
        return execute_priority(worker,store,context,observer)
    return execute_inventory(worker,store,context,observer)


def execute_inventory(worker, store, context, observer):
    state = store.state()
    snapshot = state['rounds'][context]['snapshot']
    pending = state['pending']
    if pending:
        if pending['phase']=='confirming': raise RuntimeError('上批素材消费结果待核对，已阻止重复确认。')
        previous = state['rounds'][pending['context']]['snapshot']
        observed = observer.collect(previous)
        store.settle(pending['id'],observed)
    if not store.remaining(snapshot):
        worker.note('素材目标已达成或已暂停，本次跳过。',status='SKIPPED',completed=0)
        return True
    instance = worker.current_instance_id
    reserve = worker.task_params['material_sweep'].get('reserve',0)
    observation = observer.collect(snapshot)
    store.observe(observation,snapshot)
    if not store.remaining(snapshot):
        worker.note('当前库存已满足素材目标，本次跳过，未执行扫荡。',status='SKIPPED',completed=0)
        return True
    completed = 0
    while store.remaining(snapshot):
        worker.guard.check()
        state = store.state()
        round_ = state['rounds'][context]
        if instance in round_['blocked']:
            worker.note('上批次数由玩家标记为未知，本轮不再执行此素材指令。',status='PARTIAL',completed=completed)
            return True
        table = plan(snapshot,observation,state['completed'],snapshot['rules'].get(instance,{}),
                     round_['used'].get(instance,{}),reserve)
        if not table['rows']:
            reasons = '；'.join(dict.fromkeys(table['waiting'].values())) or '没有可执行来源'
            worker.note('素材目标有余项：'+reasons+'。继续后续任务。',status='PARTIAL',completed=completed)
            return True
        row = table['rows'][0]
        stage_id = row['stage_id']
        if not observer.select(stage_id):
            observation['stages'][stage_id] = {'status':'unavailable','reason':'执行前复核不可扫'}
            store.observe(observation,snapshot)
            continue
        batch_id = None
        def before_confirm(actual, after):
            nonlocal batch_id
            if after is None or after < reserve:
                worker.click(*sweep.SWEEP_POINTS['cancel'])
                raise RuntimeError('无法确认保留体力，已取消本批素材扫荡。')
            if getattr(worker,'plan_pass',None): worker.plan_pass.check_day()
            worker.guard.check()
            batch_id = store.prepare_batch(context,instance,stage_id,actual,row['refs'])
        batch = sweep.start_sweep(worker,row['batch_count'],catalog()['stages'][stage_id]['cost'],
                                  before_confirm=before_confirm)
        if batch.count == 0:
            if batch_id: raise RuntimeError('已发送素材消费操作但未取得结果，请核对后继续。')
            if batch.stage_limited:
                observation['stages'][stage_id] = {'status':'unavailable','reason':'本关次数用尽'}
                worker.to_main_page()
                continue
            worker.note('当前资源或可扫次数不足，素材目标保留，继续后续任务。',status='PARTIAL',completed=completed)
            return True
        store.result_seen(batch_id,batch.count)
        sweep.return_to_list(worker)
        observation = observer.after_batch(observation,stage_id,batch)
        store.settle(batch_id,observation)
        completed += batch.count
    worker.note('素材目标已达成。',status='SUCCESS',completed=completed)
    return True


def execute_priority(worker, store, context, observer):
    state = store.state(); pending = state['pending']
    if pending:
        if pending['phase']=='confirming': raise RuntimeError('上批素材消费结果待核对，已阻止重复确认。')
        # The confirmed count is durable even when inventory/OCR is unavailable.
        store.settle(pending['id'],{})
    snapshot = deepcopy(state['rounds'][context]['snapshot'])
    instance = worker.current_instance_id
    key = getattr(worker,'material_allocation_id',instance)
    inventory_only = getattr(worker,'material_inventory_only',False)
    snapshot['inventory_only'] = inventory_only
    reserve = worker.task_params['material_sweep'].get('reserve',0)
    rules = snapshot['rules'].get(instance,{})
    data = catalog()

    def report(reason=''):
        allocation = store.allocation(context,key) or {'rows':[],'completed':0}
        left = [{'stage_id':r['stage_id'],'count':r['count']} for r in allocation['rows'] if r['count']>0]
        pending_stock = any(stock_limited(t) for t in store.remaining(snapshot))
        status = 'PARTIAL' if left or pending_stock or allocation.get('waiting_data') else 'SUCCESS' if allocation['completed'] else 'SKIPPED'
        message = reason or ('本次扫荡次数已完成，库存目标仍保留。' if pending_stock else
                            '本次素材扫荡安排已完成。' if allocation['completed'] else '本次没有可分配的素材扫荡次数。')
        if not reason and allocation.get('waiting'):
            message += ' '+'；'.join(data['items'].get(ref,{}).get('name','游戏数据')+'：'+why for ref,why in allocation['waiting'].items())+'。'
        fields = dict(status=status,completed=allocation['completed'],material_allocation=key)
        if left: fields['remaining'] = left
        worker.note(message,**fields)
        return True

    if instance in store.state()['rounds'][context]['blocked']:
        allocation = store.allocation(context,key)
        worker.note('上批次数不明，这条指令本轮额度已结束；后续不同指令可继续。',status='SKIPPED',
                    completed=allocation['completed'] if allocation else 0,material_allocation=key)
        return True
    if not store.remaining(snapshot):
        store.save_allocation(context,key,instance,{'rows':[],'waiting':{}},inventory_only)
        return report('未选择素材，或库存目标已达成／暂停，本次跳过。')
    allocation = store.allocation(context,key)
    if allocation and not allocation.get('waiting_data') and not any(r['count'] for r in allocation['rows']) and not any(stock_limited(t) for t in store.remaining(snapshot)):
        return report()
    try: observation = observer.collect(snapshot)
    except RuntimeError as error:
        store.save_allocation(context,key,instance,{'rows':[],'waiting':{'runtime':str(error)},'waiting_data':True},inventory_only)
        return report(str(error)+'；已保留安排，继续后续任务。')
    store.observe(observation,snapshot)
    allocation = store.allocation(context,key)
    if allocation is None or (not allocation['budget'] and not allocation['completed'] and allocation.get('waiting_data')):
        current = store.state()
        table = plan(snapshot,observation,current['completed'],rules,current['rounds'][context]['used'].get(instance,{}),reserve)
        allocation = store.save_allocation(context,key,instance,table,inventory_only)

    def replan():
        current = store.state(); saved = store.allocation(context,key)
        observed = deepcopy(observation)
        # Availability can change; a smaller live balance must not erase debt.
        observed['balance'] = max(0,saved['budget']-saved['spent'])+reserve
        used = current['rounds'][context]['used'].get(instance,{})
        table = plan(snapshot,observed,current['completed'],rules,used,reserve)
        active,_ = active_targets(snapshot,observed,current['completed'],rules,used)
        if not table['rows'] and active and any(r['count']>0 for r in saved['rows']): table['waiting_data'] = True
        store.save_allocation(context,key,instance,table,inventory_only)
        return bool(table['rows']) or not table.get('waiting_data')

    if allocation.get('waiting_data'):
        if not replan(): return report('当前来源或库存条件待确认，已保留未完成次数；继续后续任务。')
    while True:
        worker.guard.check()
        current = store.state(); allocation = store.allocation(context,key)
        used = current['rounds'][context]['used'].get(instance,{})
        active,_ = active_targets(snapshot,observation,current['completed'],rules,used)
        rows = [r for r in allocation['rows'] if r['count']>0]
        if not rows:
            waiting = '；'.join(dict.fromkeys(allocation.get('waiting',{}).values()))
            return report(waiting+'；继续后续任务。' if allocation.get('waiting_data') else '')
        if any(observation.get('stages',{}).get(r['stage_id'],{}).get('status')!='sweepable' or
               any(ref not in source_refs(r['stage_id'],active,rules,data) for ref in r['refs']) for r in rows):
            if not replan(): return report('当前来源或库存条件待确认，已保留未完成次数；继续后续任务。')
            continue
        row = rows[0]; stage = row['stage_id']; cost = data['stages'][stage]['cost']
        refs = source_refs(stage,active,rules,data)
        balance = observation.get('balance')
        if type(balance) is not int or balance-reserve < cost:
            return report('当前体力不足或已达到保留体力，未完成次数保留；继续后续任务。')
        limited = any(stock_limited(t) and t['ref'] in data['stages'][stage]['drops'] for t in store.remaining(snapshot))
        count = min(row['count'],1 if limited else 5,(balance-reserve)//cost)
        caps = [rules[r]['max_runs']-used.get(r,0) for r in refs if rules.get(r,{}).get('max_runs') is not None]
        if caps: count = min(count,min(caps))
        if not observer.select(stage):
            observer.reject_stage(stage)
            observation = observer.collect(snapshot); store.observe(observation,snapshot)
            if not replan(): return report('原关卡不可扫，未完成次数保留；继续后续任务。')
            continue
        batch_id = None
        def before_confirm(actual, after):
            nonlocal batch_id
            if after is None or after < reserve:
                worker.click(*sweep.SWEEP_POINTS['cancel'])
                raise RuntimeError('无法确认保留体力，已取消本批素材扫荡。')
            if getattr(worker,'plan_pass',None): worker.plan_pass.check_day()
            worker.guard.check()
            batch_id = store.prepare_batch(context,instance,stage,actual,refs,key)
        batch = sweep.start_sweep(worker,count,cost,before_confirm=before_confirm)
        if not batch.count:
            if batch_id: raise RuntimeError('已发送素材消费但未取得结果，请核对后继续。')
            if batch.stage_limited:
                observer.reject_stage(stage)
                worker.to_main_page()
                observation = observer.collect(snapshot); store.observe(observation,snapshot)
                if not replan(): return report('关卡次数已用尽，余项保留；继续后续任务。')
                continue
            return report('当前资源不足，未完成次数保留；继续后续任务。')
        store.result_seen(batch_id,batch.count)
        store.settle(batch_id,{})
        sweep.return_to_list(worker)
        observation = observer.after_batch(observation,stage,batch)
        store.observe(observation,snapshot)


def implement(worker):
    store = MaterialStore(worker.material_repository)
    return execute(worker,store,worker.material_context,Observer(worker))
