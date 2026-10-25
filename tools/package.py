"""Bundle attribution, dependency licenses and the editable launcher source."""
import hashlib
import importlib.metadata
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from psydroid import VERSION

bundle = root / 'dist' / 'PsyDroid'
notices = bundle / 'licenses'
notices.mkdir(parents=True, exist_ok=True)
for name in ('LICENSE', 'THIRD_PARTY_NOTICES.md', 'README.md'):
    shutil.copy2(root / name, bundle / name)
for dist in importlib.metadata.distributions():
    for path in dist.files or []:
        if any(token in path.name.upper() for token in ('LICENSE', 'COPYING', 'NOTICE')) and path.suffix != '.py':
            source = Path(dist.locate_file(path))
            if source.is_file():
                target = notices / dist.metadata['Name'] / Path(*path.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
source_zip = root / 'dist' / f'PsyDroid-{VERSION}-source.zip'
files = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard'], cwd=root, text=True)
with zipfile.ZipFile(source_zip, 'w', zipfile.ZIP_DEFLATED) as archive:
    for name in files.splitlines():
        file = root / name
        if file.is_file() and not name.startswith(('artifacts/',)):
            archive.write(file, f'PsyDroid-source/{name}')
shutil.copy2(source_zip, bundle / 'source.zip')
archive_path = root / 'dist' / f'PsyDroid-{VERSION}-windows-x64.zip'
with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    for file in bundle.rglob('*'):
        if file.is_file():
            archive.write(file, file.relative_to(bundle.parent))
checksums = []
for path in (archive_path, source_zip):
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    checksums.append(f'{digest}  {path.name}')
(root / 'dist' / 'SHA256SUMS.txt').write_text('\n'.join(checksums) + '\n', encoding='utf-8')
print(f'Portable ZIP: {archive_path.stat().st_size / 1e6:.1f} MB')
print(f'Unpacked launcher: {sum(f.stat().st_size for f in bundle.rglob("*") if f.is_file()) / 1e6:.1f} MB')
