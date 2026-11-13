"""BAAS heartbeat/systole scheduler, pinned baseline 1110e88 (GPL-3.0).

MAD differences: existing task IDs, repository field writes, explicit UI timezone,
and a one-pass selector. No second persistent schedule or dependency graph.
"""
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from core.config.repository import ProfileRepository

def daily_reset_timestamp(reset,now,*,upcoming=False):
    """Shared server-day boundary for progress and the existing event clock."""
    if not reset['enabled'] or not reset.get('reset_at'): return None
    parts=[int(v) for v in reset['reset_at'].split(':')]
    current=datetime.fromtimestamp(now,ZoneInfo(reset['server_timezone']))
    boundary=current.replace(hour=parts[0],minute=parts[1],second=parts[2] if len(parts)>2 else 0,microsecond=0)
    if upcoming:
        if boundary<=current: boundary+=timedelta(days=1)
    elif boundary>current: boundary-=timedelta(days=1)
    return boundary.timestamp()

class Scheduler:
    def __init__(self,update_signal=None,path=None,*,repository=None,clock=time.time):
        self.repository=repository or ProfileRepository(path)
        self.update_signal=update_signal
        self.clock=clock
        self._current_task=None
        self._waitingTaskDisplayQueue=[]
        self._currentTaskDisplay=None
        self.first_waiting=True
        self._read_config()

    def _read_config(self):
        self._event_config=self.repository.load_events()
        self.instances={e['instance_id']:e for e in self._event_config}

    @staticmethod
    def convert_to_seconds(hour,minute,second=0): return hour*3600+minute*60+second

    @staticmethod
    def is_disable_period(event,seconds):
        return any(Scheduler.convert_to_seconds(*a)<=seconds<=Scheduler.convert_to_seconds(*b) for a,b in event['disabled_time_range'])

    def eligible(self,once=False,task_ids=None):
        self._read_config()
        zone=self.repository.load_config()['scheduling']['timezone']
        now=datetime.fromtimestamp(self.clock(),ZoneInfo(zone))
        seconds=self.convert_to_seconds(now.hour,now.minute,now.second)
        return sorted([e for e in self._event_config
                       if (once or not e.get('follow_after'))
                       and (e['instance_id'] in task_ids if task_ids is not None else e['enabled'])
                       and (once or e['next_tick']<=self.clock()) and not self.is_disable_period(e,seconds)],key=lambda e:e['priority'])

    def expand(self,event,*,once=False):
        # Legacy explicit hooks can reference disabled original rows. Linked
        # copies, instead, obey their own switch and the parent's trigger.
        root=event['instance_id']
        zone=self.repository.load_config()['scheduling']['timezone']
        now=datetime.fromtimestamp(self.clock(),ZoneInfo(zone))
        seconds=self.convert_to_seconds(now.hour,now.minute,now.second)
        followers=[e['instance_id'] for e in sorted(self._event_config,key=lambda e:e['priority'])
                   if not once and e.get('follow_after')==root and e['enabled'] and not self.is_disable_period(e,seconds)]
        def hooks(refs):
            return [key for key in refs if key in self.instances and not self.instances[key].get('follow_after')]
        return {'current_task':root,'pre_task':hooks(event['pre_task']),
                'post_task':hooks(event['post_task'])+followers}

    def _emit(self,names):
        if self.update_signal is not None:
            (self.update_signal.emit if hasattr(self.update_signal,'emit') else self.update_signal)(names)

    def heartbeat(self):
        queue=self.eligible()
        self._waitingTaskDisplayQueue=[e['event_name'] for e in queue[1:]]
        if not queue:
            self._currentTaskDisplay=None
            if self.first_waiting:
                self._emit(['暂无任务'])
                self.first_waiting=False
            return None
        self.first_waiting=True
        self._current_task=self.expand(queue[0])
        self._currentTaskDisplay=queue[0]['event_name']
        self._emit([self._currentTaskDisplay,*self._waitingTaskDisplayQueue])
        return self._current_task

    def systole(self,task_name,next_time=0,force_task=False):
        if not force_task and (not self._current_task or task_name!=self._current_task['current_task']): return None
        self._read_config()
        event=self.instances[task_name]
        now=self.clock()
        if next_time>0: tick=now+next_time
        else:
            tick=now+(event['interval'] if event['interval']>0 else 86400)
            utc=datetime.fromtimestamp(now,timezone.utc)
            for h,m,s in event['daily_reset']:
                reset=utc.replace(hour=h,minute=m,second=s,microsecond=0)
                if reset.timestamp()<=now: reset+=timedelta(days=1)
                tick=min(tick,reset.timestamp())
            boundary=daily_reset_timestamp(self.repository.load_config()['scheduling']['reset'],now,upcoming=True)
            if boundary is not None: tick=min(tick,boundary)
        self.repository.save_events([{'instance_id':task_name,'next_tick':int(tick)}],fields={'next_tick'})
        return tick

    def getWaitingTaskList(self): return self._waitingTaskDisplayQueue
    def getCurrentTaskName(self): return self._currentTaskDisplay
