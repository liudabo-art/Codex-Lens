"""Create the local public-source review archive from an explicit allowlist."""
from hashlib import sha256
from pathlib import Path
import re
import stat
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
FILES = (
    '.gitignore', 'AGENTS.md', 'SECURITY.md', 'LICENSE', 'VERSION', 'README.md',
    'FILE_GUIDE.md', 'WINDOWS.md', 'CHANGELOG.md', 'CONTRIBUTING.md', 'desktop.py', 'run.py', 'usage_worker.py',
    '启动中转检测.cmd', '启动桌面端.cmd',
    'requirements-build.txt', 'requirements-desktop.txt',
    'Technical-Documentation-Principles-of-Mathematics-Transfer-Station-Inspection.md',
    'README/README.md', 'README/README-Simplified_Chinese.md',
    'docs/DEVELOPMENT_PLAN.md', 'docs/EXTENDING.md', 'docs/METHODS.md',
    'docs/INSTALLATION.md', 'docs/RELEASING.md', 'docs/VERIFICATION.md',
    '.github/workflows/build-native.yml', '.github/workflows/synthetic.yml',
    'assets/codex-lens.svg', 'assets/codex-lens.png',
    'assets/codex-lens.ico', 'assets/codex-lens.icns', 'assets/workbench-demo.png',
    'relay_auditor/web/index.html', 'relay_auditor/web/app.js', 'relay_auditor/web/styles.css',
    'relay_auditor/vendor/__init__.py', 'relay_auditor/vendor/safety.py',
    'relay_auditor/vendor/sessions.py', 'tests/test_dashboard.cjs',
)
GROUPS = {
    'relay_auditor': ('*.py',),
    'tests': ('test_*.py',),
    'build_tools': ('*.py', '*.spec', '*.iss'),
}
TOKEN = re.compile(rb'gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,}|sk-(?:proj-)?[A-Za-z0-9_-]{45,}|-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----')
BINARY_ASSETS = {'.png', '.ico', '.icns'}


def local_file(path):
    for item in (*reversed(path.parents), path):
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('linked_public_source')
    if not path.is_file() or path.stat().st_nlink != 1:
        raise ValueError('public_source_file_required')
    return path


def stage():
    version = local_file(ROOT / 'VERSION').read_text(encoding='ascii').strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('invalid_version')
    sources = {ROOT / name for name in FILES}
    for folder, patterns in GROUPS.items():
        for pattern in patterns:
            sources.update((ROOT / folder).glob(pattern))
    contents = {}
    for path in sorted(sources):
        data = local_file(path).read_bytes()
        if len(data) > 2 * 1024 * 1024 or (path.suffix not in BINARY_ASSETS and TOKEN.search(data)):
            raise ValueError('public_source_review_required')
        contents[path.relative_to(ROOT).as_posix()] = data
    manifest = ''.join(f'{sha256(data).hexdigest()}  {name}\n' for name, data in contents.items())

    destination = ROOT / 'release'
    destination.mkdir(exist_ok=True)
    if destination.resolve() != destination:
        raise ValueError('linked_output')
    label = f'Codex-Lens-{version}-source'
    archive = destination / (label + '.zip')
    temporary = archive.with_suffix('.zip.tmp')
    with temporary.open('xb') as output:
        try:
            with ZipFile(output, 'w', compression=ZIP_DEFLATED) as package:
                for name, data in contents.items():
                    package.writestr(f'{label}/{name}', data)
                package.writestr(f'{label}/SOURCE-SHA256SUMS.txt', manifest)
        except BaseException:
            output.close()
            temporary.unlink()
            raise
    temporary.replace(archive)
    print(f'{archive.name}: {len(contents)} public files')


if __name__ == '__main__':
    try:
        stage()
    except (OSError, ValueError):
        raise SystemExit('public_source_stage_failed') from None
