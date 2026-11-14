"""Stage A acceptance: real Qt controls and existing worker, isolated storage, no ADB."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from PyQt5.QtCore import Qt, QPoint, QRect
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QMessageBox, QDialog
from main import create_window


class DailyWorkspaceStageA(TestCase):
    windows = []

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.app, self.w = create_window(Path(self.tmp.name))
        type(self).app = self.app
        type(self).windows.append(self.w)
        self.w._plan_timer.stop()
        self.w._preview_timer.stop()
        self.p, self.h = self.w.routineInterface, self.w.homeInterface
        self.repo = self.w.repository
        self.w._fit_initial_size(QRect(0,0,1920,1080))
        self.w.show()
        self.app.processEvents()

    def tearDown(self):
        self.w.runtime.worker = None
        self.w.close()
        self.app.processEvents()
        self.tmp.cleanup()

    def event(self, kind, **fields):
        self.w._on_runtime_event(dict(kind=kind, **fields))

    def test_failure_keeps_exact_instance_and_full_details_without_wall_of_traceback(self):
        key = self.p.add_instance('mad.normal_sweep', 'mad.normal_sweep')
        self.p.rename_instance(key, '领奖后尾扫')
        self.p.save_changes()
        self.p.cards[key].set_expanded(False)
        self.event('state', state='starting')
        self.event('task', state='running', task_id='mad.normal_sweep', instance_id=key, event_name='领奖后尾扫')
        error = 'Traceback (most recent call last):\n  File "sweep_utils.py", line 51\nRuntimeError: 关卡列表未找到 NORMAL 5-1'
        self.event('log', level='ERROR', message=error)
        self.event('result', state='failed', result={'tasks': [], 'error': error})
        self.event('state', state='failed')  # Actual worker emits both; keep the reason.
        self.assertEqual(self.h.current_label.text(), '领奖后尾扫')
        self.assertEqual(self.h.reason_label.text(), 'RuntimeError: 关卡列表未找到 NORMAL 5-1')
        self.assertEqual(self.h.routine_button.text(), '继续本轮')
        self.assertTrue(self.h.log_panel.isHidden())
        self.assertNotIn('File "sweep_utils.py"', self.h.logger_box.toPlainText())
        self.h.locate_button.click()
        self.assertTrue(self.p.cards[key].expand.isChecked())
        self.assertFalse(self.p.cards['mad.normal_sweep'].expand.isChecked())
        self.h.log_mode.setCurrentIndex(1)
        self.assertIn('File "sweep_utils.py"', self.h.logger_box.toPlainText())
        clipboard = Mock()
        with patch.object(QApplication, 'clipboard', return_value=clipboard): self.h._copy_logs()
        self.assertIn(error, clipboard.setText.call_args.args[0])

    def test_six_of_ten_sweeps_continue_next_task_and_report_four_remaining(self):
        from core.Mad_thread import MadThread
        from module import normal_sweep, sweep_utils
        config = self.repo.load_config()
        routine = deepcopy(config['routine'])
        routine['normal_sweep']['plans'] = [{'stage_id': 'normal:4-1', 'count': 10}]
        self.repo.patch_config({'routine': routine})
        self.repo.save_events([{'instance_id': e['instance_id'], 'func_name': e['func_name'],
                              'enabled': e['func_name'] in ('mad.normal_sweep', 'mad.mail')}
                             for e in self.repo.load_events()], fields={'enabled'})
        balance = [60]
        worker = MadThread(self.repo, self.w._on_runtime_event)
        worker.connect = worker.to_main_page = Mock()
        worker.func_dict['restart'] = Mock(return_value=True)
        worker.func_dict['mad.mail'] = Mock(return_value=True)
        worker.line = lambda *_: f'{balance[0]}/114'
        worker.template = Mock(return_value=True)
        self.w.runtime.worker = worker
        def settle(w, count, cost):
            actual = min(count, balance[0] // cost)
            balance[0] -= actual * cost
            return sweep_utils.SweepBatch(actual, balance[0])
        with patch.object(normal_sweep, 'navigate'), patch.object(sweep_utils, 'enter'), \
             patch.object(sweep_utils, 'select_stage', return_value=True), \
             patch.object(sweep_utils, 'start_sweep', side_effect=settle) as sweep, \
             patch.object(sweep_utils, 'return_to_list'):
            worker.flag_run = True
            worker.thread_starter()
        self.assertIsNone(worker.last_result['error'])
        self.assertEqual(sweep.call_count, 1)
        worker.func_dict['mad.mail'].assert_called_once()
        self.assertEqual(self.repo.load_config()['unfinished_tasks']['mad.normal_sweep'], [{'stage_id': 'normal:4-1', 'count': 4}])
        self.assertEqual(self.h.status_label.text(), '本轮结束 · 有余项')
        self.assertIn('本次完成 6 次，剩余 4 次', self.h.reason_label.text())
        self.assertEqual(self.p.cards['mad.mail'].result.text(), '已完成')
        self.assertEqual(worker.last_result['device_actions'], 0)

    def test_plan_entry_and_sync_keep_their_execution_context(self):
        self.w._plan_auto = True
        self.h.set_plan_summary('今天已安排', True)
        with patch.object(QDialog, 'exec_', return_value=0), patch.object(self.w, '_start_plan') as start_plan, \
             patch.object(self.w.runtime, 'start') as start:
            self.h.routine_button.click()
            self.assertIsNotNone(self.w.plan_page)
            start.assert_not_called()
            start_plan.assert_not_called()
        self.w._plan_auto = False
        self.h.set_plan_summary('', False)
        self.event('state', state='starting', plan_date='2099-01-01')
        self.event('task', state='running', task_id='mad.mail', instance_id='plan-mail', event_name='计划邮箱', plan_date='2099-01-01')
        self.assertIn('2099-01-01', self.h.source_label.text())
        self.assertNotIn('plan-mail', self.p._results)
        self.event('result', state='failed', material_sync=True, result={'tasks': [], 'error': '库存读取失败'})
        self.assertIn('同步素材数据', self.h.source_label.text())
        self.assertEqual(self.h.routine_button.text(), '开始／继续日常')
        self.assertNotIn('plan-mail', self.p._results)

    def test_unknown_material_batch_uses_existing_review_and_does_not_block_other_tasks(self):
        from core.material_store import MaterialStore, TASK
        store = MaterialStore(self.repo)
        store.save_targets([{'ref': 'item:80201', 'amount': 20}])
        store.freeze('test-round')
        store.prepare_batch('test-round', TASK, 'normal:4-1', 1, ['item:80201'])
        self.p.cards[TASK].check.setChecked(True)
        self.w._refresh_recovery()
        self.assertEqual(self.h.routine_button.text(), '核对素材结果')
        with patch.object(self.w, '_show_materials') as review, patch.object(self.w.runtime, 'start') as start:
            self.h.routine_button.click()
            review.assert_called_once_with('routine', TASK, 'review')
            start.assert_not_called()
            self.assertEqual(store.state()['pending']['phase'], 'confirming')
            self.p.cards[TASK].check.setChecked(False)
            self.h.routine_button.click()
            start.assert_called_once_with(False, new_round=False)
        self.assertEqual(store.state()['pending']['phase'], 'confirming')

    def test_new_round_is_explicit_and_start_failure_can_be_read(self):
        before = deepcopy(self.repo.load_config())
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.No), patch.object(self.w.runtime, 'start') as start:
            self.w._start(new_round=True)
            start.assert_not_called()
        self.assertEqual(self.repo.load_config(), before)
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes), patch.object(self.w.runtime, 'start', side_effect=RuntimeError('配置已被其他窗口占用')) as start:
            self.w._start(new_round=True)
            start.assert_called_once_with(False, new_round=True)
        self.assertEqual(self.h.reason_label.text(), '配置已被其他窗口占用')
        self.assertEqual(self.h.state, 'failed')
        self.assertTrue(self.h.routine_button.isEnabled())

    def test_plan_unknown_consumption_routes_to_calendar_without_replaying(self):
        from core.Mad_thread import MadThread
        store = self.w.plan_store
        plan, day = store.load(), store.today()
        spec = store.from_daily()
        for row in spec['events']: row['enabled'] = row['func_name'] == 'mad.normal_sweep'
        plan['days'][day] = {'kind':'tasks', 'name':'核对样例', 'routine':spec}
        store.save(plan)
        def factory(*args, **kwargs):
            worker = MadThread(*args, **kwargs)
            worker.connect = Mock()
            worker.func_dict['restart'] = Mock(return_value=True)
            worker.func_dict['mad.normal_sweep'] = Mock(side_effect=RuntimeError('确认后画面中断'))
            return worker
        self.w.plan_runner.worker_factory = factory
        self.assertTrue(self.w.plan_runner.start_today())
        self.assertTrue(self.w.worker.join(5))
        self.app.processEvents()
        self.assertEqual(store.record(day)['status'], 'needs_review')
        self.assertEqual(self.h.status_label.text(), '今日计划待核对')
        with patch.object(QDialog, 'exec_', return_value=0), patch.object(self.w.plan_runner, 'start_today') as start:
            self.h.recovery_button.click()
            start.assert_not_called()
        self.assertEqual(self.w.plan_page.start.text(), '核对并继续今日')
        with patch.object(QMessageBox, 'exec_', return_value=0), patch.object(self.w.plan_runner, 'start_today') as start:
            self.w._start_plan()
            start.assert_not_called()
        self.assertEqual(store.record(day)['status'], 'needs_review')
        self.assertEqual(self.w.worker.last_result['device_actions'], 0)

    def test_later_material_completion_clears_stale_partial_without_editing_receipts(self):
        from core.material_store import MaterialStore, TASK
        store = MaterialStore(self.repo)
        store.save_targets([{'ref':'item:80201', 'amount':20}])
        snapshot = store.freeze('sample-round')
        store.observe({'inventory':{'item:80201':20}, 'source':'game', 'at':1}, snapshot)
        tasks = [{'task_id':TASK, 'instance_id':TASK, 'event_name':'首扫',
                  'status':'PARTIAL', 'material_context':'sample-round', 'reason':'当时尚未达标'},
                 {'task_id':TASK, 'instance_id':'tail', 'event_name':'尾扫',
                  'status':'SUCCESS', 'material_context':'sample-round'}]
        self.event('result', state='succeeded', result={'tasks':tasks})
        self.assertEqual(self.h.status_label.text(), '本轮结束')
        self.assertEqual(self.p.cards[TASK].result.text(), '已完成')
        self.assertEqual(tasks[0]['status'], 'PARTIAL')

    def test_log_reading_keyboard_and_small_window_preserve_controls(self):
        self.h.log_toggle.setChecked(True)
        for i in range(70): self.h.on_log_received('INFO', '步骤 '+str(i))
        self.app.processEvents()
        bar = self.h.logger_box.verticalScrollBar()
        self.assertGreater(bar.maximum(), 0)
        bar.setValue(0)
        self.h.on_log_received('ERROR', '新的错误')
        self.assertEqual(bar.value(), 0)
        self.assertFalse(self.h.latest_button.isHidden())
        self.h.latest_button.click()
        self.assertEqual(bar.value(), bar.maximum())
        card = self.p.cards['mad.mail']
        self.p.ensureWidgetVisible(card)
        card.setFocus()
        QTest.keyClick(card, Qt.Key_Space)
        self.assertTrue(card.expand.isChecked())
        before = [e['instance_id'] for e in self.p._queue]
        QTest.keyClick(card, Qt.Key_Up, Qt.AltModifier)
        after = [e['instance_id'] for e in self.p._queue]
        self.assertEqual(after.index('mad.mail'), before.index('mad.mail')-1)
        # Enter in a parameter editor must not bubble up and collapse the row.
        sweep_card = self.p.cards['mad.normal_sweep']
        self.p.open_settings('mad.normal_sweep')
        selector = self.p.sweep_selectors['mad.normal_sweep']
        field = selector.rows[selector.value()[0]['stage_id']][2].lineEdit()
        field.setFocus()
        self.app.processEvents()
        QTest.keyClick(field, Qt.Key_Return)
        self.assertTrue(sweep_card.expand.isChecked())
        for theme in ('light', 'dark', 'system'):
            self.w.theme.apply(theme)
            self.w.resize(980,680); self.app.processEvents()
            self.assertEqual((self.w.width(),self.w.height()),(980,680))
            self.assertTrue(self.w.rect().contains(self.h.routine_button.mapTo(self.w,self.h.routine_button.rect().bottomRight())))
            image = self.h.run_content.grab().toImage()
            self.assertEqual(image.pixelColor(image.width()-2,image.height()-2).name().lower(), self.w.theme.surfaces['card'].lower())
        self.w._fit_initial_size(QRect(0,0,800,600)); self.app.processEvents()
        self.assertTrue(self.h._compact)
        self.assertTrue(self.h.routine_button.isVisible())
        self.h.set_state('running')
        self.assertEqual(self.h.routine_button.text(), '停止')
        self.assertTrue(self.w.rect().contains(self.h.routine_button.mapTo(self.w,QPoint(0,0))))
        self.h.show_error('未找到 NORMAL 5-1')
        self.h.set_state('failed')
        self.assertIn('未找到 NORMAL 5-1', self.h.compact_status.text())
