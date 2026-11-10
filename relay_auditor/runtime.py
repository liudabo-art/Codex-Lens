"""Fixed runtime locations and worker entry; no parent-project imports."""
import os
from pathlib import Path
import subprocess
import sys

from .storage import checked_path


def data_directory(*, desktop=False):
    if desktop or getattr(sys, 'frozen', False):
        if sys.platform == 'win32':
            base = Path(os.environ.get('LOCALAPPDATA', ''))
        elif sys.platform == 'darwin':
            base = Path.home()/'Library'/'Application Support'
        elif sys.platform.startswith('linux'):
            base = Path(os.environ.get('XDG_DATA_HOME', ''))
            if not base.is_absolute():
                base = Path.home()/'.local'/'share'
        else:
            raise ValueError('desktop_platform_unsupported')
        if not base.is_absolute():
            raise ValueError('local_data_unavailable')
        return checked_path(base/'Relay-Auditor')
    return checked_path(Path(__file__).resolve().parents[1]/'.relay-data')


def worker_command():
    if getattr(sys, 'frozen', False):
        filename = 'Relay-Auditor-Worker.exe' if sys.platform == 'win32' else 'Relay-Auditor-Worker'
        worker = checked_path(Path(sys.executable).with_name(filename))
        if not worker.is_file():
            raise ValueError('worker_unavailable')
        return [str(worker)]
    return [sys.executable, '-I', '-S', '-B', str(Path(__file__).resolve().parents[1]/'usage_worker.py')]


def open_export_folder(folder):
    folder = checked_path(folder)
    if sys.platform == 'win32':
        os.startfile(folder)
        return
    opener = '/usr/bin/open' if sys.platform == 'darwin' else '/usr/bin/xdg-open'
    env = os.environ.copy()
    if getattr(sys, 'frozen', False):
        library_path = env.pop('LD_LIBRARY_PATH_ORIG', None)
        env.pop('LD_LIBRARY_PATH', None)
        if library_path:
            env['LD_LIBRARY_PATH'] = library_path
    subprocess.Popen([opener, str(folder)], env=env, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
