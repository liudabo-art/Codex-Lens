"""Narrow native actions; selections never return paths or secrets to JS."""
from datetime import datetime, timezone
import json
import secrets
import threading

from .catalog import read_catalog, locate_catalog
from .observer import Observer
from .storage import checked_path, safe_snapshot


class DesktopActions:
    def __init__(self, service, choose, open_folder, flash):
        self.service, self.choose = service, choose
        self.open_folder, self.flash = open_folder, flash
        self.lock = threading.Lock()
        self.observer = None
        self.notifications = False
        self.last_notification = service.notification_id

    def dispatch(self, route, body):
        if not self.lock.acquire(blocking=False):
            raise ValueError('dialog_busy')
        try:
            if route == 'catalog':
                source = body.get('source')
                if source not in ('cc_switch', 'codexplusplus'):
                    raise ValueError('invalid_source')
                selection = (str(locate_catalog(source)),) if body.get('auto') is True else self.choose('file', source)
                if not selection:
                    return {'ok': True, 'cancelled': True}
                catalog = read_catalog(source, selection[0], self.service.store.directory)
                with self.service.lock:
                    self.service.catalog, self.service.catalog_source = catalog, source
            elif route == 'observe':
                selection = self.choose('folder', None)
                if not selection:
                    return {'ok': True, 'cancelled': True}
                observer = Observer(self.service, selection[0])
                if self.observer:
                    self.observer.stop()
                self.observer = observer
                observer.start()
            elif route == 'export':
                format=body.get('format','json')
                if format not in ('json','html'): raise ValueError('invalid_export_format')
                folder = checked_path(self.service.store.directory/'exports')
                folder.mkdir(exist_ok=True)
                filename = 'relay-assessment-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + secrets.token_hex(4) + '.'+format
                path = checked_path(folder/filename)
                # Exclusive creation never overwrites original configuration/data.
                with path.open('x', encoding='utf-8') as handle:
                    if format=='html':
                        from .exporting import html_report
                        handle.write(html_report(self.service.snapshot()))
                    else: json.dump(safe_snapshot(self.service.snapshot()), handle, ensure_ascii=False, allow_nan=False, indent=2)
                self.open_folder(folder)
            elif route == 'notifications':
                enabled = body.get('enabled')
                if type(enabled) is not bool:
                    raise ValueError('invalid_enabled')
                self.notifications = enabled
                self.last_notification = self.service.notification_id
            elif route == 'notify':
                current = self.service.notification_id
                if self.notifications and current > self.last_notification:
                    self.flash()
                self.last_notification = current
            else:
                raise ValueError('invalid_desktop_action')
            return {'ok': True}
        finally:
            self.lock.release()

    def close(self):
        if self.observer:
            self.observer.stop()
