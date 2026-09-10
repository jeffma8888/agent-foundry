"""Black-box behaviour tests for iter 325 -- `foundry leak-check`, the dormant,
read-only verb that gives the fail-CLOSED public-safety leak gate a
machine-readable verdict of its OWN.

WHY THE VERB EXISTS (spec's "Why", re-asserted as Behaviors 3/5/6): this repo is
PUBLIC and the loop auto-pushes, so the committed leak guard is the last line of
defence -- and `roles/final.md` graded it by EXIT CODE alone, which is shell
plumbing the most time-pressured seat hand-types. One iteration earlier that
grading broke: the gate piped the guard through `tail` and read a bash-only
`${PIPESTATUS[0]}` that expands to the empty string under zsh, so the verdict was
UNREADABLE while the scanner's own `0 finding(s) in ... scanned` summary still
LOOKED like a pass. The verb is the second, un-loseable channel: a verdict WORD
on stdout plus the SAME 0/1/2 code, and an undecidable scan gets its own name
(`UNKNOWN`) so "could not decide" can never collapse into `CLEAN`.

Public surface exercised here: the pure `leak_guard_verdict`, the single I/O seam
`run_leak_guard`, the `leak_check_cli` printer, and the
`main(["leak-check", ...])` entry.

ISOLATION / SAFETY CONTRACT: every CLI behaviour below drives a SCRIPTED
`run_leak_guard` seam patched by BARE module name, so no real scan, git command
or network call runs; `subprocess.run` is replaced by a RECORDER in those tests
and the recorder is asserted EMPTY. The two seam tests use a tmp `repo` dir only
-- the real foundry repo is never scanned and nothing is written outside
`tmp_path`. Every fixture string is SYNTHETIC with no absolute machine path and
no personal identifier, so the in-loop leak guard stays clean on the ship commit,
and no assertion depends on git-ignored local state (Behaviors 9/10 read TRACKED
files resolved off this file's own location).
"""
from __future__ import annotations

import ast
import io
import json
import pathlib
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402

VERB = "leak-check"
SOURCE = _ROOT / "foundry.py"
DISPATCHER = _ROOT / "dispatcher.py"
FINAL_CARD = _ROOT / "roles" / "final.md"

# The three names the feature adds; Behavior 9 asserts none is reachable from
# the live pipeline.
NEW_NAMES = ("leak_guard_verdict", "run_leak_guard", "leak_check_cli")

# Every non-clean, non-leaked code the guard (or its death) can produce. `2` is
# the guard's own "could not complete"; `-9` is a signal kill; `None` is "the
# scan never produced a code at all".
UNDECIDABLE = (2, 3, -9, 255, None)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _write_cfg(tmp_path, guard_body: str | None = None, **over):
    """A minimal product config in a tmp dir. `repo` is a TMP dir so the real
    foundry repo is NEVER scanned. `guard_body`, when given, is seeded as that
    tmp repo's own `scripts/leak_guard.py`."""
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True, exist_ok=True)
    if guard_body is not None:
        (repo / "scripts" / "leak_guard.py").write_text(guard_body)
    data = {
        "name": "demoprod",
        "repo": str(repo),
        "allowed_push_repo": "demoprod",
        "vision": str(tmp_path / "VISION.md"),
        "work_root": str(tmp_path / "work"),
    }
    data.update(over)
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data))
    return p, repo


def _capture(fn):
    """Run fn() with stdout/stderr captured SEPARATELY; return (rc, out, err).
    Separate capture matters: Behavior 7 requires the JSON to be the ENTIRE
    stdout, so stderr noise must not contaminate the parse."""
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = fn()
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue(), err.getvalue()


def _one_line(text: str) -> str:
    """The single non-empty stdout line, asserting there is EXACTLY one."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert len(lines) == 1, f"expected EXACTLY one stdout line, got {lines!r}"
    return lines[0].strip()


def _script_seam(monkeypatch, result, calls=None):
    """Patch the ONE I/O seam by BARE module name and forbid any subprocess."""
    def fake(repo, ref="HEAD", **kw):
        if calls is not None:
            calls.append((str(repo), ref))
        if isinstance(result, BaseException):
            raise result
        return result
    monkeypatch.setattr(foundry, "run_leak_guard", fake)
    spawned = []
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: spawned.append(a) or None)
    return spawned


# --------------------------------------------------------------------------
# Behavior 1 -- ABSENT is never a gate failure, whatever the returncode
# --------------------------------------------------------------------------
def test_b01_absent_guard_is_clean_exit_zero_for_every_returncode():
    assert foundry.leak_guard_verdict(guard_present=False, returncode=None,
                                      detail="") == ("ABSENT", 0)
    for rc in (0, 1, 2, None, -9, 255):
        assert foundry.leak_guard_verdict(False, rc, "anything") == ("ABSENT", 0), (
            f"a product repo carrying NO scripts/leak_guard.py must read ABSENT/0 "
            f"whatever returncode is passed; returncode={rc!r} broke that"
        )


# --------------------------------------------------------------------------
# Behavior 2 -- the two decisive arms
# --------------------------------------------------------------------------
def test_b02_present_guard_maps_zero_to_clean_and_one_to_leaked():
    assert foundry.leak_guard_verdict(True, 0, "0 finding(s)") == ("CLEAN", 0)
    assert foundry.leak_guard_verdict(True, 1, "1 finding(s)") == ("LEAKED", 1)


# --------------------------------------------------------------------------
# Behavior 3 -- FAIL-CLOSED TOTALITY, stated as a property
# --------------------------------------------------------------------------
def test_b03_every_undecidable_code_folds_to_unknown_two():
    for rc in UNDECIDABLE:
        assert foundry.leak_guard_verdict(True, rc, "") == ("UNKNOWN", 2), (
            f"returncode={rc!r} must be UNDECIDABLE (UNKNOWN/2), never a decisive "
            f"verdict: 'could not decide' collapsing into CLEAN is the whole bug"
        )


def test_b03_clean_is_reachable_only_from_present_and_zero():
    for present in (True, False):
        for rc in (0, 1) + UNDECIDABLE:
            verdict, code = foundry.leak_guard_verdict(present, rc, "d")
            if (verdict, code) == ("CLEAN", 0):
                assert present is True and rc == 0, (
                    f"CLEAN leaked out of guard_present={present!r} "
                    f"returncode={rc!r}"
                )
            if code == 0:
                assert verdict in ("CLEAN", "ABSENT"), (
                    f"exit 0 must come ONLY from CLEAN or ABSENT, got {verdict!r}"
                )
            assert verdict in ("ABSENT", "CLEAN", "LEAKED", "UNKNOWN")
            assert code in (0, 1, 2)


def test_b03_function_is_total_and_raises_for_no_input():
    # Odd shapes must fail both equality tests and land in the fail-closed arm
    # rather than raise: a crash in the decision is an un-gradeable gate.
    for rc in ("0", 0.0, True, [], object()):
        verdict, code = foundry.leak_guard_verdict(True, rc, "")
        assert (verdict, code) in (("CLEAN", 0), ("LEAKED", 1), ("UNKNOWN", 2))
    assert foundry.leak_guard_verdict(True, "2", None) == ("UNKNOWN", 2)


# --------------------------------------------------------------------------
# Behavior 4 -- ONE exact stdout line, the code returned, nothing spawned
# --------------------------------------------------------------------------
def test_b04_leaked_prints_exactly_one_line_and_returns_one(tmp_path, monkeypatch):
    cfg_path, repo = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    calls = []
    spawned = _script_seam(monkeypatch, (True, 1, "1 finding"), calls)
    rc, out, err = _capture(lambda: foundry.leak_check_cli(cfg, ref="HEAD"))
    assert _one_line(out) == "leak-guard: LEAKED -- 1 finding"
    assert rc == 1
    assert spawned == [], "no subprocess may run: the seam is the only I/O"
    assert calls == [(str(repo), "HEAD")], (
        "the seam must be reached by BARE module name with the PRODUCT's repo "
        f"and the ref, got {calls!r}"
    )


# --------------------------------------------------------------------------
# Behavior 5 -- the line SHAPE is stable across all four verdicts
# --------------------------------------------------------------------------
@pytest.mark.parametrize("seam,word,code", [
    ((False, None, "no guard here"), "ABSENT", 0),
    ((True, 0, "0 finding(s) in 3 file(s) scanned"), "CLEAN", 0),
    ((True, 1, "1 finding(s) in 3 file(s) scanned"), "LEAKED", 1),
    ((True, 2, "scan could not run"), "UNKNOWN", 2),
])
def test_b05_line_shape_and_code_agree_with_the_pure_verdict(
        tmp_path, monkeypatch, seam, word, code):
    cfg_path, _repo = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    spawned = _script_seam(monkeypatch, seam)
    rc, out, _err = _capture(lambda: foundry.leak_check_cli(cfg))
    line = _one_line(out)
    assert line.startswith("leak-guard: ")
    assert line.split()[1] == word
    assert (word, rc) == foundry.leak_guard_verdict(seam[0], seam[1], seam[2]), (
        "the printed WORD and the returned CODE must come from the SAME pure "
        "decision, so the two channels can never disagree"
    )
    assert rc == code
    assert spawned == []


# --------------------------------------------------------------------------
# Behavior 6 -- a RAISING seam is UNKNOWN, not a crash
# --------------------------------------------------------------------------
def test_b06_raising_seam_is_unknown_not_a_traceback(tmp_path, monkeypatch):
    cfg_path, _repo = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _script_seam(monkeypatch, RuntimeError("boom"))
    rc, out, _err = _capture(lambda: foundry.leak_check_cli(cfg))
    line = _one_line(out)
    assert line.startswith("leak-guard: UNKNOWN -- ")
    assert "boom" in line, f"the detail must name the failure, got {line!r}"
    assert rc == 2, "the fail-closed reading of 'we do not know' is 2"


def test_b06_seam_may_raise_anything_and_still_reports_unknown(
        tmp_path, monkeypatch):
    cfg_path, _repo = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    for exc in (RuntimeError("boom"), OSError("boom"), ValueError("boom"),
                KeyError("boom")):
        _script_seam(monkeypatch, exc)
        rc, out, _err = _capture(lambda: foundry.leak_check_cli(cfg))
        assert _one_line(out).split()[1] == "UNKNOWN"
        assert rc == 2


# --------------------------------------------------------------------------
# Behavior 7 -- --json is ONE parseable document, and the human line is gone
# --------------------------------------------------------------------------
@pytest.mark.parametrize("seam", [
    (False, None, "no guard here"),
    (True, 0, "0 finding(s) in 3 file(s) scanned"),
    (True, 1, "1 finding(s) in 3 file(s) scanned"),
    (True, 2, "scan could not run"),
])
def test_b07_json_mode_carries_the_stable_key_set(tmp_path, monkeypatch, seam):
    cfg_path, _repo = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _script_seam(monkeypatch, seam)
    rc, out, _err = _capture(
        lambda: foundry.leak_check_cli(cfg, ref="HEAD", as_json=True))
    doc = json.loads(_one_line(out))
    assert isinstance(doc, dict)
    for key in ("product", "ref", "verdict", "exit_code", "returncode",
                "detail"):
        assert key in doc, f"json mode must carry {key!r}; got {sorted(doc)}"
    verdict, code = foundry.leak_guard_verdict(seam[0], seam[1], seam[2])
    assert (doc["verdict"], doc["exit_code"]) == (verdict, code)
    assert rc == code, "the RETURN value is identical in both modes"
    assert doc["product"] == cfg.name and doc["ref"] == "HEAD"
    assert "leak-guard: " not in out, (
        "the human line must NOT be printed in json mode -- one line, one format"
    )


# --------------------------------------------------------------------------
# Behavior 8 -- the verb is REGISTERED and its flags reach the call
# --------------------------------------------------------------------------
def test_b08_main_dispatches_to_the_cli_with_ref_defaulting_to_head(
        tmp_path, monkeypatch):
    cfg_path, _repo = _write_cfg(tmp_path)
    seen = {}

    def fake_cli(cfg, ref="HEAD", as_json=False):
        seen.update(product=cfg.name, ref=ref, as_json=as_json)
        return 7
    monkeypatch.setattr(foundry, "leak_check_cli", fake_cli)
    rc, _out, _err = _capture(
        lambda: foundry.main([VERB, "--config", str(cfg_path)]))
    assert rc == 7, "main must return the verb's own exit code"
    assert seen == {"product": "demoprod", "ref": "HEAD", "as_json": False}


def test_b08_ref_and_json_flags_reach_the_call(tmp_path, monkeypatch):
    cfg_path, _repo = _write_cfg(tmp_path)
    seen = {}

    def fake_cli(cfg, ref="HEAD", as_json=False):
        seen.update(ref=ref, as_json=as_json)
        return 0
    monkeypatch.setattr(foundry, "leak_check_cli", fake_cli)
    _capture(lambda: foundry.main([
        VERB, "--config", str(cfg_path), "--ref", "abc1234", "--json"]))
    assert seen == {"ref": "abc1234", "as_json": True}


def test_b08_verb_is_in_the_registered_parser_set(tmp_path):
    # The registration itself, read through the product's own parser rather than
    # by grepping source text.
    with pytest.raises(SystemExit):
        foundry.main([VERB])  # --config is required
    cfg_path, _repo = _write_cfg(tmp_path)
    with pytest.raises(SystemExit):
        foundry.main([VERB, "--config", str(cfg_path), "--bogus-flag"])


# --------------------------------------------------------------------------
# Behavior 9 -- DORMANT / resume-safe
# --------------------------------------------------------------------------
def _called_names(tree: ast.AST, func_name: str) -> set[str]:
    """Every Name/Attribute identifier appearing inside `func_name`'s body."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == func_name:
            names = set()
            for sub in ast.walk(node):
                if isinstance(sub, ast.Name):
                    names.add(sub.id)
                elif isinstance(sub, ast.Attribute):
                    names.add(sub.attr)
            return names
    raise AssertionError(f"{func_name} not found in the parsed source")


@pytest.mark.parametrize("live", [
    "run_iteration", "run_stage", "build_prompt", "postrelease_step"])
def test_b09_no_live_pipeline_function_reaches_the_new_names(live):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    names = _called_names(tree, live)
    for new in NEW_NAMES:
        assert new not in names, (
            f"{live} reaches {new}: the verb must stay DORMANT so a loop in "
            f"flight resumes byte-identically"
        )


def test_b09_dispatcher_never_mentions_the_new_names():
    text = DISPATCHER.read_text(encoding="utf-8")
    for new in NEW_NAMES:
        assert new not in text, f"dispatcher.py must not reach {new}"


def test_b09_both_modules_still_import():
    assert foundry.__name__ == "foundry"
    assert dispatcher.__name__ == "dispatcher"
    for new in NEW_NAMES:
        assert callable(getattr(foundry, new))


def test_b09_only_the_verb_dispatch_calls_the_cli():
    """`leak_check_cli`'s only call site in foundry.py is main()'s dispatch."""
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    callers = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) \
                        and sub.func.id == "leak_check_cli":
                    callers.add(node.name)
    assert callers == {"main"}, (
        f"expected main() to be the ONLY caller, got {sorted(callers)}"
    )


# --------------------------------------------------------------------------
# Behavior 10 -- roles/final.md NAMES the verb, and keeps the old literal
# --------------------------------------------------------------------------
def test_b10_final_card_names_the_verb_in_both_gate_paragraphs():
    text = FINAL_CARD.read_text(encoding="utf-8")
    item6 = [ln for ln in text.splitlines()
             if ln.lstrip().startswith("6. **Leak-guard clean")]
    bullet = [ln for ln in text.splitlines()
              if ln.lstrip().startswith("- **Leak-guard gate")]
    assert len(item6) == 1 and len(bullet) == 1, (
        f"expected one checklist item 6 and one ship bullet, got "
        f"{len(item6)}/{len(bullet)}"
    )
    for label, line in (("checklist item 6", item6[0]),
                        ("pre-push ship bullet", bullet[0])):
        assert "foundry.py leak-check" in line, (
            f"{label} must NAME the verb instead of leaving the gate to grade "
            f"shell exit-code plumbing"
        )
        assert "scripts/leak_guard.py" in line, (
            f"{label} must KEEP the iteration-52 guard literal"
        )


def test_b10_final_card_stays_pure_ascii():
    text = FINAL_CARD.read_text(encoding="utf-8")
    assert text.isascii(), "roles/final.md must stay pure ASCII"


# --------------------------------------------------------------------------
# The seam itself -- offline, tmp-repo only (acceptance criterion 2)
# --------------------------------------------------------------------------
def test_seam_reports_absent_without_spawning_anything(tmp_path, monkeypatch):
    cfg_path, repo = _write_cfg(tmp_path)  # no guard seeded
    cfg = foundry.load_config(str(cfg_path))
    spawned = []
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: spawned.append(a) or None)
    present, rc, detail = foundry.run_leak_guard(cfg.repo)
    assert (present, rc) == (False, None)
    assert "scripts/leak_guard.py" in detail
    assert spawned == [], "a missing guard must be detected WITHOUT a subprocess"
    assert foundry.leak_guard_verdict(present, rc, detail) == ("ABSENT", 0)


def test_seam_scrubs_absolute_looking_tokens_out_of_the_detail(tmp_path):
    # A stand-in guard that prints an absolute-looking path in its summary. The
    # detail is the ONE string that leaves the seam, so no machine path may ride
    # it into a public artifact.
    guard = (
        "import sys\n"
        "sys.stderr.write('2 finding(s) in /aaa/bbb/repo scanned\\n')\n"
        "sys.exit(1)\n"
    )
    cfg_path, repo = _write_cfg(tmp_path, guard_body=guard)
    cfg = foundry.load_config(str(cfg_path))
    present, rc, detail = foundry.run_leak_guard(cfg.repo)
    assert present is True and rc == 1
    assert "/aaa/bbb/repo" not in detail, f"unscrubbed path in {detail!r}"
    assert "<path>" in detail and "\n" not in detail
    assert foundry.leak_guard_verdict(present, rc, detail) == ("LEAKED", 1)


# ==========================================================================
# INDEPENDENT TESTER BLOCK (iteration 325, `test_t*`)
#
# Written from the PM spec's Expected Behaviors ONLY, by an author who did not
# read foundry.py, dispatcher.py, `git diff`, or the engineer / reviewer / fix
# notes. It deliberately goes PAST the spec's fixture lists: a fixture table is
# only as wide as its author's imagination, so Behavior 3's TOTALITY claim and
# Behaviors 4/5/7's "EXACTLY ONE line" claim are re-asserted as PROPERTIES over
# domains the numbered behaviors never enumerate (wide returncode sweep,
# multi-line and empty details, JSON round-trip through `main`).
# Everything here stays offline: the one I/O seam is scripted and
# `subprocess.run` is a RECORDER that must stay EMPTY.
# ==========================================================================
_WORDS = {"ABSENT": 0, "CLEAN": 0, "LEAKED": 1, "UNKNOWN": 2}

# A domain far wider than Behavior 3's (2, 3, -9, 255, None): every signal-style
# negative, every byte-wide code, and the None a killed/never-run scan yields.
_RC_SWEEP = [None, 0, 1, 2, 3, 4, 7, 9, 64, 100, 126, 127, 128, 129, 130,
             137, 143, 200, 254, 255, 256, 1000, -1, -2, -6, -9, -11, -15,
             -127, -255, -1000]


def test_t01_verdict_is_total_over_a_wide_returncode_sweep():
    """B3 as a PROPERTY, not a fixture list: the pure function must be TOTAL and
    its two channels must agree, for every plausible returncode a real scan can
    produce -- including the 256/1000/-1000 values no numbered behavior names."""
    for present in (True, False):
        for rc in _RC_SWEEP:
            word, code = foundry.leak_guard_verdict(
                guard_present=present, returncode=rc, detail="d")
            assert word in _WORDS, f"unknown verdict word {word!r} for {(present, rc)}"
            assert code == _WORDS[word], (
                f"word/code disagree: {(word, code)} for {(present, rc)}")
            # Invariant A -- CLEAN is reachable ONLY from present + exactly 0.
            if (word, code) == ("CLEAN", 0):
                assert present is True and rc == 0, (
                    f"CLEAN leaked out of {(present, rc)}: a fail-CLOSED gate may "
                    "never call an undecided scan clean")
            # Invariant B -- exit 0 comes ONLY from CLEAN or ABSENT.
            if code == 0:
                assert word in ("CLEAN", "ABSENT"), (
                    f"exit 0 from {word!r} at {(present, rc)}")
            # Invariant C -- no guard is ALWAYS absent, whatever the code says.
            if not present:
                assert (word, code) == ("ABSENT", 0), (
                    f"missing guard must be ABSENT/0, got {(word, code)} for rc={rc}")


def test_t02_detail_never_changes_the_verdict():
    """The verdict is a function of (guard_present, returncode) alone: a detail
    string is REPORTING, so no detail may move the gate's decision. Also pins
    that `detail` is OPTIONAL, which Behavior 2's `...` leaves ambiguous."""
    details = ["", "0 finding(s) in 282 file(s) scanned", "1 finding",
               "traceback:\nline1\nline2", " " * 50, "no such file", "x" * 4000,
               "verdict: CLEAN", "LEAKED", "exit 0"]
    for present, rc in [(True, 0), (True, 1), (True, 2), (True, None),
                        (False, None), (False, 1)]:
        base = foundry.leak_guard_verdict(present, rc, "")
        for d in details:
            assert foundry.leak_guard_verdict(present, rc, d) == base, (
                f"detail {d[:24]!r} moved the verdict for {(present, rc)}")
        # detail is defaultable -- the pure decision needs only the two inputs.
        assert foundry.leak_guard_verdict(present, rc) == base


def test_t03_one_line_contract_survives_a_multiline_detail(tmp_path, monkeypatch):
    """B4/B5 promise the SINGLE stdout line unconditionally, and a real guard's
    failure detail is multi-line (a traceback / `stderr` tail). If a newline in
    the detail split the line, every downstream reader of `leak-guard: ` would
    see a second, verdict-less line -- exactly the "unreadable verdict" this
    iteration exists to remove."""
    nasty = "scan could not complete:\nTraceback (most recent call last):\n  boom"
    for seam, word in [((True, 2, nasty), "UNKNOWN"),
                       ((True, 1, "found:\n- token A\n- token B"), "LEAKED"),
                       ((False, None, "no guard\nat all"), "ABSENT"),
                       ((True, 0, "clean\n"), "CLEAN")]:
        cfg_path, _repo = _write_cfg(tmp_path)
        cfg = foundry.load_config(str(cfg_path))
        spawned = _script_seam(monkeypatch, seam)
        rc, out, _err = _capture(lambda: foundry.leak_check_cli(cfg))
        line = _one_line(out)
        assert line.startswith("leak-guard: ")
        assert line.split()[1] == word
        assert rc == _WORDS[word]
        assert spawned == []


def test_t04_empty_detail_still_leaves_a_parseable_verdict(tmp_path, monkeypatch):
    """A verdict WORD with no detail must still be readable: the word is the
    load-bearing token, so it may never be swallowed by an empty detail."""
    cfg_path, _repo = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _script_seam(monkeypatch, (True, 2, ""))
    rc, out, _err = _capture(lambda: foundry.leak_check_cli(cfg))
    line = _one_line(out)
    assert line.startswith("leak-guard: UNKNOWN"), line
    assert line.split()[1] == "UNKNOWN"
    assert rc == 2


def test_t05_json_mode_is_one_parseable_line_with_no_human_line(
        tmp_path, monkeypatch):
    """B7 over ALL FOUR verdicts (the spec names one scripted result): the whole
    of stdout must `json.loads`, carry the stable key set, agree with the pure
    verdict on BOTH channels, and NOT emit the human line."""
    keys = {"product", "ref", "verdict", "exit_code", "returncode", "detail"}
    for seam in [(False, None, "absent"), (True, 0, "clean"),
                 (True, 1, "1 finding"), (True, 2, "died\nmid-scan")]:
        cfg_path, _repo = _write_cfg(tmp_path)
        cfg = foundry.load_config(str(cfg_path))
        spawned = _script_seam(monkeypatch, seam)
        rc, out, _err = _capture(
            lambda: foundry.leak_check_cli(cfg, ref="deadbee", as_json=True))
        assert "leak-guard: " not in out, (
            "JSON mode must not also print the human line: two lines would "
            f"break the one-document contract; got {out!r}")
        doc = json.loads(out)  # the ENTIRE stdout, not a slice
        assert isinstance(doc, dict)
        assert keys <= set(doc), f"missing keys {keys - set(doc)}"
        word, code = foundry.leak_guard_verdict(seam[0], seam[1], seam[2])
        assert doc["verdict"] == word
        assert doc["exit_code"] == code
        assert rc == code, "the returned int must equal the published exit_code"
        assert doc["product"] == "demoprod"
        assert doc["ref"] == "deadbee", "the ref actually scanned must be echoed"
        assert len([ln for ln in out.splitlines() if ln.strip()]) == 1
        assert spawned == []


def test_t06_json_reaches_the_verdict_end_to_end_through_main(
        tmp_path, monkeypatch):
    """B8 without faking the CLI: `main` -> argparse -> `leak_check_cli` ->
    scripted seam, so the registered verb is proved to carry the real 0/1/2 code
    and the real document, not just to forward its arguments."""
    for seam, word, code in [((True, 1, "1 finding"), "LEAKED", 1),
                             ((True, 2, "cannot decide"), "UNKNOWN", 2),
                             ((True, 0, "ok"), "CLEAN", 0),
                             ((False, None, "none"), "ABSENT", 0)]:
        cfg_path, _repo = _write_cfg(tmp_path)
        spawned = _script_seam(monkeypatch, seam)
        rc, out, _err = _capture(lambda: foundry.main(
            ["leak-check", "--config", str(cfg_path), "--json"]))
        doc = json.loads(out)
        assert (doc["verdict"], doc["exit_code"]) == (word, code)
        assert rc == code, (
            f"main must return the fail-CLOSED code {code} for {word}, got {rc}")
        assert spawned == []
        # and the human channel through main, same inputs, same code
        rc2, out2, _e2 = _capture(lambda: foundry.main(
            ["leak-check", "--config", str(cfg_path)]))
        assert _one_line(out2).split()[1] == word
        assert rc2 == code


def test_t07_a_raising_seam_cannot_produce_clean_or_exit_zero(
        tmp_path, monkeypatch):
    """B6 widened: ANY seam explosion must land on UNKNOWN/2 in BOTH output
    modes. The dangerous failure is not the traceback, it is a swallowed error
    that reads CLEAN."""
    for exc in [RuntimeError("boom"), OSError("boom"), ValueError("boom"),
                UnicodeDecodeError("utf-8", b"\xff", 0, 1, "boom")]:
        cfg_path, _repo = _write_cfg(tmp_path)
        cfg = foundry.load_config(str(cfg_path))
        _script_seam(monkeypatch, exc)
        rc, out, _err = _capture(lambda: foundry.leak_check_cli(cfg))
        line = _one_line(out)
        assert line.split()[1] == "UNKNOWN", line
        assert rc == 2
        rcj, outj, _ej = _capture(
            lambda: foundry.leak_check_cli(cfg, as_json=True))
        docj = json.loads(outj)
        assert (docj["verdict"], docj["exit_code"]) == ("UNKNOWN", 2)
        assert rcj == 2


def test_t08_gate_card_keeps_both_channels_and_the_frozen_literal():
    """B10 read independently: the role card must name the VERB *and* keep the
    raw scanner path (iteration 52's brake) plus the 1/2 fail-CLOSED semantics,
    so replacing the invocation never deletes the fallback."""
    card = (_ROOT / "roles" / "final.md").read_text(encoding="utf-8")
    assert card.count("foundry.py leak-check") >= 2, (
        "both gate paragraphs (checklist item 6 and the pre-push ship bullet) "
        f"must name the verb; found {card.count('foundry.py leak-check')}")
    assert "scripts/leak_guard.py" in card, "iteration 52's brake literal"
    card.encode("ascii")  # pure ASCII -- raises UnicodeEncodeError otherwise
    assert "--config" in card, "the named invocation must be runnable as printed"


def test_t09_readme_documents_the_verb_once():
    """Acceptance criterion: ONE numbered README entry, so the verb is
    discoverable without reading the source."""
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")
    assert "leak-check" in readme


def test_t10_raising_seam_detail_quotes_the_exception_text_on_one_line(
        tmp_path, monkeypatch):
    """B6 has TWO halves and the second is the easy one to lose: the detail must
    MENTION the failure ("boom"), otherwise the gate is told only that something
    went wrong. Asserted together with the ONE-line contract under a MULTI-LINE
    exception message, the realistic shape (a traceback), because a detail that
    kept its newlines would emit verdict-less extra lines."""
    msg = "boom happened\nTraceback (most recent call last):\n  inner: boom"
    cfg_path, _repo = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _script_seam(monkeypatch, RuntimeError(msg))
    rc, out, _err = _capture(lambda: foundry.leak_check_cli(cfg))
    line = _one_line(out)  # exactly one non-empty line, newlines collapsed
    assert line.split()[1] == "UNKNOWN"
    assert "boom" in line, (
        f"the detail must mention the failure text, got {line!r}")
    assert rc == 2
    rcj, outj, _ej = _capture(lambda: foundry.leak_check_cli(cfg, as_json=True))
    doc = json.loads(outj)  # one parseable document, so the \n cannot split it
    assert doc["verdict"] == "UNKNOWN" and doc["exit_code"] == 2
    assert "boom" in doc["detail"]
    assert rcj == 2


def test_t11_returncode_field_is_reported_as_given_not_invented(
        tmp_path, monkeypatch):
    """B7 names `returncode` as a published key: it must carry what the SCAN
    actually returned (including `None` for "no code at all"), because the whole
    point of UNKNOWN is that the two absences stay distinguishable in the record
    even though both fail closed."""
    for seam in [(True, 2, "d"), (True, None, "d"), (False, None, "d"),
                 (True, 0, "d"), (True, 1, "d")]:
        cfg_path, _repo = _write_cfg(tmp_path)
        cfg = foundry.load_config(str(cfg_path))
        _script_seam(monkeypatch, seam)
        _rc, out, _err = _capture(
            lambda: foundry.leak_check_cli(cfg, as_json=True))
        doc = json.loads(out)
        assert doc["returncode"] == seam[1], (
            f"returncode must be echoed verbatim, got {doc['returncode']!r} "
            f"for seam {seam!r}")
