"""Black-box behaviour tests for iter 156 -- `foundry preship`, a LOCAL-clone
re-verification gate that runs in the commit-to-push window.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-156 PM spec's Expected
Behaviors 1-13, the conventions found under `tests/`, and the product's own
OBSERVABLE behaviour (importing the public names, reading their signatures,
scripting the documented module seams, and running the CLI). `foundry.py` /
`dispatcher.py` SOURCE was not read; neither the engineer's notes, the
reviewer's notes, the fix notes, nor any `git diff` was consulted.

Every test here is OFFLINE: no real subprocess, git, clone or network call is
made by any behaviour test (the only subprocess is the `import foundry,
dispatcher` importability probe of behavior 12, which is the spec's own
acceptance criterion).
"""

from __future__ import annotations

import dataclasses
import io
import contextlib
import itertools
import json
import pathlib
import subprocess
import sys
import types

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402
import dispatcher  # noqa: E402

THIS_ITER = 156
SHA = "b" * 40
OTHER_SHA = "c" * 40

NEW_SYMBOLS = ("preship_verdict", "verify_local_clone", "preship_cli",
               "PreshipResult", "PRESHIP_BUDGET_SECONDS", "preship_step_timeout")
FROZEN_POSTRELEASE = ("postrelease_verdict", "verify_fresh_clone", "postrelease_step")


# --------------------------------------------------------------------------
# helpers -- mirror the suite's existing conventions
# --------------------------------------------------------------------------
def _fn_names_consts(fn):
    """Compiled-bytecode introspection (co_names/co_consts), NOT source text --
    honors the tester isolation firewall (see tests/test_iter115_behavior.py)."""
    stack, seen = [fn.__code__], set()
    names, consts = set(), set()
    while stack:
        code = stack.pop()
        if id(code) in seen:
            continue
        seen.add(id(code))
        names |= set(code.co_names)
        for c in code.co_consts:
            if isinstance(c, str):
                consts.add(c)
            elif isinstance(c, types.CodeType):
                stack.append(c)
    return names, consts


def _cfg(tmp_path, **over):
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    work = tmp_path / "work"
    work.mkdir(parents=True, exist_ok=True)
    kw = dict(name="demo", repo=str(repo), allowed_push_repo="demo",
              work_root=str(work), test_cmd="uv run pytest", setup_cmd="uv sync")
    kw.update(over)
    return foundry.ProductConfig(**kw)


def _kind(argv):
    if "clone" in argv:
        return "clone"
    if "rev-parse" in argv:
        return "sha"
    if "sync" in argv:
        return "setup"
    return "test"


class _Harness:
    """Records every seam effect in call order (no real effect is performed)."""

    def __init__(self):
        self.calls = []    # one dict per run_cmd call
        self.events = []   # ("cleanup", path) / ("cmd", kind) in order

    @property
    def kinds(self):
        return [c["kind"] for c in self.calls]

    @property
    def argvs(self):
        return [c["argv"] for c in self.calls]

    def cleanups(self):
        return [e for e in self.events if e[0] == "cleanup"]


def _clock_steps(inc):
    """A `_monotonic` stand-in advancing `inc` seconds per reading."""
    box = {"n": 0}

    def f():
        v = box["n"] * float(inc)
        box["n"] += 1
        return v
    return f


def _install(monkeypatch, h, *, clone_ok=True, setup_ok=True, test_ok=True,
             clone_sha=SHA, raise_kind=None, clock=None, cleanup_raises=False):
    """Script the three documented seams by BARE module name (behavior 6)."""
    results = {"clone": clone_ok, "setup": setup_ok, "test": test_ok}

    def fake_run_cmd(args, cwd=None, timeout=None, **kw):
        argv = [str(a) for a in args]
        kind = _kind(argv)
        h.calls.append({"argv": argv, "cwd": cwd, "timeout": timeout, "kind": kind})
        h.events.append(("cmd", kind))
        if raise_kind is not None and kind == raise_kind:
            raise RuntimeError("boom-seam-xyz")
        if kind == "sha":
            return foundry.CmdResult(True, clone_sha + "\n")
        return foundry.CmdResult(bool(results.get(kind, True)), f"{kind} output")

    def fake_cleanup(clone_dir):
        h.events.append(("cleanup", str(clone_dir)))
        if cleanup_raises:
            raise RuntimeError("cleanup-boom")

    monkeypatch.setattr(foundry, "run_cmd", fake_run_cmd)
    monkeypatch.setattr(foundry, "cleanup_clone", fake_cleanup)
    monkeypatch.setattr(foundry, "_monotonic", clock or (lambda: 0.0))
    return h


def _verify(monkeypatch, tmp_path, **kw):
    h = _Harness()
    cfg = _cfg(tmp_path)
    _install(monkeypatch, h, **kw)
    res = foundry.verify_local_clone(cfg, SHA, tmp_path / "clone")
    return cfg, h, res


# ==========================================================================
# Behavior 1 -- preship_verdict is pure and total; the all-green case
# ==========================================================================
def test_b1_all_flags_true_is_verified() -> None:
    res = foundry.preship_verdict(
        clone_ok=True, setup_ok=True, test_ok=True, sha_ok=True, budget_exhausted=False
    )
    assert res.verified is True
    assert res.incomplete is False
    assert res.exit_code == 0
    assert res.sentinel == "PRESHIP: VERIFIED"


def test_b1_verdict_is_pure_and_total_over_every_flag_combo() -> None:
    """Total: all 32 combinations return a PreshipResult and never raise."""
    for combo in itertools.product((True, False), repeat=5):
        c, s, t, sh, be = combo
        res = foundry.preship_verdict(clone_ok=c, setup_ok=s, test_ok=t,
                                      sha_ok=sh, budget_exhausted=be)
        assert isinstance(res, foundry.PreshipResult), combo
        assert isinstance(res.detail, str) and res.detail.strip(), combo


def test_b1_verdict_is_deterministic_and_keyword_only() -> None:
    kw = dict(clone_ok=True, setup_ok=True, test_ok=False, sha_ok=True,
              budget_exhausted=False)
    assert foundry.preship_verdict(**kw) == foundry.preship_verdict(**kw)
    with pytest.raises(TypeError):
        foundry.preship_verdict(True, True, True, True, False)


# ==========================================================================
# Behavior 2 -- exit_code / sentinel are DERIVED properties, never fields
# ==========================================================================
def test_b2_result_is_frozen_dataclass_without_stored_verdict_fields() -> None:
    assert dataclasses.is_dataclass(foundry.PreshipResult)
    assert foundry.PreshipResult.__dataclass_params__.frozen is True
    names = [f.name for f in dataclasses.fields(foundry.PreshipResult)]
    assert "exit_code" not in names and "sentinel" not in names, names
    res = foundry.preship_verdict(clone_ok=True, setup_ok=True, test_ok=True,
                                  sha_ok=True, budget_exhausted=False)
    with pytest.raises(dataclasses.FrozenInstanceError):
        res.verified = False


def test_b2_exit_code_and_sentinel_are_properties_on_the_class() -> None:
    for name in ("exit_code", "sentinel"):
        assert isinstance(getattr(foundry.PreshipResult, name), property), name


def test_b2_derived_values_agree_with_flags_for_all_combos() -> None:
    table = {(True, False): (0, "PRESHIP: VERIFIED"),
             (False, True): (2, "PRESHIP: INCOMPLETE"),
             (False, False): (1, "PRESHIP: BROKEN")}
    for combo in itertools.product((True, False), repeat=5):
        c, s, t, sh, be = combo
        res = foundry.preship_verdict(clone_ok=c, setup_ok=s, test_ok=t,
                                      sha_ok=sh, budget_exhausted=be)
        assert not (res.verified and res.incomplete), combo
        code, sent = table[(bool(res.verified), bool(res.incomplete))]
        assert res.exit_code == code, (combo, res)
        assert res.sentinel == sent, (combo, res)


# ==========================================================================
# Behavior 3 -- a BOUNDARY failure is INCOMPLETE (exit 2), never BROKEN
# ==========================================================================
@pytest.mark.parametrize("flag,word", [("clone_ok", "clone"),
                                       ("setup_ok", "setup")])
def test_b3_boundary_failure_is_incomplete_exit_2(flag, word) -> None:
    kw = dict(clone_ok=True, setup_ok=True, test_ok=True, sha_ok=True,
              budget_exhausted=False)
    kw[flag] = False
    res = foundry.preship_verdict(**kw)
    assert res.incomplete is True
    assert res.verified is False
    assert res.exit_code == 2
    assert res.sentinel == "PRESHIP: INCOMPLETE"
    assert word in res.detail.lower(), res.detail


def test_b3_budget_exhausted_dominates_every_other_flag() -> None:
    res = foundry.preship_verdict(clone_ok=True, setup_ok=True, test_ok=True,
                                  sha_ok=True, budget_exhausted=True)
    assert (res.incomplete, res.verified, res.exit_code) == (True, False, 2)
    assert "budget" in res.detail.lower(), res.detail


def test_b3_boundary_dominates_a_red_suite() -> None:
    """clone/setup could not complete -> we cannot claim the tree is broken."""
    for flag in ("clone_ok", "setup_ok"):
        kw = dict(clone_ok=True, setup_ok=True, test_ok=False, sha_ok=False,
                  budget_exhausted=False)
        kw[flag] = False
        res = foundry.preship_verdict(**kw)
        assert res.exit_code == 2, (flag, res)


# ==========================================================================
# Behavior 4 -- a REAL SIGNAL is BROKEN (exit 1)
# ==========================================================================
def test_b4_red_suite_is_broken_exit_1() -> None:
    res = foundry.preship_verdict(clone_ok=True, setup_ok=True, test_ok=False,
                                  sha_ok=True, budget_exhausted=False)
    assert res.verified is False and res.incomplete is False
    assert res.exit_code == 1
    assert res.sentinel == "PRESHIP: BROKEN"
    low = res.detail.lower()
    assert "suite" in low or "test" in low, res.detail


def test_b4_sha_mismatch_with_green_suite_is_broken_exit_1() -> None:
    res = foundry.preship_verdict(clone_ok=True, setup_ok=True, test_ok=True,
                                  sha_ok=False, budget_exhausted=False)
    assert res.exit_code == 1
    assert res.incomplete is False
    assert "sha" in res.detail.lower(), res.detail


# ==========================================================================
# Behavior 5 -- clones the LOCAL path; issues NO network command
# ==========================================================================
def test_b5_clone_source_is_the_local_repo_path(monkeypatch, tmp_path) -> None:
    cfg, h, res = _verify(monkeypatch, tmp_path)
    clone_calls = [c for c in h.calls if c["kind"] == "clone"]
    assert len(clone_calls) == 1, h.argvs
    assert str(cfg.repo) in clone_calls[0]["argv"], clone_calls[0]["argv"]
    assert res.verified is True, res


def test_b5_no_network_command_is_ever_issued(monkeypatch, tmp_path) -> None:
    _, h, _ = _verify(monkeypatch, tmp_path)
    flat = [tok for argv in h.argvs for tok in argv]
    for banned in ("remote", "fetch", "push", "ls-remote"):
        assert banned not in flat, (banned, h.argvs)
    joined = " ".join(" ".join(a) for a in h.argvs)
    for scheme in ("https://", "git@", "ssh://"):
        assert scheme not in joined, (scheme, joined)


# ==========================================================================
# Behavior 6 -- every external effect goes through the three bare-name seams
# ==========================================================================
def test_b6_scripted_seams_drive_the_whole_verdict_offline(monkeypatch, tmp_path) -> None:
    """Only the script can produce this verdict, so no real effect ran."""
    _, h, res = _verify(monkeypatch, tmp_path, clone_sha=OTHER_SHA)
    assert res.exit_code == 1 and "sha" in res.detail.lower(), res
    assert h.kinds == ["clone", "setup", "test", "sha"], h.kinds


def test_b6_red_suite_from_the_script_is_broken(monkeypatch, tmp_path) -> None:
    _, h, res = _verify(monkeypatch, tmp_path, test_ok=False)
    assert res.exit_code == 1, res
    assert res.incomplete is False, res


@pytest.mark.parametrize("kind,flag", [("clone", "clone_ok"), ("setup", "setup_ok")])
def test_b6_boundary_step_short_circuits_to_incomplete(monkeypatch, tmp_path,
                                                       kind, flag) -> None:
    _, h, res = _verify(monkeypatch, tmp_path, **{flag: False})
    assert res.exit_code == 2, res
    assert h.kinds[-1] == kind, h.kinds
    assert "sha" not in h.kinds, h.kinds


def test_b6_test_seconds_is_measured_through_the_clock_seam(monkeypatch,
                                                            tmp_path) -> None:
    _, _, res = _verify(monkeypatch, tmp_path, clock=_clock_steps(1))
    assert res.test_seconds is not None
    assert res.test_seconds >= 0.0


# ==========================================================================
# Behavior 7 -- ONE budget knob, read at CALL time, enforced before each step
# ==========================================================================
def test_b7_budget_knob_is_a_module_level_float() -> None:
    assert isinstance(foundry.PRESHIP_BUDGET_SECONDS, float)
    assert foundry.PRESHIP_BUDGET_SECONDS > 0


def test_b7_within_budget_every_step_is_issued(monkeypatch, tmp_path) -> None:
    _, h, res = _verify(monkeypatch, tmp_path)
    assert h.kinds == ["clone", "setup", "test", "sha"], h.kinds
    assert res.exit_code == 0, res


def test_b7_past_budget_stops_issuing_and_returns_exit_2(monkeypatch,
                                                          tmp_path) -> None:
    """A clock jumping past the budget mid-run: later steps never issued."""
    monkeypatch.setattr(foundry, "PRESHIP_BUDGET_SECONDS", 240.0)
    _, h, res = _verify(monkeypatch, tmp_path, clock=_clock_steps(200))
    assert res.exit_code == 2, res
    assert res.incomplete is True and res.verified is False
    assert "budget" in res.detail.lower(), res.detail
    assert "sha" not in h.kinds, h.kinds
    assert len(h.calls) < 4, h.kinds


def test_b7_every_command_gets_an_explicit_timeout_inside_the_knob(monkeypatch,
                                                                   tmp_path) -> None:
    monkeypatch.setattr(foundry, "PRESHIP_BUDGET_SECONDS", 240.0)
    _, h, _ = _verify(monkeypatch, tmp_path)
    assert h.calls, "no command was issued"
    for c in h.calls:
        assert c["timeout"] is not None, c
        assert 0 <= c["timeout"] <= 240, c


def test_b7_knob_is_read_at_call_time_not_import_time(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(foundry, "PRESHIP_BUDGET_SECONDS", 12.0)
    _, h, _ = _verify(monkeypatch, tmp_path)
    assert h.calls
    for c in h.calls:
        assert c["timeout"] <= 12, c


def test_b7_step_timeout_never_exceeds_the_remaining_budget() -> None:
    for rem in (0.4, 0.9, 1.0, 5.4, 29.9, 240.0):
        t = foundry.preship_step_timeout(rem)
        assert isinstance(t, int), (rem, t)
        assert t <= rem, (rem, t)
        assert t >= 0, (rem, t)


# ==========================================================================
# Behavior 8 -- cleanup_clone before the clone AND on every exit path
# ==========================================================================
def test_b8_cleanup_runs_before_the_clone_and_after_a_verified_run(monkeypatch,
                                                                   tmp_path) -> None:
    _, h, res = _verify(monkeypatch, tmp_path)
    assert res.verified is True
    assert h.events[0][0] == "cleanup", h.events
    assert h.events[-1][0] == "cleanup", h.events
    assert len(h.cleanups()) >= 2, h.events


@pytest.mark.parametrize("kw", [
    {"test_ok": False},                       # BROKEN
    {"clone_ok": False},                      # INCOMPLETE (boundary)
    {"clock": "budget"},                      # INCOMPLETE (budget)
    {"raise_kind": "test"},                   # INCOMPLETE (seam exception)
])
def test_b8_cleanup_runs_on_every_exit_path(monkeypatch, tmp_path, kw) -> None:
    kw = dict(kw)
    if kw.get("clock") == "budget":
        monkeypatch.setattr(foundry, "PRESHIP_BUDGET_SECONDS", 240.0)
        kw["clock"] = _clock_steps(200)
    _, h, res = _verify(monkeypatch, tmp_path, **kw)
    assert h.events[0][0] == "cleanup", h.events
    assert h.events[-1][0] == "cleanup", h.events
    assert res.verified is False


def test_b8_raising_cleanup_never_changes_the_verdict_nor_propagates(monkeypatch,
                                                                     tmp_path) -> None:
    _, h, res = _verify(monkeypatch, tmp_path, cleanup_raises=True)
    assert res.verified is True, res
    assert res.exit_code == 0, res
    assert len(h.cleanups()) >= 2, h.events


def test_b8_raising_cleanup_preserves_a_broken_verdict(monkeypatch, tmp_path) -> None:
    _, _, res = _verify(monkeypatch, tmp_path, test_ok=False, cleanup_raises=True)
    assert res.exit_code == 1, res
    assert res.incomplete is False, res


# ==========================================================================
# Behavior 9 -- an unexpected seam exception is fail-SAFE (exit 2), not fail-open
# ==========================================================================
@pytest.mark.parametrize("kind", ["clone", "setup", "test", "sha"])
def test_b9_seam_exception_is_incomplete_exit_2_with_repr(monkeypatch, tmp_path,
                                                          kind) -> None:
    _, _, res = _verify(monkeypatch, tmp_path, raise_kind=kind)
    assert res.incomplete is True, (kind, res)
    assert res.verified is False, (kind, res)
    assert res.exit_code == 2, (kind, res)
    assert "boom-seam-xyz" in res.detail, res.detail
    assert "RuntimeError" in res.detail, res.detail


def test_b9_is_the_opposite_polarity_of_the_postrelease_reporter() -> None:
    """Regression guard: the post-release path keeps its OPTIMISTIC infra fold."""
    r = foundry.postrelease_verdict(remote_ok=False, clone_ok=True, setup_ok=True,
                                    test_ok=True, sha_ok=True, smoke_ran=False,
                                    smoke_ok=False)
    assert r.healthy is True, r
    assert r.skipped_infra is True, r


# ==========================================================================
# Behavior 10 -- `foundry preship --config <cfg>` (text form)
# ==========================================================================
def _cli(monkeypatch, tmp_path, *, as_json=False, head_ok=True, result=None):
    cfg = _cfg(tmp_path)
    seen = {"argvs": []}

    def fake_run_cmd(args, cwd=None, timeout=None, **kw):
        argv = [str(a) for a in args]
        seen["argvs"].append(argv)
        if "rev-parse" in argv:
            return foundry.CmdResult(head_ok, SHA + "\n" if head_ok else "fatal")
        return foundry.CmdResult(True, "")

    def fake_verify(cfg_, expected_sha, clone_dir):
        seen["cfg"] = cfg_
        seen["sha"] = expected_sha
        seen["dir"] = clone_dir
        return result

    monkeypatch.setattr(foundry, "run_cmd", fake_run_cmd)
    monkeypatch.setattr(foundry, "verify_local_clone", fake_verify)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = foundry.preship_cli(cfg, as_json=as_json)
    return cfg, seen, rc, buf.getvalue()


def _res(verified, incomplete, detail="d", secs=1.5):
    return foundry.PreshipResult(verified=verified, incomplete=incomplete,
                                 detail=detail, test_seconds=secs)


def test_b10_cli_resolves_head_itself_and_verifies_into_the_state_clone(monkeypatch,
                                                                        tmp_path) -> None:
    cfg, seen, rc, out = _cli(monkeypatch, tmp_path, result=_res(True, False))
    assert any("rev-parse" in a for a in seen["argvs"]), seen["argvs"]
    assert seen["sha"] == SHA, seen["sha"]
    assert str(seen["dir"]) == str(pathlib.Path(cfg.state) / "preship_clone"), seen["dir"]
    assert rc == 0
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert len(lines) > 1, out
    assert lines[-1] == "PRESHIP: VERIFIED", out


@pytest.mark.parametrize("verified,incomplete,code,sent", [
    (True, False, 0, "PRESHIP: VERIFIED"),
    (False, True, 2, "PRESHIP: INCOMPLETE"),
    (False, False, 1, "PRESHIP: BROKEN"),
])
def test_b10_cli_last_line_is_the_sentinel_and_rc_is_exit_code(monkeypatch, tmp_path,
                                                               verified, incomplete,
                                                               code, sent) -> None:
    _, _, rc, out = _cli(monkeypatch, tmp_path, result=_res(verified, incomplete))
    assert rc == code, out
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert lines[-1] == sent, out


def test_b10_failed_head_resolve_is_incomplete_and_never_clones(monkeypatch,
                                                                tmp_path) -> None:
    _, seen, rc, out = _cli(monkeypatch, tmp_path, head_ok=False,
                            result=_res(True, False))
    assert rc == 2, out
    assert "dir" not in seen, "verify_local_clone must not run without a sha"
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert lines[-1] == "PRESHIP: INCOMPLETE", out


def test_b10_verb_is_registered_in_the_cli_help(capsys) -> None:
    with pytest.raises(SystemExit) as ei:
        foundry.main(["--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "preship" in out, out


# ==========================================================================
# Behavior 11 -- `--json` form
# ==========================================================================
@pytest.mark.parametrize("verified,incomplete,code,sent", [
    (True, False, 0, "PRESHIP: VERIFIED"),
    (False, True, 2, "PRESHIP: INCOMPLETE"),
    (False, False, 1, "PRESHIP: BROKEN"),
])
def test_b11_json_form_carries_the_keys_and_the_same_exit_code(monkeypatch, tmp_path,
                                                               verified, incomplete,
                                                               code, sent) -> None:
    _, _, rc_txt, _ = _cli(monkeypatch, tmp_path, result=_res(verified, incomplete))
    _, _, rc, out = _cli(monkeypatch, tmp_path, as_json=True,
                         result=_res(verified, incomplete))
    doc = json.loads(out)
    assert isinstance(doc, dict)
    for k in ("verified", "incomplete", "exit_code", "detail", "sentinel",
              "test_seconds"):
        assert k in doc, (k, doc)
    assert doc["verified"] is verified and doc["incomplete"] is incomplete
    assert doc["exit_code"] == code and doc["sentinel"] == sent
    assert rc == code == rc_txt


def test_b11_json_carries_test_seconds_even_when_the_suite_never_ran(monkeypatch,
                                                                     tmp_path) -> None:
    """An INCOMPLETE run never measures the suite; the key must still be present."""
    _, _, rc, out = _cli(monkeypatch, tmp_path, as_json=True,
                         result=_res(False, True, secs=None))
    doc = json.loads(out)
    assert "test_seconds" in doc and doc["test_seconds"] is None, doc
    assert rc == 2 and doc["exit_code"] == 2, doc


def test_b11_json_output_is_exactly_one_document(monkeypatch, tmp_path) -> None:
    _, _, _, out = _cli(monkeypatch, tmp_path, as_json=True, result=_res(True, False))
    assert out.strip().startswith("{") and out.strip().endswith("}"), out
    assert out.count("PRESHIP:") == 1, out


# ==========================================================================
# Behavior 12 -- additive-dormant: OFF the control path, imports intact
# ==========================================================================
def test_b12_both_modules_still_import() -> None:
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=str(_ROOT), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_b12_control_path_never_references_the_new_symbols() -> None:
    for fn_name in ("run_iteration",) + FROZEN_POSTRELEASE:
        fn = getattr(foundry, fn_name)
        assert callable(fn), f"foundry.{fn_name} missing (regression)"
        names, consts = _fn_names_consts(fn)
        for sym in NEW_SYMBOLS:
            assert sym not in names, f"{fn_name} references {sym} -- must stay dormant"
        assert "preship" not in consts, f"{fn_name} carries a 'preship' literal"


def test_b12_dispatcher_never_references_the_new_symbols() -> None:
    names = set()
    for v in vars(dispatcher).values():
        if isinstance(v, types.FunctionType):
            names |= _fn_names_consts(v)[0]
        elif isinstance(v, type):
            for m in vars(v).values():
                if isinstance(m, types.FunctionType):
                    names |= _fn_names_consts(m)[0]
    for sym in NEW_SYMBOLS:
        assert sym not in names, f"dispatcher references {sym} -- must stay dormant"


def test_b12_postrelease_siblings_keep_their_signatures() -> None:
    import inspect
    assert list(inspect.signature(foundry.verify_fresh_clone).parameters) == \
        ["cfg", "expected_sha", "clone_dir"]
    assert list(inspect.signature(foundry.postrelease_step).parameters) == \
        ["cfg", "iteration", "expected_sha"]
    assert list(inspect.signature(foundry.postrelease_verdict).parameters) == \
        ["remote_ok", "clone_ok", "setup_ok", "test_ok", "sha_ok",
         "smoke_ran", "smoke_ok"]
    assert [f.name for f in dataclasses.fields(foundry.PostReleaseResult)] == \
        ["healthy", "skipped_infra", "detail", "test_seconds"]


def test_b12_runtime_clone_dir_is_git_ignored() -> None:
    r = subprocess.run(["git", "check-ignore", "-v",
                        "products/_platform/state/preship_clone"],
                       cwd=str(_ROOT), capture_output=True, text=True)
    assert r.returncode == 0, f"clone dir NOT git-ignored: {r.stdout}{r.stderr}"
    assert "state" in r.stdout, r.stdout


# ==========================================================================
# Behavior 13 -- exactly ONE new checklist item in roles/final.md
# ==========================================================================
def _final_card_text():
    p = _ROOT / "roles" / "final.md"
    assert p.is_file(), p
    return p.read_text()


def test_b13_final_card_gains_exactly_one_preship_checklist_item() -> None:
    text = _final_card_text()
    items = [ln for ln in text.splitlines()
             if ln.lstrip().startswith("-") and "preship" in ln.lower()]
    assert len(items) == 1, items


def test_b13_item_gives_a_cwd_independent_invocation() -> None:
    line = [ln for ln in _final_card_text().splitlines()
            if ln.lstrip().startswith("-") and "preship" in ln.lower()][0]
    assert "python3" in line, line
    assert "foundry.py preship --config" in line, line
    assert "config.json" in line, line
    assert "roles/" in line or "`roles`" in line, line
    assert "state dir" in line, line


def test_b13_item_states_the_asymmetric_rule() -> None:
    line = [ln for ln in _final_card_text().splitlines()
            if ln.lstrip().startswith("-") and "preship" in ln.lower()][0]
    low = line.lower()
    assert "blocking" in low, line
    assert "not a gate failure" in low, line
    assert "PRESHIP: BROKEN" in line and "PRESHIP: INCOMPLETE" in line, line


def test_b13_no_other_role_card_mentions_preship() -> None:
    others = []
    for p in sorted((_ROOT / "roles").glob("*.md")):
        if p.name == "final.md":
            continue
        if "preship" in p.read_text().lower():
            others.append(p.name)
    assert others == [], others
