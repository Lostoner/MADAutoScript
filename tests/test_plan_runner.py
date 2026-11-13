"""Calendar decisions run through real day repositories, checkpoints and worker loops."""
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock
from zoneinfo import ZoneInfo
import os

from core.config.repository import ProfileRepository
from core.Mad_thread import MadThread
from core.plan_store import PlanStore
from core.plan_runner import PlanRunner, start_at


class CalendarExecution(TestCase):
    def setUp(self):
        tmp=TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.repo=ProfileRepository(Path(tmp.name)/'config/default')
        self.clock= datetime(2026,11,4,8,tzinfo=ZoneInfo('Asia/Hong_Kong')).timestamp()
        self.store=PlanStore(self.repo,clock=lambda:self.clock)
        self.day=self.store.today(); self.plan=self.store.load()
        self.spec=self.store.from_daily()
        self.calls=[]; self.behaviours={}; self.stop_after=None
        self.offline=False
        def emit(event):
            if self.stop_after and event['kind']=='task' and event['state']=='succeeded' and event['instance_id']==self.stop_after:
                self.runner.stop_today()
        self.runtime=SimpleNamespace(repository=self.repo,emit=emit,worker=None)
        def factory(*args,**kwargs):
            w=MadThread(*args,**kwargs)
            def connect():
                if self.offline: raise RuntimeError('MuMu 实例 0 未启动；请先启动该实例。')
            w.connect=connect
            w.to_main_page=lambda:True
            def solve(w):
                i=w.current_instance_id
                self.calls.append(i)
                if i in self.behaviours: self.behaviours[i](w)
                return True
            w.func_dict={e['func_name']:solve for e in self.spec['events']}
            w.func_dict['restart']=lambda w:True
            return w
        self.runner=PlanRunner(self.store,self.runtime,clock=lambda:self.clock,worker_factory=factory)

    def schedule(self,keys,days=1,when='04:00',auto=True):
        self.spec['events'].sort(key=lambda e:keys.index(e['instance_id']) if e['instance_id'] in keys else 999)
        for n,e in enumerate(self.spec['events']):
            e.update(enabled=e['instance_id'] in keys,priority=n)
        day=datetime.fromisoformat(self.day)
        for index in range(days):
            self.plan['days'][(day+timedelta(days=index)).date().isoformat()]=dict(
                kind='tasks',name='材料日',time=when,routine=self.spec)
        self.store.save(self.plan)
        self.store.set_auto(auto)

    def join(self):
        self.assertTrue(self.runtime.worker.join(4))
        return self.store.record(self.day)

    def test_wait_late_start_disabled_period_and_only_remaining(self):
        keys=['mad.claim_all','mad.mail']
        next(e for e in self.spec['events'] if e['instance_id']==keys[1])['disabled_time_range']=[[[8,0,0],[10,0,0]]]
        self.schedule(keys,when='09:00')
        self.assertFalse(self.runner.poll())
        self.clock+=3601
        self.assertTrue(self.runner.poll())
        r=self.join()
        self.assertEqual((r['status'],r['remaining'],self.calls),('partial',[keys[1]],[keys[0]]))
        self.assertFalse(self.runner.poll())
        self.clock+=3600
        self.assertTrue(self.runner.start_today(remaining=True))
        self.assertEqual(self.join()['status'],'completed')
        self.assertEqual(self.calls,keys)
        self.assertFalse(self.runner.start_today())
        self.assertFalse(self.runner.poll())

    def test_stopped_after_claim_resume_keeps_future_edit_and_ordinary_data(self):
        keys=['mad.claim_all','mad.normal_sweep']
        self.schedule(keys,days=2)
        before=self.repo.load_config()
        self.stop_after=keys[0]
        self.assertTrue(self.runner.poll())
        self.assertEqual(self.join()['status'],'stopped')
        self.assertFalse(self.runner.poll())
        p=self.store.load()
        tomorrow='2026-11-05'
        p['days'][tomorrow]['routine']['params_by_id'][keys[1]]['plans'][0]['count']=9
        self.store.save(p)
        def check(w):
            self.assertNotEqual(w.task_params['normal_sweep']['plans'][0]['count'],9)
        self.behaviours[keys[1]]=check
        self.assertTrue(self.runner.start_today())
        self.assertEqual(self.join()['status'],'completed')
        self.assertEqual(self.calls,keys)
        self.assertEqual(self.repo.load_config(),before)

    def test_boundary_during_step_assigns_receipt_to_yesterday_then_starts_today(self):
        keys=['mad.mail','mad.claim_all']
        self.schedule(keys,days=2)
        self.clock+=20*3600-1  # tomorrow 03:59:59
        self.behaviours[keys[0]]=lambda w:setattr(self,'clock',self.clock+1)
        self.assertTrue(self.runner.poll())
        r=self.join()
        self.assertEqual((r['status'],[x['instance_id'] for x in r['tasks']]),('expired',[keys[0]]))
        self.assertEqual(self.calls,[keys[0]])
        self.behaviours.clear()
        self.assertTrue(self.runner.poll())
        self.runtime.worker.join(4)
        self.assertEqual(self.store.record('2026-11-05')['status'],'completed')
        self.assertEqual(self.calls,[keys[0],*keys])

    def test_settle_an_inflight_batch_then_block_next_click_at_day_change(self):
        key='mad.normal_sweep'
        self.spec['params_by_id'][key]['plans']=[{'stage_id':'normal:5-1','count':2}]
        self.schedule([key],days=2)
        self.clock+=20*3600-1
        control=Mock()
        def two_batches(w):
            w.control=control
            w.click(784,501)  # first confirmation at 03:59:59
            self.clock+=1
            w.repository.complete_sweep(key,'normal:5-1',1)  # result received at 04:00
            w.click(784,501)  # another confirmation would spend the next day's stamina
        self.behaviours[key]=two_batches
        self.assertTrue(self.runner.poll())
        self.join()
        control.click.assert_called_once_with(784,501)
        self.assertEqual(self.store.day_repository(self.day).load_config()['unfinished_tasks'][key][0]['count'],1)
        self.assertFalse(self.store.record('2026-11-05').get('frozen'))

    def test_uncertain_purchase_requires_explicit_disposition(self):
        keys=['mad.gold_shop','mad.mail']
        self.schedule(keys)
        def fail(_): raise RuntimeError('purchase acknowledgement missing')
        self.behaviours[keys[0]]=fail
        self.assertTrue(self.runner.poll())
        self.assertEqual(self.join()['status'],'needs_review')
        self.assertFalse(self.runner.poll())
        self.assertFalse(self.runner.start_today())
        self.assertTrue(self.runner.resolve_current(True))
        self.assertTrue(self.runner.start_today())
        self.assertEqual(self.join()['status'],'completed')
        self.assertEqual(self.calls,keys)

    def test_missed_dates_rest_device_wait_and_ordinary_run_conflict(self):
        self.schedule(['mad.mail'],days=4,auto=False)
        p=self.store.load()
        p['days']['2026-11-06']={'kind':'rest'}
        self.store.save(p)
        ordinary=self.repo.data_root/'state'/self.repo.profile_id/'last-run.json'
        ordinary.parent.mkdir(parents=True,exist_ok=True); ordinary.write_text('{}')
        os.utime(ordinary,(self.clock,self.clock))
        self.assertTrue(self.runner.set_auto(True))
        self.assertFalse(self.runner.poll())
        self.clock+=2*86400
        self.assertFalse(self.runner.poll())
        self.assertEqual(self.store.record('2026-11-05')['status'],'missed')
        self.clock+=86400
        self.offline=True
        self.assertTrue(self.runner.poll()); self.runtime.worker.join(4)
        self.assertEqual(self.store.record('2026-11-07')['status'],'waiting_device')
        self.assertFalse(self.runner.poll())
        self.clock+=121; self.offline=False
        self.assertTrue(self.runner.poll());self.runtime.worker.join(4)
        self.assertEqual(self.store.record('2026-11-07')['status'],'completed')
        self.assertEqual(self.calls,['mad.mail'])

    def test_after_midnight_start_belongs_to_next_civil_date(self):
        self.schedule(['mad.mail'],when='02:00')
        trigger=start_at(self.store.load(),self.day)
        self.assertEqual(datetime.fromtimestamp(trigger,ZoneInfo('Asia/Hong_Kong')).isoformat(),'2026-11-05T02:00:00+08:00')
