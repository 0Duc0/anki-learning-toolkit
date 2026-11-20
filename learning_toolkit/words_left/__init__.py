"""Words Left – shows how many words (notes) you have not started yet.

Adds a "Words left" column to the deck list and a line to each deck's
overview. A word counts as "left" when none of its cards has been studied
yet (suspended cards are ignored, buried siblings still count). The numbers
are totals: they ignore the daily new-card limit, so they can go above 9999.
"""

import json

from aqt import gui_hooks, mw

_cache = {"key": None, "by_id": {}}


def _counts():
    col = mw.col
    key = col.mod
    if _cache["key"] == key and _cache["by_id"]:
        return _cache["by_id"]
    # one pass over the cards, grouped by note: a word is "left" when none of its
    # (non-suspended) cards has been studied; it is counted in the deck of its first card
    rows = col.db.all(
        "select did, count(*), sum(n) from ("
        " select nid, min(did) as did, count(*) as n from cards"
        " where queue != -1 group by nid having max(type) = 0"
        ") group by did"
    )
    names = {d.id: d.name for d in col.decks.all_names_and_ids()}
    agg = {}
    for did, notes, cards in rows:
        name = names.get(did)
        if name is None:
            continue
        parts = name.split("::")
        for i in range(1, len(parts) + 1):
            a = agg.setdefault("::".join(parts[:i]), [0, 0])
            a[0] += notes
            a[1] += cards
    by_id = {did: agg.get(name, [0, 0]) for did, name in names.items()}
    _cache["key"] = key
    _cache["by_id"] = by_id
    return by_id


def _fmt(n):
    return f"{n:,}".replace(",", " ")


def on_deck_browser(deck_browser, content):
    try:
        data = {str(k): v for k, v in _counts().items()}
    except Exception:
        return
    js = json.dumps(data)
    content.stats += f"""
<style>.wl-col{{color:#8fa3b8;text-align:right;padding-right:10px;white-space:nowrap}}</style>
<script>
(function() {{
  var d = {js};
  var rows = document.querySelectorAll('tr');
  rows.forEach(function(tr) {{
    if (tr.querySelector('.wl-col')) return;
    var cells = tr.children;
    if (!cells.length) return;
    var last = cells[cells.length - 1];
    if (tr.querySelector('th')) {{
      var th = document.createElement('th');
      th.className = 'count wl-col';
      th.title = 'Words (notes) not started yet. Totals, not limited by the daily limit.';
      th.textContent = 'Words left';
      tr.insertBefore(th, last);
    }} else if (tr.id && d[tr.id]) {{
      var td = document.createElement('td');
      td.className = 'wl-col';
      td.title = d[tr.id][1].toLocaleString() + ' new cards';
      td.textContent = d[tr.id][0] ? d[tr.id][0].toLocaleString() : '';
      tr.insertBefore(td, last);
    }} else if (tr.id) {{
      var td2 = document.createElement('td');
      td2.className = 'wl-col';
      tr.insertBefore(td2, last);
    }}
  }});
}})();
</script>"""


def on_overview(overview, content):
    try:
        did = mw.col.decks.current()["id"]
        notes, cards = _counts().get(did, [0, 0])
    except Exception:
        return
    content.table += (
        f'<div style="margin-top:1em;color:#8fa3b8">Words not started yet: '
        f"<b>{_fmt(notes)}</b> ({_fmt(cards)} new cards in total)</div>"
    )


gui_hooks.deck_browser_will_render_content.append(on_deck_browser)
gui_hooks.overview_will_render_content.append(on_overview)
