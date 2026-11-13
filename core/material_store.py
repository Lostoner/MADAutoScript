"""Per-profile material intent and atomic observation/batch receipts."""
from copy import deepcopy
import json
import time
from uuid import uuid4

from core.config.repository import lock, ConfigValidationError, RevisionConflictError
from core.runtime_state import atomic_json

TASK = 'mad.material_sweep'
MANUAL_PREVIEW_TTL = 30*60


class MaterialStore:
    def __init__(self, repository):
        self.repository = repository
        self.path = repository.profile_dir/'material-goals.json'
        self.state_path = repository.data_root/'state'/repository.profile_id/'material-state.json'

    def definitions(self):
        with lock:
            return json.loads(self.path.read_text('utf-8')) if self.path.exists() else {'revision':0,'targets':[]}

    def state(self):
        with lock:
            return json.loads(self.state_path.read_text('utf-8')) if self.state_path.exists() else {
                'observation':{}, 'completed':{}, 'rounds':{}, 'adjustments':{}, 'pending':None}

    @staticmethod
    def token(target):
        return target['ref']+'@'+target['version']

    def save_targets(self, targets, revision=None):
        from core.material_planner import catalog
        data = catalog()
        with lock:
            old = self.definitions()
            if revision is not None and old['revision'] != revision:
                raise RevisionConflictError('素材目标已更新，请重新打开后编辑。')
            previous = {t['ref']:t for t in old['targets']}
            result, seen = [], set()
            for draft in targets:
                ref, amount = draft['ref'], draft['amount']
                if ref not in data['items'] or ref in seen:
                    raise ConfigValidationError('请选择已适配素材，每种素材只设置一个目标。')
                if type(amount) is not int or not 1 <= amount <= 2147483647:
                    raise ConfigValidationError('目标库存须为正整数。')
                seen.add(ref)
                before = previous.get(ref,{})
                version = before.get('version')
                if not version or before['amount'] != amount or draft.get('reopen'):
                    version = uuid4().hex
                excluded = list(dict.fromkeys(draft.get('excluded',[])))
                if set(excluded)-set(data['items'][ref]['sources']):
                    raise ConfigValidationError('排除列表包含非来源关卡。')
                priority = draft.get('priority',1)
                if priority not in (1,2): raise ConfigValidationError('未知优先级。')
                result.append(dict(ref=ref, amount=amount, version=version, enabled=bool(draft.get('enabled',True)),
                                   priority=priority, excluded=excluded))
            value = {'revision':old['revision']+1,'targets':result}
            atomic_json(self.path,value)
            return deepcopy(value)

    def active_context(self, scope='routine'):
        if scope.startswith('plan:'):
            return scope if scope in self.state()['rounds'] else None
        folder = self.state_path.parent
        epoch = self.repository.load_config()['last_refresh_config_time']
        for name in ('routine','selected','continuous'):
            path = folder/(name+'-checkpoint.json')
            if path.exists():
                record = json.loads(path.read_text('utf-8'))
                if record.get('context',[None,None])[1] == epoch and record.get('material_context'):
                    return record['material_context']
        return None

    def adjustments(self, scope, instance):
        return deepcopy(self.state()['adjustments'].get(scope,{}).get(instance,{}))

    def set_adjustments(self, scope, instance, rules):
        from core.material_planner import catalog
        data = catalog()
        with lock:
            if self.active_context(scope): raise ConfigValidationError('本轮已冻结；下轮再修改临时安排。')
            clean = {}
            for ref, rule in rules.items():
                if ref not in data['items']: raise ConfigValidationError('未知素材。')
                stage, limit = rule.get('stage'), rule.get('max_runs')
                if stage and stage not in data['items'][ref]['sources']: raise ConfigValidationError('指定关卡不是素材来源。')
                if limit is not None and (type(limit) is not int or limit < 0): raise ConfigValidationError('次数上限须为非负整数。')
                if stage or limit is not None: clean[ref] = {'stage':stage,'max_runs':limit}
            state = self.state()
            state['adjustments'].setdefault(scope,{})[instance] = clean
            atomic_json(self.state_path,state)

    def freeze(self, context, scope='routine'):
        from core.material_planner import catalog
        with lock:
            state = self.state()
            if context not in state['rounds']:
                snapshot = {'targets':self.definitions()['targets'],'catalog_version':catalog()['version'],
                            'rules':deepcopy(state['adjustments'].get(scope,{}))}
                state['rounds'][context] = {'snapshot':snapshot,'used':{},'blocked':[], 'receipts':[]}
                if scope == 'routine': state['adjustments'].pop(scope,None)
                atomic_json(self.state_path,state)
            return deepcopy(state['rounds'][context]['snapshot'])

    def remaining(self, snapshot):
        state = self.state()
        return [t for t in snapshot['targets'] if t['enabled'] and self.token(t) not in state['completed']]

    def _observe(self, state, observation, snapshot):
        state['observation'] = deepcopy(observation)
        if observation.get('source') != 'game': return
        for target in snapshot['targets']:
            count = observation.get('inventory',{}).get(target['ref'])
            if target['enabled'] and type(count) is int and count >= target['amount']:
                state['completed'].setdefault(self.token(target),{'at':observation['at'],'quantity':count})

    def observe(self, observation, snapshot):
        with lock:
            state = self.state()
            self._observe(state,observation,snapshot)
            atomic_json(self.state_path,state)

    def correct_inventory(self, ref, amount):
        if type(amount) is not int or amount < 0: raise ConfigValidationError('库存须为非负整数。')
        with lock:
            state = self.state()
            obs = state['observation']
            obs.setdefault('inventory',{})[ref] = amount
            obs.setdefault('manual',{})[ref] = time.time()
            obs['source'] = 'manual'
            # Manual corrections inform previews, not permanent completion.
            atomic_json(self.state_path,state)

    def preview_observation(self, now=None):
        observation = self.state()['observation']
        now = time.time() if now is None else now
        for ref, at in observation.get('manual',{}).items():
            if now-at > MANUAL_PREVIEW_TTL:
                observation.get('inventory',{})[ref] = None
        return observation

    def prepare_batch(self, context, instance, stage, count, refs):
        with lock:
            state = self.state()
            if state['pending']: raise RuntimeError('上批素材扫荡待核对，不能再次确认消费。')
            pending = dict(id=uuid4().hex,context=context,instance=instance,stage=stage,count=count,
                           refs=refs,phase='confirming',at=time.time())
            state['pending'] = pending
            atomic_json(self.state_path,state)
            return pending['id']

    def result_seen(self, batch_id, count):
        with lock:
            state = self.state()
            pending = state['pending']
            if not pending or pending['id'] != batch_id: raise RuntimeError('素材批次身份不一致。')
            pending.update(phase='result_observed',count=count)
            atomic_json(self.state_path,state)

    def settle(self, batch_id, observation):
        with lock:
            state = self.state()
            pending = state['pending']
            if not pending or pending['id'] != batch_id:
                return False  # the same receipt is never applied twice
            if pending['phase'] != 'result_observed': raise RuntimeError('消费结果未知，不能按库存猜测次数。')
            round_ = state['rounds'][pending['context']]
            used = round_['used'].setdefault(pending['instance'],{})
            for ref in pending['refs']: used[ref] = used.get(ref,0)+pending['count']
            round_['receipts'].append(deepcopy(pending))
            self._observe(state,observation,round_['snapshot'])
            state['pending'] = None
            atomic_json(self.state_path,state)
            return True

    def resolve_pending(self, performed):
        """Explicit player disposition; unknown counts remain unknown in the receipt."""
        with lock:
            state = self.state()
            pending = state['pending']
            if not pending: return
            if pending['phase']=='result_observed':
                if not performed: raise ConfigValidationError('已看到扫荡结果，不能标记为未执行。')
                self.settle(pending['id'],{})
                return
            round_ = state['rounds'][pending['context']]
            if performed and pending['instance'] not in round_['blocked']:
                round_['blocked'].append(pending['instance'])
            round_['receipts'].append(dict(pending,phase='manual_unknown' if performed else 'manual_not_sent',
                                          count=None if performed else 0))
            state['pending'] = None
            state['observation'] = {}
            atomic_json(self.state_path,state)
