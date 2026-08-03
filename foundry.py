#!/usr/bin/env python3
"""agent-foundry -- a reusable, always-on autonomous product team.

One product team = a pipeline of fresh, single-shot AI agents:

    PM (TPM) -> Engineer -> Reviewer -> [Fix] -> Isolated Tester
             -> [Fix -> Tester] -> Final Reviewer (ships or reverts)

`foundry.py` runs ONE product's loop. Point it at ANY git repo via a JSON
config (see `foundry.config.example.json`). The dispatcher (`dispatcher.py`)
runs several product configs as a SINGLE quota-aware brain so no two model
calls ever run at once (they share one finite model-API token budget).

Design invariants (learned building `repolens` -- 9 features shipped overnight):

  * Stage success == the stage's OUTPUT FILE exists and is non-empty.
    Exit codes and agent self-reports are NOT trusted.
  * Every stage is a one-shot agent-CLI run, retried with exponential
    backoff. Infra failures (throttling / stall / timeout) never kill the loop.
  * The Final Reviewer is the ONLY role that touches git; on any doubt it
    reverts to origin/<branch> rather than shipping half-done work.
  * The Tester is firewalled from src/ -- black-box behaviour verification only.
  * Every role prompt carries an anti-delegation clause (no nested agent runs,
    no re-delegation) -- else sub-agents recurse.
  * Continuous by default: runs until a STOP sentinel file appears.

Usage:
    foundry.py run   --config products/repolens.json        # continuous
    foundry.py once  --config products/repolens.json        # a single iteration
"""

from __future__ import annotations

import argparse
import ast
import dataclasses
import datetime as dt
import json
import os
import pathlib
import shlex
import shutil
import subprocess
import sys
import time

from collections.abc import Iterable, Mapping, Sequence

FOUNDRY = pathlib.Path(__file__).resolve().parent
# The agent CLI is configurable so the foundry stays tool-agnostic. AGENT_BIN
# is the executable each stage shells out to; AGENT_RUN_ARGS is its argument
# template (the literal "{prompt}" is replaced with the per-stage task prompt
# at call time). Configure both via environment variables:
#   FOUNDRY_AGENT_BIN  = /path/to/your/agent-cli
#   FOUNDRY_AGENT_ARGS = JSON list, e.g. ["run", "--task", "{prompt}"]
AGENT_BIN = os.environ.get("FOUNDRY_AGENT_BIN", "")
AGENT_RUN_ARGS = json.loads(
    os.environ.get("FOUNDRY_AGENT_ARGS", '["run", "--task", "{prompt}"]'))

STAGE_TIMEOUT = 1800            # 30 min hard cap per agent-run attempt
MAX_ATTEMPTS = 4               # attempts per stage
BACKOFFS = [600, 1200, 2400]    # 10 -> 20 -> 40 min between attempts
COOLDOWNS = [1800, 3600, 7200, 14400]  # infra cooldown 30m -> 1h -> 2h -> 4h
REPORT_EVERY = 5               # periodic status report cadence (iterations)

ANTI_DELEGATION = (
    "HARD RULES: Do ALL of this work YOURSELF in this single run. Do NOT spawn "
    "nested agent runs, background jobs, schedulers, or teammates, and do NOT "
    "re-delegate the work to any other process. Touch ONLY the product repo, "
    "your state dir, and the foundry learnings log named below. Never push to "
    "any repo other than the declared push target. Never force-push. Never run "
    "authentication or credential commands."
)

# Bounded learnings digest inlined into every stage prompt (roadmap item 2,
# bite 2/2). `build_prompt` reads these at CALL time from the module globals
# (not as default-arg values) so a `monkeypatch.setattr(foundry, ...)` bites.
# The default of 10 is deliberately tighter than the CLI's 12: the prompt path
# pays this cost on EVERY stage of EVERY iteration, so a modest bound keeps
# per-prompt overhead small and time-to-first-token friendly.
PROMPT_LEARNINGS_RECENT = 10   # newest N lessons inlined into each stage prompt
PROMPT_LEARNINGS_LABEL = (
    "- Recent foundry learnings (bounded digest; read this, do not slurp the "
    "whole log):"
)


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
@dataclasses.dataclass
class ProductConfig:
    name: str
    repo: str                    # absolute path to the product git repo
    allowed_push_repo: str       # basename the final gate is allowed to push
    branch: str = "main"
    vision: str = ""             # path to VISION.md (fixed product intent)
    roadmap: str = ""            # path to roadmap file the PM owns
    prd: str = ""                # path to prd.json machine roadmap (item 1)
    quality_ref: str = ""        # sibling repo whose conventions set the bar
    test_cmd: str = "uv run pytest"
    roles_dir: str = ""          # defaults to <foundry>/roles
    work_root: str = ""          # defaults to <foundry>/products/<name>
    learnings: str = ""          # defaults to <work_root>/LEARNINGS.md
    staffing: str = ""           # defaults to <work_root>/staffing.json (item 19)
    quality_bar: str = ""        # free-form product quality constraints
    push_enabled: bool = True    # gate may push (False => dry-run / review-only)
    # Post-release fresh-clone verification (dormant until wired in iter 03).
    # Backward-compatible: old configs that omit these load with these defaults.
    postrelease_enabled: bool = True   # run the fresh-clone verify (iter 03+)
    setup_cmd: str = "uv sync"          # how to install deps in the fresh clone
    smoke_cmd: str | None = None       # optional smoke command; None => skipped
    dual_pm_scouts: bool = False       # dual-PM-scout opt-in (dormant; wired in a later bite)

    def resolve(self) -> "ProductConfig":
        def expand(p: str) -> str:
            if not p:
                return p
            return str(pathlib.Path(
                p.replace("{FOUNDRY}", str(FOUNDRY))).expanduser())
        self.repo = expand(self.repo)
        self.vision = expand(self.vision)
        self.roadmap = expand(self.roadmap)
        # prd.json machine roadmap: an explicit path (with {FOUNDRY}/~ expanded)
        # wins; otherwise default to <repo>/prd.json. Needs `repo` expanded first.
        self.prd = expand(self.prd) or str(pathlib.Path(self.repo) / "prd.json")
        self.quality_ref = expand(self.quality_ref)
        self.roles_dir = expand(self.roles_dir) or str(FOUNDRY / "roles")
        self.work_root = expand(self.work_root) or str(
            FOUNDRY / "products" / self.name)
        self.learnings = expand(self.learnings) or str(
            pathlib.Path(self.work_root) / "LEARNINGS.md")
        # staffing manifest (item 19): an explicit path (with {FOUNDRY}/~
        # expanded) wins; otherwise default to <work_root>/staffing.json --
        # foundry-side product metadata alongside LEARNINGS.md, NOT a file in
        # the product's own git repo. Needs `work_root` resolved first (above).
        self.staffing = expand(self.staffing) or str(
            pathlib.Path(self.work_root) / "staffing.json")
        return self

    @property
    def state(self) -> pathlib.Path:
        return pathlib.Path(self.work_root) / "state"

    @property
    def night_log(self) -> pathlib.Path:
        return pathlib.Path(self.work_root) / "NIGHT_LOG.md"

    @property
    def events_log(self) -> pathlib.Path:
        # Machine-readable JSONL mirror of NIGHT_LOG.md (a sibling file). It is
        # WRITTEN only and never read on any control path -- purely diagnostic,
        # so it can never affect resume semantics.
        return pathlib.Path(self.work_root) / "events.jsonl"

    @property
    def report(self) -> pathlib.Path:
        return pathlib.Path(self.work_root) / "STATUS_REPORT.md"

    @property
    def stop_file(self) -> pathlib.Path:
        # global STOP halts every product; per-product STOP halts just this one
        return pathlib.Path(self.work_root) / "STOP"


def load_config(path: str) -> ProductConfig:
    data = json.loads(pathlib.Path(path).expanduser().read_text())
    known = {f.name for f in dataclasses.fields(ProductConfig)}
    cfg = ProductConfig(**{k: v for k, v in data.items() if k in known})
    cfg.resolve()
    pathlib.Path(cfg.work_root).mkdir(parents=True, exist_ok=True)
    cfg.state.mkdir(parents=True, exist_ok=True)
    return cfg


def global_stop() -> bool:
    return (FOUNDRY / "STOP").exists()


def stopping(cfg: ProductConfig) -> bool:
    return global_stop() or cfg.stop_file.exists()


# --------------------------------------------------------------------------- #
# Utilities
# --------------------------------------------------------------------------- #
def now() -> str:
    return dt.datetime.now().strftime("%m-%d %H:%M:%S")


# Typed machine-readable events (roadmap item 10 -- the on-mission completion).
# The foundry's ~17 `log()` messages are highly regular and their load-bearing
# tokens are stable in the source (`SHIPPED`, `reverted`, `POSTRELEASE`,
# `backing off`, `STOP requested`, ...). `classify_event` stamps a stable
# semantic `kind` onto every `events.jsonl` record (via `log()`'s best-effort
# mirror) so a dashboard / cron-alert / the reporter can FILTER by event type
# ("all ships", "all reverts", "all backoffs", "all post-release verdicts")
# instead of re-parsing the free-form prose `msg` -- exactly the brittle
# text-parsing the read-only JSON surface (iters 19-25) was built to eliminate.
#
# Matching is lowercase-substring, FIRST rule wins, so order is load-bearing:
# the specific verdicts (`ship`/`revert`/`postrelease`) precede the generic
# boundary lines (`iteration`/`stage`) so a verdict is never shadowed. NOTE the
# `ship` token is `"shipped"` (NOT `"ship"`), so "...WITHOUT ship (reverted...)"
# correctly classifies as `revert`, not `ship`.
EVENT_KIND_DEFAULT = "info"
EVENT_KIND_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ship", ("shipped",)),
    ("revert", ("reverted",)),
    ("postrelease", ("postrelease", "post-release")),
    ("timing", ("suite wall-time",)),
    ("backoff", ("backing off", "cooling down")),
    ("stop", ("stop requested", "stop honored")),
    ("lifecycle", ("foundry started", "foundry stopped")),
    ("fix", ("fix pass",)),
    ("iteration", ("iteration",)),
    ("stage", ("attempt", "produced", "no output file")),
)


def classify_event(msg: str) -> str:
    """Return a stable semantic ``kind`` for a foundry ``log()`` message.

    Pure and total: lowercases ``msg`` once, then returns the kind of the FIRST
    ``EVENT_KIND_RULES`` entry any of whose (lowercase) substrings occur in it;
    falls back to ``EVENT_KIND_DEFAULT`` (``"info"``) when nothing matches
    (including the empty string). Both module globals are looked up HERE, by bare
    name, at CALL time -- never captured as def-time defaults -- so a
    ``monkeypatch.setattr(foundry, "EVENT_KIND_RULES", ...)`` bites. It touches no
    I/O and never raises, so the best-effort ``emit_event`` mirror in ``log()`` can
    compute it inside its existing try/except with zero risk to the durable
    NIGHT_LOG write. Purely additive + off every control path: nothing in the
    pipeline branches on the result.
    """
    low = (msg or "").lower()
    for kind, needles in EVENT_KIND_RULES:
        if any(needle in low for needle in needles):
            return kind
    return EVENT_KIND_DEFAULT


def emit_event(events_path: pathlib.Path, event: str, /, **fields) -> None:
    """Append ONE JSON object (one line) to the machine-readable event log.

    Why: the human NIGHT_LOG timeline is prose a person reads, but a dashboard
    or the periodic reporter needs a stable, ``json.loads``-able record per
    event. This mirrors each timeline entry as ``{"ts", "event", ...fields}``
    JSONL so downstream tooling never has to re-parse free-form markdown.

    Design choices that matter:
      * ``ts`` is a timezone-AWARE UTC ISO-8601 instant (NOT the naive local
        ``now()`` used for the human line) so machine events sort/compare
        unambiguously across timezones.
      * The reserved ``ts``/``event`` keys are stamped LAST, so a caller-supplied
        ``ts=``/``event=`` in ``**fields`` can never shadow the real timestamp or
        the positional ``event``. ``event`` is POSITIONAL-ONLY (note the ``/``) so
        an ``event=`` keyword lands harmlessly in ``**fields`` (then loses to the
        positional value) rather than raising a "multiple values" ``TypeError``.
      * ``default=str`` coerces any non-serializable field value to its string
        form, so a stray object in the payload can never raise mid-emit.
      * Parents are auto-created and the write is append-only, so earlier lines
        are never rewritten and order is preserved.
    """
    events_path = pathlib.Path(events_path)
    events_path.parent.mkdir(parents=True, exist_ok=True)
    record = dict(fields)
    record["event"] = event
    record["ts"] = dt.datetime.now(dt.timezone.utc).isoformat()
    with events_path.open("a") as f:
        f.write(json.dumps(record, default=str) + "\n")


def log(cfg: ProductConfig, msg: str) -> None:
    line = f"- `{now()}` [{cfg.name}] {msg}"
    with cfg.night_log.open("a") as f:
        f.write(line + "\n")
    print(line, flush=True)
    # Best-effort machine-readable mirror. The durable human NIGHT_LOG write
    # above runs FIRST and must never be blocked by the JSON mirror: a disk
    # error (or a monkeypatched-to-raise emit_event in tests) can never crash a
    # shipped/in-flight iteration, so the emit is fully wrapped. Called by BARE
    # module name so ``monkeypatch.setattr(foundry, "emit_event", ...)`` seams.
    # `kind=classify_event(msg)` is computed INSIDE this try so even a classifier
    # bug can never reach the durable NIGHT_LOG write above; `event="log"` stays
    # UNCHANGED (backward compatible) -- `kind` is a purely ADDITIVE field.
    try:
        emit_event(cfg.events_log, "log", product=cfg.name, msg=msg,
                   kind=classify_event(msg))
    except Exception:
        pass


def sleep_interruptible(cfg: ProductConfig, seconds: int) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if stopping(cfg):
            return True
        time.sleep(min(30, max(1, end - time.monotonic())))
    return stopping(cfg)


def power_state() -> str:
    try:
        p = subprocess.run(["pmset", "-g", "batt"], capture_output=True,
                           text=True, timeout=15)
        return p.stdout.splitlines()[0].strip() if p.stdout else "?"
    except (subprocess.TimeoutExpired, OSError, IndexError):
        return "?"


def git(cfg: ProductConfig, *args: str) -> str:
    try:
        p = subprocess.run(["git", "-C", cfg.repo, *args],
                           capture_output=True, text=True, timeout=120)
        return (p.stdout + p.stderr).strip()
    except (subprocess.TimeoutExpired, OSError):
        return ""


def head_of_branch(cfg: ProductConfig) -> str:
    out = git(cfg, "ls-remote", "origin", f"refs/heads/{cfg.branch}")
    return out.split()[0][:9] if out else "?"


def next_iteration(cfg: ProductConfig) -> int:
    highest = 0
    for d in cfg.state.glob("iter-*"):
        try:
            highest = max(highest, int(d.name.split("-")[1]))
        except (IndexError, ValueError):
            pass
    return highest + 1


def contains(path: pathlib.Path, needle: str) -> bool:
    try:
        return needle in path.read_text()
    except OSError:
        return False


def revert_repo(cfg: ProductConfig, reason: str) -> None:
    git(cfg, "reset", "--hard", f"origin/{cfg.branch}")
    git(cfg, "clean", "-fd")
    log(cfg, f"repo reverted to origin/{cfg.branch} ({reason})")


# --------------------------------------------------------------------------- #
# Preflight (foundry doctor)
# --------------------------------------------------------------------------- #
@dataclasses.dataclass(frozen=True)
class Check:
    """One preflight check result.

    Frozen so a probe's verdict can't be mutated after the fact. `.detail` is
    always a human-readable, non-empty string so `doctor` output is actionable
    regardless of pass/fail.
    """
    name: str
    ok: bool
    detail: str


def check_power() -> Check:
    """Is the machine on AC power?

    WHY it's the first check: on battery macOS runs maintenance-sleep cycles
    that no `caffeinate` can block, so every agent-CLI run stalls (120s
    time-to-first-token) — the single most expensive unattended-run failure.
    Delegates to the `power_state` seam so the tester can force either verdict.
    """
    try:
        state = power_state()
        ok = "AC Power" in (state or "")
        return Check("power", ok, state or "power state unavailable")
    except Exception as exc:  # a probe never crashes the preflight — it FAILs
        return Check("power", False, f"power check errored: {exc!r}")


def check_agent() -> Check:
    """Does the configured agent-CLI binary exist at `AGENT_BIN`?

    Every stage shells out to this binary; a missing/unconfigured binary would
    burn all 4 attempts + backoffs producing nothing. Reads the module-level
    `AGENT_BIN` at call time so the tester can point it at an existing /
    non-existent path.
    """
    try:
        path = AGENT_BIN
        ok = bool(path) and pathlib.Path(path).exists()
        return Check("agent", ok, f"{path or '(unset)'} "
                     f"({'present' if ok else 'missing'})")
    except Exception as exc:
        return Check("agent", False, f"agent check errored: {exc!r}")


def check_uv() -> Check:
    """Is `uv` on PATH? The whole verify path is `uv run ... pytest`."""
    try:
        found = shutil.which("uv")
        return Check("uv", bool(found),
                     f"uv at {found}" if found else "uv not found on PATH")
    except Exception as exc:
        return Check("uv", False, f"uv check errored: {exc!r}")


def check_remote(cfg: ProductConfig) -> Check:
    """Is the git remote reachable (can we read origin/<branch>)?

    Delegates to the `head_of_branch` seam, which returns the sentinel `"?"`
    when `git ls-remote` can't reach origin. An unreachable remote means the
    final gate can neither push nor safely revert.
    """
    try:
        head = head_of_branch(cfg)
        ok = head != "?"
        return Check("remote", ok,
                     f"origin/{cfg.branch} at {head}" if ok
                     else f"origin/{cfg.branch} unreachable (ls-remote failed)")
    except Exception as exc:
        return Check("remote", False, f"remote check errored: {exc!r}")


def run_doctor(cfg: ProductConfig) -> list[Check]:
    """Run all four preflight probes in a stable order, exception-safe.

    Always returns exactly 4 Checks — [power, agent, uv, remote] — so the operator
    sees every result even if one probe itself raises (double-guarded here on
    top of each probe's own try/except).
    """
    probes = [
        ("power", check_power),
        ("agent", check_agent),
        ("uv", check_uv),
        ("remote", lambda: check_remote(cfg)),
    ]
    results: list[Check] = []
    for name, fn in probes:
        try:
            results.append(fn())
        except Exception as exc:
            results.append(Check(name, False, f"{name} check errored: {exc!r}"))
    return results


def doctor_ok(checks: list[Check]) -> bool:
    """True iff every check passed. An empty list is vacuously ready."""
    return all(c.ok for c in checks)


def run_doctor_cli(cfg: ProductConfig) -> int:
    """CLI entry: print one line per check + a summary; exit 0 iff all pass."""
    checks = run_doctor(cfg)
    for c in checks:
        print(f"[{'PASS' if c.ok else 'FAIL'}] {c.name}: {c.detail}")
    ok = doctor_ok(checks)
    passed = sum(1 for c in checks if c.ok)
    print(f"doctor: {passed}/{len(checks)} checks ok — "
          f"{'READY' if ok else 'NOT READY'}")
    return 0 if ok else 1


# --------------------------------------------------------------------------- #
# Single-brain launch preflight (`foundry single-brain`) -- roadmap item 14.
#
# The VISION names single-brain as a HARD constraint: one foundry per model-API
# account (the dispatcher serializes teams). The #1 OBSERVED live failure is a
# violation of exactly this -- two continuous dispatchers on one model-API account
# starve the shared token budget and BOTH stall ("Too many tokens" / 120s
# time-to-first-token). `doctor` (item 1) answers "is my machine ready?" and its
# 4-check contract is pinned by iter-01 tests, so a 5th check would regress them;
# the iter-06 watchdog only enforces single-brain at RESURRECTION time. This is
# the missing OPERATOR-launch preflight: a read-only, scriptable command a launch
# wrapper can gate on by exit code (0 SAFE / 1 CONFLICT / 2 UNKNOWN). It only
# REPORTS -- it never kills or signals a competing dispatcher (the operator
# decides). The process scan is funnelled through ONE monkeypatchable seam,
# `running_dispatchers`, exactly like `doctor`'s `power_state`/`head_of_branch`.
# --------------------------------------------------------------------------- #
def running_dispatchers(pattern: str = "dispatcher.py") -> tuple[int, ...]:
    """Return the PIDs of currently-running dispatcher processes.

    The REAL scan seam behind `foundry single-brain`: it looks in the process
    table for commands whose FULL command line contains `pattern` (default the
    dispatcher entrypoint filename) and returns their PIDs, or an empty tuple
    when none are running -- the SAFE case.

    WHY it is a single seam: like `check_uv`'s real `which` or `doctor`'s
    `power_state`, its live subprocess behavior is out of offline scope; the
    tester monkeypatches this function WHOLESALE so every `single_brain_cli`
    branch is forced offline with zero real `pgrep`.

    Contract: a NON-match is NOT an error -- `pgrep` exits 1 with empty output
    when nothing matches, which maps to the empty tuple. It RAISES only when the
    scan itself cannot be performed (e.g. `pgrep` missing -> `FileNotFoundError`,
    or `TimeoutExpired`), so the caller can tell "no dispatcher running" (empty
    tuple, SAFE) apart from "I could not check" (raise, UNKNOWN). It does NOT
    exclude the current process: the `"dispatcher.py"` pattern never matches the
    `foundry.py single-brain` invocation, and `pgrep` already omits its own PID.
    """
    proc = subprocess.run(["pgrep", "-f", pattern],
                          capture_output=True, text=True, timeout=15)
    pids: list[int] = []
    for line in proc.stdout.splitlines():
        token = line.strip()
        if token.isdigit():
            pids.append(int(token))
    return tuple(pids)


@dataclasses.dataclass(frozen=True)
class SingleBrainStatus:
    """A single-brain launch-preflight verdict (item 14).

    Frozen so a computed verdict can't be mutated after the fact (value equality
    for free, matching the other pure cores). Exactly two STORED fields; every
    verdict signal below is a PURE derivation of them, so the human `render()`,
    the `verdict` token and the scriptable `exit_code` follow deterministically
    and can never disagree.

    Fields:
      * `pids` -- PIDs of dispatcher processes the scan found (empty == none).
      * `scan_error` -- `None` on a successful scan; the error text when the scan
        itself could not be performed. An unperformed scan can neither confirm
        nor deny a competing brain, so it makes the verdict UNKNOWN (not SAFE).
    """
    pids: tuple[int, ...]
    scan_error: str | None

    @property
    def unknown(self) -> bool:
        """True iff the scan could not be performed (`scan_error` is set). When
        unknown we make NO safe/conflict claim -- we simply could not check."""
        return self.scan_error is not None

    @property
    def conflict(self) -> bool:
        """True iff the scan SUCCEEDED and found >=1 dispatcher already running
        (a second brain would starve the shared token budget). Never True when
        `unknown` -- an unperformed scan is not a conflict."""
        return not self.unknown and len(self.pids) >= 1

    @property
    def safe(self) -> bool:
        """True iff the scan SUCCEEDED and found NO dispatcher running -- safe to
        launch one brain. Never True when `unknown`. Whenever `unknown` is False
        EXACTLY one of `safe`/`conflict` is True (they partition len(pids)==0)."""
        return not self.unknown and len(self.pids) == 0

    @property
    def verdict(self) -> str:
        """The single human token for the current state -- UNKNOWN first (an
        unperformed scan dominates), else CONFLICT, else SAFE. ONE source of
        truth for both `render()` and `exit_code`, so they can never drift."""
        if self.unknown:
            return "UNKNOWN"
        return "CONFLICT" if self.conflict else "SAFE"

    @property
    def exit_code(self) -> int:
        """Scriptable verdict a launch wrapper can gate on: `2` UNKNOWN / `1`
        CONFLICT / `0` SAFE. Derived from `verdict` so the code and the printed
        token are always consistent."""
        return {"SAFE": 0, "CONFLICT": 1, "UNKNOWN": 2}[self.verdict]

    def render(self) -> str:
        """A deterministic, non-empty, multi-line human report that NEVER raises.

        Always names the verdict. In CONFLICT it lists EVERY offending PID from
        `pids`; in UNKNOWN it includes the `scan_error` text; in SAFE it states
        that no dispatcher is running. The final line echoes the verdict token
        and its exit code so the text and the scriptable code stay visibly in
        sync."""
        lines = [f"foundry single-brain: {self.verdict}"]
        if self.unknown:
            lines.append(
                f"  could not check for a running dispatcher: {self.scan_error}")
            lines.append("  verify manually before launching a brain, or re-run "
                         "once the process scan works.")
        elif self.conflict:
            lines.append(f"  {len(self.pids)} dispatcher(s) already running -- "
                         "do NOT start a second brain:")
            for pid in self.pids:
                lines.append(f"    pid {pid}")
            lines.append("  a second dispatcher would starve the shared "
                         "model-API token budget (both would stall).")
        else:
            lines.append("  no dispatcher is running -- safe to launch one brain.")
        lines.append(f"verdict: {self.verdict} (exit {self.exit_code})")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """A pure, JSON-safe launch-preflight verdict for machine consumers --
        a launch wrapper / cron / CI gate (roadmap item 10's "machine-readable
        status for dashboards / the reporter"), mirroring iter-19's
        `StatusSummary.to_dict()` and the other read-only probes.

        Returns EXACTLY 7 keys in a fixed order: the two STORED fields first --
        `pids` (as a JSON ARRAY of ints in the SAME order as the tuple, so the
        payload round-trips through `json.loads(json.dumps(...))` where a tuple
        would not) and `scan_error` verbatim -- followed by the five DERIVED
        values, each REUSING the frozen properties (`unknown`/`conflict`/`safe`/
        `verdict`/`exit_code`) so the JSON can never disagree with what
        `render()` prints or the exit code returns. Every value is JSON-native
        (list[int] / str / None / bool / int), so `json.dumps(...)` never raises.
        Pure: touches no filesystem and does not mutate the frozen status."""
        return {
            "pids": list(self.pids),
            "scan_error": self.scan_error,
            "unknown": self.unknown,
            "conflict": self.conflict,
            "safe": self.safe,
            "verdict": self.verdict,
            "exit_code": self.exit_code,
        }


def summarize_single_brain(pids: tuple[int, ...] = (), *,
                           scan_error: str | None = None) -> SingleBrainStatus:
    """Pure constructor for a `SingleBrainStatus` (item 14).

    A total, side-effect-free wrapper that packs a scan result into the frozen
    verdict: `pids` is normalised to `tuple(pids)` (accepts any iterable of ints)
    and `scan_error` is stored verbatim. Kept separate from `single_brain_cli`
    so the decision core is a pure function the tester can drive with zero
    filesystem/subprocess -- e.g. `summarize_single_brain((123, 456))` ->
    conflict / exit 1; `summarize_single_brain((), scan_error="no pgrep")` ->
    unknown / exit 2. Never raises."""
    return SingleBrainStatus(pids=tuple(pids), scan_error=scan_error)


def single_brain_cli(pattern: str = "dispatcher.py",
                     as_json: bool = False) -> int:
    """On-demand launch preflight: report whether a dispatcher is ALREADY running.

    Calls the `running_dispatchers` seam by BARE name (so a
    `monkeypatch.setattr(foundry, "running_dispatchers", ...)` in a test bites)
    inside a guard: a normal return builds a SAFE/CONFLICT status from the PIDs
    (`scan_error=None`); ANY raised exception is CAUGHT and turned into an
    UNKNOWN status carrying the exception text -- a failed scan must never crash
    the preflight, it degrades to "could not check".

    With `as_json=True` the entire stdout is ONE `json.dumps(status.to_dict(),
    indent=2)` document (the machine contract a launch wrapper / CI gate parses
    for the *why* -- which PIDs conflict or the scan error -- without brittly
    reading `render()`); the default `as_json=False` is byte-for-byte the iter-24
    human `render()` text. Either way the RETURN value is the same scriptable
    `status.exit_code` (0 SAFE / 1 CONFLICT / 2 UNKNOWN). Writes NOTHING to disk
    -- purely a read-only report; `--json` only ADDS a payload, it changes
    nothing about the verdict or the default human path."""
    try:
        pids = running_dispatchers(pattern)
        status = summarize_single_brain(pids, scan_error=None)
    except Exception as exc:  # a failed scan degrades to UNKNOWN, never crashes
        status = summarize_single_brain((), scan_error=str(exc))
    print(json.dumps(status.to_dict(), indent=2) if as_json else status.render())
    return status.exit_code


# --------------------------------------------------------------------------- #
# Composite LAUNCH preflight (`foundry preflight`) -- roadmap iter 28.
#
# The dispatcher LAUNCH is where the two most expensive unattended-run failures
# are gated: (a) a broken environment (battery / no `uv` / missing agent CLI /
# unreachable remote -- `doctor`, iter 01) and (b) a SECOND competing brain on
# one model-API account starving the shared token budget (the VISION's HARD
# single-brain constraint + the #1 OBSERVED live failure -- `single-brain`,
# iter 24). Today those are TWO commands with DIFFERENT exit-code semantics, so
# a launch wrapper must hand-combine them and a shell `&&` collapses
# `single-brain`'s UNKNOWN(2) and `doctor`'s NOT-READY(1) into one
# undifferentiated non-zero -- losing the actionable CAUTION ("env fine, I just
# could not check for a rival brain, verify manually") vs NO-GO ("hard blocker,
# do NOT launch") distinction. `foundry preflight` unifies both into ONE
# three-way GO / NO-GO / CAUTION verdict (human text + `--json`). It COMPOSES the
# existing frozen cores and adds NO new I/O seam; like `single-brain` it only
# REPORTS (never kills/signals a competing dispatcher -- the operator decides)
# and writes NOTHING.
# --------------------------------------------------------------------------- #
@dataclasses.dataclass(frozen=True)
class PreflightSummary:
    """A composite LAUNCH-preflight verdict combining env + single-brain.

    Frozen so a computed verdict can't be mutated after the fact (value equality
    for free, matching the other pure cores). Exactly two STORED fields -- the
    doctor `checks` and the single-brain `brain` status -- and every signal below
    is a PURE derivation of them, so the human `render()`, the three-way
    `verdict` token, the scriptable `exit_code`, and the `to_dict()` payload
    follow deterministically and can never disagree.

    Fields:
      * `checks` -- the doctor `Check`s (`[power, agent, uv, remote]`), stored as
        a tuple in scan order.
      * `brain` -- the `SingleBrainStatus` from the running-dispatcher scan.
    """
    checks: tuple[Check, ...]
    brain: SingleBrainStatus

    @property
    def env_ready(self) -> bool:
        """True iff EVERY stored doctor check passed. Mirrors `doctor_ok` -- an
        EMPTY `checks` tuple is vacuously ready (`all(())` is True)."""
        return all(c.ok for c in self.checks)

    @property
    def verdict(self) -> str:
        """The single composite token, evaluated in a TOTAL fixed order so a hard
        blocker ALWAYS dominates: NO-GO iff the env is not ready OR a competing
        brain is confirmed (`brain.conflict`); else CAUTION iff the brain scan
        could not run (`brain.unknown` -- env fine, verify the rival manually);
        else GO. ONE source of truth for both `render()`'s last line and
        `exit_code`, so they can never drift."""
        if not self.env_ready or self.brain.conflict:
            return "NO-GO"
        if self.brain.unknown:
            return "CAUTION"
        return "GO"

    @property
    def exit_code(self) -> int:
        """Scriptable verdict a launch wrapper gates on: `0` GO / `1` NO-GO /
        `2` CAUTION. Derived from `verdict` so the code and the printed token are
        always consistent."""
        return {"GO": 0, "NO-GO": 1, "CAUTION": 2}[self.verdict]

    def render(self) -> str:
        """A deterministic, non-empty, multi-line human report that NEVER raises.

        Names the composite verdict, states whether the env is READY, lists one
        `[PASS]`/`[FAIL] <name>: <detail>` line per stored doctor check, echoes
        the single-brain verdict token (`SAFE`/`CONFLICT`/`UNKNOWN`), and closes
        with `verdict: <VERDICT> (exit <exit_code>)` as its LAST non-empty line so
        the text and the scriptable code stay visibly in sync."""
        lines = [f"foundry preflight: {self.verdict}",
                 f"  env: {'READY' if self.env_ready else 'NOT READY'}"]
        for c in self.checks:
            lines.append(
                f"    [{'PASS' if c.ok else 'FAIL'}] {c.name}: {c.detail}")
        lines.append(f"  single-brain: {self.brain.verdict}")
        lines.append(f"verdict: {self.verdict} (exit {self.exit_code})")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """A pure, JSON-safe composite verdict for machine consumers -- a launch
        wrapper / cron / CI gate.

        Returns EXACTLY 5 keys in a fixed order: `checks` (a JSON array of
        `{"name","ok","detail"}` objects in the SAME order as the stored checks --
        `Check` has no `to_dict`, so its three fields are projected explicitly),
        the DERIVED `env_ready`, the nested `brain` (REUSING
        `SingleBrainStatus.to_dict()`), and the DERIVED `verdict`/`exit_code`
        (REUSING the frozen properties, never re-derived) so the payload can never
        disagree with `render()` or the exit code. Every value is JSON-native
        (list / bool / dict / str / int), so `json.dumps(...)` never raises and
        the dict round-trips through `json.loads(json.dumps(...))`. Pure:
        touches no filesystem and does not mutate the frozen summary."""
        return {
            "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail}
                       for c in self.checks],
            "env_ready": self.env_ready,
            "brain": self.brain.to_dict(),
            "verdict": self.verdict,
            "exit_code": self.exit_code,
        }


def summarize_preflight(*, checks: tuple[Check, ...],
                        brain: SingleBrainStatus) -> PreflightSummary:
    """Pure keyword-only constructor for a `PreflightSummary` (iter 28).

    A total, side-effect-free composer: `checks` is normalised to `tuple(checks)`
    (accepts any iterable of `Check`s -- like `summarize_single_brain` normalises
    `pids`) and `brain` is stored verbatim. Kept separate from `preflight_cli` so
    the decision core is a pure function the tester can drive with zero
    filesystem/subprocess -- e.g. `summarize_preflight(checks=(),
    brain=summarize_single_brain(()))` -> GO / exit 0. Deterministic (equal
    inputs -> an EQUAL summary by frozen value equality) and never raises."""
    return PreflightSummary(checks=tuple(checks), brain=brain)


def preflight_cli(cfg: ProductConfig, pattern: str = "dispatcher.py",
                  as_json: bool = False) -> int:
    """On-demand composite LAUNCH preflight: env (`doctor`) + single-brain in ONE
    three-way GO / NO-GO / CAUTION verdict.

    Calls `run_doctor(cfg)` and the `running_dispatchers` scan by BARE module name
    (so a `monkeypatch.setattr(foundry, "run_doctor"/"running_dispatchers", ...)`
    in a test bites) -- adding NO new seam. The brain scan is GUARDED exactly like
    `single_brain_cli`: a normal return builds a SAFE/CONFLICT status; ANY raised
    exception is CAUGHT and degraded to an UNKNOWN status carrying the error text,
    so a failed scan can never crash the launch preflight (it becomes CAUTION when
    the env is ready, else the env blocker keeps it NO-GO -- a confirmed env
    blocker is never downgraded to CAUTION). `pattern` is forwarded to the scan.

    With `as_json=True` the entire stdout is ONE `json.dumps(summary.to_dict(),
    indent=2)` document; the default `as_json=False` prints `summary.render()`.
    Either way the RETURN value is the same scriptable `summary.exit_code`
    (0 GO / 1 NO-GO / 2 CAUTION). Writes NOTHING to disk -- purely a read-only
    report; the operator (not this command) decides what to do about a competing
    brain."""
    checks = run_doctor(cfg)
    try:
        pids = running_dispatchers(pattern)
        brain = summarize_single_brain(pids, scan_error=None)
    except Exception as exc:  # a failed scan degrades to UNKNOWN, never crashes
        brain = summarize_single_brain((), scan_error=str(exc))
    summary = summarize_preflight(checks=checks, brain=brain)
    print(json.dumps(summary.to_dict(), indent=2)
          if as_json else summary.render())
    return summary.exit_code


# --------------------------------------------------------------------------- #
# Bounded learnings digest (roadmap item 2, bite 1/2).
#
# `LEARNINGS.md` grows unbounded, so a fresh agent that reads it to learn what
# already shipped burns more of its context window every iteration — directly
# eroding the VISION's promise of reliable continuous iteration. `learnings_digest`
# is the deterministic core: pure text in, bounded text out (the pinned `## Patterns`
# head verbatim + the most-recent role-tagged lessons under an accurate count
# header). `learnings_cli` is the operator-facing seam that reads the file and
# prints it. NOTHING on a control path reads the digest yet — wiring it into
# `build_prompt` is bite 2 (a later iteration); this bite is purely additive.
# --------------------------------------------------------------------------- #
def learnings_digest(text: str, recent: int = 12) -> str:
    """Reduce a role-tagged learnings log to a bounded, high-signal view.

    Returns the pinned ``## Patterns`` head verbatim (the durable curated rules)
    followed by an accurate ``## Recent lessons (last N of M)`` header and only
    the ``recent`` most-recent lesson lines. Pure — no filesystem/subprocess/
    network — so it is fully offline-testable and can back both the CLI and, in
    a later bite, the prompt builder.

    A *lesson line* is any line whose left-stripped form starts with ``- [`` (the
    ``- [ROLE iterNN] ...`` bullet). A *pattern bullet* is a plain ``- `` bullet
    that is NOT a lesson line, so curated head rules are never miscounted. The
    ``## Patterns`` head runs from its heading up to (exclusive) the first later
    ``## `` heading OR the first lesson line, whichever comes first — robust even
    when a file omits the ``## Chronological lessons`` marker. With no ``## Patterns``
    section a two-line placeholder head is emitted so the output shape is stable.
    """
    lines = text.splitlines()

    def is_lesson(line: str) -> bool:
        return line.lstrip().startswith("- [")

    def is_h2(line: str) -> bool:
        return line.lstrip().startswith("## ")

    # Pinned head: verbatim from `## Patterns` to the next `## ` heading or the
    # first lesson line (whichever is first); a placeholder when absent.
    head_start = next(
        (i for i, ln in enumerate(lines)
         if ln.lstrip().startswith("## Patterns")),
        None,
    )
    if head_start is None:
        head = ["## Patterns", "(none recorded yet)"]
    else:
        head = [lines[head_start]]
        for ln in lines[head_start + 1:]:
            if is_h2(ln) or is_lesson(ln):
                break
            head.append(ln)

    # Bounded tail: every lesson line in document order, keep the last `recent`.
    lessons = [ln for ln in lines if is_lesson(ln)]
    total = len(lessons)
    kept = lessons[max(0, total - recent):]

    parts = [*head, "", f"## Recent lessons (last {len(kept)} of {total})", *kept]
    return "\n".join(parts)


def learnings_cli(cfg: ProductConfig, recent: int = 12) -> int:
    """CLI entry: print the bounded learnings digest for a product; return 0.

    Reads ``cfg.learnings`` defensively — a missing file yields an empty-text
    digest (the ``## Patterns`` placeholder + a zero-count header) instead of a
    ``FileNotFoundError`` — so it works on a product that has recorded nothing
    yet. Purely diagnostic: reads one file, prints, exits 0.
    """
    path = pathlib.Path(cfg.learnings)
    text = path.read_text() if path.exists() else ""
    print(learnings_digest(text, recent=recent))
    return 0


# --------------------------------------------------------------------------- #
# AGENTS.md house-rules artifact (roadmap item 3, bite 1/2).
#
# Every stage is a FRESH single-shot agent that starts with zero context. An
# `AGENTS.md` at a product repo's root is auto-loaded by the agent CLI, so the
# durable house rules reach every stage without re-learning. `render_agents_md`
# is the deterministic core: it wraps the already-tested bounded `learnings_digest`
# (the pinned `## Patterns` head + recent role-tagged lessons) in a product-titled
# heading and an auto-generated banner. It is PURE — no filesystem/subprocess/
# network/clock — so it is fully offline-testable. `agents_cli` is the on-demand
# operator seam that reads the learnings file and writes (or prints) the doc.
# NOTHING on a control path calls this yet — auto-refreshing `<repo>/AGENTS.md`
# at ship time is bite 2 (a later iteration); this bite is purely additive.
# --------------------------------------------------------------------------- #
def render_agents_md(learnings_text: str, product_name: str,
                     recent: int = 12) -> str:
    """Render a self-contained ``AGENTS.md`` house-rules doc for a product.

    Wraps the bounded ``learnings_digest`` in a product-titled top heading and an
    auto-generated banner that tells any reader how to refresh the file and not to
    hand-edit it. Pure — no filesystem/subprocess/network/clock — so identical
    arguments always return byte-identical output and it can never crash (an empty
    ``learnings_text`` yields the digest's stable placeholder). The embedded
    ``learnings_digest(learnings_text, recent=recent)`` appears verbatim, so the
    house rules are exactly the digest's high-signal content.
    """
    banner = (
        "> This file is auto-generated by `foundry agents` from this product's "
        "LEARNINGS.md. Do NOT hand-edit it — it is regenerated on demand; re-run "
        "`foundry agents` to refresh it after new lessons land."
    )
    parts = [
        f"# {product_name} — house rules for agents",
        "",
        banner,
        "",
        learnings_digest(learnings_text, recent=recent),
    ]
    return "\n".join(parts)


def agents_cli(cfg: ProductConfig, recent: int = 12,
               print_only: bool = False) -> int:
    """CLI entry: render a product's ``AGENTS.md`` house-rules doc; return 0.

    Reads ``cfg.learnings`` defensively — a missing file yields the empty-text
    placeholder digest instead of a ``FileNotFoundError`` — so it works on a
    product that has recorded nothing yet. By default WRITES ``<cfg.repo>/AGENTS.md``
    (creating the repo dir first, so a valid config never fails on a first write);
    ``print_only`` writes the doc to stdout and touches NO file. Repo-agnostic: the
    target path derives only from ``cfg.repo``.
    """
    path = pathlib.Path(cfg.learnings)
    text = path.read_text() if path.exists() else ""
    doc = render_agents_md(text, cfg.name, recent=recent)
    if print_only:
        print(doc)
        return 0
    repo = pathlib.Path(cfg.repo)
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "AGENTS.md").write_text(doc)
    return 0


# --------------------------------------------------------------------------- #
# Spec-completeness + size guard (roadmap item 5 — COMPLETES the item).
#
# Oversized iterations are the foundry's #1 reliability failure mode: a feature
# too big for one context window blows the stage timeout, burns retries/backoff,
# and can strand a shift (the 3 engineer timeouts on repolens were the smell).
# `spec_lint` is the deterministic core: pure spec text in, a structural+size
# verdict out — no filesystem/subprocess/network/clock, so it is fully
# offline-testable. `lint_spec_cli` is the on-demand operator seam (read a file
# -> spec_lint -> print). NOTHING on a control path calls this yet; wiring it
# into the PM stage or a blocking gate touches control flow and is a later bite.
# The three tuning knobs below are module-level so `spec_lint` reads them at CALL
# time (a `monkeypatch.setattr(foundry, ...)` bites) and an operator can retune.
# --------------------------------------------------------------------------- #
REQUIRED_SPEC_SECTIONS = (
    "## Feature",
    "## Why",
    "## Expected Behaviors",
    "## Acceptance Criteria",
    "## Out of Scope",
    "## Size self-check",
)
SPEC_SIZE_WARN_CHARS = 16000   # a spec longer than this smells oversized
SPEC_MAX_BEHAVIORS = 20        # more behaviors than this smells oversized


@dataclasses.dataclass(frozen=True)
class SpecLint:
    """A structural + size lint verdict for a single PM spec (roadmap item 5).

    Frozen so a computed verdict can't be mutated after the fact, which also
    gives value-equality for free: two `spec_lint` calls on the same text hold
    equal fields, so they compare ``==`` (Behavior 1). The five stored fields are
    the raw measurements taken from the spec at call time; the four properties
    are pure derivations, so the whole verdict follows deterministically from
    what was measured (the CLI adds no independent logic on top).
    """
    char_count: int
    num_behaviors: int
    missing_sections: tuple[str, ...]
    size_over_chars: bool
    size_over_behaviors: bool

    @property
    def sections_ok(self) -> bool:
        """True iff no required heading is missing."""
        return self.missing_sections == ()

    @property
    def size_ok(self) -> bool:
        """True iff the spec is within BOTH size thresholds."""
        return not (self.size_over_chars or self.size_over_behaviors)

    @property
    def ok(self) -> bool:
        """The combined verdict: structurally complete AND right-sized."""
        return self.sections_ok and self.size_ok

    @property
    def verdict(self) -> str:
        """The operator-facing token: ``"OK"`` when ok, else ``"REVIEW"``."""
        return "OK" if self.ok else "REVIEW"


def _count_expected_behaviors(lines: list[str]) -> int:
    """Count ordered-list items inside the ``## Expected Behaviors`` section only.

    The section spans from the FIRST line whose stripped form is
    ``## Expected Behaviors`` (or starts with ``## Expected Behaviors ``),
    exclusive, up to (exclusive) the next line whose stripped form starts with
    ``## `` (or end-of-text). A counted line is one whose left-stripped form
    starts with one-or-more ASCII digits immediately followed by a ``.`` (``1.``,
    ``12.``). ASCII-only on purpose (``str.isdigit`` would also match non-ASCII
    numerals). Absent section -> ``0``. Helper, so `spec_lint` stays flat.
    """
    start = None
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s == "## Expected Behaviors" or s.startswith("## Expected Behaviors "):
            start = i
            break
    if start is None:
        return 0
    count = 0
    for ln in lines[start + 1:]:
        if ln.strip().startswith("## "):
            break
        item = ln.lstrip()
        digits = 0
        for ch in item:
            if ch in "0123456789":
                digits += 1
            else:
                break
        if digits and len(item) > digits and item[digits] == ".":
            count += 1
    return count


def spec_lint(spec_text: str) -> SpecLint:
    """Score a PM spec for structural completeness + size (pure, total).

    Reads the three module knobs — ``REQUIRED_SPEC_SECTIONS``,
    ``SPEC_SIZE_WARN_CHARS``, ``SPEC_MAX_BEHAVIORS`` — AT CALL TIME (not captured
    at import / as default args) so patching any of them changes a subsequent
    call's verdict. Performs NO filesystem/subprocess/network/clock access, never
    raises for any ``spec_text`` (including ``""``), and is deterministic, so the
    same input always yields an equal ``SpecLint``.

    A required heading ``H`` is PRESENT iff some line, after ``str.strip()``,
    equals ``H`` or starts with ``H + " "`` (so a trailing parenthetical like
    ``## Size self-check (dogfooded)`` still counts as ``## Size self-check``).
    """
    lines = spec_text.splitlines()

    def present(heading: str) -> bool:
        for ln in lines:
            s = ln.strip()
            if s == heading or s.startswith(heading + " "):
                return True
        return False

    missing = tuple(h for h in REQUIRED_SPEC_SECTIONS if not present(h))
    char_count = len(spec_text)
    num_behaviors = _count_expected_behaviors(lines)
    return SpecLint(
        char_count=char_count,
        num_behaviors=num_behaviors,
        missing_sections=missing,
        size_over_chars=char_count > SPEC_SIZE_WARN_CHARS,
        size_over_behaviors=num_behaviors > SPEC_MAX_BEHAVIORS,
    )


def lint_spec_cli(path: str) -> int:
    """On-demand CLI: lint a PM spec file for completeness + size.

    Reads the file at ``path``, computes `spec_lint`, prints a human-readable
    report, and returns ``0`` (ok) / ``1`` (incomplete or oversized) / ``2``
    (file not found). Writes NOTHING to disk. A thin wrapper over the pure core:
    it adds no lint logic beyond read -> `spec_lint` -> format, so the printed
    verdict/char/behavior figures always match the ``SpecLint`` fields. A missing
    file returns ``2`` (distinct from a lint REVIEW) without letting a
    ``FileNotFoundError`` propagate.
    """
    p = pathlib.Path(path)
    if not p.exists():
        print(f"lint-spec: file not found: {path}")
        return 2
    lint = spec_lint(p.read_text())
    print(f"lint-spec: {path}")
    print(f"  char_count: {lint.char_count} (warn > {SPEC_SIZE_WARN_CHARS})")
    print(f"  num_behaviors: {lint.num_behaviors} (max {SPEC_MAX_BEHAVIORS})")
    if lint.missing_sections:
        print(f"  missing sections: {', '.join(lint.missing_sections)}")
    else:
        print("  missing sections: (none)")
    print(f"  size_over_chars: {lint.size_over_chars}  "
          f"size_over_behaviors: {lint.size_over_behaviors}")
    print(f"verdict: {lint.verdict}")
    return 0 if lint.ok else 1


# --------------------------------------------------------------------------- #
# Product-config linter (`foundry lint-config`) -- the CONFIG-validation
# complement to `doctor`'s ENV validation (item 9) and `lint-spec`'s SPEC
# validation (item 5).
#
# `doctor` answers "is my machine ready?" and `lint-spec` answers "is this PM
# spec complete + right-sized?", but NOTHING validates the PRODUCT CONFIG
# itself. A typo'd `vision`/`roadmap` path, a `repo` that is not a git
# repository, an empty `test_cmd`, a missing `roles_dir`, or -- a SAFETY problem
# -- an empty `allowed_push_repo` while `push_enabled` is true (the push guard
# then blocks EVERY ship, so a shipping loop can never ship) each degrade or
# silently break a shift with no early signal. `lint_config` is the
# deterministic, OFFLINE core: a `ProductConfig` in, a `ConfigLint` verdict out
# -- filesystem-existence + string checks ONLY (NO network; remote reachability
# stays `doctor`'s job), it NEVER raises, and it emits findings in a FIXED check
# order. `lint_config_cli` is the operator-facing seam (load a config -> lint it
# -> print the report; exit 0 OK-or-warnings-only / 1 config-errors / 2
# unreadable config), so a launch wrapper can lint a config once before
# committing a shift. DORMANT / on-demand only -- the pipeline/gate/dispatcher
# NEVER call it; it writes nothing (the only filesystem touch is `load_config`'s
# own work_root mkdir, shared by every --config command). It changes NO control
# flow, NO existing CLI, and NO running-loop semantics.
# --------------------------------------------------------------------------- #
@dataclasses.dataclass(frozen=True)
class ConfigFinding:
    """One leveled misconfiguration found in a `ProductConfig`.

    Frozen (value equality for free, matching the other verdict cores). `field`
    is the config field the problem concerns (`"name"`, `"repo"`,
    `"allowed_push_repo"`, `"test_cmd"`, `"roles_dir"`, `"vision"`, `"roadmap"`,
    `"quality_ref"`); `level` is `"error"` (breaks or silently defeats a shift)
    or `"warn"` (degraded but a shift can still run); `detail` is a human
    sentence naming the specific problem.
    """
    field: str
    level: str
    detail: str

    def to_dict(self) -> dict:
        """A pure, JSON-safe `{"field","level","detail"}` triple (fixed order)."""
        return {"field": self.field, "level": self.level, "detail": self.detail}


@dataclasses.dataclass(frozen=True)
class ConfigLint:
    """A lint verdict for one product config (the CONFIG-validation axis).

    Frozen so a computed verdict can't be mutated after the fact, which also
    gives value-equality for free. The two stored fields are the raw inputs --
    the linted config's identity (`config_path`) and the `findings` emitted in
    a fixed check order -- and EVERY count/verdict/exit-code is a PURE property
    over `findings`, so `render()` / `to_dict()` / the exit code can never
    disagree (single source of truth). A WARNING never fails the verdict -- only
    an ERROR does -- because a warning names a degraded-but-runnable config (a
    missing roadmap the PM creates on the first iteration) while an error names a
    config that breaks or silently defeats a shift.
    """
    config_path: str
    findings: tuple[ConfigFinding, ...]

    @property
    def errors(self) -> tuple[ConfigFinding, ...]:
        """The error-level findings, in check (fix) order."""
        return tuple(f for f in self.findings if f.level == "error")

    @property
    def warnings(self) -> tuple[ConfigFinding, ...]:
        """The warning-level findings, in check (fix) order."""
        return tuple(f for f in self.findings if f.level == "warn")

    @property
    def n_errors(self) -> int:
        """How many error-level findings there are."""
        return len(self.errors)

    @property
    def n_warnings(self) -> int:
        """How many warning-level findings there are."""
        return len(self.warnings)

    @property
    def ok(self) -> bool:
        """True iff there are NO errors (warnings alone still pass -- a
        warnings-only config can still run a shift)."""
        return self.n_errors == 0

    @property
    def verdict(self) -> str:
        """The operator-facing token: `"PROBLEMS"` if any error, else
        `"WARNINGS"` if any warning, else `"OK"` -- ONE source of truth for
        `render()`'s last line so text + exit code never drift."""
        if self.n_errors:
            return "PROBLEMS"
        if self.n_warnings:
            return "WARNINGS"
        return "OK"

    @property
    def exit_code(self) -> int:
        """Scriptable verdict: `1` iff any error (`not ok`), else `0` (clean OR
        warnings-only). The unreadable-config `2` is the CLI's concern, never a
        `ConfigLint`'s (a `ConfigLint` only exists once a config has loaded)."""
        return 0 if self.ok else 1

    def render(self) -> str:
        """A deterministic multi-line report.

        The FIRST line names the linted config (the CLI's black-box contract)
        and the LAST line is exactly `verdict: <TOKEN>` (`OK`/`WARNINGS`/
        `PROBLEMS`). Between them: an `errors`/`warnings` count line, then one
        `  [error] <field>: <detail>` line per error and one
        `  [warn] <field>: <detail>` line per warning (check order). A clean
        config lists NO finding lines yet still ends `verdict: OK`. Detail
        above the sentinel, so "last non-empty line == verdict" always holds."""
        lines = [
            f"foundry lint-config -- {self.config_path}",
            f"  errors: {self.n_errors}  warnings: {self.n_warnings}",
        ]
        for f in self.errors:
            lines.append(f"  [error] {f.field}: {f.detail}")
        for f in self.warnings:
            lines.append(f"  [warn] {f.field}: {f.detail}")
        lines.append(f"verdict: {self.verdict}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """A pure, JSON-safe serialization.

        Returns EXACTLY these keys in this fixed order: `config_path`,
        `findings` (a list of `{"field","level","detail"}` dicts in finding
        order), `n_errors`, `n_warnings`, `ok`, `verdict`, `exit_code`. Every
        value is JSON-native so `json.dumps(...)` never raises and the dict
        round-trips through `json.loads(json.dumps(...))`. Pure: no filesystem."""
        return {
            "config_path": self.config_path,
            "findings": [f.to_dict() for f in self.findings],
            "n_errors": self.n_errors,
            "n_warnings": self.n_warnings,
            "ok": self.ok,
            "verdict": self.verdict,
            "exit_code": self.exit_code,
        }


def lint_config(cfg: ProductConfig) -> ConfigLint:
    """Lint one product config for the misconfigurations that silently waste a
    shift or defeat the push guard (the pure core behind `foundry lint-config`).

    Deterministic + OFFLINE: filesystem-existence (`Path.exists()`) + string
    checks ONLY -- no network (remote reachability stays `doctor`'s job), no
    subprocess, no clock -- so it is fully offline-testable and NEVER raises for
    any `ProductConfig`. Findings are emitted in a FIXED check order (name,
    repo, allowed_push_repo, test_cmd, roles_dir, vision, roadmap, quality_ref)
    so the verdict is deterministic.

    Works on a RESOLVED COPY (`dataclasses.replace` then `.resolve()`, inside a
    guard so a pathological `~`-expansion can never raise) so `{FOUNDRY}`/`~` are
    expanded and empty path fields take their defaults (an empty `roles_dir`
    becomes `<foundry>/roles`) WITHOUT mutating the caller's config; `.resolve()`
    is a no-op on the absolute paths the pure tests construct, and it is
    idempotent on the already-resolved config the CLI passes.

    Levels: an ERROR names a config that breaks or silently defeats a shift (an
    empty `name`, a missing/non-git `repo`, an empty `test_cmd`, a missing
    `roles_dir`, a missing `vision` FILE, or -- the SAFETY case -- an empty
    `allowed_push_repo` while `push_enabled` is true, which makes the push guard
    block EVERY ship); a WARN names a degraded-but-runnable config (an unset
    `vision`, or a missing `roadmap`/`quality_ref` FILE -- the PM creates the
    roadmap on the first iteration). An empty (unset) `roadmap`/`quality_ref` is
    optional and produces no finding.
    """
    try:
        resolved = dataclasses.replace(cfg).resolve()
    except Exception:
        # `.resolve()` only touches strings and never hits the network, so the
        # sole theoretical raise is a `~`-expansion with no home directory. Fall
        # back to the config as-given rather than break the "never raises"
        # contract; in practice this branch is unreachable for a real config.
        resolved = cfg
    findings: list[ConfigFinding] = []

    if not resolved.name.strip():
        findings.append(ConfigFinding(
            "name", "error", "product name is empty"))

    repo = pathlib.Path(resolved.repo) if resolved.repo else None
    if repo is None or not repo.exists():
        findings.append(ConfigFinding(
            "repo", "error", f"repo path does not exist: {resolved.repo!r}"))
    elif not (repo / ".git").exists():
        findings.append(ConfigFinding(
            "repo", "error",
            f"repo is not a git repository (no .git entry): {resolved.repo!r}"))

    if resolved.push_enabled and not resolved.allowed_push_repo.strip():
        findings.append(ConfigFinding(
            "allowed_push_repo", "error",
            "allowed_push_repo is empty while push_enabled is true -- the push "
            "guard would block EVERY ship"))

    if not resolved.test_cmd.strip():
        findings.append(ConfigFinding(
            "test_cmd", "error",
            "test_cmd is empty (no quality-check command)"))

    if not resolved.roles_dir or not pathlib.Path(resolved.roles_dir).exists():
        findings.append(ConfigFinding(
            "roles_dir", "error",
            f"roles_dir does not exist: {resolved.roles_dir!r}"))

    if not resolved.vision:
        findings.append(ConfigFinding(
            "vision", "warn",
            "vision path is unset (no fixed product intent to hold to)"))
    elif not pathlib.Path(resolved.vision).exists():
        findings.append(ConfigFinding(
            "vision", "error",
            f"vision file does not exist: {resolved.vision!r}"))

    if resolved.roadmap and not pathlib.Path(resolved.roadmap).exists():
        findings.append(ConfigFinding(
            "roadmap", "warn",
            f"roadmap file does not exist yet: {resolved.roadmap!r} "
            "(the PM creates it on the first iteration)"))

    if resolved.quality_ref and not pathlib.Path(resolved.quality_ref).exists():
        findings.append(ConfigFinding(
            "quality_ref", "warn",
            f"quality_ref path does not exist: {resolved.quality_ref!r}"))

    return ConfigLint(config_path=resolved.name, findings=tuple(findings))


def lint_config_cli(config_path: str, as_json: bool = False) -> int:
    """On-demand CLI: lint a PRODUCT config file for misconfigurations.

    Loads the config at `config_path` INSIDE a try so an unreadable or
    invalid-JSON file returns `2` (distinct from a lint PROBLEMS=1) after
    printing a `lint-config: ...` diagnostic, without letting the load exception
    propagate. On a successful load it runs the pure `lint_config` core and
    prints the human `render()` (or, with `as_json=True`, one
    `json.dumps(to_dict())` document -- a single parseable doc), returning the
    `ConfigLint.exit_code` (0 OK-or-warnings-only / 1 config-errors). Writes
    nothing itself (the only filesystem touch is `load_config`'s own work_root
    mkdir, shared by every --config command). A thin wrapper over the pure core:
    it adds no lint logic beyond load -> `lint_config` -> format, so the printed
    verdict always matches the `ConfigLint` fields.
    """
    try:
        cfg = load_config(config_path)
    except Exception as exc:
        message = (f"lint-config: cannot read config {config_path}: "
                   f"{type(exc).__name__}: {exc}")
        if as_json:
            print(json.dumps({"config_path": config_path,
                              "error": message, "exit_code": 2}))
        else:
            print(message)
        return 2
    lint = lint_config(cfg)
    if as_json:
        print(json.dumps(lint.to_dict(), indent=2))
    else:
        print(lint.render())
    return lint.exit_code


def gather_config_lint(cfg: ProductConfig) -> ConfigLint:
    """Gather one product's config-lint verdict into a `ConfigLint` -- the
    per-product gather the `company-lint-config` roll-up drives (the exact analog
    of `gather_skipped_tests` for `company-skipped-tests` / `gather_test_quality`
    for `company-test-quality`).

    A thin seam that RETURNS `lint_config(cfg)`, calling the SHIPPED iter-60
    `lint_config` core by BARE module name so a `monkeypatch.setattr(foundry, ...)`
    in a test bites. Adds NO new I/O seam of its own -- `lint_config` already does
    its own offline `.exists()` checks -- and gives the company CLI ONE dedicated
    monkeypatchable seam decoupled from the `lint_config` that `lint_config_cli`
    calls directly, mirroring the "one per-product gather per company roll-up"
    idiom every other `company-*` member uses. `lint_config`/`lint_config_cli`
    stay byte-unchanged (a DRY change to either is out of scope). Writes NOTHING
    to disk (read-only)."""
    return lint_config(cfg)


# --------------------------------------------------------------------------- #
# Bench role-card linter (`foundry lint-bench`) -- the BENCH-facing sibling of
# `doctor` (env #0), `lint-spec` (spec #6), and `lint-config` (config #27), and
# the FIRST item of the org-design track (roadmap item 17). `roles/bench/` holds
# the hand-written role-cards the kickoff council staffs from; the later
# manifest-driven items (18 `lint-manifest`, 19 the manifest-driven pipeline)
# cannot trust a card as machine-readable unless SOMETHING enforces its shape,
# and today nothing does -- so a card drifts silently as it is edited. This is
# the missing enforcement: a pure `lint_bench_card(text) -> findings` core that
# checks a card against the FIXED 7-marker contract (a `# Bench role card:`
# title H1, `Status:`/`Model note:` line-start header fields, `Activation:`/
# `Tenure:` substrings, and the `## Mission` + `## I/O contract` sections),
# emitting one finding per missing marker in a FIXED order; a `lint_bench`
# dir-walker that skips the non-card `README.md` by basename and folds the
# per-card findings into a `BenchLint` verdict (exit 0 clean / 1 findings-or-
# parse-errors / 2 no-cards); and a thin `lint_bench_cli` that defaults to the
# foundry's OWN `roles/bench` so `foundry lint-bench` validates the live bench.
# Deterministic + OFFLINE (string checks + a dir glob only; NO network, NO
# subprocess, NO clock) and it NEVER raises for a card (an unreadable file is a
# recorded parse error, not an exception). DORMANT / on-demand only -- the
# pipeline/gate/dispatcher NEVER call it; it writes nothing. It changes NO
# control flow, NO existing CLI, and NO running-loop semantics.
# --------------------------------------------------------------------------- #

# The title H1 every well-formed bench card must open with. Kept as a module
# constant so the pure core, its docstrings, and any future manifest tooling
# name the same literal (single source of truth for the contract).
BENCH_CARD_TITLE_PREFIX = "# Bench role card:"


@dataclasses.dataclass(frozen=True)
class BenchCardFinding:
    """One missing REQUIRED marker in a single bench role-card.

    Frozen (value equality for free, matching the other verdict cores). `card`
    is the card's name (basename when walked from a dir, or the caller-supplied
    label for the pure core); `line` is always ``1`` -- a missing marker has no
    natural source location, so line 1 is the deterministic convention that
    still lets the report emit a `card:line` prefix; `requirement` is the exact
    contract token that is absent (`"title"`, `"Status:"`, `"Activation:"`,
    `"Tenure:"`, `"Model note:"`, `"## Mission"`, `"## I/O contract"`);
    `message` is a human sentence naming what to add.
    """
    card: str
    line: int
    requirement: str
    message: str

    def to_dict(self) -> dict:
        """A pure, JSON-safe `{"card","line","requirement","message"}` (fixed order)."""
        return {"card": self.card, "line": self.line,
                "requirement": self.requirement, "message": self.message}


@dataclasses.dataclass(frozen=True)
class BenchParseError:
    """A bench card file that could not be read (e.g. a permission error).

    Frozen. A parse error is a real problem (an unreadable card validates
    nothing yet is a card the bench claims to declare), so it gates the verdict
    like a finding -- but it is tracked separately from `BenchCardFinding`
    because it has no contract `requirement`, only the card name and the reason.
    """
    card: str
    message: str

    def to_dict(self) -> dict:
        """A pure, JSON-safe `{"card","message"}` pair (fixed order)."""
        return {"card": self.card, "message": self.message}


def lint_bench_card(text: str, card: str = "<card>") -> tuple[BenchCardFinding, ...]:
    """Lint ONE bench role-card's text against the FIXED 7-marker contract.

    Pure + deterministic + OFFLINE (string inspection only -- no filesystem, no
    network, no clock) and it NEVER raises. Returns one `BenchCardFinding` per
    ABSENT required marker, in this FIXED check order so the verdict is stable:
    `title`, `Status:`, `Activation:`, `Tenure:`, `Model note:`, `## Mission`,
    `## I/O contract`. A fully-compliant card returns an empty tuple.

    The marker predicates are deliberately DIFFERENT kinds, matching how the
    real cards are written (verified against all 11 shipped cards):

    * `title` -- the file's FIRST markdown H1 (the first line whose STRIPPED
      form starts with ``"# "``, which excludes ``"## "`` headings because
      ``"## x".startswith("# ")`` is False) must start with
      ``BENCH_CARD_TITLE_PREFIX``. A card with no H1, or whose first H1 is a
      different title (e.g. ``# The bench``), is flagged.
    * `Status:` / `Model note:` -- some line whose STRIPPED form STARTS WITH the
      token (they are their own lines in every card).
    * `Activation:` / `Tenure:` -- a raw SUBSTRING of the text (they live inline
      on the ``Status:`` line, so a line-start check would miss them).
    * `## Mission` / `## I/O contract` -- some line whose STRIPPED form EQUALS
      the heading EXACTLY, so a bare word ``Mission`` in prose or a ``# Mission``
      H1 does NOT satisfy it (exact-heading match, not substring).

    Every finding carries `line == 1` and the passed-in `card` name.
    """
    stripped = [ln.strip() for ln in text.splitlines()]
    findings: list[BenchCardFinding] = []

    # title: the FIRST H1 line must open with the bench-card prefix.
    first_h1 = next((s for s in stripped if s.startswith("# ")), None)
    if first_h1 is None or not first_h1.startswith(BENCH_CARD_TITLE_PREFIX):
        findings.append(BenchCardFinding(
            card, 1, "title",
            f"first H1 must start with {BENCH_CARD_TITLE_PREFIX!r} "
            "(the card must name the role)"))

    # Status: / Model note: -- line-start header fields.
    if not any(s.startswith("Status:") for s in stripped):
        findings.append(BenchCardFinding(
            card, 1, "Status:",
            "no line starting 'Status:' (the card's status/lifecycle field)"))

    # Activation: / Tenure: -- inline substrings (they share the Status line).
    if "Activation:" not in text:
        findings.append(BenchCardFinding(
            card, 1, "Activation:",
            "missing the 'Activation:' field (when this role activates)"))
    if "Tenure:" not in text:
        findings.append(BenchCardFinding(
            card, 1, "Tenure:",
            "missing the 'Tenure:' field (how long this role is seated)"))

    if not any(s.startswith("Model note:") for s in stripped):
        findings.append(BenchCardFinding(
            card, 1, "Model note:",
            "no line starting 'Model note:' (the model-choice guidance)"))

    # ## Mission / ## I/O contract -- exact-heading sections.
    if not any(s == "## Mission" for s in stripped):
        findings.append(BenchCardFinding(
            card, 1, "## Mission",
            "missing the '## Mission' section heading"))
    if not any(s == "## I/O contract" for s in stripped):
        findings.append(BenchCardFinding(
            card, 1, "## I/O contract",
            "missing the '## I/O contract' section heading"))

    return tuple(findings)


@dataclasses.dataclass(frozen=True)
class BenchLint:
    """A lint verdict for a whole bench directory of role-cards.

    Frozen so a computed verdict can't be mutated after the fact (value equality
    for free). The stored fields are the raw walk results -- the `bench_dir`
    linted, the `cards_scanned` count (non-`README.md` `*.md` files, readable or
    not), the `skipped` basenames (the non-card `README.md`), the flattened
    `findings` (each card's missing-marker findings in walk order), and the
    `parse_errors` (unreadable cards) -- and every count/verdict/exit-code is a
    PURE property, so `render()` / `to_dict()` / the exit code can never disagree
    (single source of truth). A parse error gates the verdict like a finding (an
    unreadable card validates nothing).
    """
    bench_dir: str
    cards_scanned: int
    skipped: tuple[str, ...]
    findings: tuple[BenchCardFinding, ...]
    parse_errors: tuple[BenchParseError, ...]

    @property
    def total_findings(self) -> int:
        """How many missing-marker findings there are across all cards."""
        return len(self.findings)

    @property
    def clean(self) -> bool:
        """True iff NO findings AND NO parse errors (every scanned card
        satisfies the contract and was readable)."""
        return not self.findings and not self.parse_errors

    @property
    def exit_code(self) -> int:
        """Scriptable verdict, DIR-scan model: `2` iff NOTHING to scan (no card
        files -- checked FIRST, so an empty/README-only dir is 2 not 0), else
        `1` iff any finding OR any parse error, else `0` clean. A parse error is
        a real problem (an unreadable card), NOT 'nothing to scan'."""
        if self.cards_scanned == 0:
            return 2
        if self.findings or self.parse_errors:
            return 1
        return 0

    @property
    def verdict(self) -> str:
        """The operator-facing token -- ONE source of truth for `render()`'s
        last line so text + exit code never drift: `"NO CARDS"` (exit 2),
        `"CARD ISSUES FOUND"` (exit 1), or `"OK"` (exit 0)."""
        code = self.exit_code
        if code == 2:
            return "NO CARDS"
        if code == 1:
            return "CARD ISSUES FOUND"
        return "OK"

    def render(self) -> str:
        """A deterministic multi-line report.

        The FIRST line names the linted bench dir and the LAST non-empty line is
        exactly `verdict: <TOKEN>` (`OK` / `CARD ISSUES FOUND` / `NO CARDS`).
        Between them: a scan-count line, then one `  <card>:<line> [<req>] <msg>`
        line per finding (walk order) and one `  <card>: unreadable: <msg>` line
        per parse error. A clean bench lists no finding lines yet still ends
        `verdict: OK`. Detail above the sentinel, so 'last non-empty line ==
        verdict' always holds."""
        lines = [
            f"foundry lint-bench -- {self.bench_dir}",
            f"  cards scanned: {self.cards_scanned}  skipped: {len(self.skipped)}"
            f"  findings: {self.total_findings}  "
            f"parse errors: {len(self.parse_errors)}",
        ]
        for f in self.findings:
            lines.append(f"  {f.card}:{f.line} [{f.requirement}] {f.message}")
        for e in self.parse_errors:
            lines.append(f"  {e.card}: unreadable: {e.message}")
        lines.append(f"verdict: {self.verdict}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """A pure, JSON-safe serialization.

        Returns EXACTLY these keys in this fixed order: `bench_dir`,
        `cards_scanned`, `skipped`, `findings` (a list of
        `{"card","line","requirement","message"}` dicts in walk order),
        `parse_errors` (a list of `{"card","message"}` dicts), `total_findings`,
        `clean`, `exit_code`, `verdict`. Every value is JSON-native so
        `json.dumps(...)` never raises and the dict round-trips through
        `json.loads(json.dumps(...))`."""
        return {
            "bench_dir": self.bench_dir,
            "cards_scanned": self.cards_scanned,
            "skipped": list(self.skipped),
            "findings": [f.to_dict() for f in self.findings],
            "parse_errors": [e.to_dict() for e in self.parse_errors],
            "total_findings": self.total_findings,
            "clean": self.clean,
            "exit_code": self.exit_code,
            "verdict": self.verdict,
        }


def lint_bench(bench_dir: str) -> BenchLint:
    """Walk a bench directory and lint every role-card against the contract.

    Deterministic + OFFLINE: globs `*.md` in `bench_dir` (sorted by name so the
    finding order is stable), SKIPS `README.md` by basename (it is documentation,
    not a card -- recorded in `.skipped`, NOT counted in `.cards_scanned`), and
    for every other `*.md` file reads its text and folds `lint_bench_card`'s
    findings in. An unreadable card is recorded as a `BenchParseError` (never
    raised) so one bad file can't abort the walk. A NONEXISTENT `bench_dir`
    globs to nothing -> `cards_scanned == 0` -> the `NO CARDS` verdict (never
    raises). Calls `lint_bench_card` by BARE module name so a test can
    monkeypatch it. Writes NOTHING to disk (read-only)."""
    d = pathlib.Path(bench_dir)
    skipped: list[str] = []
    findings: list[BenchCardFinding] = []
    parse_errors: list[BenchParseError] = []
    cards_scanned = 0
    for path in sorted(d.glob("*.md"), key=lambda p: p.name):
        name = path.name
        if name == "README.md":
            skipped.append(name)
            continue
        cards_scanned += 1
        try:
            text = path.read_text()
        except Exception as exc:  # unreadable card -> recorded, not raised
            parse_errors.append(BenchParseError(
                name, f"{type(exc).__name__}: {exc}"))
            continue
        findings.extend(lint_bench_card(text, name))
    return BenchLint(
        bench_dir=str(bench_dir),
        cards_scanned=cards_scanned,
        skipped=tuple(skipped),
        findings=tuple(findings),
        parse_errors=tuple(parse_errors),
    )


def lint_bench_cli(bench_dir: str | None = None, as_json: bool = False) -> int:
    """On-demand CLI: lint a bench directory of role-cards.

    Defaults `bench_dir` to the foundry's OWN `roles/bench` (so `foundry
    lint-bench` with no `--dir` validates the live bench), runs the pure
    `lint_bench` walker, and prints the human `render()` (or, with
    `as_json=True`, one `json.dumps(to_dict())` document -- a single parseable
    doc), returning the `BenchLint.exit_code` (0 OK / 1 card-issues / 2
    no-cards). Writes nothing. A thin wrapper over the pure core: it adds no
    lint logic beyond default -> `lint_bench` -> format, so the printed verdict
    always matches the `BenchLint` fields. Needs NO product `--config`, so like
    `lint-spec` it is dispatched BEFORE the top-level `load_config`."""
    if bench_dir is None:
        bench_dir = str(FOUNDRY / "roles" / "bench")
    lint = lint_bench(bench_dir)
    if as_json:
        print(json.dumps(lint.to_dict(), indent=2))
    else:
        print(lint.render())
    return lint.exit_code


# --------------------------------------------------------------------------- #
# Staffing-manifest linter (`foundry lint-manifest`) -- the MANIFEST-facing
# sibling of `doctor` (env #0), `lint-spec` (spec #6), `lint-config` (config
# #27), and `lint-bench` (bench #29), and the SECOND org-design-track item
# (roadmap item 18, bite 1). The org design (docs/ORG_DESIGN.md sect 5) has a
# kickoff council emit a machine-checkable STAFFING MANIFEST (products/<name>/
# staffing.json): which bench roles are ON, their run sequence + gates, a
# per-role model note, done-criteria, and an iteration budget. The
# manifest-driven pipeline (item 19) will READ that manifest -- but nothing in
# code enforces its shape, so a manifest cannot be trusted before item 19
# consumes it. This is the missing enforcement: a pure `lint_manifest(data,
# bench_dir, manifest_path=...)` core that validates a parsed manifest against
# a DOCUMENTED schema and reports leveled findings, each tagged with the RULE
# it violates, plus a thin `lint_manifest_cli` that reads + JSON-parses a file
# and formats the verdict.
#
# THE SCHEMA (documented here, enforced by the core). A staffing manifest is a
# JSON OBJECT with these REQUIRED top-level keys:
#   * `product`          -- a non-empty string.
#   * `iteration_budget` -- an int strictly > 0 (a plain int, NOT a bool).
#   * `roles`            -- a non-empty LIST of role objects, in run order (the
#                           list order IS the sequence). Each role object
#                           requires: `role` (str, a bench-card name), `model`
#                           (str, the per-role model note), `gate` (bool), and
#                           `done_criteria` (str).
# THE FOUR RULES (each finding is tagged with its `rule`):
#   * `schema`     -- the top level must be an object with the required keys of
#                     the correct type, and every role entry must be a
#                     well-formed object (all four fields, correct types). A
#                     malformed role contributes NO name to the role set.
#   * `bench_card` -- every well-formed role name must have a
#                     `<bench_dir>/<name>.md` card file.
#   * `core_seat`  -- the five core seats (`product_manager`, `engineer`,
#                     `reviewer`, `qa_tester`, `release_gate`), in that FIXED
#                     order, must all appear among the well-formed role names.
#   * `budget`     -- `iteration_budget` must be a positive int (see below).
# Finding order is DETERMINISTIC: all `schema`, then `bench_card` (manifest role
# order), then `core_seat` (fixed seat order), then `budget`.
#
# Deterministic + OFFLINE (only `.exists()` reads under `bench_dir`; NO network,
# NO subprocess, NO clock) and the pure core NEVER raises on malformed `data`
# (a non-dict, missing keys, or wrong types all produce findings, not
# exceptions). DORMANT / on-demand only -- the pipeline/gate/dispatcher NEVER
# call it; it writes nothing. It changes NO control flow, NO existing CLI, and
# NO running-loop semantics. Exit 0 clean / 1 findings; the CLI maps an
# unreadable/invalid-JSON file to 2 (distinct from a lint finding).
# --------------------------------------------------------------------------- #

# The five always-on core seats (docs/ORG_DESIGN.md sect 4), in the FIXED order
# the `core_seat` rule reports missing seats. Kept as a module constant so the
# pure core, its docstrings, and any future manifest tooling name the same
# literals (single source of truth for the core-seat contract).
MANIFEST_CORE_SEATS = (
    "product_manager", "engineer", "reviewer", "qa_tester", "release_gate",
)

# The three role fields that must be STRINGS (any string, even empty -- unlike
# top-level `product`, the schema only constrains a role field's TYPE). `gate`
# is validated separately with a strict `type(...) is bool` check, because
# `bool` subclasses `int` in Python, so an int `1`/`0` must NOT masquerade as a
# boolean gate.
_MANIFEST_ROLE_STR_FIELDS = ("role", "model", "done_criteria")


@dataclasses.dataclass(frozen=True)
class ManifestFinding:
    """One rule violation in a staffing manifest.

    Frozen (value equality for free, matching the other verdict cores). `rule`
    is the contract axis violated (`"schema"`, `"bench_card"`, `"core_seat"`,
    or `"budget"`); `message` is a human sentence naming what is wrong and, for
    the per-role rules, WHICH role/seat.
    """
    rule: str
    message: str

    def to_dict(self) -> dict:
        """A pure, JSON-safe `{"rule","message"}` pair (fixed order)."""
        return {"rule": self.rule, "message": self.message}


def _validate_manifest_role(entry: object, index: int) -> tuple[str | None, str | None]:
    """Validate ONE role entry against the role-object schema.

    Pure + never raises. Returns `(name, error)`: a WELL-FORMED entry yields
    `(its 'role' name, None)`; a MALFORMED entry yields `(None, <a schema error
    message naming the 0-based index and the first defect>)`. A well-formed
    role object is a dict carrying all four required fields with the correct
    type -- `role`/`model`/`done_criteria` strings and `gate` a strict bool.
    The first defect found (not-an-object -> missing-field(s) -> wrong-type)
    is reported so a malformed entry yields exactly ONE finding.
    """
    if not isinstance(entry, dict):
        return None, (f"roles[{index}] must be an object, "
                      f"got {type(entry).__name__}")
    missing = [k for k in ("role", "model", "gate", "done_criteria")
               if k not in entry]
    if missing:
        return None, (f"roles[{index}] is missing required field(s): "
                      f"{', '.join(missing)}")
    for field in _MANIFEST_ROLE_STR_FIELDS:
        if not isinstance(entry[field], str):
            return None, (f"roles[{index}] field {field!r} must be a string, "
                          f"got {type(entry[field]).__name__}")
    # `gate` must be a REAL bool (not an int) -- bool subclasses int, so an
    # explicit identity check is required to reject `1`/`0`.
    if type(entry["gate"]) is not bool:
        return None, (f"roles[{index}] field 'gate' must be a boolean, "
                      f"got {type(entry['gate']).__name__}")
    return entry["role"], None


@dataclasses.dataclass(frozen=True)
class ManifestLint:
    """A lint verdict for a whole staffing manifest.

    Frozen so a computed verdict can't be mutated after the fact (value
    equality for free). The stored fields are the raw validation results -- the
    `manifest_path` label, the `bench_dir` cards were checked against, the
    `roles` tuple (the WELL-FORMED role names in manifest order; a malformed
    role contributes no name), and the flattened `findings` in the
    deterministic rule order -- and every count / verdict / exit-code /
    `core_seats_present` is a PURE property derived from those fields, so
    `render()` / `to_dict()` / the exit code can never disagree (single source
    of truth).
    """
    manifest_path: str
    bench_dir: str
    roles: tuple[str, ...]
    findings: tuple[ManifestFinding, ...]

    @property
    def n_findings(self) -> int:
        """How many rule violations were found across all four rules."""
        return len(self.findings)

    @property
    def core_seats_present(self) -> bool:
        """True iff all five `MANIFEST_CORE_SEATS` appear among the well-formed
        role names. Derived from `roles` (the SAME set the `core_seat` rule
        checks), so it can never disagree with the core_seat findings."""
        names = set(self.roles)
        return all(seat in names for seat in MANIFEST_CORE_SEATS)

    @property
    def clean(self) -> bool:
        """True iff there are NO findings (a fully schema-valid, fully-staffed,
        fully-carded manifest with a positive integer budget)."""
        return self.n_findings == 0

    @property
    def exit_code(self) -> int:
        """Scriptable verdict: `0` clean, else `1` (any finding). The CLI maps
        an unreadable/invalid-JSON file to `2` separately -- a parse failure is
        not a manifest finding."""
        return 0 if self.clean else 1

    @property
    def verdict(self) -> str:
        """The operator-facing token -- ONE source of truth for `render()`'s
        last line so text + exit code never drift: `"OK"` (exit 0) or
        `"MANIFEST ISSUES FOUND"` (exit 1)."""
        return "OK" if self.clean else "MANIFEST ISSUES FOUND"

    def render(self) -> str:
        """A deterministic multi-line report.

        The FIRST line names the manifest path; a summary line names the bench
        dir, the well-formed role count, and whether the core seats are all
        present; then one `  [<rule>] <message>` line per finding (in the
        deterministic rule order); and the LAST non-empty line is exactly
        `verdict: <TOKEN>` (`OK` / `MANIFEST ISSUES FOUND`). Detail above the
        sentinel, so 'last non-empty line == verdict' always holds. Every value
        is taken from the stored fields, never a source-literal home path."""
        lines = [
            f"foundry lint-manifest -- {self.manifest_path}",
            f"  bench dir: {self.bench_dir}",
            f"  roles: {len(self.roles)}  findings: {self.n_findings}  "
            f"core seats present: {'yes' if self.core_seats_present else 'no'}",
        ]
        for f in self.findings:
            lines.append(f"  [{f.rule}] {f.message}")
        lines.append(f"verdict: {self.verdict}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """A pure, JSON-safe serialization.

        Returns EXACTLY these keys in this fixed order: `manifest_path`,
        `bench_dir`, `roles` (a list of the well-formed role-name strings in
        manifest order), `findings` (a list of `{"rule","message"}` dicts in
        the deterministic rule order), `n_findings`, `core_seats_present`,
        `clean`, `exit_code`, `verdict`. Every value is JSON-native so
        `json.dumps(...)` never raises and the dict round-trips through
        `json.loads(json.dumps(...))`."""
        return {
            "manifest_path": self.manifest_path,
            "bench_dir": self.bench_dir,
            "roles": list(self.roles),
            "findings": [f.to_dict() for f in self.findings],
            "n_findings": self.n_findings,
            "core_seats_present": self.core_seats_present,
            "clean": self.clean,
            "exit_code": self.exit_code,
            "verdict": self.verdict,
        }


def lint_manifest(data: object, bench_dir: "str | pathlib.Path",
                  manifest_path: str = "staffing.json") -> ManifestLint:
    """Validate a parsed staffing manifest against the documented schema.

    Pure + deterministic + OFFLINE: the ONLY effect is `.exists()` reads under
    `bench_dir` (the bench_card rule); NO network, NO subprocess, NO clock, and
    it NEVER raises on malformed `data` (a non-dict, missing keys, or wrong
    types all become findings). `data` is a parsed JSON value of ANY type;
    `bench_dir` is a str or `pathlib.Path`; `manifest_path` is a display label.
    Applies the four rules and returns a `ManifestLint` whose `findings` are in
    the FIXED order `schema` -> `bench_card` (manifest role order) -> `core_seat`
    (fixed seat order) -> `budget`, so two runs on identical inputs are
    identical.
    """
    bd = pathlib.Path(bench_dir)
    schema: list[ManifestFinding] = []
    bench_card: list[ManifestFinding] = []
    core_seat: list[ManifestFinding] = []
    budget: list[ManifestFinding] = []

    # Rule 1a (schema): the top level MUST be a JSON object. A non-dict is a
    # HARD STOP -- there are no keys to inspect, so emit exactly one schema
    # finding and return (no bench_card/core_seat/budget rules run).
    if not isinstance(data, dict):
        schema.append(ManifestFinding(
            "schema",
            f"manifest is not a JSON object (got {type(data).__name__}); the "
            "top level must be an object with 'product', 'iteration_budget', "
            "and 'roles'"))
        return ManifestLint(str(manifest_path), str(bench_dir), (),
                            tuple(schema))

    # Rule 1b (schema): required top-level keys of the correct type. `product`
    # must be a NON-EMPTY string; `roles` must be a NON-EMPTY list.
    # `iteration_budget` is validated by the budget rule, NOT here.
    product = data.get("product")
    if not isinstance(product, str) or not product:
        schema.append(ManifestFinding(
            "schema", "'product' must be a non-empty string"))
    roles_val = data.get("roles")
    roles_is_list = isinstance(roles_val, list)
    if not roles_is_list or not roles_val:
        schema.append(ManifestFinding(
            "schema",
            "'roles' must be a non-empty list of role objects (in run order)"))

    # Rule 1c (schema): validate each role entry + collect the WELL-FORMED role
    # names in manifest order. A malformed entry yields one schema finding and
    # contributes NO name (so it cannot satisfy a core seat or be card-checked).
    names: list[str] = []
    if roles_is_list:
        for i, entry in enumerate(roles_val):
            name, err = _validate_manifest_role(entry, i)
            if err is not None:
                schema.append(ManifestFinding("schema", err))
            else:
                names.append(name)

    # Rule 2 (bench_card): every well-formed role name needs a card file, in
    # manifest role order.
    for name in names:
        if not (bd / f"{name}.md").exists():
            bench_card.append(ManifestFinding(
                "bench_card",
                f"role {name!r} has no bench card ({name}.md) under the "
                "bench dir"))

    # Rule 3 (core_seat): the five core seats in FIXED order.
    name_set = set(names)
    for seat in MANIFEST_CORE_SEATS:
        if seat not in name_set:
            core_seat.append(ManifestFinding(
                "core_seat",
                f"core seat {seat!r} is not staffed (no role named {seat!r})"))

    # Rule 4 (budget): `iteration_budget` must be a positive int, NOT a bool.
    # The `type(...) is not int` check rejects bool/float/str/None; the
    # short-circuit protects the `<= 0` comparison from a non-int operand.
    budget_val = data.get("iteration_budget")
    if type(budget_val) is not int or budget_val <= 0:
        budget.append(ManifestFinding(
            "budget",
            "'iteration_budget' must be an integer strictly greater than 0"))

    findings = tuple(schema + bench_card + core_seat + budget)
    return ManifestLint(str(manifest_path), str(bench_dir), tuple(names),
                        findings)


def lint_manifest_cli(file: str, bench_dir: "str | None" = None,
                      as_json: bool = False) -> int:
    """On-demand CLI: validate a staffing-manifest JSON file.

    Reads + JSON-parses `file` INSIDE a try so a nonexistent / unreadable /
    invalid-JSON file returns `2` (distinct from a lint finding=1) after
    printing a `lint-manifest: ...` diagnostic (or, with `as_json=True`, one
    `{"manifest_path","error","exit_code":2}` document), WITHOUT letting the
    exception propagate. On a successful parse it resolves `bench_dir` (None ->
    the foundry's OWN `roles/bench`), runs the pure `lint_manifest` core BY BARE
    module name (so a `monkeypatch.setattr(foundry, "lint_manifest", ...)`
    bites), and prints the human `render()` (or one `json.dumps(to_dict())`
    document with `as_json=True`), returning the `ManifestLint.exit_code` (0
    clean / 1 findings). Writes nothing. Needs NO product `--config`, so like
    `lint-spec`/`lint-bench` it is dispatched BEFORE the top-level
    `load_config`. A thin wrapper: it adds no lint logic beyond read -> parse ->
    `lint_manifest` -> format, so the printed verdict always matches the
    `ManifestLint` fields."""
    try:
        with open(file, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as exc:
        message = (f"lint-manifest: cannot read manifest {file}: "
                   f"{type(exc).__name__}: {exc}")
        if as_json:
            print(json.dumps({"manifest_path": str(file),
                              "error": message, "exit_code": 2}))
        else:
            print(message)
        return 2
    if bench_dir is None:
        bench_dir = str(FOUNDRY / "roles" / "bench")
    lint = lint_manifest(data, bench_dir, manifest_path=str(file))
    if as_json:
        print(json.dumps(lint.to_dict(), indent=2))
    else:
        print(lint.render())
    return lint.exit_code


# --------------------------------------------------------------------------- #
# Manifest-driven stage sequence (roadmap item 19, bite 1/2).
#
# `run_iteration` today runs a FIXED five-core-seat pipeline (pm -> engineer ->
# reviewer -> tester -> final). Item 19 makes that order DATA-DRIVEN: a product's
# `staffing.json` (validated by `lint_manifest`, item 18) can name the ordered
# seats, and any extra activated bench seat inserts its bounded stage at its
# declared position. This bite ships the PURE derivation core ONLY -- there is
# NO call site, so the running loop is bit-for-bit unchanged (resume-safe); bite
# 2 wires it behind an `absent-manifest == current-behavior` guard.
#
# `CORE_SEAT_STAGES` is the single source of truth mapping each core seat to the
# exact `(stage, role_file, out_file)` triple `run_iteration` already passes to
# `run_stage`, so the derived DEFAULT sequence reproduces today's pipeline. The
# derivation is pure/offline/never-raises and FAIL-SAFE: a structurally-unusable
# manifest is treated as absent, honoring the "absent manifest = current
# behavior, bit-for-bit" contract. It reads ONLY the `role` name order here;
# `gate`/`model`/`done_criteria` are consumed by later items, and it does NOT
# re-validate the manifest (that is `lint_manifest`'s job -- bite 2 lints first).
# --------------------------------------------------------------------------- #

# Each core seat -> the exact (stage, role_file, out_file) triple that
# `run_iteration` passes to `run_stage` for that seat, in `MANIFEST_CORE_SEATS`
# order (a dict preserves insertion order). Kept beside `MANIFEST_CORE_SEATS` so
# the manifest core names and the pipeline stage literals stay a single source
# of truth; a future drift between this table and `run_iteration`'s calls would
# surface right here.
CORE_SEAT_STAGES: dict[str, tuple[str, str, str]] = {
    "product_manager": ("pm", "pm.md", "pm.md"),
    "engineer": ("engineer", "engineer.md", "engineer.md"),
    "reviewer": ("reviewer", "reviewer.md", "reviewer.md"),
    "qa_tester": ("tester", "tester.md", "tester.md"),
    "release_gate": ("final", "final.md", "final.md"),
}


@dataclasses.dataclass(frozen=True)
class StageSpec:
    """One derived pipeline stage: which seat runs, and the `run_stage` args.

    Frozen for value equality and immutability (matching the other verdict
    cores) so a derived sequence can be compared element-by-element and cannot
    be mutated after derivation. `seat` is the manifest role name; `stage` is
    the short pipeline label; `role_file` is the prompt-card path relative to
    the roles dir; `out_file` is the required output file name.
    """
    seat: str
    stage: str
    role_file: str
    out_file: str


def _stage_spec_for_seat(name: str) -> StageSpec:
    """The `StageSpec` for one seat name.

    A CORE seat (a key of `CORE_SEAT_STAGES`) uses its canonical
    `(stage, role_file, out_file)` triple; any other name is an EXTRA activated
    bench seat and uses the `bench/<name>.md` role-file convention with a
    stage/out_file named after the seat. Pure; the caller guarantees `name` is a
    string.
    """
    if name in CORE_SEAT_STAGES:
        return StageSpec(name, *CORE_SEAT_STAGES[name])
    return StageSpec(seat=name, stage=name,
                     role_file=f"bench/{name}.md", out_file=f"{name}.md")


def _default_stage_sequence() -> tuple[StageSpec, ...]:
    """The fixed five-core-seat sequence -- today's pipeline, bit-for-bit.

    Backs BOTH the `manifest is None` case and the fail-safe fallback, so an
    absent OR structurally-unusable manifest reproduces the current fixed
    behavior exactly. Built through the same `_stage_spec_for_seat` path a
    core-only manifest takes, so the default and a core-only manifest can never
    diverge.
    """
    return tuple(_stage_spec_for_seat(seat) for seat in MANIFEST_CORE_SEATS)


def derive_stage_sequence(manifest: dict | None) -> tuple[StageSpec, ...]:
    """Map a parsed staffing manifest to the ordered pipeline stage sequence.

    PURE + deterministic + offline: no filesystem / network / subprocess /
    clock access, and it NEVER raises. Reads ONLY each role's `role` name for
    ordering; `gate`/`model`/`done_criteria` and any other role-object keys are
    ignored here (they are consumed by later items). It does NOT re-validate
    core-seat completeness, budget, or card existence -- that is
    `lint_manifest`'s job; bite 2 will lint-then-derive.

    - `manifest is None` -> the DEFAULT sequence (the five `MANIFEST_CORE_SEATS`
      in fixed order).
    - a dict whose `roles` is a NON-EMPTY list where EVERY entry is a dict
      carrying a STRING `role` -> map each role entry IN ORDER to a `StageSpec`
      (declared order is authoritative): a core seat uses its canonical triple;
      an extra seat uses the `bench/<name>.md` convention.
    - ANY other input (not a dict; no `roles` key; `roles` not a list; empty
      `roles`; ANY role entry not a dict or lacking a string `role`) -> the
      DEFAULT sequence. Well-formedness is all-or-nothing: a single malformed
      role entry falls the WHOLE manifest back to the default (a
      structurally-unusable manifest is treated as absent).
    """
    if not isinstance(manifest, dict):
        return _default_stage_sequence()
    roles = manifest.get("roles")
    if not isinstance(roles, list) or not roles:
        return _default_stage_sequence()
    names: list[str] = []
    for entry in roles:
        if not isinstance(entry, dict):
            return _default_stage_sequence()
        name = entry.get("role")
        if not isinstance(name, str):
            return _default_stage_sequence()
        names.append(name)
    return tuple(_stage_spec_for_seat(name) for name in names)


# --------------------------------------------------------------------------- #
# Execution PLAN (roadmap item 19, bite 3a) -- the DORMANT pure layer above
# `derive_stage_sequence`. A derived `StageSpec` sequence says WHICH seats run
# in WHAT order; an execution plan additionally pairs each seat with the GATE
# BEHAVIOR the executor must apply (pm / build / review / test / release /
# bench). `SEAT_GATE_KINDS` is the single source of truth mapping each core seat
# to its gate kind, mirroring `run_iteration`'s hard-coded per-stage behavior
# VERBATIM: the pm stage failing returns infra-fail with NO revert (nothing is
# built yet); every later stage failing reverts; only the release stage runs the
# `ACTION: PUSHED` -> ship + `postrelease_step` branch. An extra activated bench
# seat defaults to the `bench` gate (revert-on-fail, never a ship gate). This is
# PURE + offline + never-raises and has ZERO call site: it is the pre-computed,
# already-verified plan the manifest-driven executor (bite 3b) will iterate, so
# wiring becomes a thin switch over this plan rather than from-scratch gate
# reasoning. The gate-triggered/mechanical stages (fix-review / fix-tests /
# tester-rerun / reporter) are NOT manifest-derived seats (the iter-67
# exclusion): they are IMPLIED by the `review`/`test` gate kinds and handled
# inline by the executor, never their own plan steps.
# --------------------------------------------------------------------------- #

# Each core seat -> the gate kind the executor applies for that stage. Kept
# beside `CORE_SEAT_STAGES`/`MANIFEST_CORE_SEATS` so the seat identities and
# their gate behaviors stay a single source of truth; `tuple(SEAT_GATE_KINDS)`
# equals `MANIFEST_CORE_SEATS` (same five keys, same order).
SEAT_GATE_KINDS: dict[str, str] = {
    "product_manager": "pm",
    "engineer": "build",
    "reviewer": "review",
    "qa_tester": "test",
    "release_gate": "release",
}

# The gate kind for any NON-core (extra activated bench) seat: bench seats
# revert-on-fail and are never a ship gate.
DEFAULT_GATE_KIND = "bench"


@dataclasses.dataclass(frozen=True)
class StagePlan:
    """One planned pipeline stage: its `StageSpec` plus the executor gate kind.

    Frozen for value-equality + immutability (matching `StageSpec` and the other
    verdict cores) so a derived plan can be compared element-by-element and
    cannot be mutated after derivation. `spec` is the iter-67 `StageSpec` (which
    seat runs, and the `run_stage` args); `gate` is the gate-behavior kind the
    executor applies (`pm`/`build`/`review`/`test`/`release`/`bench`). The two
    properties are pure derivations of `gate`, so a stage's fail/ship semantics
    follow deterministically from its gate kind.
    """
    spec: StageSpec
    gate: str

    @property
    def reverts_on_fail(self) -> bool:
        """True iff a failure at this stage must `revert_repo`.

        Mirrors `run_iteration`: the `pm` stage failing returns infra-fail with
        NO revert (nothing has been built yet), so ONLY `pm` is False; every
        other gate (`build`/`review`/`test`/`release`/`bench`) reverts on fail.
        """
        return self.gate != "pm"

    @property
    def is_ship_gate(self) -> bool:
        """True iff this stage runs the ship (`ACTION: PUSHED` + postrelease).

        Mirrors `run_iteration`: only the `final`/`release_gate` stage runs the
        `ACTION: PUSHED` -> ship + `postrelease_step` branch.
        """
        return self.gate == "release"


def _gate_kind_for_seat(seat: str) -> str:
    """The gate kind for one seat name.

    A CORE seat (a key of `SEAT_GATE_KINDS`) uses its declared gate kind; any
    other name is an extra activated bench seat and uses `DEFAULT_GATE_KIND`
    (`"bench"`). EXACT match only -- no normalization, so `"reviewer "` (a
    trailing space) or `""` is a bench seat. Reads the module globals INSIDE the
    function (not captured at def-time) so a `monkeypatch.setattr` on either
    `SEAT_GATE_KINDS` or `DEFAULT_GATE_KIND` takes effect. Pure; never raises for
    a string input.
    """
    return SEAT_GATE_KINDS.get(seat, DEFAULT_GATE_KIND)


def derive_execution_plan(
        sequence: tuple[StageSpec, ...] | list[StageSpec]) -> tuple[StagePlan, ...]:
    """Map a derived `StageSpec` sequence to the ordered EXECUTION PLAN.

    PURE + deterministic + offline (no filesystem / network / subprocess /
    clock) and NEVER raises for a sequence of `StageSpec`s. Returns one
    `StagePlan` per input `StageSpec`, IN THE SAME ORDER, pairing each spec with
    `_gate_kind_for_seat(spec.seat)` -- so the DEFAULT sequence reproduces
    `run_iteration`'s five hard-coded stages and their gate behaviors
    bit-for-bit (Behavior 7), and an extra activated seat gets the `bench` gate
    at its declared position. `StagePlan.spec` is the identical input object.
    Accepts any finite iterable of `StageSpec` (a list or a tuple) and returns a
    tuple in both cases; two calls on equal input return equal output. This has
    ZERO call site -- the manifest-driven executor (bite 3b) will consume it;
    nothing runs it yet.
    """
    return tuple(
        StagePlan(spec=spec, gate=_gate_kind_for_seat(spec.seat))
        for spec in sequence
    )


def run_execution_plan(cfg: ProductConfig, iteration: int,
                       plan: tuple[StagePlan, ...] | list[StagePlan],
                       base: str) -> dict:
    """Drive an arbitrary derived execution `plan` through the pipeline.

    The manifest-driven EXECUTOR for item 19 (bite 3b-i): given the ordered
    `StagePlan` tuple from `derive_execution_plan` and the `base` head captured
    by the caller, run each seat's `run_stage` and apply its gate behavior BY
    GATE KIND so the DEFAULT plan reproduces `run_iteration`'s five hard-coded
    stages + ship return dict bit-for-bit, and a non-default plan drives its own
    seats. Returns the same result dict shape as `run_iteration`
    (status in {'shipped', 'no-ship', 'infra-fail'}).

    Gate behaviors, each mirroring `run_iteration` VERBATIM:
      * ANY stage that fails -> infra-fail keyed on that stage; `revert_repo`
        first iff `StagePlan.reverts_on_fail` (True for every gate except `pm`,
        because at the pm stage nothing has been built yet).
      * `review` gate whose report contains `CHANGES_REQUIRED` -> a fix-review
        pass; if it fails, revert + infra-fail (stage `fix-review`).
      * `test` gate whose report contains `RESULT: FAIL` -> a fix-tests pass and,
        on its success, a tester-rerun; if either fails, revert + infra-fail
        (stage `fix-tests`).
      * `release` gate -> TERMINAL: if the report has `ACTION: PUSHED` AND the
        branch head moved off `base`, ship (postrelease + shipped dict); else
        revert + no-ship. No plan step after a release gate is ever run.
      * `pm` / `build` / `bench` gates -> no post-success work; continue.

    `base` is a PARAMETER, not re-read here, so the eventual wiring (bite 3b-ii)
    can pass the head `run_iteration` already captured for its log line without a
    second `head_of_branch` call. Every external effect (`run_stage`,
    `revert_repo`, `head_of_branch`, `postrelease_step`, `contains`, `log`) is
    called by its BARE module name so a test's `monkeypatch.setattr` bites, and
    module globals are read inside the call. If the plan has NO release gate and
    every stage passes, the loop completes and returns no-ship WITHOUT reverting
    (defensive totality; a well-formed manifest always ends in a release gate,
    which 3b-ii's lint gate enforces). This has ZERO call site -- 3b-ii wires it
    behind an absent-or-default guard; nothing runs it yet.
    """
    for step in plan:
        spec = step.spec
        ok, report = run_stage(cfg, iteration, spec.stage, spec.role_file,
                               spec.out_file)
        if not ok:
            if step.reverts_on_fail:
                revert_repo(cfg, f"{spec.stage} stage failed")
            return {"status": "infra-fail", "stage": spec.stage,
                    "iteration": iteration}

        if step.gate == "review" and contains(report, "CHANGES_REQUIRED"):
            log(cfg, f"iter {iteration:02d} - review requires changes -> fix pass")
            ok, _ = run_stage(cfg, iteration, "fix-review", "fix.md",
                              "fix_review.md",
                              f"Gate file to address: {report} ([BLOCKING] only).")
            if not ok:
                revert_repo(cfg, "fix-review failed")
                return {"status": "infra-fail", "stage": "fix-review",
                        "iteration": iteration}
        elif step.gate == "test" and contains(report, "RESULT: FAIL"):
            log(cfg, f"iter {iteration:02d} - tests failed -> fix pass + retest")
            ok, _ = run_stage(cfg, iteration, "fix-tests", "fix.md",
                              "fix_tests.md",
                              f"Gate file to address: {report} (failing tests).")
            if ok:
                ok, _ = run_stage(
                    cfg, iteration, "tester-rerun", "tester.md", "tester2.md",
                    "This is a RE-RUN after an engineering fix. Re-verify all "
                    "behaviors; update your earlier tests only if they misread "
                    "the spec.")
            if not ok:
                revert_repo(cfg, "fix/retest failed")
                return {"status": "infra-fail", "stage": "fix-tests",
                        "iteration": iteration}
        elif step.gate == "release":
            new_head = head_of_branch(cfg)
            if contains(report, "ACTION: PUSHED") and new_head != base:
                log(cfg, f"iter {iteration:02d} SHIPPED - origin/{cfg.branch} "
                    f"now {new_head}")
                post = postrelease_step(cfg, iteration, new_head)
                log(cfg, f"iter {iteration:02d} post-release {post.sentinel}")
                return {"status": "shipped", "head": new_head,
                        "iteration": iteration, "postrelease": post.sentinel}
            revert_repo(cfg, "final gate declined to ship")
            log(cfg, f"iter {iteration:02d} completed WITHOUT ship "
                f"(reverted; see final.md)")
            return {"status": "no-ship", "iteration": iteration}

    return {"status": "no-ship", "iteration": iteration}


def load_staffing_manifest(cfg: ProductConfig) -> dict | None:
    """Read the product's staffing manifest as a dict, or None if unusable.

    The manifest READ seam for item 19 (bite 2): read `cfg.staffing` (resolved
    to `<work_root>/staffing.json` by default) and return the parsed JSON
    OBJECT. FAIL-SAFE and NEVER raises -- returns None for every unusable case
    (missing file, a directory, an unreadable path, invalid JSON, or a
    valid-JSON NON-object such as a bare array / number / string) so a broken
    or absent manifest is indistinguishable from "no manifest" to the caller.
    The strict contract is `dict | None`; structural validity beyond "is a JSON
    object" is left to `derive_stage_sequence` (fail-safe) and, in bite 3,
    `lint_manifest`. Module-level so `run_iteration` calls it by BARE name and a
    test's `monkeypatch.setattr(foundry, "load_staffing_manifest", ...)` bites.
    """
    try:
        data = json.loads(pathlib.Path(cfg.staffing).read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


# --------------------------------------------------------------------------- #
# prd.json machine-roadmap status (roadmap item 1, bite 1/2).
#
# Right now the only record of what a product has shipped is the prose
# NIGHT_LOG / roadmap, which a machine cannot reliably parse to decide "are we
# done?". A per-product `prd.json` (a list of stories, each with a `passes`
# flag) is the jq-able machine roadmap. `prd_status` is the deterministic core:
# pure JSON text in, a `PrdStatus` count out -- no filesystem/subprocess/
# network/clock, and it NEVER raises -- so it is fully offline-testable and can
# back both the on-demand CLI now AND, in a later bite, the dispatcher's
# deterministic global-stop. `prd_status_cli` is the operator-facing seam (read
# cfg.prd -> prd_status -> print "N/M stories pass"). NOTHING on a control path
# calls this yet -- wiring it into the dispatcher touches control flow (bite 2).
# --------------------------------------------------------------------------- #
@dataclasses.dataclass(frozen=True)
class PrdStatus:
    """A story-pass count for a product's prd.json machine roadmap.

    Frozen so a computed status can't be mutated after the fact, which also
    gives value-equality for free: two `prd_status` calls on byte-identical text
    hold equal fields, so they compare ``==`` (Behavior 9). ``pending`` is a
    tuple (hashable + order-stable) of the not-yet-passing stories' identifiers
    in file order. The two properties are pure derivations of the stored counts,
    so the whole verdict follows deterministically from what was parsed.
    """
    valid: bool
    total: int
    passed: int
    pending: tuple

    @property
    def complete(self) -> bool:
        """True iff valid AND there is >=1 story AND every story passes.

        An empty story list (``total == 0``) is deliberately NOT complete -- a
        product with no stories has shipped nothing, so it must never read as
        done (Behavior 5).
        """
        return self.valid and self.total > 0 and self.passed == self.total

    @property
    def summary(self) -> str:
        """The operator one-liner, e.g. ``"2/5 stories pass"`` (Behavior 6)."""
        return f"{self.passed}/{self.total} stories pass"


def prd_status(prd_text: str) -> PrdStatus:
    """Count passing stories in a prd.json machine roadmap (pure, total).

    Accepts both top-level shapes (Behavior 2): a bare array ``[ ... ]`` and an
    object ``{"stories": [ ... ]}`` wrapping the same stories. Story-list entries
    that are not JSON objects are ignored entirely -- excluded from ``total``,
    ``passed`` and ``pending`` (Behavior 4). ``passes`` is evaluated as truthy,
    so ``true``/``1`` pass while a missing key / ``false`` / ``null`` / ``0`` do
    not (Behavior 3).

    NEVER raises (Behavior 8): malformed JSON, or valid JSON that is neither an
    array nor an object containing a ``stories`` array (e.g. ``42``, ``"x"``,
    ``{}`` with no ``stories`` key), returns
    ``PrdStatus(valid=False, total=0, passed=0, pending=())``.

    A pending story's identifier is its ``id`` if present and truthy, else its
    ``title`` if present and truthy, else ``"#{k}"`` where ``k`` is its 1-based
    position among the story OBJECTS (junk entries do not advance ``k``),
    matching Behavior 7.
    """
    invalid = PrdStatus(valid=False, total=0, passed=0, pending=())
    try:
        data = json.loads(prd_text)
    except (ValueError, TypeError):
        return invalid

    if isinstance(data, list):
        raw_stories = data
    elif isinstance(data, dict) and isinstance(data.get("stories"), list):
        raw_stories = data["stories"]
    else:
        return invalid

    # Only JSON objects are stories; k enumerates objects (Behaviors 4 & 7).
    stories = [s for s in raw_stories if isinstance(s, dict)]
    passed = 0
    pending: list = []
    for k, story in enumerate(stories, start=1):
        if story.get("passes"):
            passed += 1
        else:
            pending.append(story.get("id") or story.get("title") or f"#{k}")
    return PrdStatus(valid=True, total=len(stories), passed=passed,
                     pending=tuple(pending))


def prd_status_cli(cfg: ProductConfig) -> int:
    """On-demand CLI: report "N/M stories pass" from a product's ``cfg.prd``.

    Reads the file at ``cfg.prd``, computes `prd_status`, prints a human-readable
    report, and returns ``0`` (complete) / ``1`` (incomplete) / ``2`` (missing or
    invalid prd). Writes NOTHING to disk (Behavior 14). A thin wrapper over the
    pure core -- it adds no counting logic beyond read -> `prd_status` -> format,
    so the printed figures always match the ``PrdStatus`` fields. A missing file
    returns ``2`` naming the path (Behavior 11) without letting a
    ``FileNotFoundError`` propagate; an existing-but-malformed file returns ``2``
    flagged as invalid JSON (Behavior 13).
    """
    path = pathlib.Path(cfg.prd)
    if not path.exists():
        print(f"prd: file not found: {cfg.prd}")
        return 2
    status = prd_status(path.read_text())
    print(f"prd: {cfg.prd}")
    if not status.valid:
        print('prd: invalid JSON -- expected an array of story objects '
              'or a {"stories": [...]} object')
        return 2
    print(f"  {status.summary}")
    print(f"  complete: {status.complete}")
    if status.pending:
        print(f"  pending: {', '.join(str(x) for x in status.pending)}")
    return 0 if status.complete else 1


# --------------------------------------------------------------------------- #
# Dispatcher progress reporting (item 1, bite 2a -- REPORTING ONLY).
#
# `dispatch_progress_line` is the shift-loop reporting hook: read `cfg.prd` ->
# `prd_status` -> a one-line "N/M stories pass" summary the dispatcher `dlog`s
# after each shift. Diagnostic-only and OFF every control path -- nothing in
# `run_iteration`/`run_continuous`/`run_stage`/`build_prompt` calls it and it
# introduces no sentinel -- so it is a runtime no-op (returns `None`) for every
# product until an operator adds a `prd.json`. The automatic global-stop half
# (bite 2b) that would touch loop-termination/resume semantics is deferred.
# --------------------------------------------------------------------------- #
def dispatch_progress_line(cfg: ProductConfig) -> str | None:
    """One-line "N/M stories pass" progress for the dispatcher (pure, total).

    Closes item 1's remaining "done when" -- the dispatcher can report a
    product's prd progress every shift. A thin, diagnostic-only wrapper over the
    frozen pure core (read `cfg.prd` -> `prd_status` -> format), so its counts are
    always exactly the `PrdStatus` fields; it adds NO counting logic of its own
    (Behavior 8). Off every control path: nothing in `run_iteration`/
    `run_continuous`/`run_stage`/`build_prompt` calls it and it adds no sentinel,
    so wiring it into the dispatcher changes no loop, numbering, or state layout
    and stays a runtime no-op until an operator adds a `prd.json`.

    Returns (the exact-string contract, see the PM spec Behaviors):
      * ``None`` -- `cfg.prd` is absent, OR any unexpected read error (e.g. it
        points at a DIRECTORY or an unreadable path). NEVER raises (Behaviors 1, 6).
      * ``"{name}: prd.json present but unparseable"`` -- the file EXISTS but is not
        a valid story list, so an operator sees the problem, not a silent miss; this
        string never contains the substring "stories pass" (Behavior 5).
      * ``"{name}: {passed}/{total} stories pass (COMPLETE)"``   -- valid + complete.
      * ``"{name}: {passed}/{total} stories pass (in progress)"`` -- valid + not
        complete, which includes the empty-list case (``0/0``, never "done").
    Writes NOTHING to disk (Behavior 7): it only reads `cfg.prd`.
    """
    try:
        path = pathlib.Path(cfg.prd)
        if not path.exists():
            return None
        status = prd_status(path.read_text())
    except Exception:
        # Any unexpected filesystem/decode error (e.g. cfg.prd is a directory)
        # must never crash the dispatcher shift loop -- degrade to a no-op.
        return None
    if not status.valid:
        return f"{cfg.name}: prd.json present but unparseable"
    state = "COMPLETE" if status.complete else "in progress"
    # `status.summary` is the single source of "{passed}/{total} stories pass".
    return f"{cfg.name}: {status.summary} ({state})"


# --------------------------------------------------------------------------- #
# Diff-scope classifier (roadmap item 4, bite 1/2 -- DORMANT).
#
# Item 7 established that continuous-shipping throughput is dominated by verify
# time. Item 4 attacks that: a *coverage-only* iteration (every changed path is
# a test file) could ride a light gate instead of the heavy full path. That
# needs an OBJECTIVE, deterministic answer to "does this diff touch shippable
# source, or is it test-only?". `classify_gate_scope` is that answer: a pure,
# total, offline function -- path strings in, a frozen `GateScope` out -- with
# NO filesystem/subprocess/network/clock, so it is fully offline-testable.
# `gate_scope_cli` is the operator-facing seam (--files, or the monkeypatchable
# `run_cmd` git-diff seam -> classify -> print). This bite is DORMANT: NOTHING on
# a control path calls it -- the final gate does NOT consult the verdict and the
# section-3 independent full-suite-rerun invariant is untouched. Wiring the light
# path into the gate (and preserving that invariant) is a future bite. Same
# purely-additive, off-control-path, on-demand-CLI class as doctor/lint-spec/prd.
# The two constants are module-level + patchable so the buckets stay tunable per
# box AND are read at CALL time (not captured at import) -- see Behavior 8.
# --------------------------------------------------------------------------- #
GATE_TEST_DIR_NAMES: tuple[str, ...] = ("tests", "test")
GATE_DOC_SUFFIXES: tuple[str, ...] = (".md", ".rst", ".txt")


@dataclasses.dataclass(frozen=True)
class GateScope:
    """A bucketed classification of one diff's changed paths (item 4).

    Frozen so a computed scope can't be mutated after the fact (value-equality
    for free, matching the other pure cores). Every field is a `tuple[str, ...]`
    (hashable + order-stable): `changed` is the input paths in order after blank
    entries are dropped; `source`/`test`/`doc` PARTITION `changed` (pairwise
    disjoint, and their union is exactly `changed`). The two properties are pure
    derivations of the buckets, so the verdict follows deterministically from
    what was classified.
    """
    changed: tuple[str, ...]
    source: tuple[str, ...]
    test: tuple[str, ...]
    doc: tuple[str, ...]

    @property
    def light(self) -> bool:
        """True iff there is >=1 change AND every change is a test path.

        A coverage-only diff -- no source, no doc. Deliberately conservative: an
        empty diff is NOT light (there is nothing to gate lighter), and a doc-only
        diff is NOT light (docs such as `roles/*.md` can encode behaviour).
        """
        return bool(self.changed) and not self.source and not self.doc

    @property
    def scope(self) -> str:
        """The operator one-word verdict: `"light"` when `light` else `"full"`."""
        return "light" if self.light else "full"


def _is_test_path(path: str) -> bool:
    """True iff `path` is a test file (pure, total).

    A path is a TEST path iff any of its `/`-split components is in
    `GATE_TEST_DIR_NAMES`, OR its basename is `conftest.py` / ends with
    `_test.py` / starts with `test_` and ends `.py`. Reads `GATE_TEST_DIR_NAMES`
    at CALL time so a monkeypatch of the module constant reclassifies subsequent
    calls (Behavior 8). Never raises for any string.
    """
    parts = path.split("/")
    if any(part in GATE_TEST_DIR_NAMES for part in parts):
        return True
    base = parts[-1]
    if base == "conftest.py" or base.endswith("_test.py"):
        return True
    return base.startswith("test_") and base.endswith(".py")


def classify_gate_scope(changed_paths) -> GateScope:
    """Bucket a diff's changed paths into test / doc / source (pure, total).

    Drops blank/whitespace-only entries, then classifies each remaining path into
    exactly ONE bucket, preserving input order:
      * TEST   -- `_is_test_path` (a test-dir component or a test basename);
      * else DOC    -- its suffix is in `GATE_DOC_SUFFIXES`;
      * else SOURCE.
    The test-check WINS over the doc-suffix (a `.md` under `tests/` is a fixture,
    not shippable doc). NEVER raises for any iterable of strings, and reads BOTH
    `GATE_TEST_DIR_NAMES`/`GATE_DOC_SUFFIXES` at CALL time (Behavior 8) -- the loop
    does zero I/O, so the whole classification is offline + deterministic.
    """
    changed: list[str] = []
    source: list[str] = []
    test: list[str] = []
    doc: list[str] = []
    for raw in changed_paths:
        path = raw.strip()
        if not path:
            continue
        changed.append(path)
        if _is_test_path(path):
            test.append(path)
        elif any(path.endswith(sfx) for sfx in GATE_DOC_SUFFIXES):
            doc.append(path)
        else:
            source.append(path)
    return GateScope(changed=tuple(changed), source=tuple(source),
                     test=tuple(test), doc=tuple(doc))


def gate_scope_cli(cfg: ProductConfig, files=None, base=None) -> int:
    """On-demand CLI: classify a diff's scope and report it (item 4, DORMANT).

    Obtains the changed paths one of two ways, then hands them to the pure core:
      * `files` given -> classify those paths directly;
      * else -> call the monkeypatchable `run_cmd` seam for
        `git -C {cfg.repo} diff --name-only {base or origin/<branch>}...HEAD`
        and `.splitlines()` its output.
    Prints a report CONTAINING the literal `scope: <light|full>` plus the bucket
    counts, and returns `0` (light) / `1` (full) / `2` (git seam `ok=False`).
    Writes NOTHING to disk. A THIN wrapper over `classify_gate_scope`: it adds NO
    classification logic beyond (files or `run_cmd` output) -> splitlines ->
    `classify_gate_scope` -> format, so the printed buckets always equal the
    `GateScope` fields. DORMANT -- no control path calls it; the final gate does
    not consult the verdict.
    """
    if files is None:
        ref = base or f"origin/{cfg.branch}"
        res = run_cmd(["git", "-C", str(cfg.repo), "diff", "--name-only",
                       f"{ref}...HEAD"])
        if not res.ok:
            print(f"gate-scope: git diff failed: {res.out.strip()}")
            return 2
        paths = res.out.splitlines()
    else:
        paths = list(files)
    result = classify_gate_scope(paths)
    print(f"gate-scope: repo {cfg.repo}")
    print(f"  changed: {len(result.changed)}  test: {len(result.test)}  "
          f"doc: {len(result.doc)}  source: {len(result.source)}")
    print(f"scope: {result.scope}")
    return 0 if result.light else 1


# --------------------------------------------------------------------------- #
# Product-gate deterministic pre-check (DORMANT -- roadmap item 20, bite 1).
#
# The tri-perspective product gate (ORG_DESIGN.md section 6, README "tri-
# perspective product gate") subjects each proposal to three decorrelated
# adversarial attacks so runway is not spent on ideas that cannot survive them;
# the default verdict is Kill. Two design details keep the gate "cheap and
# honest": DETERMINISTIC pre-checks that "run before any model call" and bounce
# FOR FREE a proposal missing its impact number / stated appetite / listed
# alternatives, and a circuit-breaker iteration bet. This is the offline,
# deterministic pre-check slice that lands FIRST -- the same purely-additive,
# off-control-path, on-demand-CLI class as spec_lint/lint-spec (item 5),
# classify_gate_scope/gate-scope (item 4), and prd_status/prd (item 11): the
# pipeline NEVER calls it, so build_prompt/run_stage/run_iteration/
# run_continuous/run_execution_plan/dispatcher.py are untouched, NO sentinel/
# config field/artifact is added, and the CLI writes NOTHING. The three keyword
# tuples are module-level + patchable so the vocabularies stay tunable per box
# AND are read at CALL time (not captured at import) -- see Behavior 10. Wiring
# the pre-check into the product-gate STAGE is a later bite (item 20 bite 4).
# --------------------------------------------------------------------------- #
GATE_IMPACT_KEYWORDS: tuple[str, ...] = ("impact",)
GATE_APPETITE_KEYWORDS: tuple[str, ...] = ("appetite",)
GATE_ALTERNATIVES_KEYWORDS: tuple[str, ...] = ("alternative",)


@dataclasses.dataclass(frozen=True)
class ProductGatePrecheck:
    """The deterministic pre-check verdict for one product proposal (item 20).

    Frozen so a computed verdict can't be mutated after the fact, which also
    gives value-equality for free: two `product_gate_precheck` calls on the same
    text hold equal fields, so they compare ``==`` (Behavior 1). The three stored
    booleans are the raw measurements taken from the proposal at call time; the
    three properties are pure derivations, so the whole verdict follows
    deterministically from what was measured (the CLI adds no logic on top). The
    default is Kill: `verdict` is ``"PROCEED"`` ONLY when all three are present.
    """
    impact_present: bool
    appetite_present: bool
    alternatives_present: bool

    @property
    def passed(self) -> bool:
        """True iff the proposal has an impact number, an appetite, AND an alternative."""
        return (self.impact_present and self.appetite_present
                and self.alternatives_present)

    @property
    def verdict(self) -> str:
        """The operator-facing token: ``"PROCEED"`` when passed, else ``"KILL"``.

        Default-Kill: any failed pre-check bounces the proposal for free, before
        a single model call is spent on it.
        """
        return "PROCEED" if self.passed else "KILL"

    @property
    def missing(self) -> tuple[str, ...]:
        """The human labels of the FAILED checks, in a fixed order.

        Order is always ``("impact number", "appetite", "alternatives")``
        filtered to the checks that failed, so the report is stable and
        greppable. Empty tuple iff `passed`.
        """
        labels: list[str] = []
        if not self.impact_present:
            labels.append("impact number")
        if not self.appetite_present:
            labels.append("appetite")
        if not self.alternatives_present:
            labels.append("alternatives")
        return tuple(labels)

    def to_dict(self) -> dict:
        """A pure, JSON-safe pre-check verdict for machine consumers -- a release
        gate / CI job / operator reading the deterministic product-gate pre-check
        (item 20 bite 1), the org-design analog of the other read-only `--json`
        probes (`EscalationClassification.to_dict()` and siblings).

        Returns EXACTLY 6 keys in a fixed order: the three STORED presence
        booleans verbatim (`impact_present` / `appetite_present` /
        `alternatives_present`), then the two derived scalars (`passed` bool /
        `verdict` str) REUSING the frozen properties, then the derived `missing`
        labels as a JSON ARRAY via `list(self.missing)` -- NOT the frozen tuple,
        so the payload round-trips through `json.loads(json.dumps(...))` where a
        tuple would come back a list and break equality. Every value is
        JSON-native (bool / str / list[str]), so `json.dumps(...)` never raises.
        Pure: touches no filesystem, does not mutate the frozen verdict, and
        returns a fresh dict each call. NO `exit_code` key: the CLI exit derives
        from `passed` (0/1) and file-not-found (2) is a CLI-only concern, not
        part of the verdict.
        """
        return {
            "impact_present": self.impact_present,
            "appetite_present": self.appetite_present,
            "alternatives_present": self.alternatives_present,
            "passed": self.passed,
            "verdict": self.verdict,
            "missing": list(self.missing),
        }


def product_gate_precheck(proposal_text: str) -> ProductGatePrecheck:
    """Run the product gate's deterministic pre-checks on a proposal (pure, total).

    Reads the three module knobs -- ``GATE_IMPACT_KEYWORDS``,
    ``GATE_APPETITE_KEYWORDS``, ``GATE_ALTERNATIVES_KEYWORDS`` -- AT CALL TIME
    (not captured at import / as default args) so patching any of them changes a
    subsequent call's verdict (Behavior 10). Performs NO filesystem/subprocess/
    network/clock access, never raises for any ``proposal_text`` (including
    ``""``), and is deterministic, so the same input always yields an equal
    ``ProductGatePrecheck``.

    The IMPACT check demands an impact NUMBER, not just an impact claim: some
    line whose lowercase contains an impact keyword AND that SAME line carries at
    least one digit (so "This has real impact." with no number, and "3 weeks"
    with no impact keyword, both fail impact). Appetite/alternatives need only
    their keyword on some line (no digit). Matching is case-insensitive
    (compare against ``line.lower()``); a "digit" is any ``c`` with
    ``c.isdigit()`` True.
    """
    lowered = [ln.lower() for ln in proposal_text.splitlines()]

    def has_keyword(keywords: tuple[str, ...]) -> bool:
        return any(any(kw in ln for kw in keywords) for ln in lowered)

    impact_present = any(
        any(kw in ln for kw in GATE_IMPACT_KEYWORDS)
        and any(ch.isdigit() for ch in ln)
        for ln in lowered
    )
    return ProductGatePrecheck(
        impact_present=impact_present,
        appetite_present=has_keyword(GATE_APPETITE_KEYWORDS),
        alternatives_present=has_keyword(GATE_ALTERNATIVES_KEYWORDS),
    )


def gate_precheck_cli(path: str, as_json: bool = False) -> int:
    """On-demand CLI: run the product-gate pre-checks on a proposal file.

    Reads the file at ``path``, computes `product_gate_precheck`, prints a
    human-readable report, and returns ``0`` (PROCEED) / ``1`` (KILL) / ``2``
    (file not found). Writes NOTHING to disk. A THIN wrapper over the pure core:
    it adds no pre-check logic beyond read -> `product_gate_precheck` -> format,
    so the printed present/missing figures always match the
    ``ProductGatePrecheck`` fields. With ``as_json=True`` it prints one
    ``json.dumps(result.to_dict(), indent=2)`` document (machine-readable)
    instead of the human report; the ``0``/``1``/``2`` exit contract and the
    missing-file branch are byte-identical in both modes. A missing file returns
    ``2`` (distinct from a KILL verdict) WITHOUT letting a ``FileNotFoundError``
    propagate.
    """
    p = pathlib.Path(path)
    if not p.exists():
        print(f"gate-precheck: file not found: {path}")
        return 2
    result = product_gate_precheck(p.read_text())
    if as_json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(f"gate-precheck: {path}")
        print(f"  impact_present: {result.impact_present}  "
              f"appetite_present: {result.appetite_present}  "
              f"alternatives_present: {result.alternatives_present}")
        if result.missing:
            print(f"  missing: {', '.join(result.missing)}")
        else:
            print("  missing: (none)")
        print(f"verdict: {result.verdict}")
    return 0 if result.passed else 1


# --------------------------------------------------------------------------- #
# Product-gate verdict aggregation (DORMANT -- roadmap item 20, bite 2).
#
# The tri-perspective product gate (ORG_DESIGN.md section 6, README "tri-
# perspective product gate") seats three decorrelated adversaries -- Business,
# Product, and a Senior engineer -- who each vote Go / Kill / Recycle on a
# proposal before any iteration budget is spent: "a proposal that survives three
# decorrelated attacks is worth a bounded bet; a proposal that cannot is killed
# by default (verdicts are Go / Kill / Recycle, and the default is Kill)." Bite 1
# (item 20) shipped the deterministic pre-checks (product_gate_precheck); this
# bite ships the pure, offline AGGREGATION rule that folds three seat verdicts
# into one gate verdict with default-Kill semantics -- the same purely-additive,
# off-control-path, on-demand-CLI class as the sibling product_gate_precheck/
# gate-precheck (item 20 bite 1), spec_lint/lint-spec (item 5), and
# classify_gate_scope/gate-scope (item 4): the pipeline NEVER calls it, so
# build_prompt/run_stage/run_iteration/run_continuous/run_execution_plan/
# dispatcher.py are untouched, NO sentinel/config field/artifact is added, and
# the CLI writes NOTHING. The three verdict-token tuples are module-level +
# patchable so the accepted vocabularies stay tunable per box AND are read at
# CALL time (not captured at import) -- see Behavior 11. Wiring the aggregation
# into the product-gate STAGE (with an events.jsonl gate kind + the fixed
# iteration bet) is a later bite (item 20 bite 4).
# --------------------------------------------------------------------------- #
GATE_GO_TOKENS: tuple[str, ...] = ("go",)
GATE_KILL_TOKENS: tuple[str, ...] = ("kill",)
GATE_RECYCLE_TOKENS: tuple[str, ...] = ("recycle",)


@dataclasses.dataclass(frozen=True)
class ProductGateVerdict:
    """The aggregated verdict of the tri-perspective product gate (item 20).

    Frozen so a computed verdict can't be mutated after the fact, which also
    gives value-equality for free: two `aggregate_gate_verdict` calls on the same
    three seat verdicts hold equal fields, so they compare ``==`` (Behavior 1).
    Each stored field is the NORMALIZED seat token -- one of "GO"/"KILL"/
    "RECYCLE" -- for the Business, Product, and Senior-engineer seats in that
    fixed order; the three properties are pure derivations, so the aggregate
    verdict and the killer/recycler rosters follow deterministically from the
    three seat tokens (the CLI adds no logic on top).
    """
    business: str
    product: str
    engineering: str

    @property
    def verdict(self) -> str:
        """The aggregate gate token by precedence KILL > RECYCLE > GO.

        Any "KILL" seat kills the whole proposal; else any "RECYCLE" seat
        recycles it; else (all three "GO") it is a Go. This is the gate's
        default-Kill rule: it takes unanimous Go minus any veto to advance, so a
        single adversary can stop a bad bet before runway is spent.
        """
        seats = (self.business, self.product, self.engineering)
        if "KILL" in seats:
            return "KILL"
        if "RECYCLE" in seats:
            return "RECYCLE"
        return "GO"

    @property
    def killers(self) -> tuple[str, ...]:
        """Seat NAMES whose normalized verdict is "KILL", in fixed seat order.

        Order is always ("business", "product", "engineering") filtered to the
        "KILL" seats, so the roster is stable and greppable. Empty tuple when no
        seat killed the proposal.
        """
        return self._seats_voting("KILL")

    @property
    def recyclers(self) -> tuple[str, ...]:
        """Seat NAMES whose normalized verdict is "RECYCLE", in fixed seat order.

        The "RECYCLE" analogue of `killers`; empty tuple when no seat recycled.
        """
        return self._seats_voting("RECYCLE")

    def _seats_voting(self, token: str) -> tuple[str, ...]:
        """The seat names whose stored verdict equals ``token``, in seat order.

        Shared by `killers`/`recyclers` so both rosters iterate the seats in the
        one canonical order (business, product, engineering).
        """
        seats = (("business", self.business),
                 ("product", self.product),
                 ("engineering", self.engineering))
        return tuple(name for name, verdict in seats if verdict == token)

    def to_dict(self) -> dict:
        """A pure, JSON-safe product-gate verdict for machine consumers -- a
        release gate, a CI job, or an operator dashboard consuming the
        tri-perspective seat aggregation (item 20 bite 2), the org-design analog
        of `ScoutPhasePlan.to_dict()` and the other read-only `--json` probes.

        Returns EXACTLY 6 keys: the three stored seat tokens verbatim
        (`business` / `product` / `engineering`), then the derived `verdict` /
        `killers` / `recyclers`, each REUSING the frozen fields/properties so the
        JSON can never disagree with what the CLI renders or the exit code
        returns. `killers` / `recyclers` are `list(self.killers)` /
        `list(self.recyclers)` (the tuple properties coerced to JSON-native
        lists, like the `escalation-check` categories -- a bare tuple would be
        read back by json.loads as a list and break the round-trip). Pure:
        touches no filesystem, does not mutate the frozen verdict, and returns a
        fresh dict each call. NO `exit_code` key: the CLI exit derives from
        `verdict` (0/1/2 = GO/KILL/RECYCLE) and the value object does not carry
        one -- same as every prior org-design CLI.
        """
        return {
            "business": self.business,
            "product": self.product,
            "engineering": self.engineering,
            "verdict": self.verdict,
            "killers": list(self.killers),
            "recyclers": list(self.recyclers),
        }


def aggregate_gate_verdict(
    business: str, product: str, engineering: str
) -> ProductGateVerdict:
    """Fold three raw seat verdicts into one gate verdict (pure, total).

    Normalizes each raw seat verdict, then stores the three normalized tokens on
    a `ProductGateVerdict` (whose properties derive the aggregate verdict + the
    killer/recycler rosters). Reads the module knobs -- ``GATE_GO_TOKENS``,
    ``GATE_KILL_TOKENS``, ``GATE_RECYCLE_TOKENS`` -- AT CALL TIME (not captured at
    import / as default args) so patching any of them changes a subsequent call's
    result (Behavior 11). Performs NO filesystem/subprocess/network/clock access,
    never raises for any three string inputs (including ``""``), and is
    deterministic, so equal inputs always yield an ``==``-equal result.

    Normalization is case-insensitive and whitespace-tolerant: a raw seat verdict
    is ``.strip().lower()``-ed, then matched by EXACT membership (whole-string,
    NOT substring -- substring matching would wrongly KILL a phrase like "we
    should not kill this") against the three token tuples. Anything matching none
    of them -- an unrecognized word or the empty string -- normalizes to "KILL",
    the gate's fail-closed default (Behavior 4). GO is checked first, then KILL,
    then RECYCLE, so if a patched vocabulary lists one token in two tuples the
    earlier bucket wins deterministically.
    """

    def normalize(raw: str) -> str:
        token = raw.strip().lower()
        if token in GATE_GO_TOKENS:
            return "GO"
        if token in GATE_KILL_TOKENS:
            return "KILL"
        if token in GATE_RECYCLE_TOKENS:
            return "RECYCLE"
        return "KILL"

    return ProductGateVerdict(
        business=normalize(business),
        product=normalize(product),
        engineering=normalize(engineering),
    )


def gate_verdict_cli(business: str, product: str, engineering: str, as_json: bool = False) -> int:
    """On-demand CLI: aggregate three raw seat verdicts into one gate verdict.

    Computes `aggregate_gate_verdict`, prints the three NORMALIZED seat verdicts,
    the killer and recycler rosters (or "(none)"), and a final ``verdict:`` line,
    then returns ``0`` (GO) / ``1`` (KILL) / ``2`` (RECYCLE). Writes NOTHING to
    disk. A THIN wrapper over the pure core: it adds no aggregation logic beyond
    aggregate -> format, so the printed seat/roster/verdict figures always match
    the ``ProductGateVerdict`` fields and properties. With ``as_json=True`` it
    prints one ``json.dumps(result.to_dict(), indent=2)`` document
    (machine-readable) instead of the human report; the ``0``/``1``/``2`` exit
    contract is byte-identical in both modes.
    """
    result = aggregate_gate_verdict(business, product, engineering)
    if as_json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print("gate-verdict:")
        print(f"  business: {result.business}  product: {result.product}  "
              f"engineering: {result.engineering}")
        print(f"  killers: {', '.join(result.killers) if result.killers else '(none)'}")
        print(f"  recyclers: "
              f"{', '.join(result.recyclers) if result.recyclers else '(none)'}")
        print(f"verdict: {result.verdict}")
    return {"GO": 0, "KILL": 1, "RECYCLE": 2}[result.verdict]


# --------------------------------------------------------------------------- #
# Per-role MODEL OVERRIDE resolver (DORMANT -- roadmap item 20, bite 3 of ~4).
#
# ORG_DESIGN section 9 / item 20 want a per-role model override: the staffing
# manifest already carries a per-role `model` note (parsed by
# `parse_staffing_manifest`, ~L1723), but nothing turns that note into the
# argument vector a launcher would actually use. This bite supplies exactly that
# missing PURE mapping -- a model note in, an agent-CLI argv out -- so the
# product-gate PM and the release gate can run a DIFFERENT model than the
# builder (a decorrelated adversarial seat: a same-model reviewer favors its own
# author). Same purely-additive, off-control-path, on-demand-CLI class as the
# sibling product_gate_precheck/gate-precheck (item 20 bite 1) and
# aggregate_gate_verdict/gate-verdict (item 20 bite 2): the pipeline NEVER calls
# it, so build_prompt/run_stage/run_iteration/run_continuous/run_execution_plan/
# dispatcher.py are untouched, NO sentinel/config field/artifact is added, and
# the CLI writes NOTHING (env/args level only, no subprocess launch). The
# argument template is a module-level + patchable tuple read at CALL time (not
# captured at import) -- see Behavior 6. The load-bearing invariant is the
# passthrough: an empty/whitespace note returns the base argv byte-identical (no
# args appended), so a later WIRING bite (bite 3b / bite 4) can adopt the
# resolver in the live launch path with zero risk to the default (no-override)
# behavior. Wiring the override into run_stage / the manifest executor is that
# later bite; this bite is the pure resolver ALONE.
# --------------------------------------------------------------------------- #
MODEL_ARG_TEMPLATE: tuple[str, ...] = ("--model", "{model}")


@dataclasses.dataclass(frozen=True)
class RoleModelInvocation:
    """A resolved per-role agent-CLI invocation for a model override (item 20).

    Frozen so a resolved invocation cannot be mutated after the fact, which also
    gives value-equality for free: two `resolve_role_model_argv` calls on the
    same base argv + note hold equal fields, so they compare ``==`` (Behavior 1).
    `model` is the stripped model note that was applied ("" when no override was
    requested); `argv` is the full argument vector the launcher would use -- the
    base argv with the model args APPENDED, or the base argv unchanged in the
    passthrough case.
    """
    model: str
    argv: tuple[str, ...]

    @property
    def overridden(self) -> bool:
        """True iff a non-empty model note was applied (a pure derivation).

        Equal to ``bool(self.model)``: the passthrough result carries
        ``model == ""`` -> False, and an applied override carries a non-empty
        stripped note -> True (Behavior 8).
        """
        return bool(self.model)

    def to_dict(self) -> dict:
        """Machine-readable dict of this resolution (Behavior 1, item 20).

        The three keys are the two stored fields in declaration order (``model``
        then ``argv``) followed by the derived ``overridden`` property LAST, so
        the str-list ``argv`` lands in the MIDDLE. ``argv`` is coerced to a plain
        ``list`` (one level): the frozen ``tuple`` would round-trip through JSON
        as a list and break ``json.loads(json.dumps(d)) == d`` otherwise. No
        ``exit_code`` key -- the CLI derives the exit code from ``overridden``.
        """
        return {
            "model": self.model,
            "argv": list(self.argv),
            "overridden": self.overridden,
        }


def resolve_role_model_argv(
    base_argv: Sequence[str],
    model_note: str,
    template: Sequence[str] | None = None,
) -> RoleModelInvocation:
    """Map a per-role model note to the agent-CLI argv a launcher would use.

    Pure, total, deterministic: performs NO filesystem/subprocess/network/clock
    access, never raises for any string sequence `base_argv` and any string
    `model_note`, and equal inputs always yield an ``==``-equal result. Never
    mutates `base_argv` (it is only iterated); the returned `argv` is a tuple.

    Passthrough (Behavior 3): when ``model_note.strip()`` is empty (the note is
    ``""`` or whitespace-only) the result is the base argv UNCHANGED --
    ``argv == tuple(base_argv)`` with no args appended and ``model == ""`` -- the
    "absent an override, current behavior is unchanged" invariant a later wiring
    bite relies on.

    Override (Behaviors 4/5): when the stripped note is non-empty the model args
    are APPENDED after the base argv, in order -- each template element has the
    literal substring ``{model}`` replaced with the stripped note (an element
    with no ``{model}`` is appended unchanged). With the default
    ``MODEL_ARG_TEMPLATE == ("--model", "{model}")`` and note ``"opus"`` the
    appended args are ``("--model", "opus")``.

    The template is read AT CALL TIME (Behavior 6): with ``template is None`` the
    module constant ``MODEL_ARG_TEMPLATE`` is read here (not captured at import /
    as a default-arg value), so monkeypatching it changes a subsequent call; an
    explicit ``template=`` argument overrides the module constant for that call.
    """
    base = tuple(base_argv)
    model = model_note.strip()
    if not model:
        return RoleModelInvocation(model="", argv=base)
    tmpl = MODEL_ARG_TEMPLATE if template is None else tuple(template)
    appended = tuple(element.replace("{model}", model) for element in tmpl)
    return RoleModelInvocation(model=model, argv=base + appended)


def role_model_cli(model_note: str, as_json: bool = False) -> int:
    """On-demand CLI: resolve a per-role model note over the launcher base argv.

    Resolves `resolve_role_model_argv` over the module ``AGENT_RUN_ARGS`` as the
    base argv and ``MODEL_ARG_TEMPLATE`` as the template (BOTH read at call time
    so a monkeypatch bites -- Behavior 11), prints the resolved argv and a
    summary (the applied model + ``overridden: true|false``), then returns ``0``
    when an override was applied / ``1`` on passthrough (empty/whitespace note).
    Writes NOTHING to disk. A THIN wrapper over the pure core: it adds no logic
    beyond resolve -> format, so the printed argv/model/overridden figures always
    match the `RoleModelInvocation` fields and property. With ``as_json``
    the same resolution is emitted as one machine-readable JSON document
    instead of the human render; the exit code is identical in both modes.
    """
    result = resolve_role_model_argv(AGENT_RUN_ARGS, model_note)
    if as_json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print("role-model:")
        print(f"  argv: {list(result.argv)}")
        print(f"  model: {result.model or '(none)'}")
        print(f"  overridden: {'true' if result.overridden else 'false'}")
    return 0 if result.overridden else 1


# --------------------------------------------------------------------------- #
# Composite product-gate decision (DORMANT -- roadmap item 20, bite 4a).
#
# The tri-perspective product gate (ORG_DESIGN.md section 6) wants a proposal to
# survive the deterministic pre-checks FIRST -- bouncing for free before any
# model call is spent -- and only then face three decorrelated seat votes folded
# into one Go/Kill/Recycle verdict with default-Kill. Bites 1-3 shipped the
# three pure ingredients dormant: product_gate_precheck (the free pre-check,
# item 20 bite 1), aggregate_gate_verdict (the seat aggregation, item 20 bite 2),
# and resolve_role_model_argv (the per-role model override, item 20 bite 3).
# This bite ships the pure COMPOSITION that realizes the ordering: run the free
# pre-check, and consult the seats ONLY if it passes. It is the same purely-
# additive, off-control-path, on-demand-CLI class as its siblings
# product_gate_precheck/gate-precheck (item 20 bite 1) and aggregate_gate_verdict
# /gate-verdict (item 20 bite 2): the pipeline NEVER calls it, so build_prompt/
# run_stage/run_iteration/run_continuous/run_execution_plan/dispatcher.py are
# untouched, NO sentinel/config field/artifact is added, and the CLI writes
# NOTHING. It reuses the two shipped cores (which thereby gain a new NON-
# orchestrator caller but stay absent from the orchestrators, so the iter-73/
# iter-74 dormancy tests still hold) and inherits their call-time knob reads.
# Wiring the composite into the product-gate STAGE (with an events.jsonl gate
# kind + the fixed iteration bet) is the final item-20 bite.
# --------------------------------------------------------------------------- #
@dataclasses.dataclass(frozen=True)
class ProductGateDecision:
    """The composite tri-perspective product-gate decision for one proposal (item 20).

    Frozen so a computed decision can't be mutated after the fact, which also
    gives value-equality for free: two `decide_product_gate` calls on the same
    four args hold equal fields, so they compare ``==`` (Behavior 1). Folds the
    two shipped decision cores in the ORG_DESIGN section-6 ORDER: the
    deterministic `precheck` runs first and, when it does NOT pass, the proposal
    is bounced FOR FREE and `seats` is ``None`` -- the seat aggregation is never
    computed (Behavior 4). Only when the pre-check passes does `seats` hold the
    aggregated `ProductGateVerdict` (Behavior 5). The two properties are pure
    derivations, so the composite verdict follows deterministically from the two
    stored cores (the CLI adds no logic on top).
    """
    precheck: ProductGatePrecheck
    seats: ProductGateVerdict | None

    @property
    def bounced(self) -> bool:
        """True iff the pre-check did NOT pass (equivalently, iff `seats is None`).

        The bounce-for-free signal: a bounced proposal never reaches the three
        seats, so no model call is spent on a proposal the free deterministic
        checks already reject (Behavior 6).
        """
        return not self.precheck.passed

    @property
    def verdict(self) -> str:
        """The composite gate token: ``"KILL"`` when bounced, else the seat verdict.

        A bounced proposal is a default-Kill (the pre-check failed, so the seats
        were never consulted); otherwise the verdict is the aggregated seat
        verdict -- one of ``"GO"``/``"KILL"``/``"RECYCLE"`` (Behavior 7). The
        ``self.seats is None`` guard is redundant with `bounced` by construction
        (they are equivalent), but keeps the property total and None-safe.
        """
        if self.bounced or self.seats is None:
            return "KILL"
        return self.seats.verdict

    def to_dict(self) -> dict:
        """A pure, JSON-safe composite product-gate decision for machine
        consumers -- a release gate, a CI job, or an operator dashboard that
        needs the WHOLE item-20 gate as one document, the org-design analog of
        the other read-only `--json` probes. It is the FIRST composite: rather
        than re-deriving any figure it NESTS the two already-shipped leaf
        `to_dict`s, so the payload can never disagree with the leaves, the human
        render, or the exit code.

        Returns EXACTLY 4 keys in a fixed order: `precheck` (the nested 6-key
        `ProductGatePrecheck.to_dict()` verbatim), then `seats` (the nested
        6-key `ProductGateVerdict.to_dict()` when the pre-check passed, else JSON
        ``null`` -- a bounced proposal never computed the seats, Behavior 4),
        then the two derived scalars `bounced` (bool) / `verdict` (str) REUSING
        the frozen properties. The nested leaf dicts already coerce their tuple
        fields to JSON-native lists, and ``None`` round-trips to ``None``, so the
        whole document round-trips through `json.loads(json.dumps(...))`. Pure:
        touches no filesystem, does not mutate the frozen decision, and returns a
        fresh dict each call. NO `exit_code` key: the CLI exit derives from
        `verdict` (0/1/2 = GO/KILL/RECYCLE) and file-not-found (3) is a CLI-only
        concern.
        """
        return {
            "precheck": self.precheck.to_dict(),
            "seats": self.seats.to_dict() if self.seats is not None else None,
            "bounced": self.bounced,
            "verdict": self.verdict,
        }


def decide_product_gate(
    proposal_text: str, business: str, product: str, engineering: str
) -> ProductGateDecision:
    """Compose the two shipped product-gate cores into one decision (pure, total).

    Realizes the ORG_DESIGN section-6 ORDERING: run the deterministic
    `product_gate_precheck` FIRST and, if it does NOT pass, bounce the proposal
    for free -- `seats` is ``None`` and `aggregate_gate_verdict` is NEVER called,
    so no model call would be spent on a proposal the free checks already reject
    (Behavior 4). Only when the pre-check passes are the three seat verdicts
    folded via `aggregate_gate_verdict` (Behavior 5). Adds NO gate logic of its
    own beyond this composition + ordering, so the decision follows
    deterministically from the two shipped cores.

    Pure, total, deterministic: performs NO filesystem/subprocess/network/clock
    access (it only calls the two pure cores), never raises for ANY four string
    inputs (including all four ``""``), and equal inputs always yield an
    ``==``-equal `ProductGateDecision`. Because it reuses the shipped cores, it
    honors their call-time knob reads -- patching e.g. ``GATE_APPETITE_KEYWORDS``
    or ``GATE_GO_TOKENS`` by bare name changes a subsequent decision (Behavior 8).
    """
    precheck = product_gate_precheck(proposal_text)
    seats = (
        aggregate_gate_verdict(business, product, engineering)
        if precheck.passed
        else None
    )
    return ProductGateDecision(precheck=precheck, seats=seats)


def product_gate_cli(
    path: str, business: str, product: str, engineering: str,
    as_json: bool = False,
) -> int:
    """On-demand CLI: run the composite product gate on a proposal file.

    Reads the proposal at ``path``, computes `decide_product_gate`, prints the
    pre-check present/missing figures followed by either the seat verdicts +
    killer/recycler rosters (when the pre-check passed, `seats` not ``None``) or
    a bounced note (when it did not, `seats is None`), then a final ``verdict:``
    line, and returns ``{"GO": 0, "KILL": 1, "RECYCLE": 2}[decision.verdict]``
    (so a bounced proposal returns ``1`` KILL). A missing file prints a
    ``file not found`` message naming the path and returns ``3`` -- distinct from
    every verdict code -- WITHOUT letting a ``FileNotFoundError`` propagate.
    Writes NOTHING to disk. A THIN wrapper over the pure core: it adds no gate
    logic beyond read -> `decide_product_gate` -> format, so the printed figures
    always match the ``ProductGateDecision`` fields and properties. With
    ``as_json`` the whole decision is emitted as one machine-readable JSON
    document (nesting both leaf `to_dict` outputs) instead of the human
    report; the exit code is identical in both modes.
    """
    p = pathlib.Path(path)
    if not p.exists():
        print(f"product-gate: file not found: {path}")
        return 3
    decision = decide_product_gate(p.read_text(), business, product, engineering)
    if as_json:
        print(json.dumps(decision.to_dict(), indent=2))
    else:
        pc = decision.precheck
        print(f"product-gate: {path}")
        print(f"  impact_present: {pc.impact_present}  "
              f"appetite_present: {pc.appetite_present}  "
              f"alternatives_present: {pc.alternatives_present}")
        if pc.missing:
            print(f"  missing: {', '.join(pc.missing)}")
        else:
            print("  missing: (none)")
        seats = decision.seats
        if seats is None:
            print("  seats: bounced (pre-check failed, seats not consulted)")
        else:
            print(f"  business: {seats.business}  product: {seats.product}  "
                  f"engineering: {seats.engineering}")
            print(f"  killers: "
                  f"{', '.join(seats.killers) if seats.killers else '(none)'}")
            print(f"  recyclers: "
                  f"{', '.join(seats.recyclers) if seats.recyclers else '(none)'}")
        print(f"verdict: {decision.verdict}")
    return {"GO": 0, "KILL": 1, "RECYCLE": 2}[decision.verdict]


# --------------------------------------------------------------------------- #
# CEO-escalation classifier (DORMANT -- roadmap item 21, org-design section 9,
# offline slice). The CEO decides autonomously EXCEPT where a deterministic
# predicate detects one of five RESERVED categories that must escalate to the
# human operator before anything ships: (1) security / credentials,
# (2) personal data / PII, (3) spending real money, (4) legal / licensing
# exposure, (5) changes to public visibility. The committed scripts/leak_guard.py
# is section 9's FIRST shipped instance of this pattern (category 2, PII,
# enforced at the release gate); item 21 GENERALIZES it to all five categories.
# This is the pure, offline, deterministic DETECTION core plus an operator-facing
# read-only CLI -- the same purely-additive, off-control-path, on-demand-CLI
# class as product_gate_precheck/gate-precheck (item 20 bite 1),
# aggregate_gate_verdict/gate-verdict (bite 2), and decide_product_gate/
# product-gate (bite 4a): the pipeline NEVER calls it, so build_prompt/run_stage/
# run_iteration/run_continuous/run_execution_plan/dispatcher.py are untouched, NO
# sentinel/config field/artifact is added, and the CLI writes NOTHING. The five
# keyword vocabularies are module-level + patchable so they stay tunable per box
# AND are read at CALL time (not captured at import) -- see Behavior 13. Wiring
# the predicate into the release gate is a later bite (item 21 bite 2); this bite
# only REPORTS which reserved categories a change touches.
# --------------------------------------------------------------------------- #
ESCALATION_SECURITY_KEYWORDS: tuple[str, ...] = (
    "credential", "password", "secret", "api key", "api_key", "private key",
    "private_key", "access key", "access_key", "ssh key",
)
ESCALATION_PII_KEYWORDS: tuple[str, ...] = (
    "ssn", "social security", "date of birth", "passport number",
    "home address", "personal data", "phone number", "biometric",
)
ESCALATION_MONEY_KEYWORDS: tuple[str, ...] = (
    "payment", "billing", "invoice", "credit card", "stripe", "paypal",
    "purchase order", "wire transfer", "real money",
)
ESCALATION_LEGAL_KEYWORDS: tuple[str, ...] = (
    "license", "licence", "copyright", "patent", "trademark",
    "terms of service", "proprietary", "indemnif",
)
ESCALATION_VISIBILITY_KEYWORDS: tuple[str, ...] = (
    "make public", "make it public", "publish to", "open source",
    "open-source", "public repository", "publicly visible", "go public",
)


@dataclasses.dataclass(frozen=True)
class EscalationClassification:
    """Which of the five reserved-escalation categories a change touches (item 21).

    Frozen so a computed classification can't be mutated after the fact, which
    also gives value-equality for free: two `classify_escalation` calls on the
    same text hold equal fields, so they compare ``==`` (Behavior 1). The five
    stored booleans are the raw category hits taken from the text at call time,
    in ORG_DESIGN section-9 order (security, pii, money, legal, visibility); the
    three properties are pure derivations, so the whole classification follows
    deterministically from what was detected (the CLI adds no logic on top). The
    default is CLEAR: `escalate` is True ONLY when at least one category hit.
    """
    security: bool
    pii: bool
    money: bool
    legal: bool
    visibility: bool

    @property
    def categories(self) -> tuple[str, ...]:
        """The labels of the True category fields, in the fixed section-9 order.

        Order is always ``("security", "pii", "money", "legal", "visibility")``
        filtered to the categories that hit, regardless of the order the keywords
        appear in the text (Behavior 11). Empty tuple iff nothing hit.
        """
        labels: list[str] = []
        if self.security:
            labels.append("security")
        if self.pii:
            labels.append("pii")
        if self.money:
            labels.append("money")
        if self.legal:
            labels.append("legal")
        if self.visibility:
            labels.append("visibility")
        return tuple(labels)

    @property
    def escalate(self) -> bool:
        """True iff ANY reserved category was detected (needs human sign-off)."""
        return bool(self.categories)

    @property
    def verdict(self) -> str:
        """Operator token: ``"ESCALATE"`` when any category hit, else ``"CLEAR"``."""
        return "ESCALATE" if self.escalate else "CLEAR"

    def to_dict(self) -> dict:
        """A pure, JSON-safe classification for machine consumers -- a release
        gate / CI job / operator routing an escalation (item 21 bite 1), the
        org-design analog of `SingleBrainStatus.to_dict()` and the other
        read-only `--json` probes.

        Returns EXACTLY 8 keys: the five STORED category booleans verbatim
        (`security`/`pii`/`money`/`legal`/`visibility`), then the derived
        `categories` as a JSON ARRAY via `list(self.categories)` -- NOT the
        frozen tuple, so the payload round-trips through
        `json.loads(json.dumps(...))` where a tuple would come back a list and
        break equality -- then the two derived verdict values (`escalate` bool /
        `verdict` str), each REUSING the frozen properties so the JSON can never
        disagree with what the CLI renders or the exit code returns. Every value
        is JSON-native (bool / list[str] / str), so `json.dumps(...)` never
        raises. Pure: touches no filesystem, does not mutate the frozen
        classification, and returns a fresh dict each call. NO `exit_code` key:
        the CLI exit derives from `escalate` (0/1) and file-not-found (2) is a
        CLI-only concern, not part of the classification.
        """
        return {
            "security": self.security,
            "pii": self.pii,
            "money": self.money,
            "legal": self.legal,
            "visibility": self.visibility,
            "categories": list(self.categories),
            "escalate": self.escalate,
            "verdict": self.verdict,
        }


def classify_escalation(text: str) -> EscalationClassification:
    """Classify which reserved-escalation categories a change touches (pure, total).

    Reads the five module vocabularies -- ``ESCALATION_SECURITY_KEYWORDS``,
    ``ESCALATION_PII_KEYWORDS``, ``ESCALATION_MONEY_KEYWORDS``,
    ``ESCALATION_LEGAL_KEYWORDS``, ``ESCALATION_VISIBILITY_KEYWORDS`` -- AT CALL
    TIME (not captured at import / as default args) so patching any of them
    changes a subsequent call's result (Behavior 13). Performs NO filesystem/
    subprocess/network/clock access, never raises for any ``text`` (including
    ``""``), and is deterministic, so the same input always yields an equal
    ``EscalationClassification``.

    Matching is case-insensitive over the FULL input text: the text is lowercased
    once and a category hits iff ANY member substring of its vocabulary is present
    (no unified-diff parsing -- a later wiring bite decides whether to pass only
    the diff's added lines).
    """
    lowered = text.lower()

    def hits(keywords: tuple[str, ...]) -> bool:
        return any(kw in lowered for kw in keywords)

    return EscalationClassification(
        security=hits(ESCALATION_SECURITY_KEYWORDS),
        pii=hits(ESCALATION_PII_KEYWORDS),
        money=hits(ESCALATION_MONEY_KEYWORDS),
        legal=hits(ESCALATION_LEGAL_KEYWORDS),
        visibility=hits(ESCALATION_VISIBILITY_KEYWORDS),
    )


def escalation_check_cli(path: str, as_json: bool = False) -> int:
    """On-demand CLI: classify a file's content for reserved-escalation categories.

    Reads the file at ``path``, computes `classify_escalation`, prints the file
    path, the triggered category labels (or ``(none)`` when clear), and a final
    ``verdict:`` line, and returns ``1`` (ESCALATE) / ``0`` (CLEAR). Writes
    NOTHING to disk. A THIN wrapper over the pure core: it adds no detection
    logic beyond read -> `classify_escalation` -> format, so the printed
    categories always match the ``EscalationClassification``. With
    ``as_json=True`` it prints one ``json.dumps(result.to_dict(),
    indent=2)`` document (machine-readable) instead of the human
    report; the ``0``/``1``/``2`` exit contract and the missing-file
    branch are byte-identical in both modes. A missing file
    prints a ``file not found`` message naming the path and returns ``2``
    (distinct from a verdict code) WITHOUT letting a ``FileNotFoundError``
    propagate.
    """
    p = pathlib.Path(path)
    if not p.exists():
        print(f"escalation-check: file not found: {path}")
        return 2
    result = classify_escalation(p.read_text())
    if as_json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(f"escalation-check: {path}")
        if result.categories:
            print(f"  categories: {', '.join(result.categories)}")
        else:
            print("  categories: (none)")
        print(f"verdict: {result.verdict}")
    return 1 if result.escalate else 0


# --------------------------------------------------------------------------- #
# Bounded re-staffing: the fixed-N no-trigger cadence-review fallback (DORMANT
# -- roadmap item 22 bite 1, org-design section 7). Even when no anomaly
# trigger fires, a quiet loop can silently drift precisely BECAUSE nothing
# looked wrong; section 7 bounds that failure mode with a fixed-N fallback:
# "if no trigger has fired for 5 consecutive iterations, the CEO + PM
# proactively review the project anyway ... Start at N=5; relax toward N=10
# once the review history shows steering is rarely needed." This is the
# smallest self-contained piece of item 22 -- a TOTAL arithmetic state-machine
# with a complete truth table. Same purely-additive, off-control-path,
# on-demand-CLI class as gate-precheck (item 20 bite 1) / gate-verdict (bite 2)
# / role-model (bite 3) / product-gate (bite 4a) / escalation-check (item 21
# bite 1): the pipeline NEVER calls it, so build_prompt/run_stage/
# run_iteration/run_continuous/run_execution_plan/dispatcher.py are untouched,
# NO sentinel/config field/artifact is added, and the CLI writes NOTHING. The
# threshold N is a module-level + patchable constant read at CALL time (not
# captured at import / as a default arg) so it stays tunable per box -- see
# Behavior 9. WIRING the cadence counter into the loop (increment on a quiet
# iteration, queue the CEO+PM review when it fires) is the item-22 final
# control-flow bite; this bite only DECIDES.
# --------------------------------------------------------------------------- #
CADENCE_REVIEW_N: int = 5


@dataclasses.dataclass(frozen=True)
class CadenceReviewDecision:
    """Whether the fixed-N no-trigger cadence fallback fires this iteration (item 22).

    Frozen so a computed decision can't be mutated after the fact, which also
    gives value-equality for free: two `decide_cadence_review` calls on the same
    arguments hold equal fields, so they compare ``==`` (Behavior 1). The three
    stored fields are the raw decision inputs -- ``counter`` (the quiet-streak
    length carried in from prior iterations, BEFORE this one), ``trigger_fired``
    (did any anomaly trigger fire THIS iteration), and ``threshold`` (the
    effective N that was used) -- and the three properties are pure derivations,
    so the whole decision follows deterministically from them (the CLI adds no
    logic on top).
    """
    counter: int
    trigger_fired: bool
    threshold: int

    @property
    def fires(self) -> bool:
        """True iff the no-trigger fallback fires this iteration.

        Fires ONLY on a quiet iteration (no real trigger) whose incremented
        streak reaches the threshold: ``(not trigger_fired) and (counter + 1 >=
        threshold)``. The ``+ 1`` counts THIS quiet iteration (Behavior 6's exact
        boundary at ``counter + 1 == threshold``); the ``>=`` (not ``==``) means
        an already-at/over-threshold quiet streak still fires (Behavior 7). A
        real trigger this iteration breaks the streak, so the fallback never also
        fires (Behavior 4).
        """
        return (not self.trigger_fired) and (self.counter + 1 >= self.threshold)

    @property
    def next_counter(self) -> int:
        """The quiet-streak counter to carry into the next iteration.

        Resets to 0 whenever the streak is broken or consumed -- either a real
        trigger fired (Behavior 4) or the fallback fires (Behaviors 6/7); else it
        grows by one to count this quiet iteration (Behavior 5).
        """
        if self.trigger_fired or self.fires:
            return 0
        return self.counter + 1

    @property
    def verdict(self) -> str:
        """Operator token: ``"REVIEW"`` when the fallback fires, else ``"CONTINUE"``."""
        return "REVIEW" if self.fires else "CONTINUE"

    def to_dict(self) -> dict:
        """A pure, JSON-safe cadence-review decision for machine consumers --
        an operator, a CI job, or a dashboard consuming the fixed-N no-trigger
        cadence verdict (item 22 bite 1), the org-design analog of
        `EscalationClassification.to_dict()` and the other read-only `--json`
        probes.

        Returns EXACTLY 6 keys: the three STORED decision inputs verbatim
        (`counter`/`trigger_fired`/`threshold`), then the three derived values
        (`fires` bool / `next_counter` int / `verdict` str), each REUSING the
        frozen properties so the JSON can never disagree with what the CLI
        renders or the exit code returns. Every value is a JSON-native scalar
        (int / bool / str) -- there is NO list/tuple/nested field (unlike
        `escalation-check`'s `categories`), so `json.dumps(...)` never raises
        and no `list(...)` coercion is needed. Pure: touches no filesystem,
        does not mutate the frozen decision, and returns a fresh dict each
        call. NO `exit_code` key: the CLI exit derives from `fires` (0/1) and
        `cadence-review` takes no file, so there is no file-not-found (2) path
        to serialize -- contrast `escalation-check`.
        """
        return {
            "counter": self.counter,
            "trigger_fired": self.trigger_fired,
            "threshold": self.threshold,
            "fires": self.fires,
            "next_counter": self.next_counter,
            "verdict": self.verdict,
        }


def decide_cadence_review(
    counter: int, trigger_fired: bool, n: int | None = None
) -> CadenceReviewDecision:
    """Decide whether the fixed-N no-trigger cadence fallback fires (pure, total).

    ``counter`` is the quiet-streak length carried in from prior iterations,
    ``trigger_fired`` is whether any anomaly trigger fired THIS iteration, and
    ``n`` is an optional explicit threshold override. When ``n`` is None the
    threshold is read from the module-level ``CADENCE_REVIEW_N`` AT CALL TIME
    (not captured as a default arg / at import) so patching it changes a
    subsequent call's result (Behavior 9); an explicit ``n`` overrides it for
    that call only (Behavior 10). Performs NO filesystem/subprocess/network/
    clock access, never raises for any int ``counter`` (including 0 / negatives)
    or ``n``, and is deterministic, so equal arguments always yield an equal
    ``CadenceReviewDecision``. A thin normalizer: it only fills in the threshold
    default; all fire/reset logic lives in the frozen result's pure properties.
    """
    threshold = CADENCE_REVIEW_N if n is None else n
    return CadenceReviewDecision(
        counter=counter, trigger_fired=bool(trigger_fired), threshold=threshold
    )


def cadence_review_cli(counter: int, trigger_fired: bool, n: int | None, as_json: bool = False) -> int:
    """On-demand CLI: report the fixed-N no-trigger cadence-review decision.

    Computes `decide_cadence_review`, prints the counter, trigger_fired,
    threshold, fires, and next_counter figures plus a final ``verdict:`` line,
    and returns ``1`` (REVIEW) / ``0`` (CONTINUE) -- non-zero = action needed,
    mirroring `escalation-check`. With ``as_json=True`` it prints one
    ``json.dumps(result.to_dict(), indent=2)`` document (machine-readable)
    instead of the human report; the ``0``/``1`` exit contract is
    byte-identical in both modes. Writes NOTHING to disk. A THIN wrapper over the
    pure core: it adds no logic beyond decide -> format, so the printed figures
    always match the ``CadenceReviewDecision``. Takes no file, so there is no
    file-not-found path.
    """
    result = decide_cadence_review(counter, trigger_fired, n)
    if as_json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(f"cadence-review: counter={result.counter} "
              f"trigger_fired={result.trigger_fired} threshold={result.threshold}")
        print(f"  fires: {result.fires}")
        print(f"  next_counter: {result.next_counter}")
        print(f"verdict: {result.verdict}")
    return 1 if result.fires else 0


# --------------------------------------------------------------------------- #
# Bounded re-staffing: the hysteresis-constrained re-staffing DIFF core (DORMANT
# -- roadmap item 22 bite 2, org-design section 10). Team-composition changes
# are PROPOSALS, not drift: a re-staffing review emits a DIFF against
# staffing.json (it never edits it) constrained by three hysteresis rules that
# prevent thrash (the multi-agent equivalent of a re-org every sprint) --
# (1) a role must serve a minimum tenure K before it can be deactivated,
# (2) at most a capped number of changes are accepted per review, and
# (3) every change must cite the logged trigger that motivated it. Item 22 bite
# 1 (iter 78) shipped the cadence half (decide_cadence_review); this bite ships
# the DIFF half: take a set of PROPOSED changes and partition them into a
# hysteresis-valid ACCEPTED diff plus tagged REJECTIONS. Same purely-additive,
# off-control-path, on-demand-CLI class as gate-precheck (item 20 bite 1) /
# gate-verdict (bite 2) / role-model (bite 3) / product-gate (bite 4a) /
# escalation-check (item 21 bite 1) / cadence-review (item 22 bite 1): the
# pipeline NEVER calls it, so build_prompt/run_stage/run_iteration/
# run_continuous/run_execution_plan/dispatcher.py are untouched, NO
# sentinel/config field/artifact is added, and the CLI writes NOTHING. The two
# thresholds K and cap are module-level + patchable constants read at CALL time
# (not captured at import / as default args) so they stay tunable per box --
# see Behaviors 9/10. WIRING a re-staffing STAGE into the pipeline (and APPLYING
# the accepted diff to staffing.json) is the item-22 final control-flow bite;
# this bite only DECIDES.
# --------------------------------------------------------------------------- #
RESTAFFING_MIN_TENURE_K: int = 3
RESTAFFING_MAX_CHANGES: int = 2


@dataclasses.dataclass(frozen=True)
class RestaffingChange:
    """A single proposed team-composition change (item 22 bite 2).

    Frozen so a normalized change can't be mutated after the fact, which also
    gives value-equality for free. ``action`` is the proposed operation
    (lower-cased + stripped -- only ``"deactivate"`` is tenure-gated, any other
    action is treated as non-deactivating), ``role`` is the target role id
    (stripped), and ``trigger`` is the logged-trigger citation (stripped). A
    missing key normalizes to the empty string (Behavior 3).
    """
    action: str
    role: str
    trigger: str

    def to_dict(self) -> dict:
        """A pure, JSON-safe ``{"action","role","trigger"}`` triple (fixed order).

        The leaf of the composite `RestaffingDiff.to_dict` serialization -- mirrors
        `ConfigFinding.to_dict`. Every value is the STORED string verbatim, so
        ``json.dumps`` never raises and the payload can never disagree with the
        human ``+ action role (trigger)`` render (Behavior 1)."""
        return {"action": self.action, "role": self.role, "trigger": self.trigger}


@dataclasses.dataclass(frozen=True)
class RestaffingRejection:
    """A proposed change rejected by a named hysteresis rule (item 22 bite 2).

    ``change`` is the normalized `RestaffingChange` that failed; ``rule`` is the
    FIRST rule it violated in the fixed order trigger -> tenure -> cap (Behavior
    8). Frozen for value-equality and immutability.
    """
    change: RestaffingChange
    rule: str

    def to_dict(self) -> dict:
        """A pure, JSON-safe ``{"change","rule"}`` pair (fixed order).

        ``change`` is the NESTED `RestaffingChange.to_dict()` (a plain ``dict``,
        never a dataclass instance -- so ``json.dumps`` cannot raise), matching
        the human ``- action role (rule)`` render; ``rule`` is the stored rule
        string (Behavior 2)."""
        return {"change": self.change.to_dict(), "rule": self.rule}


@dataclasses.dataclass(frozen=True)
class RestaffingDiff:
    """The partition of proposed changes into accepted + rejected (item 22 bite 2).

    Frozen so a computed diff can't be mutated and two `decide_restaffing` calls
    on equal arguments compare ``==`` (Behavior 1). ``accepted`` is the tuple of
    hysteresis-valid `RestaffingChange`s (in input order, at most ``cap`` of
    them); ``rejected`` is the tuple of `RestaffingRejection`s; ``k`` and ``cap``
    are the EFFECTIVE thresholds that were used (Behavior 11). The four
    properties are pure derivations, so the whole diff follows deterministically
    from the stored fields (the CLI adds no logic on top).
    """
    accepted: tuple[RestaffingChange, ...]
    rejected: tuple[RestaffingRejection, ...]
    k: int
    cap: int

    @property
    def accepted_count(self) -> int:
        """Number of accepted changes (Behavior 12)."""
        return len(self.accepted)

    @property
    def rejected_count(self) -> int:
        """Number of rejected changes (Behavior 12)."""
        return len(self.rejected)

    @property
    def has_diff(self) -> bool:
        """True iff at least one change was accepted (Behavior 12)."""
        return bool(self.accepted)

    @property
    def verdict(self) -> str:
        """Operator token: ``"DIFF"`` when >= 1 change accepted, else ``"NOOP"``."""
        return "DIFF" if self.has_diff else "NOOP"

    def to_dict(self) -> dict:
        """A pure, JSON-safe serialization of the whole diff.

        Returns EXACTLY these 8 keys in this fixed order: ``accepted`` (a LIST of
        ``{"action","role","trigger"}`` dicts in accepted order), ``rejected`` (a
        LIST of ``{"change",...,"rule"}`` dicts in rejection order), ``k``,
        ``cap``, ``accepted_count``, ``rejected_count``, ``has_diff``,
        ``verdict``. ``accepted`` / ``rejected`` are LISTS (not the frozen
        tuples) of NESTED dicts (not dataclass instances) -- mirrors
        `ConfigLint.to_dict` one level deeper -- so ``json.dumps(...)`` never
        raises and the dict round-trips through ``json.loads(json.dumps(...))``
        (Behaviors 4/6). There is NO ``exit_code`` key: the CLI derives its exit
        from ``has_diff`` (0/1) and the file-error 2 is a CLI-only concern (RD,
        like `EscalationClassification`, has no ``exit_code`` property). Every
        scalar REUSES a frozen field/property so the payload can never disagree
        with the render/exit (single source of truth). Pure: no filesystem."""
        return {
            "accepted": [c.to_dict() for c in self.accepted],
            "rejected": [r.to_dict() for r in self.rejected],
            "k": self.k,
            "cap": self.cap,
            "accepted_count": self.accepted_count,
            "rejected_count": self.rejected_count,
            "has_diff": self.has_diff,
            "verdict": self.verdict,
        }


def _normalize_restaffing_change(
    change: Mapping[str, object] | RestaffingChange,
) -> RestaffingChange:
    """Normalize a proposed change (a mapping or a `RestaffingChange`) to a change.

    Accepts either a mapping with keys ``action`` / ``role`` / ``trigger`` or an
    already-built `RestaffingChange` (idempotent). ``action`` is lower-cased +
    stripped; ``role`` and ``trigger`` are stripped; a missing key becomes the
    empty string (Behavior 3). Pure and total.
    """
    if isinstance(change, RestaffingChange):
        action, role, trigger = change.action, change.role, change.trigger
    else:
        action = change.get("action", "")
        role = change.get("role", "")
        trigger = change.get("trigger", "")
    return RestaffingChange(
        action=str(action).strip().lower(),
        role=str(role).strip(),
        trigger=str(trigger).strip(),
    )


def decide_restaffing(
    changes: Iterable[Mapping[str, object] | RestaffingChange],
    tenures: Mapping[str, int] | None = None,
    logged_triggers: Iterable[str] | None = None,
    *,
    k: int | None = None,
    cap: int | None = None,
) -> RestaffingDiff:
    """Partition proposed re-staffing changes into a hysteresis-valid diff (pure, total).

    ``changes`` is an iterable of proposed changes (mappings or
    `RestaffingChange`s); ``tenures`` maps role -> iterations served (a role
    absent from it, or ``tenures=None``, is treated as tenure 0 -- Behavior 6);
    ``logged_triggers`` is the set of trigger ids that have actually been logged
    (``None`` == none logged, so every change fails citation -- Behavior 4).
    Each change is evaluated in the FIXED order trigger -> tenure -> cap and the
    FIRST failing rule tags its rejection (Behavior 8): a change must cite a
    LOGGED trigger (else rule ``"trigger"``); a ``"deactivate"`` whose role
    tenure is ``< k`` is rejected (rule ``"tenure"``, an ``"activate"`` is never
    tenure-gated -- Behavior 5); and only OTHERWISE-VALID changes consume cap
    slots, so at most ``cap`` are accepted in input order (rule ``"cap"`` for the
    overflow -- Behavior 7). When ``k`` / ``cap`` are None the thresholds are
    read from the module-level ``RESTAFFING_MIN_TENURE_K`` /
    ``RESTAFFING_MAX_CHANGES`` AT CALL TIME (not captured as default args / at
    import) so patching them changes a subsequent call's result (Behaviors
    9/10); an explicit ``k`` / ``cap`` overrides for that call only (Behavior
    11). Performs NO filesystem/subprocess/network/clock access, never raises
    for well-formed or empty input, and is deterministic.
    """
    threshold_k = RESTAFFING_MIN_TENURE_K if k is None else k
    threshold_cap = RESTAFFING_MAX_CHANGES if cap is None else cap
    tenure_map = tenures or {}
    logged = set(logged_triggers or ())

    accepted: list[RestaffingChange] = []
    rejected: list[RestaffingRejection] = []
    for raw in changes:
        change = _normalize_restaffing_change(raw)
        # Rule 1 (trigger): every change must cite a LOGGED trigger.
        if not change.trigger or change.trigger not in logged:
            rejected.append(RestaffingRejection(change=change, rule="trigger"))
            continue
        # Rule 2 (tenure): a deactivate needs minimum tenure K; activate exempt.
        if change.action == "deactivate":
            tenure = tenure_map.get(change.role, 0)
            if tenure < threshold_k:
                rejected.append(
                    RestaffingRejection(change=change, rule="tenure")
                )
                continue
        # Rule 3 (cap): only otherwise-valid changes consume a slot.
        if len(accepted) >= threshold_cap:
            rejected.append(RestaffingRejection(change=change, rule="cap"))
            continue
        accepted.append(change)
    return RestaffingDiff(
        accepted=tuple(accepted),
        rejected=tuple(rejected),
        k=threshold_k,
        cap=threshold_cap,
    )


def restaffing_review_cli(path: str, as_json: bool = False) -> int:
    """On-demand CLI: report the hysteresis re-staffing diff for a JSON review.

    Reads the JSON review object at ``path`` (keys ``changes`` [list, default
    []], ``tenures`` [object role->int, default {}], ``logged_triggers`` [list,
    default []], and optional ``k`` / ``cap`` integer overrides used when
    present, else the module defaults), computes `decide_restaffing`, prints the
    effective k / cap / accepted / rejected figures, one line per accepted
    change (with a ``+`` marker) and per rejected change (with its failing rule),
    and a final ``verdict:`` line, and returns ``1`` (DIFF -- a diff to apply) /
    ``0`` (NOOP) -- non-zero = action needed, mirroring `cadence-review` REVIEW /
    `escalation-check` ESCALATE. Writes NOTHING to disk. A THIN wrapper over the
    pure core: it adds no decision logic beyond read -> `decide_restaffing` ->
    format. With ``as_json=True`` it prints one ``json.dumps(result.to_dict(),
    indent=2)`` document (machine-readable) instead of the human report; the
    ``0``/``1``/``2`` exit contract and the three error branches are
    byte-identical in both modes. A missing file, invalid JSON, or a non-object
    review prints a message naming the problem and returns ``2`` (distinct from a
    verdict code) WITHOUT letting an exception propagate.
    """
    p = pathlib.Path(path)
    if not p.exists():
        print(f"restaffing-review: file not found: {path}")
        return 2
    try:
        review = json.loads(p.read_text())
    except (ValueError, OSError) as exc:
        print(f"restaffing-review: invalid JSON in {path}: {exc}")
        return 2
    if not isinstance(review, dict):
        print(f"restaffing-review: review in {path} is not a JSON object")
        return 2
    result = decide_restaffing(
        review.get("changes", []),
        tenures=review.get("tenures", {}),
        logged_triggers=review.get("logged_triggers", []),
        k=review.get("k"),
        cap=review.get("cap"),
    )
    if as_json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(f"restaffing-review: {path}")
        print(f"  k={result.k} cap={result.cap} "
              f"accepted={result.accepted_count} rejected={result.rejected_count}")
        for change in result.accepted:
            print(f"  + {change.action} {change.role} (trigger: {change.trigger})")
        for rejection in result.rejected:
            c = rejection.change
            print(f"  - {c.action} {c.role} (rule: {rejection.rule})")
        print(f"verdict: {result.verdict}")
    return 1 if result.has_diff else 0


# --------------------------------------------------------------------------- #
# Dual-PM-scout phase planner: the ordered scout pre-stage plan (DORMANT --
# dual-PM-scout feature bite 1, docs/DUAL_PM_SCOUT_SPEC.md). The spec wants an
# OPTIONAL two-scout pre-stage: when a config flag is on, an iteration runs
# pm_scout_a (new-capability lens) then pm_scout_b (hardening/DX lens)
# sequentially BEFORE the PM lead, which then triages both slates -- so every
# product team gets more diverse candidate features than a single PM produces.
# That payload is control-flow WIRING into run_iteration (a pre-stage sequence +
# PM-lead triage), the operator-gated later bite; this bite ships only the
# deterministic PLANNER the wiring will consult to know WHICH scout stages to
# run, in what ORDER, with which LENS. Same purely-additive, off-control-path,
# on-demand-CLI class as gate-precheck (item 20 bite 1) / gate-verdict (bite 2)
# / role-model (bite 3) / product-gate (bite 4a) / escalation-check (item 21
# bite 1) / cadence-review (item 22 bite 1) / restaffing-review (item 22 bite
# 2): the pipeline NEVER calls it, so build_prompt/run_stage/run_iteration/
# run_continuous/run_execution_plan/dispatcher.py are untouched, NO sentinel/
# config field/artifact is added, and the CLI writes NOTHING. The lens set is a
# module-level + patchable constant read at CALL time (not captured at import /
# as a default arg) so it stays tunable per box -- see Behavior 8.
# --------------------------------------------------------------------------- #
PM_SCOUT_LENSES: tuple[str, ...] = ("new-capability", "hardening/DX")


@dataclasses.dataclass(frozen=True)
class ScoutPhasePlan:
    """The ordered scout pre-stage plan for one iteration (dual-PM-scout bite 1).

    Frozen so a computed plan can't be mutated after the fact, which also gives
    value-equality for free: two `decide_scout_phase` calls on equal arguments
    hold equal fields, so they compare ``==`` (Behavior 12). ``enabled`` is
    whether the dual-scout pre-phase runs at all; ``stages`` is the ordered
    tuple of ``(stage_name, lens)`` pairs the iteration would run before the PM
    lead (empty when disabled). The three properties are pure derivations, so
    the whole plan follows deterministically from the two fields (the CLI adds
    no logic on top).
    """
    enabled: bool
    stages: tuple[tuple[str, str], ...]

    @property
    def count(self) -> int:
        """Number of scout stages in the plan (Behaviors 1/2/6)."""
        return len(self.stages)

    @property
    def stage_names(self) -> tuple[str, ...]:
        """The scout stage names in order (Behaviors 2/4)."""
        return tuple(name for name, _lens in self.stages)

    @property
    def verdict(self) -> str:
        """Operator token: ``"DUAL"`` when the pre-phase is enabled, else ``"SINGLE"``."""
        return "DUAL" if self.enabled else "SINGLE"

    def to_dict(self) -> dict:
        """A pure, JSON-safe scout-phase plan for machine consumers -- an
        operator, a CI job, or a dashboard consuming the dual-PM-scout phase
        verdict (dual-PM-scout bite 1), the org-design analog of
        `CadenceReviewDecision.to_dict()` and the other read-only `--json`
        probes.

        Returns EXACTLY 5 keys: the stored `enabled` bool verbatim, then the
        derived `stages` / `count` / `stage_names` / `verdict`, each REUSING the
        frozen field/properties so the JSON can never disagree with what the CLI
        renders or the exit code returns. `stages` serializes each
        `(name, lens)` pair as a self-describing `{"stage": name, "lens": lens}`
        dict (NOT a bare `list(self.stages)`, whose inner tuples json.loads would
        read back as lists and break the round-trip); `stage_names` is
        `list(self.stage_names)` (the tuple property coerced to a JSON-native
        list, like the `escalation-check` categories). Pure: touches no
        filesystem, does not mutate the frozen plan, and returns a fresh dict
        (with fresh nested stage dicts) each call. NO `exit_code` key: the CLI
        exit derives from `enabled` (0/1) and `scout-plan` takes no file, so
        there is no file-not-found (2) path to serialize -- contrast
        `escalation-check`.
        """
        return {
            "enabled": self.enabled,
            "stages": [{"stage": name, "lens": lens} for name, lens in self.stages],
            "count": self.count,
            "stage_names": list(self.stage_names),
            "verdict": self.verdict,
        }


def decide_scout_phase(
    dual_pm_scouts: object, lenses: Iterable[str] | None = None
) -> ScoutPhasePlan:
    """Compute the ordered scout pre-stage plan for an iteration (pure, total).

    ``dual_pm_scouts`` is the dual-scout flag (coerced with ``bool(...)`` --
    Behavior 3); ``lenses`` is an optional explicit lens override. When the flag
    is falsy the plan is disabled with no stages (Behaviors 1/3). When enabled,
    stage names are assigned BY POSITION ``pm_scout_a``, ``pm_scout_b``,
    ``pm_scout_c``, ... paired with each lens in input order (Behavior 4). When
    ``lenses`` is None the lens set is read from the module-level
    ``PM_SCOUT_LENSES`` AT CALL TIME (not captured as a default arg / at import)
    so patching it changes a subsequent call's result (Behavior 8); an explicit
    ``lenses`` (any iterable, including a one-shot generator) overrides it for
    that call only (Behaviors 7/9/10). Performs NO filesystem/subprocess/network/
    clock access, never raises for any bool-ish flag or None/iterable ``lenses``
    (an empty lens set yields an enabled-but-empty plan -- Behavior 6), and is
    deterministic. Position suffixes past ``z`` are unsupported (Out of Scope),
    still total.
    """
    enabled = bool(dual_pm_scouts)
    if not enabled:
        return ScoutPhasePlan(enabled=False, stages=())
    active = PM_SCOUT_LENSES if lenses is None else tuple(lenses)
    stages = tuple(
        (f"pm_scout_{chr(ord('a') + i)}", lens) for i, lens in enumerate(active)
    )
    return ScoutPhasePlan(enabled=True, stages=stages)


def scout_plan_cli(dual_pm_scouts: bool, lenses: list[str] | None, as_json: bool = False) -> int:
    """On-demand CLI: report the ordered dual-PM-scout pre-stage plan.

    Computes `decide_scout_phase`, prints the ``dual_pm_scouts`` flag + a
    ``count`` figure, one line per scout stage naming BOTH the stage name and
    its lens, and a final ``verdict:`` line, and returns ``1`` (DUAL -- the
    dual-scout pre-phase is active) / ``0`` (SINGLE) -- non-zero = the pre-phase
    runs, mirroring `cadence-review` REVIEW / `restaffing-review` DIFF. Writes
    NOTHING to disk. A THIN wrapper over the pure core: it adds no logic beyond
    decide -> format, so the printed figures always match the `ScoutPhasePlan`.
    Takes no file, so there is no file-not-found path. With ``as_json=True`` it
    prints one ``json.dumps(result.to_dict(), indent=2)`` document
    (machine-readable) instead of the human report; the ``0``/``1`` exit
    contract is byte-identical in both modes.
    """
    result = decide_scout_phase(dual_pm_scouts, lenses)
    if as_json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(f"scout-plan: dual_pm_scouts={result.enabled} count={result.count}")
        for name, lens in result.stages:
            print(f"  {name} (lens: {lens})")
        print(f"verdict: {result.verdict}")
    return 1 if result.enabled else 0


@dataclasses.dataclass(frozen=True)
class ScoutStageSpec:
    """One scout's concrete run_stage descriptor (dual-PM-scout bite 3a).

    Bridges the iter-80 abstract ``ScoutPhasePlan`` (ordered ``(stage_name,
    lens)`` pairs) to the concrete per-scout arguments the operator-gated
    bite-3b wiring will loop over. Frozen for the same reason as
    ``ScoutPhasePlan``: a derived descriptor must not be mutated after the fact,
    and value-equality comes free (Behavior 11). ``stage`` is the scout's stage
    name; ``out_name`` is the exact output file that scout must write, tying its
    output-file-success contract to a named file (``stage + ".md"`` -- Behavior
    3); ``lens`` is the assigned candidate-generation lens, carried verbatim
    (Behavior 8). The shared scout role card is INVARIANT across scouts, so it is
    NOT per-descriptor data: it lives at the bite-3b ``run_stage`` call site, not
    here (keeping this bite off iter-81's role-file dormancy -- Behavior 15).
    """
    stage: str
    out_name: str
    lens: str


def derive_scout_stage_specs(plan: ScoutPhasePlan) -> tuple[ScoutStageSpec, ...]:
    """Map an abstract scout plan to its concrete per-scout run_stage descriptors.

    The direct analog of iter-69's ``derive_execution_plan`` (abstract plan ->
    concrete execution descriptor): given the iter-80 ``ScoutPhasePlan`` it
    returns one ``ScoutStageSpec`` per ordered ``(stage_name, lens)`` pair,
    pinning each scout's output-file-success contract to ``stage_name + ".md"``.
    Order is preserved from ``plan.stages`` (Behavior 4); a disabled or
    enabled-but-empty plan yields an empty tuple (Behaviors 1/7). Pure, total,
    deterministic, offline: performs NO filesystem/subprocess/network/clock
    access and never raises for any ``ScoutPhasePlan`` input (Behavior 12).
    ZERO call site -- the operator-gated bite-3b wiring loops over the result;
    nothing in the running loop constructs or calls it, so the disabled path is
    byte-identical (Behavior 14).
    """
    return tuple(
        ScoutStageSpec(stage=name, out_name=f"{name}.md", lens=lens)
        for name, lens in plan.stages
    )


@dataclasses.dataclass(frozen=True)
class ScoutPhaseResult:
    """Outcome of running the dual-PM-scout pre-phase (dual-PM-scout bite 3b-i).

    Frozen so a computed result can't be mutated after the fact, which also gives
    value-equality for free (Behavior 11), mirroring ``ScoutPhasePlan`` /
    ``ScoutStageSpec``. ``ok`` is whether every scout produced its output file;
    ``outputs`` is the ordered tuple of the ``out_name``s that DID succeed (so the
    PM lead can read exactly the scout files that exist -- on a mid-phase failure
    it retains the earlier successes, never the failed/unrun scouts); ``failed_stage``
    is the stage name of the first scout that failed, or None on full success
    (including the vacuous disabled-plan success). The scout phase runs BEFORE
    anything is built, so a failure never reverts the repo -- mirroring
    ``run_iteration``'s PM stage, which returns an infra-fail with no revert.
    """
    ok: bool
    outputs: tuple[str, ...]
    failed_stage: str | None = None


def run_scout_phase(cfg: ProductConfig, iteration: int, plan: ScoutPhasePlan,
                    role_file: str) -> ScoutPhaseResult:
    """Run the ordered dual-PM-scout pre-phase for one iteration (DORMANT executor).

    The direct analog of iter-70's ``run_execution_plan``: a dormant full executor
    built as a pure-seam, offline-testable function now, so the operator-gated
    wiring (bite 3b-ii) collapses to a trivial ``if plan.enabled: run_scout_phase(
    ...)`` call. Given the iter-80 ``ScoutPhasePlan`` it derives the iter-82 per-
    scout ``ScoutStageSpec``s (via ``derive_scout_stage_specs``) and runs each scout
    stage SEQUENTIALLY through the ``run_stage`` seam -- concurrency 1 preserved,
    single-brain (Behavior 3) -- keying each on its ``spec.out_name`` (ties output-
    file success to a named file -- Behavior 4) and carrying that scout's assigned
    ``spec.lens`` verbatim in the prompt (Behavior 6). Returns a ``ScoutPhaseResult``
    naming the scouts that produced output (Behavior 2).

    ``role_file`` is a PARAMETER, never hardcoded, so the literal card name never
    enters foundry.py and iters 81/82's role-file count-0 dormancy tests stay green
    (the wiring bite passes the concrete card at the call site -- mirrors iter-70
    deferring ``base`` to the wiring). A disabled or empty plan derives no specs, so
    the loop runs zero times and the phase is a vacuous success (Behavior 1). On the
    FIRST scout failure the phase short-circuits and returns immediately, retaining
    any earlier successes in ``outputs`` (Behaviors 7/8); it NEVER reverts the repo
    on any path -- scouts run before anything is built, mirroring ``run_iteration``'s
    no-revert PM stage (Behavior 9). Performs no direct I/O of its own -- every
    external effect goes through the ``run_stage`` seam (Behavior 12); ``run_stage``
    and ``derive_scout_stage_specs`` are called by BARE module name so a test's
    ``monkeypatch.setattr`` bites and the module globals are read at call time
    (Behavior 13). ZERO call site -- no orchestrator runs it yet, so the disabled
    path is byte-identical (Behavior 14).
    """
    specs = derive_scout_stage_specs(plan)
    outputs: list[str] = []
    for spec in specs:
        extra = (
            f"You are a PM scout for the '{spec.lens}' lens. Propose 2-3 candidate "
            f"features in the '{spec.lens}' lens and decide nothing."
        )
        ok, _ = run_stage(cfg, iteration, spec.stage, role_file, spec.out_name,
                          extra)
        if not ok:
            return ScoutPhaseResult(ok=False, outputs=tuple(outputs),
                                    failed_stage=spec.stage)
        outputs.append(spec.out_name)
    return ScoutPhaseResult(ok=True, outputs=tuple(outputs), failed_stage=None)


def scout_phase_outcome(cfg: ProductConfig, iteration: int,
                        role_file: str) -> dict | None:
    """Compose the config gate + scout phase into run_iteration's status idiom.

    The last untested piece of dual-PM-scout WIRING logic, extracted as a dormant
    offline-testable helper so bite 3b-ii's operator-gated wiring collapses to a
    trivial pre-tested call at the run_iteration front: run the scout pre-phase,
    and if it hands back a status dict, return that dict; otherwise fall through to
    the PM lead. Reads the ``cfg.dual_pm_scouts`` flag (coerced by
    ``decide_scout_phase``'s own ``bool(...)``), builds the plan, runs the iter-83
    executor ``run_scout_phase``, and maps its outcome onto ``run_iteration``'s
    idiom.

    Return contract: ``None`` means "proceed to the PM lead" and is returned in
    exactly two cases -- the feature is DISABLED (``cfg.dual_pm_scouts`` falsy, so
    no scout machinery runs at all), OR every scout succeeded. A status ``dict`` is
    returned ONLY when a scout stage failed, with EXACTLY ``run_iteration``'s
    PM-stage infra-fail shape ``{"status": "infra-fail", "stage": <failed scout>,
    "iteration": iteration}``. The disabled and full-success None cases are
    distinguishable by the ``run_stage`` call count (0 vs >=1), which the tests pin.

    ``role_file`` is a PARAMETER, never hardcoded, so the literal card name stays
    out of foundry.py and iters 81/82/83's role-file count-0 dormancy tests stay
    green -- the wiring bite supplies the concrete scout role card at the call site
    (mirrors iter-70 deferring ``base``). NEVER reverts the repo on any path: scouts
    run before anything is built, exactly like ``run_iteration``'s no-revert PM
    stage, and ``run_scout_phase`` never reverts either. Performs no direct I/O of
    its own -- every external effect flows through ``run_scout_phase`` ->
    ``run_stage``; ``decide_scout_phase`` and ``run_scout_phase`` are called by BARE
    module name so a test's ``monkeypatch.setattr`` bites at call time. ZERO call
    site -- no orchestrator runs it yet, so the running loop's disabled path is
    byte-identical and resume semantics are preserved (bite 3b-ii wires it,
    operator-gated).
    """
    if not cfg.dual_pm_scouts:
        return None
    plan = decide_scout_phase(cfg.dual_pm_scouts)
    result = run_scout_phase(cfg, iteration, plan, role_file)
    if not result.ok:
        return {"status": "infra-fail", "stage": result.failed_stage,
                "iteration": iteration}
    return None


# --------------------------------------------------------------------------- #
# Assertion-free test detector (DORMANT — roadmap item 6, offline slice).
#
# Item 6's own failure mode: a fresh Tester agent writes a `test*` function that
# CANNOT fail (no assertion) -> a false green. The full remedy (mutation testing
# via `mutmut`) stays blocked -- it needs a network install and is not
# offline-deterministic (VISION bar). This is the offline, deterministic slice
# that lands today: a pure `ast` scan that flags every `test*` function whose
# body carries NO assertion signal. That is not a heuristic -- an assertion-free
# test validates nothing yet reports green, so the check is precise + low-false-
# positive. Same purely-additive, off-control-path, on-demand-CLI class as
# doctor/lint-spec/prd/gate-scope: the pipeline NEVER calls it, so
# build_prompt/run_stage/run_iteration/run_continuous/dispatcher.py are
# untouched, NO sentinel/config field/artifact is added, and the CLI writes
# NOTHING. The two constants are module-level + patchable so the globs and the
# context-manager assertion names stay tunable per box AND are read at CALL time
# (not captured at import) -- see Behaviors 8/10.
# --------------------------------------------------------------------------- #
WEAK_TEST_GLOBS: tuple[str, ...] = ("test_*.py", "*_test.py")
WEAK_TEST_ASSERTION_CALLS: frozenset[str] = frozenset({"raises", "warns", "fail"})
# Trailing decorator names that ALWAYS skip a test regardless of args or dotted
# path (`@skip`, `@pytest.mark.skip`, `@unittest.skip`). Module-level + patchable
# + read at CALL time (not captured at import) so a monkeypatch bites -- mirror
# `WEAK_TEST_ASSERTION_CALLS`. `skipif`/`skipIf`/`skipUnless` are NOT decided by
# membership here; their constant condition is judged in `_is_always_skip_decorator`.
WEAK_TEST_SKIP_NAMES: frozenset[str] = frozenset({"skip"})


def _callee_trailing_name(func_node: ast.expr) -> str | None:
    """The trailing name of a call's callee, or None (pure, total).

    `a.b.c(...)` -> ``"c"`` (the `ast.Attribute.attr`); `f(...)` -> ``"f"`` (the
    `ast.Name.id`). Any other callee shape (`obj[k]()`, `f()()`, a lambda) has no
    stable name, so returns None -- such a call is never an assertion signal by
    name. Never raises for any expression node.
    """
    if isinstance(func_node, ast.Name):
        return func_node.id
    if isinstance(func_node, ast.Attribute):
        return func_node.attr
    return None


def _has_assertion_signal(func: ast.AST) -> bool:
    """True iff `func`'s own AST subtree carries ANY assertion signal.

    A signal is: (a) an `assert` statement, (b) a `raise` statement, (c) a call
    whose callee trailing-name starts with the literal ``"assert"`` (covers
    `self.assertEqual`, `assertTrue`, ...), or (d) a call whose callee
    trailing-name is a member of `WEAK_TEST_ASSERTION_CALLS` (covers the pytest
    `with pytest.raises(...)` / `warns` / `fail` context managers). Reads
    `WEAK_TEST_ASSERTION_CALLS` at CALL time so a monkeypatch of the module
    constant re-decides subsequent calls (Behavior 10). `ast.walk` includes
    `func` itself, so signals inside a nested body still count -- matching the
    contract's "ANY node in that function's own AST subtree". Pure: no I/O.
    """
    calls = WEAK_TEST_ASSERTION_CALLS
    for node in ast.walk(func):
        if isinstance(node, (ast.Assert, ast.Raise)):
            return True
        if isinstance(node, ast.Call):
            name = _callee_trailing_name(node.func)
            if name is not None and (name.startswith("assert") or name in calls):
                return True
    return False


def find_assertionless_tests(source: str) -> tuple[str, ...]:
    """Names of every `test*` function in `source` with no assertion signal.

    Pure AST scan -- no filesystem/subprocess/network/clock, so fully
    offline-testable. Considers EVERY `def`/`async def` (top-level OR a class
    method) whose name starts with the literal ``"test"`` (Behaviors 3/6/8), and
    flags those whose subtree has NO assertion signal per `_has_assertion_signal`
    (Behaviors 1/2/4/5). Results are returned in ASCENDING SOURCE ORDER by line
    number, NOT alphabetically (Behavior 7). Raises `SyntaxError` verbatim when
    `source` is not valid Python (Behavior 9) -- the caller decides how to
    degrade (the CLI turns it into a graceful parse-error entry).
    """
    tree = ast.parse(source)
    funcs = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test")
    ]
    flagged = [f for f in funcs if not _has_assertion_signal(f)]
    flagged.sort(key=lambda f: f.lineno)
    return tuple(f.name for f in flagged)


def _assert_signals(func: ast.AST) -> tuple[bool, bool]:
    """`(has_constant_assert, has_real_signal)` over `func`'s own AST subtree.

    A "constant assert" is an `ast.Assert` whose `.test` is a plain
    `ast.Constant` (`assert True`, `assert 1`, `assert "x"`, `assert None`): it
    reports green yet validates nothing, so it slips past
    `find_assertionless_tests` (which sees the `assert` node itself as a signal).
    A "real signal" is any genuine check: an `ast.Assert` whose `.test` is NOT a
    plain `ast.Constant` (`assert x`, `assert x == 1`, `assert func()`, and --
    conservatively -- `assert not True`, a `UnaryOp`), an `ast.Raise`, a call
    whose callee trailing-name starts with the literal ``"assert"``
    (`self.assertEqual`, `assertTrue`), or a call whose trailing-name is a member
    of `WEAK_TEST_ASSERTION_CALLS` (the pytest `raises`/`warns`/`fail` context
    managers). Only the assert's `.test` is inspected, never its `.msg`, so
    `assert True, "boom"` is still purely constant. Reads
    `WEAK_TEST_ASSERTION_CALLS` at CALL time so a monkeypatch of the module
    constant re-decides subsequent calls (Behavior 6). `ast.walk` includes `func`
    itself, so signals inside a nested body still count -- mirroring
    `_has_assertion_signal`. Pure: no I/O.
    """
    calls = WEAK_TEST_ASSERTION_CALLS
    has_constant_assert = False
    has_real_signal = False
    for node in ast.walk(func):
        if isinstance(node, ast.Assert):
            if isinstance(node.test, ast.Constant):
                has_constant_assert = True
            else:
                has_real_signal = True
        elif isinstance(node, ast.Raise):
            has_real_signal = True
        elif isinstance(node, ast.Call):
            name = _callee_trailing_name(node.func)
            if name is not None and (name.startswith("assert") or name in calls):
                has_real_signal = True
    return has_constant_assert, has_real_signal


def find_constant_assert_tests(source: str) -> tuple[str, ...]:
    """Names of `test*` functions whose ONLY validation is a constant assert.

    Pure AST scan -- no filesystem/subprocess/network/clock, so fully
    offline-testable. Complements the shipped `find_assertionless_tests`: that
    detector flags tests with NO assertion signal at all, while this one flags
    the classic LLM-emitted weak test that DOES carry an `assert` node yet checks
    nothing -- a bare-literal `assert True`/`assert 1`/`assert "x"` (Behavior 1).
    A `test*` function is flagged iff its subtree has >=1 constant `assert` AND no
    real assertion signal per `_assert_signals` (Behaviors 1/2). By construction
    the two detectors are DISJOINT -- an assertion-free test has no constant
    assert (so only `find_assertionless_tests` sees it), and a test carrying a
    real check has a real signal (so neither flags a constant assert it also
    holds), so a given `test*` name lands in at most one (Behavior 3). Considers
    EVERY `def`/`async def` (top-level OR a class method) whose name starts with
    the literal ``"test"`` (Behavior 4); results in ASCENDING SOURCE ORDER by line
    number, NOT alphabetically (Behavior 5). Raises `SyntaxError` verbatim when
    `source` is not valid Python (Behavior 7) -- the caller decides how to degrade.
    Never referenced on any run path this iteration (dormant, Behavior 8).
    """
    tree = ast.parse(source)
    funcs = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test")
    ]
    flagged = []
    for f in funcs:
        has_constant_assert, has_real_signal = _assert_signals(f)
        if has_constant_assert and not has_real_signal:
            flagged.append(f)
    flagged.sort(key=lambda f: f.lineno)
    return tuple(f.name for f in flagged)


def _is_always_skip_decorator(decorator: ast.expr) -> bool:
    """True iff `decorator` UNCONDITIONALLY skips the test it decorates.

    Handles a decorator in any of its three shapes -- a bare name (`@skip`), a
    dotted attribute (`@pytest.mark.skip`, `@unittest.skip`), or a call of either
    (`@pytest.mark.skip(reason=...)`, `@unittest.skipIf(True, ...)`) -- resolving
    the callee's trailing name via `_callee_trailing_name` (Behavior 1). A
    trailing name in `WEAK_TEST_SKIP_NAMES` (default `{"skip"}`) ALWAYS skips,
    regardless of args or dotted path. A `skipif`/`skipIf` skips ONLY when its
    first positional arg is a constant-TRUTHY `ast.Constant` (Behavior 2); a
    `skipUnless` skips ONLY when its first positional arg is a constant-FALSY
    `ast.Constant` (Behavior 3). A non-constant condition (`sys.platform == ...`,
    `HAVE_LIB`) -- or no positional arg at all -- is UNKNOWN, so conservatively
    NOT a skip, so a legitimate runtime platform/capability guard is never a
    false positive. Reads `WEAK_TEST_SKIP_NAMES` at CALL time (not captured at
    def-time) so a monkeypatch of the module constant re-decides subsequent calls
    (Behavior 8). Pure: no I/O, and never raises for any decorator expression node.
    """
    if isinstance(decorator, ast.Call):
        name = _callee_trailing_name(decorator.func)
        args = decorator.args
    else:
        name = _callee_trailing_name(decorator)
        args = []
    if name is None:
        return False
    # A bare/dotted/called `skip` (any member of the patchable set) always skips.
    if name in WEAK_TEST_SKIP_NAMES:
        return True
    # A conditional skip is statically decidable ONLY when its first positional
    # arg is a literal `ast.Constant`; a runtime value (name/compare/call) is
    # UNKNOWN, so it is conservatively NOT flagged.
    first = args[0] if args else None
    if not isinstance(first, ast.Constant):
        return False
    truthy = bool(first.value)
    if name in ("skipif", "skipIf"):
        return truthy
    if name == "skipUnless":
        return not truthy
    return False


def find_always_skipped_tests(source: str) -> tuple[str, ...]:
    """Names of every `test*` function unconditionally skipped by a decorator.

    Pure AST scan -- no filesystem/subprocess/network/clock, so fully
    offline-testable. The 3rd member of the item-6 weak-test detector family
    (after `find_assertionless_tests` and `find_constant_assert_tests`): a test
    carrying an UNCONDITIONAL skip decorator (`@pytest.mark.skip`,
    `@unittest.skip`, a constant-condition `skipif(True)` / `skipUnless(False)`)
    never runs, validates nothing, yet reports the suite green -- the degenerate
    "no assertion runs at all" case, and a real way a fresh Tester/Engineer fakes
    a green suite that the item-11 fresh-clone re-run does not catch (a skipped
    test passes there too). A `test*` function is flagged iff ANY of its
    decorators is an always-skip per `_is_always_skip_decorator` (Behaviors
    1/2/3/4), so a test with multiple decorators including one skip is flagged
    exactly ONCE (Behavior 6). Considers EVERY `def`/`async def` (top-level OR a
    class method) whose name starts with the literal ``"test"`` (Behavior 5);
    results in ASCENDING SOURCE ORDER by line number, NOT alphabetically
    (Behavior 6). Runtime `pytest.skip()` / `self.skipTest()` body CALLS are OUT
    of scope -- a body-level call may be guarded by an `if`, so it is not
    statically "always-skip". Raises `SyntaxError` verbatim when `source` is not
    valid Python (Behavior 7) -- the caller decides how to degrade. Never
    referenced on any run path this iteration (dormant, Behavior 8).
    """
    tree = ast.parse(source)
    funcs = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test")
    ]
    flagged = [
        f for f in funcs
        if any(_is_always_skip_decorator(d) for d in f.decorator_list)
    ]
    flagged.sort(key=lambda f: f.lineno)
    return tuple(f.name for f in flagged)




@dataclasses.dataclass(frozen=True)
class WeakTestSummary:
    """The result of one weak-test scan over a product's test files (item 6).

    Frozen so a computed summary can't be mutated after the fact (value equality
    for free, matching the other pure cores). `findings` is a tuple of
    ``(file_path, test_name)`` pairs (one per assertion-free test) and
    `parse_errors` a tuple of ``(file_path, message)`` pairs (files that would
    not parse / read) -- both hashable + order-stable. The three properties are
    pure derivations of the stored fields, so the scriptable exit code follows
    deterministically from what was gathered.
    """
    product: str
    files_scanned: int
    findings: tuple[tuple[str, str], ...]
    parse_errors: tuple[tuple[str, str], ...]

    @property
    def total_findings(self) -> int:
        """How many assertion-free `test*` functions were flagged."""
        return len(self.findings)

    @property
    def clean(self) -> bool:
        """True iff >=1 file was scanned AND nothing was flagged or unparseable.

        Scanning zero files is NOT clean (there was nothing to certify), so the
        operator can distinguish "verified clean" from "found nothing to look
        at" -- see Behavior 16."""
        return (self.files_scanned > 0 and not self.findings
                and not self.parse_errors)

    @property
    def exit_code(self) -> int:
        """Scriptable verdict: ``2`` when nothing was scanned, else ``1`` when
        anything was flagged OR failed to parse, else ``0`` (clean). Nothing-to-
        scan is checked FIRST so an empty run is `2`, never a false `0`."""
        if self.files_scanned == 0:
            return 2
        if self.findings or self.parse_errors:
            return 1
        return 0

    @property
    def verdict(self) -> str:
        """The single human token for the current `exit_code` -- ONE source of
        truth for `render()`'s last line so text + exit code never drift."""
        return {0: "clean", 1: "WEAK TESTS FOUND",
                2: "nothing to scan"}[self.exit_code]

    def render(self) -> str:
        """A deterministic multi-line report carrying every gathered signal.

        Contains, as substrings (the CLI's black-box contract): the product
        name; ``files scanned: N``; ``assertion-free tests: N``; one
        ``  <file> :: <test_name>`` line per finding (so a dirty report names
        BOTH the file path and the test -- Behavior 11); ``parse errors: N``
        with one ``  <file>: <message>`` line each (Behavior 15); and a final
        ``verdict:`` token matching `exit_code`. When clean, no test-function
        name is printed (Behavior 12)."""
        lines = [
            f"foundry weak-tests -- {self.product}",
            f"  files scanned: {self.files_scanned}",
            f"  assertion-free tests: {self.total_findings}",
        ]
        for path, name in self.findings:
            lines.append(f"  {path} :: {name}")
        lines.append(f"  parse errors: {len(self.parse_errors)}")
        for path, message in self.parse_errors:
            lines.append(f"  {path}: {message}")
        lines.append(f"verdict: {self.verdict}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """A pure, JSON-safe serialization of the whole weak-test scan for
        machine consumers (roadmap item 10's "machine-readable status for
        dashboards / the reporter"), mirroring iter-19's `StatusSummary.
        to_dict()` and iter-20's `HistorySummary.to_dict()`.

        Returns EXACTLY 8 keys in a fixed order: `product`/`files_scanned` as
        the stored fields verbatim, then the four DERIVED values each REUSING
        the frozen properties -- `total_findings`/`clean`/`exit_code`/`verdict`
        -- so the payload can never disagree with what `render()` prints or the
        exit code returns (`to_dict` re-derives nothing), then `findings` as a
        JSON array of ``{"file","test"}`` objects in the SAME order as
        `self.findings` and `parse_errors` as a JSON array of
        ``{"file","message"}`` objects in the SAME order as `self.parse_errors`.
        Every value is JSON-native (str / int / bool / list of str-only dicts),
        so `json.dumps(...)` never raises and the dict round-trips through
        `json.loads(json.dumps(...))` -- including when both lists are empty.
        Pure: touches no filesystem, only the already-gathered snapshot."""
        return {
            "product": self.product,
            "files_scanned": self.files_scanned,
            "total_findings": self.total_findings,
            "clean": self.clean,
            "exit_code": self.exit_code,
            "verdict": self.verdict,
            "findings": [{"file": path, "test": name}
                         for path, name in self.findings],
            "parse_errors": [{"file": path, "message": message}
                             for path, message in self.parse_errors],
        }


def summarize_weak_tests(*, product: str, files_scanned: int,
                         findings: tuple[tuple[str, str], ...],
                         parse_errors: tuple[tuple[str, str], ...]
                         ) -> WeakTestSummary:
    """Pure keyword-only constructor for a `WeakTestSummary` (Behavior 16).

    A thin, total wrapper that packs the gathered signals into the frozen
    summary -- keyword-only so a caller can never transpose the fields by
    position, and it never raises. Kept separate from `weak_tests_cli` so the
    decision core stays a pure function the tester can drive without any
    filesystem."""
    return WeakTestSummary(
        product=product, files_scanned=files_scanned,
        findings=tuple(findings), parse_errors=tuple(parse_errors))


def _gather_weak_test_files(repo: str) -> list[pathlib.Path]:
    """Test files under `repo` matching `WEAK_TEST_GLOBS`, sorted + deduped.

    Recursively globs each pattern (read at CALL time), skips any path with a
    hidden or `.git` directory component, keeps only regular files, dedupes (a
    file could match two globs), and returns a deterministic sorted list. Pure
    filesystem read -- creates/modifies nothing.
    """
    root = pathlib.Path(repo)
    seen: set[pathlib.Path] = set()
    for pattern in WEAK_TEST_GLOBS:
        for path in root.rglob(pattern):
            if not path.is_file():
                continue
            rel_parts = path.relative_to(root).parts
            if any(part == ".git" or part.startswith(".") for part in rel_parts):
                continue
            seen.add(path)
    return sorted(seen)


def gather_weak_tests(cfg: ProductConfig, files=None) -> WeakTestSummary:
    """Gather one product's assertion-free-test scan into a `WeakTestSummary`
    (item 6's offline slice -- a false-green test is the foundry's #1
    verification failure mode).

    Extracted output-preservingly from the iter-22 `weak_tests_cli` gathering so
    BOTH the single-product `foundry weak-tests` and the coming company-wide
    roll-up (bite 2's `company_weak_tests_cli`) share ONE gathering seam; a
    monkeypatch on this one function then reshapes every consumer at once.
    Output-preserving: the summary it builds is byte-identical to what iter 22
    built, so `foundry weak-tests` is unchanged (mirroring iter-39's
    `gather_timing` extraction from `timing_cli`, iter-30's `gather_status` from
    `status_cli`, and iter-31's `gather_history` from `history_cli`).

    Reads every signal through the EXISTING module-level seams -- each called by
    BARE name so a `monkeypatch.setattr(foundry, ...)` in a test bites: gathers
    the paths from `files` if given (scanning EXACTLY those `pathlib.Path(f)` and
    NOT walking the repo -- the iter-22/14 `--files` contract) else an rglob of
    `cfg.repo` via `_gather_weak_test_files`; parses each path's text through
    `find_assertionless_tests` (folding a raised `SyntaxError`/`OSError` into a
    graceful `parse_errors` entry `(str(path), f"{type(exc).__name__}: {exc}")`
    rather than crashing -- Behavior 15 -- and continuing, never propagating);
    collects each assertion-free finding as `(str(path), name)`; hands them to
    the pure `summarize_weak_tests`; and returns the frozen `WeakTestSummary`
    core. Writes NOTHING to disk (read-only)."""
    if files is None:
        paths = _gather_weak_test_files(cfg.repo)
    else:
        paths = [pathlib.Path(f) for f in files]
    findings: list[tuple[str, str]] = []
    parse_errors: list[tuple[str, str]] = []
    for path in paths:
        try:
            names = find_assertionless_tests(path.read_text())
        except (SyntaxError, OSError) as exc:
            parse_errors.append((str(path), f"{type(exc).__name__}: {exc}"))
            continue
        for name in names:
            findings.append((str(path), name))
    return summarize_weak_tests(
        product=cfg.name, files_scanned=len(paths),
        findings=tuple(findings), parse_errors=tuple(parse_errors))


def weak_tests_cli(cfg: ProductConfig, files=None, as_json: bool = False) -> int:
    """On-demand CLI: scan test files for assertion-free `test*` functions.

    Gathers the scan through the `gather_weak_tests(cfg, files)` seam (iter 42 --
    which walks `cfg.repo` via `_gather_weak_test_files` or scans EXACTLY `files`,
    parses each through `find_assertionless_tests`, folds a `SyntaxError`/`OSError`
    into a graceful `parse_errors` entry rather than crashing, and builds the
    summary via the pure bare-name `summarize_weak_tests`) then prints the pure
    `WeakTestSummary` core and returns its `exit_code` (0 clean / 1 weak-or-
    unparseable / 2 nothing to scan). Output-preserving: the printed report /
    JSON / `--files` selection / exit code are byte-identical to iter 22/23.

    With `as_json=True` the entire stdout is ONE `json.dumps(summary.to_dict(),
    indent=2)` document (the stable machine contract for dashboards/reporter/CI,
    mirroring iter-19/20/21's `status`/`history`/`timing --json`); the default
    `as_json=False` is byte-for-byte the iter-22 human `render()` text. Either
    way the RETURN value is the same `summary.exit_code`, and `--files`
    selection is identical in both modes. Writes NOTHING to disk. A thin printer
    over the pure gather seam that adds no decision logic of its own, so the
    printed figures always match the `WeakTestSummary` fields. DORMANT -- no
    control path calls it."""
    summary = gather_weak_tests(cfg, files)
    # `--json` emits the pure snapshot as a single JSON document (stdout-only, no
    # decision logic added); the default stays the exact iter-22 human report.
    print(json.dumps(summary.to_dict(), indent=2) if as_json else summary.render())
    return summary.exit_code


@dataclasses.dataclass(frozen=True)
class ConstantAssertSummary:
    """The result of one constant-assert scan over a product's test files.

    Frozen structural mirror of `WeakTestSummary` (iter 22) that surfaces the
    iter-47 `find_constant_assert_tests` detector: `test*` functions whose ONLY
    assertion signal is a constant/tautological assert (`assert True`,
    `assert 1`, `assert "x"`). Such a test reports green yet validates nothing,
    and it slips past `find_assertionless_tests` -- and thus `foundry
    weak-tests` -- because the `assert` node itself reads as "has a signal", so
    this is the exact false-green class `weak-tests` structurally MISSES.
    `findings` is a tuple of ``(file_path, test_name)`` pairs (one per
    constant-assert test) and `parse_errors` a tuple of ``(file_path,
    message)`` pairs (files that would not parse / read) -- both hashable +
    order-stable. The three properties are pure derivations of the stored
    fields, so the scriptable exit code follows deterministically from what was
    gathered.
    """
    product: str
    files_scanned: int
    findings: tuple[tuple[str, str], ...]
    parse_errors: tuple[tuple[str, str], ...]

    @property
    def total_findings(self) -> int:
        """How many constant-assert `test*` functions were flagged."""
        return len(self.findings)

    @property
    def clean(self) -> bool:
        """True iff >=1 file was scanned AND nothing was flagged or unparseable.

        Scanning zero files is NOT clean (there was nothing to certify), so the
        operator can distinguish "verified clean" from "found nothing to look
        at" -- mirroring `WeakTestSummary.clean` (Behavior 2)."""
        return (self.files_scanned > 0 and not self.findings
                and not self.parse_errors)

    @property
    def exit_code(self) -> int:
        """Scriptable verdict: ``2`` when nothing was scanned, else ``1`` when
        anything was flagged OR failed to parse, else ``0`` (clean). Nothing-to-
        scan is checked FIRST so an empty run is `2`, never a false `0`
        (Behavior 2)."""
        if self.files_scanned == 0:
            return 2
        if self.findings or self.parse_errors:
            return 1
        return 0

    @property
    def verdict(self) -> str:
        """The single human token for the current `exit_code` -- ONE source of
        truth for `render()`'s last line so text + exit code never drift
        (Behavior 2)."""
        return {0: "clean", 1: "CONSTANT ASSERTS FOUND",
                2: "nothing to scan"}[self.exit_code]

    def render(self) -> str:
        """A deterministic multi-line report carrying every gathered signal.

        Contains, as substrings (the CLI's black-box contract): the literal
        ``foundry constant-asserts -- <product>``; ``files scanned: N``;
        ``constant-assert tests: N``; one ``  <file> :: <test_name>`` line per
        finding (so a dirty report names BOTH the file path and the test);
        ``parse errors: N`` with one ``  <file>: <message>`` line each; and a
        final ``verdict:`` token matching `exit_code` as the LAST non-empty
        line. When clean, no test-function name is printed (Behavior 3)."""
        lines = [
            f"foundry constant-asserts -- {self.product}",
            f"  files scanned: {self.files_scanned}",
            f"  constant-assert tests: {self.total_findings}",
        ]
        for path, name in self.findings:
            lines.append(f"  {path} :: {name}")
        lines.append(f"  parse errors: {len(self.parse_errors)}")
        for path, message in self.parse_errors:
            lines.append(f"  {path}: {message}")
        lines.append(f"verdict: {self.verdict}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """A pure, JSON-safe serialization of the whole constant-assert scan for
        machine consumers, mirroring `WeakTestSummary.to_dict()` (iter 22).

        Returns EXACTLY 8 keys in a fixed order: `product`/`files_scanned` as
        the stored fields verbatim, then the four DERIVED values each REUSING
        the frozen properties -- `total_findings`/`clean`/`exit_code`/`verdict`
        -- so the payload can never disagree with what `render()` prints or the
        exit code returns (`to_dict` re-derives nothing), then `findings` as a
        JSON array of ``{"file","test"}`` objects in the SAME order as
        `self.findings` and `parse_errors` as a JSON array of
        ``{"file","message"}`` objects in the SAME order as `self.parse_errors`.
        Every value is JSON-native (str / int / bool / list of str-only dicts),
        so `json.dumps(...)` never raises and the dict round-trips through
        `json.loads(json.dumps(...))` -- including when both lists are empty
        (Behavior 4). Pure: touches no filesystem, only the already-gathered
        snapshot."""
        return {
            "product": self.product,
            "files_scanned": self.files_scanned,
            "total_findings": self.total_findings,
            "clean": self.clean,
            "exit_code": self.exit_code,
            "verdict": self.verdict,
            "findings": [{"file": path, "test": name}
                         for path, name in self.findings],
            "parse_errors": [{"file": path, "message": message}
                             for path, message in self.parse_errors],
        }


def summarize_constant_asserts(*, product: str, files_scanned: int,
                               findings: tuple[tuple[str, str], ...],
                               parse_errors: tuple[tuple[str, str], ...]
                               ) -> ConstantAssertSummary:
    """Pure keyword-only constructor for a `ConstantAssertSummary` (Behavior 1).

    A thin, total wrapper (mirror of `summarize_weak_tests`) that packs the
    gathered signals into the frozen summary -- keyword-only so a caller can
    never transpose the fields by position, and it never raises. Kept separate
    from `constant_asserts_cli` so the decision core stays a pure function the
    tester can drive without any filesystem."""
    return ConstantAssertSummary(
        product=product, files_scanned=files_scanned,
        findings=tuple(findings), parse_errors=tuple(parse_errors))


def gather_constant_asserts(cfg: ProductConfig, files=None) -> ConstantAssertSummary:
    """Gather one product's constant-assert scan into a `ConstantAssertSummary`.

    The FIRST real call site of the iter-47 `find_constant_assert_tests`
    detector (shipped DORMANT with zero callers). A structural mirror of
    `gather_weak_tests` (iter 42) that differs ONLY in the detector it parses
    each file through -- `find_constant_assert_tests` (a `test*` whose only
    signal is a constant assert) instead of `find_assertionless_tests` (a
    `test*` with no signal at all). The two scans are DISJOINT by the detectors'
    construction, so `foundry constant-asserts` COMPLEMENTS `foundry weak-tests`
    rather than overlapping it.

    Reads every signal through the EXISTING module-level seams -- each called by
    BARE name so a `monkeypatch.setattr(foundry, ...)` in a test bites: gathers
    the paths from `files` if given (scanning EXACTLY those `pathlib.Path(f)`
    and NOT walking the repo -- the iter-22/14 `--files` contract) else an
    rglob of `cfg.repo` via the REUSED `_gather_weak_test_files` (same
    `WEAK_TEST_GLOBS` / skip-hidden/`.git` rules); parses each path's text
    through `find_constant_assert_tests` (folding a raised `SyntaxError`/
    `OSError` into a graceful `parse_errors` entry `(str(path),
    f"{type(exc).__name__}: {exc}")` rather than crashing, and CONTINUING to
    the next path, never propagating -- Behavior 5); collects each
    constant-assert finding as `(str(path), name)`; hands them to the pure
    bare-name `summarize_constant_asserts`; and returns the frozen
    `ConstantAssertSummary` core. Writes NOTHING to disk (read-only)."""
    if files is None:
        paths = _gather_weak_test_files(cfg.repo)
    else:
        paths = [pathlib.Path(f) for f in files]
    findings: list[tuple[str, str]] = []
    parse_errors: list[tuple[str, str]] = []
    for path in paths:
        try:
            names = find_constant_assert_tests(path.read_text())
        except (SyntaxError, OSError) as exc:
            parse_errors.append((str(path), f"{type(exc).__name__}: {exc}"))
            continue
        for name in names:
            findings.append((str(path), name))
    return summarize_constant_asserts(
        product=cfg.name, files_scanned=len(paths),
        findings=tuple(findings), parse_errors=tuple(parse_errors))


def constant_asserts_cli(cfg: ProductConfig, files=None,
                         as_json: bool = False) -> int:
    """On-demand CLI: scan test files for constant-assert `test*` functions.

    Gathers the scan through the `gather_constant_asserts(cfg, files)` seam
    (which walks `cfg.repo` via `_gather_weak_test_files` or scans EXACTLY
    `files`, parses each through `find_constant_assert_tests`, folds a
    `SyntaxError`/`OSError` into a graceful `parse_errors` entry rather than
    crashing, and builds the summary via the pure bare-name
    `summarize_constant_asserts`) then prints the pure `ConstantAssertSummary`
    core and returns its `exit_code` (0 clean / 1 constant-assert-or-unparseable
    / 2 nothing to scan).

    With `as_json=True` the entire stdout is ONE `json.dumps(summary.to_dict(),
    indent=2)` document (the stable machine contract for dashboards/reporter/CI,
    mirroring `weak_tests_cli --json`); the default `as_json=False` is the human
    `render()` text. Either way the RETURN value is the same `summary.exit_code`,
    and `--files` selection is identical in both modes. Writes NOTHING to disk.
    A thin printer over the pure gather seam that adds no decision logic of its
    own, so the printed figures always match the `ConstantAssertSummary` fields.
    DORMANT -- no control path calls it; only `main()`'s argparse dispatch."""
    summary = gather_constant_asserts(cfg, files)
    # `--json` emits the pure snapshot as a single JSON document (stdout-only,
    # no decision logic added); the default stays the human report.
    print(json.dumps(summary.to_dict(), indent=2) if as_json else summary.render())
    return summary.exit_code


@dataclasses.dataclass(frozen=True)
class SkippedTestSummary:
    """The result of one always-skipped-test scan over a product's test files.

    Frozen structural mirror of `ConstantAssertSummary` (iter 48) that surfaces
    the iter-55 `find_always_skipped_tests` detector: `test*` functions that are
    UNCONDITIONALLY skipped -- decorated with `@pytest.mark.skip` /
    `@unittest.skip`, or a constant-condition `@skipif(True)` /
    `@skipUnless(False)`. Such a test NEVER runs, validates nothing, yet reports
    the suite green, and no existing gate catches it (the item-11 fresh-clone
    re-run passes a skipped test too). It COMPLEMENTS `weak-tests` /
    `constant-asserts` (which flag tests that DO run but assert nothing
    meaningful) by catching a DIFFERENT antipattern -- a test that does not run
    at all -- so unlike the DISJOINT `constant-asserts` its findings can OVERLAP
    those detectors (a skipped test may also be assertion-free). `findings` is a
    tuple of ``(file_path, test_name)`` pairs (one per always-skipped test) and
    `parse_errors` a tuple of ``(file_path, message)`` pairs (files that would
    not parse / read) -- both hashable + order-stable. The three properties are
    pure derivations of the stored fields, so the scriptable exit code follows
    deterministically from what was gathered.
    """
    product: str
    files_scanned: int
    findings: tuple[tuple[str, str], ...]
    parse_errors: tuple[tuple[str, str], ...]

    @property
    def total_findings(self) -> int:
        """How many always-skipped `test*` functions were flagged."""
        return len(self.findings)

    @property
    def clean(self) -> bool:
        """True iff >=1 file was scanned AND nothing was flagged or unparseable.

        Scanning zero files is NOT clean (there was nothing to certify), so the
        operator can distinguish "verified clean" from "found nothing to look
        at" -- mirroring `ConstantAssertSummary.clean` (Behavior 2)."""
        return (self.files_scanned > 0 and not self.findings
                and not self.parse_errors)

    @property
    def exit_code(self) -> int:
        """Scriptable verdict: ``2`` when nothing was scanned, else ``1`` when
        anything was flagged OR failed to parse, else ``0`` (clean). Nothing-to-
        scan is checked FIRST so an empty run is `2`, never a false `0`
        (Behavior 2)."""
        if self.files_scanned == 0:
            return 2
        if self.findings or self.parse_errors:
            return 1
        return 0

    @property
    def verdict(self) -> str:
        """The single human token for the current `exit_code` -- ONE source of
        truth for `render()`'s last line so text + exit code never drift
        (Behavior 2)."""
        return {0: "clean", 1: "ALWAYS-SKIPPED TESTS FOUND",
                2: "nothing to scan"}[self.exit_code]

    def render(self) -> str:
        """A deterministic multi-line report carrying every gathered signal.

        Contains, as substrings (the CLI's black-box contract): the literal
        ``foundry skipped-tests -- <product>``; ``files scanned: N``;
        ``always-skipped tests: N``; one ``  <file> :: <test_name>`` line per
        finding (so a dirty report names BOTH the file path and the test);
        ``parse errors: N`` with one ``  <file>: <message>`` line each; and a
        final ``verdict:`` token matching `exit_code` as the LAST non-empty
        line. When clean, no test-function name is printed (Behavior 3)."""
        lines = [
            f"foundry skipped-tests -- {self.product}",
            f"  files scanned: {self.files_scanned}",
            f"  always-skipped tests: {self.total_findings}",
        ]
        for path, name in self.findings:
            lines.append(f"  {path} :: {name}")
        lines.append(f"  parse errors: {len(self.parse_errors)}")
        for path, message in self.parse_errors:
            lines.append(f"  {path}: {message}")
        lines.append(f"verdict: {self.verdict}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """A pure, JSON-safe serialization of the whole skipped-test scan for
        machine consumers, mirroring `ConstantAssertSummary.to_dict()` (iter 48).

        Returns EXACTLY 8 keys in a fixed order: `product`/`files_scanned` as
        the stored fields verbatim, then the four DERIVED values each REUSING
        the frozen properties -- `total_findings`/`clean`/`exit_code`/`verdict`
        -- so the payload can never disagree with what `render()` prints or the
        exit code returns (`to_dict` re-derives nothing), then `findings` as a
        JSON array of ``{"file","test"}`` objects in the SAME order as
        `self.findings` and `parse_errors` as a JSON array of
        ``{"file","message"}`` objects in the SAME order as `self.parse_errors`.
        Every value is JSON-native (str / int / bool / list of str-only dicts),
        so `json.dumps(...)` never raises and the dict round-trips through
        `json.loads(json.dumps(...))` -- including when both lists are empty
        (Behavior 4). Pure: touches no filesystem, only the already-gathered
        snapshot."""
        return {
            "product": self.product,
            "files_scanned": self.files_scanned,
            "total_findings": self.total_findings,
            "clean": self.clean,
            "exit_code": self.exit_code,
            "verdict": self.verdict,
            "findings": [{"file": path, "test": name}
                         for path, name in self.findings],
            "parse_errors": [{"file": path, "message": message}
                             for path, message in self.parse_errors],
        }


def summarize_skipped_tests(*, product: str, files_scanned: int,
                            findings: tuple[tuple[str, str], ...],
                            parse_errors: tuple[tuple[str, str], ...]
                            ) -> SkippedTestSummary:
    """Pure keyword-only constructor for a `SkippedTestSummary` (Behavior 1).

    A thin, total wrapper (mirror of `summarize_constant_asserts`) that packs
    the gathered signals into the frozen summary -- keyword-only so a caller can
    never transpose the fields by position, and it never raises. Kept separate
    from `skipped_tests_cli` so the decision core stays a pure function the
    tester can drive without any filesystem."""
    return SkippedTestSummary(
        product=product, files_scanned=files_scanned,
        findings=tuple(findings), parse_errors=tuple(parse_errors))


def gather_skipped_tests(cfg: ProductConfig, files=None) -> SkippedTestSummary:
    """Gather one product's always-skipped-test scan into a `SkippedTestSummary`.

    The FIRST real call site of the iter-55 `find_always_skipped_tests`
    detector (shipped DORMANT with zero callers). A structural mirror of
    `gather_constant_asserts` (iter 48) that differs ONLY in the detector it
    parses each file through -- `find_always_skipped_tests` (a `test*`
    unconditionally skipped by decorator) instead of `find_constant_assert_tests`
    (a `test*` whose only signal is a constant assert). Unlike the DISJOINT
    `constant-asserts` scan this can OVERLAP the other weak-test detectors (a
    skipped test may also be assertion-free), so `foundry skipped-tests` is a
    THIRD COMPLEMENTARY lens catching a DIFFERENT antipattern -- a test that
    never runs at all.

    Reads every signal through the EXISTING module-level seams -- each called by
    BARE name so a `monkeypatch.setattr(foundry, ...)` in a test bites: gathers
    the paths from `files` if given (scanning EXACTLY those `pathlib.Path(f)`
    and NOT walking the repo -- the iter-22/14 `--files` contract) else an
    rglob of `cfg.repo` via the REUSED `_gather_weak_test_files` (same
    `WEAK_TEST_GLOBS` / skip-hidden/`.git` rules); parses each path's text
    through `find_always_skipped_tests` (folding a raised `SyntaxError` /
    `OSError` into a graceful `parse_errors` entry `(str(path),
    f"{type(exc).__name__}: {exc}")` rather than crashing, and CONTINUING to the
    next path, never propagating -- Behavior 5); collects each always-skipped
    finding as `(str(path), name)`; hands them to the pure bare-name
    `summarize_skipped_tests`; and returns the frozen `SkippedTestSummary` core.
    Writes NOTHING to disk (read-only)."""
    if files is None:
        paths = _gather_weak_test_files(cfg.repo)
    else:
        paths = [pathlib.Path(f) for f in files]
    findings: list[tuple[str, str]] = []
    parse_errors: list[tuple[str, str]] = []
    for path in paths:
        try:
            names = find_always_skipped_tests(path.read_text())
        except (SyntaxError, OSError) as exc:
            parse_errors.append((str(path), f"{type(exc).__name__}: {exc}"))
            continue
        for name in names:
            findings.append((str(path), name))
    return summarize_skipped_tests(
        product=cfg.name, files_scanned=len(paths),
        findings=tuple(findings), parse_errors=tuple(parse_errors))


def skipped_tests_cli(cfg: ProductConfig, files=None,
                      as_json: bool = False) -> int:
    """On-demand CLI: scan test files for always-skipped `test*` functions.

    Gathers the scan through the `gather_skipped_tests(cfg, files)` seam (which
    walks `cfg.repo` via `_gather_weak_test_files` or scans EXACTLY `files`,
    parses each through `find_always_skipped_tests`, folds a `SyntaxError` /
    `OSError` into a graceful `parse_errors` entry rather than crashing, and
    builds the summary via the pure bare-name `summarize_skipped_tests`) then
    prints the pure `SkippedTestSummary` core and returns its `exit_code` (0
    clean / 1 always-skipped-or-unparseable / 2 nothing to scan).

    With `as_json=True` the entire stdout is ONE `json.dumps(summary.to_dict(),
    indent=2)` document (the stable machine contract for dashboards/reporter/CI,
    mirroring `constant_asserts_cli --json`); the default `as_json=False` is the
    human `render()` text. Either way the RETURN value is the same
    `summary.exit_code`, and `--files` selection is identical in both modes.
    Writes NOTHING to disk. A thin printer over the pure gather seam that adds no
    decision logic of its own, so the printed figures always match the
    `SkippedTestSummary` fields. DORMANT -- no control path calls it; only
    `main()`'s argparse dispatch."""
    summary = gather_skipped_tests(cfg, files)
    # `--json` emits the pure snapshot as a single JSON document (stdout-only,
    # no decision logic added); the default stays the human report.
    print(json.dumps(summary.to_dict(), indent=2) if as_json else summary.render())
    return summary.exit_code


@dataclasses.dataclass(frozen=True)
class TestQualitySummary:
    """Composite of the THREE offline "validates-nothing" scans for one product.

    Folds `WeakTestSummary` (assertion-free, iter 22), `ConstantAssertSummary`
    (constant/tautological assert, iter 48) and `SkippedTestSummary` (never
    runs, iter 56) into ONE frozen quality gate over a product's test files
    (roadmap item 6 -- a false-green test is the foundry's #1 verification
    failure). It is the QUALITY-axis parallel of iter-28's LAUNCH `preflight`
    composite (which folds `doctor` + `single-brain` into ONE GO/NO-GO/CAUTION
    verdict): to certify a product against all three test antipatterns an
    operator would otherwise run three commands, each re-walking the repo with
    its own 0/1/2 exit code, and a shell `weak-tests && constant-asserts &&
    skipped-tests` collapses those into ONE undifferentiated non-zero (losing
    both the nothing-to-scan(2) vs issues-found(1) distinction AND the
    per-category breakdown). This gives ONE verdict + a per-CATEGORY triage
    breakdown in one pass.

    Frozen (value equality for free, matching the sub-cores). EVERY derived
    property REUSES the frozen sub-`WeakTestSummary`/`ConstantAssertSummary`/
    `SkippedTestSummary` props, so `render()` / `to_dict()` / the exit code can
    never disagree with the sub-scans.

    OVERLAP note (a first-class correctness item, per the iter-56/57 disjoint-vs-
    overlap lesson): `constant-asserts` is DISJOINT from `weak-tests` by the
    detectors' construction (a constant assert CARRIES an assert node, so an
    assertion-free scan can never also flag it), BUT an always-skipped test CAN
    also be assertion-free AND can carry a constant assert -- so `skipped`
    findings can OVERLAP `weak` and `constant`. Therefore `total_findings` is a
    per-CATEGORY triage total in which a test flagged by two lenses counts once
    in EACH category (intentionally NOT a de-duplicated distinct-test count).
    """
    product: str
    weak: WeakTestSummary
    constant: ConstantAssertSummary
    skipped: SkippedTestSummary

    @property
    def files_scanned(self) -> int:
        """Files scanned by the composite -- the weak sub-scan's count.

        All three sub-scans walk the IDENTICAL file set (`_gather_weak_test_files
        (cfg.repo)` when `files is None`, else `[Path(f) for f in files]`), so
        the weak sub's `files_scanned` is representative -- a documented
        invariant, not an approximation."""
        return self.weak.files_scanned

    @property
    def weak_findings(self) -> int:
        """How many assertion-free `test*` functions the weak lens flagged."""
        return self.weak.total_findings

    @property
    def constant_findings(self) -> int:
        """How many constant-assert `test*` functions the constant lens flagged."""
        return self.constant.total_findings

    @property
    def skipped_findings(self) -> int:
        """How many always-skipped `test*` functions the skipped lens flagged."""
        return self.skipped.total_findings

    @property
    def total_findings(self) -> int:
        """CATEGORY-WEIGHTED sum of the three lenses' findings.

        NOT a de-duplicated union: because `skipped` findings can OVERLAP `weak`
        and `constant` (see the class OVERLAP note), a test flagged by two
        lenses counts once in EACH category. This is a triage total answering
        "how many category-hits are there", not "how many distinct tests"."""
        return (self.weak_findings + self.constant_findings
                + self.skipped_findings)

    @property
    def parse_errors(self) -> tuple[tuple[str, str], ...]:
        """The DISTINCT `(file, message)` parse errors across the three lenses,
        in first-seen order (weak, then constant, then skipped).

        All three sub-scans fold a `SyntaxError`/`OSError` into the IDENTICAL
        `(str(path), f"{type(exc).__name__}: {exc}")` entry, so in a real run a
        genuinely unparseable file yields a byte-identical entry in all three
        lists and this dedup collapses them to ONE (no triple-count). The dedup
        also keeps the union correct if a test constructs the three sub-summaries
        with DIFFERENT parse errors."""
        seen: set[tuple[str, str]] = set()
        merged: list[tuple[str, str]] = []
        for sub in (self.weak, self.constant, self.skipped):
            for entry in sub.parse_errors:
                if entry not in seen:
                    seen.add(entry)
                    merged.append(entry)
        return tuple(merged)

    @property
    def total_parse_errors(self) -> int:
        """How many DISTINCT parse errors the composite carries."""
        return len(self.parse_errors)

    @property
    def exit_code(self) -> int:
        """Scriptable composite verdict derived from the THREE sub exit codes.

        Let `codes = (weak.exit_code, constant.exit_code, skipped.exit_code)`:
        return ``2`` iff EVERY lens had nothing to scan (`all(c == 2)`), else
        ``1`` iff ANY lens flagged a finding or parse error (`1 in codes`), else
        ``0`` (clean). Derived from the sub exit codes rather than re-aggregating
        `files_scanned`, so it stays correct even when a test constructs the
        three sub-summaries independently."""
        codes = (self.weak.exit_code, self.constant.exit_code,
                 self.skipped.exit_code)
        if all(c == 2 for c in codes):
            return 2
        if 1 in codes:
            return 1
        return 0

    @property
    def clean(self) -> bool:
        """True iff the composite `exit_code` is 0 -- the SINGLE source of truth
        (no independent re-derivation, so `clean` can never disagree with the
        exit code)."""
        return self.exit_code == 0

    @property
    def verdict(self) -> str:
        """The single human token for the current `exit_code` -- ONE source of
        truth for `render()`'s last line so text + exit code never drift. The
        composite token set is `clean`/`QUALITY ISSUES FOUND`/`nothing to scan`,
        NOT the sub-scans' `WEAK TESTS FOUND`/etc."""
        return {0: "clean", 1: "QUALITY ISSUES FOUND",
                2: "nothing to scan"}[self.exit_code]

    def render(self) -> str:
        """A deterministic multi-line composite report carrying every lens's
        signal.

        Contains, as substrings (the CLI's black-box contract): the literal
        ``foundry test-quality -- <product>``; ``files scanned: N``;
        ``assertion-free tests: A``; ``constant-assert tests: B``;
        ``always-skipped tests: C``; ``total quality findings: T`` (T ==
        `total_findings`); one ``  [assertion-free] <file> :: <test>`` line per
        weak finding, one ``  [constant-assert] <file> :: <test>`` per constant
        finding, one ``  [always-skipped] <file> :: <test>`` per skipped finding
        (each tag names WHICH lens flagged it, so an OVERLAPPING test appears
        under BOTH tags); ``parse errors: P`` with one ``  <file>: <message>``
        line each (the deduped union); and a final ``verdict:`` token matching
        `exit_code` as the LAST non-empty line. A clean composite prints NO
        finding lines."""
        lines = [
            f"foundry test-quality -- {self.product}",
            f"  files scanned: {self.files_scanned}",
            f"  assertion-free tests: {self.weak_findings}",
            f"  constant-assert tests: {self.constant_findings}",
            f"  always-skipped tests: {self.skipped_findings}",
            f"  total quality findings: {self.total_findings}",
        ]
        for path, name in self.weak.findings:
            lines.append(f"  [assertion-free] {path} :: {name}")
        for path, name in self.constant.findings:
            lines.append(f"  [constant-assert] {path} :: {name}")
        for path, name in self.skipped.findings:
            lines.append(f"  [always-skipped] {path} :: {name}")
        lines.append(f"  parse errors: {self.total_parse_errors}")
        for path, message in self.parse_errors:
            lines.append(f"  {path}: {message}")
        lines.append(f"verdict: {self.verdict}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """A pure, JSON-safe serialization of the whole composite scan.

        Returns EXACTLY these keys in a fixed order: `product`; then the scalar
        derived fields `files_scanned`/`weak_findings`/`constant_findings`/
        `skipped_findings`/`total_findings`/`total_parse_errors`/`clean`/
        `exit_code`/`verdict`, each REUSING the frozen properties (so the payload
        can never disagree with `render()`/the exit code); then the three
        sub-documents `weak`/`constant`/`skipped` as their respective
        `to_dict()` VERBATIM (so a machine consumer can drill into any lens); and
        `parse_errors` as a JSON array of ``{"file","message"}`` objects (the
        deduped union, same order as `self.parse_errors`). Every value is
        JSON-native, so `json.dumps(...)` never raises and the dict round-trips
        through `json.loads(json.dumps(...))`. Pure: touches no filesystem, only
        the already-gathered sub-summaries."""
        return {
            "product": self.product,
            "files_scanned": self.files_scanned,
            "weak_findings": self.weak_findings,
            "constant_findings": self.constant_findings,
            "skipped_findings": self.skipped_findings,
            "total_findings": self.total_findings,
            "total_parse_errors": self.total_parse_errors,
            "clean": self.clean,
            "exit_code": self.exit_code,
            "verdict": self.verdict,
            "weak": self.weak.to_dict(),
            "constant": self.constant.to_dict(),
            "skipped": self.skipped.to_dict(),
            "parse_errors": [{"file": path, "message": message}
                             for path, message in self.parse_errors],
        }


def summarize_test_quality(*, product: str, weak: WeakTestSummary,
                           constant: ConstantAssertSummary,
                           skipped: SkippedTestSummary) -> TestQualitySummary:
    """Pure keyword-only constructor for a `TestQualitySummary` (Behavior 1).

    A thin, total wrapper (mirror of `summarize_skipped_tests`) that packs the
    three sub-summaries into the frozen composite -- keyword-only so a caller can
    never transpose the fields by position, and it never raises. Kept separate
    from `test_quality_cli` so the decision core stays a pure function the tester
    can drive without any filesystem."""
    return TestQualitySummary(product=product, weak=weak,
                              constant=constant, skipped=skipped)


def gather_test_quality(cfg: ProductConfig, files=None) -> TestQualitySummary:
    """Gather one product's COMPOSITE test-quality scan into a
    `TestQualitySummary` -- the per-product gather the `company-test-quality`
    roll-up drives (the exact analog of `gather_skipped_tests` for
    `company-skipped-tests`).

    Composes the three SHIPPED gather seams -- `gather_weak_tests`,
    `gather_constant_asserts`, `gather_skipped_tests` (iters 42/48/56) -- each
    called by BARE module name so a `monkeypatch.setattr(foundry, ...)` in a test
    bites, and each passed the SAME `files` so all three scan the identical set,
    then folds the three frozen sub-summaries into the pure composite via
    `summarize_test_quality`. Adds NO new I/O seam of its own (the iter-28/30
    endorsed "compose existing frozen cores" pattern). `test_quality_cli` keeps
    its OWN inline composition (byte-unchanged this iter); a DRY refactor to share
    this seam is a separate future bite. Writes NOTHING to disk (read-only)."""
    return summarize_test_quality(
        product=cfg.name,
        weak=gather_weak_tests(cfg, files),
        constant=gather_constant_asserts(cfg, files),
        skipped=gather_skipped_tests(cfg, files),
    )


def test_quality_cli(cfg: ProductConfig, files=None,
                     as_json: bool = False) -> int:
    """On-demand COMPOSITE CLI: fold all THREE offline "validates-nothing" scans
    over one product's test files into ONE verdict / ONE exit code / ONE report.

    The QUALITY-axis parallel of iter-28's LAUNCH `preflight` (which composes
    `doctor` + `single-brain`): rather than run `weak-tests`, `constant-asserts`
    and `skipped-tests` separately -- each re-walking the repo, each with its own
    0/1/2 exit code a shell `&&` would collapse into one undifferentiated
    non-zero -- this scans once and reports a per-CATEGORY breakdown.

    Composes the three SHIPPED gather seams -- `gather_weak_tests`,
    `gather_constant_asserts`, `gather_skipped_tests` (iters 42/48/56) -- each
    called by BARE module name so a `monkeypatch.setattr(foundry, ...)` in a
    test bites, and each passed the SAME `files` so all three scan the identical
    set. It adds NO new I/O seam of its own (the iter-28/30 endorsed "compose
    existing frozen cores" pattern). Prints the pure `TestQualitySummary` core
    and returns its `exit_code` (0 clean / 1 quality-issues / 2 nothing to scan).

    With `as_json=True` the entire stdout is ONE `json.dumps(summary.to_dict(),
    indent=2)` document (embedding the three sub-docs); the default `as_json=
    False` is the human `render()` text. Either way the RETURN value is the same
    `summary.exit_code`, and `--files` selection is identical in both modes.
    Writes NOTHING to disk. A thin printer that adds no decision logic of its
    own, so the printed figures always match the `TestQualitySummary` fields.
    DORMANT -- no control path calls it; only `main()`'s argparse dispatch."""
    summary = summarize_test_quality(
        product=cfg.name,
        weak=gather_weak_tests(cfg, files),
        constant=gather_constant_asserts(cfg, files),
        skipped=gather_skipped_tests(cfg, files),
    )
    # `--json` emits the pure snapshot as a single JSON document (stdout-only,
    # no decision logic added); the default stays the human report.
    print(json.dumps(summary.to_dict(), indent=2) if as_json else summary.render())
    return summary.exit_code



# --------------------------------------------------------------------------- #
# Post-release fresh-clone verification (DORMANT — item 11, bite 1/2).
#
# Proves the *pushed* commit is deployable from a clean checkout, not just that
# the working tree is green — closing the class of release bugs (a file never
# `git add`-ed, uv.lock drift, a leftover-dev-tree-only import) a CD system
# exists to prevent. Every external effect flows through two monkeypatchable
# module-level seams — `run_cmd` (all command execution) and `cleanup_clone`
# (throwaway-clone deletion) — so the whole path is offline-verifiable.
# `sha_matches` and `postrelease_verdict` are pure. NOTHING in the running loop
# calls any of this yet; the pipeline wiring is deferred to iter 03.
# --------------------------------------------------------------------------- #
CMD_TIMEOUT = 600  # default per-command wall clock for run_cmd (seconds)


@dataclasses.dataclass(frozen=True)
class CmdResult:
    """Outcome of one external command run through the `run_cmd` seam.

    `.ok` is True ONLY when the process launched, exited, and returned 0.
    `.out` carries combined stdout+stderr (or the reason a launch/timeout
    failed) so callers never touch the raw process object. Frozen so a result
    can't be mutated after the fact.
    """
    ok: bool
    out: str


def run_cmd(args, cwd=None, timeout: int = CMD_TIMEOUT) -> "CmdResult":
    """Execute one command, NEVER raising (Behavior 2).

    The single I/O seam for the whole verify path: the tester monkeypatches
    `foundry.run_cmd` to script command outcomes offline, so verification does
    zero real subprocess/network work in tests. A launch failure or timeout is
    folded into a `.ok is False` result with a non-empty `.out` explaining why
    — an unreachable command must never crash the verifier.
    """
    try:
        p = subprocess.run(list(args), cwd=cwd, capture_output=True,
                           text=True, timeout=timeout)
        return CmdResult(p.returncode == 0, (p.stdout or "") + (p.stderr or ""))
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CmdResult(
            False, f"run_cmd could not execute {list(args)!r}: {exc!r}")


def cleanup_clone(clone_dir) -> None:
    """Delete a throwaway clone dir (best-effort deletion seam).

    Isolated so the tester can force a raising cleanup and confirm the verdict
    is unaffected. `verify_fresh_clone` guards every call, so a cleanup failure
    never propagates or changes the verdict (Behavior 10).
    """
    shutil.rmtree(clone_dir, ignore_errors=True)


def _monotonic() -> float:
    """Monotonic clock read -- a measurement-only module seam.

    Isolated as a module-level name (NOT `time.monotonic` inline) so a test can
    `monkeypatch.setattr(foundry, "_monotonic", ...)` to script the two reads
    that bracket the fresh-clone test command (roadmap item 7). It feeds ONLY
    the per-ship suite wall-time measurement -- never any control flow -- so
    patching it can never perturb `sleep_interruptible` or loop timing.
    """
    return time.monotonic()


def sha_matches(expected: str, actual: str) -> bool:
    """True iff two commit ids agree on the shorter of their lengths.

    A short sha is a prefix of the full sha it names, so prefix comparison on
    the common length lets a 9-char short id match its 40-char full id. An
    empty id or the `"?"` unreachable-sentinel on either side is never a match.
    """
    if not expected or not actual or expected == "?" or actual == "?":
        return False
    n = min(len(expected), len(actual))
    return expected[:n] == actual[:n]


# Default fresh-clone suite wall-time (seconds) past which a ship is flagged
# SLOW. Module-level + patchable so a test -- and, later, item 7 bite 2 (a PM
# speed-story trigger) -- reads the threshold at CALL time, not a hard-coded one.
SUITE_SLOW_SECONDS: float = 120.0


def suite_timing_line(seconds: float, threshold: float) -> str:
    """Format the per-ship deployable-suite wall-time line (item 7, bite 1).

    Pure + total: renders `seconds` to exactly two decimals and appends a `SLOW`
    advisory ONLY when strictly `seconds > threshold` -- the boundary case
    (seconds == threshold) is deliberately NOT slow, so a suite sitting right at
    the limit never nags. This is the smallest visible unit of the throughput
    signal the unattended-continuous-shipping goal needs; bite 2 will file a
    speed story off the same threshold.
    """
    base = f"fresh-clone suite wall-time: {seconds:.2f}s"
    if seconds > threshold:
        return (f"{base} SLOW (>{threshold:.2f}s threshold; "
                "consider a speed story)")
    return base


@dataclasses.dataclass(frozen=True)
class PostReleaseResult:
    """Verdict of a fresh-clone verification.

    `.sentinel` is DERIVED from `.healthy` (property), so the two can never
    disagree: HEALTHY whenever healthy (including the infra-skipped case), else
    BROKEN. `.skipped_infra` marks a network-boundary skip — never a hotfix.
    """
    healthy: bool
    skipped_infra: bool
    detail: str
    # Fresh-clone suite wall-time in seconds (item 7, bite 1). DIAGNOSTIC ONLY:
    # it NEVER affects `healthy`, `skipped_infra`, or the derived `sentinel`.
    # `None` whenever the fresh-clone test command did not run (infra-skip,
    # postrelease disabled, or a verify error) -- see `verify_fresh_clone`.
    test_seconds: float | None = None

    @property
    def sentinel(self) -> str:
        return "POSTRELEASE: HEALTHY" if self.healthy else "POSTRELEASE: BROKEN"


def postrelease_verdict(*, remote_ok: bool, clone_ok: bool, setup_ok: bool,
                        test_ok: bool, sha_ok: bool, smoke_ran: bool,
                        smoke_ok: bool) -> "PostReleaseResult":
    """Pure decision logic mapping step outcomes to a verdict.

    WHY infra tolerance takes precedence (Behavior 5): remote discovery,
    `git clone`, and `uv sync` are the network-boundary steps; a transient
    failure there must NEVER raise a hotfix, so any of them failing =>
    HEALTHY + skipped_infra. Only once the boundary is clean do the real
    signals (test, sha, smoke) decide BROKEN (Behavior 6). A skipped smoke
    (no smoke_cmd) never causes BROKEN (Behavior 7).
    """
    if not (remote_ok and clone_ok and setup_ok):
        return PostReleaseResult(
            True, True,
            "network-boundary step failed "
            f"(remote_ok={remote_ok}, clone_ok={clone_ok}, "
            f"setup_ok={setup_ok}); treated as infra, not a hotfix")
    if not test_ok:
        return PostReleaseResult(
            False, False, "fresh-clone test suite failed")
    if not sha_ok:
        return PostReleaseResult(
            False, False, "cloned HEAD does not match the pushed sha")
    if smoke_ran and not smoke_ok:
        return PostReleaseResult(
            False, False, "fresh-clone smoke command failed")
    return PostReleaseResult(
        True, False,
        "fresh clone builds, tests, and matches the pushed sha"
        + ("" if smoke_ran else " (smoke skipped)"))


def verify_fresh_clone(cfg: "ProductConfig", expected_sha: str,
                       clone_dir) -> "PostReleaseResult":
    """Re-verify a pushed commit from a throwaway clone (DORMANT this iter).

    Runs every external effect through the `run_cmd`/`cleanup_clone` module
    seams — read as module-level names AT CALL TIME so
    `monkeypatch.setattr(foundry, "run_cmd"/"cleanup_clone", ...)` bites — and
    folds the step outcomes through the pure `postrelease_verdict`. Cleanup is
    attempted on EVERY path (Behavior 10); an unexpected seam error is treated
    as infra (HEALTHY + skipped_infra), never a false hotfix (Behavior 11).
    """
    remote_ok = clone_ok = setup_ok = test_ok = sha_ok = False
    smoke_ran = False
    smoke_ok = True  # only consulted when smoke_ran is True
    test_seconds: float | None = None  # set ONLY when the test command runs
    result: "PostReleaseResult"
    try:
        # 1. discover the clone source (origin remote URL) in cfg.repo
        url_res = run_cmd(["git", "-C", str(cfg.repo),
                           "remote", "get-url", "origin"])
        remote_ok = url_res.ok
        clone_url = url_res.out.strip()

        # 2. clone into the throwaway dir
        if remote_ok:
            clone_ok = run_cmd(
                ["git", "clone", clone_url, str(clone_dir)]).ok
        # 3. install deps in the clone
        if remote_ok and clone_ok:
            setup_ok = run_cmd(shlex.split(cfg.setup_cmd), cwd=clone_dir).ok
        # 4. test + sha check + optional smoke, all inside the clone
        if remote_ok and clone_ok and setup_ok:
            # Time ONLY the full-suite run: this is the comparable per-ship
            # "deployable-suite wall-time" (item 7). `_monotonic` is a module
            # seam so a test scripts the two bracketing reads; the delta is a
            # non-negative float threaded onto the verdict below.
            _t0 = _monotonic()
            test_ok = run_cmd(shlex.split(cfg.test_cmd), cwd=clone_dir).ok
            test_seconds = _monotonic() - _t0
            head_res = run_cmd(["git", "-C", str(clone_dir),
                                "rev-parse", "HEAD"])
            sha_ok = head_res.ok and sha_matches(
                expected_sha, head_res.out.strip())
            if cfg.smoke_cmd:  # smoke is issued ONLY when a smoke_cmd is set
                smoke_ran = True
                smoke_ok = run_cmd(shlex.split(cfg.smoke_cmd),
                                   cwd=clone_dir).ok

        result = postrelease_verdict(
            remote_ok=remote_ok, clone_ok=clone_ok, setup_ok=setup_ok,
            test_ok=test_ok, sha_ok=sha_ok, smoke_ran=smoke_ran,
            smoke_ok=smoke_ok)
        # Thread the measured wall-time onto the PURE verdict WITHOUT touching
        # its decision logic (test_seconds is inert; Behaviors 6/12). It stays
        # None on the infra-skip path where the test command never ran.
        result = dataclasses.replace(result, test_seconds=test_seconds)
    except Exception as exc:  # a seam blew up => infra, never a false hotfix
        result = PostReleaseResult(
            True, True, f"verification errored, treated as infra: {exc!r}")
    finally:
        try:
            cleanup_clone(clone_dir)  # always attempted, on every path
        except Exception:
            pass  # cleanup failure must never change the verdict (Behavior 10)
    return result


# --------------------------------------------------------------------------- #
# Post-release wiring (item 11, bite 2/2) -- the deterministic inline "stage".
#
# NOT an LLM agent role: bite 1 already built the whole verification as a
# pure/mechanical helper, and the product quality bar demands deterministic +
# offline-testable, which an agent stage is neither. `postrelease_step` gives
# `verify_fresh_clone` a call site, a `POSTRELEASE:` sentinel artifact, and a
# per-product `HOTFIX_NEEDED.md` lifecycle. It runs ONLY on the SHIPPED branch
# (after the push already happened), so a BROKEN verdict never reverts and
# never changes `status` -- the bad public commit is fixed forward by the next
# iteration via the hotfix flag.
# --------------------------------------------------------------------------- #
def hotfix_flag_path(cfg: ProductConfig) -> pathlib.Path:
    """Per-product hotfix flag location: `<work_root>/HOTFIX_NEEDED.md`."""
    return pathlib.Path(cfg.work_root) / "HOTFIX_NEEDED.md"


def write_hotfix_flag(cfg: ProductConfig, sha: str, detail: str) -> None:
    """Raise the hotfix flag after a BROKEN post-release.

    Overwrites any existing flag (newest breakage wins -- no append pile-up) and
    embeds both the pushed `sha` and the verbatim `detail` so the next PM has
    the evidence it needs. Never raises for a normal writable work_root.
    """
    path = hotfix_flag_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# HOTFIX NEEDED -- post-release verification is BROKEN\n\n"
        f"- Pushed sha: {sha}\n"
        f"- Evidence: {detail}\n\n"
        "The next PM's ONLY feature this iteration is the hotfix that makes the "
        "post-release verification HEALTHY again (which clears this flag). Do "
        "NOT revert or force-push the bad commit -- fix it forward.\n")


def clear_hotfix_flag(cfg: ProductConfig) -> None:
    """Remove the hotfix flag if present; silent no-op when it is absent."""
    hotfix_flag_path(cfg).unlink(missing_ok=True)


# --------------------------------------------------------------------------- #
# item 7, bite 2 (COMPLETES item 7): surface the SLOW-suite throughput signal
# to the next single-shot PM the same way a BROKEN release is surfaced -- a
# per-product flag file the PM checks at the top of its turn -- but ADVISORY
# (NON-blocking). A slow suite is a throughput concern, not a release defect,
# so this flag never forces the iteration's feature and is always subordinate
# to `HOTFIX_NEEDED.md`. It mirrors the iter-03 hotfix flag lifecycle
# (write on slow / clear on fast / leave-untouched on an un-timed skip), keyed
# on the MEASURED fresh-clone suite wall-time, INDEPENDENT of `healthy`.
# --------------------------------------------------------------------------- #
def speed_story_needed(test_seconds: float | None, threshold: float) -> bool:
    """Whether the measured fresh-clone suite wall-time warrants a speed story.

    Pure + total: `True` iff a wall-time was actually measured AND it strictly
    exceeds the threshold. `None` (no comparable measurement -- infra-skip,
    disabled, or a verify error) is NOT slow; the boundary (seconds ==
    threshold) is NOT slow either, matching `suite_timing_line`'s strictly-`>`
    rule so a suite sitting right at the limit never nags. Never raises.
    """
    return test_seconds is not None and test_seconds > threshold


def speed_story_flag_path(cfg: ProductConfig) -> pathlib.Path:
    """Per-product ADVISORY speed-story flag: `<work_root>/SPEED_STORY_NEEDED.md`.

    A DIFFERENT file from `hotfix_flag_path` -- the two have distinct lifecycles
    (hotfix = blocking release defect; speed = advisory throughput signal) and
    must never collide.
    """
    return pathlib.Path(cfg.work_root) / "SPEED_STORY_NEEDED.md"


def write_speed_story_flag(cfg: ProductConfig, sha: str, seconds: float,
                           threshold: float) -> None:
    """Raise the ADVISORY speed-story flag after a SLOW post-release suite.

    Overwrites any existing flag (newest measurement wins -- no append pile-up)
    and embeds the pushed `sha`, the measured suite wall-time, and the threshold
    it exceeded, so the next PM has the throughput evidence. UNLIKE
    `HOTFIX_NEEDED.md`, this is NON-blocking: it merely suggests a speed /
    throughput increment; it never forces the iteration's feature and is always
    subordinate to a present hotfix flag. Auto-clears on the next genuine fast
    ship. Never raises for a normal writable work_root.
    """
    path = speed_story_flag_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# SPEED STORY NEEDED -- advisory (NON-blocking)\n\n"
        f"- Pushed sha: {sha}\n"
        f"- Fresh-clone suite wall-time: {seconds:.2f}s\n"
        f"- Threshold (SUITE_SLOW_SECONDS): {threshold:.2f}s\n\n"
        "This is an ADVISORY throughput signal, NOT a release defect. It is "
        "NON-blocking and always subordinate to `HOTFIX_NEEDED.md` -- if a "
        "hotfix flag is present, that wins. Prefer a speed / throughput "
        "increment (split a slow suite, parallelize, or trim) when no clearly-"
        "higher-value feature is warranted. You need NOT clear this manually; "
        "it auto-clears on the next genuine fast ship.\n")


def clear_speed_story_flag(cfg: ProductConfig) -> None:
    """Remove the advisory speed-story flag if present; silent no-op when absent."""
    speed_story_flag_path(cfg).unlink(missing_ok=True)


def _write_postrelease_artifact(artifact: pathlib.Path, expected_sha: str,
                                result: "PostReleaseResult") -> None:
    """Write the per-iteration `postrelease.md` sentinel artifact.

    The LAST non-empty line is EXACTLY `result.sentinel`, mirroring the
    `VERDICT:`/`RESULT:`/`ACTION:` sentinel-line contract so the verdict is
    greppable and machine-readable. The body carries the pushed sha, the
    fresh-clone suite wall-time (`suite_seconds`, `n/a` when the test command
    did not run), and the verdict detail for a human reading the artifact.
    """
    secs = ("n/a" if result.test_seconds is None
            else f"{result.test_seconds:.2f}")
    artifact.write_text(
        f"# Post-release fresh-clone verification -- pushed sha {expected_sha}\n\n"
        f"- skipped_infra: {result.skipped_infra}\n"
        f"- suite_seconds: {secs}\n"
        f"- detail: {result.detail}\n\n"
        f"{result.sentinel}\n")


def postrelease_step(cfg: ProductConfig, iteration: int,
                     expected_sha: str) -> "PostReleaseResult":
    """Re-verify a just-pushed commit from a throwaway fresh clone.

    Calls `verify_fresh_clone` / the flag helpers by their BARE module names at
    call time so `monkeypatch.setattr(foundry, "<name>", ...)` bites. Writes the
    `POSTRELEASE:` sentinel artifact on every enabled path and applies the
    hotfix-flag lifecycle:

      * genuine HEALTHY (healthy and not skipped_infra) -> clear the flag
      * BROKEN (not healthy)                            -> raise the flag
      * infra-skipped HEALTHY / disabled / verify error -> leave the flag as-is

    NEVER propagates a `verify_fresh_clone` exception: the commit is already
    pushed, so a verification error is treated as infra (HEALTHY + skipped) and
    must never crash the loop or raise a false hotfix.
    """
    it_dir = cfg.state / f"iter-{iteration:02d}"
    it_dir.mkdir(parents=True, exist_ok=True)
    artifact = it_dir / "postrelease.md"

    if not cfg.postrelease_enabled:
        # A no-op skip: don't clone, don't touch the flag, still emit a sentinel.
        result = PostReleaseResult(
            True, True,
            "post-release verification disabled (cfg.postrelease_enabled is "
            "False); skipped without touching the hotfix flag")
        _write_postrelease_artifact(artifact, expected_sha, result)
        return result

    clone_dir = it_dir / "postrelease_clone"  # throwaway; verify cleans it up
    try:
        result = verify_fresh_clone(cfg, expected_sha, clone_dir)
    except Exception as exc:  # a verify error must never crash a shipped iter
        result = PostReleaseResult(
            True, True,
            f"post-release verification errored, treated as infra: {exc!r}")

    if not result.healthy:
        write_hotfix_flag(cfg, expected_sha, result.detail)
    elif not result.skipped_infra:
        clear_hotfix_flag(cfg)
    # infra-skipped HEALTHY: leave any pre-existing flag intact -- an unverified
    # skip must neither clear a real hotfix nor raise a false one.

    # Record the per-ship deployable-suite wall-time (item 7, bite 1) ONLY when
    # the fresh-clone test command actually ran (test_seconds is set). An
    # infra-skip / disabled / errored path has no comparable number, so it emits
    # no timing line. SUITE_SLOW_SECONDS is read as a module global at call time
    # so a monkeypatched threshold bites; `log` best-effort mirrors it to
    # events.jsonl too.
    if result.test_seconds is not None:
        log(cfg, suite_timing_line(result.test_seconds, SUITE_SLOW_SECONDS))
        # item 7, bite 2: apply the ADVISORY speed-story flag lifecycle keyed on
        # the MEASURED wall-time vs the threshold, INDEPENDENT of `healthy` (a
        # slow suite that also failed is still slow). SLOW -> raise the flag;
        # not-slow -> clear it; the guard being False (test_seconds is None)
        # leaves it untouched -- an unverified skip has no comparable number.
        # Wrapped so a flag I/O error is SWALLOWED and never changes the returned
        # result/sentinel or crashes the shipped iter: the advisory is off the
        # control path and the commit is already pushed. (The hotfix write above
        # stays UN-wrapped by design -- a swallowed hotfix write would hide a
        # real breakage; only this informational advisory is swallow-safe.)
        try:
            if speed_story_needed(result.test_seconds, SUITE_SLOW_SECONDS):
                write_speed_story_flag(
                    cfg, expected_sha, result.test_seconds, SUITE_SLOW_SECONDS)
            else:
                clear_speed_story_flag(cfg)
        except Exception:  # advisory I/O must never affect the release verdict
            pass

    _write_postrelease_artifact(artifact, expected_sha, result)
    return result


# --------------------------------------------------------------------------- #
# Read-only company-health probe (roadmap item 12 -- `foundry status`).
#
# The VISION's single job is to run indefinitely "without babysitting each
# step". Iteration by iteration the foundry grew a rich set of durable health
# signals -- the `POSTRELEASE: HEALTHY|BROKEN` sentinel + the blocking
# `HOTFIX_NEEDED.md` flag (iter 03), the `prd.json` progress line (iters 11/12),
# the advisory `SPEED_STORY_NEEDED.md` flag (iters 13/14) -- but NO single
# command answers "is my company healthy right now?". Today an operator must
# hand-inspect the newest `state/iter-NN/postrelease.md`, `ls` for two flag
# files, and run `foundry prd`: exactly the scattered babysitting the VISION
# says to eliminate. `foundry status` is the read-only capstone that aggregates
# those already-shipped primitives into ONE deterministic snapshot + a
# scriptable 0/1/2 exit code. Same purely-additive, off-control-path,
# on-demand-CLI class as doctor/learnings/agents/lint-spec/prd/gate-scope: the
# pipeline NEVER calls it, it introduces no sentinel/config/artifact, and it
# writes NOTHING -- so the gate and the running loop are entirely unchanged.
# `parse_postrelease_verdict` is the pure verdict parser; `StatusSummary` +
# `summarize_status` are the pure decision core; `status_cli` is the thin
# operator seam that gathers the live signals through the EXISTING module-level
# functions (so a `monkeypatch.setattr(foundry, ...)` bites) and prints them.
# --------------------------------------------------------------------------- #
def parse_postrelease_verdict(text: str) -> str | None:
    """Extract the `POSTRELEASE:` verdict from a `postrelease.md` body (pure).

    The verdict is the token on the LAST non-empty line when that line reads
    `POSTRELEASE: HEALTHY` or `POSTRELEASE: BROKEN` -- mirroring the sentinel
    contract `_write_postrelease_artifact` writes (the verdict is always the
    artifact's final non-empty line). Trailing blank lines are ignored (the last
    NON-empty line wins) and leading/trailing whitespace on the sentinel line
    AND around the token is tolerated (`  POSTRELEASE:  BROKEN  ` -> `"BROKEN"`).

    Returns `None` -- never raising for ANY string -- when there is no verdict:
    empty / whitespace-only text; no `POSTRELEASE:` line; an unrecognized token
    (`POSTRELEASE: MAYBE`); or a `POSTRELEASE:` line that is NOT the last
    non-empty line (prose follows it -- a still-in-progress or malformed
    artifact). Requiring the sentinel to be LAST matches how the artifact is
    emitted, so stray earlier mentions of the word can never be misread.
    """
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return None
    last = lines[-1]
    prefix = "POSTRELEASE:"
    if not last.startswith(prefix):
        return None
    token = last[len(prefix):].strip()
    return token if token in ("HEALTHY", "BROKEN") else None


@dataclasses.dataclass(frozen=True)
class StatusSummary:
    """A one-shot company-health snapshot for one product (item 12).

    Frozen so a computed snapshot can't be mutated after the fact (value
    equality for free, matching the other pure cores). The three properties are
    pure derivations of the stored fields, so the whole verdict -- including the
    scriptable exit code -- follows deterministically from what was gathered.

    Fields:
      * `product`/`repo`/`branch` -- identity, echoed into `render()`.
      * `latest_iter` -- the highest shipped iteration number (`<= 0` == nothing
        shipped yet).
      * `postrelease` -- the latest ship's verdict: `"HEALTHY"` / `"BROKEN"` /
        `None` (no `postrelease.md`, i.e. a no-ship / in-progress iteration).
      * `hotfix` -- whether the blocking `HOTFIX_NEEDED.md` flag is raised.
      * `speed_story` -- whether the ADVISORY `SPEED_STORY_NEEDED.md` flag is
        raised (never affects `attention`/`exit_code` -- it is non-blocking).
      * `prd_line` -- the `dispatch_progress_line` text, or `None` when there is
        no `prd.json`.
    """
    product: str
    repo: str
    branch: str
    latest_iter: int
    postrelease: str | None
    hotfix: bool
    speed_story: bool
    prd_line: str | None

    @property
    def attention(self) -> bool:
        """True iff something needs an operator: a raised hotfix flag OR a
        BROKEN latest post-release. The advisory `speed_story` NEVER counts --
        a slow suite is throughput, not a release defect (mirrors the iter-14
        non-blocking contract)."""
        return bool(self.hotfix) or self.postrelease == "BROKEN"

    @property
    def ok(self) -> bool:
        """The healthy mirror of `attention` -- True iff nothing needs attention."""
        return not self.attention

    @property
    def exit_code(self) -> int:
        """Scriptable verdict, attention-first: `1` when `attention` (even with
        nothing shipped yet -- a raised flag matters more than the iter count),
        else `2` when nothing has shipped (`latest_iter <= 0`), else `0`."""
        if self.attention:
            return 1
        if self.latest_iter <= 0:
            return 2
        return 0

    @property
    def verdict(self) -> str:
        """The single human token for the current `exit_code` -- `"OK"` (0) /
        `"ATTENTION"` (1) / `"no iterations yet"` (2). ONE source of truth for
        both `render()`'s last line and the JSON `verdict` key (Behavior 2), so
        the text and the machine payload can never drift."""
        return {0: "OK", 1: "ATTENTION", 2: "no iterations yet"}[self.exit_code]

    def render(self) -> str:
        """A deterministic multi-line report carrying every gathered signal.

        Contains, as substrings (the CLI's black-box contract): the product
        name; `branch {branch}`; `latest iteration: N` (or `... none` when
        nothing shipped); `post-release: HEALTHY|BROKEN|unknown` (`unknown` when
        no verdict); `hotfix flag: RAISED|clear`; `speed-story flag:
        RAISED|clear`; the `prd_line` verbatim or `no prd.json`; and a final
        verdict token that MATCHES `exit_code` -- `OK` (0) / `ATTENTION` (1) /
        `no iterations yet` (2)."""
        iter_line = (f"latest iteration: {self.latest_iter}"
                     if self.latest_iter > 0 else "latest iteration: none")
        pr = self.postrelease if self.postrelease is not None else "unknown"
        prd = self.prd_line if self.prd_line is not None else "no prd.json"
        verdict = self.verdict
        return "\n".join([
            f"foundry status -- {self.product}",
            f"  repo: {self.repo}  branch {self.branch}",
            f"  {iter_line}",
            f"  post-release: {pr}",
            f"  hotfix flag: {'RAISED' if self.hotfix else 'clear'}",
            f"  speed-story flag: {'RAISED' if self.speed_story else 'clear'}",
            f"  prd: {prd}",
            f"verdict: {verdict}",
        ])

    def to_dict(self) -> dict:
        """A pure, JSON-safe health snapshot for machine consumers -- dashboards
        / cron alerts / the reporter (roadmap item 10's "machine-readable status").

        Returns EXACTLY 12 keys in a fixed order: the eight STORED fields
        verbatim (`product`/`repo`/`branch`/`latest_iter`/`postrelease`/`hotfix`/
        `speed_story`/`prd_line`) followed by the four DERIVED values, each
        REUSING the frozen properties -- `attention`/`ok`/`exit_code`/`verdict`
        -- so the JSON payload can never disagree with what `render()` prints or
        the exit code returns. Every value is JSON-native (str / int / bool /
        None), so `json.dumps(...)` never raises and the dict round-trips
        through `json.loads(json.dumps(...))`. Pure: touches no filesystem, only
        the already-gathered snapshot."""
        return {
            "product": self.product,
            "repo": self.repo,
            "branch": self.branch,
            "latest_iter": self.latest_iter,
            "postrelease": self.postrelease,
            "hotfix": self.hotfix,
            "speed_story": self.speed_story,
            "prd_line": self.prd_line,
            "attention": self.attention,
            "ok": self.ok,
            "exit_code": self.exit_code,
            "verdict": self.verdict,
        }


def summarize_status(*, product: str, repo: str, branch: str, latest_iter: int,
                     postrelease: str | None, hotfix: bool, speed_story: bool,
                     prd_line: str | None) -> StatusSummary:
    """Pure keyword-only constructor for a `StatusSummary` (item 12).

    A thin, total wrapper that just packs the gathered signals into the frozen
    snapshot -- keyword-only so a caller can never transpose the eight fields by
    position, and it never raises. Kept separate from `status_cli` so the
    decision core stays a pure function the tester can drive without any
    filesystem (Behavior 7)."""
    return StatusSummary(
        product=product, repo=repo, branch=branch, latest_iter=latest_iter,
        postrelease=postrelease, hotfix=hotfix, speed_story=speed_story,
        prd_line=prd_line)


def gather_status(cfg: ProductConfig) -> StatusSummary:
    """Gather one product's live health signals into a `StatusSummary` (item 30).

    Extracted verbatim from the iter-16 `status_cli` gathering so BOTH the
    single-product `foundry status` and the new company-wide roll-up
    (`company_status_cli`) share ONE gathering seam; a monkeypatch on this one
    function then reshapes every consumer at once. Output-preserving: the
    produced snapshot is byte-identical to what iter-16 built, so `foundry
    status` is unchanged.

    Reads every signal through the EXISTING module-level seams -- each called by
    BARE name so a `monkeypatch.setattr(foundry, ...)` in a test bites:
      * `latest_iter` = `next_iteration(cfg) - 1` (the highest shipped iter);
      * the latest iter's `state/iter-NN/postrelease.md` (2-digit zero-pad), read
        GUARDED through `parse_postrelease_verdict` (absent file / read error ->
        `None`, so a no-ship iteration reads as `unknown`, never an error);
      * the two flag files via `hotfix_flag_path(cfg).exists()` /
        `speed_story_flag_path(cfg).exists()`;
      * the prd progress via `dispatch_progress_line(cfg)`.
    Returns a frozen `StatusSummary`; writes NOTHING to disk (read-only)."""
    latest_iter = next_iteration(cfg) - 1
    postrelease: str | None = None
    if latest_iter > 0:
        artifact = cfg.state / f"iter-{latest_iter:02d}" / "postrelease.md"
        try:
            if artifact.exists():
                postrelease = parse_postrelease_verdict(artifact.read_text())
        except OSError:
            # A read error on the artifact must degrade to "unknown", never
            # crash the probe -- no-news-is-good-news, only BROKEN/hotfix alarm.
            postrelease = None
    return summarize_status(
        product=cfg.name, repo=cfg.repo, branch=cfg.branch,
        latest_iter=latest_iter, postrelease=postrelease,
        hotfix=hotfix_flag_path(cfg).exists(),
        speed_story=speed_story_flag_path(cfg).exists(),
        prd_line=dispatch_progress_line(cfg))


def status_cli(cfg: ProductConfig, as_json: bool = False) -> int:
    """On-demand CLI: print a company-health snapshot + a 0/1/2 exit code.

    With `as_json=True` the entire stdout is ONE `json.dumps(summary.
    to_dict(), indent=2)` document (the stable machine contract for
    dashboards/alerts); the default `as_json=False` is byte-for-byte the
    iter-16 human `render()` text. Either way the RETURN value is the same
    `summary.exit_code`, and nothing is written to disk.

    Gathers every signal through the `gather_status(cfg)` seam (which reads the
    live signals via the EXISTING module-level functions, called by BARE name so
    a `monkeypatch.setattr(foundry, ...)` bites) then prints the pure
    `StatusSummary` core. Prints `summary.render()` (or its `to_dict()` JSON) and
    returns `summary.exit_code`. Writes NOTHING to disk (read-only) -- a thin
    printer over the pure core that adds no decision logic of its own, so the
    printed verdict always equals the `StatusSummary` fields."""
    summary = gather_status(cfg)
    # `--json` emits the pure snapshot as a single JSON document (stdout-only, no
    # decision logic added); the default stays the exact iter-16 human report.
    print(json.dumps(summary.to_dict(), indent=2) if as_json else summary.render())
    return summary.exit_code


# --------------------------------------------------------------------------- #
# Company-wide health roll-up (`company-status`) -- roadmap iter 30.
#
# The dispatcher runs a whole COMPANY of product teams (`foundry.config.json`
# `work_items`, each -> a product config) round-robin at concurrency 1, but
# `foundry status` (iter 16) reports on exactly ONE product. An operator running
# N teams had to run `status --config <cfg>` once per product and mentally roll
# up the verdicts -- exactly the scattered babysitting the VISION says to
# eliminate. `company_status_cli` closes iter-16's own half-delivered "company
# health" promise by COMPOSING the already-frozen per-product `gather_status`
# core across every ENABLED dispatch work item into ONE company verdict + a
# scriptable 0 healthy / 1 needs-attention / 2 no-enabled exit code.
#
# Purely additive + OFF the control path: it only reads the dispatch config and
# each product's live signals and prints; the pipeline / dispatcher NEVER call
# it and it writes NOTHING. Same "compose existing frozen cores, add no new I/O
# seam" pattern the read-only probe family (iters 16-28) is built on, applied to
# the multi-product axis the dispatcher actually operates on.
# --------------------------------------------------------------------------- #
def parse_dispatch_work_items(
        dispatch: dict) -> tuple[tuple[str, str, bool], ...]:
    """Extract `(name, config, enabled)` triples from a DISPATCH config (pure).

    Mirrors how `dispatcher.py` reads `foundry.config.json`: each `work_items`
    entry is an object with a `name`, a `config` path, and an optional `enabled`
    flag. Returns one triple per dict entry IN FILE ORDER -- `name`/`config`
    default to `""` when the key is absent and `enabled` defaults to `True`
    (matching the dispatcher's `w.get("enabled", True)`), coerced to `bool`.

    Total + never-raises for ANY dict input (Behavior 2): a missing / `None` /
    non-list `work_items` yields the empty tuple, and any non-dict entry in the
    list is SKIPPED (a stray string / null in the array can't crash the roll-up).
    Touches no filesystem -- a pure parse of the already-loaded dict."""
    items = dispatch.get("work_items")
    if not isinstance(items, list):
        return ()
    out: list[tuple[str, str, bool]] = []
    for entry in items:
        if not isinstance(entry, dict):
            continue  # skip a stray scalar / null in the work_items array
        out.append((entry.get("name", ""), entry.get("config", ""),
                    bool(entry.get("enabled", True))))
    return tuple(out)


@dataclasses.dataclass(frozen=True)
class CompanyStatus:
    """A one-shot COMPANY-wide health roll-up across a dispatch config (item 30).

    Frozen so a computed roll-up can't be mutated after the fact (value equality
    for free, matching the other pure cores). Every derived value is a pure
    property over the stored fields, so the whole verdict -- including the
    scriptable exit code -- follows deterministically from what was gathered, and
    the JSON payload / render text can never disagree with the exit code.

    Fields:
      * `dispatch_path` -- the dispatch config path, echoed into `render()`.
      * `products` -- the per-product `StatusSummary` snapshots that were
        successfully gathered, IN dispatch-file order (an enabled product that
        failed to load/gather is NOT here -- it lands in `errors`).
      * `disabled` -- names of work items with `enabled=False` (never loaded).
      * `errors` -- `(product, message)` 2-tuples for enabled items that raised
        while loading/gathering (the sole caller guarantees each is a 2-tuple).
    """
    dispatch_path: str
    products: tuple[StatusSummary, ...]
    disabled: tuple[str, ...]
    errors: tuple[tuple[str, str], ...]

    @property
    def n_products(self) -> int:
        """Count of products successfully ROLLED UP (an errored enabled product
        is NOT counted here -- it is in `errors`)."""
        return len(self.products)

    @property
    def n_ok(self) -> int:
        """Count of gathered products whose own `StatusSummary` is `ok`."""
        return sum(1 for p in self.products if p.ok)

    @property
    def n_attention(self) -> int:
        """Count of gathered products that need attention (a raised hotfix flag
        OR a BROKEN latest post-release)."""
        return sum(1 for p in self.products if p.attention)

    @property
    def n_disabled(self) -> int:
        return len(self.disabled)

    @property
    def n_errors(self) -> int:
        return len(self.errors)

    @property
    def attention(self) -> bool:
        """True iff SOMETHING needs an operator: ANY gathered product needs
        attention, OR any enabled product failed to load/gather (a non-empty
        `errors`). Disabled items are deliberate and never raise attention."""
        return any(p.attention for p in self.products) or bool(self.errors)

    @property
    def ok(self) -> bool:
        """The healthy mirror of `attention` (matches the per-product core)."""
        return not self.attention

    @property
    def exit_code(self) -> int:
        """Scriptable verdict, attention-first: `1` when `attention`, else `2`
        when NO products were gathered (every item disabled or `work_items`
        empty -- reachable only with `attention` False, so no errors either),
        else `0` healthy."""
        if self.attention:
            return 1
        if self.n_products == 0:
            return 2
        return 0

    @property
    def verdict(self) -> str:
        """The single human token for the current `exit_code` -- `"OK"` (0) /
        `"ATTENTION"` (1) / `"no enabled products"` (2). ONE source of truth for
        both `render()`'s last line and the JSON `verdict` key, so the text and
        the machine payload can never drift from the exit code."""
        return {0: "OK", 1: "ATTENTION", 2: "no enabled products"}[self.exit_code]

    def render(self) -> str:
        """A deterministic multi-line company report (the CLI's black-box contract).

        Contains, as substrings: the `dispatch_path`; a counts line reporting the
        number of GATHERED products, the ok count, the attention count, the
        disabled count, and the error count; ONE line per gathered product with
        its name AND its `StatusSummary.verdict` token (plus `hotfix` iff that
        product's hotfix flag is raised and/or `BROKEN` iff its post-release is
        BROKEN, for an attention product); one line per disabled item with its
        name and `disabled`; one line per error with its name, `ERROR`, and the
        message; and a final `verdict:` line whose token EQUALS `verdict`."""
        lines = [
            "foundry company-status",
            f"  dispatch config: {self.dispatch_path}",
            f"  products: {self.n_products} gathered "
            f"({self.n_ok} ok, {self.n_attention} attention), "
            f"{self.n_disabled} disabled, {self.n_errors} error(s)",
        ]
        for p in self.products:
            line = f"  - {p.product}: {p.verdict}"
            if p.attention:
                marks = []
                if p.hotfix:
                    marks.append("hotfix")
                if p.postrelease == "BROKEN":
                    marks.append("BROKEN")
                if marks:
                    line += f" [{', '.join(marks)}]"
            lines.append(line)
        for name in self.disabled:
            lines.append(f"  - {name}: disabled")
        for name, message in self.errors:
            lines.append(f"  - {name}: ERROR {message}")
        lines.append(f"verdict: {self.verdict}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """A pure, JSON-safe company roll-up for machine consumers -- a dashboard
        / cron alert / the reporter. Every derived value REUSES the frozen
        properties, so the payload can never disagree with `render()` or the exit
        code, and every value is JSON-native, so it round-trips through
        `json.loads(json.dumps(...))`. Pure: touches no filesystem."""
        return {
            "dispatch_config": self.dispatch_path,
            "products": [p.to_dict() for p in self.products],
            "disabled": list(self.disabled),
            "errors": [{"product": name, "message": message}
                       for name, message in self.errors],
            "n_products": self.n_products,
            "n_ok": self.n_ok,
            "n_attention": self.n_attention,
            "n_disabled": self.n_disabled,
            "n_errors": self.n_errors,
            "attention": self.attention,
            "ok": self.ok,
            "exit_code": self.exit_code,
            "verdict": self.verdict,
        }


def summarize_company(*, dispatch_path: str,
                      products: tuple[StatusSummary, ...],
                      disabled: tuple[str, ...],
                      errors: tuple[tuple[str, str], ...]) -> CompanyStatus:
    """Pure keyword-only constructor for a `CompanyStatus` (Behaviors 4-7).

    A thin, total wrapper that packs the gathered signals into the frozen
    roll-up -- keyword-only so a caller can never transpose the fields by
    position, and it never raises for well-formed inputs (each `errors` entry is
    a `(product, message)` 2-tuple, which the sole caller `company_status_cli`
    guarantees; documenting the precondition keeps the "never raises" contract
    airtight). Kept separate from `company_status_cli` so the decision core stays
    a pure function the tester can drive without any filesystem."""
    return CompanyStatus(
        dispatch_path=dispatch_path,
        products=tuple(products),
        disabled=tuple(disabled),
        errors=tuple((name, message) for name, message in errors))


def company_status_cli(dispatch_path: str, as_json: bool = False) -> int:
    """On-demand CLI: roll every ENABLED team's health into ONE company verdict.

    Reads the DISPATCH config at `dispatch_path` (`foundry.config.json`, NOT a
    product config), then for each ENABLED work item substitutes a `{FOUNDRY}`
    token in its config path to the foundry root and loads + gathers that
    product's health via the `load_config` / `gather_status` seams (both called
    by BARE name so a `monkeypatch.setattr(foundry, ...)` bites). A DISABLED item
    is recorded in `disabled` and never loaded.

    Resilient (Behaviors 12-13): if reading/parsing the dispatch config fails
    (missing / not JSON / not an object) it prints a report recording ONE
    synthetic error and returns exit 1; if a single work item's `load_config` or
    `gather_status` raises, that item is recorded in `errors` and the roll-up
    CONTINUES gathering the rest (company exit 1). No exception ever propagates.

    With `as_json=True` stdout is exactly ONE `json.dumps(to_dict(), indent=2)`
    document; either way the RETURN value is the same `CompanyStatus.exit_code`
    (0 healthy / 1 needs-attention / 2 no-enabled-products). Writes NOTHING to
    disk -- a read-only report; with `load_config` monkeypatched the filesystem
    is untouched."""
    try:
        dispatch = json.loads(
            pathlib.Path(dispatch_path).expanduser().read_text())
        if not isinstance(dispatch, dict):
            raise ValueError("dispatch config is not a JSON object")
    except Exception as exc:
        # A missing / malformed dispatch config is a real operator problem, not a
        # crash: surface it as ONE synthetic error (attention -> exit 1).
        company = summarize_company(
            dispatch_path=dispatch_path, products=(), disabled=(),
            errors=((dispatch_path, str(exc)),))
        print(json.dumps(company.to_dict(), indent=2) if as_json
              else company.render())
        return company.exit_code

    products: list[StatusSummary] = []
    disabled: list[str] = []
    errors: list[tuple[str, str]] = []
    for name, config, enabled in parse_dispatch_work_items(dispatch):
        if not enabled:
            disabled.append(name)      # deliberate; never loaded
            continue
        try:
            # {FOUNDRY} -> foundry root BEFORE load_config, exactly as the
            # dispatcher resolves each work item's config path.
            cfg = load_config(config.replace("{FOUNDRY}", str(FOUNDRY)))
            products.append(gather_status(cfg))
        except Exception as exc:
            # One bad team never sinks the whole roll-up -- record + continue.
            errors.append((name, str(exc)))
    company = summarize_company(
        dispatch_path=dispatch_path, products=tuple(products),
        disabled=tuple(disabled), errors=tuple(errors))
    print(json.dumps(company.to_dict(), indent=2) if as_json else company.render())
    return company.exit_code


# --------------------------------------------------------------------------- #
# Multi-iteration ship ledger (`history`) -- item 13
#
# The read-only, offline TREND view that complements `status`: `status` answers
# "is my company healthy RIGHT NOW?" from the latest snapshot; `history` answers
# "what has my company actually DONE over its run?" -- a compact ledger of every
# iteration's ship ACTION + POSTRELEASE outcome, built with the same proven
# pattern (pure decision functions + a thin CLI over existing seams) and REUSING
# `parse_postrelease_verdict` verbatim. Purely additive, off the control path:
# the pipeline/dispatcher NEVER call it, so the gate and the running loop are
# untouched. It writes NOTHING.
# --------------------------------------------------------------------------- #
def parse_ship_action(text: str) -> str | None:
    """Extract the ship ACTION from a `final.md` body (pure, total).

    The action is the FIRST token on the LAST non-empty line when that line reads
    `ACTION: PUSHED <sha>` (-> `"PUSHED"`, the trailing sha ignored) or
    `ACTION: REVERTED` (-> `"REVERTED"`) -- mirroring `parse_postrelease_verdict`
    and the sentinel the Final Reviewer writes as the artifact's final line.
    Trailing blank lines are ignored (the last NON-empty line wins) and
    leading/trailing whitespace on the sentinel line is tolerated
    (`  ACTION:  REVERTED  ` -> `"REVERTED"`).

    Returns `None` -- never raising for ANY string -- when there is no action:
    empty / whitespace-only text; no `ACTION:` line; an unrecognized token
    (`ACTION: MAYBE`); or an `ACTION:` line that is NOT the last non-empty line
    (prose follows it -- an in-progress or malformed artifact). Requiring the
    sentinel to be LAST matches how the artifact is emitted, so a stray earlier
    mention can never be misread.
    """
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return None
    last = lines[-1]
    prefix = "ACTION:"
    if not last.startswith(prefix):
        return None
    # `.split()` collapses any run of whitespace after `ACTION:`, so the first
    # element is the action token regardless of the spacing around it; a bare
    # `ACTION:` with nothing after yields an empty list -> `None`.
    tokens = last[len(prefix):].split()
    if not tokens:
        return None
    action = tokens[0]
    return action if action in ("PUSHED", "REVERTED") else None


def iteration_numbers(names) -> list[int]:
    """Parse an iterable of dir names into sorted-ascending UNIQUE iteration ints.

    Keeps only names of the EXACT form `iter-<digits>` (2-digit zero-pad in
    practice, but any run of decimal digits is accepted), maps each to its int,
    de-dupes, and returns them sorted numerically -- so `iter-10` sorts AFTER
    `iter-03`, not lexically before it. Every other name (`foo`, `iter-`,
    `iter-xx`) is ignored. Uses `str.isdecimal()` (which is exactly the set
    `int()` accepts for a bare digit run) so the function is TOTAL: it never
    raises for any input, and an empty / no-match iterable returns `[]`.
    """
    prefix = "iter-"
    seen: set[int] = set()
    for name in names:
        text = str(name)
        if not text.startswith(prefix):
            continue
        digits = text[len(prefix):]
        # `isdecimal()` is False for "", "iter-xx", "iter-+3" etc. and True only
        # for a pure decimal-digit run, which `int()` then always parses.
        if digits.isdecimal():
            seen.add(int(digits))
    return sorted(seen)


@dataclasses.dataclass(frozen=True)
class IterationRecord:
    """One iteration's ship outcome (item 13).

    Frozen so a computed record can't be mutated after the fact (value equality
    for free, matching the other pure cores). Fields:
      * `iteration` -- the iteration number (e.g. `3` for `iter-03`).
      * `action` -- the ship action: `"PUSHED"` / `"REVERTED"` / `None`
        (no `final.md` / no recognizable `ACTION:` sentinel).
      * `postrelease` -- the ship's post-release verdict: `"HEALTHY"` /
        `"BROKEN"` / `None` (no `postrelease.md`, i.e. a no-ship / older iter).
    """
    iteration: int
    action: str | None
    postrelease: str | None

    @property
    def label(self) -> str:
        """A compact ASCII outcome word for the ledger row.

        A REVERT is a REVERT regardless of any stray post-release verdict, so it
        is tested FIRST; a PUSH is then qualified by its post-release health
        (`BROKEN` is loud so it stays upper-case)."""
        if self.action == "REVERTED":
            return "reverted"
        if self.action == "PUSHED":
            if self.postrelease == "BROKEN":
                return "shipped/BROKEN"
            if self.postrelease == "HEALTHY":
                return "shipped/healthy"
            return "shipped"
        return "no-ship"

    def to_dict(self) -> dict:
        """A pure, JSON-safe serialization of one ledger row for machine
        consumers (roadmap item 10's "machine-readable status for dashboards /
        the reporter").

        Returns EXACTLY 4 keys in a fixed order: the three STORED fields verbatim
        (`iteration`/`action`/`postrelease`) followed by the DERIVED `label`,
        REUSING the frozen `label` property so the JSON row can never disagree
        with what `render()` prints. Every value is JSON-native (int / str /
        None), so `json.dumps(...)` never raises and the dict round-trips through
        `json.loads(json.dumps(...))`. Pure: touches no filesystem, only the
        already-computed record."""
        return {
            "iteration": self.iteration,
            "action": self.action,
            "postrelease": self.postrelease,
            "label": self.label,
        }


@dataclasses.dataclass(frozen=True)
class HistorySummary:
    """A multi-iteration ship ledger for one product (item 13).

    Frozen (value equality, no post-hoc mutation). `records` is stored as a
    `tuple` in the order to render. The four counts and `exit_code` are pure
    derivations of `records`. `exit_code` is `2` iff there is NOTHING to report
    (`total == 0`) else `0`: history is INFORMATIONAL -- a past-then-fixed
    `BROKEN` never gates (that's `foundry status`'s current-attention job), so a
    healthy-looking history and a history-with-old-breakage both exit `0`.
    """
    product: str
    records: tuple["IterationRecord", ...]

    @property
    def total(self) -> int:
        return len(self.records)

    @property
    def shipped(self) -> int:
        return sum(1 for r in self.records if r.action == "PUSHED")

    @property
    def reverted(self) -> int:
        return sum(1 for r in self.records if r.action == "REVERTED")

    @property
    def broken(self) -> int:
        return sum(1 for r in self.records if r.postrelease == "BROKEN")

    @property
    def exit_code(self) -> int:
        """`2` iff nothing to report else `0` -- history never gates on a
        past-then-fixed breakage (current attention is `foundry status`'s job)."""
        return 2 if self.total == 0 else 0

    def render(self) -> str:
        """A deterministic multi-line ledger carrying every per-iter outcome.

        Contains, as substrings (the CLI's black-box contract): the `product`
        name; for EACH record (in stored order) a row with `iter-NN` (2-digit
        zero-pad), the record's `label`, and `post-release: HEALTHY|BROKEN|
        unknown` (`unknown` when there is no verdict); and a final rollup line
        `{total} iterations: {shipped} shipped, {reverted} reverted, {broken}
        broken`. When there are no records it also carries `no iterations yet`
        (and the rollup naturally shows `0 iterations`)."""
        header = f"foundry history -- {self.product}"
        rollup = (f"{self.total} iterations: {self.shipped} shipped, "
                  f"{self.reverted} reverted, {self.broken} broken")
        if not self.records:
            return "\n".join([header, "  no iterations yet", rollup])
        rows = []
        for r in self.records:
            pr = r.postrelease if r.postrelease is not None else "unknown"
            rows.append(f"  iter-{r.iteration:02d}  {r.label}  "
                        f"post-release: {pr}")
        return "\n".join([header, *rows, rollup])

    def to_dict(self) -> dict:
        """A pure, JSON-safe serialization of the whole ledger for machine
        consumers (roadmap item 10's "machine-readable status for dashboards /
        the reporter"), mirroring iter-19's `StatusSummary.to_dict()`.

        Returns EXACTLY 7 keys in a fixed order: `product` verbatim, the four
        counts + `exit_code` each REUSING the frozen properties (`total`/
        `shipped`/`reverted`/`broken`/`exit_code`) so the payload can never
        disagree with `render()`/the returned exit code, then `records` as a JSON
        array of each record's `to_dict()` in the SAME order as `self.records`.
        Every value is JSON-native (str / int / list of dicts), so
        `json.dumps(...)` never raises and the dict round-trips through
        `json.loads(json.dumps(...))`. Pure: touches no filesystem, only the
        already-gathered records."""
        return {
            "product": self.product,
            "total": self.total,
            "shipped": self.shipped,
            "reverted": self.reverted,
            "broken": self.broken,
            "exit_code": self.exit_code,
            "records": [r.to_dict() for r in self.records],
        }


def summarize_history(*, product: str, records) -> HistorySummary:
    """Pure keyword-only constructor for a `HistorySummary` (item 13).

    A thin, total wrapper that packs the product name + an iterable of
    `IterationRecord` into the frozen ledger, materializing `records` as a
    `tuple` (so the frozen dataclass stays hashable/immutable and a caller's
    list can never be mutated out from under it). Keyword-only so the two fields
    can never be transposed; it never raises. Kept separate from `history_cli`
    so the decision core stays a pure function the tester can drive without any
    filesystem (Behavior 7)."""
    return HistorySummary(product=product, records=tuple(records))


def _read_sentinel(path: pathlib.Path, parser) -> str | None:
    """Read a sentinel artifact through `parser`, degrading to `None` on any
    absent file or read error (never raising).

    Both parsers (`parse_ship_action` / `parse_postrelease_verdict`) are already
    total, so the only failure mode is the filesystem: a missing artifact or an
    `OSError` on read reads as `None` ("unknown"), never crashing the read-only
    probe. `parser` is passed in (rather than hard-wired) so the caller's
    bare-name reference is resolved in the module globals at call time -- a
    `monkeypatch.setattr(foundry, "parse_ship_action", ...)` still bites."""
    try:
        if path.exists():
            return parser(path.read_text())
    except OSError:
        return None
    return None


def gather_history(cfg: ProductConfig, limit: int | None = None) -> HistorySummary:
    """Gather one product's multi-iteration ship LEDGER into a `HistorySummary`.

    Extracted verbatim from the iter-17 `history_cli` gathering (iter 31) so BOTH
    the single-product `foundry history` and the new company-wide roll-up
    (`company_history_cli`) share ONE gathering seam; a monkeypatch on this one
    function then reshapes every consumer at once. Output-preserving: the records
    it builds are byte-identical to what iter 17 built, so `foundry history` is
    unchanged (mirroring iter-30's `gather_status` extraction from `status_cli`).

    Reads every signal through the EXISTING module-level seams -- each called by
    BARE name so a `monkeypatch.setattr(foundry, ...)` in a test bites:
      * lists `cfg.state`'s dir names (guarded -- a missing / unreadable state dir
        yields no names, never an error) and derives the iteration numbers via
        `iteration_numbers`;
      * applies `limit` -- keep the highest-N iterations when `limit` is a
        POSITIVE int, else ALL (a `None` / non-positive `limit` shows the full
        run); the numbers stay ascending so the ledger reads oldest-first;
      * for each iteration reads `state/iter-NN/final.md` through
        `parse_ship_action` and `state/iter-NN/postrelease.md` through
        `parse_postrelease_verdict`, both guarded via `_read_sentinel` to `None`
        on an absent file / read error.
    Returns the pure `summarize_history`/`HistorySummary` core; writes NOTHING to
    disk (read-only). A missing / unreadable `cfg.state` yields an empty ledger
    (`total == 0`), never raising."""
    state = cfg.state
    try:
        names = [p.name for p in state.iterdir()] if state.exists() else []
    except OSError:
        # A read error on the state dir must degrade to "no iterations", never
        # crash the probe (same no-news-is-good-news contract as the artifacts).
        names = []
    numbers = iteration_numbers(names)
    if isinstance(limit, int) and limit > 0:
        # `numbers` is ascending, so the most-recent N are the LAST N; the slice
        # preserves ascending order for the ledger.
        numbers = numbers[-limit:]
    records = [
        IterationRecord(
            iteration=n,
            action=_read_sentinel(state / f"iter-{n:02d}" / "final.md",
                                  parse_ship_action),
            postrelease=_read_sentinel(
                state / f"iter-{n:02d}" / "postrelease.md",
                parse_postrelease_verdict),
        )
        for n in numbers
    ]
    return summarize_history(product=cfg.name, records=records)


def history_cli(cfg: ProductConfig, limit: int | None = None,
                as_json: bool = False) -> int:
    """On-demand CLI: print a multi-iteration ship ledger + a 0/2 exit code.

    With `as_json=True` the entire stdout is ONE `json.dumps(summary.to_dict(),
    indent=2)` document (the stable machine contract for dashboards/reporters,
    mirroring iter-19's `status --json`); the default `as_json=False` is
    byte-for-byte the iter-17 human `render()` text. Either way the RETURN value
    is the same `summary.exit_code`, `--limit` selection is identical, and
    nothing is written to disk.

    Gathers the ledger through the `gather_history(cfg, limit)` seam (iter 31 --
    which reads the on-disk artifacts via the EXISTING module-level functions,
    called by BARE name so a `monkeypatch.setattr(foundry, ...)` bites) then
    prints the pure `HistorySummary` core. Output-preserving: the printed report
    / JSON / exit code are byte-identical to iter 17. Writes NOTHING to disk
    (read-only) -- a thin printer over the pure core that adds no decision logic
    of its own, so the printed rollup always equals the `HistorySummary` fields."""
    summary = gather_history(cfg, limit)
    # `--json` emits the pure ledger as a single JSON document (stdout-only, no
    # decision logic added); the default stays the exact iter-17 human report.
    print(json.dumps(summary.to_dict(), indent=2) if as_json else summary.render())
    return summary.exit_code


# --------------------------------------------------------------------------- #
# Company-wide ship LEDGER roll-up (`company-history`) -- roadmap iter 31.
#
# The TREND-axis complement to iter-30's `company-status`: `company-status`
# answers "is my company healthy NOW?"; `company-history` answers "what has my
# company DONE over its whole run?". The dispatcher runs a whole COMPANY of
# product teams (`foundry.config.json` `work_items`, each -> a product config)
# round-robin at concurrency 1, but `foundry history` (iter 17) reports the ship
# ledger of exactly ONE product. An operator running N teams otherwise runs
# `history --config <cfg>` once per product and mentally sums the ledgers --
# exactly the scattered babysitting the VISION says to eliminate.
#
# Purely additive + OFF the control path: it only reads the dispatch config and
# each product's on-disk ledger artifacts and prints; the pipeline / dispatcher
# NEVER call it and it writes NOTHING. Same "compose existing frozen cores + a
# shared gathering seam, add no new I/O seam" pattern iter 30 endorsed, applied
# to the LEDGER probe -- REUSING the already-shipped, tested
# `parse_dispatch_work_items` (iter 30) and the frozen `HistorySummary` core.
# Company-history is INFORMATIONAL like per-product history: a past `BROKEN`
# inside a team's ledger does NOT gate; only a STRUCTURAL read/parse error
# (unreadable dispatch config, or a team that failed to load/gather) -> exit 1.
# --------------------------------------------------------------------------- #
@dataclasses.dataclass(frozen=True)
class CompanyHistory:
    """A one-shot COMPANY-wide ship-ledger roll-up across a dispatch config (iter 31).

    Frozen so a computed roll-up can't be mutated after the fact (value equality
    for free, matching the other pure cores). Every derived value is a pure
    property over the stored fields, so the whole verdict -- including the
    scriptable exit code -- follows deterministically from what was gathered, and
    the JSON payload / render text can never disagree with the exit code.

    Fields:
      * `dispatch_path` -- the dispatch config path, echoed into `render()`.
      * `products` -- the per-product `HistorySummary` ledgers that were
        successfully gathered, IN dispatch-file order (an enabled product that
        failed to load/gather is NOT here -- it lands in `errors`).
      * `disabled` -- names of work items with `enabled=False` (never loaded).
      * `errors` -- `(product, message)` 2-tuples for enabled items that raised
        while loading/gathering (the sole caller guarantees each is a 2-tuple).
    """
    dispatch_path: str
    products: tuple[HistorySummary, ...]
    disabled: tuple[str, ...]
    errors: tuple[tuple[str, str], ...]

    @property
    def n_products(self) -> int:
        """Count of products successfully ROLLED UP (an errored enabled product
        is NOT counted here -- it is in `errors`)."""
        return len(self.products)

    @property
    def n_disabled(self) -> int:
        return len(self.disabled)

    @property
    def n_errors(self) -> int:
        return len(self.errors)

    @property
    def total(self) -> int:
        """Company total iterations = the SUM of every gathered product's `total`."""
        return sum(p.total for p in self.products)

    @property
    def shipped(self) -> int:
        """Company shipped = the SUM of every gathered product's `shipped`."""
        return sum(p.shipped for p in self.products)

    @property
    def reverted(self) -> int:
        """Company reverted = the SUM of every gathered product's `reverted`."""
        return sum(p.reverted for p in self.products)

    @property
    def broken(self) -> int:
        """Company broken = the SUM of every gathered product's `broken`."""
        return sum(p.broken for p in self.products)

    @property
    def exit_code(self) -> int:
        """Scriptable verdict, errors-first: `1` when `errors` is non-empty
        (a structural read/parse failure -- the ONLY thing history gates on),
        else `2` when NO products were gathered (every item disabled or
        `work_items` empty -- reachable only with `errors` empty), else `0`.

        A past `BROKEN` inside a team's ledger does NOT gate: company-history is
        informational, exactly like per-product `history` (current attention is
        `company-status`'s job)."""
        if self.errors:
            return 1
        if self.n_products == 0:
            return 2
        return 0

    @property
    def verdict(self) -> str:
        """The single human token for the current `exit_code` -- `"OK"` (0) /
        `"ERRORS"` (1) / `"no enabled products"` (2). ONE source of truth for
        both `render()`'s last line and the JSON `verdict` key, so the text and
        the machine payload can never drift from the exit code."""
        return {0: "OK", 1: "ERRORS", 2: "no enabled products"}[self.exit_code]

    def render(self) -> str:
        """A deterministic multi-line company ledger report (the CLI's contract).

        Contains, as substrings: the `dispatch_path`; a counts line reporting the
        number of GATHERED products, the disabled count, and the error count, PLUS
        the company rollup `{total} iterations: {shipped} shipped, {reverted}
        reverted, {broken} broken`; ONE line per gathered product with its
        `product` name AND its OWN rollup (same `{total} iterations: ...` shape);
        one line per disabled item with its name and `disabled`; one line per
        error with its name, `ERROR`, and the message; and a final `verdict:` line
        whose token EQUALS `verdict`."""
        rollup = (f"{self.total} iterations: {self.shipped} shipped, "
                  f"{self.reverted} reverted, {self.broken} broken")
        lines = [
            "foundry company-history",
            f"  dispatch config: {self.dispatch_path}",
            f"  products: {self.n_products} gathered, "
            f"{self.n_disabled} disabled, {self.n_errors} error(s) -- {rollup}",
        ]
        for p in self.products:
            p_rollup = (f"{p.total} iterations: {p.shipped} shipped, "
                        f"{p.reverted} reverted, {p.broken} broken")
            lines.append(f"  - {p.product}: {p_rollup}")
        for name in self.disabled:
            lines.append(f"  - {name}: disabled")
        for name, message in self.errors:
            lines.append(f"  - {name}: ERROR {message}")
        lines.append(f"verdict: {self.verdict}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """A pure, JSON-safe company roll-up for machine consumers -- a dashboard
        / cron alert / the reporter. Every derived value REUSES the frozen
        properties, so the payload can never disagree with `render()` or the exit
        code, and every value is JSON-native, so it round-trips through
        `json.loads(json.dumps(...))`. Pure: touches no filesystem."""
        return {
            "dispatch_config": self.dispatch_path,
            "products": [p.to_dict() for p in self.products],
            "disabled": list(self.disabled),
            "errors": [{"product": name, "message": message}
                       for name, message in self.errors],
            "n_products": self.n_products,
            "n_disabled": self.n_disabled,
            "n_errors": self.n_errors,
            "total": self.total,
            "shipped": self.shipped,
            "reverted": self.reverted,
            "broken": self.broken,
            "exit_code": self.exit_code,
            "verdict": self.verdict,
        }


def summarize_company_history(*, dispatch_path: str,
                              products: tuple[HistorySummary, ...],
                              disabled: tuple[str, ...],
                              errors: tuple[tuple[str, str], ...]
                              ) -> CompanyHistory:
    """Pure keyword-only constructor for a `CompanyHistory` (Behaviors 3-7).

    A thin, total wrapper that packs the gathered ledgers into the frozen
    roll-up -- keyword-only so a caller can never transpose the fields by
    position, and it never raises for well-formed inputs (each `errors` entry is
    a `(product, message)` 2-tuple, which the sole caller `company_history_cli`
    guarantees; documenting the precondition keeps the "never raises" contract
    airtight). Kept separate from `company_history_cli` so the decision core
    stays a pure function the tester can drive without any filesystem."""
    return CompanyHistory(
        dispatch_path=dispatch_path,
        products=tuple(products),
        disabled=tuple(disabled),
        errors=tuple((name, message) for name, message in errors))


def company_history_cli(dispatch_path: str, limit: int | None = None,
                        as_json: bool = False) -> int:
    """On-demand CLI: roll every ENABLED team's ship ledger into ONE company view.

    Reads the DISPATCH config at `dispatch_path` (`foundry.config.json`, NOT a
    product config), then for each ENABLED work item substitutes a `{FOUNDRY}`
    token in its config path to the foundry root and loads + gathers that
    product's ledger via the `load_config` / `gather_history` seams (both called
    by BARE name so a `monkeypatch.setattr(foundry, ...)` bites). `limit` flows
    through to EVERY `gather_history(cfg, limit)` call (most-recent N per team).
    A DISABLED item is recorded in `disabled` (by name) and never loaded.

    Resilient (Behaviors 9-10): if reading/parsing the dispatch config fails
    (missing / not JSON / not an object) it prints a report recording ONE
    synthetic error and returns exit 1; if a single work item's `load_config` or
    `gather_history` raises, that item is recorded in `errors` and the roll-up
    CONTINUES gathering the rest (company exit 1). No exception ever propagates.

    With `as_json=True` stdout is exactly ONE `json.dumps(to_dict(), indent=2)`
    document; either way the RETURN value is the same `CompanyHistory.exit_code`
    (0 gathered-no-errors / 1 errors / 2 no-enabled-products). Writes NOTHING to
    disk -- a read-only report; with `load_config` monkeypatched the filesystem
    is untouched."""
    try:
        dispatch = json.loads(
            pathlib.Path(dispatch_path).expanduser().read_text())
        if not isinstance(dispatch, dict):
            raise ValueError("dispatch config is not a JSON object")
    except Exception as exc:
        # A missing / malformed dispatch config is a real operator problem, not a
        # crash: surface it as ONE synthetic error (errors -> exit 1).
        company = summarize_company_history(
            dispatch_path=dispatch_path, products=(), disabled=(),
            errors=((dispatch_path, str(exc)),))
        print(json.dumps(company.to_dict(), indent=2) if as_json
              else company.render())
        return company.exit_code

    products: list[HistorySummary] = []
    disabled: list[str] = []
    errors: list[tuple[str, str]] = []
    for name, config, enabled in parse_dispatch_work_items(dispatch):
        if not enabled:
            disabled.append(name)      # deliberate; never loaded
            continue
        try:
            # {FOUNDRY} -> foundry root BEFORE load_config, exactly as the
            # dispatcher resolves each work item's config path.
            cfg = load_config(config.replace("{FOUNDRY}", str(FOUNDRY)))
            products.append(gather_history(cfg, limit))
        except Exception as exc:
            # One bad team never sinks the whole roll-up -- record + continue.
            errors.append((name, str(exc)))
    company = summarize_company_history(
        dispatch_path=dispatch_path, products=tuple(products),
        disabled=tuple(disabled), errors=tuple(errors))
    print(json.dumps(company.to_dict(), indent=2) if as_json else company.render())
    return company.exit_code


# --------------------------------------------------------------------------- #
# `foundry timing` -- read-only, offline per-iteration suite-wall-time digest.
# The signal it reports (`- suite_seconds:` in each `postrelease.md`) is already
# persisted by every genuine ship (item 7, bites 1/2); this is the operator lens
# on it -- `status` answers "healthy now?", `history` answers "what shipped?",
# and `timing` answers "is verify-time trending up?". `parse_suite_seconds` is
# the pure body-line parser; `TimingRecord`/`TimingSummary` + the pure
# `summarize_timing` are the decision core (driven by the tester with zero
# filesystem); `timing_cli` is the thin read-only shell that reads the on-disk
# artifacts through the SAME bare-name seams (`iteration_numbers`,
# `parse_suite_seconds`, `SUITE_SLOW_SECONDS`) so a test's `monkeypatch` bites.
# Purely additive + off the control path -- the pipeline/dispatcher never call
# any of it and it writes NOTHING.
# --------------------------------------------------------------------------- #
def parse_suite_seconds(text: str) -> float | None:
    """Extract the fresh-clone suite wall-time from a `postrelease.md` body (pure).

    Returns the float on the FIRST body line whose stripped form is the
    `suite_seconds:` key -- an optional leading `- ` markdown bullet is tolerated
    (that is exactly how `_write_postrelease_artifact` emits the line) and
    whitespace anywhere on the line is ignored, so `-  suite_seconds:   12.34  `
    still yields `12.34`. A measured `0.00` returns the float `0.0` (a real value,
    distinct from an unmeasured iteration).

    Returns `None` -- never raising for ANY string -- when the value cannot be a
    measured wall-time: the `n/a` sentinel the artifact writes when the test
    command did not run (`float("n/a")` fails); no `suite_seconds:` line at all;
    empty / whitespace-only text; or a present-but-unparseable value (`abc`, an
    empty value). The first matching line is authoritative: if its value does not
    `float()`-parse, we stop and report `None` rather than scanning on, so a stray
    later mention can never be misread as the measurement.
    """
    key = "suite_seconds:"
    for raw in (text or "").splitlines():
        line = raw.strip()
        # Tolerate a single optional leading markdown bullet ("- "), then re-strip
        # so `-  suite_seconds: ...` (extra spaces after the dash) still matches.
        if line.startswith("-"):
            line = line[1:].strip()
        if not line.startswith(key):
            continue
        value = line[len(key):].strip()
        try:
            return float(value)
        except ValueError:
            # Present but not a measured number (`n/a`, `abc`, empty) -> unmeasured.
            return None
    return None


@dataclasses.dataclass(frozen=True)
class TimingRecord:
    """One iteration's fresh-clone suite wall-time (item 7 timing lens).

    Frozen so a computed record cannot be mutated after the fact (value equality
    for free, matching the other pure cores). `seconds` is `None` for an
    UNMEASURED iteration (the test command did not run, or there is no
    `postrelease.md`) -- distinct from a measured `0.0`.
    """
    iteration: int
    seconds: float | None

    def to_dict(self) -> dict:
        """A pure, JSON-safe serialization of one timing row for machine
        consumers (roadmap item 10's "machine-readable status for dashboards /
        the reporter"), mirroring iter-20's `IterationRecord.to_dict()`.

        Returns EXACTLY 2 keys in a fixed order: the two STORED fields verbatim
        (`iteration`/`seconds`). Every value is JSON-native (int / float / None),
        so `json.dumps(...)` never raises and the dict round-trips through
        `json.loads(json.dumps(...))`; a measured `0.0` stays the float `0.0`,
        distinct from an unmeasured `None`. Pure: touches no filesystem, only the
        already-computed record."""
        return {
            "iteration": self.iteration,
            "seconds": self.seconds,
        }


@dataclasses.dataclass(frozen=True)
class TimingSummary:
    """A multi-iteration suite-wall-time digest for one product (item 7 lens).

    Frozen (value equality, no post-hoc mutation). `records` is stored as a
    `tuple` in render order; `threshold` is the slow cutoff captured at build
    time. Every count and statistic is a pure derivation of `records`
    (`min`/`max`/`avg`/`last`/slow-count computed over ONLY the measured subset,
    so an unmeasured iteration never skews the trend). `exit_code` is `2` iff
    there is NOTHING measured to report else `0`: timing is INFORMATIONAL and, like
    `history`, NEVER gates on a slow suite -- a run full of slow-but-fixed timings
    still exits `0` (raising a speed story is item 7 bite 2's job, not this lens).
    """
    product: str
    records: tuple["TimingRecord", ...]
    threshold: float

    @property
    def _measured(self) -> list[float]:
        """The measured wall-times in record order (unmeasured records dropped)."""
        return [r.seconds for r in self.records if r.seconds is not None]

    @property
    def measured_seconds(self) -> tuple[float, ...]:
        """The measured wall-times in record order as an immutable tuple, with
        unmeasured (`None`) records dropped -- e.g. records whose `seconds` are
        `(10.0, None, 30.0)` yield `(10.0, 30.0)`, and nothing measured yields the
        empty tuple `()`. A measured `0.0` is KEPT (distinct from an unmeasured
        `None`). Purely additive and derives ONLY from `self.records` (leaves
        `render()` / `to_dict()` / `exit_code` untouched) -- this is the accessor
        bite 2 pooled company min/max/avg will fold over."""
        return tuple(self._measured)

    @property
    def total(self) -> int:
        return len(self.records)

    @property
    def measured(self) -> int:
        return len(self._measured)

    @property
    def min_seconds(self) -> float | None:
        vals = self._measured
        return min(vals) if vals else None

    @property
    def max_seconds(self) -> float | None:
        vals = self._measured
        return max(vals) if vals else None

    @property
    def avg_seconds(self) -> float | None:
        vals = self._measured
        return sum(vals) / len(vals) if vals else None

    @property
    def last_seconds(self) -> float | None:
        # The LAST measured record in the given (ascending) order -- the most
        # recent measured wall-time, the operator's "where is it now" datapoint.
        vals = self._measured
        return vals[-1] if vals else None

    @property
    def count_slow(self) -> int:
        """Measured records STRICTLY over the threshold -- matches
        `suite_timing_line`/`speed_story_needed` (a suite exactly at the limit is
        deliberately NOT slow)."""
        return sum(1 for s in self._measured if s > self.threshold)

    @property
    def exit_code(self) -> int:
        """`2` iff nothing measured to report else `0` -- timing never gates on a
        slow suite (that is `foundry status`/item-7-bite-2's job)."""
        return 2 if self.measured == 0 else 0

    def render(self) -> str:
        """A deterministic multi-line digest carrying every per-iter wall-time.

        Contains, as substrings (the CLI's black-box contract): the `product`
        name; for EACH record (in stored order) a row with `iter-NN` (2-digit
        zero-pad) and either its wall-time to two decimals with a trailing `s`
        (e.g. `12.34s`) or `n/a` for an unmeasured record; and a rollup line
        carrying `measured {measured}/{total}` plus, when anything is measured,
        `min`/`max`/`avg`/`last` (each a two-decimal seconds value) and
        `slow (>{threshold:.2f}s): {count_slow}`. With NOTHING measured the rollup
        instead carries the literal `no measured timings yet`.
        """
        header = f"foundry timing -- {self.product}"
        rows = [
            f"  iter-{r.iteration:02d}  "
            f"{'n/a' if r.seconds is None else f'{r.seconds:.2f}s'}"
            for r in self.records
        ]
        if self.measured == 0:
            rollup = (f"measured {self.measured}/{self.total}: "
                      "no measured timings yet")
        else:
            rollup = (
                f"measured {self.measured}/{self.total}: "
                f"min {self.min_seconds:.2f}s, max {self.max_seconds:.2f}s, "
                f"avg {self.avg_seconds:.2f}s, last {self.last_seconds:.2f}s, "
                f"slow (>{self.threshold:.2f}s): {self.count_slow}")
        return "\n".join([header, *rows, rollup])

    def to_dict(self) -> dict:
        """A pure, JSON-safe serialization of the whole digest for machine
        consumers -- dashboards / cron / the reporter (roadmap item 10's
        "machine-readable status for dashboards / the reporter"), mirroring
        iter-19's `StatusSummary.to_dict()` and iter-20's
        `HistorySummary.to_dict()`.

        Returns EXACTLY 11 keys in a fixed order: `product` verbatim, then the
        eight DERIVED counts/stats/exit_code each REUSING the frozen iter-18
        properties (`total`/`measured`/`min_seconds`/`max_seconds`/`avg_seconds`/
        `last_seconds`/`count_slow`/`exit_code`) so the payload can never disagree
        with `render()`/the returned exit code, then the STORED `threshold`, then
        `records` as a JSON array of each record's `to_dict()` in the SAME order
        as `self.records`. Every value is JSON-native (str / int / float / None /
        list of dicts), so `json.dumps(...)` never raises and the dict round-trips
        through `json.loads(json.dumps(...))` -- including when the measured-only
        stats are `None` (nothing measured). Pure: touches no filesystem, only the
        already-gathered records."""
        return {
            "product": self.product,
            "total": self.total,
            "measured": self.measured,
            "min_seconds": self.min_seconds,
            "max_seconds": self.max_seconds,
            "avg_seconds": self.avg_seconds,
            "last_seconds": self.last_seconds,
            "count_slow": self.count_slow,
            "threshold": self.threshold,
            "exit_code": self.exit_code,
            "records": [r.to_dict() for r in self.records],
        }


def summarize_timing(*, product: str, records, threshold: float) -> TimingSummary:
    """Pure keyword-only constructor for a `TimingSummary` (item 7 lens).

    A thin, total wrapper packing the product name, an iterable of `TimingRecord`,
    and the slow `threshold` into the frozen digest, materializing `records` as a
    `tuple` (so the frozen dataclass stays immutable and a caller's list cannot be
    mutated out from under it). Keyword-only so the fields can never be transposed;
    it never raises. Kept separate from `timing_cli` so the decision core stays a
    pure function the tester can drive with zero filesystem (Behaviors 5-9)."""
    return TimingSummary(product=product, records=tuple(records),
                         threshold=threshold)


def gather_timing(cfg: ProductConfig, limit: int | None = None) -> TimingSummary:
    """Gather one product's multi-iteration suite WALL-TIME digest into a
    `TimingSummary` (item 7 timing lens).

    Extracted output-preservingly from the iter-18 `timing_cli` gathering so BOTH
    the single-product `foundry timing` and the coming company-wide roll-up
    (bite 2's `company_timing_cli`) share ONE gathering seam; a monkeypatch on
    this one function then reshapes every consumer at once. Output-preserving: the
    records/summary it builds are byte-identical to what iter 18 built, so `foundry
    timing` is unchanged (mirroring iter-30's `gather_status` extraction from
    `status_cli` and iter-31's `gather_history` from `history_cli`).

    Reads every signal through the EXISTING module-level seams -- each called by
    BARE name so a `monkeypatch.setattr(foundry, ...)` in a test bites:
      * lists `cfg.state`'s dir names (guarded -- a missing / unreadable state dir
        yields no names, never an error) and derives the iteration numbers via
        `iteration_numbers`;
      * applies `limit` -- keep the highest-N (most-recent) iterations when `limit`
        is a POSITIVE int, else ALL (a `None` / non-positive `limit` shows the full
        run); the numbers stay ascending so the digest reads oldest-first;
      * for each iteration reads `state/iter-NN/postrelease.md` (2-digit zero-pad)
        through `parse_suite_seconds` (via the shared `_read_sentinel` guard ->
        `None` on an absent file / `OSError`), building an ascending `TimingRecord`.
    Reads the slow `threshold` from the module global `SUITE_SLOW_SECONDS` AT CALL
    time (so a `monkeypatch.setattr(foundry, "SUITE_SLOW_SECONDS", ...)` still
    bites), hands the records to the pure `summarize_timing`, and returns the
    frozen `TimingSummary` core; writes NOTHING to disk (read-only). A missing /
    unreadable `cfg.state` yields an empty digest (`total == 0`), never raising."""
    state = cfg.state
    try:
        names = [p.name for p in state.iterdir()] if state.exists() else []
    except OSError:
        # A read error on the state dir must degrade to "no iterations", never
        # crash the probe (same no-news-is-good-news contract as the artifacts).
        names = []
    numbers = iteration_numbers(names)
    if isinstance(limit, int) and limit > 0:
        # `numbers` is ascending, so the most-recent N are the LAST N; the slice
        # preserves ascending order for the digest.
        numbers = numbers[-limit:]
    records = [
        TimingRecord(
            iteration=n,
            seconds=_read_sentinel(state / f"iter-{n:02d}" / "postrelease.md",
                                   parse_suite_seconds),
        )
        for n in numbers
    ]
    return summarize_timing(product=cfg.name, records=records,
                           threshold=SUITE_SLOW_SECONDS)


def timing_cli(cfg: ProductConfig, limit: int | None = None,
               as_json: bool = False) -> int:
    """On-demand CLI: print a per-iteration suite-wall-time digest + 0/2 exit code.

    With `as_json=True` the entire stdout is ONE `json.dumps(summary.to_dict(),
    indent=2)` document (the stable machine contract for dashboards/reporters,
    mirroring iter-19's `status --json` and iter-20's `history --json`); the
    default `as_json=False` is byte-for-byte the iter-18 human `render()` text.
    Either way the RETURN value is the same `summary.exit_code`, `--limit`
    selection is identical, and nothing is written to disk.

    Gathers the digest through the `gather_timing(cfg, limit)` seam (iter 39 --
    which reads the on-disk artifacts via the EXISTING module-level functions,
    called by BARE name so a `monkeypatch.setattr(foundry, ...)` bites, and reads
    the `SUITE_SLOW_SECONDS` threshold at call time) then prints the pure
    `TimingSummary` core. Output-preserving: the printed report / JSON / exit code
    are byte-identical to iter 18. Writes NOTHING to disk (read-only) -- a thin
    printer over the pure core that adds no decision logic of its own, so the
    printed rollup always equals the `TimingSummary` fields."""
    summary = gather_timing(cfg, limit)
    # `--json` emits the pure digest as a single JSON document (stdout-only, no
    # decision logic added); the default stays the exact iter-18 human report.
    print(json.dumps(summary.to_dict(), indent=2) if as_json else summary.render())
    return summary.exit_code


# --------------------------------------------------------------------------- #
# Company-wide suite-wall-time roll-up (`company-timing`) -- roadmap item 7,
# bite 2 (COMPLETES the feature; bite 1 shipped the `gather_timing` seam + the
# `TimingSummary.measured_seconds` accessor in iter 39).
#
# The THROUGHPUT-axis complement to iter-30's `company-status` (health NOW) and
# iter-31's `company-history` (ship LEDGER): `company-timing` answers "how is my
# whole company's VERIFY time trending?". The dispatcher runs a whole COMPANY of
# product teams (`foundry.config.json` `work_items`, each -> a product config)
# round-robin at concurrency 1, but `foundry timing` (iter 18) reports the
# suite-wall-time digest of exactly ONE product. An operator running N teams
# otherwise runs `timing --config <cfg>` once per team and mentally pools the
# numbers -- exactly the scattered babysitting the VISION says to eliminate.
#
# Purely additive + OFF the control path: it only reads the dispatch config and
# each product's on-disk timing artifacts and prints; the pipeline / dispatcher
# NEVER call it and it writes NOTHING. Same "compose existing frozen cores + a
# shared gathering seam, add no new I/O seam" pattern iters 30/31 endorsed,
# applied to the TIMING probe -- REUSING the already-shipped, tested
# `parse_dispatch_work_items` (iter 30) and the frozen `TimingSummary` core +
# its `gather_timing` seam and `measured_seconds` accessor (iter 39). Timing is
# INFORMATIONAL like per-product `timing`: a slow-but-fixed suite does NOT gate
# (raising a speed story is item-7-bite-2's PER-PRODUCT job); only a STRUCTURAL
# read/parse error (unreadable dispatch config, or a team that failed to
# load/gather) -> exit 1, exactly like `company-history`.
# --------------------------------------------------------------------------- #
@dataclasses.dataclass(frozen=True)
class CompanyTiming:
    """A one-shot COMPANY-wide suite-wall-time roll-up across a dispatch config.

    Frozen so a computed roll-up can't be mutated after the fact (value equality
    for free, matching the other pure cores). Every derived value is a pure
    property over the stored fields, so the whole verdict -- including the
    scriptable exit code -- follows deterministically from what was gathered, and
    the JSON payload / render text can never disagree with the exit code.

    Fields:
      * `dispatch_path` -- the dispatch config path, echoed into `render()`.
      * `products` -- the per-product `TimingSummary` digests that were
        successfully gathered, IN dispatch-file order (an enabled product that
        failed to load/gather is NOT here -- it lands in `errors`).
      * `disabled` -- names of work items with `enabled=False` (never loaded).
      * `errors` -- `(product, message)` 2-tuples for enabled items that raised
        while loading/gathering (the sole caller guarantees each is a 2-tuple).
      * `threshold` -- the company slow cutoff (`SUITE_SLOW_SECONDS` at call
        time), echoed into the rollup `slow (>{threshold}s)` line.

    Pooled `min`/`max`/`avg` fold over the CONCATENATED measured seconds of every
    product (each product's `measured_seconds` in stored order); there is NO
    company `last_seconds` (ill-defined across teams). `count_slow` is the SUM of
    each product's own `count_slow` (each per-product count uses that product's
    build-time threshold, which for a live roll-up is the same
    `SUITE_SLOW_SECONDS` as the company threshold).
    """
    dispatch_path: str
    products: tuple[TimingSummary, ...]
    disabled: tuple[str, ...]
    errors: tuple[tuple[str, str], ...]
    threshold: float

    @property
    def n_products(self) -> int:
        """Count of products successfully ROLLED UP (an errored enabled product
        is NOT counted here -- it is in `errors`)."""
        return len(self.products)

    @property
    def n_disabled(self) -> int:
        return len(self.disabled)

    @property
    def n_errors(self) -> int:
        return len(self.errors)

    @property
    def total(self) -> int:
        """Company total iterations = the SUM of every gathered product's `total`."""
        return sum(p.total for p in self.products)

    @property
    def measured(self) -> int:
        """Company measured iterations = the SUM of every product's `measured`."""
        return sum(p.measured for p in self.products)

    @property
    def count_slow(self) -> int:
        """Company slow count = the SUM of every product's own `count_slow`
        (each measured record STRICTLY over its build-time threshold)."""
        return sum(p.count_slow for p in self.products)

    @property
    def _pool(self) -> list[float]:
        """The POOLED measured wall-times of all products (each product's
        `measured_seconds` concatenated in stored product order) -- the sample the
        company min/max/avg fold over. An unmeasured product contributes nothing."""
        pool: list[float] = []
        for p in self.products:
            pool.extend(p.measured_seconds)
        return pool

    @property
    def min_seconds(self) -> float | None:
        pool = self._pool
        return min(pool) if pool else None

    @property
    def max_seconds(self) -> float | None:
        pool = self._pool
        return max(pool) if pool else None

    @property
    def avg_seconds(self) -> float | None:
        pool = self._pool
        return sum(pool) / len(pool) if pool else None

    @property
    def exit_code(self) -> int:
        """Scriptable verdict, errors-first: `1` when `errors` is non-empty (a
        structural read/parse failure -- the ONLY thing timing gates on), else `2`
        when NO products were gathered (every item disabled or `work_items` empty
        -- reachable only with `errors` empty), else `0`.

        A gathered product with ZERO measured timings does NOT force exit 2 (it
        still counts as a product -> exit 0); a company full of slow-but-fixed
        timings still exits 0 (timing is informational, exactly like per-product
        `timing` -- raising a speed story is item-7-bite-2's per-product job)."""
        if self.errors:
            return 1
        if self.n_products == 0:
            return 2
        return 0

    @property
    def verdict(self) -> str:
        """The single human token for the current `exit_code` -- `"OK"` (0) /
        `"ERRORS"` (1) / `"no enabled products"` (2). ONE source of truth for
        both `render()`'s last line and the JSON `verdict` key, so the text and
        the machine payload can never drift from the exit code."""
        return {0: "OK", 1: "ERRORS", 2: "no enabled products"}[self.exit_code]

    def _rollup(self) -> str:
        """The company timing rollup as a substring: `measured {measured}/{total}`
        plus, when anything is measured company-wide, pooled `min`/`max`/`avg`
        (two-decimal seconds) and `slow (>{threshold}s): {count_slow}`; with
        NOTHING measured the literal `no measured timings yet` (no min/max/avg)."""
        if self.measured == 0:
            return f"measured {self.measured}/{self.total}: no measured timings yet"
        return (
            f"measured {self.measured}/{self.total}: "
            f"min {self.min_seconds:.2f}s, max {self.max_seconds:.2f}s, "
            f"avg {self.avg_seconds:.2f}s, "
            f"slow (>{self.threshold:.2f}s): {self.count_slow}")

    def render(self) -> str:
        """A deterministic multi-line company timing report (the CLI's contract).

        Contains, as substrings: the literal `foundry company-timing`; the
        `dispatch_path`; a counts line reporting `{n_products} gathered`,
        `{n_disabled} disabled`, `{n_errors} error(s)` PLUS the company rollup
        (`measured {measured}/{total}` with pooled `min`/`max`/`avg` +
        `slow (>{threshold}s): {count_slow}` when anything is measured, else the
        literal `no measured timings yet`); ONE line per gathered product
        beginning `  - {product}:` carrying its OWN `measured {p.measured}/
        {p.total}` and, when it has measured timings, its `min`/`max`/`avg`/`last`
        (two-decimal seconds) + `slow: {p.count_slow}` (else `no measured timings
        yet`); one `  - {name}: disabled` line per disabled item; one
        `  - {name}: ERROR {message}` line per error; and a final `verdict:` line
        whose token EQUALS `verdict`."""
        lines = [
            "foundry company-timing",
            f"  dispatch config: {self.dispatch_path}",
            f"  products: {self.n_products} gathered, "
            f"{self.n_disabled} disabled, {self.n_errors} error(s) -- "
            f"{self._rollup()}",
        ]
        for p in self.products:
            if p.measured == 0:
                p_rollup = (f"measured {p.measured}/{p.total}: "
                            "no measured timings yet")
            else:
                p_rollup = (
                    f"measured {p.measured}/{p.total}: "
                    f"min {p.min_seconds:.2f}s, max {p.max_seconds:.2f}s, "
                    f"avg {p.avg_seconds:.2f}s, last {p.last_seconds:.2f}s, "
                    f"slow: {p.count_slow}")
            lines.append(f"  - {p.product}: {p_rollup}")
        for name in self.disabled:
            lines.append(f"  - {name}: disabled")
        for name, message in self.errors:
            lines.append(f"  - {name}: ERROR {message}")
        lines.append(f"verdict: {self.verdict}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """A pure, JSON-safe company roll-up for machine consumers -- a dashboard
        / cron alert / the reporter. Every derived value REUSES the frozen
        properties, so the payload can never disagree with `render()` or the exit
        code, and every value is JSON-native, so it round-trips through
        `json.loads(json.dumps(...))` -- including when the pooled stats are
        `None` (nothing measured -> JSON `null`). Pure: touches no filesystem."""
        return {
            "dispatch_config": self.dispatch_path,
            "products": [p.to_dict() for p in self.products],
            "disabled": list(self.disabled),
            "errors": [{"product": name, "message": message}
                       for name, message in self.errors],
            "n_products": self.n_products,
            "n_disabled": self.n_disabled,
            "n_errors": self.n_errors,
            "total": self.total,
            "measured": self.measured,
            "count_slow": self.count_slow,
            "min_seconds": self.min_seconds,
            "max_seconds": self.max_seconds,
            "avg_seconds": self.avg_seconds,
            "threshold": self.threshold,
            "exit_code": self.exit_code,
            "verdict": self.verdict,
        }


def summarize_company_timing(*, dispatch_path: str,
                             products: tuple[TimingSummary, ...],
                             disabled: tuple[str, ...],
                             errors: tuple[tuple[str, str], ...],
                             threshold: float) -> CompanyTiming:
    """Pure keyword-only constructor for a `CompanyTiming` (Behaviors 1-6).

    A thin, total wrapper that packs the gathered digests into the frozen
    roll-up -- keyword-only so a caller can never transpose the fields by
    position, and it never raises for well-formed inputs (each `errors` entry is
    a `(product, message)` 2-tuple, which the sole caller `company_timing_cli`
    guarantees; documenting the precondition keeps the "never raises" contract
    airtight). Kept separate from `company_timing_cli` so the decision core stays
    a pure function the tester can drive without any filesystem."""
    return CompanyTiming(
        dispatch_path=dispatch_path,
        products=tuple(products),
        disabled=tuple(disabled),
        errors=tuple((name, message) for name, message in errors),
        threshold=threshold)


def company_timing_cli(dispatch_path: str, limit: int | None = None,
                       as_json: bool = False) -> int:
    """On-demand CLI: roll every ENABLED team's suite-wall-time digest into ONE
    company throughput lens (roadmap item 7, bite 2).

    Reads the DISPATCH config at `dispatch_path` (`foundry.config.json`, NOT a
    product config), then for each ENABLED work item substitutes a `{FOUNDRY}`
    token in its config path to the foundry root and loads + gathers that
    product's digest via the `load_config` / `gather_timing` seams (both called
    by BARE name so a `monkeypatch.setattr(foundry, ...)` bites). `limit` flows
    through to EVERY `gather_timing(cfg, limit)` call (most-recent N per team).
    A DISABLED item is recorded in `disabled` (by name) and never loaded. The
    company `threshold` is read from the module global `SUITE_SLOW_SECONDS` AT
    CALL time (so a `monkeypatch.setattr(foundry, "SUITE_SLOW_SECONDS", ...)`
    bites), exactly as `gather_timing` reads each product's own threshold.

    Resilient (Behaviors 7-8): if reading/parsing the dispatch config fails
    (missing / not JSON / not an object) it prints a report recording ONE
    synthetic error and returns exit 1; if a single work item's `load_config` or
    `gather_timing` raises, that item is recorded in `errors` and the roll-up
    CONTINUES gathering the rest (company exit 1). No exception ever propagates.

    With `as_json=True` stdout is exactly ONE `json.dumps(to_dict(), indent=2)`
    document; either way the RETURN value is the same `CompanyTiming.exit_code`
    (0 gathered-no-errors / 1 errors / 2 no-enabled-products). Writes NOTHING to
    disk -- a read-only report; with `load_config` monkeypatched the filesystem
    is untouched."""
    threshold = SUITE_SLOW_SECONDS  # read at call time -- monkeypatch bites
    try:
        dispatch = json.loads(
            pathlib.Path(dispatch_path).expanduser().read_text())
        if not isinstance(dispatch, dict):
            raise ValueError("dispatch config is not a JSON object")
    except Exception as exc:
        # A missing / malformed dispatch config is a real operator problem, not a
        # crash: surface it as ONE synthetic error (errors -> exit 1).
        company = summarize_company_timing(
            dispatch_path=dispatch_path, products=(), disabled=(),
            errors=((dispatch_path, str(exc)),), threshold=threshold)
        print(json.dumps(company.to_dict(), indent=2) if as_json
              else company.render())
        return company.exit_code

    products: list[TimingSummary] = []
    disabled: list[str] = []
    errors: list[tuple[str, str]] = []
    for name, config, enabled in parse_dispatch_work_items(dispatch):
        if not enabled:
            disabled.append(name)      # deliberate; never loaded
            continue
        try:
            # {FOUNDRY} -> foundry root BEFORE load_config, exactly as the
            # dispatcher resolves each work item's config path.
            cfg = load_config(config.replace("{FOUNDRY}", str(FOUNDRY)))
            products.append(gather_timing(cfg, limit))
        except Exception as exc:
            # One bad team never sinks the whole roll-up -- record + continue.
            errors.append((name, str(exc)))
    company = summarize_company_timing(
        dispatch_path=dispatch_path, products=tuple(products),
        disabled=tuple(disabled), errors=tuple(errors), threshold=threshold)
    print(json.dumps(company.to_dict(), indent=2) if as_json else company.render())
    return company.exit_code


# --------------------------------------------------------------------------- #
# Company-wide weak-test roll-up (`company-weak-tests`) -- roadmap item 6,
# bite 2 of 2 (the company view on the iter-42 `gather_weak_tests` foundation).
#
# The QUALITY-axis complement to iter-30's `company-status` (health NOW),
# iter-31's `company-history` (ship LEDGER) and iter-40's `company-timing`
# (THROUGHPUT): `company-weak-tests` answers "does ANY team have a worthless,
# assertion-free test?" -- the foundry's #1 verification failure mode (a
# false-green test that certifies nothing). It reads the DISPATCH config and
# folds every ENABLED team's iter-22 `weak-tests` scan into ONE company view
# (summed files-scanned / assertion-free-tests / parse-errors + a per-product
# breakdown), reusing the SHIPPED `gather_weak_tests` (iter 42) /
# `parse_dispatch_work_items` (iter 30) / frozen `WeakTestSummary` (iter 22)
# seams -- adds NO new I/O seam, sentinel, config field, or artifact. Purely
# additive and DORMANT: the pipeline / gate / dispatcher NEVER call it and it
# WRITES NOTHING (read-only). UNLIKE the INFORMATIONAL history/timing roll-ups,
# it GATES on findings (mirroring the per-product `weak-tests` gate): a worthless
# test OR an unparseable file OR a structural gather error ANYWHERE -> exit 1.
# --------------------------------------------------------------------------- #
@dataclasses.dataclass(frozen=True)
class CompanyWeakTests:
    """A one-shot COMPANY-wide assertion-free-test roll-up across a dispatch config.

    Frozen so a computed roll-up can't be mutated after the fact (value equality
    for free, matching the other pure cores). Every derived value is a pure
    property over the stored fields, so the whole verdict -- including the
    scriptable exit code -- follows deterministically from what was gathered, and
    the JSON payload / render text can never disagree with the exit code.

    Fields:
      * `dispatch_path` -- the dispatch config path, echoed into `render()`.
      * `products` -- the per-product `WeakTestSummary` scans that were
        successfully gathered, IN dispatch-file order (an enabled product that
        failed to load/gather is NOT here -- it lands in `errors`).
      * `disabled` -- names of work items with `enabled=False` (never loaded).
      * `errors` -- `(product, message)` 2-tuples for enabled items that raised
        while loading/gathering (the sole caller guarantees each is a 2-tuple).

    The company totals are SUMS over the gathered products: `files_scanned` /
    `total_findings` sum the same-named per-product fields, `total_parse_errors`
    sums each product's `len(parse_errors)`. `n_flagged` counts gathered products
    that have a finding OR a parse error (the per-product "not clean but scanned"
    signal), giving the operator "how many teams need looking at" at a glance.
    """
    dispatch_path: str
    products: tuple[WeakTestSummary, ...]
    disabled: tuple[str, ...]
    errors: tuple[tuple[str, str], ...]

    @property
    def n_products(self) -> int:
        """Count of products successfully ROLLED UP (an errored enabled product
        is NOT counted here -- it is in `errors`)."""
        return len(self.products)

    @property
    def n_disabled(self) -> int:
        return len(self.disabled)

    @property
    def n_errors(self) -> int:
        return len(self.errors)

    @property
    def files_scanned(self) -> int:
        """Company files scanned = the SUM of every gathered product's
        `files_scanned`."""
        return sum(p.files_scanned for p in self.products)

    @property
    def total_findings(self) -> int:
        """Company assertion-free tests = the SUM of every product's
        `total_findings`."""
        return sum(p.total_findings for p in self.products)

    @property
    def total_parse_errors(self) -> int:
        """Company parse errors = the SUM of every product's own
        `len(parse_errors)` (files that would not parse / read anywhere)."""
        return sum(len(p.parse_errors) for p in self.products)

    @property
    def n_flagged(self) -> int:
        """How many GATHERED products have a finding OR a parse error -- the
        per-product "scanned but not clean" signal, so an operator sees "how many
        teams need looking at" without expanding the breakdown."""
        return sum(1 for p in self.products
                   if p.total_findings > 0 or p.parse_errors)

    @property
    def exit_code(self) -> int:
        """Scriptable verdict, findings-first (UNLIKE informational
        history/timing): `1` when `errors` is non-empty (a structural gather
        failure) OR `total_findings > 0` (a worthless test) OR
        `total_parse_errors > 0` (an unparseable file) ANYWHERE -- all three gate,
        mirroring the per-product `weak-tests` exit code; else `2` when NO
        products were gathered (every item disabled or `work_items` empty --
        reachable only with `errors` empty and no findings); else `0` (clean).

        A gathered product that scanned ZERO test files (its own
        `WeakTestSummary.exit_code == 2`) does NOT force company exit 2 -- it
        still counts in `n_products`, so with no findings/parse-errors/structural-
        errors the company exits 0 (mirroring `company-timing`, where a product
        with zero measured timings does not force exit 2)."""
        if self.errors or self.total_findings > 0 or self.total_parse_errors > 0:
            return 1
        if self.n_products == 0:
            return 2
        return 0

    @property
    def verdict(self) -> str:
        """The single human token for the current `exit_code` -- `"clean"` (0) /
        `"ATTENTION"` (1) / `"no enabled products"` (2). ONE source of truth for
        both `render()`'s last line and the JSON `verdict` key, so the text and
        the machine payload can never drift from the exit code."""
        return {0: "clean", 1: "ATTENTION", 2: "no enabled products"}[self.exit_code]

    def _rollup(self) -> str:
        """The company weak-test rollup as a substring: `{files_scanned} files
        scanned, {total_findings} assertion-free tests, {total_parse_errors}
        parse errors` -- the summed counts only (per-team leaf findings live in
        the per-product breakdown / `to_dict()`, keeping the report bounded like
        `company-history`/`company-timing`)."""
        return (f"{self.files_scanned} files scanned, "
                f"{self.total_findings} assertion-free tests, "
                f"{self.total_parse_errors} parse errors")

    def render(self) -> str:
        """A deterministic multi-line company weak-test report (the CLI's contract).

        Contains, as substrings: the literal `foundry company-weak-tests`; the
        `dispatch_path`; a counts line reporting `{n_products} gathered`,
        `{n_disabled} disabled`, `{n_errors} error(s)` PLUS the company rollup
        (`{files_scanned} files scanned, {total_findings} assertion-free tests,
        {total_parse_errors} parse errors`); ONE line per gathered product
        beginning `  - {product}:` carrying its OWN `{p.files_scanned} files
        scanned, {p.total_findings} assertion-free, {len(p.parse_errors)} parse
        error(s)` (per-product COUNTS only, NOT each `(file :: test)` leaf); one
        `  - {name}: disabled` line per disabled item; one `  - {name}: ERROR
        {message}` line per error; and a final `verdict:` line whose token EQUALS
        `verdict`."""
        lines = [
            "foundry company-weak-tests",
            f"  dispatch config: {self.dispatch_path}",
            f"  products: {self.n_products} gathered, "
            f"{self.n_disabled} disabled, {self.n_errors} error(s) -- "
            f"{self._rollup()}",
        ]
        for p in self.products:
            lines.append(
                f"  - {p.product}: {p.files_scanned} files scanned, "
                f"{p.total_findings} assertion-free, "
                f"{len(p.parse_errors)} parse error(s)")
        for name in self.disabled:
            lines.append(f"  - {name}: disabled")
        for name, message in self.errors:
            lines.append(f"  - {name}: ERROR {message}")
        lines.append(f"verdict: {self.verdict}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """A pure, JSON-safe company roll-up for machine consumers -- a dashboard
        / cron alert / the reporter. `products` carries the FULL per-product
        `WeakTestSummary.to_dict()` payload (the 8-key per-team detail INCLUDING
        each team's `findings`/`parse_errors` leaf arrays) in stored order, so no
        leaf detail is lost even though `render()` prints per-product counts only.
        Every derived value REUSES the frozen properties, so the payload can never
        disagree with `render()` or the exit code, and every value is JSON-native,
        so it round-trips through `json.loads(json.dumps(...))` -- including when
        `products`/`disabled`/`errors` are all empty. Pure: touches no filesystem."""
        return {
            "dispatch_config": self.dispatch_path,
            "products": [p.to_dict() for p in self.products],
            "disabled": list(self.disabled),
            "errors": [{"product": name, "message": message}
                       for name, message in self.errors],
            "n_products": self.n_products,
            "n_disabled": self.n_disabled,
            "n_errors": self.n_errors,
            "n_flagged": self.n_flagged,
            "files_scanned": self.files_scanned,
            "total_findings": self.total_findings,
            "total_parse_errors": self.total_parse_errors,
            "exit_code": self.exit_code,
            "verdict": self.verdict,
        }


def summarize_company_weak_tests(*, dispatch_path: str,
                                 products: tuple[WeakTestSummary, ...],
                                 disabled: tuple[str, ...],
                                 errors: tuple[tuple[str, str], ...],
                                 ) -> CompanyWeakTests:
    """Pure keyword-only constructor for a `CompanyWeakTests` (Behaviors 1-7).

    A thin, total wrapper that packs the gathered scans into the frozen roll-up
    -- keyword-only so a caller can never transpose the fields by position, and
    it never raises for well-formed inputs (each `errors` entry is a
    `(product, message)` 2-tuple, which the sole caller `company_weak_tests_cli`
    guarantees; documenting the precondition keeps the "never raises" contract
    airtight). Kept separate from `company_weak_tests_cli` so the decision core
    stays a pure function the tester can drive without any filesystem."""
    return CompanyWeakTests(
        dispatch_path=dispatch_path,
        products=tuple(products),
        disabled=tuple(disabled),
        errors=tuple((name, message) for name, message in errors))


def company_weak_tests_cli(dispatch_path: str, as_json: bool = False) -> int:
    """On-demand CLI: roll every ENABLED team's assertion-free-test scan into ONE
    company quality view (roadmap item 6, bite 2).

    Reads the DISPATCH config at `dispatch_path` (`foundry.config.json`, NOT a
    product config), then for each ENABLED work item substitutes a `{FOUNDRY}`
    token in its config path to the foundry root and loads + scans that product
    via the `load_config` / `gather_weak_tests` seams (both called by BARE name
    so a `monkeypatch.setattr(foundry, ...)` bites). A DISABLED item is recorded
    in `disabled` (by name) and never loaded.

    Resilient (Behaviors 6-7): if reading/parsing the dispatch config fails
    (missing / not JSON / not an object) it prints a report recording ONE
    synthetic error and returns exit 1; if a single work item's `load_config` or
    `gather_weak_tests` raises, that item is recorded in `errors` and the roll-up
    CONTINUES scanning the rest (company exit 1). No exception ever propagates.

    With `as_json=True` stdout is exactly ONE `json.dumps(to_dict(), indent=2)`
    document; either way the RETURN value is the same `CompanyWeakTests.exit_code`
    (0 clean / 1 findings-or-parse-errors-or-team-errored / 2 no-enabled-
    products). Writes NOTHING to disk -- a read-only report; with `load_config`
    monkeypatched the filesystem is untouched."""
    try:
        dispatch = json.loads(
            pathlib.Path(dispatch_path).expanduser().read_text())
        if not isinstance(dispatch, dict):
            raise ValueError("dispatch config is not a JSON object")
    except Exception as exc:
        # A missing / malformed dispatch config is a real operator problem, not a
        # crash: surface it as ONE synthetic error (errors -> exit 1).
        company = summarize_company_weak_tests(
            dispatch_path=dispatch_path, products=(), disabled=(),
            errors=((dispatch_path, str(exc)),))
        print(json.dumps(company.to_dict(), indent=2) if as_json
              else company.render())
        return company.exit_code

    products: list[WeakTestSummary] = []
    disabled: list[str] = []
    errors: list[tuple[str, str]] = []
    for name, config, enabled in parse_dispatch_work_items(dispatch):
        if not enabled:
            disabled.append(name)      # deliberate; never loaded
            continue
        try:
            # {FOUNDRY} -> foundry root BEFORE load_config, exactly as the
            # dispatcher resolves each work item's config path.
            cfg = load_config(config.replace("{FOUNDRY}", str(FOUNDRY)))
            products.append(gather_weak_tests(cfg))
        except Exception as exc:
            # One bad team never sinks the whole roll-up -- record + continue.
            errors.append((name, str(exc)))
    company = summarize_company_weak_tests(
        dispatch_path=dispatch_path, products=tuple(products),
        disabled=tuple(disabled), errors=tuple(errors))
    print(json.dumps(company.to_dict(), indent=2) if as_json else company.render())
    return company.exit_code


# --------------------------------------------------------------------------- #
# Company-wide constant-assert roll-up (`company-constant-asserts`) -- roadmap
# item 6, the company view on the iter-48 `gather_constant_asserts` foundation
# (the 6th and FINAL `company-*` family member).
#
# The QUALITY-axis complement to iter-30's `company-status` (health NOW),
# iter-31's `company-history` (ship LEDGER), iter-40's `company-timing`
# (THROUGHPUT), iter-43's `company-weak-tests` (assertion-FREE tests) and
# iter-46's `company-events` (ACTIVITY): `company-constant-asserts` answers
# "does ANY team have a CONSTANT-assert test?" -- a `test*` whose ONLY signal
# is a tautological `assert True`/`assert 1`/`assert "x"`, the exact false-green
# class `weak-tests` structurally MISSES (a constant assert CARRIES an assert
# node, so it reads as a signal). It reads the DISPATCH config and folds every
# ENABLED team's iter-48 `constant-asserts` scan into ONE company view (summed
# files-scanned / constant-assert-tests / parse-errors + a per-product
# breakdown), reusing the SHIPPED `gather_constant_asserts` (iter 48) /
# `parse_dispatch_work_items` (iter 30) / frozen `ConstantAssertSummary`
# (iter 48) seams -- adds NO new I/O seam, sentinel, config field, or artifact.
# Purely additive and DORMANT: the pipeline / gate / dispatcher NEVER call it
# and it WRITES NOTHING (read-only). UNLIKE the INFORMATIONAL history/timing/
# events roll-ups, it GATES on findings (mirroring the per-product
# `constant-asserts` gate): a constant-assert test OR an unparseable file OR a
# structural gather error ANYWHERE -> exit 1.
# --------------------------------------------------------------------------- #
@dataclasses.dataclass(frozen=True)
class CompanyConstantAsserts:
    """A one-shot COMPANY-wide constant-assert-test roll-up across a dispatch config.

    Frozen so a computed roll-up can't be mutated after the fact (value equality
    for free, matching the other pure cores). Every derived value is a pure
    property over the stored fields, so the whole verdict -- including the
    scriptable exit code -- follows deterministically from what was gathered, and
    the JSON payload / render text can never disagree with the exit code.

    Fields:
      * `dispatch_path` -- the dispatch config path, echoed into `render()`.
      * `products` -- the per-product `ConstantAssertSummary` scans that were
        successfully gathered, IN dispatch-file order (an enabled product that
        failed to load/gather is NOT here -- it lands in `errors`).
      * `disabled` -- names of work items with `enabled=False` (never loaded).
      * `errors` -- `(product, message)` 2-tuples for enabled items that raised
        while loading/gathering (the sole caller guarantees each is a 2-tuple).

    The company totals are SUMS over the gathered products: `files_scanned` /
    `total_findings` sum the same-named per-product fields, `total_parse_errors`
    sums each product's `len(parse_errors)`. `n_flagged` counts gathered products
    that have a finding OR a parse error (the per-product "not clean but scanned"
    signal), giving the operator "how many teams need looking at" at a glance.

    A structural mirror of `CompanyWeakTests` (iter 43) differing ONLY in the
    per-product summary type (`ConstantAssertSummary` not `WeakTestSummary`), the
    gather seam its CLI drives, and the human labels -- the constant-assert scan
    is DISJOINT from the assertion-free scan by the detectors' construction, so a
    separate roll-up has zero downstream ripple.
    """
    dispatch_path: str
    products: tuple[ConstantAssertSummary, ...]
    disabled: tuple[str, ...]
    errors: tuple[tuple[str, str], ...]

    @property
    def n_products(self) -> int:
        """Count of products successfully ROLLED UP (an errored enabled product
        is NOT counted here -- it is in `errors`)."""
        return len(self.products)

    @property
    def n_disabled(self) -> int:
        return len(self.disabled)

    @property
    def n_errors(self) -> int:
        return len(self.errors)

    @property
    def files_scanned(self) -> int:
        """Company files scanned = the SUM of every gathered product's
        `files_scanned`."""
        return sum(p.files_scanned for p in self.products)

    @property
    def total_findings(self) -> int:
        """Company constant-assert tests = the SUM of every product's
        `total_findings`."""
        return sum(p.total_findings for p in self.products)

    @property
    def total_parse_errors(self) -> int:
        """Company parse errors = the SUM of every product's own
        `len(parse_errors)` (files that would not parse / read anywhere)."""
        return sum(len(p.parse_errors) for p in self.products)

    @property
    def n_flagged(self) -> int:
        """How many GATHERED products have a finding OR a parse error -- the
        per-product "scanned but not clean" signal, so an operator sees "how many
        teams need looking at" without expanding the breakdown."""
        return sum(1 for p in self.products
                   if p.total_findings > 0 or p.parse_errors)

    @property
    def exit_code(self) -> int:
        """Scriptable verdict, findings-first (UNLIKE informational
        history/timing/events): `1` when `errors` is non-empty (a structural
        gather failure) OR `total_findings > 0` (a constant-assert test) OR
        `total_parse_errors > 0` (an unparseable file) ANYWHERE -- all three
        gate, mirroring the per-product `constant-asserts` exit code; else `2`
        when NO products were gathered (every item disabled or `work_items` empty
        -- reachable only with `errors` empty and no findings); else `0` (clean).

        A gathered product that scanned ZERO test files (its own
        `ConstantAssertSummary.exit_code == 2`) does NOT force company exit 2 --
        it still counts in `n_products`, so with no findings/parse-errors/
        structural-errors the company exits 0 (mirroring `company-weak-tests`,
        where a product with zero scanned files does not force exit 2)."""
        if self.errors or self.total_findings > 0 or self.total_parse_errors > 0:
            return 1
        if self.n_products == 0:
            return 2
        return 0

    @property
    def verdict(self) -> str:
        """The single human token for the current `exit_code` -- `"clean"` (0) /
        `"ATTENTION"` (1) / `"no enabled products"` (2). ONE source of truth for
        both `render()`'s last line and the JSON `verdict` key, so the text and
        the machine payload can never drift from the exit code."""
        return {0: "clean", 1: "ATTENTION", 2: "no enabled products"}[self.exit_code]

    def _rollup(self) -> str:
        """The company constant-assert rollup as a substring: `{files_scanned}
        files scanned, {total_findings} constant-assert tests, {total_parse_errors}
        parse errors` -- the summed counts only (per-team leaf findings live in
        the per-product breakdown / `to_dict()`, keeping the report bounded like
        `company-weak-tests`/`company-timing`)."""
        return (f"{self.files_scanned} files scanned, "
                f"{self.total_findings} constant-assert tests, "
                f"{self.total_parse_errors} parse errors")

    def render(self) -> str:
        """A deterministic multi-line company constant-assert report (the CLI's
        contract).

        Contains, as substrings: the literal `foundry company-constant-asserts`;
        the `dispatch_path`; a counts line reporting `{n_products} gathered`,
        `{n_disabled} disabled`, `{n_errors} error(s)` PLUS the company rollup
        (`{files_scanned} files scanned, {total_findings} constant-assert tests,
        {total_parse_errors} parse errors`); ONE line per gathered product
        beginning `  - {product}:` carrying its OWN `{p.files_scanned} files
        scanned, {p.total_findings} constant-assert, {len(p.parse_errors)} parse
        error(s)` (per-product COUNTS only, NOT each `(file :: test)` leaf); one
        `  - {name}: disabled` line per disabled item; one `  - {name}: ERROR
        {message}` line per error; and a final `verdict:` line whose token EQUALS
        `verdict`."""
        lines = [
            "foundry company-constant-asserts",
            f"  dispatch config: {self.dispatch_path}",
            f"  products: {self.n_products} gathered, "
            f"{self.n_disabled} disabled, {self.n_errors} error(s) -- "
            f"{self._rollup()}",
        ]
        for p in self.products:
            lines.append(
                f"  - {p.product}: {p.files_scanned} files scanned, "
                f"{p.total_findings} constant-assert, "
                f"{len(p.parse_errors)} parse error(s)")
        for name in self.disabled:
            lines.append(f"  - {name}: disabled")
        for name, message in self.errors:
            lines.append(f"  - {name}: ERROR {message}")
        lines.append(f"verdict: {self.verdict}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """A pure, JSON-safe company roll-up for machine consumers -- a dashboard
        / cron alert / the reporter. `products` carries the FULL per-product
        `ConstantAssertSummary.to_dict()` payload (the 8-key per-team detail
        INCLUDING each team's `findings`/`parse_errors` leaf arrays) in stored
        order, so no leaf detail is lost even though `render()` prints per-product
        counts only. Every derived value REUSES the frozen properties, so the
        payload can never disagree with `render()` or the exit code, and every
        value is JSON-native, so it round-trips through
        `json.loads(json.dumps(...))` -- including when `products`/`disabled`/
        `errors` are all empty. Pure: touches no filesystem."""
        return {
            "dispatch_config": self.dispatch_path,
            "products": [p.to_dict() for p in self.products],
            "disabled": list(self.disabled),
            "errors": [{"product": name, "message": message}
                       for name, message in self.errors],
            "n_products": self.n_products,
            "n_disabled": self.n_disabled,
            "n_errors": self.n_errors,
            "n_flagged": self.n_flagged,
            "files_scanned": self.files_scanned,
            "total_findings": self.total_findings,
            "total_parse_errors": self.total_parse_errors,
            "exit_code": self.exit_code,
            "verdict": self.verdict,
        }


def summarize_company_constant_asserts(*, dispatch_path: str,
                                       products: tuple[ConstantAssertSummary, ...],
                                       disabled: tuple[str, ...],
                                       errors: tuple[tuple[str, str], ...],
                                       ) -> CompanyConstantAsserts:
    """Pure keyword-only constructor for a `CompanyConstantAsserts` (Behaviors 1-5).

    A thin, total wrapper that packs the gathered scans into the frozen roll-up
    -- keyword-only so a caller can never transpose the fields by position, and
    it never raises for well-formed inputs (each `errors` entry is a
    `(product, message)` 2-tuple, which the sole caller
    `company_constant_asserts_cli` guarantees; documenting the precondition keeps
    the "never raises" contract airtight). Kept separate from
    `company_constant_asserts_cli` so the decision core stays a pure function the
    tester can drive without any filesystem."""
    return CompanyConstantAsserts(
        dispatch_path=dispatch_path,
        products=tuple(products),
        disabled=tuple(disabled),
        errors=tuple((name, message) for name, message in errors))


def company_constant_asserts_cli(dispatch_path: str, as_json: bool = False) -> int:
    """On-demand CLI: roll every ENABLED team's constant-assert scan into ONE
    company quality view (roadmap item 6, the 6th/FINAL `company-*` member).

    Reads the DISPATCH config at `dispatch_path` (`foundry.config.json`, NOT a
    product config), then for each ENABLED work item substitutes a `{FOUNDRY}`
    token in its config path to the foundry root and loads + scans that product
    via the `load_config` / `gather_constant_asserts` seams (both called by BARE
    name so a `monkeypatch.setattr(foundry, ...)` bites). A DISABLED item is
    recorded in `disabled` (by name) and never loaded.

    Resilient (Behaviors 6-7): if reading/parsing the dispatch config fails
    (missing / not JSON / not an object) it prints a report recording ONE
    synthetic error and returns exit 1; if a single work item's `load_config` or
    `gather_constant_asserts` raises, that item is recorded in `errors` and the
    roll-up CONTINUES scanning the rest (company exit 1). No exception ever
    propagates.

    With `as_json=True` stdout is exactly ONE `json.dumps(to_dict(), indent=2)`
    document; either way the RETURN value is the same
    `CompanyConstantAsserts.exit_code` (0 clean / 1 findings-or-parse-errors-or-
    team-errored / 2 no-enabled-products). Writes NOTHING to disk -- a read-only
    report; with `load_config` monkeypatched the filesystem is untouched."""
    try:
        dispatch = json.loads(
            pathlib.Path(dispatch_path).expanduser().read_text())
        if not isinstance(dispatch, dict):
            raise ValueError("dispatch config is not a JSON object")
    except Exception as exc:
        # A missing / malformed dispatch config is a real operator problem, not a
        # crash: surface it as ONE synthetic error (errors -> exit 1).
        company = summarize_company_constant_asserts(
            dispatch_path=dispatch_path, products=(), disabled=(),
            errors=((dispatch_path, str(exc)),))
        print(json.dumps(company.to_dict(), indent=2) if as_json
              else company.render())
        return company.exit_code

    products: list[ConstantAssertSummary] = []
    disabled: list[str] = []
    errors: list[tuple[str, str]] = []
    for name, config, enabled in parse_dispatch_work_items(dispatch):
        if not enabled:
            disabled.append(name)      # deliberate; never loaded
            continue
        try:
            # {FOUNDRY} -> foundry root BEFORE load_config, exactly as the
            # dispatcher resolves each work item's config path.
            cfg = load_config(config.replace("{FOUNDRY}", str(FOUNDRY)))
            products.append(gather_constant_asserts(cfg))
        except Exception as exc:
            # One bad team never sinks the whole roll-up -- record + continue.
            errors.append((name, str(exc)))
    company = summarize_company_constant_asserts(
        dispatch_path=dispatch_path, products=tuple(products),
        disabled=tuple(disabled), errors=tuple(errors))
    print(json.dumps(company.to_dict(), indent=2) if as_json else company.render())
    return company.exit_code


# --------------------------------------------------------------------------- #
# Company-wide always-skipped-test roll-up (`company-skipped-tests`) -- roadmap
# item 6, the company view on the iter-56 `gather_skipped_tests` foundation
# (the 7th `company-*` family member).
#
# The QUALITY-axis complement to iter-30's `company-status` (health NOW),
# iter-31's `company-history` (ship LEDGER), iter-40's `company-timing`
# (THROUGHPUT), iter-43's `company-weak-tests` (assertion-FREE tests),
# iter-46's `company-events` (ACTIVITY) and iter-54's `company-constant-asserts`
# (CONSTANT-assert tests): `company-skipped-tests` answers "does ANY team have
# an ALWAYS-SKIPPED test?" -- a `test*` that is UNCONDITIONALLY skipped by
# decorator (`@pytest.mark.skip` / `@unittest.skip`, or a constant-condition
# `@skipif(True)` / `@skipUnless(False)`), so it NEVER runs, validates nothing,
# yet reports the suite green, and no existing gate catches it (the item-11
# fresh-clone re-run passes a skipped test too). It reads the DISPATCH config and
# folds every ENABLED team's iter-56 `skipped-tests` scan into ONE company view
# (summed files-scanned / always-skipped-tests / parse-errors + a per-product
# breakdown), reusing the SHIPPED `gather_skipped_tests` (iter 56) /
# `parse_dispatch_work_items` (iter 30) / frozen `SkippedTestSummary` (iter 56)
# seams -- adds NO new I/O seam, sentinel, config field, or artifact. Purely
# additive and DORMANT: the pipeline / gate / dispatcher NEVER call it and it
# WRITES NOTHING (read-only). UNLIKE the INFORMATIONAL history/timing/events
# roll-ups, it GATES on findings (mirroring the per-product `skipped-tests`
# gate): an always-skipped test OR an unparseable file OR a structural gather
# error ANYWHERE -> exit 1.
#
# ONE correctness divergence from the `company-constant-asserts` reference (NOT
# a copy-paste of its "disjoint" framing): `company-constant-asserts` is DISJOINT
# from `company-weak-tests` by the detectors' construction (a constant assert
# CARRIES an assert node, so an assertion-free scan can never also flag it). But
# an always-skipped test CAN also be assertion-free, so `company-skipped-tests`
# findings CAN OVERLAP both `company-weak-tests` and `company-constant-asserts`.
# It is a THIRD COMPLEMENTARY company lens catching a DIFFERENT antipattern -- a
# test that never RUNS at all -- not a disjoint partition.
# --------------------------------------------------------------------------- #
@dataclasses.dataclass(frozen=True)
class CompanySkippedTests:
    """A one-shot COMPANY-wide always-skipped-test roll-up across a dispatch config.

    Frozen so a computed roll-up can't be mutated after the fact (value equality
    for free, matching the other pure cores). Every derived value is a pure
    property over the stored fields, so the whole verdict -- including the
    scriptable exit code -- follows deterministically from what was gathered, and
    the JSON payload / render text can never disagree with the exit code.

    Fields:
      * `dispatch_path` -- the dispatch config path, echoed into `render()`.
      * `products` -- the per-product `SkippedTestSummary` scans that were
        successfully gathered, IN dispatch-file order (an enabled product that
        failed to load/gather is NOT here -- it lands in `errors`).
      * `disabled` -- names of work items with `enabled=False` (never loaded).
      * `errors` -- `(product, message)` 2-tuples for enabled items that raised
        while loading/gathering (the sole caller guarantees each is a 2-tuple).

    The company totals are SUMS over the gathered products: `files_scanned` /
    `total_findings` sum the same-named per-product fields, `total_parse_errors`
    sums each product's `len(parse_errors)`. `n_flagged` counts gathered products
    that have a finding OR a parse error (the per-product "not clean but scanned"
    signal), giving the operator "how many teams need looking at" at a glance.

    A structural mirror of `CompanyConstantAsserts` (iter 54) differing ONLY in
    the per-product summary type (`SkippedTestSummary` not `ConstantAssertSummary`),
    the gather seam its CLI drives (`gather_skipped_tests`), and the human labels.
    Its ONE correctness divergence from that reference: UNLIKE the DISJOINT
    constant-assert roll-up, an always-skipped test CAN also be assertion-free, so
    this roll-up's findings can OVERLAP `company-weak-tests` /
    `company-constant-asserts` -- a THIRD COMPLEMENTARY company lens catching a
    DIFFERENT antipattern (a test that never RUNS at all), not a disjoint scan.
    """
    dispatch_path: str
    products: tuple[SkippedTestSummary, ...]
    disabled: tuple[str, ...]
    errors: tuple[tuple[str, str], ...]

    @property
    def n_products(self) -> int:
        """Count of products successfully ROLLED UP (an errored enabled product
        is NOT counted here -- it is in `errors`)."""
        return len(self.products)

    @property
    def n_disabled(self) -> int:
        return len(self.disabled)

    @property
    def n_errors(self) -> int:
        return len(self.errors)

    @property
    def files_scanned(self) -> int:
        """Company files scanned = the SUM of every gathered product's
        `files_scanned`."""
        return sum(p.files_scanned for p in self.products)

    @property
    def total_findings(self) -> int:
        """Company always-skipped tests = the SUM of every product's
        `total_findings`."""
        return sum(p.total_findings for p in self.products)

    @property
    def total_parse_errors(self) -> int:
        """Company parse errors = the SUM of every product's own
        `len(parse_errors)` (files that would not parse / read anywhere)."""
        return sum(len(p.parse_errors) for p in self.products)

    @property
    def n_flagged(self) -> int:
        """How many GATHERED products have a finding OR a parse error -- the
        per-product "scanned but not clean" signal, so an operator sees "how many
        teams need looking at" without expanding the breakdown."""
        return sum(1 for p in self.products
                   if p.total_findings > 0 or p.parse_errors)

    @property
    def exit_code(self) -> int:
        """Scriptable verdict, findings-first (UNLIKE informational
        history/timing/events): `1` when `errors` is non-empty (a structural
        gather failure) OR `total_findings > 0` (an always-skipped test) OR
        `total_parse_errors > 0` (an unparseable file) ANYWHERE -- all three
        gate, mirroring the per-product `skipped-tests` exit code; else `2`
        when NO products were gathered (every item disabled or `work_items` empty
        -- reachable only with `errors` empty and no findings); else `0` (clean).

        A gathered product that scanned ZERO test files (its own
        `SkippedTestSummary.exit_code == 2`) does NOT force company exit 2 --
        it still counts in `n_products`, so with no findings/parse-errors/
        structural-errors the company exits 0 (mirroring `company-constant-asserts`
        / `company-weak-tests`, where a product with zero scanned files does not
        force exit 2)."""
        if self.errors or self.total_findings > 0 or self.total_parse_errors > 0:
            return 1
        if self.n_products == 0:
            return 2
        return 0

    @property
    def verdict(self) -> str:
        """The single human token for the current `exit_code` -- `"clean"` (0) /
        `"ATTENTION"` (1) / `"no enabled products"` (2). ONE source of truth for
        both `render()`'s last line and the JSON `verdict` key, so the text and
        the machine payload can never drift from the exit code. NOTE these are the
        COMPANY tokens, NOT the per-product `SkippedTestSummary` token
        `"ALWAYS-SKIPPED TESTS FOUND"`."""
        return {0: "clean", 1: "ATTENTION", 2: "no enabled products"}[self.exit_code]

    def _rollup(self) -> str:
        """The company always-skipped rollup as a substring: `{files_scanned}
        files scanned, {total_findings} always-skipped tests, {total_parse_errors}
        parse errors` -- the summed counts only (per-team leaf findings live in
        the per-product breakdown / `to_dict()`, keeping the report bounded like
        `company-constant-asserts` / `company-weak-tests`)."""
        return (f"{self.files_scanned} files scanned, "
                f"{self.total_findings} always-skipped tests, "
                f"{self.total_parse_errors} parse errors")

    def render(self) -> str:
        """A deterministic multi-line company always-skipped report (the CLI's
        contract).

        Contains, as substrings: the literal `foundry company-skipped-tests`;
        the `dispatch_path`; a counts line reporting `{n_products} gathered`,
        `{n_disabled} disabled`, `{n_errors} error(s)` PLUS the company rollup
        (`{files_scanned} files scanned, {total_findings} always-skipped tests,
        {total_parse_errors} parse errors`); ONE line per gathered product
        beginning `  - {product}:` carrying its OWN `{p.files_scanned} files
        scanned, {p.total_findings} always-skipped, {len(p.parse_errors)} parse
        error(s)` (per-product COUNTS only, NOT each `(file :: test)` leaf); one
        `  - {name}: disabled` line per disabled item; one `  - {name}: ERROR
        {message}` line per error; and a final `verdict:` line whose token EQUALS
        `verdict`."""
        lines = [
            "foundry company-skipped-tests",
            f"  dispatch config: {self.dispatch_path}",
            f"  products: {self.n_products} gathered, "
            f"{self.n_disabled} disabled, {self.n_errors} error(s) -- "
            f"{self._rollup()}",
        ]
        for p in self.products:
            lines.append(
                f"  - {p.product}: {p.files_scanned} files scanned, "
                f"{p.total_findings} always-skipped, "
                f"{len(p.parse_errors)} parse error(s)")
        for name in self.disabled:
            lines.append(f"  - {name}: disabled")
        for name, message in self.errors:
            lines.append(f"  - {name}: ERROR {message}")
        lines.append(f"verdict: {self.verdict}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """A pure, JSON-safe company roll-up for machine consumers -- a dashboard
        / cron alert / the reporter. `products` carries the FULL per-product
        `SkippedTestSummary.to_dict()` payload (the 8-key per-team detail
        INCLUDING each team's `findings`/`parse_errors` leaf arrays) in stored
        order, so no leaf detail is lost even though `render()` prints per-product
        counts only. Every derived value REUSES the frozen properties, so the
        payload can never disagree with `render()` or the exit code, and every
        value is JSON-native, so it round-trips through
        `json.loads(json.dumps(...))` -- including when `products`/`disabled`/
        `errors` are all empty. Pure: touches no filesystem."""
        return {
            "dispatch_config": self.dispatch_path,
            "products": [p.to_dict() for p in self.products],
            "disabled": list(self.disabled),
            "errors": [{"product": name, "message": message}
                       for name, message in self.errors],
            "n_products": self.n_products,
            "n_disabled": self.n_disabled,
            "n_errors": self.n_errors,
            "n_flagged": self.n_flagged,
            "files_scanned": self.files_scanned,
            "total_findings": self.total_findings,
            "total_parse_errors": self.total_parse_errors,
            "exit_code": self.exit_code,
            "verdict": self.verdict,
        }


def summarize_company_skipped_tests(*, dispatch_path: str,
                                    products: tuple[SkippedTestSummary, ...],
                                    disabled: tuple[str, ...],
                                    errors: tuple[tuple[str, str], ...],
                                    ) -> CompanySkippedTests:
    """Pure keyword-only constructor for a `CompanySkippedTests` (Behaviors 1-5).

    A thin, total wrapper that packs the gathered scans into the frozen roll-up
    -- keyword-only so a caller can never transpose the fields by position, and
    it never raises for well-formed inputs (each `errors` entry is a
    `(product, message)` 2-tuple, which the sole caller
    `company_skipped_tests_cli` guarantees; documenting the precondition keeps
    the "never raises" contract airtight). Kept separate from
    `company_skipped_tests_cli` so the decision core stays a pure function the
    tester can drive without any filesystem."""
    return CompanySkippedTests(
        dispatch_path=dispatch_path,
        products=tuple(products),
        disabled=tuple(disabled),
        errors=tuple((name, message) for name, message in errors))


def company_skipped_tests_cli(dispatch_path: str, as_json: bool = False) -> int:
    """On-demand CLI: roll every ENABLED team's always-skipped-test scan into ONE
    company quality view (roadmap item 6, the 7th `company-*` member).

    Reads the DISPATCH config at `dispatch_path` (`foundry.config.json`, NOT a
    product config), then for each ENABLED work item substitutes a `{FOUNDRY}`
    token in its config path to the foundry root and loads + scans that product
    via the `load_config` / `gather_skipped_tests` seams (both called by BARE
    name so a `monkeypatch.setattr(foundry, ...)` bites). A DISABLED item is
    recorded in `disabled` (by name) and never loaded.

    Resilient (Behaviors 6-7): if reading/parsing the dispatch config fails
    (missing / not JSON / not an object) it prints a report recording ONE
    synthetic error and returns exit 1; if a single work item's `load_config` or
    `gather_skipped_tests` raises, that item is recorded in `errors` and the
    roll-up CONTINUES scanning the rest (company exit 1). No exception ever
    propagates.

    With `as_json=True` stdout is exactly ONE `json.dumps(to_dict(), indent=2)`
    document; either way the RETURN value is the same
    `CompanySkippedTests.exit_code` (0 clean / 1 findings-or-parse-errors-or-
    team-errored / 2 no-enabled-products). Writes NOTHING to disk -- a read-only
    report; with `load_config` monkeypatched the filesystem is untouched.

    UNLIKE the DISJOINT `company-constant-asserts`, an always-skipped test CAN
    also be assertion-free, so this roll-up's findings can OVERLAP
    `company-weak-tests` / `company-constant-asserts` -- a THIRD COMPLEMENTARY
    company lens catching a DIFFERENT antipattern (a test that never RUNS at
    all)."""
    try:
        dispatch = json.loads(
            pathlib.Path(dispatch_path).expanduser().read_text())
        if not isinstance(dispatch, dict):
            raise ValueError("dispatch config is not a JSON object")
    except Exception as exc:
        # A missing / malformed dispatch config is a real operator problem, not a
        # crash: surface it as ONE synthetic error (errors -> exit 1).
        company = summarize_company_skipped_tests(
            dispatch_path=dispatch_path, products=(), disabled=(),
            errors=((dispatch_path, str(exc)),))
        print(json.dumps(company.to_dict(), indent=2) if as_json
              else company.render())
        return company.exit_code

    products: list[SkippedTestSummary] = []
    disabled: list[str] = []
    errors: list[tuple[str, str]] = []
    for name, config, enabled in parse_dispatch_work_items(dispatch):
        if not enabled:
            disabled.append(name)      # deliberate; never loaded
            continue
        try:
            # {FOUNDRY} -> foundry root BEFORE load_config, exactly as the
            # dispatcher resolves each work item's config path.
            cfg = load_config(config.replace("{FOUNDRY}", str(FOUNDRY)))
            products.append(gather_skipped_tests(cfg))
        except Exception as exc:
            # One bad team never sinks the whole roll-up -- record + continue.
            errors.append((name, str(exc)))
    company = summarize_company_skipped_tests(
        dispatch_path=dispatch_path, products=tuple(products),
        disabled=tuple(disabled), errors=tuple(errors))
    print(json.dumps(company.to_dict(), indent=2) if as_json else company.render())
    return company.exit_code


# --------------------------------------------------------------------------- #
# Company-wide COMPOSITE test-quality roll-up (`company-test-quality`) --
# roadmap item 6, the COMPANY-axis parallel of the iter-58 per-product
# `test-quality` composite (the 8th `company-*` family member and the
# QUALITY-axis capstone of the company family).
#
# All three offline "validates-nothing" detectors now have detector +
# per-product CLI + company roll-up (weak-tests 22/23/43, constant-asserts
# 47/48/54, skipped-tests 55/56/57) AND iter 58 shipped the per-product
# COMPOSITE `test-quality` (#25) folding all three into ONE per-product gate.
# This is the LONE missing surface: the COMPANY-axis composite. To certify the
# WHOLE company against all three antipatterns an operator/cron must otherwise
# run THREE separate company commands (`company-weak-tests` #19,
# `company-constant-asserts` #22, `company-skipped-tests` #24), each iterating
# the dispatch config, each with its OWN 0/1/2 exit code a shell `&&` collapses
# into one undifferentiated non-zero AND loses the per-category + per-team
# breakdown. This reads the DISPATCH config and folds every ENABLED team's
# iter-58 `test-quality` composite into ONE company view (summed files-scanned /
# per-category findings / total findings / parse-errors + a per-product
# breakdown), driving a NEW `gather_test_quality` seam that composes the SHIPPED
# `gather_weak_tests` / `gather_constant_asserts` / `gather_skipped_tests`
# (iters 42/48/56) via `summarize_test_quality` -- it adds NO new I/O seam,
# sentinel, config field, or artifact. Purely additive and DORMANT: the
# pipeline / gate / dispatcher NEVER call it and it WRITES NOTHING (read-only).
# UNLIKE the INFORMATIONAL history/timing/events roll-ups it GATES on findings
# (mirroring the per-product `test-quality` gate): a quality finding of ANY
# category OR an unparseable file OR a structural gather error ANYWHERE ->
# exit 1.
#
# OVERLAP (a first-class correctness item, NOT a copy of any "disjoint"
# framing): `constant-asserts` is DISJOINT from `weak-tests` by the detectors'
# construction (a constant assert CARRIES an assert node, so an assertion-free
# scan can never also flag it). BUT an always-skipped test CAN also be
# assertion-free AND can carry a constant assert, so a #24 always-skipped
# finding CAN OVERLAP #19 `company-weak-tests` / #22 `company-constant-asserts`.
# Therefore the company `total_findings` (and its per-category components)
# INHERITS the per-product #25 composite's category-weighting: a test flagged by
# two lenses counts once in EACH category -- a company-wide per-CATEGORY triage
# total, intentionally NOT a de-duplicated distinct-test count. This is the
# COMPANY-axis parallel of the per-product #25 composite, folding the three
# company quality axes #19/#22/#24 into ONE view.
# --------------------------------------------------------------------------- #
@dataclasses.dataclass(frozen=True)
class CompanyTestQuality:
    """A one-shot COMPANY-wide composite test-quality roll-up across a dispatch
    config.

    Frozen so a computed roll-up can't be mutated after the fact (value equality
    for free, matching the other pure cores). Every derived value is a pure
    property over the stored fields, so the whole verdict -- including the
    scriptable exit code -- follows deterministically from what was gathered, and
    the JSON payload / render text can never disagree with the exit code.

    Fields:
      * `dispatch_path` -- the dispatch config path, echoed into `render()`.
      * `products` -- the per-product `TestQualitySummary` composite scans that
        were successfully gathered, IN dispatch-file order (an enabled product
        that failed to load/gather is NOT here -- it lands in `errors`).
      * `disabled` -- names of work items with `enabled=False` (never loaded).
      * `errors` -- `(product, message)` 2-tuples for enabled items that raised
        while loading/gathering (the sole caller guarantees each is a 2-tuple).

    The company totals are SUMS over the gathered products: `files_scanned` /
    `total_weak_findings` / `total_constant_findings` / `total_skipped_findings`
    / `total_findings` sum the same-named per-product fields, `total_parse_errors`
    sums each product's `total_parse_errors`. `n_flagged` counts gathered
    products that have a finding OR a parse error (the per-product "not clean but
    scanned" signal), giving the operator "how many teams need looking at" at a
    glance.

    A structural mirror of `CompanySkippedTests` (iter 57) differing ONLY in the
    per-product summary type (`TestQualitySummary` not `SkippedTestSummary`), the
    gather seam its CLI drives (`gather_test_quality`), and the per-CATEGORY
    breakdown (a composite carries three finding categories, not one).

    OVERLAP (NOT a copy of any "disjoint" framing): this is the COMPANY-axis
    parallel of the per-product #25 `test-quality` composite, folding the three
    company quality axes #19 `company-weak-tests` / #22 `company-constant-asserts`
    / #24 `company-skipped-tests` into ONE view and INHERITING #25's
    category-weighting. `constant-asserts` is DISJOINT from `weak-tests` by
    construction, BUT an always-skipped test CAN also be assertion-free AND carry
    a constant assert, so a #24 finding can OVERLAP #19/#22 -- therefore
    `total_findings` is a per-CATEGORY triage total in which a test flagged by two
    lenses counts once in EACH category, NOT a de-duplicated distinct-test count.
    """
    dispatch_path: str
    products: tuple[TestQualitySummary, ...]
    disabled: tuple[str, ...]
    errors: tuple[tuple[str, str], ...]

    @property
    def n_products(self) -> int:
        """Count of products successfully ROLLED UP (an errored enabled product
        is NOT counted here -- it is in `errors`)."""
        return len(self.products)

    @property
    def n_disabled(self) -> int:
        return len(self.disabled)

    @property
    def n_errors(self) -> int:
        return len(self.errors)

    @property
    def files_scanned(self) -> int:
        """Company files scanned = the SUM of every gathered product's
        `files_scanned` (each product's composite files-scanned == its weak
        sub-scan's count, all three lenses walking the identical set)."""
        return sum(p.files_scanned for p in self.products)

    @property
    def total_weak_findings(self) -> int:
        """Company assertion-free tests = the SUM of every product's
        `weak_findings`."""
        return sum(p.weak_findings for p in self.products)

    @property
    def total_constant_findings(self) -> int:
        """Company constant-assert tests = the SUM of every product's
        `constant_findings`."""
        return sum(p.constant_findings for p in self.products)

    @property
    def total_skipped_findings(self) -> int:
        """Company always-skipped tests = the SUM of every product's
        `skipped_findings`."""
        return sum(p.skipped_findings for p in self.products)

    @property
    def total_findings(self) -> int:
        """Company quality findings = the SUM of every product's category-weighted
        `total_findings`.

        Each per-product `total_findings` is ALREADY category-weighted (a test
        flagged by two lenses counts once per category -- see the class OVERLAP
        note), so this company total INHERITS that weighting: it is a company-wide
        per-CATEGORY triage total, NOT a de-duplicated distinct-test count."""
        return sum(p.total_findings for p in self.products)

    @property
    def total_parse_errors(self) -> int:
        """Company parse errors = the SUM of every product's own
        `total_parse_errors` (each the deduped `(file, message)` union for that
        product across its three lenses)."""
        return sum(p.total_parse_errors for p in self.products)

    @property
    def n_flagged(self) -> int:
        """How many GATHERED products have a finding OR a parse error -- the
        per-product "scanned but not clean" signal, so an operator sees "how many
        teams need looking at" without expanding the breakdown."""
        return sum(1 for p in self.products
                   if p.total_findings > 0 or p.parse_errors)

    @property
    def exit_code(self) -> int:
        """Scriptable verdict, findings-first (UNLIKE informational
        history/timing/events; mirroring `company-skipped-tests`): `1` when
        `errors` is non-empty (a structural gather failure) OR `total_findings >
        0` (a quality finding of ANY category) OR `total_parse_errors > 0` (an
        unparseable file) ANYWHERE -- all three gate; else `2` when NO products
        were gathered (every item disabled or `work_items` empty -- reachable only
        with `errors` empty and no findings); else `0` (clean).

        A gathered product that scanned ZERO test files (its own composite
        `TestQualitySummary.exit_code == 2`) does NOT force company exit 2 -- it
        still counts in `n_products`, so with no findings/parse-errors/structural-
        errors the company exits 0 (mirroring `company-skipped-tests` /
        `company-constant-asserts`)."""
        if self.errors or self.total_findings > 0 or self.total_parse_errors > 0:
            return 1
        if self.n_products == 0:
            return 2
        return 0

    @property
    def verdict(self) -> str:
        """The single human token for the current `exit_code` -- `"clean"` (0) /
        `"ATTENTION"` (1) / `"no enabled products"` (2). ONE source of truth for
        both `render()`'s last line and the JSON `verdict` key, so the text and
        the machine payload can never drift from the exit code. NOTE these are the
        COMPANY tokens, NOT the per-product `TestQualitySummary` composite tokens
        (`clean` / `QUALITY ISSUES FOUND` / `nothing to scan`)."""
        return {0: "clean", 1: "ATTENTION", 2: "no enabled products"}[self.exit_code]

    def _rollup(self) -> str:
        """The company composite rollup as a substring: `{files_scanned} files
        scanned, {total_weak_findings} assertion-free, {total_constant_findings}
        constant-assert, {total_skipped_findings} always-skipped, {total_findings}
        total quality findings, {total_parse_errors} parse errors` -- the summed
        per-category counts only (per-team leaf findings live in the per-product
        breakdown / `to_dict()`, keeping the report bounded like
        `company-skipped-tests`)."""
        return (f"{self.files_scanned} files scanned, "
                f"{self.total_weak_findings} assertion-free, "
                f"{self.total_constant_findings} constant-assert, "
                f"{self.total_skipped_findings} always-skipped, "
                f"{self.total_findings} total quality findings, "
                f"{self.total_parse_errors} parse errors")

    def render(self) -> str:
        """A deterministic multi-line company composite report (the CLI's
        contract).

        Contains, as substrings: the literal `foundry company-test-quality`; the
        `dispatch_path`; a counts line reporting `{n_products} gathered`,
        `{n_disabled} disabled`, `{n_errors} error(s)` PLUS the company rollup
        (`{files_scanned} files scanned, {total_weak_findings} assertion-free,
        {total_constant_findings} constant-assert, {total_skipped_findings}
        always-skipped, {total_findings} total quality findings,
        {total_parse_errors} parse errors`); ONE line per gathered product
        beginning `  - {product}:` carrying its OWN `{p.files_scanned} files
        scanned, {p.weak_findings} assertion-free, {p.constant_findings}
        constant-assert, {p.skipped_findings} always-skipped, {p.total_findings}
        total, {p.total_parse_errors} parse error(s)` (per-product per-category
        COUNTS only, NOT each `(file :: test)` leaf); one `  - {name}: disabled`
        line per disabled item; one `  - {name}: ERROR {message}` line per error;
        and a final `verdict:` line whose token EQUALS `verdict`."""
        lines = [
            "foundry company-test-quality",
            f"  dispatch config: {self.dispatch_path}",
            f"  products: {self.n_products} gathered, "
            f"{self.n_disabled} disabled, {self.n_errors} error(s) -- "
            f"{self._rollup()}",
        ]
        for p in self.products:
            lines.append(
                f"  - {p.product}: {p.files_scanned} files scanned, "
                f"{p.weak_findings} assertion-free, "
                f"{p.constant_findings} constant-assert, "
                f"{p.skipped_findings} always-skipped, "
                f"{p.total_findings} total, "
                f"{p.total_parse_errors} parse error(s)")
        for name in self.disabled:
            lines.append(f"  - {name}: disabled")
        for name, message in self.errors:
            lines.append(f"  - {name}: ERROR {message}")
        lines.append(f"verdict: {self.verdict}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """A pure, JSON-safe company roll-up for machine consumers -- a dashboard
        / cron alert / the reporter. `products` carries the FULL per-product
        `TestQualitySummary.to_dict()` payload (the composite per-team detail
        INCLUDING each team's three sub-documents + leaf finding/parse-error
        arrays) in stored order, so no leaf detail is lost even though `render()`
        prints per-product counts only. Every derived value REUSES the frozen
        properties, so the payload can never disagree with `render()` or the exit
        code, and every value is JSON-native, so it round-trips through
        `json.loads(json.dumps(...))` -- including when `products`/`disabled`/
        `errors` are all empty. Pure: touches no filesystem."""
        return {
            "dispatch_config": self.dispatch_path,
            "products": [p.to_dict() for p in self.products],
            "disabled": list(self.disabled),
            "errors": [{"product": name, "message": message}
                       for name, message in self.errors],
            "n_products": self.n_products,
            "n_disabled": self.n_disabled,
            "n_errors": self.n_errors,
            "n_flagged": self.n_flagged,
            "files_scanned": self.files_scanned,
            "total_weak_findings": self.total_weak_findings,
            "total_constant_findings": self.total_constant_findings,
            "total_skipped_findings": self.total_skipped_findings,
            "total_findings": self.total_findings,
            "total_parse_errors": self.total_parse_errors,
            "exit_code": self.exit_code,
            "verdict": self.verdict,
        }


def summarize_company_test_quality(*, dispatch_path: str,
                                   products: tuple[TestQualitySummary, ...],
                                   disabled: tuple[str, ...],
                                   errors: tuple[tuple[str, str], ...],
                                   ) -> CompanyTestQuality:
    """Pure keyword-only constructor for a `CompanyTestQuality` (Behaviors 1-6).

    A thin, total wrapper that packs the gathered composite scans into the frozen
    roll-up -- keyword-only so a caller can never transpose the fields by
    position, and it never raises for well-formed inputs (each `errors` entry is
    a `(product, message)` 2-tuple, which the sole caller
    `company_test_quality_cli` guarantees; documenting the precondition keeps the
    "never raises" contract airtight). Kept separate from
    `company_test_quality_cli` so the decision core stays a pure function the
    tester can drive without any filesystem."""
    return CompanyTestQuality(
        dispatch_path=dispatch_path,
        products=tuple(products),
        disabled=tuple(disabled),
        errors=tuple((name, message) for name, message in errors))


def company_test_quality_cli(dispatch_path: str, as_json: bool = False) -> int:
    """On-demand CLI: roll every ENABLED team's COMPOSITE test-quality scan into
    ONE company quality view (roadmap item 6, the 8th `company-*` member and the
    QUALITY-axis capstone of the company family).

    Reads the DISPATCH config at `dispatch_path` (`foundry.config.json`, NOT a
    product config), then for each ENABLED work item substitutes a `{FOUNDRY}`
    token in its config path to the foundry root and loads + scans that product
    via the `load_config` / `gather_test_quality` seams (both called by BARE name
    so a `monkeypatch.setattr(foundry, ...)` bites). A DISABLED item is recorded
    in `disabled` (by name) and never loaded.

    Resilient (Behaviors 7-8): if reading/parsing the dispatch config fails
    (missing / not JSON / not an object) it prints a report recording ONE
    synthetic error and returns exit 1; if a single work item's `load_config` or
    `gather_test_quality` raises, that item is recorded in `errors` and the
    roll-up CONTINUES scanning the rest (company exit 1). No exception ever
    propagates.

    With `as_json=True` stdout is exactly ONE `json.dumps(to_dict(), indent=2)`
    document; either way the RETURN value is the same `CompanyTestQuality.
    exit_code` (0 clean / 1 findings-or-parse-errors-or-team-errored / 2
    no-enabled-products). Writes NOTHING to disk -- a read-only report; with
    `load_config` monkeypatched the filesystem is untouched.

    This is the COMPANY-axis parallel of the per-product #25 `test-quality`
    composite, folding the three company quality axes #19 `company-weak-tests` /
    #22 `company-constant-asserts` / #24 `company-skipped-tests` into ONE view and
    INHERITING #25's category-weighting -- a #24 always-skipped finding CAN
    OVERLAP #19/#22 (an always-skipped test may also be assertion-free), so the
    company `total_findings` is a per-CATEGORY triage total, NOT a de-duplicated
    distinct-test count."""
    try:
        dispatch = json.loads(
            pathlib.Path(dispatch_path).expanduser().read_text())
        if not isinstance(dispatch, dict):
            raise ValueError("dispatch config is not a JSON object")
    except Exception as exc:
        # A missing / malformed dispatch config is a real operator problem, not a
        # crash: surface it as ONE synthetic error (errors -> exit 1).
        company = summarize_company_test_quality(
            dispatch_path=dispatch_path, products=(), disabled=(),
            errors=((dispatch_path, str(exc)),))
        print(json.dumps(company.to_dict(), indent=2) if as_json
              else company.render())
        return company.exit_code

    products: list[TestQualitySummary] = []
    disabled: list[str] = []
    errors: list[tuple[str, str]] = []
    for name, config, enabled in parse_dispatch_work_items(dispatch):
        if not enabled:
            disabled.append(name)      # deliberate; never loaded
            continue
        try:
            # {FOUNDRY} -> foundry root BEFORE load_config, exactly as the
            # dispatcher resolves each work item's config path.
            cfg = load_config(config.replace("{FOUNDRY}", str(FOUNDRY)))
            products.append(gather_test_quality(cfg))
        except Exception as exc:
            # One bad team never sinks the whole roll-up -- record + continue.
            errors.append((name, str(exc)))
    company = summarize_company_test_quality(
        dispatch_path=dispatch_path, products=tuple(products),
        disabled=tuple(disabled), errors=tuple(errors))
    print(json.dumps(company.to_dict(), indent=2) if as_json else company.render())
    return company.exit_code


# --------------------------------------------------------------------------- #
# Company-wide product-config lint roll-up (`company-lint-config`) -- roadmap
# item 6 family, the 9th `company-*` member and the CONFIG-VALIDATION-axis fleet
# roll-up.
#
# iter 60 shipped the per-product `lint-config` (#27): an offline, deterministic
# linter that inspects ONE resolved `ProductConfig` for the misconfigurations
# that silently waste a shift or defeat the push guard. But answering "are ALL my
# fleet's product configs sound?" meant running `lint-config` once per team and
# mentally merging N exit codes -- the scattered babysitting the VISION targets.
# Every OTHER read-only per-product probe already has a company roll-up
# (`company-status` 30 / `-history` 31 / `-timing` 40 / `-weak-tests` 43 /
# `-events` 46 / `-constant-asserts` 54 / `-skipped-tests` 57 / `-test-quality`
# 59); `lint-config` was the LONE read-only per-product probe with no roll-up.
# `company-lint-config` closes that asymmetry: read the DISPATCH config, fold
# every ENABLED team's iter-27 `lint-config` verdict into ONE fleet view (summed
# config-errors / warnings / total-findings + a per-team breakdown) and ONE
# scriptable exit code, so an operator can gate the whole fleet on
# `[ $? -eq 0 ]`. The highest-value finding is the SAFETY case -- a team whose
# `allowed_push_repo` is empty while `push_enabled` is true would silently block
# EVERY ship -- surfaced across all teams at once.
#
# KEY correctness divergence from the QUALITY roll-ups (`company-weak-tests` /
# `-constant-asserts` / `-skipped-tests` / `-test-quality`, which gate on ANY
# finding): `company-lint-config` INHERITS the per-product `ConfigLint` semantics
# where ONLY ERRORS gate -- WARNINGS ALONE STILL PASS. A warning names a
# degraded-but-runnable config (a missing roadmap the PM creates on iter 1), so a
# fleet of warnings-only configs is still shippable. The exit code is `1` iff a
# team load/gather ERROR OR any product config ERROR, else `2` if no enabled
# products, else `0`; warnings never change the exit code or the company verdict
# but ARE surfaced in the counts line, the per-team breakdown (each team's
# OK/WARNINGS/PROBLEMS token), and `to_dict()` via `total_warnings`.
#
# DORMANT -- the pipeline / gate / dispatcher NEVER call it and it writes nothing
# (exit 0 clean-or-warnings-only / 1 config-errors-or-team-errored /
# 2 no-enabled-products); read-only.
# --------------------------------------------------------------------------- #
@dataclasses.dataclass(frozen=True)
class CompanyConfigLint:
    """A one-shot COMPANY-wide product-config lint roll-up across a dispatch
    config.

    Frozen so a computed roll-up can't be mutated after the fact (value equality
    for free, matching the other pure cores). Every derived value is a pure
    property over the stored fields, so the whole verdict -- including the
    scriptable exit code -- follows deterministically from what was gathered, and
    the JSON payload / render text can never disagree with the exit code.

    Fields:
      * `dispatch_path` -- the dispatch config path, echoed into `render()`.
      * `products` -- the per-product `ConfigLint` verdicts that were
        successfully gathered, IN dispatch-file order (an enabled product that
        failed to load/gather is NOT here -- it lands in `errors`).
      * `disabled` -- names of work items with `enabled=False` (never loaded).
      * `errors` -- `(product, message)` 2-tuples for enabled items that raised
        while loading/gathering (the sole caller guarantees each is a 2-tuple).

    The company totals are SUMS over the gathered products: `total_errors` sums
    each product's `n_errors`, `total_warnings` sums each `n_warnings`, and
    `total_findings` sums `len(p.findings)` (== `total_errors + total_warnings`).
    `n_flagged` counts gathered products with a config ERROR (`n_errors > 0`) --
    NOT warnings-only teams, mirroring the per-product `ConfigLint.ok` where a
    warning never fails the verdict.

    A structural mirror of `CompanyTestQuality` (iter 59) / `CompanySkippedTests`
    (iter 57) differing in the per-product summary type (`ConfigLint`), the gather
    seam its CLI drives (`gather_config_lint`), and -- the load-bearing divergence
    -- the exit-code gate: the QUALITY roll-ups gate on ANY finding, but this one
    gates ONLY on ERRORS (a team load/gather failure or a product config error);
    WARNINGS alone still PASS (exit 0 / verdict "clean"), because a warning names
    a degraded-but-runnable config.
    """
    dispatch_path: str
    products: tuple[ConfigLint, ...]
    disabled: tuple[str, ...]
    errors: tuple[tuple[str, str], ...]

    @property
    def n_products(self) -> int:
        """Count of products successfully ROLLED UP (an errored enabled product
        is NOT counted here -- it is in `errors`)."""
        return len(self.products)

    @property
    def n_disabled(self) -> int:
        return len(self.disabled)

    @property
    def n_errors(self) -> int:
        """How many TEAMS failed to load/gather (a STRUCTURAL error), NOT the
        count of config error-level findings (that is `total_errors`)."""
        return len(self.errors)

    @property
    def total_errors(self) -> int:
        """Company config errors = the SUM of every gathered product's `n_errors`
        (error-level findings). These GATE the company exit code."""
        return sum(p.n_errors for p in self.products)

    @property
    def total_warnings(self) -> int:
        """Company config warnings = the SUM of every gathered product's
        `n_warnings` (warn-level findings). Surfaced but NON-gating."""
        return sum(p.n_warnings for p in self.products)

    @property
    def total_findings(self) -> int:
        """Company config findings = the SUM of every gathered product's finding
        count (== `total_errors + total_warnings`)."""
        return sum(len(p.findings) for p in self.products)

    @property
    def n_flagged(self) -> int:
        """How many GATHERED products carry a config ERROR (`n_errors > 0`) -- the
        teams whose config would break or silently defeat a shift. A
        warnings-only team is NOT flagged (mirroring the per-product
        `ConfigLint.ok`), so an operator sees "how many teams must be FIXED"
        without counting the merely-degraded ones."""
        return sum(1 for p in self.products if p.n_errors > 0)

    @property
    def exit_code(self) -> int:
        """Scriptable verdict, findings-first but ERROR-ONLY-gating (the
        load-bearing divergence from the QUALITY roll-ups): `1` when `errors` is
        non-empty (a team load/gather failure) OR `total_errors > 0` (any product
        config ERROR) ANYWHERE; else `2` when NO products were gathered (every
        item disabled or `work_items` empty -- reachable only with `errors` empty
        and no config errors); else `0` (clean OR warnings-only).

        WARNINGS DO NOT GATE: a fleet whose gathered products carry only
        warn-level findings exits 0 (mirroring the per-product `ConfigLint` where
        a warning names a degraded-but-runnable config). A warnings-only gathered
        product (its own `ConfigLint.exit_code == 0`) counts in `n_products` and
        never forces exit 1 or 2."""
        if self.errors or self.total_errors > 0:
            return 1
        if self.n_products == 0:
            return 2
        return 0

    @property
    def verdict(self) -> str:
        """The single human token for the current `exit_code` -- `"clean"` (0) /
        `"ATTENTION"` (1) / `"no enabled products"` (2). ONE source of truth for
        both `render()`'s last line and the JSON `verdict` key, so text and
        machine payload never drift from the exit code. NOTE these are the COMPANY
        tokens, NOT the per-product `ConfigLint` tokens (`OK` / `WARNINGS` /
        `PROBLEMS`)."""
        return {0: "clean", 1: "ATTENTION", 2: "no enabled products"}[self.exit_code]

    def _rollup(self) -> str:
        """The company rollup as a substring: `{total_errors} config errors,
        {total_warnings} warnings, {total_findings} total findings` -- the summed
        counts only (per-team leaf findings live in the per-product breakdown /
        `to_dict()`, keeping the report bounded like the other `company-*`
        members)."""
        return (f"{self.total_errors} config errors, "
                f"{self.total_warnings} warnings, "
                f"{self.total_findings} total findings")

    def render(self) -> str:
        """A deterministic multi-line company config-lint report (the CLI's
        contract).

        Contains, as substrings: the literal `foundry company-lint-config`; the
        `dispatch_path`; a counts line reporting `{n_products} gathered`,
        `{n_disabled} disabled`, `{n_errors} error(s)` PLUS the company rollup
        (`{total_errors} config errors, {total_warnings} warnings,
        {total_findings} total findings`); ONE line per gathered product
        beginning `  - {p.config_path}:` carrying its OWN `{p.n_errors} error(s),
        {p.n_warnings} warning(s)` and its per-product `verdict` token
        (`OK`/`WARNINGS`/`PROBLEMS`); one `  - {name}: disabled` line per disabled
        item; one `  - {name}: ERROR {message}` line per team error; and a FINAL
        `verdict:` line whose token EQUALS `verdict`. Detail above the sentinel,
        so "last non-empty line == verdict" always holds."""
        lines = [
            "foundry company-lint-config",
            f"  dispatch config: {self.dispatch_path}",
            f"  products: {self.n_products} gathered, "
            f"{self.n_disabled} disabled, {self.n_errors} error(s) -- "
            f"{self._rollup()}",
        ]
        for p in self.products:
            lines.append(
                f"  - {p.config_path}: {p.n_errors} error(s), "
                f"{p.n_warnings} warning(s) [{p.verdict}]")
        for name in self.disabled:
            lines.append(f"  - {name}: disabled")
        for name, message in self.errors:
            lines.append(f"  - {name}: ERROR {message}")
        lines.append(f"verdict: {self.verdict}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """A pure, JSON-safe company roll-up for machine consumers -- a dashboard
        / cron alert / the reporter. `products` carries the FULL per-product
        `ConfigLint.to_dict()` payload (each team's findings + counts + verdict)
        in stored order, so no leaf detail is lost even though `render()` prints
        per-product counts only. Every derived value REUSES the frozen properties,
        so the payload can never disagree with `render()` or the exit code, and
        every value is JSON-native so it round-trips through
        `json.loads(json.dumps(...))` -- including when `products`/`disabled`/
        `errors` are all empty. EXACTLY these 13 keys in this fixed order. Pure:
        touches no filesystem."""
        return {
            "dispatch_config": self.dispatch_path,
            "products": [p.to_dict() for p in self.products],
            "disabled": list(self.disabled),
            "errors": [{"product": name, "message": message}
                       for name, message in self.errors],
            "n_products": self.n_products,
            "n_disabled": self.n_disabled,
            "n_errors": self.n_errors,
            "n_flagged": self.n_flagged,
            "total_errors": self.total_errors,
            "total_warnings": self.total_warnings,
            "total_findings": self.total_findings,
            "exit_code": self.exit_code,
            "verdict": self.verdict,
        }


def summarize_company_config_lint(*, dispatch_path: str,
                                  products: tuple[ConfigLint, ...],
                                  disabled: tuple[str, ...],
                                  errors: tuple[tuple[str, str], ...],
                                  ) -> CompanyConfigLint:
    """Pure keyword-only constructor for a `CompanyConfigLint` (Behaviors 1-6).

    A thin, total wrapper that packs the gathered lint verdicts into the frozen
    roll-up -- keyword-only so a caller can never transpose the fields by
    position, and it never raises for well-formed inputs (each `errors` entry is
    a `(product, message)` 2-tuple, which the sole caller
    `company_config_lint_cli` guarantees). Kept separate from
    `company_config_lint_cli` so the decision core stays a pure function the
    tester can drive without any filesystem."""
    return CompanyConfigLint(
        dispatch_path=dispatch_path,
        products=tuple(products),
        disabled=tuple(disabled),
        errors=tuple((name, message) for name, message in errors))


def company_config_lint_cli(dispatch_path: str, as_json: bool = False) -> int:
    """On-demand CLI: roll every ENABLED team's product-config lint into ONE
    company config-validation view (roadmap item 6 family, the 9th `company-*`
    member and the CONFIG-VALIDATION-axis fleet roll-up).

    Reads the DISPATCH config at `dispatch_path` (`foundry.config.json`, NOT a
    product config), then for each ENABLED work item substitutes a `{FOUNDRY}`
    token in its config path to the foundry root and loads + lints that product
    via the `load_config` / `gather_config_lint` seams (both called by BARE name
    so a `monkeypatch.setattr(foundry, ...)` bites). A DISABLED item is recorded
    in `disabled` (by name) and never loaded.

    Resilient (Behavior 8): if reading/parsing the dispatch config fails (missing
    / not JSON / not an object) it prints a report recording ONE synthetic error
    and returns exit 1; if a single work item's `load_config` or
    `gather_config_lint` raises, that item is recorded in `errors` and the roll-up
    CONTINUES linting the rest (company exit 1). No exception ever propagates.

    With `as_json=True` stdout is exactly ONE `json.dumps(to_dict(), indent=2)`
    document; either way the RETURN value is the same `CompanyConfigLint.
    exit_code` (0 clean-or-warnings-only / 1 config-errors-or-team-errored / 2
    no-enabled-products). Writes NOTHING to disk -- a read-only report; with
    `load_config` monkeypatched the filesystem is untouched.

    UNLIKE the QUALITY roll-ups, ONLY config ERRORS gate -- a fleet of
    warnings-only configs still exits 0 (the per-product `ConfigLint` semantics,
    inherited)."""
    try:
        dispatch = json.loads(
            pathlib.Path(dispatch_path).expanduser().read_text())
        if not isinstance(dispatch, dict):
            raise ValueError("dispatch config is not a JSON object")
    except Exception as exc:
        # A missing / malformed dispatch config is a real operator problem, not a
        # crash: surface it as ONE synthetic error (errors -> exit 1).
        company = summarize_company_config_lint(
            dispatch_path=dispatch_path, products=(), disabled=(),
            errors=((dispatch_path, str(exc)),))
        print(json.dumps(company.to_dict(), indent=2) if as_json
              else company.render())
        return company.exit_code

    products: list[ConfigLint] = []
    disabled: list[str] = []
    errors: list[tuple[str, str]] = []
    for name, config, enabled in parse_dispatch_work_items(dispatch):
        if not enabled:
            disabled.append(name)      # deliberate; never loaded
            continue
        try:
            # {FOUNDRY} -> foundry root BEFORE load_config, exactly as the
            # dispatcher resolves each work item's config path.
            cfg = load_config(config.replace("{FOUNDRY}", str(FOUNDRY)))
            products.append(gather_config_lint(cfg))
        except Exception as exc:
            # One bad team never sinks the whole roll-up -- record + continue.
            errors.append((name, str(exc)))
    company = summarize_company_config_lint(
        dispatch_path=dispatch_path, products=tuple(products),
        disabled=tuple(disabled), errors=tuple(errors))
    print(json.dumps(company.to_dict(), indent=2) if as_json else company.render())
    return company.exit_code


# --------------------------------------------------------------------------- #
# Machine-readable event reader (`events`) -- item 10, the READ half.
#
# iter 05 added the write-only `events.jsonl` stream ("for dashboards / the
# reporter") and iter 26 stamped every record with a stable semantic `kind`.
# This is the on-demand READER over that stream: filter by `kind`, tail to the
# most-recent `N`, count by kind, human or JSON output -- so an operator (or the
# periodic reporter) supervising a 24/7 run gets "the last 5 ships" / "how many
# reverts?" without hand-parsing raw JSONL. Built with the same proven pattern
# as `status`/`history`/`timing`/`weak-tests` (iters 16-25): pure decision
# functions + a frozen summary + a thin CLI over an existing seam. Purely
# additive and DORMANT: the pipeline / gate / dispatcher NEVER call it, it only
# READS the EXISTING `cfg.events_log`, and it writes NOTHING.
# --------------------------------------------------------------------------- #
def parse_events_jsonl(text: str) -> tuple[tuple[dict, ...], int]:
    """Parse an `events.jsonl` body into (records, parse_errors). Pure + total.

    Returns a 2-tuple: `records` is a `tuple` of the JSON OBJECTS (each a `dict`)
    parsed from `text`, one per non-blank line, in file (top-to-bottom) order;
    `parse_errors` is the count of non-blank lines that either failed
    `json.loads` OR parsed to a non-dict JSON value (array / number / string /
    bool / null). A blank / whitespace-only line is SKIPPED and never counts as a
    parse error, so `parse_events_jsonl("")` and an all-whitespace input both
    return `((), 0)`.

    Total by construction: `(text or "")` tolerates `None`, and every per-line
    `json.loads` is wrapped so a malformed line is COUNTED, never raised -- a
    mixed input of valid objects and junk returns exactly the valid objects (in
    order) plus the correct error count. It touches no I/O and never mutates its
    input, so the tester can drive it with pure strings."""
    records: list[dict] = []
    parse_errors = 0
    for line in (text or "").splitlines():
        if not line.strip():
            # blank / whitespace-only lines are structural, not errors
            continue
        try:
            obj = json.loads(line)
        except (ValueError, TypeError):
            parse_errors += 1
            continue
        # a JSON value that is not an object (array / scalar / null) is not an
        # event record -- count it as malformed rather than storing it.
        if isinstance(obj, dict):
            records.append(obj)
        else:
            parse_errors += 1
    return tuple(records), parse_errors


@dataclasses.dataclass(frozen=True)
class EventsSummary:
    """A read-only digest over a slice of the typed `events.jsonl` stream.

    Frozen so a computed summary can't be mutated after the fact (value equality
    for free, matching the other pure cores -- two summaries built from equal
    arguments compare equal). `records` is stored as a `tuple` of the SELECTED
    event objects (post kind-filter + limit) in file order; `total` is the count
    of ALL parseable records in the file, `matched` the count AFTER the kind
    filter but BEFORE the limit, and `parse_errors` the malformed-line count.
    `shown`/`kind_counts`/`exit_code` are pure derivations of the stored fields,
    so `render()`, `to_dict()`, and the returned exit code can never disagree.
    """
    product: str
    records: tuple[dict, ...]
    total: int
    matched: int
    parse_errors: int
    kind_filter: str | None

    @property
    def shown(self) -> int:
        """How many records this summary actually carries (post-limit)."""
        return len(self.records)

    @property
    def kind_counts(self) -> dict:
        """Per-kind tally over the STORED (shown) records, first-encountered order.

        A `dict[str, int]` keyed by each stored record's `kind`; a record missing
        `kind`, or whose `kind` is not a `str`, is tallied under the sentinel key
        `"(none)"` (distinct from any real kind). Dict insertion order is
        preserved, so keys appear in the order first seen among the shown records.
        Empty when nothing is shown."""
        counts: dict[str, int] = {}
        for rec in self.records:
            kind = rec.get("kind")
            key = kind if isinstance(kind, str) else "(none)"
            counts[key] = counts.get(key, 0) + 1
        return counts

    @property
    def exit_code(self) -> int:
        """`0` when anything is shown, else `2` (nothing to show).

        `parse_errors` NEVER affects the verdict: a file whose only good record is
        shown alongside malformed lines still exits `0`, and an empty selection
        exits `2` even when `parse_errors == 0`. Malformed lines are a rollup
        DIAGNOSTIC, not a gate (this reader never fails a run)."""
        return 0 if self.shown > 0 else 2

    def render(self) -> str:
        """A deterministic multi-line digest carrying every selected event.

        Contains, as substrings (the CLI's black-box contract): a header
        `foundry events -- {product}` that additionally carries `kind={kind_filter}`
        iff a kind filter is set; then, for EACH stored record (in order), a line
        carrying that record's `ts` value (or `?` when the `ts` key is absent),
        its `kind` value (or `?` when absent), and its `msg` value (empty string
        when absent) -- all three present as substrings on that record's line; and
        a final rollup line. The rollup carries `showing {shown} of {matched}
        matched`, `{total} total`, `{parse_errors} malformed`, plus each
        `kind_counts` entry as `{kind}:{count}`. When NOTHING is shown the rollup
        instead carries the substring `no events` and NO per-record line is
        emitted."""
        header = f"foundry events -- {self.product}"
        if self.kind_filter is not None:
            header += f"  kind={self.kind_filter}"
        lines = [header]
        for rec in self.records:
            ts = rec["ts"] if "ts" in rec else "?"
            kind = rec["kind"] if "kind" in rec else "?"
            msg = rec["msg"] if "msg" in rec else ""
            lines.append(f"  {ts}  {kind}  {msg}")
        if self.shown == 0:
            rollup = (f"no events -- {self.total} total, "
                      f"{self.parse_errors} malformed")
        else:
            tally = "".join(f" {k}:{v}" for k, v in self.kind_counts.items())
            rollup = (f"showing {self.shown} of {self.matched} matched, "
                      f"{self.total} total, {self.parse_errors} malformed;"
                      f"{tally}")
        lines.append(rollup)
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """A pure, JSON-safe serialization of the whole digest for machine
        consumers -- dashboards / cron / the reporter (roadmap item 10's
        "machine-readable status for dashboards / the reporter"), mirroring
        iter-19/20/21's `status`/`history`/`timing --json`.

        Returns EXACTLY 9 keys in this fixed order: `product`, `kind_filter`,
        `total`, `matched`, `shown`, `parse_errors`, `exit_code`, `kind_counts`,
        `events`. `product`/`kind_filter`/`total`/`matched`/`parse_errors` are
        the STORED fields verbatim; `shown`/`exit_code`/`kind_counts` each REUSE
        the frozen properties (so the payload can never disagree with `render()`
        / the returned exit code); `events` is a JSON array of the stored records
        VERBATIM. Every value is
        JSON-native (str / int / None / dict / list of dicts -- the records were
        produced by `json.loads`), so `json.dumps(...)` never raises and
        `json.loads(json.dumps(...))` round-trips to an equal structure, including
        the empty case (`events == []`, `kind_counts == {}`). Pure: touches no
        filesystem, only the already-gathered snapshot."""
        return {
            "product": self.product,
            "kind_filter": self.kind_filter,
            "total": self.total,
            "matched": self.matched,
            "shown": self.shown,
            "parse_errors": self.parse_errors,
            "exit_code": self.exit_code,
            "kind_counts": self.kind_counts,
            "events": list(self.records),
        }


def summarize_events(*, product: str, records, total: int, matched: int,
                     parse_errors: int, kind_filter: str | None
                     ) -> EventsSummary:
    """Pure keyword-only constructor for an `EventsSummary` (item 10 reader).

    A thin, total wrapper packing the selected event records + the three counts +
    the active kind filter into the frozen digest, materializing `records` as a
    `tuple` (so the frozen dataclass stays immutable and a caller's list cannot be
    mutated out from under it). Keyword-only so the fields can never be transposed
    by position; it never raises. Kept separate from `events_cli` so the decision
    core stays a pure function the tester can drive with zero filesystem."""
    return EventsSummary(
        product=product, records=tuple(records), total=total,
        matched=matched, parse_errors=parse_errors, kind_filter=kind_filter)


def gather_events(cfg: ProductConfig, kind: str | None = None,
                  limit: int | None = None) -> EventsSummary:
    """Gather one product's typed `events.jsonl` stream into an `EventsSummary`
    (item 10 reader).

    Extracted output-preservingly from the iter-27 `events_cli` gathering so BOTH
    the single-product `foundry events` and the coming company-wide roll-up
    (bite 2's `company_events_cli`) share ONE gathering seam; a monkeypatch on
    this one function then reshapes every consumer at once. Output-preserving: the
    records / summary it builds are byte-identical to what iter 27 built, so
    `foundry events` is unchanged (mirroring iter-30's `gather_status` extraction
    from `status_cli`, iter-31's `gather_history` from `history_cli`, iter-39's
    `gather_timing` from `timing_cli`, and iter-42's `gather_weak_tests` from
    `weak_tests_cli`).

    Reads every signal through the EXISTING module-level seams -- each called by
    BARE name so a `monkeypatch.setattr(foundry, ...)` in a test bites:
      * reads `cfg.events_log.read_text()` -- an ABSENT file (FileNotFoundError)
        or any `OSError` on read degrades to empty content (no records,
        `parse_errors == 0`), never propagating the exception;
      * `parse_events_jsonl` turns the file body into `(records, parse_errors)`;
        `total` is the count of ALL parseable records;
      * with `kind` set, keeps ONLY records whose `kind` equals it (exact string
        match via `r.get("kind") == kind`); `matched` is the post-filter,
        PRE-limit count;
      * with a POSITIVE int `limit`, tails to the LAST `matched[-limit:]` records
        while PRESERVING file order (`kind` filters FIRST, then `limit` tails); a
        `None` / non-positive `limit` keeps all matched;
      * hands the selection to the pure `summarize_events`.
    Returns the frozen `EventsSummary` core; writes NOTHING to disk (read-only) --
    a thin gatherer over the pure helpers that adds no decision logic beyond
    read -> parse -> filter -> tail -> summarize."""
    try:
        # `read_text` raises FileNotFoundError (an OSError) for an absent file,
        # so the single except covers BOTH "absent" and "unreadable" -> empty.
        text = cfg.events_log.read_text()
    except OSError:
        text = ""
    records, parse_errors = parse_events_jsonl(text)
    total = len(records)
    if kind is not None:
        matched_records = [r for r in records if r.get("kind") == kind]
    else:
        matched_records = list(records)
    matched = len(matched_records)
    # tail to the most-recent N (positive int only); the slice preserves the
    # ascending file order so the digest still reads oldest-first.
    if isinstance(limit, int) and limit > 0:
        shown_records = matched_records[-limit:]
    else:
        shown_records = matched_records
    return summarize_events(
        product=cfg.name, records=shown_records, total=total,
        matched=matched, parse_errors=parse_errors, kind_filter=kind)


def events_cli(cfg: ProductConfig, kind: str | None = None,
               limit: int | None = None, as_json: bool = False) -> int:
    """On-demand CLI: read/digest `cfg.events_log` + a 0/2 exit code.

    Reads the EXISTING `cfg.events_log` (write half unchanged since iters 05/26)
    and degrades gracefully: an ABSENT file or an `OSError` on read yields empty
    content (no records, `parse_errors == 0`) and exit `2`, never raising. Writes
    NOTHING to disk in any mode.

    Gathers the digest through the `gather_events(cfg, kind, limit)` seam (iter 44
    -- which reads `cfg.events_log` and runs the read -> parse -> kind-filter ->
    limit-tail -> summarize pipeline via the EXISTING module-level functions,
    called by BARE name so a `monkeypatch.setattr(foundry, ...)` bites) then
    prints the pure `EventsSummary` core:
      * `--kind` keeps ONLY records whose `kind` equals it (exact match), applied
        FIRST; `--limit` then tails to the LAST N while preserving file order;
      * with `as_json=True` the entire stdout is ONE `json.dumps(summary.to_dict(),
        indent=2)` document (the stable machine contract for dashboards / reporter
        / CI, mirroring iter-19/20/21); the default `as_json=False` is the human
        `render()` text.
    Either way the RETURN value is the same `summary.exit_code`, and the
    kind-filter + limit selection is byte-identical between the two modes.
    Output-preserving: the printed report / JSON / exit code are byte-identical to
    iter 27. A thin printer over the pure core -- no decision logic of its own, so
    the printed rollup always equals the `EventsSummary` fields. DORMANT -- its
    ONLY caller is `main()`, no control path calls it."""
    summary = gather_events(cfg, kind, limit)
    # `--json` emits the pure digest as a single JSON document (stdout-only, no
    # decision logic added); the default stays the human report.
    print(json.dumps(summary.to_dict(), indent=2) if as_json else summary.render())
    return summary.exit_code


# --------------------------------------------------------------------------- #
# Company-wide event roll-up (`company-events`) -- roadmap item 10, bite 2 of 2
# (the company view on the iter-44 `gather_events` foundation).
#
# The ACTIVITY-axis complement of `company-status` (health NOW), `company-history`
# (ship LEDGER), `company-timing` (THROUGHPUT) and `company-weak-tests` (QUALITY):
# `company-events` folds every ENABLED team's iter-27 typed `events.jsonl` digest
# into ONE company view -- summed total/matched/shown/malformed + a merged
# per-`kind` tally + a per-product breakdown -- so an operator running N teams
# reads "how many ships/reverts/backoffs across the WHOLE company" in one shot
# instead of running `events` once per team and summing by hand. It reuses the
# SHIPPED `gather_events` (iter 44) / `parse_dispatch_work_items` (iter 30) /
# frozen `EventsSummary` (iter 27) seams -- adds NO new I/O seam, sentinel, config
# field, or artifact. Purely additive + DORMANT: the pipeline / gate / dispatcher
# NEVER call it and it WRITES NOTHING (read-only). Like the INFORMATIONAL
# history/timing roll-ups (UNLIKE gating weak-tests) it never gates on a malformed
# line or a quiet team; only a STRUCTURAL gather failure gates (exit 1). This is
# the 5th and LAST `company-*` member.
# --------------------------------------------------------------------------- #
@dataclasses.dataclass(frozen=True)
class CompanyEvents:
    """A one-shot COMPANY-wide typed-event roll-up across a dispatch config.

    Frozen so a computed roll-up can't be mutated after the fact (value equality
    for free, matching the other pure cores). Every derived value is a pure
    property over the stored fields, so the whole verdict -- including the
    scriptable exit code -- follows deterministically from what was gathered, and
    the JSON payload / render text can never disagree with the exit code.

    Fields:
      * `dispatch_path` -- the dispatch config path, echoed into `render()`.
      * `products` -- the per-product `EventsSummary` digests that were
        successfully gathered, IN dispatch-file order (an enabled product that
        failed to load/gather is NOT here -- it lands in `errors`).
      * `disabled` -- names of work items with `enabled=False` (never loaded).
      * `errors` -- `(product, message)` 2-tuples for enabled items that raised
        while loading/gathering (the sole caller guarantees each is a 2-tuple).
      * `kind_filter` -- the `--kind` applied to EVERY team's gather (or `None`),
        echoed into `render()` and carried in `to_dict()`.

    The company counts are SUMS over the gathered products: `total`/`matched`/
    `shown`/`parse_errors` sum the same-named per-product fields (`EventsSummary.
    parse_errors` is an INT count, so these SUM ints -- they never concatenate).
    `kind_counts` MERGES every product's per-kind tally into one, summing counts
    per key with keys in first-encountered order across products in stored order.
    `n_active` counts gathered products that actually showed an event.
    """
    dispatch_path: str
    products: tuple[EventsSummary, ...]
    disabled: tuple[str, ...]
    errors: tuple[tuple[str, str], ...]
    kind_filter: str | None

    @property
    def n_products(self) -> int:
        """Count of products successfully ROLLED UP (an errored enabled product
        is NOT counted here -- it is in `errors`)."""
        return len(self.products)

    @property
    def n_disabled(self) -> int:
        return len(self.disabled)

    @property
    def n_errors(self) -> int:
        return len(self.errors)

    @property
    def total(self) -> int:
        """Company total events = the SUM of every gathered product's `total`."""
        return sum(p.total for p in self.products)

    @property
    def matched(self) -> int:
        """Company matched events = the SUM of every product's `matched`."""
        return sum(p.matched for p in self.products)

    @property
    def shown(self) -> int:
        """Company shown events = the SUM of every product's `shown`."""
        return sum(p.shown for p in self.products)

    @property
    def parse_errors(self) -> int:
        """Company malformed lines = the SUM of every product's `parse_errors`
        (an INT count on `EventsSummary`, NOT a tuple -- so this SUMS, never
        concatenates)."""
        return sum(p.parse_errors for p in self.products)

    @property
    def kind_counts(self) -> dict:
        """The MERGED per-kind tally over all products' `kind_counts` -- a
        `dict[str, int]` summing counts per key, keys in first-encountered order
        across products in stored product order (dict insertion order preserves
        it). Empty when nothing is shown company-wide."""
        merged: dict[str, int] = {}
        for p in self.products:
            for key, count in p.kind_counts.items():
                merged[key] = merged.get(key, 0) + count
        return merged

    @property
    def n_active(self) -> int:
        """How many GATHERED products actually showed >=1 event -- "how many
        teams have recent activity" at a glance, without expanding the breakdown."""
        return sum(1 for p in self.products if p.shown > 0)

    @property
    def exit_code(self) -> int:
        """Scriptable verdict, errors-first (INFORMATIONAL like history/timing,
        UNLIKE gating weak-tests): `1` when `errors` is non-empty (a structural
        gather failure -- the ONLY thing events gates on), else `2` when NO
        products were gathered (every item disabled or `work_items` empty --
        reachable only with `errors` empty), else `0`.

        `parse_errors` NEVER changes the verdict (a malformed line is a
        diagnostic, not a gate). A gathered product that showed ZERO events (its
        own `EventsSummary.exit_code == 2`) does NOT force company exit 2 -- it
        still counts in `n_products`, so with no structural errors the company
        exits 0 (mirroring `company-timing`, where a product with zero measured
        timings does not force exit 2)."""
        if self.errors:
            return 1
        if self.n_products == 0:
            return 2
        return 0

    @property
    def verdict(self) -> str:
        """The single human token for the current `exit_code` -- `"OK"` (0) /
        `"ERRORS"` (1) / `"no enabled products"` (2). ONE source of truth for
        both `render()`'s last line and the JSON `verdict` key, so the text and
        the machine payload can never drift from the exit code."""
        return {0: "OK", 1: "ERRORS", 2: "no enabled products"}[self.exit_code]

    def _rollup(self) -> str:
        """The company events rollup as a substring: `{shown} shown of {matched}
        matched, {total} total, {parse_errors} malformed` followed by each merged
        `kind_counts` entry as ` {kind}:{count}` (a `;` separates the counts from
        the tally, mirroring `EventsSummary.render()`). Company COUNTS only --
        per-team leaf events live in `to_dict()`, keeping the report bounded like
        the other `company-*` members."""
        tally = "".join(f" {k}:{v}" for k, v in self.kind_counts.items())
        return (f"{self.shown} shown of {self.matched} matched, "
                f"{self.total} total, {self.parse_errors} malformed;{tally}")

    def render(self) -> str:
        """A deterministic multi-line company events report (the CLI's contract).

        Contains, as substrings: the literal `foundry company-events`; the
        `dispatch_path`; when `kind_filter is not None`, additionally
        `kind={kind_filter}`; a counts line reporting `{n_products} gathered`,
        `{n_disabled} disabled`, `{n_errors} error(s)` PLUS the company rollup
        (`{shown} shown of {matched} matched, {total} total, {parse_errors}
        malformed` + each merged `kind_counts` entry as ` {kind}:{count}`); ONE
        line per gathered product beginning `  - {product}:` carrying its OWN
        `{p.shown} shown of {p.matched} matched, {p.total} total, {p.parse_errors}
        malformed` (per-product COUNTS only, NOT each event line); one
        `  - {name}: disabled` line per disabled item; one `  - {name}: ERROR
        {message}` line per error; and a final `verdict:` line whose token EQUALS
        `verdict`."""
        header = "foundry company-events"
        if self.kind_filter is not None:
            header += f"  kind={self.kind_filter}"
        lines = [
            header,
            f"  dispatch config: {self.dispatch_path}",
            f"  products: {self.n_products} gathered, "
            f"{self.n_disabled} disabled, {self.n_errors} error(s) -- "
            f"{self._rollup()}",
        ]
        for p in self.products:
            lines.append(
                f"  - {p.product}: {p.shown} shown of {p.matched} matched, "
                f"{p.total} total, {p.parse_errors} malformed")
        for name in self.disabled:
            lines.append(f"  - {name}: disabled")
        for name, message in self.errors:
            lines.append(f"  - {name}: ERROR {message}")
        lines.append(f"verdict: {self.verdict}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """A pure, JSON-safe company roll-up for machine consumers -- a dashboard
        / cron alert / the reporter. `products` carries the FULL per-product
        `EventsSummary.to_dict()` payload (the 9-key per-team detail INCLUDING
        each team's `events` array) in stored order, so no leaf detail is lost
        even though `render()` prints per-product counts only. Every derived value
        REUSES the frozen properties, so the payload can never disagree with
        `render()` or the exit code, and every value is JSON-native, so it
        round-trips through `json.loads(json.dumps(...))` -- including when
        `products`/`disabled`/`errors` are all empty (`kind_counts == {}`). Pure:
        touches no filesystem."""
        return {
            "dispatch_config": self.dispatch_path,
            "kind_filter": self.kind_filter,
            "products": [p.to_dict() for p in self.products],
            "disabled": list(self.disabled),
            "errors": [{"product": name, "message": message}
                       for name, message in self.errors],
            "n_products": self.n_products,
            "n_disabled": self.n_disabled,
            "n_errors": self.n_errors,
            "n_active": self.n_active,
            "total": self.total,
            "matched": self.matched,
            "shown": self.shown,
            "parse_errors": self.parse_errors,
            "kind_counts": self.kind_counts,
            "exit_code": self.exit_code,
            "verdict": self.verdict,
        }


def summarize_company_events(*, dispatch_path: str,
                             products: tuple[EventsSummary, ...],
                             disabled: tuple[str, ...],
                             errors: tuple[tuple[str, str], ...],
                             kind_filter: str | None) -> CompanyEvents:
    """Pure keyword-only constructor for a `CompanyEvents` (Behaviors 1-7).

    A thin, total wrapper that packs the gathered digests into the frozen
    roll-up -- keyword-only so a caller can never transpose the fields by
    position, and it never raises for well-formed inputs (each `errors` entry is
    a `(product, message)` 2-tuple, which the sole caller `company_events_cli`
    guarantees). Kept separate from `company_events_cli` so the decision core
    stays a pure function the tester can drive without any filesystem."""
    return CompanyEvents(
        dispatch_path=dispatch_path,
        products=tuple(products),
        disabled=tuple(disabled),
        errors=tuple((name, message) for name, message in errors),
        kind_filter=kind_filter)


def company_events_cli(dispatch_path: str, kind: str | None = None,
                       limit: int | None = None, as_json: bool = False) -> int:
    """On-demand CLI: roll every ENABLED team's typed-event digest into ONE
    company activity lens (roadmap item 10, bite 2).

    Reads the DISPATCH config at `dispatch_path` (`foundry.config.json`, NOT a
    product config), then for each ENABLED work item substitutes a `{FOUNDRY}`
    token in its config path to the foundry root and loads + gathers that
    product's digest via the `load_config` / `gather_events` seams (both called
    by BARE name so a `monkeypatch.setattr(foundry, ...)` bites). `kind` and
    `limit` flow THROUGH to EVERY `gather_events(cfg, kind, limit)` call (kind =
    exact-match filter, limit = most-recent N per team). A DISABLED item is
    recorded in `disabled` (by name) and never loaded. The company `kind_filter`
    is the `kind` argument (so `render()`/`to_dict()` echo the filter applied to
    every team).

    Resilient (Behaviors 6-8): if reading/parsing the dispatch config fails
    (missing / not JSON / not an object) it prints a report recording ONE
    synthetic error and returns exit 1; if a single work item's `load_config` or
    `gather_events` raises, that item is recorded in `errors` and the roll-up
    CONTINUES gathering the rest (company exit 1). No exception ever propagates.

    With `as_json=True` stdout is exactly ONE `json.dumps(to_dict(), indent=2)`
    document; either way the RETURN value is the same `CompanyEvents.exit_code`
    (0 gathered-no-errors / 1 errors / 2 no-enabled-products). Writes NOTHING to
    disk -- a read-only report; with `load_config` monkeypatched the filesystem
    is untouched."""
    try:
        dispatch = json.loads(
            pathlib.Path(dispatch_path).expanduser().read_text())
        if not isinstance(dispatch, dict):
            raise ValueError("dispatch config is not a JSON object")
    except Exception as exc:
        # A missing / malformed dispatch config is a real operator problem, not a
        # crash: surface it as ONE synthetic error (errors -> exit 1).
        company = summarize_company_events(
            dispatch_path=dispatch_path, products=(), disabled=(),
            errors=((dispatch_path, str(exc)),), kind_filter=kind)
        print(json.dumps(company.to_dict(), indent=2) if as_json
              else company.render())
        return company.exit_code

    products: list[EventsSummary] = []
    disabled: list[str] = []
    errors: list[tuple[str, str]] = []
    for name, config, enabled in parse_dispatch_work_items(dispatch):
        if not enabled:
            disabled.append(name)      # deliberate; never loaded
            continue
        try:
            # {FOUNDRY} -> foundry root BEFORE load_config, exactly as the
            # dispatcher resolves each work item's config path.
            cfg = load_config(config.replace("{FOUNDRY}", str(FOUNDRY)))
            products.append(gather_events(cfg, kind, limit))
        except Exception as exc:
            # One bad team never sinks the whole roll-up -- record + continue.
            errors.append((name, str(exc)))
    company = summarize_company_events(
        dispatch_path=dispatch_path, products=tuple(products),
        disabled=tuple(disabled), errors=tuple(errors), kind_filter=kind)
    print(json.dumps(company.to_dict(), indent=2) if as_json else company.render())
    return company.exit_code


# --------------------------------------------------------------------------- #
# Prompt + stage runner
# --------------------------------------------------------------------------- #
def build_prompt(cfg: ProductConfig, iteration: int, stage: str,
                 role_file: str, out_file: pathlib.Path,
                 it_dir: pathlib.Path, extra: str) -> str:
    # Inline the bounded learnings digest so EVERY fresh stage agent reads the
    # pinned `## Patterns` head + the newest lessons directly, instead of
    # slurping the unbounded LEARNINGS.md off disk (roadmap item 2, bite 2/2).
    # Read defensively: a missing/unreadable file must never crash the pipeline
    # on a product that has recorded nothing yet -> empty text -> placeholder
    # digest. `PROMPT_LEARNINGS_RECENT` / `learnings_digest` are referenced as
    # module globals so `monkeypatch.setattr(foundry, ...)` bites at call time.
    lp = pathlib.Path(cfg.learnings)
    try:
        text = lp.read_text() if lp.exists() else ""
    except OSError:
        text = ""
    digest = learnings_digest(text, recent=PROMPT_LEARNINGS_RECENT)
    return (
        f"You are the {stage.upper()} in iteration {iteration} of the "
        f"autonomous product team building the product '{cfg.name}'.\n\n"
        f"## Context (all paths absolute)\n"
        f"- Product repo: {cfg.repo}\n"
        f"- Push target (final gate only): repo '{cfg.allowed_push_repo}', "
        f"branch '{cfg.branch}', push_enabled={cfg.push_enabled}\n"
        f"- Product vision (fixed intent, stay inside it): {cfg.vision}\n"
        f"- Product roadmap file (PM owns): {cfg.roadmap}\n"
        f"- Quality-reference repo (mirror its conventions): {cfg.quality_ref}\n"
        f"- Product quality bar: {cfg.quality_bar or '(see VISION)'}\n"
        f"- Quality-check command (full suite must pass): {cfg.test_cmd}\n"
        f"- This iteration's state dir (all stage outputs live here): {it_dir}\n"
        f"- Foundry learnings log (append your role lessons here): "
        f"{cfg.learnings}\n"
        f"{PROMPT_LEARNINGS_LABEL}\n{digest}\n"
        f"- Iteration number for file naming: {iteration:02d}\n"
        f"- YOUR REQUIRED OUTPUT FILE: {out_file} -- you MUST write it before "
        f"finishing, even on failure (state what failed and why).\n\n"
        f"READ AND FOLLOW EXACTLY: {pathlib.Path(cfg.roles_dir) / role_file}\n"
        f"{extra}\n{ANTI_DELEGATION}"
    )


def run_stage(cfg: ProductConfig, iteration: int, stage: str, role_file: str,
              out_name: str, extra: str = "") -> tuple[bool, pathlib.Path]:
    it_dir = cfg.state / f"iter-{iteration:02d}"
    it_dir.mkdir(parents=True, exist_ok=True)
    out_file = it_dir / out_name
    prompt = build_prompt(cfg, iteration, stage, role_file, out_file,
                          it_dir, extra)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if stopping(cfg) and stage != "reporter":
            log(cfg, f"iter {iteration:02d} · {stage} STOP requested; abandoning")
            return False, out_file
        log(cfg, f"iter {iteration:02d} · **{stage}** attempt {attempt} started")
        try:
            agent_cmd = [AGENT_BIN] + [
                (prompt if a == "{prompt}" else a) for a in AGENT_RUN_ARGS]
            p = subprocess.run(
                agent_cmd,
                capture_output=True, text=True, timeout=STAGE_TIMEOUT)
            blob = (p.stdout or "") + (p.stderr or "")
        except subprocess.TimeoutExpired:
            blob = "(stage attempt timed out)"
        with (it_dir / f"{stage}.attempt{attempt}.log").open("w") as f:
            f.write(blob)
        if out_file.exists() and out_file.stat().st_size > 0:
            log(cfg, f"iter {iteration:02d} · {stage} produced `{out_file.name}`")
            return True, out_file
        log(cfg, f"iter {iteration:02d} · {stage} no output file "
            f"(attempt {attempt}/{MAX_ATTEMPTS}); tail: {blob[-160:]!r}")
        if attempt < MAX_ATTEMPTS:
            delay = BACKOFFS[min(attempt - 1, len(BACKOFFS) - 1)]
            log(cfg, f"iter {iteration:02d} · {stage} backing off {delay // 60} min")
            if sleep_interruptible(cfg, delay):
                return False, out_file
    return False, out_file


# --------------------------------------------------------------------------- #
# One full pipeline iteration
# --------------------------------------------------------------------------- #
def run_iteration(cfg: ProductConfig, iteration: int | None = None) -> dict:
    """Run one PM->...->final pipeline. Returns a result dict.

    result['status'] in {'shipped', 'no-ship', 'infra-fail', 'stopped'}
    """
    if iteration is None:
        iteration = next_iteration(cfg)
    base = head_of_branch(cfg)
    log(cfg, f"—— iteration {iteration:02d} begins (origin/{cfg.branch} {base}; "
        f"power: {power_state()}) ——")

    # item 19 (bite 3b-ii, COMPLETES item 19): READ the staffing manifest each
    # iteration and derive the stage sequence. For a NON-default team whose
    # manifest lints CLEAN and whose execution plan ENDS on the ship gate,
    # delegate the whole pipeline to the manifest-driven executor
    # `run_execution_plan`. Every other case (absent / default-equivalent /
    # lint-dirty / release-not-last -- i.e. every configured product today)
    # falls through to the fixed pipeline below, byte-for-byte identical, so a
    # live loop resumes byte-for-byte until an operator drops a valid non-default
    # staffing.json. Short-circuit safe: a non-default sequence is never empty
    # (so `plan[-1]` is always valid) and `and` never evaluates `plan[-1]` when
    # the lint is dirty.
    manifest = load_staffing_manifest(cfg)
    sequence = derive_stage_sequence(manifest)
    if sequence != _default_stage_sequence():
        plan = derive_execution_plan(sequence)
        lint = lint_manifest(manifest, pathlib.Path(cfg.roles_dir) / "bench",
                             str(cfg.staffing))
        if lint.clean and plan[-1].is_ship_gate:
            log(cfg, f"iter {iteration:02d} staffing manifest activates a "
                f"non-default team ({len(sequence)} seats); delegating to the "
                f"manifest-driven executor")
            return run_execution_plan(cfg, iteration, plan, base)
        log(cfg, f"iter {iteration:02d} staffing manifest activates a non-default "
            f"team ({len(sequence)} seats) but is not delegable; running the "
            f"fixed pipeline")

    ok, _ = run_stage(cfg, iteration, "pm", "pm.md", "pm.md")
    if not ok:
        return {"status": "infra-fail", "stage": "pm", "iteration": iteration}

    ok, _ = run_stage(cfg, iteration, "engineer", "engineer.md", "engineer.md")
    if not ok:
        revert_repo(cfg, "engineer stage failed")
        return {"status": "infra-fail", "stage": "engineer", "iteration": iteration}

    ok, review = run_stage(cfg, iteration, "reviewer", "reviewer.md",
                           "reviewer.md")
    if not ok:
        revert_repo(cfg, "reviewer stage failed")
        return {"status": "infra-fail", "stage": "reviewer", "iteration": iteration}

    if contains(review, "CHANGES_REQUIRED"):
        log(cfg, f"iter {iteration:02d} · review requires changes -> fix pass")
        ok, _ = run_stage(cfg, iteration, "fix-review", "fix.md",
                          "fix_review.md",
                          f"Gate file to address: {review} ([BLOCKING] only).")
        if not ok:
            revert_repo(cfg, "fix-review failed")
            return {"status": "infra-fail", "stage": "fix-review",
                    "iteration": iteration}

    ok, test_report = run_stage(cfg, iteration, "tester", "tester.md",
                                "tester.md")
    if not ok:
        revert_repo(cfg, "tester stage failed")
        return {"status": "infra-fail", "stage": "tester", "iteration": iteration}

    if contains(test_report, "RESULT: FAIL"):
        log(cfg, f"iter {iteration:02d} · tests failed -> fix pass + retest")
        ok, _ = run_stage(cfg, iteration, "fix-tests", "fix.md", "fix_tests.md",
                          f"Gate file to address: {test_report} (failing tests).")
        if ok:
            ok, test_report = run_stage(
                cfg, iteration, "tester-rerun", "tester.md", "tester2.md",
                "This is a RE-RUN after an engineering fix. Re-verify all "
                "behaviors; update your earlier tests only if they misread "
                "the spec.")
        if not ok:
            revert_repo(cfg, "fix/retest failed")
            return {"status": "infra-fail", "stage": "fix-tests",
                    "iteration": iteration}

    ok, final = run_stage(cfg, iteration, "final", "final.md", "final.md")
    if not ok:
        revert_repo(cfg, "final stage failed")
        return {"status": "infra-fail", "stage": "final", "iteration": iteration}

    new_head = head_of_branch(cfg)
    if contains(final, "ACTION: PUSHED") and new_head != base:
        log(cfg, f"iter {iteration:02d} SHIPPED — origin/{cfg.branch} now {new_head}")
        # Post-release: re-verify the PUSHED commit from a fresh clone. Additive
        # only -- a BROKEN verdict raises the hotfix flag but keeps status
        # "shipped" (the commit is genuinely pushed; fix forward next iter).
        post = postrelease_step(cfg, iteration, new_head)
        log(cfg, f"iter {iteration:02d} post-release {post.sentinel}")
        return {"status": "shipped", "head": new_head, "iteration": iteration,
                "postrelease": post.sentinel}
    revert_repo(cfg, "final gate declined to ship")
    log(cfg, f"iter {iteration:02d} completed WITHOUT ship (reverted; see final.md)")
    return {"status": "no-ship", "iteration": iteration}


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def mechanical_report(cfg: ProductConfig, iters_done: int,
                      pushes: list[str]) -> None:
    lines = [
        f"# {cfg.name} — Foundry Status (mechanical fallback)", "",
        f"- Generated: {dt.datetime.now():%Y-%m-%d %H:%M}",
        f"- Iterations attempted this session: {iters_done}",
        f"- Commits pushed this session: {len(pushes)}", "",
        "## Pushed", *[f"- {p}" for p in (pushes or ["(none)"])], "",
        "See NIGHT_LOG.md for the timeline and LEARNINGS.md for lessons.",
    ]
    cfg.report.write_text("\n".join(lines) + "\n")


def narrative_report(cfg: ProductConfig, iteration: int) -> None:
    run_stage(cfg, iteration, "reporter", "reporter.md",
              f"reporter_done_{iteration:02d}.md",
              f"CONTINUOUS MODE: the loop is still running; this is a periodic "
              f"status report, not a final one. Write the narrative report to "
              f"{cfg.report} (overwrite it). Cover everything since the previous "
              f"report (check NIGHT_LOG.md session markers). Also write your "
              f"required output file when done.")


# --------------------------------------------------------------------------- #
# Continuous single-product loop
# --------------------------------------------------------------------------- #
def run_continuous(cfg: ProductConfig) -> int:
    with cfg.night_log.open("a") as f:
        f.write(f"\n## Continuous session — started {dt.datetime.now():%Y-%m-%d %H:%M}\n\n")
    if not pathlib.Path(cfg.learnings).exists():
        pathlib.Path(cfg.learnings).write_text(f"# {cfg.name} — Foundry Learnings\n\n")
    if stopping(cfg):
        print(f"STOP present for {cfg.name}; remove the STOP file to run.")
        return 1
    subprocess.Popen(["caffeinate", "-i", "-s", "-w", str(os.getpid())])
    log(cfg, f"foundry started (continuous) for '{cfg.name}'; "
        f"origin/{cfg.branch} = {head_of_branch(cfg)}; power: {power_state()}")

    pushes: list[str] = []
    infra_streak = 0
    cooldown_idx = 0
    session_iters = 0
    try:
        while not stopping(cfg):
            session_iters += 1
            res = run_iteration(cfg)
            if res["status"] == "shipped":
                pushes.append(f"iter {res['iteration']:02d} -> {res['head']}")
                infra_streak = 0
                cooldown_idx = 0
            elif res["status"] == "no-ship":
                infra_streak = 0
                cooldown_idx = 0
            else:  # infra-fail / stopped
                infra_streak += 1

            if infra_streak >= 2 and not stopping(cfg):
                delay = COOLDOWNS[min(cooldown_idx, len(COOLDOWNS) - 1)]
                cooldown_idx += 1
                log(cfg, f"infra streak {infra_streak} -> cooling down "
                    f"{delay // 60} min")
                if sleep_interruptible(cfg, delay):
                    break

            if session_iters % REPORT_EVERY == 0 and not stopping(cfg):
                mechanical_report(cfg, session_iters, pushes)
                narrative_report(cfg, res["iteration"])

        log(cfg, f"STOP honored: session iters={session_iters}, "
            f"pushes={len(pushes)}")
    finally:
        mechanical_report(cfg, session_iters, pushes)
        log(cfg, f"foundry stopped for '{cfg.name}'; report at {cfg.report}")
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="agent-foundry product team runner")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "once", "doctor"):
        s = sub.add_parser(name)
        s.add_argument("--config", required=True, help="path to product JSON config")
    # `learnings` also takes --recent to bound the rendered tail (default 12).
    lrn = sub.add_parser("learnings")
    lrn.add_argument("--config", required=True, help="path to product JSON config")
    lrn.add_argument("--recent", type=int, default=12,
                     help="most-recent lessons to include (default 12)")
    # `agents` renders (writes, or --print) the product repo's AGENTS.md from its
    # learnings. On-demand only — the pipeline never calls it (bite 2 wires it in).
    agt = sub.add_parser("agents")
    agt.add_argument("--config", required=True, help="path to product JSON config")
    agt.add_argument("--recent", type=int, default=12,
                     help="most-recent lessons to embed (default 12)")
    agt.add_argument("--print", dest="print_only", action="store_true",
                     help="print to stdout instead of writing <repo>/AGENTS.md")
    # `lint-spec` scores a PM spec file for completeness + size. It takes a spec
    # PATH (--file), NOT a product --config, so it is dispatched BEFORE
    # `load_config` below. On-demand only — the pipeline never calls it.
    lnt = sub.add_parser("lint-spec")
    lnt.add_argument("--file", required=True,
                     help="path to a PM spec (pm.md) to lint")
    # `gate-precheck` runs the tri-perspective product gate's DETERMINISTIC
    # pre-checks on a proposal file (item 20 bite 1, the deterministic slice):
    # it bounces FOR FREE -- before any model call -- a proposal missing an
    # impact NUMBER, a stated appetite, or a listed alternative, with a
    # default-Kill verdict. It takes a proposal PATH (--file), NOT a product
    # --config, so like `lint-spec` it is dispatched BEFORE the top-level
    # `load_config` below. DORMANT / on-demand only -- the pipeline/gate/
    # dispatcher NEVER call it; it writes nothing. Exit 0 PROCEED / 1 KILL /
    # 2 file-not-found.
    gpc = sub.add_parser("gate-precheck")
    gpc.add_argument("--file", required=True,
                     help="path to a product proposal to pre-check")
    gpc.add_argument("--json", action="store_true",
                     help="emit the pre-check verdict as one JSON document "
                          "(machine-readable) instead of the human report; "
                          "same 0/1/2 exit code")
    # `gate-verdict` aggregates the three tri-perspective product-gate seat
    # verdicts (Business / Product / Senior-engineer, item 20 bite 2) into
    # ONE gate verdict with default-Kill semantics: any KILL seat kills, else
    # any RECYCLE recycles, else all-GO is a Go. It takes three raw verdict
    # strings (--business/--product/--engineering), NOT a product --config, so
    # like `gate-precheck`/`lint-spec` it is dispatched BEFORE the top-level
    # `load_config` below. DORMANT / on-demand only -- the pipeline/gate/
    # dispatcher NEVER call it; it writes nothing. Exit 0 GO / 1 KILL /
    # 2 RECYCLE.
    gvd = sub.add_parser("gate-verdict")
    gvd.add_argument("--business", required=True,
                     help="the Business seat's raw Go/Kill/Recycle verdict")
    gvd.add_argument("--product", required=True,
                     help="the Product seat's raw Go/Kill/Recycle verdict")
    gvd.add_argument("--engineering", required=True,
                     help="the Senior-engineer seat's raw Go/Kill/Recycle verdict")
    gvd.add_argument("--json", action="store_true",
                     help="emit the gate verdict as one JSON document "
                          "(machine-readable) instead of the human report; "
                          "same 0/1/2 exit code")
    # `role-model` resolves a per-role MODEL-OVERRIDE note (item 20 bite 3) into
    # the agent-CLI argv a launcher would use over the module `AGENT_RUN_ARGS`
    # base + `MODEL_ARG_TEMPLATE` (both read at call time). It takes an optional
    # `--model` NOTE (default ""), NOT a product --config, so like
    # `gate-verdict`/`gate-precheck`/`lint-spec` it is dispatched BEFORE the
    # top-level `load_config` below. DORMANT / on-demand only -- the pipeline/
    # gate/dispatcher NEVER call it; it writes nothing. Exit 0 override-applied /
    # 1 passthrough (empty/whitespace note).
    rmo = sub.add_parser("role-model")
    rmo.add_argument("--model", default="",
                     help="per-role model note to resolve into agent-CLI args; "
                          "empty or whitespace-only means passthrough (no "
                          "override)")
    rmo.add_argument("--json", action="store_true",
                     help="emit the resolution as one JSON document "
                          "(machine-readable) instead of the human report; "
                          "same 0/1 exit code")
    # `product-gate` composes the deterministic pre-check (#31 gate-precheck)
    # with the tri-perspective seat aggregation (#32 gate-verdict) into ONE
    # composite decision on a proposal file (item 20 bite 4a): run the free
    # pre-check FIRST and, if it fails, bounce the proposal FOR FREE before the
    # three seats are consulted; else fold the seat verdicts. It takes a
    # proposal `--file` plus the three raw seat verdicts (--business/--product/
    # --engineering, mirroring `gate-verdict`), NOT a product --config, so like
    # `role-model`/`gate-verdict`/`gate-precheck`/`lint-spec` it is dispatched
    # BEFORE the top-level `load_config` below. DORMANT / on-demand only -- the
    # pipeline/gate/dispatcher NEVER call it; it writes nothing. Exit 0 GO /
    # 1 KILL / 2 RECYCLE / 3 file-not-found.
    pgt = sub.add_parser("product-gate")
    pgt.add_argument("--file", required=True,
                     help="path to a product proposal to gate")
    pgt.add_argument("--business", required=True,
                     help="the Business seat's raw Go/Kill/Recycle verdict")
    pgt.add_argument("--product", required=True,
                     help="the Product seat's raw Go/Kill/Recycle verdict")
    pgt.add_argument("--engineering", required=True,
                     help="the Senior-engineer seat's raw Go/Kill/Recycle verdict")
    pgt.add_argument("--json", action="store_true",
                     help="emit the gate decision as one JSON document "
                          "(machine-readable) instead of the human report; "
                          "same 0/1/2/3 exit code")
    # `escalation-check` is the CEO-escalation predicate (item 21, org-design
    # section 9): classify a file/diff's content for the five RESERVED
    # categories (security / PII / money / legal / visibility) that must
    # escalate to the human operator before anything ships -- generalizing
    # the committed scripts/leak_guard.py (section 9's first instance, PII).
    # It takes a `--file`, NOT a product --config, so like `product-gate`/
    # `gate-verdict`/`gate-precheck`/`lint-spec` it is dispatched BEFORE the
    # top-level `load_config` below. DORMANT / on-demand only -- the pipeline/
    # gate/dispatcher NEVER call it; it writes nothing. Exit 1 ESCALATE / 0
    # CLEAR / 2 file-not-found.
    esc = sub.add_parser("escalation-check")
    esc.add_argument("--file", required=True,
                     help="path to a file/diff to classify for reserved "
                          "CEO-escalation categories")
    esc.add_argument("--json", action="store_true",
                     help="emit the classification as one JSON document "
                          "(machine-readable) instead of the human report; "
                          "same 0/1/2 exit code")
    # `cadence-review` is the fixed-N no-trigger cadence-review fallback (item
    # 22 bite 1, org-design section 7): even when no anomaly trigger fires, a
    # quiet loop can silently drift precisely because nothing looked wrong, so
    # after N consecutive quiet iterations the CEO + PM proactively review the
    # project anyway. Given the current quiet-streak `--counter` and whether a
    # trigger fired THIS iteration (`--trigger-fired`), it decides whether the
    # fallback fires and what counter to carry forward. It takes no file and no
    # product --config -- the threshold is the module-level CADENCE_REVIEW_N
    # (default 5, patchable + read at call time) or an explicit `--n` -- so like
    # `escalation-check`/`product-gate`/`lint-spec` it is dispatched BEFORE the
    # top-level `load_config` below. DORMANT / on-demand only -- the pipeline/
    # gate/dispatcher NEVER call it; it writes nothing. Exit 1 REVIEW / 0
    # CONTINUE.
    cad = sub.add_parser("cadence-review")
    cad.add_argument("--counter", type=int, required=True,
                     help="the current no-trigger quiet-streak length carried "
                          "in from prior iterations")
    cad.add_argument("--trigger-fired", action="store_true",
                     help="an anomaly trigger fired THIS iteration (breaks the "
                          "quiet streak so the fallback does not fire)")
    cad.add_argument("--n", type=int, default=None,
                     help="explicit threshold override; omit to read the "
                          "module-level CADENCE_REVIEW_N (default 5) at call time")
    cad.add_argument("--json", action="store_true",
                     help="emit the decision as one JSON document "
                          "(machine-readable) instead of the human report; "
                          "same 0/1 exit code")
    # `restaffing-review` is the hysteresis-constrained re-staffing DIFF review
    # (item 22 bite 2, org-design section 10): team-composition changes are
    # PROPOSALS, not drift, so a review emits a DIFF against staffing.json
    # (never editing it) partitioned by three hysteresis rules that prevent
    # thrash -- every change must cite a LOGGED trigger, a deactivate needs
    # minimum tenure K, and at most `cap` changes are accepted per review. Given
    # a `--file` JSON review object (changes / tenures / logged_triggers, and
    # optional k / cap overrides), it partitions the proposed changes into an
    # ACCEPTED diff plus tagged REJECTIONS. It takes a `--file`, NOT a product
    # --config, so like `cadence-review`/`escalation-check`/`product-gate`/
    # `lint-spec` it is dispatched BEFORE the top-level `load_config` below.
    # DORMANT / on-demand only -- the pipeline/gate/dispatcher NEVER call it; it
    # writes nothing. Exit 1 DIFF / 0 NOOP / 2 file-not-found-or-invalid-JSON.
    rst = sub.add_parser("restaffing-review")
    rst.add_argument("--file", required=True,
                     help="path to a JSON re-staffing review object (changes / "
                          "tenures / logged_triggers, optional k / cap)")
    rst.add_argument("--json", action="store_true",
                     help="emit the diff as one JSON document "
                          "(machine-readable) instead of the human report; "
                          "same 0/1/2 exit code")
    # `scout-plan` is the dual-PM-scout PHASE PLANNER (dual-PM-scout feature
    # bite 1, docs/DUAL_PM_SCOUT_SPEC.md): given the dual-scout flag (and an
    # optional lens override), compute the ordered scout pre-stage plan an
    # iteration would run BEFORE the PM lead -- pm_scout_a (new-capability lens)
    # then pm_scout_b (hardening/DX lens) by default, positional a/b/c/... for
    # more lenses. It takes a flag, NOT a product --config or a --file, so like
    # `cadence-review`/`escalation-check`/`product-gate`/`lint-spec` it is
    # dispatched BEFORE the top-level `load_config` below. DORMANT / on-demand
    # only -- the pipeline/gate/dispatcher NEVER call it; it writes nothing.
    # Exit 1 DUAL / 0 SINGLE.
    scp = sub.add_parser("scout-plan")
    scp.add_argument("--dual-pm-scouts", action="store_true",
                     help="run the two-scout pre-phase (pm_scout_a then "
                          "pm_scout_b) before the PM lead")
    scp.add_argument("--lens", action="append", default=None,
                     help="explicit scout lens (repeatable, in order); omit to "
                          "read the module-level PM_SCOUT_LENSES at call time")
    scp.add_argument("--json", action="store_true",
                     help="emit the plan as one JSON document "
                          "(machine-readable) instead of the human report; "
                          "same 0/1 exit code")
    # `lint-config` is the CONFIG-validation complement to `doctor` (env, #0)
    # and `lint-spec` (spec, #6): an offline, deterministic linter that inspects
    # a resolved product config for the misconfigurations that silently waste a
    # shift or defeat the push guard (a missing/non-git `repo`, an empty
    # `test_cmd`, a missing `roles_dir`, a missing `vision`, or -- the SAFETY
    # case -- an empty `allowed_push_repo` while push_enabled is true). It takes
    # a product `--config` but manages its OWN load (so an unreadable/invalid
    # config maps to exit 2, distinct from a lint PROBLEMS=1), so like
    # `lint-spec`/`single-brain`/the `company-*` commands it is dispatched BEFORE
    # the top-level `load_config` below. On-demand only -- the pipeline/gate/
    # dispatcher NEVER call it; it writes nothing. Exit 0 OK-or-warnings-only /
    # 1 config-errors / 2 unreadable-config.
    lcfg = sub.add_parser("lint-config")
    lcfg.add_argument("--config", required=True,
                      help="path to the PRODUCT JSON config to lint")
    lcfg.add_argument("--json", action="store_true",
                      help="emit the lint verdict as one JSON document "
                           "(machine-readable) instead of the human report; "
                           "same 0/1/2 exit code")
    # `lint-bench` validates the hand-written bench role-cards in the
    # foundry's `roles/bench` against the fixed card contract (a
    # `# Bench role card:` title + `Status:`/`Activation:`/`Tenure:`/
    # `Model note:` header fields + the `## Mission`/`## I/O contract`
    # sections) -- the BENCH-facing sibling of `doctor` (env #0),
    # `lint-spec` (spec #6), and `lint-config` (config #27), and the first
    # org-design-track item (roadmap 17). It takes a bench `--dir`
    # (defaulting to the foundry's OWN bench), NOT a product `--config`, so
    # like `lint-spec` it is dispatched BEFORE the top-level `load_config`
    # below. On-demand only -- the pipeline/gate/dispatcher NEVER call it;
    # it writes nothing. Exit 0 OK / 1 card-issues-or-unreadable / 2 no-cards.
    lnb = sub.add_parser("lint-bench")
    lnb.add_argument("--dir", dest="dir", default=None,
                     help="path to the bench directory of role-cards "
                          "(default: the foundry's own roles/bench)")
    lnb.add_argument("--json", action="store_true",
                     help="emit the lint verdict as one JSON document "
                          "(machine-readable) instead of the human report; "
                          "same 0/1/2 exit code")
    # `lint-manifest` validates a product's STAFFING MANIFEST
    # (staffing.json) against the documented schema -- the MANIFEST-facing
    # sibling of `doctor` (env #0), `lint-spec` (spec #6), `lint-config`
    # (config #27), and `lint-bench` (bench #29), and the SECOND
    # org-design-track item (roadmap 18, bite 1). It takes a manifest
    # `--file` (NOT a product `--config`) and an optional `--bench-dir`
    # (defaulting to the foundry's OWN `roles/bench`) to check each named
    # role has a card, so like `lint-spec`/`lint-bench` it is dispatched
    # BEFORE the top-level `load_config` below. On-demand only -- the
    # pipeline/gate/dispatcher NEVER call it; it writes nothing. Exit 0
    # clean / 1 manifest-findings / 2 unreadable-or-invalid-JSON file.
    lnm = sub.add_parser("lint-manifest")
    lnm.add_argument("--file", required=True,
                     help="path to a staffing manifest (staffing.json) "
                          "to lint")
    lnm.add_argument("--bench-dir", dest="bench_dir", default=None,
                     help="path to the bench directory of role-cards to "
                          "check each named role against (default: the "
                          "foundry's own roles/bench)")
    lnm.add_argument("--json", action="store_true",
                     help="emit the lint verdict as one JSON document "
                          "(machine-readable) instead of the human report; "
                          "same 0/1/2 exit code")
    # `single-brain` is a read-only launch PREFLIGHT: it reports whether a
    # dispatcher is ALREADY running so an operator (or a launch wrapper) can
    # refuse to start a SECOND competing brain, which would starve the shared
    # model-API token budget -- the #1 observed unattended-run failure. Like
    # `lint-spec`, it needs NO --config (nothing product-specific), so it is
    # dispatched BEFORE load_config below. On-demand only -- the pipeline /
    # dispatcher NEVER call it; it writes nothing. Exit 0 SAFE / 1 CONFLICT /
    # 2 UNKNOWN, so a wrapper can gate a launch on `[ $? -eq 0 ]`.
    sgl = sub.add_parser("single-brain")
    sgl.add_argument("--pattern", default="dispatcher.py",
                     help="process-command pattern to scan for "
                          "(default 'dispatcher.py')")
    sgl.add_argument("--json", action="store_true",
                     help="emit the preflight verdict as one JSON document "
                          "(machine-readable) instead of the human report; "
                          "same 0/1/2 exit code")
    # `prd` reports "N/M stories pass" from a product's prd.json machine roadmap
    # (cfg.prd). On-demand only -- the pipeline/dispatcher NEVER call it (bite 2
    # wires the same pure prd_status into the dispatcher for an automatic stop).
    prd = sub.add_parser("prd")
    prd.add_argument("--config", required=True,
                     help="path to product JSON config")
    # `gate-scope` classifies a diff (via --files, or the run_cmd git-diff seam)
    # into test/doc/source and reports whether it is coverage-only ("light").
    # DORMANT / on-demand only -- the gate never consults it (item 4 bite 2 wires
    # the light path in). `--files nargs="*"` classifies paths directly; without
    # it the classifier diffs `cfg.repo` against `--base` (default origin/branch).
    gsc = sub.add_parser("gate-scope")
    gsc.add_argument("--config", required=True,
                     help="path to product JSON config")
    gsc.add_argument("--base", default=None,
                     help="git base ref to diff against (default origin/<branch>)")
    gsc.add_argument("--files", nargs="*", default=None,
                     help="classify these paths directly instead of a git diff")
    # `status` prints a read-only company-health snapshot for one product (the
    # latest iter + the last ship's POSTRELEASE verdict + the two flag files +
    # the prd line) and returns 0 healthy / 1 needs-attention / 2 nothing-shipped.
    # On-demand only -- the pipeline/dispatcher NEVER call it; it writes nothing.
    sts = sub.add_parser("status")
    sts.add_argument("--config", required=True,
                     help="path to product JSON config")
    sts.add_argument("--json", action="store_true",
                     help="emit the snapshot as one JSON document (machine-readable) "
                          "instead of the human report; same 0/1/2 exit code")
    # `history` prints a read-only, offline multi-iteration ship LEDGER for
    # one product: each iter's ACTION (from final.md) + POSTRELEASE verdict
    # + a rollup, in ascending order. `--limit N` shows only the most-recent
    # N. On-demand only -- the pipeline/dispatcher NEVER call it; it writes
    # nothing. Exit 0 (has history) / 2 (nothing shipped yet).
    his = sub.add_parser("history")
    his.add_argument("--config", required=True,
                     help="path to product JSON config")
    his.add_argument("--limit", type=int, default=None,
                     help="show only the most-recent N iterations (default: all)")
    his.add_argument("--json", action="store_true",
                     help="emit the ledger as one JSON document (machine-readable) "
                          "instead of the human report; same 0/2 exit code, honours --limit")
    # `timing` prints a read-only, offline per-iteration suite-wall-time DIGEST
    # (min/max/avg/last/slow-count) for one product, parsed from each iter's
    # `postrelease.md` `suite_seconds` body line, ascending. `--limit N` shows
    # only the most-recent N. On-demand only -- the pipeline/dispatcher NEVER
    # call it; it writes nothing. Exit 0 (has measured timings) / 2 (none yet).
    tmg = sub.add_parser("timing")
    tmg.add_argument("--config", required=True,
                     help="path to product JSON config")
    tmg.add_argument("--limit", type=int, default=None,
                     help="show only the most-recent N iterations (default: all)")
    tmg.add_argument("--json", action="store_true",
                     help="emit the digest as one JSON document (machine-readable) "
                          "instead of the human report; same 0/2 exit code, honours --limit")
    # `weak-tests` scans a product's test files for assertion-free `test*`
    # functions (a test with no assertion passes without validating anything --
    # a false green). DORMANT / on-demand only -- the pipeline/gate/dispatcher
    # NEVER call it; it writes nothing. `--files` scans EXACTLY those paths
    # instead of walking `cfg.repo`. Exit 0 clean / 1 weak-or-unparseable / 2
    # nothing to scan.
    wkt = sub.add_parser("weak-tests")
    wkt.add_argument("--config", required=True,
                     help="path to product JSON config")
    wkt.add_argument("--files", nargs="*", default=None,
                     help="scan these test files directly instead of walking the repo")
    wkt.add_argument("--json", action="store_true",
                     help="emit the scan as one JSON document (machine-readable) "
                          "instead of the human report; same 0/1/2 exit code, honours --files")
    # `constant-asserts` scans a product's test files for `test*` functions
    # whose ONLY assertion signal is a constant/tautological assert (`assert
    # True`, `assert 1`, `assert "x"`) -- a false green that `weak-tests`
    # structurally MISSES (a constant assert CARRIES an assert node, so
    # `find_assertionless_tests` reads it as a signal). The FIRST call site of
    # the iter-47 `find_constant_assert_tests` detector; DISJOINT from
    # `weak-tests` by construction. DORMANT / on-demand only -- the
    # pipeline/gate/dispatcher NEVER call it; it writes nothing. `--files` scans
    # EXACTLY those paths instead of walking `cfg.repo`. Exit 0 clean / 1
    # constant-assert-or-unparseable / 2 nothing to scan.
    cas = sub.add_parser("constant-asserts")
    cas.add_argument("--config", required=True,
                     help="path to product JSON config")
    cas.add_argument("--files", nargs="*", default=None,
                     help="scan these test files directly instead of walking the repo")
    cas.add_argument("--json", action="store_true",
                     help="emit the scan as one JSON document (machine-readable) "
                          "instead of the human report; same 0/1/2 exit code, honours --files")
    # `skipped-tests` scans a product's test files for `test*` functions
    # that are UNCONDITIONALLY skipped -- `@pytest.mark.skip` /
    # `@unittest.skip`, or a constant-condition `@skipif(True)` /
    # `@skipUnless(False)`. Such a test NEVER runs, validates nothing, yet
    # reports the suite green, and no gate catches it (the item-11 fresh-clone
    # re-run passes a skipped test too). The FIRST call site of the iter-55
    # `find_always_skipped_tests` detector; a THIRD complementary lens that
    # can OVERLAP #12/#21 (a skipped test may also be assertion-free) by
    # catching a DIFFERENT antipattern -- a test that never runs at all.
    # DORMANT / on-demand only -- the pipeline/gate/dispatcher NEVER call it;
    # it writes nothing. `--files` scans EXACTLY those paths instead of
    # walking `cfg.repo`. Exit 0 clean / 1 always-skipped-or-unparseable / 2
    # nothing to scan.
    skt = sub.add_parser("skipped-tests")
    skt.add_argument("--config", required=True,
                     help="path to product JSON config")
    skt.add_argument("--files", nargs="*", default=None,
                     help="scan these test files directly instead of walking the repo")
    skt.add_argument("--json", action="store_true",
                     help="emit the scan as one JSON document (machine-readable) "
                          "instead of the human report; same 0/1/2 exit code, honours --files")
    # `test-quality` is the per-product COMPOSITE gate: it folds all THREE
    # offline "validates-nothing" scans -- #12 `weak-tests` (assertion-free),
    # #21 `constant-asserts` (constant/tautological assert), #23 `skipped-tests`
    # (never runs) -- into ONE scan / ONE 0/1/2 exit code / ONE three-way verdict
    # / ONE JSON doc, the QUALITY-axis parallel of the #15 launch `preflight`
    # composite. #21 is DISJOINT from #12, but a #23 always-skipped test may ALSO
    # be assertion-free AND carry a constant assert, so its findings can OVERLAP
    # #12/#21 -- therefore `total quality findings` is a per-CATEGORY triage
    # total (a test flagged by two lenses counts once per category), NOT a
    # de-duplicated distinct-test count. DORMANT / on-demand only -- the
    # pipeline/gate/dispatcher NEVER call it; it writes nothing. `--files` scans
    # EXACTLY those paths instead of walking `cfg.repo`. Exit 0 clean / 1
    # quality-issues / 2 nothing to scan.
    tq = sub.add_parser("test-quality")
    tq.add_argument("--config", required=True,
                    help="path to product JSON config")
    tq.add_argument("--files", nargs="*", default=None,
                    help="scan these test files directly instead of walking the repo")
    tq.add_argument("--json", action="store_true",
                    help="emit the composite scan as one JSON document (machine-readable) "
                         "instead of the human report; same 0/1/2 exit code, honours --files")
    # `events` reads/digests a product's typed `events.jsonl` (item 10, the READ
    # half): filter by `--kind`, tail the most-recent `--limit N`, count by kind,
    # human or `--json` output. Read-only + DORMANT -- the pipeline/dispatcher
    # NEVER call it; it writes nothing. Exit 0 (>=1 shown) / 2 (nothing shown).
    evt = sub.add_parser("events")
    evt.add_argument("--config", required=True,
                     help="path to product JSON config")
    evt.add_argument("--kind", default=None,
                     help="show only records whose kind equals this exact string")
    evt.add_argument("--limit", type=int, default=None,
                     help="show only the most-recent N matched records (default: all)")
    evt.add_argument("--json", action="store_true",
                     help="emit the digest as one JSON document (machine-readable) "
                          "instead of the human report; same 0/2 exit code, honours --kind/--limit")
    # `preflight` is the composite LAUNCH gate: it runs the env preflight
    # (`doctor`, iter 01) AND the single-brain scan (iter 24) and folds them into
    # ONE three-way GO / NO-GO / CAUTION verdict (human or `--json`) an operator /
    # launch wrapper checks before starting `dispatcher.py`. It needs `--config`
    # (for `run_doctor`), so it is dispatched AFTER `load_config` below. Read-only
    # + on-demand: the pipeline/dispatcher NEVER call it, it writes nothing, and it
    # only REPORTS (never kills/signals a competing brain -- the operator decides).
    # Exit 0 GO / 1 NO-GO / 2 CAUTION.
    pfl = sub.add_parser("preflight")
    pfl.add_argument("--config", required=True,
                     help="path to product JSON config")
    pfl.add_argument("--pattern", default="dispatcher.py",
                     help="process-command pattern to scan for a running "
                          "dispatcher (default 'dispatcher.py')")
    pfl.add_argument("--json", action="store_true",
                     help="emit the composite verdict as one JSON document "
                          "(machine-readable) instead of the human report; "
                          "same 0/1/2 exit code")
    # `company-status` rolls up EVERY enabled dispatch team's iter-16
    # `status` health into ONE company verdict. Its `--config` points at the
    # DISPATCH config (`foundry.config.json`), NOT a product config, and it
    # does its own per-work-item `load_config` internally -- so, like
    # `single-brain`/`lint-spec`, it is dispatched BEFORE the
    # `load_config(args.config)` call below. Read-only + on-demand: the
    # pipeline/dispatcher NEVER call it; it writes nothing. Exit 0 healthy /
    # 1 needs-attention / 2 no-enabled-products.
    cst = sub.add_parser("company-status")
    cst.add_argument("--config", default=str(FOUNDRY / "foundry.config.json"),
                     help="path to the DISPATCH config (foundry.config.json), "
                          "NOT a product config (default: the repo's "
                          "foundry.config.json)")
    cst.add_argument("--json", action="store_true",
                     help="emit the company roll-up as one JSON document "
                          "(machine-readable) instead of the human report; "
                          "same 0/1/2 exit code")
    # `company-history` rolls up EVERY enabled dispatch team's iter-17
    # ship LEDGER into ONE company-wide view (total iterations / shipped /
    # reverted / broken summed across all teams). Its `--config` points at the
    # DISPATCH config (`foundry.config.json`), NOT a product config, and it
    # does its own per-work-item `load_config` internally -- so, like
    # `company-status`/`single-brain`/`lint-spec`, it is dispatched BEFORE the
    # `load_config(args.config)` call below. Read-only + on-demand: the
    # pipeline/dispatcher NEVER call it; it writes nothing. Exit 0
    # gathered-no-errors / 1 errors / 2 no-enabled-products.
    chi = sub.add_parser("company-history")
    chi.add_argument("--config", default=str(FOUNDRY / "foundry.config.json"),
                     help="path to the DISPATCH config (foundry.config.json), "
                          "NOT a product config (default: the repo's "
                          "foundry.config.json)")
    chi.add_argument("--limit", type=int, default=None,
                     help="show only the most-recent N iterations per team "
                          "(default: all)")
    chi.add_argument("--json", action="store_true",
                     help="emit the company roll-up as one JSON document "
                          "(machine-readable) instead of the human report; "
                          "same 0/1/2 exit code, honours --limit")
    # `company-timing` rolls up EVERY enabled dispatch team's iter-18
    # suite-wall-time DIGEST into ONE company throughput lens (pooled
    # min/max/avg + summed measured/total/slow-count across all teams -- the
    # THROUGHPUT complement to `company-status` health-NOW and `company-history`
    # ship-LEDGER). Its `--config` points at the DISPATCH config
    # (`foundry.config.json`), NOT a product config, and it does its own
    # per-work-item `load_config` internally -- so, like `company-status`/
    # `company-history`/`single-brain`/`lint-spec`, it is dispatched BEFORE the
    # `load_config(args.config)` call below. Read-only + on-demand: the
    # pipeline/dispatcher NEVER call it; it writes nothing. Timing is
    # INFORMATIONAL and never gates on a slow suite -- exit 0
    # gathered-no-errors / 1 errors / 2 no-enabled-products.
    ctm = sub.add_parser("company-timing")
    ctm.add_argument("--config", default=str(FOUNDRY / "foundry.config.json"),
                     help="path to the DISPATCH config (foundry.config.json), "
                          "NOT a product config (default: the repo's "
                          "foundry.config.json)")
    ctm.add_argument("--limit", type=int, default=None,
                     help="show only the most-recent N iterations per team "
                          "(default: all)")
    ctm.add_argument("--json", action="store_true",
                     help="emit the company roll-up as one JSON document "
                          "(machine-readable) instead of the human report; "
                          "same 0/1/2 exit code, honours --limit")
    # `company-weak-tests` rolls up EVERY enabled dispatch team's iter-22
    # `weak-tests` scan into ONE company view (summed files-scanned /
    # assertion-free-tests / parse-errors + a per-product breakdown -- the
    # QUALITY complement to `company-status` health-NOW, `company-history`
    # ship-LEDGER and `company-timing` THROUGHPUT). Its `--config` points at the
    # DISPATCH config (`foundry.config.json`), NOT a product config, and it does
    # its own per-work-item `load_config` internally -- so, like `company-status`/
    # `company-history`/`company-timing`/`single-brain`/`lint-spec`, it is
    # dispatched BEFORE the `load_config(args.config)` call below. Read-only +
    # on-demand: the pipeline/dispatcher NEVER call it; it writes nothing. UNLIKE
    # informational history/timing it GATES on findings -- a worthless test OR an
    # unparseable file OR a team error ANYWHERE -> exit 1; else 0 clean / 2
    # no-enabled-products. NO --limit (a scan is whole-suite, not most-recent-N).
    cwk = sub.add_parser("company-weak-tests")
    cwk.add_argument("--config", default=str(FOUNDRY / "foundry.config.json"),
                     help="path to the DISPATCH config (foundry.config.json), "
                          "NOT a product config (default: the repo's "
                          "foundry.config.json)")
    cwk.add_argument("--json", action="store_true",
                     help="emit the company roll-up as one JSON document "
                          "(machine-readable) instead of the human report; "
                          "same 0/1/2 exit code")
    # `company-events` rolls up EVERY enabled dispatch team's iter-27 `events`
    # digest into ONE company view (summed total/matched/shown/malformed + a
    # merged per-kind tally + a per-product breakdown -- the ACTIVITY complement
    # to `company-status` health-NOW, `company-history` ship-LEDGER,
    # `company-timing` THROUGHPUT and `company-weak-tests` QUALITY; the 5th and
    # LAST company-* member). Its `--config` points at the DISPATCH config
    # (`foundry.config.json`), NOT a product config, and it does its own
    # per-work-item `load_config` internally -- so, like `company-status`/
    # `company-history`/`company-timing`/`company-weak-tests`/`single-brain`/
    # `lint-spec`, it is dispatched BEFORE the `load_config(args.config)` call
    # below. Read-only + on-demand: the pipeline/dispatcher NEVER call it; it
    # writes nothing. INFORMATIONAL like history/timing -- a malformed line or a
    # quiet team never gates; only a structural gather error -> exit 1; else 0
    # gathered-no-errors / 2 no-enabled-products. `--kind`/`--limit` pass through
    # to every team's gather.
    cev = sub.add_parser("company-events")
    cev.add_argument("--config", default=str(FOUNDRY / "foundry.config.json"),
                     help="path to the DISPATCH config (foundry.config.json), "
                          "NOT a product config (default: the repo's "
                          "foundry.config.json)")
    cev.add_argument("--kind", default=None,
                     help="show only records whose kind equals this exact string "
                          "(applied to every team's gather)")
    cev.add_argument("--limit", type=int, default=None,
                     help="show only the most-recent N matched records per team "
                          "(default: all)")
    cev.add_argument("--json", action="store_true",
                     help="emit the company roll-up as one JSON document "
                          "(machine-readable) instead of the human report; "
                          "same 0/1/2 exit code, honours --kind/--limit")
    # `company-constant-asserts` rolls up EVERY enabled dispatch team's iter-21
    # `constant-asserts` scan into ONE company view (summed files-scanned /
    # constant-assert-tests / parse-errors + a per-product breakdown -- the
    # QUALITY complement to `company-weak-tests`, catching the CONSTANT-assert
    # false-green that `weak-tests` structurally misses; the 6th and LAST
    # company-* member). Its `--config` points at the DISPATCH config
    # (`foundry.config.json`), NOT a product config, and it does its own
    # per-work-item `load_config` internally -- so, like `company-status`/
    # `company-history`/`company-timing`/`company-weak-tests`/`company-events`/
    # `single-brain`/`lint-spec`, it is dispatched BEFORE the
    # `load_config(args.config)` call below. Read-only + on-demand: the
    # pipeline/dispatcher NEVER call it; it writes nothing. UNLIKE informational
    # history/timing/events it GATES on findings -- a constant-assert test OR an
    # unparseable file OR a team error ANYWHERE -> exit 1; else 0 clean / 2
    # no-enabled-products. NO --limit and NO --files (a scan is whole-suite; each
    # team walks its own repo).
    cca = sub.add_parser("company-constant-asserts")
    cca.add_argument("--config", default=str(FOUNDRY / "foundry.config.json"),
                     help="path to the DISPATCH config (foundry.config.json), "
                          "NOT a product config (default: the repo's "
                          "foundry.config.json)")
    cca.add_argument("--json", action="store_true",
                     help="emit the company roll-up as one JSON document "
                          "(machine-readable) instead of the human report; "
                          "same 0/1/2 exit code")
    # `company-skipped-tests` rolls up EVERY enabled dispatch team's iter-23
    # `skipped-tests` scan into ONE company view (summed files-scanned /
    # always-skipped-tests / parse-errors + a per-product breakdown -- the
    # QUALITY complement to `company-weak-tests`/`company-constant-asserts`; the
    # 7th company-* member). UNLIKE the DISJOINT `company-constant-asserts`, an
    # always-skipped test CAN also be assertion-free, so its findings CAN OVERLAP
    # `company-weak-tests`/`company-constant-asserts` -- a THIRD COMPLEMENTARY
    # lens catching a DIFFERENT antipattern (a test that never RUNS at all). Its
    # `--config` points at the DISPATCH config (`foundry.config.json`), NOT a
    # product config, and it does its own per-work-item `load_config` internally
    # -- so, like the other `company-*` commands, it is dispatched BEFORE the
    # `load_config(args.config)` call below. Read-only + on-demand: the
    # pipeline/dispatcher NEVER call it; it writes nothing. UNLIKE informational
    # history/timing/events it GATES on findings -- an always-skipped test OR an
    # unparseable file OR a team error ANYWHERE -> exit 1; else 0 clean / 2
    # no-enabled-products. NO --limit and NO --files (a scan is whole-suite; each
    # team walks its own repo).
    cst = sub.add_parser("company-skipped-tests")
    cst.add_argument("--config", default=str(FOUNDRY / "foundry.config.json"),
                     help="path to the DISPATCH config (foundry.config.json), "
                          "NOT a product config (default: the repo's "
                          "foundry.config.json)")
    cst.add_argument("--json", action="store_true",
                     help="emit the company roll-up as one JSON document "
                          "(machine-readable) instead of the human report; "
                          "same 0/1/2 exit code")
    # `company-test-quality` rolls up EVERY enabled dispatch team's iter-25
    # per-product `test-quality` composite into ONE company view (summed
    # files-scanned / per-category findings / total findings / parse-errors + a
    # per-product breakdown -- the COMPANY-axis parallel of the per-product #25
    # composite; the 8th company-* member and the QUALITY-axis capstone of the
    # company family). It folds the three company quality axes #19
    # `company-weak-tests` / #22 `company-constant-asserts` / #24
    # `company-skipped-tests` into ONE view, INHERITING #25's category-weighting:
    # UNLIKE the DISJOINT #22, an always-skipped test CAN also be assertion-free,
    # so its findings CAN OVERLAP #19/#22 -- therefore `total quality findings` is
    # a per-CATEGORY triage total (a test flagged by two lenses counts once per
    # category), NOT a de-duplicated distinct-test count. Its `--config` points at
    # the DISPATCH config (`foundry.config.json`), NOT a product config, and it
    # does its own per-work-item `load_config` internally -- so, like the other
    # `company-*` commands, it is dispatched BEFORE the `load_config(args.config)`
    # call below. Read-only + on-demand: the pipeline/dispatcher NEVER call it; it
    # writes nothing. UNLIKE informational history/timing/events it GATES on
    # findings -- a quality finding of ANY category OR an unparseable file OR a
    # team error ANYWHERE -> exit 1; else 0 clean / 2 no-enabled-products. NO
    # --limit and NO --files (a scan is whole-suite; each team walks its own repo).
    ctq = sub.add_parser("company-test-quality")
    ctq.add_argument("--config", default=str(FOUNDRY / "foundry.config.json"),
                     help="path to the DISPATCH config (foundry.config.json), "
                          "NOT a product config (default: the repo's "
                          "foundry.config.json)")
    ctq.add_argument("--json", action="store_true",
                     help="emit the company roll-up as one JSON document "
                          "(machine-readable) instead of the human report; "
                          "same 0/1/2 exit code")
    # `company-lint-config` rolls up EVERY enabled dispatch team's iter-27
    # per-product `lint-config` verdict into ONE company config-validation view
    # (summed config-errors / warnings / total-findings + a per-team breakdown --
    # the CONFIG-VALIDATION-axis fleet roll-up; the 9th company-* member, closing
    # the LONE read-only per-product probe that had no roll-up). Its `--config`
    # points at the DISPATCH config (`foundry.config.json`), NOT a product config,
    # and it does its own per-work-item `load_config` internally -- so, like the
    # other `company-*` commands, it is dispatched BEFORE the
    # `load_config(args.config)` call below. Read-only + on-demand: the
    # pipeline/dispatcher NEVER call it; it writes nothing. KEY divergence from
    # the QUALITY roll-ups: ONLY config ERRORS gate -- a team load/gather error OR
    # a product config ERROR ANYWHERE -> exit 1; WARNINGS ALONE STILL PASS (a
    # warning names a degraded-but-runnable config), surfaced but non-gating; else
    # 0 clean-or-warnings-only / 2 no-enabled-products. NO --limit and NO --files
    # (a lint is one config per team).
    clc = sub.add_parser("company-lint-config")
    clc.add_argument("--config", default=str(FOUNDRY / "foundry.config.json"),
                     help="path to the DISPATCH config (foundry.config.json), "
                          "NOT a product config (default: the repo's "
                          "foundry.config.json)")
    clc.add_argument("--json", action="store_true",
                     help="emit the company roll-up as one JSON document "
                          "(machine-readable) instead of the human report; "
                          "same 0/1/2 exit code")
    args = ap.parse_args(argv)

    if args.cmd == "lint-spec":
        return lint_spec_cli(args.file)
    if args.cmd == "gate-precheck":
        return gate_precheck_cli(args.file, as_json=args.json)
    if args.cmd == "gate-verdict":
        return gate_verdict_cli(args.business, args.product, args.engineering, as_json=args.json)
    if args.cmd == "role-model":
        return role_model_cli(args.model, as_json=args.json)
    if args.cmd == "product-gate":
        return product_gate_cli(args.file, args.business, args.product,
                                args.engineering, as_json=args.json)
    if args.cmd == "escalation-check":
        return escalation_check_cli(args.file, as_json=args.json)
    if args.cmd == "cadence-review":
        return cadence_review_cli(args.counter, args.trigger_fired, args.n, as_json=args.json)
    if args.cmd == "restaffing-review":
        return restaffing_review_cli(args.file, as_json=args.json)
    if args.cmd == "scout-plan":
        return scout_plan_cli(args.dual_pm_scouts, args.lens, as_json=args.json)
    if args.cmd == "lint-config":
        return lint_config_cli(args.config, as_json=args.json)
    if args.cmd == "lint-bench":
        return lint_bench_cli(bench_dir=args.dir, as_json=args.json)
    if args.cmd == "lint-manifest":
        return lint_manifest_cli(args.file, bench_dir=args.bench_dir,
                                 as_json=args.json)
    if args.cmd == "single-brain":
        return single_brain_cli(pattern=args.pattern, as_json=args.json)
    if args.cmd == "company-status":
        return company_status_cli(args.config, as_json=args.json)
    if args.cmd == "company-history":
        return company_history_cli(args.config, limit=args.limit,
                                   as_json=args.json)
    if args.cmd == "company-timing":
        return company_timing_cli(args.config, limit=args.limit,
                                  as_json=args.json)
    if args.cmd == "company-weak-tests":
        return company_weak_tests_cli(args.config, as_json=args.json)
    if args.cmd == "company-events":
        return company_events_cli(args.config, kind=args.kind,
                                  limit=args.limit, as_json=args.json)
    if args.cmd == "company-constant-asserts":
        return company_constant_asserts_cli(args.config, as_json=args.json)
    if args.cmd == "company-skipped-tests":
        return company_skipped_tests_cli(args.config, as_json=args.json)
    if args.cmd == "company-test-quality":
        return company_test_quality_cli(args.config, as_json=args.json)
    if args.cmd == "company-lint-config":
        return company_config_lint_cli(args.config, as_json=args.json)

    cfg = load_config(args.config)
    if args.cmd == "doctor":
        return run_doctor_cli(cfg)
    if args.cmd == "learnings":
        return learnings_cli(cfg, recent=args.recent)
    if args.cmd == "agents":
        return agents_cli(cfg, recent=args.recent, print_only=args.print_only)
    if args.cmd == "prd":
        return prd_status_cli(cfg)
    if args.cmd == "gate-scope":
        return gate_scope_cli(cfg, files=args.files, base=args.base)
    if args.cmd == "status":
        return status_cli(cfg, as_json=args.json)
    if args.cmd == "history":
        return history_cli(cfg, limit=args.limit, as_json=args.json)
    if args.cmd == "timing":
        return timing_cli(cfg, limit=args.limit, as_json=args.json)
    if args.cmd == "weak-tests":
        return weak_tests_cli(cfg, files=args.files, as_json=args.json)
    if args.cmd == "constant-asserts":
        return constant_asserts_cli(cfg, files=args.files, as_json=args.json)
    if args.cmd == "skipped-tests":
        return skipped_tests_cli(cfg, files=args.files, as_json=args.json)
    if args.cmd == "test-quality":
        return test_quality_cli(cfg, files=args.files, as_json=args.json)
    if args.cmd == "events":
        return events_cli(cfg, kind=args.kind, limit=args.limit, as_json=args.json)
    if args.cmd == "preflight":
        return preflight_cli(cfg, pattern=args.pattern, as_json=args.json)
    if args.cmd == "once":
        res = run_iteration(cfg)
        print(json.dumps(res))
        return 0
    return run_continuous(cfg)


if __name__ == "__main__":
    sys.exit(main())
