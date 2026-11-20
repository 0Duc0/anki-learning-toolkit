import os, sys, types
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _toolkit
import anki.lang; anki.lang.set_lang("en")
from aqt.qt import *
app = QApplication([])
_px = int(os.environ.get("PX", "0"))
if _px:
    f = app.font(); f.setPixelSize(_px); app.setFont(f)
import aqt
from aqt import sound, gui_hooks
SAVED = {}
class FakeMw(QMainWindow):
    def __init__(self):
        super().__init__()
        self.form = types.SimpleNamespace(menuTools=QMenu("Tools", self))
        self.addonManager = types.SimpleNamespace(getConfig=lambda n: dict(SAVED) if SAVED else None, writeConfig=lambda n, c: SAVED.update(c))
        self.state = "review"
        self.replays = 0
        self.reviewer = types.SimpleNamespace(replayAudio=lambda: setattr(self, "replays", self.replays + 1))
aqt.mw = FakeMw(); aqt.mw.show()
TIPS = []
import aqt.utils
class FakeMpv(sound.MpvManager):
    def __init__(self, refuse=()):
        self.props = {}; self.log = []; self.refuse = set(refuse); self._proc = types.SimpleNamespace(pid=111)
    def set_property(self, name, value):
        if name in self.refuse: raise RuntimeError("refused")
        self.props[name] = value; self.log.append(name)
class OtherPlayer:  # e.g. TTS
    def set_property(self, *a): raise AssertionError("must not be touched")
mpv = FakeMpv(); other = OtherPlayer()
sound.av_player.players = [other, mpv]
sv = _toolkit.module("sound", flat=True)
sv.tooltip = lambda text, period=0: TIPS.append(text)
FAILS = []
def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  -> {extra}"))
    if not cond: FAILS.append(name)

def _all_actions(menu):
    for a in menu.actions():
        yield a
        if a.menu() is not None:
            yield from _all_actions(a.menu())
check("1 Tools › Learning Toolkit menu entry", any(a.text() == "Sound Volume…" for a in _all_actions(aqt.mw.form.menuTools)))
check("2 three app-wide shortcuts", [s.key().toString() for s in sv._shortcuts] == ["Ctrl+Alt+Up", "Ctrl+Alt+Down", "Ctrl+Alt+M"]
      and all(s.context() == Qt.ShortcutContext.ApplicationShortcut for s in sv._shortcuts))
gui_hooks.av_player_will_play(None)
check("3 before a sound: defaults pushed to mpv only", mpv.props == {"volume-max": 200.0, "volume": 100.0, "mute": False, "speed": 1.0, "af": ""}, mpv.props)
sv._shortcuts[1].activated.emit(); sv._shortcuts[1].activated.emit()
check("4 quieter twice -> 80 %, applied live, tooltip", mpv.props["volume"] == 80.0 and SAVED["volume"] == 80 and TIPS[-1] == "🔊 Volume 80%", (mpv.props, TIPS))
for _ in range(20): sv._shortcuts[0].activated.emit()
check("5 louder stops at 200 %", mpv.props["volume"] == 200.0 and SAVED["volume"] == 200)
sv._shortcuts[2].activated.emit()
check("6 mute toggles on", mpv.props["mute"] is True and TIPS[-1] == "🔇 Sound muted")
sv._shortcuts[1].activated.emit()
check("7 changing volume un-mutes", mpv.props["mute"] is False and mpv.props["volume"] == 190.0)
n_af = mpv.log.count("af")
gui_hooks.av_player_will_play(None); gui_hooks.av_player_will_play(None)
check("8 filter not re-sent before every sound", mpv.log.count("af") == n_af)
mpv._proc = types.SimpleNamespace(pid=222)
gui_hooks.av_player_will_play(None)
check("9 mpv restarted -> filter sent again", mpv.log.count("af") == n_af + 1)
# dialog
sv.open_dialog(); d = sv._dialog
check("10 dialog shows saved values", d.spin.value() == 190 and d.slider.value() == 190 and not d.mute.isChecked())
d.slider.setValue(55)
check("11 slider applies live + saves", mpv.props["volume"] == 55.0 and SAVED["volume"] == 55 and d.spin.value() == 55)
d.speed.setValue(0.75)
check("12 speed applies", mpv.props["speed"] == 0.75 and SAVED["speed"] == 0.75)
d.normalize.setChecked(True)
check("13 loudness filter on", mpv.props["af"] == sv.LOUDNORM and SAVED["normalize"] is True)
d.mute.setChecked(True)
check("14 mute disables the slider", mpv.props["mute"] is True and not d.slider.isEnabled())
d.replay.click()
check("15 replay card audio while reviewing", aqt.mw.replays == 1 and d.replay.isEnabled())
d.show(); app.processEvents()
lbls = [l for l in d.findChildren(QLabel) if l.wordWrap() and l.isVisibleTo(d)]
check("16 no clipped text", all(l.height() >= l.heightForWidth(l.width()) - 1 for l in lbls))
d.grab().save(_toolkit.SHOTS + f"ui_volume{'_px%d' % _px if _px else ''}.png")
[b for b in d.findChildren(QPushButton) if b.text() == "Reset"][0].click()
check("17 reset", mpv.props == {"volume-max": 200.0, "volume": 100.0, "mute": False, "speed": 1.0, "af": ""} and d.spin.value() == 100, mpv.props)
sv._shortcuts[1].activated.emit()
check("18 shortcut while dialog open updates the dialog", d.spin.value() == 90)
d.close(); app.processEvents()
check("19 closing clears the dialog", sv._dialog is None)
sv.open_dialog(); check("20 reopens", sv._dialog is not None); sv._dialog.close()
# robustness
SAVED.clear(); SAVED.update({"volume": "loud", "speed": 9, "muted": "yes", "step": -4})
c = sv.config()
check("21 bad config -> safe values", c["volume"] == 100 and c["speed"] == 2.0 and c["muted"] is False and c["step"] == 1, c)
SAVED.clear(); SAVED.update({"volume": 180})
old_mpv = FakeMpv(refuse={"volume-max"}); sound.av_player.players = [old_mpv]
sv.apply_to_players()
check("22 old mpv without volume-max: capped at 130, rest still applied", old_mpv.props.get("volume") == 130.0 and "speed" in old_mpv.props, old_mpv.props)
sound.av_player.players = []
check("23 no player yet: nothing breaks", sv.apply_to_players() == 0)
print("\nRESULT:", "ALL PASSED" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
sys.exit(1 if FAILS else 0)
