"""Anki integration through public read operations and display hooks only."""

from __future__ import annotations

import sys
import traceback

from aqt import gui_hooks
from aqt.operations import QueryOp
from aqt.qt import QAction, QDialog, QTimer, qconnect
from aqt.utils import showInfo

from .core import CollectionUnavailable, Options, collect_snapshot, options_dict, parse_options
from .display import update_script
from .settings import SettingsDialog
from ..common.config import SectionConfig
from ..common.menu import toolkit_menu

_CFG = SectionConfig('deck_progress')


class Controller:
    def __init__(self, mw):
        self.mw = mw
        self.options = Options()
        self.snapshot = None
        self.profile = ""
        self.active = False
        self.temporary_close = False
        self.epoch = 0
        self.ticket = 0
        self.inflight = None
        self.dirty = True
        self.error = False
        self.last_error = ""
        self.dialog = None
        self.pending_settings = None
        self.hooks = []
        self.timer = QTimer(mw)
        self.timer.setSingleShot(True)
        qconnect(self.timer.timeout, self._safe(self._refresh))

    def _safe(self, callback):
        def wrapped(*args):
            try:
                return callback(*args)
            except Exception as error:
                self._failure(error)
                return None
        return wrapped

    def install(self):
        required = (
            "profile_did_open", "profile_will_close", "deck_browser_did_render",
            "operation_did_execute", "collection_will_temporarily_close",
            "collection_did_temporarily_close", "webview_did_receive_js_message",
        )
        missing = [name for name in required if not hasattr(gui_hooks, name)]
        if missing:
            raise RuntimeError("This Anki version does not provide: " + ", ".join(missing))
        for name, callback in (
            ("profile_did_open", self._open), ("profile_will_close", self._close),
            ("collection_will_temporarily_close", self._suspend),
            ("collection_did_temporarily_close", self._resume),
            ("deck_browser_did_render", self._rendered),
            ("operation_did_execute", self._changed),
            ("reviewer_did_answer_card", self._changed),
            ("sync_did_finish", self._changed),
            ("state_did_reset", self._changed),
        ):
            hook = getattr(gui_hooks, name, None)
            if hook is not None:
                wrapped = self._safe(callback)
                hook.append(wrapped)
                self.hooks.append((hook, wrapped))
        # This is a filter: preserve another add-on's handled result on errors.
        gui_hooks.webview_did_receive_js_message.append(self._bridge)
        self.hooks.append((gui_hooks.webview_did_receive_js_message, self._bridge))
        menu = self._toolkit_menu()
        self.action = QAction("Deck Progress…", self.mw)
        qconnect(self.action.triggered, self._safe(lambda _checked=False: self.open_settings()))
        menu.addAction(self.action)
        if getattr(self.mw, "col", None) is not None:
            self._open()

    def _toolkit_menu(self):
        return toolkit_menu()

    def _load_options(self):
        raw = _CFG.getConfig()
        profiles = raw.get("profiles", {}) if isinstance(raw, dict) else {}
        return parse_options(profiles.get(self.profile) if isinstance(profiles, dict) else None)

    def _open(self, *_args):
        self.epoch += 1
        self.profile = str(self.mw.pm.name)
        self.active = True
        self.temporary_close = False
        self.inflight = None
        self.snapshot = None
        self.error = False
        self.last_error = ""
        self.options = self._load_options()
        self.dirty = True
        self._schedule()

    def _close(self, *_args):
        self.epoch += 1
        self.active = False
        self.timer.stop()
        self.inflight = None
        self.snapshot = None
        self.pending_settings = None
        if self.dialog is not None:
            self.dialog.reject()
        self._push(remove=True)

    def _suspend(self, *_args):
        self._close()
        self.temporary_close = True

    def _resume(self, *_args):
        self._open()

    def _usable(self):
        col = getattr(self.mw, "col", None)
        return self.active and not self.temporary_close and col is not None and getattr(col, "db", None) is not None

    def _at_home(self):
        return getattr(self.mw, "state", None) == "deckBrowser"

    def _changed(self, *_args):
        self.dirty = True
        self._schedule()

    def _rendered(self, *_args):
        if not self._usable():
            return
        self._push()
        # Returning home always invalidates the cache, even for older add-ons
        # which use legacy reset hooks instead of CollectionOp.
        self.dirty = True
        self._schedule()

    def _schedule(self):
        if (self._usable() and self.inflight is None and not self.timer.isActive()
                and (self._at_home() and self.options.enabled or self.pending_settings is not None)):
            self.timer.start(160)

    def _refresh(self):
        if not self._usable() or self.inflight is not None:
            return
        if not self.options.enabled and self.pending_settings is None:
            return
        if not self._at_home() and self.pending_settings is None:
            return
        self.ticket += 1
        token = (self.epoch, self.ticket)
        self.inflight = token
        self.dirty = False
        expected = self.mw.col
        options = self.options
        self._push(updating=True)

        def query(col):
            # A queued query must not silently switch to another profile.
            if col is not expected:
                raise CollectionUnavailable("The active collection changed.")
            return collect_snapshot(col, options)

        def success(snapshot):
            if token != self.inflight or token[0] != self.epoch or not self._usable():
                return
            self.inflight = None
            self.snapshot = snapshot
            self.error = False
            self.last_error = ""
            self._push(updating=self.dirty)
            if self.pending_settings is not None:
                focus = self.pending_settings
                self.pending_settings = None
                self.open_settings(focus or None)
            if self.dirty:
                self._schedule()

        def failure(error):
            if token != self.inflight or token[0] != self.epoch:
                return
            self.inflight = None
            self._failure(error)
            if self.pending_settings is not None:
                self.pending_settings = None
                showInfo("Deck Progress could not load the deck list. Close other dialogs and try again.", parent=self.mw)

        try:
            QueryOp(parent=self.mw, op=query, success=self._safe(success)).failure(self._safe(failure)).run_in_background()
        except Exception as error:
            failure(error)

    def _push(self, *, updating=False, remove=False):
        if not self._at_home():
            return
        browser = getattr(self.mw, "deckBrowser", None)
        web = getattr(browser, "web", None)
        if web is None:
            return
        options = Options(enabled=False) if remove else self.options
        web.eval(update_script(options, self.snapshot, updating=updating, error=self.error))

    def _failure(self, error):
        self.error = True
        detail = f"{type(error).__name__}: {error}"
        if detail != self.last_error:
            self.last_error = detail
            print("[Deck Progress] Display refresh paused: " + detail, file=sys.stderr)
            traceback.print_exception(type(error), error, error.__traceback__)
        try:
            self._push()
        except Exception:
            pass

    def _bridge(self, handled, message, context):
        if handled[0] or context is not getattr(self.mw, "deckBrowser", None):
            return handled
        if not isinstance(message, str) or not message.startswith("deck_progress:"):
            return handled
        try:
            if message == "deck_progress:settings":
                self.open_settings()
            elif message == "deck_progress:refresh":
                self._changed()
            elif message.startswith("deck_progress:edit:"):
                key = message.split(":", 2)[2]
                if any(c.id == key for c in self.options.counters):
                    self.open_settings(key)
            else:
                return handled
        except Exception as error:
            self._failure(error)
        return True, None

    def open_settings(self, focus=None):
        if not self._usable():
            showInfo("Open an Anki profile before customizing Deck Progress.", parent=self.mw)
            return
        if self.dialog is not None:
            self.dialog.raise_()
            self.dialog.activateWindow()
            return
        if self.snapshot is None or self.dirty:
            self.pending_settings = focus or ""
            self._schedule()
            return
        epoch, profile = self.epoch, self.profile
        dialog = SettingsDialog(self.mw, self.options, self.snapshot.decks, focus)
        self.dialog = dialog
        try:
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
            if accepted and dialog.result_options is not None and self._usable() and epoch == self.epoch:
                raw = _CFG.getConfig() or {}
                raw = dict(raw) if isinstance(raw, dict) else {}
                profiles = raw.get("profiles")
                profiles = dict(profiles) if isinstance(profiles, dict) else {}
                profiles[profile] = options_dict(dialog.result_options)
                raw["profiles"] = profiles
                # This writes only this add-on's settings JSON, not the collection.
                _CFG.writeConfig(__name__, raw)
                self.options = dialog.result_options
                self.epoch += 1
                self.inflight = None
                self.snapshot = None
                self.error = False
                self.dirty = True
                self._push(updating=True)
                self._schedule()
        finally:
            self.dialog = None
            dialog.deleteLater()


_controller = None


def register():
    global _controller
    from aqt import mw

    if mw is not None and _controller is None:
        controller = Controller(mw)
        controller.install()
        _controller = controller
