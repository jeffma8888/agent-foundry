"""Offline fixed-task trial adapter: a bench.py arm command over real Foundry stages.

`bench.py` stays the only scorer. This module is the arm command it runs, inside
the arm copy (cwd), with the frozen task at `$BENCH_SPEC` and the budget at
`$BENCH_BUDGET_S`:

    python3 <checkout>/trial.py arm --arm baseline  --state-root ABS --agent-argv-json JSON
    python3 <checkout>/trial.py arm --arm candidate --state-root ABS --agent-argv-json JSON

- baseline  = one `engineer` stage.
- candidate = `engineer` then `reviewer`, plus `fix-review` only when the existing
  reviewer gate (`needs_review_repair(read_review_disposition(...))`) fires.

Both arms seed the exact task bytes as `iter-01/pm.md` in an arm-private state
root and call the real `foundry.build_prompt` / `foundry.run_stage` over a
`ProductConfig` built here. No pm, scout, tester, final, revert, push or release
stage is reachable. NOT a sandbox: any agent argv runs with the operator's
privileges. Never import this module from the dispatcher or the live pipeline:
it overrides foundry module globals for its own (one-arm) process.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import os
import pathlib
import subprocess
import sys
import time

sys.dont_write_bytecode = True
_HERE = pathlib.Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
import foundry  # noqa: E402

ARMS = ("baseline", "candidate")
ARM_STAGES = {"baseline": ("engineer",), "candidate": ("engineer", "reviewer")}
ALLOWED_STAGES = frozenset({"engineer", "reviewer", "fix-review"})
# `fix-review` is in no foundry table; this literal mirrors run_iteration's call.
FIX_REVIEW_ARGS = ("fix.md", "fix_review.md")
ITERATION = 1
MAX_BUDGET_S = (2 ** 31 - 1) // 1000   # same ceiling as bench.MAX_BUDGET_S
STAGE_MARGIN_S = 5                     # left for logging/exit inside bench's killpg budget
STATE_MARKER = ".trial-state"
PROMPT_PLACEHOLDER = "{prompt}"
EXIT_OK, EXIT_STAGE_FAILED, EXIT_INVALID, EXIT_GIT = 0, 1, 2, 3
# Inherited git variables pick the repository (and its index/objects) that the arm's own
# git calls and the agent it spawns act on. They are refused by name, never cleared.
REPO_LOCATING_GIT_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
                         "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR", "GIT_NAMESPACE")
# The only GIT_* names an arm inherits. Any other one (discovery, prefix, template, exec
# path, replace refs, injected config or hook settings, ...) is refused the same way.
HARMLESS_GIT_ENV = frozenset({"GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_AUTHOR_DATE",
                              "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "GIT_COMMITTER_DATE",
                              "GIT_TERMINAL_PROMPT", "GIT_OPTIONAL_LOCKS", "GIT_PAGER",
                              "GIT_EDITOR"})
HARMLESS_GIT_ENV_PREFIX = "GIT_TRACE"


class TrialError(RuntimeError):
    """A refusal raised before or during an arm; the arm exits nonzero."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _inside(child: pathlib.Path, parent: pathlib.Path) -> bool:
    return child == parent or parent in child.parents


def _path_errors(label: str, value: object) -> list[str]:
    if not isinstance(value, str) or not value or not os.path.isabs(value):
        return [f"{label} must be an absolute path: {value!r}"]
    if os.path.normpath(value) != value:
        return [f"{label} must be normalized: {value!r}"]
    if str(pathlib.Path(value).resolve()) != value:
        return [f"{label} must not traverse a symlink or alias: {value!r}"]
    return []


def _enclosing_git(path: pathlib.Path) -> pathlib.Path | None:
    """Nearest dir at or above `path` holding a `.git` entry (read-only, no git call)."""
    for p in (path, *path.parents):
        if (p / ".git").exists():
            return p
    return None


def git_env_errors(environ=None) -> list[str]:
    """Refuse inherited git variables that could aim git, or the agent, at another
    repository, config or hooks. Reports names only, never values."""
    environ = os.environ if environ is None else environ
    bad = sorted(k for k in environ if k in REPO_LOCATING_GIT_ENV or (
        k.startswith("GIT_") and k not in HARMLESS_GIT_ENV
        and not k.startswith(HARMLESS_GIT_ENV_PREFIX)))
    if not bad:
        return []
    return ["refusing inherited git environment that can redirect the repository, its "
            f"index/objects, discovery, config or hooks; unset it and rerun: {', '.join(bad)}"]


def agent_argv_errors(argv: object) -> list[str]:
    ok = (isinstance(argv, list) and len(argv) >= 2
          and all(isinstance(a, str) and a for a in argv)
          and argv.count(PROMPT_PLACEHOLDER) == 1 and argv[0] != PROMPT_PLACEHOLDER)
    if not ok:
        return ["agent argv must be an explicit list of non-empty strings: an executable "
                f"plus exactly one {PROMPT_PLACEHOLDER!r} argument"]
    if any("\0" in a for a in argv):
        return ["agent argv elements must not contain NUL characters"]
    try:
        for a in argv:
            os.fsencode(a)
    except UnicodeEncodeError:
        return ["agent argv elements must be encodable with the OS filesystem encoding"]
    return []


def budget_errors(budget_s: object) -> list[str]:
    if (isinstance(budget_s, bool) or not isinstance(budget_s, (int, float))
            or not math.isfinite(float(budget_s)) or not 0 < budget_s <= MAX_BUDGET_S):
        return [f"budget_s must be a finite number in (0, {MAX_BUDGET_S}]: {budget_s!r}"]
    return []


def validate_trial(*, arm: object, repo: object, state_root: object, budget_s: object,
                   agent_argv: object = None, check_argv: bool = True) -> list[str]:
    """Every refusal, computed with reads only: no mkdir, no git, no spawn."""
    errs: list[str] = git_env_errors()
    if arm not in ARMS:
        return errs + [f"arm must be one of {ARMS}: {arm!r}"]
    if any(st not in ALLOWED_STAGES for st in ARM_STAGES[arm]):
        errs.append(f"forbidden stage in {arm}: {ARM_STAGES[arm]}")
    name = arm_name(arm)
    froot = pathlib.Path(foundry.FOUNDRY).resolve()
    if (froot / "products" / name).exists():
        errs.append(f"name collides with a production product: {name}")
    errs += budget_errors(budget_s)
    if check_argv:
        errs += agent_argv_errors(agent_argv)
    perr = _path_errors("repo", repo) + _path_errors("state_root", state_root)
    if perr:
        return errs + perr
    r, s = pathlib.Path(repo), pathlib.Path(state_root)
    for label, p in (("repo", r), ("state_root", s)):
        if _inside(p, froot) or _inside(froot, p):
            errs.append(f"{label} overlaps the Foundry checkout: {p}")
    if _inside(r, s) or _inside(s, r):
        errs.append("repo and state_root overlap")
    if not r.is_dir():
        errs.append(f"repo is not a directory: {r}")
    else:
        enclosing = _enclosing_git(r)
        if enclosing is not None:
            errs.append(f"repo is already inside a git worktree: {enclosing}")
    if not s.parent.is_dir():
        errs.append(f"state_root parent does not exist: {s.parent}")
    if s.exists() and (not s.is_dir() or any(s.iterdir())):
        errs.append(f"state_root exists and is not an empty directory: {s}")
    for p in s.parents:
        if (p / STATE_MARKER).exists():
            errs.append(f"state_root overlaps another arm's state: {p}")
            break
    if _enclosing_git(s.parent if not s.exists() else s) is not None:
        errs.append("state_root is inside a git worktree")
    return errs


def arm_name(arm: str) -> str:
    return f"trial-{arm}"


def trial_config(arm: str, repo: str, state_root: str) -> "foundry.ProductConfig":
    """A ProductConfig whose every writable path is under repo or state_root."""
    cfg = foundry.ProductConfig(
        name=arm_name(arm), repo=repo, allowed_push_repo="", branch="trial",
        vision="", roadmap="", quality_ref="", test_cmd="",
        roles_dir=str(pathlib.Path(foundry.FOUNDRY).resolve() / "roles"),
        work_root=state_root, learnings="", staffing="", push_enabled=False,
        postrelease_enabled=False, setup_cmd="", smoke_cmd=None, dual_pm_scouts=False,
        gap_register="", gap_layers=(), practice_register="", notify_cmd="")
    return cfg.resolve()


def stage_args(stage: str) -> tuple[str, str]:
    if stage not in ALLOWED_STAGES:
        raise TrialError(f"forbidden stage: {stage!r}")
    if stage == "fix-review":
        return FIX_REVIEW_ARGS
    args = foundry.prompt_stage_args(stage)
    if args is None:
        raise TrialError(f"foundry has no stage args for {stage!r}")
    return args


def private_config_path(cfg) -> pathlib.Path:
    return pathlib.Path(cfg.work_root) / "config.json"


def plan_arm(arm: str, repo: str, state_root: str, task: bytes, budget_s) -> dict:
    """DRY RUN: the attempt-1 prompt of the arm's first stage. Writes nothing and
    spawns nothing. The private config.json the arm will seed does not exist yet,
    so `product_config_path` is answered with the path the seed will verify."""
    errs = validate_trial(arm=arm, repo=repo, state_root=state_root, budget_s=budget_s,
                          check_argv=False)
    if errs:
        raise TrialError("; ".join(errs))
    cfg = trial_config(arm, repo, state_root)
    it_dir = cfg.state / f"iter-{ITERATION:02d}"
    saved = foundry.product_config_path
    foundry.product_config_path = lambda _cfg: str(private_config_path(cfg))
    try:
        stages = []
        for st in ARM_STAGES[arm]:
            role_file, out_name = stage_args(st)
            prompt = foundry.build_prompt(cfg, ITERATION, st, role_file, it_dir / out_name,
                                          it_dir, "")
            prompt += foundry.retry_directive(1, st, it_dir / out_name)
            stages.append({"stage": st, "role_file": role_file, "out_file": str(it_dir / out_name),
                           "attempt1_prompt_sha": sha256(prompt.encode("utf-8")),
                           "exact": st == ARM_STAGES[arm][0], "prompt": prompt})
    finally:
        foundry.product_config_path = saved
    return {"executed": False, "writes": [], "arm": arm, "name": cfg.name, "repo": repo,
            "state_root": state_root, "task_sha": sha256(task), "budget_s": budget_s,
            "push_enabled": False, "stages": stages,
            "optional_stage": "fix-review (candidate only, on reviewer CHANGES_REQUIRED)",
            "note": "only the first stage's prompt is exact; later stages read files "
                    "earlier stages may append to"}


def seed_task(cfg, task: bytes) -> dict:
    root = pathlib.Path(cfg.work_root)
    root.mkdir(exist_ok=True)
    (root / STATE_MARKER).write_text(cfg.name + "\n")
    data = {f.name: getattr(cfg, f.name) for f in dataclasses.fields(cfg)}
    data["gap_layers"] = list(cfg.gap_layers)
    private_config_path(cfg).write_text(json.dumps(data, indent=2) + "\n")
    it_dir = cfg.state / f"iter-{ITERATION:02d}"
    it_dir.mkdir(parents=True)
    (it_dir / "pm.md").write_bytes(task)
    if foundry.product_config_path(cfg) != str(private_config_path(cfg)):
        raise TrialError("private config.json did not verify as this product's config")
    return {"pm_md": str(it_dir / "pm.md"), "pm_sha": sha256((it_dir / "pm.md").read_bytes()),
            "config": str(private_config_path(cfg))}


def _git(repo: str, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True,
                          env=env, timeout=120)


def prepare_arm_repo(repo: str, arm: str) -> dict:
    """Make the arm copy its own git root with one baseline commit, through the
    effective hooks (resolved at runtime, never set). The new repo's identity (its
    own `.git`, toplevel, no remote) is verified after `init` and before anything
    is staged. Any refusal raises."""
    errs = git_env_errors()
    if errs:
        raise TrialError("; ".join(errs))
    info: dict = {}
    p = _git(repo, "init", "-q")
    if p.returncode != 0:
        raise TrialError(f"git init failed ({p.returncode}): {p.stderr.strip()[-300:]}")
    own = pathlib.Path(repo) / ".git"
    gd = _git(repo, "rev-parse", "--absolute-git-dir")
    if (gd.returncode != 0 or gd.stdout.strip() != str(own)
            or own.is_symlink() or not own.is_dir()):
        raise TrialError("arm git dir is not the arm copy's own .git")
    top = _git(repo, "rev-parse", "--show-toplevel")
    if top.returncode != 0 or top.stdout.strip() != repo:
        raise TrialError("arm git toplevel is not the arm copy")
    rem = _git(repo, "remote")
    if rem.returncode != 0 or rem.stdout.strip():
        raise TrialError("arm git repo has a remote")
    p = _git(repo, "add", "-A")
    if p.returncode != 0:
        raise TrialError(f"git add failed ({p.returncode}): {p.stderr.strip()[-300:]}")
    info["hooks_path"] = _git(repo, "rev-parse", "--git-path", "hooks").stdout.strip()
    ident = {"GIT_AUTHOR_NAME": "trial", "GIT_AUTHOR_EMAIL": "trial@example.invalid",
             "GIT_COMMITTER_NAME": "trial", "GIT_COMMITTER_EMAIL": "trial@example.invalid"}
    p = _git(repo, "commit", "-q", "--allow-empty", "-m", f"trial: {arm} arm snapshot",
             env={**os.environ, **ident})
    info["commit_exit"], info["commit_stderr"] = p.returncode, p.stderr.strip()[-300:]
    if p.returncode != 0:
        raise TrialError(f"git commit refused ({p.returncode}): {info['commit_stderr']}")
    info["head"] = _git(repo, "rev-parse", "HEAD").stdout.strip()
    return info


def install_overrides(agent_argv: list[str]) -> None:
    """Single attempt, explicit argv only, no auth-hold sleep, no ambient endpoint."""
    for key in [k for k in os.environ if k.startswith("FOUNDRY_AGENT_")]:
        del os.environ[key]
    foundry.AGENT_BIN, foundry.AGENT_RUN_ARGS = agent_argv[0], list(agent_argv[1:])
    foundry.MAX_ATTEMPTS = 1
    foundry.AUTH_HOLD_SECONDS = 0
    foundry.resolve_agent_endpoint = lambda *a, **k: None


def _run_one(cfg, stage: str, deadline: float, extra: str = "") -> dict:
    if str(pathlib.Path(os.getcwd()).resolve()) != cfg.repo:
        raise TrialError(f"cwd is not the arm git root before {stage}")
    remaining = int(deadline - time.monotonic() - STAGE_MARGIN_S)
    if remaining < 1:
        return {"stage": stage, "ok": False, "timeout_s": 0, "reason": "budget exhausted"}
    foundry.STAGE_TIMEOUT = remaining
    role_file, out_name = stage_args(stage)
    ok, out = foundry.run_stage(cfg, ITERATION, stage, role_file, out_name, extra)
    return {"stage": stage, "ok": bool(ok), "timeout_s": remaining, "out": str(out)}


def run_arm(cfg, arm: str, *, agent_argv: list[str], deadline: float) -> dict:
    """Run the arm's stages through foundry.run_stage; stop at the first failure.
    No retry, no revert: a failed stage leaves its outputs for diagnosis."""
    install_overrides(agent_argv)
    ran: list[dict] = []
    for st in ARM_STAGES[arm]:
        step = _run_one(cfg, st, deadline)
        ran.append(step)
        if not step["ok"]:
            return {"arm": arm, "status": "stage-failed", "stages": ran}
        if st == "reviewer":
            gate = pathlib.Path(step["out"])
            if foundry.needs_review_repair(foundry.read_review_disposition(gate)):
                fix = _run_one(cfg, "fix-review", deadline,
                               f"Gate file to address: {gate} ([BLOCKING] only).")
                ran.append(fix)
                if not fix["ok"]:
                    return {"arm": arm, "status": "stage-failed", "stages": ran}
    return {"arm": arm, "status": "completed", "stages": ran}


def _read_bench_env() -> tuple[bytes, float]:
    spec, raw = os.environ.get("BENCH_SPEC", ""), os.environ.get("BENCH_BUDGET_S", "")
    if not spec or not os.path.isabs(spec) or not pathlib.Path(spec).is_file():
        raise TrialError("BENCH_SPEC must name the frozen task file")
    try:
        budget = float(raw)
    except ValueError:
        raise TrialError(f"BENCH_BUDGET_S is not a number: {raw!r}") from None
    return pathlib.Path(spec).read_bytes(), budget


def cmd_arm(ns) -> int:
    start = time.monotonic()
    try:
        argv = json.loads(ns.agent_argv_json)
    except ValueError:
        argv = None
    try:
        task, budget = _read_bench_env()
    except TrialError as exc:
        print(json.dumps({"status": "invalid", "errors": [str(exc)]}))
        return EXIT_INVALID
    repo = os.getcwd()
    errs = validate_trial(arm=ns.arm, repo=repo, state_root=ns.state_root, budget_s=budget,
                          agent_argv=argv)
    if errs:
        print(json.dumps({"status": "invalid", "errors": errs}))
        return EXIT_INVALID
    cfg = trial_config(ns.arm, repo, ns.state_root)
    record: dict = {"arm": ns.arm, "task_sha": sha256(task), "budget_s": budget}
    try:
        record["git"] = prepare_arm_repo(repo, ns.arm)
    except (TrialError, OSError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "git-refused", "error": str(exc)}))
        return EXIT_GIT
    record["seed"] = seed_task(cfg, task)
    result = run_arm(cfg, ns.arm, agent_argv=argv, deadline=start + budget)
    record["result"] = result
    (pathlib.Path(cfg.work_root) / "trial-result.json").write_text(json.dumps(record, indent=2))
    print(json.dumps({"arm": ns.arm, "status": result["status"],
                      "stages": [s["stage"] for s in result["stages"]]}))
    return EXIT_OK if result["status"] == "completed" else EXIT_STAGE_FAILED


def cmd_plan(ns) -> int:
    try:
        task = pathlib.Path(ns.spec).read_bytes()
        plan = plan_arm(ns.arm, ns.repo, ns.state_root, task, ns.budget_s)
    except (TrialError, OSError) as exc:
        print(json.dumps({"status": "invalid", "errors": [str(exc)]}))
        return EXIT_INVALID
    if not ns.with_prompt:
        for st in plan["stages"]:
            st.pop("prompt")
    print(json.dumps(plan, indent=2))
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="trial.py", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("arm", help="run one arm (cwd = bench arm copy)")
    a.add_argument("--arm", required=True, choices=ARMS)
    a.add_argument("--state-root", required=True)
    a.add_argument("--agent-argv-json", required=True)
    p = sub.add_parser("plan", help="dry run: print the arm's first-stage prompt sha")
    p.add_argument("--arm", required=True, choices=ARMS)
    p.add_argument("--repo", required=True)
    p.add_argument("--state-root", required=True)
    p.add_argument("--spec", required=True)
    p.add_argument("--budget-s", required=True, type=float)
    p.add_argument("--with-prompt", action="store_true")
    ns = ap.parse_args(argv)
    return cmd_arm(ns) if ns.cmd == "arm" else cmd_plan(ns)


if __name__ == "__main__":
    sys.exit(main())
