"""One shared target list and a read-only derived plan, with explicit overrides."""
from copy import deepcopy
from datetime import datetime
from PyQt5.QtCore import Qt, QSize, pyqtSignal, QMimeData
from PyQt5.QtGui import QDrag
from PyQt5.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTabWidget,
                            QComboBox, QTableWidgetItem, QAbstractItemView,
                            QInputDialog, QMessageBox, QDialogButtonBox, QListWidgetItem, QToolButton, QMenu, QAction)
from qfluentwidgets import PushButton, PrimaryPushButton, SpinBox, CheckBox, TableWidget
from core.material_store import MaterialStore
from core.material_planner import catalog, plan, stock_limited
from core.plan_store import PlanStore
from gui.theme import typography, apply_typography
from gui.widgets import CheckableListWidget
from gui.material_picker import MaterialPicker, material_icon, material_tooltip
from gui.selection_thumbnails import decorate_item, prepare_thumbnail_combo, add_thumbnail_choice


class MaterialTable(TableWidget):
    moved = pyqtSignal(int,int)
    MIME = 'application/x-mad-material-row'

    def __init__(self, parent, ordered=False):
        super().__init__(parent)
        if ordered:
            self.setDragEnabled(True); self.setAcceptDrops(True)
            self.setDragDropMode(QAbstractItemView.DragDrop); self.setDropIndicatorShown(True)

    def fit_name(self):
        others=sum(self.columnWidth(c) for c in range(self.columnCount()) if c!=1 and not self.isColumnHidden(c))
        self.setColumnWidth(1,max(240,self.viewport().width()-others))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_name()

    def startDrag(self, actions):
        if self.currentRow()<0: return
        mime=QMimeData(); mime.setData(self.MIME,str(self.currentRow()).encode())
        drag=QDrag(self); drag.setMimeData(mime); drag.exec_(Qt.MoveAction)

    def dragEnterEvent(self, event):
        if event.source() is self and event.mimeData().hasFormat(self.MIME): event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.source() is self and event.mimeData().hasFormat(self.MIME): event.acceptProposedAction()

    def dropEvent(self, event):
        if event.source() is not self or not event.mimeData().hasFormat(self.MIME): return
        row=self.indexAt(event.pos()).row()
        if row<0: row=self.rowCount()-1
        self.moved.emit(int(bytes(event.mimeData().data(self.MIME))),row)
        event.acceptProposedAction()


class MaterialDialog(QDialog):
    syncRequested = pyqtSignal()
    stopRequested = pyqtSignal()

    def __init__(self, repository, theme, instance, reserve=0, scope='routine', parent=None, *, instance_name=None):
        super().__init__(parent)
        self.store, self.theme = MaterialStore(repository), theme
        self.instance, self.reserve, self.scope = instance, reserve, scope
        self.instance_name = instance_name or next((e['event_name'] for e in repository.load_events() if e['instance_id']==instance),instance)
        self.data = catalog()
        self.base = self.store.definitions()
        self.targets = deepcopy(self.base['targets'])
        self._busy = False
        self._picker_filter = ('voucher',2)
        self.setWindowTitle('素材扫荡 · 共享本配置')
        self.resize(1060,730)
        self.setMinimumSize(760,540)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(22,18,22,18); outer.setSpacing(12)
        outer.addWidget(typography(QLabel('勾选素材，按优先级分配次数'),22,True))
        self.note = QLabel('先选的优先；拖动行或上移／下移调整。库存达标停止可单独开启，保存不启动游戏。')
        self.note.setWordWrap(True); outer.addWidget(self.note)
        self.tabs = QTabWidget(self); outer.addWidget(self.tabs,1)
        self.goals_page = QWidget(); goals = QVBoxLayout(self.goals_page)
        toolbar = QHBoxLayout()
        self.add = PushButton('＋ 添加素材'); toolbar.addWidget(self.add)
        self.up = PushButton('↑ 上移'); toolbar.addWidget(self.up)
        self.down = PushButton('↓ 下移'); toolbar.addWidget(self.down)
        self.remove = PushButton('移除'); toolbar.addWidget(self.remove)
        self.more = QToolButton(); self.more.setText('更多'); self.more.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self.more); self.more.setMenu(menu); toolbar.addWidget(self.more)
        self.reopen = menu.addAction('重新开启库存目标')
        self.correct = menu.addAction('纠正最近库存')
        self.exclude = menu.addAction('排除来源')
        menu.addSeparator(); self.disable_stock = menu.addAction('全部关闭库存停止条件…')
        toolbar.addStretch(); goals.addLayout(toolbar)
        self.table = self.make_table(['启用','素材','最近库存','达到库存','缺口','可选条件','状态'],ordered=True)
        self.table.verticalHeader().show()
        self.table.moved.connect(self.move_target)
        self.table.setIconSize(QSize(32,36))
        self.table.setColumnWidth(0,52); self.table.setColumnWidth(2,114)
        self.table.setColumnWidth(3,156); self.table.setColumnWidth(4,70)
        self.table.setColumnWidth(5,128); self.table.setColumnWidth(6,110)
        header=self.table.horizontalHeader()
        header.moveSection(header.visualIndex(5),2); header.moveSection(header.visualIndex(3),3)
        goals.addWidget(self.table,1)
        self.inventory_note = QLabel('未知库存显示“待同步”，不会按零库存安排。')
        self.inventory_note.setWordWrap(True); goals.addWidget(self.inventory_note)
        self.tabs.addTab(self.goals_page,'素材与排序')
        self.plan_page = QWidget(); planning = QVBoxLayout(self.plan_page)
        self.context = QLabel(); self.context.setWordWrap(True); planning.addWidget(self.context)
        self.preview = self.make_table(['关卡','关联素材','权重','计划次数','完成 / 剩余','余需体力','安排'])
        self.preview.setIconSize(QSize(32,32))
        self.preview.setColumnWidth(0,160); self.preview.setColumnWidth(2,60)
        self.preview.setColumnWidth(3,80); self.preview.setColumnWidth(4,100); self.preview.setColumnWidth(5,80); self.preview.setColumnWidth(6,70)
        planning.addWidget(self.preview,1)
        self.waiting = QLabel(); self.waiting.setWordWrap(True); planning.addWidget(self.waiting)
        sources = QHBoxLayout()
        self.rule_target = QComboBox(); self.rule_target.setMinimumWidth(180)
        self.rule_target.setIconSize(QSize(24,28))
        self.rule_stage = QComboBox(); self.rule_stage.setMinimumWidth(150)
        prepare_thumbnail_combo(self.rule_stage)
        self.rule_cap = SpinBox(); self.rule_cap.setRange(-1,2147483647); self.rule_cap.setSpecialValueText('自动'); self.rule_cap.setValue(-1)
        self.rule_cap.setMinimumWidth(130); self.rule_cap.setMaximumWidth(180)
        sources.addWidget(self.rule_target,1); sources.addWidget(self.rule_stage,1)
        planning.addLayout(sources)
        rules = QHBoxLayout()
        rules.addWidget(QLabel('本轮最多')); rules.addWidget(self.rule_cap)
        self.apply_rule = PushButton('应用调整'); rules.addWidget(self.apply_rule)
        self.reset_rule = PushButton('恢复自动'); rules.addWidget(self.reset_rule)
        rules.addStretch()
        planning.addLayout(rules)
        hint = QLabel('调低次数后不会从其他关卡补回。指定来源和次数仅用于本轮；永久排除请在共享目标中设置。')
        hint.setWordWrap(True); planning.addWidget(hint)
        self.tabs.addTab(self.plan_page,'扫荡安排')
        footer = QHBoxLayout()
        self.feedback = QLabel(); self.feedback.setWordWrap(True); footer.addWidget(self.feedback,1)
        self.review = PushButton('核对上批结果'); footer.addWidget(self.review)
        self.stop_button = PushButton('停止任务'); self.stop_button.hide(); footer.addWidget(self.stop_button)
        self.sync_button = PushButton('同步游戏数据'); footer.addWidget(self.sync_button)
        self.save_button = PrimaryPushButton('保存并应用'); footer.addWidget(self.save_button)
        outer.addLayout(footer)
        self.add.clicked.connect(self.add_dialog); self.remove.clicked.connect(self.remove_target)
        self.up.clicked.connect(lambda:self.move_target(self.table.currentRow(),self.table.currentRow()-1))
        self.down.clicked.connect(lambda:self.move_target(self.table.currentRow(),self.table.currentRow()+1))
        self.reopen.triggered.connect(self.reopen_target); self.correct.triggered.connect(self.correct_stock)
        self.exclude.triggered.connect(self.exclude_sources); self.disable_stock.triggered.connect(self.disable_stock_goals)
        for title,shortcut,delta in [('上移素材','Alt+Up',-1),('下移素材','Alt+Down',1)]:
            action=QAction(title,self.table); action.setShortcut(shortcut); action.setShortcutContext(Qt.WidgetWithChildrenShortcut)
            action.triggered.connect(lambda _,d=delta:self.move_target(self.table.currentRow(),self.table.currentRow()+d))
            self.table.addAction(action)
        self.save_button.clicked.connect(self.save_targets); self.sync_button.clicked.connect(self.request_sync)
        self.apply_rule.clicked.connect(self.save_rule); self.reset_rule.clicked.connect(self.clear_rule)
        self.rule_target.currentIndexChanged.connect(self.load_rule)
        self.tabs.currentChanged.connect(lambda _:self.refresh_preview())
        self.review.clicked.connect(self.resolve_pending)
        self.stop_button.clicked.connect(self.stopRequested)
        self.render_targets(); self.refresh_preview()
        theme.changed.connect(self.apply_theme)
        self.apply_theme()

    def apply_theme(self):
        theme=self.theme
        for surface in (self,self.tabs,self.goals_page,self.plan_page,self.more.menu()): theme.apply_surface(surface)
        s,c=theme.surfaces,theme.colors
        self.more.setStyleSheet(f'QToolButton {{padding:7px 12px;border:1px solid {s["line"]};border-radius:5px;'
            f'background:{s["card"]};color:{c["text"]};}} QToolButton:hover {{background:{s["selected"]};}}')
        self.more.menu().setStyleSheet(f'QMenu {{background:{s["card"]};color:{c["text"]};border:1px solid {s["line"]};}} '
            f'QMenu::item {{padding:8px 18px;}} QMenu::item:selected {{background:{s["selected"]};}}')
        self.tabs.setStyleSheet(f'QTabWidget::pane {{border:1px solid {s["line"]};background:{s["page"]};}} '
            f'QTabBar::tab {{background:{s["card"]};color:{c["text"]};padding:8px 20px;border-bottom:2px solid transparent;}} '
            f'QTabBar::tab:selected {{border-bottom:2px solid {s["accent"]};}}')
        for table in (self.table,self.preview):
            theme.apply_surface(table,'input'); theme.apply_surface(table.viewport(),'input')
        apply_typography(self)

    def make_table(self, labels, ordered=False):
        table = MaterialTable(self,ordered)
        table.setColumnCount(len(labels)); table.setHorizontalHeaderLabels(labels)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.verticalHeader().hide(); table.setShowGrid(False)
        return table

    def amount_box(self, row):
        return self.table.cellWidget(row,3).findChild(SpinBox)

    def values(self):
        targets = deepcopy(self.targets)
        for row,t in enumerate(targets):
            t.update(enabled=self.table.cellWidget(row,0).isChecked(),
                     amount=self.amount_box(row).value() or None,
                     stock_limit_enabled=self.table.cellWidget(row,5).isChecked())
            t.pop('priority',None)
        return targets

    def render_targets(self):
        state = self.store.state(); obs = self.store.preview_observation()
        self.table.setRowCount(len(self.targets))
        self.rule_target.blockSignals(True); self.rule_target.clear()
        for row,t in enumerate(self.targets):
            ref = t['ref']; item = self.data['items'][ref]
            check = CheckBox(); check.setChecked(t.get('enabled',True))
            check.setAccessibleName('启用'+item['name'])
            check.toggled.connect(self.update_stock_controls)
            self.table.setCellWidget(row,0,check)
            name = QTableWidgetItem(material_icon(item),item['name'])
            name.setToolTip(material_tooltip(item))
            self.table.setItem(row,1,name)
            owned = obs.get('inventory',{}).get(ref)
            self.table.setItem(row,2,QTableWidgetItem('待同步' if owned is None else str(owned)))
            at=obs.get('inventory_at',{}).get(ref,obs.get('at'))
            if at: self.table.item(row,2).setToolTip('库存观察于 '+datetime.fromtimestamp(at).strftime('%m-%d %H:%M'))
            amount = SpinBox(); amount.setRange(0,2147483647); amount.setSpecialValueText('未设置'); amount.setValue(t.get('amount') or 0); amount.setMinimumWidth(140)
            cell=QWidget(); layout=QHBoxLayout(cell); layout.setContentsMargins(0,0,0,0); layout.addWidget(amount)
            self.table.setCellWidget(row,3,cell)
            gap = QTableWidgetItem('—' if owned is None or not t.get('amount') else str(max(0,t['amount']-owned)))
            self.table.setItem(row,4,gap)
            amount.valueChanged.connect(self.update_stock_controls)
            condition = CheckBox('达标停止'); condition.setChecked(stock_limited(t))
            condition.setAccessibleName(item['name']+'达到库存后停止')
            self.table.setCellWidget(row,5,condition)
            condition.toggled.connect(self.update_stock_controls)
            done = self.store.token(t) in state['completed'] if t.get('version') else False
            status = '已暂停' if not t.get('enabled',True) else '按次数分配' if not stock_limited(t) else '重新开启' if t.get('reopen') else '已达成' if done else '待达标'
            self.table.setItem(row,6,QTableWidgetItem(status))
            self.table.setRowHeight(row,48)
            self.rule_target.addItem(material_icon(item),item['name'],ref)
        self.rule_target.blockSignals(False); self.load_rule()
        at = obs.get('at')
        when = datetime.fromtimestamp(at).strftime('%m-%d %H:%M') if at else '尚未同步'
        manual = ' · 含手工值，执行时重新读取' if obs.get('source')=='manual' else ''
        self.inventory_note.setText('最近读取游戏数据：'+when+manual+'。仅开启库存条件的素材需要读取库存。')
        self.review.setVisible(bool(state['pending']))
        self.update_stock_controls()
        apply_typography(self.table)

    def update_stock_controls(self):
        flags=[self.table.cellWidget(row,5).isChecked() for row in range(self.table.rowCount())]
        obs=self.store.preview_observation(); completed=self.store.state()['completed']
        for col in (2,3,4): self.table.setColumnHidden(col,not any(flags))
        for row,enabled in enumerate(flags):
            target=self.targets[row]; amount=self.amount_box(row).value()
            self.amount_box(row).setVisible(enabled)
            self.amount_box(row).setEnabled(enabled and not self._busy)
            owned=obs.get('inventory',{}).get(target['ref'])
            self.table.item(row,2).setText(('待同步' if owned is None else str(owned)) if enabled else '不读取')
            self.table.item(row,4).setText(str(max(0,amount-owned)) if enabled and owned is not None and amount else '—')
            done=bool(target.get('version') and self.store.token(target) in completed and amount==target.get('amount'))
            status=('已暂停' if not self.table.cellWidget(row,0).isChecked() else '按次数分配' if not enabled else
                    '待设置数量' if not amount else '重新开启' if target.get('reopen') else '已达成' if done else '待达标')
            self.table.item(row,6).setText(status)
        self.sync_button.setText('同步游戏数据' if any(flags) else '刷新可扫关卡和体力')
        self.table.fit_name()

    def move_target(self, source, target):
        if self._busy or not (0<=source<len(self.targets) and 0<=target<len(self.targets)) or source==target: return
        self.targets=self.values(); self.targets.insert(target,self.targets.pop(source))
        self.render_targets(); self.table.selectRow(target); self.table.scrollToItem(self.table.item(target,1)); self.table.setFocus()

    def disable_stock_goals(self):
        if self._busy: return
        if QMessageBox.question(self,'改为按次数分配','关闭全部库存停止条件后，所选素材将按可用体力持续参与每次分配。原数量和历史记录保留，保存后生效。',
                QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes: return
        self.targets=self.values()
        for target in self.targets: target['stock_limit_enabled']=False
        self.render_targets()

    def selected_target(self):
        row = self.table.currentRow()
        if row < 0: self.feedback.setText('先选择一种素材。'); return None
        self.targets = self.values()
        return self.targets[row]

    def add_target(self, ref, amount=None):
        self.add_targets([ref],amount)

    def add_targets(self, refs, amount=None):
        self.targets = self.values()
        existing={t['ref'] for t in self.targets}
        first=len(self.targets)
        for ref in refs:
            if ref in existing: continue
            self.targets.append({'ref':ref,'amount':amount,'stock_limit_enabled':amount is not None,'enabled':True,'excluded':[]})
            existing.add(ref)
        if first==len(self.targets): return
        self.render_targets()
        self.table.selectRow(first)
        self.table.scrollToItem(self.table.item(first,1))
        if amount is not None:
            amount_box=self.amount_box(first); amount_box.setFocus(); amount_box.selectAll()
        else: self.table.setFocus()

    def add_dialog(self):
        picker=MaterialPicker(self.data['items'],{t['ref'] for t in self.targets},self.theme,self,
                              category=self._picker_filter[0],tier=self._picker_filter[1])
        if picker.exec_()==QDialog.Accepted: self.add_targets(picker.selection)
        self._picker_filter=picker.category,picker.tier
        picker.deleteLater()

    def remove_target(self):
        target = self.selected_target()
        if target: self.targets.remove(target); self.render_targets()

    def reopen_target(self):
        target = self.selected_target()
        if target and stock_limited(target): target.update(reopen=True,enabled=True); self.render_targets()
        elif target: self.feedback.setText('这项未开启库存停止条件，无需重新开启。')

    def correct_stock(self):
        target = self.selected_target()
        if not target: return
        value,ok = QInputDialog.getInt(self,'纠正最近库存','仅修正预览，有效 30 分钟；执行时仍会重新读取游戏',0,0,2147483647)
        if ok:
            self.store.correct_inventory(target['ref'],value); self.render_targets(); self.refresh_preview()

    def exclude_sources(self):
        target = self.selected_target()
        if not target: return
        dialog = QDialog(self); dialog.setWindowTitle('永久排除来源'); dialog.resize(400,460)
        layout = QVBoxLayout(dialog); choices = CheckableListWidget(dialog); layout.addWidget(choices)
        choices.setIconSize(QSize(40,40))
        for stage in self.data['items'][target['ref']]['sources']:
            item = QListWidgetItem(stage.replace('normal:','NORMAL '),choices); item.setData(Qt.UserRole,stage)
            decorate_item(item,'stages',stage); item.setSizeHint(QSize(0,48))
            item.setFlags(Qt.ItemIsEnabled|Qt.ItemIsUserCheckable|Qt.ItemIsSelectable)
            item.setCheckState(Qt.Checked if stage in target.get('excluded',[]) else Qt.Unchecked)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel); layout.addWidget(buttons)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject)
        if dialog.exec_()==QDialog.Accepted:
            target['excluded'] = [choices.item(i).data(Qt.UserRole) for i in range(choices.count()) if choices.item(i).checkState()==Qt.Checked]
            self.feedback.setText('排除列表已修改，保存目标后生效。')

    def save_targets(self):
        if self._busy: return False
        try: self.base = self.store.save_targets(self.values(),self.base['revision'])
        except (ValueError,OSError) as exc: self.feedback.setText(str(exc)); return False
        self.targets = deepcopy(self.base['targets']); self.render_targets(); self.refresh_preview()
        self.feedback.setText('已保存并应用。'+('本轮已冻结，修改用于后续轮次。' if self.store.active_context(self.scope) else ''))
        return True

    def load_rule(self):
        ref = self.rule_target.currentData()
        self.rule_stage.clear(); self.rule_stage.addItem('自动选择来源',None)
        if not ref: return
        for stage in self.data['items'][ref]['sources']:
            add_thumbnail_choice(self.rule_stage,'stages',stage,stage.replace('normal:','NORMAL '))
        context = self.store.active_context(self.scope)
        state = self.store.state()
        rules = (state['rounds'][context]['snapshot']['rules'].get(self.instance,{}) if context
                 else self.store.adjustments(self.scope,self.instance))
        rule = rules.get(ref,{})
        self.rule_stage.setCurrentIndex(max(0,self.rule_stage.findData(rule.get('stage'))))
        self.rule_cap.setValue(rule['max_runs'] if rule.get('max_runs') is not None else -1)

    def save_rule(self, reset=False):
        ref = self.rule_target.currentData()
        if not ref or self._busy: return
        rules = self.store.adjustments(self.scope,self.instance)
        if reset: rules.pop(ref,None)
        else: rules[ref] = {'stage':self.rule_stage.currentData(),'max_runs':None if self.rule_cap.value()<0 else self.rule_cap.value()}
        try: self.store.set_adjustments(self.scope,self.instance,rules)
        except (ValueError,OSError) as exc: self.feedback.setText(str(exc)); return
        self.feedback.setText('本轮安排已应用。'); self.load_rule(); self.refresh_preview()

    def clear_rule(self): self.save_rule(reset=True)

    def refresh_preview(self):
        state = self.store.state(); context = self.store.active_context(self.scope)
        frozen = state['rounds'].get(context)
        snapshot = frozen['snapshot'] if frozen else {'targets':self.store.definitions()['targets'],'catalog_version':self.data['version'],'allocation_version':2}
        rules = snapshot.get('rules',{}).get(self.instance,{}) if frozen else self.store.adjustments(self.scope,self.instance)
        used = frozen['used'].get(self.instance,{}) if frozen else {}
        observation = self.store.preview_observation()
        future = self.scope.startswith('plan:') and self.scope[5:] != PlanStore(self.store.repository).today()
        if future: observation['balance'] = None
        self.context.setText((self.scope[5:] if self.scope.startswith('plan:') else '本轮普通日常')+' · '+self.instance_name+
            (' · 已冻结，按本轮目标与规则显示' if frozen else ' · 保存目标默认应用')+
            ('\n未来日期不预分配今天的体力；执行时生成安排。' if future else '\n权重按素材顺序计算，同关取最高；未开启库存条件时不看掉落数量。'))
        self.context.setToolTip('指令编号：'+self.instance)
        table = plan(snapshot,observation,state['completed'],rules,used,self.reserve)
        records=[a for a in frozen.get('allocations',{}).values() if a['instance']==self.instance] if frozen else []
        allocation=next((a for a in records if a.get('waiting_data') or any(r['count'] for r in a['rows'])),records[-1] if records else None)
        if allocation:
            table={'rows':deepcopy(allocation['rows']),'waiting':allocation['waiting']}
            stages={r['stage_id'] for r in table['rows']}
            for stage,done in allocation['by_stage'].items():
                if stage not in stages:
                    table['rows'].append(dict(stage_id=stage,count=0,cost=0,refs=[t['ref'] for t in snapshot['targets'] if t['ref'] in self.data['stages'][stage]['drops']],manual=False,reason='已经执行'))
            self.context.setText(self.context.text()+'\n显示已保存次数安排：累计完成 '+str(allocation['completed'])+' 次。')
        pending=state['pending']
        if pending or (frozen and self.instance in frozen['blocked']):
            reason=('上批消费结果待核对，暂不安排扫荡' if pending['phase']=='confirming' else
                    '上批次数已确认，待复读库存后更新') if pending else '本轮次数不明，这条指令的额度已结束'
            table={'rows':[], 'waiting':{t['ref']:reason for t in self.store.remaining(snapshot)}}
        self.preview.setRowCount(len(table['rows']))
        for i,row in enumerate(table['rows']):
            names = '、'.join(self.data['items'][r]['name'] for r in row['refs'])
            done=allocation['by_stage'].get(row['stage_id'],0) if allocation else 0
            for j,value in enumerate([row['stage_id'].replace('normal:','NORMAL '),names,row.get('weight','—'),row['count']+done,
                                      f'{done} / {row["count"]}',row['cost'],'手动' if row['manual'] else '自动']):
                item = QTableWidgetItem(str(value)); item.setToolTip(names+'\n'+row['reason'])
                if j==0: decorate_item(item,'stages',row['stage_id'])
                self.preview.setItem(i,j,item)
            self.preview.setRowHeight(i,42)
        waiting=[self.data['items'].get(r,{}).get('name','读取游戏数据')+'：'+why for r,why in table['waiting'].items()]
        self.waiting.setText('；'.join(waiting[:3])+('；另有 '+str(len(waiting)-3)+' 项待处理（悬停查看）' if len(waiting)>3 else '') or
                            ('当前没有待安排次数。' if not table['rows'] else '实际扫荡次数以结算为准；不根据掉落数量重分配。'))
        self.waiting.setToolTip('\n'.join(waiting))
        for control in (self.rule_target,self.rule_stage,self.rule_cap,self.apply_rule,self.reset_rule):
            control.setEnabled(not frozen and not self._busy)

    def request_sync(self):
        if self.save_targets(): self.syncRequested.emit()

    def set_busy(self, busy):
        self._busy = busy
        self.stop_button.setVisible(busy)
        for control in (self.table,self.add,self.remove,self.up,self.down,self.more,self.save_button,self.sync_button,self.review):
            control.setEnabled(not busy)
        self.refresh_preview()
        if busy: self.feedback.setText('任务运行中，目标与调整暂时只读。')

    def refreshed(self):
        self.targets = self.values(); self.render_targets(); self.refresh_preview()

    def resolve_pending(self):
        pending=self.store.state()['pending']
        if not pending: return
        known=pending['phase']=='result_observed'
        box = QMessageBox(self); box.setWindowTitle('核对素材扫荡')
        box.setText(f'已看到上批扫荡结果，共 {pending["count"]} 次；库存复读未完成。保存已确认次数后，下次执行重新读取库存。' if known else
                    '请先在游戏中核对上批是否发生消费。次数未知时，结束这条指令本轮额度，不推测扫荡次数。')
        done = box.addButton('保存已确认次数' if known else '已执行 / 次数不明',QMessageBox.AcceptRole)
        retry = box.addButton('确认未执行',QMessageBox.ActionRole)
        retry.setEnabled(not known)
        cancel = box.addButton('稍后处理',QMessageBox.RejectRole); box.setDefaultButton(cancel)
        box.exec_()
        if box.clickedButton() not in (done,retry): return
        try: self.store.resolve_pending(box.clickedButton()==done)
        except (ValueError,OSError) as exc: self.feedback.setText(str(exc)); return
        self.feedback.setText('核对结果已保存，后续执行按原配额和已开启的库存条件恢复。'); self.refreshed()

    def reject(self):
        if self.values()!=self.base['targets']:
            answer = QMessageBox.question(self,'未保存的素材目标','保存目标后关闭？',QMessageBox.Save|QMessageBox.Discard|QMessageBox.Cancel,QMessageBox.Save)
            if answer==QMessageBox.Cancel or (answer==QMessageBox.Save and not self.save_targets()): return
        super().reject()
