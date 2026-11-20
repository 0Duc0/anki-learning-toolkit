"""One-click Browser actions for moving selected notes to a deck."""

from __future__ import annotations

from aqt import gui_hooks, mw
from aqt.browser import Browser, SidebarItemType, SidebarTreeView
from aqt.operations import CollectionOp, QueryOp
from aqt.qt import (
    QAction,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFont,
    QFormLayout,
    QKeySequence,
    QLabel,
    QMenu,
    QPalette,
    QVBoxLayout,
    QWidget,
    qconnect,
    sip,
)
from aqt.utils import askUser, showWarning, tooltip

from ..common.config import SectionConfig
from .core import (
    NoteMovePlan,
    NoteMoveResult,
    StageDeck,
    StageGroup,
    apply_note_move_plan,
    build_note_move_plan,
    scan_stage_groups,
    target_for_deck_id,
)

_CFG = SectionConfig('note_mover')


DEFAULTS = {
    "last_parent": "",
    "last_stage": "c",
    "target_deck_id": 0,
    "last_target_name": "",
    "target_collection_path": "",
    "shortcut": "",
    "saved_shortcut": "",
    "set_target_shortcut": "",
    "warn_before_stage_reassignment": True,
}
# empty config value = this default; "none" = no shortcut
DEFAULT_SHORTCUTS = {
    "shortcut": "Ctrl+Alt+Q",                 # Move selected notes here
    "saved_shortcut": "Ctrl+Alt+S",           # Move selected notes to saved target
    "set_target_shortcut": "Ctrl+Alt+Shift+S",  # Use current deck as saved target
}
_collection_epoch = 0


def _invalidate_pending(*_args) -> None:
    global _collection_epoch
    _collection_epoch += 1


def _browser_alive(browser: Browser, expected_col=None, epoch=None) -> bool:
    try:
        col = getattr(mw, "col", None)
        return (
            not sip.isdeleted(browser)
            and col is not None
            and getattr(col, "db", None) is not None
            and getattr(browser, "col", None) is col
            and (expected_col is None or col is expected_col)
            and (epoch is None or epoch == _collection_epoch)
        )
    except (RuntimeError, AttributeError):
        return False


def _release_move(browser: Browser) -> None:
    try:
        browser._quick_note_mover_pending = False
    except RuntimeError:
        pass


def _rgba(color, alpha: int) -> str:
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {alpha})"


def _style(widget: QWidget) -> str:
    palette = widget.palette()
    window = palette.color(QPalette.ColorRole.Window)
    text = palette.color(QPalette.ColorRole.WindowText)
    muted = palette.color(QPalette.ColorRole.PlaceholderText)
    border = palette.color(QPalette.ColorRole.Mid)
    accent = palette.color(QPalette.ColorRole.Highlight)
    button = palette.color(QPalette.ColorRole.Button)
    button_text = palette.color(QPalette.ColorRole.ButtonText)
    return f"""
        QDialog#quickNoteTarget {{
            background: {_rgba(window, 255)};
            color: {_rgba(text, 255)};
        }}
        QLabel#subtitle, QLabel#hint {{ color: {_rgba(muted, 255)}; }}
        QLabel#targetSummary {{
            background: {_rgba(accent, 22)};
            border-left: 3px solid {_rgba(accent, 190)};
            border-radius: 5px;
            padding: 9px 11px;
        }}
        QComboBox {{
            background: {_rgba(button, 245)};
            color: {_rgba(button_text, 255)};
            border: 1px solid {_rgba(border, 110)};
            border-radius: 7px;
            padding: 5px 9px;
            min-height: 22px;
        }}
    """


def _heading(text: str) -> QLabel:
    label = QLabel(text)
    font = label.font()
    point_size = font.pointSizeF() if font.pointSizeF() > 0 else 13.0
    font.setPointSizeF(point_size + 5.0)
    font.setWeight(QFont.Weight.Bold)
    label.setFont(font)
    return label


def _pretty_path(name: str) -> str:
    return name.replace("::", "  ›  ") if name else "Top level"


def _config() -> dict:
    config = dict(DEFAULTS)
    try:
        raw = _CFG.getConfig()
        if isinstance(raw, dict):
            config.update(raw)
    except Exception:
        pass
    try:
        config["target_deck_id"] = max(0, int(config["target_deck_id"] or 0))
    except (TypeError, ValueError, OverflowError):
        config["target_deck_id"] = 0
    for key in (
        "last_parent",
        "last_stage",
        "last_target_name",
        "target_collection_path",
        "shortcut",
        "saved_shortcut",
        "set_target_shortcut",
    ):
        if not isinstance(config.get(key), str):
            config[key] = DEFAULTS[key]
    if not isinstance(config.get("warn_before_stage_reassignment"), bool):
        config["warn_before_stage_reassignment"] = True
    return config


def _warning_enabled() -> bool:
    return bool(_config().get("warn_before_stage_reassignment", True))


def _set_warning_enabled(enabled: bool) -> None:
    config = _config()
    config["warn_before_stage_reassignment"] = bool(enabled)
    _CFG.writeConfig(__name__, config)
    tooltip(
        "Quick Note Mover stage warning enabled."
        if enabled
        else "Quick Note Mover stage warning disabled.",
        parent=mw,
    )


def _leaf(name: str) -> str:
    return name.rsplit("::", 1)[-1] if name else "Unknown deck"


def _target_from_id(browser: Browser, deck_id: int) -> StageDeck | None:
    if not _browser_alive(browser):
        return None
    try:
        return target_for_deck_id(browser.col, int(deck_id))
    except Exception:
        return None


def _current_target(browser: Browser) -> StageDeck | None:
    try:
        return _target_from_id(browser, int(browser.col.decks.get_current_id()))
    except Exception:
        return None


def _saved_target(browser: Browser) -> StageDeck | None:
    if not _browser_alive(browser):
        return None
    config = _config()
    scope = config.get("target_collection_path", "")
    if scope and scope != str(browser.col.path):
        return None
    target_id = int(config.get("target_deck_id", 0) or 0)
    if target_id and (target := _target_from_id(browser, target_id)):
        if scope or config.get("last_target_name") == target.full_name:
            return target

    # Upgrade targets saved by Quick Note Mover 1.1 / Note Stage Mover 1.0.
    target_name = str(config.get("last_target_name", ""))
    parent_name = str(config.get("last_parent", ""))
    stage_key = str(config.get("last_stage", ""))
    for deck in browser.col.decks.all_names_and_ids(include_filtered=False):
        name = str(deck.name)
        if target_name and name == target_name:
            return _target_from_id(browser, int(deck.id))
    if parent_name and stage_key:
        for group in scan_stage_groups(browser.col):
            if group.parent_name == parent_name:
                for stage in group.stages:
                    if stage.key == stage_key.lower():
                        return stage
    return None


def _here_action_text(browser: Browser) -> str:
    target = _current_target(browser)
    suffix = _leaf(target.full_name) if target else "current deck unavailable"
    return f"Move selected notes here → {suffix}"


def _saved_action_text(browser: Browser) -> str:
    target = _saved_target(browser)
    suffix = _leaf(target.full_name) if target else "set target first"
    return f"Move selected notes to saved target → {suffix}"


def _shortcut(key: str = "shortcut") -> QKeySequence:
    configured = str(_config().get(key, "")).strip()
    if configured.lower() in {"none", "off", "-"}:
        return QKeySequence()
    if configured:
        return QKeySequence(configured)
    return QKeySequence(DEFAULT_SHORTCUTS[key])


def _default_group_index(groups: tuple[StageGroup, ...], config: dict) -> int:
    configured = str(config.get("last_parent", ""))
    for index, group in enumerate(groups):
        if group.parent_name == configured:
            return index
    for index, group in enumerate(groups):
        if group.parent_name.endswith("詞彙"):
            return index
    return 0


def _choose_target(
    browser: Browser,
    groups: tuple[StageGroup, ...],
    *,
    move_after_save: bool = False,
) -> StageDeck | None:
    if not groups:
        showWarning(
            "No compatible stage-deck group was found.\n\n"
            "A compatible group contains direct sibling decks named a., b., c., "
            "and so on without gaps.",
            parent=browser,
        )
        return None

    config = _config()
    dialog = QDialog(browser)
    dialog.setObjectName("quickNoteTarget")
    dialog.setWindowTitle("Set Quick-Move Target")
    dialog.setMinimumWidth(630)
    dialog.setStyleSheet(_style(dialog))
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(18, 17, 18, 16)
    layout.setSpacing(11)
    layout.addWidget(_heading("Choose the permanent quick target"))

    subtitle = QLabel(
        
            "Choose this once. The current selection will move immediately after "
            "saving; later saved-target moves use it without another dialog."
            if move_after_save
            else "Choose this once. Afterwards the saved-target action moves "
            "selected notes here immediately. The shortcut always uses Anki's "
            "current deck."
        
    )
    subtitle.setObjectName("subtitle")
    subtitle.setWordWrap(True)
    layout.addWidget(subtitle)

    form = QFormLayout()
    group_combo = QComboBox()
    for group in groups:
        group_combo.addItem(
            f"{_pretty_path(group.parent_name)}  ·  {len(group.stages)} stages",
            group.parent_name,
        )
    group_combo.setCurrentIndex(_default_group_index(groups, config))
    target_combo = QComboBox()
    form.addRow("Stage-deck group:", group_combo)
    form.addRow("Permanent target:", target_combo)
    layout.addLayout(form)

    summary = QLabel()
    summary.setObjectName("targetSummary")
    summary.setWordWrap(True)
    layout.addWidget(summary)

    def selected_group() -> StageGroup:
        return groups[group_combo.currentIndex()]

    def update_summary(_index: int = -1) -> None:
        index = target_combo.currentIndex()
        group = selected_group()
        if 0 <= index < len(group.stages):
            stage = group.stages[index]
            summary.setText(
                f"Future quick moves will send every card belonging to the "
                f"selected notes directly to <b>{_pretty_path(stage.full_name)}</b>."
            )

    def update_targets(_index: int = -1) -> None:
        group = selected_group()
        preferred = str(config.get("last_stage", "c"))
        target_combo.clear()
        for stage in group.stages:
            target_combo.addItem(stage.label, stage.key)
        preferred_index = next(
            (
                index
                for index, stage in enumerate(group.stages)
                if stage.key == preferred
            ),
            0,
        )
        target_combo.setCurrentIndex(preferred_index)
        update_summary()

    qconnect(group_combo.currentIndexChanged, update_targets)
    qconnect(target_combo.currentIndexChanged, update_summary)
    update_targets()

    hint = QLabel(
        "Quick moves have no extra preview, but remain one Undo step. Cards in "
        "filtered decks are rejected instead of being moved unexpectedly."
    )
    hint.setObjectName("hint")
    hint.setWordWrap(True)
    layout.addWidget(hint)

    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
    )
    save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
    save_button.setText(
        "Set target and move now" if move_after_save else "Save quick target"
    )
    qconnect(buttons.accepted, dialog.accept)
    qconnect(buttons.rejected, dialog.reject)
    layout.addWidget(buttons)
    if not dialog.exec():
        return None

    group = selected_group()
    stage_index = target_combo.currentIndex()
    if stage_index < 0 or stage_index >= len(group.stages):
        return None
    return group.stages[stage_index]


def _save_target(stage: StageDeck) -> None:
    parent_name = stage.full_name.rsplit("::", 1)[0] if "::" in stage.full_name else ""
    config = _config()
    config.update(
        {
            "last_parent": parent_name,
            "last_stage": stage.key,
            "target_deck_id": stage.deck_id,
            "last_target_name": stage.full_name,
            "target_collection_path": str(mw.col.path)
            if getattr(mw, "col", None) is not None
            else "",
        }
    )
    _CFG.writeConfig(__name__, config)


def _refresh_actions(browser: Browser) -> None:
    if not _browser_alive(browser):
        return
    here_action = getattr(browser, "_quick_note_mover_here_action", None)
    if here_action is not None:
        here_action.setText(_here_action_text(browser))
        here_action.setEnabled(_current_target(browser) is not None)
    saved_action = getattr(browser, "_quick_note_mover_saved_action", None)
    if saved_action is not None:
        saved_action.setText(_saved_action_text(browser))
        # stays enabled: without a saved target it asks for one, so its shortcut keeps working
        saved_action.setEnabled(True)


def _show_result(_browser: Browser, result: NoteMoveResult) -> None:
    _release_move(_browser)
    if not _browser_alive(_browser):
        return
    if not result.moved_cards:
        tooltip(
            f"Already in {_pretty_path(result.destination_name)} — nothing moved.",
            parent=mw,
        )
        return
    tooltip(
        f"Quick moved {result.moved_notes:,} notes · {result.moved_cards:,} cards "
        f"to {_pretty_path(result.destination_name)}. Undo: Cmd/Ctrl+Z.",
        parent=mw,
    )


def _failure(_browser: Browser, error: Exception) -> None:
    _release_move(_browser)
    # Always report: a failed move (or an unconfirmed rollback) must never be
    # silent just because the Browser was closed while the operation ran.
    # The main window remains a stable parent for result/error feedback.
    showWarning(f"The quick move stopped.\n\n{error}", parent=mw)


def _apply_frozen_plan(browser: Browser, plan: NoteMovePlan) -> None:
    if not _browser_alive(browser):
        _release_move(browser)
        return
    origin_col = browser.col
    epoch = _collection_epoch

    def operation(col):
        if col is not origin_col or epoch != _collection_epoch:
            raise RuntimeError(
                "The profile changed before the move. Nothing was changed."
            )
        return apply_note_move_plan(col, plan)

    # CollectionOp already shows Anki's native progress window.  Unlike QueryOp,
    # CollectionOp has no with_progress() method in Anki 25.09.x.  Keeping the
    # operation chain to the stable, documented methods also makes this work on
    # both older and newer Anki releases.
    # Use the main window as the operation parent; the Browser may be closed or
    # rebuilt while the background operation finishes.
    operation_handle = (
        CollectionOp(parent=mw, op=operation)
        .success(lambda result: _show_result(browser, result))
        .failure(lambda error: _failure(browser, error))
    )

    # The initiator keyword lets the Browser refresh itself efficiently, but it
    # did not exist in every older CollectionOp implementation.  Feature-detect
    # the call signature instead of crashing if Anki changes it again.
    try:
        browser_is_alive = not sip.isdeleted(browser)
    except (AttributeError, RuntimeError):
        browser_is_alive = False
    if browser_is_alive:
        try:
            operation_handle.run_in_background(initiator=browser)
            return
        except TypeError as error:
            if "initiator" not in str(error):
                raise
    operation_handle.run_in_background()


def _confirm_stage_reassignment(plan: NoteMovePlan) -> bool:
    warning = plan.stage_warning
    if warning is None or not _warning_enabled():
        return True

    details = "\n".join(
        f"• {_leaf(source.deck_name)} — {source.note_count:,} note(s) · "
        f"{source.card_count:,} card(s)"
        for source in warning.sources
    )
    message = (
        "Some selected cards are already assigned to another stage in this "
        "deck group.\n\n"
        f"Deck group: {_pretty_path(warning.parent_name)}\n"
        f"Destination: {_leaf(warning.destination_name)}\n"
        f"Affected: {warning.affected_note_count:,} note(s) · "
        f"{warning.affected_card_count:,} card(s)\n\n"
        f"{details}\n\n"
        "Quick Move will reassign these cards to the destination. Continue?\n\n"
        "You can disable this warning under Tools → Quick Note Mover → "
        "Warn before moving between stages."
    )
    try:
        return bool(
            askUser(
                message,
                parent=mw,
                defaultno=True,
                title="Quick Note Mover",
            )
        )
    except TypeError:
        # Older compatible Anki versions did not expose the optional title.
        return bool(askUser(message, parent=mw, defaultno=True))


def _move_to_target(
    browser: Browser, note_ids: tuple[int, ...], destination: StageDeck
) -> None:
    if not _browser_alive(browser):
        _release_move(browser)
        return
    origin_col = browser.col
    epoch = _collection_epoch

    def plan_ready(plan: NoteMovePlan) -> None:
        if not _browser_alive(browser, origin_col, epoch):
            _release_move(browser)
            return
        if _confirm_stage_reassignment(plan) and _browser_alive(
            browser, origin_col, epoch
        ):
            _apply_frozen_plan(browser, plan)
        else:
            _release_move(browser)

    def prepare(col):
        if col is not origin_col or epoch != _collection_epoch:
            raise RuntimeError(
                "The profile changed before the move. Nothing was changed."
            )
        return build_note_move_plan(col, note_ids, destination.deck_id)

    # Plan in the background, confirm on the GUI thread, then apply the exact
    # frozen plan. apply_note_move_plan() verifies that neither the destination
    # nor any selected card changed while the warning was visible.
    QueryOp(
        parent=mw,
        op=prepare,
        success=plan_ready,
    ).failure(lambda error: _failure(browser, error)).run_in_background()


def _with_selected_notes(browser: Browser, callback) -> None:
    if not _browser_alive(browser) or getattr(
        browser, "_quick_note_mover_pending", False
    ):
        return
    origin_col = browser.col
    epoch = _collection_epoch
    note_ids = tuple(int(note_id) for note_id in browser.selected_notes())
    if not note_ids:
        showWarning("Select one or more notes first.", parent=mw)
        return
    browser._quick_note_mover_pending = True

    def after_editor_saved() -> None:
        if not _browser_alive(browser, origin_col, epoch):
            _release_move(browser)
            return
        try:
            callback(note_ids)
        except Exception as error:
            _failure(browser, error)

    try:
        editor = getattr(browser, "editor", None)
        save_then = getattr(editor, "call_after_note_saved", None)
        if editor is not None and not callable(save_then):
            raise RuntimeError(
                "This Anki version cannot safely save the editor. Nothing was moved."
            )
        if callable(save_then):
            save_then(after_editor_saved)
        else:
            after_editor_saved()
    except Exception as error:
        _failure(browser, error)


def _quick_move_to_target(browser: Browser, destination: StageDeck) -> None:
    _with_selected_notes(
        browser,
        lambda note_ids: _move_to_target(browser, note_ids, destination),
    )


def _quick_move_here(browser: Browser) -> None:
    destination = _current_target(browser)
    if destination is None:
        showWarning(
            "The current deck is unavailable or filtered. Select a normal deck "
            "on Anki's main screen first.",
            parent=browser,
        )
        return
    _quick_move_to_target(browser, destination)


def _quick_move_saved(browser: Browser) -> None:
    destination = _saved_target(browser)
    if destination is not None:
        # Persist an upgraded ID/name if this target came from an older config.
        _save_target(destination)
        _refresh_actions(browser)
        _quick_move_to_target(browser, destination)
        return

    def after_selected(note_ids: tuple[int, ...]) -> None:
        origin_col = browser.col
        epoch = _collection_epoch

        def choose_and_move(groups: tuple[StageGroup, ...]) -> None:
            if not _browser_alive(browser, origin_col, epoch):
                _release_move(browser)
                return
            selected = _choose_target(browser, groups, move_after_save=True)
            if selected is None:
                _release_move(browser)
                return
            _save_target(selected)
            _refresh_actions(browser)
            _move_to_target(browser, note_ids, selected)

        QueryOp(
            parent=mw,
            op=scan_stage_groups,
            success=choose_and_move,
        ).failure(lambda error: _failure(browser, error)).run_in_background()

    _with_selected_notes(browser, after_selected)


def _configure_target(browser: Browser) -> None:
    if not _browser_alive(browser):
        return
    origin_col = browser.col
    epoch = _collection_epoch

    def choose(groups: tuple[StageGroup, ...]) -> None:
        if not _browser_alive(browser, origin_col, epoch):
            return
        destination = _choose_target(browser, groups)
        if destination is None:
            return
        _save_target(destination)
        _refresh_actions(browser)
        tooltip(
            f"Quick-move target: {_pretty_path(destination.full_name)}",
            parent=mw,
        )

    QueryOp(parent=mw, op=scan_stage_groups, success=choose).failure(
        lambda error: _failure(browser, error)
    ).run_in_background()


def _use_current_as_target(browser: Browser) -> None:
    destination = _current_target(browser)
    if destination is None:
        showWarning(
            "The current deck is unavailable or filtered. Select a normal deck "
            "on Anki's main screen first.",
            parent=browser,
        )
        return
    _save_target(destination)
    _refresh_actions(browser)
    tooltip(
        f"Quick-move target: {_pretty_path(destination.full_name)}",
        parent=mw,
    )


def _use_specific_as_target(browser: Browser, destination: StageDeck) -> None:
    _save_target(destination)
    _refresh_actions(browser)
    tooltip(
        f"Quick-move target: {_pretty_path(destination.full_name)}",
        parent=mw,
    )


def _add_browser_menu(browser: Browser) -> None:
    menu = QMenu("Quick Note Move", browser.form.menu_Notes)
    browser.form.menu_Notes.addSeparator()
    browser.form.menu_Notes.addMenu(menu)
    qconnect(menu.aboutToShow, lambda: _refresh_actions(browser))

    here_action = QAction(_here_action_text(browser), menu)
    here_action.setShortcut(_shortcut())
    qconnect(here_action.triggered, lambda _checked=False: _quick_move_here(browser))
    menu.addAction(here_action)
    browser._quick_note_mover_here_action = here_action

    saved_action = QAction(_saved_action_text(browser), menu)
    saved_action.setShortcut(_shortcut("saved_shortcut"))
    qconnect(saved_action.triggered, lambda _checked=False: _quick_move_saved(browser))
    menu.addAction(saved_action)
    browser._quick_note_mover_saved_action = saved_action

    menu.addSeparator()
    current_target_action = QAction("Use current deck as saved target", menu)
    current_target_action.setShortcut(_shortcut("set_target_shortcut"))
    qconnect(
        current_target_action.triggered,
        lambda _checked=False: _use_current_as_target(browser),
    )
    menu.addAction(current_target_action)

    target_action = QAction("Choose another saved target…", menu)
    qconnect(
        target_action.triggered,
        lambda _checked=False: _configure_target(browser),
    )
    menu.addAction(target_action)


def _add_context_action(browser: Browser, menu: QMenu) -> None:
    if not _browser_alive(browser):
        return
    note_count = len(browser.selected_notes())
    if not note_count:
        return
    note_label = "note" if note_count == 1 else "notes"
    actions: list[QAction] = []
    current = _current_target(browser)
    if current is not None:
        here = QAction(
            f"Quick move {note_count:,} selected {note_label} here → "
            f"{_leaf(current.full_name)}",
            menu,
        )
        qconnect(
            here.triggered,
            lambda _checked=False, target=current: _quick_move_to_target(
                browser, target
            ),
        )
        actions.append(here)

    saved = _saved_target(browser)
    if saved is not None and (current is None or saved.deck_id != current.deck_id):
        preset = QAction(
            f"Quick move {note_count:,} selected {note_label} → saved "
            f"{_leaf(saved.full_name)}",
            menu,
        )
        qconnect(
            preset.triggered,
            lambda _checked=False, target=saved: _quick_move_to_target(browser, target),
        )
        actions.append(preset)

    if not actions:
        return
    existing = menu.actions()
    if existing:
        for action in actions:
            menu.insertAction(existing[0], action)
        menu.insertSeparator(existing[0])
    else:
        for action in actions:
            menu.addAction(action)


def _add_sidebar_context_actions(
    sidebar: SidebarTreeView, menu: QMenu, item, _index
) -> None:
    if item.item_type not in (SidebarItemType.DECK, SidebarItemType.DECK_CURRENT):
        return
    try:
        destination = target_for_deck_id(sidebar.col, int(item.id))
    except Exception:
        return

    browser = sidebar.browser
    note_count = len(browser.selected_notes())
    note_label = "note" if note_count == 1 else "notes"
    menu.addSeparator()

    move_action = QAction(
        f"Quick move {note_count:,} selected {note_label} here → "
        f"{_leaf(destination.full_name)}",
        menu,
    )
    move_action.setEnabled(bool(note_count))
    qconnect(
        move_action.triggered,
        lambda _checked=False, target=destination: _quick_move_to_target(
            browser, target
        ),
    )
    menu.addAction(move_action)

    target_action = QAction("Use this deck as saved quick target", menu)
    qconnect(
        target_action.triggered,
        lambda _checked=False, target=destination: _use_specific_as_target(
            browser, target
        ),
    )
    menu.addAction(target_action)


def _install_tools_menu() -> None:
    """Add one compact, persistent safety setting to Anki's Tools menu."""
    if getattr(mw, "_quick_note_mover_tools_menu", None) is not None:
        return
    from ..common.menu import submenu, toolkit_menu

    organize = submenu(toolkit_menu(), "codex_learning_toolkit_card_organization_menu", "Card Organization")
    menu = QMenu("Quick Note Mover", organize)
    warning_action = QAction("Warn before moving between stages", menu)
    warning_action.setCheckable(True)
    warning_action.setChecked(_warning_enabled())
    warning_action.setStatusTip(
        "Ask before cards are reassigned from one a./b./… stage deck to "
        "another stage in the same deck group."
    )
    qconnect(
        warning_action.triggered,
        lambda checked=False: _set_warning_enabled(bool(checked)),
    )
    menu.addAction(warning_action)
    organize.addMenu(menu)
    mw._quick_note_mover_tools_menu = menu
    mw._quick_note_mover_warning_action = warning_action


_install_tools_menu()
gui_hooks.browser_menus_did_init.append(_add_browser_menu)
gui_hooks.browser_will_show_context_menu.append(_add_context_action)
gui_hooks.browser_sidebar_will_show_context_menu.append(_add_sidebar_context_actions)
for _hook_name in ("profile_will_close", "collection_will_temporarily_close"):
    _hook = getattr(gui_hooks, _hook_name, None)
    if _hook is not None:
        _hook.append(_invalidate_pending)
