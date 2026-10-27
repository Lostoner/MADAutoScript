"""Atomic local JSON storage; scheduling lives in event.json."""
import json
import os
from pathlib import Path
import time
import uuid

def atomic_json(path,data):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(f'.{path.name}.{uuid.uuid4().hex}.tmp')
    try:
        with temporary.open('x',encoding='utf-8',newline='\n') as stream:
            json.dump(data,stream,ensure_ascii=False,indent=2,allow_nan=False)
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        delays=(.02,.05,.1)
        for attempt in range(len(delays)+1):
            try:
                os.replace(temporary,path); break
            except PermissionError as error:
                if getattr(error,'winerror',None) not in (5,32,33) or attempt==len(delays): raise
                time.sleep(delays[attempt])
    finally:
        temporary.unlink(missing_ok=True)
