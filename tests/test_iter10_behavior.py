"""Black-box behaviour tests for iter 10 -- the pure `spec_lint(spec_text) ->
SpecLint` helper (PM-spec completeness + size guard) and the additive on-demand
`foundry lint-spec --file <path>` CLI subcommand.

ISOLATION: written from the PM spec (Expected Behaviors 1-13) and the product's
own observable behaviour only. The implementation source (foundry.py internals),
the engineer/reviewer notes, and `git diff` were NOT read. Every check drives the
public interface: the pure core via `foundry.spec_lint(...)` against synthetic
spec strings, and the CLI via `foundry.main(["lint-spec", ...])` with tmp-path
spec files. Module constants (`REQUIRED_SPEC_SECTIONS`, `SPEC_SIZE_WARN_CHARS`,
`SPEC_MAX_BEHAVIORS`) are monkeypatched only where a behaviour calls for it and
always via pytest's `monkeypatch` fixture so global state auto-restores. Fully
offline and deterministic -- real temp files only, NO subprocess/git/network/
agent-run except the `--help` regression probe (which only prints usage + exits).
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402


# --------------------------------------------------------------------------
# helpers -- build synthetic spec strings (never read the real repo)
# --------------------------------------------------------------------------
DEFAULT_SECTIONS = (
    "## Feature",
    "## Why",
    "## Expected Behaviors",
    "## Acceptance Criteria",
    "## Out of Scope",
    "## Size self-check",
)


def _behaviors_block(n):
    return "\n".join(f"{i}. behaviour number {i}" for i in range(1, n + 1))


def _full_spec(n_behaviors=3, pad_chars=0, size_check_heading="## Size self-check"):
    """A structurally-complete spec: all 6 required sections, `n_behaviors`
    ordered items in Expected Behaviors, optional `pad_chars` filler to grow the
    char count. `size_check_heading` lets a test use a trailing-parenthetical
    variant of the last heading."""
    pad = ("x" * pad_chars) if pad_chars else ""
    return (
        "## Feature\nA small additive feature.\n\n"
        "## Why\nBecause the guard is on-mission.\n\n"
        "## Expected Behaviors\n" + _behaviors_block(n_behaviors) + "\n\n"
        "## Acceptance Criteria\n- [ ] the thing is done\n\n"
        "## Out of Scope\n- wiring it into the pipeline\n\n"
        f"{size_check_heading}\n- fits one context window " + pad + "\n"
    )


def _write_spec(tmp_path, text, name="spec.md"):
    p = tmp_path / name
    p.write_text(text)
    return p


# ==========================================================================
# A. Pure helper  spec_lint(spec_text: str) -> SpecLint
# ==========================================================================

# --- Behavior 1 -- pure, total, deterministic; never raises ----------------
def test_b01_pure_total_deterministic():
    for text in ("", "no sections here", _full_spec(), _full_spec(5, pad_chars=50)):
        a = foundry.spec_lint(text)                      # must not raise
        b = foundry.spec_lint(text)                      # identical arg
        assert type(a).__name__ == "SpecLint", "spec_lint did not return a SpecLint"
        assert a == b, "spec_lint is not deterministic for identical input"
    # empty string is handled (total) and yields a REVIEW (no sections present)
    empty = foundry.spec_lint("")
    assert empty.char_count == 0
    assert empty.verdict == "REVIEW"


# --- Behavior 2 -- char_count == len(text) ---------------------------------
def test_b02_char_count_equals_len():
    for text in ("", "abc", "héllo \u2013 unicode", _full_spec(4, pad_chars=123)):
        assert foundry.spec_lint(text).char_count == len(text), (
            f"char_count != len(text) for {text[:20]!r}..."
        )


# --- Behavior 3 -- required-section detection (default 6-tuple) ------------
def test_b03_default_required_sections_and_all_present():
    # default constant is exactly the 6-tuple, in order
    assert foundry.REQUIRED_SPEC_SECTIONS == DEFAULT_SECTIONS
    sl = foundry.spec_lint(_full_spec())
    assert sl.missing_sections == (), f"complete spec reported missing: {sl.missing_sections}"
    assert sl.sections_ok is True


def test_b03_missing_sections_in_required_order():
    # drop "## Why" and "## Out of Scope"; missing tuple must be in REQUIRED order
    text = _full_spec().replace("## Why\nBecause the guard is on-mission.\n\n", "")
    text = text.replace("## Out of Scope\n- wiring it into the pipeline\n\n", "")
    sl = foundry.spec_lint(text)
    assert sl.missing_sections == ("## Why", "## Out of Scope"), sl.missing_sections
    assert sl.sections_ok is False


def test_b03_trailing_parenthetical_heading_counts_present():
    # "## Size self-check (roadmap item 5 spirit)" must satisfy "## Size self-check"
    text = _full_spec(size_check_heading="## Size self-check (roadmap item 5 spirit)")
    sl = foundry.spec_lint(text)
    assert "## Size self-check" not in sl.missing_sections, (
        "trailing-parenthetical heading was not accepted for '## Size self-check'"
    )
    assert sl.missing_sections == ()
    # but a heading that only shares a PREFIX-without-space must NOT count:
    # "## Feature-flags" is not "## Feature"
    text2 = _full_spec().replace("## Feature\n", "## Feature-flags\n", 1)
    sl2 = foundry.spec_lint(text2)
    assert "## Feature" in sl2.missing_sections, (
        "'## Feature-flags' wrongly satisfied required '## Feature' (needs equality or 'H ')"
    )


# --- Behavior 4 -- behavior count within Expected Behaviors section only ----
def test_b04_num_behaviors_counts_only_within_section():
    text = (
        "## Feature\n1. not counted (outside)\n\n"
        "## Expected Behaviors\n"
        "1. one\n"
        "2. two\n"
        "  12. indented still counts\n"
        "not a number line\n"
        "A. lettered does not count\n"
        "1) paren does not count\n"
        "## Acceptance Criteria\n"
        "3. outside the section, not counted\n"
    )
    assert foundry.spec_lint(text).num_behaviors == 3


def test_b04_absent_section_zero():
    assert foundry.spec_lint("## Feature\n1. x\n## Why\n2. y\n").num_behaviors == 0


def test_b04_heading_with_trailing_text_still_starts_section():
    text = "## Expected Behaviors (black-box)\n1. a\n2. b\n## Out of Scope\n3. z\n"
    assert foundry.spec_lint(text).num_behaviors == 2


# --- Behavior 5 -- size verdict at DEFAULT thresholds ----------------------
def test_b05_default_thresholds_and_size_flags():
    assert foundry.SPEC_SIZE_WARN_CHARS == 16000
    assert foundry.SPEC_MAX_BEHAVIORS == 20

    small = foundry.spec_lint(_full_spec(3, pad_chars=10))
    assert small.size_over_chars is False
    assert small.size_over_behaviors is False
    assert small.size_ok is True

    # over char threshold (pad well past 16000), few behaviors
    big_chars = foundry.spec_lint(_full_spec(2, pad_chars=17000))
    assert big_chars.char_count > 16000
    assert big_chars.size_over_chars is True
    assert big_chars.size_ok is False

    # over behavior threshold (21 > 20), small char count
    many = foundry.spec_lint("## Expected Behaviors\n" + _behaviors_block(21) + "\n")
    assert many.num_behaviors == 21
    assert many.size_over_behaviors is True
    assert many.size_ok is False


# --- Behavior 6 -- combined verdict ok / verdict string --------------------
def test_b06_combined_verdict():
    ok = foundry.spec_lint(_full_spec(3, pad_chars=10))
    assert ok.sections_ok and ok.size_ok
    assert ok.ok is True
    assert ok.verdict == "OK"

    # complete sections but oversized -> ok False, verdict REVIEW
    over = foundry.spec_lint(_full_spec(3, pad_chars=17000))
    assert over.sections_ok is True and over.size_ok is False
    assert over.ok is False
    assert over.verdict == "REVIEW"

    # right-sized but missing a section -> ok False, verdict REVIEW
    miss = foundry.spec_lint(
        _full_spec().replace("## Out of Scope\n- wiring it into the pipeline\n\n", "")
    )
    assert miss.sections_ok is False and miss.size_ok is True
    assert miss.ok is False
    assert miss.verdict == "REVIEW"


# --- Behavior 7 -- thresholds / section-set resolved at CALL TIME ----------
def test_b07_max_behaviors_patch_reflected(monkeypatch):
    # example from the spec: patch SPEC_MAX_BEHAVIORS = 3, a 12-behavior spec
    # then reports size_over_behaviors True and ok False.
    spec12 = _full_spec(12, pad_chars=10)  # complete sections, small chars
    base = foundry.spec_lint(spec12)
    assert base.size_over_behaviors is False and base.ok is True, (
        "precondition: 12 behaviours should pass under the default max of 20"
    )
    monkeypatch.setattr(foundry, "SPEC_MAX_BEHAVIORS", 3)
    patched = foundry.spec_lint(spec12)
    assert patched.size_over_behaviors is True
    assert patched.ok is False
    assert patched.verdict == "REVIEW"


def test_b07_warn_chars_patch_reflected(monkeypatch):
    text = _full_spec(3, pad_chars=200)
    assert foundry.spec_lint(text).size_over_chars is False
    monkeypatch.setattr(foundry, "SPEC_SIZE_WARN_CHARS", 50)
    assert foundry.spec_lint(text).size_over_chars is True


def test_b07_required_sections_patch_reflected(monkeypatch):
    text = _full_spec()  # complete against the default 6-tuple
    assert foundry.spec_lint(text).missing_sections == ()
    monkeypatch.setattr(
        foundry, "REQUIRED_SPEC_SECTIONS", DEFAULT_SECTIONS + ("## Rollback Plan",)
    )
    sl = foundry.spec_lint(text)
    assert sl.missing_sections == ("## Rollback Plan",)
    assert sl.sections_ok is False


# ==========================================================================
# B. CLI subcommand  foundry lint-spec --file <path>
# ==========================================================================

# --- Behavior 8 -- complete + right-sized -> exit 0, report has the fields --
def test_b08_complete_spec_exit0(tmp_path, capsys):
    text = _full_spec(3, pad_chars=40)
    p = _write_spec(tmp_path, text)
    rc = foundry.main(["lint-spec", "--file", str(p)])
    out = capsys.readouterr().out
    assert rc == 0, f"complete spec returned {rc!r}, expected 0"
    sl = foundry.spec_lint(text)
    assert "verdict: OK" in out, f"report missing 'verdict: OK':\n{out}"
    assert str(sl.num_behaviors) in out, "report does not print num_behaviors"
    assert str(sl.char_count) in out, "report does not print char_count"


# --- Behavior 9 -- missing a required section -> exit 1 --------------------
def test_b09_missing_section_exit1(tmp_path, capsys):
    text = _full_spec().replace("## Out of Scope\n- wiring it into the pipeline\n\n", "")
    p = _write_spec(tmp_path, text)
    rc = foundry.main(["lint-spec", "--file", str(p)])
    out = capsys.readouterr().out
    assert rc == 1, f"missing-section spec returned {rc!r}, expected 1"
    assert "verdict: REVIEW" in out, f"report missing 'verdict: REVIEW':\n{out}"
    assert "## Out of Scope" in out, "report does not name the missing heading verbatim"


# --- Behavior 10 -- oversized -> exit 1 (drive via patched threshold) ------
def test_b10_oversized_exit1(tmp_path, monkeypatch, capsys):
    text = _full_spec(5, pad_chars=20)  # structurally complete
    p = _write_spec(tmp_path, text)
    monkeypatch.setattr(foundry, "SPEC_MAX_BEHAVIORS", 2)  # 5 > 2 -> oversized
    rc = foundry.main(["lint-spec", "--file", str(p)])
    out = capsys.readouterr().out
    assert rc == 1, f"oversized spec returned {rc!r}, expected 1"
    assert "verdict: REVIEW" in out, f"report missing 'verdict: REVIEW':\n{out}"


# --- Behavior 11 -- missing file -> exit 2, prints path, no exception ------
def test_b11_missing_file_exit2(tmp_path, capsys):
    missing = tmp_path / "does_not_exist.md"
    assert not missing.exists()
    rc = foundry.main(["lint-spec", "--file", str(missing)])  # must not raise
    cap = capsys.readouterr()
    combined = cap.out + cap.err
    assert rc == 2, f"missing file returned {rc!r}, expected 2 (distinct from lint failure)"
    assert str(missing) in combined, "error message does not include the offending path"


# --- Behavior 12 -- CLI is a thin wrapper over the pure core ---------------
def test_b12_cli_thin_wrapper(tmp_path, capsys):
    for text in (_full_spec(3, pad_chars=15),                       # OK
                 _full_spec().replace("## Why\nBecause the guard is on-mission.\n\n", "")):  # REVIEW
        p = _write_spec(tmp_path, text, name="w.md")
        foundry.main(["lint-spec", "--file", str(p)])
        out = capsys.readouterr().out
        sl = foundry.spec_lint(text)
        assert f"verdict: {sl.verdict}" in out, (
            f"CLI verdict token disagrees with spec_lint().verdict ({sl.verdict})"
        )
        assert str(sl.num_behaviors) in out, "CLI num_behaviors disagrees with SpecLint field"
        assert str(sl.char_count) in out, "CLI char_count disagrees with SpecLint field"


# ==========================================================================
# C. Non-regression (offline)
# ==========================================================================

# --- Behavior 13 -- imports, --help lists all subs, old surface intact -----
def test_b13_modules_import_and_surface_intact():
    assert foundry is not None
    assert dispatcher is not None
    assert callable(foundry.spec_lint)
    assert callable(foundry.lint_spec_cli)
    # pre-existing control-flow entry points must remain present + callable
    for fn in ("build_prompt", "run_iteration", "run_continuous", "run_stage"):
        assert callable(getattr(foundry, fn)), f"foundry.{fn} missing/not callable (regression)"


def test_b13_help_lists_all_subcommands(capsys):
    with pytest.raises(SystemExit) as ei:
        foundry.main(["--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    for sub in ("run", "once", "doctor", "learnings", "agents", "lint-spec"):
        assert sub in out, f"subcommand {sub!r} missing from --help:\n{out}"
