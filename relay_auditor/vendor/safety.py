"""Process-level offline and read-only boundaries; no dependencies."""
from __future__ import annotations

import os
from pathlib import Path
import stat
import sys


def checked_local_path(value: str | Path) -> Path:
    text = os.fspath(value)
    if text.startswith(('\\\\', '//')) or '://' in text:
        raise ValueError('只允许本机磁盘路径，禁止 UNC、网络路径和 URL。')
    path = Path(os.path.abspath(text))
    if os.name == 'nt':
        import ctypes
        if ctypes.windll.kernel32.GetDriveTypeW(str(path.anchor)) == 4:
            raise ValueError('禁止网络映射盘。')
    # Check from root to leaf so a remote junction is rejected before walking it.
    for part in (*reversed(path.parents), path):
        try:
            info=part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or (os.name=='nt' and getattr(info,'st_file_attributes',0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise ValueError('禁止通过符号链接或目录联接读取或写入文件。')
    return path


def inside(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def validate_output(output: Path, home: Path, protected: list[Path] | None = None) -> Path:
    output = checked_local_path(output)
    for root in [home, *(protected or [])]:
        checked_root = checked_local_path(root)
        if inside(output, checked_root) or inside(checked_root, output):
            raise ValueError('报告目录不能与 Codex 数据或安装目录相互包含。')
    return output


def install_guard(output: Path, *, official_launch: dict | None = None):
    """Deny sockets/arbitrary processes; restrict writes to the report directory.

    Optional official_launch is a one-shot exact stdio process exception.
    This is defense in depth for Python, not an OS sandbox for the native child.
    """
    root = checked_local_path(output)
    # PyInstaller's macOS app layout links packaged data between Frameworks
    # and Resources. Trust only read-only files whose lexical AND resolved
    # locations stay inside this executable's bundle. Source path validation
    # still rejects links, and writes never receive this exception.
    bundle_root = None
    if getattr(sys, 'frozen', False) and getattr(sys, '_MEIPASS', None):
        runtime = Path(sys._MEIPASS).resolve()
        if sys.platform == 'darwin' and runtime.name == 'Frameworks' and runtime.parent.name == 'Contents':
            runtime = runtime.parent
        bundle_root = runtime
    sys.dont_write_bytecode = True
    launching = False
    launched = False

    def launch_official():
        # The only exception is one exact precomputed stdio process. No shell,
        # arbitrary arguments, inherited environment or subsequent launches.
        nonlocal launching, launched
        if not official_launch or launched:
            raise PermissionError('未授权官方同步进程。')
        import subprocess
        launched = True
        launching = True
        try:
            return subprocess.Popen(official_launch['args'], executable=official_launch['args'][0], cwd=official_launch['cwd'],
                env=official_launch['env'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        finally:
            launching = False

    def writable(value: object) -> None:
        if isinstance(value, int):
            raise PermissionError('禁止通过文件描述符写入。')
        target = checked_local_path(os.fsdecode(value))
        if not inside(target, root):
            raise PermissionError('只允许写入独立的报告输出目录。')
        try:
            info=target.stat()
            if stat.S_ISREG(info.st_mode) and info.st_nlink>1:
                raise PermissionError('禁止修改含多个硬链接的文件，防止间接写入源数据。')
        except FileNotFoundError:
            pass

    def audit(event: str, args: tuple) -> None:
        if event == 'subprocess.Popen' and launching and official_launch:
            import subprocess
            executable, command, cwd, env = args
            expected = subprocess.list2cmdline(official_launch['args']) if os.name == 'nt' else official_launch['args']
            if (executable == official_launch['args'][0] and command == expected
                    and cwd == official_launch['cwd'] and env == official_launch['env']):
                return
        if event.startswith(('socket.', 'subprocess.', 'urllib.', 'http.client.', 'ftplib.', 'smtplib.')):
            raise PermissionError('离线策略：禁止网络及子进程。')
        if event in ('os.system', 'os.startfile', 'os.startfile/2', 'os.posix_spawn', 'os.spawn', 'os.exec', 'os.fork', 'os.forkpty'):
            raise PermissionError('离线策略：禁止启动外部程序。')
        if event == 'open':
            filename, mode, flags = args
            if launching and (isinstance(filename, int) or filename == os.devnull):
                return
            if isinstance(filename, int):
                # Existing stdin/stdout/stderr are the only accepted descriptors.
                if filename not in (0, 1, 2):
                    raise PermissionError('禁止访问任意文件描述符。')
                return
            writing = (isinstance(mode, str) and any(x in mode for x in 'wax+')) or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            if bundle_root is not None and not writing:
                resource = Path(os.path.abspath(os.fsdecode(filename)))
                if inside(resource, bundle_root) and inside(resource.resolve(), bundle_root):
                    checked_local_path(resource.resolve())
                    return
            checked_local_path(os.fsdecode(filename))
            if writing:
                writable(filename)
        elif event in ('os.remove', 'os.rmdir', 'os.mkdir', 'os.chmod', 'os.utime', 'os.truncate'):
            writable(args[0])
        elif event in ('os.rename', 'os.replace'):
            writable(args[0]); writable(args[1])
        elif event in ('os.symlink', 'os.link'):
            raise PermissionError('禁止创建链接。')
        elif event in ('os.listdir', 'os.scandir') and args and args[0] is not None:
            checked_local_path(os.fsdecode(args[0]))
        elif event == 'sqlite3.connect':
            from urllib.parse import urlsplit, unquote, parse_qs
            uri = str(args[0])
            parsed = urlsplit(uri)
            filename = unquote(parsed.path)
            if os.name == 'nt' and filename.startswith('/') and len(filename)>2 and filename[2]==':':
                filename=filename[1:]
            if parsed.scheme != 'file' or parsed.netloc or parse_qs(parsed.query).get('mode') != ['ro']:
                raise PermissionError('SQLite 只允许通过 mode=ro 读取报告目录中的副本。')
            writable(filename)
    sys.addaudithook(audit)
    return launch_official
