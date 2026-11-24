"""Task cards edit the existing BAAS-style queue and configuration draft."""
from copy import deepcopy
from uuid import uuid4
from PyQt5.QtCore import pyqtSignal, Qt, QSize
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QHeaderView,
                            QDialog, QDialogButtonBox, QComboBox, QInputDialog,
                            QListWidgetItem, QAbstractItemView, QTableWidgetItem)
from qfluentwidgets import ScrollArea, CheckBox, SpinBox, PushButton, TableWidget, FlowLayout
from core.routine_catalog import ROUTINES, parameter_summary, CLAIM_MODULES, default_routine
from core.tasks import SWEEP_TASKS
from core.config.default_config import default_events
from core.config.repository import ConfigValidationError, instance_params
from core.material_store import MaterialStore, TASK as MATERIAL_TASK, clean_targets, copy_targets
from core.game_catalog import stage_options, characters, SHOP_ITEMS
from core.mad_features import MAP_LOCATIONS
from gui.widgets import TaskCard, CheckableListWidget
from gui.theme import typography, apply_typography
from gui.run_summary import RESULT_TEXT
from gui.selection_thumbnails import (decorate_item, prepare_thumbnail_combo,
    add_thumbnail_choice, action_icon)


class SweepSelector(QWidget):
    changed = pyqtSignal()

    def __init__(self, task, parent=None):
        super().__init__(parent)
        self.task = task
        self.options = stage_options(task)
        self._order, self.rows, self.remaining = [], {}, {}
        self._loading = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)
        self.table = TableWidget(self)
        self.table.setIconSize(QSize(36, 36))
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
        hint = ('MAX 使用本关当前可扫次数，不购买次数或体力' if task == 'mad.hard_sweep'
                else '按列表顺序扫荡 · MAX 为当前可扫最大次数')
        note = typography(QLabel(hint, self), 'caption')
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
            item = QTableWidgetItem(self.options.get(key, {}).get('title', key))
            decorate_item(item, 'stages', key)
            self.table.setItem(row, 0, item)
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

    def set_remaining(self, plans, new_instance=False):
        self.remaining = plans if isinstance(plans, dict) else {p['stage_id']: p['count'] for p in plans}
        for key, (row, _, _) in self.rows.items():
            self.table.item(row, 2).setText('保存后建立' if new_instance else str(self.remaining.get(key, 0)).upper())
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
        dialog.setWindowTitle('添加 HARD 关卡' if self.task == 'mad.hard_sweep' else '添加关卡')
        dialog.resize(450, 510)
        layout = QVBoxLayout(dialog)
        group = QComboBox(dialog)
        prepare_thumbnail_combo(group)
        group.addItem('全部分类')
        groups = {}
        for key, option in self.options.items(): groups.setdefault(option['group'], key)
        for title, key in groups.items(): add_thumbnail_choice(group, 'stages', key, title)
        layout.addWidget(group)
        caption = QLabel('点击整行勾选，可多选；已添加的关卡保持原顺序和次数。', dialog)
        caption.setWordWrap(True)
        layout.addWidget(caption)
        choices = CheckableListWidget(dialog)
        choices.setObjectName('stageChoices')
        choices.setIconSize(QSize(40, 40))
        for key, option in self.options.items():
            item = QListWidgetItem(option['title'], choices)
            decorate_item(item, 'stages', key)
            item.setSizeHint(QSize(0, 48))
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


class TaskEditor:
    """Widgets and draft values belonging to one task instance."""
    def __init__(self, task, card, changed, material_action=None):
        self.task, self._changed = task, changed
        self.material_action = material_action
        self.selector = None
        self.claim_checks, self.period_checks = {}, {}
        self._build_parameters(task, card)

    def _build_parameters(self, task, card):
        layout = card.body_layout
        def label(text):
            widget = typography(QLabel(text, card.body), 13)
            widget.setWordWrap(True)
            layout.addWidget(widget)
        if task in SWEEP_TASKS:
            selector = SweepSelector(task, card.body)
            selector.changed.connect(self._changed)
            self.selector = selector
            layout.addWidget(selector)
        elif task == 'mad.material_sweep':
            label('这条指令单独选择和排序素材，按权重分配体力；可选库存达标停止。')
            row = QHBoxLayout()
            self.material_buttons = {}
            for title,action in [('选择素材与排序','goals'),('查看扫荡安排','plan'),('刷新游戏数据','sync')]:
                button = PushButton(title,card.body)
                button.clicked.connect(lambda _,a=action:self.material_action(a))
                row.addWidget(button)
                self.material_buttons[action] = button
            layout.addLayout(row)
            row = QHBoxLayout(); row.addWidget(QLabel('保留体力',card.body))
            self.material_reserve = SpinBox(card.body); self.material_reserve.setRange(0,2147483647)
            self.material_reserve.valueChanged.connect(self._changed)
            row.addWidget(self.material_reserve); row.addStretch(); layout.addLayout(row)
        elif task == 'mad.gold_shop':
            label('选择要购买的普通商品，每项独立设置数量；0 为 MAX（买完当前可购买数量）。')
            self.shop_table = TableWidget(card.body)
            self.shop_table.setIconSize(QSize(36, 36))
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
                name = QTableWidgetItem(product['title'])
                decorate_item(name, 'shop', key)
                self.shop_table.setItem(row, 1, name)
                self.shop_table.setItem(row, 2, QTableWidgetItem(f'{product["price"]:,}'))
                self.shop_table.setCellWidget(row, 3, count)
                self.shop_table.setRowHeight(row, 42)
            self.shop_table.setFixedHeight(40 + len(SHOP_ITEMS) * 42)
            layout.addWidget(self.shop_table)
        elif task == 'mad.dating':
            row = QHBoxLayout()
            self.dating_character = QComboBox(card.body)
            self.dating_character.setAccessibleName('约会角色')
            prepare_thumbnail_combo(self.dating_character, QSize(40, 40))
            self.dating_character.view().setMinimumWidth(280)
            self.dating_character.addItem('请选择角色', '')
            for name in characters(): add_thumbnail_choice(self.dating_character, 'characters', name)
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
                label(map_id)
                row = FlowLayout()
                row.setContentsMargins(0, 0, 0, 0)
                row.setHorizontalSpacing(8); row.setVerticalSpacing(8)
                choices = []
                for index in range(3):
                    field = QWidget(card.body)
                    field_layout = QHBoxLayout(field); field_layout.setContentsMargins(0, 0, 0, 0)
                    field_layout.addWidget(QLabel(str(index + 1), field))
                    choice = QComboBox(card.body)
                    title = map_id + ' · 地点优先顺序 ' + str(index + 1)
                    choice.setAccessibleName(title)
                    prepare_thumbnail_combo(choice, QSize(48, 24), prefix=title)
                    choice.setMinimumWidth(220)
                    choice.view().setMinimumWidth(240)
                    for name in locations: add_thumbnail_choice(choice, 'places', name)
                    choice.currentTextChanged.connect(self._changed)
                    field_layout.addWidget(choice)
                    row.addWidget(field)
                    choices.append(choice)
                layout.addLayout(row)
                self.location_choices[map_id] = choices
        elif task == 'mad.claim_all':
            label('依次检查所选页面；活动等待单独规则。')
            for key, title in CLAIM_MODULES.items():
                check = CheckBox(title, card.body)
                check.setIcon(action_icon(key))
                check.setIconSize(QSize(24, 24))
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

    def value(self):
        params = deepcopy(self.base)
        if self.selector:
            params['plans'] = self.selector.value()
        elif self.task == 'mad.material_sweep': params['reserve'] = self.material_reserve.value()
        elif self.task == 'mad.gold_shop':
            params['items'] = [{'item_id': key, 'count': self.shop_counts[key].value() or 'max'}
                               for key, check in self.shop_checks.items() if check.isChecked()]
        elif self.task == 'mad.dating':
            params.update(character=self.dating_character.currentData() or '', count=self.dating_count.value(),
                          location_priority={k: [c.currentText() for c in v] for k, v in self.location_choices.items()})
        elif self.task == 'mad.claim_all':
            params.update(modules={k: c.isChecked() for k, c in self.claim_checks.items()},
                          mall_periods=[k for k, c in self.period_checks.items() if c.isChecked()])
        return params

    def load(self, params):
        self.base = deepcopy(params)
        if self.selector:
            self.selector.setValue(params['plans'])
        elif self.task == 'mad.material_sweep': self.material_reserve.setValue(params.get('reserve',0))
        elif self.task == 'mad.gold_shop':
            products = {p['item_id']: p['count'] for p in params['items']}
            for key, check in self.shop_checks.items():
                check.setChecked(key in products)
                self.shop_counts[key].setValue(0 if products.get(key) == 'max' else products.get(key, 1))
                self.shop_counts[key].setEnabled(key in products)
        elif self.task == 'mad.dating':
            name = params['character']
            index = self.dating_character.findData(name)
            if index < 0 and name:
                add_thumbnail_choice(self.dating_character, 'characters', name, name + '（原配置）')
                index = self.dating_character.count() - 1
            self.dating_character.setCurrentIndex(max(0, index))
            self.dating_count.setValue(params['count'])
            for map_id, choices in self.location_choices.items():
                for choice, value in zip(choices, params['location_priority'][map_id]): choice.setCurrentText(value)
        elif self.task == 'mad.claim_all':
            for key, check in self.claim_checks.items(): check.setChecked(params['modules'][key])
            for key, check in self.period_checks.items(): check.setChecked(key in params['mall_periods'])


class RoutineFragment(ScrollArea):
    materialRequested = pyqtSignal(str,str)
    saved = pyqtSignal(dict)
    message = pyqtSignal(str, str)
    dirtyChanged = pyqtSignal(bool)

    def __init__(self, repository, theme, parent=None, *, definition=None):
        super().__init__(parent)
        self.setObjectName('routineInterface')
        self.repository, self.theme = repository, theme
        self.definition_mode = definition is not None
        if self.definition_mode:
            self._set_definition(definition)
        else:
            self.base_config = repository.load_config()
            self.base_events = repository.load_events()
        self._busy, self._loading = False, True
        self._queue, self._results = [], {}
        self._active = None
        self.cards, self.editors, self.sweep_selectors, self.follow_choices = {}, {}, {}, {}
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scrollWidget = QWidget(self)
        self.card_layout = QVBoxLayout(self.scrollWidget)
        self.card_layout.setContentsMargins(0, 0, 10, 6)
        self.card_layout.setSpacing(0)
        self.add_button = PushButton('＋ 添加指令', self.scrollWidget)
        self.add_button.clicked.connect(self._choose_task)
        self.card_layout.addWidget(self.add_button)
        self.card_layout.addStretch()
        self.save_button = PushButton('保存更改', self)
        self.cancel_button = PushButton('撤销更改', self)
        self.feedback = typography(QLabel('', self), 12)
        self.feedback.setWordWrap(True)
        self.save_button.clicked.connect(self.save_changes)
        self.cancel_button.clicked.connect(self.cancel_changes)
        if self.definition_mode:
            for control in (self.save_button,self.cancel_button,self.feedback): control.hide()
        self.setWidget(self.scrollWidget)
        theme.changed.connect(self._apply_theme)
        self._load()
        self._apply_theme()

    def _event(self, key):
        return next(e for e in self._queue if e['instance_id'] == key)

    def _set_definition(self, spec):
        self.base_events = deepcopy(spec['events'])
        self.base_config = {'routine': {}, 'instance_params': {}, 'unfinished_tasks': {}}
        for e in self.base_events:
            key, task = e['instance_id'], e['func_name']
            if key == task: self.base_config['routine'][task[4:]] = deepcopy(spec['params_by_id'][key])
            else: self.base_config['instance_params'][key] = deepcopy(spec['params_by_id'][key])

    def load_definition(self, spec):
        self._set_definition(spec)
        self._load()

    def definition(self):
        events = [dict(deepcopy(e), priority=i, next_tick=0) for i,e in enumerate(self._queue)]
        return {'events': events, 'params_by_id': {key: ed.value() for key,ed in self.editors.items()}}

    def _choose_task(self):
        options = {s.title: k for k, s in ROUTINES.items() if s.supported}
        dialog = QInputDialog(self)
        dialog.setWindowTitle('添加指令'); dialog.setLabelText('选择功能')
        dialog.setComboBoxItems(list(options)); dialog.setComboBoxEditable(False)
        choice = dialog.findChild(QComboBox)
        prepare_thumbnail_combo(choice, QSize(24, 24))
        for i, task in enumerate(options.values()): choice.setItemIcon(i, action_icon(task))
        apply_typography(dialog)
        if dialog.exec_() == QDialog.Accepted: self.add_instance(options[dialog.textValue()])
        dialog.deleteLater()

    def add_instance(self, task, source=None):
        if self._busy or not ROUTINES[task].supported: return
        event = next(e for e in default_events() if e['func_name'] == task)
        if source:
            current = self._event(source) if self.definition_mode else next(
                (e for e in self.repository.load_events() if e['instance_id'] == source), self._event(source))
            for k in ('interval', 'daily_reset', 'disabled_time_range'):
                event[k] = deepcopy(current[k])
        params = self.editors[source].value() if source else default_routine().get(task[4:], {})
        if task==MATERIAL_TASK:
            original = MaterialStore(self.repository).targets(source,params) if source and self.repository else params.get('targets',[])
            params['targets'] = copy_targets(original) if source else []
        stem = ROUTINES[task].title
        if task == 'mad.hard_sweep' and not any(e['func_name'] == task for e in self._queue):
            # Older queues have no base HARD row. A date-only addition stays removable.
            key, name = (uuid4().hex if self.definition_mode else task), stem
        else:
            key = uuid4().hex
            names = {e['event_name'] for e in self._queue}
            number = 2
            while f'{stem} {number}' in names: number += 1
            name = f'{stem} {number}'
        event.update(instance_id=key, event_name=name, enabled=True)
        self._loading = True
        self._queue.append(event)
        self._make_card(event)
        self.editors[key].load(params)
        self._update_follow_choices()
        self._loading = False
        self._reorder()
        self.open_settings(key)
        return key

    def material_draft_destination(self, key):
        if self.definition_mode: return '保存排期'
        return None if any(e['instance_id']==key for e in self.base_events) else '保存更改'

    def apply_material_targets(self, key, targets, previous):
        if self._busy or key not in self.editors:
            raise ConfigValidationError('当前指令只读，请在可编辑的指令中修改目标。')
        if self.material_draft_destination(key):
            saved = clean_targets(targets,previous)
        else:
            saved = MaterialStore(self.repository).save_targets(targets,instance=key,expected=previous)['targets']
            # A dialog save must not apply unrelated queue drafts or reset a live clock.
            instance_params(self.base_config,self._event(key))['targets'] = deepcopy(saved)
        self.editors[key].base['targets'] = deepcopy(saved)
        self._changed()
        return saved

    def rename_instance(self, key, name):
        if self._busy or not name.strip(): return
        self._event(key)['event_name'] = name.strip()
        self._update_follow_choices()
        self._changed()

    def _ask_name(self, key):
        name, ok = QInputDialog.getText(self, '重命名指令', '指令名称', text=self._event(key)['event_name'])
        if ok: self.rename_instance(key, name)

    def remove_instance(self, key):
        if self._busy or key in ROUTINES: return
        if any(e.get('follow_after') == key or key in e.get('pre_task', []) + e.get('post_task', []) for e in self._queue):
            self.feedback.setText('其他指令仍引用此指令，请先解除关联。')
            return
        self._queue.remove(self._event(key))
        self._forget_card(key)
        self._update_follow_choices()
        self._changed()

    def _forget_card(self, key):
        card = self.cards.pop(key)
        self.card_layout.removeWidget(card)
        card.hide()
        card.deleteLater()
        self.editors.pop(key)
        self.sweep_selectors.pop(key, None)
        self.follow_choices.pop(key, None)
        self._results.pop(key, None)

    def _make_card(self, event):
        key, task = event['instance_id'], event['func_name']
        card = TaskCard(key, event['event_name'], self.theme, self.scrollWidget)
        self.cards[key] = card
        card.moveRequested.connect(self.move_task)
        card.dropRequested.connect(self.drop_task)
        card.check.toggled.connect(lambda enabled: self._toggle(key, enabled))
        if ROUTINES[task].supported:
            card.menu.addSeparator()
            card.menu.addAction('复制到末尾', lambda: self.add_instance(task, key))
            card.menu.addAction('重命名', lambda: self._ask_name(key))
            if key != task: card.menu.addAction('移除这条指令', lambda: self.remove_instance(key))
        editor = self.editors[key] = TaskEditor(task, card, self._changed,
                                               lambda action:self.materialRequested.emit(key,action))
        if editor.selector:
            self.sweep_selectors[key] = editor.selector
            if self.definition_mode: editor.selector.table.hideColumn(2)
        if key == task:
            aliases = {'mad.normal_sweep': 'normal', 'mad.procurement_sweep': 'procurement'}
            setattr(self, aliases.get(task, task[4:]), card.check)
            controls = {'mad.gold_shop': ('shop_table', 'shop_checks', 'shop_counts'),
                        'mad.claim_all': ('claim_checks', 'period_checks'),
                        'mad.dating': ('dating_character', 'dating_count', 'location_choices')}
            for field in controls.get(task, ()): setattr(self, field, getattr(editor, field))
        elif not self.definition_mode:
            row = QHBoxLayout()
            row.addWidget(QLabel('持续运行时', card.body))
            choice = self.follow_choices[key] = QComboBox(card.body)
            row.addWidget(choice, 1)
            card.body_layout.addLayout(row)
            choice.currentIndexChanged.connect(lambda _: self._set_follow(key, choice.currentData()))
        card.apply_theme()
        return card

    def _set_follow(self, key, parent_id):
        if self._loading or self._busy: return
        self._event(key)['follow_after'] = parent_id or ''
        self._update_follow_choices()
        self._changed()

    def _update_follow_choices(self):
        claims = [(e['instance_id'], e['event_name']) for e in self._queue
                  if e['func_name'] == 'mad.claim_all' and not e.get('follow_after')]
        parents = {e.get('follow_after') for e in self._queue if e.get('follow_after')}
        for key, combo in self.follow_choices.items():
            combo.blockSignals(True)
            combo.clear()
            combo.addItem('按自己的调度时间执行', '')
            for parent, name in claims:
                if key != parent: combo.addItem(action_icon('mad.claim_all'), '在「' + name + '」之后执行', parent)
            combo.setCurrentIndex(max(0, combo.findData(self._event(key).get('follow_after') or '')))
            combo.setEnabled(key not in parents)
            combo.setToolTip('有其他指令跟随本指令。' if key in parents else '')
            combo.blockSignals(False)

    def _load(self):
        self._loading = True
        self._queue = deepcopy(sorted(self.base_events, key=lambda e: e['priority']))
        active_keys = {e['instance_id'] for e in self._queue}
        for key in self.cards.keys() - active_keys: self._forget_card(key)
        for index, event in enumerate(self._queue):
            key = event['instance_id']
            if key not in self.cards: self._make_card(event)
            self.editors[key].load(instance_params(self.base_config, event))
            self.card_layout.insertWidget(index, self.cards[key])
        self._update_follow_choices()
        self._loading = False
        self._changed()

    def _refresh_rows(self):
        self.add_button.setEnabled(not self._busy)
        for item in self._queue:
            key, task = item['instance_id'], item['func_name']
            card = self.cards[key]
            name = item['event_name']
            card.title.setText(name)
            card.title.setToolTip(name + ' · ' + ROUTINES[task].title)
            card.check.setAccessibleName(name + '启用')
            card.setAccessibleName(name)
            card.expand.setAccessibleName(name + ('收起参数' if card.expand.isChecked() else '展开参数'))
            card.check.blockSignals(True)
            card.check.setChecked(item['enabled'])
            card.check.blockSignals(False)
            card.set_busy(self._busy, ROUTINES[task].supported)
            if task == 'mad.material_sweep':
                # A frozen day still exposes its derived table; only edits lock.
                card.body.setEnabled(True)
                editor = self.editors[key]
                editor.material_reserve.setEnabled(not self._busy)
                for action,button in editor.material_buttons.items(): button.setEnabled(action=='plan' or not self._busy)
                if key in self.follow_choices: self.follow_choices[key].setEnabled(not self._busy)
            card.summary.setText(parameter_summary(task, {task[4:]: self.editors[key].value()}))
            result, reason = self._results.get(key, ('待适配' if not ROUTINES[task].supported else '', ''))
            card.set_result(result, reason, key == self._active)
        saved_ids = {e['instance_id'] for e in self.base_events}
        for key, selector in self.sweep_selectors.items():
            selector.set_remaining(self.base_config['unfinished_tasks'].get(key, []), new_instance=key not in saved_ids)

    def _toggle(self, task, enabled):
        if self._busy or self._loading: return
        self._event(task)['enabled'] = enabled
        self._changed()

    def move_task(self, task_id, delta):
        if self._busy: return
        index = self._queue.index(self._event(task_id))
        target = index + delta
        if 0 <= target < len(self._queue):
            self._queue[index], self._queue[target] = self._queue[target], self._queue[index]
            self._reorder()

    def drop_task(self, source, target, before):
        if self._busy or source == target or source not in self.cards: return
        item = self._event(source)
        self._queue.remove(item)
        index = self._queue.index(self._event(target))
        self._queue.insert(index + (not before), item)
        self._reorder()

    def _reorder(self):
        for index, item in enumerate(self._queue): self.card_layout.insertWidget(index, self.cards[item['instance_id']])
        self._changed()

    def open_settings(self, task_id):
        self.cards[task_id].set_expanded(True)
        self.ensureWidgetVisible(self.cards[task_id])
        self.cards[task_id].expand.setFocus(Qt.OtherFocusReason)

    def draft(self):
        config = deepcopy(self.base_config)
        config['routine'] = self._parameters()
        config['instance_params'] = {key: ed.value() for key, ed in self.editors.items() if key != ed.task}
        return config

    def _parameters(self):
        return {k: self.editors['mad.' + k].value() for k in self.base_config['routine'] if 'mad.' + k in self.editors}

    def has_unsaved_changes(self):
        return (self._queue != sorted(self.base_events, key=lambda e: e['priority'])
                or any(self.editors[e['instance_id']].value() != instance_params(self.base_config, e) for e in self._queue))

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
            self.base_config, self.base_events = self.repository.save_routine_instances(
                self._queue, {key: ed.value() for key, ed in self.editors.items()})
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
        return f'有余项 · {count} 次' if all(isinstance(p['count'], int) for p in plans) else f'有余项 · {len(plans)} 关'

    def on_event(self, event):
        kind = event.get('kind')
        if kind == 'task' and event.get('task_id') in ROUTINES:
            task = event.get('instance_id', event['task_id'])
            state = event.get('state')
            self._active = task if state == 'running' else None
            self.base_config['unfinished_tasks'] = self.repository.load_config()['unfinished_tasks']
            text = {'running': '执行中', 'succeeded': '已完成', 'skipped': '已跳过', 'partial': '有余项', 'needs_attention': '需处理', 'failed': '未完成', 'stopped': '已停止'}.get(state, '')
            text = RESULT_TEXT.get(event.get('result'), text)
            if state in ('succeeded', 'partial'): text = self.remaining_text(self.base_config['unfinished_tasks'].get(task, [])) or text
            self._results[task] = (text, event.get('message', ''))
        elif kind == 'result':
            self.base_config['unfinished_tasks'] = self.repository.load_config()['unfinished_tasks']
            if self._active:
                self._results[self._active] = ('已停止' if event.get('state') == 'stopped' else '未完成', event.get('result', {}).get('error') or '')
            self._active = None
            for item in event.get('result', {}).get('tasks', []):
                task = item.get('instance_id', item['task_id'])
                plans = item.get('remaining', self.base_config['unfinished_tasks'].get(task, []))
                text = RESULT_TEXT.get(item['status'], item['status'])
                if item['status'] in ('SUCCESS', 'PARTIAL'): text = self.remaining_text(plans) or text
                self._results[task] = (text, item.get('reason', ''))
                if item['task_id']=='mad.material_sweep' and item['status']=='PARTIAL' and item.get('material_context') and self.repository:
                    from core.material_store import MaterialStore
                    store=MaterialStore(self.repository)
                    round_=store.state()['rounds'].get(item['material_context'])
                    if round_ and not store.needs_work(item['material_context'],item.get('material_allocation'),item.get('instance_id')):
                        self._results[task]=('已完成','本次安排和库存条件已完成。')
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
        for editor in self.editors.values():
            for key, check in editor.claim_checks.items(): check.setIcon(action_icon(key))
            if editor.task == 'mad.gold_shop':
                self.theme.apply_surface(editor.shop_table, 'input')
                self.theme.apply_surface(editor.shop_table.viewport(), 'input')
        for choice in self.follow_choices.values():
            for i in range(1, choice.count()): choice.setItemIcon(i, action_icon('mad.claim_all'))
        self.feedback.setStyleSheet('color:' + self.theme.surfaces['muted'] + ';')
        apply_typography(self)
