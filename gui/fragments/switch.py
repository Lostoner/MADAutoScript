"""BAAS event parameters. Task toggles/order live only in the task list."""
from copy import deepcopy
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
from PyQt5.QtCore import Qt,pyqtSignal
from PyQt5.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QHeaderView
from qfluentwidgets import ScrollArea,TableWidget,SpinBox,LineEdit,PushButton,PrimaryPushButton,TitleLabel
from core.config.schedule_fields import parse_periods,format_periods

def convert_clock(values,source,target):
    now=datetime.now(ZoneInfo(source)).replace(hour=values[0],minute=values[1],second=values[2],microsecond=0)
    result=now.astimezone(ZoneInfo(target))
    return [result.hour,result.minute,result.second]

def parse_resets(text,zone):
    if not text.strip(): return []
    result=[]
    for clock in text.replace('；',';').split(';'):
        value=parse_periods(clock.strip()+'-'+clock.strip())[0][0]
        result.append(convert_clock(value,zone,'UTC'))
    return result

class SwitchFragment(ScrollArea):
    message=pyqtSignal(str,str)
    saved=pyqtSignal(list)
    def __init__(self,repository,tasks,theme,parent=None):
        super().__init__(parent)
        self.setObjectName('taskInterface')
        self.repository,self.tasks,self.theme=repository,tasks,theme
        self.setWidgetResizable(True)
        self.scrollWidget=QWidget(self)
        layout=QVBoxLayout(self.scrollWidget)
        self.title=TitleLabel('持续运行设置',self)
        self.note=QLabel('开关与顺序共用“任务配置”。间隔 0 使用 86400 秒；到期时间取间隔和每日重置中较早的一项。\n每日重置与禁用时段使用设置中的时区；多个时刻/时段用 ; 分隔。前后置列表保留在事件配置中。',self)
        self.note.setWordWrap(True)
        layout.addWidget(self.title); layout.addWidget(self.note)
        self.tableView=TableWidget(self)
        self.tableView.setColumnCount(4)
        self.tableView.setHorizontalHeaderLabels(['功能','间隔（秒）','每日重置 HH:MM','禁用时段 HH:MM-HH:MM'])
        self.tableView.setRowCount(len(tasks))
        self.tableView.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tableView.setMinimumHeight(480)
        self.tableView.setEditTriggers(self.tableView.NoEditTriggers)
        self.rows={}
        for row,(key,spec) in enumerate(tasks.items()):
            label=QLabel(spec.title,self.tableView)
            interval=SpinBox(self.tableView); interval.setRange(0,2147483647)
            resets=LineEdit(self.tableView); periods=LineEdit(self.tableView)
            self.tableView.setRowHeight(row,42)
            for column,widget in enumerate((label,interval,resets,periods)): self.tableView.setCellWidget(row,column,widget)
            self.rows[key]=(interval,resets,periods)
        layout.addWidget(self.tableView)
        actions=QHBoxLayout()
        self.save_button=PrimaryPushButton('保存调度参数',self)
        self.cancel_button=PushButton('取消更改',self)
        actions.addWidget(self.save_button); actions.addWidget(self.cancel_button); actions.addStretch()
        layout.addLayout(actions)
        self.feedback=QLabel('',self); self.feedback.setWordWrap(True); layout.addWidget(self.feedback)
        self.setWidget(self.scrollWidget)
        self.save_button.clicked.connect(self.save_changes)
        self.cancel_button.clicked.connect(self.cancel_changes)
        theme.changed.connect(self._apply_theme)
        self.cancel_changes(); self._apply_theme()
    def cancel_changes(self):
        self.base_events=self.repository.load_events()
        self.zone=self.repository.load_config()['scheduling']['timezone']
        for event in self.base_events:
            if event['func_name'] not in self.rows: continue
            interval,resets,periods=self.rows[event['func_name']]
            interval.setValue(int(event['interval']))
            resets.setText('; '.join(':'.join(f'{x:02d}' for x in convert_clock(v,'UTC',self.zone)) for v in event['daily_reset']))
            periods.setText(format_periods(event['disabled_time_range']))
        self.original={key:(a.value(),b.text(),c.text()) for key,(a,b,c) in self.rows.items()}
        self.feedback.setText('显示时区：'+self.zone)
    def has_unsaved_changes(self): return any((a.value(),b.text(),c.text())!=self.original[key] for key,(a,b,c) in self.rows.items())
    def save_changes(self):
        try:
            patches=[]
            for key,(a,b,c) in self.rows.items():
                old=self.original[key]
                patch={'func_name':key}
                if a.value()!=old[0]: patch['interval']=a.value()
                if b.text()!=old[1]: patch['daily_reset']=parse_resets(b.text(),self.zone)
                if c.text()!=old[2]: patch['disabled_time_range']=parse_periods(c.text())
                if len(patch)>1: patches.append(patch)
            saved=self.repository.save_events(patches,fields={'interval','daily_reset','disabled_time_range'})
            self.cancel_changes(); self.feedback.setText('已保存；下次调度读取新值。'); self.saved.emit(saved)
        except Exception as exc: self.feedback.setText('保存失败：'+str(exc))
    def set_busy(self,busy):
        self.tableView.setEnabled(not busy)
        self.save_button.setEnabled(not busy)
        self.cancel_button.setEnabled(not busy)
    def _apply_theme(self):
        self.theme.apply_scroll_surface(self,self.scrollWidget)
        self.theme.apply_surface(self.tableView)
        for label in (self.title,self.note,self.feedback,*self.tableView.findChildren(QLabel)):
            label.setStyleSheet('color: '+self.theme.colors['text']+';')
