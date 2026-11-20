"""Word search panel at the top of the Browser sidebar (4.0).

Type a word, a character or a meaning; the Browser shows the matching notes while you type. The panel
searches where you are (the deck the Browser shows) unless you pick another deck.
"""

from __future__ import annotations

from collections.abc import Callable

from aqt.qt import (
    QAction,
    QButtonGroup,
    QComboBox,
    QCompleter,
    QGridLayout,
    QHBoxLayout,
    QKeySequence,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QStringListModel,
    Qt,
    QTimer,
    QToolButton,
    QVBoxLayout,
    QWidget,
    qconnect,
)

from .core import (
    QUICK_FILTERS,
    WORD_AUTO,
    WORD_CONTAINS,
    WORD_EVERYWHERE,
    WORD_EXACT,
    WORD_MEANING,
    WORD_RELATED,
    WordSearch,
    auto_targets,
    is_cjk_text,
)

HERE = "@here"            # scope: the deck the Browser shows
KIND_WORD = "word"         # the "Word" chip: word fields with the chosen match
KINDS: tuple[tuple[str, str, str], ...] = (
    (WORD_AUTO, "Auto", "Characters search the word; Latin text searches the word and its meaning"),
    (KIND_WORD, "Word", "Only the word itself (Simplified, Traditional, Reading, Headword …)"),
    (WORD_MEANING, "Meaning", "Only the meaning / translation, as whole words: eat → 吃, 食べる, ăn"),
    (WORD_EVERYWHERE, "All fields", "Every field, also examples and long definitions – finds the most"),
)
MATCHES: tuple[tuple[str, str, str], ...] = (
    (WORD_EXACT, "Exact", "Exactly this word: 你 → 你"),
    (WORD_CONTAINS, "Contains", "Words containing it: 你 → 你, 你好, 你们 · cứ → cứ việc (not cứu)"),
    (WORD_RELATED, "Related", "Words sharing a character or syllable: 你好 → 你, 好, 好人"),
)
HISTORY_SIZE = 12
LIVE_DELAY_MS = 450

_CHIP = (
    "QPushButton{padding:3px 6px;border:1px solid palette(mid);border-radius:6px;}"
    "QPushButton:hover{border-color:palette(highlight);}"
    "QPushButton:checked{background:palette(highlight);color:palette(highlighted-text);font-weight:bold;}"
    "QPushButton:focus{border:2px solid palette(highlight);}"
)
_SEGMENT = (
    "QPushButton{padding:1px 4px;border:none;border-bottom:2px solid transparent;}"
    "QPushButton:hover{border-bottom-color:palette(mid);}"
    "QPushButton:checked{border-bottom-color:palette(highlight);font-weight:bold;}"
)
# palette(text) at reduced weight stays readable in light and dark mode (placeholder-text did not).
_QUIET = "color: palette(text);"


def _quiet(label: QLabel) -> QLabel:
    label.setStyleSheet(_QUIET)
    font = label.font()
    font.setPointSizeF(max(8.0, font.pointSizeF() - 1))
    label.setFont(font)
    return label


def _short_deck(name: str) -> str:
    parts = [p for p in name.split("::") if p]
    return " › ".join(parts[-2:]) if parts else "all decks"


class _DeckCombo(QComboBox):
    """Deck picker that refreshes its list every time it opens."""

    def __init__(self, refresh: Callable[[], None], parent: QWidget) -> None:
        super().__init__(parent)
        self._refresh = refresh

    def showPopup(self) -> None:
        try:
            self._refresh()
        except Exception:
            pass
        super().showPopup()


class WordSearchPanel(QWidget):
    """Type → see results. Auto mode picks the right fields; scope follows the deck you are in."""

    def __init__(
        self,
        parent: QWidget,
        *,
        decks: Callable[[], list[str]],
        run: Callable[[WordSearch], str],
        config: dict,
        save: Callable[[dict], None],
        here: Callable[[], str] = lambda: "",
        count: Callable[[], int | None] = lambda: None,
        show_scope: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("simpleSearchWordPanel")
        self._decks = decks
        self._run = run
        self._save = save
        self._here = here
        self._count = count
        self._show_scope = show_scope
        self._kind = str(config.get("word_kind") or WORD_AUTO)
        if self._kind not in {k for k, _l, _t in KINDS}:
            self._kind = WORD_AUTO
        old_mode = str(config.get("word_mode") or "")
        self._match = str(config.get("word_match") or (old_mode if old_mode in {m for m, _l, _t in MATCHES} else WORD_CONTAINS))
        if self._match not in {m for m, _l, _t in MATCHES}:
            self._match = WORD_CONTAINS
        self._live = bool(config.get("search_as_you_type", True))
        self._history: list[str] = [str(h) for h in config.get("word_history", []) if str(h).strip()][:HISTORY_SIZE]
        self.last_query = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 6, 8, 8)
        outer.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(4)
        self.title = QLabel("Word search")
        font = self.title.font()
        font.setBold(True)
        self.title.setFont(font)
        head.addWidget(self.title, 1)
        self.toggle = QToolButton(self)
        self.toggle.setAutoRaise(True)
        self.toggle.setAccessibleName("Show or hide word search")
        qconnect(self.toggle.clicked, lambda _checked=False: self.set_open(not self.body.isVisible()))
        head.addWidget(self.toggle)
        outer.addLayout(head)

        self.body = QWidget(self)
        body = QVBoxLayout(self.body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(6)
        outer.addWidget(self.body)

        # -- the box
        self.edit = QLineEdit(self.body)
        self.edit.setClearButtonEnabled(True)
        self.edit.setPlaceholderText("Word, character or meaning…")
        self.edit.setAccessibleName("Word to search for")
        self.edit.setToolTip("Results appear while you type · Enter searches at once · Esc clears")
        self.edit.setMinimumHeight(28)
        self._completer_model = QStringListModel(self._history, self)
        completer = QCompleter(self._completer_model, self.edit)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.edit.setCompleter(completer)
        qconnect(self.edit.returnPressed, self.search)
        qconnect(self.edit.textEdited, self._typed)
        body.addWidget(self.edit)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(LIVE_DELAY_MS)
        qconnect(self._timer.timeout, self._live_search)
        clear = QAction(self)
        clear.setShortcut(QKeySequence(Qt.Key.Key_Escape))
        clear.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        qconnect(clear.triggered, self.clear)
        self.edit.addAction(clear)

        # -- what to search: Auto · Word · Meaning · All fields
        kinds = QGridLayout()
        kinds.setHorizontalSpacing(4)
        kinds.setVerticalSpacing(4)
        self.kind_group = QButtonGroup(self)
        self.kind_buttons: dict[str, QPushButton] = {}
        for index, (key, label, tip) in enumerate(KINDS):
            button = self._chip(label, tip, _CHIP)
            self.kind_group.addButton(button)
            self.kind_buttons[key] = button
            kinds.addWidget(button, index // 2, index % 2)
            qconnect(button.clicked, lambda _c=False, k=key: self.set_kind(k))
        body.addLayout(kinds)

        # -- how the word matches: Exact · Contains · Related (for Auto and Word)
        self.match_row = QWidget(self.body)
        row = QHBoxLayout(self.match_row)
        row.setContentsMargins(2, 0, 0, 0)
        row.setSpacing(2)
        self.match_group = QButtonGroup(self)
        self.match_buttons: dict[str, QPushButton] = {}
        for key, label, tip in MATCHES:
            button = self._chip(label, tip, _SEGMENT)
            button.setMinimumHeight(22)
            self.match_group.addButton(button)
            self.match_buttons[key] = button
            row.addWidget(button)
            qconnect(button.clicked, lambda _c=False, k=key: self.set_match(k))
        body.addWidget(self.match_row)

        # -- where and which cards
        form = QGridLayout()
        form.setHorizontalSpacing(6)
        form.setVerticalSpacing(5)
        form.addWidget(QLabel("In:"), 0, 0)
        self.deck_combo = _DeckCombo(self._fill_decks, self.body)
        self.deck_combo.setAccessibleName("Search in deck")
        self.deck_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.deck_combo.setMinimumContentsLength(8)
        self.deck_combo.setMaxVisibleItems(25)
        self.deck_combo.view().setMinimumWidth(320)
        form.addWidget(self.deck_combo, 0, 1)
        form.addWidget(QLabel("Cards:"), 1, 0)
        self.card_combo = QComboBox(self.body)
        self.card_combo.setAccessibleName("Card filter")
        self.card_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.card_combo.setMinimumContentsLength(8)
        for key, label, tip in QUICK_FILTERS:
            self.card_combo.addItem("Any card" if not key else label, key)
            self.card_combo.setItemData(self.card_combo.count() - 1, tip, Qt.ItemDataRole.ToolTipRole)
        form.addWidget(self.card_combo, 1, 1)
        form.setColumnStretch(1, 1)
        body.addLayout(form)

        # -- what just happened
        self.summary = _quiet(QLabel(self.body))
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body.addWidget(self.summary)
        self.status = QLabel(self.body)          # errors only
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #e5534b;")
        self.status.setVisible(False)
        body.addWidget(self.status)

        self._wanted_deck = str(config.get("word_scope", HERE))
        self._fill_decks()
        index = self.card_combo.findData(str(config.get("word_cards", "")))
        self.card_combo.setCurrentIndex(max(0, index))
        self.kind_buttons[self._kind].setChecked(True)
        self.match_buttons[self._match].setChecked(True)
        self._refresh_match_row()
        self._describe()
        qconnect(self.deck_combo.activated, lambda _i: self._changed_scope())
        qconnect(self.card_combo.activated, lambda _i: self._changed_scope())
        self.set_open(bool(config.get("word_panel_open", True)), save=False)

    def _chip(self, label: str, tip: str, style: str) -> QPushButton:
        button = QPushButton(label, self.body)
        button.setCheckable(True)
        button.setToolTip(tip)
        button.setAccessibleName(label)
        button.setAccessibleDescription(tip)
        button.setStyleSheet(style)
        button.setMinimumHeight(26)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return button

    # ------------------------------------------------------------------ state
    def set_open(self, open_: bool, *, save: bool = True) -> None:
        self.body.setVisible(open_)
        self.toggle.setText("▾" if open_ else "▸")
        self.toggle.setToolTip("Hide word search" if open_ else "Show word search")
        if save:
            self._save({"word_panel_open": bool(open_)})

    def focus(self) -> None:
        self.set_open(True)
        self.edit.setFocus()
        self.edit.selectAll()

    @property
    def scope(self) -> str:
        """HERE, "" (all decks) or a deck name."""
        data = self.deck_combo.currentData()
        return HERE if data is None else str(data)

    def deck(self) -> str:
        """The deck the next search is limited to ("" = all decks)."""
        return self._here() if self.scope == HERE else self.scope

    def _fill_decks(self) -> None:
        current = self.deck_combo.currentData()
        wanted = self._wanted_deck if current is None else str(current)
        here = self._here()
        self.deck_combo.blockSignals(True)
        self.deck_combo.clear()
        self.deck_combo.addItem(f"Here · {here.split('::')[-1] if here else 'all decks'}", HERE)
        self.deck_combo.setItemData(0, "Follows the deck the Browser shows – click a deck on the left to change it.\n"
                                    + (here.replace("::", " › ") if here else "Now: all decks"),
                                    Qt.ItemDataRole.ToolTipRole)
        self.deck_combo.addItem("All decks", "")
        self.deck_combo.insertSeparator(self.deck_combo.count())
        for name in self._decks():
            parts = name.split("::")
            self.deck_combo.addItem("    " * (len(parts) - 1) + parts[-1], name)
            self.deck_combo.setItemData(self.deck_combo.count() - 1, name.replace("::", " › "), Qt.ItemDataRole.ToolTipRole)
        index = self.deck_combo.findData(wanted)
        self.deck_combo.setCurrentIndex(index if index >= 0 else 0)
        self.deck_combo.setToolTip(str(self.deck_combo.itemData(self.deck_combo.currentIndex(), Qt.ItemDataRole.ToolTipRole)
                                       or self.deck_combo.currentText()))
        self.deck_combo.blockSignals(False)

    def location_changed(self) -> None:
        """The Browser now shows another deck: update the label and, if a word is typed, search it there."""
        self._fill_decks()
        if self.scope == HERE and self.edit.text().strip():
            self.search(remember=False)
        else:
            self._describe()

    def set_kind(self, key: str) -> None:
        self._kind = key
        self.kind_buttons[key].setChecked(True)
        self._refresh_match_row()
        self._save({"word_kind": key})
        self._rerun()

    def set_match(self, key: str) -> None:
        self._match = key
        self.match_buttons[key].setChecked(True)
        self._save({"word_match": key})
        self._rerun()

    def _refresh_match_row(self) -> None:
        self.match_row.setVisible(self._kind in (WORD_AUTO, KIND_WORD))

    def _changed_scope(self) -> None:
        scope = self.scope
        self._wanted_deck = scope
        self.deck_combo.setToolTip(str(self.deck_combo.itemData(self.deck_combo.currentIndex(), Qt.ItemDataRole.ToolTipRole)
                                       or self.deck_combo.currentText()))
        self._save({"word_scope": scope, "word_cards": str(self.card_combo.currentData() or "")})
        if self.edit.text().strip():
            self.search()
        elif self._show_scope is not None:   # no word: just show the deck / card filter
            self.search()
        else:
            self._describe()

    def _rerun(self) -> None:
        if self.edit.text().strip():
            self.search()
        else:
            self._describe()

    # ---------------------------------------------------------------- search
    def _typed(self, text: str) -> None:
        if not self._live:
            return
        if not text.strip():
            self._timer.stop()
            self.clear(keep_text=True)
            return
        self._timer.start()

    def _live_search(self) -> None:
        text = self.edit.text().strip()
        if not text or (not is_cjk_text(text) and len(text) < 2):
            return
        self.search(remember=False)

    def current(self) -> WordSearch:
        mode = self._match if self._kind == KIND_WORD else self._kind
        return WordSearch(
            text=self.edit.text().strip(),
            mode=mode,
            deck=self.deck(),
            card_filter=str(self.card_combo.currentData() or ""),
            match=self._match,
        )

    def search(self, remember: bool = True) -> None:
        self._timer.stop()
        spec = self.current()
        try:
            query = self._run(spec)
        except Exception as error:
            self.status.setText(str(error))
            self.status.setVisible(True)
            self.summary.setVisible(False)
            return
        self.status.setVisible(False)
        self.last_query = query
        if remember and spec.text:
            self._remember(spec.text)
        self._describe(found=self._count())

    def clear(self, keep_text: bool = False) -> None:
        """Esc / ✕: empty the box and show the whole deck again."""
        self._timer.stop()
        if not keep_text:
            self.edit.clear()
        self.status.setVisible(False)
        if self._show_scope is not None:
            try:
                self._show_scope(self.deck())
            except Exception:
                pass
        self._describe()

    def _remember(self, text: str) -> None:
        self._history = [text] + [h for h in self._history if h.casefold() != text.casefold()]
        self._history = self._history[:HISTORY_SIZE]
        self._completer_model.setStringList(self._history)
        self._save({"word_history": list(self._history)})

    def _describe(self, found: int | None = None) -> None:
        spec = self.current()
        where = _short_deck(spec.deck) if spec.deck else "all decks"
        if not spec.text:
            self.summary.setText(f"Searching in {where}. Type to see results.")
        else:
            if self._kind == WORD_AUTO:
                what = "the word" if auto_targets(spec.text) == "word" else "word or meaning"
            else:
                what = {KIND_WORD: "the word", WORD_MEANING: "the meaning", WORD_EVERYWHERE: "all fields"}[self._kind]
            how = {WORD_EXACT: "is", WORD_CONTAINS: "contains", WORD_RELATED: "related to"}[self._match]
            if self._kind in (WORD_MEANING, WORD_EVERYWHERE):
                how = "contains"
            count = "" if found is None else (f"{found} note{'s' if found != 1 else ''} · ")
            line = f"{what} {how} “{spec.text}” · {where}"
            self.summary.setText(count + (line[:1].upper() + line[1:] if not count else line))
        self.summary.setVisible(True)


def install_panel(browser, panel: WordSearchPanel) -> bool:
    """Put the panel between the sidebar filter box and the sidebar tree."""
    dock = getattr(browser, "sidebarDockWidget", None)
    sidebar = getattr(browser, "sidebar", None)
    holder = dock.widget() if dock is not None else None
    grid = holder.layout() if holder is not None else None
    if isinstance(grid, QGridLayout) and sidebar is not None and grid.indexOf(sidebar) >= 0:
        row, _col, _rows, cols = grid.getItemPosition(grid.indexOf(sidebar))
        grid.removeWidget(sidebar)
        grid.addWidget(panel, row, 0, 1, max(1, cols))
        grid.addWidget(sidebar, row + 1, 0, 1, max(1, cols))
        grid.setRowStretch(row + 1, 1)
        return True
    form_grid = getattr(getattr(browser, "form", None), "gridLayout", None)
    if form_grid is not None:
        form_grid.addWidget(panel, form_grid.rowCount(), 0, 1, max(1, form_grid.columnCount()))
        return True
    return False


def focus_action(browser, panel: WordSearchPanel, shortcut: str) -> QAction:
    action = QAction("Word search", browser)
    if shortcut:
        action.setShortcut(QKeySequence(shortcut))

    def go(_checked: bool = False) -> None:
        show = getattr(browser, "showSidebar", None)
        if callable(show):
            show(True)
        panel.focus()

    qconnect(action.triggered, go)
    return action
