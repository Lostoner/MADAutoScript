"""BAAS ADB PNG screenshot. Frames stay in memory unless explicitly saved."""
from dataclasses import dataclass
import time
import cv2
import numpy as np
from core.device.runtime import Coordinates,DeviceError

def decode_png(data):
    image=cv2.imdecode(np.frombuffer(data,np.uint8),cv2.IMREAD_COLOR)
    if image is None: raise DeviceError('ADB PNG 截图解码失败')
    return image

@dataclass
class Frame:
    image: np.ndarray
    path: str=''
    sha256: str=''
    captured_at: str=''
    monotonic_time: float=0
    def evidence(self): return {'path':self.path,'raw_size':[self.image.shape[1],self.image.shape[0]]}

class AdbScreenshot:
    def __init__(self,conn): self.connection=conn
    def screenshot(self,label='frame'):
        data=self.connection.shell(['screencap','-p'],encoding=None)
        image=decode_png(data)
        self.connection.coordinates=Coordinates((image.shape[1],image.shape[0]))
        return Frame(image,monotonic_time=time.monotonic())
