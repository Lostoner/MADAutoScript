"""BAAS control facade; this project uses the configured ADB backend."""
from core.device.control.adb import AdbControl

class Control:
    def __init__(self,connection,method='adb'):
        if method!='adb': raise ValueError('当前配置的控制方式未提供实现：'+method)
        self.control_instance=AdbControl(connection)
    def click(self,x,y,evidence=None): return self.control_instance.click(x,y,evidence)
    def swipe(self,x1,y1,x2,y2,duration=.3,evidence=None): return self.control_instance.swipe(x1,y1,x2,y2,duration,evidence)
    def long_click(self,x,y,duration,evidence=None): return self.swipe(x,y,x,y,duration,evidence)
