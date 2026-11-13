from copy import deepcopy
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from zoneinfo import ZoneInfo

from core.config.repository import ConfigValidationError, ProfileRepository
from core.plan_store import PlanStore


class CalendarStore(TestCase):
    def setUp(self):
        directory=TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.repo=ProfileRepository(Path(directory.name)/'config/default')
        self.tz=ZoneInfo('Asia/Hong_Kong')
        self.now=datetime(2026,11,4,12,tzinfo=self.tz).timestamp()
        self.store=PlanStore(self.repo, clock=lambda:self.now)
        self.day='2026-11-04'
        self.tomorrow='2026-11-05'
        self.normal='mad.normal_sweep'

    def entry(self):
        return {'kind':'tasks','name':'日常材料','time':None,'routine':self.store.from_daily()}

    def test_game_dates_and_long_independent_copies(self):
        plan=self.store.load()
        self.assertFalse(self.store.path.exists())
        self.assertEqual((plan['start'],plan['end']),(self.day,'2026-11-10'))
        self.assertEqual(self.store.today(datetime(2026,11,5,3,59,tzinfo=self.tz)),self.day)
        self.assertEqual(self.store.today(datetime(2026,11,5,4,tzinfo=self.tz)),self.tomorrow)
        entry=self.entry()
        plan['end']='2026-11-17'
        plan['templates']={'材料日':deepcopy(entry['routine'])}
        plan['days']={self.day:deepcopy(entry),self.tomorrow:deepcopy(entry),'2026-11-06':{'kind':'rest'}}
        self.store.save(plan)
        plan=self.store.load()
        plan['days'][self.tomorrow]['routine']['params_by_id'][self.normal]['plans'][0]['count']=8
        saved=self.store.save(plan)
        self.assertEqual(saved['days'][self.day]['routine'],entry['routine'])
        self.assertEqual(saved['templates']['材料日'],entry['routine'])
        self.assertEqual(saved['days']['2026-11-06']['kind'],'rest')
        with self.assertRaises(ConfigValidationError): self.store.day_repository('2026-11-06')
        self.assertFalse(self.store.record_path('2026-11-06').exists())

    def test_frozen_date_owns_progress_refs_and_clock_not_the_daily_profile(self):
        entry=self.entry()
        spec=entry['routine']
        stage=spec['params_by_id'][self.normal]['plans'][0]['stage_id']
        event=next(e for e in spec['events'] if e['instance_id']==self.normal)
        spec['events'].append(dict(event,instance_id='tail',pre_task=['mad.mail'],enabled=True))
        spec['params_by_id']['tail']={'plans':[{'stage_id':stage,'count':'max'}]}
        self.repo.complete_sweep(self.normal,stage,1)
        self.repo.save_events([{'instance_id':self.normal,'next_tick':123}],fields={'next_tick'})
        regular_cfg,regular_events=self.repo.load_config(),self.repo.load_events()
        self.assertEqual(next(e for e in self.store.from_daily()['events'] if e['instance_id']==self.normal)['next_tick'],0)
        plan=self.store.load()
        plan['days']={self.day:entry,self.tomorrow:deepcopy(entry)}
        self.store.save(plan)
        today=self.store.day_repository(self.day)
        self.assertFalse(today.load_config()['scheduling']['reset']['enabled'])
        self.assertEqual(today.load_config()['unfinished_tasks'][self.normal],spec['params_by_id'][self.normal]['plans'])
        self.assertEqual(today.load_events()[-1]['pre_task'],['mad.mail'])
        today.complete_sweep('tail',stage,2,finish_max=True)
        today.save_events([{'instance_id':self.normal,'next_tick':999}],fields={'next_tick'})
        reopened=self.store.day_repository(self.day)
        self.assertEqual(reopened.load_config()['unfinished_tasks']['tail'],[])
        self.assertEqual(self.repo.load_config(),regular_cfg)
        self.assertEqual(self.repo.load_events(),regular_events)

        draft=self.store.load()
        draft['days'][self.tomorrow]['name']='周末培养'
        self.store.save(draft)
        draft['days'][self.day]['kind']='rest'
        with self.assertRaisesRegex(ConfigValidationError,'不能覆盖'):
            self.store.save(draft)
        self.assertEqual(self.store.record(self.day)['routine'],self.store.load()['days'][self.day]['routine'])
        self.now+=86400
        next_day=self.store.day_repository(self.tomorrow)
        self.assertNotEqual(next_day.data_root, today.data_root)
        self.assertEqual(next_day.load_config()['unfinished_tasks']['tail'],spec['params_by_id']['tail']['plans'])

    def test_waiting_for_device_does_not_freeze_date_but_past_dates_cannot_be_replaced(self):
        plan=self.store.load()
        plan['days'][self.day]=self.entry()
        self.store.save(plan)
        self.store.update_record(self.day,status='waiting_device')
        plan['days'][self.day]['name']='新任务'
        self.store.save(plan)
        self.assertNotIn('frozen',self.store.record(self.day))
        self.now+=86400
        plan['days'][self.day]={'kind':'rest'}
        with self.assertRaises(ConfigValidationError): self.store.save(plan)

    def test_watcher_and_editor_own_separate_fields(self):
        stale=self.store.load()
        self.store.set_auto(True)
        stale['days'][self.day]=self.entry()
        self.assertTrue(self.store.save(stale)['auto'])
        stale=self.store.load()
        self.store.set_auto(False)
        stale['days'][self.tomorrow]={'kind':'rest'}
        self.assertFalse(self.store.save(stale)['auto'])

    def test_range_shrink_cannot_hide_future_work_and_keeps_history(self):
        plan=self.store.load()
        plan['days']={self.day:self.entry(), self.tomorrow:{'kind':'rest'}}
        self.store.save(plan)
        plan['end']=self.day
        with self.assertRaisesRegex(ConfigValidationError,self.tomorrow):
            self.store.save(plan)
        self.assertEqual(self.store.load()['end'],'2026-11-10')
        del plan['days'][self.tomorrow]
        self.store.save(plan)
        self.now+=86400
        plan.update(start=self.tomorrow,end='2026-11-11')
        self.assertIn(self.day,self.store.save(plan)['days'])
