"""Native Qt workspace retaining the single Main/MadThread execution path."""
from pathlib import Path
from PyQt5.QtCore import QObject, QTimer, QUrl, Qt, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import QMainWindow, QDialog, QVBoxLayout, QMessageBox
from core.config import AppSettingsRepository
from core.tasks import TASKS
from core.plan_store import PlanStore
from core.plan_runner import PlanRunner
from gui.fragments.home import HomeFragment, ACTIVE_STATES
from gui.fragments.settings import SettingsFragment
from gui.fragments.switch import SwitchFragment
from gui.fragments.routine import RoutineFragment
from gui.theme import ThemeManager, apply_typography, typography
from main import Main


class RuntimeSignals(QObject):
    received = pyqtSignal(dict)


class Window(QMainWindow):
    def __init__(self, repository, parent=None):
        super().__init__(parent)
        self.setObjectName('madWorkspace')
        self.repository = repository
        self.app_repository = AppSettingsRepository(repository.data_root / 'config/app.json')
        self.snapshot = repository.load_config()
        self.app_snapshot = self.app_repository.load()
        self.theme = ThemeManager(self.app_snapshot['ui']['theme'], self)
        self._signals = RuntimeSignals(self)
        self._signals.received.connect(self._on_runtime_event, Qt.QueuedConnection)
        self.runtime = Main(repository, self._signals.received.emit)
        self.plan_store = PlanStore(repository)
        self.plan_runner = PlanRunner(self.plan_store, self.runtime, self._signals.received.emit)
        self.plan_dialog = self.plan_page = None
        self.material_dialog = None
        self._plan_auto = False
        self._last_plan_status = None
        self._closing = False
        self._last_run_dir = None
        self._preview_frame = None
        self._material_review_key = None
        self.routineInterface = RoutineFragment(repository, self.theme, self)
        self.homeInterface = HomeFragment(self.theme, self.routineInterface, self)
        self.setCentralWidget(self.homeInterface)
        self.schedulerInterface = SwitchFragment(repository, TASKS, self.theme, self)
        self.settingInterface = SettingsFragment(repository, self.app_repository, self.theme, self)
        self.settings_dialog = self._page_dialog('设置', self.settingInterface, 840)
        self.scheduler_dialog = self._page_dialog('调度', self.schedulerInterface, 920)
        self._fit_initial_size()
        self.theme.changed.connect(self._apply_theme)
        home = self.homeInterface
        home.routineRequested.connect(lambda: self._start())
        home.continuousRequested.connect(lambda: self._start(continuous=True))
        home.newRoutineRequested.connect(lambda: self._start(new_round=True))
        home.stopRequested.connect(self._request_stop)
        home.recordsRequested.connect(self._open_records)
        home.settingsRequested.connect(lambda: self.settings_dialog.exec_())
        home.schedulerRequested.connect(self._show_scheduler)
        home.planRequested.connect(self._show_plan)
        home.previewRequested.connect(self._refresh_preview)
        home.locateRequested.connect(self.routineInterface.open_settings)
        home.recoveryRequested.connect(self._recover_from_home)
        self.routineInterface.dirtyChanged.connect(lambda _: self._refresh_recovery())
        self.routineInterface.saved.connect(lambda c: self._update_profile(c, self.app_snapshot))
        self.routineInterface.materialRequested.connect(lambda key,action:self._show_materials('routine',key,action))
        self.settingInterface.saved.connect(self._update_profile)
        for page in (self.routineInterface, self.schedulerInterface, self.settingInterface):
            page.message.connect(home.on_log_received)
        self._close_timer = QTimer(self)
        self._close_timer.setInterval(100)
        self._close_timer.timeout.connect(self._finish_close)
        # Rendering only: this timer never asks ADB for a frame.
        self._preview_timer = QTimer(self)
        self._preview_timer.setInterval(1000)
        self._preview_timer.timeout.connect(self._refresh_preview)
        self._preview_timer.start()
        self._update_profile(self.snapshot, self.app_snapshot)
        home.on_log_received('INFO', '就绪。开始／继续日常保留原断点和剩余关卡。')
        self._plan_timer = QTimer(self)
        self._plan_timer.setInterval(5000)
        self._plan_timer.timeout.connect(self._tick_plan)
        self._plan_timer.start()

    def showEvent(self,event):
        super().showEvent(event)
        # Only the window admitted by the profile UI lock may recover plan state.
        self._sync_plan_view()
        self._refresh_recovery()

    @property
    def worker(self): return self.runtime.worker

    def _page_dialog(self, title, page, width):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(page)
        available = self.screen().availableGeometry()
        dialog.resize(min(width, available.width()), min(720, available.height()))
        typography(page.title, 18, True)
        typography(page.note, 13)
        return dialog

    def _show_scheduler(self):
        if not self.schedulerInterface.has_unsaved_changes(): self.schedulerInterface.cancel_changes()
        self.scheduler_dialog.exec_()

    def _show_plan(self):
        if self.plan_dialog is None:
            from gui.fragments.plan import PlanFragment
            self.plan_dialog = QDialog(self)
            self.plan_dialog.setWindowTitle('计划 · MADAutoScript')
            layout = QVBoxLayout(self.plan_dialog)
            self.plan_page = PlanFragment(self.plan_store, self.theme, self.plan_dialog)
            layout.addWidget(self.plan_page)
            self.plan_page.saved.connect(self._plan_updated)
            self.plan_page.materialRequested.connect(lambda day,key,action:self._show_materials('plan:'+day,key,action))
            self.plan_page.autoRequested.connect(self._change_plan_auto)
            self.plan_page.startRequested.connect(self._start_plan)
            self.plan_page.resumeRemainingRequested.connect(lambda: self._start_plan(remaining=True))
            self.plan_page.stopTodayRequested.connect(lambda: self._plan_action(self.plan_runner.stop_today))
            self.theme.apply_surface(self.plan_dialog)
            available = self.screen().availableGeometry()
            self.plan_dialog.resize(min(1260,available.width()), min(820,available.height()))
        self.plan_page.refresh()
        self._sync_plan_view()
        self.plan_dialog.exec_()

    def _plan_notice(self, message, error=False):
        if not message: return
        self.homeInterface.on_log_received('WARNING' if error else 'INFO', message)
        if self.plan_page: self.plan_page.set_feedback(message)

    def _show_materials(self, scope, key, action):
        from gui.fragments.materials import MaterialDialog
        editor=self.plan_page.editor if scope.startswith('plan:') else self.routineInterface
        dialog=MaterialDialog(self.repository,self.theme,key,editor.editors[key].value().get('reserve',0),scope,self)
        self.material_dialog=dialog
        dialog.syncRequested.connect(self._sync_materials)
        dialog.stopRequested.connect(self._request_stop)
        dialog.tabs.setCurrentIndex(1 if action=='plan' else 0)
        dialog.set_busy(bool(self.worker and self.worker.is_running))
        available=self.screen().availableGeometry()
        dialog.resize(min(1060,available.width()),min(730,available.height()))
        if action=='sync': QTimer.singleShot(0,dialog.request_sync)
        elif action=='review': QTimer.singleShot(0,dialog.resolve_pending)
        dialog.exec_()
        self.material_dialog=None
        dialog.deleteLater()
        self._refresh_recovery()

    def _sync_materials(self):
        if self.worker and self.worker.is_running: return
        self.homeInterface.begin_run('同步素材数据')
        self._set_state('starting')
        try: self.runtime.sync_materials()
        except Exception as error:
            self._set_state('failed'); self.homeInterface.on_log_received('ERROR',str(error))
            self.homeInterface.show_error(error)
            if self.material_dialog: self.material_dialog.feedback.setText(str(error))

    def _plan_action(self, action):
        try:
            outcome = action()
            self._plan_updated()
            self._plan_notice(self.plan_runner.message, outcome is False)
        except (ValueError, OSError, RuntimeError) as exc:
            self._plan_notice(str(exc), True)

    def _start_plan(self, remaining=False):
        if self.worker and self.worker.is_running:
            self._plan_notice('请先停止正在执行的任务，再开始今日计划。', True)
            return
        try:
            _, status, reason = self.plan_runner.today_status()
            if status == 'needs_review':
                box = QMessageBox(self.plan_dialog or self)
                box.setWindowTitle('核对上次操作')
                box.setText(reason + '\n请先在游戏中核对该步骤的结果。')
                done = box.addButton('已生效，跳过该步骤', QMessageBox.AcceptRole)
                retry = box.addButton('确认未执行，允许重试', QMessageBox.ActionRole)
                cancel = box.addButton('暂不继续', QMessageBox.RejectRole)
                box.setDefaultButton(cancel)
                box.exec_()
                if box.clickedButton() not in (done, retry): return
                self.plan_runner.resolve_current(done=box.clickedButton() == done)
            self._plan_action(lambda: self.plan_runner.start_today(remaining=remaining))
        except (ValueError, OSError, RuntimeError) as exc:
            self._plan_notice(str(exc), True)

    def _change_plan_auto(self, enabled):
        if enabled:
            if self.worker and self.worker.is_running and not self.plan_runner.is_plan_running:
                self._plan_notice('普通日常正在执行，停止后即可启用计划。', True)
                return
            if QMessageBox.question(self.plan_dialog or self, '启用自动执行',
                    self.plan_runner.preview_auto() + '\n保持工作台打开，按此排期自动执行？',
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
        self._plan_action(lambda: self.plan_runner.set_auto(enabled))
        if enabled: self._tick_plan()

    def _plan_updated(self):
        if self.plan_page: self.plan_page.refresh()
        self._sync_plan_view()

    def _sync_plan_view(self):
        if not self.plan_store.path.exists(): return
        try:
            plan = self.plan_store.load()
            day, status, reason = self.plan_runner.today_status()
            self._plan_auto = plan['auto']
            current = plan['days'].get(day, {})
            from gui.fragments.plan import STATUS
            record = self.plan_store.record(day)
            status_text = STATUS.get(status,reason)
            if record.get('auto_skip') and status=='ready': status_text = '今天仅手动执行'
            summary = ' · '.join(filter(None, ('计划自动执行' if self._plan_auto else '手动计划',
                                           day, record.get('name') or current.get('name'), status_text)))
            if status in ('running','stopped','partial','failed','needs_review'):
                rows = [e for e in (record.get('routine') or current.get('routine',{})).get('events',[]) if e['enabled']]
                passed = {key for key,g in record.get('groups',{}).items() if g.get('scheduled')}
                summary += f'　已处理 {sum(e["instance_id"] in passed for e in rows)}/{len(rows)} 条'
                upcoming_step = record.get('inflight') or next((e for e in rows if e['instance_id'] not in passed),{})
                if upcoming_step.get('event_name'): summary += ' · '+upcoming_step['event_name']
            upcoming = next((d for d in sorted(plan['days']) if day < d <= plan['end']
                             and plan['days'][d]['kind'] == 'tasks'), None)
            if upcoming:
                item = plan['days'][upcoming]
                at = item.get('time') or plan['default_time']
                summary += '　|　下次：' + upcoming + ' ' + ('次日 ' if at < plan['reset_at'][:5] else '') + at + ' ' + item.get('name','')
            action = '查看日程' if status in ('unscheduled','rest','ended','completed','partial') else '开始 / 继续今日'
            self.homeInterface.set_plan_summary(summary, self._plan_auto, action)
            if self.plan_page: self.plan_page.set_runtime_status(day,status,reason)
            self._last_plan_status = (day,status,reason)
            self._refresh_recovery()
        except (ValueError, OSError, RuntimeError) as exc:
            self._plan_auto = False
            self.homeInterface.set_plan_summary('计划读取失败：' + str(exc), False)

    def _tick_plan(self):
        if self._closing or not self.isVisible() or not self.plan_store.path.exists(): return
        try:
            if self._plan_auto: self.plan_runner.poll()
            status = self.plan_runner.today_status()
            if status != self._last_plan_status or (self._plan_auto and status[1]=='ended'):
                self._plan_updated()
        except (ValueError, OSError, RuntimeError) as exc:
            self._plan_notice(str(exc), True)

    def _fit_initial_size(self, available=None):
        available = available or self.screen().availableGeometry()
        self.setMinimumSize(min(980, available.width()), min(680, available.height()))
        self.resize(min(1120, available.width()), min(760, available.height()))

    def _apply_theme(self):
        self.theme.apply_surface(self, 'window')
        for dialog in (self.settings_dialog, self.scheduler_dialog, self.plan_dialog):
            if dialog: self.theme.apply_surface(dialog)
        s = self.theme.surfaces
        self.setStyleSheet(f'QMainWindow#madWorkspace {{background:{s["window"]};}} QComboBox {{color:{self.theme.colors["text"]};background:{s["input"]};'
                           f'border:1px solid {s["control"]};border-radius:5px;padding:5px 8px;}} '
                           f'QComboBox QAbstractItemView {{background:{s["input"]};color:{self.theme.colors["text"]};'
                           f'selection-background-color:{s["selected"]};}} '
                           f'QDialog {{background:{s["window"]};color:{self.theme.colors["text"]};}} '
                           f'QDialog QLabel {{color:{self.theme.colors["text"]};}} '
                           f'QListWidget, QMenu {{background:{s["card"]};color:{self.theme.colors["text"]};border:1px solid {s["line"]};}} '
                           f'QListWidget::item, QMenu::item {{padding:6px 10px;}} '
                           f'QListWidget::item:selected, QMenu::item:selected {{background:{s["selected"]};}} '
                           f'QListWidget::item:disabled {{color:{s["muted"]};}} '
                           f'QDialogButtonBox QPushButton {{color:{self.theme.colors["text"]};background:{s["card"]};'
                           f'border:1px solid {s["control"]};border-radius:5px;padding:6px 16px;}}' + self.theme.native_style())
        apply_typography(self)

    @pyqtSlot(dict, dict)
    def _update_profile(self, config, app):
        self.snapshot, self.app_snapshot = config, app
        self.homeInterface.set_profile(config)
        self.setWindowTitle('MADAutoScript · ' + config['display_name'])
        self.theme.apply(app['ui']['theme'])
        self.settingInterface.sync_profile(config)
        self.routineInterface.sync_profile(config)

    def _set_state(self, state):
        self.homeInterface.set_state(state)
        for page in (self.routineInterface, self.settingInterface, self.schedulerInterface):
            page.set_busy(state in ACTIVE_STATES)
        if self.material_dialog: self.material_dialog.set_busy(state in ACTIVE_STATES)

    def _start(self, continuous=False, new_round=False):
        if self.worker and self.worker.is_running: return
        if self._plan_auto:
            if continuous or new_round:
                self._plan_notice('请先暂停计划的自动执行，再运行普通日常。', True)
                return
            self._show_plan()
            return
        self._refresh_recovery()
        if self._material_review_key:
            self._recover_from_home()
            return
        for page, dialog in ((self.settingInterface, self.settings_dialog), (self.schedulerInterface, self.scheduler_dialog)):
            if page.has_unsaved_changes():
                self.homeInterface.on_log_received('WARNING', '设置或调度中有未保存的更改，请先保存或撤销。')
                dialog.exec_()
                return
        if new_round and QMessageBox.question(self, '开始新一轮',
                ('将先保存当前任务更改。\n' if self.routineInterface.has_unsaved_changes() else '') +
                '将开始完整的新一轮，已完成的指令也可能再次执行；扫荡次数按当前计划重建。继续？',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        if self.routineInterface.has_unsaved_changes() and not self.routineInterface.save_changes(): return
        self.homeInterface.begin_run('持续运行' if continuous else '普通日常')
        self._set_state('starting')
        try:
            self.runtime.start(continuous, new_round=new_round)
        except Exception as error:
            self._set_state('failed')
            self.homeInterface.on_log_received('ERROR', str(error))
            self.homeInterface.show_error(error)

    def _refresh_recovery(self):
        """Expose existing review paths only for the affected execution context."""
        from core.material_store import MaterialStore, TASK
        self._material_review_key = None
        try:
            pending = MaterialStore(self.repository).state()['pending']
            if pending and pending['phase'] == 'confirming':
                enabled = [e['instance_id'] for e in self.routineInterface._queue
                           if e['func_name'] == TASK and e['enabled']]
                if enabled:
                    self._material_review_key = pending['instance'] if pending['instance'] in enabled else enabled[0]
        except (ValueError, OSError, KeyError) as error:
            self.homeInterface.on_log_received('ERROR', '素材状态读取失败：' + str(error))
        plan_review = self._last_plan_status and self._last_plan_status[1] == 'needs_review'
        self.homeInterface.set_recovery('plan' if plan_review and (
            self._plan_auto or self.homeInterface._plan_date == self._last_plan_status[0]) else
            'material' if self._material_review_key else '')

    def _recover_from_home(self):
        if self.worker and self.worker.is_running: return
        if self.homeInterface._recovery == 'plan':
            self._show_plan()  # Existing calendar review owns its frozen checkpoint.
        elif self._material_review_key in self.routineInterface.editors:
            self._show_materials('routine', self._material_review_key, 'review')

    def _display_tasks(self, event):
        tasks = [dict(item) for item in event.get('result', {}).get('tasks', [])]
        # A later material instruction can satisfy an earlier instruction's goals.
        # Reflect the existing final inventory meaning without altering receipts.
        from core.material_store import MaterialStore
        store = MaterialStore(self.repository)
        for item in tasks:
            if item.get('task_id') == 'mad.material_sweep' and item.get('status') == 'PARTIAL' and item.get('material_context'):
                round_ = store.state()['rounds'].get(item['material_context'])
                if round_ and not store.remaining(round_['snapshot']):
                    item.update(status='SUCCESS', reason='共享素材目标已达成。')
        return tasks

    def _request_stop(self):
        if self.worker:
            if not self._closing and self.plan_runner.is_plan_running:
                self.plan_runner.stop_today()
            else: self.worker.request_stop()
            self._set_state('stopping')

    def _refresh_preview(self):
        if not self.homeInterface.preview_toggle.isChecked() or not self.worker: return
        frame = self.worker.latest_ui_frame
        if frame is not None and frame is not self._preview_frame:
            self._preview_frame = frame
            self.homeInterface.show_frame(*frame)

    @pyqtSlot(dict)
    def _on_runtime_event(self, event):
        is_plan = bool(event.get('plan_date'))
        if not is_plan and not event.get('material_sync'): self.routineInterface.on_event(event)
        self.homeInterface.on_runtime_event(event, self._display_tasks(event) if event['kind'] == 'result' else None)
        self.homeInterface.on_device_event(event)
        if event.get('message'):
            self.homeInterface.on_log_received(event.get('level', 'INFO'), event['message'], event['kind'] != 'log')
        if event['kind'] == 'state': self._set_state(event['state'])
        elif event['kind'] == 'result':
            self._last_run_dir = event['result'].get('run_dir')
            self._set_state(event['state'])
            if self.material_dialog:
                self.material_dialog.refreshed()
                error=(event['result'].get('error') or '').strip()
                self.material_dialog.feedback.setText(error.splitlines()[-1] if error else
                    '同步完成，已刷新库存和目标表。' if event.get('material_sync') and event['state']=='succeeded' else event.get('message','任务已结束。'))
            unfinished = {} if is_plan else self.repository.load_config()['unfinished_tasks']
            handled = {item.get('instance_id',item['task_id']) for item in event['result'].get('tasks', [])}
            remaining = sum(len(unfinished.get(task, [])) for task in handled)
            if remaining:
                self.homeInterface.on_log_received('INFO', f'本次执行的任务还有 {remaining} 个关卡保留待续。')
            self._refresh_recovery()
        if is_plan and event['kind'] in ('task','result'):
            self._plan_updated()
        if self._closing: self._finish_close()

    def _open_records(self):
        path = Path(self._last_run_dir) if self._last_run_dir else self.repository.data_root / 'runs'
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def closeEvent(self, event):
        if self.worker and not self.worker.join(0):
            self._closing = True
            self._request_stop()
            self._close_timer.start()
            event.ignore()
            return
        self._close_timer.stop()
        self._preview_timer.stop()
        self._plan_timer.stop()
        self.runtime.close()
        event.accept()

    def _finish_close(self):
        if self._closing and (not self.worker or self.worker.join(0)):
            self._close_timer.stop()
            self.close()
