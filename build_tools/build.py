"""Build Relay Auditor natively from public source and synthetic fixtures."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile


ROOT = Path(__file__).resolve().parents[1]
NAME = 'Relay-Auditor'
DISPLAY_NAME = 'Codex Lens'
ARCHES = {'amd64': 'x64', 'x86_64': 'x64', 'aarch64': 'arm64', 'arm64': 'arm64'}
SYSTEMS = {'win32': 'windows', 'darwin': 'macos', 'linux': 'linux'}


def native_target():
    system, arch = SYSTEMS.get(sys.platform), ARCHES.get(platform.machine().lower())
    if not system or not arch or system == 'windows' and arch != 'x64':
        raise ValueError('unsupported_native_builder')
    if system == 'linux' and (platform.libc_ver()[0] != 'glibc'
                              or tuple(map(int, platform.libc_ver()[1].split('.')[:2])) != (2, 39)):
        raise ValueError('linux_builder_requires_glibc_2_39')
    return system, arch


def app_version():
    version = (ROOT/'VERSION').read_text(encoding='ascii').strip()
    if not re.fullmatch(r'(?:0|[1-9][0-9]{0,4})(?:\.(?:0|[1-9][0-9]{0,4})){2}', version):
        raise ValueError('invalid_version')
    if any(int(part) > 65535 for part in version.split('.')):
        raise ValueError('invalid_version')
    return version


def run(*args):
    subprocess.run([str(arg) for arg in args], cwd=ROOT, check=True)


def windows_version(build_dir, version):
    parts = tuple(map(int, version.split('.'))) + (0,)
    (build_dir/'windows-version.txt').write_text(f'''VSVersionInfo(
ffi=FixedFileInfo(filevers={parts!r}, prodvers={parts!r}, mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0,0)),
kids=[StringFileInfo([StringTable('040904B0', [
StringStruct('FileDescription', 'Codex Lens - Relay Model Auditor'),
StringStruct('FileVersion', '{version}'),
StringStruct('ProductVersion', '{version}'),
StringStruct('ProductName', '{DISPLAY_NAME}'),
StringStruct('OriginalFilename', '{NAME}.exe')])]),
VarFileInfo([VarStruct('Translation', [1033,1200])])])''', encoding='utf-8')


def copy_licenses(bundle, system):
    shutil.copy2(ROOT/'LICENSE', bundle/'LICENSE')
    shutil.copy2(ROOT/'README.md', bundle/'README.md')
    if system == 'windows':
        shutil.copy2(ROOT/'WINDOWS.md', bundle/'使用说明-README.md')
    licenses = bundle/'third-party-licenses'
    licenses.mkdir()
    dependencies = ('pywebview', 'proxy_tools', 'bottle', 'typing_extensions', 'pyinstaller',
                    'pyinstaller-hooks-contrib', 'altgraph', 'packaging', 'setuptools')
    extra = {
        'windows': ('pythonnet', 'clr_loader', 'cffi', 'pycparser', 'pefile', 'pywin32-ctypes'),
        'macos': ('pyobjc-core', 'pyobjc-framework-Cocoa', 'pyobjc-framework-Quartz', 'pyobjc-framework-WebKit',
                  'pyobjc-framework-Security', 'pyobjc-framework-UniformTypeIdentifiers'),
        'linux': ('pygobject', 'pycairo'),
    }
    inventory = []
    for name in dependencies + extra[system]:
        dist = importlib.metadata.distribution(name)
        inventory.append({'name':dist.metadata['Name'], 'version':dist.version})
        destination = licenses/name
        destination.mkdir()
        for item in dist.files or []:
            if any(word in item.name.lower() for word in ('license', 'copying', 'notice')):
                original = dist.locate_file(item)
                if original.is_file():
                    shutil.copy2(original, destination/item.name)
    for python_license in (Path(sys.base_prefix)/'LICENSE.txt', Path(sys.base_prefix)/'LICENSE'):
        if python_license.is_file():
            shutil.copy2(python_license, licenses/'Python-LICENSE.txt')
            break
    (bundle/'dependencies.json').write_text(json.dumps(inventory, indent=2), encoding='utf-8')


def inno_compiler():
    candidate = os.environ.get('ISCC') or shutil.which('ISCC') or r'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
    if not Path(candidate).is_file():
        raise ValueError('inno_setup_6_required')
    return candidate


def package_windows(bundle, output, stem, version, compiler):
    archive = shutil.make_archive(str(output/(stem+'-portable')), 'zip', root_dir=bundle.parent, base_dir=bundle.name)
    paths = [Path(archive)]
    if compiler:
        run(compiler, f'/DAppVersion={version}', f'/DAppSource={bundle}', f'/O{output}',
            ROOT/'build_tools/windows.iss')
        paths.append(output/(stem+'-Setup.exe'))
    return paths


def package_macos(app, output, stem):
    stage = output/'dmg-stage'
    stage.mkdir()
    shutil.copytree(app, stage/app.name, symlinks=True)
    (stage/'Applications').symlink_to('/Applications', target_is_directory=True)
    image = output/(stem+'.dmg')
    run('hdiutil', 'create', '-volname', DISPLAY_NAME, '-srcfolder', stage, '-format', 'UDZO', image)
    run('hdiutil', 'verify', image)
    return [image]


def package_linux(bundle, output, stem, version, arch):
    portable = output/(stem+'.tar.gz')
    with tarfile.open(portable, 'w:gz') as archive:
        archive.add(bundle, arcname=NAME)
    stage = output/'deb-stage'
    opt = stage/'opt'/NAME
    shutil.copytree(bundle, opt, symlinks=True)
    desktop = stage/'usr/share/applications'
    desktop.mkdir(parents=True)
    (desktop/'relay-auditor.desktop').write_text(f'''[Desktop Entry]
Type=Application
Name={DISPLAY_NAME}
Comment=Local relay model quality auditor
Exec=/opt/{NAME}/{NAME}
Icon=relay-auditor
Terminal=false
Categories=Utility;
''', encoding='utf-8')
    icons = stage/'usr/share/icons/hicolor/512x512/apps'
    icons.mkdir(parents=True)
    shutil.copy2(ROOT/'assets/codex-lens.png', icons/'relay-auditor.png')
    control = stage/'DEBIAN'
    control.mkdir()
    (control/'control').write_text(f'''Package: relay-auditor
Version: {version}
Section: utils
Priority: optional
Architecture: {'amd64' if arch == 'x64' else 'arm64'}
Maintainer: Codex Lens contributors
Depends: libc6 (>= 2.39), gir1.2-gtk-3.0, gir1.2-webkit2-4.1
Description: Local relay model quality auditor
''', encoding='utf-8')
    package = output/(stem+'.deb')
    run('dpkg-deb', '--build', '--root-owner-group', stage, package)
    run('dpkg-deb', '--info', package)
    return [portable, package]


def build(*, portable_only=False):
    system, arch = native_target()
    if portable_only and system != 'windows':
        raise ValueError('portable_only_is_windows_specific')
    version = app_version()
    compiler = inno_compiler() if system == 'windows' and not portable_only else None
    build_dir = ROOT/'build'
    build_dir.mkdir(exist_ok=True)
    if system == 'windows':
        windows_version(build_dir, version)
    candidate = 'candidate-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    distribution = ROOT/'dist'/candidate
    with (build_dir/'pyinstaller.log').open('w', encoding='utf-8') as log:
        subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
                        '--distpath', str(distribution), '--workpath', str(build_dir/'pyinstaller'),
                        str(ROOT/'build_tools/relay.spec')], cwd=ROOT, check=True, stdout=log, stderr=subprocess.STDOUT)
    bundle = distribution/NAME
    if system == 'macos':
        app = distribution/(DISPLAY_NAME+'.app')
        resources = app/'Contents/Resources'
        copy_licenses(resources, system)
        # PyInstaller signs its generated bundle; re-seal the added public notices.
        run('codesign', '--force', '--sign', '-', app)
        run('codesign', '--verify', '--deep', '--strict', app)
        run(sys.executable, '-B', ROOT/'build_tools/smoke.py', app)
    else:
        copy_licenses(bundle, system)
        run(sys.executable, '-B', ROOT/'build_tools/smoke.py', bundle)
    stem = f'{NAME}-{version}-{system}-{arch}'
    staging = build_dir/candidate
    staging.mkdir()
    if system == 'windows':
        packages = package_windows(bundle, staging, stem, version, compiler)
    elif system == 'macos':
        packages = package_macos(app, staging, stem)
    else:
        packages = package_linux(bundle, staging, stem, version, arch)
    checksums = []
    for package in sorted(packages):
        with package.open('rb') as handle:
            checksums.append(hashlib.file_digest(handle, 'sha256').hexdigest()+'  '+package.name)
    release = ROOT/'release'
    release.mkdir(exist_ok=True)
    for package in packages:
        package.replace(release/package.name)
    (release/f'SHA256SUMS-{system}-{arch}.txt').write_text('\n'.join(checksums)+'\n', encoding='ascii')
    if system == 'windows':
        (ROOT/'dist/latest-desktop.cmd').write_text('@echo off\nstart "" "%~dp0'+candidate+'\\'+NAME+'\\'+NAME+'.exe"\n',encoding='ascii')
    print(f'{system}_{arch}_native_packages_built')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--portable-only', action='store_true', help='Windows only: build the ZIP without an installer compiler')
    args = parser.parse_args()
    try:
        build(portable_only=args.portable_only)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, subprocess.SubprocessError, importlib.metadata.PackageNotFoundError):
        print('desktop_build_failed; see the local build log if available', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
