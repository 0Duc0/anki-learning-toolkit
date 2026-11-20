"""Word search panel at the top of the Browser sidebar (4.0).

A search box and four small dropdown buttons (what to search, how it matches, which deck, which cards) –
the same kind of button as "Cards ▾" in the Browser toolbar. Results appear while you type; the deck
follows the deck the Browser shows unless you pick another one.
"""

from __future__ import annotations

from collections.abc import Callable

from aqt.qt import (
    QAction,
    QActionGroup,
    QCompleter,
    QGridLayout,
    QHBoxLayout,
    QKeySequence,
    QLabel,
    QLineEdit,
    QMenu,
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
KIND_WORD = "word"         # word fields with the chosen match
# key, button text, menu text
KINDS: tuple[tuple[str, str, str], ...] = (
    (WORD_AUTO, "Auto", "Auto – the word; for Latin text also the meaning"),
    (KIND_WORD, "Word", "Word only – Simplified, Traditional, Reading, Headword …"),
    (WORD_MEANING, "Meaning", "Meaning only – eat → 吃, 食べる, ăn"),
    (WORD_EVERYWHERE, "All fields", "All fields – also examples and long definitions"),
)
MATCHES: tuple[tuple[str, str, str], ...] = (
    (WORD_EXACT, "Exact", "Exact – exactly this word (你 → 你)"),
    (WORD_CONTAINS, "Contains", "Contains – 你 → 你, 你好, 你们 · cứ → cứ việc, not cứu"),
    (WORD_RELATED, "Related", "Related – shares a character or syllable (你好 → 好人)"),
)
HISTORY_SIZE = 12
LIVE_DELAY_MS = 450


def _last(deck: str) -> str:
    return deck.split("::")[-1] if deck else "All decks"


class _DropButton(QToolButton):
    """A button that opens a menu of choices, like the Browser's "Cards ▾"."""

    def __init__(self, parent: QWidget, name: str) -> None:
        super().__init__(parent)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(40)
        self.setAccessibleName(name)
        self.setStyleSheet("QToolButton{padding:3px 6px;} QToolButton::menu-indicator{image:none;width:0;}")
        self.setMenu(QMenu(self))
        self._full = ""

    def show_text(self, text: str) -> None:
        self._full = text
        room = max(30, self.width() - 26)
        self.setText(self.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, room) + " ▾")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._full:
            self.show_text(self._full)


class WordSearchPanel(QWidget):
    """Type → see results. Auto picks the right fields; the deck follows where you are."""

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
        keys = {k for k, _b, _m in KINDS}
        self._kind = str(config.get("word_kind") or WORD_AUTO)
        self._kind = self._kind if self._kind in keys else WORD_AUTO
        matches = {k for k, _b, _m in MATCHES}
        old_mode = str(config.get("word_mode") or "")
        self._match = str(config.get("word_match") or (old_mode if old_mode in matches else WORD_CONTAINS))
        self._match = self._match if self._match in matches else WORD_CONTAINS
        self._scope = str(config.get("word_scope", HERE))
        self._cards = str(config.get("word_cards", "") or "")
        self._live = bool(config.get("search_as_you_type", True))
        self._history: list[str] = [str(h) for h in config.get("word_history", []) if str(h).strip()][:HISTORY_SIZE]
        self.last_query = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 6, 8, 8)
        outer.setSpacing(5)

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
        body.setSpacing(5)
        outer.addWidget(self.body)

        self.edit = QLineEdit(self.body)
        self.edit.setClearButtonEnabled(True)
        self.edit.setPlaceholderText("Word, character or meaning")
        self.edit.setAccessibleName("Word to search for")
        self.edit.setToolTip("Results appear while you type · Enter searches at once · Esc clears")
        self._completer_model = QStringListModel(self._history, self)
        completer = QCompleter(self._completer_model, self.edit)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
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

        self.kind_button = _DropButton(self.body, "What to search")
        self.match_button = _DropButton(self.body, "How the word matches")
        self.deck_button = _DropButton(self.body, "Deck")
        self.cards_button = _DropButton(self.body, "Which cards")
        for left, right, ratio in ((self.kind_button, self.match_button, (1, 1)),
                                   (self.deck_button, self.cards_button, (3, 2))):
            row = QHBoxLayout()
            row.setSpacing(4)
            row.addWidget(left, ratio[0])
            row.addWidget(right, ratio[1])
            body.addLayout(row)
        self._fill_choice_menu(self.kind_button, KINDS, lambda: self._kind, self.set_kind)
        self._fill_choice_menu(self.match_button, MATCHES, lambda: self._match, self.set_match)
        self._card_choices = tuple(
            (key, "Any card" if not key else label, "Any card" if not key else f"{label} – {tip}")
            for key, label, tip in QUICK_FILTERS
        )
        self._fill_choice_menu(self.cards_button, self._card_choices, lambda: self._cards, self.set_cards)
        qconnect(self.deck_button.menu().aboutToShow, self._fill_deck_menu)

        self.summary = QLabel(self.body)
        self.summary.setWordWrap(True)
        body.addWidget(self.summary)
        self.status = QLabel(self.body)          # errors only
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #e5534b;")
        self.status.setVisible(False)
        body.addWidget(self.status)

        self._refresh_buttons()
        self._describe()
        self.set_open(bool(config.get("word_panel_open", True)), save=False)

    # ------------------------------------------------------------- menus
    def _fill_choice_menu(self, button: _DropButton, choices, current: Callable[[], str], pick: Callable[[str], None]) -> None:
        menu = button.menu()

        def fill() -> None:
            menu.clear()
            group = QActionGroup(menu)
            for key, _text, long in choices:
                action = menu.addAction(long)
                action.setCheckable(True)
                action.setChecked(key == current())
                group.addAction(action)
                qconnect(action.triggered, lambda _c=False, k=key: pick(k))

        qconnect(menu.aboutToShow, fill)

    def _fill_deck_menu(self) -> None:
        menu = self.deck_button.menu()
        menu.clear()
        here = self._here()
        group = QActionGroup(menu)

        def add(target: QMenu, text: str, scope: str) -> None:
            action = target.addAction(text)
            action.setCheckable(True)
            action.setChecked(scope == self._scope)
            group.addAction(action)
            qconnect(action.triggered, lambda _c=False, s=scope: self.set_scope(s))

        add(menu, f"Here – {here.replace('::', ' › ') if here else 'all decks'} (follows the Browser)", HERE)
        add(menu, "All decks", "")
        menu.addSeparator()
        children: dict[str, list[str]] = {}
        for name in self._decks():
            parent = name.rsplit("::", 1)[0] if "::" in name else ""
            children.setdefault(parent, []).append(name)

        def build(target: QMenu, parent: str) -> None:
            for name in children.get(parent, []):
                label = name.split("::")[-1]
                if name in children:
                    sub = target.addMenu(label)
                    add(sub, f"All of {label}", name)
                    sub.addSeparator()
                    build(sub, name)
                else:
                    add(target, label, name)

        build(menu, "")

    def _refresh_buttons(self) -> None:
        self.kind_button.show_text({k: t for k, t, _l in KINDS}[self._kind])
        self.kind_button.setToolTip({k: m for k, _t, m in KINDS}[self._kind])
        self.match_button.show_text({k: t for k, t, _l in MATCHES}[self._match])
        self.match_button.setToolTip({k: m for k, _t, m in MATCHES}[self._match])
        self.match_button.setEnabled(self._kind in (WORD_AUTO, KIND_WORD))
        here = self._here()
        if self._scope == HERE:
            self.deck_button.show_text(_last(here))
            self.deck_button.setToolTip("The deck the Browser shows – click a deck on the left to change it\n"
                                        + (here.replace("::", " › ") if here else "Now: all decks"))
        else:
            self.deck_button.show_text(_last(self._scope))
            self.deck_button.setToolTip(self._scope.replace("::", " › ") if self._scope else "All decks")
        self.cards_button.show_text({k: t for k, t, _l in self._card_choices}.get(self._cards, "Any card"))

    # ------------------------------------------------------------- state
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
        return self._scope

    def deck(self) -> str:
        """The deck the next search is limited to ("" = all decks)."""
        return self._here() if self._scope == HERE else self._scope

    def location_changed(self) -> None:
        """The Browser shows another deck: relabel and, if a word is typed, search it there."""
        self._refresh_buttons()
        if self._scope == HERE and self.edit.text().strip():
            self.search(remember=False)
        else:
            self._describe()

    def set_kind(self, key: str) -> None:
        self._kind = key
        self._save({"word_kind": key})
        self._refresh_buttons()
        self._rerun()

    def set_match(self, key: str) -> None:
        self._match = key
        self._save({"word_match": key})
        self._refresh_buttons()
        self._rerun()

    def set_scope(self, scope: str) -> None:
        self._scope = scope
        self._save({"word_scope": scope})
        self._refresh_buttons()
        self._rerun(show_deck=True)

    def set_cards(self, key: str) -> None:
        self._cards = key
        self._save({"word_cards": key})
        self._refresh_buttons()
        self._rerun(show_deck=True)

    def _rerun(self, show_deck: bool = False) -> None:
        if self.edit.text().strip():
            self.search()
        elif show_deck:
            self.clear(keep_text=True)
        else:
            self._describe()

    # ------------------------------------------------------------- search
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
        return WordSearch(text=self.edit.text().strip(), mode=mode, deck=self.deck(),
                          card_filter=self._cards, match=self._match)

    def search(self, remember: bool = True) -> None:
        self._timer.stop()
        spec = self.current()
        if not spec.text:
            self.clear(keep_text=True)
            return
        try:
            query = self._run(spec)
        except Exception as error:
            self.status.setText(str(error))
            self.status.setVisible(True)
            return
        self.status.setVisible(False)
        self.last_query = query
        if remember:
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
        self._describe(found=self._count() if self._show_scope is not None else None)

    def _remember(self, text: str) -> None:
        self._history = [text] + [h for h in self._history if h.casefold() != text.casefold()]
        self._history = self._history[:HISTORY_SIZE]
        self._completer_model.setStringList(self._history)
        self._save({"word_history": list(self._history)})

    def _describe(self, found: int | None = None) -> None:
        spec = self.current()
        where = _last(spec.deck)
        count = "" if found is None else f"{found:,} note{'s' if found != 1 else ''} · "
        if not spec.text:
            self.summary.setText(f"{count}{where}")
        else:
            if self._kind == WORD_AUTO:
                what = "word" if auto_targets(spec.text) == "word" else "word or meaning"
            else:
                what = {KIND_WORD: "word", WORD_MEANING: "meaning", WORD_EVERYWHERE: "any field"}[self._kind]
            self.summary.setText(f"{count}{what} · {where}")
        self.summary.setToolTip(spec.deck.replace("::", " › ") if spec.deck else "All decks")


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
