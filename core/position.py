"""BAAS prefix/name resource registry, adapted for MAD 2026-10-23.

BAAS 1110e88df5955df277737ea9717869b9ca88362b; GPL-3.0-only.
Absolute Unicode-safe paths, no BA activity resources, atomic initialization.
"""
import json
from pathlib import Path
import threading
import cv2
import numpy as np
from core.paths import REPO_ROOT
from core.device.runtime import DeviceError

IDENTIFIER='MAD_onestore_zh-CN'
image_x_y_range={}
image_dic={}
metadata={}
initialized_image={IDENTIFIER:False}
_lock=threading.RLock()

def init_image_data(context):
    identifier=context.identifier
    if identifier!=IDENTIFIER:
        raise DeviceError('只加载独立 MAD 中文资源。')
    with _lock:
        if initialized_image[identifier]:
            return True
        root=REPO_ROOT/'src'/'images'/identifier
        manifest=json.loads((root/'provenance.json').read_text('utf-8'))
        images,areas={},{}
        for name,item in manifest['templates'].items():
            payload=(root/(name+'.png')).read_bytes()
            image=cv2.imdecode(np.frombuffer(payload,np.uint8),cv2.IMREAD_COLOR)
            if image is None:
                raise DeviceError(f'MAD 模板尺寸无效：{name}')
            prefix,suffix=name.rsplit('_',1)
            areas.setdefault(prefix,{})[suffix]=item['base_area']
            images[name]=image
        image_dic[identifier]=images
        image_x_y_range[identifier]=areas
        metadata[identifier]=manifest['templates']
        initialized_image[identifier]=True
    return True

def get_area(identifier,name):
    prefix,suffix=name.rsplit('_',1)
    return image_x_y_range[identifier][prefix][suffix]
