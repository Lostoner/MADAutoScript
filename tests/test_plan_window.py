"""Exercise the calendar from the workspace button to the day's recorded sweep results."""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from core.Mad_thread import MadThread
from main import create_window
from module import normal_sweep, sweep_utils


class CalendarWorkspace(TestCase):
    def test_second_unshown_window_cannot_recover_first_windows_inflight_purchase(self):
        tmp=TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        root=Path(tmp.name)
        app,first=create_window(root)
        type(self).app=app
        self.addCleanup(first.close)
        store=first.plan_store
        store.save(store.load())
        day=store.today()
        store.update_record(day,status='running',inflight={'task_id':'mad.gold_shop'})
        lease=first.runtime.acquire_execution()
        try:
            _,other=create_window(root)  # a real second GUI is refused before show()
            self.addCleanup(other.close)
            self.assertEqual(store.record(day)['status'],'running')
            with self.assertRaises(RuntimeError):
                other.runtime.acquire_execution()
        finally:
            lease.unlock()

    def test_calendar_button_auto_trigger_two_sweeps_and_completed_date(self):
        from PyQt5.QtWidgets import QDialog, QMessageBox
        tmp=TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        app,window=create_window(Path(tmp.name))
        type(self).app=app
        self.addCleanup(window.close)
        window.show()
        store=window.plan_store
        now=datetime(2026,11,4,10,tzinfo=ZoneInfo('Asia/Hong_Kong')).timestamp()
        store.clock=window.plan_runner.clock=lambda:now
        before=window.repository.load_config()
        plan=store.load()
        day=store.today()
        spec=store.from_daily()
        normal='mad.normal_sweep'; reward='mad.claim_all'; tail='tail'
        for e in spec['events']: e['enabled']=e['instance_id'] in (normal,reward)
        row=next(e for e in spec['events'] if e['instance_id']==normal)
        spec['events'].append(dict(row,instance_id=tail,event_name='领完清体力',priority=20))
        spec['params_by_id'][normal]={'plans':[dict(stage_id='normal:5-1',count=5)]}
        spec['params_by_id'][tail]={'plans':[dict(stage_id='normal:5-1',count='max')]}
        plan['days'][day]=dict(kind='tasks',name='材料日',routine=spec)
        plan['days']['2026-11-05']=deepcopy(plan['days'][day])
        store.save(plan)
        with patch.object(QDialog,'exec_',return_value=0):
            window.homeInterface.planRequested.emit()
        self.assertTrue(window.plan_page.start.isEnabled())
        balance=[27]
        def factory(*a,**kw):
            w=MadThread(*a,**kw)
            w.connect=w.to_main_page=Mock()
            w.func_dict['restart']=lambda w:True
            def receive(w):
                balance[0]+=18
                return True
            w.func_dict[reward]=receive
            w.template=Mock(return_value=True)
            w.line=lambda *_:f'{balance[0]}/114'
            return w
        window.plan_runner.worker_factory=factory
        def settle(w,n,cost):
            actual=balance[0]//cost if n=='max' else min(n,balance[0]//cost)
            balance[0]-=actual*cost
            return sweep_utils.SweepBatch(actual,balance[0])
        with patch.object(QMessageBox,'question',return_value=QMessageBox.Yes), \
                patch.object(normal_sweep,'navigate'), patch.object(sweep_utils,'enter'), \
                patch.object(sweep_utils,'select_stage',return_value=True), \
                patch.object(sweep_utils,'start_sweep',side_effect=settle), patch.object(sweep_utils,'return_to_list'):
            window.plan_page.auto.click()
            self.assertIsNotNone(window.worker)
            self.assertTrue(window.worker.join(5))
            app.processEvents()
            rec=store.record(day)
            self.assertEqual(rec['status'],'partial')
            self.assertEqual([(r['instance_id'],r.get('completed')) for r in rec['tasks']],
                             [(normal,2),(reward,None),(tail,2)])
            self.assertEqual(balance[0],5)
            self.assertEqual(rec['remaining'],[normal])
            self.assertIn('有余项',window.homeInterface.plan_summary.text())
            self.assertNotIn(tail,window.routineInterface._results)
            previous=window.worker
            window._tick_plan()
            self.assertIs(window.worker,previous)
            window.plan_page.auto.click()
            self.assertFalse(store.load()['auto'])
            self.assertEqual(window.repository.load_config(),before)
