"""Iteration 220 -- INDEPENDENT verification that the ONE shared tester-retry
prompt makes the rescue round CONSUME the cap-killed round's checkpoint instead
of ordering it to start over from zero.

TESTER ISOLATION: written from the iteration-220 PM spec's Expected Behaviors
only. The engineer's notes, the reviewer's notes and `git diff` were NOT read.
Every check below drives the public module surface (`foundry.<NAME>`) or counts
nodes mechanically with `ast` -- no human reading of the implementation, no
subprocess, no network, no real stage.

WHY EVERY BEHAVIOR IS TWO-SIDED WHERE IT CAN BE: the feature IS a string, so a
naive suite could be satisfied by pasting every required token into the constant
in any order. Ordering claims are therefore asserted as INDEX COMPARISONS rather
than mere membership, and the "verdict is still earned" claim is asserted as a
membership arm PLUS a negative arm (no ready-made sentinel to echo).

SELF-COVERING: this module lives inside the population the whole-tree brakes
scan (`git ls-files -c -o --exclude-standard` includes an untracked path, and
two sibling brakes walk `tests/**/*.py` by directory glob), so it must be clean
under them itself. Consequences honoured here: no absolute machine path appears
as a literal, the two ship-sentinel needles are ASSEMBLED from fragments at
runtime so the banned strings never appear contiguously, and no doc-file token
appears in any function body.
"""

from __future__ import annotations

import ast
import pathlib
import re
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402

# The two ship-sentinel needles, assembled so neither appears contiguously in
# this file's own bytes (self-domain discipline).
_SENTINEL_PASS = "RESULT" + ": " + "PASS"
_SENTINEL_FAIL = "RESULT" + ": " + "FAIL"
# The checkpoint marker, likewise assembled.
_MARKER = "PROGRESS" + ": " + "CHECKPOINT"


def _prompt() -> str:
    """The single constant under test, read from the module at CALL time."""
    value = foundry.UNFINISHED_TEST_RETRY_PROMPT
    assert isinstance(value, str), type(value)
    return value


# ------------------------------------------------------------------ Behavior 1
# The four pre-existing pins survive, unedited.

@pytest.mark.parametrize("needle", ["UNFINISHED CHECKPOINT",
                                    "NO failing test",
                                    "regression",
                                    "CREATING"])
def test_b1_each_pre_existing_pin_still_appears(needle):
    assert needle in _prompt(), \
        "a pin the shipped suite depends on must not be edited away: " + needle
    # Attribution note: three of these four are pinned by a shipped module
    # already; the fourth is pinned for the first time HERE. See the stage report.


def test_b1_the_constant_is_still_ascii_only():
    _prompt().encode("ascii")


# NOTE on a claim deliberately NOT asserted here: "no pre-existing test file is
# edited" is a one-time property of this iteration's diff, not a durable
# behavior. Once the change is committed it is vacuously true in every later
# suite and in the throwaway fresh clone, so a test of it would be hollow. It is
# measured out-of-band by the test engineer instead, and the measurement is
# recorded in the stage report.


# ------------------------------------------------------------------ Behavior 2
# The prompt names where the checkpoint lives and orders it read FIRST.

def test_b2_the_prompt_names_where_the_checkpoint_lives():
    assert "state dir" in _prompt()


def test_b2_the_read_instruction_precedes_the_creation_instruction():
    prompt = _prompt()
    assert "READ" in prompt, "the case-sensitive imperative token must be present"
    assert "CREATING" in prompt
    assert prompt.index("READ") < prompt.index("CREATING"), \
        "read-first is an ORDER claim, not a membership claim"


# ------------------------------------------------------------------ Behavior 3
# The checkpoint is identified by RULE, not by filename, so it cannot go stale.

def test_b3_no_tester_report_filename_literal_appears():
    hit = re.search(r"tester\d*\.md", _prompt())
    assert hit is None, \
        "a hardcoded report filename reintroduces the drift the derived helper avoids: " \
        + (hit.group(0) if hit else "")


def test_b3_the_round_agnostic_word_carries_the_rule():
    assert "newest" in _prompt()


def test_b3_the_negative_arm_is_a_real_detector():
    """Positive control: the same regex DOES fire on the filenames it forbids.

    Without this, a typo in the pattern would make the check above vacuous.
    """
    for spelled in ("tester.md", "tester2.md", "tester3.md"):
        assert re.search(r"tester\d*\.md", "see " + spelled + " for detail") is not None


# ------------------------------------------------------------------ Behavior 4
# Carry-forward of the artifact is ordered; creation is the ABSENCE fallback.

@pytest.mark.parametrize("needle", ["KEEP", "EXTEND", "does not exist"])
def test_b4_each_carry_forward_token_is_present(needle):
    assert needle in _prompt(), needle


def test_b4_keep_precedes_create_so_creation_reads_as_the_fallback():
    prompt = _prompt()
    assert prompt.index("KEEP") < prompt.index("CREATING"), \
        "if creation came first the round would still be told to start from zero"


# ------------------------------------------------------------------ Behavior 5
# The verdict is still EARNED in the retry round, never copied forward.

def test_b5_the_round_is_still_told_to_earn_its_verdict():
    assert "your own verdict" in _prompt()


@pytest.mark.parametrize("label", ["pass", "fail"])
def test_b5_no_ready_made_ship_sentinel_is_handed_to_the_round(label):
    needle = _SENTINEL_PASS if label == "pass" else _SENTINEL_FAIL
    assert needle not in _prompt(), \
        "a sentinel in the prompt is a verdict the round could echo without testing"


# ------------------------------------------------------------------ Behavior 6
# Both mirrored call sites still pass the ONE shared constant, and nothing else
# references it.

_NAME = "UNFINISHED_TEST_RETRY" + "_PROMPT"


def _foundry_tree():
    src = (_ROOT / "foundry.py").read_text(encoding="utf-8")
    return src, ast.parse(src)


def test_b6_exactly_three_bare_name_references_exist():
    _src, tree = _foundry_tree()
    refs = [n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Name) and n.id == _NAME]
    assert len(refs) == 3, \
        "expected one assignment target plus one reference per call site, got " + repr(sorted(refs))


def test_b6_exactly_two_run_stage_calls_pass_that_bare_name():
    _src, tree = _foundry_tree()
    sites = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Name) and node.func.id == "run_stage"):
            continue
        if any(isinstance(a, ast.Name) and a.id == _NAME for a in node.args):
            sites.append(node.lineno)
    assert len(sites) == 2, \
        "the two mirrored orchestrators must tell the retry round the SAME story, got " \
        + repr(sorted(sites))


def test_b6_the_constant_is_assigned_exactly_once_at_module_level():
    _src, tree = _foundry_tree()
    targets = [node.lineno for node in tree.body
               if isinstance(node, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == _NAME for t in node.targets)]
    assert len(targets) == 1, repr(targets)


def test_b6_no_per_site_rendered_variant_was_introduced():
    """No call site may `.format(...)` / f-string / `%` the shared constant.

    That is the concrete way the two orchestrators could drift apart while the
    bare-name count above still read 3.
    """
    _src, tree = _foundry_tree()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                and node.value.id == _NAME:
            raise AssertionError(
                "method call on the shared constant at line %d: .%s" % (node.lineno, node.attr))
        if isinstance(node, ast.BinOp) and isinstance(node.left, ast.Name) \
                and node.left.id == _NAME:
            raise AssertionError("binary operation on the shared constant at line %d" % node.lineno)


# ------------------------------------------------------------------ Behavior 7
# The neighbours on the rescue path are unchanged, and both modules import.

def test_b7_the_retry_budget_is_unchanged():
    assert foundry.UNFINISHED_TEST_RETRY_STAGES == (("tester-retry", "tester2.md"),
                                                    ("tester-retry2", "tester3.md"))


def test_b7_the_checkpoint_marker_is_unchanged():
    assert foundry.UNFINISHED_TEST_MARKER == _MARKER


def test_b7_a_checkpoint_report_still_classifies_as_unfinished():
    assert foundry.classify_test_report("## " + _MARKER + "\nwork so far\n") == "UNFINISHED"


def test_b7_the_report_names_are_still_derived_for_three_rounds():
    assert foundry.tester_report_names() == ("tester.md", "tester2.md", "tester3.md")


@pytest.mark.parametrize("module_name", ["foundry", "dispatcher"])
def test_b7_both_modules_still_import(module_name):
    r = subprocess.run(
        [sys.executable, "-c",
         "import " + module_name + " as m; print(m.__name__)"],
        cwd=str(_ROOT), capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == module_name, r.stdout


# ------------------------------------------------------------------ Behavior 8
# The prompt stays a rounding error on a stage prompt.

def test_b8_the_prompt_stays_small():
    size = len(_prompt())
    assert size <= 1200, "the added text must not become an essay: " + str(size)


def test_b8_the_prompt_actually_grew_from_the_baseline():
    """The lower bound is what makes the upper bound meaningful.

    The spec measured 371 chars at HEAD, and the new instructions cannot fit in
    that budget, so a constant still at or below the old size would mean the
    feature never landed.
    """
    assert len(_prompt()) > 371


# ================================================================ Extensions
# Added by the RETRY round on top of the cap-killed round's checkpoint. Each
# one closes a way the constant could satisfy every membership check above and
# still fail the round it is written for.

# ---- the two ordering claims, as ONE monotonic chain (Behaviors 2 + 4) -----

def test_ext_the_instruction_order_is_a_single_monotonic_chain():
    """Spec Behaviors 2 and 4 each pin ONE pair against `CREATING`.

    Asserted separately they permit an ordering no reader would follow (e.g.
    the extend order arriving before the read order). The chain is the claim
    the feature actually makes: read the checkpoint, keep the artifact, extend
    it, and only then consider creating one.
    """
    prompt = _prompt()
    chain = ["READ", "KEEP", "EXTEND", "CREATING"]
    positions = [prompt.index(token) for token in chain]
    assert positions == sorted(positions), \
        "instruction order is not monotonic: " + repr(list(zip(chain, positions)))


def test_ext_the_absence_clause_sits_in_the_same_clause_as_creation():
    """`CREATING` and `does not exist` must be ONE conditional, not two ideas.

    Membership alone is satisfied by putting the absence wording in a
    different sentence, which would leave creation reading as unconditional --
    exactly the defect this iteration exists to remove. Distance is asserted
    instead of order so either phrasing of the conditional passes.
    """
    prompt = _prompt()
    gap = abs(prompt.index("does not exist") - prompt.index("CREATING"))
    assert gap <= 80, \
        "the absence fallback is detached from the creation instruction by " + str(gap) + " chars"


# ---- the constant is handed to an agent VERBATIM, so it must be renderable -

def test_ext_no_unrendered_format_placeholder_survives_in_the_constant():
    """The constant is passed through as-is, so a `{...}` field never renders.

    A placeholder would reach the round literally and name nothing.
    """
    hit = re.search(r"\{[^{}]*\}", _prompt())
    assert hit is None, "unrendered placeholder handed to the round: " + (hit.group(0) if hit else "")


def test_ext_the_placeholder_detector_is_two_sided():
    """Positive control, so the negative arm above cannot be vacuous."""
    assert re.search(r"\{[^{}]*\}", "look in {state_dir} for it") is not None


def test_ext_the_location_is_named_generically_not_as_a_machine_path():
    """Behavior 2 wants the location NAMED; an absolute path would be wrong.

    The prompt is shared by every product and every iteration, so a rooted
    path literal would be false for all but one of them. The needle is
    assembled from fragments so this file's own bytes stay clean under the
    whole-tree path scanners.
    """
    rooted = "/" + "(?:Users|home|root|private|var)" + "/"
    hit = re.search(rooted, _prompt())
    assert hit is None, "a machine-rooted path literal appears in the shared prompt"
    assert re.search(rooted, "/" + "home" + "/x") is not None, \
        "positive control: the detector must fire on a rooted path"


# ---- INTEGRATION: does the string actually reach the round it is for? ------

def _tmp_cfg(tmp_path):
    """A throwaway product config under tmp_path (the real repo is untouched)."""
    import json
    data = {"name": "demo",
            "repo": "{FOUNDRY}/products/demo/repo",
            "allowed_push_repo": "demo",
            "vision": "{FOUNDRY}/products/demo/VISION.md",
            "work_root": str(tmp_path / "work")}
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(data), encoding="utf-8")
    cfg = foundry.load_config(str(cfg_path))
    learn = pathlib.Path(cfg.learnings)
    learn.parent.mkdir(parents=True, exist_ok=True)
    learn.write_text("## Patterns\n\n- a durable rule\n\n- [ROLE iter01] a lesson\n",
                     encoding="utf-8")
    return cfg


def test_ext_the_constant_survives_prompt_assembly_contiguously(tmp_path):
    """The whole point is that the RETRY ROUND reads this text.

    Every other check in this module inspects the constant in isolation, which
    cannot see truncation, re-wrapping or a lost newline introduced when the
    stage prompt is assembled around it. This drives the public prompt builder
    with the constant in the position the rescue path uses.
    """
    cfg = _tmp_cfg(tmp_path)
    it_dir = cfg.state / "iter-220"
    assembled = foundry.build_prompt(
        cfg, 220, "tester-retry", "tester.md", it_dir / "tester2.md", it_dir,
        _prompt())
    assert _prompt() in assembled, \
        "the constant did not survive assembly as one contiguous block"
    assert assembled.count(_prompt()) == 1, \
        "the constant is duplicated in the assembled prompt: " + str(assembled.count(_prompt()))


def test_ext_the_assembled_prompt_still_names_the_round_and_its_output(tmp_path):
    """Control for the test above: assembly really happened around the string.

    Without this, a builder that returned `extra` alone would pass.
    """
    cfg = _tmp_cfg(tmp_path)
    it_dir = cfg.state / "iter-220"
    assembled = foundry.build_prompt(
        cfg, 220, "tester-retry", "tester.md", it_dir / "tester2.md", it_dir,
        _prompt())
    assert "tester2.md" in assembled, "the required output file is not named"
    assert len(assembled) > len(_prompt()) + 1000, \
        "the builder returned little more than the extra text: " + str(len(assembled))
