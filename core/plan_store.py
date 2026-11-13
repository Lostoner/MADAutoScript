"""Calendar definitions are per profile. Each started date has its own execution root."""
from copy import deepcopy
from datetime import date, datetime, time, timedelta
import json
import re
from time import time as timestamp
from zoneinfo import ZoneInfo

from core.config.repository import ConfigValidationError, ProfileRepository, instance_params, lock
from core.runtime_state import atomic_json


def _date_key(value):
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError('游戏日须为 YYYY-MM-DD')
    return value


def _clock(text):
    if not isinstance(text, str) or not re.fullmatch(r'\d{2}:\d{2}(:\d{2})?', text):
        raise ConfigValidationError('时间须为 HH:MM')
    return time.fromisoformat(text)


def game_day(now, timezone, reset_at):
    zone = ZoneInfo(timezone)
    current = (now.astimezone(zone) if isinstance(now, datetime)
               else datetime.fromtimestamp(now, zone))
    day = current.date()
    if current.time() < _clock(reset_at):
        day -= timedelta(days=1)
    return day.isoformat()


class PlanStore:
    def __init__(self, repository, clock=None):
        self.repository = repository
        self.clock = clock or timestamp
        self.path = repository.profile_dir/'plan.json'
        self.root = repository.data_root/'state'/repository.profile_id/'plan-days'

    def load(self):
        with lock:
            if self.path.exists():
                return json.loads(self.path.read_text('utf-8'))
            config = self.repository.load_config()
            reset = config['scheduling']['reset']
            zone, boundary = reset['server_timezone'], reset.get('reset_at') or '04:00'
            first = game_day(self.clock(), zone, boundary)
            return {'start': first, 'end': (date.fromisoformat(first)+timedelta(days=6)).isoformat(),
                    'timezone': zone, 'reset_at': boundary, 'default_time': boundary,
                    'auto': False, 'days': {}, 'templates': {}}

    def today(self, now=None):
        plan = self.load()
        return game_day(self.clock() if now is None else now, plan['timezone'], plan['reset_at'])

    def from_daily(self):
        with lock:
            config = self.repository.load_config()
            rows = sorted(self.repository.load_events(), key=lambda row: row['priority'])
            params = {row['instance_id']: instance_params(config, row) for row in rows}
            return ProfileRepository.routine_definition(rows, params)

    def record_path(self, day):
        return self.root/_date_key(day)/'record.json'

    def record(self, day):
        with lock:
            path = self.record_path(day)
            return json.loads(path.read_text('utf-8')) if path.exists() else {}

    def update_record(self, day, **fields):
        with lock:
            record = self.record(day)
            record.update(fields)
            atomic_json(self.record_path(day), record)
            return deepcopy(record)

    def save(self, plan):
        """Save draft content atomically; a date that started during editing stays frozen."""
        with lock:
            old, draft = self.load(), deepcopy(plan)
            # Calendar drafts can remain open while the watcher is paused/resumed.
            # Only set_auto changes execution policy; saving dates cannot restart it.
            draft['auto'] = old['auto']
            first, last = _date_key(draft['start']), _date_key(draft['end'])
            if last < first:
                raise ConfigValidationError('结束日期不能早于开始日期')
            _clock(draft['default_time'])
            today = game_day(self.clock(), draft['timezone'], draft['reset_at'])
            if old['auto'] and (old['timezone'],old['reset_at']) != (draft['timezone'],draft['reset_at']):
                raise ConfigValidationError('请先暂停计划，再修改服务器日切时间')
            if (old['start'] <= today <= old['end'] and not first <= today <= last
                    and self.record(today).get('frozen')):
                raise ConfigValidationError('今天已经开始，不能从计划日期范围中移除')
            for day in set(old['days']) | set(draft['days']):
                _date_key(day)
                entry = draft['days'].get(day)
                if entry is not None and day >= today and not first <= day <= last:
                    raise ConfigValidationError(day+' 仍有安排，请先清空该日，或将其保留在计划范围内')
                if entry == old['days'].get(day):
                    continue
                if day < today or self.record(day).get('frozen'):
                    raise ConfigValidationError(day+' 已过去或已开始，不能覆盖')
                if entry is None:
                    continue
                if entry.get('time'):
                    _clock(entry['time'])
                if entry['kind']=='tasks':
                    entry['routine'] = ProfileRepository.routine_definition(**entry['routine'])
                elif entry['kind']!='rest':
                    raise ConfigValidationError('未知的日期安排')
            draft['templates'] = {name:ProfileRepository.routine_definition(**spec)
                                  for name,spec in draft['templates'].items()}
            if any(not name.strip() for name in draft['templates']):
                raise ConfigValidationError('模板名称不能为空')
            atomic_json(self.path, draft)
            return deepcopy(draft)

    def set_auto(self, enabled):
        with lock:
            plan = self.load()
            plan['auto'] = bool(enabled)
            atomic_json(self.path,plan)
            return deepcopy(plan)

    def day_repository(self, day):
        day = _date_key(day)
        with lock:
            record = self.record(day)
            if not record.get('frozen'):
                plan = self.load()
                entry = plan['days'].get(day)
                if not entry or entry['kind']!='tasks' or not plan['start'] <= day <= plan['end']:
                    raise ConfigValidationError(day+' 没有可执行的计划')
                record.update(frozen=True, name=entry.get('name') or day, routine=deepcopy(entry['routine']),
                              timezone=plan['timezone'], reset_at=plan['reset_at'],
                              time=entry.get('time') or plan['default_time'])
                if any(e['func_name']=='mad.material_sweep' for e in entry['routine']['events']):
                    from core.material_store import MaterialStore
                    record['material_context']='plan:'+day
                    MaterialStore(self.repository).freeze(record['material_context'],record['material_context'])
                record.setdefault('status','ready')
                atomic_json(self.record_path(day), record)
            ordinary = self.repository.load_config()
            repo = ProfileRepository(self.record_path(day).parent/'config'/self.repository.profile_id)
            repo.initialize_day(ordinary, record['routine'], ordinary['scheduling']['timezone'])
            return repo
