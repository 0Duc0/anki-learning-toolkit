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
check("W4 default mode Contains, all decks, any card", panel._mode == "contains" and panel.deck_combo.currentData() == "" and panel.card_combo.currentData() == "")

panel.edit.setText("你"); panel.edit.returnPressed.emit()
check("W5 Enter searches: 你 contains -> 你, 你好, 你们", found(b.history[-1]) == ["ni", "nihao", "nimen"], b.history[-1])
panel.buttons["exact"].click()
check("W6 clicking Exact re-runs at once", found(b.history[-1]) == ["ni"], b.history[-1])
panel.buttons["related"].click()
check("W7 Related: 你 shares a character", found(b.history[-1]) == ["ni", "nihao", "nimen"])
panel.edit.setText("eat"); panel.buttons["meaning"].click()
check("W8 Meaning eat -> 吃 / 食べる / ăn only", found(b.history[-1]) == ["an", "chi", "taberu"], found(b.history[-1]))
panel.edit.setText("好"); panel.buttons["contains"].click()
i = panel.deck_combo.findData("Language::中文"); panel.deck_combo.setCurrentIndex(i); panel.deck_combo.activated.emit(i)
check("W9 choosing a deck narrows at once (中文 only)", found(b.history[-1]) == ["hao", "haoren", "nihao"], found(b.history[-1]))
check("W10 deck list is indented tree with full-path tooltip", panel.deck_combo.itemText(i).strip() == "中文" and panel.deck_combo.itemText(i).startswith("    ")
      and "Language › 中文" == panel.deck_combo.itemData(i, Qt.ItemDataRole.ToolTipRole))
j = panel.card_combo.findData("new"); panel.card_combo.setCurrentIndex(j); panel.card_combo.activated.emit(j)
check("W11 card filter New added", "is:new" in b.history[-1] and found(b.history[-1]) == ["hao", "haoren", "nihao"], b.history[-1])
check("W12 choices remembered", SAVED.get("word_mode") == "contains" and SAVED.get("word_deck") == "Language::中文" and SAVED.get("word_cards") == "new", str(SAVED))
n = len(b.history); panel.edit.setText(""); panel.card_combo.setCurrentIndex(0); panel.deck_combo.setCurrentIndex(0); panel.search()
check("W13 nothing to search -> message in the panel, no search, no popup", len(b.history) == n and panel.status.isVisibleTo(panel) and not WARN, panel.status.text())
panel.edit.setText("cứ"); panel.search()
check("W14 status hides again after a good search; cứ not cứu", not panel.status.isVisibleTo(panel) and found(b.history[-1]) == ["cu", "cuviec"])
panel.set_open(False)
check("W15 collapse saved", SAVED.get("word_panel_open") is False and not panel.body.isVisibleTo(panel))
act.trigger()
check("W16 shortcut opens panel and focuses the box", panel.body.isVisibleTo(panel) and SAVED.get("word_panel_open") is True)
b2 = FakeBrowser(); b2.show(); pkg._setup_browser(b2); p2 = b2._simple_search_word_panel
check("W17 next Browser restores mode/deck/cards", p2._mode == "contains" and p2.deck_combo.currentData() == "Language::中文" and p2.card_combo.currentData() == "new")
p2.card_combo.setCurrentIndex(0); p2.card_combo.activated.emit(0)
# panel screenshot
panel.edit.setText("你好"); panel.buttons["related"].setChecked(True); panel._mode = "related"; panel._show_hint()
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
check("C2 'Words containing' runs through the panel", panel._mode == "contains" and panel.edit.text() == "食べる" and found(b.history[-1]) == ["taberu"], b.history[-1])
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
