"""Task cards edit the existing BAAS-style queue and configuration draft."""
from copy import deepcopy
from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QHeaderView,
                            QDialog, QDialogButtonBox, QComboBox,
                            QListWidgetItem, QAbstractItemView, QTableWidgetItem)
from qfluentwidgets import ScrollArea, CheckBox, SpinBox, PushButton, TableWidget
from core.routine_catalog import ROUTINES, parameter_summary, CLAIM_MODULES
from core.game_catalog import stage_options, characters, SHOP_ITEMS
from core.config.config_set import ConfigSet
from core.mad_features import MAP_LOCATIONS
from gui.util.config_draft import ConfigDraft
from gui.widgets import TaskCard, CheckableListWidget
from gui.theme import typography, apply_typography


class SweepSelector(QWidget):
    changed = pyqtSignal()

    def __init__(self, task, parent=None):
        super().__init__(parent)
        self.options = stage_options(task)
        self._order, self.rows, self.remaining = [], {}, {}
        self._loading = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)
        self.table = TableWidget(self)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(['关卡 / 执行顺序', '计划次数', '本轮剩余', ''])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setColumnWidth(1, 146)
        self.table.setColumnWidth(2, 82)
        self.table.setColumnWidth(3, 106)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        outer.addWidget(self.table)
        row = QHBoxLayout()
        self.add_button = PushButton('+ 添加关卡', self)
        self.add_button.clicked.connect(self.add_dialog)
        row.addWidget(self.add_button)
        note = typography(QLabel('按列表顺序扫荡 · 次数 0 为 MAX', self), 12)
        note.setWordWrap(True)
        note.setToolTip('MAX 使用游戏当前允许的最大扫荡次数。保存计划会按现有进度续算剩余次数。')
        row.addWidget(note, 1)
        outer.addLayout(row)

    def value(self):
        return [{'stage_id': key, 'count': self.rows[key][2].value() or 'max'} for key in self._order]

    def setValue(self, plans):
        self._loading = True
        self._order = [p['stage_id'] for p in plans]
        self.rows = {}
        self.table.setRowCount(len(plans))
        for row, plan in enumerate(plans):
            key = plan['stage_id']
            self.table.setItem(row, 0, QTableWidgetItem(self.options.get(key, {}).get('title', key)))
            count = SpinBox(self.table)
            count.setRange(0, 2147483647)
            count.setSpecialValueText('MAX')
            count.setValue(0 if plan['count'] == 'max' else plan['count'])
            count.setMinimumWidth(136)
            count.valueChanged.connect(lambda _: self.changed.emit() if not self._loading else None)
            self.table.setCellWidget(row, 1, count)
            self.table.setItem(row, 2, QTableWidgetItem('—'))
            controls = QWidget(self.table)
            buttons = QHBoxLayout(controls)
            buttons.setContentsMargins(2, 2, 2, 2)
            buttons.setSpacing(2)
            for text, delta, tip in [('↑', -1, '上移'), ('↓', 1, '下移'), ('×', 0, '移除')]:
                button = PushButton(text, controls)
                button.setFixedSize(30, 30)
                button.setToolTip(tip)
                button.setAccessibleName(self.options.get(key, {}).get('title', key) + tip)
                button.setEnabled(delta == 0 or 0 <= row + delta < len(plans))
                button.clicked.connect(lambda _, k=key, d=delta: self.edit_order(k, d))
                buttons.addWidget(button)
            self.table.setCellWidget(row, 3, controls)
            self.table.setRowHeight(row, 42)
            self.rows[key] = (row, None, count)
        self.table.setFixedHeight(min(288, 40 + max(1, len(plans)) * 42))
        self._loading = False
        self.set_remaining(self.remaining)
        apply_typography(self)

    def set_remaining(self, plans):
        self.remaining = plans if isinstance(plans, dict) else {p['stage_id']: p['count'] for p in plans}
        for key, (row, _, _) in self.rows.items():
            self.table.item(row, 2).setText(str(self.remaining.get(key, 0)).upper())
            self.table.item(row, 2).setToolTip('已保存计划的本轮剩余次数；编辑后的变化在保存时计算。')

    def edit_order(self, key, delta):
        plans = self.value()
        index = self._order.index(key)
        if delta == 0:
            plans.pop(index)
        elif 0 <= index + delta < len(plans):
            plans[index], plans[index + delta] = plans[index + delta], plans[index]
        self.setValue(plans)
        self.changed.emit()

    def add_stages(self, keys):
        plans = self.value()
        for key in keys:
            if key in self.options and key not in self._order:
                plans.append({'stage_id': key, 'count': 1})
        self.setValue(plans)
        self.changed.emit()

    def add_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('添加关卡')
        dialog.resize(450, 510)
        layout = QVBoxLayout(dialog)
        group = QComboBox(dialog)
        group.addItem('全部分类')
        group.addItems(list(dict.fromkeys(o['group'] for o in self.options.values())))
        layout.addWidget(group)
        caption = QLabel('点击整行勾选，可多选；已添加的关卡保持原顺序和次数。', dialog)
        caption.setWordWrap(True)
        layout.addWidget(caption)
        choices = CheckableListWidget(dialog)
        choices.setObjectName('stageChoices')
        for key, option in self.options.items():
            item = QListWidgetItem(option['title'], choices)
            item.setData(Qt.UserRole, key)
            if key in self._order:
                item.setText(option['title'] + ' · 已添加')
                item.setFlags(Qt.NoItemFlags)
            else:
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
                item.setCheckState(Qt.Unchecked)
        def filter_group(text):
            for i in range(choices.count()):
                item = choices.item(i)
                item.setHidden(text != '全部分类' and self.options[item.data(Qt.UserRole)]['group'] != text)
        group.currentTextChanged.connect(filter_group)
        layout.addWidget(choices)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, dialog)
        def update_selection():
            count = sum(choices.item(i).checkState() == Qt.Checked for i in range(choices.count()))
            buttons.button(QDialogButtonBox.Ok).setText(f'添加所选（{count}）')
            buttons.button(QDialogButtonBox.Ok).setEnabled(count > 0)
        choices.itemChanged.connect(update_selection)
        update_selection()
        buttons.button(QDialogButtonBox.Cancel).setText('取消')
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        apply_typography(dialog)
        if dialog.exec_() == QDialog.Accepted:
            self.add_stages([choices.item(i).data(Qt.UserRole) for i in range(choices.count())
                             if choices.item(i).checkState() == Qt.Checked])


class RoutineFragment(ScrollArea):
    saved = pyqtSignal(dict)
    message = pyqtSignal(str, str)
    dirtyChanged = pyqtSignal(bool)

    def __init__(self, repository, theme, parent=None):
        super().__init__(parent)
        self.setObjectName('routineInterface')
        self.repository, self.theme = repository, theme
        self.base_config = repository.load_config()
        self.config_draft = ConfigDraft(ConfigSet(repository))
        self.base_events = repository.load_events()
        self._busy, self._loading = False, True
        self._queue, self._results = [], {}
        self._active = None
        self.cards, self.sweep_selectors, self.claim_checks, self.period_checks = {}, {}, {}, {}
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scrollWidget = QWidget(self)
        self.card_layout = QVBoxLayout(self.scrollWidget)
        self.card_layout.setContentsMargins(0, 0, 10, 6)
        self.card_layout.setSpacing(8)
        self.card_layout.addStretch()
        self.save_button = PushButton('保存更改', self)
        self.cancel_button = PushButton('撤销', self)
        self.feedback = typography(QLabel('按列表顺序执行已启用任务', self), 12)
        self.feedback.setWordWrap(True)
        self.save_button.clicked.connect(self.save_changes)
        self.cancel_button.clicked.connect(self.cancel_changes)
        aliases = {'mad.mail': 'mail', 'mad.normal_sweep': 'normal', 'mad.procurement_sweep': 'procurement'}
        for task, spec in ROUTINES.items():
            card = TaskCard(task, spec.title, theme, self.scrollWidget)
            self.cards[task] = card
            setattr(self, aliases.get(task, task[4:]), card.check)
            card.check.toggled.connect(lambda enabled, k=task: self._toggle(k, enabled))
            card.moveRequested.connect(self.move_task)
            card.dropRequested.connect(self.drop_task)
            self._build_parameters(task, card)
        self.setWidget(self.scrollWidget)
        theme.changed.connect(self._apply_theme)
        self._load()
        self._loading = False
        self._changed()
        self._apply_theme()

    def _build_parameters(self, task, card):
        layout = card.body_layout
        def label(text):
            widget = typography(QLabel(text, card.body), 13)
            widget.setWordWrap(True)
            layout.addWidget(widget)
        if task in ('mad.normal_sweep', 'mad.flara_sweep', 'mad.procurement_sweep'):
            selector = SweepSelector(task, card.body)
            selector.changed.connect(self._changed)
            self.sweep_selectors[task] = selector
            layout.addWidget(selector)
        elif task == 'mad.gold_shop':
            label('选择要购买的普通商品，每项独立设置数量；0 为 MAX（买完当前可购买数量）。')
            self.shop_table = TableWidget(card.body)
            self.shop_table.setColumnCount(4)
            self.shop_table.setHorizontalHeaderLabels(['购买', '商品', '单价 / 金币', '数量'])
            self.shop_table.setRowCount(len(SHOP_ITEMS))
            self.shop_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.shop_table.setSelectionMode(QAbstractItemView.NoSelection)
            self.shop_table.verticalHeader().hide()
            self.shop_table.setShowGrid(False)
            self.shop_table.setColumnWidth(0, 54)
            self.shop_table.setColumnWidth(2, 106)
            self.shop_table.setColumnWidth(3, 146)
            self.shop_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
            self.shop_checks, self.shop_counts = {}, {}
            for row, (key, product) in enumerate(SHOP_ITEMS.items()):
                check = CheckBox(self.shop_table)
                check.setAccessibleName('购买' + product['title'])
                count = SpinBox(self.shop_table)
                count.setRange(0, 2147483647)
                count.setSpecialValueText('MAX')
                count.setValue(1)
                count.setEnabled(False)
                check.toggled.connect(count.setEnabled)
                check.toggled.connect(self._changed)
                count.valueChanged.connect(self._changed)
                self.shop_checks[key], self.shop_counts[key] = check, count
                self.shop_table.setCellWidget(row, 0, check)
                self.shop_table.setItem(row, 1, QTableWidgetItem(product['title']))
                self.shop_table.setItem(row, 2, QTableWidgetItem(f'{product["price"]:,}'))
                self.shop_table.setCellWidget(row, 3, count)
                self.shop_table.setRowHeight(row, 42)
            self.shop_table.setFixedHeight(40 + len(SHOP_ITEMS) * 42)
            layout.addWidget(self.shop_table)
        elif task == 'mad.dating':
            row = QHBoxLayout()
            self.dating_character = QComboBox(card.body)
            self.dating_character.addItem('请选择角色', '')
            for name in characters(): self.dating_character.addItem(name, name)
            self.dating_character.setMinimumWidth(180)
            self.dating_count = SpinBox(card.body)
            self.dating_count.setRange(1, 3)
            self.dating_count.setFixedWidth(100)
            row.addWidget(self.dating_character, 1)
            row.addWidget(QLabel('免费次数', card.body))
            row.addWidget(self.dating_count)
            layout.addLayout(row)
            self.dating_character.currentIndexChanged.connect(self._changed)
            self.dating_count.valueChanged.connect(self._changed)
            label('各地图地点优先顺序')
            self.location_choices = {}
            for map_id, locations in MAP_LOCATIONS.items():
                row = QHBoxLayout()
                row.addWidget(QLabel(map_id, card.body))
                choices = []
                for index in range(3):
                    choice = QComboBox(card.body)
                    choice.addItems(list(locations))
                    choice.setToolTip('地点优先顺序 ' + str(index + 1))
                    choice.currentTextChanged.connect(self._changed)
                    row.addWidget(choice, 1)
                    choices.append(choice)
                layout.addLayout(row)
                self.location_choices[map_id] = choices
        elif task == 'mad.claim_all':
            label('依次检查所选页面；活动等待单独规则。')
            for key, title in CLAIM_MODULES.items():
                check = CheckBox(title, card.body)
                check.setEnabled(key != 'activity')
                check.toggled.connect(self._changed)
                self.claim_checks[key] = check
                layout.addWidget(check)
            label('商城免费物品周期')
            row = QHBoxLayout()
            for key, title in [('daily', '每日'), ('weekly', '每周'), ('monthly', '每月')]:
                check = CheckBox(title, card.body)
                check.toggled.connect(self._changed)
                self.period_checks[key] = check
                row.addWidget(check)
            row.addStretch()
            layout.addLayout(row)
        else:
            label({'mad.mail': '领取邮箱内可领取的奖励。', 'mad.stamina_claim': '打开体力页面，领取每日累积的体力。',
                   'mad.arena': '竞技场尚未开放，暂不参与执行。', 'mad.event_sweep': '活动扫荡待适配，暂不参与执行。'}[task])

    def _parameters(self):
        params = deepcopy(self.base_config['routine'])
        for task, selector in self.sweep_selectors.items(): params[task[4:]]['plans'] = selector.value()
        params['gold_shop']['items'] = [{'item_id': key, 'count': self.shop_counts[key].value() or 'max'}
                                      for key, check in self.shop_checks.items() if check.isChecked()]
        params['dating'].update(character=self.dating_character.currentData() or '', count=self.dating_count.value())
        params['dating']['location_priority'] = {key: [c.currentText() for c in choices] for key, choices in self.location_choices.items()}
        params['claim_all'].update(modules={k: c.isChecked() for k, c in self.claim_checks.items()},
                                   mall_periods=[k for k, c in self.period_checks.items() if c.isChecked()])
        return params

    def _load(self):
        self._loading = True
        self._queue = [{'task_id': e['func_name'], 'enabled': e['enabled']} for e in sorted(self.base_events, key=lambda e: e['priority']) if e['func_name'] in ROUTINES]
        params = self.base_config['routine']
        for task, selector in self.sweep_selectors.items(): selector.setValue(params[task[4:]]['plans'])
        products = {p['item_id']: p['count'] for p in params['gold_shop']['items']}
        for key, check in self.shop_checks.items():
            check.setChecked(key in products)
            self.shop_counts[key].setValue(0 if products.get(key) == 'max' else products.get(key, 1))
            self.shop_counts[key].setEnabled(key in products)
        name = params['dating']['character']
        index = self.dating_character.findData(name)
        if index < 0 and name:
            self.dating_character.addItem(name + '（原配置）', name)
            index = self.dating_character.count() - 1
        self.dating_character.setCurrentIndex(max(0, index))
        self.dating_count.setValue(params['dating']['count'])
        for map_id, choices in self.location_choices.items():
            for choice, value in zip(choices, params['dating']['location_priority'][map_id]): choice.setCurrentText(value)
        for key, check in self.claim_checks.items(): check.setChecked(params['claim_all']['modules'][key])
        for key, check in self.period_checks.items(): check.setChecked(key in params['claim_all']['mall_periods'])
        for index, item in enumerate(self._queue): self.card_layout.insertWidget(index, self.cards[item['task_id']])
        self._loading = False
        self._changed()

    def _refresh_rows(self):
        params = self._parameters()
        for item in self._queue:
            task = item['task_id']
            card = self.cards[task]
            card.check.blockSignals(True)
            card.check.setChecked(item['enabled'])
            card.check.blockSignals(False)
            card.set_busy(self._busy, ROUTINES[task].supported)
            card.summary.setText(parameter_summary(task, params))
            result, reason = self._results.get(task, ('待适配' if not ROUTINES[task].supported else '', ''))
            card.set_result(result, reason, task == self._active)
        for task, selector in self.sweep_selectors.items(): selector.set_remaining(self.base_config['unfinished_tasks'].get(task, []))

    def _toggle(self, task, enabled):
        if self._busy or self._loading: return
        next(item for item in self._queue if item['task_id'] == task)['enabled'] = enabled
        self._changed()

    def move_task(self, task_id, delta):
        if self._busy: return
        index = next(i for i, item in enumerate(self._queue) if item['task_id'] == task_id)
        target = index + delta
        if 0 <= target < len(self._queue):
            self._queue[index], self._queue[target] = self._queue[target], self._queue[index]
            self._reorder()

    def drop_task(self, source, target, before):
        if self._busy or source == target or source not in self.cards: return
        item = next(p for p in self._queue if p['task_id'] == source)
        self._queue.remove(item)
        index = next(i for i, p in enumerate(self._queue) if p['task_id'] == target)
        self._queue.insert(index + (not before), item)
        self._reorder()

    def _reorder(self):
        for index, item in enumerate(self._queue): self.card_layout.insertWidget(index, self.cards[item['task_id']])
        self._changed()

    def open_settings(self, task_id):
        self.cards[task_id].set_expanded(True)
        self.ensureWidgetVisible(self.cards[task_id])

    def draft(self):
        config = deepcopy(self.base_config)
        config['routine'] = self._parameters()
        return config

    def has_unsaved_changes(self):
        original = [{'task_id': e['func_name'], 'enabled': e['enabled']} for e in sorted(self.base_events, key=lambda e: e['priority']) if e['func_name'] in ROUTINES]
        return self._parameters() != self.base_config['routine'] or self._queue != original

    def _changed(self, *_):
        if self._loading: return
        self._refresh_rows()
        dirty = self.has_unsaved_changes()
        self.save_button.setEnabled(dirty and not self._busy)
        self.cancel_button.setEnabled(dirty and not self._busy)
        self.feedback.setText('有未保存的更改' if dirty else '按列表顺序执行已启用任务')
        self.dirtyChanged.emit(dirty)

    def save_changes(self):
        if self._busy: return False
        try:
            params = self._parameters()
            if params != self.base_config['routine']:
                self.config_draft.set('routine', params)
                self.config_draft.commit()
            self.base_events = self.repository.save_events([{'func_name': p['task_id'], 'enabled': p['enabled'], 'priority': i} for i, p in enumerate(self._queue)], fields={'enabled', 'priority'})
            self.base_config = self.repository.load_config()
        except Exception as error:
            self.feedback.setText(f'保存失败：{error}；草稿已保留。')
            self.message.emit('ERROR', self.feedback.text())
            return False
        self._load()
        self.feedback.setText('已保存')
        self.saved.emit(deepcopy(self.base_config))
        return True

    def cancel_changes(self):
        if self._busy: return
        try:
            self.base_config = self.repository.load_config()
            self.base_events = self.repository.load_events()
            self.config_draft.rollback()
        except Exception as error:
            self.feedback.setText(f'重新载入失败：{error}；草稿已保留。')
            return
        self._load()

    def sync_profile(self, config):
        if not self.has_unsaved_changes():
            self.base_config = deepcopy(config)
            self.base_events = self.repository.load_events()
            self._load()

    def set_busy(self, busy):
        self._busy = busy
        self._changed()

    @staticmethod
    def remaining_text(plans):
        if not plans: return ''
        count = sum(p['count'] for p in plans if isinstance(p['count'], int))
        return f'待续 · 剩余 {count} 次' if all(isinstance(p['count'], int) for p in plans) else f'待续 · {len(plans)} 关'

    def on_event(self, event):
        kind = event.get('kind')
        if kind == 'task' and event.get('task_id') in ROUTINES:
            task = event['task_id']
            state = event.get('state')
            self._active = task if state == 'running' else None
            self.base_config['unfinished_tasks'] = self.repository.load_config()['unfinished_tasks']
            text = {'running': '执行中', 'succeeded': '完成', 'skipped': '已跳过', 'partial': '待续', 'needs_attention': '需处理', 'failed': '失败', 'stopped': '已停止'}.get(state, '')
            if state in ('succeeded', 'partial'): text = self.remaining_text(self.base_config['unfinished_tasks'].get(task, [])) or text
            self._results[task] = (text, event.get('message', ''))
        elif kind == 'result':
            names = {'SUCCESS': '完成', 'NOTHING_TO_CLAIM': '无可领', 'SKIPPED': '已跳过', 'PARTIAL': '待续', 'FAILED': '未完成', 'NEEDS_ATTENTION': '需处理', 'STOPPED': '已停止'}
            self.base_config['unfinished_tasks'] = self.repository.load_config()['unfinished_tasks']
            if self._active:
                self._results[self._active] = ('已停止' if event.get('state') == 'stopped' else '未完成', event.get('result', {}).get('error') or '')
            self._active = None
            for item in event.get('result', {}).get('tasks', []):
                task = item['task_id']
                plans = item.get('remaining', self.base_config['unfinished_tasks'].get(task, []))
                text = names.get(item['status'], item['status'])
                if item['status'] in ('SUCCESS', 'PARTIAL'): text = self.remaining_text(plans) or text
                self._results[task] = (text, item.get('reason', ''))
        elif kind == 'state' and event.get('state') == 'starting':
            self._results.clear()
            self._active = None
        else: return
        self._refresh_rows()

    def _apply_theme(self):
        self.theme.apply_scroll_surface(self, self.scrollWidget)
        for selector in self.sweep_selectors.values():
            self.theme.apply_surface(selector.table, 'input')
            self.theme.apply_surface(selector.table.viewport(), 'input')
        self.theme.apply_surface(self.shop_table, 'input')
        self.theme.apply_surface(self.shop_table.viewport(), 'input')
        self.feedback.setStyleSheet('color:' + self.theme.surfaces['muted'] + ';')
        apply_typography(self)
