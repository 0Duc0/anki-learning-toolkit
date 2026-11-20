"""Escaped, self-contained HTML. No collection access."""

from html import escape
import json
from pathlib import Path

from .core import Options, Snapshot


HERE = Path(__file__).resolve().parent
CSS = (HERE / "web/panel.css").read_text(encoding="utf-8")
SCRIPT = (HERE / "web/panel.js").read_text(encoding="utf-8")


def panel_html(options: Options, snapshot: Snapshot | None, *, updating=False, error=False) -> str:
    if not options.enabled:
        return ""
    state = "Updating…" if updating else ""
    header = (
        '<header class="dp-header"><div><h2>Deck progress</h2>'
        '<p>Cards you have answered at least once</p></div><div class="dp-actions">'
        f'<span role="status" class="dp-state">{state}</span>'
        '<button type="button" data-dp-action="settings" class="dp-settings">'
        'Customize<span aria-hidden="true"> ↗</span></button></div></header>'
    )
    if error:
        return header + (
            '<div class="dp-empty">Counts are temporarily unavailable. Your cards have not changed. '
            '<button type="button" class="dp-text-button" data-dp-action="refresh">Try again</button></div>'
        )
    if not options.counters:
        return header + (
            '<div class="dp-empty"><p>Choose your decks and give each counter a name.</p>'
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
        title = [labels.get(d.id, d.name) for d in counter.decks]
        title.append("Includes subdecks." if counter.include_subdecks else "Selected decks only.")
        if counter.stage_a_only:
            title.append("Only a. stages within the selection.")
        title.append("A card counts as studied when Anki's answer count is greater than zero.")
        title.append("A note counts once if any selected card of that note has been answered.")
        title.append("Includes suspended cards." if counter.include_suspended else "Suspended cards excluded.")
        title.extend(result.problems)
        title = escape("\n".join(title), quote=True)
        no_selection = not result.deck_ids and bool(result.problems)
        is_notes = counter.unit == "notes"
        number = counts.notes if is_notes else counts.cards
        total = counts.total_notes if is_notes else counts.total_cards
        word = ("note" if number == 1 else "notes") if is_notes else ("card" if number == 1 else "cards")
        value = "—" if no_selection else f"{number:,}"
        total_html = f'<span class="dp-total"> / {total:,}</span>' if counter.show_total and not no_selection else ""
        secondary = ""
        if counter.unit == "both" and not no_selection:
            noun = "note" if counts.notes == 1 else "notes"
            secondary = f'<span class="dp-secondary">{counts.notes:,} studied {noun}</span>'
        warning = '<span class="dp-warning">Check deck selection</span>' if result.problems else ""
        tiles.append(
            f'<button type="button" class="dp-counter" data-dp-edit="{key}" title="{title}">'
            f'<span class="dp-counter-name">{name}</span><span class="dp-value">{value}{total_html}</span>'
            f'<span class="dp-unit">studied {word}</span>{secondary}{warning}</button>'
        )
    return header + '<div class="dp-grid">' + "".join(tiles) + '</div>'


def update_script(options: Options, snapshot: Snapshot | None, **status) -> str:
    payload = {"html": panel_html(options, snapshot, **status), "css": CSS}
    return "(" + SCRIPT + ")(" + json.dumps(payload, ensure_ascii=True) + ");"
