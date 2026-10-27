"""Collect corresponding third-party sources for a portable binary release.

Downloads are explicit, resumable by complete file, and never run at GUI startup.
The resulting source archives must accompany the portable ZIP on GitHub Releases.
"""
from pathlib import Path
import argparse
import hashlib
import json
import urllib.request

ROOT = Path(__file__).resolve().parents[1]

def download(url, path):
    if path.exists():
        return
    print('Download:', path.name, flush=True)
    request = urllib.request.Request(url, headers={'User-Agent': 'MADAutoScript-release'})
    temporary = path.with_suffix(path.suffix + '.partial')
    with urllib.request.urlopen(request, timeout=60) as response, temporary.open('wb') as output:
        while block := response.read(1024 * 1024):
            output.write(block)
    temporary.replace(path)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'.cache/release-sources')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    sources = [
        ('Qt-5.15.2.tar.xz', 'https://download.qt.io/archive/qt/5.15/5.15.2/single/qt-everywhere-src-5.15.2.tar.xz', 'LGPL-3.0 / GPL-3.0 / component licenses'),
        ('BAAS_Cpp-4c276b1.tar.gz', 'https://codeload.github.com/pur1fying/BAAS_Cpp/tar.gz/4c276b1d514ecf2f9025be7d549cdbc31e6218f7', 'GPL-3.0'),
        ('ONNXRuntime-1.22.0-LICENSE.txt', 'https://raw.githubusercontent.com/microsoft/onnxruntime/v1.22.0/LICENSE', 'MIT'),
        ('OpenCV-4.9.0-LICENSE.txt', 'https://raw.githubusercontent.com/opencv/opencv/4.9.0/LICENSE', 'Apache-2.0'),
        ('PaddleOCR-LICENSE.txt', 'https://raw.githubusercontent.com/PaddlePaddle/PaddleOCR/v2.7.0/LICENSE', 'Apache-2.0'),
    ]
    for package, version in [('PyQt5', '5.15.11')]:
        with urllib.request.urlopen(f'https://pypi.org/pypi/{package}/{version}/json', timeout=30) as response:
            metadata = json.load(response)
        source = next(f for f in metadata['urls'] if f['packagetype'] == 'sdist')
        sources.append((source['filename'], source['url'], 'GPL-3.0'))
    records = []
    for name, url, license_name in sources:
        path = args.output/name
        download(url, path)
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        records.append({'file': name, 'url': url, 'license': license_name,
                        'sha256': digest,
                        'bytes': path.stat().st_size})
    (args.output/'SOURCES.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Corresponding sources collected.', flush=True)

if __name__ == '__main__':
    main()
