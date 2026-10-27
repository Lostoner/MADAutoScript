"""UI-only acceptance; isolated profile, no ADB or game actions."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch, Mock
import json
from core.paths import REPO_ROOT


class WorkspaceAcceptance(TestCase):
    def setUp(self):
        from main import create_window
        self.tmp = TemporaryDirectory(prefix='mad-workspace-')
        self.root = Path(self.tmp.name)
        self.app, self.window = create_window(self.root)
        type(self).qt_app = self.app  # Qt/Fluent keep one QApplication for the test process.
        self.page = self.window.routineInterface
        self.repo = self.window.repository

    def tearDown(self):
        self.window.runtime.worker = None
        self.window.close()
        self.app.processEvents()
        self.tmp.cleanup()

    def test_inline_edit_undo_and_save_before_start(self):
        from PyQt5.QtCore import Qt
        from PyQt5.QtTest import QTest
        p, w = self.page, self.window
        baseline = self.repo.load_config()
        events = self.repo.load_events()
        selector = p.sweep_selectors['mad.normal_sweep']
        old = selector.value()
        new_key = next(k for k in selector.options if k not in selector._order)
        selector.add_stages([new_key])
        selector.rows[new_key][2].setValue(1000)
        selector.edit_order(new_key, -1)
        self.assertEqual(selector.value()[-2], {'stage_id': new_key, 'count': 1000})
        self.assertIn('1000', p.cards['mad.normal_sweep'].summary.full_text)
        p.drop_task('mad.mail', 'mad.normal_sweep', True)
        self.assertTrue(p.has_unsaved_changes())
        QTest.mouseClick(p.cancel_button, Qt.LeftButton)
        self.assertEqual(selector.value(), old)
        self.assertEqual(self.repo.load_config(), baseline)
        self.assertEqual(self.repo.load_events(), events)

        # Failed save must keep the draft and must not start the worker.
        p.mail.setChecked(not p.mail.isChecked())
        with patch.object(self.repo, 'save_events', side_effect=ValueError('fixture error')), patch.object(w.runtime, 'start') as start:
            QTest.mouseClick(w.homeInterface.routine_button, Qt.LeftButton)
            start.assert_not_called()
        self.assertTrue(p.has_unsaved_changes())
        self.assertIn('fixture error', p.feedback.text())
        self.assertEqual(w.homeInterface.routine_button.text(), '保存并开始')

        # Saving queue changes preserves worker-owned progress and next_tick.
        with patch.object(w.runtime, 'start') as start:
            QTest.mouseClick(w.homeInterface.routine_button, Qt.LeftButton)
            start.assert_called_once_with(False, new_round=False)
        self.assertFalse(p.has_unsaved_changes())
        self.assertEqual(self.repo.load_config()['unfinished_tasks'], baseline['unfinished_tasks'])
        self.assertEqual([e['next_tick'] for e in self.repo.load_events()], [e['next_tick'] for e in events])
        self.assertFalse(p.mail.isEnabled())
        before_order = deepcopy(p._queue)
        p.move_task('mad.mail', -1)
        self.assertEqual(p._queue, before_order)
        p.open_settings('mad.normal_sweep')
        self.assertFalse(selector.isEnabled())
        worker = Mock(is_running=True, latest_ui_frame=None)
        w.runtime.worker = worker
        QTest.mouseClick(w.homeInterface.routine_button, Qt.LeftButton)
        worker.request_stop.assert_called_once()
        self.assertEqual(w.homeInterface.state, 'stopping')
        self.assertFalse(w.homeInterface.routine_button.isEnabled())
        w._on_runtime_event({'kind': 'state', 'state': 'stopped'})
        self.assertTrue(p.mail.isEnabled())

    def test_results_logs_and_preview_use_existing_runtime(self):
        import numpy as np
        from datetime import datetime
        w, p = self.window, self.page
        w._on_runtime_event({'kind': 'task', 'task_id': 'mad.normal_sweep', 'state': 'running', 'message': '执行 普通扫荡'})
        self.assertTrue(p.cards['mad.normal_sweep'].property('active'))
        w._on_runtime_event({'kind': 'log', 'message': 'Image feature: normal_stage -> click', 'level': 'INFO'})
        self.assertNotIn('Image feature', w.homeInterface.logger_box.toPlainText())
        w.homeInterface.log_mode.setCurrentIndex(1)
        self.assertIn('Image feature', w.homeInterface.logger_box.toPlainText())
        result = {'tasks': [{'task_id': 'mad.normal_sweep', 'status': 'PARTIAL',
                            'remaining': [{'stage_id': 'normal:4-1', 'count': 7}]}]}
        w._on_runtime_event({'kind': 'result', 'state': 'succeeded', 'result': result})
        self.assertEqual(p.cards['mad.normal_sweep'].result.text(), '待续 · 剩余 7 次')
        self.assertFalse(p.cards['mad.normal_sweep'].property('active'))
        for state, text in [('failed', '未完成'), ('stopped', '已停止')]:
            w._on_runtime_event({'kind': 'task', 'task_id': 'mad.mail', 'state': 'running', 'message': '邮箱领取'})
            w._on_runtime_event({'kind': 'result', 'state': state, 'result': {'tasks': [], 'error': 'fixture error'}})
            self.assertEqual(p.cards['mad.mail'].result.text(), text)
        worker = Mock(latest_ui_frame=(np.zeros((720, 1280, 3), dtype=np.uint8), datetime.now()))
        w.runtime.worker = worker
        w.homeInterface.preview_toggle.setChecked(True)
        self.assertFalse(w.homeInterface.preview_image.pixmap().isNull())
        worker.update_screenshot_array.assert_not_called()
        w.homeInterface.preview_toggle.setChecked(False)

    def test_skipped_and_partial_sweeps_keep_reasons_in_brief_log(self):
        from core.Mad_thread import MadThread
        from module import sweep_utils
        routine=deepcopy(self.repo.load_config()['routine'])
        routine['normal_sweep']['plans']=[{'stage_id':'normal:4-5','count':2}]
        self.repo.patch_config({'routine':routine})
        self.repo.set_unfinished('mad.normal_sweep',[])
        self.repo.set_unfinished('mad.flara_sweep',[{'stage_id':'flara:热情的锻炼场:1','count':6}])
        self.repo.save_events([{'func_name':e['func_name'],'enabled':e['func_name']=='mad.normal_sweep'}
                              for e in self.repo.load_events()],fields={'enabled'})
        worker=MadThread(self.repo,self.window._on_runtime_event)
        worker.connect=Mock()
        worker.to_main_page=Mock()
        worker.func_dict['restart']=Mock(return_value=True)
        worker.template=Mock(return_value=True)
        self.window.runtime.worker=worker
        def run():
            worker.flag_run=True
            worker.thread_starter()
            self.assertIsNone(worker.last_result['error'])
            return worker.last_result['tasks'][0]
        with patch.object(sweep_utils,'enter') as enter:
            result=run()
        enter.assert_not_called()
        self.assertEqual(result['status'],'SKIPPED')
        self.assertEqual(result['completed'],0)
        self.assertEqual(worker.last_result['device_actions'],0)
        self.assertEqual(self.page.cards['mad.normal_sweep'].result.text(),'已跳过')
        reason=result['reason']
        for mode in (0,1,0):
            self.window.homeInterface.log_mode.setCurrentIndex(mode)
            self.assertEqual(self.window.homeInterface.logger_box.toPlainText().count(reason),1)
            self.assertNotIn('个关卡保留待续',self.window.homeInterface.logger_box.toPlainText())

        self.repo.reset_progress()
        with patch('module.normal_sweep.navigate'), patch.object(sweep_utils,'enter'), patch.object(sweep_utils,'select_stage',return_value=True), \
             patch.object(sweep_utils,'start_sweep',return_value=(False,0)):
            result=run()
        self.assertEqual(result['status'],'PARTIAL')
        self.assertEqual(result['completed'],0)
        self.assertEqual(self.page.cards['mad.normal_sweep'].result.text(),'待续 · 剩余 2 次')
        self.assertIn(result['reason'],self.window.homeInterface.logger_box.toPlainText())
        with patch('module.normal_sweep.navigate'), patch.object(sweep_utils,'enter'), patch.object(sweep_utils,'select_stage',return_value=True), \
             patch.object(sweep_utils,'start_sweep',return_value=(True,2)), patch.object(sweep_utils,'return_to_list'):
            result=run()
        self.assertEqual(result['status'],'SUCCESS')
        self.assertEqual(result['completed'],2)
        self.assertEqual(self.page.cards['mad.normal_sweep'].result.text(),'完成')

        routine['normal_sweep']['plans']=[]
        self.repo.patch_config({'routine':routine})
        with patch.object(sweep_utils,'enter') as enter:
            result=run()
        enter.assert_not_called()
        self.assertEqual(result['status'],'SKIPPED')
        self.assertIn('未配置关卡',result['reason'])
        self.assertIn(result['reason'],self.window.homeInterface.logger_box.toPlainText())
