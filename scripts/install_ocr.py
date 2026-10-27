"""Explicit pinned OCR installation; GUI startup never calls this script."""
from pathlib import Path
import argparse
import json
import hashlib
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def verify_runtime(target):
    manifest = json.loads((ROOT/'docs/ocr-runtime.lock.json').read_text('utf-8'))
    for relative, expected in manifest['files'].items():
        path = target / relative
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError(f'OCR 文件缺失或版本不符：{relative}')
    return manifest

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-only',action='store_true',help='offline hash check; never clone or download')
    args=parser.parse_args()
    manifest=json.loads((ROOT/'docs'/'ocr-runtime.lock.json').read_text('utf-8'))
    target=ROOT/'runtime'/'ocr'
    if not target.exists():
        if args.verify_only:
            raise FileNotFoundError('固定版本 OCR 未安装；离线检查不会自动下载。')
        target.parent.mkdir(parents=True,exist_ok=True)
        subprocess.run(['git','clone','--no-checkout',manifest['repository'],str(target)],check=True)
        subprocess.run(['git','checkout','--detach',manifest['commit']],cwd=target,check=True)
    locked=verify_runtime(target)
    print(f"OCR fixed build verified: {locked['commit']}")

if __name__=='__main__':
    main()
