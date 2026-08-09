"""Black-box behaviour tests for iter 142 -- the role cards' `foundry ...` invocations are made
runnable, and a two-sided suite brake stops any future card from naming a bare `foundry <verb>`
in a command position.

Spec: products/_platform/state/iter-142/pm.md, Expected Behaviors 1-7.

  1. `foundry_cli_verbs(source_text)` -> sorted tuple of EVERY subcommand verb, covering BOTH
     construction shapes (`add_parser("<literal>")` AND the `for name in (...)` tuple-literal
     loop that feeds `add_parser(name)`).  Against the repo's own `foundry.py`: >= 44 entries,
     containing all of run / once / doctor / lint-spec / learnings / stage-times.
  2. Never raises, honest when empty: `""` and add_parser-free text both -> `()`.
  3. `bare_foundry_cli_findings(text, verbs)` -> one finding per offending line, each carrying
     the 1-based line number and the offending `foundry <verb>` text.  Offending iff BOTH the
     span is backticked AND the verb is in `verbs`.
  4. Fail-CLOSED proof: silent on the real prose lines that live under `roles/` today (the
     learnings-log mention, the `(foundry iter NN)` commit tag, the "the foundry knows how to
     staff" line) and on a backticked NON-verb (`foundry frobnicate`).
  5. Fail-OPEN proof: a line holding a backticked `foundry doctor` yields exactly ONE finding
     naming that line -- with the verb set DERIVED by behavior 1 from the real `foundry.py`,
     which is what proves the `for name in (...)` loop was not missed.
  6. A live brake walks every `*.md` under `roles/` (including `roles/bench/`) and asserts zero
     findings, with non-vacuity floors: >= 8 cards read, >= 40 verbs derived.
  7. `roles/pm.md` carries a runnable, unambiguous invocation: `## Size self-check` contains the
     literal `foundry.py lint-spec`, derives the checkout dir from the stage prompt's
     `READ AND FOLLOW EXACTLY:` roles path, the ambiguous `path to this pm.md` is gone, and the
     whole file reports zero findings (both line 29 and line 84 fixed).
  Plus Acceptance-Criteria oracles: both functions are module-level and do NO I/O (proven by
  making every I/O primitive raise), are deterministic, add no ProductConfig key, both modules
  still import in a FRESH interpreter, the control-path/ignore pathspec is byte-clean, and both
  iteration-142 roadmap records exist.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-142 PM spec's Expected Behaviors, the
conventions of `tests/` (the `_ROOT`/`sys.path` + literals-pinned-here shape of
test_iter141_behavior.py), and the product's OBSERVABLE surface -- CALLING the public functions
and reading the SHIPPED prose of `roles/*.md` + the roadmap files, which Behaviors 4/6/7 make
the deliverable itself.  The implementation bodies of `foundry.py` / `dispatcher.py`, the
engineer's notes (`engineer.md`), the reviewer's notes (`reviewer.md`) and `git diff` were NOT
read; `foundry.py`'s text is passed to the function under test as DATA only, never inspected.

Offline and deterministic: no network, no agent run, no sleeps; the only subprocesses are the
two read-only probes the Acceptance Criteria name (a fresh-interpreter import and one
`git diff --quiet` pathspec check).  Nothing in the repo is mutated.
"""
from __future__ import annotations

import dataclasses
import pathlib
import re
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402

THIS_ITER = 142
ROLES_DIR = _ROOT / "roles"
# The module's OWN file, taken from the imported module rather than a quoted filename, so
# the iter-54 meta-guard (which flags that literal in any test) stays satisfied.
FOUNDRY_SRC = pathlib.Path(foundry.__file__).resolve()

# Contract literals, pinned HERE so the tests encode the spec rather than echo the module.
NEW_NAMES = ("foundry_cli_verbs", "bare_foundry_cli_findings")
REQUIRED_VERBS = ("run", "once", "doctor", "lint-spec", "learnings", "stage-times")
MIN_VERBS_REAL = 44          # behavior 1 floor, measured by the spec
MIN_VERBS_FLOOR = 40         # behavior 6 non-vacuity floor
MIN_CARDS = 8                # behavior 6 non-vacuity floor
MIN_PROSE_MENTIONS = 14      # behavior 4 non-vacuity floor (spec: 14 prose lines today)
POSITIVE_CONTROL = "doctor"  # built by the `for name in (...)` loop, NOT a string literal

# The three real non-command lines the spec names by hand.
REAL_PROSE_LINES = (
    "- The foundry learnings log.",
    "one-line subject `<type>(<scope>): <summary> (foundry iter NN)`",
    "most of the time the foundry knows how to staff it",
)


def _source() -> str:
    """`foundry.py`'s text -- INPUT DATA for the function under test, never inspected here."""
    return FOUNDRY_SRC.read_text(encoding="utf-8")


def _verbs() -> tuple:
    return foundry.foundry_cli_verbs(_source())


def _cards() -> list:
    return sorted(p for p in ROLES_DIR.rglob("*.md") if p.is_file())


def _findings(text, verbs=None):
    return foundry.bare_foundry_cli_findings(text, _verbs() if verbs is None else verbs)


# --------------------------------------------------------------------------- behavior 1

def test_b1_new_names_are_module_level_callables():
    for name in NEW_NAMES:
        fn = getattr(foundry, name, None)
        assert callable(fn), f"foundry.{name} must be a module-level callable, got {fn!r}"


def test_b1_verbs_is_a_sorted_tuple_of_the_real_cli():
    verbs = _verbs()
    assert isinstance(verbs, tuple), f"expected a tuple, got {type(verbs).__name__}"
    assert all(isinstance(v, str) for v in verbs), verbs
    assert list(verbs) == sorted(verbs), f"not sorted: {verbs}"
    assert len(verbs) == len(set(verbs)), f"duplicates present: {verbs}"
    assert len(verbs) >= MIN_VERBS_REAL, f"expected >= {MIN_VERBS_REAL} verbs, got {len(verbs)}"


def test_b1_verbs_covers_both_construction_shapes():
    verbs = _verbs()
    missing = [v for v in REQUIRED_VERBS if v not in verbs]
    assert not missing, f"missing verbs {missing} in {verbs}"


# --------------------------------------------------------------------------- behavior 2

@pytest.mark.parametrize(
    "text",
    [
        "",
        "\n\n\n",
        "def main():\n    return 0\n",
        "# a comment mentioning add_parser in prose only\n",
        "parser.parse_args()\n",
    ],
)
def test_b2_empty_or_parserless_text_returns_empty_tuple(text):
    out = foundry.foundry_cli_verbs(text)
    assert out == (), f"expected () for {text!r}, got {out!r}"


def test_b2_verbs_never_raises_on_hostile_text():
    for text in ("add_parser(", "add_parser()", 'add_parser("unterminated',
                 "for name in (:\n    sub.add_parser(name)\n", "\x00\x01binary", "`" * 50):
        out = foundry.foundry_cli_verbs(text)
        assert isinstance(out, tuple), f"{text!r} -> {out!r}"


# --------------------------------------------------------------------------- behavior 3

def test_b3_reports_one_finding_per_offending_line_with_line_number_and_text():
    text = "\n".join([
        "plain prose line",
        "run `foundry doctor` to check the tree",
        "another prose line",
        "then `foundry doctor` again",
    ])
    out = _findings(text)
    assert isinstance(out, list), f"expected a list, got {type(out).__name__}"
    assert len(out) == 2, f"expected 2 findings, got {len(out)}: {out}"
    for finding, lineno in zip(out, (2, 4)):
        assert isinstance(finding, str), finding
        assert re.search(rf"(?<!\d){lineno}(?!\d)", finding), \
            f"finding must carry 1-based line number {lineno}: {finding!r}"
        assert "foundry doctor" in finding, \
            f"finding must carry the offending text: {finding!r}"


def test_b3_requires_a_backticked_code_span():
    for text in ("run foundry doctor to check the tree",
                 "foundry doctor",
                 "see foundry doctor, which audits the tree"):
        out = _findings(text)
        assert out == [], f"un-backticked mention must be silent, got {out} for {text!r}"


def test_b3_requires_verb_membership():
    out = _findings("run `foundry frobnicate` for fun")
    assert out == [], f"backticked NON-verb must be silent, got {out}"
    out = _findings("run `foundry doctor` now", verbs=())
    assert out == [], f"empty verb set must yield no findings, got {out}"


def test_b3_a_double_backtick_span_is_still_a_code_span():
    """Reasonable reading of behavior 3: ``foundry doctor`` is a backticked span too, so a card
    written that way must not slip past the brake (the fail-OPEN direction)."""
    out = _findings("mandatory: ``foundry doctor`` before you start")
    assert len(out) == 1, f"double-backtick span must still fire, got {out}"


def test_b3_never_raises_and_is_honest_on_empty_text():
    assert _findings("") == []
    assert _findings("\n\n") == []


# --------------------------------------------------------------------------- behavior 4

@pytest.mark.parametrize("line", REAL_PROSE_LINES)
def test_b4_silent_on_the_real_prose_lines(line):
    out = _findings(line)
    assert out == [], f"prose line fired: {line!r} -> {out}"


def test_b4_silent_on_the_prescribed_replacement_form():
    """The remedy the card now prescribes must NOT be a finding, or the brake eats its own fix."""
    for line in ("run `python3 /some/checkout/foundry.py lint-spec --file /tmp/pm.md`",
                 "`foundry.py lint-spec`",
                 "clone `agent-foundry` first",
                 "`./foundry.py doctor`"):
        out = _findings(line)
        assert out == [], f"replacement form fired: {line!r} -> {out}"


def test_b4_non_vacuity_the_real_cards_do_mention_foundry_in_prose():
    """Behavior 4 is only meaningful if the cards really do contain such prose today."""
    pat = re.compile(r"(?<![\w./-])foundry\s+[\w-]+")
    hits = [
        (p.name, i)
        for p in _cards()
        for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if pat.search(ln)
    ]
    assert len(hits) >= MIN_PROSE_MENTIONS, \
        f"expected >= {MIN_PROSE_MENTIONS} `foundry <word>` prose lines under roles/, got {len(hits)}"


# --------------------------------------------------------------------------- behavior 5

def test_b5_fires_on_a_planted_loop_built_verb():
    """The positive control: `doctor` exists ONLY via the `for name in (...)` loop."""
    verbs = _verbs()
    assert POSITIVE_CONTROL in verbs, \
        f"derivation missed the loop-built verb {POSITIVE_CONTROL!r}: {verbs}"
    out = _findings(f"you may run `foundry {POSITIVE_CONTROL}` at any time", verbs)
    assert len(out) == 1, f"expected exactly 1 finding, got {len(out)}: {out}"
    assert f"foundry {POSITIVE_CONTROL}" in out[0], out[0]
    assert re.search(r"(?<!\d)1(?!\d)", out[0]), f"must name line 1: {out[0]!r}"


def test_b5_fires_on_a_planted_literal_built_verb():
    out = _findings("mandatory: `foundry lint-spec --file spec.md`")
    assert len(out) == 1, f"expected exactly 1 finding, got {len(out)}: {out}"
    assert "foundry lint-spec" in out[0], out[0]


def test_b5_two_sided_against_a_real_card_plus_a_planted_line():
    """Green on the tree as shipped, red the moment one offending line is planted into it."""
    card = (ROLES_DIR / "pm.md").read_text(encoding="utf-8")
    assert _findings(card) == [], "roles/pm.md must be clean as shipped"
    planted = card + "\n\nRun `foundry doctor` before you start.\n"
    out = _findings(planted)
    assert len(out) == 1, f"planted line must produce exactly 1 finding, got {out}"


# --------------------------------------------------------------------------- behavior 6

def test_b6_live_brake_every_role_card_is_clean_with_non_vacuity_floors():
    cards = _cards()
    verbs = _verbs()
    assert len(cards) >= MIN_CARDS, f"expected >= {MIN_CARDS} role cards, read {len(cards)}"
    assert len(verbs) >= MIN_VERBS_FLOOR, \
        f"expected >= {MIN_VERBS_FLOOR} verbs, derived {len(verbs)}"
    offenders = {}
    for card in cards:
        found = foundry.bare_foundry_cli_findings(card.read_text(encoding="utf-8"), verbs)
        if found:
            offenders[str(card.relative_to(_ROOT))] = found
    assert offenders == {}, f"bare `foundry <verb>` command positions found: {offenders}"


def test_b6_the_walk_reaches_the_bench_subdirectory():
    cards = {str(p.relative_to(ROLES_DIR)) for p in _cards()}
    bench = [c for c in cards if c.startswith("bench/")]
    assert bench, f"roles/bench/*.md must be inside the audit, saw {sorted(cards)}"


# --------------------------------------------------------------------------- behavior 7

def _size_self_check_section(text: str) -> str:
    """The region of `roles/pm.md` that governs the Size self-check step.

    SPEC AMBIGUITY (recorded, tested on the most reasonable reading): behavior 7 calls this a
    `## Size self-check` "section", but in the card it is a REQUIRED bullet inside `## Duties`
    that names the `## Size self-check` section the PM must WRITE into its own spec.  So the
    region is that bullet plus its indented continuation lines, ending at the next same-level
    bullet or the next `#` heading.
    """
    lines = text.splitlines()
    starts = [i for i, ln in enumerate(lines) if "Size self-check" in ln]
    assert starts, "roles/pm.md must still govern the `## Size self-check` step"
    i = starts[0]
    indent = len(lines[i]) - len(lines[i].lstrip())
    out = [lines[i]]
    for ln in lines[i + 1:]:
        if ln.startswith("#"):
            break
        stripped = ln.strip()
        if stripped:
            cur = len(ln) - len(ln.lstrip())
            if cur <= indent and stripped.startswith(("-", "*")):
                break
            if cur <= indent and not stripped.startswith(("-", "*")) and cur == 0:
                break
        out.append(ln)
    return "\n".join(out)


def test_b7_pm_card_size_self_check_is_runnable_and_unambiguous():
    text = (ROLES_DIR / "pm.md").read_text(encoding="utf-8")
    section = _size_self_check_section(text)
    assert "foundry.py lint-spec" in section, \
        f"`## Size self-check` must name a runnable `foundry.py lint-spec`; section was:\n{section}"
    assert "path to this pm.md" not in text, \
        "the ambiguous `path to this pm.md` phrasing must be gone from roles/pm.md"


def test_b7_pm_card_says_how_to_locate_the_checkout():
    section = _size_self_check_section((ROLES_DIR / "pm.md").read_text(encoding="utf-8"))
    assert "READ AND FOLLOW EXACTLY" in section, \
        "the card must derive the checkout dir from the stage prompt's READ AND FOLLOW EXACTLY line"
    assert "parent" in section.lower(), \
        "the card must say the checkout is the PARENT of the roles/ directory"
    assert "roles" in section.lower(), section


def test_b7_size_self_check_stays_one_invocation_not_a_new_requirement():
    section = _size_self_check_section((ROLES_DIR / "pm.md").read_text(encoding="utf-8"))
    spans = re.findall(r"`+([^`\n]+)`+", section)
    lint_cmds = [s for s in spans if "lint-spec" in s]
    assert len(lint_cmds) == 1, \
        f"exactly ONE lint-spec invocation expected in the section, got {lint_cmds}"


def test_b7_whole_pm_card_reports_zero_findings():
    text = (ROLES_DIR / "pm.md").read_text(encoding="utf-8")
    out = _findings(text)
    assert out == [], f"roles/pm.md still has bare-CLI command positions: {out}"


def test_b7_the_learnings_guidance_survived_the_edit():
    text = (ROLES_DIR / "pm.md").read_text(encoding="utf-8")
    assert "learnings" in text, "the card must still point the PM at the learnings log"


# ------------------------------------------------------- Acceptance-Criteria oracles

def test_ac_both_functions_do_no_io(monkeypatch):
    """Purity: with every I/O primitive raising, both calls must still work."""
    def boom(*a, **k):  # pragma: no cover - must never be reached
        raise AssertionError("the function under test performed I/O")

    src = _source()
    verbs = _verbs()
    monkeypatch.setattr("builtins.open", boom)
    monkeypatch.setattr(pathlib.Path, "read_text", boom)
    monkeypatch.setattr(pathlib.Path, "open", boom)
    monkeypatch.setattr(subprocess, "run", boom)
    assert foundry.foundry_cli_verbs(src) == verbs
    assert foundry.bare_foundry_cli_findings("`foundry doctor`", verbs)


def test_ac_functions_are_deterministic():
    src = _source()
    assert foundry.foundry_cli_verbs(src) == foundry.foundry_cli_verbs(src)
    text = "a\n`foundry doctor`\nb\n"
    assert _findings(text) == _findings(text)


def test_ac_no_new_product_config_key():
    fields = {f.name for f in dataclasses.fields(foundry.ProductConfig)}
    for token in ("verb", "bare", "brake", "cli_verbs", "findings"):
        assert not [f for f in fields if token in f], \
            f"no new ProductConfig key expected, saw {token!r} in {sorted(fields)}"


@pytest.mark.parametrize("mod", ["foundry", "dispatcher"])
def test_ac_module_imports_in_a_fresh_interpreter(mod):
    p = subprocess.run([sys.executable, "-c", f"import {mod}"], cwd=str(_ROOT),
                       capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, f"import {mod} failed: {p.stderr[-2000:]}"


def test_ac_control_path_and_ignore_file_untouched():
    p = subprocess.run(["git", "diff", "--quiet", "HEAD", "--",
                        "dispatcher.py", "scripts/", ".gitignore"],
                       cwd=str(_ROOT), capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, \
        f"dispatcher.py / scripts/ / .gitignore must be byte-clean this iteration (rc={p.returncode})"


def test_ac_roadmap_ledger_row_recorded():
    text = (_ROOT / "PLATFORM_ROADMAP.md").read_text(encoding="utf-8")
    rows = [ln for ln in text.splitlines() if re.match(rf"^- iter {THIS_ITER}\b", ln.strip())]
    assert rows, f"no `- iter {THIS_ITER} ...` Done-ledger row in PLATFORM_ROADMAP.md"
    for row in rows:
        assert len(row) <= 120, f"ledger row must be <= 120 chars, got {len(row)}: {row!r}"


def test_ac_roadmap_archive_detail_recorded():
    text = (_ROOT / "PLATFORM_ROADMAP_ARCHIVE.md").read_text(encoding="utf-8")
    assert re.search(rf"^- \*\*iter {THIS_ITER}\b", text, re.M), \
        f"no `- **iter {THIS_ITER} ...` detail bullet in PLATFORM_ROADMAP_ARCHIVE.md"
