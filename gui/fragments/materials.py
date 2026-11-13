"""One shared target list and a read-only derived plan, with explicit overrides."""
from copy import deepcopy
from datetime import datetime
from PyQt5.QtCore import Qt, QSize, pyqtSignal
from PyQt5.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTabWidget,
                            QComboBox, QTableWidgetItem, QHeaderView, QAbstractItemView,
                            QInputDialog, QMessageBox, QDialogButtonBox, QListWidgetItem)
from qfluentwidgets import PushButton, PrimaryPushButton, SpinBox, CheckBox, TableWidget
from core.material_store import MaterialStore
from core.material_planner import catalog, plan
from core.plan_store import PlanStore
from gui.theme import typography, apply_typography
from gui.widgets import CheckableListWidget
from gui.material_picker import MaterialPicker, material_icon, material_tooltip


class MaterialDialog(QDialog):
    syncRequested = pyqtSignal()
    stopRequested = pyqtSignal()

    def __init__(self, repository, theme, instance, reserve=0, scope='routine', parent=None):
        super().__init__(parent)
        self.store, self.theme = MaterialStore(repository), theme
        self.instance, self.reserve, self.scope = instance, reserve, scope
        self.data = catalog()
        self.base = self.store.definitions()
        self.targets = deepcopy(self.base['targets'])
        self._busy = False
        self._picker_filter = ('voucher',2)
        self.setWindowTitle('素材目标 · 共享本配置')
        self.resize(1060,730)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(22,18,22,18); outer.setSpacing(12)
        outer.addWidget(typography(QLabel('库存达到目标，完成后停止补货'),22,True))
        self.note = QLabel('普通关卡 · 保存即应用；实际扫荡仍按日程顺序执行。')
        self.note.setWordWrap(True); outer.addWidget(self.note)
        self.tabs = QTabWidget(self); outer.addWidget(self.tabs,1)
        self.goals_page = QWidget(); goals = QVBoxLayout(self.goals_page)
        toolbar = QHBoxLayout()
        self.add = PushButton('＋ 添加素材'); toolbar.addWidget(self.add)
        self.remove = PushButton('移除'); toolbar.addWidget(self.remove)
        self.reopen = PushButton('重新开启'); toolbar.addWidget(self.reopen)
        self.correct = PushButton('纠正库存'); toolbar.addWidget(self.correct)
        self.exclude = PushButton('排除来源'); toolbar.addWidget(self.exclude)
        toolbar.addStretch(); goals.addLayout(toolbar)
        self.table = self.make_table(['启用','素材','最近库存','目标库存','缺口','优先级','状态'])
        self.table.setIconSize(QSize(32,36))
        self.table.setColumnWidth(0,52); self.table.setColumnWidth(2,114)
        self.table.setColumnWidth(3,190); self.table.setColumnWidth(4,110)
        self.table.setColumnWidth(5,100); self.table.setColumnWidth(6,110)
        self.table.horizontalHeader().setSectionResizeMode(1,QHeaderView.Stretch)
        goals.addWidget(self.table,1)
        self.inventory_note = QLabel('未知库存显示“待同步”，不会按零库存安排。')
        self.inventory_note.setWordWrap(True); goals.addWidget(self.inventory_note)
        self.tabs.addTab(self.goals_page,'共享目标')
        self.plan_page = QWidget(); planning = QVBoxLayout(self.plan_page)
        self.context = QLabel(); self.context.setWordWrap(True); planning.addWidget(self.context)
        self.preview = self.make_table(['关卡','关联素材','预计次数','体力','预计产出','安排'])
        self.preview.setColumnWidth(0,130); self.preview.setColumnWidth(2,80)
        self.preview.setColumnWidth(3,70); self.preview.setColumnWidth(4,160); self.preview.setColumnWidth(5,70)
        self.preview.horizontalHeader().setSectionResizeMode(1,QHeaderView.Stretch)
        planning.addWidget(self.preview,1)
        self.waiting = QLabel(); self.waiting.setWordWrap(True); planning.addWidget(self.waiting)
        rules = QHBoxLayout()
        self.rule_target = QComboBox(); self.rule_target.setMinimumWidth(180)
        self.rule_target.setIconSize(QSize(24,28))
        self.rule_stage = QComboBox(); self.rule_stage.setMinimumWidth(150)
        self.rule_cap = SpinBox(); self.rule_cap.setRange(-1,2147483647); self.rule_cap.setSpecialValueText('自动'); self.rule_cap.setValue(-1)
        self.rule_cap.setMinimumWidth(130)
        rules.addWidget(self.rule_target,1); rules.addWidget(self.rule_stage,1)
        rules.addWidget(QLabel('本轮最多')); rules.addWidget(self.rule_cap)
        self.apply_rule = PushButton('应用调整'); rules.addWidget(self.apply_rule)
        self.reset_rule = PushButton('恢复自动'); rules.addWidget(self.reset_rule)
        planning.addLayout(rules)
        hint = QLabel('调低次数后不会从其他关卡补回。指定来源和次数仅用于本轮；永久排除请在共享目标中设置。')
        hint.setWordWrap(True); planning.addWidget(hint)
        self.tabs.addTab(self.plan_page,'目标表')
        footer = QHBoxLayout()
        self.feedback = QLabel(); self.feedback.setWordWrap(True); footer.addWidget(self.feedback,1)
        self.review = PushButton('核对上批结果'); footer.addWidget(self.review)
        self.stop_button = PushButton('停止任务'); self.stop_button.hide(); footer.addWidget(self.stop_button)
        self.sync_button = PushButton('同步游戏数据'); footer.addWidget(self.sync_button)
        self.save_button = PrimaryPushButton('保存目标'); footer.addWidget(self.save_button)
        outer.addLayout(footer)
        self.add.clicked.connect(self.add_dialog); self.remove.clicked.connect(self.remove_target)
        self.reopen.clicked.connect(self.reopen_target); self.correct.clicked.connect(self.correct_stock)
        self.exclude.clicked.connect(self.exclude_sources)
        self.save_button.clicked.connect(self.save_targets); self.sync_button.clicked.connect(self.request_sync)
        self.apply_rule.clicked.connect(self.save_rule); self.reset_rule.clicked.connect(self.clear_rule)
        self.rule_target.currentIndexChanged.connect(self.load_rule)
        self.tabs.currentChanged.connect(lambda _:self.refresh_preview())
        self.review.clicked.connect(self.resolve_pending)
        self.stop_button.clicked.connect(self.stopRequested)
        self.render_targets(); self.refresh_preview()
        for surface in (self,self.tabs,self.goals_page,self.plan_page): theme.apply_surface(surface)
        s,c=theme.surfaces,theme.colors
        self.tabs.setStyleSheet(f'QTabWidget::pane {{border:1px solid {s["line"]};background:{s["page"]};}} '
            f'QTabBar::tab {{background:{s["card"]};color:{c["text"]};padding:8px 20px;border-bottom:2px solid transparent;}} '
            f'QTabBar::tab:selected {{border-bottom:2px solid {s["accent"]};}}')
        for table in (self.table,self.preview):
            theme.apply_surface(table,'input'); theme.apply_surface(table.viewport(),'input')
        apply_typography(self)

    def make_table(self, labels):
        table = TableWidget(self)
        table.setColumnCount(len(labels)); table.setHorizontalHeaderLabels(labels)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.verticalHeader().hide(); table.setShowGrid(False)
        return table

    def values(self):
        targets = deepcopy(self.targets)
        for row,t in enumerate(targets):
            t.update(enabled=self.table.cellWidget(row,0).isChecked(),
                     amount=self.table.cellWidget(row,3).value(),
                     priority=self.table.cellWidget(row,5).currentData())
        return targets

    def render_targets(self):
        state = self.store.state(); obs = self.store.preview_observation()
        self.table.setRowCount(len(self.targets))
        self.rule_target.blockSignals(True); self.rule_target.clear()
        for row,t in enumerate(self.targets):
            ref = t['ref']; item = self.data['items'][ref]
            check = CheckBox(); check.setChecked(t.get('enabled',True))
            self.table.setCellWidget(row,0,check)
            name = QTableWidgetItem(material_icon(item),item['name'])
            name.setToolTip(material_tooltip(item))
            self.table.setItem(row,1,name)
            owned = obs.get('inventory',{}).get(ref)
            self.table.setItem(row,2,QTableWidgetItem('待同步' if owned is None else str(owned)))
            amount = SpinBox(); amount.setRange(1,2147483647); amount.setValue(t['amount']); amount.setMinimumWidth(180)
            self.table.setCellWidget(row,3,amount)
            gap = QTableWidgetItem('—' if owned is None else str(max(0,t['amount']-owned)))
            self.table.setItem(row,4,gap)
            amount.valueChanged.connect(lambda n,r=row,q=owned:self.table.item(r,4).setText('—' if q is None else str(max(0,n-q))))
            priority = QComboBox(); priority.addItem('普通',1); priority.addItem('优先',2)
            priority.setCurrentIndex(priority.findData(t.get('priority',1))); self.table.setCellWidget(row,5,priority)
            done = self.store.token(t) in state['completed'] if t.get('version') else False
            status = '已暂停' if not t.get('enabled',True) else '重新开启' if t.get('reopen') else '已达成' if done else '待实机补验' if item['verification']=='public_table_pending_live' else '进行中'
            self.table.setItem(row,6,QTableWidgetItem(status))
            self.table.setRowHeight(row,48)
            self.rule_target.addItem(material_icon(item),item['name'],ref)
        self.rule_target.blockSignals(False); self.load_rule()
        at = obs.get('at')
        when = datetime.fromtimestamp(at).strftime('%m-%d %H:%M') if at else '尚未同步'
        manual = ' · 含手工值，执行时重新读取' if obs.get('source')=='manual' else ''
        self.inventory_note.setText('最近观察：'+when+manual+'。未知库存不会按零计算。')
        self.review.setVisible(bool(state['pending']))
        apply_typography(self.table)

    def selected_target(self):
        row = self.table.currentRow()
        if row < 0: self.feedback.setText('先选择一种素材。'); return None
        self.targets = self.values()
        return self.targets[row]

    def add_target(self, ref, amount=1):
        self.add_targets([ref],amount)

    def add_targets(self, refs, amount=1):
        self.targets = self.values()
        existing={t['ref'] for t in self.targets}
        first=len(self.targets)
        for ref in refs:
            if ref in existing: continue
            self.targets.append({'ref':ref,'amount':amount,'priority':1,'enabled':True,'excluded':[]})
            existing.add(ref)
        if first==len(self.targets): return
        self.render_targets()
        self.table.selectRow(first)
        self.table.scrollToItem(self.table.item(first,1))
        amount_box=self.table.cellWidget(first,3); amount_box.setFocus(); amount_box.selectAll()

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
        if target: target.update(reopen=True,enabled=True); self.render_targets()

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
        for stage in self.data['items'][target['ref']]['sources']:
            item = QListWidgetItem(stage.replace('normal:','NORMAL '),choices); item.setData(Qt.UserRole,stage)
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
            self.rule_stage.addItem(stage.replace('normal:','NORMAL '),stage)
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
        snapshot = frozen['snapshot'] if frozen else {'targets':self.store.definitions()['targets'],'catalog_version':self.data['version']}
        rules = snapshot.get('rules',{}).get(self.instance,{}) if frozen else self.store.adjustments(self.scope,self.instance)
        used = frozen['used'].get(self.instance,{}) if frozen else {}
        observation = self.store.preview_observation()
        future = self.scope.startswith('plan:') and self.scope[5:] != PlanStore(self.store.repository).today()
        if future: observation['balance'] = None
        self.context.setText((self.scope[5:] if self.scope.startswith('plan:') else '本轮普通日常')+
            (' · 已冻结，按本轮目标与规则显示' if frozen else ' · 保存目标默认应用')+
            ('\n未来日期不预分配今天的体力；执行时生成安排。' if future else '\n根据最近观察估算；每批最多 5 次，临近达标缩为单次。'))
        table = plan(snapshot,observation,state['completed'],rules,used,self.reserve)
        pending=state['pending']
        if pending or (frozen and self.instance in frozen['blocked']):
            reason=('上批消费结果待核对，暂不安排扫荡' if pending['phase']=='confirming' else
                    '上批次数已确认，待复读库存后更新') if pending else '本轮次数不明，这条指令的额度已结束'
            table={'rows':[], 'waiting':{t['ref']:reason for t in self.store.remaining(snapshot)}}
        self.preview.setRowCount(len(table['rows']))
        for i,row in enumerate(table['rows']):
            names = '、'.join(self.data['items'][r]['name'] for r in row['refs'])
            estimate = ' / '.join('单次后核对' if n is None else f'约 {n:g}' for n in row['estimated'].values())
            for j,value in enumerate([row['stage_id'].replace('normal:','NORMAL '),names,row['count'],row['cost'],estimate,'手动' if row['manual'] else '自动']):
                item = QTableWidgetItem(str(value)); item.setToolTip(names+'\n'+row['reason']+'；产出估计依据公开配表。')
                self.preview.setItem(i,j,item)
            self.preview.setRowHeight(i,42)
        waiting=[self.data['items'][r]['name']+'：'+why for r,why in table['waiting'].items()]
        self.waiting.setText('；'.join(waiting[:3])+('；另有 '+str(len(waiting)-3)+' 项待处理（悬停查看）' if len(waiting)>3 else '') or
                            ('当前没有待安排目标。' if not table['rows'] else '预计产出不代表实际获得，执行后以库存为准。'))
        self.waiting.setToolTip('\n'.join(waiting))
        for control in (self.rule_target,self.rule_stage,self.rule_cap,self.apply_rule,self.reset_rule):
            control.setEnabled(not frozen and not self._busy)

    def request_sync(self):
        if self.save_targets(): self.syncRequested.emit()

    def set_busy(self, busy):
        self._busy = busy
        self.stop_button.setVisible(busy)
        for control in (self.table,self.add,self.remove,self.reopen,self.correct,self.exclude,self.save_button,self.sync_button,self.review):
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
        self.feedback.setText('核对结果已保存，后续执行会重新读取库存。'); self.refreshed()

    def reject(self):
        if self.values()!=self.base['targets']:
            answer = QMessageBox.question(self,'未保存的素材目标','保存目标后关闭？',QMessageBox.Save|QMessageBox.Discard|QMessageBox.Cancel,QMessageBox.Save)
            if answer==QMessageBox.Cancel or (answer==QMessageBox.Save and not self.save_targets()): return
        super().reject()
