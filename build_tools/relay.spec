# Public source/assets only; never collect private output, configuration or logs.
from pathlib import Path
import sys

root = Path(SPECPATH).parent
version = (root/'VERSION').read_text(encoding='ascii').strip()
excludes = ['pytest', 'IPython', 'numpy', 'matplotlib', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'cefpython3']
hidden = {
    'win32': ['webview.platforms.edgechromium', 'webview.platforms.winforms'],
    'darwin': ['webview.platforms.cocoa'],
    'linux': ['webview.platforms.gtk'],
}[sys.platform]
ui = Analysis([str(root/'desktop.py')], pathex=[str(root)],
              datas=[(str(root/'relay_auditor/web'), 'relay_auditor/web'),
                     (str(root/'assets/codex-lens.png'), 'assets')],
              hiddenimports=hidden,
              excludes=excludes, binaries=[], hookspath=[], runtime_hooks=[], noarchive=False)
ui_pyz = PYZ(ui.pure)
ui_exe = EXE(ui_pyz, ui.scripts, [], exclude_binaries=True, name='Relay-Auditor',
             console=False, debug=False, upx=False, strip=False,
             version=str(root/'build/windows-version.txt') if sys.platform == 'win32' else None,
             icon=str(root/'assets/codex-lens.ico') if sys.platform == 'win32' else None)
worker = Analysis([str(root/'usage_worker.py')], pathex=[str(root)], datas=[], binaries=[],
                  hiddenimports=[], excludes=excludes+['webview','clr','pythonnet','tkinter'],
                  hookspath=[], runtime_hooks=[], noarchive=False)
worker_pyz = PYZ(worker.pure)
worker_exe = EXE(worker_pyz, worker.scripts, [], exclude_binaries=True, name='Relay-Auditor-Worker',
                 console=True, debug=False, upx=False, strip=False)
bundle = COLLECT(ui_exe, worker_exe, ui.binaries, ui.datas, worker.binaries, worker.datas,
                 name='Relay-Auditor', upx=False, strip=False)
if sys.platform == 'darwin':
    app = BUNDLE(bundle, name='Codex Lens.app', icon=str(root/'assets/codex-lens.icns'),
                 bundle_identifier='org.codex-lens.relay-auditor',
                 info_plist={'CFBundleShortVersionString': version, 'CFBundleVersion': version,
                             'CFBundleDisplayName': 'Codex Lens', 'NSHighResolutionCapable': True,
                             'LSMinimumSystemVersion': '13.0',
                             'NSAppTransportSecurity': {'NSAllowsLocalNetworking': True}})
