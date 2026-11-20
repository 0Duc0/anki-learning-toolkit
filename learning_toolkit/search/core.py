"""Pure query construction for Simple Search Assistant."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from anki.collection import Collection, SearchNode

MATCH_EXACT = "exact"
MATCH_CONTAINS = "contains"
MATCH_STARTS = "starts"
MATCH_ENDS = "ends"
MATCH_EMPTY = "empty"
MATCH_NOT_EMPTY = "not_empty"

VALID_MATCHES = {
    MATCH_EXACT,
    MATCH_CONTAINS,
    MATCH_STARTS,
    MATCH_ENDS,
    MATCH_EMPTY,
    MATCH_NOT_EMPTY,
}

STATE_VALUES = {
    "new": SearchNode.CARD_STATE_NEW,
    "learning": SearchNode.CARD_STATE_LEARN,
    "review": SearchNode.CARD_STATE_REVIEW,
    "due": SearchNode.CARD_STATE_DUE,
    "suspended": SearchNode.CARD_STATE_SUSPENDED,
    "buried": SearchNode.CARD_STATE_BURIED,
}


# One-click card filters: (key, label, tooltip).  "" means no filter.
QUICK_FILTERS: tuple[tuple[str, str, str], ...] = (
    ("", "Any", "No card filter"),
    ("new", "New", "Cards you have never studied"),
    ("old", "Old", "Cards you have studied before (everything that is not new)"),
    ("learning", "Learning", "Cards in learning or relearning"),
    ("review", "Review", "Cards you have learned and that come back for review (includes cards being relearned)"),
    ("due", "Due today", "Cards due for review or learning today"),
    ("studied_today", "Studied today", "Cards you answered today"),
    ("failed_today", "Failed today", "Cards you answered Again today"),
    ("added_today", "Added today", "Cards created today"),
    ("suspended", "Suspended", "Cards that are suspended"),
    ("buried", "Buried", "Cards that are buried"),
    ("marked", "Marked", "Notes tagged marked"),
    ("flagged", "Flagged", "Cards with any flag colour"),
)
QUICK_KEYS = {key for key, _label, _tip in QUICK_FILTERS if key}
QUICK_LABELS = {key: label for key, label, _tip in QUICK_FILTERS}


def quick_node(key: str) -> SearchNode:
    """Return the native search node for a quick-filter key."""
    S = SearchNode
    if key in STATE_VALUES:
        return S(card_state=STATE_VALUES[key])
    if key == "old":
        return S(negated=S(card_state=S.CARD_STATE_NEW))
    if key == "studied_today":
        return S(rated=S.Rated(days=1, rating=S.RATING_ANY))
    if key == "failed_today":
        return S(rated=S.Rated(days=1, rating=S.RATING_AGAIN))
    if key == "added_today":
        return S(added_in_days=1)
    if key == "marked":
        return S(tag="marked")
    if key == "flagged":
        return S(negated=S(flag=0))
    raise ValueError("Choose a valid card filter.")


def build_quick_query(col: Collection, key: str, current_query: str = "") -> str:
    """One-click filter, optionally narrowing an existing Browser search."""
    node = col.build_search_string(quick_node(key))
    base = current_query.strip()
    return f"({base}) {node}" if base else node


@dataclass(frozen=True)
class SearchSpec:
    text: str = ""
    field_name: str = ""
    match: str = MATCH_EXACT
    deck_scope: str = "all"
    deck_name: str = ""
    note_type: str = ""
    tag_mode: str = "any"
    tag_name: str = ""
    card_state: str = ""
    current_query: str = ""
    combine_current: bool = False


@dataclass(frozen=True)
class SearchMetadata:
    fields: tuple[str, ...]
    decks: tuple[str, ...]
    note_types: tuple[str, ...]
    tags: tuple[str, ...]
    # note type name -> its field names, in the note type's order
    fields_by_type: tuple[tuple[str, tuple[str, ...]], ...] = ()
    # deck name -> note type names with cards in that deck (subdecks NOT included)
    types_by_deck: tuple[tuple[str, tuple[str, ...]], ...] = ()
    # note type name -> its sort field (the Browser's "Sort Field")
    sort_by_type: tuple[tuple[str, str], ...] = ()

    def types_in_scope(self, deck: str) -> tuple[str, ...]:
        """Note types with cards in ``deck`` or its subdecks ("" = everything)."""
        if not deck or not self.types_by_deck:
            return tuple(name for name, _fields in self.fields_by_type)
        prefix = deck.casefold() + "::"
        found: set[str] = set()
        for name, types in self.types_by_deck:
            folded = name.casefold()
            if folded == deck.casefold() or folded.startswith(prefix):
                found.update(types)
        order = [name for name, _fields in self.fields_by_type]
        return tuple(name for name in order if name in found)


def _deduplicated(values: Iterable[str]) -> tuple[str, ...]:
    by_folded: dict[str, str] = {}
    for value in values:
        cleaned = str(value).strip()
        if cleaned:
            by_folded.setdefault(cleaned.casefold(), cleaned)
    return tuple(sorted(by_folded.values(), key=str.casefold))


def collect_metadata(col: Collection) -> SearchMetadata:
    """Read all dialog choices on Anki's serialized collection thread."""
    fields: list[str] = []
    for notetype in col.models.all():
        try:
            fields.extend(col.models.field_names(notetype))
        except Exception:
            fields.extend(field.get("name", "") for field in notetype.get("flds", []))
    fields_by_type: list[tuple[str, tuple[str, ...]]] = []
    sort_by_type: list[tuple[str, str]] = []
    type_names: dict[int, str] = {}
    for notetype in sorted(col.models.all(), key=lambda nt: str(nt.get("name", "")).casefold()):
        try:
            names = tuple(col.models.field_names(notetype))
        except Exception:
            names = tuple(field.get("name", "") for field in notetype.get("flds", []))
        fields_by_type.append((str(notetype.get("name", "")), names))
        type_names[int(notetype["id"])] = str(notetype.get("name", ""))
        sortf = int(notetype.get("sortf", 0) or 0)
        if 0 <= sortf < len(names):
            sort_by_type.append((str(notetype.get("name", "")), names[sortf]))
    deck_names = {
        deck.id: deck.name for deck in col.decks.all_names_and_ids(include_filtered=False)
    }
    by_deck: dict[str, set[str]] = {}
    try:
        rows = col.db.all(
            "select distinct c.did, n.mid from cards c join notes n on n.id = c.nid"
        )
    except Exception:
        rows = []
    for did, mid in rows:
        deck = deck_names.get(did)
        notetype = type_names.get(mid)
        if deck and notetype:
            by_deck.setdefault(deck, set()).add(notetype)
    return SearchMetadata(
        fields_by_type=tuple(fields_by_type),
        sort_by_type=tuple(sort_by_type),
        types_by_deck=tuple((deck, tuple(sorted(types))) for deck, types in sorted(by_deck.items())),
        fields=_deduplicated(fields),
        decks=_deduplicated(
            deck.name for deck in col.decks.all_names_and_ids(include_filtered=False)
        ),
        note_types=_deduplicated(item.name for item in col.models.all_names_and_ids()),
        tags=_deduplicated(col.tags.all()),
    )


def _empty_field_node(field_name: str, *, negated: bool) -> SearchNode:
    node = SearchNode(
        field=SearchNode.Field(
            field_name=field_name,
            text="",
            mode=SearchNode.FIELD_SEARCH_MODE_NORMAL,
        )
    )
    return SearchNode(negated=node) if negated else node


def _quoted_regex_term(field_name: str, expression: str) -> str:
    """Quote a complete regex term without double-escaping its backslashes.

    Anki 25.09.4's SearchNode serializer doubles regex backslashes.  That turns
    a literal search such as ``a+b`` into a regex for a backslash.  Passing one
    quoted, already escaped term through Anki's parser preserves the intended
    regex and still safely contains spaces, colons and quotation marks.
    """
    term = f"{field_name}:re:{expression}"
    return '"' + term.replace('"', r"\"") + '"'


def _regex_expression(text: str, match: str) -> str:
    escaped = re.escape(text)
    if match == MATCH_EXACT:
        return f"^{escaped}$"
    if match == MATCH_CONTAINS:
        return escaped
    if match == MATCH_STARTS:
        return f"^{escaped}"
    if match == MATCH_ENDS:
        return f"{escaped}$"
    raise ValueError("Choose a valid match type.")


def _field_term(col: Collection, field_name: str, text: str, match: str) -> str:
    if match in {MATCH_EMPTY, MATCH_NOT_EMPTY}:
        return col.build_search_string(
            _empty_field_node(field_name, negated=match == MATCH_NOT_EMPTY)
        )
    return _quoted_regex_term(field_name, _regex_expression(text, match))


def build_query(
    col: Collection,
    spec: SearchSpec,
    available_fields: Iterable[str],
    word_fields: Iterable[str] | None = None,
    meaning_fields: Iterable[str] | None = None,
) -> str:
    """Build a validated, safely escaped Anki query from friendly choices."""
    word_fields = DEFAULT_WORD_FIELDS if word_fields is None else tuple(word_fields)
    meaning_fields = (
        DEFAULT_MEANING_FIELDS if meaning_fields is None else tuple(meaning_fields)
    )
    if spec.match not in VALID_MATCHES:
        raise ValueError("Choose a valid match type.")

    fields = _deduplicated(available_fields)
    terms: list[str] = []

    needs_field = spec.match in {MATCH_EMPTY, MATCH_NOT_EMPTY}
    if needs_field and not spec.field_name:
        raise ValueError("Choose a specific field for empty/not-empty searches.")
    has_other_condition = bool(
        spec.card_state
        or spec.note_type
        or spec.tag_mode in {"include", "exclude"}
        or spec.deck_scope == "specific"
    )
    use_text = needs_field or bool(spec.text)
    if not use_text and not has_other_condition:
        raise ValueError(
            "Enter the text, word, or character you want to find, "
            "or pick New / Old / another card filter."
        )

    if not use_text:
        pass
    elif spec.field_name in {FIELD_WORD, FIELD_MEANING}:
        chosen = resolve_field_choice(
            spec.field_name, fields, word_fields, meaning_fields
        )
        if not chosen:
            raise ValueError("None of the word/meaning fields exist in this collection.")
        terms.append(_or_terms(col, chosen, spec.text, spec.match))
    elif spec.field_name:
        if spec.field_name.casefold() not in {name.casefold() for name in fields}:
            raise ValueError("The selected field no longer exists.")
        terms.append(_text_term(col, spec.field_name, spec.text, spec.match))
    else:
        if not fields:
            raise ValueError("No searchable fields are available in this collection.")
        any_field = " OR ".join(
            _text_term(col, name, spec.text, spec.match) for name in fields
        )
        terms.append(f"({any_field})")

    filter_nodes: list[SearchNode] = []

    if spec.deck_scope == "current":
        filter_nodes.append(SearchNode(deck="current"))
    elif spec.deck_scope == "specific":
        if not spec.deck_name:
            raise ValueError("Choose a deck.")
        filter_nodes.append(SearchNode(deck=spec.deck_name))
    elif spec.deck_scope != "all":
        raise ValueError("Choose a valid deck scope.")

    if spec.note_type:
        filter_nodes.append(SearchNode(note=spec.note_type))

    if spec.tag_mode in {"include", "exclude"}:
        if not spec.tag_name:
            raise ValueError("Choose or enter a tag.")
        tag_node = SearchNode(tag=spec.tag_name)
        filter_nodes.append(
            SearchNode(negated=tag_node) if spec.tag_mode == "exclude" else tag_node
        )
    elif spec.tag_mode != "any":
        raise ValueError("Choose a valid tag filter.")

    if spec.card_state:
        if spec.card_state not in QUICK_KEYS:
            raise ValueError("Choose a valid card filter.")
        filter_nodes.append(quick_node(spec.card_state))

    if spec.combine_current and spec.current_query.strip():
        terms.insert(0, f"({spec.current_query.strip()})")

    if filter_nodes:
        terms.append(col.build_search_string(*filter_nodes))
    if not terms:
        raise ValueError("Choose at least one search condition.")
    return " ".join(terms)


# ---------------------------------------------------------------------------
# Word search (3.0): search the fields that hold the word itself
# ---------------------------------------------------------------------------

# Field names that hold the word / character itself (compared case-insensitively).
DEFAULT_WORD_FIELDS: tuple[str, ...] = (
    "Headword",
    "Simplified",
    "Traditional",
    "Word",
    "Reading",
    "Vietnamese",
    "Zeichen",
    "Hanzi",
    "Kanji",
    "Expression",
    "Vocab",
    "Vocabulary",
    "Front",
)
# Field names that hold a short meaning / translation.
DEFAULT_MEANING_FIELDS: tuple[str, ...] = (
    "Gloss",
    "ProductionPrompt",
    "MainMeaning",
    "English",
    "Schluesselwort",
    "MeaningPromptHTML",
    "Meaning",
    "Back",
)

FIELD_WORD = "@word"
FIELD_MEANING = "@meaning"
FIELD_AUTO = "@auto"   # word fields for characters, word or meaning for Latin text
MATCH_CONTAINS_WORD = "contains_word"
MATCH_RELATED = "related"
VALID_MATCHES.update({MATCH_CONTAINS_WORD, MATCH_RELATED})

WORD_AUTO = "auto"
WORD_EXACT = "exact"
WORD_CONTAINS = "contains"
WORD_RELATED = "related"
WORD_MEANING = "meaning"
WORD_EVERYWHERE = "everywhere"
# (key, label, tooltip) in the order the buttons are shown.
WORD_MODES: tuple[tuple[str, str, str], ...] = (
    (WORD_EXACT, "Exact", "Only notes whose word is exactly this (你 → 你)"),
    (
        WORD_CONTAINS,
        "Contains",
        "Words that contain it: 你 → 你, 你好, 你们 · cứ → cứ, cứ việc "
        "(whole syllables, so not cứu)",
    ),
    (
        WORD_RELATED,
        "Related",
        "Words sharing at least one character or syllable: 你好 → 你, 好, 好人 · "
        "việc làm → việc, làm việc",
    ),
    (
        WORD_MEANING,
        "Meaning",
        "Search the meaning / translation as whole words: eat → 吃, 食べる, ăn "
        "(not great, theater)",
    ),
    (
        WORD_EVERYWHERE,
        "Everywhere",
        "Every field, including examples and long definitions. Finds the most, "
        "but also unrelated notes",
    ),
)
WORD_MODE_KEYS = {key for key, _label, _tip in WORD_MODES} | {WORD_AUTO}
WORD_MATCHES = (WORD_EXACT, WORD_CONTAINS, WORD_RELATED)
_WORD_MATCH = {WORD_EXACT: MATCH_EXACT, WORD_CONTAINS: MATCH_CONTAINS_WORD, WORD_RELATED: MATCH_RELATED}

_CJK_RE = re.compile(
    "[⺀-⿟々぀-ヿ㐀-䶿一-鿿"
    "가-힯豈-﫿\U00020000-\U0003134f]"
)


def is_cjk_text(text: str) -> bool:
    """True when the text contains Chinese/Japanese/Korean characters or kana."""
    return bool(_CJK_RE.search(text))


def _cjk_chars(text: str) -> list[str]:
    seen: list[str] = []
    for char in text:
        if _CJK_RE.match(char) and char not in seen:
            seen.append(char)
    return seen


def _tokens(text: str) -> list[str]:
    seen: list[str] = []
    for token in re.split(r"[\s,;/]+", text.strip()):
        if token and token.casefold() not in {t.casefold() for t in seen}:
            seen.append(token)
    return seen


def _word_regex(text: str, match: str) -> str:
    """Regex for the word-aware match modes (whole syllables / characters)."""
    text = text.strip()
    if match == MATCH_CONTAINS_WORD:
        if is_cjk_text(text):
            return re.escape(text)
        return r"\b" + re.escape(text) + r"\b"
    if match == MATCH_RELATED:
        chars = _cjk_chars(text)
        if chars:
            return "[" + "".join(re.escape(char) for char in chars) + "]"
        tokens = _tokens(text)
        if not tokens:
            raise ValueError("Enter a word.")
        return r"\b(?:" + "|".join(re.escape(token) for token in tokens) + r")\b"
    raise ValueError("Choose a valid match type.")


_SUFFIX = re.compile(r"\s*\([^()]*\)\s*$")


def _base(name: str) -> str:
    """Field name without a trailing "(JP)"-style label, case-folded: "Headword (JP)" -> "headword"."""
    return _SUFFIX.sub("", str(name)).strip().casefold()


def pick_fields(available: Iterable[str], wanted: Iterable[str]) -> tuple[str, ...]:
    """The wanted field names that exist, spelled as the collection spells them.

    A wanted name matches exactly (case-insensitive) or, without its own label, every field that only adds a
    label: "Headword" -> "Headword (JP)", "Headword (VN)"."""
    available = list(available)
    by_folded = {name.casefold(): name for name in available}
    out: list[str] = []
    for name in wanted:
        want = str(name).strip()
        exact = by_folded.get(want.casefold())
        hits = [exact] if exact else ([a for a in available if _base(a) == want.casefold()]
                                      if _base(want) == want.casefold() else [])
        for real in hits:
            if real not in out:
                out.append(real)
    return tuple(out)


def merged_field_list(saved: Iterable[str], defaults: Iterable[str]) -> list[str]:
    """The user's saved list plus any newer default names it doesn't have yet (saved order first)."""
    out = [str(n) for n in saved]
    folded = {n.casefold() for n in out}
    out += [d for d in defaults if d.casefold() not in folded]
    return out


def _text_term(col: Collection, field_name: str, text: str, match: str) -> str:
    if match in {MATCH_CONTAINS_WORD, MATCH_RELATED}:
        return _quoted_regex_term(field_name, _word_regex(text, match))
    return _field_term(col, field_name, text, match)


def _or_terms(col: Collection, fields: Iterable[str], text: str, match: str) -> str:
    terms = [_text_term(col, name, text, match) for name in fields]
    if not terms:
        raise ValueError("None of the chosen fields exist in this collection.")
    return terms[0] if len(terms) == 1 else "(" + " OR ".join(terms) + ")"


@dataclass(frozen=True)
class WordSearch:
    text: str
    mode: str = WORD_CONTAINS
    deck: str = ""  # "" = all decks, "current" = current deck, else a deck name
    card_filter: str = ""
    match: str = WORD_CONTAINS  # how the word fields match in auto mode


def auto_targets(text: str) -> str:
    """What auto mode searches: "word" for characters/kana, "word_or_meaning" for Latin text."""
    return "word" if is_cjk_text(text) else "word_or_meaning"


def build_word_query(
    col: Collection,
    search: WordSearch,
    available_fields: Iterable[str],
    word_fields: Iterable[str] = DEFAULT_WORD_FIELDS,
    meaning_fields: Iterable[str] = DEFAULT_MEANING_FIELDS,
) -> str:
    """Query for the Word search panel."""
    text = search.text.strip()
    if search.mode not in WORD_MODE_KEYS:
        raise ValueError("Choose a valid search mode.")
    available = _deduplicated(available_fields)
    terms: list[str] = []
    if text:
        if search.mode == WORD_EVERYWHERE:
            terms.append(_or_terms(col, available, text, MATCH_CONTAINS))
        elif search.mode == WORD_AUTO:
            match = _WORD_MATCH.get(search.match, MATCH_CONTAINS_WORD)
            words = pick_fields(available, word_fields)
            if auto_targets(text) == "word":
                terms.append(_or_terms(col, words, text, match))
            else:
                parts = [_text_term(col, f, text, match) for f in words]
                parts += [_text_term(col, f, text, MATCH_CONTAINS_WORD) for f in pick_fields(available, meaning_fields)]
                if not parts:
                    raise ValueError("None of the chosen fields exist in this collection.")
                terms.append(parts[0] if len(parts) == 1 else "(" + " OR ".join(parts) + ")")
        elif search.mode == WORD_MEANING:
            fields = pick_fields(available, meaning_fields)
            terms.append(_or_terms(col, fields, text, MATCH_CONTAINS_WORD))
        else:
            fields = pick_fields(available, word_fields)
            match = _WORD_MATCH[search.mode]
            terms.append(_or_terms(col, fields, text, match))
    nodes: list[SearchNode] = []
    if search.deck:
        nodes.append(SearchNode(deck=search.deck))
    if search.card_filter:
        if search.card_filter not in QUICK_KEYS:
            raise ValueError("Choose a valid card filter.")
        nodes.append(quick_node(search.card_filter))
    if nodes:
        terms.append(col.build_search_string(*nodes))
    if not terms:
        raise ValueError("Type a word, or pick a deck or card filter.")
    return " ".join(terms)


def resolve_field_choice(
    field_name: str,
    available: Iterable[str],
    word_fields: Iterable[str] = DEFAULT_WORD_FIELDS,
    meaning_fields: Iterable[str] = DEFAULT_MEANING_FIELDS,
) -> tuple[str, ...]:
    """Fields behind a dialog field choice ("" = all, @word, @meaning, or one field)."""
    available = _deduplicated(available)
    if field_name == FIELD_WORD:
        return pick_fields(available, word_fields)
    if field_name == FIELD_MEANING:
        return pick_fields(available, meaning_fields)
    if not field_name:
        return available
    return pick_fields(available, [field_name])


# --- default field for Anki's normal Browser search bar -------------------------------------------

_SEARCH_SYNTAX = re.compile(r"[:()*_\\]|^-|\s(?:or|and)\s", re.IGNORECASE)


def plain_search_text(query: str) -> str | None:
    """The typed text if the query is plain words (no Anki search syntax), else None."""
    text = (query or "").strip()
    if len(text) >= 2 and text[0] == text[-1] == '"':
        text = text[1:-1].strip()
    if not text or '"' in text or _SEARCH_SYNTAX.search(text):
        return None
    return text


def rewrite_search_bar(
    col: Collection,
    query: str,
    field_choice: str,
    available_fields: Iterable[str],
    word_fields: Iterable[str] = DEFAULT_WORD_FIELDS,
    meaning_fields: Iterable[str] = DEFAULT_MEANING_FIELDS,
) -> str | None:
    """Plain text typed in the search bar -> the same 'contains' search limited to the default field(s).

    None means: leave Anki's own search alone (syntax used, default off, or the field doesn't exist).
    """
    text = plain_search_text(query)
    if text is None or not field_choice:
        return None
    if field_choice == FIELD_AUTO:
        words = pick_fields(_deduplicated(available_fields), word_fields)
        if auto_targets(text) == "word":
            return _or_terms(col, words, text, MATCH_CONTAINS_WORD) if words else None
        both = list(words) + [f for f in pick_fields(_deduplicated(available_fields), meaning_fields) if f not in words]
        return _or_terms(col, both, text, MATCH_CONTAINS_WORD) if both else None
    fields = resolve_field_choice(field_choice, available_fields, word_fields, meaning_fields)
    if not fields:
        return None
    return _or_terms(col, fields, text, MATCH_CONTAINS_WORD)


# --- recommendations for the deck the Browser shows (user 2026-11-19) -------------------------------------
_ID_LIKE = re.compile(r"(id|key|guid|sort\w*|nr|number)$", re.IGNORECASE)
_DECK_RE = re.compile(r'(?:^|\s)"?deck:(?:"([^"]+)"|([^\s"]+))')


def deck_from_search(query: str) -> str:
    """The deck a Browser search is limited to ("" if none, excluded, or "current")."""
    m = _DECK_RE.search(query or "")
    if not m:
        return ""
    deck = (m.group(1) or m.group(2) or "").strip().rstrip("*").rstrip(":")
    return "" if deck.casefold() in ("", "current", "filtered") else deck


def recommended_fields(meta: SearchMetadata, deck: str, limit: int = 3) -> tuple[str, ...]:
    """Sort fields of the deck's note types first, then their word fields (e.g. Traditional, Simplified)."""
    if not deck:
        return ()
    types = meta.types_in_scope(deck)
    if not types or len(types) == len(meta.fields_by_type) and meta.types_by_deck and not any(
            n.casefold() == deck.casefold() or n.casefold().startswith(deck.casefold() + "::")
            for n, _t in meta.types_by_deck):
        return ()
    sort = dict(meta.sort_by_type)
    fields_by_type = dict(meta.fields_by_type)
    out: list[str] = []
    for t in types:
        name = sort.get(t, "")
        if name and not _ID_LIKE.search(name) and name not in out:   # an ID or sort key is no help to search
            out.append(name)
    in_scope = [f for t in types for f in fields_by_type.get(t, ())]
    for f in pick_fields(in_scope, DEFAULT_WORD_FIELDS):
        if f not in out:
            out.append(f)
    return tuple(out[:limit])
