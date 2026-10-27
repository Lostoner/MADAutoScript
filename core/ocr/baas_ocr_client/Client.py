"""BAAS native HTTP OCR client with shared zh-cn/en-us model lifecycle."""
from pathlib import Path
import json
import socket
import subprocess
import time
import cv2
import requests
from core.device.runtime import hidden_process_args
from core.exception import OcrInternalError
from core.paths import REPO_ROOT
from core.runtime_state import atomic_json

OcrError=OcrInternalError

class BaasOcrClient:
    def __init__(self,guard,run_dir=None,*,runtime_root=None):
        self.guard=guard
        self.root=Path(runtime_root or REPO_ROOT/'runtime/ocr')
        self.server_process=None
        self._log=None
        self.base_url=None
        self.session=requests.Session()
        self.session.trust_env=False

    def start_server(self):
        if self.server_process is not None and self.server_process.poll() is None: return self.metadata
        static=json.loads((self.root/'resource/static.json').read_text('utf-8'))
        for language in ('zh-cn','en-us'):
            for filename in static['ocr_model_name'][language].values():
                if not (self.root/'resource/ocr_models'/filename).is_file(): raise OcrError('缺少 OCR 模型 '+filename)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0)); port=listener.getsockname()[1]
        self.base_url=f'http://127.0.0.1:{port}'
        setting=json.loads((self.root/'resource/global_setting.json').read_text('utf-8'))
        setting.setdefault('ocr',{}).update(gpu_id=-1,num_thread=2,enable_cpu_memory_arena=False,server={'host':'127.0.0.1','port':port})
        atomic_json(self.root/'config/global_setting.json',setting)
        self._log=(self.root/'ocr-server.log').open('wb')
        self.server_process=subprocess.Popen([str(self.root/'BAAS_ocr_server.exe')],cwd=self.root,
            stdin=subprocess.PIPE,stdout=self._log,stderr=subprocess.STDOUT,**hidden_process_args())
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            self.guard.check()
            if self.server_process.poll() is not None: raise OcrError('OCR 启动失败：'+str(self.root/'ocr-server.log'))
            try:
                if self.session.get(self.base_url,timeout=.4).status_code in (200,404): break
            except requests.RequestException: self.guard.wait(.1)
        else: raise OcrError('OCR 启动超时')
        self._request('/init_model',json={'language':['zh-cn','en-us'],'gpu_id':-1,'num_thread':2,'EnableCpuMemoryArena':False})
        self.metadata={'pid':self.server_process.pid,'base_url':self.base_url,'languages':['zh-cn','en-us']}
        return self.metadata

    def _request(self,path,**kwargs):
        self.guard.check()
        try:
            response=self.session.post(self.base_url+path,timeout=(3,30),**kwargs)
            response.raise_for_status()
            result=response.json()
        except (requests.RequestException,ValueError) as exc: raise OcrError(str(exc)) from exc
        self.guard.check()
        return result

    def _image(self,path,image,language,candidates):
        okay,encoded=cv2.imencode('.png',image)
        if not okay: raise OcrError('OCR PNG 编码失败')
        data={'language':language,'candidates':candidates,'image':{'pass_method':1},'ret_options':0b110}
        return self._request(path,files={'data':(None,json.dumps(data),'application/json'),'image':('image.png',encoded.tobytes(),'image/png')})
    def single_line(self,image,language='zh-cn',candidates=''):
        return self._image('/ocr_for_single_line',image,language,candidates)
    def ocr(self,image,language='zh-cn',candidates=''):
        return self._image('/ocr',image,language,candidates)
    def stop_server(self):
        if self.server_process is not None:
            process=self.server_process
            if process.poll() is None:
                try:
                    process.stdin.write(b'exit\n'); process.stdin.flush(); process.wait(timeout=2)
                except (OSError,subprocess.TimeoutExpired):
                    process.terminate(); process.wait(timeout=3)
            if process.stdin: process.stdin.close()
            self.server_process=None
        if self._log: self._log.close(); self._log=None
        self.session.close()
