"""M0 settings derived from BAAS SettingsFragment/TemplateLayout.

Source: pur1fying/blue_archive_auto_script@1110e88df5955df277737ea9717869b9ca88362b
GPL-3.0-only. All edits stay in a snapshot draft; UI settings and profile
settings use explicit repositories, not BAAS's implicit global config.
"""
from copy import deepcopy

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import ComboBox, FluentIcon as FIF, LineEdit, PrimaryPushButton, PushButton, ScrollArea, SpinBox, TitleLabel, CheckBox
from core.config.config_set import ConfigSet
from gui.util.config_draft import ConfigDraft

from gui.widgets import BAASSettingCard, ClickFocusLineEdit


class SettingsFragment(ScrollArea):
    saved = pyqtSignal(dict, dict)
    message = pyqtSignal(str, str)
    THEMES = [('跟随系统', 'system'), ('浅色', 'light'), ('深色', 'dark')]

    def __init__(self, repository, app_repository, theme, parent=None):
        super().__init__(parent)
        self.setObjectName('settingsInterface')
        self.repository = repository
        self.app_repository = app_repository
        self.theme = theme
        self.base_config = repository.load_config()
        self.config_draft=ConfigDraft(ConfigSet(repository))
        self.base_app = app_repository.load()
        self._loading = False
        self._busy = False
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scrollWidget = QWidget(self)
        layout = QVBoxLayout(self.scrollWidget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        self.title = TitleLabel('设置', self)
        self.note = QLabel('修改后保存设置；撤销会载入最新保存的值。', self)
        self.note.setWordWrap(True)
        layout.addWidget(self.title)
        layout.addWidget(self.note)
        self.form_panel = QWidget(self)
        self.form_panel.setObjectName('configurationForm')
        form = QVBoxLayout(self.form_panel)
        form.setContentsMargins(16, 12, 16, 16)
        form.setSpacing(12)
        self.field_labels = []

        self.name_edit = LineEdit(self)
        self.name_edit.setObjectName('displayNameEdit')
        self.name_edit.setMinimumWidth(300)
        self._add_row(form, '显示名', self.name_edit)
        self.mumu_edit = ClickFocusLineEdit(self)
        self.mumu_edit.setObjectName('mumuPathEdit')
        self.mumu_edit.setPlaceholderText('MuMu 的 mumu-cli.exe 完整路径')
        self.mumu_edit.setMinimumWidth(320)
        self.browse_button = PushButton('选择文件', self)
        self.browse_button.clicked.connect(self._choose_path)
        self._add_row(form, 'MuMu 路径', self.mumu_edit, self.browse_button)
        self.adb_edit = ClickFocusLineEdit(self)
        self.adb_edit.setPlaceholderText('留空时从所选 MuMu 安装目录查找')
        self.adb_edit.setMinimumWidth(320)
        self.adb_browse_button = PushButton('选择文件', self)
        self.adb_browse_button.clicked.connect(self._choose_adb)
        self._add_row(form, 'ADB 路径', self.adb_edit, self.adb_browse_button)
        self.instance_spin = SpinBox(self)
        self.instance_spin.setObjectName('mumuInstanceSpin')
        self.instance_spin.setRange(0, 65535)
        self._add_row(form, 'MuMu 实例编号', self.instance_spin)
        self.schedule_timezone=ComboBox(self)
        self.schedule_timezone.addItems(['Asia/Hong_Kong','UTC','Asia/Seoul'])
        self._add_row(form,'禁用时段时区',self.schedule_timezone)
        self.reset_enabled=CheckBox('在服务器日切后刷新关卡计划',self)
        self._add_row(form,'计划刷新',self.reset_enabled)
        self.reset_clock=LineEdit(self)
        self.reset_clock.setPlaceholderText('HH:MM（服务器时间）')
        self._add_row(form,'服务器日切时刻',self.reset_clock)
        self.reset_zone=ComboBox(self)
        self.reset_zone.addItems(['UTC','Asia/Seoul','Asia/Hong_Kong'])
        self._add_row(form,'服务器时区',self.reset_zone)
        self.reset_note=QLabel('ONEstore 国际服默认北京时间 04:00。开启后跨日重建计划并使任务到期；同一游戏日保留断点。关闭后需手动开始新一轮。',self)
        self.reset_note.setWordWrap(True)
        self._add_row(form,'日切状态',self.reset_note)
        self.theme_combo = ComboBox(self)
        self.theme_combo.setObjectName('themeCombo')
        self.theme_combo.addItems([label for label, _ in self.THEMES])
        self._add_row(form, '界面主题', self.theme_combo)

        self.settings_card = BAASSettingCard(FIF.SETTING, '配置与外观',
                                             'ONEstore MAD · MuMu · 1920×1080', self)
        self.settings_card.viewLayout.addWidget(self.form_panel)
        self.settings_card.setExpand(True)
        self.settings_card._adjustViewSize()
        layout.addWidget(self.settings_card)
        buttons = QHBoxLayout()
        self.save_button = PrimaryPushButton('保存设置', self)
        self.save_button.setObjectName('saveSettingsButton')
        self.cancel_button = PushButton('取消更改', self)
        self.cancel_button.setObjectName('cancelSettingsButton')
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.cancel_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self.feedback = QLabel('设置尚未修改。', self)
        self.feedback.setWordWrap(True)
        self.feedback.setObjectName('settingsFeedback')
        layout.addWidget(self.feedback)
        layout.addStretch(1)
        self.setWidget(self.scrollWidget)

        self.name_edit.textChanged.connect(self._mark_dirty)
        self.mumu_edit.textChanged.connect(self._mark_dirty)
        self.adb_edit.textChanged.connect(self._mark_dirty)
        for spin in (self.instance_spin,):
            spin.valueChanged.connect(self._mark_dirty)
        self.theme_combo.currentIndexChanged.connect(self._mark_dirty)
        self.schedule_timezone.currentIndexChanged.connect(self._mark_dirty)
        self.reset_enabled.toggled.connect(self._mark_dirty)
        self.reset_clock.textChanged.connect(self._mark_dirty)
        self.reset_zone.currentIndexChanged.connect(self._mark_dirty)
        self.save_button.clicked.connect(self.save_changes)
        self.cancel_button.clicked.connect(self.cancel_changes)
        theme.changed.connect(self._apply_theme)
        self._load_fields()
        self._apply_theme()

    def _add_row(self, layout, label, field, extra=None):
        row = QHBoxLayout()
        caption = QLabel(label, self)
        caption.setMinimumWidth(120)
        self.field_labels.append(caption)
        row.addWidget(caption)
        row.addStretch(1)
        row.addWidget(field)
        if extra is not None:
            row.addWidget(extra)
        layout.addLayout(row)

    def _choose_path(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择 MuMu 命令行程序', self.mumu_edit.text(),
                                              '可执行文件 (*.exe);;所有文件 (*)')
        if path:
            self.mumu_edit.setText(path)

    def _load_fields(self):
        self._loading = True
        config = self.base_config
        self.name_edit.setText(config['display_name'])
        self.mumu_edit.setText(config['device']['mumu_path'])
        self.adb_edit.setText(config['device'].get('adb_path', ''))
        self.instance_spin.setValue(config['device']['instance_id'])
        reset=config['scheduling']['reset']
        self.reset_enabled.setChecked(reset['enabled'])
        self.reset_clock.setText(reset.get('reset_at') or '')
        if self.reset_zone.findText(reset['server_timezone'])<0: self.reset_zone.addItem(reset['server_timezone'])
        self.reset_zone.setCurrentText(reset['server_timezone'])
        zone=config['scheduling']['timezone']
        if self.schedule_timezone.findText(zone)<0:
            self.schedule_timezone.addItem(zone)
        self.schedule_timezone.setCurrentText(zone)
        names = [value for _, value in self.THEMES]
        self.theme_combo.setCurrentIndex(names.index(self.base_app['ui']['theme']))
        self._loading = False
        self._refresh_buttons()

    def _choose_adb(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择 ADB', self.adb_edit.text(), '可执行文件 (*.exe);;所有文件 (*)')
        if path:
            self.adb_edit.setText(path)

    def _drafts(self):
        config = deepcopy(self.base_config)
        app = deepcopy(self.base_app)
        config['display_name'] = self.name_edit.text()
        config['device']['mumu_path'] = self.mumu_edit.text()
        config['device']['adb_path'] = self.adb_edit.text().strip()
        config['device']['instance_id'] = self.instance_spin.value()
        config['scheduling']['reset'].update(enabled=self.reset_enabled.isChecked(),reset_at=self.reset_clock.text().strip() or None,server_timezone=self.reset_zone.currentText())
        config['scheduling']['timezone']=self.schedule_timezone.currentText()
        app['ui']['theme'] = self.THEMES[self.theme_combo.currentIndex()][1]
        return config, app

    def has_unsaved_changes(self):
        config, app = self._drafts()
        return config != self.base_config or app != self.base_app

    def _mark_dirty(self, *_):
        if self._loading:
            return
        self.feedback.setText('有未保存的更改。' if self.has_unsaved_changes() else '设置尚未修改。')
        self._refresh_buttons()

    def _refresh_buttons(self):
        enabled = not self._busy and self.has_unsaved_changes()
        self.save_button.setEnabled(enabled)
        self.cancel_button.setEnabled(enabled)

    def save_changes(self):
        if self._busy:
            return
        config, app = self._drafts()
        profile_saved = False
        try:
            if config != self.base_config:
                for key,value in config.items():
                    if value!=self.base_config.get(key): self.config_draft.set(key,value)
                self.config_draft.commit()
                self.base_config=self.repository.load_config()
                profile_saved = True
            if app != self.base_app:
                self.base_app = self.app_repository.save(app)
        except Exception as error:
            # Repositories own atomic per-file writes. If the separate app
            # file fails after profile save, report partial success explicitly
            # and preserve the still-unsaved appearance draft.
            prefix = '配置已保存，界面设置保存失败' if profile_saved else '保存失败'
            self.feedback.setText(f'{prefix}：{error}\n未保存的输入仍保留；可调整后重试或取消。')
            self.message.emit('ERROR', f'{prefix}：{error}')
            if profile_saved:
                self.saved.emit(deepcopy(self.base_config), deepcopy(self.base_app))
            self._refresh_buttons()
            return
        self._load_fields()
        self.feedback.setText('设置已保存。')
        self.saved.emit(deepcopy(self.base_config), deepcopy(self.base_app))
        self.message.emit('INFO', '设置已保存。')

    def cancel_changes(self):
        if self._busy:
            return
        try:
            config = self.repository.load_config()
            app = self.app_repository.load()
        except Exception as error:
            # Load both files before replacing either baseline. A failed
            # reload must keep the user's current inputs and revisions intact.
            self.feedback.setText(f'无法重新载入设置：{error}\n未保存的输入仍保留。')
            self.message.emit('ERROR', f'无法重新载入设置：{error}')
            return
        self.base_config = config
        self.config_draft.rollback()
        self.base_app = app
        self._load_fields()
        self.feedback.setText('已取消未保存的更改，并载入最新已保存的设置。')
        self.saved.emit(deepcopy(config), deepcopy(app))

    def set_busy(self, busy):
        self._busy = busy
        self.form_panel.setEnabled(not busy)
        self._refresh_buttons()

    def sync_profile(self,config):
        if not self.has_unsaved_changes():
            self.base_config=deepcopy(config)
            self._load_fields()

    def _apply_theme(self):
        color = self.theme.colors['text']
        self.theme.apply_scroll_surface(self, self.scrollWidget)
        self.theme.apply_surface(self.form_panel)
        self.form_panel.setStyleSheet('QWidget#configurationForm {background:'+self.theme.surfaces['card']+';}')
        for label in (self.title, self.note, self.feedback,self.reset_note, *self.field_labels):
            label.setStyleSheet(f'color: {color};')
