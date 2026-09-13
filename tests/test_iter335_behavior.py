"""Iteration 335 -- BLACK-BOX behavior tests: doc_anchor_gaps, the doc-citation oracle.

The iteration's product is `foundry.doc_anchor_gaps(docs, sources)`: a PURE oracle
that reports every rotting `<file>.py|md:<line>` citation and every unresolvable
single-backticked `` `<file>::<anchor>` `` in the docs it is handed, plus the repair
of the ten line-number citations that `docs/DISCOVERY_LOOP_PLAN.md` carried at HEAD.

ISOLATION CONTRACT (HONORED).  Every assertion below was derived from this
iteration's PM spec (`pm.md`, Expected Behaviors 1-8 and its repair table) and from
the conventions of the existing modules under `tests/` (chiefly
`test_iter333_behavior.py`).  I did NOT read `foundry.py`'s implementation text,
`engineer.md`, `reviewer.md`, or `git diff`.  The surface is driven as a BLACK BOX:
the public function is called with plain dicts and its returned strings asserted.
The two artifacts this iteration SHIPS as observable output -- the tracked doc
`docs/DISCOVERY_LOOP_PLAN.md` and the oracle's return value -- are read as output,
never as implementation.

OFFLINE + FRESH-CLONE SAFE.  Behaviors 1-6 are decided entirely from literal dicts:
no filesystem, no subprocess, no git, no network, no clock.  Behaviors 7 and 8 read
three files plus one doc that `git ls-files` tracks, located at runtime from
`__file__` -- never a gitignored path, never an ambient file count, never an
absolute machine path or username as a source literal.
"""
from __future__ import annotations

import builtins
import inspect
import pathlib
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe -- the product quality bar)

THIS_ITER = 335

# The doc this iteration repairs, and the three sources its anchors point into.
# All four are tracked, so a throwaway fresh clone has them (OPERATOR 2026-08-11).
DOC_REL = "docs/DISCOVERY_LOOP_PLAN.md"
SOURCE_RELS = ("foundry.py", "dispatcher.py", "roles/pm.md")


def _read(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# Behavior 1 -- module-level, exactly (docs, sources), returns tuple[str], PURE
# --------------------------------------------------------------------------


def test_b1_is_a_module_level_function_taking_exactly_docs_and_sources():
    fn = getattr(foundry, "doc_anchor_gaps", None)
    assert fn is not None, "foundry.doc_anchor_gaps is missing"
    assert inspect.isfunction(fn), f"not a plain module-level function: {type(fn)!r}"
    params = list(inspect.signature(fn).parameters)
    assert params == ["docs", "sources"], params


def test_b1_returns_a_tuple_of_str():
    out = foundry.doc_anchor_gaps({"d.md": "`x.py::gone`"}, {"x.py": "hi"})
    assert isinstance(out, tuple), type(out)
    assert out and all(isinstance(item, str) for item in out), out


def test_b1_is_pure_no_filesystem_subprocess_or_network(monkeypatch):
    """Called with plain dicts it touches nothing outside its arguments."""

    def _boom(name):
        def _explode(*a, **k):
            raise AssertionError(f"doc_anchor_gaps reached {name}")

        return _explode

    monkeypatch.setattr(builtins, "open", _boom("open()"))
    monkeypatch.setattr(pathlib.Path, "open", _boom("Path.open"))
    monkeypatch.setattr(pathlib.Path, "read_text", _boom("Path.read_text"))
    monkeypatch.setattr(pathlib.Path, "exists", _boom("Path.exists"))
    monkeypatch.setattr(subprocess, "run", _boom("subprocess.run"))
    monkeypatch.setattr(subprocess, "check_output", _boom("subprocess.check_output"))

    out = foundry.doc_anchor_gaps(
        {"d.md": "`x.py::gone` plus `y.py:5`"}, {"x.py": "hi"}
    )
    assert len(out) == 2, out


def test_b1_never_reads_a_key_as_a_path():
    """A key naming a REAL tracked file is still resolved only against the
    supplied text: the shipped `foundry.py` does contain `def doc_anchor_gaps`,
    yet the supplied text does not, so the anchor must come back unresolved."""
    out = foundry.doc_anchor_gaps(
        {"foundry.py": "`foundry.py::def doc_anchor_gaps`"},
        {"foundry.py": "nothing to see"},
    )
    assert len(out) == 1, out
    assert out[0].startswith("foundry.py:1: unresolved-anchor: "), out[0]
    assert "def doc_anchor_gaps" in out[0], out[0]


# --------------------------------------------------------------------------
# Behavior 2 -- the empty and the clean case
# --------------------------------------------------------------------------


def test_b2_empty_input_returns_empty_tuple():
    assert foundry.doc_anchor_gaps({}, {}) == ()


def test_b2_a_doc_with_neither_shape_returns_empty_tuple():
    clean = (
        "# A title\n"
        "\n"
        "Prose that names foundry.py and roles/pm.md with no line number,\n"
        "mentions a ratio of 5:1 and a time of 12:30, and stops there.\n"
    )
    assert foundry.doc_anchor_gaps({"d.md": clean}, {}) == ()


# --------------------------------------------------------------------------
# Behavior 3 -- LINE-CITATION detection
# --------------------------------------------------------------------------


def test_b3_backticked_line_citation_is_one_finding_with_the_documented_prefix():
    out = foundry.doc_anchor_gaps({"d.md": "see `foundry.py:13086` now"}, {})
    assert len(out) == 1, out
    assert out[0].startswith("d.md:1: line-citation: "), out[0]
    assert "foundry.py:13086" in out[0], out[0]


@pytest.mark.parametrize(
    "text, cited",
    [
        ("see `foundry.py:13086` now", "foundry.py:13086"),   # backticked .py
        ("see foundry.py:13086 now", "foundry.py:13086"),     # bare .py
        ("see `roles/pm.md:91` now", "roles/pm.md:91"),       # backticked .md
        ("see roles/pm.md:91 now", "roles/pm.md:91"),         # bare .md
    ],
)
def test_b3_shape_is_detected_for_py_and_md_backticked_or_bare(text, cited):
    out = foundry.doc_anchor_gaps({"d.md": text}, {})
    assert len(out) == 1, out
    assert out[0].startswith("d.md:1: line-citation: "), out[0]
    assert cited in out[0], out[0]


def test_b3_line_number_is_one_based_and_reports_the_defect_line():
    doc = "first line\nsecond line\nsee `foundry.py:13086` now\n"
    out = foundry.doc_anchor_gaps({"d.md": doc}, {})
    assert len(out) == 1, out
    assert out[0].startswith("d.md:3: line-citation: "), out[0]


def test_b3_a_line_citation_needs_no_sources_entry_to_be_a_finding():
    """The shape alone convicts -- `sources={}` still reports it."""
    assert len(foundry.doc_anchor_gaps({"d.md": "`foundry.py:1`"}, {})) == 1


# --------------------------------------------------------------------------
# Behavior 4 -- a RESOLVING anchor yields no finding
# --------------------------------------------------------------------------


def test_b4_resolving_anchor_yields_no_finding():
    out = foundry.doc_anchor_gaps(
        {"d.md": "at `foundry.py::def f`"}, {"foundry.py": "def f():\n    pass\n"}
    )
    assert out == (), out


def test_b4_resolution_is_a_plain_substring_test_not_a_symbol_lookup():
    """The spec's contract is presence, not definition: a CALL SITE resolves."""
    src = "def f():\n    pass\n\nresult = f(cfg, iteration)\n"
    assert foundry.doc_anchor_gaps({"d.md": "at `m.py::f(cfg, iteration)`"}, {"m.py": src}) == ()
    # ... and a mid-line fragment resolves too, because presence is the whole test
    assert foundry.doc_anchor_gaps({"d.md": "at `m.py::sult = f(`"}, {"m.py": src}) == ()


def test_b4_an_anchor_is_recognised_only_inside_a_single_backtick_span():
    """Un-backticked `::` text has no unambiguous end, so it is not an anchor."""
    src = {"foundry.py": "def f():\n    pass\n"}
    assert foundry.doc_anchor_gaps({"d.md": "at foundry.py::def zzz here"}, src) == ()
    # inside a span, the same missing text IS reported
    assert len(foundry.doc_anchor_gaps({"d.md": "at `foundry.py::def zzz`"}, src)) == 1


# --------------------------------------------------------------------------
# Behavior 5 -- UNRESOLVED-ANCHOR detection, two ways
# --------------------------------------------------------------------------


def test_b5a_path_present_but_anchor_text_absent():
    out = foundry.doc_anchor_gaps(
        {"d.md": "at `foundry.py::def zzz`"}, {"foundry.py": "def f():\n    pass\n"}
    )
    assert len(out) == 1, out
    assert out[0].startswith("d.md:1: unresolved-anchor: "), out[0]
    assert "foundry.py" in out[0] and "def zzz" in out[0], out[0]


def test_b5b_path_absent_from_sources_entirely():
    out = foundry.doc_anchor_gaps({"d.md": "at `nope.py::def f`"}, {})
    assert len(out) == 1, out
    assert out[0].startswith("d.md:1: unresolved-anchor: "), out[0]
    assert "nope.py" in out[0] and "def f" in out[0], out[0]


def test_b5_the_two_ways_are_distinguishable_in_the_finding_text():
    absent = foundry.doc_anchor_gaps({"d.md": "`nope.py::def f`"}, {})[0]
    present = foundry.doc_anchor_gaps({"d.md": "`m.py::def f`"}, {"m.py": "x"})[0]
    assert absent != present, (absent, present)


# --------------------------------------------------------------------------
# Behavior 6 -- deterministic and ordered by (doc path, line number, kind)
# --------------------------------------------------------------------------


def test_b6_two_calls_on_equal_input_return_equal_tuples():
    docs = {"d.md": "`x.py::gone`\n\n`y.py:5`\n"}
    sources = {"x.py": "hi"}
    first = foundry.doc_anchor_gaps(docs, sources)
    second = foundry.doc_anchor_gaps(dict(docs), dict(sources))
    assert first == second, (first, second)


def test_b6_a_line_2_anchor_sorts_before_a_line_5_citation():
    doc = "one\n`x.py::gone`\nthree\nfour\n`y.py:5`\n"
    out = foundry.doc_anchor_gaps({"d.md": doc}, {"x.py": "hi"})
    assert len(out) == 2, out
    assert out[0].startswith("d.md:2: unresolved-anchor: "), out
    assert out[1].startswith("d.md:5: line-citation: "), out


def test_b6_findings_sort_by_doc_path_then_line_then_kind():
    docs = {
        "z.md": "`y.py:9`\n",
        "a.md": "`y.py:5` and `x.py::gone`\n",
    }
    out = foundry.doc_anchor_gaps(docs, {"x.py": "hi"})
    assert len(out) == 3, out
    assert out[0].startswith("a.md:1: line-citation: "), out
    assert out[1].startswith("a.md:1: unresolved-anchor: "), out
    assert out[2].startswith("z.md:1: line-citation: "), out
    # the sort is total and stable -- an insertion-order swap changes nothing
    assert foundry.doc_anchor_gaps(dict(reversed(list(docs.items()))), {"x.py": "hi"}) == out


# --------------------------------------------------------------------------
# Behavior 7 -- the LIVE CENSUS over the real tracked tree (permanent brake)
# --------------------------------------------------------------------------


def _census_inputs():
    return {DOC_REL: _read(DOC_REL)}, {rel: _read(rel) for rel in SOURCE_RELS}


def test_b7_live_census_over_the_shipped_doc_is_clean():
    docs, sources = _census_inputs()
    findings = foundry.doc_anchor_gaps(docs, sources)
    assert findings == (), "\n".join(findings)


def test_b7_the_shipped_doc_carries_no_line_number_citation_at_all():
    """Independent of the oracle: no `<file>.py|md:<digits>` text survives."""
    import re

    hits = re.findall(r"[\w./-]+\.(?:py|md):\d+", _read(DOC_REL))
    assert hits == [], hits


def test_b7_every_anchor_in_the_shipped_doc_resolves_and_there_are_ten_of_them():
    """The repair table converted 10 citations, so the doc must carry >= 10
    resolvable anchors -- a doc that simply DELETED them would also be clean."""
    import re

    doc = _read(DOC_REL)
    spans = re.findall(r"`([^`\n]+?::[^`\n]+?)`", doc)
    assert len(spans) >= 10, spans
    sources = {rel: _read(rel) for rel in SOURCE_RELS}
    for span in spans:
        path, _, anchor = span.partition("::")
        assert path in sources, f"anchor cites an unsupplied source: {span}"
        assert anchor in sources[path], f"anchor does not resolve: {span}"


def test_b7_the_census_brake_is_not_vacuous_it_fires_on_a_mutated_doc():
    """Three mutations of the REAL doc text, each in memory only: a
    re-introduced line citation, a corrupted anchor, and a source withheld."""
    docs, sources = _census_inputs()
    doc = docs[DOC_REL]

    reintroduced = doc.replace("`foundry.py::def build_prompt`", "`foundry.py:12829`", 1)
    assert reintroduced != doc, "fixture anchor not present -- mutation was a no-op"
    out = foundry.doc_anchor_gaps({DOC_REL: reintroduced}, sources)
    assert len(out) == 1 and "line-citation: foundry.py:12829" in out[0], out

    corrupted = doc.replace("`foundry.py::PM_SCOUT_LENS_POOL`", "`foundry.py::PM_SCOUT_LENS_POOOL`", 1)
    assert corrupted != doc, "fixture anchor not present -- mutation was a no-op"
    out = foundry.doc_anchor_gaps({DOC_REL: corrupted}, sources)
    assert len(out) == 1 and "unresolved-anchor: foundry.py::PM_SCOUT_LENS_POOOL" in out[0], out

    withheld = {rel: text for rel, text in sources.items() if rel != "roles/pm.md"}
    out = foundry.doc_anchor_gaps(docs, withheld)
    assert len(out) == 1 and "unresolved-anchor: roles/pm.md::" in out[0], out


# --------------------------------------------------------------------------
# Behavior 8 -- the convention paragraph is REWRITTEN IN PLACE
# --------------------------------------------------------------------------


def test_b8_convention_paragraph_states_the_anchor_form_and_bans_line_numbers():
    doc = _read(DOC_REL)
    assert "A BARE\nLINE NUMBER IS BANNED" in doc or "A BARE LINE NUMBER IS BANNED" in doc, (
        "the convention paragraph does not state the ban"
    )
    # it names the checkable two-colon form, and shows a resolvable example of it
    assert "two colons" in doc, "the paragraph does not name the `<file>::<anchor>` form"
    assert "`foundry.py::def build_prompt`" in doc, "no worked example of the form"


def test_b8_the_stale_dormancy_claims_of_the_old_paragraph_are_gone():
    """The paragraph is EDITED, not merely appended to: the wording it replaced
    (the line number called `a convenience that drifts`) must be gone."""
    doc = _read(DOC_REL)
    assert "a convenience that drifts" not in doc, doc[:400]


def test_b8_no_other_paragraph_of_the_doc_was_deleted():
    """Structure census: the STATUS block, all four bite headings, the SHIPPED /
    SATISFIED markers and the section-8 embargo text all survive the edit."""
    doc = _read(DOC_REL)
    assert "## STATUS -- READ THIS FIRST" in doc or "## STATUS" in doc, doc[:200]
    for bite in ("Bite 1", "Bite 2", "Bite 3", "Bite 4", "Bite 5"):
        assert bite in doc, f"missing {bite}"
    assert doc.count("**SHIPPED**") >= 4, doc.count("**SHIPPED**")
    assert "**SATISFIED**" in doc, "the section-8 embargo release marker is gone"
    assert "do not ship another" in doc, "the section-8 embargo text is gone"
    for heading in ("## 1.", "## 8."):
        assert heading in doc, f"missing section heading {heading}"


def test_b8_the_doc_is_still_the_operator_directive_it_was():
    doc = _read(DOC_REL)
    assert "OPERATOR DIRECTIVE" in doc
    assert doc.lstrip().startswith("# Continuous discovery loop"), doc[:80]
