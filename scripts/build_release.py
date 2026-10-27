"""Build clean MAD-only source and Windows portable ZIPs. Never publishes remotely."""
from pathlib import Path
import argparse
import ast
import hashlib
import importlib.metadata
import json
import shutil
import sys
import sysconfig
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BASELINE = '1110e88df5955df277737ea9717869b9ca88362b'
PUBLIC = [
    'README.md', 'CONTRIBUTING.md', 'CHANGELOG.md', 'LICENSE', 'UPSTREAM.txt', 'THIRD_PARTY.txt', 'NOTICE.md',
    'pyproject.toml', 'requirements.in', 'requirements.txt', 'requirements.lock.txt',
    '.gitignore', '.gitattributes', '.github/workflows/checks.yml', '启动MADAutoScript.cmd',
    '.github/ISSUE_TEMPLATE/bug_report.md', '.github/ISSUE_TEMPLATE/feature_request.md',
    '.github/pull_request_template.md', 'docs/STARTER_TASKS.md',
    'docs/ocr-runtime.lock.json', 'docs/STATUS.md', 'docs/RELEASING.md', 'docs/PRIVACY.md',
    'scripts/install_ocr.py', 'scripts/build_release.py', 'scripts/vendor_sources.py',
    'scripts/check_install.py', 'tests/test_shop_and_picker.py',
    'tests/test_ui_workspace.py', 'tests/test_release_core.py', 'tests/test_release_privacy.py',
    'src/game_catalog.json',
    'licenses/SOURCES.json', 'licenses/PyQt5-5.15.11-GPL.txt',
    'licenses/apkutils2-1.0.0-MIT.txt', 'licenses/cigam-0.0.3-MIT.txt',
    'licenses/retry-0.9.2-NOTICE.txt', 'licenses/Apache-2.0.txt',
    'licenses/ONNXRuntime-1.22.0-ThirdPartyNotices.txt',
]

def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

def public_catalog(data):
    # Only game definitions belong in the release, not local discovery evidence.
    return {key: data[key] for key in ('game_version', 'sweep', 'normal_zones', 'characters')}

def assert_no_private_paths(folder, roots):
    """Check raw, JSON-escaped and URI paths, including strings in runtime binaries."""
    markers = set()
    for root in roots:
        root = Path(root).resolve()
        for value in (str(root), root.as_posix(), root.as_uri()):
            for variant in (value, json.dumps(value, ensure_ascii=False)[1:-1],
                            json.dumps(value, ensure_ascii=True)[1:-1]):
                for encoding in ('utf-8', 'utf-16le'):
                    markers.add(variant.encode(encoding).lower())
    overlap = max(map(len, markers)) - 1
    for path in folder.rglob('*'):
        if not path.is_file(): continue
        with path.open('rb') as stream:
            tail = b''
            while block := stream.read(1024 * 1024):
                data = tail + block
                lowered = data.lower()
                if any(marker in lowered for marker in markers):
                    raise RuntimeError('Private local path in '+path.relative_to(folder).as_posix())
                tail = data[-overlap:]

def source_files():
    """Follow application imports, excluding TYPE_CHECKING-only legacy modules."""
    class Imports(ast.NodeVisitor):
        def __init__(self): self.names = []
        def visit_If(self, node):
            if ast.unparse(node.test) in ('TYPE_CHECKING', 'typing.TYPE_CHECKING'):
                for child in node.orelse: self.visit(child)
            else: self.generic_visit(node)
        def visit_Import(self, node): self.names.extend(a.name for a in node.names)
        def visit_ImportFrom(self, node):
            prefix = node.module or ''
            if node.level:
                parts = package.split('.')
                prefix = '.'.join(parts[:len(parts)-node.level+1] + ([prefix] if prefix else []))
            if prefix: self.names.append(prefix)
            self.names.extend(prefix+'.'+a.name for a in node.names if prefix and a.name != '*')
    pending, found = ['main', 'window'], {}
    while pending:
        name = pending.pop()
        if name in found: continue
        base = ROOT.joinpath(*name.split('.'))
        path = next((p for p in (base.with_suffix('.py'), base/'__init__.py')
                     if p.is_file() and p.name in {child.name for child in p.parent.iterdir()}), None)
        if path is None: continue
        found[name] = path.relative_to(ROOT).as_posix()
        package = name if path.name == '__init__.py' else name.rpartition('.')[0]
        visitor = Imports()
        visitor.visit(ast.parse(path.read_text('utf-8-sig')))
        pending.extend(visitor.names)
        for parent in path.parents:
            if parent == ROOT: break
            if (parent/'__init__.py').is_file():
                pending.append('.'.join(parent.relative_to(ROOT).parts))
    return sorted(found.values())

def copy_file(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    if target.suffix == '.cmd':
        text = target.read_text('utf-8').replace('\r\n', '\n')
        target.write_bytes(text.replace('\n', '\r\n').encode('utf-8'))

def clean_copy(source, target, *, skip_site=False):
    def ignore(directory, names):
        excluded = {n for n in names if n in ('__pycache__', '.git', '_virtualenv.py', '_virtualenv.pth',
                    'direct_url.json', '.env', '.netrc', '.pypirc', 'pip.ini', 'pip.conf',
                    'adbkey', 'adbkey.pub', 'id_rsa', 'id_ed25519')
                    or n.endswith(('.pyc', '.pyo', '.log'))}
        # MAD uses MuMu's ADB and PNG images; these optional binaries are unused.
        excluded.update(n for n in names if n.startswith('opencv_videoio_ffmpeg') and n.endswith('.dll'))
        if Path(directory).name == 'adbutils': excluded.add('binaries')
        if skip_site and Path(directory) == source/'Lib': excluded.add('site-packages')
        return excluded
    shutil.copytree(source, target, ignore=ignore, dirs_exist_ok=True)

def archive(folder, output, compression=zipfile.ZIP_DEFLATED):
    with zipfile.ZipFile(output, 'w', compression, compresslevel=6 if compression == zipfile.ZIP_DEFLATED else None) as bundle:
        for path in sorted(folder.rglob('*')):
            if path.is_file(): bundle.write(path, folder.name+'/'+path.relative_to(folder).as_posix())

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--python-runtime', type=Path, default=Path(sys.base_prefix))
    parser.add_argument('--site-packages', type=Path, default=Path(sysconfig.get_path('purelib')))
    parser.add_argument('--third-party-sources', type=Path, default=ROOT/'.cache/release-sources')
    args = parser.parse_args()
    if sys.platform != 'win32' or sys.version_info[:2] != (3, 11):
        parser.error('Use Windows x64 Python 3.11 to build this portable release.')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    version = next(n.value.value for n in ast.parse((ROOT/'main.py').read_text('utf-8')).body
                   if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'APP_VERSION' for t in n.targets))
    from install_ocr import verify_runtime
    ocr = verify_runtime(ROOT/'runtime/ocr')
    source_records = json.loads((args.third_party_sources/'SOURCES.json').read_text('utf-8'))
    for record in source_records:
        assert sha(args.third_party_sources/record['file']) == record['sha256'], record['file']
    license_records = json.loads((ROOT/'licenses/SOURCES.json').read_text('utf-8'))
    for record in license_records:
        assert sha(ROOT/'licenses'/record['file']) == record['sha256'], record['file']
    source = output/'source/MADAutoScript'
    portable = output/'windows/MADAutoScript'
    modules = source_files()
    for relative in sorted(set(PUBLIC + modules)):
        copy_file(ROOT/relative, source/relative)
    write_json(source/'src/game_catalog.json',
               public_catalog(json.loads((ROOT/'src/game_catalog.json').read_text('utf-8'))))
    assets = ROOT/'src/images/MAD_onestore_zh-CN'
    provenance = json.loads((assets/'provenance.json').read_text('utf-8'))
    for name, entry in provenance['templates'].items():
        path = assets/(name+'.png')
        assert sha(path) == entry['sha256'], name
        copy_file(path, source/'src/images/MAD_onestore_zh-CN'/path.name)
        entry['source'] = 'local-ui-capture:'+entry.get('source_sha256', '')
        entry['copyright'] = 'MAD game UI; original rights holders; not GPL artwork'
    write_json(source/'src/images/MAD_onestore_zh-CN/provenance.json', provenance)
    private_roots = (ROOT.parent, Path.home())
    print('Source:', len(modules), 'application modules', flush=True)
    shutil.copytree(source, portable)
    python = portable/'runtime/python'
    clean_copy(args.python_runtime.resolve(), python, skip_site=True)
    clean_copy(args.site_packages.resolve(), python/'Lib/site-packages')
    for relative in ocr['files']:
        copy_file(ROOT/'runtime/ocr'/relative, portable/'runtime/ocr'/relative)
    copy_file(ROOT/'LICENSE', portable/'licenses/BAAS_Cpp-GPL-3.0.txt')
    for record in source_records:
        if record['file'].endswith('.txt'):
            copy_file(args.third_party_sources/record['file'], portable/'licenses'/record['file'])
    distributions = []
    for distribution in importlib.metadata.distributions(path=[str(args.site_packages)]):
        metadata = distribution.metadata
        license_files = [str(f) for f in (distribution.files or [])
                         if any(w in f.name.upper() for w in ('LICENSE', 'COPYING', 'NOTICE'))
                         and (args.site_packages/f).is_file()]
        supplement = ['licenses/'+r['file'] for r in license_records
                      if r['package'].lower().replace('_', '-') == metadata['Name'].lower().replace('_', '-')]
        if not license_files and not supplement:
            raise RuntimeError('Missing distributed license text: '+metadata['Name'])
        distributions.append({'name': metadata['Name'], 'version': distribution.version,
            'license': metadata.get('License-Expression') or metadata.get('License', ''),
            'home_page': metadata.get('Home-page', ''),
            'project_urls': metadata.get_all('Project-URL', []),
            'license_files': license_files, 'supplemental_license_files': supplement})
    distributions.sort(key=lambda item: item['name'].lower())
    write_json(source/'docs/dependencies.json', {'python': sys.version, 'distributions': distributions,
               'license_path_base': 'runtime/python/Lib/site-packages in portable package; supplements relative to application root',
               'ocr': {'commit': ocr['commit'], 'source_commit': ocr['source_commit']}})
    copy_file(source/'docs/dependencies.json', portable/'docs/dependencies.json')
    write_json(source/'docs/source-manifest.json', {
        'application': 'MADAutoScript', 'version': version, 'baas_baseline': BASELINE,
        'application_modules': modules,
        'files': {p.relative_to(source).as_posix(): sha(p) for p in sorted(source.rglob('*')) if p.is_file()},
    })
    copy_file(source/'docs/source-manifest.json', portable/'docs/source-manifest.json')
    assert_no_private_paths(source, private_roots)
    assert_no_private_paths(portable, private_roots)
    source_zip = output/f'MADAutoScript-{version}-source.zip'
    portable_zip = output/f'MADAutoScript-{version}-windows-x64.zip'
    third_zip = output/f'MADAutoScript-{version}-third-party-sources.zip'
    archive(source, source_zip)
    print('Compressing portable runtime...', flush=True)
    archive(portable, portable_zip)
    with zipfile.ZipFile(third_zip, 'w', zipfile.ZIP_STORED) as bundle:
        bundle.write(args.third_party_sources/'SOURCES.json', 'SOURCES.json')
        for record in source_records:
            bundle.write(args.third_party_sources/record['file'], record['file'])
        for path in sorted((source/'licenses').iterdir()):
            if path.is_file(): bundle.write(path, 'licenses/'+path.name)
    files = [source_zip, portable_zip, third_zip]
    (output/'SHA256SUMS.txt').write_text(''.join(sha(p)+'  '+p.name+'\n' for p in files), encoding='utf-8')
    write_json(output/'build-result.json', {'version': version, 'modules': len(modules),
               'archives': [{'file': p.name, 'bytes': p.stat().st_size, 'sha256': sha(p)} for p in files]})
    print('Built:', output, flush=True)

if __name__ == '__main__':
    main()
