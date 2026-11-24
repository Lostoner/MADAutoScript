"""Material goals in instruction params; shared observations and atomic receipts."""
from copy import deepcopy
import json
import time
from uuid import NAMESPACE_URL, uuid4, uuid5

from core.config.repository import lock, ConfigValidationError, RevisionConflictError, instance_params
from core.runtime_state import atomic_json
from core.material_planner import stock_complete, stock_limited

TASK = 'mad.material_sweep'
MANUAL_PREVIEW_TTL = 30*60

def validate_targets(targets, *, saved=False):
    from core.material_planner import catalog
    if not isinstance(targets,list): raise ConfigValidationError('素材目标须为列表。')
    items, seen = catalog()['items'], set()
    for draft in targets:
        ref, amount = draft['ref'], draft.get('amount')
        limited = draft.get('stock_limit_enabled', amount is not None)
        if ref not in items or ref in seen:
            raise ConfigValidationError('请选择已适配素材，每种素材只设置一个目标。')
        if (limited or amount is not None) and (type(amount) is not int or not 1 <= amount <= 2147483647):
            raise ConfigValidationError('目标库存须为正整数。')
        if set(draft.get('excluded',[]))-set(items[ref]['sources']):
            raise ConfigValidationError('排除列表包含非来源关卡。')
        if saved and (not isinstance(draft.get('version'),str) or not draft['version']):
            raise ConfigValidationError('素材目标缺少版本，请在目标编辑器重新保存。')
        seen.add(ref)

def clean_targets(targets, previous):
    validate_targets(targets)
    previous = {t['ref']:t for t in previous}
    result = []
    for draft in targets:
        ref, amount = draft['ref'], draft.get('amount')
        before = previous.get(ref,{})
        same = before.get('version') and before.get('amount')==amount and not draft.get('reopen')
        target = dict(ref=ref, amount=amount, version=before['version'] if same else uuid4().hex,
                      enabled=bool(draft.get('enabled',True)),
                      stock_limit_enabled=bool(draft.get('stock_limit_enabled',amount is not None)),
                      excluded=list(dict.fromkeys(draft.get('excluded',[]))))
        if same and before.get('legacy_version'): target['legacy_version'] = before['legacy_version']
        result.append(target)
    return result

def copy_targets(targets):
    # Copy intent only, not the source instruction's sticky stock completion.
    return clean_targets(targets,[])

def material_params(events, params_by_id):
    return {e['instance_id']:params_by_id[e['instance_id']] for e in events if e['func_name']==TASK}


class MaterialStore:
    def __init__(self, repository):
        self.repository = repository
        self.path = repository.profile_dir/'material-goals.json'
        self.state_path = repository.data_root/'state'/repository.profile_id/'material-state.json'

    def _legacy_targets(self):
        if not self.path.exists(): return []
        value = json.loads(self.path.read_text('utf-8'))
        version = value.get('schema_version',1)
        if version not in (1,2): raise ConfigValidationError('素材配置版本较新，请使用对应新版程序。')
        targets = value['targets']
        if version==1:
            targets.sort(key=lambda t:-t.get('priority',1))
            for target in targets:
                target['stock_limit_enabled'] = True
                target.pop('priority',None)
        return targets

    def targets(self, instance, params, scope='routine'):
        if 'targets' in params: return deepcopy(params['targets'])  # [] is intentional
        # The old file becomes read-only. Give each inherited goal an independent
        # identity without rewriting historical completions or frozen snapshots.
        inherited = self._legacy_targets()
        for target in inherited:
            old = target['legacy_version'] = target['version']
            target['version'] = uuid5(NAMESPACE_URL,json.dumps(['mad-material',scope,instance,old])).hex
        return inherited

    def definitions(self, instance=TASK, *, params=None, scope='routine'):
        with lock:
            if params is None:
                config = self.repository.load_config()
                params = (config['routine']['material_sweep'] if instance==TASK
                          else config['instance_params'][instance])
            return {'targets':self.targets(instance,params,scope)}

    @staticmethod
    def for_step(snapshot, instance):
        if 'targets_by_id' not in snapshot: return snapshot  # old frozen round
        return {k:v for k,v in snapshot.items() if k!='targets_by_id'} | {
            'targets':snapshot['targets_by_id'].get(instance,[])}

    def copy_definition(self, spec, scope='routine'):
        """Copy a day/template, including the actual goals of a frozen source day."""
        result = deepcopy(spec)
        params = material_params(result['events'],result['params_by_id'])
        frozen = self.state()['rounds'].get(scope) if params and scope.startswith('plan:') else None
        for instance, config in params.items():
            targets = (self.for_step(frozen['snapshot'],instance)['targets'] if frozen
                       else self.targets(instance,config,scope))
            config['targets'] = copy_targets(targets)
        return result

    def state(self):
        with lock:
            return json.loads(self.state_path.read_text('utf-8')) if self.state_path.exists() else {
                'observation':{}, 'completed':{}, 'rounds':{}, 'adjustments':{}, 'pending':None}

    @staticmethod
    def token(target):
        return target['ref']+'@'+target['version']

    def save_targets(self, targets, *, instance=TASK, expected=None):
        """Save one existing daily instruction, leaving other drafts and progress alone."""
        with lock:
            event = next((e for e in self.repository.load_events() if e['instance_id']==instance),None)
            if not event or event['func_name']!=TASK: raise ConfigValidationError('素材指令已移除，请重新打开。')
            old = self.definitions(instance)['targets']
            if expected is not None and old != expected:
                raise RevisionConflictError('素材目标已更新，请重新打开后编辑。')
            result = clean_targets(targets,old)
            config = self.repository.load_config()
            if instance_params(config,event).get('targets')!=result:
                change = {'targets':result}
                self.repository.patch_config({'routine':{'material_sweep':change}} if instance==TASK
                                             else {'instance_params':{instance:change}})
            return {'targets':result}

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

    def freeze(self, context, scope='routine', *, params_by_id=None):
        from core.material_planner import catalog
        with lock:
            state = self.state()
            if context not in state['rounds']:
                if params_by_id is None:
                    config = self.repository.load_config()
                    params_by_id = {e['instance_id']:instance_params(config,e) for e in self.repository.load_events()
                                    if e['func_name']==TASK}
                snapshot = {'targets_by_id':{key:self.targets(key,p,scope) for key,p in params_by_id.items()},
                            'catalog_version':catalog()['version'],'allocation_version':2,
                            'rules':deepcopy(state['adjustments'].get(scope,{}))}
                state['rounds'][context] = {'snapshot':snapshot,'used':{},'blocked':[], 'receipts':[]}
                if scope == 'routine': state['adjustments'].pop(scope,None)
                atomic_json(self.state_path,state)
            return deepcopy(state['rounds'][context]['snapshot'])

    def remaining(self, snapshot):
        state = self.state()
        return [t for t in snapshot['targets'] if t['enabled'] and
                (not snapshot.get('inventory_only') or stock_limited(t)) and
                (not stock_limited(t) or not stock_complete(t,state['completed']))]

    def needs_work(self, context, allocation_id=None, instance=None):
        """Finite step debt and optional stock goals, never an endless checkbox."""
        state = self.state(); round_ = state['rounds'].get(context)
        if not round_: return False
        snapshot = round_['snapshot']
        if snapshot.get('allocation_version') != 2: return bool(self.remaining(self.for_step(snapshot,instance)))
        if state['pending'] and state['pending']['phase']=='confirming': return True
        allocations = round_.get('allocations',{})
        if allocation_id in allocations: instance = allocations[allocation_id]['instance']
        if instance in round_['blocked'] and (allocation_id in allocations or 'targets_by_id' in snapshot): return False
        records = ([allocations[allocation_id]] if allocation_id in allocations else
                   [] if allocation_id else [a for a in allocations.values() if instance is None or a['instance']==instance])
        records = [a for a in records if a['instance'] not in round_['blocked']]
        if any(a.get('waiting_data') or any(r['count']>0 for r in a['rows']) for a in records): return True
        if instance is None and 'targets_by_id' in snapshot:
            return any(stock_limited(t) for key in snapshot['targets_by_id'] if key not in round_['blocked']
                       for t in self.remaining(self.for_step(snapshot,key)))
        return any(stock_limited(t) for t in self.remaining(self.for_step(snapshot,instance)))

    def allocation(self, context, key):
        return deepcopy(self.state()['rounds'][context].get('allocations',{}).get(key))

    def save_allocation(self, context, key, instance, table, inventory_only=False):
        with lock:
            state = self.state(); round_ = state['rounds'][context]
            records = round_.setdefault('allocations',{})
            record = records.get(key)
            if record is None:
                record = records[key] = dict(instance=instance,completed=0,spent=0,by_stage={},
                    budget=sum(r['cost'] for r in table['rows']),inventory_only=inventory_only)
            elif not record['budget'] and not record['completed']:
                record['budget'] = sum(r['cost'] for r in table['rows'])
            # Failed re-observation must not erase an existing finite quota.
            if table['rows'] or not table.get('waiting_data') or not record.get('rows'):
                record['rows'] = deepcopy(table['rows'])
                record['planned'] = record['completed']+sum(r['count'] for r in record['rows'])
            record.update(waiting=deepcopy(table['waiting']),waiting_data=table.get('waiting_data',False))
            atomic_json(self.state_path,state)
            return deepcopy(record)

    def _observe(self, state, observation, snapshot):
        state['observation'] = deepcopy(observation)
        if observation.get('source') != 'game': return
        for target in snapshot['targets']:
            count = observation.get('inventory',{}).get(target['ref'])
            if target['enabled'] and stock_limited(target) and type(count) is int and count >= target['amount']:
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

    def prepare_batch(self, context, instance, stage, count, refs, allocation_id=None):
        with lock:
            state = self.state()
            if state['pending']: raise RuntimeError('上批素材扫荡待核对，不能再次确认消费。')
            pending = dict(id=uuid4().hex,context=context,instance=instance,stage=stage,count=count,
                           refs=refs,phase='confirming',at=time.time())
            if allocation_id is not None:
                allocation = state['rounds'][context]['allocations'][allocation_id]
                row = next((r for r in allocation['rows'] if r['stage_id']==stage),None)
                if count<=0 or not row or count>row['count']: raise RuntimeError('素材消费超出已保存次数安排。')
                pending['allocation_id'] = allocation_id
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
            if pending.get('allocation_id'):
                allocation = round_['allocations'][pending['allocation_id']]
                row = next(r for r in allocation['rows'] if r['stage_id']==pending['stage'])
                if not 0 < pending['count'] <= row['count']: raise RuntimeError('实际次数超出素材配额，需核对。')
                cost = row['cost']//row['count']
                row['count'] -= pending['count']; row['cost'] -= pending['count']*cost
                allocation['completed'] += pending['count']; allocation['spent'] += pending['count']*cost
                allocation['by_stage'][pending['stage']] = allocation['by_stage'].get(pending['stage'],0)+pending['count']
            used = round_['used'].setdefault(pending['instance'],{})
            for ref in pending['refs']: used[ref] = used.get(ref,0)+pending['count']
            round_['receipts'].append(deepcopy(pending))
            self._observe(state,observation,self.for_step(round_['snapshot'],pending['instance']))
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
