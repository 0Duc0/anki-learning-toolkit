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
    # notes: each note once, in its most active state; nids[8] still has an active new card
    assert (st.new_notes, st.learning_notes, st.relearning_notes, st.review_notes, st.suspended_notes) == (32, 1, 1, 6, 0)
    html = display.panel_html(core.Options(counters=(counter(did, show_states=True),), state_labels={"new": "Neu"}), snap)
    assert "<b>71</b> Neu" in html and "Learning" in html and "dp-suspended" in html and "dp-st-unit" not in html
    notes = counter(did, show_note_states=True)
    html = display.panel_html(core.Options(counters=(notes,)), core.collect_snapshot(c, core.Options(counters=(notes,))))
    assert "<b>32</b> New" in html and ">Notes<" in html and "dp-suspended" not in html and "<b>71</b>" not in html
    both = counter(did, show_states=True, show_note_states=True)
    html = display.panel_html(core.Options(counters=(both,)), core.collect_snapshot(c, core.Options(counters=(both,))))
    assert "<b>71</b> New" in html and "<b>32</b> New" in html and ">Cards<" in html and ">Notes<" in html


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
    assert "left" not in html.split("title=")[0] and "At 10/day" in html and "23 Nov" in html
    html = display._estimate_html(est, "", today=date(2026, 11, 20), left=25)
    assert "25 notes left · at 10/day" in html


def test_left_follows_the_counter_states_and_goal(col):
    c, did = col
    nids = c.find_notes("")
    for day, chunk in enumerate((nids[0:3], nids[3:6], nids[6:9], nids[9:12], nids[12:15])):
        _study(c, chunk, day + 1)
    # answered counter: 15 of 40 counted -> 25 left; mature-only counter (none mature here): 40 left
    answered = counter(did, estimate="pace", show_left=True)
    res = core.collect_snapshot(c, core.Options(counters=(answered,))).results[0]
    assert res.left == 25 and res.estimate.remaining == 25
    mature = core.replace(answered, counter_states=("relearning", "mature"))
    res = core.collect_snapshot(c, core.Options(counters=(mature,))).results[0]
    assert res.left == 40 and res.estimate.remaining == 40
    # notes in a goal (queue) deck are part of what is left
    queue = c.decks.id("Lang::JP::Queue")
    model = c.models.by_name("Basic (and reversed card)")
    for i in range(10):
        n = c.new_note(model)
        n["Front"], n["Back"] = f"q{i}", f"q{i}"
        c.add_note(n, queue)
    goal = core.replace(answered, goal_decks=(core.DeckRef(queue, "Lang::JP::Queue"),))
    res = core.collect_snapshot(c, core.Options(counters=(goal,))).results[0]
    assert res.left == 35
    # "left" only on request; it can be shown without an estimate
    only_left = core.replace(goal, estimate="off")
    html = display.panel_html(core.Options(counters=(only_left,)), core.collect_snapshot(c, core.Options(counters=(only_left,))))
    assert "35 notes left" in html
    hidden = core.replace(goal, show_left=False)
    html = display.panel_html(core.Options(counters=(hidden,)), core.collect_snapshot(c, core.Options(counters=(hidden,))))
    assert "notes left" not in html.replace("Left:", "") and "At your pace" in html


def test_no_history_gives_a_hint(col):
    c, did = col
    snap = core.collect_snapshot(c, core.Options(counters=(counter(did, estimate="pace"),)))
    assert snap.results[0].estimate is None and "few more days" in snap.results[0].estimate_note


def test_settings_round_trip():
    raw = {"counters": [{"id": "a", "name": "JP", "decks": [{"id": 5, "name": "X"}], "show_states": True,
                         "show_note_states": True, "show_left": True, "estimate": "fixed", "per_day": 25}], "state_labels": {"new": "Neu", "bogus": "x"}}
    opts = core.parse_options(raw)
    c0 = opts.counters[0]
    assert c0.show_states and c0.show_note_states and c0.show_left and c0.estimate == "fixed" and c0.per_day == 25
    assert opts.state_labels == {"new": "Neu"} and opts.label("new") == "Neu" and opts.label("review") == "Review"
    assert core.parse_options(core.options_dict(opts)) == opts
    old = core.parse_options({"counters": [{"id": "a", "name": "JP", "decks": []}]})   # 1.3.0 settings
    assert old.counters[0].estimate == "off" and not old.counters[0].show_states
    assert not old.counters[0].show_note_states and not old.counters[0].show_left


def math_ceil(x):
    import math
    return math.ceil(x)
