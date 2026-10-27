"""Stop handling and coordinate conversion for the BAAS device boundary."""
import subprocess
import threading
import os
from core.exception import RequestHumanTakeOver, FunctionCallTimeout

class DeviceError(RuntimeError): pass
class ForegroundMismatch(DeviceError): pass
OperationStopped=RequestHumanTakeOver
OperationTimeout=FunctionCallTimeout

class RunControl:
    def __init__(self,stop_event=None):
        self.stop_event=stop_event or threading.Event()
        self.actions=0
    def check(self):
        if self.stop_event.is_set(): raise RequestHumanTakeOver('用户停止。')
    def timeout(self,maximum=10):
        self.check()
        return maximum
    def wait(self,seconds):
        self.check()
        self.stop_event.wait(max(0,seconds))
        self.check()

def hidden_process_args():
    return {'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}

def run_bounded(arguments,guard,maximum=10):
    guard.check()
    result=subprocess.run([str(x) for x in arguments],capture_output=True,timeout=maximum,**hidden_process_args())
    guard.check()
    if result.returncode: raise DeviceError(result.stderr.decode('utf-8','replace'))
    return result.stdout

class Coordinates:
    base_size=(1280,720)
    def __init__(self,raw_size=(1920,1080)):
        self.raw_size=tuple(raw_size)
        self.ratio=raw_size[0]/1280
    def raw_point(self,x,y):
        return round(x*self.ratio),round(y*self.ratio)
    def raw_area(self,area): return tuple(round(x*self.ratio) for x in area)
