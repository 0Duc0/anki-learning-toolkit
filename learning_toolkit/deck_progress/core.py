"""Read-only counting. No Anki/Qt imports, collection opening, or writes."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import math
import re
import time
from typing import Any


STAGE = re.compile(r"^([A-Za-z])\.\s*(.+)$")
MAX_COUNTERS = 100
SQL_BATCH = 350  # Two sets of bound IDs remain below SQLite's legacy limit.
MAX_LABEL_LENGTH = 80
DEFAULT_LABELS = {"cards": "Cards answered", "notes": "Introduced"}
ALL_STATES = ("all",)
ANSWERED_STATES = ("answered",)
REVIEW_STATES = ("young", "mature")
# Anki stores the scheduling state in type and suspension/burial in queue.
CARD_STATES = {
    "new": ("New", "type = 0"),
    "learning": ("Learning", "type = 1"),
    "relearning": ("Relearning", "type = 3"),
    "young": ("Young review", "type = 2 AND ivl < 21"),
    "mature": ("Mature review", "type = 2 AND ivl >= 21"),
}


# Card states shown beside a counter, in Anki's order and colours (new, learning, review, suspended).
SHOWN_STATES = ("new", "learning", "relearning", "review", "suspended")
STATE_LABELS = {"new": "New", "learning": "Learning", "relearning": "Relearning", "review": "Review",
                "suspended": "Suspended"}
ESTIMATES = ("off", "pace", "fixed")
MAX_PER_DAY = 10000
PACE_WINDOW_DAYS = 28        # "recent" study days
PACE_MIN_RECENT = 5          # fewer recent study days → use the last study days, however old
PACE_FALLBACK_DAYS = 10
PACE_DECAY = 0.85            # each older study day weighs 15% less


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
    show_progress: bool = False
    goal_decks: tuple[DeckRef, ...] = ()
    card_label: str = ""
    note_label: str = ""
    counter_states: tuple[str, ...] = ANSWERED_STATES
    goal_states: tuple[str, ...] = ALL_STATES
    include_buried: bool = True
    all_note_cards: bool = False
    show_states: bool = False       # card states row
    show_note_states: bool = False  # note states row
    show_left: bool = False         # "N notes left" (goal total minus what the counter counts)
    estimate: str = "off"           # off | pace | fixed
    per_day: int = 20               # fixed pace (notes or cards per day)


@dataclass(frozen=True)
class Options:
    enabled: bool = True
    counters: tuple[Counter, ...] = ()
    state_labels: dict = field(default_factory=dict)   # renamed state labels, e.g. {"new": "Neu"}

    def label(self, state: str) -> str:
        return _label(self.state_labels.get(state)) or STATE_LABELS[state]


@dataclass(frozen=True)
class StateCounts:
    new: int = 0
    learning: int = 0
    relearning: int = 0
    review: int = 0
    suspended: int = 0
    # The same states for notes: each note counts once, in its most active state
    # (relearning, then learning, then review, then new; suspended only when all its cards are).
    new_notes: int = 0
    learning_notes: int = 0
    relearning_notes: int = 0
    review_notes: int = 0
    suspended_notes: int = 0

    def get(self, state: str, unit: str) -> int:
        return getattr(self, state + ("_notes" if unit == "notes" else ""))


@dataclass(frozen=True)
class Estimate:
    remaining: int
    per_day: float              # notes/cards per study day (or per day for a fixed pace)
    study_days: int             # study days still needed
    calendar_days: int          # expected calendar days
    mode: str                   # pace | fixed
    basis: str                  # how the pace was measured, for the tooltip
    unit: str                   # cards | notes


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
    goal_counts: Counts | None = None
    states: StateCounts | None = None
    estimate: Estimate | None = None
    estimate_note: str = ""
    left: int | None = None         # goal total minus what the counter counts (counter unit)
    left_unit: str = "notes"


@dataclass(frozen=True)
class Snapshot:
    results: tuple[CounterResult, ...]
    decks: tuple[DeckRef, ...]


def _bool(raw: dict, key: str, default: bool) -> bool:
    return raw[key] if isinstance(raw.get(key), bool) else default


def _label(value: Any) -> str:
    return value.strip()[:MAX_LABEL_LENGTH] if isinstance(value, str) else ""


def _parse_states(raw: Any, default: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(raw, (list, tuple)):
        return default
    if "all" in raw:
        return ALL_STATES
    if "answered" in raw:
        return ANSWERED_STATES
    return tuple(state for state in CARD_STATES if state in raw) or default


def state_summary(states: tuple[str, ...]) -> str:
    if states == ALL_STATES:
        return "All states"
    if states == ANSWERED_STATES:
        return "Answered at least once"
    labels = [label for state, (label, _) in CARD_STATES.items() if state in states]
    if "young" in states and "mature" in states:
        labels.remove(CARD_STATES["young"][0])
        labels.remove(CARD_STATES["mature"][0])
        labels.append("Review")
    return ", ".join(labels)


def default_label(unit: str, states: tuple[str, ...], *, all_note_cards: bool = False) -> str:
    if unit == "notes" and all_note_cards and states != ALL_STATES:
        if states == REVIEW_STATES:
            return "Notes fully in review"
        if states == ANSWERED_STATES:
            return "Notes fully answered"
        return "Notes · All cards match"
    if states == ANSWERED_STATES:
        return DEFAULT_LABELS[unit]
    if states == ALL_STATES:
        return f"Total {unit}"
    return f"{unit.capitalize()} · {state_summary(states)}"


def _deck_refs(values: Any) -> tuple[DeckRef, ...]:
    decks = {}
    for ref in values if isinstance(values, list) else []:
        if not isinstance(ref, dict):
            continue
        did = ref.get("id")
        if isinstance(did, bool) or not isinstance(did, int) or did <= 0:
            continue
        label = ref.get("name", "")
        decks[did] = DeckRef(did, label if isinstance(label, str) else "")
    return tuple(decks.values())


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
        unit = item.get("unit")
        counters.append(Counter(
            id=key, name=_label(item.get("name")) or "Untitled counter",
            decks=_deck_refs(item.get("decks")),
            include_subdecks=_bool(item, "include_subdecks", True),
            stage_a_only=_bool(item, "stage_a_only", False),
            unit=unit if unit in ("cards", "notes", "both") else "cards",
            include_suspended=_bool(item, "include_suspended", True),
            show_total=_bool(item, "show_total", False),
            show_progress=_bool(item, "show_progress", False),
            goal_decks=_deck_refs(item.get("goal_decks")),
            card_label=_label(item.get("card_label")),
            note_label=_label(item.get("note_label")),
            counter_states=_parse_states(item.get("counter_states"), ANSWERED_STATES),
            goal_states=_parse_states(item.get("goal_states"), ALL_STATES),
            include_buried=_bool(item, "include_buried", True),
            all_note_cards=_bool(item, "all_note_cards", False),
            show_states=_bool(item, "show_states", False),
            show_note_states=_bool(item, "show_note_states", False),
            show_left=_bool(item, "show_left", False),
            estimate=item.get("estimate") if item.get("estimate") in ESTIMATES else "off",
            per_day=_per_day(item.get("per_day")),
        ))
    labels = raw.get("state_labels")
    labels = {k: _label(v) for k, v in labels.items() if k in STATE_LABELS and _label(v)} if isinstance(labels, dict) else {}
    return Options(enabled=_bool(raw, "enabled", True), counters=tuple(counters), state_labels=labels)


def _per_day(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 20
    return max(1, min(MAX_PER_DAY, int(value)))


def options_dict(options: Options) -> dict:
    counters = []
    for counter in options.counters:
        raw = asdict(counter)
        raw["decks"] = list(raw["decks"])
        raw["goal_decks"] = list(raw["goal_decks"])
        raw["counter_states"] = list(raw["counter_states"])
        raw["goal_states"] = list(raw["goal_states"])
        counters.append(raw)
    return {"enabled": options.enabled, "counters": counters, "state_labels": dict(options.state_labels)}


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


def _state_sql(states: tuple[str, ...]) -> str:
    if states == ALL_STATES:
        return "1"
    if states == ANSWERED_STATES:
        return "reps > 0"
    return " OR ".join(f"({CARD_STATES[state][1]})" for state in states)


def _count(
    db: Any, deck_ids: tuple[int, ...], counter: Counter, extra_ids: tuple[int, ...],
) -> Counts:
    if not deck_ids:
        return Counts()
    availability = "" if counter.include_suspended else " AND queue != -1"
    if not counter.include_buried:
        availability += " AND queue NOT IN (-2, -3)"
    state_filter = _state_sql(counter.counter_states)
    note_match = "matched"
    if counter.all_note_cards and counter.counter_states != ALL_STATES:
        # A matching card must still come from the counter scope. The whole
        # note can be disqualified by an eligible sibling in any deck.
        note_match += (
            " AND NOT EXISTS (SELECT 1 FROM cards AS sibling "
            f"WHERE sibling.nid = selected.nid{availability} AND NOT ({state_filter}))"
        )
    parts = []
    scopes = (
        (deck_ids, state_filter, "1"),
        (extra_ids, "0", _state_sql(counter.goal_states)),
    )
    for ids, matching, eligible in scopes:
        for start in range(0, len(ids), SQL_BATCH):
            batch = ids[start:start + SQL_BATCH]
            marks = ",".join("?" for _ in batch)
            # odid identifies a filtered card's home deck.
            sql = (
                f"SELECT nid, ({matching}) AS matched FROM cards WHERE "
                f"((odid = 0 AND did IN ({marks})) OR odid IN ({marks}))"
                f"{availability} AND ({eligible})"
            )
            parts.append((sql, batch + batch))
    if len(deck_ids) + len(extra_ids) <= SQL_BATCH:
        # The goal adds only decks outside the counter scope. A card can
        # enter the query once, and siblings share one distinct note ID.
        sql = " UNION ALL ".join(part[0] for part in parts)
        params = tuple(value for _, batch in parts for value in batch)
        rows = db.all(
            "SELECT COUNT(*), COUNT(DISTINCT nid), "
            f"COALESCE(SUM(matched), 0), COUNT(DISTINCT CASE WHEN {note_match} THEN nid END) "
            f"FROM ({sql}) AS selected",
            *params,
        )
        total, total_notes, matching, matching_notes = rows[0]
        return Counts(int(matching), int(matching_notes), int(total), int(total_notes))
    # Rare collections with hundreds of selected decks: use bounded statements
    # and merge by note ID so siblings split across scopes still count once.
    notes: dict[int, tuple[int, int, bool]] = {}
    for sql, params in parts:
        rows = db.all(
            f"SELECT nid, COUNT(*), SUM(matched), MAX(CASE WHEN {note_match} THEN 1 ELSE 0 END) "
            f"FROM ({sql}) AS selected GROUP BY nid", *params,
        )
        for nid, total, matching, matching_note in rows:
            old_total, old_matching, old_note = notes.get(int(nid), (0, 0, False))
            notes[int(nid)] = (old_total + int(total), old_matching + int(matching), old_note or bool(matching_note))
    return Counts(
        cards=sum(n[1] for n in notes.values()), notes=sum(n[2] for n in notes.values()),
        total_cards=sum(n[0] for n in notes.values()), total_notes=len(notes),
    )


def _scope_sql(deck_ids: tuple[int, ...], table: str = "") -> tuple[str, tuple[int, ...]]:
    marks = ",".join("?" for _ in deck_ids)
    t = f"{table}." if table else ""
    return f"(({t}odid = 0 AND {t}did IN ({marks})) OR {t}odid IN ({marks}))", deck_ids + deck_ids


def state_counts(db: Any, deck_ids: tuple[int, ...], counter: Counter) -> StateCounts:
    """Cards and notes per state in the counter decks, like Anki marks them. Suspended cards are counted apart."""
    if not deck_ids:
        return StateCounts()
    totals = [0, 0, 0, 0, 0]
    notes: dict[int, list[int]] = {}
    buried = "" if counter.include_buried else " AND queue NOT IN (-2, -3)"
    for start in range(0, len(deck_ids), SQL_BATCH):
        where, params = _scope_sql(deck_ids[start:start + SQL_BATCH])
        row = db.first(
            "SELECT SUM(type = 0 AND queue != -1), SUM(type = 1 AND queue != -1), SUM(type = 3 AND queue != -1), "
            f"SUM(type = 2 AND queue != -1), SUM(queue = -1) FROM cards WHERE {where}{buried}", *params)
        totals = [t + int(v or 0) for t, v in zip(totals, row or ())]
        for nid, relearn, learn, review, active in db.all(
                "SELECT nid, MAX(type = 3 AND queue != -1), MAX(type = 1 AND queue != -1), "
                f"MAX(type = 2 AND queue != -1), MAX(queue != -1) FROM cards WHERE {where}{buried} GROUP BY nid",
                *params):
            flags = notes.setdefault(int(nid), [0, 0, 0, 0])
            for i, value in enumerate((relearn, learn, review, active)):
                flags[i] = max(flags[i], int(value or 0))
    by_note = {"new": 0, "learning": 0, "relearning": 0, "review": 0, "suspended": 0}
    for relearn, learn, review, active in notes.values():
        if not active:
            by_note["suspended"] += 1
        elif relearn:
            by_note["relearning"] += 1
        elif learn:
            by_note["learning"] += 1
        elif review:
            by_note["review"] += 1
        else:
            by_note["new"] += 1
    if not counter.include_suspended:
        totals[4] = by_note["suspended"] = 0
    return StateCounts(*totals, *(by_note[k] for k in ("new", "learning", "relearning", "review", "suspended")))


def first_study_days(db: Any, deck_ids: tuple[int, ...], unit: str, day_start: int) -> dict[int, int]:
    """New cards (or notes) studied for the first time, per day: {0: today, -1: yesterday, …}.

    A note counts on the day its first card was first answered. ``day_start`` is the epoch second today began.
    """
    if not deck_ids:
        return {}
    firsts: dict[int, int] = {}
    key = "c.nid" if unit == "notes" else "c.id"
    for start in range(0, len(deck_ids), SQL_BATCH):
        where, params = _scope_sql(deck_ids[start:start + SQL_BATCH], "c")
        for item, first in db.all(
            f"SELECT {key}, MIN(r.id) FROM revlog AS r JOIN cards AS c ON c.id = r.cid "
            f"WHERE {where} AND r.type < 4 AND r.ease > 0 GROUP BY {key}", *params):
            firsts[item] = min(first, firsts.get(item, first))
    days: dict[int, int] = {}
    for first in firsts.values():
        day = math.floor((first / 1000 - day_start) / 86400)
        days[day] = days.get(day, 0) + 1
    return days


def study_pace(days: dict[int, int]) -> tuple[float, float, str] | None:
    """(new items per study day, share of days you study, explanation) or None without enough history.

    Only days on which you started something new count, so a long break does not drag the pace towards 0.
    Recent study days weigh more. How often you study is taken from the last four weeks; after a break the
    estimate assumes you study daily again.
    """
    active = sorted((d for d, n in days.items() if n > 0 and d <= 0), reverse=True)
    recent = [d for d in active if d > -PACE_WINDOW_DAYS]
    if len(recent) >= PACE_MIN_RECENT:
        sample, basis = recent, f"your {len(recent)} study days in the last 4 weeks"
        share = len(recent) / PACE_WINDOW_DAYS
    else:
        sample = active[:PACE_FALLBACK_DAYS]
        if len(sample) < 3:
            return None
        basis = f"your last {len(sample)} study days"
        share = 1.0
    weights = [PACE_DECAY ** i for i in range(len(sample))]
    pace = sum(w * days[d] for w, d in zip(weights, sample)) / sum(weights)
    return pace, max(share, 1 / 7), basis


def make_estimate(remaining: int, counter: Counter, unit: str, days: dict[int, int] | None) -> tuple[Estimate | None, str]:
    if remaining <= 0:
        return Estimate(0, 0, 0, 0, counter.estimate, "", unit), ""
    if counter.estimate == "fixed":
        per_day = float(counter.per_day)
        need = math.ceil(remaining / per_day)
        return Estimate(remaining, per_day, need, need, "fixed", f"{counter.per_day} {unit} per day", unit), ""
    pace = study_pace(days or {})
    if pace is None or pace[0] <= 0:
        return None, "Study a few more days for an estimate"
    per_day, share, basis = pace
    need = math.ceil(remaining / per_day)
    return Estimate(remaining, per_day, need, math.ceil(need / share), "pace", basis, unit), ""


def collect_snapshot(col: Any, options: Options) -> Snapshot:
    if col is None or getattr(col, "db", None) is None:
        raise CollectionUnavailable("Open a collection to see deck progress.")
    decks = tuple(sorted(
        (DeckRef(int(d.id), d.name) for d in col.decks.all_names_and_ids(include_filtered=False)),
        key=lambda d: (d.name.casefold(), d.id),
    ))
    cache = {}

    def counts_for(ids, counter, extra_ids=()):
        key = (ids, counter.counter_states, counter.include_suspended, counter.include_buried, counter.all_note_cards,
               extra_ids, counter.goal_states if extra_ids else ALL_STATES)
        if key not in cache:
            cache[key] = _count(col.db, ids, counter, extra_ids)
        return cache[key]

    results = []
    for counter in options.counters:
        ids, problems = resolve_decks(counter, decks)
        counts = counts_for(ids, counter)
        goal_counts = None
        if counter.goal_decks and (counter.show_total or counter.show_progress):
            goal = replace(counter, decks=counter.goal_decks, stage_a_only=False)
            goal_ids, goal_problems = resolve_decks(goal, decks)
            problems += tuple(f"Goal decks: {problem}" for problem in goal_problems)
            if not problems:
                extra_ids = tuple(sorted(set(goal_ids) - set(ids)))
                goal_counts = counts_for(ids, counter, extra_ids)
        show_any_states = counter.show_states or counter.show_note_states
        states = state_counts(col.db, ids, counter) if show_any_states and ids else None
        estimate, note, left = None, "", None
        unit = "notes" if counter.unit in ("notes", "both") else "cards"
        if (counter.estimate != "off" or counter.show_left) and ids and not problems:
            # Left = goal total minus what the counter counts, so it follows the counter's card states
            # (answered, mature, ...). The goal is the counter decks plus any goal decks.
            extra_ids: tuple[int, ...] = ()
            if counter.goal_decks:
                goal_ids, goal_problems = resolve_decks(replace(counter, decks=counter.goal_decks, stage_a_only=False), decks)
                if not goal_problems:
                    extra_ids = tuple(sorted(set(goal_ids) - set(ids)))
            scope = counts_for(ids, counter, extra_ids)
            done = scope.notes if unit == "notes" else scope.cards
            total = scope.total_notes if unit == "notes" else scope.total_cards
            left = max(0, total - done)
            if counter.estimate != "off":
                days = None
                if counter.estimate == "pace":
                    try:
                        day_start = int(col.sched.day_cutoff) - 86400
                    except Exception:
                        day_start = int(time.time()) // 86400 * 86400
                    days = first_study_days(col.db, ids + extra_ids, unit, day_start)
                estimate, note = make_estimate(left, counter, unit, days)
        results.append(CounterResult(counter, counts, ids, problems, goal_counts, states, estimate, note, left, unit))
    return Snapshot(tuple(results), decks)
