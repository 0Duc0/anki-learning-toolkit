"""Escaped, self-contained HTML. No collection access."""

from datetime import date, timedelta
from html import escape
import json
from pathlib import Path

from .core import ANSWERED_STATES, SHOWN_STATES, Estimate, Options, Snapshot, StateCounts, default_label, state_summary


HERE = Path(__file__).resolve().parent
CSS = (HERE / "web/panel.css").read_text(encoding="utf-8")
SCRIPT = (HERE / "web/panel.js").read_text(encoding="utf-8")


def _fraction(number: int, total: int) -> str:
    return f'{number:,}<span class="dp-total"> / {total:,}</span>'


def _goal_row(label: str, number: int, total: int, *, fraction: bool, bar: bool) -> str:
    value = _fraction(number, total) if fraction else ""
    track = ""
    if bar and not total:
        value += '<span class="dp-percent">No items in goal</span>'
    elif bar:
        percent = number * 100 / total
        rounded = round(percent)
        if number and rounded == 0:
            percent_text = "&lt;1%"
        elif number < total and rounded == 100:
            percent_text = "&gt;99%"
        else:
            percent_text = f"{rounded}%"
        value += f'<span class="dp-percent">{percent_text}</span>'
        track = (
            '<span class="dp-track" aria-hidden="true">'
            f'<span style="inline-size: {percent:.8g}%"></span></span>'
        )
    return (
        '<span class="dp-goal"><span class="dp-goal-line">'
        f'<span>{label}</span><span class="dp-goal-value">{value}</span></span>{track}</span>'
    )


def _states_html(options: Options, states: StateCounts) -> str:
    chips = []
    for state in SHOWN_STATES:
        number = getattr(states, state)
        if state == "suspended" and not number:
            continue
        chips.append(f'<span class="dp-st dp-{state}"><b>{number:,}</b> {escape(options.label(state))}</span>')
    return '<span class="dp-states">' + "".join(chips) + "</span>"


def _span(days: int) -> str:
    if days <= 1:
        return "about a day"
    if days < 14:
        return f"about {days} days"
    if days < 70:
        return f"about {round(days / 7)} weeks"
    if days < 730:
        return f"about {round(days / 30.4)} months"
    return f"about {days / 365:.1f} years"


def _estimate_html(estimate: Estimate | None, note: str, today: date | None = None) -> str:
    if estimate is None:
        return f'<span class="dp-estimate">{escape(note)}</span>' if note else ""
    if estimate.remaining <= 0:
        return '<span class="dp-estimate">All done 🎉</span>'
    finish = (today or date.today()) + timedelta(days=estimate.calendar_days)
    when = f"{finish.day} {finish.strftime('%b')}" + (f" {finish.year}" if finish.year != (today or date.today()).year else "")
    per = f"{estimate.per_day:.0f}" if estimate.per_day >= 10 else f"{estimate.per_day:.1f}".rstrip("0").rstrip(".")
    if estimate.mode == "fixed":
        line = f"{estimate.remaining:,} {estimate.unit} left · at {per}/day: {_span(estimate.calendar_days)} (≈ {when})"
        tip = f"Fixed pace: {per} {estimate.unit} per day."
    else:
        line = f"{estimate.remaining:,} {estimate.unit} left · at your pace: {_span(estimate.calendar_days)} (≈ {when})"
        tip = (f"Your pace: about {per} new {estimate.unit} per study day, from {estimate.basis}. "
               f"{estimate.study_days} study days still needed. Days without new {estimate.unit} don't lower the pace.")
    return f'<span class="dp-estimate" title="{escape(tip, quote=True)}">{escape(line)}</span>'


def panel_html(options: Options, snapshot: Snapshot | None, *, updating=False, error=False) -> str:
    if not options.enabled:
        return ""
    state = "Updating…" if updating else ""
    header = (
        '<header class="dp-header"><h2>Deck progress</h2><div class="dp-actions">'
        f'<span role="status" class="dp-state">{state}</span>'
        '<button type="button" data-dp-action="settings" class="dp-settings" '
        'aria-label="Deck Progress settings" title="Deck Progress settings">'
        '<span class="dp-sliders" aria-hidden="true"><i></i><i></i><i></i></span></button></div></header>'
    )
    if error:
        return header + (
            '<div class="dp-empty">Counts are temporarily unavailable. '
            '<button type="button" class="dp-text-button" data-dp-action="refresh">Try again</button></div>'
        )
    if not options.counters:
        return header + (
            '<div class="dp-empty"><p>Choose decks to track your progress.</p>'
            '<button type="button" class="dp-add" data-dp-action="settings">'
            '＋ Add your first counter</button></div>'
        )
    if snapshot is None:
        return header + '<div class="dp-empty" role="status">Loading your counters…</div>'
    labels = {deck.id: deck.name for deck in snapshot.decks}
    tiles = []
    for result in snapshot.results:
        counter, counts = result.counter, result.counts
        name, key = escape(counter.name), escape(counter.id, quote=True)
        title = ["Counter decks:", *(labels.get(d.id, d.name) for d in counter.decks)]
        title.append(f"Counter states: {state_summary(counter.counter_states)}")
        if counter.goal_decks and (counter.show_total or counter.show_progress):
            title.extend(["Additional goal decks:", *(labels.get(d.id, d.name) for d in counter.goal_decks)])
            title.append(f"Additional goal states: {state_summary(counter.goal_states)}")
            title.append("The goal total includes all counter cards and matching cards from additional goal decks.")
        if counter.unit != "cards":
            if counter.all_note_cards:
                title.append("A note needs a matching card in the counter decks. Every eligible card of that note must match, including cards in other decks.")
            else:
                title.append("A note counts once if any of its selected cards matches the filter.")
        if not counter.include_suspended:
            title.append("Ignores suspended cards.")
        if not counter.include_buried:
            title.append("Ignores buried cards.")
        if counter.show_progress:
            title.append("The percentage is the counter count divided by the goal total.")
        title.extend(result.problems)
        title = escape("\n".join(title), quote=True)
        no_selection = not result.deck_ids and bool(result.problems)
        units = ("cards", "notes") if counter.unit == "both" else (counter.unit,)
        inline_total = counter.show_total and not counter.goal_decks and not result.problems
        metrics = []
        for index, unit in enumerate(units):
            label = counter.card_label if unit == "cards" else counter.note_label
            label = escape(label or default_label(unit, counter.counter_states, all_note_cards=counter.all_note_cards))
            number = getattr(counts, unit)
            if no_selection:
                if index:
                    break
                value = "—"
            elif inline_total:
                value = _fraction(number, getattr(counts, "total_" + unit))
            else:
                value = f"{number:,}"
            kind = "dp-primary" if index == 0 else "dp-secondary"
            metrics.append(
                f'<span class="{kind}"><span class="dp-value">{value}</span>'
                f'<span class="dp-unit">{label}</span></span>'
            )
        goals = []
        goal_counts = result.goal_counts if counter.goal_decks else counts
        if goal_counts is not None and not result.problems and (counter.show_progress or (counter.show_total and counter.goal_decks)):
            kind = "goal" if counter.counter_states == ANSWERED_STATES else "share"
            for unit in units:
                noun = "Card" if unit == "cards" else "Note"
                goals.append(_goal_row(
                    f"{noun} {kind}",
                    getattr(goal_counts, unit), getattr(goal_counts, "total_" + unit),
                    fraction=bool(counter.show_total and counter.goal_decks), bar=counter.show_progress,
                ))
        goal_html = '<span class="dp-goals">' + "".join(goals) + '</span>' if goals else ""
        extra = ""
        if result.states is not None and not result.problems:
            extra += _states_html(options, result.states)
        if counter.estimate != "off" and not result.problems:
            extra += _estimate_html(result.estimate, result.estimate_note)
        warning = '<span class="dp-warning">Check deck selection</span>' if result.problems else ""
        tiles.append(
            f'<button type="button" class="dp-counter" data-dp-edit="{key}" title="{title}">'
            f'<span class="dp-counter-name">{name}</span>{"".join(metrics)}'
            f'{goal_html}{extra}{warning}</button>'
        )
    return header + '<div class="dp-grid">' + "".join(tiles) + '</div>'


def update_script(options: Options, snapshot: Snapshot | None, **status) -> str:
    payload = {"html": panel_html(options, snapshot, **status), "css": CSS}
    return "(" + SCRIPT + ")(" + json.dumps(payload, ensure_ascii=True) + ");"
