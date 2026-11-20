"""Native settings: named counters, searchable multi-deck picker, no DB calls."""

from __future__ import annotations

from dataclasses import replace
import uuid

from aqt.qt import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QSplitter, QTreeWidget, QTreeWidgetItem,
    Qt, QVBoxLayout, QWidget, qconnect,
)

from .core import Counter, DeckRef, MAX_COUNTERS, Options


STYLE = """
QDialog#deckProgressSettings QLabel#dpTitle { font-size: 20px; font-weight: 600; }
QDialog#deckProgressSettings QLabel#dpHint { color: palette(mid); }
QDialog#deckProgressSettings QLineEdit { padding: 6px; }
QDialog#deckProgressSettings QPushButton { padding: 5px 10px; }
QDialog#deckProgressSettings QListWidget { border-radius: 6px; }
QDialog#deckProgressSettings QListWidget::item { padding: 9px 8px; }
"""


class DeckPicker(QDialog):
    def __init__(self, parent, decks: tuple[DeckRef, ...], selected: tuple[DeckRef, ...]):
        super().__init__(parent)
        self.setWindowTitle("Choose decks")
        self.resize(650, 470)
        self.decks = decks
        self.items: dict[int, QTreeWidgetItem] = {}
        layout = QVBoxLayout(self)
        hint = QLabel("Select one or more decks. Parent and child selections are counted only once.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search decks…")
        self.search.setClearButtonEnabled(True)
        layout.addWidget(self.search)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tree.setAccessibleName("Decks to count")
        paths: dict[str, QTreeWidgetItem] = {}
        chosen = {d.id for d in selected}
        for deck in decks:
            parts = deck.name.split("::")
            for depth, leaf in enumerate(parts):
                path = "::".join(parts[:depth + 1])
                if path in paths:
                    item = paths[path]
                else:
                    parent_item = paths.get("::".join(parts[:depth]))
                    item = QTreeWidgetItem(parent_item if parent_item is not None else self.tree)
                    item.setText(0, leaf)
                    item.setToolTip(0, path)
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                    paths[path] = item
                if depth == len(parts) - 1:
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setData(0, Qt.ItemDataRole.UserRole, deck.id)
                    item.setCheckState(0, Qt.CheckState.Checked if deck.id in chosen else Qt.CheckState.Unchecked)
                    self.items[deck.id] = item
        self.tree.expandAll()
        layout.addWidget(self.tree)
        self.count_label = QLabel()
        layout.addWidget(self.count_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        layout.addWidget(buttons)
        qconnect(buttons.accepted, self.accept)
        qconnect(buttons.rejected, self.reject)
        qconnect(self.search.textChanged, self._filter)
        qconnect(self.tree.itemChanged, self._update_count)
        self._update_count()

    def _filter(self, query: str):
        query = query.strip().casefold()

        def visit(item):
            matches = query in item.toolTip(0).casefold()
            child_visible = False
            for index in range(item.childCount()):
                child_visible = visit(item.child(index)) or child_visible
            visible = matches or child_visible
            item.setHidden(not visible)
            if query and child_visible:
                item.setExpanded(True)
            return visible

        for index in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(index))

    def _update_count(self, *_args):
        count = len(self.selected_decks())
        self.count_label.setText(f"{count} deck{'s' if count != 1 else ''} selected")

    def selected_decks(self) -> tuple[DeckRef, ...]:
        chosen = {did for did, item in self.items.items() if item.checkState(0) == Qt.CheckState.Checked}
        return tuple(d for d in self.decks if d.id in chosen)


class SettingsDialog(QDialog):
    def __init__(self, parent, options: Options, decks: tuple[DeckRef, ...], focus: str | None = None):
        super().__init__(parent)
        self.setObjectName("deckProgressSettings")
        self.setWindowTitle("Deck Progress — Customize")
        self.resize(860, 600)
        self.setStyleSheet(STYLE)
        self.decks = decks
        self.rows = list(options.counters)
        self._loading = False
        self._index = -1
        self._selected: tuple[DeckRef, ...] = ()
        self.result_options: Options | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)
        title = QLabel("Your decks. Your counters.")
        title.setObjectName("dpTitle")
        layout.addWidget(title)
        hint = QLabel("Create one counter per language, course, or goal. Only cards answered at least once count as studied.")
        hint.setObjectName("dpHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.enabled = QCheckBox("Show Deck Progress below the heatmap on the deck list")
        self.enabled.setChecked(options.enabled)
        layout.addWidget(self.enabled)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        left, right = QWidget(), QWidget()
        sidebar, editor = QVBoxLayout(left), QVBoxLayout(right)
        sidebar.setContentsMargins(0, 0, 8, 0)
        editor.setContentsMargins(8, 0, 0, 0)
        sidebar.addWidget(QLabel("Counters"))
        self.list = QListWidget()
        self.list.setAccessibleName("Progress counters")
        sidebar.addWidget(self.list)
        add_row = QHBoxLayout()
        self.add_button, self.remove_button = QPushButton("＋ Add"), QPushButton("Remove")
        add_row.addWidget(self.add_button)
        add_row.addWidget(self.remove_button)
        sidebar.addLayout(add_row)
        order_row = QHBoxLayout()
        self.up, self.down = QPushButton("Move up"), QPushButton("Move down")
        order_row.addWidget(self.up)
        order_row.addWidget(self.down)
        sidebar.addLayout(order_row)

        self.editor = right
        self.name = QLineEdit()
        self.name.setMaxLength(80)
        self.name.setPlaceholderText("For example: Japanese")
        form = QFormLayout()
        form.addRow("Display name", self.name)
        self.unit = QComboBox()
        self.unit.addItem("Studied cards", "cards")
        self.unit.addItem("Studied words (notes)", "notes")
        self.unit.addItem("Cards + words (notes)", "both")
        form.addRow("Count", self.unit)
        editor.addLayout(form)
        editor.addWidget(QLabel("Selected decks"))
        self.deck_list = QListWidget()
        self.deck_list.setAccessibleName("Selected decks for this counter")
        self.deck_list.setMinimumHeight(85)
        editor.addWidget(self.deck_list, 1)
        self.choose = QPushButton("Choose decks…")
        editor.addWidget(self.choose, 0, Qt.AlignmentFlag.AlignLeft)
        self.children = QCheckBox("Include subdecks")
        self.stages = QCheckBox("Only a. stages within this selection")
        self.stages.setToolTip("Choose a language/category deck, then count only its a. stage decks and their descendants.")
        self.suspended = QCheckBox("Include suspended cards that have been studied")
        self.total = QCheckBox("Show selected total beside the studied count")
        for box in (self.children, self.stages, self.suspended, self.total):
            editor.addWidget(box)
        explainer = QLabel(
            "Stage Shifter tip: choose a. Frieren and name the counter Japanese. "
            "Or choose the Japanese parent deck and enable “Only a. stages”. "
            "The counter updates after moves and undo. It never moves cards."
        )
        explainer.setObjectName("dpHint")
        explainer.setWordWrap(True)
        editor.addWidget(explainer)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([255, 560])
        layout.addWidget(splitter, 1)
        bottom = QLabel("A word is one Anki note. If any selected card of that note was answered, the note counts once.")
        bottom.setObjectName("dpHint")
        bottom.setWordWrap(True)
        layout.addWidget(bottom)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        layout.addWidget(buttons)
        qconnect(buttons.accepted, self._save)
        qconnect(buttons.rejected, self.reject)
        qconnect(self.add_button.clicked, self._add)
        qconnect(self.remove_button.clicked, self._remove)
        qconnect(self.up.clicked, lambda: self._reorder(-1))
        qconnect(self.down.clicked, lambda: self._reorder(1))
        qconnect(self.list.currentRowChanged, self._select)
        qconnect(self.choose.clicked, self._choose)
        qconnect(self.name.textChanged, self._edited)
        qconnect(self.unit.currentIndexChanged, self._edited)
        for box in (self.children, self.stages, self.suspended, self.total):
            qconnect(box.toggled, self._edited)
        index = next((i for i, row in enumerate(self.rows) if row.id == focus), 0)
        self._rebuild(index)
        if not self.rows:
            self._add()

    def _store(self):
        if self._loading or not 0 <= self._index < len(self.rows):
            return
        self.rows[self._index] = replace(
            self.rows[self._index], name=self.name.text().strip(), decks=self._selected,
            unit=self.unit.currentData(), include_subdecks=self.children.isChecked(),
            stage_a_only=self.stages.isChecked(), include_suspended=self.suspended.isChecked(),
            show_total=self.total.isChecked(),
        )

    def _edited(self, *_args):
        self._store()
        if not self._loading and self._index >= 0:
            item = self.list.item(self._index)
            item.setText(self.rows[self._index].name or "Untitled counter")

    def _rebuild(self, index):
        self.list.blockSignals(True)
        self.list.clear()
        for row in self.rows:
            item = QListWidgetItem(row.name or "Untitled counter")
            item.setToolTip("\n".join(d.name for d in row.decks))
            self.list.addItem(item)
        self.list.blockSignals(False)
        self._index = -1
        if self.rows:
            self.list.setCurrentRow(max(0, min(index, len(self.rows) - 1)))
        else:
            self._select(-1)
        self.add_button.setEnabled(len(self.rows) < MAX_COUNTERS)

    def _select(self, index):
        self._store()
        self._loading = True
        self._index = index
        self.editor.setEnabled(index >= 0)
        self.remove_button.setEnabled(index >= 0)
        self.up.setEnabled(index > 0)
        self.down.setEnabled(0 <= index < len(self.rows) - 1)
        if index >= 0:
            row = self.rows[index]
            self.name.setText(row.name)
            self.unit.setCurrentIndex(max(0, self.unit.findData(row.unit)))
            self.children.setChecked(row.include_subdecks)
            self.stages.setChecked(row.stage_a_only)
            self.suspended.setChecked(row.include_suspended)
            self.total.setChecked(row.show_total)
            self._selected = row.decks
            self._show_decks()
        self._loading = False

    def _show_decks(self):
        by_id = {d.id: d.name for d in self.decks}
        self.deck_list.clear()
        for deck in self._selected:
            missing = deck.id not in by_id
            text = by_id.get(deck.id, deck.name or str(deck.id)).replace("::", " › ")
            item = QListWidgetItem(("Missing: " if missing else "") + text)
            item.setToolTip(by_id.get(deck.id, deck.name))
            self.deck_list.addItem(item)
        if not self._selected:
            self.deck_list.addItem("No decks selected — click Choose decks…")

    def _choose(self):
        picker = DeckPicker(self, self.decks, self._selected)
        if picker.exec() == QDialog.DialogCode.Accepted:
            self._selected = picker.selected_decks()
            self._show_decks()
            self._edited()

    def _add(self):
        if len(self.rows) >= MAX_COUNTERS:
            return
        self._store()
        self.rows.append(Counter(uuid.uuid4().hex, f"Counter {len(self.rows) + 1}", ()))
        self._rebuild(len(self.rows) - 1)
        self.name.setFocus()
        self.name.selectAll()

    def _remove(self):
        index = self._index
        if index < 0:
            return
        # Only removes an unsaved display configuration, never a deck or card.
        self.rows.pop(index)
        self._rebuild(index)

    def _reorder(self, step):
        self._store()
        index, target = self._index, self._index + step
        if index < 0 or not 0 <= target < len(self.rows):
            return
        self.rows[index], self.rows[target] = self.rows[target], self.rows[index]
        self._rebuild(target)

    def _save(self):
        self._store()
        for index, row in enumerate(self.rows):
            if not row.name or not row.decks:
                self.list.setCurrentRow(index)
                QMessageBox.information(self, "Complete this counter", "Enter a display name and choose at least one deck, or remove this counter.")
                return
        self.result_options = Options(self.enabled.isChecked(), tuple(self.rows))
        self.accept()
