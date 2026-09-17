"""Iteration 370 -- BLACK-BOX behavior tests: the two LIVE docs that describe
doctor's `stage-budget:` figure must NAME the population that figure prices, and a
suite brake reds when they stop naming it.

Spec under test: products/_platform/state/iter-370/pm.md, Expected Behaviors 1-4.

  1. A PURE, TOTAL helper reports which required token(s) a doc text fails to NAME --
     gap direction ONLY, sorted, deduped, `()` == clean -- and an EXISTING in-tree
     oracle is REUSED rather than duplicated.  The oracle under test is
     `foundry.role_card_doc_gaps(names, doc_text)`; its reuse is proved by finding it
     already exercised by iteration-behavior tests OLDER than this one.
  2. The live `README.md` text NAMES `STAGE_BUDGET_EXCLUDED_KINDS`, in BOTH places
     that describe the gauge (the `# 0.` preflight entry and the `# 47.` entry), and
     says plainly, next to the token, that `stage-times` still prices ALL attempts so
     the two surfaces legitimately report DIFFERENT medians.
  3. The live `roles/pm.md` names the population the copied `stage-budget:` line
     prices -- the attempts that DID WORK -- next to the instruction that makes that
     line a required verbatim spec input.
  4. Full quality-check suite passes (run separately; reported in tester.md).

  Acceptance criteria also encoded: `import foundry, dispatcher` clean, and a roadmap
  index row + archive detail bullet for iteration 370 in the shipping tree.

ISOLATION CONTRACT (HONORED): every assertion below was derived ONLY from the iter-370
PM spec, the pre-existing conventions under `tests/`, the product README / roadmap /
role-card TEXT (all of which this stage is explicitly allowed to read), and the
product's OWN observable behavior by importing and CALLING its public names.  The
implementation SOURCE of `foundry.py` / `dispatcher.py` was NOT read, nor the
engineer's notes, the reviewer's notes, the fix notes, `IMPLEMENTATION.patch`, or any
`git diff`.

NOT A POST-COMMIT INVERTER (deliberate design choice): the spec phrases behavior 2's
two-sidedness as "green on the shipping tree and RED at `HEAD~1`".  A test that reds
against `git show HEAD~1:<doc>` (or `git show HEAD:<doc>`) is true only inside the one
commit that lands it and inverts forever afterwards.  So the NON-VACUITY leg here is
built from the LIVE doc text with the token surgically REMOVED -- same oracle, same
population, no git, no history, durable at every future HEAD.

FRESH-CLONE SAFE / OFFLINE: every path read below (`README.md`, `roles/pm.md`,
`PLATFORM_ROADMAP.md`, `PLATFORM_ROADMAP_ARCHIVE.md`, `tests/`) is git-TRACKED, so it
exists in a throwaway clone; nothing gitignored (`products/*/state`, `dispatcher.out`,
logs) is read or counted.  No subprocess, no git, no network, no clock.
"""
from __future__ import annotations

import pathlib
import re
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  -- in-process import-safety probe (the quality bar)

THIS_ITER = 370

# The constant whose NAME the live docs must carry.  Built from a joined literal so
# this module is not itself a "the docs name it" false positive for any census that
# greps the tree for the token: the brake below asserts on the docs, not on itself.
REQUIRED_TOKEN = "STAGE_BUDGET" + "_EXCLUDED_KINDS"

# Generous windows: measured distances from the token to each required neighbour are
# <= 240 chars in README.md and <= 390 in roles/pm.md, so 1200 leaves ~5x headroom and
# will not red on ordinary re-wording.
NEIGHBOUR_WINDOW = 1200

_GAPS = foundry.role_card_doc_gaps


def _read(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding="utf-8")


def _window(text: str, at: int, radius: int = NEIGHBOUR_WINDOW) -> str:
    return text[max(0, at - radius): at + radius]


# ---------------------------------------------------------------------------
# Behavior 1 -- the pure, total, REUSED gap oracle
# ---------------------------------------------------------------------------

def test_b1_gap_direction_only() -> None:
    """Only required-but-ABSENT names are reported; the doc's extras never are."""
    # present -> clean, even though the doc names things nobody required
    assert _GAPS(["alpha"], "alpha and beta and gamma") == ()
    # absent -> reported
    assert _GAPS(["beta"], "alpha only") == ("beta",)
    # mixed: exactly the absent ones, never the present one, never the doc's extras
    assert _GAPS(["alpha", "beta"], "alpha and gamma") == ("beta",)


def test_b1_output_is_sorted_and_deduped() -> None:
    out = _GAPS(["zulu", "alpha", "mike", "alpha", "zulu"], "names nothing")
    assert out == ("alpha", "mike", "zulu")
    assert list(out) == sorted(out)
    assert len(out) == len(set(out))


def test_b1_clean_is_the_empty_tuple() -> None:
    for names, doc in ((["a"], "a"), ([], "anything"), ([], "")):
        out = _GAPS(names, doc)
        assert out == (), (names, doc, out)
        assert isinstance(out, tuple)


def test_b1_is_total_over_adversarial_inputs() -> None:
    """Never raises; degrades instead.  Enumerated shapes, each asserted."""
    assert _GAPS(["a"], "") == ("a",)          # empty doc
    assert _GAPS(["a"], None) == ("a",)        # unreadable doc
    assert _GAPS(None, "a") == ()              # no requirements
    assert _GAPS([1, "a"], "a") == ()          # non-string member skipped
    assert _GAPS([1], "") == ()                # ... and never coerced into a gap
    assert _GAPS([None, "a"], "a") == ()
    assert _GAPS(["", "a"], "a") == ()
    # a ONE-SHOT iterator is fully consumed, not silently truncated: the excluded
    # rows sit at positions 1 AND 3 so a lazily-dropped first element would show up
    assert _GAPS(iter(["z", "a", "y"]), "a") == ("y", "z")
    assert _GAPS((n for n in ("z", "a", "y")), "a") == ("y", "z")


def test_b1_is_pure_no_mutation_no_io() -> None:
    """Same input -> same output; the argument is not mutated; no filesystem read."""
    names = ["zulu", "alpha"]
    first = _GAPS(names, "")
    assert names == ["zulu", "alpha"]           # caller's list untouched
    assert first == _GAPS(list(names), "")      # idempotent
    assert first == ("alpha", "zulu")


def test_b1_no_filesystem_or_subprocess_access(monkeypatch) -> None:
    """A PURE helper: it cannot need `open`, `Path.read_text` or a subprocess."""
    import builtins
    import subprocess

    def _boom(*a, **k):  # pragma: no cover - must never be reached
        raise AssertionError("the pure oracle performed I/O")

    monkeypatch.setattr(builtins, "open", _boom)
    monkeypatch.setattr(pathlib.Path, "read_text", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "check_output", _boom)
    assert _GAPS([REQUIRED_TOKEN], "names " + REQUIRED_TOKEN + " here") == ()
    assert _GAPS([REQUIRED_TOKEN], "names nothing") == (REQUIRED_TOKEN,)


def test_b1_match_is_case_sensitive_so_the_token_brake_cannot_be_faked() -> None:
    """A lowercase paraphrase is NOT the constant's name."""
    assert _GAPS([REQUIRED_TOKEN], REQUIRED_TOKEN.lower()) == (REQUIRED_TOKEN,)
    assert _GAPS([REQUIRED_TOKEN], REQUIRED_TOKEN) == ()


def test_b1_oracle_is_reused_not_duplicated() -> None:
    """The spec requires REUSE of an in-tree oracle when one fits.

    Evidence that `role_card_doc_gaps` pre-dates this iteration: it is already
    exercised by iteration-behavior tests with a LOWER iteration number.  Only
    git-TRACKED files under tests/ are scanned, so this holds in a fresh clone.
    """
    pat = re.compile(r"^test_iter(\d+)_behavior\.py$")
    earlier = []
    for path in sorted((_ROOT / "tests").glob("test_iter*_behavior.py")):
        m = pat.match(path.name)
        if not m or int(m.group(1)) >= THIS_ITER:
            continue
        if "role_card_doc_gaps" in path.read_text(encoding="utf-8"):
            earlier.append(int(m.group(1)))
    assert earlier, "no pre-existing test exercises the reused oracle"
    assert max(earlier) < THIS_ITER


# ---------------------------------------------------------------------------
# Behavior 2 -- the live README names the constant (brake + non-vacuity)
# ---------------------------------------------------------------------------

def test_b2_live_readme_names_the_constant() -> None:
    """THE BRAKE.  Reds the suite if README.md stops naming the constant."""
    assert _GAPS([REQUIRED_TOKEN], _read("README.md")) == ()


def test_b2_brake_is_two_sided_on_the_same_population() -> None:
    """NON-VACUITY without git: strip the token from the LIVE text, brake reds."""
    text = _read("README.md")
    assert REQUIRED_TOKEN in text
    stripped = text.replace(REQUIRED_TOKEN, "<removed>")
    assert REQUIRED_TOKEN not in stripped
    assert _GAPS([REQUIRED_TOKEN], stripped) == (REQUIRED_TOKEN,)


def test_b2_both_gauge_descriptions_name_the_constant() -> None:
    """Both README places that describe the gauge carry it: the `# 0.` preflight
    entry and the `# 47.` entry, so an investigator hits it from either surface."""
    text = _read("README.md")
    heads = [(m.start(), m.group(1)) for m in re.finditer(r"(?m)^# (\d+)\.", text)]
    assert heads, "README entry headings not found"

    def entry_of(offset: int) -> str:
        before = [h for h in heads if h[0] <= offset]
        after = [h for h in heads if h[0] > offset]
        assert before, offset
        return before[-1][1]

    owners = {entry_of(m.start()) for m in re.finditer(re.escape(REQUIRED_TOKEN), text)}
    assert {"0", "47"} <= owners, owners


def test_b2_readme_says_stage_times_still_prices_all_attempts() -> None:
    """Naming the constant is not enough: next to it the README must say the OTHER
    surface prices ALL attempts, and that the two medians legitimately DIFFER."""
    text = _read("README.md")
    hits = [m.start() for m in re.finditer(re.escape(REQUIRED_TOKEN), text)]
    assert hits
    for at in hits:
        near = _window(text, at)
        low = near.lower()
        assert "stage-times" in low, at
        assert "all attempts" in low, at
        assert "different median" in low, at


# ---------------------------------------------------------------------------
# Behavior 3 -- the live roles/pm.md names the population it prices
# ---------------------------------------------------------------------------

def test_b3_live_pm_card_names_the_constant() -> None:
    """THE BRAKE, second doc."""
    assert _GAPS([REQUIRED_TOKEN], _read("roles/pm.md")) == ()


def test_b3_pm_card_brake_is_two_sided() -> None:
    text = _read("roles/pm.md")
    stripped = text.replace(REQUIRED_TOKEN, "<removed>")
    assert _GAPS([REQUIRED_TOKEN], stripped) == (REQUIRED_TOKEN,)
    assert _GAPS([REQUIRED_TOKEN], text) == ()


def test_b3_pm_card_names_the_population_next_to_the_copy_instruction() -> None:
    """The card orders every PM to copy the `stage-budget:` line verbatim; the
    population that line prices must be named in the SAME instruction."""
    text = _read("roles/pm.md")
    at = text.index(REQUIRED_TOKEN)
    near = _window(text, at)
    low = near.lower()
    assert "stage-budget:" in low          # the copied line is the subject
    assert "did work" in low               # the population it prices
    assert "stage-times" in low            # the surface it disagrees with
    assert "different" in low              # and that the disagreement is legitimate


def test_b3_population_clause_is_load_bearing_not_decorative() -> None:
    """Non-vacuity for behavior 3: delete the population clause's key phrase and a
    population-aware brake reds, so the assertion above is measuring the text."""
    text = _read("roles/pm.md")
    required = [REQUIRED_TOKEN, "did work", "stage-budget:"]
    assert _GAPS(required, text) == ()
    for phrase in required:
        stripped = text.replace(phrase, "<removed>")
        assert _GAPS(required, stripped) == (phrase,), phrase


# ---------------------------------------------------------------------------
# Acceptance criteria -- imports clean, roadmap ledger rows present
# ---------------------------------------------------------------------------

def test_ac_imports_stay_clean() -> None:
    assert foundry.__name__ == "foundry"
    assert dispatcher.__name__ == "dispatcher"
    assert callable(foundry.role_card_doc_gaps)
    assert callable(foundry.roadmap_ledger_gaps)


def test_ac_roadmap_ledger_rows_for_this_iteration_are_in_the_tree() -> None:
    """Index row + archive detail bullet for iteration 370, measured on the tree
    the commit will ship (both files are git-tracked)."""
    index_text = _read("PLATFORM_ROADMAP.md")
    archive_text = _read("PLATFORM_ROADMAP_ARCHIVE.md")
    assert foundry.roadmap_ledger_gaps(index_text, archive_text, (THIS_ITER,)) == []
    # non-vacuity: the same oracle DOES report a missing iteration
    assert foundry.roadmap_ledger_gaps(index_text, archive_text, (10 ** 6,)) == [10 ** 6]
