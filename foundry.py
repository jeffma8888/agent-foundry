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
            test_ok = run_cmd(shlex.split(cfg.test_cmd), cwd=clone_dir).ok
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


def _write_postrelease_artifact(artifact: pathlib.Path, expected_sha: str,
                                result: "PostReleaseResult") -> None:
    """Write the per-iteration `postrelease.md` sentinel artifact.

    The LAST non-empty line is EXACTLY `result.sentinel`, mirroring the
    `VERDICT:`/`RESULT:`/`ACTION:` sentinel-line contract so the verdict is
    greppable and machine-readable. The body carries the pushed sha and the
    verdict detail for a human reading the artifact.
    """
    artifact.write_text(
        f"# Post-release fresh-clone verification -- pushed sha {expected_sha}\n\n"
        f"- skipped_infra: {result.skipped_infra}\n"
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

    _write_postrelease_artifact(artifact, expected_sha, result)
    return result


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
    if args.cmd == "once":
        res = run_iteration(cfg)
        print(json.dumps(res))
        return 0
    return run_continuous(cfg)


if __name__ == "__main__":
    sys.exit(main())
