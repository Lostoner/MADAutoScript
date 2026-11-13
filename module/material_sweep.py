"""Observe NORMAL rewards, plan small batches, and settle against exact stock."""
from copy import deepcopy
import re
import time
import cv2

from core.game_catalog import stage_options
from core.material_store import MaterialStore, TASK
from core.material_planner import catalog, plan
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

    def after_batch(self, observation, stage_id, batch):
        refs = [r for r in observation['inventory'] if r in self.data['stages'][stage_id]['drops']]
        updated = deepcopy(observation)
        updated['inventory'].update(self.stock_on_stage(refs))
        updated['balance'] = sweep.list_balance(self.w)
        if updated['balance'] is None: updated['balance'] = batch.balance_after
        updated['at'] = time.time()
        return updated


def sync(worker):
    store = MaterialStore(worker.material_repository)
    snapshot = {'targets':store.definitions()['targets'],'catalog_version':catalog()['version'],'rules':{}}
    if store.state()['pending'] and store.state()['pending']['phase']=='confirming':
        raise RuntimeError('上批素材消费结果待核对，请先在素材目标窗口处理。')
    obs = Observer(worker).collect(snapshot)
    store.observe(obs,snapshot)
    worker.note('素材库存与候选关卡已同步；未执行扫荡。',status='SUCCESS')
    return True


def execute(worker, store, context, observer):
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


def implement(worker):
    store = MaterialStore(worker.material_repository)
    return execute(worker,store,worker.material_context,Observer(worker))
