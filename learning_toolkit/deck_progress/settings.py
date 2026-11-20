"""Native settings: named counters, searchable multi-deck picker, no DB calls."""

from __future__ import annotations

from dataclasses import replace
import uuid

from aqt.qt import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QSpinBox, QSplitter, QTabWidget,
    QTreeWidget, QTreeWidgetItem, Qt, QVBoxLayout, QWidget, pyqtSignal, qconnect,
)

from .core import (
    ALL_STATES, ANSWERED_STATES, CARD_STATES, MAX_PER_DAY, SHOWN_STATES, STATE_LABELS, Counter, DeckRef,
    MAX_COUNTERS, MAX_LABEL_LENGTH, Options, default_label, state_summary,
)


class StateNames(QDialog):
    """Rename the card states shown beside counters (e.g. New → Neu)."""

    def __init__(self, parent, labels: dict):
        super().__init__(parent)
        self.setWindowTitle("Names of card states")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Leave a field empty to use Anki's name."))
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.fields = {}
        for state in SHOWN_STATES:
            field = QLineEdit(labels.get(state, ""))
            field.setMaxLength(MAX_LABEL_LENGTH)
            field.setPlaceholderText(STATE_LABELS[state])
            form.addRow(STATE_LABELS[state], field)
            self.fields[state] = field
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        qconnect(buttons.accepted, self.accept)
        qconnect(buttons.rejected, self.reject)
        layout.addWidget(buttons)

    def labels(self) -> dict:
        return {state: field.text().strip() for state, field in self.fields.items() if field.text().strip()}


class DeckPicker(QDialog):
    def __init__(self, parent, title: str, decks: tuple[DeckRef, ...], selected: tuple[DeckRef, ...]):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(540, 420)
        self.decks = decks
        self.items: dict[int, QTreeWidgetItem] = {}
        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search decks…")
        self.search.setAccessibleName("Search decks")
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


class DeckSelection(QWidget):
    changed = pyqtSignal()

    def __init__(self, decks: tuple[DeckRef, ...], label: str, button_text: str, empty_text: str):
        super().__init__()
        self.decks = decks
        self.by_id = {deck.id: deck.name for deck in decks}
        self.selected: tuple[DeckRef, ...] = ()
        self.empty_text = empty_text

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        heading = QLabel(label)
        header.addWidget(heading, 1)
        self.choose = QPushButton(button_text)
        self.choose.setAutoDefault(False)
        header.addWidget(self.choose)
        layout.addLayout(header)
        self.list = QListWidget()
        self.list.setAccessibleName(label)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.list.setSpacing(2)
        self.list.setMinimumHeight(64)
        layout.addWidget(self.list)
        qconnect(self.choose.clicked, self._choose)

    def set_decks(self, selected: tuple[DeckRef, ...]):
        self.selected = selected
        self.list.clear()
        for deck in selected:
            name = self.by_id.get(deck.id, deck.name or str(deck.id))
            prefix = "Missing deck · " if deck.id not in self.by_id else ""
            item = QListWidgetItem(prefix + name.replace("::", " › "))
            item.setToolTip(name)
            self.list.addItem(item)
        if not selected:
            self.list.addItem(self.empty_text)

    def _choose(self):
        picker = DeckPicker(self, self.choose.text().rstrip("…"), self.decks, self.selected)
        if picker.exec() == QDialog.DialogCode.Accepted:
            self.set_decks(picker.selected_decks())
            self.changed.emit()
        picker.deleteLater()


class StateSelection(QPushButton):
    changed = pyqtSignal()

    def __init__(self, title: str):
        super().__init__()
        self.title = title
        self.setAccessibleName(title)
        self.setAutoDefault(False)
        self.set_states(ALL_STATES)
        qconnect(self.clicked, self._choose)

    def set_states(self, states: tuple[str, ...]):
        self.states = states
        self.setText(state_summary(states) + "…")

    def _choose(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(self.title)
        layout = QVBoxLayout(dialog)
        mode = QComboBox()
        mode.setAccessibleName("Filter mode")
        mode.addItem(state_summary(ALL_STATES), "all")
        mode.addItem(state_summary(ANSWERED_STATES), "answered")
        mode.addItem("Selected states", "selected")
        layout.addWidget(mode)

        checks = {}
        review_hints = {"young": "interval under 21 days", "mature": "interval of 21 days or more"}
        for state, (label, _) in CARD_STATES.items():
            text = f"{label} ({review_hints[state]})" if state in review_hints else label
            box = QCheckBox(text)
            box.setChecked(state in self.states)
            checks[state] = box
            layout.addWidget(box)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        layout.addWidget(buttons)

        def update_ok(*_):
            buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
                mode.currentData() != "selected" or any(box.isChecked() for box in checks.values())
            )

        def choose_states(_):
            mode.setCurrentIndex(mode.findData("selected"))
            update_ok()

        for box in checks.values():
            qconnect(box.toggled, choose_states)
        saved_mode = self.states[0] if self.states in (ALL_STATES, ANSWERED_STATES) else "selected"
        mode.setCurrentIndex(mode.findData(saved_mode))
        qconnect(mode.currentIndexChanged, update_ok)
        qconnect(buttons.accepted, dialog.accept)
        qconnect(buttons.rejected, dialog.reject)
        update_ok()
        if dialog.exec() == QDialog.DialogCode.Accepted:
            preset = mode.currentData()
            states = tuple(state for state, box in checks.items() if box.isChecked()) if preset == "selected" else (preset,)
            self.set_states(states)
            self.changed.emit()
        dialog.deleteLater()


class SettingsDialog(QDialog):
    def __init__(self, parent, options: Options, decks: tuple[DeckRef, ...], focus: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("Deck Progress Settings")
        self.resize(680, 420)
        self.rows = list(options.counters)
        self.state_labels = dict(options.state_labels)
        self._loading = False
        self._index = -1
        self.result_options: Options | None = None
        layout = QVBoxLayout(self)
        self.enabled = QCheckBox("Show Deck Progress on the deck list")
        self.enabled.setChecked(options.enabled)
        layout.addWidget(self.enabled)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        left = QWidget()
        sidebar = QVBoxLayout(left)
        sidebar.setContentsMargins(0, 0, 4, 0)
        sidebar.addWidget(QLabel("Counters"))
        self.list = QListWidget()
        self.list.setAccessibleName("Progress counters")
        self.list.setSpacing(2)
        sidebar.addWidget(self.list, 1)
        controls = QGridLayout()
        self.add_button, self.remove_button = QPushButton("Add"), QPushButton("Remove")
        self.up, self.down = QPushButton("Move up"), QPushButton("Move down")
        for index, button in enumerate((self.add_button, self.remove_button, self.up, self.down)):
            button.setAutoDefault(False)
            controls.addWidget(button, index // 2, index % 2)
        sidebar.addLayout(controls)

        self.tabs = QTabWidget()
        counter_tab = QWidget()
        editor = QVBoxLayout(counter_tab)
        self.name = QLineEdit()
        self.name.setMaxLength(MAX_LABEL_LENGTH)
        self.name.setPlaceholderText("e.g. Japanese")
        self.form = QFormLayout()
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.form.addRow("Name", self.name)
        self.unit = QComboBox()
        self.unit.addItem("Cards", "cards")
        self.unit.addItem("Notes", "notes")
        self.unit.addItem("Cards and notes", "both")
        self.unit.setToolTip("Count individual cards, distinct notes, or both.")
        self.form.addRow("Count", self.unit)
        self.counter_states = StateSelection("Counter card states")
        self.counter_states.setToolTip("Choose the scheduling states to count.")
        self.form.addRow("Card states", self.counter_states)
        self.card_label = QLineEdit()
        self.note_label = QLineEdit()
        for field in (self.card_label, self.note_label):
            field.setMaxLength(MAX_LABEL_LENGTH)
            field.setToolTip("Leave blank to use the default label.")
        self.form.addRow("Card label", self.card_label)
        self.form.addRow("Note label", self.note_label)
        self.all_note_cards = QCheckBox("Require every card of a note to match")
        self.all_note_cards.setToolTip(
            "Check the note's cards across decks. The suspended and buried card options apply here too."
        )
        self.form.addRow(self.all_note_cards)
        editor.addLayout(self.form)
        self.sources = DeckSelection(decks, "Counter decks", "Choose decks…", "Choose at least one deck")
        editor.addWidget(self.sources, 1)
        self.children = QCheckBox("Include subdecks")
        self.stages = QCheckBox("Only a. stages in counter decks")
        self.stages.setToolTip("Apply the Stage Shifter filter to counter decks and their descendants.")
        self.suspended = QCheckBox("Include suspended cards")
        self.buried = QCheckBox("Include buried cards")
        for box in (self.children, self.stages):
            editor.addWidget(box)
        availability = QHBoxLayout()
        availability.addWidget(self.suspended)
        availability.addWidget(self.buried)
        availability.addStretch()
        editor.addLayout(availability)

        progress_tab = QWidget()
        progress = QVBoxLayout(progress_tab)
        self.total = QCheckBox("Show selected total")
        self.total.setToolTip("Show the counter count over the full goal size.")
        self.progress = QCheckBox("Show progress bar and percentage")
        progress.addWidget(self.total)
        progress.addWidget(self.progress)
        hint = QLabel(
            "The bar shows the counter count divided by the goal total. The total includes the counter decks "
            "and matching cards from additional goal decks."
        )
        hint.setWordWrap(True)
        progress.addWidget(hint)
        goal_form = QFormLayout()
        goal_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.goal_states = StateSelection("Additional goal card states")
        self.goal_states.setToolTip("Apply this filter to additional goal decks.")
        goal_form.addRow("Goal deck states", self.goal_states)
        progress.addLayout(goal_form)
        self.goals = DeckSelection(decks, "Additional goal decks", "Choose goal decks…", "Uses counter decks only")
        progress.addWidget(self.goals, 1)
        details_tab = QWidget()
        details = QVBoxLayout(details_tab)
        self.show_states = QCheckBox("Show card states (New, Learning, Relearning, Review, Suspended)")
        self.show_states.setToolTip("Cards in the counter decks by state, in Anki's colours. Suspended cards are counted apart.")
        details.addWidget(self.show_states)
        self.show_note_states = QCheckBox("Show note states")
        self.show_note_states.setToolTip("Notes in the counter decks by state. Each note counts once, in its most active state "
                                         "(relearning, learning, review, new); suspended only when all its cards are.")
        details.addWidget(self.show_note_states)
        rename = QPushButton("Rename states…")
        rename.setAutoDefault(False)
        rename.setToolTip("Use your own words, e.g. Neu, Lernen, Wiederholen")
        qconnect(rename.clicked, self._rename_states)
        rename_row = QHBoxLayout()
        rename_row.addWidget(rename)
        rename_row.addStretch()
        details.addLayout(rename_row)
        estimate_form = QFormLayout()
        estimate_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.estimate = QComboBox()
        self.estimate.addItem("Off", "off")
        self.estimate.addItem("At my pace", "pace")
        self.estimate.addItem("At a fixed pace", "fixed")
        estimate_form.addRow("Finish estimate", self.estimate)
        self.per_day = QSpinBox()
        self.per_day.setRange(1, MAX_PER_DAY)
        self.per_day.setSuffix(" per day")
        estimate_form.addRow("Fixed pace", self.per_day)
        details.addLayout(estimate_form)
        self.show_left = QCheckBox("Show what's left (e.g. \u201c1,995 notes left\u201d)")
        self.show_left.setToolTip("Goal total minus what the counter counts, so it follows the counter's card states.")
        details.addWidget(self.show_left)
        explain = QLabel(
            "<b>At my pace</b> uses how many new notes (or cards) you start on days you study, recent days "
            "counting more. Days off and long breaks don't pull the pace down. If you studied on fewer than "
            "5 days in the last 4 weeks, your last study days are used and the date assumes you study daily.<br>"
            "<b>Left</b> is the goal total (or all notes of the counter decks) minus what the counter counts, so it "
            "follows the counter's card states (e.g. mature only). The estimate is left ÷ pace."
        )
        explain.setWordWrap(True)
        details.addWidget(explain)
        details.addStretch()
        self.tabs.addTab(counter_tab, "Counter")
        self.tabs.addTab(progress_tab, "Progress")
        self.tabs.addTab(details_tab, "States && estimate")
        splitter.addWidget(left)
        splitter.addWidget(self.tabs)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([175, 475])
        layout.addWidget(splitter, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        layout.addWidget(buttons)
        qconnect(buttons.accepted, self._save)
        qconnect(buttons.rejected, self.reject)
        qconnect(self.add_button.clicked, self._add)
        qconnect(self.remove_button.clicked, self._remove)
        qconnect(self.up.clicked, lambda: self._reorder(-1))
        qconnect(self.down.clicked, lambda: self._reorder(1))
        qconnect(self.list.currentRowChanged, self._select)
        for chooser in (self.sources, self.goals):
            qconnect(chooser.changed, self._edited)
        qconnect(self.counter_states.changed, self._states_changed)
        qconnect(self.all_note_cards.toggled, self._states_changed)
        qconnect(self.goal_states.changed, self._edited)
        for field in (self.name, self.card_label, self.note_label):
            qconnect(field.textChanged, self._edited)
        qconnect(self.unit.currentIndexChanged, self._unit_changed)
        for box in (self.children, self.stages, self.suspended, self.buried, self.total, self.progress, self.show_states,
                    self.show_note_states, self.show_left):
            qconnect(box.toggled, self._edited)
        qconnect(self.estimate.currentIndexChanged, self._estimate_changed)
        qconnect(self.per_day.valueChanged, self._edited)
        index = next((i for i, row in enumerate(self.rows) if row.id == focus), 0)
        self._rebuild(index)
        if not self.rows:
            self._add()

    def _store(self):
        if self._loading or not 0 <= self._index < len(self.rows):
            return
        self.rows[self._index] = replace(
            self.rows[self._index], name=self.name.text().strip(), decks=self.sources.selected,
            unit=self.unit.currentData(), include_subdecks=self.children.isChecked(),
            stage_a_only=self.stages.isChecked(), include_suspended=self.suspended.isChecked(),
            show_total=self.total.isChecked(), show_progress=self.progress.isChecked(),
            goal_decks=self.goals.selected, card_label=self.card_label.text().strip(),
            note_label=self.note_label.text().strip(),
            counter_states=self.counter_states.states, goal_states=self.goal_states.states,
            include_buried=self.buried.isChecked(),
            all_note_cards=self.all_note_cards.isChecked(),
            show_states=self.show_states.isChecked(),
            show_note_states=self.show_note_states.isChecked(),
            show_left=self.show_left.isChecked(),
            estimate=self.estimate.currentData(),
            per_day=self.per_day.value(),
        )

    def _estimate_changed(self, *_args):
        self.per_day.setEnabled(self.estimate.currentData() == "fixed")
        self._edited()

    def _rename_states(self):
        dialog = StateNames(self, self.state_labels)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.state_labels = dialog.labels()

    def _states_changed(self, *_args):
        self.card_label.setPlaceholderText(default_label("cards", self.counter_states.states))
        self.note_label.setPlaceholderText(default_label(
            "notes", self.counter_states.states, all_note_cards=self.all_note_cards.isChecked(),
        ))
        self._edited()

    def _unit_changed(self, *_args):
        unit = self.unit.currentData()
        self.form.setRowVisible(self.card_label, unit != "notes")
        self.form.setRowVisible(self.note_label, unit != "cards")
        self.form.setRowVisible(self.all_note_cards, unit != "cards")
        self._edited()

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
        self.tabs.setEnabled(index >= 0)
        self.remove_button.setEnabled(index >= 0)
        self.up.setEnabled(index > 0)
        self.down.setEnabled(0 <= index < len(self.rows) - 1)
        if index >= 0:
            row = self.rows[index]
            self.name.setText(row.name)
            self.unit.setCurrentIndex(max(0, self.unit.findData(row.unit)))
            self._unit_changed()
            self.card_label.setText(row.card_label)
            self.note_label.setText(row.note_label)
            self.counter_states.set_states(row.counter_states)
            self.goal_states.set_states(row.goal_states)
            self.all_note_cards.setChecked(row.all_note_cards)
            self._states_changed()
            self.children.setChecked(row.include_subdecks)
            self.stages.setChecked(row.stage_a_only)
            self.suspended.setChecked(row.include_suspended)
            self.buried.setChecked(row.include_buried)
            self.total.setChecked(row.show_total)
            self.progress.setChecked(row.show_progress)
            self.sources.set_decks(row.decks)
            self.goals.set_decks(row.goal_decks)
            self.show_states.setChecked(row.show_states)
            self.show_note_states.setChecked(row.show_note_states)
            self.show_left.setChecked(row.show_left)
            self.estimate.setCurrentIndex(max(0, self.estimate.findData(row.estimate)))
            self.per_day.setValue(row.per_day)
            self.per_day.setEnabled(row.estimate == "fixed")
        self._loading = False

    def _add(self):
        if len(self.rows) >= MAX_COUNTERS:
            return
        self._store()
        self.rows.append(Counter(uuid.uuid4().hex, f"Counter {len(self.rows) + 1}", ()))
        self._rebuild(len(self.rows) - 1)
        self.tabs.setCurrentIndex(0)
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
                self.tabs.setCurrentIndex(0)
                QMessageBox.information(self, "Complete this counter", "Enter a display name and choose at least one deck, or remove this counter.")
                return
        self.result_options = Options(self.enabled.isChecked(), tuple(self.rows), dict(self.state_labels))
        self.accept()
