#!/usr/bin/env python3
"""Portable, committed leak-guard (roadmap item 16, bites 1-2 of 3).

WHY this lives in tracked source rather than a git hook: this repository is
public and the autonomous dispatcher auto-pushes on every successful ship with no
human in the review loop. A drifted iteration could reintroduce internal or
personal tokens -- an internal agent-CLI name (and its .app / _BIN variants), a
model-provider service name, two internal skill names, an internal auth command,
a personal home-path prefix, a personal username -- into a public commit. The
only guard today is a LOCAL pre-push hook, and git does NOT clone hooks, so a
fresh checkout, a new operator, CI, and the post-release fresh-clone verify all
run with ZERO leak protection. A committed scanner is portable and therefore
always armed.

WHY the denylist is base64-encoded: a committed scanner that embedded its needles
as raw literals would ITSELF leak them -- the exact thing it guards against -- to
GitHub code search, automated secret scanners, and casual browsing. So the
committed denylist stores every needle URL-safe-base64-encoded; the plaintext
file reveals no secret, and a self-scan meta-test proves both committed files are
clean.

Bite 1 shipped the pure, offline, stdlib-only core -- encode_pattern /
load_denylist / scan_text. Bite 2 (this bite) makes it RUNNABLE: a main() CLI
that scans a git tree (--ref, default HEAD) or an explicit --files list against
the committed denylist and exits non-zero on any hit, funnelling its one
external effect through the monkeypatchable run_git seam. It is STILL a
standalone script off the pipeline control path -- nothing in the running loop
imports it, so foundry.py / dispatcher.py stay untouched. install_hooks.sh +
setup docs are bite 2b; wiring it into the ship gate is bite 3.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import dataclasses
import pathlib
import re
import subprocess
import sys
from typing import List, Optional, Sequence, Tuple

# Path to the committed denylist, resolved at runtime from this module's own
# location so NO literal home path ever appears in this (public) source file.
DENYLIST_PATH = pathlib.Path(__file__).resolve().parent / "leak_denylist.txt"

# Longest snippet kept in a finding record, so report lines stay bounded.
_SNIPPET_MAX = 90

# A denylist line must be pure URL-safe base64 (A-Z a-z 0-9 - _) with optional
# trailing '=' padding -- no '+' or '/'. Anchored so a stray disallowed char (a
# common non-base64 line) is rejected loudly rather than silently stripped.
_URLSAFE_B64_RE = re.compile(r"\A[A-Za-z0-9_-]*={0,2}\Z")


def encode_pattern(pattern: str) -> str:
    """URL-safe-base64-encode a regex PATTERN so the raw token never appears in
    committed plaintext.

    Round-trips exactly: ``urlsafe_b64decode(encode_pattern(p)).decode() == p``.
    The URL-safe alphabet (A-Z a-z 0-9 - _ =) contains no '/' or '+', so an
    encoded blob can never accidentally contain a home-path prefix, and the
    transform hides the literal token from casual reading / code search.
    """
    return base64.urlsafe_b64encode(pattern.encode("utf-8")).decode("ascii")


def _decode_pattern(encoded: str, lineno: int) -> str:
    """Reverse :func:`encode_pattern`, raising ``ValueError`` (naming the 1-based
    LINE NUMBER) on anything that is not valid URL-safe base64 or not UTF-8 --
    the guard fails loud and never silently drops a needle."""
    if not _URLSAFE_B64_RE.match(encoded):
        raise ValueError(
            f"leak_denylist line {lineno}: not valid URL-safe base64"
        )
    try:
        raw = base64.urlsafe_b64decode(encoded.encode("ascii"))
    except (binascii.Error, ValueError) as exc:
        raise ValueError(
            f"leak_denylist line {lineno}: not valid URL-safe base64: {exc}"
        ) from exc
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"leak_denylist line {lineno}: decoded bytes are not UTF-8: {exc}"
        ) from exc


def load_denylist(text: str) -> Tuple["re.Pattern[str]", ...]:
    """Parse denylist TEXT into an ordered tuple of compiled, case-insensitive
    regex patterns.

    Blank lines and lines whose first non-blank char is ``#`` are ignored; every
    other line must be a base64-encoded regex (see :func:`encode_pattern`). A
    line that is not valid URL-safe base64, or whose decoded text is not a valid
    regex, raises ``ValueError`` naming the offending 1-based line number -- a
    broken denylist is a hard error, never a quietly weakened guard.

    Patterns are compiled case-insensitively (a leaked token is a leak in any
    casing), preserving file order in the returned tuple.
    """
    patterns: List["re.Pattern[str]"] = []
    for lineno, raw_line in enumerate(text.splitlines(), 1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        decoded = _decode_pattern(stripped, lineno)
        try:
            patterns.append(re.compile(decoded, re.IGNORECASE))
        except re.error as exc:
            raise ValueError(
                f"leak_denylist line {lineno}: decoded text is not a valid "
                f"regex: {exc}"
            ) from exc
    return tuple(patterns)


def scan_text(
    text: str, patterns: Sequence["re.Pattern[str]"]
) -> Tuple[Tuple[int, str], ...]:
    """Scan TEXT line by line, returning ``((lineno, snippet), ...)`` for every
    line that matches at least one pattern.

    Line numbers are 1-based and ascending; AT MOST ONE record per matching line
    (the first match short-circuits -- we report the offending line, not each
    individual hit); each snippet is the line stripped of surrounding whitespace
    and truncated to 90 characters. Clean text yields the empty tuple.
    """
    findings: List[Tuple[int, str]] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for rx in patterns:
            if rx.search(line):
                findings.append((lineno, line.strip()[:_SNIPPET_MAX]))
                break
    return tuple(findings)


# --------------------------------------------------------------------------- #
# Bite 2 (roadmap item 16): the RUNNABLE surface over the bite-1 core.
#
# A committed scanner is only a guard if it can be RUN. This bite adds a
# `main()` CLI + the frozen `LeakReport` result + a single, monkeypatchable git
# seam (`run_git`) so a git TREE can be scanned fully offline in a test. The
# whole surface stays in this STANDALONE script (nothing in the running pipeline
# imports it), so it changes no loop/dispatcher semantics. Wiring it into the
# ship gate is bite 3.
# --------------------------------------------------------------------------- #

# Repo-relative path suffixes that are NEVER scanned: the guard's OWN files.
# They legitimately describe the needle categories, so scanning them would
# self-trip. Excluded by POSIX-suffix match. Read at CALL time via the bare
# module name (never captured at def-time) so a test's monkeypatch of this
# constant takes effect.
LEAK_GUARD_SKIP_PATHS: Tuple[str, ...] = (
    "scripts/leak_guard.py",
    "scripts/leak_denylist.txt",
)


@dataclasses.dataclass(frozen=True)
class LeakReport:
    """The immutable result of one leak scan (a `--files` list OR a git tree).

    `findings` is an ordered tuple of ``(path, lineno, snippet)`` -- one per
    matching line, in scan order (files in the order given / tree order, then
    ascending line within a file). `files_scanned` counts the files actually
    read (self-skip and unreadable paths excluded). `error` is a human string
    when the scan could NOT complete (bad denylist or git-seam failure) else
    ``None``. `exit_code` is a pure derivation of these fields, so the scriptable
    verdict can never drift from what was printed.
    """
    findings: Tuple[Tuple[str, int, str], ...]
    files_scanned: int
    error: Optional[str]

    @property
    def exit_code(self) -> int:
        """Scriptable verdict: ``2`` when the scan could not complete (error),
        else ``1`` when anything was flagged, else ``0`` (clean). Error is
        checked FIRST so a scan that never completed is never mistaken for a
        clean tree."""
        if self.error is not None:
            return 2
        if self.findings:
            return 1
        return 0

    def render(self) -> str:
        """The STDOUT block: one ``{path}:{lineno}: {snippet}`` line per
        finding, in scan order.

        Returns the empty string when clean so `main` prints NOTHING to STDOUT
        on a clean tree -- findings (STDOUT) and the summary/errors (STDERR) are
        never mixed, so a caller can pipe the STDOUT finding lines straight into
        another tool."""
        return "\n".join(
            f"{path}:{lineno}: {snippet}"
            for path, lineno, snippet in self.findings
        )

    def summary(self) -> str:
        """The one-line human summary for STDERR (never mixed into the STDOUT
        finding lines): the finding count + files scanned, or the error
        reason."""
        if self.error is not None:
            return f"leak-guard: ERROR -- {self.error}"
        return (f"leak-guard: {len(self.findings)} finding(s) "
                f"in {self.files_scanned} file(s) scanned")


def run_git(args: Sequence[str], *, repo: "pathlib.Path") -> str:
    """The ONE external-effect seam: run ``git <args>`` inside `repo` and return
    its stdout as text.

    In `--ref` mode every git call (the `ls-tree` blob enumeration and each
    `show` blob read) funnels through here, so a test monkeypatches THIS single
    function (dispatching on ``args[0]``) to drive the whole ref scan offline
    with ZERO real subprocess/git/network. Raises (e.g.
    ``subprocess.CalledProcessError`` on a non-zero git exit, ``FileNotFoundError``
    if git is absent) which `main` catches and turns into exit 2 -- the guard
    fails CLOSED, never with a traceback. Decodes with ``errors="replace"`` so a
    binary blob in the tree can never crash the scan."""
    completed = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        check=True,
        capture_output=True,
        text=True,
        errors="replace",
    )
    return completed.stdout


def _should_skip(path: str) -> bool:
    """True iff `path`'s POSIX form ends with any entry in the module-level
    `LEAK_GUARD_SKIP_PATHS`.

    The constant is read HERE at call time via its bare module name (not
    captured at def-time) so a test's ``monkeypatch.setattr(mod,
    "LEAK_GUARD_SKIP_PATHS", ...)`` bites. POSIX-suffix match so a repo-relative
    tree path (``scripts/leak_guard.py``) and an absolute CLI path
    (``/x/y/scripts/leak_guard.py``) both skip identically across platforms."""
    posix = pathlib.PurePath(path).as_posix()
    return any(posix.endswith(suffix) for suffix in LEAK_GUARD_SKIP_PATHS)


def scan_paths(
    paths: Sequence[str], patterns: Sequence["re.Pattern[str]"]
) -> Tuple[Tuple[Tuple[str, int, str], ...], int, Tuple[str, ...]]:
    """Scan an explicit list of filesystem PATHS against `patterns`.

    Returns ``(findings, files_scanned, missing)``. `findings` is an ordered
    tuple of ``(path, lineno, snippet)`` -- files in the given order, then
    ascending line within a file, and the path is the string AS PASSED so a
    report names exactly what the operator typed. `files_scanned` counts the
    files actually read. `missing` lists paths that could not be read: a SOFT
    skip -- the caller notes them on STDERR but they do NOT change the exit code,
    since an operator passing a stale path is not a leak. Self-skip paths
    (`_should_skip`) are excluded silently. Reuses the pure iter-49 `scan_text`
    per file (decoding with ``errors="replace"`` so a binary file cannot crash
    the scan); writes nothing."""
    findings: List[Tuple[str, int, str]] = []
    missing: List[str] = []
    files_scanned = 0
    for path in paths:
        if _should_skip(path):
            continue
        try:
            text = pathlib.Path(path).read_text(
                encoding="utf-8", errors="replace")
        except OSError:
            missing.append(path)
            continue
        files_scanned += 1
        for lineno, snippet in scan_text(text, patterns):
            findings.append((path, lineno, snippet))
    return tuple(findings), files_scanned, tuple(missing)


def scan_ref(
    ref: str, patterns: Sequence["re.Pattern[str]"], *, repo: "pathlib.Path"
) -> Tuple[Tuple[Tuple[str, int, str], ...], int]:
    """Scan every tracked blob in git tree `ref` against `patterns`.

    Enumerates repo-relative paths via ``run_git(["ls-tree", "-r",
    "--name-only", "-z", ref], repo=repo)`` (NUL-separated; empty / trailing
    entries dropped), then reads each non-skipped blob's text via
    ``run_git(["show", f"{ref}:{path}"], repo=repo)`` and scans it. `run_git` is
    called by BARE name so a monkeypatch bites, and it is the ONLY external
    effect, so replacing that one seam makes the whole ref scan offline. Returns
    ``(findings, files_scanned)`` with findings in tree order then ascending
    line. Propagates any git failure to the caller (`main` turns it into exit
    2)."""
    raw = run_git(["ls-tree", "-r", "--name-only", "-z", ref], repo=repo)
    findings: List[Tuple[str, int, str]] = []
    files_scanned = 0
    for path in (p for p in raw.split("\0") if p):
        if _should_skip(path):
            continue
        blob = run_git(["show", f"{ref}:{path}"], repo=repo)
        files_scanned += 1
        for lineno, snippet in scan_text(blob, patterns):
            findings.append((path, lineno, snippet))
    return tuple(findings), files_scanned


def _build_parser() -> "argparse.ArgumentParser":
    """Build the CLI parser: `--files` (explicit list) vs `--ref` (git tree,
    default HEAD when neither is given), plus `--denylist` (override the
    committed default) and `--repo` (git working dir for `--ref`)."""
    parser = argparse.ArgumentParser(
        prog="leak_guard",
        description=(
            "Scan a git tree or an explicit file list against the committed "
            "base64 denylist and exit non-zero on any leaked token."
        ),
    )
    parser.add_argument(
        "--files", nargs="+", metavar="PATH",
        help="scan exactly these files instead of a git tree",
    )
    parser.add_argument(
        "--ref", metavar="REF",
        help="git ref/tree to scan (default HEAD when neither --files nor "
             "--ref is given)",
    )
    parser.add_argument(
        "--denylist", metavar="PATH", default=None,
        help="override the committed denylist path (default: the co-located "
             "leak_denylist.txt)",
    )
    parser.add_argument(
        "--repo", metavar="DIR", default=".",
        help="git working directory for --ref mode (default: cwd)",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Runnable entry point: load the denylist, scan (files or a git ref), print
    findings to STDOUT + a one-line summary to STDERR, and return the scriptable
    exit code (0 clean / 1 findings / 2 error).

    NO Python traceback ever escapes: a bad/unreadable denylist or a git-seam
    failure is caught and reported as ONE STDERR ``error:`` line with exit 2 (the
    guard fails CLOSED). `--files` takes precedence when given; otherwise a git
    tree is scanned at `--ref` (default ``HEAD``). A missing/unreadable `--files`
    path is a SOFT skip (an STDERR note, no exit-code change) -- an operator's
    stale path is not a leak. DORMANT with respect to the pipeline: only an
    operator, a git hook, or the future ship gate (bite 3) calls this; the
    running loop never does."""
    args = _build_parser().parse_args(argv)

    denylist_path = (pathlib.Path(args.denylist)
                     if args.denylist is not None else DENYLIST_PATH)
    try:
        patterns = load_denylist(denylist_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        # A broken/unreadable denylist means the guard cannot function -- fail
        # CLOSED (exit 2) with ONE error line, never a traceback (Behavior 7).
        report = LeakReport(findings=(), files_scanned=0, error=str(exc))
        print(f"error: {report.error}", file=sys.stderr)
        return report.exit_code

    if args.files is not None:
        findings, files_scanned, missing = scan_paths(args.files, patterns)
        for path in missing:
            print(f"note: skipped unreadable path {path}", file=sys.stderr)
        report = LeakReport(
            findings=findings, files_scanned=files_scanned, error=None)
    else:
        ref = args.ref if args.ref is not None else "HEAD"
        try:
            findings, files_scanned = scan_ref(
                ref, patterns, repo=pathlib.Path(args.repo))
        except Exception as exc:
            # The git seam is git/operator-controlled; fail CLOSED (exit 2, one
            # error line, no traceback, no findings) rather than crash the
            # caller -- a git hook or the ship gate must never abort on a
            # scanner exception (Behavior 8).
            report = LeakReport(findings=(), files_scanned=0, error=str(exc))
            print(f"error: git scan of {ref!r} failed: {report.error}",
                  file=sys.stderr)
            return report.exit_code
        report = LeakReport(
            findings=findings, files_scanned=files_scanned, error=None)

    stdout_block = report.render()
    if stdout_block:
        print(stdout_block)
    print(report.summary(), file=sys.stderr)
    return report.exit_code


if __name__ == "__main__":  # pragma: no cover -- exercised via main(argv)
    sys.exit(main())
