"""BAAS Screenshot.ensure_interval and shared-frame capture (GPL-3.0)."""
import time
from core.device.screenshot.adb import AdbScreenshot

class Screenshot:
    def __init__(self,connection,interval=.3):
        self.connection=connection
        self.backend=AdbScreenshot(connection)
        self.interval=max(.3,interval)
        self.last_capture=0
    def ensure_interval(self):
        self.connection.guard.wait(max(0,self.interval-(time.monotonic()-self.last_capture)))
    def screenshot(self):
        self.ensure_interval()
        frame=self.backend.screenshot()
        self.last_capture=time.monotonic()
        return frame
