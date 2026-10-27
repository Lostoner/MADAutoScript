"""Compact Qt workspace: ordered tasks beside connection, preview and log."""
import html
from collections import deque
from datetime import datetime
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QSplitter, QMenu, QToolButton, QComboBox
from qfluentwidgets import PrimaryPushButton, PushButton, TextEdit
from gui.theme import typography, apply_typography

STATE_TEXT = {'idle': '待机', 'starting': '正在连接', 'running': '运行中', 'waiting': '等待到期任务',
              'stopping': '正在停止', 'stopped': '已停止', 'succeeded': '本轮结束', 'failed': '执行失败'}
ACTIVE_STATES = {'starting', 'running', 'waiting', 'stopping'}


class HomeFragment(QFrame):
    routineRequested = pyqtSignal()
    continuousRequested = pyqtSignal()
    newRoutineRequested = pyqtSignal()
    stopRequested = pyqtSignal()
    recordsRequested = pyqtSignal()
    settingsRequested = pyqtSignal()
    schedulerRequested = pyqtSignal()
    previewRequested = pyqtSignal()

    def __init__(self, theme, routine, parent=None):
        super().__init__(parent)
        self.setObjectName('homeInterface')
        self.theme, self.routine = theme, routine
        self.state, self.dirty = 'idle', False
        self.entries = deque(maxlen=2000)
        self._pixmap = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(12)
        header = QHBoxLayout()
        self.profile_label = typography(QLabel('', self), 14, True)
        header.addWidget(self.profile_label)
        self.edition_label = typography(QLabel('ONEstore · MuMu', self), 12)
        header.addWidget(self.edition_label)
        header.addStretch()
        for name, signal in [('运行记录', self.recordsRequested), ('调度', self.schedulerRequested), ('设置', self.settingsRequested)]:
            button = PushButton(name, self)
            button.setFixedHeight(32)
            button.clicked.connect(signal)
            header.addWidget(button)
        layout.addLayout(header)
        self.splitter = QSplitter(Qt.Horizontal, self)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(12)
        left = QFrame(self.splitter)
        left.setMinimumWidth(590)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)
        task_header = QHBoxLayout()
        self.task_count = typography(QLabel('', left), 12)
        task_header.addWidget(self.task_count)
        task_header.addStretch()
        self.hint = typography(QLabel('拖动排序 · 点击展开参数', left), 12)
        task_header.addWidget(self.hint)
        left_layout.addLayout(task_header)
        left_layout.addWidget(routine, 1)
        footer = QHBoxLayout()
        for button in (routine.save_button, routine.cancel_button): footer.addWidget(button)
        footer.addWidget(routine.feedback, 1)
        self.routine_button = PrimaryPushButton('开始 / 继续', left)
        self.routine_button.setObjectName('routineRunButton')
        self.routine_button.setMinimumSize(124, 36)
        typography(self.routine_button, 14, True)
        self.routine_button.clicked.connect(self._primary)
        footer.addWidget(self.routine_button)
        self.more_button = QToolButton(left)
        self.more_button.setText('⋯')
        self.more_button.setFixedSize(30, 36)
        self.more_button.setToolTip('其他运行方式')
        self.more_button.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self.more_button)
        self.continuous_action = menu.addAction('持续运行', self.continuousRequested.emit)
        self.new_routine_action = menu.addAction('开始新一轮（重新建立完整计划）', self.newRoutineRequested.emit)
        self.more_button.setMenu(menu)
        footer.addWidget(self.more_button)
        left_layout.addLayout(footer)
        self.side = QFrame(self.splitter)
        self.side.setMinimumWidth(280)
        side_layout = QVBoxLayout(self.side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(10)
        self.connection_panel, connection = self._panel(self.side)
        title_row = QHBoxLayout()
        title_row.addWidget(typography(QLabel('连接', self.side), 14, True))
        title_row.addStretch()
        self.status_label = typography(QLabel('待机', self.side), 12)
        title_row.addWidget(self.status_label)
        connection.addLayout(title_row)
        self.device_label = typography(QLabel('尚未连接 · 开始时自动连接', self.side), 13)
        self.device_label.setWordWrap(True)
        connection.addWidget(self.device_label)
        self.current_label = typography(QLabel('暂无运行中的任务', self.side), 12)
        self.current_label.setWordWrap(True)
        connection.addWidget(self.current_label)
        side_layout.addWidget(self.connection_panel)
        self.preview_panel, preview = self._panel(self.side)
        self.preview_toggle = PushButton('最近画面  ⌄', self.preview_panel)
        self.preview_toggle.setCheckable(True)
        self.preview_toggle.toggled.connect(self._toggle_preview)
        preview.addWidget(self.preview_toggle)
        self.preview_body = QFrame(self.preview_panel)
        box = QVBoxLayout(self.preview_body)
        box.setContentsMargins(0, 0, 0, 0)
        self.preview_image = QLabel('运行后显示最近截图', self.preview_body)
        self.preview_image.setAlignment(Qt.AlignCenter)
        self.preview_image.setFixedHeight(146)
        self.preview_image.setMinimumWidth(0)
        box.addWidget(self.preview_image)
        self.preview_time = typography(QLabel('尚无截图', self.preview_body), 12)
        box.addWidget(self.preview_time)
        preview.addWidget(self.preview_body)
        self.preview_body.hide()
        side_layout.addWidget(self.preview_panel)
        self.log_panel, logs = self._panel(self.side)
        row = QHBoxLayout()
        row.addWidget(typography(QLabel('运行日志', self.side), 14, True))
        row.addStretch()
        self.log_mode = QComboBox(self.side)
        self.log_mode.addItems(['简要', '详细'])
        self.log_mode.setFixedWidth(80)
        self.log_mode.currentIndexChanged.connect(self._render_logs)
        row.addWidget(self.log_mode)
        logs.addLayout(row)
        self.logger_box = TextEdit(self.side)
        typography(self.logger_box, 13)
        self.logger_box.setObjectName('runtimeLog')
        self.logger_box.setReadOnly(True)
        self.logger_box.document().setMaximumBlockCount(2000)
        self.logger_box.setMinimumWidth(0)
        logs.addWidget(self.logger_box, 1)
        side_layout.addWidget(self.log_panel, 1)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.setSizes([780, 300])
        layout.addWidget(self.splitter, 1)
        routine.dirtyChanged.connect(self.set_dirty)
        theme.changed.connect(self._apply_theme)
        self.set_state('idle')
        self.set_dirty(routine.has_unsaved_changes())
        self._apply_theme()

    @staticmethod
    def _panel(parent):
        panel = QFrame(parent)
        panel.setObjectName('sidePanel')
        box = QVBoxLayout(panel)
        box.setContentsMargins(12, 12, 12, 12)
        box.setSpacing(8)
        return panel, box

    def _primary(self):
        (self.stopRequested if self.state in ACTIVE_STATES else self.routineRequested).emit()

    def set_profile(self, config):
        self.profile_label.setText(config['display_name'])
        if self.state == 'idle': self.device_label.setText(f'MuMu 实例 {config["device"]["instance_id"]}\n尚未连接 · 开始时自动连接')

    def set_dirty(self, dirty):
        self.dirty = dirty
        self.task_count.setText(f'任务列表 · {sum(p["enabled"] for p in self.routine._queue)} 项启用')
        self._buttons()

    def _buttons(self):
        busy = self.state in ACTIVE_STATES
        self.routine_button.setText('正在停止…' if self.state == 'stopping' else '停止' if busy else '保存并开始' if self.dirty else '开始 / 继续')
        self.routine_button.setEnabled(self.state != 'stopping')
        self.more_button.setEnabled(not busy)

    def set_state(self, state):
        self.state = state
        self.status_label.setText(STATE_TEXT.get(state, state))
        self._buttons()
        if state == 'starting':
            self.current_label.setText('正在准备本轮任务')
            self.device_label.setText('正在连接 MuMu…')
        elif state not in ACTIVE_STATES:
            self.current_label.setText('暂无运行中的任务')
            if state != 'idle': self.device_label.setText('本轮连接已结束 · 下次开始时自动连接')

    def set_current_task(self, text): self.current_label.setText(text)

    def on_device_event(self, event):
        if event['kind'] == 'device':
            device = event['device']
            self.device_label.setText(f'MuMu {device["instance_id"]} · {device["serial"]}\nONEstore MAD · 已连接')

    def _toggle_preview(self, checked):
        self.preview_body.setVisible(checked)
        self.preview_toggle.setText('最近画面  ⌃' if checked else '最近画面  ⌄')
        if checked: self.previewRequested.emit()

    def show_frame(self, frame, captured_at):
        height, width = frame.shape[:2]
        self._pixmap = QPixmap.fromImage(QImage(frame.data, width, height, frame.strides[0], QImage.Format_RGB888).rgbSwapped().copy())
        self.preview_time.setText('最近采集 ' + captured_at.strftime('%H:%M:%S'))
        self._scale_preview()

    def _scale_preview(self):
        if self._pixmap:
            self.preview_image.setPixmap(self._pixmap.scaled(self.preview_image.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'preview_image'): self._scale_preview()

    def on_log_received(self, level, message, important=True):
        if not message: return
        entry = (datetime.now().strftime('%H:%M:%S'), level, str(message), important)
        if self.entries and self.entries[-1][1:3] == entry[1:3]: return
        self.entries.append(entry)
        if important or level in ('WARNING', 'ERROR', 'CRITICAL') or self.log_mode.currentIndex(): self._append_log(entry)

    def _append_log(self, entry):
        stamp, level, message, _ = entry
        color = self.theme.colors['text__error'] if level in ('ERROR', 'CRITICAL') else self.theme.colors['text__warning'] if level == 'WARNING' else self.theme.colors['text']
        self.logger_box.append(f'<div style="font-size:13px;color:{color};"><span style="color:{self.theme.surfaces["muted"]};">{stamp}</span>  {html.escape(message).replace(chr(10), "<br>")}</div>')

    def _render_logs(self, *_):
        self.logger_box.clear()
        for entry in self.entries:
            if entry[3] or entry[1] in ('WARNING', 'ERROR', 'CRITICAL') or self.log_mode.currentIndex(): self._append_log(entry)

    def _apply_theme(self):
        self.theme.apply_surface(self)
        s = self.theme.surfaces
        self.setStyleSheet(f'QFrame#homeInterface {{background:{s["window"]};}}')
        self.splitter.setStyleSheet(f'QSplitter::handle {{background:{s["window"]};}}')
        for panel in (self.connection_panel, self.preview_panel, self.log_panel):
            panel.setStyleSheet(f'QFrame#sidePanel {{background:{s["card"]};border:1px solid {s["line"]};border-radius:9px;}}')
        for label in self.findChildren(QLabel): label.setStyleSheet('color:' + self.theme.colors['text'] + ';')
        for label in (self.edition_label, self.hint, self.task_count, self.current_label, self.preview_time): label.setStyleSheet('color:' + s['muted'] + ';')
        self.theme.apply_surface(self.logger_box, 'input')
        self.theme.apply_surface(self.logger_box.viewport(), 'input')
        self.logger_box.setStyleSheet(f'QTextEdit {{background:{s["card"]};color:{self.theme.colors["text"]};border:0;}}')
        self.more_button.setStyleSheet(f'QToolButton {{background:{s["card"]};border:1px solid {s["line"]};border-radius:6px;color:{self.theme.colors["text"]};}} QToolButton::menu-indicator {{image:none;}}')
        self._render_logs()
        apply_typography(self)
        for card in self.routine.cards.values(): card.apply_theme()
