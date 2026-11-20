"""Tests for the Even mode of new_card_stage_shifter (real Anki 25.9.4 collection)."""
import importlib.util
import _toolkit  # noqa: F401  (path set-up)
import os
import sys
import tempfile
import traceback

from anki.collection import AddNoteRequest, Collection

CORE_PATH = os.environ.get(
    "CORE_PATH", _toolkit.core_path("stage_shifter")
)
ORIG_CORE_PATH = _toolkit.old_core_path("anki-addon-new-card-stage-shifter")


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


core = load("ncss_core", CORE_PATH)

PARENT = "Test::詞彙"
LETTERS = "abcdefghijklmno"
NAMES = "孫悟空 托塔李天王 哪吒 二郎神 豬八戒 唐三藏 沙悟淨 白龍馬 太白金星 牛魔王 鐵扇公主 紅孩兒 觀音菩薩 玉皇大帝 如來佛祖".split()
# the user's real queue: a. is empty, h. has 9, j. has 23 ...
USER_SIZES = [0, 19, 20, 19, 20, 20, 20, 9, 20, 23, 19, 15, 0, 2, 0]


def make_collection(sizes, note_type="Basic (and reversed card)"):
    col = Collection(os.path.join(tempfile.mkdtemp(), "c.anki2"))
    model = col.models.by_name(note_type)
    deck_ids = []
    for letter, name in zip(LETTERS, NAMES):
        deck_ids.append(col.decks.id(f"{PARENT}::{letter}. {name}"))
    rank = 0
    for did, size in zip(deck_ids, sizes):
        reqs = []
        for _ in range(size):
            note = col.new_note(model)
            note["Front"] = f"w{rank:03d}"
            note["Back"] = "x"
            reqs.append(AddNoteRequest(note=note, deck_id=did))
            rank += 1
        if reqs:
            col.add_notes(reqs)
    return col, deck_ids


def opts(**kw):
    base = dict(
        parent_name=PARENT,
        direction="toward_a",
        start_key="o",
        stop_key="a",
        card_types=(0,),
        even=True,
        even_notes=20,
    )
    base.update(kw)
    return core.ShiftOptions(**base)


def stage_contents(col, deck_ids):
    """list (per stage a..o) of note labels in queue order."""
    out = []
    for did in deck_ids:
        rows = col.db.all(
            "select n.flds, c.due, c.id from cards c join notes n on n.id=c.nid "
            "where c.did=? order by c.due, c.id",
            did,
        )
        seen, labels = set(), []
        for flds, _due, _cid in rows:
            label = flds.split("\x1f")[0]
            if label not in seen:
                seen.add(label)
                labels.append(label)
        out.append(labels)
    return out


def card_state(col):
    return {
        cid: (nid, typ, queue, due, ivl, reps)
        for cid, nid, typ, queue, due, ivl, reps in col.db.all(
            "select id, nid, type, queue, due, ivl, reps from cards"
        )
    }


def card_decks(col):
    return dict(col.db.all("select id, did from cards"))


def note_decks_consistent(col):
    rows = col.db.all("select nid, count(distinct did) from cards group by nid")
    return all(n == 1 for _nid, n in rows)


RESULTS = []


def check(fn):
    RESULTS.append(fn)
    return fn


@check
def even_blocks_of_20_on_users_queue():
    col, ids = make_collection(USER_SIZES)
    before = stage_contents(col, ids)
    queue_order = [w for stage in before for w in stage]
    plan = core.build_plan(col, opts())
    core.shift_plan(col, plan)
    after = stage_contents(col, ids)
    sizes = [len(s) for s in after]
    assert sizes == [20] * 10 + [6] + [0] * 4, sizes
    assert [w for stage in after for w in stage] == queue_order, "queue order changed"
    assert note_decks_consistent(col), "a note's cards were split across decks"


@check
def plan_stage_counts_match_reality():
    col, ids = make_collection(USER_SIZES)
    plan = core.build_plan(col, opts())
    assert [b for _l, b, _a in plan.stage_counts] == USER_SIZES
    expected_after = [20] * 10 + [6] + [0] * 4
    assert [a for _l, _b, a in plan.stage_counts] == expected_after
    core.shift_plan(col, plan)
    assert [len(s) for s in stage_contents(col, ids)] == expected_after


@check
def scheduling_untouched_and_nothing_lost():
    col, ids = make_collection(USER_SIZES)
    # give some cards review state so we can see they are untouched
    col.db.execute("update cards set type=2, queue=2, due=?, ivl=7, reps=3 where id in (select id from cards where did=? limit 2)", col.sched.today, ids[1])
    before = card_state(col)
    core.shift_plan(col, core.build_plan(col, opts()))
    assert card_state(col) == before, "scheduling data or card set changed"
    # the two review cards are not "new", so they must not have moved
    assert all(card_decks(col)[cid] == ids[1] for cid, st in before.items() if st[1] == 2)


@check
def idempotent_second_run_moves_nothing():
    col, ids = make_collection(USER_SIZES)
    core.shift_plan(col, core.build_plan(col, opts()))
    again = core.build_plan(col, opts())
    assert again.total == 0 and not again.moves, again.total


@check
def one_undo_restores_everything():
    col, ids = make_collection(USER_SIZES)
    original = card_decks(col)
    core.shift_plan(col, core.build_plan(col, opts()))
    assert card_decks(col) != original
    col.undo()
    assert card_decks(col) == original, "undo did not restore the original decks"


@check
def start_stage_limits_the_range():
    col, ids = make_collection(USER_SIZES)
    plan = core.build_plan(col, opts(start_key="e"))
    core.shift_plan(col, plan)
    sizes = [len(s) for s in stage_contents(col, ids)]
    # a..e hold 0+19+20+19+20 = 78 notes -> 20,20,20,18,0 ; f..o untouched
    assert sizes[:5] == [20, 20, 20, 18, 0], sizes
    assert sizes[5:] == USER_SIZES[5:], sizes


@check
def overflow_goes_to_last_stage_with_warning():
    col, ids = make_collection([25, 25, 25] + [0] * 12)
    plan = core.build_plan(col, opts(start_key="c"))
    assert any("room" in w for w in plan.warnings), plan.warnings
    core.shift_plan(col, plan)
    assert [len(s) for s in stage_contents(col, ids)][:3] == [20, 20, 35]


@check
def split_note_is_left_alone_and_reported():
    col, ids = make_collection(USER_SIZES)
    # move ONE card of the first note of b. into d. -> that note is split across stages
    nid, cid = col.db.first("select nid, id from cards where did=? order by due, id", ids[1])
    col.db.execute("update cards set did=? where id=?", ids[3], cid)
    plan = core.build_plan(col, opts())
    assert plan.skipped_notes == 1 and any("more than one stage" in w for w in plan.warnings)
    core.shift_plan(col, plan)
    decks = col.db.all("select did from cards where nid=?", nid)
    assert sorted(d for (d,) in decks) == sorted([ids[1], ids[3]]), "split note was moved"


@check
def suspended_cards_ignored_by_default():
    col, ids = make_collection(USER_SIZES)
    # suspend both cards of the first note in c.
    nid = col.db.scalar("select nid from cards where did=? order by due, id", ids[2])
    col.db.execute("update cards set queue=-1 where nid=?", nid)
    plan = core.build_plan(col, opts())
    core.shift_plan(col, plan)
    assert set(col.db.list("select did from cards where nid=?", nid)) == {ids[2]}
    assert col.db.scalar("select count(*) from cards where nid=? and queue=-1", nid) == 2


@check
def rejects_unsupported_even_combinations():
    col, ids = make_collection(USER_SIZES)
    for bad in (
        dict(card_types=()),
        dict(direction="toward_end", start_key="a", stop_key="o"),
        dict(even_notes=0),
    ):
        try:
            core.build_plan(col, opts(**bad))
        except RuntimeError:
            continue
        raise AssertionError(f"accepted {bad}")


@check
def even_with_review_and_learning_cards():
    """1.x: Even also distributes learning/relearning/review cards; studied notes come first, scheduling kept."""
    col, ids = make_collection([0, 6, 6, 6, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
    # make the notes of c. studied: review (due later) and learning
    c_nids = col.db.list("select distinct nid from cards where did=?", ids[2])
    for k, nid in enumerate(c_nids):
        typ, queue = (2, 2) if k % 2 == 0 else (1, 1)
        col.db.execute("update cards set type=?, queue=?, ivl=?, due=?, reps=3 where nid=?", typ, queue, 5 if typ == 2 else 0, 9000 + k, nid)
    before = card_state(col)
    plan = core.build_plan(col, opts(card_types=(0, 1, 2, 3), start_key="d", stop_key="a", even_notes=6))
    core.shift_plan(col, plan)
    contents = stage_contents(col, ids[:4])
    assert [len(x) for x in contents] == [6, 6, 6, 0], [len(x) for x in contents]
    labels_a = set(contents[0])
    studied = {col.get_note(n)["Front"] for n in c_nids}
    assert labels_a == set(contents[0]) and len(contents[0]) == 6
    # scheduling unchanged for every card
    after = card_state(col)
    assert all(before[c][1:] == after[c][1:] for c in before), "scheduling changed"
    # with only New chosen, the studied notes stay where they are
    col2, ids2 = make_collection([0, 6, 6, 6, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
    c2 = col2.db.list("select distinct nid from cards where did=?", ids2[2])
    col2.db.execute(f"update cards set type=2, queue=2, ivl=5 where nid in ({','.join(map(str, c2))})")
    core.shift_plan(col2, core.build_plan(col2, opts(card_types=(0,), start_key="d", stop_key="a", even_notes=6)))
    assert set(col2.db.list("select distinct nid from cards where did=?", ids2[2])) == set(c2)


@check
def stale_preview_is_refused_and_nothing_moves():
    col, ids = make_collection(USER_SIZES)
    plan = core.build_plan(col, opts())
    original = card_decks(col)
    cid = col.db.scalar("select id from cards where did=? limit 1", ids[4])
    col.db.execute("update cards set did=? where id=?", ids[9], cid)  # changed after preview
    changed = card_decks(col)
    try:
        core.shift_plan(col, plan)
    except RuntimeError:
        pass
    else:
        raise AssertionError("stale plan was applied")
    assert card_decks(col) == changed, "something moved despite the refusal"


@check
def failure_midway_rolls_everything_back():
    col, ids = make_collection(USER_SIZES)
    original = card_decks(col)
    plan = core.build_plan(col, opts())
    real = col.set_deck
    calls = []

    def flaky(card_ids, deck_id):
        calls.append(1)
        if len(calls) == 3:
            raise RuntimeError("boom")
        return real(card_ids, deck_id)

    col.set_deck = flaky
    try:
        core.shift_plan(col, plan)
    except RuntimeError as e:
        assert "undone" in str(e) or "rollback" in str(e).lower(), str(e)
    else:
        raise AssertionError("expected a failure")
    finally:
        col.set_deck = real
    assert card_decks(col) == original, "rollback left cards in new decks"


@check
def non_even_behaviour_is_identical_to_the_original():
    orig = load("ncss_core_orig", ORIG_CORE_PATH)
    col, ids = make_collection(USER_SIZES)
    for kw in (
        dict(max_per_source=100, limit_unit="cards"),
        dict(max_per_source=5, limit_unit="notes"),
        dict(max_per_source=7, limit_unit="cards", start_key="h"),
        dict(max_per_source=0, limit_unit="notes", start_key="c", stop_key="b"),
    ):
        base = dict(parent_name=PARENT, direction="toward_a", start_key="o", stop_key="a", card_types=(0,))
        base.update(kw)
        new_plan = core.build_plan(col, core.ShiftOptions(**base))
        old_plan = orig.build_plan(col, orig.ShiftOptions(**base))
        sig = lambda p: [(m.source.key, m.destination.key, m.card_ids, m.note_ids) for m in p.moves]
        assert sig(new_plan) == sig(old_plan), f"plans differ for {kw}"


def main():
    failed = 0
    for fn in RESULTS:
        try:
            fn()
            print("PASS", fn.__name__)
        except Exception:
            failed += 1
            print("FAIL", fn.__name__)
            traceback.print_exc(limit=3)
    print(f"\n{len(RESULTS) - failed}/{len(RESULTS)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
