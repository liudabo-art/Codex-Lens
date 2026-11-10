"""Local source reads are delegated to a fixed offline guarded worker."""
import json
import os
import subprocess
import threading

from .storage import checked_path, safe_snapshot
from .runtime import worker_command


class Observer:
    def __init__(self, service, home):
        self.service = service
        self.home = checked_path(home)
        output = service.store.directory
        if self.home == output or self.home in output.parents or output in self.home.parents:
            raise ValueError('source_output_overlap')
        self.stop_event = threading.Event()
        self.process = None
        self.process_lock = threading.Lock()
        self.thread = None

    def refresh(self):
        service = self.service
        with service.lock:
            targets = [{'source_alias': alias, 'base_url': m.target.base_url}
                       for alias, m in service.monitors.items()]
        try:
            command = worker_command()
            with self.process_lock:
                if self.stop_event.is_set() or service.stop_event.is_set():
                    return
                self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                                stderr=subprocess.DEVNULL,
                                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                process = self.process
            try:
                output, _ = process.communicate(json.dumps({'home': str(self.home), 'output': str(service.store.directory),
                                                            'targets': targets}).encode(), timeout=120)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                raise ValueError('worker_timeout') from None
            finally:
                with self.process_lock:
                    self.process = None
            if self.stop_event.is_set() or service.stop_event.is_set():
                return
            if process.returncode != 0 or len(output) > 100000:
                raise ValueError('worker_limit')
            body = json.loads(output)
            usage = safe_snapshot(body.get('usage', {}))
            with service.lock:
                service.local_usage = usage
                for alias in body.get('active_aliases', []):
                    if alias in service.monitors:
                        service.mark_active(alias)
        except Exception:
            with service.lock:
                service.local_usage = {'local_status': 'unavailable', 'source_kind': 'unknown'}

    def start(self):
        def loop():
            while not self.stop_event.is_set() and not self.service.stop_event.is_set():
                self.refresh()
                self.stop_event.wait(15)
        self.thread = threading.Thread(target=loop, daemon=True, name='relay-usage-observer')
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        with self.process_lock:
            if self.process and self.process.poll() is None:
                self.process.terminate()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=2)
