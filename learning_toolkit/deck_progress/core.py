"""Read-only counting. No Anki/Qt imports, collection opening, or writes."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any


STAGE = re.compile(r"^([A-Za-z])\.\s*(.+)$")
MAX_COUNTERS = 100
SQL_BATCH = 350  # Two sets of bound IDs remain below SQLite's legacy limit.


class CollectionUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class DeckRef:
    id: int
    name: str


@dataclass(frozen=True)
class Counter:
    id: str
    name: str
    decks: tuple[DeckRef, ...]
    include_subdecks: bool = True
    stage_a_only: bool = False
    unit: str = "cards"
    include_suspended: bool = True
    show_total: bool = False


@dataclass(frozen=True)
class Options:
    enabled: bool = True
    counters: tuple[Counter, ...] = ()


@dataclass(frozen=True)
class Counts:
    cards: int = 0
    notes: int = 0
    total_cards: int = 0
    total_notes: int = 0


@dataclass(frozen=True)
class CounterResult:
    counter: Counter
    counts: Counts
    deck_ids: tuple[int, ...]
    problems: tuple[str, ...] = ()


@dataclass(frozen=True)
class Snapshot:
    results: tuple[CounterResult, ...]
    decks: tuple[DeckRef, ...]


def _bool(raw: dict, key: str, default: bool) -> bool:
    return raw[key] if isinstance(raw.get(key), bool) else default


def parse_options(raw: Any) -> Options:
    """Invalid settings never broaden a deck selection to the entire collection."""
    if not isinstance(raw, dict):
        return Options()
    counters = []
    seen = set()
    values = raw.get("counters", [])
    for item in values[:MAX_COUNTERS] if isinstance(values, list) else []:
        if not isinstance(item, dict):
            continue
        key = item.get("id")
        if not isinstance(key, str) or not key.strip() or key in seen:
            continue
        seen.add(key)
        name = item.get("name", "Untitled counter")
        name = name.strip()[:80] if isinstance(name, str) else "Untitled counter"
        decks = {}
        refs = item.get("decks", [])
        for ref in refs if isinstance(refs, list) else []:
            if not isinstance(ref, dict):
                continue
            did = ref.get("id")
            if isinstance(did, bool) or not isinstance(did, int) or did <= 0:
                continue
            label = ref.get("name", "")
            decks[did] = DeckRef(did, label if isinstance(label, str) else "")
        unit = item.get("unit")
        counters.append(Counter(
            id=key, name=name or "Untitled counter", decks=tuple(decks.values()),
            include_subdecks=_bool(item, "include_subdecks", True),
            stage_a_only=_bool(item, "stage_a_only", False),
            unit=unit if unit in ("cards", "notes", "both") else "cards",
            include_suspended=_bool(item, "include_suspended", True),
            show_total=_bool(item, "show_total", False),
        ))
    return Options(enabled=_bool(raw, "enabled", True), counters=tuple(counters))


def options_dict(options: Options) -> dict:
    raw = asdict(options)
    raw["counters"] = [dict(asdict(c), decks=[asdict(d) for d in c.decks]) for c in options.counters]
    return raw


def in_family(name: str, root: str) -> bool:
    return name == root or name.startswith(root + "::")


def _in_a_stage(name: str, root: str) -> bool:
    # Include a selected a. deck itself and its descendants, or a. stages
    # strictly below a selected language/category deck. An a. ancestor above
    # an explicitly selected b. deck does not change that selection's meaning.
    components = name[len(root):].lstrip(":").split("::")
    components.insert(0, root.rsplit("::", 1)[-1])
    return any((match := STAGE.match(part)) and match[1].lower() == "a" for part in components)


def resolve_decks(counter: Counter, decks: tuple[DeckRef, ...]) -> tuple[tuple[int, ...], tuple[str, ...]]:
    by_id = {d.id: d for d in decks}
    selected = set()
    problems = []
    if not counter.decks:
        problems.append("No decks selected. Choose decks in Settings.")
    for ref in counter.decks:
        current = by_id.get(ref.id)
        if current is None:
            problems.append(f"Deck missing: {ref.name or ref.id}. Choose its replacement in Settings.")
            continue
        for deck in decks:
            belongs = in_family(deck.name, current.name) if counter.include_subdecks else deck.id == ref.id
            if belongs and (not counter.stage_a_only or _in_a_stage(deck.name, current.name)):
                selected.add(deck.id)
    if counter.decks and not selected and not problems:
        problems.append("No a. stage found in this selection.")
    return tuple(sorted(selected)), tuple(problems)


def _count(db: Any, deck_ids: tuple[int, ...], include_suspended: bool) -> Counts:
    if not deck_ids:
        return Counts()
    extra = "" if include_suspended else " AND queue != -1"
    if len(deck_ids) <= SQL_BATCH:
        marks = ",".join("?" for _ in deck_ids)
        # odid is a filtered card's home deck. Each physical card counts once.
        rows = db.all(
            "SELECT COUNT(*), COUNT(DISTINCT nid), "
            "COALESCE(SUM(CASE WHEN reps > 0 THEN 1 ELSE 0 END), 0), "
            "COUNT(DISTINCT CASE WHEN reps > 0 THEN nid END) FROM cards WHERE "
            f"((odid = 0 AND did IN ({marks})) OR odid IN ({marks})){extra}",
            *deck_ids, *deck_ids,
        )
        total, total_notes, studied, studied_notes = rows[0]
        return Counts(int(studied), int(studied_notes), int(total), int(total_notes))
    # Rare collections with hundreds of selected decks: use bounded statements
    # and merge by note ID so split siblings do not inflate a word count.
    notes: dict[int, tuple[int, int]] = {}
    for start in range(0, len(deck_ids), SQL_BATCH):
        batch = deck_ids[start:start + SQL_BATCH]
        marks = ",".join("?" for _ in batch)
        rows = db.all(
            "SELECT nid, COUNT(*), SUM(CASE WHEN reps > 0 THEN 1 ELSE 0 END) "
            "FROM cards WHERE "
            f"((odid = 0 AND did IN ({marks})) OR odid IN ({marks})){extra} GROUP BY nid",
            *batch, *batch,
        )
        for nid, total, studied in rows:
            old_total, old_studied = notes.get(int(nid), (0, 0))
            notes[int(nid)] = (old_total + int(total), old_studied + int(studied))
    return Counts(
        cards=sum(n[1] for n in notes.values()), notes=sum(n[1] > 0 for n in notes.values()),
        total_cards=sum(n[0] for n in notes.values()), total_notes=len(notes),
    )


def collect_snapshot(col: Any, options: Options) -> Snapshot:
    if col is None or getattr(col, "db", None) is None:
        raise CollectionUnavailable("Open a collection to see deck progress.")
    decks = tuple(sorted(
        (DeckRef(int(d.id), d.name) for d in col.decks.all_names_and_ids(include_filtered=False)),
        key=lambda d: (d.name.casefold(), d.id),
    ))
    cache = {}
    results = []
    for counter in options.counters:
        ids, problems = resolve_decks(counter, decks)
        key = (ids, counter.include_suspended)
        if key not in cache:
            cache[key] = _count(col.db, ids, counter.include_suspended)
        results.append(CounterResult(counter, cache[key], ids, problems))
    return Snapshot(tuple(results), decks)
