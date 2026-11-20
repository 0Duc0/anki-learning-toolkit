"""Collection-only logic for moving complete notes into a deck."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Sequence, TypeVar

from anki.collection import Collection, OpChanges


STAGE_RE = re.compile(r"^([A-Za-z])\.\s*(.+)$")
_T = TypeVar("_T")


def _require_write_ready(col: Collection) -> None:
    """Fail before changing cards when storage or required undo APIs are unavailable."""
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
            "Less than 1 GiB of free space remains. Free space before moving cards."
        )


def _rollback_own_move(col: Collection, undo_entry: int, error: Exception) -> None:
    """Roll back only our serialized custom entry; never undo a previous user action."""
    try:
        col.merge_undo_entries(undo_entry)
        if col.undo_status().last_step != undo_entry:
            raise RuntimeError("The move no longer owns the current undo entry.")
        col.undo()
    except Exception as rollback_error:
        raise RuntimeError(
            "The move failed and automatic rollback could not be confirmed. "
            "Stop making changes and check the collection before syncing. "
            f"Original error: {error}. Rollback error: {rollback_error}"
        ) from error
    raise RuntimeError(
        f"The move failed and its changes were undone. {error}"
    ) from error


@dataclass(frozen=True)
class StageDeck:
    key: str
    deck_id: int
    full_name: str
    label: str


@dataclass(frozen=True)
class StageGroup:
    parent_name: str
    stages: tuple[StageDeck, ...]


@dataclass(frozen=True)
class CardSnapshot:
    card_id: int
    note_id: int
    deck_id: int
    original_deck_id: int


@dataclass(frozen=True)
class SourceSummary:
    deck_name: str
    note_count: int
    card_count: int


@dataclass(frozen=True)
class StageReassignmentWarning:
    parent_name: str
    destination_name: str
    affected_note_count: int
    affected_card_count: int
    sources: tuple[SourceSummary, ...]


@dataclass(frozen=True)
class SelectionContext:
    note_ids: tuple[int, ...]
    groups: tuple[StageGroup, ...]
    card_count: int
    source_deck_ids: tuple[int, ...]


@dataclass(frozen=True)
class NoteMovePlan:
    note_ids: tuple[int, ...]
    destination: StageDeck
    cards: tuple[CardSnapshot, ...]
    sources: tuple[SourceSummary, ...]
    stage_warning: StageReassignmentWarning | None

    @property
    def selected_notes(self) -> int:
        return len(self.note_ids)

    @property
    def selected_cards(self) -> int:
        return len(self.cards)

    @property
    def move_card_ids(self) -> tuple[int, ...]:
        return tuple(
            card.card_id
            for card in self.cards
            if card.deck_id != self.destination.deck_id
        )

    @property
    def move_note_ids(self) -> tuple[int, ...]:
        return tuple(
            sorted(
                {
                    card.note_id
                    for card in self.cards
                    if card.deck_id != self.destination.deck_id
                }
            )
        )

    @property
    def already_there(self) -> int:
        return self.selected_cards - len(self.move_card_ids)

    @property
    def notes_without_cards(self) -> int:
        return self.selected_notes - len({card.note_id for card in self.cards})

    @property
    def stage_reassignment_sources(self) -> tuple[SourceSummary, ...]:
        return self.stage_warning.sources if self.stage_warning else ()

    @property
    def stage_reassignment_card_count(self) -> int:
        return self.stage_warning.affected_card_count if self.stage_warning else 0


@dataclass(frozen=True)
class NoteMoveResult:
    changes: OpChanges
    destination_name: str
    selected_notes: int
    moved_notes: int
    moved_cards: int
    already_there: int
    notes_without_cards: int


def _chunks(items: Sequence[_T], size: int = 500) -> Iterator[Sequence[_T]]:
    for offset in range(0, len(items), size):
        yield items[offset : offset + size]


def _split_parent(full_name: str) -> tuple[str, str]:
    if "::" not in full_name:
        return "", full_name
    parent, leaf = full_name.rsplit("::", 1)
    return parent, leaf


def scan_stage_groups(col: Collection) -> tuple[StageGroup, ...]:
    """Return unambiguous, contiguous sibling sequences beginning with a."""
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
    for parent_name, by_key in candidates.items():
        if any(len(matches) != 1 for matches in by_key.values()):
            continue
        keys = sorted(by_key)
        if not keys or keys[0] != "a":
            continue
        expected = [chr(code) for code in range(ord("a"), ord(keys[-1]) + 1)]
        if keys != expected or len(keys) < 2:
            continue
        stages = tuple(
            StageDeck(
                key=key,
                deck_id=by_key[key][0][0],
                full_name=by_key[key][0][1],
                label=by_key[key][0][2],
            )
            for key in keys
        )
        groups.append(StageGroup(parent_name=parent_name, stages=stages))
    return tuple(sorted(groups, key=lambda group: group.parent_name.casefold()))


def _card_rows_for_notes(
    col: Collection, note_ids: Sequence[int]
) -> list[tuple[int, int, int, int]]:
    rows: list[tuple[int, int, int, int]] = []
    for chunk in _chunks(note_ids):
        placeholders = ",".join("?" for _ in chunk)
        rows.extend(
            (int(card_id), int(note_id), int(deck_id), int(original_deck_id))
            for card_id, note_id, deck_id, original_deck_id in col.db.all(
                f"SELECT id, nid, did, odid FROM cards "
                f"WHERE nid IN ({placeholders}) ORDER BY nid, id",
                *chunk,
            )
        )
    rows.sort(key=lambda row: (row[1], row[0]))
    return rows


def prepare_selection(col: Collection, note_ids: Iterable[int]) -> SelectionContext:
    frozen_note_ids = tuple(sorted({int(note_id) for note_id in note_ids}))
    rows = _card_rows_for_notes(col, frozen_note_ids) if frozen_note_ids else []
    return SelectionContext(
        note_ids=frozen_note_ids,
        groups=scan_stage_groups(col),
        card_count=len(rows),
        source_deck_ids=tuple(sorted({row[2] for row in rows})),
    )


def _deck_name(col: Collection, deck_id: int) -> str:
    deck = col.decks.get(deck_id, default=False)
    return str(deck["name"]) if deck else f"Missing deck ({deck_id})"


def target_for_deck_id(col: Collection, deck_id: int) -> StageDeck:
    """Resolve any normal deck as a quick-move destination."""
    destination_deck = col.decks.get(int(deck_id), default=False)
    if not destination_deck:
        raise RuntimeError("The destination deck no longer exists.")
    if destination_deck.get("dyn"):
        raise RuntimeError(
            "Filtered decks cannot be quick-move destinations. Choose a normal "
            "deck instead. Nothing was changed."
        )

    destination_name = str(destination_deck["name"])
    _parent_name, leaf = _split_parent(destination_name)
    match = STAGE_RE.match(leaf)
    if match:
        key = match.group(1).lower()
        label = f"{key}. {match.group(2)}"
    else:
        key = ""
        label = leaf
    return StageDeck(
        key=key,
        deck_id=int(deck_id),
        full_name=destination_name,
        label=label,
    )


def _stage_reassignment_warning(
    col: Collection,
    destination: StageDeck,
    cards: tuple[CardSnapshot, ...],
    summaries_by_deck_id: dict[int, SourceSummary],
) -> StageReassignmentWarning | None:
    """Describe real stage-to-stage changes inside one validated group."""
    destination_group = next(
        (
            group
            for group in scan_stage_groups(col)
            if any(stage.deck_id == destination.deck_id for stage in group.stages)
        ),
        None,
    )
    if destination_group is None:
        return None

    conflicting_ids = {
        stage.deck_id
        for stage in destination_group.stages
        if stage.deck_id != destination.deck_id
    }
    affected_cards = tuple(card for card in cards if card.deck_id in conflicting_ids)
    if not affected_cards:
        return None

    source_ids = {card.deck_id for card in affected_cards}
    sources = tuple(
        summaries_by_deck_id[deck_id]
        for deck_id in sorted(
            source_ids,
            key=lambda source_id: summaries_by_deck_id[source_id].deck_name.casefold(),
        )
    )
    return StageReassignmentWarning(
        parent_name=destination_group.parent_name,
        destination_name=destination.full_name,
        affected_note_count=len({card.note_id for card in affected_cards}),
        affected_card_count=len(affected_cards),
        sources=sources,
    )


def build_note_move_plan(
    col: Collection,
    note_ids: Sequence[int],
    destination_deck_id: int,
) -> NoteMovePlan:
    frozen_note_ids = tuple(sorted({int(note_id) for note_id in note_ids}))
    if not frozen_note_ids:
        raise RuntimeError("No notes are selected.")

    destination = target_for_deck_id(col, int(destination_deck_id))

    rows = _card_rows_for_notes(col, frozen_note_ids)
    filtered = [row for row in rows if row[3] != 0]
    if filtered:
        raise RuntimeError(
            f"{len(filtered):,} selected card(s) are currently inside a filtered "
            "deck. Empty that filtered deck first, then try again. Nothing was changed."
        )
    cards = tuple(CardSnapshot(*row) for row in rows)

    by_source: dict[int, list[CardSnapshot]] = {}
    for card in cards:
        by_source.setdefault(card.deck_id, []).append(card)
    summaries_by_deck_id = {
        deck_id: SourceSummary(
            deck_name=_deck_name(col, deck_id),
            note_count=len({card.note_id for card in source_cards}),
            card_count=len(source_cards),
        )
        for deck_id, source_cards in sorted(
            by_source.items(), key=lambda item: _deck_name(col, item[0]).casefold()
        )
    }
    summaries = tuple(summaries_by_deck_id.values())
    return NoteMovePlan(
        note_ids=frozen_note_ids,
        destination=destination,
        cards=cards,
        sources=summaries,
        stage_warning=_stage_reassignment_warning(
            col,
            destination,
            cards,
            summaries_by_deck_id,
        ),
    )


def apply_note_move_plan(col: Collection, plan: NoteMovePlan) -> NoteMoveResult:
    """Apply exactly the frozen selection as one undoable operation."""
    _require_write_ready(col)
    destination_deck = col.decks.get(plan.destination.deck_id, default=False)
    if (
        not destination_deck
        or destination_deck.get("dyn")
        or str(destination_deck["name"]) != plan.destination.full_name
    ):
        raise RuntimeError(
            "The quick-move destination changed before the move. Nothing was changed."
        )

    current_rows = _card_rows_for_notes(col, plan.note_ids)
    expected_rows = [
        (card.card_id, card.note_id, card.deck_id, card.original_deck_id)
        for card in plan.cards
    ]
    if current_rows != expected_rows:
        raise RuntimeError(
            "The selected notes or their cards changed before the move. "
            "Try the quick move again. Nothing was changed."
        )

    move_card_ids = plan.move_card_ids
    move_note_ids = plan.move_note_ids
    if not move_card_ids:
        return NoteMoveResult(
            changes=OpChanges(),
            destination_name=plan.destination.full_name,
            selected_notes=plan.selected_notes,
            moved_notes=0,
            moved_cards=0,
            already_there=plan.already_there,
            notes_without_cards=plan.notes_without_cards,
        )

    undo_entry = col.add_custom_undo_entry("Quick move selected notes")
    try:
        col.set_deck(move_card_ids, plan.destination.deck_id)
        moved_destinations: dict[int, int] = {}
        for chunk in _chunks(move_card_ids):
            placeholders = ",".join("?" for _ in chunk)
            moved_destinations.update(
                {
                    int(card_id): int(deck_id)
                    for card_id, deck_id in col.db.all(
                        f"SELECT id, did FROM cards WHERE id IN ({placeholders})",
                        *chunk,
                    )
                }
            )
        if len(moved_destinations) != len(move_card_ids) or any(
            moved_destinations.get(card_id) != plan.destination.deck_id
            for card_id in move_card_ids
        ):
            raise RuntimeError("The post-move verification failed.")
        changes = col.merge_undo_entries(undo_entry)
    except Exception as error:
        _rollback_own_move(col, undo_entry, error)

    return NoteMoveResult(
        changes=changes,
        destination_name=plan.destination.full_name,
        selected_notes=plan.selected_notes,
        moved_notes=len(move_note_ids),
        moved_cards=len(move_card_ids),
        already_there=plan.already_there,
        notes_without_cards=plan.notes_without_cards,
    )
