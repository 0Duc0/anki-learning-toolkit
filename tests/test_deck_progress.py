"""Deck Progress core: card states and the finish estimate, on a real collection with review history."""
import importlib.util
import os
import sys
import time
from datetime import date

import pytest
from anki.collection import Collection

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name):
    path = os.path.join(ROOT, "learning_toolkit", "deck_progress", f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"dp_{name}", path, submodule_search_locations=[])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# display imports ".core" – load both as a small package
pkg_path = os.path.join(ROOT, "learning_toolkit", "deck_progress")
spec = importlib.util.spec_from_file_location("dp_pkg", os.path.join(pkg_path, "core.py"))
import types
dp_pkg = types.ModuleType("dp_pkg"); dp_pkg.__path__ = [pkg_path]; sys.modules["dp_pkg"] = dp_pkg
core = importlib.import_module("dp_pkg.core")
display = importlib.import_module("dp_pkg.display")


@pytest.fixture
def col(tmp_path):
    c = Collection(str(tmp_path / "c.anki2"))
    model = c.models.by_name("Basic (and reversed card)")
    did = c.decks.id("Lang::JP::a. Frieren")
    for i in range(40):
        n = c.new_note(model)
        n["Front"], n["Back"] = f"w{i}", f"m{i}"
        c.add_note(n, did)
    yield c, did
    c.close()


def _study(col, nids, days_ago):
    """Write a first review for each note's first card, `days_ago` days back."""
    start = int(col.sched.day_cutoff) - 86400 - days_ago * 86400 + 3600
    for k, nid in enumerate(nids):
        cid = col.db.scalar("select id from cards where nid = ? order by ord limit 1", nid)
        col.db.execute("update cards set type=2, queue=2, ivl=3, reps=1 where id=?", cid)
        col.db.execute("insert into revlog values (?,?,?,?,?,?,?,?,?)", (start + k) * 1000, cid, -1, 3, 3, 0, 2500, 3000, 0)


def counter(did, **kw):
    return core.Counter(id="c1", name="JP", decks=(core.DeckRef(did, "Lang::JP::a. Frieren"),), unit="notes", **kw)


def test_states_like_anki(col):
    c, did = col
    nids = c.find_notes("")
    _study(c, nids[:6], 1)
    cid = c.db.scalar("select id from cards where nid=? order by ord limit 1", nids[6])
    c.db.execute("update cards set type=1, queue=1 where id=?", cid)
    c.db.execute("update cards set type=3, queue=1 where id in (select id from cards where nid=? and ord=1)", nids[7])
    c.db.execute("update cards set queue=-1 where id in (select id from cards where nid=? and ord=1)", nids[8])
    snap = core.collect_snapshot(c, core.Options(counters=(counter(did, show_states=True),)))
    st = snap.results[0].states
    assert (st.learning, st.relearning, st.review, st.suspended) == (1, 1, 6, 1)
    assert st.new == 80 - 1 - 1 - 6 - 1
    html = display.panel_html(core.Options(counters=(counter(did, show_states=True),), state_labels={"new": "Neu"}), snap)
    assert "Neu" in html and "Learning" in html and 'dp-suspended' in html


def test_pace_ignores_long_breaks():
    # 300 days nothing, then 6 recent study days of ~20 notes
    days = {-400: 15, -399: 15, -5: 20, -4: 22, -3: 18, -2: 20, -1: 21, 0: 19}
    per_day, share, basis = core.study_pace(days)
    assert 18 <= per_day <= 22 and "last 4 weeks" in basis
    # inactive for a year: use the last study days, assume daily study again
    old = {-400: 10, -399: 12, -398: 11, -390: 9}
    per_day, share, basis = core.study_pace(old)
    assert 9 <= per_day <= 12 and share == 1.0 and "last 4 study days" in basis
    assert core.study_pace({-3: 5, -1: 5}) is None        # too little history


def test_estimate_pace_and_fixed(col):
    c, did = col
    nids = c.find_notes("")
    for day, chunk in enumerate((nids[0:3], nids[3:6], nids[6:9], nids[9:12], nids[12:15])):
        _study(c, chunk, day + 1)
    snap = core.collect_snapshot(c, core.Options(counters=(counter(did, estimate="pace"),)))
    est = snap.results[0].estimate
    assert est.remaining == 25 and est.unit == "notes" and abs(est.per_day - 3) < 1e-9
    assert est.study_days == 9 and est.calendar_days == math_ceil(9 / max(5 / 28, 1 / 7))
    snap = core.collect_snapshot(c, core.Options(counters=(counter(did, estimate="fixed", per_day=10),)))
    est = snap.results[0].estimate
    assert (est.remaining, est.calendar_days) == (25, 3)
    html = display._estimate_html(est, "", today=date(2026, 11, 20))
    assert "25 notes left" in html and "10/day" in html and "23 Nov" in html


def test_no_history_gives_a_hint(col):
    c, did = col
    snap = core.collect_snapshot(c, core.Options(counters=(counter(did, estimate="pace"),)))
    assert snap.results[0].estimate is None and "few more days" in snap.results[0].estimate_note


def test_settings_round_trip():
    raw = {"counters": [{"id": "a", "name": "JP", "decks": [{"id": 5, "name": "X"}], "show_states": True,
                         "estimate": "fixed", "per_day": 25}], "state_labels": {"new": "Neu", "bogus": "x"}}
    opts = core.parse_options(raw)
    assert opts.counters[0].show_states and opts.counters[0].estimate == "fixed" and opts.counters[0].per_day == 25
    assert opts.state_labels == {"new": "Neu"} and opts.label("new") == "Neu" and opts.label("review") == "Review"
    assert core.parse_options(core.options_dict(opts)) == opts
    old = core.parse_options({"counters": [{"id": "a", "name": "JP", "decks": []}]})   # 1.3.0 settings
    assert old.counters[0].estimate == "off" and not old.counters[0].show_states


def math_ceil(x):
    import math
    return math.ceil(x)
