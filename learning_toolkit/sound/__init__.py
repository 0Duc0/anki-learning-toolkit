"""Sound Volume: one volume (and speed) for all card audio, with live shortcuts.

Anki plays card sounds through mpv.  Before every sound, and whenever you change
a setting, this add-on sets mpv's volume, mute, playback speed and (optionally)
a loudness-normalising filter.  Nothing in your collection is changed.
"""

from __future__ import annotations

import sys
import traceback

from aqt import gui_hooks, mw
from aqt.qt import (
    QAction,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QKeySequence,
    QLabel,
    QPushButton,
    QShortcut,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    Qt,
    qconnect,
)
from aqt.utils import tooltip
from ..common.config import SectionConfig

_CFG = SectionConfig('sound')

DEFAULTS = {
    "volume": 100,
    "muted": False,
    "speed": 1.0,
    "normalize": False,
    "step": 10,
    "volume_up_shortcut": "Ctrl+Alt+Up",
    "volume_down_shortcut": "Ctrl+Alt+Down",
    "mute_shortcut": "Ctrl+Alt+M",
    "show_tooltips": True,
}
MAX_VOLUME = 200
LOUDNORM = "lavfi=[loudnorm=I=-16:TP=-1.5:LRA=11]"


def _log(what: str) -> None:
    print(f"[sound_volume] {what}\n{traceback.format_exc()}", file=sys.stderr)


def _clamp(value, low, high, default):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:  # NaN
        return default
    return min(high, max(low, number))


def config() -> dict:
    cfg = dict(DEFAULTS)
    try:
        raw = _CFG.getConfig()
        if isinstance(raw, dict):
            cfg.update(raw)
    except Exception:
        pass
    cfg["volume"] = int(round(_clamp(cfg.get("volume"), 0, MAX_VOLUME, 100)))
    cfg["speed"] = round(_clamp(cfg.get("speed"), 0.5, 2.0, 1.0), 2)
    cfg["step"] = int(round(_clamp(cfg.get("step"), 1, 50, 10)))
    for key in ("muted", "normalize", "show_tooltips"):
        if not isinstance(cfg.get(key), bool):
            cfg[key] = DEFAULTS[key]
    for key in ("volume_up_shortcut", "volume_down_shortcut", "mute_shortcut"):
        if not isinstance(cfg.get(key), str):
            cfg[key] = DEFAULTS[key]
    return cfg


def save(changes: dict) -> dict:
    cfg = config()
    cfg.update(changes)
    try:
        _CFG.writeConfig(__name__, cfg)
    except Exception:
        _log("could not save the settings")
    cfg = config()
    apply_to_players()
    return cfg


# ---------------------------------------------------------------------------
# mpv
# ---------------------------------------------------------------------------

def _mpv_players() -> list:
    try:
        from aqt import sound

        players = getattr(sound.av_player, "players", []) or []
        return [p for p in players if isinstance(p, sound.MpvManager)]
    except Exception:
        return []


def _process_id(player) -> int | None:
    proc = getattr(player, "_proc", None)
    return getattr(proc, "pid", None)


def apply_to_players(*_args) -> int:
    """Push the settings to every mpv player. Returns how many were updated."""
    cfg = config()
    updated = 0
    for player in _mpv_players():
        ok = True

        def put(name, value) -> bool:
            nonlocal ok
            try:
                player.set_property(name, value)
                return True
            except Exception:
                ok = False
                _log(f"mpv refused {name}={value!r}")
                return False

        volume = float(cfg["volume"])
        if not put("volume-max", float(MAX_VOLUME)):
            volume = min(volume, 130.0)  # mpv's own default maximum
        put("volume", volume)
        put("mute", bool(cfg["muted"]))
        put("speed", float(cfg["speed"]))
        # Changing the audio filter restarts mpv's audio chain, so only touch
        # it when it really changed (or mpv itself was restarted).
        wanted = (LOUDNORM if cfg["normalize"] else "", _process_id(player))
        if getattr(player, "_sound_volume_af", None) != wanted and put("af", wanted[0]):
            player._sound_volume_af = wanted
        if ok:
            updated += 1
    return updated


def _say(text: str) -> None:
    if config()["show_tooltips"]:
        try:
            tooltip(text, period=1200)
        except Exception:
            pass


def _describe(cfg: dict) -> str:
    if cfg["muted"]:
        return "🔇 Sound muted"
    speed = "" if cfg["speed"] == 1.0 else f" · speed {cfg['speed']:.2f}×"
    return f"🔊 Volume {cfg['volume']}%{speed}"


def change_volume(delta: int) -> None:
    cfg = config()
    volume = int(min(MAX_VOLUME, max(0, cfg["volume"] + delta)))
    cfg = save({"volume": volume, "muted": False})
    _say(_describe(cfg))
    _sync_dialog()


def toggle_mute() -> None:
    cfg = save({"muted": not config()["muted"]})
    _say(_describe(cfg))
    _sync_dialog()


# ---------------------------------------------------------------------------
# dialog
# ---------------------------------------------------------------------------

_dialog: "VolumeDialog | None" = None


def _sync_dialog() -> None:
    if _dialog is not None:
        try:
            _dialog.load()
        except RuntimeError:
            pass


class VolumeDialog(QDialog):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sound Volume")
        self.setMinimumWidth(460)
        self._loading = False
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(10)

        title = QLabel("Sound volume for card audio")
        font = title.font()
        font.setBold(True)
        if font.pointSizeF() > 0:
            font.setPointSizeF(font.pointSizeF() + 3)
        elif font.pixelSize() > 0:
            font.setPixelSize(int(font.pixelSize() * 1.25))
        title.setFont(font)
        root.addWidget(title)
        intro = QLabel(
            "Changes apply immediately, also to a sound that is playing, and are "
            "remembered. Text-to-speech voices are not affected."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        root.addLayout(form)

        row = QHBoxLayout()
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, MAX_VOLUME)
        self.slider.setSingleStep(5)
        self.slider.setPageStep(10)
        self.slider.setTickInterval(50)
        self.slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.slider.setAccessibleName("Volume in percent")
        self.spin = QSpinBox()
        self.spin.setRange(0, MAX_VOLUME)
        self.spin.setSuffix(" %")
        self.spin.setAccessibleName("Volume in percent")
        row.addWidget(self.slider, 1)
        row.addWidget(self.spin)
        form.addRow("Volume:", row)
        self.boost = QLabel("Above 100 % boosts quiet recordings and may distort loud ones.")
        self.boost.setWordWrap(True)
        self.boost.setStyleSheet("color: palette(placeholder-text);")
        form.addRow("", self.boost)

        self.mute = QCheckBox("Mute card audio")
        form.addRow("", self.mute)

        speed_row = QHBoxLayout()
        self.speed = QDoubleSpinBox()
        self.speed.setRange(0.5, 2.0)
        self.speed.setSingleStep(0.05)
        self.speed.setDecimals(2)
        self.speed.setSuffix(" ×")
        self.speed.setAccessibleName("Playback speed")
        self.speed.setToolTip("Slower or faster speech; the pitch stays natural")
        speed_reset = QPushButton("Normal")
        speed_reset.setToolTip("Back to 1.00 ×")
        qconnect(speed_reset.clicked, lambda _c=False: self.speed.setValue(1.0))
        speed_row.addWidget(self.speed)
        speed_row.addWidget(speed_reset)
        speed_row.addStretch(1)
        form.addRow("Speed:", speed_row)

        self.normalize = QCheckBox("Even out loud and quiet recordings")
        self.normalize.setToolTip(
            "Applies a loudness filter so recordings from different sources sound "
            "about equally loud. Turn it off if a sound starts late or is cut."
        )
        form.addRow("Loudness:", self.normalize)

        cfg = config()
        keys = QLabel(
            "Shortcuts: "
            + " · ".join(
                f"{QKeySequence(cfg[k]).toString(QKeySequence.SequenceFormat.NativeText)} {label}"
                for k, label in (
                    ("volume_up_shortcut", "louder"),
                    ("volume_down_shortcut", "quieter"),
                    ("mute_shortcut", "mute"),
                )
                if cfg[k]
            )
        )
        keys.setWordWrap(True)
        keys.setStyleSheet("color: palette(placeholder-text);")
        root.addWidget(keys)

        self.status = QLabel()
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.replay = buttons.addButton("Replay card audio", QDialogButtonBox.ButtonRole.ActionRole)
        reset = buttons.addButton("Reset", QDialogButtonBox.ButtonRole.ResetRole)
        qconnect(buttons.rejected, self.close)
        qconnect(self.replay.clicked, self._replay)
        qconnect(reset.clicked, self._reset)
        root.addWidget(buttons)

        qconnect(self.slider.valueChanged, self.spin.setValue)
        qconnect(self.spin.valueChanged, self.slider.setValue)
        qconnect(self.spin.valueChanged, lambda _v: self._store())
        qconnect(self.mute.toggled, lambda _v: self._store())
        qconnect(self.speed.valueChanged, lambda _v: self._store())
        qconnect(self.normalize.toggled, lambda _v: self._store())
        self.load()

    def load(self) -> None:
        cfg = config()
        self._loading = True
        try:
            self.spin.setValue(cfg["volume"])
            self.slider.setValue(cfg["volume"])
            self.mute.setChecked(cfg["muted"])
            self.speed.setValue(cfg["speed"])
            self.normalize.setChecked(cfg["normalize"])
        finally:
            self._loading = False
        self._refresh()

    def _store(self) -> None:
        if self._loading:
            return
        save(
            {
                "volume": int(self.spin.value()),
                "muted": self.mute.isChecked(),
                "speed": round(float(self.speed.value()), 2),
                "normalize": self.normalize.isChecked(),
            }
        )
        self._refresh()

    def _refresh(self) -> None:
        cfg = config()
        self.slider.setEnabled(not cfg["muted"])
        self.spin.setEnabled(not cfg["muted"])
        players = len(_mpv_players())
        self.status.setText(
            _describe(cfg)
            + ("" if players else "  ·  (applies as soon as Anki plays the next sound)")
        )
        reviewer = getattr(mw, "reviewer", None)
        self.replay.setEnabled(getattr(mw, "state", "") == "review" and reviewer is not None)

    def _replay(self) -> None:
        reviewer = getattr(mw, "reviewer", None)
        replay = getattr(reviewer, "replayAudio", None) if reviewer else None
        if callable(replay):
            replay()

    def _reset(self) -> None:
        save({"volume": 100, "muted": False, "speed": 1.0, "normalize": False})
        self.load()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        global _dialog
        _dialog = None
        super().closeEvent(event)


def open_dialog() -> None:
    global _dialog
    if _dialog is not None:
        try:
            _dialog.load()
            _dialog.show()
            _dialog.raise_()
            _dialog.activateWindow()
            return
        except RuntimeError:
            _dialog = None
    _dialog = VolumeDialog(mw)
    _dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    _dialog.show()


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------

_shortcuts: list = []


def _install_shortcuts() -> None:
    cfg = config()
    for key, handler in (
        ("volume_up_shortcut", lambda: change_volume(config()["step"])),
        ("volume_down_shortcut", lambda: change_volume(-config()["step"])),
        ("mute_shortcut", toggle_mute),
    ):
        sequence = cfg[key].strip()
        if not sequence:
            continue
        shortcut = QShortcut(QKeySequence(sequence), mw)
        shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        qconnect(shortcut.activated, handler)
        _shortcuts.append(shortcut)


def _setup() -> None:
    action = QAction("Sound Volume…", mw)
    qconnect(action.triggered, lambda _checked=False: open_dialog())
    from ..common.menu import toolkit_menu

    toolkit_menu().addAction(action)
    mw._sound_volume_action = action
    _install_shortcuts()
    gui_hooks.av_player_will_play.append(lambda _tag: apply_to_players())
    gui_hooks.profile_did_open.append(apply_to_players)


if mw is not None:
    try:
        _setup()
    except Exception:
        _log("setup failed")
