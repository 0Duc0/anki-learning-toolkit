"""The test scripts of the eight former stand-alone add-ons, run against the toolkit modules.

Each script runs in its own process (they build their own stand-in Anki window). Where an old
add-on release is available (``LT_OLD_ADDONS``), some scripts also compare the toolkit's core
logic with that release.
"""
import os
import subprocess
import sys

import pytest

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "legacy")
SCRIPTS = ["run_even_core.py", "test_ui_flow.py", "test_change_deck.py", "test_search_core.py",
           "test_word_core.py", "test_search_ui.py", "test_word_ui.py", "test_sound.py"]
NEEDS_OLD = {"run_even_core.py", "test_search_core.py", "test_word_core.py", "test_ui_flow.py"}


@pytest.mark.parametrize("script", SCRIPTS)
def test_script(script):
    old = os.environ.get("LT_OLD_ADDONS", "/home/claude/work/installed")
    if script in NEEDS_OLD and not os.path.isdir(old):
        pytest.skip("old add-on releases not available (set LT_OLD_ADDONS)")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    run = subprocess.run([sys.executable, script], cwd=HERE, env=env, capture_output=True, text=True, timeout=900)
    out = run.stdout + run.stderr
    assert run.returncode == 0 and ("ALL PASSED" in out or "13/13 passed" in out), out[-3000:]


@pytest.mark.parametrize("test_file", ["test_note_mover.py", "test_search_bar.py"])
def test_pytest_file(test_file):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    run = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", test_file],
                         cwd=HERE, env=env, capture_output=True, text=True, timeout=600)
    assert run.returncode == 0, (run.stdout + run.stderr)[-3000:]
