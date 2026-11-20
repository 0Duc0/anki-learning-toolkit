import sys, importlib.util
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _toolkit
import fixture_user as fx
def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m; spec.loader.exec_module(m); return m
core = load(_toolkit.core_path("search"), "ssa_core3")
old = load(_toolkit.old_core_path("anki-addon-simple-search-assistant"), "ssa_core201")
col, ids = fx.make()
meta = core.collect_metadata(col)
FAILS = []
def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  -> {extra}"))
    if not cond: FAILS.append(name)
rev = {v: k for k, v in ids.items()}
def found(q): return sorted(rev[n] for n in col.find_notes(q) if n in rev)
W = core.WordSearch
def wq(text, mode, deck="", cf=""):
    return core.build_word_query(col, W(text, mode, deck, cf), meta.fields)
cases = [
    ("你", "exact", "", ["ni"]),
    ("你", "contains", "", ["nihao", "ni", "nimen"]),
    ("你好", "related", "", ["hao", "haoren", "he_hao", "ni", "nihao", "nihonjin", "nimen"]),
    ("好", "contains", "Language::中文", ["hao", "haoren", "nihao"]),
    ("陽光", "exact", "", ["yangguang"]),          # traditional input
    ("たべる", "exact", "", ["taberu"]),           # kana reading
    ("食べる", "exact", "", ["taberu"]),
    ("cứ", "exact", "", ["cu"]),
    ("cứ", "contains", "", ["cu", "cuviec"]),     # not cứu
    ("Cứ", "contains", "", ["cu", "cuviec"]),     # case-insensitive
    ("việc làm", "related", "", ["cuviec", "lamviec", "vieclam"]),
    ("eat", "meaning", "", ["an", "chi", "taberu"]),  # not great / theater / examples
    ("good", "meaning", "Heisig", ["he_hao"]),
    ("好", "contains", "", ["hao", "haoren", "he_hao", "nihao", "nihonjin"]),
]
for text, mode, deck, want in cases:
    q = wq(text, mode, deck)
    got = found(q)
    check(f"{mode:9} {text!r:10} {deck or 'all'} -> {want}", got == sorted(want), f"got {got}  q={q}")
# everywhere finds the example-sentence hits too (old behaviour, labelled as broad)
got = found(wq("你好", "everywhere"))
check("everywhere also finds examples (chi has 你好 in its example)", {"chi", "nihao", "ni"} <= set(got), got)
check("contains does NOT find example-only hits", "chi" not in found(wq("你好", "contains")))
# card filter + deck, no text
q = wq("", "contains", fx.CN_A, "new")
check("no text + deck + New", found(q) == ["ni", "nihao"], found(q))
try:
    wq("", "exact"); check("empty search rejected", False)
except ValueError: check("empty search rejected", True)
# HTML-quoted characters, regex specials, quotes are safe
for weird in ['a+b', '"quoted"', 'x:y', '(paren', 'back\\slash', '*star*', '_under']:
    for mode in ("exact", "contains", "related", "meaning", "everywhere"):
        try: col.find_notes(wq(weird, mode))
        except Exception as e: check(f"safe {mode} {weird!r}", False, e); break
    else: check(f"safe all modes {weird!r}", True)
# metadata scoping
check("types_in_scope Chinese = only CC-CEDICT", meta.types_in_scope("Language::中文") == ("CC-CEDICT Optimized EN v5.3",), meta.types_in_scope("Language::中文"))
check("types_in_scope Language = 3 types", len(meta.types_in_scope("Language")) == 3, meta.types_in_scope("Language"))
check("types_in_scope all = 4 + stock", len(meta.types_in_scope("")) >= 4)
# dialog spec with @word / @meaning / related
S = core.SearchSpec
q = core.build_query(col, S(text="你", field_name=core.FIELD_WORD, match="contains_word"), meta.fields)
check("dialog @word contains", found(q) == ["ni", "nihao", "nimen"], found(q))
q = core.build_query(col, S(text="eat", field_name=core.FIELD_MEANING, match="contains_word"), meta.fields)
check("dialog @meaning", found(q) == ["an", "chi", "taberu"], found(q))
q = core.build_query(col, S(text="你好", field_name="Simplified", match="related"), meta.fields)
check("dialog single field related", found(q) == ["hao", "haoren", "ni", "nihao", "nimen"], found(q))
# regression: every 2.0.1 spec shape builds the identical query
fields = meta.fields
regs = [dict(text="你", field_name="Simplified"), dict(text="a+b [x]", match="contains"), dict(text="rev", match="starts", deck_scope="current"),
        dict(text="due", match="ends", deck_scope="specific", deck_name="Heisig"), dict(field_name="Notizen", match="empty"),
        dict(field_name="Notizen", match="not_empty", note_type="Vietnamese Optimized EN v7"), dict(text="x", tag_mode="include", tag_name="marked"),
        dict(text="x", card_state="new"), dict(card_state="old"), dict(text="x", combine_current=True, current_query="deck:Heisig")]
for r in regs:
    a = core.build_query(col, core.SearchSpec(**r), fields); b = old.build_query(col, old.SearchSpec(**r), fields)
    check(f"unchanged vs 2.0.1 {r}", a == b, f"{a} != {b}")
if __name__ == "__main__":
    print("\nRESULT:", "ALL PASSED" if not FAILS else f"{len(FAILS)} FAILED")
    sys.exit(1 if FAILS else 0)
