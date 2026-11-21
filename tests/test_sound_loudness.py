"""Even out: real recordings of different loudness must come out equally loud (uses the real mpv)."""
import os
import shutil
import subprocess

import pytest

from stub_anki import make_mw

pytestmark = pytest.mark.skipif(not (shutil.which("mpv") and shutil.which("ffmpeg")), reason="needs mpv and ffmpeg")


def _make(path, source, volume_db):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", source, "-af", f"volume={volume_db}dB", path],
                   check=True)


def _played_loudness(sv, path, gain):
    chain = f"volume={gain}dB,{sv.LIMITER},aloop=loop=3:size=2000000,ebur128"
    out = subprocess.run(["mpv", "--no-config", "--load-scripts=no", "--vo=null", "--ao=null", "--ao-null-untimed",
                          "--untimed", "--no-video", "--msg-level=all=no,ffmpeg=v", f"--af=lavfi=[{chain}]", path],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True).stdout.decode()
    return sv.parse_loudness(out)


def test_recordings_of_different_loudness_come_out_equal(tmp_path):
    make_mw()
    import importlib
    sv = importlib.import_module("learning_toolkit.sound")
    files = {
        "quiet_word.mp3": ("sine=f=330:d=0.7", -16),
        "loud_word.mp3": ("sine=f=440:d=0.9", 12),
        "very_short.mp3": ("sine=f=520:d=0.25", -6),   # shorter than one 0.4 s R128 block
        "sentence.mp3": ("anoisesrc=d=3:c=pink:a=0.5", -14),
    }
    levels = {}
    for name, (source, vol) in files.items():
        path = str(tmp_path / name)
        _make(path, source, vol)
        levels[name] = sv.measure(path, "mpv")
        assert levels[name] is not None, name
    spread_before = max(levels.values()) - min(levels.values())
    after = {n: _played_loudness(sv, str(tmp_path / n), sv.gain_for(lufs)) for n, lufs in levels.items()}
    assert spread_before > 20
    assert all(abs(v - sv.TARGET_LUFS) <= 1.0 for v in after.values()), after


def test_parse_and_gain_limits():
    make_mw()
    import importlib
    sv = importlib.import_module("learning_toolkit.sound")
    out = "[ffmpeg] Summary:\n[ffmpeg]   Integrated loudness:\n[ffmpeg]     I:         -26.4 LUFS\n"
    assert sv.parse_loudness(out) == -26.4
    assert sv.parse_loudness(out.replace("-26.4", "-70.0")) is None
    assert sv.parse_loudness("garbage") is None
    if shutil.which("mpv"):
        assert sv.limiter_supported("mpv") is True
    assert sv.gain_for(-26.4) == 8.4
    assert sv.gain_for(-60) == sv.MAX_BOOST_DB and sv.gain_for(20) == sv.MAX_CUT_DB and sv.gain_for(None) == 0.0
