"""Change Deck: right-click menu entry + New / Learn / Due counts in the dialog.

Small, display-only additions to the Anki browser:

1. "Change Deck..." is shown in the notes/cards right-click menu, directly under
   the "Quick move ..." lines (or at the top when there are none). It is Anki's
   own Change Deck action, so shortcut, selection handling and undo are unchanged.
2. The browser's Change Deck dialog shows New / Learn / Due next to every deck,
   coloured like the main deck list. The numbers come from the same scheduler
   call the main screen uses (``col.sched.deck_due_tree()``). A fourth, grey
   column shows how many notes (not cards) the deck holds, subdecks included.

The add-on never moves cards or touches the collection itself. If anything in
here fails, it logs to stderr and the stock Anki behaviour is left untouched.
"""

from __future__ import annotations

import sys
import traceback
from typing import Optional

from aqt import gui_hooks
from aqt.browser import Browser
from aqt.qt import (
    QApplication, QColor, QFontMetrics, QMenu, QPainter, QPalette, QRect, QStyle, QStyledItemDelegate,
    QStyleOptionViewItem, Qt, QWidget, qconnect,
)
from aqt.studydeck import StudyDeck
from aqt.utils import tr

# Text that the quick-move add-on's menu lines start with (compared lower-case).
QUICK_MOVE_PREFIX = "quick move"

# Item data roles: the (new, learn, due) tuple and the note count of a list row.
COUNTS_ROLE = Qt.ItemDataRole.UserRole.value + 1
NOTES_ROLE = Qt.ItemDataRole.UserRole.value + 2

# Same hues as the main deck list: blue = new, red = learn, green = due.
COLORS_LIGHT = ("#0000ee", "#cc0000", "#008800")
COLORS_DARK = ("#7aa7ff", "#ff7a7a", "#5fd38d")
ZERO_COLOR = "#808080"


def _log(what: str) -> None:
    print(f"[change_deck_counts] {what}\n{traceback.format_exc()}", file=sys.stderr)


# ---------------------------------------------------------------------------
# 1. Menu entry
# ---------------------------------------------------------------------------


def _place_change_deck(browser: Browser, menu: QMenu) -> None:
    """Put Anki's Change Deck action under the last 'Quick move' line."""
    try:
        action = browser.form.actionChange_Deck
        actions = menu.actions()
        if action in actions:  # cards mode already lists it at the top level
            return
        last_quick = -1
        for i, act in enumerate(actions):
            if act.text().replace("&", "").strip().lower().startswith(QUICK_MOVE_PREFIX):
                last_quick = i
        # insert before whatever follows the quick-move block (or before the
        # first entry when there is no such block); None appends at the end
        pos = last_quick + 1
        before = actions[pos] if pos < len(actions) else None
        menu.insertAction(before, action)
    except Exception:
        _log("could not add the Change Deck entry")


def _on_context_menu(browser: Browser, menu: QMenu) -> None:
    # Other add-ons add their lines in this same hook, in an order we do not
    # control. aboutToShow fires after all of them, so we can place ourselves
    # relative to their lines.
    qconnect(menu.aboutToShow, lambda: _place_change_deck(browser, menu))


# ---------------------------------------------------------------------------
# 2. Counts in the Change Deck dialog
# ---------------------------------------------------------------------------


def _deck_counts(mw) -> dict[str, tuple[int, int, int]]:
    """full deck name -> (new, learn, due), as shown on the main screen."""
    out: dict[str, tuple[int, int, int]] = {}

    def walk(node, prefix: str) -> None:
        for child in node.children:
            full = f"{prefix}::{child.name}" if prefix else child.name
            out[full] = (child.new_count, child.learn_count, child.review_count)
            walk(child, full)

    walk(mw.col.sched.deck_due_tree(), "")
    return out


def _note_counts(col) -> dict[str, int]:
    """full deck name -> number of distinct notes with a card in it (subdecks included).

    Exact, and cheap on big collections: one grouped query for the decks
    themselves, plus a correction for the (rare) notes whose cards sit in more
    than one deck, so parent decks never count such a note twice.
    """
    ids = {d.name: d.id for d in col.decks.all_names_and_ids(include_filtered=False)}
    direct = dict(col.db.all("select did, count(distinct nid) from cards group by did"))
    spread: dict[int, set[int]] = {}
    for nid, did in col.db.all(
        "select nid, did from cards where nid in "
        "(select nid from cards group by nid having count(distinct did) > 1)"
    ):
        spread.setdefault(nid, set()).add(did)
    names = sorted(ids)
    out: dict[str, int] = {}
    for name in names:
        prefix = name + "::"
        family = {ids[n] for n in names if n == name or n.startswith(prefix)}
        total = sum(direct.get(d, 0) for d in family)
        if len(family) > 1:
            for decks in spread.values():
                overlap = len(decks & family)
                if overlap > 1:
                    total -= overlap - 1
        out[name] = total
    return out


def _notes_text(count: int) -> str:
    return f"{count:,} note" if count == 1 else f"{count:,} notes"


def _is_browser_change_deck(dialog: StudyDeck) -> bool:
    return isinstance(dialog.parent(), Browser) and (
        dialog.windowTitle() == tr.browsing_change_deck()
    )


def _night_mode() -> bool:
    try:
        from aqt.theme import theme_manager

        return bool(theme_manager.night_mode)
    except Exception:
        return False


class CountsDelegate(QStyledItemDelegate):
    """Draws the deck name on the left and three right-aligned count columns."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.colors = COLORS_DARK if _night_mode() else COLORS_LIGHT

    def _column_width(self, metrics: QFontMetrics) -> int:
        return metrics.horizontalAdvance("00000") + 10

    def _notes_width(self, metrics: QFontMetrics) -> int:
        return metrics.horizontalAdvance("000,000 notes") + 18

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        counts = index.data(COUNTS_ROLE)
        if not counts:
            super().paint(painter, option, index)
            return

        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text = opt.text
        opt.text = ""
        widget = opt.widget
        style = widget.style() if widget else QApplication.style()
        # background, selection highlight and focus frame, without the text
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)

        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        text_color = opt.palette.color(
            QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text
        )
        col_w = self._column_width(opt.fontMetrics)
        notes = index.data(NOTES_ROLE)
        notes_w = self._notes_width(opt.fontMetrics) if notes is not None else 0
        rect = opt.rect.adjusted(6, 0, -6, 0)
        notes_left = rect.right() - notes_w + 1
        counts_left = notes_left - 3 * col_w
        name_rect = QRect(rect.left(), rect.top(), counts_left - rect.left() - 8, rect.height())

        painter.save()
        painter.setFont(opt.font)
        painter.setPen(text_color)
        elided = opt.fontMetrics.elidedText(
            text, Qt.TextElideMode.ElideMiddle, max(name_rect.width(), 10)
        )
        painter.drawText(
            name_rect,
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            elided,
        )
        for i, value in enumerate(counts):
            cell = QRect(counts_left + i * col_w, rect.top(), col_w, rect.height())
            if selected:
                painter.setPen(text_color)
            else:
                painter.setPen(QColor(self.colors[i] if value else ZERO_COLOR))
            painter.drawText(
                cell,
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight),
                str(value),
            )
        if notes is not None:
            painter.setPen(text_color if selected else QColor(ZERO_COLOR))
            painter.drawText(
                QRect(notes_left, rect.top(), notes_w, rect.height()),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight),
                _notes_text(int(notes)),
            )
        painter.restore()


def _decorate(dialog: StudyDeck) -> None:
    lst = dialog.form.list
    counts = getattr(dialog, "_cdc_counts", None)
    if counts is None:
        counts = _deck_counts(dialog.mw)
        dialog._cdc_counts = counts
    if getattr(dialog, "_cdc_delegate", None) is None:
        dialog._cdc_delegate = CountsDelegate(lst)
        lst.setItemDelegate(dialog._cdc_delegate)
        dialog.setMinimumWidth(max(dialog.minimumWidth(), 640))
    notes = getattr(dialog, "_cdc_notes", None)
    if notes is None:
        try:
            notes = _note_counts(dialog.mw.col)
        except Exception:
            _log("could not count the notes per deck")
            notes = {}
        dialog._cdc_notes = notes
    for row, name in enumerate(dialog.names):
        item = lst.item(row)
        values = counts.get(name)
        if item is None or values is None:
            continue
        item.setData(COUNTS_ROLE, values)
        tip = f"{name}\nNew {values[0]} · Learn {values[1]} · Due {values[2]}"
        if name in notes:
            item.setData(NOTES_ROLE, notes[name])
            tip += f" · {_notes_text(notes[name])}"
        item.setToolTip(tip)


_original_redraw = StudyDeck.redraw


def _redraw_with_counts(self: StudyDeck, filt: str, focus: Optional[str] = None) -> None:
    _original_redraw(self, filt, focus)  # stock behaviour first, always
    try:
        if _is_browser_change_deck(self):
            _decorate(self)
    except Exception:
        _log("could not add the counts to the Change Deck dialog")


def _install() -> None:
    if getattr(StudyDeck, "_cdc_patched", False):
        return
    StudyDeck.redraw = _redraw_with_counts  # type: ignore[method-assign]
    StudyDeck._cdc_patched = True  # type: ignore[attr-defined]
    gui_hooks.browser_will_show_context_menu.append(_on_context_menu)


_install()
