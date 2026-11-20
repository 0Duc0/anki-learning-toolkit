"""Core logic for configurable shifts through alphabetic sibling decks."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from anki.collection import Collection, OpChanges
from anki.consts import (
    CARD_TYPE_LRN,
    CARD_TYPE_NEW,
    CARD_TYPE_RELEARNING,
    CARD_TYPE_REV,
)


STAGE_RE = re.compile(r"^([A-Za-z])\.\s*(.+)$")
VALID_DIRECTIONS = {"toward_a", "toward_end"}
VALID_LIMIT_UNITS = {"cards", "notes"}
VALID_CARD_TYPES = {
    int(CARD_TYPE_NEW),
    int(CARD_TYPE_LRN),
    int(CARD_TYPE_REV),
    int(CARD_TYPE_RELEARNING),
}


def _require_write_ready(col: Collection) -> None:
    if getattr(col, "db", None) is None:
        raise RuntimeError("The collection is closed. Open the profile again.")
    for name in (
        "set_deck",
        "add_custom_undo_entry",
        "merge_undo_entries",
        "undo_status",
        "undo",
    ):
        if not callable(getattr(col, name, None)):
            raise RuntimeError(
                f"This Anki version lacks the required {name} API. Nothing was changed."
            )
    try:
        free = shutil.disk_usage(Path(col.path).parent).free
    except OSError as error:
        raise RuntimeError(
            "The collection storage could not be checked. Nothing was changed."
        ) from error
    if free < 1024**3:
        raise RuntimeError(
            "Less than 1 GiB of free space remains. Free space before shifting cards."
        )


def _rollback_own_shift(col: Collection, undo_entry: int, error: Exception) -> None:
    try:
        col.merge_undo_entries(undo_entry)
        if col.undo_status().last_step != undo_entry:
            raise RuntimeError("The shift no longer owns the current undo entry.")
        col.undo()
    except Exception as rollback_error:
        raise RuntimeError(
            "The shift failed and automatic rollback could not be confirmed. "
            "Stop making changes and check the collection before syncing. "
            f"Original error: {error}. Rollback error: {rollback_error}"
        ) from error
    raise RuntimeError(
        f"The shift failed and its changes were undone. {error}"
    ) from error


@dataclass(frozen=True)
class StageDeck:
    key: str
    deck_id: int
    full_name: str
    label: str
    new_count: int
    learning_count: int
    review_count: int
    suspended_count: int


@dataclass(frozen=True)
class StageGroup:
    parent_name: str
    stages: tuple[StageDeck, ...]

    @property
    def new_count(self) -> int:
        return sum(stage.new_count for stage in self.stages)


@dataclass(frozen=True)
class ShiftOptions:
    parent_name: str
    direction: str
    start_key: str
    stop_key: str
    card_types: tuple[int, ...]
    include_suspended: bool = False
    max_per_source: int = 100
    limit_unit: str = "cards"
    # Even mode: refill every stage (from the endpoint onward) to even_notes notes
    even: bool = False
    even_notes: int = 20


@dataclass(frozen=True)
class PlannedMove:
    source: StageDeck
    destination: StageDeck
    card_ids: tuple[int, ...]
    note_ids: tuple[int, ...]

    @property
    def count(self) -> int:
        return len(self.card_ids)

    @property
    def note_count(self) -> int:
        return len(self.note_ids)


@dataclass(frozen=True)
class ShiftPlan:
    options: ShiftOptions
    moves: tuple[PlannedMove, ...]
    # Even mode only: (stage label, notes before, notes after) per stage, in order
    stage_counts: tuple[tuple[str, int, int], ...] = ()
    skipped_notes: int = 0
    warnings: tuple[str, ...] = ()

    @property
    def parent_name(self) -> str:
        return self.options.parent_name

    @property
    def total(self) -> int:
        return sum(move.count for move in self.moves)

    @property
    def total_notes(self) -> int:
        return len({note_id for move in self.moves for note_id in move.note_ids})


@dataclass
class ShiftResult:
    changes: OpChanges
    options: ShiftOptions
    moved: int
    moved_notes: int
    move_counts: tuple[tuple[str, str, int, int], ...]
    stage_counts: tuple[tuple[str, int, int], ...] = ()


def _split_parent(full_name: str) -> tuple[str, str]:
    if "::" not in full_name:
        return "", full_name
    return tuple(full_name.rsplit("::", 1))  # type: ignore[return-value]


def scan_groups(col: Collection) -> list[StageGroup]:
    """Return safe contiguous a./b./c. sibling sequences."""
    candidates: dict[str, dict[str, list[tuple[int, str, str]]]] = {}
    for deck in col.decks.all_names_and_ids(include_filtered=False):
        parent, leaf = _split_parent(deck.name)
        match = STAGE_RE.match(leaf)
        if not match:
            continue
        key = match.group(1).lower()
        label = f"{key}. {match.group(2)}"
        candidates.setdefault(parent, {}).setdefault(key, []).append(
            (int(deck.id), deck.name, label)
        )

    groups: list[StageGroup] = []
    for parent, by_key in candidates.items():
        if any(len(values) != 1 for values in by_key.values()):
            continue
        keys = sorted(by_key)
        if not keys or keys[0] != "a":
            continue
        expected = [chr(code) for code in range(ord("a"), ord(keys[-1]) + 1)]
        if keys != expected or len(keys) < 2:
            continue

        stages: list[StageDeck] = []
        for key in keys:
            deck_id, full_name, label = by_key[key][0]
            rows = col.db.all(
                """SELECT type, queue, COUNT(*)
                   FROM cards WHERE did=? GROUP BY type, queue""",
                deck_id,
            )
            by_type: dict[int, int] = {}
            suspended = 0
            for card_type, queue, count in rows:
                by_type[int(card_type)] = by_type.get(int(card_type), 0) + int(count)
                if int(queue) == -1:
                    suspended += int(count)
            stages.append(
                StageDeck(
                    key=key,
                    deck_id=deck_id,
                    full_name=full_name,
                    label=label,
                    new_count=by_type.get(int(CARD_TYPE_NEW), 0),
                    learning_count=by_type.get(int(CARD_TYPE_LRN), 0)
                    + by_type.get(int(CARD_TYPE_RELEARNING), 0),
                    review_count=by_type.get(int(CARD_TYPE_REV), 0),
                    suspended_count=suspended,
                )
            )
        groups.append(StageGroup(parent_name=parent, stages=tuple(stages)))
    return sorted(groups, key=lambda group: group.parent_name.casefold())


def find_group(col: Collection, parent_name: str) -> StageGroup:
    for group in scan_groups(col):
        if group.parent_name == parent_name:
            return group
    raise RuntimeError(
        "The selected alphabetic deck group no longer exists or is ambiguous."
    )


def card_type_label(card_types: tuple[int, ...]) -> str:
    selected = set(card_types)
    labels: list[str] = []
    if int(CARD_TYPE_NEW) in selected:
        labels.append("New")
    if selected.intersection({int(CARD_TYPE_LRN), int(CARD_TYPE_RELEARNING)}):
        labels.append("Learning/Relearning")
    if int(CARD_TYPE_REV) in selected:
        labels.append("Review")
    return ", ".join(labels) or "None"


def _validate_options(group: StageGroup, options: ShiftOptions) -> tuple[int, int]:
    if options.direction not in VALID_DIRECTIONS:
        raise RuntimeError("Unknown shift direction.")
    if not options.card_types or not set(options.card_types).issubset(VALID_CARD_TYPES):
        raise RuntimeError("Select at least one supported card state.")
    if options.max_per_source < 0:
        raise RuntimeError("The per-stage limit cannot be negative.")
    if options.limit_unit not in VALID_LIMIT_UNITS:
        raise RuntimeError("The per-stage limit must be measured in cards or notes.")
    if options.even:
        if options.direction != "toward_a":
            raise RuntimeError("Even mode only works toward a. (earlier stage).")
        if set(options.card_types) != {int(CARD_TYPE_NEW)}:
            raise RuntimeError("Even mode works with New cards only.")
        if not 1 <= options.even_notes <= 10000:
            raise RuntimeError("Even mode needs 1 to 10,000 notes per stage.")
    keys = [stage.key for stage in group.stages]
    if options.start_key not in keys or options.stop_key not in keys:
        raise RuntimeError("The selected start or end stage no longer exists.")
    start = keys.index(options.start_key)
    stop = keys.index(options.stop_key)
    if options.direction == "toward_a" and start <= stop:
        raise RuntimeError(
            "Toward a. requires the start stage to be after the end stage."
        )
    if options.direction == "toward_end" and start >= stop:
        raise RuntimeError(
            "Toward the last stage requires the start stage to be before the end stage."
        )
    return start, stop


def build_plan(col: Collection, options: ShiftOptions) -> ShiftPlan:
    group = find_group(col, options.parent_name)
    start, stop = _validate_options(group, options)
    if options.even:
        return _build_even_plan(col, group, options, start, stop)
    source_indexes = (
        range(start, stop, -1)
        if options.direction == "toward_a"
        else range(start, stop)
    )
    type_placeholders = ",".join("?" for _ in options.card_types)
    moves: list[PlannedMove] = []
    for index in source_indexes:
        destination_index = index - 1 if options.direction == "toward_a" else index + 1
        source = group.stages[index]
        destination = group.stages[destination_index]
        sql = (
            f"SELECT id, nid FROM cards WHERE did=? AND odid=0 AND type IN ({type_placeholders})"
            + ("" if options.include_suspended else " AND queue != -1")
            + " ORDER BY due, id"
        )
        args: list[int] = [source.deck_id, *options.card_types]
        rows = [
            (int(card_id), int(note_id)) for card_id, note_id in col.db.all(sql, *args)
        ]
        if options.max_per_source:
            if options.limit_unit == "cards":
                rows = rows[: options.max_per_source]
            else:
                selected_notes: list[int] = []
                selected_note_set: set[int] = set()
                for _card_id, note_id in rows:
                    if note_id in selected_note_set:
                        continue
                    selected_notes.append(note_id)
                    selected_note_set.add(note_id)
                    if len(selected_notes) >= options.max_per_source:
                        break
                rows = [row for row in rows if row[1] in selected_note_set]
        card_ids = tuple(card_id for card_id, _note_id in rows)
        note_ids = tuple(dict.fromkeys(note_id for _card_id, note_id in rows))
        moves.append(
            PlannedMove(
                source=source,
                destination=destination,
                card_ids=card_ids,
                note_ids=note_ids,
            )
        )
    return ShiftPlan(options=options, moves=tuple(moves))


def _eligible_sql(options: ShiftOptions) -> str:
    return "type=? AND odid=0" + ("" if options.include_suspended else " AND queue != -1")


def _stage_note_counts(
    col: Collection, group: StageGroup, options: ShiftOptions, start: int, stop: int
) -> list[int]:
    """Notes with at least one eligible (New) card, per stage from the endpoint on."""
    return [
        int(
            col.db.scalar(
                f"SELECT COUNT(DISTINCT nid) FROM cards WHERE did=? AND {_eligible_sql(options)}",
                group.stages[index].deck_id,
                int(CARD_TYPE_NEW),
            )
            or 0
        )
        for index in range(stop, start + 1)
    ]


def _build_even_plan(
    col: Collection,
    group: StageGroup,
    options: ShiftOptions,
    start: int,
    stop: int,
) -> ShiftPlan:
    """Cut the queue (stage by stage, then card position) into blocks of N notes.

    Block 0 belongs to the endpoint stage (a.), block 1 to the next stage, and so on.
    The queue order never changes; only notes whose block differs from their current
    stage move. Surplus beyond the last stage's room stays in the last stage. A note
    with eligible cards in more than one stage is left where it is.
    """
    n = options.even_notes
    indexes = list(range(stop, start + 1))
    per_stage: dict[int, dict[int, list[int]]] = {}
    stages_of_note: dict[int, set[int]] = {}
    for index in indexes:
        rows = col.db.all(
            f"SELECT id, nid FROM cards WHERE did=? AND {_eligible_sql(options)} ORDER BY due, id",
            group.stages[index].deck_id,
            int(CARD_TYPE_NEW),
        )
        notes: dict[int, list[int]] = {}
        for card_id, note_id in rows:
            notes.setdefault(int(note_id), []).append(int(card_id))
        per_stage[index] = notes
        for note_id in notes:
            stages_of_note.setdefault(note_id, set()).add(index)

    split = {note_id for note_id, where in stages_of_note.items() if len(where) > 1}
    before = {index: len(per_stage[index]) for index in indexes}
    after = {
        index: sum(1 for note_id in per_stage[index] if note_id in split)
        for index in indexes
    }
    ordered = [
        (index, note_id, card_ids)
        for index in indexes
        for note_id, card_ids in per_stage[index].items()
        if note_id not in split
    ]
    last = indexes[-1]
    grouped: dict[tuple[int, int], list[tuple[int, list[int]]]] = {}
    for rank, (index, note_id, card_ids) in enumerate(ordered):
        target = min(stop + rank // n, last)
        after[target] += 1
        if target != index:
            grouped.setdefault((index, target), []).append((note_id, card_ids))

    moves = tuple(
        PlannedMove(
            source=group.stages[source],
            destination=group.stages[target],
            card_ids=tuple(card_id for _nid, ids in members for card_id in ids),
            note_ids=tuple(note_id for note_id, _ids in members),
        )
        for (source, target), members in sorted(grouped.items())
    )

    warnings: list[str] = []
    capacity = len(indexes) * n
    if len(ordered) > capacity:
        warnings.append(
            f"These stages hold {len(ordered):,} notes but have room for {capacity:,} at "
            f"{n} per stage, so {group.stages[last].label} will hold the extra "
            f"{len(ordered) - capacity:,}. Begin with a later source stage for a more even result."
        )
    if split:
        warnings.append(
            f"{len(split):,} note(s) have cards in more than one stage and are left where they are."
        )
    return ShiftPlan(
        options=options,
        moves=moves,
        stage_counts=tuple(
            (group.stages[index].label, before[index], after[index]) for index in indexes
        ),
        skipped_notes=len(split),
        warnings=tuple(warnings),
    )


def _card_rows(
    col: Collection, card_ids: tuple[int, ...]
) -> dict[int, tuple[int, int, int, int, int]]:
    """Return id -> (nid, did, type, queue, odid) without exceeding SQLite limits."""
    result: dict[int, tuple[int, int, int, int, int]] = {}
    for offset in range(0, len(card_ids), 900):
        chunk = card_ids[offset : offset + 900]
        placeholders = ",".join("?" for _ in chunk)
        for card_id, note_id, deck_id, card_type, queue, original_deck_id in col.db.all(
            f"SELECT id, nid, did, type, queue, odid FROM cards WHERE id IN ({placeholders})",
            *chunk,
        ):
            result[int(card_id)] = (
                int(note_id),
                int(deck_id),
                int(card_type),
                int(queue),
                int(original_deck_id),
            )
    return result


def _validate_frozen_plan(col: Collection, plan: ShiftPlan) -> None:
    """Refuse a stale preview instead of silently moving a different selection."""
    group = find_group(col, plan.options.parent_name)
    _validate_options(group, plan.options)
    current_decks = {stage.deck_id: stage.full_name for stage in group.stages}
    if plan.options.even:
        keys = [stage.key for stage in group.stages]
        start, stop = keys.index(plan.options.start_key), keys.index(plan.options.stop_key)
        if _stage_note_counts(col, group, plan.options, start, stop) != [
            before for _label, before, _after in plan.stage_counts
        ]:
            raise RuntimeError(
                "The stages changed since the preview. Nothing was moved; "
                "open the Card Stage Shifter again."
            )
    all_ids = [card_id for move in plan.moves for card_id in move.card_ids]
    if len(all_ids) != len(set(all_ids)):
        raise RuntimeError(
            "A card appears in more than one planned move. Create a fresh preview."
        )
    expected_types = set(plan.options.card_types)
    for move in plan.moves:
        for stage in (move.source, move.destination):
            if current_decks.get(stage.deck_id) != stage.full_name:
                raise RuntimeError(
                    "A stage deck was renamed, removed, or filtered. Create a fresh preview."
                )
        if not move.card_ids:
            continue
        rows = _card_rows(col, move.card_ids)
        expected_note_ids = set(move.note_ids)
        if len(rows) != len(move.card_ids):
            raise RuntimeError(
                "The preview is stale because one or more cards no longer exist. "
                "Open the Card Stage Shifter again."
            )
        for card_id in move.card_ids:
            note_id, deck_id, card_type, queue, original_deck_id = rows[card_id]
            if (
                deck_id != move.source.deck_id
                or card_type not in expected_types
                or (not plan.options.include_suspended and queue == -1)
                or note_id not in expected_note_ids
                or original_deck_id != 0
            ):
                raise RuntimeError(
                    "The preview is stale because the cards or their states changed. "
                    "Nothing was moved; open the Card Stage Shifter again."
                )


def shift_plan(col: Collection, plan: ShiftPlan) -> ShiftResult:
    """Apply the exact confirmed snapshot as one validated Undo operation."""
    _require_write_ready(col)
    _validate_frozen_plan(col, plan)
    counts = tuple(
        (
            move.source.label,
            move.destination.label,
            move.note_count,
            move.count,
        )
        for move in plan.moves
    )
    if not plan.total:
        return ShiftResult(
            changes=OpChanges(),
            options=plan.options,
            moved=0,
            moved_notes=0,
            move_counts=counts,
        )

    undo_entry = col.add_custom_undo_entry("Shift cards between stage decks")
    try:
        # All IDs are captured before any move, so a card never moves twice.
        for move in plan.moves:
            if move.card_ids:
                col.set_deck(move.card_ids, move.destination.deck_id)
        for move in plan.moves:
            if not move.card_ids:
                continue
            rows = _card_rows(col, move.card_ids)
            if any(
                card_id not in rows or rows[card_id][1] != move.destination.deck_id
                for card_id in move.card_ids
            ):
                raise RuntimeError("A moved-card verification check failed.")
        if plan.options.even:
            group = find_group(col, plan.options.parent_name)
            keys = [stage.key for stage in group.stages]
            start = keys.index(plan.options.start_key)
            stop = keys.index(plan.options.stop_key)
            if _stage_note_counts(col, group, plan.options, start, stop) != [
                after for _label, _before, after in plan.stage_counts
            ]:
                raise RuntimeError("The even-shift verification check failed.")
        changes = col.merge_undo_entries(undo_entry)
    except Exception as error:
        _rollback_own_shift(col, undo_entry, error)

    return ShiftResult(
        changes=changes,
        options=plan.options,
        moved=plan.total,
        moved_notes=plan.total_notes,
        move_counts=counts,
        stage_counts=plan.stage_counts,
    )


def shift_cards(col: Collection, options: ShiftOptions) -> ShiftResult:
    """Compatibility helper that creates and immediately applies a fresh plan."""
    return shift_plan(col, build_plan(col, options))
