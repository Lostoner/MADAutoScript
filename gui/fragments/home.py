"""Daily workspace: instruction list, explicit run context and recoverable results."""
import html
from collections import deque
from datetime import datetime
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QVBoxLayout,
                            QSplitter, QMenu, QToolButton, QComboBox, QScrollArea, QSizePolicy)
from qfluentwidgets import PrimaryPushButton, PushButton, TextEdit
from gui.theme import typography, apply_typography
from gui.run_summary import STATE_TEXT, brief_error, result_title, result_lines

ACTIVE_STATES = {'starting', 'running', 'waiting', 'stopping'}


class HomeFragment(QFrame):
    routineRequested = pyqtSignal()
    continuousRequested = pyqtSignal()
    newRoutineRequested = pyqtSignal()
    stopRequested = pyqtSignal()
    recordsRequested = pyqtSignal()
    settingsRequested = pyqtSignal()
    schedulerRequested = pyqtSignal()
    planRequested = pyqtSignal()
    previewRequested = pyqtSignal()
    recoveryRequested = pyqtSignal()
    locateRequested = pyqtSignal(str)

    def __init__(self, theme, routine, parent=None):
        super().__init__(parent)
        self.setObjectName('homeInterface')
        self.theme, self.routine = theme, routine
        self.state, self.dirty, self.plan_auto = 'idle', False, False
        self.plan_action_text = '查看今日计划'
        self.entries = deque(maxlen=2000)
        self._pixmap = None
        self._source, self._plan_date = '普通日常', None
        self._current_id = self._current_name = None
        self._result = None
        self._error = ''
        self._recovery = ''
        self._compact = False
        self._instance = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 20)
        layout.setSpacing(16)
        header = QHBoxLayout()
        self.profile_label = self._label('', 'body', True)
        header.addWidget(self.profile_label, 1)
        self.edition_label = self._label('ONEstore · MuMu', 'caption')
        header.addWidget(self.edition_label)
        for name, signal in [('计划', self.planRequested), ('运行记录', self.recordsRequested),
                             ('调度', self.schedulerRequested), ('设置', self.settingsRequested)]:
            button = PushButton(name, self)
            button.setMinimumHeight(36)
            button.clicked.connect(signal)
            header.addWidget(button)
        layout.addLayout(header)
        heading = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(4)
        self.title = self._label('日常任务', 'title')
        self.task_count = self._label('', 'caption')
        titles.addWidget(self.title)
        titles.addWidget(self.task_count)
        heading.addLayout(titles, 1)
        routine.card_layout.removeWidget(routine.add_button)
        heading.addWidget(routine.add_button)
        layout.addLayout(heading)
        self.plan_summary = self._label('', 'caption')
        self.plan_summary.hide()
        layout.addWidget(self.plan_summary)
        self.compact_bar = QFrame(self)
        compact = QHBoxLayout(self.compact_bar)
        compact.setContentsMargins(0, 0, 0, 0)
        self.compact_status = self._label('', 'caption')
        compact.addWidget(self.compact_status, 1)
        self.details_toggle = PushButton('运行详情', self.compact_bar)
        self.details_toggle.setCheckable(True)
        self.details_toggle.toggled.connect(lambda checked: self.side.setVisible(checked or not self._compact))
        compact.addWidget(self.details_toggle)
        self.compact_actions = compact
        self.compact_bar.hide()
        layout.addWidget(self.compact_bar)
        self.splitter = QSplitter(Qt.Horizontal, self)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(24)
        self.left = QFrame(self.splitter)
        self.left.setMinimumWidth(520)
        left = QVBoxLayout(self.left)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(12)
        self.hint = self._label('拖动排序 · 展开查看参数', 'caption')
        left.addWidget(self.hint)
        left.addWidget(routine, 1)
        footer = QHBoxLayout()
        footer.addWidget(routine.save_button)
        footer.addWidget(routine.cancel_button)
        footer.addWidget(routine.feedback, 1)
        left.addLayout(footer)
        self.side = QFrame(self.splitter)
        self.side.setObjectName('runPanel')
        self.side.setMinimumWidth(300)
        side = QVBoxLayout(self.side)
        side.setContentsMargins(16, 16, 16, 16)
        side.setSpacing(12)
        self.run_scroll = QScrollArea(self.side)
        self.run_scroll.setObjectName('runScroll')
        self.run_scroll.setWidgetResizable(True)
        self.run_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.run_scroll.setFrameShape(QFrame.NoFrame)
        self.run_content = QFrame()
        self.run_content.setObjectName('runContent')
        info = QVBoxLayout(self.run_content)
        info.setContentsMargins(0, 0, 6, 0)
        info.setSpacing(12)
        self.source_label = self._label('执行对象 · 普通日常', 'caption')
        self.status_label = self._label('待机', 'section')
        self.current_label = self._label('按列表顺序执行已启用任务', 'body', True)
        self.reason_label = self._label('', 'caption')
        self.help_label = self._label('', 'caption')
        for widget in (self.source_label, self.status_label, self.current_label, self.reason_label, self.help_label):
            info.addWidget(widget)
        self.locate_button = PushButton('定位这条指令', self.run_content)
        self.locate_button.clicked.connect(self._locate)
        info.addWidget(self.locate_button)
        self.recovery_button = PushButton('核对上次结果', self.run_content)
        self.recovery_button.clicked.connect(self.recoveryRequested)
        info.addWidget(self.recovery_button)
        self.device_label = self._label('开始时连接 MuMu 实例 0', 'caption')
        info.addWidget(self.device_label)
        self.log_toggle = PushButton('执行详情与日志  ⌄', self.run_content)
        self.log_toggle.setCheckable(True)
        self.log_toggle.toggled.connect(self._toggle_logs)
        info.addWidget(self.log_toggle)
        self.log_panel = QFrame(self.run_content)
        logs = QVBoxLayout(self.log_panel)
        logs.setContentsMargins(0, 0, 0, 0)
        self.result_detail = self._label('', 'caption')
        self.result_detail.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        logs.addWidget(self.result_detail)
        row = QHBoxLayout()
        self.log_mode = QComboBox(self.log_panel)
        self.log_mode.setAccessibleName('日志详细程度')
        self.log_mode.addItems(['简要', '详细'])
        self.log_mode.currentIndexChanged.connect(self._render_logs)
        row.addWidget(self.log_mode)
        copy = PushButton('复制日志', self.log_panel)
        copy.clicked.connect(self._copy_logs)
        row.addWidget(copy)
        logs.addLayout(row)
        self.logger_box = TextEdit(self.log_panel)
        typography(self.logger_box, 'caption')
        self.logger_box.setObjectName('runtimeLog')
        self.logger_box.setReadOnly(True)
        self.logger_box.document().setMaximumBlockCount(2000)
        self.logger_box.setMinimumWidth(0)
        self.logger_box.setFixedHeight(200)
        logs.addWidget(self.logger_box)
        self.latest_button = PushButton('回到最新', self.log_panel)
        self.latest_button.clicked.connect(self._latest_log)
        self.latest_button.hide()
        logs.addWidget(self.latest_button)
        self.log_panel.hide()
        info.addWidget(self.log_panel)
        self.preview_toggle = PushButton('最近画面  ⌄', self.run_content)
        self.preview_toggle.setCheckable(True)
        self.preview_toggle.toggled.connect(self._toggle_preview)
        info.addWidget(self.preview_toggle)
        self.preview_body = QFrame(self.run_content)
        preview = QVBoxLayout(self.preview_body)
        preview.setContentsMargins(0, 0, 0, 0)
        self.preview_image = self._label('运行后显示最近截图', 'caption')
        self.preview_image.setAlignment(Qt.AlignCenter)
        self.preview_image.setFixedHeight(146)
        preview.addWidget(self.preview_image)
        self.preview_time = self._label('尚无截图', 'caption')
        preview.addWidget(self.preview_time)
        self.preview_body.hide()
        info.addWidget(self.preview_body)
        info.addStretch()
        self.run_scroll.setWidget(self.run_content)
        side.addWidget(self.run_scroll, 1)
        self.run_actions = QHBoxLayout()
        self.routine_button = PrimaryPushButton('开始日常', self.side)
        self.routine_button.setObjectName('routineRunButton')
        self.routine_button.setMinimumHeight(40)
        typography(self.routine_button, 'body', True)
        self.routine_button.clicked.connect(self._primary)
        self.run_actions.addWidget(self.routine_button, 1)
        self.more_button = QToolButton(self.side)
        self.more_button.setText('⋯')
        self.more_button.setFixedSize(36, 40)
        self.more_button.setToolTip('其他运行方式')
        self.more_button.setAccessibleName('其他运行方式')
        self.more_button.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self.more_button)
        self.continuous_action = menu.addAction('持续运行', self.continuousRequested.emit)
        self.new_routine_action = menu.addAction('开始新一轮（重新建立完整计划）', self.newRoutineRequested.emit)
        self.more_button.setMenu(menu)
        self.run_actions.addWidget(self.more_button)
        side.addLayout(self.run_actions)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.setSizes([724, 300])
        layout.addWidget(self.splitter, 1)
        routine.dirtyChanged.connect(self.set_dirty)
        theme.changed.connect(self._apply_theme)
        self.set_state('idle')
        self.set_dirty(routine.has_unsaved_changes())
        self._apply_theme()

    def _label(self, text, size='caption', bold=False):
        label = typography(QLabel(text, self), size, bold)
        label.setTextFormat(Qt.PlainText)
        label.setWordWrap(True)
        label.setMinimumWidth(0)
        label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        return label

    def _primary(self):
        if self.state == 'stopping': return
        if self.state in ACTIVE_STATES: self.stopRequested.emit()
        elif self.plan_auto: self.planRequested.emit()
        elif self._recovery == 'material': self.recoveryRequested.emit()
        else: self.routineRequested.emit()

    def _locate(self):
        if self._plan_date: self.planRequested.emit()
        elif self._current_id in self.routine.cards: self.locateRequested.emit(self._current_id)
        else: self.log_toggle.setChecked(True)

    def set_profile(self, config):
        self.profile_label.setText(config['display_name'])
        self._instance = config['device']['instance_id']
        if self.state == 'idle': self.device_label.setText(f'开始时连接 MuMu 实例 {self._instance}')

    def set_dirty(self, dirty):
        self.dirty = dirty
        self.task_count.setText(f'普通日常 · {sum(p["enabled"] for p in self.routine._queue)} 条已启用 · 按列表顺序执行')
        self._buttons()

    def _buttons(self):
        busy = self.state in ACTIVE_STATES
        if self.state == 'stopping': text = '正在停止…'
        elif busy: text = '停止'
        elif self.plan_auto: text = '查看今日计划'
        elif self._recovery == 'material': text = '核对素材结果'
        elif self.dirty: text = '保存并开始日常'
        elif self._source == '普通日常' and self.state in ('failed', 'stopped'): text = '继续本轮'
        elif self._source == '普通日常' and self._result and any(t.get('status') == 'PARTIAL' for t in self._result.get('tasks', [])): text = '继续本轮'
        else: text = '开始／继续日常'
        self.routine_button.setText(text)
        self.routine_button.setEnabled(self.state != 'stopping')
        self.more_button.setEnabled(not busy and not self.plan_auto)
        self.recovery_button.setVisible(bool(self._recovery) and not busy and (self.plan_auto or self._recovery != 'material'))
        self.recovery_button.setText('查看待核对计划' if self._recovery == 'plan' else '核对素材结果')
        self.compact_status.setText(self.status_label.text() + ' · ' + self._source +
            ('\n' + self.reason_label.text() if self._compact and self.reason_label.text() else ''))

    def set_recovery(self, kind=''):
        self._recovery = kind
        self._render_summary()

    def set_plan_summary(self, text, automatic, action_text='查看今日计划'):
        self.plan_auto = automatic
        self.plan_action_text = action_text
        self.plan_summary.setText(('自动计划已接管执行 · ' if automatic else '') + text)
        self.plan_summary.setVisible(bool(text))
        self._buttons()

    def begin_run(self, source='普通日常', plan_date=None):
        self._source, self._plan_date = source, plan_date
        self._current_id = self._current_name = None
        self._result = None
        self._error = ''

    def on_runtime_event(self, event, tasks=None):
        kind = event['kind']
        if event.get('plan_date'):
            if self._plan_date != event['plan_date']: self.begin_run('今日计划 · ' + event['plan_date'], event['plan_date'])
        elif event.get('material_sync') and self._source != '同步素材数据':
            self.begin_run('同步素材数据')
        if kind == 'state' and event.get('state') == 'starting':
            source = ('今日计划 · ' + event['plan_date'] if event.get('plan_date') else
                      '同步素材数据' if event.get('material_sync') else
                      '持续运行' if self._source == '持续运行' else '普通日常')
            self.begin_run(source, event.get('plan_date'))
        elif kind == 'task':
            if event.get('state') == 'running':
                self._current_id = event.get('instance_id', event.get('task_id'))
                self._current_name = event.get('event_name') or event.get('message') or self._current_id
                self._error = ''
            else: self._error = event.get('message', '')
        elif kind == 'result':
            self._result = dict(event['result'])
            if tasks is not None: self._result['tasks'] = tasks
            self._error = brief_error(self._result.get('error'))
            if event.get('state') == 'succeeded':
                issue = next((t for t in self._result.get('tasks', []) if t.get('status') in ('PARTIAL', 'FAILED', 'NEEDS_ATTENTION')), None)
                if issue:
                    self._current_id = issue.get('instance_id', issue.get('task_id'))
                    self._current_name = issue.get('event_name') or self._current_id
        self._render_summary()

    def show_error(self, error):
        self._error = brief_error(error)
        self._render_summary()

    def set_state(self, state):
        self.state = state
        if state == 'starting': self.device_label.setText(f'正在连接 MuMu 实例 {self._instance}…')
        elif state not in ACTIVE_STATES and state != 'idle':
            self.device_label.setText('本轮连接已结束，下次开始时连接。')
        self._render_summary()

    def _render_summary(self):
        tasks = (self._result or {}).get('tasks', [])
        self.source_label.setText('执行来源 · ' + self._source)
        title = result_title(self.state, tasks)
        if self._recovery == 'material' and self.state not in ACTIVE_STATES: title = '素材消费待核对'
        elif self._recovery == 'plan' and self._plan_date and self.state not in ACTIVE_STATES: title = '今日计划待核对'
        self.status_label.setText(title)
        self.current_label.setText(self._current_name or ('正在准备本轮任务' if self.state == 'starting' else '按列表顺序执行已启用任务'))
        if self._source == '同步素材数据' and self.state == 'succeeded': self.current_label.setText('素材数据同步结束')
        lines = result_lines(tasks)
        reason = brief_error(self._error) or (lines[0] if lines else '')
        if self._recovery == 'material' and self.state not in ACTIVE_STATES: reason = '上批素材消费结果不明，请先核对；不会自动重复确认。'
        self.reason_label.setText(reason)
        self.reason_label.setVisible(bool(reason))
        self.result_detail.setText('\n'.join(lines))
        self.result_detail.setVisible(bool(lines))
        help_text = ('正在等待当前动作安全结束。' if self.state == 'stopping' else
                     '继续时保留原断点和剩余关卡。' if self.state in ('failed', 'stopped') and not self._plan_date and self._source == '普通日常' else
                     '剩余关卡已保留，可查看指令参数后继续本轮。' if '有余项' in title and not self._plan_date else '')
        self.help_label.setText(help_text)
        self.help_label.setVisible(bool(help_text) and not self._recovery)
        self.locate_button.setText('查看今日计划' if self._plan_date else '定位这条指令' if self._current_id in self.routine.cards else '查看执行详情')
        self.locate_button.setVisible(bool(self._current_id or reason) and self._recovery != 'plan')
        self.reason_label.setStyleSheet('color:' + self.theme.colors['text__error' if self.state == 'failed' else 'text__warning'] + ';')
        self._buttons()

    def set_current_task(self, text):
        self._current_name = text
        self._render_summary()

    def on_device_event(self, event):
        if event['kind'] == 'device':
            device = event['device']
            self.device_label.setText(f'MuMu {device["instance_id"]} · ONEstore MAD · 已连接')
            self.device_label.setToolTip(device['serial'])

    def _toggle_logs(self, checked):
        self.log_panel.setVisible(checked)
        self.log_toggle.setText('执行详情与日志  ' + ('⌃' if checked else '⌄'))

    def _copy_logs(self):
        QApplication.clipboard().setText('\n'.join(f'{t} {level} {message}' for t, level, message, _ in self.entries))

    def _latest_log(self):
        bar = self.logger_box.verticalScrollBar()
        bar.setValue(bar.maximum())
        self.latest_button.hide()

    def _toggle_preview(self, checked):
        self.preview_body.setVisible(checked)
        self.preview_toggle.setText('最近画面  ' + ('⌃' if checked else '⌄'))
        if checked: self.previewRequested.emit()

    def show_frame(self, frame, captured_at):
        height, width = frame.shape[:2]
        self._pixmap = QPixmap.fromImage(QImage(frame.data, width, height, frame.strides[0], QImage.Format_RGB888).rgbSwapped().copy())
        self.preview_time.setText('最近采集 ' + captured_at.strftime('%H:%M:%S'))
        self._scale_preview()

    def _scale_preview(self):
        if self._pixmap: self.preview_image.setPixmap(self._pixmap.scaled(self.preview_image.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self, 'routine_button'): return
        compact = self.width() < 980
        if compact != self._compact:
            self._compact = compact
            self.left.setMinimumWidth(0 if compact else 520)
            self.side.setMinimumWidth(0 if compact else 300)
            self.splitter.setOrientation(Qt.Vertical if compact else Qt.Horizontal)
            target = self.compact_actions if compact else self.run_actions
            target.addWidget(self.routine_button)
            target.addWidget(self.more_button)
            self.compact_bar.setVisible(compact)
            self.side.setVisible(not compact or self.details_toggle.isChecked())
            self.splitter.setSizes([320, 220] if compact else [724, 300])
            self._buttons()
        self._scale_preview()

    def on_log_received(self, level, message, important=True):
        if not message: return
        entry = (datetime.now().strftime('%H:%M:%S'), level, str(message), important)
        if self.entries and self.entries[-1][1:3] == entry[1:3]:
            if important and not self.entries[-1][3]:
                self.entries[-1] = entry
                self._render_logs()
            return
        self.entries.append(entry)
        if important or level in ('WARNING', 'ERROR', 'CRITICAL') or self.log_mode.currentIndex(): self._append_log(entry)

    def _append_log(self, entry):
        stamp, level, message, _ = entry
        bar = self.logger_box.verticalScrollBar()
        previous, follow = bar.value(), bar.value() >= bar.maximum() - 4
        if not self.log_mode.currentIndex() and 'Traceback (most recent call last)' in message: message = brief_error(message)
        color = self.theme.colors['text__error'] if level in ('ERROR', 'CRITICAL') else self.theme.colors['text__warning'] if level == 'WARNING' else self.theme.colors['text']
        self.logger_box.append(f'<div style="color:{color};"><span style="color:{self.theme.surfaces["muted"]};">{stamp}</span>  {html.escape(message).replace(chr(10), "<br>")}</div>')
        if follow: bar.setValue(bar.maximum())
        else:
            bar.setValue(previous)
            self.latest_button.show()

    def _render_logs(self, *_):
        if not hasattr(self, 'logger_box'): return
        bar = self.logger_box.verticalScrollBar()
        previous, follow = bar.value(), bar.value() >= bar.maximum() - 4
        self.logger_box.clear()
        for entry in self.entries:
            if entry[3] or entry[1] in ('WARNING', 'ERROR', 'CRITICAL') or self.log_mode.currentIndex(): self._append_log(entry)
        bar.setValue(bar.maximum() if follow else previous)

    def _apply_theme(self):
        self.theme.apply_surface(self)
        s, c = self.theme.surfaces, self.theme.colors
        self.setStyleSheet(f'QFrame#homeInterface {{background:{s["window"]};}}')
        self.splitter.setStyleSheet(f'QSplitter::handle {{background:{s["window"]};}}')
        self.side.setStyleSheet(f'QFrame#runPanel {{background:{s["card"]};border:0;border-radius:8px;}}')
        for widget in (self.run_scroll, self.run_scroll.viewport(), self.run_content, self.logger_box, self.logger_box.viewport()):
            self.theme.apply_surface(widget, 'card')
        self.run_scroll.setStyleSheet(f'QScrollArea#runScroll {{background:{s["card"]};border:0;}}')
        self.run_content.setStyleSheet(f'QFrame#runContent {{background:{s["card"]};border:0;}}')
        for label in self.findChildren(QLabel): label.setStyleSheet('color:' + c['text'] + ';')
        for label in (self.edition_label, self.hint, self.task_count, self.source_label, self.device_label, self.help_label, self.preview_time, self.plan_summary):
            label.setStyleSheet('color:' + s['muted'] + ';')
        self.logger_box.setStyleSheet(f'QTextEdit {{background:{s["card"]};color:{c["text"]};border:0;}}')
        self.routine_button.setStyleSheet(f'QPushButton {{background:{s["action"]};color:{s["action_text"]};border:2px solid {s["action"]};border-radius:6px;padding:6px 12px;}} '
            f'QPushButton:hover {{background:{s["action_hover"]};}} QPushButton:pressed {{background:{s["action_pressed"]};}} '
            f'QPushButton:focus {{border-color:{s["focus"]};}} '
            f'QPushButton:disabled {{background:{s["subtle"]};color:{s["muted"]};border-color:{s["line"]};}}')
        self.more_button.setStyleSheet(f'QToolButton {{background:{s["card"]};border:1px solid {s["control"]};border-radius:6px;color:{c["text"]};}} '
            f'QToolButton:focus {{border-color:{s["focus"]};}} QToolButton::menu-indicator {{image:none;}}')
        self._render_logs()
        apply_typography(self)
        for card in self.routine.cards.values(): card.apply_theme()
        self._render_summary()
