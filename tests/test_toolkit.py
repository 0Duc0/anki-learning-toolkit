"""Loading the whole toolkit into a stand-in Anki main window (offscreen, real AddonManager)."""
import importlib
import json
import os

import pytest

from stub_anki import make_mw, menu_tree

MODULES = ["stage_shifter", "note_mover", "change_deck", "words_left",
           "deck_progress", "search", "sound", "study_clock"]


def _load(legacy=None):
    mw, addons = make_mw(legacy=legacy)
    pkg = importlib.import_module("learning_toolkit")
    return mw, addons, pkg


def test_all_modules_load_and_share_one_menu():
    mw, _addons, pkg = _load()
    assert {k: pkg.STATUS[k] for k in MODULES} == {k: "on" for k in MODULES}, pkg.DETAIL
    tree = menu_tree(mw.form.menuTools)
    assert tree.count("Learning Toolkit") == 1
    assert any("Sound Volume" in line for line in tree)


def test_sections_are_isolated_and_only_saved_keys_are_written():
    mw, addons, _pkg = _load()
    from learning_toolkit.common.config import SectionConfig, all_config, saved_config

    sound = SectionConfig("sound")
    sound.writeConfig("ignored", {"volume": 70})
    SectionConfig("search").writeConfig("ignored", {"shortcut": "Ctrl+K"})
    saved = {k: v for k, v in saved_config().items() if k != "migrated_legacy_settings"}
    assert saved == {"sound": {"volume": 70}, "search": {"shortcut": "Ctrl+K"}}
    assert sound.getConfig()["volume"] == 70
    # defaults of other sections are still read from config.json, not frozen into meta.json
    assert "deck_progress" in all_config() and "deck_progress" not in saved_config()


def test_switched_off_module_is_not_loaded():
    mw, addons = make_mw()
    mw.addonManager.writeConfig("learning_toolkit", {"modules": {"sound": False}})
    pkg = importlib.import_module("learning_toolkit")
    assert pkg.STATUS["sound"] == "off"
    assert not any("Sound Volume" in line for line in menu_tree(mw.form.menuTools))


def test_old_settings_are_migrated_once_and_old_addon_blocks_its_module():
    legacy = {"sound_volume": (True, {"volume": 135, "step": 5})}
    mw, addons, pkg = _load(legacy)
    from learning_toolkit.common.config import saved_section

    assert saved_section("sound")["volume"] == 135
    assert pkg.STATUS["sound"] != "on"          # the old add-on is still enabled → module waits
    meta = json.load(open(os.path.join(addons, "learning_toolkit", "meta.json")))
    assert meta["config"].get("migrated_legacy_settings")


def test_package_installs_and_switches_old_addons_off(tmp_path):
    import shutil
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
    import package

    built = package.main()
    mw, addons = make_mw(legacy={"sound_volume": (True, {}), "words_left": (True, {})})
    shutil.rmtree(os.path.join(addons, "learning_toolkit"))   # start as a fresh install
    result = mw.addonManager.install(str(built))
    assert getattr(result, "name", None) == "Learning Toolkit", result
    assert os.path.isfile(os.path.join(addons, "learning_toolkit", "__init__.py"))
    assert set(result.conflicts) >= {"sound_volume", "words_left"}
    assert not mw.addonManager.isEnabled("sound_volume")
    assert os.path.isdir(os.path.join(addons, "sound_volume"))   # switched off, not deleted
