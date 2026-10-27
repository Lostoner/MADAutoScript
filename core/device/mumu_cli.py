"""MuMu CLI adapter derived from BAAS mumu_manager_api.py; GPL-3.0-only.

BAAS 1110e88df5955df277737ea9717869b9ca88362b; MAD 2026-10-23:
exact instance JSON; no nearby-port fallback or global setting changes.
"""
from dataclasses import asdict, dataclass
import ipaddress
import json
from pathlib import Path
from core.device.runtime import DeviceError, run_bounded

@dataclass(frozen=True)
class DeviceInfo:
    instance_id: int
    name: str
    android_version: str
    host: str
    port: int

    @property
    def serial(self):
        return f'{self.host}:{self.port}'

    def to_dict(self):
        return {**asdict(self), 'serial':self.serial}

def parse_info(payload, instance_id):
    try:
        data=json.loads(payload)
        if not isinstance(data,dict):
            raise ValueError('not an object')
        if 'index' not in data:
            if set(data)!={str(instance_id)}:
                raise ValueError('instance is missing or ambiguous')
            data=data[str(instance_id)]
        if data.get('error_code')!=0 or str(data.get('index'))!=str(instance_id):
            raise ValueError('instance/error_code mismatch')
        if data.get('is_android_started') is not True:
            raise DeviceError(f'MuMu 实例 {instance_id} 未启动；请先启动该实例。')
        host,port=data['adb_host_ip'],data['adb_port']
        if not ipaddress.ip_address(host).is_loopback or ':' in host:
            raise ValueError('only local IPv4 MuMu is supported')
        if isinstance(port,bool) or not isinstance(port,int) or not 1<=port<=65535:
            raise ValueError('invalid adb_port')
        return DeviceInfo(instance_id,str(data.get('name','')),str(data['android_version']),host,port)
    except (ValueError,KeyError,TypeError) as exc:
        raise DeviceError(f'MuMu 实例信息无效；不猜测其他端口：{exc}') from exc

def get_device_info(config,guard):
    path=Path(config['mumu_path'])
    if not path.is_file():
        raise DeviceError(f'找不到配置的 MuMu CLI：{path}')
    payload=run_bounded([path,'info','--vmindex',str(config['instance_id'])],guard)
    return parse_info(payload.decode('utf-8-sig'),config['instance_id'])

def find_adb(config):
    """Keep explicit ADB settings; otherwise use the selected MuMu installation."""
    configured = config.get('adb_path', '').strip()
    if configured:
        path = Path(configured)
        if path.is_file():
            return path
        raise DeviceError(f'找不到配置的 ADB：{path}；请在设置中选择文件或留空自动查找。')
    cli = Path(config['mumu_path'])
    candidates = [cli.parent / 'adb.exe']
    candidates += sorted((cli.parent.parent / 'nx_device').glob('*/shell/adb.exe'), reverse=True)
    candidates += [cli.parent.parent / 'shell/adb.exe']
    for path in candidates:
        if path.is_file():
            return path
    raise DeviceError('未在所选 MuMu 安装目录找到 adb.exe，请在设置中指定 ADB 路径。')
