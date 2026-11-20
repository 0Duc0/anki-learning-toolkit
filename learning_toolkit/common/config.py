"""One settings file for the whole toolkit.

``config.json`` holds one section per module (``"sound": {...}``, ``"search": {...}`` …) plus
``"modules"`` (which parts are switched on). Modules read and write only their own section,
so a module can never overwrite another module's settings.
"""

from __future__ import annotations

import sys
import traceback

PACKAGE = __name__.split(".", 1)[0]

try:
    from .._build import ONLY   # a single add-on built from the toolkit: its settings are not sectioned
except ImportError:
    ONLY = ""


def _mw():
    from aqt import mw

    return mw


def _log(what: str) -> None:
    print(f"[learning_toolkit] {what}\n{traceback.format_exc()}", file=sys.stderr)


def all_config() -> dict:
    try:
        raw = _mw().addonManager.getConfig(PACKAGE)
    except Exception:
        _log("could not read the settings")
        raw = None
    return dict(raw) if isinstance(raw, dict) else {}


def section(name: str) -> dict:
    """The module's saved settings (a copy). Missing or broken sections give {}."""
    if ONLY:   # single add-on: the whole settings file is this module's (same as the old stand-alone add-on)
        return {k: v for k, v in all_config().items() if k != "modules"}
    value = all_config().get(name)
    return dict(value) if isinstance(value, dict) else {}


def saved_config() -> dict:
    """Only what the user saved (meta.json), without the defaults from config.json."""
    try:
        value = _mw().addonManager.addonMeta(PACKAGE).get("config")
    except Exception:
        value = None
    return dict(value) if isinstance(value, dict) else {}


def saved_section(name: str) -> dict:
    if ONLY:
        return saved_config()
    value = saved_config().get(name)
    return dict(value) if isinstance(value, dict) else {}


def write_key(name: str, value) -> None:
    """Store one top-level key. Only saved keys are written back, never the defaults, so a
    newer toolkit version can still change a default the user never touched."""
    raw = saved_config()
    raw[name] = value
    _mw().addonManager.writeConfig(PACKAGE, raw)


def write_section(name: str, data: dict) -> None:
    if ONLY:
        _mw().addonManager.writeConfig(PACKAGE, dict(data))
        return
    write_key(name, dict(data))


def module_enabled(key: str) -> bool:
    if ONLY:
        return key == ONLY
    modules = all_config().get("modules")
    return not (isinstance(modules, dict) and modules.get(key) is False)


def set_module_enabled(key: str, enabled: bool) -> None:
    modules = dict(all_config().get("modules") or {})
    modules[key] = bool(enabled)
    write_key("modules", modules)


class SectionConfig:
    """Stands in for ``mw.addonManager`` inside a module: ``getConfig``/``writeConfig`` act on one section.

    The modules were separate add-ons before; this keeps their (tested) settings code unchanged.
    """

    def __init__(self, name: str) -> None:
        self.name = name

    def getConfig(self, _module: str = "") -> dict:
        return section(self.name)

    def writeConfig(self, _module: str, data: dict) -> None:
        write_section(self.name, data)

    def saved(self) -> dict:
        return saved_section(self.name)
