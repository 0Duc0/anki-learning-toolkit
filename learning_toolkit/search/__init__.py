"""Friendly, read-only search builder for Anki's Browser."""

from __future__ import annotations

from anki.utils import strip_html
from aqt import gui_hooks, mw
from aqt.browser import Browser
from aqt.operations import QueryOp
from aqt.qt import (
    QAction,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QEvent,
    QFontMetrics,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QKeySequence,
    QLineEdit,
    QMenu,
    QObject,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
    Qt,
    qconnect,
    sip,
)
from aqt.utils import showWarning

from .core import (
    DEFAULT_MEANING_FIELDS,
    DEFAULT_WORD_FIELDS,
    FIELD_MEANING,
    FIELD_WORD,
    MATCH_CONTAINS,
    MATCH_CONTAINS_WORD,
    MATCH_RELATED,
    WORD_CONTAINS,

    WORD_RELATED,
    WordSearch,
    build_word_query,
    deck_from_search,
    merged_field_list,
    pick_fields,
    recommended_fields,
    MATCH_EMPTY,
    MATCH_ENDS,
    MATCH_EXACT,
    MATCH_NOT_EMPTY,
    MATCH_STARTS,
    QUICK_FILTERS,
    QUICK_LABELS,
    SearchMetadata,
    SearchSpec,
    build_query,
    build_quick_query,
    collect_metadata,
    rewrite_search_bar,
)
from .panel import WordSearchPanel, focus_action, install_panel
from ..common.config import SectionConfig

_CFG = SectionConfig('search')


DEFAULTS = {
    "last_field": "",
    "last_match": MATCH_EXACT,
    "shortcut": "",
    "quick_shortcut": "",
    "quick_combine": True,
    "last_field_choice": FIELD_WORD,
    "word_mode": WORD_CONTAINS,
    "word_deck": "",
    "word_cards": "",
    "word_panel_open": True,
    "word_search_shortcut": "Ctrl+Shift+W",
    "word_fields": list(DEFAULT_WORD_FIELDS),
    "meaning_fields": list(DEFAULT_MEANING_FIELDS),
    "search_bar_field": "",
    "remember_look_in": True,
}
_collection_epoch = 0
_CHIP_STYLE = (
    "QPushButton{padding:5px 12px;border:1px solid palette(mid);border-radius:7px;}"
    "QPushButton:hover{border-color:palette(highlight);}"
    "QPushButton:checked{background:palette(highlight);color:palette(highlighted-text);"
    "font-weight:bold;}"
    "QPushButton:focus{border:2px solid palette(highlight);}"
)


def _invalidate_pending(*_args) -> None:
    global _collection_epoch
    _collection_epoch += 1


def _config() -> dict:
    config = dict(DEFAULTS)
    try:
        raw = _CFG.getConfig()
        if isinstance(raw, dict):
            config.update(raw)
    except Exception:
        pass
    for key, default in DEFAULTS.items():
        if not isinstance(config.get(key), type(default)):
            config[key] = default
        elif isinstance(default, list):
            cleaned = [str(item).strip() for item in config[key] if str(item).strip()]
            config[key] = cleaned or list(default)
    return config


def _save_config(changes: dict) -> None:
    config = _config()
    config.update(changes)
    try:
        _CFG.writeConfig(__name__, config)
    except Exception:
        pass


def _browser_deck(browser) -> str:
    """The deck the Browser's current search is limited to ("" if none)."""
    current = getattr(browser, "current_search", None)
    try:
        return deck_from_search(str(current()) if callable(current) else "")
    except Exception:
        return ""


def _deck_recommendations(col, deck: str) -> tuple[str, ...]:
    return _deck_recommendations_with_sort(col, deck)[0]


def _deck_recommendations_with_sort(col, deck: str) -> tuple[tuple[str, ...], set]:
    """Sort field(s) and word fields of the note types used in ``deck`` and its subdecks (cheap query)."""
    if col is None or not deck:
        return (), set()
    try:
        did = col.decks.id_for_name(deck)
        if not did:
            return (), set()
        ids = list(col.decks.deck_and_child_ids(did))
        mids = col.db.list(f"select distinct n.mid from cards c join notes n on n.id = c.nid "
                           f"where c.did in ({','.join(str(int(i)) for i in ids)})")
        models = [col.models.get(m) for m in mids]
        meta = SearchMetadata(
            fields=(), decks=(), note_types=(), tags=(),
            fields_by_type=tuple((m["name"], tuple(f["name"] for f in m["flds"])) for m in models if m),
            types_by_deck=((deck, tuple(m["name"] for m in models if m)),),
            sort_by_type=tuple((m["name"], m["flds"][int(m.get("sortf", 0) or 0)]["name"])
                               for m in models if m and m["flds"]),
        )
        return recommended_fields(meta, deck), {name for _t, name in meta.sort_by_type}
    except Exception:
        return (), set()


def _word_fields() -> list[str]:
    return merged_field_list(_config()["word_fields"], DEFAULT_WORD_FIELDS)


def _meaning_fields() -> list[str]:
    return merged_field_list(_config()["meaning_fields"], DEFAULT_MEANING_FIELDS)


def _save_preferences(field_name: str, match: str) -> None:
    config = _config()
    config["last_field_choice"] = field_name
    config["last_match"] = match
    try:
        _CFG.writeConfig(__name__, config)
    except Exception:
        # A closing profile must never turn a harmless search into an Anki error.
        pass


def _live_collection(browser: Browser):
    col = getattr(mw, "col", None)
    if (
        col is None
        or getattr(browser, "col", None) is not col
        or getattr(col, "db", None) is None
    ):
        return None
    return col


def _browser_alive(browser: Browser, expected_col=None, epoch=None) -> bool:
    try:
        col = _live_collection(browser)
        return (
            not sip.isdeleted(browser)
            and col is not None
            and (expected_col is None or col is expected_col)
            and (epoch is None or epoch == _collection_epoch)
        )
    except (AttributeError, RuntimeError):
        return False


def _run_query(operation: QueryOp, label: str | None = None) -> None:
    progress = getattr(operation, "with_progress", None)
    if label and callable(progress):
        operation = progress(label)
    operation.run_in_background()


def _all_fields(col) -> tuple[str, ...]:
    names: dict[str, str] = {}
    try:
        notetypes = col.models.all()
    except Exception:
        notetypes = []
    for notetype in notetypes:
        try:
            fields = col.models.field_names(notetype)
        except Exception:
            fields = [field.get("name", "") for field in notetype.get("flds", [])]
        for field in fields:
            value = str(field).strip()
            if value:
                names.setdefault(value.casefold(), value)
    return tuple(sorted(names.values(), key=str.casefold))


def _selected_sort_value(browser: Browser) -> tuple[str, str] | None:
    """Return the single selected note's sort field and plain-text value."""
    col = _live_collection(browser)
    if col is None:
        return None
    try:
        note_ids = tuple(dict.fromkeys(int(nid) for nid in browser.selected_notes()))
        if len(note_ids) != 1:
            return None
        note = col.get_note(note_ids[0])
        notetype = note.note_type()
        field_names = list(note.keys())
        for name in pick_fields(field_names, _word_fields()):
            value = strip_html(str(note[name])).strip()
            if value:
                return name, value
        index = int(notetype.get("sortf", 0))
        if index < 0 or index >= len(field_names) or index >= len(note.fields):
            return None
        field_name = str(field_names[index])
        value = strip_html(str(note.fields[index])).strip()
        if not field_name or not value:
            return None
        return field_name, value
    except Exception:
        return None


def _short(text: str, maximum: int = 28) -> str:
    single_line = " ".join(str(text).split())
    if len(single_line) <= maximum:
        return single_line
    return single_line[: maximum - 1] + "…"


def _perform_search(browser: Browser, query: str) -> None:
    """Save the editor, then run a normal native Browser search."""
    if not _browser_alive(browser):
        return
    origin_col = _live_collection(browser)
    epoch = _collection_epoch

    def after_saved() -> None:
        if not _browser_alive(browser, origin_col, epoch):
            return
        try:
            search_for = getattr(browser, "search_for", None)
            if callable(search_for):
                # build_query() already returns a parser-safe query. Running it
                # through build_search_string() again would double-escape regex
                # literals such as '+' or '[' on Anki 25.09.x.
                search_for(query)
                update_history = getattr(browser, "update_history", None)
                if callable(update_history):
                    update_history()
                return

            # Conservative fallback for a future Browser API rename.
            search_box = getattr(getattr(browser, "form", None), "searchEdit", None)
            activated = getattr(browser, "onSearchActivated", None)
            if search_box is None or not callable(activated):
                raise RuntimeError("This Anki version does not expose Browser search.")
            search_box.setEditText(query)
            activated()
        except Exception as error:
            showWarning(f"The search could not be started.\n\n{error}", parent=mw)

    editor = getattr(browser, "editor", None)
    save_then = getattr(editor, "call_after_note_saved", None)
    try:
        if callable(save_then):
            save_then(after_saved)
        elif editor is not None:
            raise RuntimeError(
                "This Anki version cannot safely save the editor before searching."
            )
        else:
            after_saved()
    except Exception as error:
        if _browser_alive(browser, origin_col, epoch):
            showWarning(f"The search could not be started.\n\n{error}", parent=mw)


class _HeightGuard(QObject):
    """Keep the dialog big enough for its content, never taller than the screen.

    Qt does not always honour height-for-width for a top-level dialog, so with
    larger system fonts controls got squeezed together.  The form sits in a
    scroll area: the dialog grows to fit it (up to 90% of the screen height)
    and scrolls beyond that, so the buttons always stay reachable.
    """

    _EVENTS = (QEvent.Type.Show, QEvent.Type.Resize, QEvent.Type.LayoutRequest)

    def __init__(self, dialog: QDialog, content: QWidget, footer: QWidget) -> None:
        super().__init__(dialog)
        self._dialog = dialog
        self._content = content
        self._footer = footer
        self._busy = False
        dialog.installEventFilter(self)
        content.installEventFilter(self)

    def fit(self) -> None:
        outer = self._dialog.layout()
        inner = self._content.layout()
        if self._busy or outer is None or inner is None:
            return
        self._busy = True
        try:
            margins = outer.contentsMargins()
            extra_w = margins.left() + margins.right() + 24  # scroll bar room
            min_width = inner.totalMinimumSize().width() + extra_w
            if min_width > self._dialog.minimumWidth():
                self._dialog.setMinimumWidth(min_width)
            if self._dialog.width() < min_width:
                self._dialog.resize(min_width, self._dialog.height())
            inner_width = max(1, self._dialog.width() - extra_w)
            form_height = max(
                inner.totalMinimumSize().height(), inner.totalHeightForWidth(inner_width)
            )
            needed = (
                margins.top()
                + margins.bottom()
                + form_height
                + outer.spacing()
                + self._footer.sizeHint().height()
            )
            screen = self._dialog.screen()
            if screen is not None:
                needed = min(needed, int(screen.availableGeometry().height() * 0.9))
            if needed > 0 and self._dialog.minimumHeight() != needed:
                self._dialog.setMinimumHeight(needed)
            if self._dialog.height() < needed:
                self._dialog.resize(self._dialog.width(), needed)
        finally:
            self._busy = False

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 (Qt API)
        if watched in (self._dialog, self._content) and event.type() in self._EVENTS:
            self.fit()
        return False


class SearchAssistantDialog(QDialog):
    def __init__(
        self,
        browser: Browser,
        metadata: SearchMetadata,
        *,
        initial_field: str = "",
        initial_text: str = "",
        initial_match: str | None = None,
    ) -> None:
        super().__init__(browser)
        self.browser = browser
        col = _live_collection(browser)
        if col is None:
            raise RuntimeError("Open a normal Anki profile before searching.")
        self.col = col
        self.fields = metadata.fields
        self.query = ""

        self.setWindowTitle("Search Assistant")
        self.setMinimumWidth(650)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(11)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._content = QWidget()
        scroll.setWidget(self._content)
        outer.addWidget(scroll, 1)
        root = QVBoxLayout(self._content)
        root.setContentsMargins(0, 0, 8, 0)
        root.setSpacing(11)

        heading = QLabel("Find cards and notes without remembering commands")
        heading_font = heading.font()
        heading_font.setBold(True)
        heading_font.setPointSizeF(max(heading_font.pointSizeF(), 13.0) + 3.0)
        heading.setFont(heading_font)
        root.addWidget(heading)

        intro = QLabel(
            "Pick the decks first, then where the text should be found. "
            "“The word itself” ignores examples and long definitions, so unrelated "
            "notes stay out."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        show_label = QLabel("Show which cards?")
        show_font = show_label.font()
        show_font.setBold(True)
        show_label.setFont(show_font)
        root.addWidget(show_label)
        self.quick_group = QButtonGroup(self)
        self.quick_group.setExclusive(True)
        self.quick_buttons: dict[str, QPushButton] = {}
        chips = QGridLayout()
        chips.setHorizontalSpacing(7)
        chips.setVerticalSpacing(7)
        for index, (key, label, tip) in enumerate(QUICK_FILTERS):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setToolTip(tip)
            button.setAccessibleName(f"Show {label} cards")
            button.setAccessibleDescription(tip)
            button.setMinimumHeight(32)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(_CHIP_STYLE)
            bold = button.font()
            bold.setBold(True)
            button.setMinimumWidth(QFontMetrics(bold).horizontalAdvance("✓ " + label) + 30)
            self.quick_group.addButton(button)
            self.quick_buttons[key] = button
            chips.addWidget(button, index // 5, index % 5)
            chips.setColumnStretch(index % 5, 1)
            qconnect(button.toggled, lambda _on, b=button: self._chip_text(b))
        self.quick_buttons[""].setChecked(True)
        self._chip_text(self.quick_buttons[""])
        root.addLayout(chips)

        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(9)
        root.addLayout(form)

        self.find_edit = QLineEdit(initial_text)
        self.find_edit.setClearButtonEnabled(True)
        self.find_edit.setPlaceholderText(
            "Character, word, phrase… (optional when a card filter is chosen)"
        )
        self.find_edit.setAccessibleName("Text to find")
        form.addRow("Find:", self.find_edit)

        self.metadata = metadata
        self.deck_combo = QComboBox()
        self.deck_combo.addItem("All decks", ("all", ""))
        self.deck_combo.addItem("Current deck", ("current", ""))
        if metadata.decks:
            self.deck_combo.insertSeparator(self.deck_combo.count())
        for deck in metadata.decks:
            parts = deck.split("::")
            self.deck_combo.addItem("    " * (len(parts) - 1) + parts[-1], ("specific", deck))
            self.deck_combo.setItemData(
                self.deck_combo.count() - 1, deck.replace("::", " › "), Qt.ItemDataRole.ToolTipRole
            )
        self.deck_combo.setMaxVisibleItems(25)
        self.deck_combo.setAccessibleName("Search in deck")
        form.addRow("Search in:", self.deck_combo)

        self.field_combo = QComboBox()
        self.field_combo.setMaxVisibleItems(25)
        self.field_combo.setAccessibleName("Look in field")
        self.field_combo.setToolTip(
            "Only fields of note types in the chosen decks are listed"
        )
        self._browser_deck = _browser_deck(browser)
        look_row = QWidget()
        look_layout = QHBoxLayout(look_row)
        look_layout.setContentsMargins(0, 0, 0, 0)
        look_layout.addWidget(self.field_combo, 1)
        self.remember_look_in = QCheckBox("Remember my choice")
        self.remember_look_in.setToolTip(
            "On: the dialog opens with the field you used last time.\n"
            "Off: it opens with the recommended field of the deck you're in (its sort field),\n"
            "or \"The word itself\" outside a deck."
        )
        self.remember_look_in.setChecked(bool(_config().get("remember_look_in", True)))
        look_layout.addWidget(self.remember_look_in)
        form.addRow("Look in:", look_row)
        self._wanted_field = ""
        self._fill_fields()

        self.match_combo = QComboBox()
        self.match_combo.addItem("Exact value (recommended)", MATCH_EXACT)
        self.match_combo.addItem("Contains the word (你 → 你好 · cứ → cứ việc)", MATCH_CONTAINS_WORD)
        self.match_combo.addItem("Shares a character or syllable (你好 → 好人)", MATCH_RELATED)
        self.match_combo.addItem("Contains text (any part)", MATCH_CONTAINS)
        self.match_combo.addItem("Starts with", MATCH_STARTS)
        self.match_combo.addItem("Ends with", MATCH_ENDS)
        self.match_combo.addItem("Is empty", MATCH_EMPTY)
        self.match_combo.addItem("Is not empty", MATCH_NOT_EMPTY)
        form.addRow("Match:", self.match_combo)



        self.optional = QGroupBox("Optional filters")
        self.optional.setCheckable(True)
        self.optional.setChecked(False)
        optional_form = QFormLayout(self.optional)
        optional_form.setHorizontalSpacing(14)
        optional_form.setVerticalSpacing(8)
        root.addWidget(self.optional)

        self.note_combo = QComboBox()
        self.note_combo.addItem("Any note type", "")
        for name in metadata.note_types:
            self.note_combo.addItem(name, name)
        optional_form.addRow("Note type:", self.note_combo)

        tag_row = QWidget(self.optional)
        tag_layout = QHBoxLayout(tag_row)
        tag_layout.setContentsMargins(0, 0, 0, 0)
        tag_layout.setSpacing(7)
        self.tag_mode = QComboBox()
        self.tag_mode.addItem("Any tag", "any")
        self.tag_mode.addItem("Has tag", "include")
        self.tag_mode.addItem("Does not have tag", "exclude")
        self.tag_combo = QComboBox()
        self.tag_combo.setEditable(True)
        self.tag_combo.addItem("")
        self.tag_combo.addItems(list(metadata.tags))
        tag_layout.addWidget(self.tag_mode)
        tag_layout.addWidget(self.tag_combo, 1)
        optional_form.addRow("Tag:", tag_row)

        self.combine_current = QCheckBox("Also narrow the current Browser search")
        current_query = self._current_query()
        self.combine_current.setEnabled(bool(current_query))
        self.combine_current.setToolTip(
            "Keeps the currently visible Browser search and adds these conditions."
        )
        optional_form.addRow("Combine:", self.combine_current)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)

        technical_label = QLabel(
            "Anki query (for reference only — you do not need to memorize it):"
        )
        technical_label.setWordWrap(True)
        root.addWidget(technical_label)
        technical_row = QHBoxLayout()
        self.query_preview = QLineEdit()
        self.query_preview.setReadOnly(True)
        copy_button = QPushButton("Copy")
        qconnect(copy_button.clicked, self._copy_query)
        technical_row.addWidget(self.query_preview, 1)
        technical_row.addWidget(copy_button)
        root.addLayout(technical_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.search_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.search_button.setText("Search")
        self.search_button.setDefault(True)
        clear_button = buttons.addButton("Clear", QDialogButtonBox.ButtonRole.ResetRole)
        qconnect(self.search_button.clicked, self._accept_search)
        qconnect(buttons.rejected, self.reject)
        qconnect(clear_button.clicked, self._clear)
        outer.addWidget(buttons)

        config = _config()
        if initial_field:
            wanted_field = initial_field
        elif self.remember_look_in.isChecked():
            wanted_field = str(config.get("last_field_choice", FIELD_WORD))
        else:
            wanted_field = (getattr(self, "_recommended", ()) or (FIELD_WORD,))[0]
        field_index = self.field_combo.findData(wanted_field)
        self.field_combo.setCurrentIndex(field_index if field_index >= 0 else 0)
        qconnect(self.deck_combo.currentIndexChanged, lambda _i: self._fill_fields())
        wanted_match = initial_match or str(config.get("last_match", MATCH_EXACT))
        match_index = self.match_combo.findData(wanted_match)
        if match_index >= 0:
            self.match_combo.setCurrentIndex(match_index)

        for signal in (
            self.find_edit.textChanged,
            self.field_combo.currentIndexChanged,
            self.match_combo.currentIndexChanged,
            self.deck_combo.currentIndexChanged,
            self.optional.toggled,
            self.note_combo.currentIndexChanged,
            self.quick_group.buttonToggled,
            self.tag_mode.currentIndexChanged,
            self.tag_combo.currentTextChanged,
            self.combine_current.toggled,
        ):
            signal.connect(self._refresh_preview)

        self._refresh_preview()
        self._height_guard = _HeightGuard(self, self._content, buttons)
        self._height_guard.fit()
        self.find_edit.setFocus()
        if initial_text:
            self.find_edit.selectAll()

    def _scope_deck(self) -> str:
        scope = self.deck_combo.currentData() or ("all", "")
        if scope[0] == "specific":
            return str(scope[1])
        if scope[0] == "current":
            try:
                return str(self.col.decks.current()["name"])
            except Exception:
                return ""
        return ""

    def _fill_fields(self) -> None:
        """Special choices first, then the fields of note types in the chosen decks."""
        current = self.field_combo.currentData()
        wanted = str(current) if current is not None else self._wanted_field
        types = self.metadata.types_in_scope(self._scope_deck())
        fields_by_type = dict(self.metadata.fields_by_type)
        in_scope = [f for t in types for f in fields_by_type.get(t, ())]
        word = pick_fields(in_scope, _word_fields()) or pick_fields(self.fields, _word_fields())
        meaning = pick_fields(in_scope, _meaning_fields()) or pick_fields(self.fields, _meaning_fields())
        combo = self.field_combo
        combo.blockSignals(True)
        combo.clear()
        rec_deck = self._scope_deck() or getattr(self, "_browser_deck", "")
        self._recommended, sort_fields = _deck_recommendations_with_sort(self.col, rec_deck)
        for name in self._recommended:
            combo.addItem(f"★ {name}" + ("  (sort field)" if name in sort_fields else ""), name)
            combo.setItemData(combo.count() - 1, f"Recommended for {rec_deck}", Qt.ItemDataRole.ToolTipRole)
        if self._recommended:
            combo.insertSeparator(combo.count())
        combo.addItem("The word itself – " + ", ".join(word[:4]) + (" …" if len(word) > 4 else ""), FIELD_WORD)
        combo.setItemData(combo.count() - 1, "Searches only: " + ", ".join(word), Qt.ItemDataRole.ToolTipRole)
        combo.addItem("Meaning / translation – " + ", ".join(meaning[:3]) + (" …" if len(meaning) > 3 else ""), FIELD_MEANING)
        combo.setItemData(combo.count() - 1, "Searches only: " + ", ".join(meaning), Qt.ItemDataRole.ToolTipRole)
        combo.addItem("All fields (also examples and definitions – may find unrelated notes)", "")
        for notetype in types:
            names = fields_by_type.get(notetype, ())
            if not names:
                continue
            combo.insertSeparator(combo.count())
            combo.addItem(notetype, None)
            header = combo.model().item(combo.count() - 1)
            if header is not None:
                header.setEnabled(False)
                font = header.font()
                font.setBold(True)
                header.setFont(font)
            for name in names:
                combo.addItem("    " + name, name)
        index = combo.findData(wanted) if wanted else combo.findData("")
        if wanted == "" and current is None:
            index = combo.findData(FIELD_WORD)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(False)
        self._wanted_field = str(combo.currentData() or "")
        self._scoped_word = list(word)
        self._scoped_meaning = list(meaning)
        if hasattr(self, "query_preview"):
            self._refresh_preview()

    def _quick_key(self) -> str:
        for key, button in self.quick_buttons.items():
            if button.isChecked():
                return key
        return ""

    @staticmethod
    def _chip_text(button: QPushButton) -> None:
        """A tick mark makes the chosen filter obvious without relying on colour."""
        base = button.text().removeprefix("✓ ")
        button.setText(f"✓ {base}" if button.isChecked() else base)

    def _current_query(self) -> str:
        current = getattr(self.browser, "current_search", None)
        if not callable(current):
            return ""
        try:
            return str(current()).strip()
        except Exception:
            return ""

    def _spec(self) -> SearchSpec:
        scope_data = self.deck_combo.currentData() or ("all", "")
        optional = self.optional.isChecked()
        return SearchSpec(
            text=self.find_edit.text(),
            field_name=str(self.field_combo.currentData() or ""),
            match=str(self.match_combo.currentData() or MATCH_EXACT),
            deck_scope=str(scope_data[0]),
            deck_name=str(scope_data[1]),
            note_type=str(self.note_combo.currentData() or "") if optional else "",
            tag_mode=str(self.tag_mode.currentData() or "any") if optional else "any",
            tag_name=self.tag_combo.currentText().strip() if optional else "",
            card_state=self._quick_key(),
            current_query=self._current_query(),
            combine_current=optional and self.combine_current.isChecked(),
        )

    def _friendly_summary(self, spec: SearchSpec) -> str:
        mode = {
            MATCH_EXACT: "Exact value",
            MATCH_CONTAINS_WORD: "Contains the word",
            MATCH_RELATED: "Shares a character or syllable",
            MATCH_CONTAINS: "Contains",
            MATCH_STARTS: "Starts with",
            MATCH_ENDS: "Ends with",
            MATCH_EMPTY: "Empty field",
            MATCH_NOT_EMPTY: "Non-empty field",
        }.get(spec.match, "Search")
        where = {FIELD_WORD: "the word itself", FIELD_MEANING: "the meaning", "": "all fields"}.get(
            spec.field_name, spec.field_name
        )
        cards = QUICK_LABELS.get(spec.card_state, "") if spec.card_state else ""
        if not spec.text and spec.match not in {MATCH_EMPTY, MATCH_NOT_EMPTY}:
            mode = "All cards" if not cards else f"{cards} cards"
            where = ""
        elif cards:
            mode = f"{cards} cards · {mode.lower()}"
        if spec.deck_scope == "current":
            scope = "current deck"
        elif spec.deck_scope == "specific":
            scope = spec.deck_name.replace("::", " › ")
        else:
            scope = "all decks"
        if not where:
            return f"{mode}  ·  {scope}"
        return f"{mode} in {where}  ·  {scope}"

    def _refresh_preview(self, *_args) -> None:
        match = str(self.match_combo.currentData() or MATCH_EXACT)
        needs_text = match not in {MATCH_EMPTY, MATCH_NOT_EMPTY}
        self.find_edit.setEnabled(needs_text)
        try:
            spec = self._spec()
            self.query = build_query(
                self.col,
                spec,
                self.fields,
                getattr(self, "_scoped_word", None) or _word_fields(),
                getattr(self, "_scoped_meaning", None) or _meaning_fields(),
            )
        except Exception as error:
            self.query = ""
            self.query_preview.setText(str(error))
            self.query_preview.setStyleSheet("color: palette(mid);")
            self.summary.setText("Choose the search conditions above.")
            self.search_button.setEnabled(False)
            return
        self.query_preview.setStyleSheet("")
        self.query_preview.setText(self.query)
        self.summary.setText(self._friendly_summary(spec))
        self.search_button.setEnabled(True)

    def _accept_search(self) -> None:
        self._refresh_preview()
        if not self.query:
            return
        remember = self.remember_look_in.isChecked()
        _save_preferences(
            str(self.field_combo.currentData() or "") if remember
            else str(_config().get("last_field_choice", FIELD_WORD)),
            str(self.match_combo.currentData() or MATCH_EXACT),
        )
        _save_config({"remember_look_in": remember})
        self.accept()
        _perform_search(self.browser, self.query)

    def _clear(self) -> None:
        self.find_edit.clear()
        self.deck_combo.setCurrentIndex(0)
        self.field_combo.setCurrentIndex(max(0, self.field_combo.findData(FIELD_WORD)))
        self.match_combo.setCurrentIndex(0)
        self.optional.setChecked(False)
        self.note_combo.setCurrentIndex(0)
        self.quick_buttons[""].setChecked(True)
        self.tag_mode.setCurrentIndex(0)
        self.tag_combo.setCurrentIndex(0)
        self.combine_current.setChecked(False)
        self.find_edit.setFocus()

    def _copy_query(self) -> None:
        if self.query:
            mw.app.clipboard().setText(self.query)


def _open_assistant(
    browser: Browser,
    *,
    initial_field: str = "",
    initial_text: str = "",
    initial_match: str | None = None,
) -> None:
    if not _browser_alive(browser):
        showWarning("Open a normal Anki profile before searching.", parent=mw)
        return
    existing = getattr(browser, "_simple_search_assistant_dialog", None)
    if existing is not None:
        try:
            existing.raise_()
            existing.activateWindow()
            return
        except RuntimeError:
            browser._simple_search_assistant_dialog = None
    if getattr(browser, "_simple_search_assistant_loading", False):
        return
    origin_col = _live_collection(browser)
    epoch = _collection_epoch

    if not initial_text:
        current = getattr(browser, "current_search", None)
        try:
            visible_query = str(current()).strip() if callable(current) else ""
        except Exception:
            visible_query = ""
        if (
            visible_query
            and ":" not in visible_query
            and " OR " not in visible_query.upper()
            and not visible_query.startswith("-")
            and not any(character in visible_query for character in "()")
        ):
            if len(visible_query) >= 2 and visible_query[0] == visible_query[-1] == '"':
                visible_query = visible_query[1:-1]
            initial_text = visible_query

    def ready(metadata: SearchMetadata) -> None:
        browser._simple_search_assistant_loading = False
        if not _browser_alive(browser, origin_col, epoch):
            return
        try:
            dialog = SearchAssistantDialog(
                browser,
                metadata,
                initial_field=initial_field,
                initial_text=initial_text,
                initial_match=initial_match,
            )
            browser._simple_search_assistant_dialog = dialog
            dialog.exec()
            browser._simple_search_assistant_dialog = None
        except Exception as error:
            showWarning(f"Search Assistant could not open.\n\n{error}", parent=mw)
        finally:
            browser._simple_search_assistant_dialog = None

    def failed(error: Exception) -> None:
        browser._simple_search_assistant_loading = False
        if _browser_alive(browser, origin_col, epoch):
            showWarning(
                f"Search Assistant could not read the collection.\n\n{error}", parent=mw
            )

    def read_metadata(col):
        if col is not origin_col or epoch != _collection_epoch:
            raise RuntimeError("The collection changed while preparing the search.")
        return collect_metadata(col)

    browser._simple_search_assistant_loading = True
    try:
        _run_query(
            QueryOp(parent=mw, op=read_metadata, success=ready).failure(failed),
            "Preparing Search Assistant…",
        )
    except Exception as error:
        failed(error)


def _exact_selected(browser: Browser, field_name: str, value: str) -> None:
    col = _live_collection(browser)
    if col is None:
        showWarning("The Anki collection is currently unavailable.", parent=mw)
        return
    try:
        query = build_query(
            col,
            SearchSpec(text=value, field_name=field_name, match=MATCH_EXACT),
            _all_fields(col),
            _word_fields(),
            _meaning_fields(),
        )
    except Exception as error:
        showWarning(f"The exact search could not be built.\n\n{error}", parent=mw)
        return
    _perform_search(browser, query)


def _quick_search(browser: Browser, key: str) -> None:
    """Run a one-click card filter, optionally narrowing the visible search."""
    col = _live_collection(browser)
    if col is None:
        showWarning("The Anki collection is currently unavailable.", parent=mw)
        return
    current = getattr(browser, "current_search", None)
    try:
        visible = str(current()).strip() if callable(current) else ""
    except Exception:
        visible = ""
    # Clicking New and then Review must not stack both filters: when the visible
    # search is the one we produced last time, narrow the search it was built from.
    if visible and visible == getattr(browser, "_simple_search_last_query", None):
        visible = getattr(browser, "_simple_search_base_query", "")
    base = visible if _config().get("quick_combine") else ""
    try:
        query = build_quick_query(col, key, base)
    except Exception as error:
        showWarning(f"The filter could not be built.\n\n{error}", parent=mw)
        return
    browser._simple_search_base_query = base
    browser._simple_search_last_query = query
    _perform_search(browser, query)


def _set_quick_combine(checked: bool) -> None:
    config = _config()
    config["quick_combine"] = bool(checked)
    try:
        _CFG.writeConfig(__name__, config)
    except Exception:
        pass


def _fill_quick_menu(menu: QMenu, browser: Browser, *, with_options: bool = True) -> None:
    for key, label, tip in QUICK_FILTERS:
        if not key:
            continue
        action = menu.addAction(label)
        if action is None:
            continue
        action.setToolTip(tip)
        action.setStatusTip(tip)
        qconnect(action.triggered, lambda _checked=False, k=key: _quick_search(browser, k))
    if not with_options:
        return
    menu.addSeparator()
    narrow = menu.addAction("Narrow the current search")
    if narrow is not None:
        narrow.setCheckable(True)
        narrow.setChecked(bool(_config().get("quick_combine")))
        narrow.setToolTip(
            "On: the filter is added to what the Browser currently shows "
            "(for example the current deck). Off: it searches all decks."
        )
        qconnect(narrow.toggled, _set_quick_combine)
    more = menu.addAction("Search Assistant…")
    if more is not None:
        qconnect(more.triggered, lambda _checked=False: _open_assistant(browser))


def _deck_names() -> list[str]:
    col = getattr(mw, "col", None)
    if col is None:
        return []
    names = [
        deck.name
        for deck in col.decks.all_names_and_ids(
            include_filtered=False, skip_empty_default=True
        )
    ]
    return sorted(names, key=lambda name: [part.casefold() for part in name.split("::")])


def _word_search(browser: Browser, search: WordSearch) -> str:
    col = _live_collection(browser)
    if col is None:
        raise RuntimeError("The Anki collection is currently unavailable.")
    query = build_word_query(col, search, _all_fields(col), _word_fields(), _meaning_fields())
    _perform_search(browser, query)
    return query


def _setup_word_panel(browser: Browser) -> None:
    config = _config()
    panel = WordSearchPanel(
        browser,
        decks=_deck_names,
        run=lambda search: _word_search(browser, search),
        config=config,
        save=_save_config,
    )
    if not install_panel(browser, panel):
        panel.deleteLater()
        return
    browser._simple_search_word_panel = panel
    action = focus_action(browser, panel, str(config.get("word_search_shortcut", "")).strip())
    browser.addAction(action)
    menu = getattr(getattr(browser, "form", None), "menuEdit", None)
    if menu is not None:
        menu.addAction(action)
    browser._simple_search_word_action = action


def _word_from_context(browser: Browser, text: str, mode: str) -> None:
    panel = getattr(browser, "_simple_search_word_panel", None)
    try:
        if panel is not None:
            panel.edit.setText(text)
            panel.buttons[mode].click()
            return
        _word_search(browser, WordSearch(text=text, mode=mode))
    except Exception as error:
        showWarning(f"The search could not be started.\n\n{error}", parent=mw)


_BAR_STYLE = (
    "QToolButton::menu-indicator{image:none;width:0px;}"
    "QToolButton[active=\"true\"]{background:palette(highlight);color:palette(highlighted-text);"
    "border-radius:5px;padding:2px 8px;font-weight:bold;}"
)


def _bar_label(choice: str) -> str:
    if not choice:
        return "all fields"
    if choice == FIELD_WORD:
        return "the word"
    if choice == FIELD_MEANING:
        return "meaning"
    return choice


def _refresh_bar_button(button: QToolButton) -> None:
    choice = str(_config().get("search_bar_field", "") or "")
    button.setText(f"Search bar: {_bar_label(choice)} ▾")
    button.setProperty("active", bool(choice))
    button.setToolTip(
        "What plain words typed in the search bar look in.\n"
        + (f"Now: only {_bar_label(choice)} (contains the word)." if choice
           else "Now: all fields – Anki's normal search.")
        + "\nSearches with Anki syntax (deck:, Simplified:…, OR, -, *) always work as usual."
    )
    style = button.style()
    if style is not None:  # re-apply the [active] style
        style.unpolish(button)
        style.polish(button)


def _set_search_bar_field(browser: Browser, button: QToolButton, choice: str) -> None:
    _save_config({"search_bar_field": choice})
    _refresh_bar_button(button)
    rerun = getattr(browser, "search", None)  # show the effect on what is typed right now
    if callable(rerun) and _live_collection(browser) is not None:
        try:
            rerun()
        except Exception:
            pass


def _fill_search_bar_menu(menu: QMenu, browser: Browser, button: QToolButton) -> None:
    menu.clear()
    current = str(_config().get("search_bar_field", "") or "")
    header = menu.addAction("Plain words typed in the search bar look in:")
    header.setEnabled(False)
    col = _live_collection(browser)
    fields = _all_fields(col) if col is not None else ()
    word = pick_fields(fields, _word_fields())
    meaning = pick_fields(fields, _meaning_fields())
    choices = [("All fields (Anki's normal search)", "")]
    choices.append(("The word itself – " + ", ".join(word[:4]) + (" …" if len(word) > 4 else ""), FIELD_WORD))
    choices.append(("Meaning / translation – " + ", ".join(meaning[:3]) + (" …" if len(meaning) > 3 else ""), FIELD_MEANING))

    def add(text: str, value: str, target: QMenu) -> None:
        action = target.addAction(text)
        action.setCheckable(True)
        action.setChecked(value == current)
        qconnect(action.triggered, lambda _c=False, v=value: _set_search_bar_field(browser, button, v))

    deck = _browser_deck(browser)
    rec, sort_fields = _deck_recommendations_with_sort(col, deck)
    if rec:
        head = menu.addAction(f"Recommended for {deck.split('::')[-1]}:")
        head.setEnabled(False)
        for name in rec:
            add(f"{name}  (sort field)" if name in sort_fields else name, name, menu)
        menu.addSeparator()
    for text, value in choices:
        add(text, value, menu)
    if word:
        menu.addSeparator()
        one = menu.addAction("Only one field:")
        one.setEnabled(False)
        for name in word:
            add(name, name, menu)
    others = [f for f in fields if f not in word]
    if others:
        sub = menu.addMenu("Other fields")
        if sub is not None:
            for name in others:
                add(name, name, sub)
            if current in others:
                sub.setTitle(f"Other fields (now: {current})")


def _make_search_bar_button(browser: Browser) -> QToolButton:
    button = QToolButton(browser)
    button.setObjectName("simpleSearchBarFieldButton")
    button.setAccessibleName("Field the normal search bar looks in")
    button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    button.setStyleSheet(_BAR_STYLE)
    menu = QMenu(button)
    qconnect(menu.aboutToShow, lambda: _fill_search_bar_menu(menu, browser, button))
    button.setMenu(menu)
    _refresh_bar_button(button)
    return button


def _setup_browser(browser: Browser) -> None:
    if getattr(browser, "_simple_search_assistant_ready", False):
        return
    browser._simple_search_assistant_ready = True

    action = QAction("Search Assistant…", browser)
    shortcut = str(_config().get("shortcut", "")).strip()
    if shortcut:
        action.setShortcut(QKeySequence(shortcut))
    qconnect(action.triggered, lambda _checked=False: _open_assistant(browser))
    menu = getattr(getattr(browser, "form", None), "menuEdit", None)
    if menu is not None:
        menu.addSeparator()
        menu.addAction(action)
        quick_menu = menu.addMenu("Quick card filters")
        if quick_menu is not None:
            _fill_quick_menu(quick_menu, browser, with_options=False)
            browser._simple_search_quick_edit_menu = quick_menu
    browser._simple_search_assistant_action = action

    form = getattr(browser, "form", None)
    grid = getattr(form, "gridLayout", None)
    if grid is not None:
        button = QToolButton(browser)
        button.setObjectName("simpleSearchAssistantButton")
        button.setText("Search…")
        button.setToolTip("Build an exact or filtered search without commands")
        qconnect(button.clicked, lambda _checked=False: _open_assistant(browser))
        quick = QToolButton(browser)
        quick.setObjectName("simpleSearchQuickButton")
        quick.setText("Cards ▾")
        quick.setToolTip("One-click filters: New, Old, Due, Suspended, …")
        quick.setAccessibleName("Quick card filters")
        quick.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        quick_menu = QMenu(quick)
        _fill_quick_menu(quick_menu, browser)
        quick.setMenu(quick_menu)
        quick_shortcut = str(_config().get("quick_shortcut", "")).strip()
        if quick_shortcut:
            quick_action = QAction("Quick card filters", browser)
            quick_action.setShortcut(QKeySequence(quick_shortcut))
            qconnect(quick_action.triggered, lambda _checked=False: quick.showMenu())
            browser.addAction(quick_action)
            browser._simple_search_quick_action = quick_action
        bar = _make_search_bar_button(browser)
        try:
            column = max(2, int(grid.columnCount()))
            grid.addWidget(bar, 0, column, 1, 1)
            grid.addWidget(quick, 0, column + 1, 1, 1)
            grid.addWidget(button, 0, column + 2, 1, 1)
            browser._simple_search_assistant_button = button
            browser._simple_search_quick_button = quick
            browser._simple_search_bar_button = bar
        except Exception:
            button.deleteLater()
            quick.deleteLater()
            bar.deleteLater()
    try:
        _setup_word_panel(browser)
    except Exception as error:  # never break the Browser over the extra panel
        print(f"[simple_search_assistant] word panel unavailable: {error}")


def _add_context_menu(browser: Browser, menu: QMenu) -> None:
    if _live_collection(browser) is None:
        return
    submenu = menu.addMenu("Search Assistant")
    selected = _selected_sort_value(browser)
    if selected is not None:
        field_name, value = selected
        exact = submenu.addAction(f'Find exact "{_short(value)}" in {field_name}')
        if exact is not None:
            qconnect(
                exact.triggered,
                lambda _checked=False, f=field_name, v=value: _exact_selected(
                    browser, f, v
                ),
            )
    if selected is not None:
        _f, word = selected
        for mode, label in (
            (WORD_CONTAINS, f'Words containing "{_short(word, 16)}"'),
            (WORD_RELATED, 'Related words (sharing a character or syllable)'),
        ):
            entry = submenu.addAction(label)
            if entry is not None:
                qconnect(
                    entry.triggered,
                    lambda _checked=False, m=mode, w=word: _word_from_context(browser, w, m),
                )
    quick_sub = submenu.addMenu("Quick card filters")
    if quick_sub is not None:
        _fill_quick_menu(quick_sub, browser, with_options=False)
    open_action = submenu.addAction("Open Search Assistant…")
    if open_action is not None:
        selected_field, selected_value = selected or ("", "")
        qconnect(
            open_action.triggered,
            lambda _checked=False, f=selected_field, v=selected_value: _open_assistant(
                browser,
                initial_field=f,
                initial_text=v,
                initial_match=MATCH_EXACT if v else None,
            ),
        )


def _default_field_search(context) -> None:
    """Plain words typed in the normal search bar search the chosen default field(s)."""
    try:
        choice = str(_config().get("search_bar_field", "") or "")
        if not choice or getattr(context, "ids", None) is not None:
            return
        col = _live_collection(context.browser)
        if col is None:
            return
        rewritten = rewrite_search_bar(
            col, context.search, choice, _all_fields(col), _word_fields(), _meaning_fields()
        )
        if rewritten:
            context.search = rewritten
    except Exception:
        return  # never break Anki's own search


gui_hooks.browser_will_search.append(_default_field_search)
gui_hooks.browser_menus_did_init.append(_setup_browser)
gui_hooks.browser_will_show_context_menu.append(_add_context_menu)
for _hook_name in ("profile_will_close", "collection_will_temporarily_close"):
    _hook = getattr(gui_hooks, _hook_name, None)
    if _hook is not None:
        _hook.append(_invalidate_pending)
