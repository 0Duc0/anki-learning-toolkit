"""Sound Volume: one volume (and speed) for all card audio, with live shortcuts.

Anki plays card sounds through mpv.  Before every sound, and whenever you change
a setting, this add-on sets mpv's volume, mute and playback speed.

"Even out" measures each recording once (EBU R128 integrated loudness, with the
same mpv Anki uses) and plays it with a fixed gain so it reaches the same
loudness as every other recording; a limiter stops boosted sounds from clipping.
Measurements are cached in user_files.  Nothing in your collection is changed.
"""

from __future__ import annotations

import json
import math
import os
import queue
import re
import subprocess
import sys
import threading
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
    Qt,
    QVBoxLayout,
    QWidget,
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
TARGET_LUFS = -18.0     # every recording is played at this loudness
MAX_BOOST_DB = 20.0
MAX_CUT_DB = -30.0
GAIN_LABEL = "@sv_even"
LIMITER = "alimiter=limit=0.891:level=0"   # -1 dBFS, no auto-level
MEASURE_FILTER = "lavfi=[aloop=loop=3:size=2000000,ebur128]"  # short clips are looped to reach R128's 0.4 s blocks
MEASURE_TIMEOUT = 4.0


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
        if ok:
            updated += 1
    return updated


# ---------------------------------------------------------------------------
# even out: measure each file once, then play it with a fixed gain
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_cache: dict | None = None      # file name -> [mtime, size, lufs or None]
_unsaved = 0
_jobs: "queue.Queue[tuple[str, str, str, dict | None]]" = queue.Queue()
_worker: threading.Thread | None = None


def _cache_path() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "user_files", "sound_loudness.json")


def _load_cache() -> dict:
    global _cache
    if _cache is None:
        try:
            with open(_cache_path(), encoding="utf-8") as f:
                data = json.load(f)
            _cache = data if isinstance(data, dict) else {}
        except Exception:
            _cache = {}
    return _cache


def save_cache() -> None:
    global _unsaved
    with _lock:
        if not _unsaved or _cache is None:
            return
        data = dict(_cache)
        _unsaved = 0
    try:
        path = _cache_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
    except Exception:
        _log("could not save loudness measurements")


def parse_loudness(output: str) -> float | None:
    """Integrated loudness (LUFS) from ffmpeg's ebur128 summary; None for silence or no summary."""
    tail = output.split("Integrated loudness", 1)
    if len(tail) < 2:
        return None
    m = re.search(r"I:\s*(-?\d+(?:\.\d+)?)\s*LUFS", tail[1])
    if not m:
        return None
    value = float(m.group(1))
    return None if value <= -69.9 else value


def _run_mpv(executable: str, env: dict | None, af: str, target: str) -> str:
    argv = [executable, "--no-config", "--load-scripts=no", "--vo=null", "--ao=null", "--ao-null-untimed",
            "--untimed", "--no-video", "--msg-level=all=no,ffmpeg=v", f"--af={af}", "--", target]
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    result = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                            env=env, timeout=MEASURE_TIMEOUT, **kwargs)
    return result.stdout.decode("utf-8", "replace")


def measure(path: str, executable: str, env: dict | None = None) -> float | None:
    """Loudness of one file in LUFS, measured with mpv's built-in ffmpeg filters."""
    return parse_loudness(_run_mpv(executable, env, MEASURE_FILTER, path))


_limiter_ok: bool | None = None


def limiter_supported(executable: str, env: dict | None = None) -> bool:
    """Once per session: can this mpv run the limiter? (A filter mpv can't build would silence the sound.)"""
    global _limiter_ok
    if _limiter_ok is None:
        try:
            out = _run_mpv(executable, env, f"lavfi=[volume=0dB,{LIMITER},ebur128]", "av://lavfi:sine=f=440:d=0.6")
            _limiter_ok = parse_loudness(out) is not None
        except Exception:
            _limiter_ok = False
    return _limiter_ok


def gain_for(lufs: float | None) -> float:
    if lufs is None:
        return 0.0
    return round(max(MAX_CUT_DB, min(MAX_BOOST_DB, TARGET_LUFS - lufs)), 1)


def _stat(path: str) -> tuple[int, int] | None:
    try:
        st = os.stat(path)
        return int(st.st_mtime), int(st.st_size)
    except OSError:
        return None


def cached_loudness(name: str, path: str) -> tuple[bool, float | None]:
    """(known, lufs) - known is False when the file was never measured or has changed since."""
    stat = _stat(path)
    with _lock:
        entry = _load_cache().get(name)
    if stat and isinstance(entry, list) and len(entry) == 3 and tuple(entry[:2]) == stat:
        return True, entry[2]
    return False, None


def loudness(name: str, path: str, executable: str, env: dict | None = None) -> float | None:
    global _unsaved
    known, lufs = cached_loudness(name, path)
    if known:
        return lufs
    stat = _stat(path)
    if stat is None:
        return None
    try:
        lufs = measure(path, executable, env)
    except Exception:
        _log(f"could not measure {name}")
        return None
    with _lock:
        _load_cache()[name] = [stat[0], stat[1], lufs]
        _unsaved += 1
        flush = _unsaved >= 25
    if flush:
        save_cache()
    return lufs


def _file_tags(tags) -> list[str]:
    names = []
    for tag in tags or ():
        name = getattr(tag, "filename", None)
        if isinstance(name, str) and name:
            names.append(name)
    return names


def _player_for_measuring():
    players = _mpv_players()
    if not players:
        return None
    player = players[0]
    executable = getattr(player, "executable", None)
    return (player, executable, getattr(player, "popenEnv", None)) if executable else None


def _work() -> None:
    while True:
        name, path, executable, env = _jobs.get()
        try:
            loudness(name, path, executable, env)
        except Exception:
            _log("measuring failed")
        if _jobs.empty():
            save_cache()


def prefetch(names: list[str]) -> None:
    """Measure these files in the background (e.g. the answer audio while you read the question)."""
    global _worker
    if not config()["normalize"] or not names:
        return
    found = _player_for_measuring()
    if not found:
        return
    player, executable, env = found
    folder = getattr(player, "media_folder", None)
    if not folder:
        return
    if _worker is None or not _worker.is_alive():
        _worker = threading.Thread(target=_work, name="sound-volume-measure", daemon=True)
        _worker.start()
    for name in names:
        path = os.path.join(folder, name)
        if not cached_loudness(name, path)[0]:
            _jobs.put((name, path, executable, env))


def _set_gain(player, gain: float | None) -> None:
    """Put (or remove) the per-file gain + limiter in front of mpv's own volume."""
    if getattr(player, "_sv_gain", None) == gain:
        return
    try:
        player.command("af", "remove", GAIN_LABEL)
    except Exception:
        pass
    player._sv_gain = None
    if gain is None:
        return
    executable = getattr(player, "executable", None)
    limiter = bool(executable) and limiter_supported(executable, getattr(player, "popenEnv", None))
    for chain in ((f"volume={gain}dB,{LIMITER}",) if limiter else ()) + (f"volume={gain}dB",):
        try:
            player.command("af", "add", f"{GAIN_LABEL}:lavfi=[{chain}]")
            player._sv_gain = gain
            return
        except Exception:
            continue
    _log("mpv refused the gain filter")


def even_out(tag) -> None:
    """Before a sound plays: give it the gain that brings it to TARGET_LUFS."""
    cfg = config()
    names = _file_tags([tag])
    for player in _mpv_players():
        if not cfg["normalize"] or not names:
            _set_gain(player, None)
            continue
        folder = getattr(player, "media_folder", None) or ""
        executable = getattr(player, "executable", None)
        path = os.path.join(folder, names[0])
        known, lufs = cached_loudness(names[0], path)
        if not known and executable:
            lufs = loudness(names[0], path, executable, getattr(player, "popenEnv", None))
        _set_gain(player, gain_for(lufs) if lufs is not None else None)


def measured_count() -> int:
    with _lock:
        return sum(1 for v in _load_cache().values() if isinstance(v, list) and len(v) == 3 and v[2] is not None)


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

_dialog: VolumeDialog | None = None


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
            "Each recording is measured once (EBU R128) and played at the same loudness. "
            "The first time a new recording plays, it may start a moment later."
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
        even = f"  ·  {measured_count():,} recordings measured" if cfg["normalize"] else ""
        self.status.setText(
            _describe(cfg)
            + even
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

    def closeEvent(self, event) -> None:
        global _dialog
        _dialog = None
        save_cache()
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
    gui_hooks.av_player_will_play.append(_will_play)
    gui_hooks.profile_did_open.append(apply_to_players)
    gui_hooks.reviewer_did_show_question.append(_prefetch_card)
    gui_hooks.profile_will_close.append(save_cache)


def _will_play(tag) -> None:
    apply_to_players()
    try:
        even_out(tag)
    except Exception:
        _log("even out failed")


def _prefetch_card(card) -> None:
    try:
        prefetch(_file_tags(card.question_av_tags()) + _file_tags(card.answer_av_tags()))
    except Exception:
        _log("prefetch failed")


if mw is not None:
    try:
        _setup()
    except Exception:
        _log("setup failed")
