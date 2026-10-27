"""Native Qt workspace retaining the single Main/MadThread execution path."""
from pathlib import Path
from PyQt5.QtCore import QObject, QTimer, QUrl, Qt, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import QMainWindow, QDialog, QVBoxLayout
from core.config import AppSettingsRepository
from core.tasks import TASKS
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
        self._closing = False
        self._last_run_dir = None
        self._preview_frame = None
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
        home.previewRequested.connect(self._refresh_preview)
        self.routineInterface.saved.connect(lambda c: self._update_profile(c, self.app_snapshot))
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
        home.on_log_received('INFO', '就绪。开始 / 继续将保留本轮剩余关卡。')

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

    def _fit_initial_size(self, available=None):
        available = available or self.screen().availableGeometry()
        self.setMinimumSize(min(980, available.width()), min(680, available.height()))
        self.resize(min(1120, available.width()), min(760, available.height()))

    def _apply_theme(self):
        self.theme.apply_surface(self, 'window')
        for dialog in (self.settings_dialog, self.scheduler_dialog): self.theme.apply_surface(dialog)
        s = self.theme.surfaces
        self.setStyleSheet(f'QMainWindow#madWorkspace {{background:{s["window"]};}} QComboBox {{color:{self.theme.colors["text"]};background:{s["input"]};'
                           f'border:1px solid {s["line"]};border-radius:5px;padding:5px 8px;}} '
                           f'QComboBox QAbstractItemView {{background:{s["input"]};color:{self.theme.colors["text"]};'
                           f'selection-background-color:{s["selected"]};}} '
                           f'QDialog {{background:{s["window"]};color:{self.theme.colors["text"]};}} '
                           f'QDialog QLabel {{color:{self.theme.colors["text"]};}} '
                           f'QListWidget, QMenu {{background:{s["card"]};color:{self.theme.colors["text"]};border:1px solid {s["line"]};}} '
                           f'QListWidget::item, QMenu::item {{padding:6px 10px;}} '
                           f'QListWidget::item:selected, QMenu::item:selected {{background:{s["selected"]};}} '
                           f'QListWidget::item:disabled {{color:{s["muted"]};}} '
                           f'QDialogButtonBox QPushButton {{color:{self.theme.colors["text"]};background:{s["card"]};'
                           f'border:1px solid {s["line"]};border-radius:5px;padding:6px 16px;}}')
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

    def _start(self, continuous=False, new_round=False):
        if self.worker and self.worker.is_running: return
        for page, dialog in ((self.settingInterface, self.settings_dialog), (self.schedulerInterface, self.scheduler_dialog)):
            if page.has_unsaved_changes():
                self.homeInterface.on_log_received('WARNING', '设置或调度中有未保存的更改，请先保存或撤销。')
                dialog.exec_()
                return
        if self.routineInterface.has_unsaved_changes() and not self.routineInterface.save_changes(): return
        self._set_state('starting')
        try:
            self.runtime.start(continuous, new_round=new_round)
        except Exception as error:
            self._set_state('failed')
            self.homeInterface.on_log_received('ERROR', str(error))

    def _request_stop(self):
        if self.worker:
            self.worker.request_stop()
            self._set_state('stopping')

    def _refresh_preview(self):
        if not self.homeInterface.preview_toggle.isChecked() or not self.worker: return
        frame = self.worker.latest_ui_frame
        if frame is not None and frame is not self._preview_frame:
            self._preview_frame = frame
            self.homeInterface.show_frame(*frame)

    @pyqtSlot(dict)
    def _on_runtime_event(self, event):
        self.routineInterface.on_event(event)
        self.homeInterface.on_device_event(event)
        if event.get('message'):
            self.homeInterface.on_log_received(event.get('level', 'INFO'), event['message'], event['kind'] != 'log')
        if event['kind'] == 'state': self._set_state(event['state'])
        elif event['kind'] == 'task' and event['state'] == 'running':
            self.homeInterface.set_current_task(event['message'])
        elif event['kind'] == 'result':
            self._last_run_dir = event['result'].get('run_dir')
            self._set_state(event['state'])
            remaining = sum(len(v) for v in self.repository.load_config()['unfinished_tasks'].values())
            message = f'本轮结束，{remaining} 个关卡保留待续。' if remaining else '本轮结束。'
            self.homeInterface.on_log_received('INFO', message)
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
        self.runtime.close()
        event.accept()

    def _finish_close(self):
        if self._closing and (not self.worker or self.worker.join(0)):
            self._close_timer.stop()
            self.close()
