"""Material quotas through real plan and ordinary execution cursors; no device."""
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from core.Mad_thread import MadThread
from core.material_store import MaterialStore, TASK
from core.routine_checkpoint import RoutineCheckpoint
from module.material_sweep import execute
from module import sweep_utils as sweep
from tests import test_plan_runner as calendar_tests, test_material_priority as priority_tests
from tests.test_material_priority import fixture, A, B, S, T


class MaterialPlanExecution(TestCase):
    schedule = calendar_tests.CalendarExecution.schedule
    join = calendar_tests.CalendarExecution.join

    def setUp(self):
        calendar_tests.CalendarExecution.setUp(self)
        self.materials=MaterialStore(self.repo)
        self.data,self.snapshot,self.observation=fixture()
        self.snapshot['targets']=self.snapshot['targets'][:2]
        for name in ('core.material_planner.catalog','module.material_sweep.catalog'):
            p=patch(name,return_value=self.data); p.start(); self.addCleanup(p.stop)
        self.balance=100; self.stock=0; self.batches=[]; self.lower_balance=False; self.unknown=False
        self.observer=Mock(); self.observer.select.return_value=True
        def observe(*_):
            return dict(deepcopy(self.observation),balance=self.balance,inventory={A:self.stock})
        self.observer.collect.side_effect=observe; self.observer.after_batch.side_effect=observe
        def start(w,count,cost,*,before_confirm):
            if self.lower_balance: self.balance=min(self.balance,60)
            actual=min(count,self.balance//cost)
            if not actual: return sweep.SweepBatch()
            before_confirm(actual,self.balance-actual*cost)
            self.balance-=actual*cost; self.stock+=actual
            self.batches.append((w.material_allocation_id,w.current_instance_id,actual))
            if self.unknown: raise RuntimeError('确认后结果丢失')
            return sweep.SweepBatch(actual,self.balance)
        for p in (patch.object(sweep,'start_sweep',side_effect=start),patch.object(sweep,'return_to_list')):
            p.start(); self.addCleanup(p.stop)
        self.behaviours[TASK]=lambda w:execute(w,self.materials,w.material_context,self.observer)

    def prepare(self,limited=False):
        if limited: self.snapshot['targets'][0].update(stock_limit_enabled=True,amount=50)
        self.materials.save_targets(self.snapshot['targets'])
        self.schedule([TASK,'mad.mail'])

    def test_only_remaining_resumes_exact_debt_and_does_not_repeat_mail(self):
        self.prepare(); self.lower_balance=True
        self.assertTrue(self.runner.start_today()); first=self.join()
        self.assertEqual(first['status'],'partial'); self.assertEqual(sum(b[2] for b in self.batches),6)
        self.balance=100; self.lower_balance=False
        self.assertTrue(self.runner.start_today(remaining=True)); last=self.join()
        self.assertEqual(last['status'],'completed'); self.assertEqual(sum(b[2] for b in self.batches),10)
        self.assertEqual(len({b[0] for b in self.batches}),1)
        self.assertEqual(self.calls,[TASK,'mad.mail',TASK]); self.assertFalse(self.runner.start_today(remaining=True))

    def test_explicit_stock_continuation_gets_new_quota_without_pure_material(self):
        self.prepare(limited=True)
        self.assertTrue(self.runner.start_today()); self.assertEqual(self.join()['status'],'partial')
        first=self.materials.state()['rounds']['plan:'+self.day]['allocations']
        self.assertEqual(next(iter(first.values()))['by_stage'],{S:7,T:3})
        self.balance=100; self.stock=49
        self.assertTrue(self.runner.start_today(remaining=True)); last=self.join()
        self.assertEqual(last['status'],'completed'); self.assertEqual(sum(b[2] for b in self.batches),11)
        records=self.materials.state()['rounds']['plan:'+self.day]['allocations']
        self.assertEqual(len(records),2)
        second=list(records.values())[-1]
        self.assertTrue(second['inventory_only']); self.assertEqual(second['by_stage'],{S:1})
        self.assertEqual(self.calls,[TASK,'mad.mail',TASK])

    def test_unknown_batch_cannot_escape_review_and_disposition_closes_step(self):
        self.prepare(); self.unknown=True
        self.assertTrue(self.runner.start_today()); record=self.join()
        self.assertEqual(record['status'],'needs_review')
        self.assertIn('material_allocation',record['inflight'])
        self.assertFalse(self.runner.start_today()); self.assertTrue(self.runner.resolve_current(True))
        self.unknown=False
        self.assertTrue(self.runner.start_today()); record=self.join()
        self.assertEqual(record['status'],'completed'); self.assertEqual(self.calls,[TASK,'mad.mail'])
        self.assertEqual(len(self.batches),1); self.assertEqual(record['tasks'][0]['status'],'SKIPPED')


class MaterialExecutionIdentity(TestCase):
    setUp = priority_tests.PriorityStorageTests.setUp

    def test_occurrences_roles_roots_cycles_and_restart_have_distinct_stable_keys(self):
        event=next(e for e in self.repo.load_events() if e['instance_id']==TASK)
        event['next_tick']=10
        scheduler=SimpleNamespace(instances={TASK:event},systole=Mock())
        worker=SimpleNamespace(repository=self.repo,scheduler=scheduler,guard=Mock(),plan_pass=None,
            emit=Mock(),material_context='round',error=None)
        task={'current_task':TASK,'pre_task':[TASK,TASK],'post_task':[TASK]}
        keys=[]
        def solve(_):
            keys.append(worker.material_allocation_id)
            return len(keys)!=3
        worker.solve=solve
        directory=self.repo.data_root/'state/identity'
        cursor=RoutineCheckpoint(directory,True,None,1)
        with self.assertRaises(RuntimeError): MadThread.run_group(worker,task,cursor,[])
        cursor=RoutineCheckpoint(directory,True,None,1)
        MadThread.run_group(worker,task,cursor,[])
        self.assertEqual(keys[2],keys[3]); self.assertEqual(len(set(keys)),4)
        self.assertEqual([json.loads(k)[1:4] for k in keys[:3]],[['pre',TASK,1],['pre',TASK,2],['main',TASK,1]])
        previous=set(keys); event['next_tick']=20
        MadThread.run_group(worker,task,cursor,[])
        self.assertFalse(previous.intersection(keys[-4:]))
        other='mad.mail'; scheduler.instances[other]=next(e for e in self.repo.load_events() if e['instance_id']==other)
        scheduler.instances[other]['next_tick']=20
        task['current_task']=other
        worker.solve=lambda kind:(keys.append(worker.material_allocation_id) if kind==TASK else None) or True
        MadThread.run_group(worker,task,cursor,[])
        self.assertEqual(json.loads(keys[-1])[0],other)
