"""BAAS profile config/event storage and one-time MAD schema migration.

JSON writes are atomic; execution policy belongs to Scheduler and tasks.
"""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import json
import threading
import time
from zoneinfo import ZoneInfo
from core.paths import DEFAULT_PROFILE_DIR, REPO_ROOT
from core.runtime_state import atomic_json
from core.tasks import TASKS, SWEEP_TASKS
from core.game_catalog import SHOP_ITEMS
from .default_config import SCHEMA_VERSION, default_config, default_events, default_app_settings

lock=threading.RLock()
class ConfigError(ValueError): pass
class ConfigValidationError(ConfigError): pass
class UnsupportedSchemaVersion(ConfigError): pass
class RevisionConflictError(ConfigError): pass
class ConfigBusyError(ConfigError): pass

def _read(path,default):
    return json.loads(path.read_text('utf-8-sig')) if path.exists() else deepcopy(default)

def _merge(base,changes):
    result=deepcopy(base)
    for key,value in changes.items():
        result[key]=_merge(result[key],value) if isinstance(value,dict) and isinstance(result.get(key),dict) else deepcopy(value)
    return result

def instance_params(config,event):
    """Original rows keep their public routine keys; copies own their parameters."""
    task=event['func_name']
    key=event.get('instance_id',task)
    return (config['routine'].get(task[4:],{}) if key==task
            else config['instance_params'][key])

def _remaining_plans(plans,old_plans,left_plans):
    old={p['stage_id']:p['count'] for p in old_plans}
    left={p['stage_id']:p['count'] for p in left_plans}
    updated=[]
    for plan in plans:
        key,count=plan['stage_id'],plan['count']
        if key not in old: remaining=count
        elif count==old[key]=='max': remaining='max' if key in left else 0
        elif type(count) is int and type(old[key]) is int:
            remaining=max(0,count-max(0,old[key]-left.get(key,0)))
        else: remaining=count
        if remaining: updated.append({'stage_id':key,'count':remaining})
    return updated

def _remaining(new_routine,old_routine=None,unfinished=None):
    result=deepcopy(unfinished or {})
    for task in SWEEP_TASKS:
        name=task[4:]
        plans=new_routine[name]['plans']
        if old_routine is not None and old_routine.get(name,{}).get('plans')==plans: continue
        result[task]=_remaining_plans(plans,(old_routine or {}).get(name,{}).get('plans',[]),result.get(task,[]))
    return result

def _validate(config):
    if not config['display_name'].strip(): raise ConfigValidationError('显示名不能为空')
    ZoneInfo(config['scheduling']['timezone'])
    reset=config['scheduling']['reset']
    ZoneInfo(reset['server_timezone'])
    if reset.get('reset_at'):
        parts=[int(x) for x in reset['reset_at'].split(':')]
        if len(parts) not in (2,3) or not 0<=parts[0]<24 or not all(0<=x<60 for x in parts[1:]):
            raise ConfigValidationError('日切时间应为 HH:MM 或 HH:MM:SS')
    elif reset['enabled']: raise ConfigValidationError('启用日切时请填写服务器重置时间')
    for task in TASKS:
        _validate_params(task,config['routine'].get(task[4:],{}))

def _validate_params(task,params):
    if task=='mad.material_sweep' and (type(params.get('reserve')) is not int or params['reserve']<0):
        raise ConfigValidationError('保留体力须为非负整数')
    if task in SWEEP_TASKS:
        seen=set()
        for plan in params['plans']:
            if plan['stage_id'] in seen: raise ConfigValidationError('同一关卡只能配置一次')
            seen.add(plan['stage_id'])
            if plan['count']!='max' and (type(plan['count']) is not int or plan['count']<1):
                raise ConfigValidationError('次数必须是正整数或 max')
    if task=='mad.claim_all' and params['modules'].get('activity'):
        raise ConfigValidationError('活动领取等待用户的单独规则')
    if task!='mad.gold_shop': return
    seen=set()
    for item in params['items']:
        if item['item_id'] not in SHOP_ITEMS or item['item_id'] in seen:
            raise ConfigValidationError('请选择普通商店中的商品，每种商品只配置一次')
        seen.add(item['item_id'])
        if item['count']!='max' and (type(item['count']) is not int or item['count']<1):
            raise ConfigValidationError('购买数量必须是正整数或 max')

class ProfileRepository:
    def __init__(self,profile_dir=None):
        self.profile_dir=Path(profile_dir or DEFAULT_PROFILE_DIR).resolve()
        self.data_root=self.profile_dir.parent.parent
        self.profile_id=self.profile_dir.name
        self.config_path=self.profile_dir/'config.json'
        self.event_path=self.profile_dir/'event.json'
        self.pending_path=self.profile_dir/'.routine-commit.json'

    def _finish_commit(self,pair):
        atomic_json(self.config_path,pair['config'])
        atomic_json(self.event_path,pair['events'])
        self.pending_path.unlink()

    def _commit_pair(self,config,events):
        # A crash between the two atomic replacements is replayed before any read.
        self._validate_events(events)
        pair={'config':config,'events':events}
        atomic_json(self.pending_path,pair)
        self._finish_commit(pair)

    def _ensure(self):
        if self.pending_path.exists():
            self._finish_commit(_read(self.pending_path,None))
        defaults=default_config(self.profile_id)
        raw=_read(self.config_path,defaults)
        version=raw.get('schema_version',0)
        if version>SCHEMA_VERSION: raise UnsupportedSchemaVersion(f'未知配置版本 {version}')
        if version<4:
            original=deepcopy(raw)
            backup=self.profile_dir/'backups'/('schema'+str(version)+'-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
            backup.mkdir(parents=True,exist_ok=False)
            atomic_json(backup/'config.json',raw)
            if self.event_path.exists(): (backup/'event.json').write_bytes(self.event_path.read_bytes())
            progress_path=self.data_root/'state'/self.profile_id/'routine-progress.json'
            progress=_read(progress_path,{})
            if progress_path.exists(): (backup/'routine-progress.json').write_bytes(progress_path.read_bytes())
            routine=raw.setdefault('routine',{})
            queue=routine.pop('queue',None)
            events=default_events()
            prior=_read(self.event_path,[])
            prior=prior if isinstance(prior,list) else prior.get('events',[])
            prior_by_id={e.get('func_name',e.get('task_id')):e for e in prior}
            if queue:
                order={x['task_id']:i for i,x in enumerate(queue)}
                flags={x['task_id']:x['enabled'] for x in queue}
                for event in events:
                    key=event['func_name']
                    event.update(priority=order.get(key,len(order)+event['priority']),enabled=flags.get(key,event['enabled']))
            for event in events:
                prev=prior_by_id.get(event['func_name'],{})
                for key in ('interval','pre_task','post_task','disabled_time_range','daily_reset','next_tick'):
                    if key in prev: event[key]=deepcopy(prev[key])
            for name in ('free_seeds','mail_before','rewards_after'): routine.pop(name,None)
            for task in SWEEP_TASKS:
                name=task[4:]
                item=routine.setdefault(name,deepcopy(defaults['routine'][name]))
                if 'plans' not in item:
                    stage=('normal:'+str(item.get('stage','9-10')) if task=='mad.normal_sweep' else 'procurement:'+item.get('category','数据窃取')+':'+str(item.get('stage',4)))
                    item['plans']=[{'stage_id':stage,'count':item.get('count',1)}]
                for key in ('budget','reserve','enabled','stage','category','count'): item.pop(key,None)
            shop=routine.setdefault('gold_shop',{})
            for key in ('budget','reserve','enabled'): shop.pop(key,None)
            shop.setdefault('items',[{'item_id':'c_battle_log','count':1}])
            routine.setdefault('dating',{}).pop('enabled',None)
            raw=_merge(defaults,raw)
            for key in ('timeout_seconds','max_actions'): raw['runtime'].pop(key,None)
            for key in ('retry_limit','retry_backoff_seconds','poll_seconds'): raw['scheduling'].pop(key,None)
            pending={}
            for task in SWEEP_TASKS:
                pending[task]=[]
                for plan in raw['routine'][task[4:]]['plans']:
                    done=progress.get('plans',{}).get(task,{}).get(plan['stage_id'],{})
                    count=plan['count']
                    left=('max' if not done.get('max_complete') else 0) if count=='max' else max(0,count-done.get('count',0))
                    if left: pending[task].append({'stage_id':plan['stage_id'],'count':left})
            raw['unfinished_tasks']=pending
            raw['last_refresh_config_time']=datetime.fromisoformat(progress['started_at']).timestamp() if progress.get('started_at') else time.time()
            raw['schema_version']=4
            raw['revision']=original.get('revision',0)+1
            _validate(raw)
            self._write_events(events)
            atomic_json(self.config_path,raw)
            atomic_json(backup/'migration.json',{'from':version,'to':4,'unfinished':pending})
        if not self.config_path.exists():
            raw['unfinished_tasks']=_remaining(raw['routine'])
            raw['last_refresh_config_time']=time.time()
            atomic_json(self.config_path,raw)
        if not self.event_path.exists(): self._write_events(default_events())
        # Older MAD profiles left the unverified reset time empty. Fill that
        # placeholder only; explicit clocks/switches and current progress stay.
        if raw.get('schema_version',0)<5:
            reset=raw.get('scheduling',{}).get('reset',{})
            if not reset.get('reset_at') and not reset.get('enabled'):
                raw.setdefault('scheduling',{})['reset']=deepcopy(defaults['scheduling']['reset'])
        if raw.get('schema_version',0)<6:
            if version in (4,5):
                # An older launcher rejects schema 6; keep both original files
                # together so rolling the application back has a matching profile.
                backup=self.profile_dir/'backups'/('schema'+str(version)+'-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
                backup.mkdir(parents=True,exist_ok=False)
                for path in (self.config_path,self.event_path):
                    (backup/path.name).write_bytes(path.read_bytes())
            events=_read(self.event_path,default_events())
            for event in events: event.setdefault('instance_id',event['func_name'])
            raw.setdefault('instance_params',{})
            raw['schema_version']=6
            raw['revision']=raw.get('revision',0)+1
            self._commit_pair(raw,events)
        return _merge(defaults,raw)

    def load_config(self):
        with lock: return deepcopy(self._ensure())

    def load_events(self):
        with lock:
            self._ensure()
            return _read(self.event_path,default_events())

    def patch_config(self,changes):
        with lock:
            current=self._ensure()
            result=_merge(current,changes)
            if 'routine' in changes: result['unfinished_tasks']=_remaining(result['routine'],current['routine'],current['unfinished_tasks'])
            result['revision']=current.get('revision',0)+1
            _validate(result)
            atomic_json(self.config_path,result)
            return deepcopy(result)

    def save_config(self,snapshot,base=None):
        changes={k:v for k,v in snapshot.items() if k not in ('revision','schema_version','unfinished_tasks','last_refresh_config_time') and (base is None or v!=base.get(k))}
        return self.patch_config(changes)

    def set_unfinished(self,task,plans):
        with lock:
            config=self._ensure()
            config['unfinished_tasks'][task]=deepcopy(plans)
            atomic_json(self.config_path,config)

    def complete_sweep(self,task,stage_id,count,finish_max=False):
        with lock:
            config=self._ensure()
            remaining=[]
            for plan in config['unfinished_tasks'].get(task,[]):
                if plan['stage_id']!=stage_id: remaining.append(plan); continue
                if plan['count']=='max':
                    if not finish_max: remaining.append(plan)
                elif plan['count']>count: remaining.append({**plan,'count':plan['count']-count})
            config['unfinished_tasks'][task]=remaining
            atomic_json(self.config_path,config)

    def reset_progress(self,when=None,*,reset_schedule=False):
        with lock:
            config=self._ensure()
            events=self.load_events()
            config['unfinished_tasks']={e['instance_id']:deepcopy(instance_params(config,e)['plans'])
                                        for e in events if e['func_name'] in SWEEP_TASKS}
            config['last_refresh_config_time']=time.time() if when is None else when
            if reset_schedule:
                for event in events:
                    event['next_tick']=min(event['next_tick'],int(config['last_refresh_config_time']))
                self._commit_pair(config,events)
            else: atomic_json(self.config_path,config)
            return config

    @staticmethod
    def _validate_events(events):
        seen=set()
        for event in events:
            key=event['func_name']
            instance=event.setdefault('instance_id',key)
            if not isinstance(instance,str) or not instance.strip() or instance in seen:
                raise ConfigValidationError('指令编号为空或重复：'+str(instance))
            if instance in TASKS and instance!=key: raise ConfigValidationError('原始指令编号已保留：'+instance)
            seen.add(instance)
            if key not in TASKS: continue
            if event['enabled'] and not TASKS[key].supported: raise ConfigValidationError(TASKS[key].resource)
            for field in ('priority','interval','next_tick'):
                if not isinstance(event[field],(int,float)) or event[field]<0: raise ConfigValidationError(field+' 必须非负')
            ranges=[]
            for start,end in event['disabled_time_range']:
                ranges.extend([[start,[23,59,59]],[[0,0,0],end]] if start>end else [[start,end]])
            event['disabled_time_range']=ranges
        by_id={e['instance_id']:e for e in events}
        for event in events:
            parent=event.get('follow_after')
            if not parent: continue
            if (event['instance_id']==event['func_name'] or parent not in by_id or
                    parent==event['instance_id'] or by_id[parent].get('follow_after')):
                raise ConfigValidationError('后置指令须为副本，且跟随现存的独立指令')

    def _write_events(self,events):
        self._validate_events(events)
        atomic_json(self.event_path,events)

    def save_events(self,events,fields=None):
        with lock:
            self._ensure()
            current=_read(self.event_path,[])
            mapping={e.get('instance_id',e['func_name']):e for e in current}
            for incoming in events:
                key=incoming.get('instance_id') or incoming['func_name']
                if key not in mapping:
                    if key!=incoming.get('func_name'):
                        raise ConfigValidationError('指令已移除；新增指令须同时保存参数')
                    current.append(deepcopy(incoming)); mapping[key]=current[-1]
                else:
                    if incoming.get('func_name',mapping[key]['func_name'])!=mapping[key]['func_name']:
                        raise ConfigValidationError('不可改变已有指令的类型')
                    mapping[key].update({k:deepcopy(v) for k,v in incoming.items() if k not in ('func_name','instance_id') and
                        ((fields is None and k!='next_tick') or (fields is not None and k in fields))})
            self._write_events(current)
            return deepcopy(current)

    def save_routine_instances(self,events,params_by_id):
        """Commit the ordered editor draft without overwriting live clock/progress."""
        with lock:
            config=self._ensure()
            previous={e['instance_id']:e for e in self.load_events()}
            templates={e['func_name']:e for e in default_events()}
            ordered=[]
            for priority,draft in enumerate(events):
                task=draft['func_name']
                key=draft.get('instance_id',task)
                old=previous.get(key)
                if task not in templates or (old and old['func_name']!=task):
                    raise ConfigValidationError('未知指令类型或类型已改变：'+task)
                event=deepcopy(old or templates[task])
                if old is None:
                    for field in ('interval','daily_reset','disabled_time_range'):
                        if field in draft: event[field]=deepcopy(draft[field])
                for field in ('event_name','enabled','follow_after'):
                    if field in draft: event[field]=draft[field]
                event.update(instance_id=key,priority=priority)
                if not event['event_name'].strip(): raise ConfigValidationError('指令名不能为空')
                ordered.append(event)
                params=deepcopy(params_by_id[key])
                _validate_params(task,params)
                old_params=instance_params(config,event) if old else {}
                if task in SWEEP_TASKS and (old is None or old_params.get('plans')!=params['plans']):
                    config['unfinished_tasks'][key]=_remaining_plans(params['plans'],old_params.get('plans',[]),
                                                                    config['unfinished_tasks'].get(key,[]))
                if key!=task: config['instance_params'][key]=params
                elif task[4:] in config['routine']: config['routine'][task[4:]]=params
            removed=set(previous)-{e['instance_id'] for e in ordered}
            for key in removed:
                if key in TASKS: raise ConfigValidationError('原始指令可停用但不可移除')
                config['instance_params'].pop(key,None)
                config['unfinished_tasks'].pop(key,None)
            if any(removed.intersection(e.get('pre_task',[])+e.get('post_task',[])) for e in ordered):
                raise ConfigValidationError('请先解除前后置引用，再移除指令')
            config['revision']+=1
            _validate(config)
            self._commit_pair(config,ordered)
            return deepcopy(config),deepcopy(ordered)

    @classmethod
    def routine_definition(cls, events, params_by_id):
        """Portable one-day definition: ordered local refs and parameters, no run state."""
        rows = deepcopy(events)
        for index, row in enumerate(rows):
            row.update(priority=index, next_tick=0)
        cls._validate_events(rows)
        ids = {row['instance_id'] for row in rows}
        if set(params_by_id) != ids:
            raise ConfigValidationError('每条日程指令都须有自己的参数')
        for row in rows:
            task = row['func_name']
            if task not in TASKS:
                raise ConfigValidationError('未知日程指令：'+task)
            if set(row.get('pre_task', []) + row.get('post_task', [])) - ids:
                raise ConfigValidationError('日程中的前后置指令必须属于同一天')
            _validate_params(task, params_by_id[row['instance_id']])
        return {'events': rows, 'params_by_id': deepcopy(params_by_id)}

    def initialize_day(self, ordinary, definition, timezone):
        """Prepare a *separate* date profile once; existing progress always wins."""
        with lock:
            if self.pending_path.exists() or self.config_path.exists():
                current = self._ensure()  # recover an interrupted pair before resuming
                # Device / OCR settings can be corrected between attempts. Only the
                # day's instructions and progress are frozen, not its MuMu setup.
                live = {key:deepcopy(ordinary[key]) for key in ('device','game','runtime')
                        if ordinary[key] != current[key]}
                if live: self.patch_config(live)
                return
            config = default_config(self.profile_id)
            for key in ('device','game','runtime'):
                config[key] = deepcopy(ordinary[key])
            config['scheduling']['timezone'] = timezone
            # The calendar owns midnight rollover. Never refresh yesterday's snapshot.
            config['scheduling']['reset']['enabled'] = False
            spec = self.routine_definition(**definition)
            for event in spec['events']:
                key, task = event['instance_id'], event['func_name']
                params = spec['params_by_id'][key]
                if key != task:
                    config['instance_params'][key] = params
                elif task[4:] in config['routine']:
                    config['routine'][task[4:]] = params
                if task in SWEEP_TASKS:
                    config['unfinished_tasks'][key] = deepcopy(params['plans'])
            config['last_refresh_config_time'] = time.time()
            _validate(config)
            self._commit_pair(config, spec['events'])

class AppSettingsRepository:
    def __init__(self,path=None): self.path=Path(path or REPO_ROOT/'config/app.json')
    def load(self):
        with lock: return _merge(default_app_settings(),_read(self.path,{}))
    def save(self,snapshot):
        with lock:
            result=_merge(self.load(),snapshot)
            if result['ui']['theme'] not in ('system','light','dark'): raise ConfigValidationError('未知主题')
            result['schema_version']=SCHEMA_VERSION
            atomic_json(self.path,result)
            return result
