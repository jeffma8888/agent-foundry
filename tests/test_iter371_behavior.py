"""Iteration 371 -- BLACK-BOX behavior tests: `foundry stop` is the WRITE half of the
STOP contract, and every sentinel it writes must round-trip through the reader that
shipped 168 iterations earlier.

Spec under test: products/_platform/state/iter-371/pm.md ("Two additive CLI verbs ...
that write and lift a STOP sentinel whose reason round-trips through the already-shipped
reader"), read together with the iteration-371 rows the PM wrote into the roadmap index
and archive, which cut the LIFT half explicitly ("A `resume` verb is recorded as the
follow-on bite") and enumerate the write half's rules.  The spec's own `## Expected
Behaviors` section was left at the placeholder `(refining)` -- its PM stage was cut
short -- so the behaviors below are derived from the Feature line, the roadmap rows and
the verb's OWN documented `--help` contract, all of which this stage may read.

  1. `stop` is a reachable CLI verb whose target can never be acquired by omission:
     `--config` / `--global` is a REQUIRED mutually-exclusive group, `--reason` is
     required, and a rejected invocation writes NOTHING.
  2. Team scope writes `<work_root>/STOP` -- the exact path the dispatcher checks --
     and the reason round-trips VERBATIM back through the shipped reader (`gather_stop`
     and the `company-stops` report).
  3. A blank reason is REFUSED and never written -- including with `--force` over an
     existing sentinel, which must not be truncated by a write that then fails.
  4. An existing sentinel is REFUSED without `--force` and its text is preserved
     VERBATIM (it may hold a reactivation condition), and the verdict quotes the
     EXISTING reason, not the rejected new one.
  5. `--force` replaces an existing sentinel.
  6. The written text is ONE line of at most `STOP_REASON_MAX_CHARS`, and is a FIXPOINT
     of the shipped reader over a hostile table (leading blank line, CRLF, tabs, a cut
     that lands on a space, 400 chars, unicode).
  7. `--json` emits exactly ONE machine-readable verdict document whose `exit_code`
     agrees with the process exit code and with the human arm's.
  8. `--global` writes `<foundry>/STOP`, the sentinel the dispatcher checks before
     every shift -- exercised ONLY against a patched root, and proved to leave the real
     company sentinel byte-unchanged.
  9. Acceptance: `import foundry, dispatcher` clean, the READ half still behaves as it
     did, README documents the new verb, and the roadmap ledger records iteration 371.

ISOLATION CONTRACT (HONORED): every assertion below was derived ONLY from the iter-371
PM spec, the product README / roadmap / archive TEXT, the pre-existing conventions under
`tests/`, and the product's OWN observable behavior by importing and CALLING its public
names and by reading its `--help` output.  The implementation SOURCE of `foundry.py` /
`dispatcher.py` was NOT read, nor the engineer's notes, the reviewer's notes, the fix
notes, `IMPLEMENTATION.patch`, or any `git diff`.

FLEET SAFETY (the one footgun in this verb): the `--global` arm resolves its target from
`foundry.FOUNDRY` at CALL time, and that is the same sentinel the live dispatcher checks
before every shift -- so an unpatched global call would be a GREEN test that halts every
team.  Behavior 8 therefore patches `foundry.FOUNDRY` into `tmp_path` before it calls
anything, and then asserts the real company sentinel's existence AND bytes are unchanged
by the test.  No other test in this module touches global scope.

FRESH-CLONE SAFE / OFFLINE: every sentinel, product config and dispatch config used
below is built inside `tmp_path`; nothing gitignored (`products/*/STOP`,
`products/*/state`, the repo-root `STOP`) is asserted to exist or not exist, and no
absolute machine path is written into this file.  No subprocess, no git, no network.
"""
from __future__ import annotations

import io
import json
import pathlib
import re
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  -- in-process import-safety probe (the quality bar)

THIS_ITER = 371
SENTINEL_NAME = "STOP"


# ---------------------------------------------------------------- helpers


def _capture(fn):
    """Run fn() with stdout/stderr captured SEPARATELY; return (rc, out, err).

    A SystemExit (argparse's own failure path) is caught and its code returned, so the
    CLI contract can be asserted without leaking a half-restored stdout.
    """
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        try:
            rc = fn()
        except SystemExit as exc:  # argparse
            rc = exc.code if isinstance(exc.code, int) else 2
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue(), err.getvalue()


def _product_config(tmp_path: pathlib.Path, name: str, *, make_work_root: bool = True):
    """Write a throwaway PRODUCT config in tmp_path; return (config_path, work_root).

    Nothing here points at a live product: the work_root is inside tmp_path, so the
    sentinel this verb writes can only ever land in the test's own directory.
    """
    work_root = tmp_path / name
    if make_work_root:
        work_root.mkdir(parents=True, exist_ok=True)
    config_path = tmp_path / (name + ".json")
    config_path.write_text(
        json.dumps(
            {
                "name": name,
                "repo": str(tmp_path / "repo"),
                "allowed_push_repo": "none",
                "branch": "main",
                "vision": str(tmp_path / "VISION.md"),
                "roadmap": str(tmp_path / "ROADMAP.md"),
                "quality_ref": str(tmp_path / "repo"),
                "test_cmd": "true",
                "roles_dir": str(_ROOT / "roles"),
                "work_root": str(work_root),
                "quality_bar": "throwaway fixture",
                "push_enabled": False,
            },
            indent=2,
        )
    )
    return config_path, work_root


def _stop(config_path, reason, *args):
    """Drive the verb through the real CLI entry point; return (rc, out, err)."""
    argv = ["stop", "--config", str(config_path), "--reason", reason, *args]
    return _capture(lambda: foundry.main(argv))


def _sentinel_text(work_root: pathlib.Path) -> str | None:
    path = work_root / SENTINEL_NAME
    return path.read_text() if path.exists() else None


def _max_chars() -> int:
    """Read the cap at CALL time, so narrowing the constant narrows this test too."""
    cap = foundry.STOP_REASON_MAX_CHARS
    assert isinstance(cap, int) and cap > 0, cap
    return cap


# ------------------------------------------------- 1. the verb and its target


def test_behavior1_stop_is_a_cli_verb_whose_target_is_never_acquired_by_omission(tmp_path):
    rc, out, err = _capture(lambda: foundry.main(["--help"]))
    assert rc == 0, (rc, err)
    # The BARE verb token, not merely the substring: `company-stops` shipped 168
    # iterations earlier and contains "stop", so a substring check is vacuous here.
    assert re.search(r"[,{]stop[,}]", out.replace(" ", "").replace("\n", "")), out[:600]

    rc, out, err = _capture(lambda: foundry.main(["stop", "--help"]))
    assert rc == 0, (rc, err)
    for flag in ("--config", "--global", "--reason", "--force", "--json"):
        assert flag in out, (flag, out[:800])

    config_path, work_root = _product_config(tmp_path, "omission")

    # No target at all, both targets, and no reason: each is a hard usage error (2),
    # and -- the assertion that matters -- NOTHING is written by a rejected call.
    rejected = (
        ["stop", "--reason", "no target given"],
        ["stop", "--config", str(config_path), "--global", "--reason", "two targets"],
        ["stop", "--config", str(config_path)],
    )
    for argv in rejected:
        rc, out, err = _capture(lambda argv=argv: foundry.main(argv))
        assert rc == 2, (argv, rc, out, err)
        assert _sentinel_text(work_root) is None, (argv, _sentinel_text(work_root))


# ------------------------------------------- 2. team scope + reader round-trip


def test_behavior2_team_scope_writes_the_dispatchers_path_and_round_trips(tmp_path):
    config_path, work_root = _product_config(tmp_path, "roundtrip")
    cfg = foundry.load_config(str(config_path))
    reason = "paused for a release audit; resume once the audit closes"

    rc, out, err = _stop(config_path, reason)
    assert rc == 0, (rc, out, err)
    assert "WROTE" in out, out

    # The writer writes exactly where the config -- and therefore the dispatcher's
    # `cfg.stop_file.exists()` check -- looks for it.
    assert pathlib.Path(str(cfg.stop_file)) == work_root / SENTINEL_NAME
    assert _sentinel_text(work_root) == reason + "\n"

    # ... and the SHIPPED reader renders that reason verbatim, both as a row object
    # and through the company report a human actually reads.
    row = foundry.gather_stop(cfg)
    assert (row.stopped, row.scope, row.reason) == (True, "team", reason), row

    dispatch_path = tmp_path / "dispatch.json"
    dispatch_path.write_text(
        json.dumps(
            {"work_items": [{"name": "roundtrip", "config": str(config_path),
                             "priority": 0, "enabled": True}]}
        )
    )
    rc, out, err = _capture(
        lambda: foundry.main(["company-stops", "--config", str(dispatch_path)])
    )
    assert reason in out, out
    assert "roundtrip" in out, out

    # A work_root that does not exist yet is CREATED rather than crashed on: an
    # operator retiring a team must not have to mkdir first.
    fresh_config, fresh_root = _product_config(tmp_path, "notyet", make_work_root=False)
    assert not fresh_root.exists()
    rc, out, err = _stop(fresh_config, "retired before its first shift")
    assert rc == 0, (rc, out, err)
    assert _sentinel_text(fresh_root) == "retired before its first shift\n"


# ------------------------------------------------------- 3. a blank reason


def test_behavior3_a_blank_reason_is_refused_and_never_written(tmp_path):
    for index, blank in enumerate(("", "   ", " \t ", "\n\n\n", "\r\n")):
        config_path, work_root = _product_config(tmp_path, "blank%d" % index)
        rc, out, err = _stop(config_path, blank)
        assert rc == 2, (repr(blank), rc, out, err)
        assert "FAILED" in out, (repr(blank), out)
        assert _sentinel_text(work_root) is None, (repr(blank), _sentinel_text(work_root))

    # The dangerous shape: --force over an EXISTING sentinel. A writer that opened the
    # file before validating would truncate a reactivation condition and THEN fail.
    config_path, work_root = _product_config(tmp_path, "blankforce")
    preserved = "stopped by hand\nlift when the audit closes\nowner: whoever reads this\n"
    (work_root / SENTINEL_NAME).write_text(preserved)
    rc, out, err = _stop(config_path, "   ", "--force")
    assert rc == 2, (rc, out, err)
    assert _sentinel_text(work_root) == preserved, _sentinel_text(work_root)

    # The blank verdict names the blank-reason rule in the product's own words.
    rc, out, err = _stop(config_path, "", "--json")
    assert rc == 2, (rc, out, err)
    doc = json.loads(out)
    assert doc["action"] == "FAILED", doc
    assert doc["error"] == foundry.STOP_BLANK_REASON_ERROR, doc
    assert _sentinel_text(work_root) == preserved, _sentinel_text(work_root)


# ------------------------------------------ 4. an existing sentinel is fail-SAFE


def test_behavior4_an_existing_sentinel_is_refused_and_preserved_verbatim(tmp_path):
    config_path, work_root = _product_config(tmp_path, "handwritten")
    cfg = foundry.load_config(str(config_path))
    preserved = "retired 2026-01-01\nlift only after the owner signs off\ntrailing note\n"
    (work_root / SENTINEL_NAME).write_text(preserved)

    rc, out, err = _stop(config_path, "a DIFFERENT reason that must not land")
    assert rc == 1, (rc, out, err)
    assert "REFUSED" in out, out
    assert _sentinel_text(work_root) == preserved, _sentinel_text(work_root)
    assert "a DIFFERENT reason that must not land" not in _sentinel_text(work_root)

    # The verdict quotes the reason that SURVIVED, so an operator reading the refusal
    # sees what is actually on disk rather than what they just tried to write.
    rc, out, err = _stop(config_path, "another rejected reason", "--json")
    assert rc == 1, (rc, out, err)
    doc = json.loads(out)
    assert doc["action"] == "REFUSED", doc
    assert (doc["existed"], doc["forced"]) == (True, False), doc
    assert doc["reason"] == "retired 2026-01-01", doc

    # The reader is likewise unaffected by the refused write.
    assert foundry.gather_stop(cfg).reason == "retired 2026-01-01"


# ------------------------------------------------------------- 5. --force


def test_behavior5_force_replaces_an_existing_sentinel(tmp_path):
    config_path, work_root = _product_config(tmp_path, "forced")
    cfg = foundry.load_config(str(config_path))
    (work_root / SENTINEL_NAME).write_text("an older reason\n")

    rc, out, err = _stop(config_path, "replaced on purpose", "--force", "--json")
    assert rc == 0, (rc, out, err)
    doc = json.loads(out)
    assert doc["action"] == "WROTE", doc
    assert (doc["existed"], doc["forced"]) == (True, True), doc
    assert _sentinel_text(work_root) == "replaced on purpose\n"
    assert foundry.gather_stop(cfg).reason == "replaced on purpose"


# ------------------------------- 6. one bounded line, a fixpoint of the reader


def test_behavior6_written_text_is_one_bounded_line_and_a_reader_fixpoint(tmp_path):
    cap = _max_chars()
    hostile = {
        "plain": "paused for an audit",
        "leading_blank": "\n\nlift when the audit closes",
        "crlf": "first line of the reason\r\nsecond line",
        "tabs": "held\tby\tops",
        "cut_on_space": ("a" * (cap - 1)) + " tail beyond the cap",
        "overlong": "b" * (cap * 3),
        "unicode": "held \u2014 lift after r\u00e9view \u6682\u505c",
        "unicode_overlong": "\u4e00" * (cap * 3),
        "trailing_ws": "  spaced out   \n",
    }
    for label, reason in hostile.items():
        config_path, work_root = _product_config(tmp_path, "hostile_" + label)
        cfg = foundry.load_config(str(config_path))
        rc, out, err = _stop(config_path, reason)
        assert rc == 0, (label, rc, out, err)

        text = _sentinel_text(work_root)
        assert text is not None, label
        line = text[:-1] if text.endswith("\n") else text

        # ONE line, bounded, no trailing whitespace (a cut can land ON a space).
        assert text.endswith("\n"), (label, repr(text))
        assert text.count("\n") == 1, (label, repr(text))
        assert "\r" not in text, (label, repr(text))
        assert len(line) <= cap, (label, len(line))
        assert line == line.rstrip(), (label, repr(text))
        # Non-vacuity: a reason with leading blank lines must NOT collapse to nothing.
        assert line.strip(), (label, repr(text))

        # FIXPOINT: feeding the written bytes back through the SHIPPED reader returns
        # exactly the line on disk, and the fleet report cannot misread it.
        assert foundry.stop_reason(text) == line, (label, repr(text))
        assert foundry.render_stop_text(line) == text, (label, repr(text))
        assert foundry.gather_stop(cfg).reason == line, (label, repr(text))
        # The human verdict quotes the same bytes it wrote.
        assert line in out, (label, out)

    # The two shapes with a definite expected VALUE, spelled out rather than inferred.
    _, blank_first = _product_config(tmp_path, "leading_blank_value")
    rc, out, err = _stop(tmp_path / "leading_blank_value.json", "\n\nlate content wins")
    assert rc == 0, (rc, out, err)
    assert _sentinel_text(blank_first) == "late content wins\n"

    _, capped = _product_config(tmp_path, "capped_value")
    rc, out, err = _stop(tmp_path / "capped_value.json", "c" * (cap + 40))
    assert rc == 0, (rc, out, err)
    assert _sentinel_text(capped) == ("c" * cap) + "\n"


# ------------------------------------------------------------- 7. --json


def test_behavior7_json_arm_is_one_document_agreeing_with_the_human_arm(tmp_path):
    situations = {
        "WROTE": ("clean write", ()),
        "REFUSED": ("rejected write", ()),
        "FAILED": ("   ", ()),
    }
    for expected_action, (reason, extra) in situations.items():
        human_cfg, human_root = _product_config(tmp_path, "human_" + expected_action)
        json_cfg, json_root = _product_config(tmp_path, "json_" + expected_action)
        if expected_action == "REFUSED":
            for root in (human_root, json_root):
                (root / SENTINEL_NAME).write_text("an earlier reason\n")

        human_rc, human_out, _ = _stop(human_cfg, reason, *extra)
        json_rc, json_out, _ = _stop(json_cfg, reason, *extra, "--json")

        # Same situation -> same exit code on both arms.
        assert human_rc == json_rc, (expected_action, human_rc, json_rc)
        assert not human_out.lstrip().startswith("{"), (expected_action, human_out)

        doc = json.loads(json_out)  # exactly ONE document, or this raises
        assert doc["action"] == expected_action, (expected_action, doc)
        assert doc["action"] in foundry.STOP_WRITE_ACTIONS, doc
        assert set(doc) >= {"action", "scope", "sentinel", "reason", "existed",
                            "forced", "error", "exit_code"}, sorted(doc)
        assert doc["exit_code"] == json_rc, (expected_action, doc, json_rc)
        assert doc["scope"] == "team", doc
        assert pathlib.Path(doc["sentinel"]) == json_root / SENTINEL_NAME, doc


# --------------------------------- 8. --global, exercised only on a patched root


def test_behavior8_global_scope_writes_the_company_sentinel_fleet_safely(tmp_path, monkeypatch):
    real_root = foundry.FOUNDRY
    real_sentinel = pathlib.Path(str(real_root)) / SENTINEL_NAME
    before = (real_sentinel.exists(),
              real_sentinel.read_bytes() if real_sentinel.exists() else None)

    # The company sentinel the WRITER targets is the one the DISPATCHER checks.
    assert dispatcher.STOP_FILE.name == SENTINEL_NAME
    assert pathlib.Path(str(dispatcher.STOP_FILE)) == real_sentinel

    # Patch FIRST: every call below must land in tmp_path, never in the live repo.
    monkeypatch.setattr(foundry, "FOUNDRY", tmp_path)
    assert pathlib.Path(str(foundry.FOUNDRY)) == tmp_path

    rc, out, err = _capture(
        lambda: foundry.main(["stop", "--global", "--reason", "company-wide freeze",
                              "--json"])
    )
    assert rc == 0, (rc, out, err)
    doc = json.loads(out)
    assert doc["action"] == "WROTE", doc
    assert doc["scope"] == "global", doc
    assert pathlib.Path(doc["sentinel"]) == tmp_path / SENTINEL_NAME, doc
    assert (tmp_path / SENTINEL_NAME).read_text() == "company-wide freeze\n"
    assert foundry.global_stop() is True

    # Same fail-safe rules in company scope: refused without --force, replaced with it,
    # and a blank reason never written.
    rc, out, err = _capture(
        lambda: foundry.main(["stop", "--global", "--reason", "second attempt"])
    )
    assert rc == 1, (rc, out, err)
    assert (tmp_path / SENTINEL_NAME).read_text() == "company-wide freeze\n"

    rc, out, err = _capture(
        lambda: foundry.main(["stop", "--global", "--reason", " \t ", "--force"])
    )
    assert rc == 2, (rc, out, err)
    assert (tmp_path / SENTINEL_NAME).read_text() == "company-wide freeze\n"

    rc, out, err = _capture(
        lambda: foundry.main(["stop", "--global", "--reason", "lifted then re-set",
                              "--force"])
    )
    assert rc == 0, (rc, out, err)
    assert (tmp_path / SENTINEL_NAME).read_text() == "lifted then re-set\n"

    # THE ASSERTION THIS WHOLE TEST EXISTS FOR: the live company sentinel was not
    # created, deleted or rewritten by any of the above.
    after = (real_sentinel.exists(),
             real_sentinel.read_bytes() if real_sentinel.exists() else None)
    assert after == before, (before[0], after[0])


# ------------------------------------------------------- 9. acceptance criteria


def test_behavior9_acceptance_imports_read_half_docs_and_roadmap_ledger():
    # `import foundry, dispatcher` clean -- both are imported at module level above.
    assert callable(foundry.main)
    assert hasattr(dispatcher, "STOP_FILE")

    # The READ half that shipped at iteration 203 still behaves as it did: the writer
    # was additive, so these are byte-for-byte regression pins, not new behavior.
    assert foundry.stop_reason(None) == ""
    assert foundry.stop_reason("") == ""
    assert foundry.stop_reason("only line\n") == "only line"
    assert foundry.stop_reason("first\nsecond\n") == "first"
    assert isinstance(foundry.global_stop(), bool)

    # README documents the verb (its own index brake requires the section; this pins
    # the operator-facing invocation, which is what a human copies).
    readme = (_ROOT / "README.md").read_text()
    assert "foundry.py stop --config" in readme
    assert "--global" in readme

    # Roadmap ledger: an index row and an archive detail bullet for this iteration.
    index = (_ROOT / "PLATFORM_ROADMAP.md").read_text()
    archive = (_ROOT / "PLATFORM_ROADMAP_ARCHIVE.md").read_text()
    row = "iter %d" % THIS_ITER
    assert row in index, row
    assert row in archive, row


# --------------------------------------------- 10. the LIFT half is NOT here yet

def test_behavior10_the_lift_half_is_recorded_as_the_follow_on_bite():
    """The spec's Feature line names TWO verbs (`stop` and `resume`); the roadmap rows
    the same PM wrote cut the lift half explicitly.  This test pins the CUT so the gap
    is visible and a later `resume` bite has a red to turn green: it asserts the
    RECORD, and deliberately does not assert that `resume` is absent -- adding the verb
    must not red this module.
    """
    archive = (_ROOT / "PLATFORM_ROADMAP_ARCHIVE.md").read_text()
    row = [line for line in archive.splitlines() if ("iter %d" % THIS_ITER) in line]
    assert row, "no iteration-%d archive bullet" % THIS_ITER
    assert "resume" in row[0], row[0][:200]
