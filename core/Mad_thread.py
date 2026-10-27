"""MAD port of BAAS Baas_thread: one lifecycle, solve, page loop and scheduler.

Upstream 1110e88df5955df277737ea9717869b9ca88362b, GPL-3.0-only.
"""
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import logging
import re
import threading
import time
import traceback
import uuid
import cv2
from core.config.repository import ProfileRepository
from core.config.config_set import ConfigSet
from core.scheduler import Scheduler
from core.tasks import TASKS, function_table
from core.exception import FunctionCallTimeout, PackageIncorrect, RequestHumanTakeOver
from core.device.runtime import RunControl
from core.device.connection import Connection
from core.device.Control import Control
from core.device.Screenshot import Screenshot
from core.ocr.ocr import Baas_ocr
from core.ocr.baas_ocr_client.Client import BaasOcrClient
from core import image, position
from core.runtime_state import atomic_json

class _Events(logging.Handler):
    def __init__(self,worker): super().__init__(); self.worker=worker
    def emit(self,record): self.worker.emit('log',record.getMessage(),level=record.levelname)

class MadThread:
    def __init__(self,repository,emit_event=None,resources=None):
        self.repository=repository if isinstance(repository,ProfileRepository) else ProfileRepository(repository)
        self.config_set=ConfigSet(self.repository)
        self.config=self.repository.load_config()
        self.emit_event=emit_event or (lambda event:None)
        self.resources=resources
        self._stop_event=threading.Event()
        self.guard=RunControl(self._stop_event)
        self.flag_run=False
        self.state='idle'
        self._thread=None
        self.connection=self.ocr_client=None
        self.last_result=None
        self.identifier=position.IDENTIFIER
        self.is_android_device=True
        self.server='MAD'
        self.rgb_feature={}
        self.latest_img_array=None
        self.latest_ui_frame=None
        self.ratio=1.0
        self.screenshot_interval=max(.3,self.config['runtime'].get('screenshot_interval',.3))
        self._cache={}
        self.next_time=0
        self.current_task=None
        self.task_params={}
        self.task_details={}
        self.date_popup_handled=False
        self.error=None
        self.func_dict=function_table()
        self.scheduler=Scheduler(repository=self.repository,update_signal=lambda queue:self.emit('queue','',tasks=queue))
        self.logger=logging.getLogger('mad.'+uuid.uuid4().hex)
        self.logger.setLevel(logging.INFO)
        self.logger.propagate=False
        self.logger.addHandler(_Events(self))

    @property
    def is_running(self): return bool(self._thread and self._thread.is_alive())
    def emit(self,kind,message='',**fields):
        self.emit_event({'kind':kind,'message':message,'time':datetime.now().isoformat(),**fields})
    def _state(self,state,message=''):
        self.state=state
        self.emit('state',message,state=state)
    def start_tasks(self,continuous=False,task_ids=None,new_round=False):
        if self.is_running: return False
        self._stop_event.clear()
        self.flag_run=True
        self.error=None
        self._state('starting','正在连接设备与 OCR。')
        self._thread=threading.Thread(target=self.thread_starter,args=(continuous,task_ids,new_round),name='MAD-Baas-thread',daemon=False)
        self._thread.start()
        return True
    def request_stop(self):
        self.flag_run=False
        self._stop_event.set()
        if self.is_running: self._state('stopping','正在停止。')
        return True
    signal_stop=request_stop
    def join(self,timeout=None):
        if self._thread is not None and self._thread is not threading.current_thread(): self._thread.join(timeout)
        return not self.is_running

    def connect(self):
        self.config=self.repository.load_config()
        self.package_name=self.config['game']['package']
        self.connection=Connection(self.config,self.guard,self.run_dir,self.emit).connect()
        self.control=Control(self.connection,self.config['device']['control_method'])
        self.screenshot=Screenshot(self.connection,self.screenshot_interval)
        if self.resources is None:
            self.ocr_client=BaasOcrClient(self.guard)
            self.ocr_client.start_server()
        else: self.ocr_client=self.resources.get_ocr(self.guard)
        self.ocr=Baas_ocr(self.ocr_client)
        position.init_image_data(self)
        self.update_screenshot_array()

    def thread_starter(self,continuous=False,task_ids=None,new_round=False):
        stamp=datetime.now().strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8]
        self.run_dir=self.repository.data_root/'runs'/stamp
        self.run_dir.mkdir(parents=True,exist_ok=False)
        logfile=logging.FileHandler(self.run_dir/'run.log',encoding='utf-8')
        logfile.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(message)s'))
        self.logger.addHandler(logfile)
        results=[]
        terminal='failed'
        try:
            if new_round: self.repository.reset_progress()
            self.connect()
            self._state('running','已连接；按已保存任务配置执行。')
            if not self.solve('restart'): raise RuntimeError(self.error or '启动导航未完成')
            once=self.scheduler.eligible(once=True,task_ids=set(task_ids) if task_ids else None) if not continuous else None
            self.emit('queue','',tasks=[e['event_name'] for e in once] if once is not None else [])
            idle_home=False
            while self.flag_run:
                if once is not None:
                    event=once.pop(0) if once else None
                    task=self.scheduler.expand(event) if event else None
                else: task=self.scheduler.heartbeat()
                if task is None:
                    if not idle_home:
                        self.to_main_page()
                        idle_home=True
                    if once is not None: break
                    if self.state!='waiting': self._state('waiting','等待下一个到期任务。')
                    self.guard.wait(1)
                    continue
                idle_home=False
                self._state('running')
                self.daily_config_refresh()
                current_next_time=0
                for activity in [*task['pre_task'],task['current_task'],*task['post_task']]:
                    self.guard.check()
                    self.current_task=activity
                    self.task_params=deepcopy(self.repository.load_config()['routine'])
                    self.task_details={}
                    title=TASKS[activity].title
                    self.emit('task',title,task_id=activity,state='running')
                    self.next_time=0
                    if not self.solve(activity): raise RuntimeError(self.error or title+'执行失败')
                    self.guard.check()
                    result={'task_id':activity,'status':'SUCCESS','reason':self.task_details.get('reason',title+'处理完成。'),**self.task_details}
                    results.append(result)
                    self.emit('task',result['reason'],task_id=activity,state='succeeded',result='SUCCESS')
                    if activity==task['current_task']: current_next_time=self.next_time
                self.scheduler.systole(task['current_task'],current_next_time,force_task=True)
            terminal='succeeded' if self.flag_run else 'stopped'
        except RequestHumanTakeOver:
            terminal='stopped'
        except Exception as exc:
            self.error=f'{type(exc).__name__}: {exc}'
            self.logger.error(traceback.format_exc())
            if self.latest_img_array is not None:
                try: self.save_screenshot('failure')
                except OSError: pass
        finally:
            self.flag_run=False
            if self.connection: self.connection.close()
            if self.ocr_client and self.resources is None: self.ocr_client.stop_server()
            self.last_result={'status':terminal,'tasks':results,'error':self.error,'device_actions':self.guard.actions,'run_dir':str(self.run_dir)}
            try:
                atomic_json(self.run_dir/'result.json',self.last_result)
                atomic_json(self.repository.data_root/'state'/self.repository.profile_id/'last-run.json',self.last_result)
            except OSError as exc: self.logger.warning('运行摘要写入失败：'+str(exc))
            self.emit('result','单轮执行完成。' if terminal=='succeeded' else '已停止。' if terminal=='stopped' else '执行失败，请查看日志。',state=terminal,result=self.last_result,error=self.error)
            self._state(terminal)
            self.logger.removeHandler(logfile)
            logfile.close()

    def solve(self,activity):
        # BAAS Baas_thread.py:529-552. Only these two exceptions recover.
        for attempt in range(3):
            if attempt: self.logger.info('Retry Task %s %s',activity,attempt)
            try: return self.func_dict[activity](self)
            except FunctionCallTimeout:
                if not self.deal_with_func_call_timeout(): return False
            except PackageIncorrect as exc:
                if not self.deal_with_package_incorrect(exc.message): return False
            except Exception:
                if self.flag_run:
                    self.error=traceback.format_exc()
                    self.logger.error(self.error)
                    return False
                return True
        return False

    def deal_with_package_incorrect(self,curr_pkg):
        for attempt in range(3):
            if attempt and self.connection.get_current_package()==self.package_name:
                self.connection.close_current_app()
            try:
                self.func_dict['restart'](self); return True
            except RequestHumanTakeOver: return False
            except Exception: pass
        return False

    def deal_with_func_call_timeout(self):
        # Keep the pinned upstream branch behaviour, documented in the design.
        package=self.connection.get_current_package()
        if package!=self.package_name: self.deal_with_package_incorrect(package)
        else:
            for _ in range(3): self.connection.close_current_app(package)
            try:
                self.func_dict['restart'](self); return True
            except Exception: pass
        return False

    def daily_config_refresh(self,force=False,now=None):
        config=self.repository.load_config()
        reset=config['scheduling']['reset']
        now=time.time() if now is None else now
        if not force:
            if not reset['enabled'] or not reset.get('reset_at'): return False
            parts=[int(v) for v in reset['reset_at'].split(':')]
            seconds=parts[0]*3600+parts[1]*60+(parts[2] if len(parts)>2 else 0)
            zone=ZoneInfo(reset['server_timezone'])
            day=lambda ts:(datetime.fromtimestamp(ts,zone)-timedelta(seconds=seconds)).date()
            if day(now)==day(config['last_refresh_config_time']): return False
        self.repository.reset_progress(now)
        self.logger.info('服务器日切：已从用户计划刷新未完成任务。')
        return True

    def update_screenshot_array(self):
        self.guard.check()
        frame=self.screenshot.screenshot()
        self.latest_img_array=frame.image
        self.latest_ui_frame=(frame.image,datetime.now())
        self.ratio=frame.image.shape[1]/1280
        self._cache={}
        return frame.image
    get_screenshot_array=update_screenshot_array
    def set_screenshot_interval(self,value):
        self.screenshot_interval=max(.3,value)
        self.screenshot.interval=self.screenshot_interval
    def line(self,area,language='zh-cn',candidates=''):
        key=('line',tuple(area),language,candidates)
        if key not in self._cache:
            self._cache[key]=re.sub(r'\s+','',self.ocr.get_region_res(self,area,language,candidates))
        return self._cache[key]
    def scan(self,area,language='zh-cn',candidates=''):
        key=('scan',tuple(area),language,candidates)
        if key not in self._cache: self._cache[key]=self.ocr.text_list(self,area,language,candidates)
        return self._cache[key]
    def match(self,name):
        from core.mad_features import FEATURES
        key=('feature',name)
        if key not in self._cache: self._cache[key]=bool(FEATURES[name](self))
        return self._cache[key]
    def template(self,name): return image.compare_image(self,name)
    def click(self,x,y,count=1,rate=1,duration=0,wait_over=False,**kwargs):
        self.guard.check()
        for i in range(count):
            self.guard.check()
            self.control.click(x,y)
            if count>1 and i<count-1: self.guard.wait(max(.08,duration/max(count,1)))
        if wait_over: self.guard.wait(self.screenshot_interval*rate)
    def swipe(self,x1,y1,x2,y2,duration=.3,post_sleep_time=1):
        self.guard.check()
        self.control.swipe(x1,y1,x2,y2,duration)
        self.guard.wait(post_sleep_time)
    def to_main_page(self,skip_first_screenshot=False):
        from module.restart import to_main_page
        return to_main_page(self,skip_first_screenshot)
    def open_page(self,name):
        from module.restart import open_page
        return open_page(self,name)
    def note(self,reason,**details):
        self.logger.info(reason)
        self.task_details.update(reason=reason,**details)
    def save_screenshot(self,label):
        path=self.run_dir/(label+'.png')
        okay,data=cv2.imencode('.png',self.latest_img_array)
        if okay: path.write_bytes(data.tobytes())
        return str(path)
    def get_resource(self,area):
        text=self.line(area,'en-us','0123456789/')
        try: return int(text.split('/',1)[0])
        except ValueError:
            self.logger.warning('资源识别失败，按 BAAS 返回 999，后续由游戏不足状态处理。')
            return 999

MadWorker=MadThread
