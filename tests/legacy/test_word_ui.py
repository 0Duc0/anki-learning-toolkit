"""Word search panel + reworked dialog, real add-on code, collection shaped like the user's."""
import os, sys, types
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _toolkit
import anki.lang; anki.lang.set_lang("en")
from aqt.qt import *
app = QApplication([])
_px = int(os.environ.get("PX", "0"))
if _px:
    _f = app.font(); _f.setPixelSize(_px); app.setFont(_f)
import aqt
import fixture_user as fx
col, ids = fx.make()
rev = {v: k for k, v in ids.items()}
SAVED = {}
class FakeMw(QMainWindow):
    def __init__(self):
        super().__init__(); self.col = col; self.app = app
        self.addonManager = types.SimpleNamespace(getConfig=lambda n: dict(SAVED) if SAVED else None, writeConfig=lambda n, c: SAVED.update(c))
aqt.mw = FakeMw()
pkg = _toolkit.module("search", flat=True)
WARN = []
pkg.showWarning = lambda text, *a, **k: WARN.append(text)
class FakeQueryOp:
    def __init__(self, parent, op, success): self.op, self.s = op, success
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
    """Same widget structure as Anki 25.09's Browser for the parts the add-on touches."""
    def __init__(self):
        super().__init__()
        self.col = col; self.editor = FakeEditor(); self.sel = []
        self.form = types.SimpleNamespace(menuEdit=QMenu("Edit", self), gridLayout=QGridLayout())
        host = QWidget(); v = QVBoxLayout(host); v.addLayout(self.form.gridLayout)
        self.table = QTableWidget(8, 3); v.addWidget(self.table, 1); self.setCentralWidget(host)
        self.form.gridLayout.addWidget(QLineEdit("deck:current"), 0, 0)
        self.form.gridLayout.addWidget(QPushButton("Search"), 0, 1)
        dw = self.sidebarDockWidget = QDockWidget("Sidebar", self)
        self.sidebar = QTreeWidget(); self.sidebar.setHeaderHidden(True)
        for name in ("Saved Searches", "Today", "Flags", "Card State", "Decks", "Note Types", "Tags"):
            QTreeWidgetItem(self.sidebar, [name])
        self.sidebar.searchBar = QLineEdit(); self.sidebar.searchBar.setPlaceholderText("Filter sidebar")
        self.sidebar.toolbar = QToolBar(); self.sidebar.toolbar.addAction("⌖")
        grid = QGridLayout()
        grid.addWidget(self.sidebar.searchBar, 0, 0); grid.addWidget(self.sidebar.toolbar, 0, 1)
        grid.addWidget(self.sidebar, 1, 0, 1, 2); grid.setContentsMargins(8, 4, 0, 0); grid.setSpacing(0)
        w = QWidget(); w.setLayout(grid); dw.setWidget(w); dw.setTitleBarWidget(QWidget())
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dw)
        self._search = "deck:current"; self.history = []
    def showSidebar(self, show=True): self.sidebarDockWidget.setVisible(show)
    def current_search(self): return self._search
    def search_for(self, q): self._search = q; self.history.append(q)
    def update_history(self): pass
    def selected_notes(self): return list(self.sel)

FAILS = []
def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  -> {extra}"))
    if not cond: FAILS.append(name)
def found(q): return sorted(rev[n] for n in col.find_notes(q) if n in rev)
SHOTS = _toolkit.SHOTS
tag = f"_px{_px}" if _px else ""

b = FakeBrowser(); b.resize(1000, 640); b.show()
pkg._setup_browser(b)
panel = getattr(b, "_simple_search_word_panel", None)
check("W1 panel created", panel is not None)
grid = b.sidebarDockWidget.widget().layout()
pos = {grid.itemAt(i).widget(): grid.getItemPosition(i) for i in range(grid.count())}
check("W2 panel sits under the sidebar filter, tree below it", pos.get(panel, (None,))[0] == 1 and pos[b.sidebar][0] == 2, str({type(k).__name__: v for k, v in pos.items()}))
act = b._simple_search_word_action
check("W3 shortcut Ctrl+Shift+W + Edit menu entry", act.shortcut().toString() == "Ctrl+Shift+W" and act in b.form.menuEdit.actions())
check("W4 defaults: Auto, Here (all decks at first), any card", panel._kind == "auto" and panel.scope == "@here" and panel.deck() == "" and panel._cards == "")
check("W4b four dropdown buttons like 'Cards ▾'", all(isinstance(x, QToolButton) and x.text().endswith("▾") for x in (panel.kind_button, panel.match_button, panel.deck_button, panel.cards_button)),
      [x.text() for x in (panel.kind_button, panel.match_button, panel.deck_button, panel.cards_button)])

panel.edit.setText("你"); panel.edit.returnPressed.emit()
check("W5 Enter: Auto 你 -> word contains: 你, 你好, 你们", found(b.history[-1]) == ["ni", "nihao", "nimen"], b.history[-1])
check("W5b summary short: what · where", panel.summary.text() == "word · All decks", panel.summary.text())
panel.set_match("exact")
check("W6 Exact re-runs at once", found(b.history[-1]) == ["ni"], b.history[-1])
panel.set_match("related")
check("W7 Related: 你 shares a character", found(b.history[-1]) == ["ni", "nihao", "nimen"])
panel.set_match("contains")
panel.edit.setText("eat"); panel.search()
check("W8 Auto with Latin text: word or meaning (吃, 食べる, ăn – not great/theater)", found(b.history[-1]) == ["an", "chi", "taberu"], found(b.history[-1]))
check("W8b summary says word or meaning", panel.summary.text().startswith("word or meaning"), panel.summary.text())
panel.set_kind("meaning")
check("W8c Meaning: same result, match button disabled", found(b.history[-1]) == ["an", "chi", "taberu"] and not panel.match_button.isEnabled())
panel.set_kind("everywhere")
check("W8d All fields finds more (example + long definition)", set(found(b.history[-1])) >= {"an", "chi", "taberu", "weida"}, found(b.history[-1]))
panel.set_kind("word")
check("W8e Word: 'eat' is in no word field", found(b.history[-1]) == [] and panel.match_button.isEnabled())
panel.set_kind("auto")

# -- the deck follows where you are, also deck names with spaces
panel.edit.setText("好"); panel.search()
check("W9 好 in all decks", set(found(b.history[-1])) >= {"hao", "haoren", "nihao", "nihonjin", "he_hao"}, found(b.history[-1]))
pkg._browser_did_search(types.SimpleNamespace(browser=b, search='"deck:Language::中文"'))
check("W9b clicking a deck on the left: panel follows and searches there", b._ssa_here == "Language::中文" and found(b.history[-1]) == ["hao", "haoren", "nihao"] and panel.deck_button.text().startswith("中文"), (b._ssa_here, found(b.history[-1]), panel.deck_button.text()))
n = len(b.history)
pkg._browser_did_search(types.SimpleNamespace(browser=b, search=b.history[-1]))
check("W9c our own searches don't count as moving", len(b.history) == n and b._ssa_here == "Language::中文")
pkg._browser_did_search(types.SimpleNamespace(browser=b, search="is:due"))
check("W9d a search without a deck keeps where you are", b._ssa_here == "Language::中文")
pkg._browser_did_search(types.SimpleNamespace(browser=b, search='"deck:Language::Tiếng"'))
check("W9e a deck that doesn't exist is ignored", b._ssa_here == "Language::中文")
pkg._browser_did_search(types.SimpleNamespace(browser=b, search='"deck:Language::Tiếng Việt"'))
panel.edit.setText("đức"); panel.search()
check("W9f deck name with a space (Tiếng Việt): đức found there", b._ssa_here == "Language::Tiếng Việt" and found(b.history[-1]) == ["duc"], (b._ssa_here, b.history[-1], found(b.history[-1])))
panel.edit.setText("好"); panel.set_scope("Language::中文::詞彙::a. 孫悟空"); app.processEvents()
check("W10 picking a deck from the menu narrows at once", found(b.history[-1]) == ["nihao"] and panel.deck_button.text().startswith("a. 孫悟空"), (found(b.history[-1]), panel.deck_button.text()))
m = panel.deck_button.menu(); m.aboutToShow.emit()
top = [a.text() for a in m.actions()]
check("W10b deck menu: Here, All decks, then a deck tree", top[0].startswith("Here – Language › Tiếng Việt") and top[1] == "All decks" and "Language" in top, top)
pkg._browser_did_search(types.SimpleNamespace(browser=b, search='"deck:Language::中文"'))
panel.set_scope("@here")
panel.set_cards("new")
check("W11 card filter New added", "is:new" in b.history[-1] and found(b.history[-1]) == ["hao", "haoren", "nihao"] and panel.cards_button.text().startswith("New"), b.history[-1])
check("W12 choices remembered", SAVED.get("word_kind") == "auto" and SAVED.get("word_scope") == "@here" and SAVED.get("word_cards") == "new" and SAVED.get("word_match") == "contains", str(SAVED))
check("W12b Enter remembers the word for the completer", SAVED.get("word_history", [])[:3] == ["好", "đức", "eat"], SAVED.get("word_history"))

panel.clear()
check("W13 Esc/clear: no word -> whole deck shown, no error", panel.edit.text() == "" and "好" not in b.history[-1] and "中文" in b.history[-1] and not panel.status.isVisibleTo(panel) and not WARN, b.history[-1])
panel.set_cards("")

n = len(b.history)
panel.edit.setText("c"); panel.edit.textEdited.emit("c"); panel._timer.timeout.emit()
check("W14 one Latin letter is not searched live", len(b.history) == n)
pkg._browser_did_search(types.SimpleNamespace(browser=b, search='"deck:Language::Tiếng Việt"'))
panel.edit.setText("cứ"); panel.edit.textEdited.emit("cứ")
check("W14b typing starts the timer", panel._timer.isActive())
panel._timer.timeout.emit()
check("W14c live result: cứ, cứ việc (not cứu), not added to history", found(b.history[-1]) == ["cu", "cuviec"] and "cứ" not in SAVED.get("word_history", []), (found(b.history[-1]), SAVED.get("word_history")))
panel.edit.setText(""); panel.edit.textEdited.emit("")
check("W14d deleting the text shows the deck again", "cứ" not in b.history[-1] and "Tiếng Việt" in b.history[-1], b.history[-1])

panel.edit.setText(""); panel.search()
check("W15 nothing typed + Enter: deck shown, no popup", not WARN)
panel.set_open(False)
check("W15b collapse saved", SAVED.get("word_panel_open") is False and not panel.body.isVisibleTo(panel))
act.trigger()
check("W16 shortcut opens panel and focuses the box", panel.body.isVisibleTo(panel) and SAVED.get("word_panel_open") is True)
b2 = FakeBrowser(); b2.show(); pkg._setup_browser(b2); p2 = b2._simple_search_word_panel
check("W17 next Browser restores kind/match/scope", p2._kind == "auto" and p2._match == "contains" and p2.scope == "@here")
check("W17b search bar starts on Auto once", pkg._config()["search_bar_field"] == "@auto" and pkg._config()["search_bar_auto_4"] is True)
# panel screenshot
pkg._browser_did_search(types.SimpleNamespace(browser=b, search='"deck:Language::中文"'))
panel.edit.setText("你好"); panel.search()
b.resize(1000, 640); app.processEvents()
b.grab().save(SHOTS + f"ui_word_panel{tag}.png")
lbls = [l for l in panel.findChildren(QLabel) if l.wordWrap() and l.isVisibleTo(panel)]
check("W18 panel hint text not clipped", all(l.height() >= l.heightForWidth(l.width()) - 1 for l in lbls))
check("W19 panel does not force a wide sidebar (min width <= 240)", panel.minimumSizeHint().width() <= (240 if _px <= 17 else 280), panel.minimumSizeHint().width())

# ---- right-click on a JP note uses the Word field, not EntryID
b.sel = [ids["taberu"]]
menu = QMenu(); pkg._add_context_menu(b, menu)
sub = [a for a in menu.actions() if a.text() == "Search Assistant"][0].menu()
names = [a.text() for a in sub.actions()]
check("C1 exact uses the word field (Word), not EntryID", any(t.startswith('Find exact "食べる" in Word') for t in names), names)
[a for a in sub.actions() if a.text().startswith("Words containing")][0].trigger()
check("C2 'Words containing' runs through the panel", panel._kind == "word" and panel._match == "contains" and panel.edit.text() == "食べる" and found(b.history[-1]) == ["taberu"], b.history[-1])
b.sel = [ids["yangguang"]]
menu = QMenu(); pkg._add_context_menu(b, menu)
sub = [a for a in menu.actions() if a.text() == "Search Assistant"][0].menu()
check("C3 Chinese note: exact uses Simplified", any(a.text().startswith('Find exact "阳光" in Simplified') for a in sub.actions()), [a.text() for a in sub.actions()])
b.sel = []

# ---- dialog
CUR = {"setup": lambda d: None, "shot": None}
SQ = []
def fake_exec(self):
    CUR["setup"](self)
    if CUR["shot"]:
        self.show()
        for _ in range(4): app.processEvents()
        labels = [l for l in self.findChildren(QLabel) if l.wordWrap() and l.isVisibleTo(self)]
        bad = [l.text()[:30] for l in labels if l.height() < l.heightForWidth(l.width()) - 1]
        SQ.append((bad, self.height(), min(self.layout().totalHeightForWidth(self.width()), int(QApplication.primaryScreen().availableGeometry().height() * 0.9))))
        self.grab().save(SHOTS + CUR["shot"])
    return 1
pkg.SearchAssistantDialog.exec = fake_exec
seen = {}
def items(c): return [(c.itemText(i), c.itemData(i)) for i in range(c.count())]
def s1(d):
    seen["default"] = d.field_combo.currentData()
    seen["all"] = items(d.field_combo)
    i = next(k for k in range(d.deck_combo.count()) if d.deck_combo.itemData(k) == ("specific", "Language::中文"))
    d.deck_combo.setCurrentIndex(i)
    seen["cn"] = items(d.field_combo)
    d.find_edit.setText("你好")
    d.match_combo.setCurrentIndex(d.match_combo.findData("related"))
    seen["q"] = d.query
    seen["summary"] = d.summary.text()
CUR.update(setup=s1, shot=f"ui_dialog_scoped{tag}.png")
pkg._open_assistant(b)
check("D1 dialog defaults to 'The word itself'", seen["default"] == "@word", seen["default"])
cn_fields = [d for _t, d in seen["cn"] if d not in (None, "", "@word", "@meaning")]
check("D2 Chinese scope lists only Chinese fields", set(cn_fields) == set(fx.TYPES["CC-CEDICT Optimized EN v5.3"]), cn_fields)
check("D3 list is much shorter than everything", len(seen["cn"]) < len(seen["all"]), (len(seen["cn"]), len(seen["all"])))
word_entry = next((t for t, dd in seen["cn"] if dd == "@word"), "")
check("D4 word entry names the real fields", word_entry.startswith("The word itself – Simplified, Traditional"), word_entry)
check("D4b recommended (sort) fields come first", seen["cn"][0][0].startswith("★ "), seen["cn"][0][0])
check("D5 note-type header present and not selectable", any(t == "CC-CEDICT Optimized EN v5.3" and dd is None for t, dd in seen["cn"]))
check("D6 related in Chinese: 你好 -> 你 好 你们 好人 你好 only", found(seen["q"]) == ["hao", "haoren", "ni", "nihao", "nimen"], seen["q"])
check("D7 friendly summary", "Shares a character" in seen["summary"] and "the word itself" in seen["summary"], seen["summary"])
def s2(d):
    d.find_edit.setText("cứ"); d.match_combo.setCurrentIndex(d.match_combo.findData("contains_word")); d._accept_search()
CUR.update(setup=s2, shot=None); pkg._open_assistant(b)
check("D8 dialog search ran (cứ whole syllable)", found(b.history[-1]) == ["cu", "cuviec"], b.history[-1])
check("D9 dialog remembers field choice", SAVED.get("last_field_choice") == "@word")
def s3(d):
    seen["after"] = d.field_combo.currentData()
    i = d.field_combo.findData("Traditional"); d.field_combo.setCurrentIndex(i)
    k = next(k for k in range(d.deck_combo.count()) if d.deck_combo.itemData(k) == ("specific", "Heisig")); d.deck_combo.setCurrentIndex(k)
    seen["fallback"] = d.field_combo.currentData()
CUR.update(setup=s3, shot=None); pkg._open_assistant(b)
check("D10 field not in new deck scope falls back to that deck's recommended field",
      seen["after"] == "@word" and seen["fallback"] in ("@word", "Zeichen"), (seen["after"], seen["fallback"]))
for bad, h, need in SQ:
    check(f"layout: dialog not squeezed ({h} vs {need})", not bad and h >= need - 1, bad)
check("no warnings raised", not WARN, WARN)
print("\nRESULT:", "ALL PASSED" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
sys.exit(1 if FAILS else 0)
