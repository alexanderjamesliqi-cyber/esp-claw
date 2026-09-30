"""Package exact CI binaries, public tools and hashes without local credentials."""
import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--image', choices=['product', 'factory'], required=True)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
root = Path(__file__).resolve().parents[3]
project = 'edge_agent' if a.image == 'product' else 'spark_factory'
build = root / 'application' / project / 'build'
out = a.output.resolve()
out.mkdir(parents=True, exist_ok=False)
flash = json.loads((build / 'flasher_args.json').read_text())
for name in set(flash['flash_files'].values()) | {'flasher_args.json'}:
    source = (build / name).resolve()
    if not source.is_relative_to(build.resolve()):
        raise ValueError('Flash input outside build directory')
    target = out / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
tools = out / 'tools'
tools.mkdir()
for name in ['device.py', 'update_device.py', 'requirements-factory.txt'] + (['factory_station.py'] if a.image == 'factory' else []):
    shutil.copy2(root / 'integration/labplus/tools' / name, tools / name)
shutil.copy2(root / 'integration/labplus/FACTORY_IDENTITY.md', out / 'FACTORY_IDENTITY.md')
if a.image == 'product':
    shutil.copytree(root / 'integration/labplus/sdcard', out / 'sdcard', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    licenses = out / 'licenses'
    licenses.mkdir()
    for name in ['OFL.txt', 'RobotoMono-OFL.txt']:
        shutil.copy2(root / 'integration/labplus/assets' / name, licenses / name)
manifest = {
    'image': a.image,
    'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
    'board': 'labplus_ledong_max_v1',
    'hardware_validated': False,
    'files': {str(f.relative_to(out)): hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(out.rglob('*')) if f.is_file()},
}
(out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
print(out)
