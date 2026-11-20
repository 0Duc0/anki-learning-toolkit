"""Word search panel shown at the top of the Browser sidebar (3.0)."""

from __future__ import annotations

from collections.abc import Callable

from aqt.qt import (
    QAction,
    QButtonGroup,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QKeySequence,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    Qt,
    QToolButton,
    QVBoxLayout,
    QWidget,
    qconnect,
)

from .core import QUICK_FILTERS, WORD_CONTAINS, WORD_MODES, WordSearch

_PANEL_CHIP = (
    "QPushButton{padding:3px 8px;border:1px solid palette(mid);border-radius:6px;}"
    "QPushButton:hover{border-color:palette(highlight);}"
    "QPushButton:checked{background:palette(highlight);color:palette(highlighted-text);"
    "font-weight:bold;}"
    "QPushButton:focus{border:2px solid palette(highlight);}"
)


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
    """Type a word, pick how it should match, press Enter."""

    def __init__(
        self,
        parent: QWidget,
        *,
        decks: Callable[[], list[str]],
        run: Callable[[WordSearch], str],
        config: dict,
        save: Callable[[dict], None],
    ) -> None:
        super().__init__(parent)
        self.setObjectName("simpleSearchWordPanel")
        self._decks = decks
        self._run = run
        self._save = save
        self._mode = str(config.get("word_mode") or WORD_CONTAINS)
        if self._mode not in {key for key, _l, _t in WORD_MODES}:
            self._mode = WORD_CONTAINS

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

        self.edit = QLineEdit(self.body)
        self.edit.setClearButtonEnabled(True)
        self.edit.setPlaceholderText("Word, character or meaning…")
        self.edit.setAccessibleName("Word to search for")
        self.edit.setToolTip("Type a word and press Enter")
        qconnect(self.edit.returnPressed, self.search)
        body.addWidget(self.edit)

        chips = QGridLayout()
        chips.setHorizontalSpacing(5)
        chips.setVerticalSpacing(5)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QPushButton] = {}
        for index, (key, label, tip) in enumerate(WORD_MODES):
            button = QPushButton(label, self.body)
            button.setCheckable(True)
            button.setToolTip(tip)
            button.setAccessibleName(f"{label} match")
            button.setAccessibleDescription(tip)
            button.setStyleSheet(_PANEL_CHIP)
            button.setMinimumHeight(28)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.group.addButton(button)
            self.buttons[key] = button
            last = index == len(WORD_MODES) - 1 and len(WORD_MODES) % 2 == 1
            chips.addWidget(button, index // 2, index % 2, 1, 2 if last else 1)
            qconnect(button.clicked, lambda _checked=False, k=key: self._pick_mode(k))
        body.addLayout(chips)

        self.hint = QLabel(self.body)
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: palette(placeholder-text);")
        body.addWidget(self.hint)

        form = QGridLayout()
        form.setHorizontalSpacing(6)
        form.setVerticalSpacing(5)
        form.addWidget(QLabel("In:"), 0, 0)
        self.deck_combo = _DeckCombo(self._fill_decks, self.body)
        self.deck_combo.setAccessibleName("Search in deck")
        self.deck_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.deck_combo.setMinimumContentsLength(8)
        self.deck_combo.setMaxVisibleItems(25)
        self.deck_combo.view().setMinimumWidth(320)
        form.addWidget(self.deck_combo, 0, 1)
        form.addWidget(QLabel("Cards:"), 1, 0)
        self.card_combo = QComboBox(self.body)
        self.card_combo.setAccessibleName("Card filter")
        self.card_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.card_combo.setMinimumContentsLength(8)
        for key, label, tip in QUICK_FILTERS:
            self.card_combo.addItem("Any card" if not key else label, key)
            self.card_combo.setItemData(self.card_combo.count() - 1, tip, Qt.ItemDataRole.ToolTipRole)
        form.addWidget(self.card_combo, 1, 1)
        form.setColumnStretch(1, 1)
        body.addLayout(form)

        self.status = QLabel(self.body)
        self.status.setWordWrap(True)
        self.status.setVisible(False)
        body.addWidget(self.status)

        self._wanted_deck = str(config.get("word_deck", ""))
        self._fill_decks()
        index = self.card_combo.findData(str(config.get("word_cards", "")))
        self.card_combo.setCurrentIndex(max(0, index))
        self.buttons[self._mode].setChecked(True)
        self._show_hint()
        qconnect(self.deck_combo.activated, lambda _i: self._changed_scope())
        qconnect(self.card_combo.activated, lambda _i: self._changed_scope())
        self.set_open(bool(config.get("word_panel_open", True)), save=False)

    # ----------------------------------------------------------------- state
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

    def _fill_decks(self) -> None:
        current = self.deck_combo.currentData()
        wanted = self._wanted_deck if current is None else str(current)
        self.deck_combo.blockSignals(True)
        self.deck_combo.clear()
        self.deck_combo.addItem("All decks", "")
        self.deck_combo.addItem("Current deck", "current")
        self.deck_combo.insertSeparator(self.deck_combo.count())
        for name in self._decks():
            parts = name.split("::")
            self.deck_combo.addItem("    " * (len(parts) - 1) + parts[-1], name)
            self.deck_combo.setItemData(
                self.deck_combo.count() - 1, name.replace("::", " › "), Qt.ItemDataRole.ToolTipRole
            )
        index = self.deck_combo.findData(wanted)
        self.deck_combo.setCurrentIndex(index if index >= 0 else 0)
        self.deck_combo.setToolTip(self.deck_combo.itemData(self.deck_combo.currentIndex(), Qt.ItemDataRole.ToolTipRole) or self.deck_combo.currentText())
        self.deck_combo.blockSignals(False)

    def _show_hint(self) -> None:
        for key, _label, tip in WORD_MODES:
            if key == self._mode:
                self.hint.setText(tip)

    def _pick_mode(self, key: str) -> None:
        self._mode = key
        self._show_hint()
        self._save({"word_mode": key})
        if self.edit.text().strip():
            self.search()

    def _changed_scope(self) -> None:
        deck = str(self.deck_combo.currentData() or "")
        self._wanted_deck = deck
        self.deck_combo.setToolTip(deck.replace("::", " › ") or self.deck_combo.currentText())
        self._save({"word_deck": deck, "word_cards": str(self.card_combo.currentData() or "")})
        if self.edit.text().strip():
            self.search()

    def current(self) -> WordSearch:
        return WordSearch(
            text=self.edit.text().strip(),
            mode=self._mode,
            deck=str(self.deck_combo.currentData() or ""),
            card_filter=str(self.card_combo.currentData() or ""),
        )

    def search(self) -> None:
        try:
            query = self._run(self.current())
        except Exception as error:
            self.status.setText(str(error))
            self.status.setStyleSheet("color: #d0453a;")
            self.status.setVisible(True)
            return
        self.status.setVisible(False)
        self.last_query = query


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
    # Fallback: a row under the Browser's own search box.
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
