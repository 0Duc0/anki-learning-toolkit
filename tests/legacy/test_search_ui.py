"""UI flow of Search Assistant 2.0: real add-on + real Anki collection, offscreen Qt."""
import os, sys, types
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import anki.lang
anki.lang.set_lang("en")
from aqt.qt import *
app = QApplication([])
_px = int(os.environ.get('PX', '0'))
if _px:
    _f = app.font(); _f.setPixelSize(_px); app.setFont(_f)
import aqt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _toolkit
import test_search_core as t   # builds `col`, `rows`

col, rows = t.col, t.rows
SAVED = {}

class FakeMw(QMainWindow):
    def __init__(self):
        super().__init__()
        self.col = col
        self.app = app
        self.addonManager = types.SimpleNamespace(
            getConfig=lambda name: dict(SAVED) if SAVED else None,
            writeConfig=lambda name, cfg: SAVED.update(cfg))
aqt.mw = FakeMw()
pkg = _toolkit.module("search", flat=True)

WARN = []
pkg.showWarning = lambda text, *a, **k: WARN.append(text)

class FakeQueryOp:
    def __init__(self, parent, op, success):
        self.op, self.s = op, success
    def failure(self, f): self.f = f; return self
    def with_progress(self, label=None): return self
    def run_in_background(self):
        try: r = self.op(col)
        except Exception as e: self.f(e); return
        self.s(r)
pkg.QueryOp = FakeQueryOp

class FakeEditor:
    def call_after_note_saved(self, cb): cb()

class FakeBrowser(QMainWindow):
    def __init__(self):
        super().__init__()
        self.col = col
        self.editor = FakeEditor()
        self.form = types.SimpleNamespace(menuEdit=QMenu("Edit", self), gridLayout=QGridLayout())
        host = QWidget(); host.setLayout(self.form.gridLayout); self.setCentralWidget(host)
        self.form.gridLayout.addWidget(QLineEdit("deck:current"), 0, 0)
        self.form.gridLayout.addWidget(QPushButton("Search"), 0, 1)
        self._search = "deck:current"; self.history = []
        self.sel = []
    def current_search(self): return self._search
    def search_for(self, q): self._search = q; self.history.append(q)
    def update_history(self): pass
    def selected_notes(self): return list(self.sel)

FAILS = []
def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  -> {extra}" if (extra and not cond) else ""))
    if not cond: FAILS.append(name)

SHOTS = _toolkit.SHOTS
b = FakeBrowser(); b.resize(900, 200); b.show()
pkg._setup_browser(b)

# --- A: toolbar + Edit menu ------------------------------------------------------------
quick = getattr(b, "_simple_search_quick_button", None)
check("A1 'Cards ▾' button added next to Search…", quick is not None and quick.text().startswith("Cards"))
grid = b.form.gridLayout
cols = {grid.getItemPosition(i)[1]: grid.itemAt(i).widget() for i in range(grid.count()) if grid.getItemPosition(i)[0] == 0}
bar = getattr(b, "_simple_search_bar_button", None)
check("A2 buttons sit side by side (Search bar, Cards, Search…)", cols.get(2) is bar and cols.get(3) is quick and cols.get(4).text() == "Search…", str({k: v.text() for k, v in cols.items()}))
acts = [a.text() for a in quick.menu().actions() if a.text()]
check("A3 quick menu lists 12 filters + options", acts[:12] == ["New","Old","Learning","Review","Due today","Studied today","Failed today","Added today","Suspended","Buried","Marked","Flagged"] and "Narrow the current search" in acts and "Search Assistant…" in acts, str(acts))
sub = [a for a in b.form.menuEdit.actions() if a.menu() is not None]
check("A4 Edit menu has 'Quick card filters' with 12 entries", len(sub) == 1 and len([x for x in sub[0].menu().actions()]) == 12)

def trigger(menu, text):
    [a for a in menu.actions() if a.text() == text][0].trigger()

trigger(quick.menu(), "New")
check("A5 New narrows current deck", b.history[-1] == "(deck:current) is:new", b.history[-1])
trigger(quick.menu(), "Review")
check("A6 second filter replaces, never stacks", b.history[-1] == "(deck:current) is:review", b.history[-1])
trigger(quick.menu(), "Old")
check("A7 third filter also replaces", b.history[-1] == "(deck:current) -is:new", b.history[-1])
b._search = "hello"            # user types a search by hand
trigger(quick.menu(), "Suspended")
check("A8 after a manual search the new filter narrows that one", b.history[-1] == "(hello) is:suspended", b.history[-1])
trigger(quick.menu(), "Narrow the current search")      # untick
check("A9 narrow option is saved", SAVED.get("quick_combine") is False, str(SAVED))
trigger(quick.menu(), "New")
check("A10 narrow off -> searches all decks", b.history[-1] == "is:new", b.history[-1])
check("A11 results of the shown query are right", {k for k,v in rows.items() if v in set(col.find_cards(b.history[-1]))} == t.exp["new"])
trigger(quick.menu(), "Narrow the current search")      # back on
check("A12 narrow option saved again", SAVED.get("quick_combine") is True)
b._search = "deck:Test::A"
trigger(quick.menu(), "Due today")
got = {k for k,v in rows.items() if v in set(col.find_cards(b.history[-1]))}
check("A13 Due today in deck A", got == {"rev_due","learn1","buried_rev"} - {"buried_rev"} or got == {"rev_due","learn1"}, str(sorted(got)) + " " + b.history[-1])
# the Edit menu action works too
sub[0].menu().actions()[1].trigger()    # 'Old'
check("A14 Edit-menu entry runs the filter", b.history[-1] == "(deck:Test::A) -is:new", b.history[-1])

# --- B: dialog -------------------------------------------------------------------------
SQ = []
CUR = {"setup": lambda d: None, "shot": None}
def fake_exec(self):
    CUR["setup"](self)
    if CUR["shot"]:
        self.show()
        for _ in range(4): app.processEvents()
        labels = [l for l in self.findChildren(QLabel) if l.wordWrap() and l.isVisibleTo(self)]
        bad = [l.text()[:30] for l in labels if l.height() < l.heightForWidth(l.width()) - 1]
        SQ.append((len(labels), bad, self.height(), self.layout().totalHeightForWidth(self.width())))
        self.grab().save(SHOTS + CUR["shot"])
    return 1
pkg.SearchAssistantDialog.exec = fake_exec

def open_dialog(setup, shot=None, browser=b):
    CUR["setup"], CUR["shot"] = setup, shot
    pkg._open_assistant(browser)

seen = {}
def s1(d):
    seen["chips"] = [(k, btn.text()) for k, btn in d.quick_buttons.items()]
    seen["any_checked"] = d.quick_buttons[""].isChecked()
    seen["search_enabled_empty"] = d.search_button.isEnabled()
    seen["preview_empty"] = d.query_preview.text()
    d.quick_buttons["new"].setChecked(True)
    seen["new_query"] = d.query
    seen["new_enabled"] = d.search_button.isEnabled()
    seen["new_summary"] = d.summary.text()
    seen["new_text"] = d.quick_buttons["new"].text()
    seen["any_text_after"] = d.quick_buttons[""].text()
    d.quick_buttons["old"].setChecked(True)
    seen["exclusive"] = [k for k, bt in d.quick_buttons.items() if bt.isChecked()]
    d.find_edit.setText("rev_due")
    d.field_combo.setCurrentIndex(d.field_combo.findData("Front"))
    seen["combo_query"] = d.query
    seen["combo_summary"] = d.summary.text()
    d.deck_combo.setCurrentIndex(next(i for i in range(d.deck_combo.count()) if d.deck_combo.itemData(i) == ("specific", "Test::A")))
open_dialog(s1, "ui_dialog_old_exact.png")
check("B1 13 filter buttons incl. Any", len(seen["chips"]) == 13, str(seen["chips"]))
check("B2 starts on 'Any' and Search is off with nothing chosen", seen["any_checked"] and not seen["search_enabled_empty"], str(seen))
check("B3 New alone (no text) is searchable", seen["new_query"] == "is:new" and seen["new_enabled"], seen["new_query"])
check("B4 summary names the filter", seen["new_summary"].startswith("New cards"), seen["new_summary"])
check("B5 chosen filter shows a tick, others do not", seen["new_text"] == "✓ New" and seen["any_text_after"] == "Any", str(seen))
check("B6 filters are exclusive", seen["exclusive"] == ["old"], str(seen["exclusive"]))
check("B7 Old + exact text builds the right query", "-is:new" in seen["combo_query"] and "Front:re:^rev_due$" in seen["combo_query"], seen["combo_query"])
check("B8 summary combines filter and text", seen["combo_summary"].startswith("Old cards"), seen["combo_summary"])

# search through the dialog with chips only
def s2(d):
    d.quick_buttons["failed_today"].setChecked(True)
    d.deck_combo.setCurrentIndex(next(i for i in range(d.deck_combo.count()) if d.deck_combo.itemData(i) == ("specific", "Test::A")))
    d._accept_search()
before = len(b.history)
open_dialog(s2)
q = b.history[-1]
check("B9 dialog search ran", len(b.history) == before + 1 and "rated:1:1" in q and "Test::A" in q, q)
check("B10 and finds the failed card in deck A", {k for k,v in rows.items() if v in set(col.find_cards(q))} == {"rev_due"}, q)

# Clear resets the filter chip
def s3(d):
    d.quick_buttons["buried"].setChecked(True); d.find_edit.setText("zzz")
    [bt for bt in d.findChildren(QPushButton) if bt.text() == "Clear"][0].click()
    seen["after_clear"] = (d.quick_buttons[""].isChecked(), d.find_edit.text())
open_dialog(s3)
check("B11 Clear resets filter and text", seen["after_clear"] == (True, ""), str(seen["after_clear"]))

# accessibility properties
def s4(d):
    seen["acc"] = [(bt.accessibleName(), bool(bt.toolTip())) for bt in d.quick_buttons.values()]
    seen["acc_find"] = d.find_edit.accessibleName()
    seen["default_btn"] = d.search_button.isDefault()
open_dialog(s4)
check("B12 every filter button has an accessible name + tooltip", all(n.startswith("Show ") and tip for n, tip in seen["acc"]), str(seen["acc"]))
check("B13 find box named, Search is the default (Enter) button", seen["acc_find"] and seen["default_btn"])

# 3.1: a selected note no longer overrides the remembered "Look in" choice (it reset it to Simplified)
nid = col.find_notes("Front:rev_due")[0]
pkg._save_config({"last_field_choice": "Back"})
b.sel = [nid]
def s5(d): seen["prefill"] = d.field_combo.currentData()
open_dialog(s5); b.sel = []
check("B14 selected note keeps the remembered Look in field", seen["prefill"] == "Back", str(seen["prefill"]))

# 3.2: the search bar's default field is its own button next to the search bar (no dialog, no typing)
pkg._save_config({"search_bar_field": ""})
bar = b._simple_search_bar_button
check("B15 button shows the current setting (off = all fields)", bar.text() == "Search bar: all fields ▾", bar.text())
m = bar.menu(); m.aboutToShow.emit()
def _all_actions(menu):
    out = []
    for a in menu.actions():
        out.append(a)
        if a.menu() is not None: out += _all_actions(a.menu())
    return out
items = {a.text(): a for a in _all_actions(m) if a.text()}
check("B16 menu explains itself and offers all fields, the word, meaning and real fields",
      any("plain words" in t.lower() for t in items) and "All fields (Anki's normal search)" in items
      and any(t.startswith("The word itself") for t in items) and "Back" in items, str(list(items)))
items["Back"].trigger()
check("B17 picking a field saves it and relabels the button at once", pkg._config()["search_bar_field"] == "Back" and bar.text() == "Search bar: Back ▾", bar.text())
m.aboutToShow.emit()
checked = [a.text() for a in _all_actions(m) if a.isCheckable() and a.isChecked()]
check("B18 the chosen field is ticked", checked == ["Back"], str(checked))
check("B19 the button is highlighted while a default is active", bool(bar.property("active")), str(bar.property("active")))
[a for a in m.actions() if a.text() == "All fields (Anki's normal search)"][0].trigger()
check("B20 'All fields' turns it off", pkg._config()["search_bar_field"] == "" and bar.text() == "Search bar: all fields ▾" and not bar.property("active"))
def s7(d): seen["has_checkbox"] = hasattr(d, "bar_default")
open_dialog(s7)
check("B21 the Search Assistant dialog no longer has a second, confusing switch", not seen["has_checkbox"])
pkg._save_config({"search_bar_field": "", "last_field_choice": "@word"})

# --- C: context menu --------------------------------------------------------------------
b.sel = [nid]
menu = QMenu()
pkg._add_context_menu(b, menu)
top = [a for a in menu.actions() if a.text() == "Search Assistant"][0].menu()
names = [a.text() for a in top.actions()]
check("C1 right-click: exact search + Quick card filters + open", any(n.startswith('Find exact') for n in names) and "Quick card filters" in names and "Open Search Assistant…" in names, str(names))
qsub = [a for a in top.actions() if a.text() == "Quick card filters"][0].menu()
b._search = "deck:current"; qsub.actions()[0].trigger()
check("C2 right-click quick filter works", b.history[-1] == "(deck:current) is:new", b.history[-1])
b.sel = []

# --- D: config robustness ---------------------------------------------------------------
SAVED.clear(); SAVED.update({"quick_combine": "yes", "shortcut": 5, "last_match": None})
cfg = pkg._config()
check("D1 malformed config falls back to safe defaults", cfg["quick_combine"] is True and cfg["shortcut"] == "" and cfg["last_match"] == "exact", str(cfg))
SAVED.clear()

# --- E: a second browser gets its own buttons, no leaks between them -------------------
b2 = FakeBrowser(); b2.show(); pkg._setup_browser(b2)
check("E1 second Browser window gets its own quick button", getattr(b2, "_simple_search_quick_button", None) is not None and b2._simple_search_quick_button is not quick)
pkg._setup_browser(b2)
check("E2 setup is idempotent", b2.form.gridLayout.count() == 6, str(b2.form.gridLayout.count()))

# screenshot of the toolbar with the open menu
b.resize(900, 120); b.show(); app.processEvents()
b.grab().save(SHOTS + "ui_toolbar.png")
check("no warnings were raised", not WARN, str(WARN))
for n, bad, h, need in SQ:
    check(f"layout: dialog not squeezed ({n} wrapped labels, height {h} vs {need})", not bad and h >= min(need, int(QApplication.primaryScreen().availableGeometry().height() * 0.9)) - 1, str(bad))
# --- E: normal search bar default (browser_will_search hook) -------------------------------
class _Ctx:
    def __init__(self, search): self.search, self.browser, self.ids = search, b, None
pkg._save_config({"search_bar_field": "Back"})
c1 = _Ctx("hello"); pkg._default_field_search(c1)
c2 = _Ctx("deck:current"); pkg._default_field_search(c2)
pkg._save_config({"search_bar_field": ""})
c3 = _Ctx("hello"); pkg._default_field_search(c3)
check("F1 plain text in the search bar searches only the default field", c1.search.startswith('"Back:re:'), c1.search)
check("F2 Anki syntax is left alone", c2.search == "deck:current", c2.search)
check("F3 off by default: plain text untouched", c3.search == "hello", c3.search)

print("\nRESULT:", "ALL PASSED" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
sys.exit(1 if FAILS else 0)
