"""Iteration 239 -- BLACK-BOX behavior tests: two pure, total, DORMANT helpers that
derive the tracked top-level role-card inventory and diff it against a doc's text,
plus the LIVE brake that pins ``README.md``'s repo map to the shipping tree.

Spec under test (products/_platform/state/iter-239/pm.md), Expected Behaviors 1-5:
   1. ``top_level_role_card_names(paths)`` -- SORTED, DEDUPED tuple of the basenames
      of path STRINGS that sit DIRECTLY inside ``roles/`` and end in ``.md``; nested
      (``roles/bench/*``), non-``roles/`` and non-``.md`` members excluded; TOTAL over
      an empty iterable and over all-excluded input, including the awkward members
      ``"roles/"``, ``"roles"``, ``"ROLES/pm.md"``, ``"roles/x.txt"`` and ``""``.
   2. ``role_card_doc_gaps(card_names, doc_text)`` -- SORTED, DEDUPED tuple of the
      names absent as a verbatim substring of ``doc_text``, ``()`` when all appear;
      takes TEXT, never paths; TOTAL for empty ``card_names`` and for ``doc_text == ""``.
   3. Both PURE and DORMANT -- (a) eleven named I/O / clock entry points monkeypatched
      to raise and both functions still return their documented values; (b) an ``ast``
      census of ``foundry.py``, ``dispatcher.py`` and ``watchdog.py`` finds ZERO ``Call``
      sites naming either function outside its own ``def``.
   4. LIVE BRAKE from the shipping tree -- names derived by feeding ``git ls-files --
      roles/`` stdout through behavior 1: (a) non-vacuity floor >= 8 entries INCLUDING
      ``pm_scout.md``; (b) ``role_card_doc_gaps(derived, README text) == ()``;
      (c) FAILABILITY via one planted ``zz_planted_card.md``.
   5. README repo-map content -- (a) neither ``7 project-agnostic`` nor
      ``11 versioned role-cards`` appears anywhere in the file; (b) the row beginning
      ``| `roles/` |`` carries all 8 basenames verbatim ON THAT ONE ROW; (c) the row
      beginning ``| `roles/bench/` |`` still contains ``versioned role-cards``.

ISOLATION CONTRACT (HONORED): written ONLY from the iteration-239 PM spec, the
conventions of ``tests/`` (mirroring ``tests/test_iter227_behavior.py``'s dormancy
census and ``tests/test_iter238_behavior.py``'s purity raisers), and the product's OWN
OBSERVABLE surface -- importing ``foundry`` and calling the two public oracles under
test.  I did NOT read the implementation source of ``foundry.py`` (behavior 3b hands it
to ``ast`` as opaque TEXT, read programmatically), nor ``engineer.md``, ``reviewer.md``,
nor ``git diff``.

Every path read below (``foundry.py``, ``dispatcher.py``, ``watchdog.py``, ``README.md``)
and every name derived (via ``git ls-files``, i.e. exactly what a fresh clone has) is
GIT-TRACKED, so these preconditions hold in a throwaway clone -- OPERATOR 2026-08-11.
No absolute machine path appears anywhere in this file (OPERATOR/iter-205 leak guard).
"""

import ast
import builtins
import io
import os
import pathlib
import socket
import subprocess
import sys
import time

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402
import dispatcher  # noqa: E402  -- in-process import-safety probe

THIS_ITER = 239

_FOUNDRY_PY = _ROOT / "foundry.py"
_DISPATCHER_PY = _ROOT / "dispatcher.py"
_WATCHDOG_PY = _ROOT / "watchdog.py"
_README = _ROOT / "README.md"

NEW_NAMES = ("role_card_doc_gaps", "top_level_role_card_names")

# The 8 tracked top-level cards the README map must name (behavior 5b).  Kept as a
# literal so the test states the SPEC's claim; behavior 4 proves the shipping tree
# agrees with it rather than the other way round.
SPEC_CARD_BASENAMES = (
    "engineer.md",
    "final.md",
    "fix.md",
    "pm.md",
    "pm_scout.md",
    "reporter.md",
    "reviewer.md",
    "tester.md",
)

PLANTED = "zz_planted_card.md"


# ============================================================ Behavior 1


def test_b1_worked_example_exactly_as_specced():
    """The spec's own worked equality, asserted verbatim."""
    assert foundry.top_level_role_card_names(
        (
            "roles/pm.md",
            "roles/engineer.md",
            "roles/bench/ceo.md",
            "roles/bench/README.md",
            "docs/pm.md",
            "roles/notes.txt",
            "roles/pm.md",
        )
    ) == ("engineer.md", "pm.md")


def test_b1_result_is_a_tuple_sorted_and_deduped():
    got = foundry.top_level_role_card_names(
        ["roles/tester.md", "roles/pm.md", "roles/tester.md", "roles/engineer.md"]
    )
    assert isinstance(got, tuple), "must be a tuple, got %r" % (type(got),)
    assert got == ("engineer.md", "pm.md", "tester.md")
    assert list(got) == sorted(got), "must be sorted"
    assert len(set(got)) == len(got), "must be deduped"


def test_b1_declaration_order_does_not_change_the_result():
    a = foundry.top_level_role_card_names(("roles/a.md", "roles/b.md", "roles/c.md"))
    b = foundry.top_level_role_card_names(("roles/c.md", "roles/a.md", "roles/b.md"))
    assert a == b == ("a.md", "b.md", "c.md")


def test_b1_total_over_empty_iterable():
    assert foundry.top_level_role_card_names(()) == ()
    assert foundry.top_level_role_card_names([]) == ()
    assert foundry.top_level_role_card_names(iter([])) == ()


@pytest.mark.parametrize(
    "member",
    [
        "roles/",
        "roles",
        "ROLES/pm.md",
        "roles/x.txt",
        "",
        "roles/bench/ceo.md",
        "roles/bench/README.md",
        "docs/pm.md",
        "notroles/pm.md",
        "roles/a/b/c.md",
    ],
)
def test_b1_each_excluded_member_is_individually_excluded(member):
    """TOTAL: an all-excluded input returns () and raises nothing."""
    assert foundry.top_level_role_card_names((member,)) == ()


def test_b1_all_awkward_members_together_return_empty():
    awkward = ("roles/", "roles", "ROLES/pm.md", "roles/x.txt", "")
    assert foundry.top_level_role_card_names(awkward) == ()


def test_b1_one_kept_member_survives_a_crowd_of_excluded_ones():
    """Non-vacuity for the exclusion rules: the filter is not simply rejecting all."""
    mixed = ("roles/", "roles", "ROLES/pm.md", "roles/x.txt", "", "roles/final.md")
    assert foundry.top_level_role_card_names(mixed) == ("final.md",)


def test_b1_input_is_not_mutated_and_repeat_calls_agree():
    src = ["roles/pm.md", "roles/bench/ceo.md", "roles/pm.md"]
    snapshot = list(src)
    first = foundry.top_level_role_card_names(src)
    second = foundry.top_level_role_card_names(src)
    assert first == second == ("pm.md",)
    assert src == snapshot, "the input must not be mutated"


# ============================================================ Behavior 2


def test_b2_worked_example_exactly_as_specced():
    assert foundry.role_card_doc_gaps(("pm.md", "pm_scout.md"), "see roles/pm.md") == (
        "pm_scout.md",
    )


def test_b2_empty_tuple_when_every_name_appears():
    doc = "cards: engineer.md, pm.md, tester.md"
    assert foundry.role_card_doc_gaps(("pm.md", "tester.md", "engineer.md"), doc) == ()


def test_b2_gaps_are_sorted_and_deduped_and_a_tuple():
    got = foundry.role_card_doc_gaps(
        ("tester.md", "pm.md", "tester.md", "engineer.md"), "only pm.md here"
    )
    assert isinstance(got, tuple), "must be a tuple, got %r" % (type(got),)
    assert got == ("engineer.md", "tester.md")
    assert list(got) == sorted(got) and len(set(got)) == len(got)


def test_b2_total_for_empty_card_names_whatever_the_doc_text():
    for doc in ("", "anything at all", "pm.md tester.md"):
        assert foundry.role_card_doc_gaps((), doc) == ()
    assert foundry.role_card_doc_gaps([], "") == ()


def test_b2_full_sorted_tuple_when_doc_text_is_empty():
    assert foundry.role_card_doc_gaps(SPEC_CARD_BASENAMES, "") == tuple(
        sorted(SPEC_CARD_BASENAMES)
    )
    assert foundry.role_card_doc_gaps(("tester.md", "pm.md"), "") == ("pm.md", "tester.md")


def test_b2_matching_is_a_verbatim_substring_test_not_a_path_test():
    """It takes the doc TEXT, never paths -- a name embedded in a longer path counts."""
    assert foundry.role_card_doc_gaps(("pm.md",), "| `roles/pm.md` |") == ()
    assert foundry.role_card_doc_gaps(("pm.md",), "roles/PM.MD") == ("pm.md",)


def test_b2_input_is_not_mutated_and_repeat_calls_agree():
    names = ["pm.md", "tester.md"]
    snapshot = list(names)
    doc = "pm.md"
    assert foundry.role_card_doc_gaps(names, doc) == foundry.role_card_doc_gaps(names, doc)
    assert names == snapshot, "the input must not be mutated"


# ============================================================ Behavior 3(a) -- PURITY


def test_b3a_both_calls_are_pure_no_io_no_subprocess_no_socket_no_clock(monkeypatch):
    """Every named filesystem / subprocess / network / clock entry point raises here,
    so a hidden read, shell-out, connection or clock read fails loudly instead of
    silently passing."""

    def _boom(*_a, **_k):  # pragma: no cover - only runs if purity is violated
        raise AssertionError("impure: the helper touched a forbidden entry point")

    monkeypatch.setattr(builtins, "open", _boom)
    monkeypatch.setattr(io, "open", _boom, raising=False)
    monkeypatch.setattr(pathlib.Path, "read_text", _boom)
    monkeypatch.setattr(pathlib.Path, "open", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)
    monkeypatch.setattr(subprocess, "check_output", _boom)
    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(os, "system", _boom)
    monkeypatch.setattr(time, "time", _boom)
    monkeypatch.setattr(time, "monotonic", _boom)

    assert foundry.top_level_role_card_names(
        (
            "roles/pm.md",
            "roles/engineer.md",
            "roles/bench/ceo.md",
            "roles/bench/README.md",
            "docs/pm.md",
            "roles/notes.txt",
            "roles/pm.md",
        )
    ) == ("engineer.md", "pm.md")
    assert foundry.top_level_role_card_names(()) == ()
    assert foundry.role_card_doc_gaps(("pm.md", "pm_scout.md"), "see roles/pm.md") == (
        "pm_scout.md",
    )
    assert foundry.role_card_doc_gaps((), "") == ()


def test_b3a_control_the_raisers_really_do_fire(monkeypatch):
    """The purity probe above is only meaningful if a real read WOULD raise."""

    def _boom(*_a, **_k):
        raise AssertionError("raiser fired")

    monkeypatch.setattr(pathlib.Path, "read_text", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)
    with pytest.raises(AssertionError):
        _README.read_text(encoding="utf-8")
    with pytest.raises(AssertionError):
        subprocess.run(["git", "--version"])


# ============================================================ Behavior 3(b) -- DORMANCY


def _module_level_defs(tree):
    return [
        n.name
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in NEW_NAMES
    ]


def test_b3b_both_helpers_are_defined_exactly_once_at_module_level():
    """ANTI-VACUITY for the census below: 'zero call sites' is trivially true of a
    name that does not exist, so first demand each helper IS shipped."""
    tree = ast.parse(_FOUNDRY_PY.read_text(encoding="utf-8"))
    defined = _module_level_defs(tree)
    for name in NEW_NAMES:
        assert defined.count(name) == 1, (
            "%s must be defined exactly once at module level in foundry.py, found %d"
            % (name, defined.count(name))
        )


@pytest.mark.parametrize(
    "path", [_FOUNDRY_PY, _DISPATCHER_PY, _WATCHDOG_PY], ids=lambda p: p.name
)
def test_b3b_no_call_site_for_either_helper_anywhere(path):
    """Dormant-additive: with zero call sites, no prompt, artifact, exit code or resume
    path can change this iteration, so a loop in flight resumes byte-identically."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    called = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if name in NEW_NAMES:
            called.append((name, getattr(node, "lineno", -1)))
    assert called == [], "%s must not call the new helpers, found: %r" % (path.name, called)


def test_b3b_control_the_ast_walk_really_would_see_a_call_site():
    """The census is only meaningful if it can FIND a call -- prove it on a sample."""
    sample = (
        "def f(paths, doc):\n"
        "    return role_card_doc_gaps(top_level_role_card_names(paths), doc)\n"
    )
    hits = sorted(
        getattr(n.func, "id", None)
        for n in ast.walk(ast.parse(sample))
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) in NEW_NAMES
    )
    assert hits == ["role_card_doc_gaps", "top_level_role_card_names"]


def test_b3b_control_the_ast_walk_also_sees_an_attribute_call_site():
    sample = "def f(p):\n    return foundry.top_level_role_card_names(p)\n"
    hits = [
        getattr(n.func, "attr", None)
        for n in ast.walk(ast.parse(sample))
        if isinstance(n, ast.Call) and getattr(n.func, "attr", None) in NEW_NAMES
    ]
    assert hits == ["top_level_role_card_names"]


def test_b3b_both_helpers_are_public_callables_and_both_modules_import():
    for name in NEW_NAMES:
        assert callable(getattr(foundry, name)), "%s must be a public callable" % name
    assert hasattr(dispatcher, "__file__"), "dispatcher must stay importable"


# ============================================================ Behavior 4 -- LIVE BRAKE


def _derived_card_names():
    """Names of the TRACKED top-level role cards, i.e. exactly what a fresh clone has.

    Skips (never passes vacuously) when git is unavailable or exits non-zero.
    """
    try:
        proc = subprocess.run(
            ["git", "ls-files", "--", "roles/"],
            cwd=str(_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover
        pytest.skip("git unavailable: %s" % (exc,))
    if proc.returncode != 0:  # pragma: no cover
        pytest.skip("git ls-files exited %d: %s" % (proc.returncode, proc.stderr.strip()))
    lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    if not lines:  # pragma: no cover
        pytest.skip("git ls-files -- roles/ produced no paths; derivation would be vacuous")
    return foundry.top_level_role_card_names(lines)


def test_b4a_non_vacuity_floor_at_least_eight_cards_including_pm_scout():
    derived = _derived_card_names()
    assert len(derived) >= 8, "expected >= 8 tracked top-level role cards, got %r" % (
        derived,
    )
    assert "pm_scout.md" in derived, "pm_scout.md must be in the derivation, got %r" % (
        derived,
    )


def test_b4b_readme_names_every_tracked_top_level_role_card():
    """THE BRAKE: the README repo map may not drop a shipped seat's playbook."""
    derived = _derived_card_names()
    gaps = foundry.role_card_doc_gaps(derived, _README.read_text(encoding="utf-8"))
    assert gaps == (), "README.md does not name these tracked role cards: %r" % (gaps,)


def test_b4c_planted_name_proves_the_brake_can_fail():
    """FAILABILITY: a name README cannot contain must come back as the only gap."""
    derived = _derived_card_names()
    readme = _README.read_text(encoding="utf-8")
    assert PLANTED not in readme, "the planted control name must be absent from README"
    gaps = foundry.role_card_doc_gaps(tuple(derived) + (PLANTED,), readme)
    assert gaps == (PLANTED,), "expected exactly the planted gap, got %r" % (gaps,)


def test_b4_derivation_excludes_the_bench_cards():
    """The derivation is TOP-LEVEL only -- bench cards are tracked but must not leak in."""
    derived = _derived_card_names()
    assert "ceo.md" not in derived, "bench cards must be excluded, got %r" % (derived,)
    assert all(name.endswith(".md") for name in derived)
    assert all("/" not in name for name in derived)


# ============================================================ Behavior 5 -- README rows


def _readme_lines():
    return _README.read_text(encoding="utf-8").splitlines()


def _repo_map_row(prefix):
    rows = [ln for ln in _readme_lines() if ln.strip().startswith(prefix)]
    assert len(rows) == 1, "expected exactly one row starting %r, found %d" % (
        prefix,
        len(rows),
    )
    return rows[0]


@pytest.mark.parametrize("stale", ["7 project-agnostic", "11 versioned role-cards"])
def test_b5a_stale_count_words_are_deleted_from_readme(stale):
    text = _README.read_text(encoding="utf-8")
    assert stale not in text, "the stale count word %r must be DELETED from README.md" % (
        stale,
    )


def test_b5b_roles_row_names_all_eight_card_basenames_on_that_one_row():
    row = _repo_map_row("| `roles/` |")
    missing = [name for name in SPEC_CARD_BASENAMES if name not in row]
    assert missing == [], "the `roles/` repo-map row is missing %r; row was: %s" % (
        missing,
        row,
    )


def test_b5c_bench_row_still_contains_versioned_role_cards():
    row = _repo_map_row("| `roles/bench/` |")
    assert "versioned role-cards" in row, (
        "the bench row must be RE-WORDED, not deleted; row was: %s" % row
    )


def test_b5_the_row_finder_is_real_and_the_two_rows_are_distinct():
    """Non-vacuity for behavior 5: both anchors resolve, and to different lines."""
    roles_row = _repo_map_row("| `roles/` |")
    bench_row = _repo_map_row("| `roles/bench/` |")
    assert roles_row != bench_row
    assert "roles/" in roles_row and "roles/bench/" in bench_row
