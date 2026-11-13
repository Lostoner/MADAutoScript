"""Seven-game-day calendar. Date drafts reuse the ordinary instruction editor."""
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path

from PyQt5.QtCore import Qt, QDate, QTime, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (QWidget, QLabel, QVBoxLayout, QHBoxLayout, QFormLayout,
    QDateEdit, QTimeEdit, QLineEdit, QDialog, QDialogButtonBox, QListWidget, QListWidgetItem,
    QStackedWidget, QSplitter, QMenu, QInputDialog, QMessageBox, QTextEdit, QCheckBox, QTabWidget)
from qfluentwidgets import PushButton, PrimaryPushButton
from core.config.default_config import default_events
from core.routine_catalog import default_routine, parameter_summary
from core.game_catalog import stage_options
from core.config.schedule_fields import format_periods
from gui.fragments.routine import RoutineFragment
from gui.theme import typography


STATUS = {'ready':'待执行','running':'执行中','waiting_device':'待设备','stopped':'已停止',
          'failed':'执行失败','needs_review':'待核对','partial':'已执行 · 有余项',
          'completed':'已结束','expired':'已归档','missed':'已错过','paused':'已暂停'}
WEEK = '一二三四五六日'

def shift(day, n):
    return (date.fromisoformat(day) + timedelta(days=n)).isoformat()

def count(day):
    return sum(bool(e['enabled']) for e in day.get('routine',{}).get('events',[]))

def time_control(value):
    widget = QTimeEdit(QTime.fromString(value[:5],'HH:mm'))
    widget.setDisplayFormat('HH:mm')
    return widget

def date_control(value):
    widget=QDateEdit(QDate.fromString(value,'yyyy-MM-dd'))
    widget.setDisplayFormat('yyyy-MM-dd'); widget.setCalendarPopup(True)
    return widget

def buttons(parent, accept='确定'):
    box=QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel,parent=parent)
    box.button(QDialogButtonBox.Ok).setText(accept); box.button(QDialogButtonBox.Cancel).setText('取消')
    box.accepted.connect(parent.accept); box.rejected.connect(parent.reject)
    return box

class PlanFragment(QWidget):
    materialRequested = pyqtSignal(str,str,str)
    saved = pyqtSignal()
    startRequested = pyqtSignal()
    resumeRemainingRequested = pyqtSignal()
    autoRequested = pyqtSignal(bool)
    stopTodayRequested = pyqtSignal()

    def __init__(self, store, theme, parent=None):
        super().__init__(parent)
        self.store,self.theme=store,theme
        self.base=store.load(); self.draft=deepcopy(self.base)
        self.day=self._clamp(store.today()); self.week=self.day
        self._loading=False; self._runtime=('','',''); self.editor=None
        outer=QVBoxLayout(self); outer.setContentsMargins(10,8,10,8); outer.setSpacing(10)
        head=QHBoxLayout()
        self.heading=typography(QLabel('日程计划'),22,True)
        self.range_label=typography(QLabel(),13)
        self.options=PushButton('排期设置'); self.options.clicked.connect(self._settings)
        archive=PushButton('历史记录'); archive.clicked.connect(self._choose_history)
        head.addWidget(self.heading); head.addSpacing(8); head.addWidget(self.range_label,1); head.addWidget(archive); head.addWidget(self.options)
        outer.addLayout(head)
        self.horizon=QLabel(); self.horizon.setWordWrap(True); outer.addWidget(self.horizon)
        splitter=QSplitter(Qt.Horizontal); outer.addWidget(splitter,1)
        left=QWidget(); left.setMinimumWidth(218); ll=QVBoxLayout(left); ll.setContentsMargins(0,0,10,0)
        nav=QHBoxLayout(); self.prev=PushButton('‹'); self.next=PushButton('›')
        for b,hint in ((self.prev,'上一周'),(self.next,'下一周')):
            b.setFixedWidth(34); b.setAccessibleName(hint); b.setToolTip(hint)
        self.prev.clicked.connect(lambda:self._page(-7)); self.next.clicked.connect(lambda:self._page(7))
        self.week_title=typography(QLabel(),13,True); self.week_title.setAlignment(Qt.AlignCenter)
        nav.addWidget(self.prev); nav.addWidget(self.week_title,1); nav.addWidget(self.next); ll.addLayout(nav)
        self.days=QListWidget(); self.days.setWordWrap(True); self.days.currentItemChanged.connect(self._select)
        ll.addWidget(self.days,1)
        self.week_copy=PushButton('复制本周到下周…'); self.week_copy.clicked.connect(self._copy_week); ll.addWidget(self.week_copy)
        splitter.addWidget(left)
        right=QWidget(); r=QVBoxLayout(right); r.setContentsMargins(10,0,0,0)
        top=QHBoxLayout(); self.day_title=typography(QLabel(),17,True); top.addWidget(self.day_title,1)
        self.copy_day=PushButton('复制到日期…');self.copy_day.clicked.connect(self._copy_dialog);top.addWidget(self.copy_day)
        self.history=PushButton('当日记录'); self.history.clicked.connect(lambda:self._history(self.day)); top.addWidget(self.history)
        self.actions=PushButton('日期操作  ▾'); self.actions.clicked.connect(self._menu); top.addWidget(self.actions)
        r.addLayout(top)
        self.fields=QWidget(); f=QHBoxLayout(self.fields); f.setContentsMargins(0,0,0,0)
        self.name=QLineEdit(); self.name.setPlaceholderText('一日任务名称'); self.name.setAccessibleName('一日任务名称')
        self.name.textEdited.connect(self._edit_meta)
        self.override=QCheckBox('单独设时'); self.override.toggled.connect(self._edit_meta)
        self.clock=time_control('04:00'); self.clock.timeChanged.connect(self._edit_meta)
        f.addWidget(self.name,1); f.addWidget(self.override); f.addWidget(self.clock)
        r.addWidget(self.fields)
        self.day_note=QLabel(); self.day_note.setWordWrap(True); r.addWidget(self.day_note)
        self.stack=QStackedWidget(); r.addWidget(self.stack,1)
        empty=QWidget(); e=QVBoxLayout(empty); e.setContentsMargins(20,16,20,16); e.addStretch()
        self.empty_title=typography(QLabel(),20,True); self.empty_title.setAlignment(Qt.AlignCenter); e.addWidget(self.empty_title)
        self.empty_note=QLabel(); self.empty_note.setWordWrap(True); self.empty_note.setAlignment(Qt.AlignCenter); e.addWidget(self.empty_note)
        row=QHBoxLayout(); row.addStretch()
        self.from_daily=PrimaryPushButton('从当前日常复制'); self.from_daily.clicked.connect(self.use_daily)
        self.use_template=PushButton('使用模板…'); self.use_template.clicked.connect(self._use_template)
        row.addWidget(self.from_daily); row.addWidget(self.use_template); row.addStretch(); e.addLayout(row); e.addStretch()
        self.stack.addWidget(empty); splitter.addWidget(right); splitter.setSizes([240,760]); splitter.setStretchFactor(1,1)
        self.feedback=QLabel(); self.feedback.setWordWrap(True); outer.addWidget(self.feedback)
        foot=QHBoxLayout()
        self.save_button=PushButton('保存排期'); self.save_button.clicked.connect(self._confirm_save)
        self.undo=PushButton('撤销'); self.undo.clicked.connect(self.cancel_changes)
        self.auto=PushButton(); self.auto.clicked.connect(self._toggle_auto)
        self.remain=PushButton('仅续做余项…'); self.remain.clicked.connect(self._resume_remaining)
        self.stop=PushButton('停止今日'); self.stop.clicked.connect(self.stopTodayRequested)
        self.start=PrimaryPushButton('开始／继续今日'); self.start.clicked.connect(lambda:self._request(self.startRequested))
        for b in (self.save_button,self.undo): foot.addWidget(b)
        foot.addStretch()
        for b in (self.auto,self.remain,self.stop,self.start): foot.addWidget(b)
        outer.addLayout(foot)
        theme.changed.connect(self._theme); self._theme()
        self._render()

    def _theme(self):
        s=self.theme.surfaces; text=self.theme.colors['text']
        self.theme.apply_surface(self)
        self.setStyleSheet(f'QDialog {{background:{s["window"]};color:{text};}} QDialog QLabel {{color:{text};}} '
            f'QDialog QTextEdit,QDialog QListWidget,QDialog QLineEdit,QDialog QDateTimeEdit {{background:{s["input"]};color:{text};border:1px solid {s["line"]};padding:4px;}} '
            f'QDialog QPushButton,QTabBar::tab {{background:{s["card"]};color:{text};border:1px solid {s["line"]};padding:5px 10px;}} '
            f'QTabBar::tab:selected {{background:{s["selected"]};}} QTabWidget::pane {{border:0;}}')
        self.days.setStyleSheet(f'QListWidget {{background:{s["card"]};color:{text};border:1px solid {s["line"]};border-radius:7px;}} '
            f'QListWidget::item {{padding:7px;}} QListWidget::item:selected {{background:{s["selected"]};color:{text};border-left:3px solid {s["accent"]};}}')
        for w in (self.day_note,self.range_label,self.empty_note,self.feedback):
            w.setStyleSheet('color:'+s['muted']+';')
        self.horizon.setStyleSheet('color:'+self.theme.colors['text__warning']+';')

    def _clamp(self,key):
        return min(max(key,self.draft['start']),self.draft['end'])

    def _locked(self,key):
        return key < self.store.today() or bool(self.store.record(key).get('frozen'))

    def _time_label(self,day):
        value=day.get('time') or self.draft['default_time']
        return ('次日 ' if value < self.draft['reset_at'][:5] else '')+value

    def _day_summary(self,key,today=None):
        day=self.draft['days'].get(key,{})
        status=self.store.record(key).get('status')
        if self._runtime[0]==key and self._runtime[1] in STATUS:
            status=self._runtime[1]
        if day.get('kind')=='tasks':
            desc=day.get('name') or '一日任务'
            state=STATUS.get(status,'已错过' if key < (today or self.store.today()) else f'{count(day)} 条指令')
            return f'{self._time_label(day)}  {desc} · {state}'
        return '休息' if day else '未安排'

    def _paint_week(self):
        self.days.blockSignals(True); self.days.clear()
        end=min(shift(self.week,6),self.draft['end'])
        today=self.store.today()
        self.week_title.setText(f'{self.week[5:]} 至 {end[5:]}')
        for i in range(7):
            key=shift(self.week,i)
            if key>end: break
            prefix='今天 · ' if key==today else ''
            item=QListWidgetItem(f'{prefix}{key[5:]}   周{WEEK[date.fromisoformat(key).weekday()]}\n{self._day_summary(key,today)}')
            item.setData(Qt.UserRole,key); item.setToolTip(item.text())
            self.days.addItem(item)
            if key==self.day: self.days.setCurrentItem(item)
        self.days.blockSignals(False)
        self.prev.setEnabled(self.week>self.draft['start']); self.next.setEnabled(end<self.draft['end'])

    def _page(self,delta):
        self.week=self._clamp(shift(self.week,delta)); self.day=self.week; self._render()

    def _select(self,item,previous):
        if item:
            self.day=item.data(Qt.UserRole); self._render_day()

    def _render(self):
        self.week=self._clamp(self.week); self.day=self._clamp(self.day)
        self.range_label.setText(f'{self.draft["start"]} 至 {self.draft["end"]}　·　{self.draft["timezone"]} {self.draft["reset_at"]} 日切')
        n=(date.fromisoformat(self.draft['end'])-date.fromisoformat(self.draft['start'])).days+1
        self.horizon.setVisible(n>7)
        self.horizon.setText(f'已安排 {n} 天。活动和资源需求可能变化，建议一次安排不超过 7 天。')
        self._paint_week(); self._render_day()

    def _render_day(self):
        self._loading=True
        day=self.draft['days'].get(self.day,{})
        rec=self.store.record(self.day)
        if rec.get('frozen') and rec.get('routine'):
            day=dict(day,kind='tasks',routine=rec['routine'],name=rec.get('name') or day.get('name',''))
        tasks=day.get('kind')=='tasks'; locked=self._locked(self.day)
        self._last_lock=locked
        self.day_title.setText(f'{self.day}　周{WEEK[date.fromisoformat(self.day).weekday()]}')
        self.fields.setVisible(tasks); self.fields.setEnabled(not locked); self.history.setVisible(bool(rec))
        self.copy_day.setVisible(tasks)
        self.name.setText(day.get('name','')); self.override.setChecked(bool(day.get('time')))
        self.clock.setTime(QTime.fromString((day.get('time') or self.draft['default_time'])[:5],'HH:mm'))
        self.clock.setEnabled(self.override.isChecked())
        self.empty_title.setText('这一天休息' if day else '这一天还没有安排')
        self.empty_note.setText('过去的日期可查看或作为复制来源。' if locked else '复制已有日常开始编辑，或从模板建立这一天。')
        self.from_daily.setVisible(not locked); self.use_template.setVisible(not locked and bool(self.draft['templates']))
        if tasks:
            if self.editor is None:
                self.editor=RoutineFragment(None,self.theme,self.stack,definition=day['routine'])
                self.stack.addWidget(self.editor); self.editor.dirtyChanged.connect(self._edit_cards)
                self.editor.materialRequested.connect(lambda key,action:self.materialRequested.emit(self.day,key,action))
            else: self.editor.load_definition(day['routine'])
            self.editor.set_busy(locked); self.stack.setCurrentWidget(self.editor)
        else: self.stack.setCurrentIndex(0)
        suffix=' · 只读' if locked else ''
        self.day_note.setText((f'{count(day)} 条已启用　·　{self._time_label(day)} 开始'+suffix) if tasks else '')
        self._loading=False; self._controls()

    def _edit_meta(self,*_):
        if self._loading or self._locked(self.day): return
        day=self.draft['days'].get(self.day)
        if not day or day['kind']!='tasks': return
        day['name']=self.name.text(); day['time']=self.clock.time().toString('HH:mm') if self.override.isChecked() else ''
        self.clock.setEnabled(self.override.isChecked())
        self._edited(day)

    def _edit_cards(self,*_):
        if self._loading or self._locked(self.day): return
        day=self.draft['days'].get(self.day)
        if not day or day['kind']!='tasks': return
        day['routine']=self.editor.definition()
        self._edited(day)

    def _edited(self,day):
        self.day_note.setText(f'{count(day)} 条已启用　·　{self._time_label(day)} 开始')
        self._paint_week(); self._controls()

    def has_unsaved_changes(self): return self.draft!=self.base

    def _controls(self):
        dirty=self.has_unsaved_changes()
        self.save_button.setEnabled(dirty); self.undo.setEnabled(dirty)
        self.auto.setText('暂停计划' if self.base['auto'] else '启用自动执行')
        self.auto.setEnabled(self.base['auto'] or not dirty)
        today=self.store.today()
        status=self._runtime[1] if self._runtime[0]==today else self.store.record(today).get('status')
        today_tasks=self.draft['days'].get(today,{}).get('kind')=='tasks'
        self.start.setEnabled(not dirty and today_tasks and status not in ('running','completed','partial','expired','missed'))
        self.remain.setVisible(status=='partial'); self.remain.setEnabled(not dirty)
        self.stop.setVisible(status in ('running','waiting_device') or
                             (today_tasks and self.base['auto'] and status in (None,'ready')))
        if dirty: self.set_feedback('排期有未保存的更改。保存后可执行。')

    def set_feedback(self,message): self.feedback.setText(str(message))

    def set_runtime_status(self,day,status,reason=''):
        value=(str(day),status,reason)
        if value==self._runtime: return
        self._runtime=value; self._paint_week()
        if self._locked(self.day)!=self._last_lock: self._render_day()
        else: self._controls()
        if not self.has_unsaved_changes() and reason: self.set_feedback(str(reason))

    def refresh(self):
        latest=self.store.load()
        if not self.has_unsaved_changes():
            if self.base!=latest:
                self.base=deepcopy(latest); self.draft=deepcopy(latest); self._render(); return
        else:
            self.base['auto']=self.draft['auto']=latest['auto']
            for k in ('auto_start_day','auto_from'):
                if k in latest: self.base[k]=self.draft[k]=latest[k]
            # A day may start while a future-week draft is open. Keep the
            # editable dates and never write stale edits over a frozen day.
            discarded=[]
            for k in set(self.base['days']) | set(self.draft['days']):
                if self.base['days'].get(k)!=self.draft['days'].get(k) and self._locked(k):
                    if k in latest['days']: self.draft['days'][k]=deepcopy(latest['days'][k])
                    else: self.draft['days'].pop(k,None)
                    discarded.append(k)
            if discarded:
                self._render(); self.set_feedback('以下日期已开始或过去，保留其原安排：'+', '.join(sorted(discarded))+'。其他草稿仍可保存。');return
        self._paint_week()
        if self._locked(self.day)!=self._last_lock: self._render_day()
        else: self._controls()

    def _request(self,signal):
        if self.has_unsaved_changes(): self.set_feedback('请先保存或撤销排期。'); return
        signal.emit()

    def _toggle_auto(self):
        if self.base['auto']: self.autoRequested.emit(False)
        elif not self.has_unsaved_changes(): self.autoRequested.emit(True)

    def _set_tasks(self,key,name,spec):
        if self._locked(key): return
        self.draft['days'][key]={'kind':'tasks','name':name,'time':self.draft['days'].get(key,{}).get('time',''),
                                'routine':deepcopy(spec)}

    def use_daily(self):
        self._set_tasks(self.day,'日常任务',self.store.from_daily()); self._render()

    def _new_day(self):
        rows=default_events(); params=default_routine()
        for e in rows: e['enabled']=False
        self._set_tasks(self.day,'一日任务',dict(events=rows,params_by_id={
            e['instance_id']:params.get(e['func_name'][4:],{}) for e in rows}))
        self._render()

    def _menu(self):
        menu=QMenu(self); day=self.draft['days'].get(self.day,{})
        tasks=day.get('kind')=='tasks'
        if not self._locked(self.day):
            menu.addAction('新建空白一日任务',self._new_day)
            menu.addAction('从当前日常复制', self.use_daily)
            if self.draft['templates']: menu.addAction('使用模板…',self._use_template)
            menu.addAction('设为休息日',lambda:self._mark('rest'))
            if day: menu.addAction('清除这天的安排',lambda:self._mark('empty'))
        if tasks:
            menu.addAction('另存为模板…',self._save_template)
        if self.draft['templates']: menu.addAction('删除模板…',self._delete_template)
        if not menu.isEmpty(): menu.exec_(self.actions.mapToGlobal(self.actions.rect().bottomLeft()))

    def _mark(self,kind):
        if self._locked(self.day): return
        if kind=='rest': self.draft['days'][self.day]={'kind':'rest'}
        else: self.draft['days'].pop(self.day,None)
        self._render()

    def _save_template(self):
        day=self.draft['days'][self.day]
        name,ok=QInputDialog.getText(self,'另存为模板','模板名称',text=day['name'])
        name=name.strip()
        if ok and name:
            if name in self.draft['templates'] and QMessageBox.question(self,'更新模板',f'替换模板「{name}」？已安排的日期保持不变。')!=QMessageBox.Yes: return
            self.draft['templates'][name]=deepcopy(day['routine']); self._render(); self.set_feedback('模板已加入草稿。')

    def _use_template(self):
        names=sorted(self.draft['templates'])
        if not names: return
        name,ok=QInputDialog.getItem(self,'使用模板','复制到 '+self.day,names,0,False)
        if ok: self._set_tasks(self.day,name,self.draft['templates'][name]); self._render()

    def _delete_template(self):
        name,ok=QInputDialog.getItem(self,'删除模板','选择模板（已安排日期不受影响）',sorted(self.draft['templates']),0,False)
        if ok: self.draft['templates'].pop(name); self._render()

    def _pick_targets(self,title,mapping):
        # Select and review possible replacements together; existing dates start unchecked.
        dialog=QDialog(self); dialog.setWindowTitle(title); dialog.resize(415,480)
        layout=QVBoxLayout(dialog); layout.addWidget(QLabel('已勾选未安排日。勾选已有安排的日期将替换该日。'))
        box=QListWidget(); layout.addWidget(box)
        for key,source in mapping.items():
            day=self.draft['days'].get(key)
            dest='替换：'+self._day_summary(key) if day else '未安排'
            item=QListWidgetItem(f'{key}　← {source[5:]}　{dest}')
            item.setData(Qt.UserRole,key); item.setFlags(item.flags()|Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked if day else Qt.Checked); box.addItem(item)
        layout.addWidget(buttons(dialog,'加入草稿'))
        if dialog.exec_()!=QDialog.Accepted: return []
        return [box.item(i).data(Qt.UserRole) for i in range(box.count()) if box.item(i).checkState()==Qt.Checked]

    def copy_to(self,source,targets,whole_day=False):
        day=self.draft['days'].get(source)
        if not day: return
        for key in targets:
            if key==source or self._locked(key): continue
            oldtime=self.draft['days'].get(key,{}).get('time','')
            copy=deepcopy(day)
            if not whole_day and copy['kind']=='tasks': copy['time']=oldtime
            self.draft['days'][key]=copy

    def _copy_dialog(self):
        n=(date.fromisoformat(self.draft['end'])-date.fromisoformat(self.draft['start'])).days+1
        mapping={k:self.day for i in range(n) if (k:=shift(self.draft['start'],i))!=self.day and not self._locked(k)}
        if not mapping: self.set_feedback('范围内没有可复制的其他日期，请先延长排期。'); return
        self.copy_to(self.day,self._pick_targets('复制这一天',mapping)); self._render()

    def _copy_week(self):
        mapping={shift(self.week,i+7):shift(self.week,i) for i in range(7)
                 if shift(self.week,i) in self.draft['days'] and not self._locked(shift(self.week,i+7))}
        if not mapping: self.set_feedback('本页没有可复制到下一周的安排。'); return
        chosen=self._pick_targets('复制本周到下周',mapping)
        if not chosen: return
        self.draft['end']=max(self.draft['end'],shift(self.week,13))
        for key in chosen: self.copy_to(mapping[key],[key],True)
        self.week=shift(self.week,7); self.day=chosen[0]; self._render()

    def _settings(self):
        dialog=QDialog(self); dialog.setWindowTitle('排期设置')
        form=QFormLayout(dialog); start=date_control(self.draft['start']); end=date_control(self.draft['end'])
        clock=time_control(self.draft['default_time']); reset=time_control(self.draft['reset_at'])
        zone=QLineEdit(self.draft['timezone'])
        frozen=bool(self.base['auto'] or self.store.record(self.store.today()).get('frozen'))
        reset.setEnabled(not frozen); zone.setEnabled(not frozen)
        for label,w in [('开始日期',start),('结束日期',end),('默认开始时间',clock),('服务器时区',zone),('游戏日切',reset)]:form.addRow(label,w)
        form.addRow(buttons(dialog,'应用到草稿'))
        if dialog.exec_()!=QDialog.Accepted: return
        a,b=(w.date().toString('yyyy-MM-dd') for w in (start,end))
        if a>b: self.set_feedback('结束日期不能早于开始日期。');return
        if any(not a<=k<=b for k in self.draft['days'] if k>=self.store.today()):
            self.set_feedback('新范围之外仍有已安排日期；请保留这些日期，或先清除尚未开始的安排。');return
        self.draft.update(start=a,end=b,default_time=clock.time().toString('HH:mm'),timezone=zone.text().strip(),reset_at=reset.time().toString('HH:mm'))
        self._render()

    def _preview(self):
        before,after=self.base['days'],self.draft['days']
        lines=[]
        for key in sorted(set(before)|set(after)):
            if before.get(key)!=after.get(key):
                action='替换' if key in before and key in after else '新增' if key in after else '清除'
                lines.append(f'{action}　{key}　{self._day_summary(key)}')
        if any(self.base.get(k)!=self.draft.get(k) for k in ('start','end','timezone','reset_at','default_time')):
            lines.insert(0,f'排期范围 {self.draft["start"]} 至 {self.draft["end"]}，默认 {self.draft["default_time"]} 开始')
        if self.base['templates']!=self.draft['templates']: lines.append('更新一日任务模板')
        if (date.fromisoformat(self.draft['end'])-date.fromisoformat(self.draft['start'])).days>=7:
            lines.append(self.horizon.text())
        if self.base['auto']:
            from core.plan_runner import start_at
            today=self.store.today(); item=after.get(today,{})
            rec=self.store.record(today)
            if (self.draft['start']<=today<=self.draft['end'] and item.get('kind')=='tasks'
                    and count(item) and not rec.get('auto_skip')
                    and rec.get('status') in (None,'ready','waiting_device')
                    and self.store.clock()>=max(start_at(self.draft,today),rec.get('retry_at',0))):
                lines.append(f'自动执行已开启：今日安排的开始时间（{self._time_label(item)}）已到，保存后可能立即启动。')
        return '\n'.join(lines)

    def _confirm_save(self):
        dialog=QDialog(self); dialog.setWindowTitle('保存排期'); dialog.resize(480,340)
        layout=QVBoxLayout(dialog); layout.addWidget(typography(QLabel('以下更改将写入日历'),16,True))
        content=QTextEdit(); content.setReadOnly(True); content.setPlainText(self._preview()); layout.addWidget(content)
        layout.addWidget(buttons(dialog,'保存排期'))
        if dialog.exec_()==QDialog.Accepted: self.save_changes()

    def save_changes(self):
        try:
            latest=self.store.load()
            for k in set(latest)-{'start','end','timezone','reset_at','default_time','days','templates'}:
                self.draft[k]=deepcopy(latest[k])
            self.base=self.store.save(self.draft)
        except (OSError,ValueError,KeyError) as exc:
            self.set_feedback(f'保存失败：{exc}');return False
        self.draft=deepcopy(self.base); self._render(); self.set_feedback('排期已保存。'); self.saved.emit();return True

    def cancel_changes(self):
        self.base=self.store.load(); self.draft=deepcopy(self.base);self._render();self.set_feedback('已撤销未保存的更改。')

    def _choose_history(self):
        dialog=QDialog(self); dialog.setWindowTitle('按游戏日查看历史')
        form=QFormLayout(dialog); which=date_control(min(self.day,self.store.today()))
        which.setMaximumDate(QDate.fromString(self.store.today(),'yyyy-MM-dd'))
        form.addRow('游戏日',which);form.addRow(buttons(dialog,'查看'))
        if dialog.exec_()==QDialog.Accepted:self._history(which.date().toString('yyyy-MM-dd'))

    @staticmethod
    def _remaining_lines(rec):
        spec=rec.get('routine') or {}; rows={e['instance_id']:e for e in spec.get('events',[])}
        latest={e['instance_id']:e for e in rec.get('tasks',[]) if 'instance_id' in e}
        lines=[]
        for key in dict.fromkeys([*rec.get('remaining',[]), *rec.get('deferred',[])]):
            event=rows.get(key,{})
            title=event.get('event_name',key)
            if key in rec.get('deferred',[]):
                periods=format_periods(event.get('disabled_time_range',[]))
                lines.append(f'{title}：本轮处于禁用时段'+(f'（{periods}）' if periods else ''))
            else:
                lines.append(f'{title}：上次未完成')
            params=spec.get('params_by_id',{}).get(key,{})
            plans=latest.get(key,{}).get('remaining', params.get('plans',[]))
            if plans:
                catalog=stage_options(event['func_name'])
                for p in plans:
                    stage=catalog.get(p['stage_id'],{}).get('title',p['stage_id'])
                    lines.append(f'    {stage}　剩余 '+('MAX' if p['count']=='max' else f'{p["count"]} 次'))
        return lines

    def _resume_remaining(self):
        if self.has_unsaved_changes():self.set_feedback('请先保存或撤销排期。');return
        rec=self.store.record(self.store.today()); lines=self._remaining_lines(rec)
        if not lines:self.set_feedback('当天没有可续做的余项。');return
        dialog=QDialog(self);dialog.setWindowTitle('续做今日余项');dialog.resize(490,330)
        layout=QVBoxLayout(dialog); layout.addWidget(QLabel('仅处理下列余项。仍处在禁用时段的指令会保留。'))
        text=QTextEdit();text.setReadOnly(True);text.setPlainText('\n'.join(lines));layout.addWidget(text)
        layout.addWidget(buttons(dialog,'续做今日余项'))
        if dialog.exec_()==QDialog.Accepted:self.resumeRemainingRequested.emit()

    def _history(self,key):
        rec=self.store.record(key)
        if not rec: self.set_feedback(key+' 没有计划执行记录。');return
        dialog=QDialog(self); dialog.setWindowTitle(key+' · 执行记录'); dialog.resize(560,400)
        status=rec.get('status') or ('自动跳过今日' if rec.get('auto_skip') else '未开始')
        layout=QVBoxLayout(dialog); layout.addWidget(typography(QLabel((rec.get('name') or key)+' · '+STATUS.get(status,status)),18,True))
        tabs=QTabWidget();layout.addWidget(tabs,1)
        text=QTextEdit();text.setReadOnly(True); lines=[]
        for item in rec.get('tasks',[]):
            label=item.get('event_name') or item.get('task_id','')
            lines.append(f'{label}：{item.get("reason") or item.get("status","")}')
        if rec.get('error'): lines.append(str(rec['error']))
        if rec.get('inflight'):
            lines.append('中断步骤：'+rec['inflight'].get('event_name',rec['inflight'].get('task_id','')))
        remaining=self._remaining_lines(rec)
        if remaining: lines.extend(['','余项',*remaining])
        text.setPlainText('\n'.join(lines) or '尚无已结算步骤。');tabs.addTab(text,'执行结果')
        if rec.get('routine'):
            spec=rec['routine']; detail=[]
            for e in spec['events']:
                task=e['func_name']; params=spec['params_by_id'][e['instance_id']]
                detail.append(('启用　' if e['enabled'] else '停用　')+e['event_name'])
                summary=parameter_summary(task,{task[4:]:params})
                if summary:detail.append('    '+summary)
                periods=format_periods(e.get('disabled_time_range',[]))
                if periods:detail.append('    禁用时段：'+periods)
                if task=='mad.dating':
                    for map_name,places in params.get('location_priority',{}).items():
                        detail.append('    '+map_name+'：'+' → '.join(places))
                if task=='mad.claim_all' and params.get('modules',{}).get('mall'):
                    periods={'daily':'每日','weekly':'每周','monthly':'每月'}
                    detail.append('    商城：'+'、'.join(periods.get(p,p) for p in params.get('mall_periods',[])))
            config=QTextEdit();config.setReadOnly(True);config.setPlainText('\n'.join(detail))
            tabs.addTab(config,'当时的一日任务')
        if rec.get('run_dir') and Path(rec['run_dir']).is_dir():
            openlog=PushButton('打开运行记录目录'); openlog.clicked.connect(lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(rec['run_dir']))));layout.addWidget(openlog)
        close=PushButton('关闭'); close.clicked.connect(dialog.accept); layout.addWidget(close);dialog.exec_()
