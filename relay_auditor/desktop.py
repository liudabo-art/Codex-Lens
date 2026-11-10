"""Native window lifetime owns the opt-in engine and loopback service."""
import json
import logging
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
from urllib.parse import urldefrag

from .controller import Service
from .desktop_actions import DesktopActions
from .runtime import data_directory, open_export_folder
from .server import make_server
from .storage import Store, checked_path
from .core import Auditor


TITLE = '中转模型检测 · Relay Auditor'
START_ERROR = '桌面端无法启动。请确认系统已安装 Microsoft Edge WebView2 Runtime，并完整解压便携包。源码启动还需要桌面依赖。未启动模型检测。'
START_ERRORS = {
    'win32': START_ERROR,
    'darwin': '桌面端无法启动。请确认安装包与本机 macOS 架构匹配，并完整安装应用。源码启动需要 Cocoa 桌面依赖。未启动模型检测。',
    'linux': '桌面端无法启动。请确认已进入图形桌面，并已安装 GTK 3 和 WebKitGTK 4.1。未启动模型检测。',
}
BACKENDS = {'win32': ('edgechromium', 'edgechromium'), 'darwin': ('cocoa', 'wkwebview'),
            'linux': ('gtk', 'gtkwebkit2')}


def catalog_dialog_types(source):
    if source not in ('cc_switch', 'codexplusplus'):
        raise ValueError('invalid_source')
    return ('CC Switch (*.db)',) if source == 'cc_switch' else ('Codex settings (*.json)',)


def load_webview():
    import webview
    return webview


def show_error(message):
    if os.name == 'nt':
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, TITLE, 0x10)
        return
    if sys.platform == 'darwin':
        try:
            import AppKit
            AppKit.NSApplication.sharedApplication()
            alert = AppKit.NSAlert.alloc().init()
            alert.setMessageText_(TITLE)
            alert.setInformativeText_(message)
            alert.runModal()
            return
        except Exception:
            pass
    if sys.stderr is not None:
        print(message, file=sys.stderr)


class DesktopSession:
    def __init__(self, directory):
        self.auditor=Auditor(directory,persist_settings=True)
        self.store,self.service=self.auditor.store,self.auditor.service
        self.server = make_server(self.service, desktop=self)
        self.thread = None
        self.closed = False
        self.actions = None

    def dispatch(self, route, body):
        if not self.actions:
            raise ValueError('desktop_not_ready')
        return self.actions.dispatch(route, body)

    def start(self):
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True, name='relay-desktop-server')
        self.thread.start()
        self.service.start()

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.service.stop()
        if self.actions:
            self.actions.close()
        if self.thread:
            self.server.shutdown()
            self.thread.join(timeout=2)
        self.server.server_close()
        # An issued API request may still settle its reservation. Keep its
        # connection alive until process exit rather than close beneath it.
        self.auditor.close()


class LocalWindowPolicy:
    def __init__(self, url, renderer='edgechromium'):
        self.url = url
        self.renderer = renderer
        self.failed = False
        self.filter_ready = False

    def initialized(self, renderer):
        # pywebview may fall back to a backend without our native policy.
        if renderer != self.renderer:
            self.failed = True
            return False

    def fail(self, window):
        self.failed = True
        def close_after_show():
            try:
                if window.events.shown.wait(10):
                    window.destroy()
            except Exception:
                pass
        threading.Thread(target=close_after_show, daemon=True, name='relay-window-startup-failure').start()

    def allows_navigation(self, url):
        return urldefrag(url)[0] == self.url

    def allows_resource(self, url):
        return url.startswith(self.url) or url == 'data:,'

    def content_rules(self):
        # A session URL is ASCII, including unescaped hyphens in its random token.
        prefix = re.escape(self.url).replace(r'\-', '-')
        return json.dumps([
            {'trigger': {'url-filter': '.*'}, 'action': {'type': 'block'}},
            *({'trigger': {'url-filter': expression, 'url-filter-is-case-sensitive': True},
               'action': {'type': 'ignore-previous-rules'}}
              for expression in ('^' + prefix, '^data:,$')),
        ])

    def install(self, window, profile=None):
        try:
            if self.renderer == 'edgechromium':
                self._install_edge(window)
                return
            # The renderer starts at a blank page. Only a successfully compiled
            # native filter can start loading the protected local app.
            window.real_url = None
            if self.renderer == 'gtkwebkit2':
                self._install_gtk(window, profile)
            else:
                self._install_cocoa(window, profile)
        except Exception:
            # pywebview catches event-handler errors; carry failure explicitly
            # to main rather than silently leave an unprotected/blank window.
            self.fail(window)

    def _install_edge(self, window):
        # before_show runs on the native UI thread, before the first page loads.
        control = window.native.browser.webview
        def navigating(sender, args):
            if not self.allows_navigation(str(args.Uri)):
                args.Cancel = True
        def ready(sender, args):
            if not args.IsSuccess:
                self.fail(window)
                return
            try:
                core = control.CoreWebView2
                def new_window(sender, args):
                    args.Handled = True
                def resource(sender, args):
                    if not self.allows_resource(str(args.Request.Uri)):
                        args.Response = core.Environment.CreateWebResourceResponse(None, 403, 'Blocked', '')
                # Remove the library's external-browser handler before adding ours.
                core.NewWindowRequested -= window.native.browser.on_new_window_request
                core.NewWindowRequested += new_window
                core.WebResourceRequested += resource
                core.Settings.IsPasswordAutosaveEnabled = False
                core.Settings.IsGeneralAutofillEnabled = False
                core.Settings.AreDevToolsEnabled = False
                core.Settings.IsBuiltInErrorPageEnabled = False
            except Exception:
                self.fail(window)
        control.NavigationStarting += navigating
        control.CoreWebView2InitializationCompleted += ready

    def prepare_unix(self):
        """Install native navigation handlers before pywebview creates its view."""
        if self.renderer == 'gtkwebkit2':
            from webview.platforms import gtk
            policy = self

            def navigation(browser, view, decision, decision_type):
                kinds = gtk.webkit.PolicyDecisionType
                allow = False
                try:
                    if decision_type == kinds.NAVIGATION_ACTION:
                        action = decision.get_navigation_action()
                        uri = action.get_request().get_uri()
                        allow = action.get_frame_name() != '_blank' and policy._allows_webkit_navigation(uri)
                    elif decision_type == kinds.RESPONSE:
                        uri = decision.get_response().get_uri()
                        allow = decision.is_mime_type_supported() and (uri == 'about:blank' or policy.allows_resource(uri))
                except Exception:
                    allow = False
                (decision.use if allow else decision.ignore)()
                return True

            # Replace the backend callback, which would otherwise open some
            # target=_blank navigations in the same or an external browser.
            gtk.BrowserView.on_navigation = navigation
        elif self.renderer == 'wkwebview':
            from webview.platforms import cocoa
            import objc
            policy = self
            host = cocoa.BrowserView.WebKitHost

            def private_init(view, frame, configuration):
                configuration.setWebsiteDataStore_(cocoa.WebKit.WKWebsiteDataStore.nonPersistentDataStore())
                return objc.super(host, view).initWithFrame_configuration_(frame, configuration)

            # Configure the ephemeral store before WebKit copies the native
            # configuration. Preserve the host class and its other methods.
            initializer = host.initWithFrame_configuration_
            objc.classAddMethods(host, [objc.selector(private_init, selector=initializer.selector,
                                                      signature=initializer.signature)])

            class RelayCocoaDelegate(cocoa.BrowserView.BrowserDelegate):
                def webView_decidePolicyForNavigationAction_decisionHandler_(self, view, action, handler):
                    try:
                        uri = str(action.request().URL().absoluteString())
                        allowed = action.targetFrame() is not None and policy._allows_webkit_navigation(uri)
                    except Exception:
                        allowed = False
                    handler(cocoa.WebKit.WKNavigationActionPolicyAllow if allowed
                            else cocoa.WebKit.WKNavigationActionPolicyCancel)

                def webView_createWebViewWithConfiguration_forNavigationAction_windowFeatures_(self, view, config, action, features):
                    return None

            cocoa.BrowserView.BrowserDelegate = RelayCocoaDelegate

    def _allows_webkit_navigation(self, uri):
        return uri == 'about:blank' or self.allows_navigation(uri)

    def _filter_timeout(self, window):
        if not self.filter_ready and not self.failed:
            self.fail(window)

    def _load_guarded(self, window, browser):
        window.real_url = self.url
        browser.load_url(self.url)
        self.filter_ready = True

    def _install_gtk(self, window, profile):
        from webview.platforms import gtk
        browser = gtk.BrowserView.instances[window.uid]
        store = gtk.webkit.UserContentFilterStore.new(profile)

        def compiled(store, result, *_):
            if self.failed:
                return
            try:
                browser.manager.add_filter(store.save_finish(result))
                self._load_guarded(window, browser)
            except Exception:
                self.fail(window)

        contents = gtk.glib.Bytes.new(self.content_rules().encode('utf-8'))
        store.save('relay-local-session', contents, None, compiled, None)
        gtk.glib.timeout_add(10000, self._filter_timeout, window)

    def _install_cocoa(self, window, profile):
        from webview.platforms import cocoa
        browser = cocoa.BrowserView.instances[window.uid]
        configuration = browser.webview.configuration()
        if configuration.websiteDataStore().isPersistent():
            raise ValueError('webview_private_store_unavailable')
        location = cocoa.Foundation.NSURL.fileURLWithPath_(profile)
        store = cocoa.WebKit.WKContentRuleListStore.storeWithURL_(location)

        def compiled(rules, error):
            def apply():
                if self.failed:
                    return
                try:
                    if error is not None or rules is None:
                        raise ValueError('webview_filter_unavailable')
                    configuration.userContentController().addContentRuleList_(rules)
                    self._load_guarded(window, browser)
                except Exception:
                    self.fail(window)
            cocoa.AppHelper.callAfter(apply)

        store.compileContentRuleListForIdentifier_encodedContentRuleList_completionHandler_(
            'relay-local-session', self.content_rules(), compiled)
        cocoa.AppHelper.callLater(10, self._filter_timeout, window)


def flash_window(window):
    if sys.platform == 'darwin':
        from webview.platforms import cocoa
        cocoa.AppHelper.callAfter(cocoa.BrowserView.app.requestUserAttention_, cocoa.AppKit.NSInformationalRequest)
        return
    if sys.platform.startswith('linux'):
        from webview.platforms import gtk
        gtk.glib.idle_add(window.native.set_urgency_hint, True)
        return
    import ctypes
    from ctypes import wintypes
    class FLASHWINFO(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.UINT), ('hwnd', wintypes.HWND), ('dwFlags', wintypes.DWORD),
                    ('uCount', wintypes.UINT), ('dwTimeout', wintypes.DWORD)]
    info = FLASHWINFO(ctypes.sizeof(FLASHWINFO), int(window.native.Handle.ToInt64()), 2 | 12, 3, 0)
    ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))


def main(*, show_error=show_error):
    session = None
    try:
        platform = 'linux' if sys.platform.startswith('linux') else sys.platform
        gui, renderer = BACKENDS[platform]
        webview = load_webview()
        directory = data_directory(desktop=True)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        logger = logging.getLogger('pywebview')
        logger.handlers = [logging.NullHandler()]
        logger.propagate = False
        logger.disabled = True
        webview.settings['ALLOW_FILE_URLS'] = False
        webview.settings['ALLOW_DOWNLOADS'] = False
        webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = False
        webview.settings['REMOTE_DEBUGGING_PORT'] = None
        webview.settings['IGNORE_SSL_ERRORS'] = False
        session = DesktopSession(directory)
        window = webview.create_window(TITLE, session.server.local_url, width=1280, height=900,
                                       min_size=(900, 650), background_color='#f3f7f8',
                                       text_select=True, zoomable=True)
        def choose(kind, source):
            if kind == 'folder':
                return window.create_file_dialog(webview.FileDialog.FOLDER)
            types = catalog_dialog_types(source)
            return window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=False, file_types=types)
        session.actions = DesktopActions(session.service, choose, open_export_folder, lambda: flash_window(window))
        policy = LocalWindowPolicy(session.server.local_url, renderer)
        policy.prepare_unix()
        window.events.initialized += policy.initialized
        window.events.closing += session.service.stop
        session.start()
        # No JS-Python filesystem bridge, external browser or runtime download.
        with tempfile.TemporaryDirectory(prefix='webview-', dir=checked_path(directory)) as profile:
            window.events.before_show += lambda: policy.install(window, profile)
            asset_root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
            icon = asset_root/'assets'/'codex-lens.png'
            # Cocoa's configured nonpersistent store takes precedence. Avoid
            # pywebview clearing the default store during startup.
            webview.start(gui=gui, debug=False, private_mode=platform != 'darwin', storage_path=profile,
                          icon=str(icon) if icon.is_file() and platform != 'win32' else None)
        if policy.failed or platform != 'win32' and not policy.filter_ready:
            raise ValueError('webview_startup_failed')
        return 0
    except Exception:
        show_error(START_ERRORS.get(sys.platform, START_ERRORS['linux']))
        return 1
    finally:
        if session:
            session.close()
