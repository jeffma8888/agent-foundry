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
    quality_bar: str = ""        # free-form product quality constraints
    push_enabled: bool = True    # gate may push (False => dry-run / review-only)
    # Post-release fresh-clone verification (dormant until wired in iter 03).
    # Backward-compatible: old configs that omit these load with these defaults.
    postrelease_enabled: bool = True   # run the fresh-clone verify (iter 03+)
    setup_cmd: str = "uv sync"          # how to install deps in the fresh clone
    smoke_cmd: str | None = None       # optional smoke command; None => skipped

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


def emit_event(events_path: pathlib.Path, event: str, **fields) -> None:
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
        ``ts=`` in ``**fields`` can never shadow the real timestamp.
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
    try:
        emit_event(cfg.events_log, "log", product=cfg.name, msg=msg)
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


def status_cli(cfg: ProductConfig, as_json: bool = False) -> int:
    """On-demand CLI: print a company-health snapshot + a 0/1/2 exit code.

    With `as_json=True` the entire stdout is ONE `json.dumps(summary.
    to_dict(), indent=2)` document (the stable machine contract for
    dashboards/alerts); the default `as_json=False` is byte-for-byte the
    iter-16 human `render()` text. Either way the RETURN value is the same
    `summary.exit_code`, and nothing is written to disk.

    Gathers every signal through the EXISTING module-level seams -- called by
    BARE name so a `monkeypatch.setattr(foundry, ...)` in a test bites -- then
    hands them to the pure `summarize_status`/`StatusSummary` core:
      * `latest_iter` = `next_iteration(cfg) - 1` (the highest shipped iter);
      * the latest iter's `state/iter-NN/postrelease.md` (2-digit zero-pad), read
        GUARDED through `parse_postrelease_verdict` (absent file / read error ->
        `None`, so a no-ship iteration reads as `unknown`, never an error);
      * the two flag files via `hotfix_flag_path(cfg).exists()` /
        `speed_story_flag_path(cfg).exists()`;
      * the prd progress via `dispatch_progress_line(cfg)`.
    Prints `summary.render()` and returns `summary.exit_code`. Writes NOTHING to
    disk (read-only) -- a thin wrapper over the pure core that adds no decision
    logic of its own, so the printed verdict always equals the `StatusSummary`
    fields."""
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
    summary = summarize_status(
        product=cfg.name, repo=cfg.repo, branch=cfg.branch,
        latest_iter=latest_iter, postrelease=postrelease,
        hotfix=hotfix_flag_path(cfg).exists(),
        speed_story=speed_story_flag_path(cfg).exists(),
        prd_line=dispatch_progress_line(cfg))
    # `--json` emits the pure snapshot as a single JSON document (stdout-only, no
    # decision logic added); the default stays the exact iter-16 human report.
    print(json.dumps(summary.to_dict(), indent=2) if as_json else summary.render())
    return summary.exit_code


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


def history_cli(cfg: ProductConfig, limit: int | None = None,
                as_json: bool = False) -> int:
    """On-demand CLI: print a multi-iteration ship ledger + a 0/2 exit code.

    With `as_json=True` the entire stdout is ONE `json.dumps(summary.to_dict(),
    indent=2)` document (the stable machine contract for dashboards/reporters,
    mirroring iter-19's `status --json`); the default `as_json=False` is
    byte-for-byte the iter-17 human `render()` text. Either way the RETURN value
    is the same `summary.exit_code`, `--limit` selection is identical, and
    nothing is written to disk.

    Gathers every signal through the EXISTING module-level seams -- called by
    BARE name so a `monkeypatch.setattr(foundry, ...)` in a test bites:
      * lists `cfg.state`'s dir names (guarded -- a missing state dir yields no
        names, never an error) and derives the iteration numbers via
        `iteration_numbers`;
      * applies `limit` -- keep the highest-N iterations when `limit` is a
        POSITIVE int, else ALL (a missing / non-positive `--limit` shows the full
        run); the numbers stay ascending so the ledger reads oldest-first;
      * for each iteration reads `state/iter-NN/final.md` through
        `parse_ship_action` and `state/iter-NN/postrelease.md` through the
        EXISTING `parse_postrelease_verdict`, both guarded to `None` on an absent
        file / read error.
    Hands the records to the pure `summarize_history`/`HistorySummary` core,
    prints `render()`, and returns `exit_code`. Writes NOTHING to disk
    (read-only) -- no decision logic of its own, so the printed rollup always
    equals the `HistorySummary` fields."""
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
    summary = summarize_history(product=cfg.name, records=records)
    # `--json` emits the pure ledger as a single JSON document (stdout-only, no
    # decision logic added); the default stays the exact iter-17 human report.
    print(json.dumps(summary.to_dict(), indent=2) if as_json else summary.render())
    return summary.exit_code


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


def timing_cli(cfg: ProductConfig, limit: int | None = None,
               as_json: bool = False) -> int:
    """On-demand CLI: print a per-iteration suite-wall-time digest + 0/2 exit code.

    With `as_json=True` the entire stdout is ONE `json.dumps(summary.to_dict(),
    indent=2)` document (the stable machine contract for dashboards/reporters,
    mirroring iter-19's `status --json` and iter-20's `history --json`); the
    default `as_json=False` is byte-for-byte the iter-18 human `render()` text.
    Either way the RETURN value is the same `summary.exit_code`, `--limit`
    selection is identical, and nothing is written to disk.

    Gathers every signal through the EXISTING module-level seams -- each called by
    BARE name so a `monkeypatch.setattr(foundry, ...)` in a test bites:
      * lists `cfg.state`'s dir names (guarded -- a missing / unreadable state dir
        yields no names, never an error) and derives the iteration numbers via
        `iteration_numbers`;
      * applies `limit` -- keep the highest-N (most-recent) iterations when `limit`
        is a POSITIVE int, else ALL; the numbers stay ascending so the digest reads
        oldest-first;
      * for each iteration reads `state/iter-NN/postrelease.md` through
        `parse_suite_seconds` (via the shared `_read_sentinel` guard -> `None` on an
        absent file / `OSError`), building an ascending `TimingRecord`.
    Reads the slow `threshold` from the module global `SUITE_SLOW_SECONDS` AT CALL
    time (patchable), hands the records to the pure `summarize_timing`, prints
    `render()`, and returns `exit_code`. Writes NOTHING to disk (read-only) -- no
    decision logic of its own, so the printed rollup always equals the
    `TimingSummary` fields."""
    state = cfg.state
    try:
        names = [p.name for p in state.iterdir()] if state.exists() else []
    except OSError:
        # A read error on the state dir degrades to "no iterations", never
        # crashing the probe (same no-news-is-good-news contract as the artifacts).
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
    summary = summarize_timing(product=cfg.name, records=records,
                              threshold=SUITE_SLOW_SECONDS)
    # `--json` emits the pure digest as a single JSON document (stdout-only, no
    # decision logic added); the default stays the exact iter-18 human report.
    print(json.dumps(summary.to_dict(), indent=2) if as_json else summary.render())
    return summary.exit_code


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
    args = ap.parse_args(argv)

    if args.cmd == "lint-spec":
        return lint_spec_cli(args.file)

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
    if args.cmd == "once":
        res = run_iteration(cfg)
        print(json.dumps(res))
        return 0
    return run_continuous(cfg)


if __name__ == "__main__":
    sys.exit(main())
