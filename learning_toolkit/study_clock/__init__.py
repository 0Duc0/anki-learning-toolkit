"""Study clock, idle-aware focused timer, and per-deck time dashboard."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime

from anki.consts import REVLOG_RESCHED
from aqt import gui_hooks, mw
from aqt.qt import (
    QAbstractItemView,
    QAction,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QEvent,
    QFont,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QObject,
    QPalette,
    QProgressBar,
    QPushButton,
    Qt,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTimer,
    QToolButton,
    QVBoxLayout,
    QWidget,
    qconnect,
)
from aqt.utils import askUser, tooltip

from ..common.config import SectionConfig
from ..common.menu import submenu, toolkit_menu
from .core import SessionTimer, format_duration

_CFG = SectionConfig('study_clock')


DEFAULTS = {
    "auto_start": True,
    "count_background_in_session": True,
    "show_clock": True,
    "use_24_hour_clock": True,
    "show_session": True,
    "show_active": True,
    "show_today": True,
    "show_last_answer_in_review": True,
    "show_average_answer_in_review": True,
    "idle_timeout_seconds": 120,
    "history_default_range_days": 7,
}

STUDY_MENU_OBJECT = "codex_learning_toolkit_study_clock_menu"

_timer: QTimer | None = None
_display: QToolButton | None = None
_session: SessionTimer | None = None
_dashboard: StudyTimeDialog | None = None
_activity_filter: ActivityFilter | None = None
_today_seconds = 0.0
_today_cards = 0
_last_today_refresh = 0.0
_last_answer_ms: int | None = None
_answer_total_ms = 0
_answer_count = 0
_last_recorded_revlog_id: int | None = None
_last_user_activity = 0.0
_session_deck_seconds: dict[int, float] = {}
_history_cache: dict[int, list[DeckTimeRow]] = {}
_profile_active = False
_collection_temporarily_closed = False
_statistics_error: str | None = None
_timer_failed = False


@dataclass(frozen=True)
class DeckTimeRow:
    deck_id: int | None
    deck_name: str
    seconds: float
    answers: int


class ActivityFilter(QObject):
    """Record mouse/keyboard activity so an open card is not timed forever."""

    ACTIVITY_EVENTS = frozenset(
        {
            QEvent.Type.KeyPress,
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseMove,
            QEvent.Type.Wheel,
            QEvent.Type.TouchBegin,
        }
    )

    def eventFilter(self, watched, event) -> bool:
        global _last_user_activity
        if event.type() in self.ACTIVITY_EVENTS:
            _last_user_activity = time.monotonic()
        return False


def _config() -> dict:
    try:
        raw = _CFG.getConfig() or {}
    except Exception:
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    config = dict(DEFAULTS)
    config.update(raw)

    # Version 2.2 exposed one combined switch. Read the actual saved user
    # config (not only getConfig(), which also contains new defaults) so an
    # existing disabled choice remains disabled after the split into two
    # independent controls.
    try:
        saved = _CFG.saved()
    except Exception:
        saved = dict(raw)
    legacy = saved.get("show_answer_speed_in_review")
    if legacy is not None:
        if "show_last_answer_in_review" not in saved:
            config["show_last_answer_in_review"] = bool(legacy)
        if "show_average_answer_in_review" not in saved:
            config["show_average_answer_in_review"] = bool(legacy)
    config.pop("show_answer_speed_in_review", None)
    for key, default in DEFAULTS.items():
        if isinstance(default, bool) and not isinstance(config.get(key), bool):
            config[key] = default
    try:
        config["idle_timeout_seconds"] = min(
            3600, max(0, int(config["idle_timeout_seconds"]))
        )
    except (TypeError, ValueError, OverflowError):
        config["idle_timeout_seconds"] = 120
    if config.get("history_default_range_days") not in (1, 7, 30, 90):
        config["history_default_range_days"] = 7
    return config


def _app_is_active() -> bool:
    return mw.app.applicationState() == Qt.ApplicationState.ApplicationActive


def _live_collection():
    """Return the collection only while its database is still available.

    During profile closing, Anki can clear ``col.db`` shortly before the
    profile-will-close hook tears down our one-second timer.  Keeping the
    check in one place makes every read-only statistic safe in that interval.
    """
    if _collection_temporarily_closed:
        return None
    col = getattr(mw, "col", None)
    if col is None or getattr(col, "db", None) is None:
        return None
    return col


def _deck_name(deck_id: int | None) -> str:
    if deck_id is None:
        return "Deleted / unavailable cards"
    col = _live_collection()
    if col is None:
        return f"Deck {deck_id}"
    try:
        name = col.decks.name(deck_id)
    except Exception:
        name = ""
    return name or f"Deleted / unavailable deck ({deck_id})"


def _current_review_deck_id() -> int | None:
    reviewer = getattr(mw, "reviewer", None)
    card = getattr(reviewer, "card", None)
    if card is None:
        return None
    # A filtered card retains its source deck in odid while it is being reviewed.
    source_deck = int(getattr(card, "odid", 0) or 0)
    return source_deck or int(card.did)


def _refresh_today() -> None:
    global _today_seconds, _today_cards, _last_today_refresh
    if _statistics_error is not None or getattr(mw, "_background_op_count", 0):
        return
    col = _live_collection()
    if col is None:
        _today_seconds = 0.0
        _today_cards = 0
        _last_today_refresh = time.monotonic()
        return
    try:
        cutoff_ms = (col.sched.day_cutoff - 86400) * 1000
        row = col.db.first(
            "SELECT COUNT(*), COALESCE(SUM(time), 0) FROM revlog "
            "WHERE type != ? AND id > ?",
            int(REVLOG_RESCHED),
            cutoff_ms,
        )
    except Exception as error:
        # Full sync/import/export may close the DB between the availability
        # check and this timer-driven read. Treat that interval as unavailable
        # instead of letting a Qt timer exception reach Anki's crash dialog.
        _last_today_refresh = time.monotonic()
        if _live_collection() is not None:
            _suspend_statistics(error)
        return
    cards, milliseconds = row or (0, 0)
    _today_cards = int(cards or 0)
    _today_seconds = float(milliseconds or 0) / 1000.0
    _last_today_refresh = time.monotonic()


def _history_rows(days: int, *, refresh: bool = False) -> list[DeckTimeRow]:
    if _statistics_error is not None:
        return []
    if getattr(mw, "_background_op_count", 0):
        return _history_cache.get(days, [])
    col = _live_collection()
    if col is None:
        return []
    if not refresh and days in _history_cache:
        return _history_cache[days]
    try:
        cutoff_ms = int((col.sched.day_cutoff - days * 86400) * 1000)
        rows = col.db.all(
            "SELECT CASE "
            "WHEN c.id IS NULL THEN NULL "
            "WHEN c.odid != 0 THEN c.odid "
            "ELSE c.did END AS effective_did, "
            "COUNT(*), "
            "COALESCE(SUM(CASE WHEN r.time > 0 THEN r.time ELSE 0 END), 0) "
            "FROM revlog r LEFT JOIN cards c ON c.id = r.cid "
            "WHERE r.type != ? AND r.id > ? "
            "GROUP BY effective_did ORDER BY 3 DESC, 2 DESC",
            int(REVLOG_RESCHED),
            cutoff_ms,
        )
    except Exception as error:
        if _live_collection() is not None:
            _suspend_statistics(error)
        return []
    result = [
        DeckTimeRow(
            deck_id=int(deck_id) if deck_id is not None else None,
            deck_name=_deck_name(int(deck_id) if deck_id is not None else None),
            seconds=float(milliseconds or 0) / 1000.0,
            answers=int(answers or 0),
        )
        for deck_id, answers, milliseconds in rows
    ]
    _history_cache[days] = result
    return result


def _status_clock_text(config: dict) -> str:
    """A compact clock for the narrow status bar."""
    if config["use_24_hour_clock"]:
        return datetime.now().strftime("%H:%M")
    return datetime.now().strftime("%I:%M %p").lstrip("0")


def _compact_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _answer_time_text(milliseconds: float | int | None) -> str:
    if milliseconds is None:
        return "—"
    return f"{max(0.0, float(milliseconds)) / 1000.0:.1f}s"


def _answer_average_ms() -> float | None:
    if not _answer_count:
        return None
    return _answer_total_ms / _answer_count


def _rgba(color, alpha: int) -> str:
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {alpha})"


def _set_relative_font(
    widget: QWidget,
    *,
    point_delta: float = 0.0,
    weight: QFont.Weight | None = None,
) -> None:
    font = widget.font()
    base_size = font.pointSizeF()
    if base_size <= 0:
        base_size = 13.0
    font.setPointSizeF(max(8.0, base_size + point_delta))
    if weight is not None:
        font.setWeight(weight)
    widget.setFont(font)


def _interface_style(widget: QWidget) -> str:
    """Build an adaptive stylesheet from Anki's current Qt palette."""
    palette = widget.palette()
    window = palette.color(QPalette.ColorRole.Window)
    window_text = palette.color(QPalette.ColorRole.WindowText)
    surface = palette.color(QPalette.ColorRole.Base)
    alternate = palette.color(QPalette.ColorRole.AlternateBase)
    text = palette.color(QPalette.ColorRole.Text)
    muted = palette.color(QPalette.ColorRole.PlaceholderText)
    border = palette.color(QPalette.ColorRole.Mid)
    accent = palette.color(QPalette.ColorRole.Highlight)
    accent_text = palette.color(QPalette.ColorRole.HighlightedText)
    button = palette.color(QPalette.ColorRole.Button)
    button_text = palette.color(QPalette.ColorRole.ButtonText)
    return f"""
        QDialog#studyTimeDashboard, QDialog#studyClockSettings {{
            background: {_rgba(window, 255)};
            color: {_rgba(window_text, 255)};
        }}
        QLabel#dashboardSubtitle, QLabel#summaryDetail, QLabel#summaryMeta,
        QLabel#sectionHint {{ color: {_rgba(muted, 255)}; }}
        QLabel#summaryTitle {{
            color: {_rgba(muted, 255)};
            font-weight: 700;
        }}
        QLabel#summaryValue, QLabel#sectionTitle {{
            color: {_rgba(text, 255)};
            font-weight: 700;
        }}
        QLabel#statusBadge, QLabel#totalPill {{
            background: {_rgba(accent, 28)};
            border: 1px solid {_rgba(accent, 90)};
            border-radius: 9px;
            color: {_rgba(text, 255)};
            font-weight: 600;
            padding: 4px 9px;
        }}
        QLabel#infoBox {{
            background: {_rgba(accent, 18)};
            border-left: 3px solid {_rgba(accent, 180)};
            border-radius: 5px;
            color: {_rgba(text, 235)};
            padding: 9px 11px;
        }}
        QFrame#summaryCard {{
            background: {_rgba(surface, 245)};
            border: 1px solid {_rgba(border, 105)};
            border-radius: 12px;
        }}
        QFrame#summaryAccent {{
            background: {_rgba(accent, 225)};
            border: none;
            border-radius: 2px;
        }}
        QFrame#controlBar {{
            background: {_rgba(alternate, 165)};
            border: 1px solid {_rgba(border, 85)};
            border-radius: 9px;
        }}
        QTabWidget#studyTabs::pane {{
            background: {_rgba(surface, 225)};
            border: 1px solid {_rgba(border, 95)};
            border-radius: 10px;
            top: -1px;
        }}
        QTabBar::tab {{
            background: transparent;
            color: {_rgba(muted, 255)};
            border: none;
            padding: 8px 15px;
            margin-right: 4px;
            font-weight: 600;
        }}
        QTabBar::tab:hover {{
            color: {_rgba(text, 255)};
            background: {_rgba(accent, 18)};
            border-radius: 7px;
        }}
        QTabBar::tab:selected {{
            color: {_rgba(text, 255)};
            background: {_rgba(accent, 35)};
            border-bottom: 2px solid {_rgba(accent, 230)};
            border-radius: 7px 7px 0 0;
        }}
        QTableWidget {{
            background: {_rgba(surface, 245)};
            alternate-background-color: {_rgba(alternate, 135)};
            color: {_rgba(text, 255)};
            border: 1px solid {_rgba(border, 80)};
            border-radius: 8px;
            gridline-color: transparent;
            outline: none;
        }}
        QTableWidget::item {{
            border-bottom: 1px solid {_rgba(border, 42)};
            padding: 7px 8px;
        }}
        QTableWidget::item:selected {{
            background: {_rgba(accent, 135)};
            color: {_rgba(accent_text, 255)};
        }}
        QHeaderView::section {{
            background: {_rgba(alternate, 225)};
            color: {_rgba(muted, 255)};
            border: none;
            border-bottom: 1px solid {_rgba(border, 85)};
            padding: 8px;
            font-weight: 700;
        }}
        QProgressBar {{
            background: {_rgba(alternate, 190)};
            border: none;
            border-radius: 4px;
            min-width: 88px;
            max-height: 8px;
        }}
        QProgressBar::chunk {{
            background: {_rgba(accent, 185)};
            border-radius: 4px;
        }}
        QLabel#sharePercent {{
            color: {_rgba(muted, 255)};
        }}
        QPushButton, QComboBox {{
            background: {_rgba(button, 245)};
            color: {_rgba(button_text, 255)};
            border: 1px solid {_rgba(border, 105)};
            border-radius: 7px;
            padding: 5px 10px;
            min-height: 20px;
        }}
        QPushButton:hover, QComboBox:hover {{
            background: {_rgba(accent, 28)};
            border-color: {_rgba(accent, 125)};
        }}
        QPushButton:pressed {{ background: {_rgba(accent, 52)}; }}
        QGroupBox {{
            background: {_rgba(surface, 180)};
            border: 1px solid {_rgba(border, 85)};
            border-radius: 9px;
            margin-top: 12px;
            padding: 13px 10px 8px 10px;
            font-weight: 650;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 5px;
            color: {_rgba(text, 255)};
        }}
    """


def _apply_status_style(widget: QToolButton) -> None:
    palette = widget.palette()
    surface = palette.color(QPalette.ColorRole.Base)
    text = palette.color(QPalette.ColorRole.Text)
    border = palette.color(QPalette.ColorRole.Mid)
    accent = palette.color(QPalette.ColorRole.Highlight)
    widget.setObjectName("studyClockStatus")
    widget.setStyleSheet(
        f"""
        QToolButton#studyClockStatus {{
            background: {_rgba(surface, 225)};
            color: {_rgba(text, 255)};
            border: 1px solid {_rgba(border, 90)};
            border-radius: 9px;
            padding: 4px 10px;
            font-weight: 550;
        }}
        QToolButton#studyClockStatus:hover {{
            background: {_rgba(accent, 28)};
            border-color: {_rgba(accent, 125)};
        }}
        QToolButton#studyClockStatus:pressed {{
            background: {_rgba(accent, 52)};
        }}
        """
    )


def _idle_timeout_text(seconds: int) -> str:
    if seconds <= 0:
        return "idle detection disabled"
    if seconds % 60 == 0:
        minutes = seconds // 60
        return f"{minutes} minute{'s' if minutes != 1 else ''} without input"
    return f"{seconds} seconds without input"


def _update_display() -> None:
    global _display
    try:
        _update_display_once()
    except (RuntimeError, AttributeError):
        # Qt may have already destroyed the status widget during shutdown.
        _display = None


def _update_display_once() -> None:
    if _display is None or _session is None:
        return
    config = _config()
    parts: list[str] = []
    if config["show_clock"]:
        parts.append(f"◷  {_status_clock_text(config)}")
    if config["show_session"]:
        parts.append(f"Session  {_compact_duration(_session.session_seconds)}")
    if config["show_active"]:
        parts.append(f"Focus  {_compact_duration(_session.active_seconds)}")
    if config["show_today"]:
        parts.append(
            "Today  unavailable"
            if _statistics_error
            else f"Today  {_compact_duration(_today_seconds)}"
        )
    if mw.state == "review":
        if config["show_last_answer_in_review"]:
            parts.append(f"Last  {_answer_time_text(_last_answer_ms)}")
        if config["show_average_answer_in_review"]:
            parts.append(f"Avg  {_answer_time_text(_answer_average_ms())}")
    if not parts:
        parts.append("Study Clock")
    if not _session.running:
        parts.append("Paused")
    _display.setText("   ·   ".join(parts))
    timeout_text = _idle_timeout_text(int(config["idle_timeout_seconds"]))
    answer_speed_help = ""
    if config["show_last_answer_in_review"] or config["show_average_answer_in_review"]:
        enabled = []
        if config["show_last_answer_in_review"]:
            enabled.append("Last")
        if config["show_average_answer_in_review"]:
            enabled.append("Avg")
        answer_speed_help = (
            f"<br>{' / '.join(enabled)}: Anki's capped answer timing; "
            "visible only while reviewing.<br>"
        )
    _display.setToolTip(
        "<qt><b>Study time</b><br>"
        "Session: stopwatch time since opening or resetting Anki.<br>"
        f"Focus: active review time; pauses after {timeout_text}.<br>"
        "Today: Anki's stored answer time, including earlier sessions."
        f"{answer_speed_help}<br>"
        "<b>Click to open the deck dashboard.</b>"
        + (
            "<br>Statistics paused after a database error. Reopen the profile after checking the collection."
            if _statistics_error
            else ""
        )
        + "</qt>"
    )
    toggle_action.setText("Pause Stopwatch" if _session.running else "Resume Stopwatch")


def _suspend_statistics(error: Exception) -> None:
    """One log entry, then stop DB polling until the profile is reopened."""
    global _statistics_error
    if _statistics_error is None:
        _statistics_error = str(error)
        print(f"Study Session Clock: statistics paused after a database error: {error}")
    _history_cache.clear()


def _tick() -> None:
    global _timer_failed
    if _timer_failed:
        return
    try:
        _tick_once()
    except Exception as error:
        # Never let a repeating Qt callback create an endless error-dialog loop.
        _timer_failed = True
        print(f"Study Session Clock: timer stopped after an error: {error}")
        try:
            if _timer is not None:
                _timer.stop()
            if _display is not None:
                _display.setText("Study Clock paused — reopen the profile")
        except (RuntimeError, AttributeError):
            pass


def _tick_once() -> None:
    global _last_today_refresh
    if _session is None or not _profile_active or _live_collection() is None:
        return
    now = time.monotonic()
    config = _config()
    reviewing = mw.state == "review"
    app_active = _app_is_active()
    idle_timeout = int(config["idle_timeout_seconds"])
    recently_active = idle_timeout <= 0 or now - _last_user_activity <= idle_timeout
    focused = reviewing and app_active and recently_active
    previous_tick = _session.last_tick
    was_running = _session.running
    previous_active = _session.active_seconds
    _session.tick(
        now,
        reviewing=focused,
        app_active=app_active,
        count_background=bool(config["count_background_in_session"]),
    )
    if previous_tick is not None and was_running and focused:
        deck_id = _current_review_deck_id()
        if deck_id is not None:
            elapsed = max(0.0, _session.active_seconds - previous_active)
            _session_deck_seconds[deck_id] = (
                _session_deck_seconds.get(deck_id, 0.0) + elapsed
            )
    if now - _last_today_refresh >= 15:
        _refresh_today()
    _update_display()
    _refresh_dashboard()


def _refresh_dashboard(*, history: bool = False) -> None:
    global _dashboard
    try:
        if _dashboard is not None and _dashboard.isVisible():
            _dashboard.refresh_live()
            if history:
                _dashboard.refresh_history(force=True)
    except (RuntimeError, AttributeError):
        _dashboard = None


def _summary_card(title: str, description: str) -> tuple[QFrame, QLabel, QLabel]:
    frame = QFrame()
    frame.setObjectName("summaryCard")
    frame.setMinimumHeight(126)
    outer = QHBoxLayout(frame)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)
    accent = QFrame()
    accent.setObjectName("summaryAccent")
    accent.setFixedWidth(4)
    outer.addWidget(accent)
    layout = QVBoxLayout()
    layout.setContentsMargins(15, 13, 15, 13)
    layout.setSpacing(4)
    outer.addLayout(layout, 1)
    heading = QLabel(title.upper())
    heading.setObjectName("summaryTitle")
    _set_relative_font(heading, point_delta=-1.0, weight=QFont.Weight.Bold)
    value = QLabel("00:00:00")
    value.setObjectName("summaryValue")
    _set_relative_font(value, point_delta=7.0, weight=QFont.Weight.Bold)
    meta = QLabel()
    meta.setObjectName("summaryMeta")
    _set_relative_font(meta, point_delta=-0.5)
    meta.hide()
    detail = QLabel(description)
    detail.setObjectName("summaryDetail")
    detail.setWordWrap(True)
    _set_relative_font(detail, point_delta=-1.0)
    layout.addWidget(heading)
    layout.addWidget(value)
    layout.addWidget(meta)
    layout.addWidget(detail)
    layout.addStretch(1)
    return frame, value, meta


def _prepare_table(table: QTableWidget, headers: list[str]) -> None:
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.setWordWrap(False)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(36)
    header = table.horizontalHeader()
    header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    for column in range(1, len(headers)):
        header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)


def _right_item(text: str, sort_value: float | int) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    item.setData(Qt.ItemDataRole.UserRole, sort_value)
    return item


def _empty_table(table: QTableWidget, message: str) -> None:
    table.clearSpans()
    table.clearContents()
    table.setRowCount(1)
    table.setSpan(0, 0, 1, table.columnCount())
    item = QTableWidgetItem(message)
    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    item.setForeground(table.palette().color(QPalette.ColorRole.PlaceholderText))
    font = item.font()
    font.setItalic(True)
    item.setFont(font)
    table.setItem(0, 0, item)
    table.setRowHeight(0, 92)


def _share_widget(share: float) -> QWidget:
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(8, 0, 6, 0)
    layout.setSpacing(9)
    bar = QProgressBar()
    bar.setObjectName("shareBar")
    bar.setRange(0, 1000)
    bar.setTextVisible(False)
    label = QLabel()
    label.setObjectName("sharePercent")
    label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    label.setMinimumWidth(43)
    layout.addWidget(bar, 1)
    layout.addWidget(label)
    _update_share_widget(container, share)
    return container


def _update_share_widget(container: QWidget, share: float) -> None:
    bar = container.findChild(QProgressBar, "shareBar")
    label = container.findChild(QLabel, "sharePercent")
    if bar is not None:
        bar.setValue(round(share * 1000))
    if label is not None:
        label.setText(f"{share * 100:.1f}%")


def _fill_deck_table(
    table: QTableWidget,
    rows: list[DeckTimeRow],
    *,
    show_answers: bool,
    empty_message: str = "No review time was recorded for this selection.",
) -> None:
    table.clearSpans()
    table.clearContents()
    if not rows:
        _empty_table(table, empty_message)
        return
    table.setRowCount(len(rows))
    total = sum(row.seconds for row in rows)
    for row_index, row in enumerate(rows):
        deck_item = QTableWidgetItem(row.deck_name.replace("::", "  ›  "))
        deck_item.setToolTip(row.deck_name)
        if row.deck_id is None:
            deck_item.setForeground(
                table.palette().color(QPalette.ColorRole.PlaceholderText)
            )
            font = deck_item.font()
            font.setItalic(True)
            deck_item.setFont(font)
        table.setItem(row_index, 0, deck_item)
        table.setItem(
            row_index,
            1,
            _right_item(format_duration(row.seconds), row.seconds),
        )
        share = row.seconds / total if total else 0.0
        column = 2
        if show_answers:
            table.setItem(
                row_index,
                column,
                _right_item(f"{row.answers:,}", row.answers),
            )
            column += 1
        table.setCellWidget(row_index, column, _share_widget(share))


class StudyTimeDialog(QDialog):
    def __init__(self) -> None:
        super().__init__(mw)
        self.setObjectName("studyTimeDashboard")
        self.setWindowTitle("Study Time Dashboard")
        self.resize(920, 700)
        self.setMinimumSize(780, 580)
        self.setStyleSheet(_interface_style(self))
        self._session_row_ids: tuple[int | None, ...] = ()
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 17, 18, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(12)
        title_stack = QVBoxLayout()
        title_stack.setSpacing(1)
        title = QLabel("Study time")
        title.setObjectName("dashboardTitle")
        _set_relative_font(title, point_delta=8.0, weight=QFont.Weight.Bold)
        subtitle = QLabel(
            "A clear view of this session and your recent review activity"
        )
        subtitle.setObjectName("dashboardSubtitle")
        title_stack.addWidget(title)
        title_stack.addWidget(subtitle)
        header.addLayout(title_stack)
        header.addStretch(1)
        self.state_badge = QLabel("Running")
        self.state_badge.setObjectName("statusBadge")
        self.state_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self.state_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(header)

        summary = QGridLayout()
        summary.setHorizontalSpacing(12)
        summary.setVerticalSpacing(12)
        session_frame, self.session_value, self.session_meta = _summary_card(
            "Elapsed session",
            "Stopwatch time, including breaks according to your settings.",
        )
        active_frame, self.active_value, self.active_meta = _summary_card(
            "Focused review",
            "Review-screen time with automatic idle pause.",
        )
        today_frame, self.today_value, self.today_meta = _summary_card(
            "Logged answer time today",
            "Anki's saved per-answer time, including earlier sessions.",
        )
        summary.addWidget(session_frame, 0, 0)
        summary.addWidget(active_frame, 0, 1)
        summary.addWidget(today_frame, 0, 2)
        for column in range(3):
            summary.setColumnStretch(column, 1)
        root.addLayout(summary)

        tabs = QTabWidget()
        tabs.setObjectName("studyTabs")
        tabs.addTab(self._session_tab(), "Current Session")
        tabs.addTab(self._history_tab(), "Deck History")
        root.addWidget(tabs, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        qconnect(buttons.rejected, self.reject)
        root.addWidget(buttons)
        self.refresh_live()
        self.refresh_history()

    def _session_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(9)
        heading = QLabel("Focused time by deck")
        heading.setObjectName("sectionTitle")
        _set_relative_font(heading, point_delta=1.0, weight=QFont.Weight.DemiBold)
        layout.addWidget(heading)
        timeout_text = _idle_timeout_text(int(_config()["idle_timeout_seconds"]))
        explanation = QLabel(
            "Focused time is tracked live for the current stopwatch session and "
            "split by source deck. It includes thinking and answer viewing, but "
            f"pauses after {timeout_text}."
        )
        explanation.setObjectName("sectionHint")
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        self.session_table = QTableWidget()
        _prepare_table(self.session_table, ["Deck", "Focused time", "Share"])
        layout.addWidget(self.session_table, 1)
        return page

    def _history_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)
        heading = QLabel("Recorded activity by deck")
        heading.setObjectName("sectionTitle")
        _set_relative_font(heading, point_delta=1.0, weight=QFont.Weight.DemiBold)
        layout.addWidget(heading)
        control_bar = QFrame()
        control_bar.setObjectName("controlBar")
        controls = QHBoxLayout(control_bar)
        controls.setContentsMargins(10, 7, 8, 7)
        controls.setSpacing(8)
        controls.addWidget(QLabel("Period:"))
        self.range_combo = QComboBox()
        self.range_combo.addItem("Today", 1)
        self.range_combo.addItem("Last 7 Anki days", 7)
        self.range_combo.addItem("Last 30 Anki days", 30)
        self.range_combo.addItem("Last 90 Anki days", 90)
        configured = int(_config().get("history_default_range_days", 7))
        index = self.range_combo.findData(configured)
        self.range_combo.setCurrentIndex(max(0, index))
        qconnect(self.range_combo.currentIndexChanged, self.refresh_history)
        controls.addWidget(self.range_combo)
        controls.addStretch(1)
        refresh = QPushButton("Refresh")
        qconnect(refresh.clicked, self._force_history_refresh)
        controls.addWidget(refresh)
        layout.addWidget(control_bar)

        note = QLabel(
            "This is Anki's stored answer time, capped by each deck's maximum "
            "answer time; it is not full wall-clock time. Rows use each card's "
            "current source deck. Earlier deck moves cannot be reconstructed, and "
            "deleted or unavailable cards appear separately. Anki-day boundaries "
            "follow the next-day setting, not necessarily midnight."
        )
        note.setObjectName("infoBox")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.history_table = QTableWidget()
        _prepare_table(
            self.history_table,
            ["Current deck", "Logged time", "Answers", "Share"],
        )
        layout.addWidget(self.history_table, 1)
        self.history_total = QLabel()
        self.history_total.setObjectName("totalPill")
        self.history_total.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        total_row = QHBoxLayout()
        total_row.addStretch(1)
        total_row.addWidget(self.history_total)
        layout.addLayout(total_row)
        return page

    def refresh_live(self) -> None:
        if _session is None:
            return
        self.session_value.setText(format_duration(_session.session_seconds))
        self.active_value.setText(format_duration(_session.active_seconds))
        self.today_value.setText(format_duration(_today_seconds))
        self.today_meta.setText(f"{_today_cards:,} answers in this Anki day")
        self.today_meta.show()
        self.state_badge.setText("Running" if _session.running else "Paused")
        rows = [
            DeckTimeRow(
                deck_id=deck_id,
                deck_name=_deck_name(deck_id),
                seconds=seconds,
                answers=0,
            )
            for deck_id, seconds in sorted(
                _session_deck_seconds.items(), key=lambda item: item[1], reverse=True
            )
        ]
        self._refresh_session_table(rows)

    def _refresh_session_table(self, rows: list[DeckTimeRow]) -> None:
        row_ids = tuple(row.deck_id for row in rows)
        if row_ids != self._session_row_ids:
            _fill_deck_table(
                self.session_table,
                rows,
                show_answers=False,
                empty_message=(
                    "No focused review time yet. Start reviewing and this view "
                    "will fill automatically."
                ),
            )
            self._session_row_ids = row_ids
            return
        if not rows:
            return
        total = sum(row.seconds for row in rows)
        for row_index, row in enumerate(rows):
            time_item = self.session_table.item(row_index, 1)
            if time_item is not None:
                time_item.setText(format_duration(row.seconds))
                time_item.setData(Qt.ItemDataRole.UserRole, row.seconds)
            share = row.seconds / total if total else 0.0
            share_container = self.session_table.cellWidget(row_index, 2)
            if share_container is not None:
                _update_share_widget(share_container, share)

    def refresh_history(self, *_args, force: bool = False) -> None:
        days = int(self.range_combo.currentData())
        rows = _history_rows(days, refresh=force)
        _fill_deck_table(self.history_table, rows, show_answers=True)
        seconds = sum(row.seconds for row in rows)
        answers = sum(row.answers for row in rows)
        unavailable_rows = [row for row in rows if row.deck_id is None]
        unavailable_answers = sum(row.answers for row in unavailable_rows)
        unavailable_seconds = sum(row.seconds for row in unavailable_rows)
        suffix = ""
        if unavailable_answers:
            suffix = (
                " · Unavailable: "
                f"{format_duration(unavailable_seconds)} / "
                f"{unavailable_answers:,} answers"
            )
        self.history_total.setText(
            f"Total: {format_duration(seconds)} · {answers:,} answers{suffix}"
        )

    def _force_history_refresh(self) -> None:
        self.refresh_history(force=True)


def _dashboard_finished(_result: int) -> None:
    global _dashboard
    _dashboard = None


def show_details() -> None:
    global _dashboard
    if _session is None:
        return
    if _dashboard is None:
        _dashboard = StudyTimeDialog()
        qconnect(_dashboard.finished, _dashboard_finished)
    _dashboard.refresh_live()
    _dashboard.refresh_history()
    _dashboard.show()
    _dashboard.raise_()
    _dashboard.activateWindow()


def toggle_stopwatch() -> None:
    if _session is None:
        return
    now = time.monotonic()
    if _session.running:
        _session.pause(now)
        tooltip("Study stopwatch paused.", parent=mw)
    else:
        _session.resume(now)
        tooltip("Study stopwatch resumed.", parent=mw)
    _update_display()


def reset_stopwatch() -> None:
    if _session is None:
        return
    if not askUser(
        "Reset elapsed, focused, and current-session per-deck times to 00:00:00?"
    ):
        return
    _session.reset(time.monotonic())
    _session_deck_seconds.clear()
    _reset_answer_speed()
    _update_display()
    if _dashboard is not None:
        _dashboard.refresh_live()
    tooltip("Study stopwatch reset.", parent=mw)


def open_settings() -> None:
    config = _config()
    dialog = QDialog(mw)
    dialog.setObjectName("studyClockSettings")
    dialog.setWindowTitle("Study Clock Settings")
    dialog.setMinimumWidth(560)
    dialog.setStyleSheet(_interface_style(dialog))
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(18, 17, 18, 16)
    layout.setSpacing(12)
    title = QLabel("Study Clock")
    title.setObjectName("dashboardTitle")
    _set_relative_font(title, point_delta=6.0, weight=QFont.Weight.Bold)
    layout.addWidget(title)
    intro = QLabel(
        "Choose what appears in Anki's status bar and how the elapsed/focused "
        "timers behave. These settings never alter cards or review history."
    )
    intro.setObjectName("dashboardSubtitle")
    intro.setWordWrap(True)
    layout.addWidget(intro)
    auto_start = QCheckBox("Start the stopwatch when the profile opens")
    auto_start.setChecked(bool(config["auto_start"]))
    background = QCheckBox("Include breaks while Anki is in the background")
    background.setChecked(bool(config["count_background_in_session"]))
    show_clock = QCheckBox("Show current clock time")
    show_clock.setChecked(bool(config["show_clock"]))
    use_24 = QCheckBox("Use 24-hour clock")
    use_24.setChecked(bool(config["use_24_hour_clock"]))
    show_session = QCheckBox("Show elapsed session stopwatch")
    show_session.setChecked(bool(config["show_session"]))
    show_active = QCheckBox("Show focused review time")
    show_active.setChecked(bool(config["show_active"]))
    show_today = QCheckBox("Show Anki's logged answer time today")
    show_today.setChecked(bool(config["show_today"]))
    show_last_answer = QCheckBox("Show last answer time")
    show_last_answer.setChecked(bool(config["show_last_answer_in_review"]))
    show_last_answer.setToolTip(
        "Shows Anki's capped time for the most recently answered card."
    )
    show_average_answer = QCheckBox("Show current-session average answer time")
    show_average_answer.setChecked(bool(config["show_average_answer_in_review"]))
    show_average_answer.setToolTip(
        "Average of answers since the profile opened or Current Session was reset."
    )
    show_clock.setToolTip("Current local time in the compact status pill.")
    use_24.setToolTip("Use 23:15 instead of 11:15 PM.")
    show_session.setToolTip("Elapsed stopwatch time for the current Clock session.")
    show_active.setToolTip("Idle-aware time spent on the review screen.")
    show_today.setToolTip("Anki's saved answer time for the current Anki day.")
    use_24.setEnabled(show_clock.isChecked())
    qconnect(show_clock.toggled, use_24.setEnabled)
    idle_timeout = QComboBox()
    idle_timeout.addItem("30 seconds", 30)
    idle_timeout.addItem("1 minute", 60)
    idle_timeout.addItem("2 minutes (recommended)", 120)
    idle_timeout.addItem("5 minutes", 300)
    idle_timeout.addItem("Never pause for inactivity", 0)
    timeout_index = idle_timeout.findData(int(config["idle_timeout_seconds"]))
    idle_timeout.setCurrentIndex(max(0, timeout_index))
    history_range = QComboBox()
    history_range.addItem("Today", 1)
    history_range.addItem("Last 7 Anki days", 7)
    history_range.addItem("Last 30 Anki days", 30)
    history_range.addItem("Last 90 Anki days", 90)
    range_index = history_range.findData(
        int(config.get("history_default_range_days", 7))
    )
    history_range.setCurrentIndex(max(0, range_index))
    status_group = QGroupBox("Status bar")
    status_form = QFormLayout(status_group)
    status_form.setContentsMargins(12, 13, 12, 10)
    for widget in (
        show_clock,
        use_24,
        show_session,
        show_active,
        show_today,
    ):
        status_form.addRow(widget)
    layout.addWidget(status_group)

    review_metrics_group = QGroupBox("Review-only answer timing")
    review_metrics_layout = QVBoxLayout(review_metrics_group)
    review_metrics_layout.setContentsMargins(12, 13, 12, 10)
    review_metrics_layout.setSpacing(6)
    review_metrics_layout.addWidget(show_last_answer)
    review_metrics_layout.addWidget(show_average_answer)
    review_metrics_hint = QLabel(
        "These values appear only while a card is being reviewed. They use "
        "Anki's saved, deck-capped answer times."
    )
    review_metrics_hint.setObjectName("sectionHint")
    review_metrics_hint.setWordWrap(True)
    review_metrics_layout.addWidget(review_metrics_hint)
    layout.addWidget(review_metrics_group)

    behavior_group = QGroupBox("Timer and dashboard")
    behavior_form = QFormLayout(behavior_group)
    behavior_form.setContentsMargins(12, 13, 12, 10)
    behavior_form.addRow(auto_start)
    behavior_form.addRow(background)
    behavior_form.addRow("Focused timer idle pause:", idle_timeout)
    behavior_form.addRow("Default dashboard history:", history_range)
    layout.addWidget(behavior_group)
    definitions = QLabel(
        "Elapsed is the session stopwatch. Focused is idle-aware review-screen "
        "time. Logged answer time is Anki's capped per-answer timing, so it can be "
        "lower than focused or elapsed time."
    )
    definitions.setObjectName("infoBox")
    definitions.setWordWrap(True)
    layout.addWidget(definitions)
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
    )
    qconnect(buttons.accepted, dialog.accept)
    qconnect(buttons.rejected, dialog.reject)
    layout.addWidget(buttons)
    if not dialog.exec():
        return
    config.update(
        {
            "auto_start": auto_start.isChecked(),
            "count_background_in_session": background.isChecked(),
            "show_clock": show_clock.isChecked(),
            "use_24_hour_clock": use_24.isChecked(),
            "show_session": show_session.isChecked(),
            "show_active": show_active.isChecked(),
            "show_today": show_today.isChecked(),
            "show_last_answer_in_review": show_last_answer.isChecked(),
            "show_average_answer_in_review": show_average_answer.isChecked(),
            "idle_timeout_seconds": int(idle_timeout.currentData()),
            "history_default_range_days": int(history_range.currentData()),
        }
    )
    config.pop("show_answer_speed_in_review", None)
    _CFG.writeConfig(__name__, config)
    _update_display()
    tooltip("Study clock settings saved.", parent=mw)


def _setup(*_args) -> None:
    global _timer, _display, _session, _activity_filter, _last_user_activity
    global _profile_active, _collection_temporarily_closed
    global _statistics_error, _timer_failed
    _teardown()
    _collection_temporarily_closed = False
    if _live_collection() is None:
        return
    _profile_active = True
    _statistics_error = None
    _timer_failed = False
    config = _config()
    _session = SessionTimer(running=bool(config["auto_start"]))
    _session.begin(time.monotonic())
    _last_user_activity = time.monotonic()
    _session_deck_seconds.clear()
    _reset_answer_speed()
    _history_cache.clear()
    _refresh_today()
    _activity_filter = ActivityFilter(mw.app)
    mw.app.installEventFilter(_activity_filter)
    _display = QToolButton(mw)
    _display.setAutoRaise(True)
    _display.setCursor(Qt.CursorShape.PointingHandCursor)
    _apply_status_style(_display)
    qconnect(_display.clicked, show_details)
    mw.statusBar().addPermanentWidget(_display)
    mw.statusBar().show()
    _timer = QTimer(mw)
    _timer.setInterval(1000)
    qconnect(_timer.timeout, _tick)
    _timer.start()
    _update_display()


def _teardown(*_args) -> None:
    global _timer, _display, _session, _dashboard, _activity_filter
    global _profile_active, _collection_temporarily_closed
    # Flip this first, so a queued timer callback becomes a no-op even if Qt
    # delivers it while the remaining widgets are being dismantled.
    _profile_active = False
    _collection_temporarily_closed = True
    if _timer is not None:
        try:
            _timer.stop()
            _timer.deleteLater()
        except RuntimeError:
            pass
        _timer = None
    if _activity_filter is not None:
        try:
            mw.app.removeEventFilter(_activity_filter)
            _activity_filter.deleteLater()
        except RuntimeError:
            pass
        _activity_filter = None
    if _dashboard is not None:
        try:
            _dashboard.close()
        except RuntimeError:
            pass
        _dashboard = None
    if _display is not None:
        try:
            mw.statusBar().removeWidget(_display)
            _display.deleteLater()
        except RuntimeError:
            pass
        _display = None
    _session = None
    _session_deck_seconds.clear()
    _history_cache.clear()


def _mark_review_activity(*_args) -> None:
    global _last_user_activity
    _last_user_activity = time.monotonic()


def _reset_answer_speed() -> None:
    global _last_answer_ms, _answer_total_ms, _answer_count
    global _last_recorded_revlog_id
    _last_answer_ms = None
    _answer_total_ms = 0
    _answer_count = 0
    _last_recorded_revlog_id = None


def _record_answer_speed(card) -> None:
    """Read the just-written revlog row, so values match Anki's capped timing."""
    global _last_answer_ms, _answer_total_ms, _answer_count
    global _last_recorded_revlog_id
    col = _live_collection()
    if col is None or card is None or _statistics_error is not None:
        return
    try:
        row = col.db.first(
            "SELECT id, time, type FROM revlog WHERE cid=? ORDER BY id DESC LIMIT 1",
            int(card.id),
        )
    except Exception as error:
        if _live_collection() is not None:
            _suspend_statistics(error)
        return
    if not row:
        return
    revlog_id, milliseconds, review_type = row
    revlog_id = int(revlog_id)
    if int(review_type) == int(REVLOG_RESCHED):
        return
    if revlog_id == _last_recorded_revlog_id:
        return
    value = max(0, int(milliseconds))
    _last_recorded_revlog_id = revlog_id
    _last_answer_ms = value
    _answer_total_ms += value
    _answer_count += 1


def _answer_recorded(_reviewer, _card, _ease, *_args) -> None:
    if not _profile_active or _live_collection() is None:
        return
    _mark_review_activity()
    _record_answer_speed(_card)
    _history_cache.clear()
    _refresh_today()
    _update_display()
    _refresh_dashboard(history=True)


def _state_changed(_new_state, _old_state, *_args) -> None:
    # Show/hide review-only answer metrics immediately on screen changes.
    _update_display()


def _collection_will_temporarily_close(_col=None, *_args) -> None:
    """Pause database-backed refreshes during full-sync/export close cycles."""
    global _collection_temporarily_closed
    _collection_temporarily_closed = True
    if _session is not None:
        _session.begin(time.monotonic())


def _collection_did_temporarily_close(_col=None, *_args) -> None:
    """Resume statistics after Anki has reopened the same collection."""
    global _collection_temporarily_closed, _last_today_refresh, _last_user_activity
    _collection_temporarily_closed = False
    if not _profile_active or _live_collection() is None:
        return
    if _session is not None:
        _session.begin(time.monotonic())
    _last_user_activity = 0.0
    _history_cache.clear()
    _last_today_refresh = 0.0
    _refresh_today()
    _update_display()
    _refresh_dashboard(history=True)


study_menu = submenu(toolkit_menu(), STUDY_MENU_OBJECT, "Study Clock")

details_action = QAction("Open Time Dashboard…", mw)
qconnect(details_action.triggered, show_details)
study_menu.addAction(details_action)

toggle_action = QAction("Pause Stopwatch", mw)
qconnect(toggle_action.triggered, toggle_stopwatch)
study_menu.addAction(toggle_action)

reset_action = QAction("Reset Current Session…", mw)
qconnect(reset_action.triggered, reset_stopwatch)
study_menu.addAction(reset_action)

study_menu.addSeparator()

settings_action = QAction("Settings…", mw)
qconnect(settings_action.triggered, open_settings)
study_menu.addAction(settings_action)

gui_hooks.profile_did_open.append(_setup)
gui_hooks.profile_will_close.append(_teardown)
gui_hooks.collection_will_temporarily_close.append(_collection_will_temporarily_close)
gui_hooks.collection_did_temporarily_close.append(_collection_did_temporarily_close)
gui_hooks.state_did_change.append(_state_changed)
gui_hooks.reviewer_did_show_question.append(_mark_review_activity)
gui_hooks.reviewer_did_answer_card.append(_answer_recorded)
