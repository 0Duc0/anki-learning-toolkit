"""User interface for configurable card shifts between alphabetic stage decks."""

from __future__ import annotations

from anki.consts import (
    CARD_TYPE_LRN,
    CARD_TYPE_NEW,
    CARD_TYPE_RELEARNING,
    CARD_TYPE_REV,
)
from aqt import gui_hooks, mw
from aqt.operations import CollectionOp, QueryOp
from aqt.qt import (
    QAction,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QEvent,
    QFont,
    QFrame,
    QFormLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QMenu,
    QObject,
    QPalette,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    Qt,
    qconnect,
)
from aqt.utils import showInfo, showWarning

from .core import (
    ShiftOptions,
    ShiftPlan,
    ShiftResult,
    StageGroup,
    build_plan,
    card_type_label,
    scan_groups,
    shift_plan,
)
from ..common.config import SectionConfig
from ..common.menu import submenu, toolkit_menu

_CFG = SectionConfig('stage_shifter')

_collection_epoch = 0


def _invalidate_pending(*_args) -> None:
    global _collection_epoch
    _collection_epoch += 1


def _origin_ready(origin) -> bool:
    col, epoch = origin
    return _live_collection() is col and epoch == _collection_epoch


def _checked_operation(origin, operation):
    def run(col):
        if col is not origin[0] or not _origin_ready(origin):
            raise RuntimeError(
                "The collection changed. Open Card Stage Shifter again; nothing was moved."
            )
        return operation(col)

    return run


def _live_collection():
    col = getattr(mw, "col", None)
    if col is None or getattr(col, "db", None) is None:
        return None
    return col


def _run_query(operation: QueryOp, label: str | None = None) -> None:
    """Use progress when supported, while remaining safe across Anki APIs."""
    progress = getattr(operation, "with_progress", None)
    if label and callable(progress):
        operation = progress(label)
    operation.run_in_background()


DEFAULTS = {
    "direction": "toward_a",
    "start_key": "e",
    "stop_key": "a",
    "include_new": True,
    "include_learning": False,
    "include_review": False,
    "include_suspended": False,
    "max_per_source": 100,
    "limit_unit": "cards",
    "even": False,
    "even_notes": 20,
}

CARD_ORGANIZATION_MENU_OBJECT = "codex_learning_toolkit_card_organization_menu"


def _rgba(color, alpha: int) -> str:
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {alpha})"


class _HeightGuard(QObject):
    """Keep a dialog tall enough for its word-wrapped labels.

    Qt does not always honour height-for-width for a top-level dialog, so with
    larger system fonts the wrapped hint texts were squeezed on top of the
    controls below them.  This guard raises the dialog's minimum height to what
    the layout needs at the current width, on every show, resize and layout
    change (for example when a hint text is swapped).

    With ``content``/``footer`` the form lives in a scroll area: the dialog is
    then at most as tall as the screen and the form scrolls, so the footer
    buttons always stay reachable.
    """

    _EVENTS = (QEvent.Type.Show, QEvent.Type.Resize, QEvent.Type.LayoutRequest)

    def __init__(self, dialog: QDialog, content=None, footer=None) -> None:
        super().__init__(dialog)
        self._dialog = dialog
        self._content = content
        self._footer = footer
        self._busy = False
        dialog.installEventFilter(self)

    def _needed(self) -> int:
        outer = self._dialog.layout()
        if self._content is None or self._footer is None:
            return max(
                outer.totalMinimumSize().height(),
                outer.totalHeightForWidth(self._dialog.width()),
            )
        margins = outer.contentsMargins()
        inner_width = max(1, self._dialog.width() - margins.left() - margins.right())
        form = self._content.layout()
        form_height = max(
            form.totalMinimumSize().height(), form.totalHeightForWidth(inner_width)
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
        return needed

    def fit(self) -> None:
        if self._busy or self._dialog.layout() is None:
            return
        self._busy = True
        try:
            needed = self._needed()
            if needed > 0 and self._dialog.minimumHeight() != needed:
                self._dialog.setMinimumHeight(needed)
            if self._dialog.height() < needed:
                self._dialog.resize(self._dialog.width(), needed)
        finally:
            self._busy = False

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 (Qt API)
        if watched is self._dialog and event.type() in self._EVENTS:
            self.fit()
        return False


def _guard_height(dialog: QDialog, content=None, footer=None) -> None:
    dialog._height_guard = _HeightGuard(dialog, content, footer)
    dialog._height_guard.fit()


def _dialog_style(widget: QWidget) -> str:
    """Small adaptive style layer that follows Anki's active palette."""
    palette = widget.palette()
    window = palette.color(QPalette.ColorRole.Window)
    text = palette.color(QPalette.ColorRole.WindowText)
    base = palette.color(QPalette.ColorRole.Base)
    alternate = palette.color(QPalette.ColorRole.AlternateBase)
    muted = palette.color(QPalette.ColorRole.PlaceholderText)
    border = palette.color(QPalette.ColorRole.Mid)
    accent = palette.color(QPalette.ColorRole.Highlight)
    button = palette.color(QPalette.ColorRole.Button)
    button_text = palette.color(QPalette.ColorRole.ButtonText)
    return f"""
        QDialog#stageShifterDialog, QDialog#stageShiftPreview {{
            background: {_rgba(window, 255)};
            color: {_rgba(text, 255)};
        }}
        QLabel#dialogSubtitle, QLabel#sectionHint {{ color: {_rgba(muted, 255)}; }}
        QLabel#routeSummary, QLabel#safetyNote {{
            background: {_rgba(accent, 20)};
            border-left: 3px solid {_rgba(accent, 190)};
            border-radius: 5px;
            padding: 8px 10px;
        }}
        QLabel#totalPill {{
            background: {_rgba(accent, 30)};
            border: 1px solid {_rgba(accent, 100)};
            border-radius: 8px;
            font-weight: 700;
            padding: 5px 10px;
        }}
        QGroupBox {{
            background: {_rgba(base, 190)};
            border: 1px solid {_rgba(border, 90)};
            border-radius: 9px;
            margin-top: 12px;
            padding: 13px 10px 9px 10px;
            font-weight: 650;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 5px;
        }}
        QComboBox, QSpinBox {{
            background: {_rgba(button, 245)};
            color: {_rgba(button_text, 255)};
            border: 1px solid {_rgba(border, 110)};
            border-radius: 7px;
            padding: 5px 9px;
            min-height: 20px;
        }}
        QComboBox:disabled, QSpinBox:disabled {{
            background: transparent;
            color: {_rgba(muted, 255)};
            border: 1px dashed {_rgba(border, 90)};
        }}
        QTableWidget {{
            background: {_rgba(base, 245)};
            alternate-background-color: {_rgba(alternate, 145)};
            border: 1px solid {_rgba(border, 85)};
            border-radius: 8px;
            gridline-color: transparent;
        }}
        QTableWidget::item {{ padding: 7px 8px; }}
        QHeaderView::section {{
            background: {_rgba(alternate, 220)};
            color: {_rgba(muted, 255)};
            border: none;
            border-bottom: 1px solid {_rgba(border, 90)};
            padding: 8px;
            font-weight: 700;
        }}
    """


def _heading(text: str, *, delta: float = 5.0) -> QLabel:
    label = QLabel(text)
    font = label.font()
    size = font.pointSizeF() if font.pointSizeF() > 0 else 13.0
    font.setPointSizeF(size + delta)
    font.setWeight(QFont.Weight.Bold)
    label.setFont(font)
    return label


def _pretty_path(name: str) -> str:
    return name.replace("::", "  ›  ") if name else "Top level"


def _card_organization_menu() -> QMenu:
    return submenu(toolkit_menu(), CARD_ORGANIZATION_MENU_OBJECT, "Card Organization")


def _config() -> dict:
    config = dict(DEFAULTS)
    try:
        raw = _CFG.getConfig()
        if isinstance(raw, dict):
            config.update(raw)
    except Exception:
        pass
    for key in (
        "include_new",
        "include_learning",
        "include_review",
        "include_suspended",
    ):
        if not isinstance(config.get(key), bool):
            config[key] = DEFAULTS[key]
    if not isinstance(config.get("even"), bool):
        config["even"] = DEFAULTS["even"]
    try:
        config["even_notes"] = min(10000, max(1, int(config["even_notes"])))
    except (TypeError, ValueError, OverflowError):
        config["even_notes"] = DEFAULTS["even_notes"]
    for key in ("direction", "start_key", "stop_key", "limit_unit"):
        if not isinstance(config.get(key), str):
            config[key] = DEFAULTS[key]
    if config["direction"] not in ("toward_a", "toward_end"):
        config["direction"] = "toward_a"
    if config["limit_unit"] not in ("cards", "notes"):
        config["limit_unit"] = "cards"
    try:
        config["max_per_source"] = min(100000, max(0, int(config["max_per_source"])))
    except (TypeError, ValueError, OverflowError):
        config["max_per_source"] = 100
    return config


def _group_label(group: StageGroup) -> str:
    parent = _pretty_path(group.parent_name)
    return f"{parent}  ·  {len(group.stages)} stages  ·  {group.new_count:,} new"


def _default_group_index(groups: list[StageGroup]) -> int:
    try:
        current_name = mw.col.decks.current()["name"]
    except Exception:
        current_name = ""
    for index, group in enumerate(groups):
        if current_name == group.parent_name or current_name.startswith(
            group.parent_name + "::"
        ):
            return index
    for index, group in enumerate(groups):
        if group.parent_name.endswith("詞彙"):
            return index
    return 0


def _route_description(
    group: StageGroup,
    direction: str,
    start_key: str,
    stop_key: str,
    even_notes: int = 0,
) -> str:
    keys = [stage.key for stage in group.stages]
    if start_key not in keys or stop_key not in keys:
        return "Choose a valid start and stopping stage."
    start = keys.index(start_key)
    stop = keys.index(stop_key)
    if even_notes:
        if direction != "toward_a" or start <= stop:
            return "Even mode needs a source stage after the endpoint."
        first = group.stages[stop].label
        last = group.stages[start].label
        return (
            f"Even: the not-started notes in {first} … {last} keep their order and are "
            f"refilled to {even_notes} notes per stage. {first} gets the first "
            f"{even_notes}, the next stage the following {even_notes}, and so on; the "
            "last block holds the remainder."
        )
    if direction == "toward_a":
        source_indexes = range(start, stop, -1)
        end_note = f"{group.stages[stop].label} is the endpoint and does not move."
        direction_text = "one stage earlier"
    else:
        source_indexes = range(start, stop)
        end_note = f"{group.stages[stop].label} is the endpoint and does not move."
        direction_text = "one stage later"
    moves = [
        f"{group.stages[index].label} → "
        f"{group.stages[index - 1 if direction == 'toward_a' else index + 1].label}"
        for index in source_indexes
    ]
    return (
        f"Each matching card moves {direction_text}: "
        + "  ·  ".join(moves)
        + f"\n{end_note}"
    )


def _stage_table(plan: ShiftPlan) -> QTableWidget:
    """Even mode: notes per stage before and after."""
    table = QTableWidget(len(plan.stage_counts), 3)
    table.setHorizontalHeaderLabels(["Stage", "Before", "After"])
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(30)
    header = table.horizontalHeader()
    header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
    right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
    for row, (label, before, after) in enumerate(plan.stage_counts):
        table.setItem(row, 0, QTableWidgetItem(label))
        for column, value in ((1, before), (2, after)):
            item = QTableWidgetItem(f"{value:,}")
            item.setTextAlignment(right)
            table.setItem(row, column, item)
    return table


def _confirm_plan(plan: ShiftPlan) -> bool:
    """Show a readable, final preview before the collection operation."""
    dialog = QDialog(mw)
    dialog.setObjectName("stageShiftPreview")
    dialog.setWindowTitle("Preview Card Stage Shift")
    dialog.resize(900 if plan.stage_counts else 720, 560 if plan.stage_counts else 520)
    dialog.setMinimumSize(620, 420)
    dialog.setStyleSheet(_dialog_style(dialog))
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(18, 17, 18, 16)
    layout.setSpacing(11)
    layout.addWidget(_heading("Review the stage shift"))
    subtitle = QLabel(
        "This is the exact frozen selection that will be moved. Review it before "
        "applying the change."
    )
    subtitle.setObjectName("dialogSubtitle")
    subtitle.setWordWrap(True)
    layout.addWidget(subtitle)

    options = plan.options
    limit_label = "notes" if options.limit_unit == "notes" else "cards"
    limit_text = (
        f"even, {options.even_notes:,} notes per stage"
        if options.even
        else f"up to {options.max_per_source:,} {limit_label}"
        if options.max_per_source
        else "no limit"
    )
    summary = QLabel(
        f"<b>Deck group:</b> {_pretty_path(options.parent_name)}<br>"
        f"<b>Cards:</b> {card_type_label(options.card_types)} &nbsp;·&nbsp; "
        f"Suspended {'included' if options.include_suspended else 'excluded'} &nbsp;·&nbsp; "
        f"{'Per-stage cap' if not options.even else 'Mode'}: {limit_text}"
    )
    summary.setObjectName("routeSummary")
    summary.setWordWrap(True)
    layout.addWidget(summary)

    table = QTableWidget(len(plan.moves), 4)
    table.setHorizontalHeaderLabels(["From", "To", "Notes", "Cards"])
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(35)
    header = table.horizontalHeader()
    header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
    header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
    for row, move in enumerate(plan.moves):
        table.setItem(row, 0, QTableWidgetItem(move.source.label))
        table.setItem(row, 1, QTableWidgetItem(move.destination.label))
        note_count = QTableWidgetItem(f"{move.note_count:,}")
        note_count.setTextAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        table.setItem(row, 2, note_count)
        count = QTableWidgetItem(f"{move.count:,}")
        count.setTextAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        table.setItem(row, 3, count)
    if plan.stage_counts:
        tables = QHBoxLayout()
        tables.addWidget(_stage_table(plan), 2)
        tables.addWidget(table, 3)
        layout.addLayout(tables, 1)
    else:
        layout.addWidget(table, 1)
    if plan.warnings:
        warning = QLabel("<br>".join(plan.warnings))
        warning.setObjectName("safetyNote")
        warning.setWordWrap(True)
        layout.addWidget(warning)

    footer = QHBoxLayout()
    safety = QLabel(
        "Nothing is deleted. Scheduling and review history remain attached to "
        "each card. The complete change is one Undo step."
    )
    safety.setObjectName("sectionHint")
    safety.setWordWrap(True)
    footer.addWidget(safety, 1)
    total = QLabel(f"{plan.total_notes:,} notes · {plan.total:,} cards")
    total.setObjectName("totalPill")
    footer.addWidget(total, 0, Qt.AlignmentFlag.AlignVCenter)
    layout.addLayout(footer)

    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel
    )
    apply_button = buttons.button(QDialogButtonBox.StandardButton.Apply)
    apply_button.setText(f"Move {plan.total:,} cards from {plan.total_notes:,} notes")
    # ApplyRole buttons intentionally do not emit QDialogButtonBox.accepted.
    # Connect the concrete button so the confirmation works on Qt 6/macOS.
    qconnect(apply_button.clicked, lambda _checked=False: dialog.accept())
    qconnect(buttons.rejected, dialog.reject)
    layout.addWidget(buttons)
    _guard_height(dialog)
    return bool(dialog.exec())


def _success(result: ShiftResult) -> None:
    if not result.moved:
        showInfo("No matching cards were found. Nothing was changed.")
        return
    if result.stage_counts:
        counts = "  ·  ".join(
            f"{label.split('.')[0]}. {after:,}" for label, _before, after in result.stage_counts
        )
        showInfo(
            f"Rebalanced the queue: moved {result.moved:,} cards from "
            f"{result.moved_notes:,} notes.\n\nNotes per stage now:\n{counts}\n\n"
            "No card or note was deleted. Use Edit → Undo (or Cmd/Ctrl+Z) to reverse "
            "the complete operation."
        )
        return
    details = "\n".join(
        f"• {source} → {destination}: {note_count:,} notes · {card_count:,} cards"
        for source, destination, note_count, card_count in result.move_counts
    )
    showInfo(
        f"Moved {result.moved:,} cards from {result.moved_notes:,} notes "
        "exactly one stage.\n\n"
        f"{details}\n\n"
        "No card or note was deleted. Use Edit → Undo (or Cmd/Ctrl+Z) to reverse "
        "the complete operation."
    )


def _failure(error: Exception) -> None:
    showWarning(f"The stage shift stopped.\n\n{error}")


def _show_options(
    groups: list[StageGroup], selected_parent: str | None = None, origin=None
) -> None:
    origin = origin or (_live_collection(), _collection_epoch)
    if origin[0] is None or not _origin_ready(origin):
        return
    if not groups:
        showWarning(
            "No compatible stage-deck group was found.\n\n"
            "A compatible group contains direct sibling decks with one continuous, "
            "unambiguous sequence such as a., b., c., d."
        )
        return

    config = _config()
    dialog = QDialog(mw)
    dialog.setObjectName("stageShifterDialog")
    dialog.setWindowTitle("Card Stage Shifter")
    dialog.setMinimumWidth(660)
    dialog.setStyleSheet(_dialog_style(dialog))
    outer = QVBoxLayout(dialog)
    outer.setContentsMargins(18, 17, 18, 16)
    outer.setSpacing(11)
    scroll = QScrollArea(dialog)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    content = QWidget()
    content.setObjectName("stageShifterContent")
    scroll.setWidget(content)
    outer.addWidget(scroll, 1)
    layout = QVBoxLayout(content)
    layout.setContentsMargins(0, 0, 6, 0)
    layout.setSpacing(11)
    layout.addWidget(_heading("Card Stage Shifter"))
    intro = QLabel(
        "Move a selected set of cards exactly one step through an alphabetic "
        "deck sequence, or use Even mode to refill every stage to the same number "
        "of notes. You will see the exact counts before anything changes."
    )
    intro.setObjectName("dialogSubtitle")
    intro.setWordWrap(True)
    layout.addWidget(intro)

    route_box = QGroupBox("1. Choose the route")
    route_layout = QVBoxLayout(route_box)
    route_layout.setSpacing(8)
    form = QFormLayout()
    group_combo = QComboBox()
    for group in groups:
        group_combo.addItem(_group_label(group), group.parent_name)
    group_index = _default_group_index(groups)
    if selected_parent is not None:
        group_index = next(
            (
                index
                for index, group in enumerate(groups)
                if group.parent_name == selected_parent
            ),
            group_index,
        )
    group_combo.setCurrentIndex(group_index)

    direction_combo = QComboBox()
    direction_combo.addItem("Toward a. (earlier stage)", "toward_a")
    direction_combo.addItem("Toward the last stage", "toward_end")
    configured_index = direction_combo.findData(
        str(config.get("direction", "toward_a"))
    )
    direction_combo.setCurrentIndex(max(0, configured_index))

    start_combo = QComboBox()
    stop_combo = QComboBox()
    form.addRow("Stage-deck group:", group_combo)
    form.addRow("Move cards:", direction_combo)
    form.addRow("Begin with source stage:", start_combo)
    form.addRow("Stop before endpoint:", stop_combo)
    route_layout.addLayout(form)
    route_summary = QLabel()
    route_summary.setObjectName("routeSummary")
    route_summary.setWordWrap(True)
    route_layout.addWidget(route_summary)
    layout.addWidget(route_box)

    selection_box = QGroupBox("2. Choose which cards may move")
    selection_layout = QVBoxLayout(selection_box)
    selection_layout.setSpacing(8)
    even_check = QCheckBox("Even: refill every stage to the same number of notes")
    even_check.setToolTip(
        "Refill every stage deck (a., b., c. …) to the same number of notes, "
        "keeping the current queue order."
    )
    even_check.setChecked(bool(config["even"]))
    even_spin = QSpinBox()
    even_spin.setRange(1, 10000)
    even_spin.setValue(int(config["even_notes"]))
    even_spin.setSuffix(" notes per stage")
    even_row = QHBoxLayout()
    even_row.addWidget(even_check)
    even_row.addWidget(even_spin)
    even_row.addStretch(1)
    selection_layout.addLayout(even_row)
    even_hint = QLabel(
        "Even keeps the queue order (stage by stage, then position) and cuts it into "
        "blocks: the endpoint stage gets the first block, the next stage the second, "
        "and so on. It works with New cards toward a. and replaces the per-stage limit."
    )
    even_hint.setObjectName("sectionHint")
    even_hint.setWordWrap(True)
    selection_layout.addWidget(even_hint)
    states_hint = QLabel(
        "New-only is the safest default. Learning and review cards keep their "
        "complete scheduling history if selected."
    )
    states_hint.setObjectName("sectionHint")
    states_hint.setWordWrap(True)
    selection_layout.addWidget(states_hint)
    states_layout = QHBoxLayout()
    include_new = QCheckBox("New")
    include_new.setChecked(bool(config["include_new"]))
    include_learning = QCheckBox("Learning / Relearning")
    include_learning.setChecked(bool(config["include_learning"]))
    include_review = QCheckBox("Review")
    include_review.setChecked(bool(config["include_review"]))
    states_layout.addWidget(include_new)
    states_layout.addWidget(include_learning)
    states_layout.addWidget(include_review)
    states_layout.addStretch(1)
    selection_layout.addLayout(states_layout)

    extra_form = QFormLayout()
    include_suspended = QCheckBox(
        "Also include suspended cards that match the selected states"
    )
    include_suspended.setChecked(bool(config["include_suspended"]))
    limit_unit = QComboBox()
    limit_unit.addItem("Cards (exact card cap)", "cards")
    limit_unit.addItem("Notes (keep matching sibling cards together)", "notes")
    configured_limit_index = limit_unit.findData(str(config.get("limit_unit", "cards")))
    limit_unit.setCurrentIndex(max(0, configured_limit_index))
    maximum = QSpinBox()
    maximum.setRange(0, 100000)
    maximum.setValue(int(config["max_per_source"]))
    limit_hint = QLabel()
    limit_hint.setObjectName("sectionHint")
    limit_hint.setWordWrap(True)

    def update_limit_text() -> None:
        unit = str(limit_unit.currentData() or "cards")
        maximum.setSpecialValueText(
            "All matching notes" if unit == "notes" else "All matching cards"
        )
        maximum.setSuffix(
            " notes per source stage" if unit == "notes" else " cards per source stage"
        )
        limit_hint.setText(
            "The note limit selects up to this many notes and moves every matching "
            "card from those notes in each source stage."
            if unit == "notes"
            else "The card limit is exact and may select only some matching cards "
            "from a note when the cap is reached."
        )

    qconnect(limit_unit.currentIndexChanged, lambda _index: update_limit_text())
    update_limit_text()
    extra_form.addRow(include_suspended)
    extra_form.addRow("Limit measured by:", limit_unit)
    extra_form.addRow("Maximum per source stage:", maximum)
    selection_layout.addLayout(extra_form)
    selection_layout.addWidget(limit_hint)
    layout.addWidget(selection_box)

    hint = QLabel(
        "The endpoint itself never moves. Every selected card moves only one stage, "
        "even when several source stages are included. The final preview is read-only."
    )
    hint.setObjectName("safetyNote")
    hint.setWordWrap(True)
    layout.addWidget(hint)

    def selected_group() -> StageGroup:
        return groups[group_combo.currentIndex()]

    def update_route_summary() -> None:
        route_summary.setText(
            _route_description(
                selected_group(),
                str(direction_combo.currentData()),
                str(start_combo.currentData() or ""),
                str(stop_combo.currentData() or ""),
                even_spin.value() if even_check.isChecked() else 0,
            )
        )

    def update_stop_choices() -> None:
        group = selected_group()
        keys = [stage.key for stage in group.stages]
        start_key = str(start_combo.currentData() or "")
        if start_key not in keys:
            return
        start_index = keys.index(start_key)
        direction = str(direction_combo.currentData())
        candidates = (
            group.stages[:start_index]
            if direction == "toward_a"
            else group.stages[start_index + 1 :]
        )
        previous = str(stop_combo.currentData() or config.get("stop_key", "a"))
        stop_combo.clear()
        for stage in candidates:
            stop_combo.addItem(stage.label, stage.key)
        preferred = "a" if direction == "toward_a" else group.stages[-1].key
        index = stop_combo.findData(previous)
        if index < 0:
            index = stop_combo.findData(preferred)
        stop_combo.setCurrentIndex(max(0, index))
        update_route_summary()

    def update_start_choices() -> None:
        group = selected_group()
        direction = str(direction_combo.currentData())
        candidates = group.stages[1:] if direction == "toward_a" else group.stages[:-1]
        previous = str(start_combo.currentData() or config.get("start_key", "e"))
        start_combo.clear()
        for stage in candidates:
            start_combo.addItem(stage.label, stage.key)
        preferred = "e" if direction == "toward_a" else group.stages[0].key
        index = start_combo.findData(previous)
        if index < 0:
            index = start_combo.findData(preferred)
        start_combo.setCurrentIndex(max(0, index))
        update_stop_choices()

    qconnect(group_combo.currentIndexChanged, lambda _index: update_start_choices())
    qconnect(direction_combo.currentIndexChanged, lambda _index: update_start_choices())
    qconnect(start_combo.currentIndexChanged, lambda _index: update_stop_choices())
    qconnect(stop_combo.currentIndexChanged, lambda _index: update_route_summary())
    update_start_choices()

    normal_hint = hint.text()
    even_note = (
        "In Even mode the queue order stays the same, but a note can move more than "
        "one stage when several stages are short. The final preview shows every move "
        "and is read-only."
    )

    def apply_even_state(user_changed: bool = False) -> None:
        even = even_check.isChecked()
        if even:
            include_new.setChecked(True)
            include_learning.setChecked(False)
            include_review.setChecked(False)
            if direction_combo.currentData() != "toward_a":
                direction_combo.setCurrentIndex(max(0, direction_combo.findData("toward_a")))
            if user_changed and start_combo.count():
                start_combo.setCurrentIndex(start_combo.count() - 1)
        for widget in (include_new, include_learning, include_review, direction_combo):
            widget.setEnabled(not even)
        for widget in (limit_unit, maximum):
            widget.setEnabled(not even)
        even_spin.setEnabled(even)
        hint.setText(even_note if even else normal_hint)
        even_hint.setVisible(even)
        update_route_summary()

    qconnect(even_check.toggled, lambda _checked: apply_even_state(True))
    qconnect(even_spin.valueChanged, lambda _value: update_route_summary())
    apply_even_state(False)

    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    preview_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
    preview_button.setText("Preview card moves…")

    def validate_and_accept() -> None:
        if not (
            include_new.isChecked()
            or include_learning.isChecked()
            or include_review.isChecked()
        ):
            showWarning(
                "Choose at least one card state: New, Learning / Relearning, or Review.",
                parent=dialog,
            )
            return
        if start_combo.currentData() is None or stop_combo.currentData() is None:
            showWarning(
                "The selected route does not contain a valid source and endpoint.",
                parent=dialog,
            )
            return
        dialog.accept()

    qconnect(buttons.accepted, validate_and_accept)
    qconnect(buttons.rejected, dialog.reject)
    outer.addWidget(buttons)
    dialog.setMinimumWidth(760)
    _guard_height(dialog, content, buttons)
    if not dialog.exec():
        return
    if not _origin_ready(origin):
        return

    card_types: list[int] = []
    if include_new.isChecked():
        card_types.append(int(CARD_TYPE_NEW))
    if include_learning.isChecked():
        card_types.extend([int(CARD_TYPE_LRN), int(CARD_TYPE_RELEARNING)])
    if include_review.isChecked():
        card_types.append(int(CARD_TYPE_REV))
    if even_check.isChecked():
        card_types = [int(CARD_TYPE_NEW)]
    if not card_types:
        return

    group = selected_group()
    options = ShiftOptions(
        parent_name=group.parent_name,
        direction=str(direction_combo.currentData()),
        start_key=str(start_combo.currentData()),
        stop_key=str(stop_combo.currentData()),
        card_types=tuple(card_types),
        include_suspended=include_suspended.isChecked(),
        max_per_source=maximum.value(),
        limit_unit=str(limit_unit.currentData() or "cards"),
        even=even_check.isChecked(),
        even_notes=even_spin.value(),
    )
    config.update(
        {
            "start_key": options.start_key,
            "stop_key": options.stop_key,
            "even": options.even,
            "even_notes": options.even_notes,
        }
    )
    if not options.even:  # Even mode forces its own choices; keep the regular ones
        config.update(
            {
                "direction": options.direction,
                "include_new": include_new.isChecked(),
                "include_learning": include_learning.isChecked(),
                "include_review": include_review.isChecked(),
                "include_suspended": options.include_suspended,
                "max_per_source": options.max_per_source,
                "limit_unit": options.limit_unit,
            }
        )
    _CFG.writeConfig(__name__, config)

    def show_preview(plan: ShiftPlan) -> None:
        if not _origin_ready(origin):
            return
        if not plan.total and plan.options.even:
            showInfo(
                "Every stage already holds the right number of notes, or there is "
                "nothing to move. Nothing was changed."
            )
            return
        if not plan.total:
            showInfo(
                "No cards match the selected route and filters.\n\n"
                "Try a different source range, include another card state, or "
                "increase the per-stage limit. Nothing was changed."
            )
            return
        if not _confirm_plan(plan):
            return
        if not _origin_ready(origin):
            return
        CollectionOp(
            parent=mw, op=_checked_operation(origin, lambda col: shift_plan(col, plan))
        ).success(_success).failure(_failure).run_in_background()

    _run_query(
        QueryOp(
            parent=mw,
            op=_checked_operation(origin, lambda col: build_plan(col, options)),
            success=show_preview,
        ).failure(_failure),
        "Preparing stage-shift preview…",
    )


def start_shift() -> None:
    _load_options()


def _load_options(selected_parent: str | None = None) -> None:
    if _live_collection() is None:
        showWarning("Open a normal Anki profile before using Card Stage Shifter.")
        return
    origin = (_live_collection(), _collection_epoch)
    _run_query(
        QueryOp(
            parent=mw,
            op=_checked_operation(origin, scan_groups),
            success=lambda groups: _show_options(groups, selected_parent, origin),
        ).failure(_failure),
        "Finding stage decks…",
    )


def _add_deck_options_action(menu: QMenu, deck_id: int) -> None:
    col = _live_collection()
    if col is None:
        return
    deck = col.decks.get(deck_id, default=False)
    if not deck:
        return
    deck_name = deck["name"]
    try:
        group = next(
            (group for group in scan_groups(col) if group.parent_name == deck_name),
            None,
        )
    except Exception:
        return
    if group is None:
        return
    menu.addSeparator()
    action = menu.addAction("Card Stage Shifter…")
    if action is not None:
        qconnect(
            action.triggered,
            lambda _checked=False, parent=group.parent_name: _load_options(parent),
        )


action = QAction("Card Stage Shifter…", mw)
qconnect(action.triggered, start_shift)
_card_organization_menu().addAction(action)
gui_hooks.deck_browser_will_show_options_menu.append(_add_deck_options_action)
for _hook_name in ("profile_will_close", "collection_will_temporarily_close"):
    _hook = getattr(gui_hooks, _hook_name, None)
    if _hook is not None:
        _hook.append(_invalidate_pending)
