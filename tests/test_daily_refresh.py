"""Focused day-boundary checks; temporary profiles, no device or real waits."""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo
import json

from core.config.repository import ProfileRepository
from core.Mad_thread import MadThread
from core.scheduler import Scheduler
from module import restart


class DailyRefresh(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory(prefix='mad-day-')
        self.repo=ProfileRepository(Path(self.tmp.name)/'config/default')
        self.config=self.repo.load_config()
        self.plans=[{'stage_id':'normal:4-5','count':2},{'stage_id':'normal:4-6','count':3}]
        routine=deepcopy(self.config['routine'])
        routine['normal_sweep']['plans']=self.plans
        self.boundary=datetime(2026,10,28,4,tzinfo=ZoneInfo('Asia/Hong_Kong')).timestamp()
        self.repo.patch_config({'routine':routine,'last_refresh_config_time':self.boundary-60})

    def tearDown(self):
        self.tmp.cleanup()

    def test_legacy_upgrade_preserves_progress_and_refreshes_once(self):
        self.repo.complete_sweep('mad.normal_sweep','normal:4-5',1)
        original=self.repo.load_config()
        original['schema_version']=4
        original['last_refresh_config_time']=self.boundary-5*3600
        original['scheduling']['reset']={'enabled':False,'server_timezone':'UTC','reset_at':None}
        self.repo.config_path.write_text(json.dumps(original),encoding='utf-8')
        events_before=self.repo.event_path.read_bytes()
        upgraded=self.repo.load_config()
        expected=deepcopy(original)
        expected['scheduling']['reset']=self.config['scheduling']['reset']
        expected['schema_version']=self.config['schema_version']
        expected['revision']+=1
        self.assertEqual(upgraded,expected)
        self.assertEqual(self.repo.event_path.read_bytes(),events_before)
        self.assertEqual(self.repo.load_config(),upgraded)

        worker=MadThread(self.repo)
        self.assertFalse(worker.daily_config_refresh(now=self.boundary-4*3600))
        self.assertFalse(worker.daily_config_refresh(now=self.boundary-1))
        self.assertEqual(self.repo.load_config()['unfinished_tasks'],original['unfinished_tasks'])
        self.assertTrue(worker.daily_config_refresh(now=self.boundary))
        self.assertEqual(self.repo.load_config()['unfinished_tasks']['mad.normal_sweep'],self.plans)
        self.repo.complete_sweep('mad.normal_sweep','normal:4-5',1)
        progress=self.repo.load_config()['unfinished_tasks']
        reopened=MadThread(ProfileRepository(self.repo.profile_dir))
        self.assertFalse(reopened.daily_config_refresh(now=self.boundary+10))
        self.assertEqual(self.repo.load_config()['unfinished_tasks'],progress)
        custom={'enabled':False,'server_timezone':'UTC','reset_at':'07:30'}
        older=self.repo.load_config()
        older['schema_version']=4
        older['scheduling']['reset']=custom
        self.repo.config_path.write_text(json.dumps(older),encoding='utf-8')
        self.assertEqual(self.repo.load_config()['scheduling']['reset'],custom)
        self.assertEqual(self.repo.load_config()['unfinished_tasks'],progress)
        self.assertFalse(reopened.daily_config_refresh(now=self.boundary+86400))
        # This is a one-time upgrade, not a rule that re-enables a user switch.
        self.repo.patch_config({'scheduling':{'reset':{'enabled':False,'reset_at':None}}})
        self.assertFalse(self.repo.load_config()['scheduling']['reset']['enabled'])
        self.assertIsNone(self.repo.load_config()['scheduling']['reset']['reset_at'])

    def test_continuous_wait_refreshes_before_selecting_due_tasks(self):
        self.repo.set_unfinished('mad.normal_sweep',[])
        self.repo.save_events([{'func_name':e['func_name'],'enabled':e['func_name']=='mad.normal_sweep'}
                              for e in self.repo.load_events()],fields={'enabled'})
        clock=[self.boundary-1]
        scheduler=Scheduler(repository=self.repo,clock=lambda:clock[0])
        self.assertEqual(scheduler.systole('mad.normal_sweep',force_task=True),self.boundary)
        # Reproduce a stored next_tick from the previous 24-hour-only scheduler.
        self.repo.save_events([{'func_name':'mad.normal_sweep','next_tick':self.boundary+3600}],fields={'next_tick'})
        events_before=self.repo.load_events()
        worker=MadThread(self.repo)
        worker.scheduler.clock=lambda:clock[0]
        worker.connect=Mock()
        worker.to_main_page=Mock()
        worker.guard.wait=Mock(side_effect=lambda seconds:clock.__setitem__(0,self.boundary))
        processed=[]
        def task(w):
            processed.append(w.repository.load_config()['unfinished_tasks']['mad.normal_sweep'])
            w.flag_run=False
            return True
        worker.func_dict={'restart':lambda w:True,'mad.normal_sweep':task}
        worker.flag_run=True
        with patch('core.Mad_thread.time.time',side_effect=lambda:clock[0]):
            worker.thread_starter(continuous=True)
        self.assertIsNone(worker.last_result['error'])
        self.assertEqual(processed,[self.plans])
        worker.guard.wait.assert_called_once_with(1)
        events_after=self.repo.load_events()
        self.assertEqual([{k:v for k,v in e.items() if k!='next_tick'} for e in events_after],
                         [{k:v for k,v in e.items() if k!='next_tick'} for e in events_before])
        self.assertEqual(next(e for e in events_after if e['func_name']=='mad.normal_sweep')['next_tick'],self.boundary+86400)

    def test_date_dialog_reloads_old_plan_but_does_not_reset_twice(self):
        self.repo.complete_sweep('mad.normal_sweep','normal:4-5',1)
        worker=MadThread(self.repo)
        worker.flag_run=True
        worker.match=Mock(return_value=False)
        worker.scan=Mock(return_value=[{'text':'日期变更','point':(640,300)},
                                      {'text':'确认','point':(640,500)}])
        worker.click=Mock()
        worker.to_main_page=Mock(side_effect=lambda:setattr(worker,'date_popup_handled',False))
        seen=[]
        def task(w):
            seen.append(w.repository.load_config()['unfinished_tasks']['mad.normal_sweep'])
            if len(seen)==2: w.repository.complete_sweep('mad.normal_sweep','normal:4-5',1)
            if len(seen)<3: restart.deal_with_popup(w)
            return True
        worker.func_dict={'mad.normal_sweep':task}
        with patch('core.Mad_thread.time.time',return_value=self.boundary), \
             patch.object(self.repo,'reset_progress',wraps=self.repo.reset_progress) as refresh:
            self.assertTrue(worker.solve('mad.normal_sweep'))
        self.assertEqual([plans[0]['count'] for plans in seen],[1,2,1])
        refresh.assert_called_once_with(self.boundary,reset_schedule=True)
        self.assertEqual(worker.click.call_count,2)
