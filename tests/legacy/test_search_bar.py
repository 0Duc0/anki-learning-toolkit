"""Default field for Anki's normal Browser search bar (plain text only)."""
import importlib.util
import os
import sys

import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)
import _toolkit
import fixture_user as fx  # noqa: E402

spec = importlib.util.spec_from_file_location("ssa_core_bar", _toolkit.core_path("search"))
core = importlib.util.module_from_spec(spec)
sys.modules["ssa_core_bar"] = core
spec.loader.exec_module(core)


@pytest.fixture(scope="module")
def env():
    col, ids = fx.make()
    meta = core.collect_metadata(col)
    rev = {v: k for k, v in ids.items()}
    yield col, meta, rev
    col.close()


@pytest.mark.parametrize("query,expected", [
    ("學校", "學校"), ("  你好 ", "你好"), ('"tiếng Việt"', "tiếng Việt"), ("eat", "eat"),
    ("Traditional:學校", None), ("deck:current", None), ("a OR b", None), ("-你", None),
    ("(你)", None), ("你*", None), ("_好", None), ("", None), ("is:due", None),
])
def test_only_plain_text_is_rewritten(query, expected):
    assert core.plain_search_text(query) == expected


def test_specific_field_searches_only_that_field(env):
    col, meta, rev = env
    q = core.rewrite_search_bar(col, "陽光", "Traditional", meta.fields)
    assert q.startswith('"Traditional:re:') and sorted(rev[n] for n in col.find_notes(q) if n in rev) == ["yangguang"]


def test_word_choice_searches_word_fields_like_contains(env):
    col, meta, rev = env
    q = core.rewrite_search_bar(col, "你", core.FIELD_WORD, meta.fields)
    assert sorted(rev[n] for n in col.find_notes(q) if n in rev) == ["ni", "nihao", "nimen"]


def test_non_plain_queries_and_off_are_left_alone(env):
    col, meta, _ = env
    assert core.rewrite_search_bar(col, "deck:current", "Traditional", meta.fields) is None
    assert core.rewrite_search_bar(col, "你", "", meta.fields) is None         # off / all fields = Anki's own search
    assert core.rewrite_search_bar(col, "你", "NoSuchField", meta.fields) is None  # unknown field: never an empty result
