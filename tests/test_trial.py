"""Behavior pins for `trial.py`, the offline fixed-task arm adapter for bench.py.

Every agent here is a short scripted spy (a Python file the test writes), passed as
explicit argv. No model is called. Tripwires make any revert/iteration/release
seam, or an agent spawn on an invalid input, fail the test.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import bench  # noqa: E402
import foundry  # noqa: E402
import trial  # noqa: E402

TASK = "# Fixed task\n\nMake `calc.add(a, b)` return a + b.\n\u00e9\u2014\u4e2d\n\ttab\t\n".encode()
BUDGET = 60
TRIPWIRES = ("revert_repo", "run_iteration", "run_execution_plan", "head_of_branch",
             "postrelease_step", "git", "capture_abort_patch")

SPY = r'''
import hashlib, json, os, pathlib, re, sys
prompt = sys.argv[-1]
grab = lambda rx: re.search(rx, prompt).group(1).strip()
stage = grab(r"You are the (\S+) in iteration")
out = pathlib.Path(grab(r"YOUR REQUIRED OUTPUT FILE: (.+?) -- you MUST"))
state = pathlib.Path(grab(r"- This iteration's state dir \(all stage outputs live here\): (.+)\n"))
rec = {"stage": stage, "argv0": sys.argv[0], "argc": len(sys.argv), "cwd": os.getcwd(),
       "prompt_sha": hashlib.sha256(prompt.encode()).hexdigest(), "out": str(out),
       "task_sha": hashlib.sha256((state / "pm.md").read_bytes()).hexdigest()}
with open(os.environ["TRIAL_SPY_LOG"], "a") as f:
    f.write(json.dumps(rec) + "\n")
if os.environ.get("TRIAL_SPY_SILENT") == stage:
    sys.exit(0)
if stage == "ENGINEER" and pathlib.Path("calc.py").exists():
    p = pathlib.Path("calc.py"); p.write_text(p.read_text().replace("a - b", "a + b"))
body = f"VERDICT: {os.environ.get('TRIAL_SPY_VERDICT', 'APPROVE')}\n" if stage == "REVIEWER" else stage + " done\n"
out.write_text(body)
'''

ENTRY = r'''
import sys
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
import foundry, trial
def trip(*a, **k):
    raise SystemExit("TRIPWIRE")
for n in %r:
    setattr(foundry, n, trip)
foundry.global_stop = lambda: False
sys.exit(trial.main(sys.argv[2:]))
''' % (TRIPWIRES,)


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Owned fixture dirs, spy argv, tripwires, and every foundry global restored."""
    for name in ("AGENT_BIN", "AGENT_RUN_ARGS", "MAX_ATTEMPTS", "STAGE_TIMEOUT",
                 "AUTH_HOLD_SECONDS", "resolve_agent_endpoint", "product_config_path"):
        monkeypatch.setattr(foundry, name, getattr(foundry, name))
    hits: list[str] = []
    for n in TRIPWIRES:
        monkeypatch.setattr(foundry, n, lambda *a, _n=n, **k: hits.append(_n) or (_ for _ in ()).throw(AssertionError(_n)))
    monkeypatch.setattr(foundry, "global_stop", lambda: False)
    monkeypatch.setenv("FOUNDRY_AGENT_BIN", str(tmp_path / "ambient-agent-must-not-run"))
    monkeypatch.setenv("FOUNDRY_AGENT_ARGS", '["{prompt}"]')
    spy = tmp_path / "spy.py"
    spy.write_text(SPY)
    log = tmp_path / "spy.jsonl"
    monkeypatch.setenv("TRIAL_SPY_LOG", str(log))
    spec = tmp_path / "spec.md"
    spec.write_bytes(TASK)
    monkeypatch.setenv("BENCH_SPEC", str(spec))
    monkeypatch.setenv("BENCH_BUDGET_S", str(BUDGET))
    fx = tmp_path / "fixture"
    fx.mkdir()
    (fx / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    (fx / "test_calc.py").write_text("import unittest\nfrom calc import add\n\n"
                                     "class T(unittest.TestCase):\n    def test_add(self):\n"
                                     "        self.assertEqual(add(2, 3), 5)\n")

    class E:
        pass
    e = E()
    e.tmp, e.spy, e.log, e.spec, e.fx, e.hits, e.mp = tmp_path, spy, log, spec, fx, hits, monkeypatch
    e.argv = [sys.executable, str(spy), "{prompt}"]
    e.calls = lambda: [json.loads(x) for x in log.read_text().splitlines()] if log.exists() else []
    return e


def _run_arm(e, arm, *, argv=None):
    repo = e.tmp / f"{arm}-repo"
    shutil.copytree(e.fx, repo)
    state = e.tmp / f"{arm}-state"
    e.mp.chdir(repo)
    code = trial.main(["arm", "--arm", arm, "--state-root", str(state),
                       "--agent-argv-json", json.dumps(e.argv if argv is None else argv)])
    e.mp.chdir(e.tmp)
    return code, repo, state


def _engineer_prompts(env):
    """Plan, then run, both arms. Pins task bytes, plan-vs-execution prompt hashes, spy
    argv/cwd, stage lists and tripwires; returns {arm: (repo, state, sent prompt)}."""
    plans, runs = {}, {}
    for arm in trial.ARMS:
        repo, state = env.tmp / f"{arm}-repo", env.tmp / f"{arm}-state"
        repo.mkdir()
        plans[arm] = trial.plan_arm(arm, str(repo), str(state), TASK, BUDGET)
        assert plans[arm]["executed"] is False and not state.exists()
        assert plans[arm]["name"] == trial.arm_name(arm)
        repo.rmdir()
        before = len(env.calls())
        code, repo, state = _run_arm(env, arm)
        assert code == 0
        runs[arm] = (repo, state, env.calls()[before:])
    for arm, (repo, state, calls) in runs.items():
        assert (state / "state" / "iter-01" / "pm.md").read_bytes() == TASK
        assert all(c["task_sha"] == _sha(TASK) for c in calls)
        sent = (state / "state" / "iter-01" / "engineer.attempt1.prompt").read_bytes()
        assert _sha(sent) == calls[0]["prompt_sha"] == plans[arm]["stages"][0]["attempt1_prompt_sha"]
        assert all(c["cwd"] == str(repo) and c["argv0"] == str(env.spy) and c["argc"] == 2 for c in calls)
    assert [c["stage"] for c in runs["baseline"][2]] == ["ENGINEER"]
    assert [c["stage"] for c in runs["candidate"][2]] == ["ENGINEER", "REVIEWER"]  # APPROVE: no fix
    assert env.hits == []
    return {a: (r[0], r[1], (r[1] / "state" / "iter-01" / "engineer.attempt1.prompt").read_text())
            for a, r in runs.items()}


def _arm_neutral(prompt: str, arm: str, repo: pathlib.Path, state: pathlib.Path) -> str:
    """Blank ONLY this arm's own fields: the declared product-name field and the exact
    repo and state-root paths. A whole-prompt `replace(arm, ...)` also rewrote the shared
    roles path whenever the checkout path held an arm word, and would hide a real arm
    word planted in common text; both stay visible here."""
    field = f"the product '{trial.arm_name(arm)}'.\n"
    assert prompt.count(field) == 1, field
    out = prompt.replace(field, "the product '<NAME>'.\n")
    for path, tag in ((str(state), "<STATE>"), (str(repo), "<REPO>")):
        assert path in out, tag
        out = out.replace(path, tag)
    return out


def _neutral(arms: dict) -> dict:
    return {a: _arm_neutral(p, a, repo, state) for a, (repo, state, p) in arms.items()}


def _checkout_named(env, name: str) -> str:
    """Point foundry.FOUNDRY at a real dir (not a symlink: roles_dir is resolve()d) named
    `name` holding a copy of the shared roles; returns the shared role-file prompt line."""
    fake = env.tmp / "checkouts" / name
    shutil.copytree(pathlib.Path(foundry.FOUNDRY).resolve() / "roles", fake / "roles")
    env.mp.setattr(foundry, "FOUNDRY", fake)
    return f"READ AND FOLLOW EXACTLY: {fake.resolve() / 'roles' / 'engineer.md'}\n"


def test_arms_share_task_bytes_and_engineer_prompt_and_plan_matches_execution(env):
    norm = _neutral(_engineer_prompts(env))
    assert norm["baseline"] == norm["candidate"]


@pytest.mark.parametrize("checkout", ["baseline", "candidate", "baseline-and-candidate", "neutral"])
def test_arm_word_in_shared_checkout_path_is_compared_not_normalized(env, checkout):
    roles = _checkout_named(env, checkout)
    norm = _neutral(_engineer_prompts(env))
    assert all(p.count(roles) == 1 for p in norm.values())
    assert norm["baseline"] == norm["candidate"]


def test_normalization_keeps_common_bytes_and_literal_arm_words_comparable(env):
    roles = _checkout_named(env, "baseline-and-candidate")
    arms = _engineer_prompts(env)
    (rb, sb, b), (rc, sc, c) = arms["baseline"], arms["candidate"]
    assert _arm_neutral(b, "baseline", rb, sb) == _arm_neutral(c, "candidate", rc, sc)
    path = roles[len("READ AND FOLLOW EXACTLY: "):-1]
    per_arm = lambda p, a: p.replace(path, path.replace("/baseline-and-candidate/", f"/{a}/"))
    plants = {
        "common role file": (b, c.replace(path, path.replace("engineer.md", "reviewer.md"))),
        "role dir named per arm": (per_arm(b, "baseline"), per_arm(c, "candidate")),
        "common text": (b, c.replace("HARD RULES", "HARD  RULES")),
        "literal arm word in common text": (b.replace("HARD RULES", "HARD RULES baseline"),
                                            c.replace("HARD RULES", "HARD RULES candidate")),
        "other arm's state path": (b, c.replace(str(sc), str(sb), 1)),
    }
    for label, (pb, pc) in plants.items():
        assert (pb, pc) != (b, c), label
        assert _arm_neutral(pb, "baseline", rb, sb) != _arm_neutral(pc, "candidate", rc, sc), label


def test_planted_arm_word_in_real_prompt_is_a_mismatch(env):
    real = foundry.build_prompt
    env.mp.setattr(foundry, "build_prompt",
                   lambda cfg, *a, **k: real(cfg, *a, **k) + f"seat: {cfg.name.removeprefix('trial-')}\n")
    norm = _neutral(_engineer_prompts(env))
    assert norm["baseline"] != norm["candidate"]


def test_fix_review_runs_only_on_changes_required(env):
    env.mp.setenv("TRIAL_SPY_VERDICT", "CHANGES_REQUIRED")
    code, repo, state = _run_arm(env, "candidate")
    assert code == 0
    assert [c["stage"] for c in env.calls()] == ["ENGINEER", "REVIEWER", "FIX-REVIEW"]
    res = json.loads((state / "trial-result.json").read_text())
    assert [s["stage"] for s in res["result"]["stages"]] == ["engineer", "reviewer", "fix-review"]
    assert all(0 < s["timeout_s"] <= BUDGET - trial.STAGE_MARGIN_S for s in res["result"]["stages"])


def test_paths_stay_private_and_config_line_names_private_config(env):
    code, repo, state = _run_arm(env, "baseline")
    assert code == 0
    prompt = (state / "state" / "iter-01" / "engineer.attempt1.prompt").read_text()
    conf = state / "config.json"
    assert f"{conf}\n" in prompt
    assert str(pathlib.Path(foundry.FOUNDRY) / "products") not in prompt
    loaded = json.loads(conf.read_text())
    assert loaded["work_root"] == str(state) and loaded["repo"] == str(repo)
    assert loaded["push_enabled"] is False and loaded["allowed_push_repo"] == ""
    assert set(loaded) == {f.name for f in __import__("dataclasses").fields(foundry.ProductConfig)}
    for p in state.rglob("*"):
        assert trial._inside(p, state)
    assert all(trial._inside(pathlib.Path(c["out"]), state) for c in env.calls())


def test_stage_without_output_fails_once_with_no_retry_sleep_or_revert(env):
    env.mp.setenv("TRIAL_SPY_SILENT", "ENGINEER")
    env.mp.setattr(foundry, "classify_attempt_failure", lambda blob: foundry.AUTH_HOLD_KIND)
    waits: list = []
    real_sleep = foundry.sleep_interruptible
    env.mp.setattr(foundry, "sleep_interruptible", lambda cfg, s: waits.append(s) or real_sleep(cfg, s))
    code, repo, state = _run_arm(env, "candidate")
    assert code == trial.EXIT_STAGE_FAILED
    assert [c["stage"] for c in env.calls()] == ["ENGINEER"]
    assert json.loads((state / "trial-result.json").read_text())["result"]["status"] == "stage-failed"
    assert waits == [0]  # auth-hold path reached, held for 0 s
    assert env.hits == []


def test_real_stop_fails_safe_before_spawn(env):
    env.mp.setattr(foundry, "global_stop", lambda: True)
    code, _, _ = _run_arm(env, "baseline")
    assert code == trial.EXIT_STAGE_FAILED and env.calls() == []


@pytest.mark.parametrize("argv", [[], ["x"], ["x", "y"], ["x", "{prompt}", "{prompt}"],
                                  ["{prompt}", "x"], ["x", ""], "x {prompt}", None])
def test_agent_argv_must_be_explicit(env, argv):
    code, _, state = _run_arm(env, "baseline", argv=argv if argv is not None else ["{x}"])
    assert code == trial.EXIT_INVALID and env.calls() == [] and not state.exists()


NUL_ARGV = {
    "executable": lambda e: ["invalid\x00executable", "{prompt}"],
    "standalone_arg": lambda e: [e.argv[0], e.argv[1], "\x00", "{prompt}"],
    "inside_arg": lambda e: [e.argv[0], e.argv[1], "arg\x00value", "{prompt}"],
}


@pytest.mark.parametrize("argv", [["invalid\x00executable", "{prompt}"],
                                  ["python", "arg\x00value", "{prompt}"],
                                  ["python", "\x00", "{prompt}"]])
def test_agent_argv_with_nul_is_rejected_by_validator(env, argv):
    errs = trial.agent_argv_errors(argv)
    assert errs and any("NUL" in x for x in errs)
    assert any("NUL" in x for x in trial.validate_trial(
        arm="baseline", repo=str(env.tmp / "r"), state_root=str(env.tmp / "s"),
        budget_s=BUDGET, agent_argv=argv))


@pytest.mark.parametrize("argv", [["python", "{prompt}"],
                                  ["/opt/my agent/bin", "--name", "caf\u00e9 \u4e2d", "{prompt}"],
                                  ["python", "say \"hi\" 'there'", "{prompt}"]])
def test_agent_argv_without_nul_stays_valid(argv):
    assert trial.agent_argv_errors(argv) == []


@pytest.mark.parametrize("arm", trial.ARMS)
@pytest.mark.parametrize("case", sorted(NUL_ARGV))
def test_cli_arm_rejects_nul_argv_before_git_seed_or_spawn(env, capsys, arm, case):
    hits: list[str] = []
    for n in ("prepare_arm_repo", "seed_task", "run_arm"):
        env.mp.setattr(trial, n, lambda *a, _n=n, **k: hits.append(_n) or (_ for _ in ()).throw(
            AssertionError(f"TRIPWIRE {_n}")))
    capsys.readouterr()
    code, repo, state = _run_arm(env, arm, argv=NUL_ARGV[case](env))
    out = json.loads(capsys.readouterr().out)
    assert code == trial.EXIT_INVALID and out["status"] == "invalid"
    assert any("NUL" in x for x in out["errors"])
    assert hits == [] and env.hits == [] and env.calls() == []
    assert not state.exists() and not (repo / ".git").exists()


@pytest.mark.parametrize("arm", trial.ARMS)
def test_argv_with_spaces_unicode_and_quotes_still_runs_arm(env, arm):
    extra = ["a b", "caf\u00e9 \u4e2d", "say \"hi\" 'x'"]
    code, _, _ = _run_arm(env, arm, argv=[env.argv[0], env.argv[1], *extra, "{prompt}"])
    calls = env.calls()
    assert code == trial.EXIT_OK and calls
    assert all(c["argc"] == 2 + len(extra) and c["stage"] for c in calls)


def _fs_rejects(s: str) -> bool:
    try:
        os.fsencode(s)
    except UnicodeEncodeError:
        return True
    return False


# POSIX encodes argv with the filesystem encoding + surrogateescape, which maps only
# U+DC80..U+DCFF back to single bytes; any other lone surrogate cannot be encoded.
POSIX_FS = sys.getfilesystemencodeerrors() == "surrogateescape"
UNENCODABLE = {"high_d800": "\ud800", "high_dbff": "\udbff", "low_dc00": "\udc00",
               "low_dc7f": "\udc7f", "low_dd00": "\udd00", "low_dfff": "\udfff",
               "pair_then_trailing_high": "\U0001f600\ud83d"}
ENCODABLE = {"escape_dc80": "\udc80", "escape_dcff": "\udcff", "emoji": "\U0001f600",
             "accent": "caf\u00e9", "cjk": "\u4e2d", "quotes": "say \"hi\" 'x'"}
needs_lone_surrogate_rejection = pytest.mark.skipif(
    not _fs_rejects("\ud800"), reason="this OS filesystem encoding encodes lone surrogates")
ENC_ARGV = {
    "executable": lambda e, c: ["python" + c, "{prompt}"],
    "non_placeholder_arg": lambda e, c: [e.argv[0], e.argv[1], c, "{prompt}"],
    "trailing_in_arg": lambda e, c: [e.argv[0], e.argv[1], "--flag=x" + c, "{prompt}"],
}


@pytest.mark.parametrize("pos", sorted(ENC_ARGV))
@pytest.mark.parametrize("ch", sorted({**UNENCODABLE, **ENCODABLE}.values()))
def test_agent_argv_validator_matches_real_os_fsencode(env, pos, ch):
    argv = ENC_ARGV[pos](env, ch)
    errs = trial.agent_argv_errors(argv)
    assert bool(errs) == any(_fs_rejects(a) for a in argv)
    assert all(ch not in x for x in errs)


@pytest.mark.skipif(not POSIX_FS, reason="filesystem error handler is not surrogateescape")
def test_posix_surrogateescape_rejects_lone_surrogates_but_keeps_dc80_dcff():
    for ch in UNENCODABLE.values():
        assert _fs_rejects(ch)
        errs = trial.agent_argv_errors(["python", "a" + ch, "{prompt}"])
        assert len(errs) == 1 and "encod" in errs[0] and ch not in errs[0]
    for ch in ENCODABLE.values():
        assert trial.agent_argv_errors(["python", ch, "{prompt}"]) == []
    assert os.fsdecode(b"\x80") == "\udc80" and os.fsencode("\udc80") == b"\x80"


def test_encoding_check_keeps_shape_and_nul_errors_first():
    assert "explicit list" in trial.agent_argv_errors(["\ud800"])[0]
    assert "explicit list" in trial.agent_argv_errors([b"x", "{prompt}"])[0]
    assert "NUL" in trial.agent_argv_errors(["\ud800\x00", "{prompt}"])[0]


def test_unexpected_encoder_failure_is_not_swallowed(env, monkeypatch):
    def boom(_):
        raise RuntimeError("internal")
    monkeypatch.setattr(os, "fsencode", boom)
    with pytest.raises(RuntimeError, match="internal"):
        trial.agent_argv_errors(["python", "{prompt}"])
    with pytest.raises(RuntimeError, match="internal"):
        _run_arm(env, "baseline")


def _run_arm_raw(e, arm, raw_json):
    repo = e.tmp / f"{arm}-repo"
    shutil.copytree(e.fx, repo)
    state = e.tmp / f"{arm}-state"
    e.mp.chdir(repo)
    try:
        code = trial.main(["arm", "--arm", arm, "--state-root", str(state),
                           "--agent-argv-json", raw_json])
    finally:
        e.mp.chdir(e.tmp)
    return code, repo, state


def _setup_tripwires(e):
    hits: list[str] = []
    trip = lambda n: lambda *a, **k: hits.append(n) or (_ for _ in ()).throw(AssertionError(f"TRIPWIRE {n}"))
    for n in ("trial_config", "prepare_arm_repo", "seed_task", "run_arm"):
        e.mp.setattr(trial, n, trip(n))
    for n in ("run", "Popen", "check_output", "call"):
        e.mp.setattr(subprocess, n, trip(f"subprocess.{n}"))
    return hits


@needs_lone_surrogate_rejection
@pytest.mark.parametrize("arm", trial.ARMS)
@pytest.mark.parametrize("raw", [
    r'["python\ud800", "{prompt}"]',
    r'["python", "\udc00", "{prompt}"]',
    r'["python", "--name=x\udfff", "{prompt}"]',
    r'["python", "\ud83d\ude00\ud83d", "{prompt}"]',
], ids=["high_in_executable", "low_arg", "trailing_low", "pair_then_trailing_high"])
def test_cli_arm_rejects_unencodable_argv_before_any_setup(env, capsys, arm, raw):
    assert _fs_rejects("".join(json.loads(raw)))
    hits = _setup_tripwires(env)
    capsys.readouterr()
    code, repo, state = _run_arm_raw(env, arm, raw)
    cap = capsys.readouterr()
    out = json.loads(cap.out)
    assert code == trial.EXIT_INVALID and out["status"] == "invalid" and cap.err == ""
    assert len(out["errors"]) == 1 and "encod" in out["errors"][0]
    assert "\\ud8" not in cap.out and "\\udc" not in cap.out and "\\udf" not in cap.out
    cap.out.encode("ascii")
    assert hits == [] and env.hits == [] and env.calls() == []
    assert not state.exists() and not (repo / ".git").exists()
    assert sorted(p.name for p in repo.iterdir()) == ["calc.py", "test_calc.py"]


ARGV_SPY = r"""
import json, os, runpy, sys
with open(os.environ["TRIAL_ARGV_LOG"], "a") as f:
    f.write(json.dumps([os.fsencode(a).hex() for a in sys.argv[1:-1]]) + "\n")
runpy.run_path(os.environ["TRIAL_SPY_PATH"], run_name="__main__")
"""


@pytest.mark.skipif(not POSIX_FS, reason="filesystem error handler is not surrogateescape")
@pytest.mark.parametrize("arm", trial.ARMS)
def test_valid_unicode_and_surrogateescape_args_reach_agent_unchanged(env, arm):
    wrap = env.tmp / "argv_spy.py"
    wrap.write_text(ARGV_SPY)
    log = env.tmp / "argv.jsonl"
    env.mp.setenv("TRIAL_ARGV_LOG", str(log))
    env.mp.setenv("TRIAL_SPY_PATH", str(env.spy))
    escaped = os.fsdecode(b"\x80")
    assert escaped == "\udc80"
    pair = json.loads(r'"\ud83d\ude00"')
    assert pair == "\U0001f600" and len(pair) == 1
    extra = ["caf\u00e9 \u4e2d", pair, escaped, "x\udcff", "{prompt}x"]
    raw = json.dumps([sys.executable, str(wrap), *extra, "{prompt}"])
    assert "\\ud83d\\ude00" in raw and "\\udc80" in raw
    code, _, _ = _run_arm_raw(env, arm, raw)
    assert code == trial.EXIT_OK and env.calls() and env.hits == []
    seen = [json.loads(x) for x in log.read_text().splitlines()]
    want = [os.fsencode(a).hex() for a in extra]
    assert want[2] == "80" and want[3] == "78ff"
    assert seen and all(s == want for s in seen)


def test_missing_agent_argv_has_no_ambient_fallback(env):
    with pytest.raises(SystemExit):
        trial.main(["arm", "--arm", "baseline", "--state-root", str(env.tmp / "s")])
    assert env.calls() == []


def test_overrides_ignore_ambient_agent_env(env):
    trial.install_overrides(env.argv)
    assert foundry.AGENT_BIN == sys.executable and foundry.AGENT_RUN_ARGS == env.argv[1:]
    assert foundry.MAX_ATTEMPTS == 1 and foundry.AUTH_HOLD_SECONDS == 0
    assert foundry.resolve_agent_endpoint() is None
    assert not any(k.startswith("FOUNDRY_AGENT_") for k in os.environ)


def _bad_cases(e):
    froot = pathlib.Path(foundry.FOUNDRY).resolve()
    repo = e.tmp / "r"
    repo.mkdir()
    full = e.tmp / "full"
    full.mkdir()
    (full / "x").write_text("x")
    marked = e.tmp / "marked"
    marked.mkdir()
    (marked / trial.STATE_MARKER).write_text("x")
    link = e.tmp / "link"
    link.symlink_to(repo)
    inner = e.tmp / "outer" / "inner"
    inner.mkdir(parents=True)
    (e.tmp / "outer" / ".git").mkdir()
    ok_state = str(e.tmp / "s")
    return {
        "relative_repo": dict(repo="r", state_root=ok_state),
        "non_normalized": dict(repo=str(repo) + "/../r", state_root=ok_state),
        "symlink_alias": dict(repo=str(link), state_root=ok_state),
        "repo_is_checkout": dict(repo=str(froot), state_root=ok_state),
        "state_under_products": dict(repo=str(repo), state_root=str(froot / "products" / "trial-x")),
        "state_in_repo": dict(repo=str(repo), state_root=str(repo / "s")),
        "repo_in_state": dict(repo=str(repo), state_root=str(e.tmp)),
        "nonempty_state": dict(repo=str(repo), state_root=str(full)),
        "overlapping_arm_state": dict(repo=str(repo), state_root=str(marked / "s")),
        "repo_in_git_worktree": dict(repo=str(inner), state_root=ok_state),
        "budget_zero": dict(repo=str(repo), state_root=ok_state, budget_s=0),
        "budget_bool": dict(repo=str(repo), state_root=ok_state, budget_s=True),
        "budget_inf": dict(repo=str(repo), state_root=ok_state, budget_s=float("inf")),
        "budget_huge": dict(repo=str(repo), state_root=ok_state, budget_s=trial.MAX_BUDGET_S + 1),
        "bad_arm": dict(repo=str(repo), state_root=ok_state, arm="final"),
    }


def test_invalid_inputs_rejected_before_anything_is_created(env):
    for label, kw in _bad_cases(env).items():
        args = {"arm": "baseline", "budget_s": BUDGET, "agent_argv": env.argv, **kw}
        assert trial.validate_trial(**args), label
    assert not (env.tmp / "s").exists() and env.calls() == []
    assert not (pathlib.Path(foundry.FOUNDRY) / "products" / "trial-x").exists()


def test_production_product_name_rejected(env, tmp_path):
    fake = tmp_path / "fake-checkout"
    (fake / "products" / "trial-baseline").mkdir(parents=True)
    env.mp.setattr(foundry, "FOUNDRY", fake)
    (tmp_path / "r").mkdir()
    errs = trial.validate_trial(arm="baseline", repo=str(tmp_path / "r"),
                                state_root=str(tmp_path / "s"), budget_s=BUDGET, agent_argv=env.argv)
    assert any("production product" in x for x in errs)


def test_plan_spawns_nothing_and_writes_nothing(env, capsys):
    def boom(*a, **k):
        raise AssertionError("spawned")
    env.mp.setattr(subprocess, "run", boom)
    env.mp.setattr(subprocess, "Popen", boom)
    repo = env.tmp / "r"
    repo.mkdir()
    before = sorted(env.tmp.rglob("*"))
    assert trial.main(["plan", "--arm", "candidate", "--repo", str(repo), "--state-root",
                       str(env.tmp / "s"), "--spec", str(env.spec), "--budget-s", "60"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["executed"] is False and plan["writes"] == [] and plan["task_sha"] == _sha(TASK)
    assert [s["stage"] for s in plan["stages"]] == ["engineer", "reviewer"]
    assert sorted(env.tmp.rglob("*")) == before


def test_arm_git_root_commits_through_effective_hooks(env):
    repo = env.tmp / "hooked"
    shutil.copytree(env.fx, repo)
    info = trial.prepare_arm_repo(str(repo), "baseline")
    assert info["commit_exit"] == 0 and len(info["head"]) == 40
    runtime = subprocess.run(["git", "rev-parse", "--git-path", "hooks"], cwd=repo,
                             capture_output=True, text=True).stdout.strip()
    assert info["hooks_path"] == runtime


def test_refusing_hook_in_owned_fixture_fails_closed(env):
    repo = env.tmp / "refused"
    shutil.copytree(env.fx, repo)
    hooks = env.tmp / "fixture-hooks"
    hooks.mkdir()
    hook = hooks / "pre-commit"
    hook.write_text("#!/bin/sh\necho fixture-refusal >&2\nexit 1\n")
    hook.chmod(0o755)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "core.hooksPath", str(hooks)], cwd=repo, check=True)
    with pytest.raises(trial.TrialError, match="refused"):
        trial.prepare_arm_repo(str(repo), "baseline")
    head = subprocess.run(["git", "rev-parse", "--verify", "-q", "HEAD"], cwd=repo,
                          capture_output=True, text=True)
    assert head.returncode != 0


def test_trial_source_has_no_bypass_or_pipeline_reach():
    src = (_ROOT / "trial.py").read_text()
    for token in ("--no-verify", "hooksPath", "GIT_CONFIG", "commit-tree", "update-ref", "HUSKY",
                  "import dispatcher", "from dispatcher", "run_iteration(", "revert_repo(",
                  "head_of_branch(", "postrelease_step("):
        assert token not in src, token
    assert set(trial.ARM_STAGES["baseline"]) | set(trial.ARM_STAGES["candidate"]) <= trial.ALLOWED_STAGES
    assert trial.ALLOWED_STAGES == {"engineer", "reviewer", "fix-review"}


def test_real_bench_end_to_end_with_spy_arms(env):
    entry = env.tmp / "entry.py"
    entry.write_text(ENTRY)
    arm = lambda a: [sys.executable, str(entry), str(_ROOT), "arm", "--arm", a, "--state-root",
                     str(env.tmp / f"bench-state-{a}"), "--agent-argv-json", json.dumps(env.argv)]
    record = bench.run_bench(env.fx, env.spec, BUDGET, arm("baseline"), arm("candidate"),
                             [sys.executable, "-m", "unittest", "-q", "test_calc"],
                             env.tmp / "bench-out", ["test_calc.py"], ["calc.py"])
    assert record["frozen"]["spec_sha"] == _sha(TASK)
    for a in trial.ARMS:
        assert record[a]["exit_code"] == 0 and not record[a]["timed_out"], record[a]
        assert record[a]["accept"] == "PASS"
        res = json.loads((env.tmp / f"bench-state-{a}" / "trial-result.json").read_text())
        assert res["task_sha"] == res["seed"]["pm_sha"] == _sha(TASK)
        assert res["git"]["commit_exit"] == 0
    assert [c["stage"] for c in env.calls()] == ["ENGINEER", "ENGINEER", "REVIEWER"]
    assert all(c["argv0"] == str(env.spy) for c in env.calls())


# Inherited git environment (review B1): an arm must never act on another repository.
REPO_LOCATING_GIT_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
                         "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR", "GIT_NAMESPACE")
DISCOVERY_CONFIG_HOOK_GIT_ENV = ("GIT_CEILING_DIRECTORIES", "GIT_DISCOVERY_ACROSS_FILESYSTEM",
                                 "GIT_PREFIX", "GIT_TEMPLATE_DIR", "GIT_EXEC_PATH",
                                 "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_GLOBAL",
                                 "GIT_CONFIG_SYSTEM", "GIT_CONFIG_NOSYSTEM", "GIT_CONFIG",
                                 "GIT_REPLACE_REF_BASE", "GIT_SHALLOW_FILE")


def _clean_git(cwd, *args, extra=None):
    clean = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          env={**clean, **(extra or {})})


def _other_owned_repo(e, remote: bool) -> pathlib.Path:
    """A different repo the test owns: one tracked sentinel, committed through the effective hooks."""
    other = e.tmp / "other-owned"
    other.mkdir()
    (other / "keep.txt").write_text("sentinel\n")
    assert _clean_git(other, "init", "-q").returncode == 0
    assert _clean_git(other, "add", "keep.txt").returncode == 0
    ident = {"GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
             "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid"}
    c = _clean_git(other, "commit", "-q", "-m", "fixture sentinel", extra=ident)
    assert c.returncode == 0, c.stderr
    if remote:
        assert _clean_git(other, "remote", "add", "origin", "https://example.invalid/o.git").returncode == 0
    return other


def _repo_state(r: pathlib.Path) -> dict:
    index = r / ".git" / "index"
    return {"head": _clean_git(r, "rev-parse", "HEAD").stdout, "count": _clean_git(r, "rev-list", "--count", "--all").stdout,
            "tree": _clean_git(r, "rev-parse", "HEAD^{tree}").stdout, "ls": _clean_git(r, "ls-files", "-s").stdout,
            "status": _clean_git(r, "status", "--porcelain").stdout,
            "index": _sha(index.read_bytes()) if index.exists() else None,
            "sentinel": (r / "keep.txt").read_bytes()}


@pytest.mark.parametrize("remote", [True, False], ids=["with-remote", "no-remote"])
def test_inherited_git_dir_into_other_owned_repo_is_refused_and_leaves_it_untouched(env, capsys, remote):
    other = _other_owned_repo(env, remote)
    before = _repo_state(other)
    env.mp.setenv("GIT_DIR", str(other / ".git"))
    code, repo, state = _run_arm(env, "baseline")
    env.mp.delenv("GIT_DIR")
    out = capsys.readouterr().out
    assert _repo_state(other) == before
    assert code == trial.EXIT_INVALID
    assert not (repo / ".git").exists() and not state.exists() and env.calls() == []
    assert "GIT_DIR" in out and str(other) not in out


@pytest.mark.parametrize("name", REPO_LOCATING_GIT_ENV + DISCOVERY_CONFIG_HOOK_GIT_ENV)
def test_redirecting_git_env_is_refused_before_any_git_call_or_spawn(env, capsys, name):
    calls: list = []

    def no_git(repo, *args, env=None):  # never reaches real git with the variable set
        calls.append(args)
        return subprocess.CompletedProcess(["git", *args], 1, "", "spy: git must not run")
    env.mp.setattr(trial, "_git", no_git)
    secret = str(env.tmp / "elsewhere-value")
    env.mp.setenv(name, secret)
    code, repo, state = _run_arm(env, "baseline")
    env.mp.delenv(name)
    out = capsys.readouterr().out
    assert code == trial.EXIT_INVALID and calls == [] and env.calls() == []
    assert not state.exists() and not (repo / ".git").exists()
    assert name in out and secret not in out


def test_plan_refuses_redirecting_git_env(env, capsys):
    repo = env.tmp / "r"
    repo.mkdir()
    secret = str(env.tmp / "elsewhere" / ".git")
    env.mp.setenv("GIT_DIR", secret)
    code = trial.main(["plan", "--arm", "baseline", "--repo", str(repo), "--state-root",
                       str(env.tmp / "s"), "--spec", str(env.spec), "--budget-s", "60"])
    out = capsys.readouterr().out
    assert code == trial.EXIT_INVALID and json.loads(out)["status"] == "invalid"
    assert "GIT_DIR" in out and secret not in out and not (env.tmp / "s").exists()


def test_harmless_git_env_still_runs_arm_through_effective_hooks(env):
    trace = env.tmp / "trace2.json"
    env.mp.setenv("GIT_TRACE2_EVENT", str(trace))
    env.mp.setenv("GIT_TERMINAL_PROMPT", "0")
    code, repo, state = _run_arm(env, "baseline")
    assert code == 0 and [c["stage"] for c in env.calls()] == ["ENGINEER"]
    res = json.loads((state / "trial-result.json").read_text())
    runtime = _clean_git(repo, "rev-parse", "--git-path", "hooks").stdout.strip()
    assert res["git"]["commit_exit"] == 0 and res["git"]["hooks_path"] == runtime
    assert _clean_git(repo, "rev-parse", "--absolute-git-dir").stdout.strip() == str(repo / ".git")


@pytest.mark.parametrize("lie", ["git-dir", "toplevel", "remote"])
def test_arm_repo_identity_is_verified_after_init_and_before_any_staging(env, lie):
    repo = env.tmp / "spied"
    shutil.copytree(env.fx, repo)
    elsewhere = str(env.tmp / "elsewhere")
    real, calls = trial._git, []

    def redirected(r, *args, env=None):  # a git whose answers say "some other repo"
        calls.append(args)
        if args[0] in ("add", "commit"):
            return subprocess.CompletedProcess(["git", *args], 0, "", "")
        if lie == "git-dir" and args[:2] == ("rev-parse", "--absolute-git-dir"):
            return subprocess.CompletedProcess(["git", *args], 0, elsewhere + "/.git\n", "")
        if lie == "toplevel" and args[:2] == ("rev-parse", "--show-toplevel"):
            return subprocess.CompletedProcess(["git", *args], 0, elsewhere + "\n", "")
        if lie == "remote" and args[:1] == ("remote",):
            return subprocess.CompletedProcess(["git", *args], 0, "origin\n", "")
        return real(r, *args, env=env)
    env.mp.setattr(trial, "_git", redirected)
    with pytest.raises(trial.TrialError):
        trial.prepare_arm_repo(str(repo), "baseline")
    verbs = [a[0] for a in calls]
    assert verbs[0] == "init" and "add" not in verbs and "commit" not in verbs, verbs
    assert not (repo / ".git" / "index").exists()
