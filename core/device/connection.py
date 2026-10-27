"""BAAS Connection lifecycle with MuMu CLI serial selection (GPL-3.0)."""
from pathlib import Path
import re
from adbutils import AdbClient
from core.device.mumu_cli import get_device_info,find_adb
from core.device.runtime import Coordinates,DeviceError,run_bounded

MAD_PACKAGE='com.wemadeconnect.aos.makedrama.onestore'

def foreground_package(text):
    for key in ('topResumedActivity','mResumedActivity'):
        match=re.search(r'\b'+key+r'\s*[:=][^\r\n]*?\bu\d+\s+([A-Za-z0-9_.]+)/',text)
        if match: return match[1]
    return ''

class Connection:
    def __init__(self,snapshot,guard,run_dir,emit=None):
        self.config,self.guard=snapshot,guard
        self.run_dir=Path(run_dir)
        self.emit=emit or (lambda *a,**k:None)
        self.package=snapshot['game']['package']
        self.coordinates=Coordinates(snapshot['device'].get('reference_size',[1920,1080]))
        self.serial=self.adb=self.client=None

    def connect(self):
        self.info=get_device_info(self.config['device'],self.guard)
        self.serial=self.info.serial
        run_bounded([find_adb(self.config['device']),'start-server'],self.guard)
        self.client=AdbClient(host='127.0.0.1',port=5037,socket_timeout=10)
        self.client.connect(self.serial,timeout=10)
        self.adb=self.client.device(self.serial)
        if not self.shell(['pm','path',self.package]).startswith('package:'):
            raise DeviceError('指定 MuMu 未安装 '+self.package)
        self.metadata={**self.info.to_dict(),'package':self.package}
        self.emit('device','已连接 MuMu / ONEstore MAD。',device=self.metadata)
        return self

    def shell(self,command,maximum=10,encoding='utf-8'):
        self.guard.check()
        result=self.adb.shell(command,timeout=maximum,encoding=encoding)
        self.guard.check()
        return result

    def get_current_package(self): return foreground_package(self.shell(['dumpsys','activity','activities']))
    current_package=get_current_package
    def close_current_app(self,package=None): self.shell(['am','force-stop',package or self.package])
    def start_game(self): self.shell(['am','start','-n',self.package+'/'+self.config['game']['activity']])
    def send_input(self,command,evidence=None):
        self.guard.check()
        result=self.shell(command)
        self.guard.actions+=1
        if result.strip(): raise DeviceError('ADB input: '+result)
    def close(self):
        self.adb=None  # Do not kill the shared ADB server or touch other devices.
