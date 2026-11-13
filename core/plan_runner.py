"""Calendar triggers for the existing one-pass worker, with one receipt per game day."""
from datetime import date, datetime, timedelta, time as clock_time
from zoneinfo import ZoneInfo
import time

from core.Mad_thread import MadThread
from core.exception import GameDayChanged
from core.tasks import SWEEP_TASKS
from core.material_store import MaterialStore, TASK as MATERIAL_TASK


def material_pending(store):
    pending=MaterialStore(store.repository).state()['pending']
    return bool(pending and pending['phase']=='confirming')


def material_remaining(store, day):
    materials=MaterialStore(store.repository)
    round_=materials.state()['rounds'].get('plan:'+day)
    return bool(round_ and materials.remaining(round_['snapshot']))


def start_at(plan, day):
    at = clock_time.fromisoformat(plan['days'][day].get('time') or plan['default_time'])
    d = date.fromisoformat(day) + timedelta(days=at < clock_time.fromisoformat(plan['reset_at']))
    return datetime.combine(d, at, ZoneInfo(plan['timezone'])).timestamp()


class PlanPass:
    """A day's checkpoint. One atomic write records both a step receipt and its cursor."""
    def __init__(self, store, day, repo, clock, only_remaining=False):
        self.store, self.day, self.repo, self.clock = store, day, repo, clock
        record = store.record(day)
        boundary=clock_time.fromisoformat(record['reset_at'])
        zone=ZoneInfo(record['timezone'])
        calendar_date=date.fromisoformat(day)
        self.window=(datetime.combine(calendar_date,boundary,zone).timestamp(),
                     datetime.combine(calendar_date+timedelta(days=1),boundary,zone).timestamp())
        self.groups = record.get('groups', {})
        self.tasks = record.get('tasks', [])
        self.deferred = record.get('deferred', [])
        self.inflight = None
        self.day_changed = False
        self.finished = False
        self.stop_requested = False
        if only_remaining:
            left = repo.load_config()['unfinished_tasks']
            for item in self.tasks:
                remaining=(left.get(item['instance_id']) if item['task_id'] in SWEEP_TASKS else
                           material_remaining(store,day) if item['task_id']==MATERIAL_TASK else False)
                if item['status']=='PARTIAL' and remaining:
                    group = self.groups[item['root']]
                    if item['token'] in group['steps']:
                        group['steps'].remove(item['token'])
                        group['scheduled'] = False
        store.update_record(day, status='running', groups=self.groups, error='', inflight=None)

    def check_day(self):
        if not self.window[0]<=self.clock()<self.window[1]:
            self.day_changed = True
            raise GameDayChanged()

    def started(self, run_dir):
        self.store.update_record(self.day,run_dir=str(run_dir))
        self.check_day()

    def selected(self, queue, instances):
        selected = {e['instance_id'] for e in queue}
        self.deferred = [i for i,e in instances.items() if e['enabled'] and i not in selected
                         and not self.groups.get(i,{}).get('scheduled')]
        reasons={i:instances[i]['event_name']+'：当前处于禁用时段，可在允许时段仅续做余项。' for i in self.deferred}
        self.store.update_record(self.day,deferred=self.deferred,deferred_reasons=reasons)
        return reasons.values()

    def group(self, root, tick):
        return self.groups.setdefault(root, {'steps':[], 'scheduled':False, 'next_time':0})

    def begin_step(self, root, token, identity):
        self.check_day()
        self.inflight = dict(identity,root=root,token=token)
        self.store.update_record(self.day,inflight=self.inflight)

    def confirm(self, result):
        self.tasks.append(dict(self.inflight,**result))
        self.inflight = None
        self.store.update_record(self.day, groups=self.groups, tasks=self.tasks, inflight=None)

    def finish_group(self, root):
        self.groups[root]['scheduled'] = True
        self.store.update_record(self.day, groups=self.groups)

    def finish_pass(self):
        left = self.repo.load_config()['unfinished_tasks']
        remaining = list(dict.fromkeys(self.deferred + [r['instance_id'] for r in self.tasks
                         if r['status']=='PARTIAL' and ((r['task_id'] in SWEEP_TASKS and left.get(r['instance_id']))
                         or (r['task_id']==MATERIAL_TASK and material_remaining(self.store,self.day)))]))
        self.store.update_record(self.day, status='partial' if remaining else 'completed',
                                 remaining=remaining, deferred=self.deferred, inflight=None)
        self.finished = True

    def ended(self, result):
        full_error = result.get('error') or ''
        reason = full_error.strip().splitlines()[-1] if full_error.strip() else ''
        fields = {'run_dir':result['run_dir'],'error':reason}
        if not self.finished:
            if self.inflight and (self.inflight['task_id'] in ('mad.gold_shop','mad.dating',*SWEEP_TASKS) or
                    (self.inflight['task_id']==MATERIAL_TASK and material_pending(self.store))):
                fields.update(status='needs_review',error=reason or '步骤中断，请先核对游戏内的实际结果。')
            elif self.day_changed or self.store.today(self.clock()) != self.day:
                fields.update(status='expired',inflight=None)
            elif self.stop_requested:
                fields.update(status='stopped',inflight=None)
            elif not self.inflight and 'MuMu 实例' in reason and '未启动' in reason:
                fields.update(status='waiting_device',retry_at=self.clock()+120)
            else:
                fields.update(status='failed' if reason else 'stopped',inflight=None)
        self.store.update_record(self.day, **fields)


class PlanRunner:
    """UI calls poll on a timer; all emulator/ADB/OCR work stays in MadThread."""
    def __init__(self, store, runtime, emit=None, clock=time.time, worker_factory=MadThread):
        self.store,self.runtime,self.emit=store,runtime,emit or runtime.emit
        self.clock,self.worker_factory=clock,worker_factory
        self.message=''
        self._archived=None

    @property
    def is_plan_running(self):
        w=self.runtime.worker
        return bool(w and w.is_running and getattr(w,'plan_date',None))

    def _busy(self):
        return self.runtime.worker and self.runtime.worker.is_running

    def _recover(self, day):
        r=self.store.record(day)
        if r.get('status')=='running' and not self.is_plan_running:
            op=r.get('inflight') or {}
            review=(op.get('task_id') in ('mad.gold_shop','mad.dating',*SWEEP_TASKS) or
                    (op.get('task_id')==MATERIAL_TASK and material_pending(self.store)))
            r=self.store.update_record(day,status='needs_review' if review else 'stopped',
                    error='上次运行未正常结束。'+('请核对当前步骤。' if review else '可继续今日。'))
        return r

    def today_status(self):
        now=self.clock()
        day=self.store.today(now)
        plan=self.store.load()
        r=self._recover(day)
        if r.get('status'): return day,r['status'],r.get('error','')
        if day>plan['end']: return day,'ended','计划已结束'
        item=plan['days'].get(day,{})
        if day<plan['start'] or not item: return day,'unscheduled','今天未安排'
        if item['kind']=='rest': return day,'rest','今天休息'
        return day,'ready','等待执行'

    def _ordinary_ran(self,day):
        repo=self.runtime.repository
        path=repo.data_root/'state'/repo.profile_id/'last-run.json'
        return path.is_file() and self.store.today(path.stat().st_mtime)==day

    def _next_date(self, plan, day, skip):
        for key,item in sorted(plan['days'].items()):
            if key<max(day,plan['start']) or key>plan['end'] or item['kind']!='tasks': continue
            if key==day and (skip or self.store.record(key).get('status') not in (None,'ready','waiting_device')): continue
            return key

    def preview_auto(self):
        p=self.store.load(); day=self.store.today(self.clock())
        skip=self._ordinary_ran(day) or self.store.record(day).get('auto_skip',False)
        key=self._next_date(p,day,skip)
        prefix='今天普通日常已有运行记录，自动执行跳过今天。' if skip else ''
        if not key: return prefix+'当前范围没有待自动启动的日期。'
        at=start_at(p,key)
        if key==day and at<=self.clock(): return prefix+'启用后将立即执行今天的安排。'
        text=datetime.fromtimestamp(at,ZoneInfo(p['timezone'])).strftime('%m/%d %H:%M')
        return prefix+'下次自动开始：'+text+'。'

    def set_auto(self, enabled):
        if enabled and self._busy() and not self.is_plan_running:
            self.message='请先停止正在执行的普通日常。'; return False
        p=self.store.load(); day=self.store.today(self.clock())
        if enabled:
            self.message=self.preview_auto()
            if not p['auto'] and self._ordinary_ran(day):
                self.store.update_record(day,auto_skip=True)
        else:
            if self.is_plan_running: self.stop_today()
            self.message='计划自动执行已暂停。'
        self.store.set_auto(enabled)
        return True

    def start_today(self, remaining=False):
        if self._busy():
            self.message='已有任务运行中。'; return False
        now=self.clock(); day=self.store.today(now); plan=self.store.load(); item=plan['days'].get(day)
        if not plan['start']<=day<=plan['end'] or not item or item['kind']!='tasks':
            self.message='今天没有待执行的安排。'; return False
        r=self._recover(day); status=r.get('status','ready')
        if status=='needs_review':
            self.message='此步骤结果待核对，请先标记结果。'; return False
        if status in ('missed','expired','completed') or (status=='partial')!=bool(remaining):
            self.message='有未完成的余项，可选择「仅续做余项」。' if status=='partial' else '当天没有可执行的此类任务。'
            return False
        repo=self.store.day_repository(day)
        if not any(e['enabled'] for e in repo.load_events()):
            self.store.update_record(day,status='completed',tasks=[],remaining=[],error='没有启用的指令')
            self.message='今天没有启用的指令。'
            return False
        policy=PlanPass(self.store,day,repo,self.clock,remaining)
        w=self.worker_factory(repo,self.emit,self.runtime,plan_pass=policy)
        w.scheduler.clock=self.clock
        self.runtime.worker=w
        self.message='开始今日：'+(item.get('name') or day)
        return w.start_tasks()

    def resolve_current(self, done):
        day=self.store.today(self.clock())
        r=self._recover(day)
        if self._busy() or r.get('status')!='needs_review' or not r.get('inflight'): return False
        op=r['inflight']
        if op['task_id']==MATERIAL_TASK:
            MaterialStore(self.store.repository).resolve_pending(done)
        groups=r.get('groups',{})
        if done:
            g=groups.setdefault(op['root'],{'steps':[],'scheduled':False,'next_time':0})
            if op['token'] not in g['steps']: g['steps'].append(op['token'])
        tasks=r.get('tasks',[])
        if done:
            tasks.append(dict(op,status='PARTIAL' if op['task_id']==MATERIAL_TASK else 'MANUAL',
                              reason='玩家已核对，跳过此步骤；素材目标仍按共享库存判定。' if op['task_id']==MATERIAL_TASK
                              else '玩家已核对，跳过此步骤。'))
        self.store.update_record(day,status='stopped',groups=groups,tasks=tasks,inflight=None,error='')
        self.message='核对结果已保存，可继续今日。'
        return True

    def stop_today(self):
        if self.is_plan_running:
            self.runtime.worker.plan_pass.stop_requested=True
            self.runtime.worker.request_stop()
        else:
            day,status,_=self.today_status()
            if status in ('ready','waiting_device','failed'):
                self.store.update_record(day,status='stopped',error='')
        self.message='已停止今日自动启动，可手动继续。'

    def poll(self):
        if self._busy(): return False
        now=self.clock(); plan=self.store.load(); day=self.store.today(now)
        # Record only explicit task dates. No backlog, no game operations for missed days.
        if self._archived!=day:
            for key,item in plan['days'].items():
                if key>=day or item['kind']!='tasks': continue
                r=self._recover(key); old=r.get('status')
                if old in (None,'ready','waiting_device','stopped','running','failed'):
                    self.store.update_record(key,status='expired' if r.get('frozen') else 'missed')
            self._archived=day
        if not plan['auto']: return False
        if day>plan['end']:
            self.store.set_auto(False); self.message='计划已结束。'; return False
        item=plan['days'].get(day)
        if day<plan['start'] or not item or item['kind']!='tasks': return False
        r=self._recover(day)
        if (r.get('auto_skip') or r.get('status') not in (None,'ready','waiting_device')
                or now<max(start_at(plan,day),r.get('retry_at',0))): return False
        return self.start_today()
