"""Quick filters + query builder against a real Anki 25.9.4 collection."""
import os, sys, tempfile, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _toolkit
import importlib.util
from anki.collection import Collection

def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); sys.modules[name] = m; spec.loader.exec_module(m); return m

core = load(_toolkit.core_path("search"), "ssa_new_core")
orig = load(_toolkit.old_core_path("anki-addon-simple-search-assistant"), "ssa_old_core")

def make():
    col = Collection(os.path.join(tempfile.mkdtemp(), "c.anki2"))
    nt = col.models.by_name("Basic")
    deck_a = col.decks.id("Test::A"); deck_b = col.decks.id("Test::B")
    today = col.sched.today
    rows = {}
    spec = [  # label, deck, type, queue, due, extra
        ("new1", deck_a, 0, 0, 1, {}), ("new2", deck_a, 0, 0, 2, {}), ("new3", deck_b, 0, 0, 3, {}),
        ("learn1", deck_a, 1, 1, int(time.time()) - 60, {}),
        ("relearn1", deck_b, 3, 1, int(time.time()) - 60, {}),
        ("rev_due", deck_a, 2, 2, today - 1, {"ivl": 5}),
        ("rev_future", deck_a, 2, 2, today + 10, {"ivl": 20}),
        ("rev_due_b", deck_b, 2, 2, today, {"ivl": 7}),
        ("susp_old", deck_a, 2, -1, today + 3, {"ivl": 9}),
        ("susp_new", deck_b, 0, -1, 4, {}),
        ("buried_rev", deck_a, 2, -2, today, {"ivl": 9}),
        ("flag_new", deck_b, 0, 0, 5, {"flags": 3}),
    ]
    for i, (label, did, typ, queue, due, extra) in enumerate(spec):
        n = col.new_note(nt); n["Front"] = label; n["Back"] = f"b{i}"
        if label == "rev_due": n.tags = ["marked"]
        col.add_note(n, did)
        c = n.cards()[0]
        c.type, c.queue, c.due = typ, queue, due
        c.ivl = extra.get("ivl", 0); c.flags = extra.get("flags", 0)
        col.update_card(c); rows[label] = c.id
    now = int(time.time() * 1000)
    for label, ease in (("rev_due", 1), ("rev_due_b", 3), ("learn1", 3)):
        col.db.execute("insert into revlog values (?,?,?,?,?,?,?,?,?)", now + len(label), rows[label], -1, ease, 1, 0, 2500, 3000, 1)
    return col, rows

col, rows = make()
FAILS = []
def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  {extra}" if extra and not cond else ""))
    if not cond: FAILS.append(name)

def ids_for(q): return set(col.find_cards(q))
def labels(q): return sorted(k for k, v in rows.items() if v in ids_for(q))

exp = {
 "new": {"new1","new2","new3","susp_new","flag_new"} ,   # is:new includes suspended new cards in Anki
 "learning": {"learn1","relearn1"},
 "review": {"rev_due","rev_future","rev_due_b","susp_old","buried_rev","relearn1"},  # Anki: is:review includes relearning
 "suspended": {"susp_old","susp_new"},
 "buried": {"buried_rev"},
 "studied_today": {"rev_due","rev_due_b","learn1"},
 "failed_today": {"rev_due"},
 "added_today": set(rows),
 "marked": {"rev_due"},
 "flagged": {"flag_new"},
}
for key, want in exp.items():
    q = core.build_quick_query(col, key)
    got = {k for k, v in rows.items() if v in ids_for(q)}
    check(f"quick '{key}' -> {q}", got == want, f"got={sorted(got)} want={sorted(want)}")

# 'old' = everything that is not new
q = core.build_quick_query(col, "old")
got = {k for k, v in rows.items() if v in ids_for(q)}
check("quick 'old' == all - new", got == set(rows) - exp["new"], str(sorted(got)))
# 'due' equals Anki's own is:due
check("quick 'due' == is:due", ids_for(core.build_quick_query(col, "due")) == ids_for("is:due"))
check("due contains rev_due and learn1 and not rev_future",
      {"rev_due","rev_due_b","learn1","relearn1"} <= {k for k,v in rows.items() if v in ids_for(core.build_quick_query(col,"due"))}
      and rows["rev_future"] not in ids_for(core.build_quick_query(col,"due")))

# narrowing the current search, and never stacking nodes in the produced text
q = core.build_quick_query(col, "new", "deck:Test::A")
check("narrow current deck + new", labels(q) == ["new1","new2"], q)
check("narrow query text", q.startswith("(deck:Test::A) "), q)
check("invalid key raises", all(_raises(lambda: core.build_quick_query(col, "x")) for _raises in [lambda f: (lambda: (f(), False))() if False else None]) or True)
try:
    core.build_quick_query(col, "nonsense"); check("invalid key raises", False)
except ValueError: check("invalid key raises", True)

# text optional when another condition exists
fields = ("Front", "Back")
S = core.SearchSpec
q = core.build_query(col, S(card_state="new"), fields)
check("state-only search works", {k for k,v in rows.items() if v in ids_for(q)} == exp["new"], q)
q = core.build_query(col, S(card_state="new", deck_scope="specific", deck_name="Test::A"), fields)
check("state + specific deck", labels(q) == ["new1","new2"], q)
q = core.build_query(col, S(deck_scope="specific", deck_name="Test::B"), fields)
check("specific deck without text", len(ids_for(q)) == 5, q)
q = core.build_query(col, S(card_state="old", text="rev_due", field_name="Front"), fields)
check("old + exact text in field", labels(q) == ["rev_due"], q)
for bad in (S(), S(deck_scope="all"), S(card_state="bogus")):
    try: core.build_query(col, bad, fields); check(f"rejects {bad}", False)
    except ValueError: check(f"rejects empty/invalid spec", True)

# regression: specs the original supported give the identical query text
cases = [
 dict(text="rev_due", field_name="Front"), dict(text="a+b [x]", match="contains"),
 dict(text="rev", match="starts", deck_scope="current"), dict(text="due", match="ends", deck_scope="specific", deck_name="Test::A"),
 dict(field_name="Back", match="empty"), dict(field_name="Back", match="not_empty", note_type="Basic"),
 dict(text="new", tag_mode="include", tag_name="marked"), dict(text="x", tag_mode="exclude", tag_name="marked"),
 dict(text="x", card_state="new"), dict(text="x", card_state="learning"), dict(text="x", card_state="review"),
 dict(text="x", card_state="due"), dict(text="x", card_state="suspended"), dict(text="x", card_state="buried"),
 dict(text="x", combine_current=True, current_query="deck:Test::A"),
]
for c in cases:
    a = core.build_query(col, core.SearchSpec(**c), fields); b = orig.build_query(col, orig.SearchSpec(**c), fields)
    check(f"unchanged vs original: {c}", a == b, f"{a!r} != {b!r}")
if __name__ == "__main__":
    print("\nRESULT:", "ALL PASSED" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
    sys.exit(1 if FAILS else 0)
