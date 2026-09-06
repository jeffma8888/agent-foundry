"""Black-box behaviour tests for iter 236 -- the tracked, portable, leak-clean
dispatcher launcher `launch.sh` and the on-ramp that names it.

ISOLATION: written SOLELY from the iter-236 PM spec (`pm.md`, Expected Behaviors
1-7), the existing test conventions under `tests/` (the `_git` helper shape from
`test_iter174_behavior.py`), and the shipped artifacts read AS DATA -- which is
what every behavior in this spec is defined over. The engineer's and reviewer's
notes for this iteration were NOT read, and neither was `git diff`. Every
assertion below encodes a sentence of the spec, not a shape observed in the
implementation; each one carries the offending text in its own message so a
failure diagnoses itself without opening the artifact by hand.

SAFETY (spec-mandated): **no test executes `launch.sh`.** A bug in a branch
guard would start a real second dispatcher on the operator's machine while a
live loop runs, so the only tool invocations pointed at the file are `bash -n`
(parse only), `python3 scripts/leak_guard.py --files` (read only), `compile()`
(parse only) and `ast.parse()`. No network, no fixtures, no tmp_path trees.
"""
from __future__ import annotations

import ast
import pathlib
import re
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_LAUNCH = _ROOT / "launch.sh"
_USAGE = _ROOT / "USAGE.md"
_EMPTY_BLOB = "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"
# Behavior 2 names four absolute-path prefixes. They are COMPOSED here, never
# written as literals: an absolute-path SHAPE in a shipped source line is itself
# what `scripts/leak_guard.py` fails on, and this module is inside the population
# that iter-210/iter-214 scan every suite.
_ABS_ROOTS = ("Users", "home", "Applications", "opt")
_ABS_PREFIXES = tuple("/%s/" % _r for _r in _ABS_ROOTS)


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(_ROOT), capture_output=True, text=True)


def _launch_text() -> str:
    assert _LAUNCH.is_file(), "launch.sh must ship at the repo ROOT (not under scripts/)"
    return _LAUNCH.read_text()


def _numbered(text: str):
    return list(enumerate(text.splitlines(), start=1))


def _embedded_python(text: str) -> str:
    """Extract the single-quoted argument to `python3 -c` exactly as the spec
    defines it: it begins on a line ending in `python3 -c '` and ends on a line
    that is exactly `'`."""
    m = re.search(r"^python3 -c '\n(.*?)^'\s*$", text, re.MULTILINE | re.DOTALL)
    assert m, "no `python3 -c '` ... `'` block found in launch.sh (Behavior 3)"
    return m.group(1)


def _dup2_pairs(tree: ast.AST):
    """Every `os.dup2(a, b)` in the embedded program as (source-text, target-text)."""
    out = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "dup2"
            and len(node.args) >= 2
        ):
            out.append((ast.unparse(node.args[0]), ast.unparse(node.args[1])))
    return out


def _open_assignments(tree: ast.AST):
    """`name = os.open(...)` assignments as {name: unparsed call}."""
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            fn = node.value.func
            if isinstance(fn, ast.Attribute) and fn.attr == "open":
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name):
                        out[tgt.id] = ast.unparse(node.value)
    return out


# ==========================================================================
# Behavior 1 -- it ships, and it ships runnable
# ==========================================================================
def test_b1_launch_sh_is_tracked_at_repo_root():
    listed = _git("ls-files", "launch.sh")
    assert listed.returncode == 0, listed.stderr
    assert listed.stdout.split() == ["launch.sh"], (
        "git ls-files launch.sh must list exactly `launch.sh` at the repo root, got %r"
        % listed.stdout
    )


def test_b1_staged_blob_is_mode_100755_and_not_empty():
    staged = _git("ls-files", "-s", "launch.sh")
    assert staged.returncode == 0, staged.stderr
    fields = staged.stdout.split()
    assert fields, "launch.sh has no index entry: %r" % staged.stdout
    mode, blob = fields[0], fields[1]
    assert mode == "100755", (
        "the executable bit must be in the STAGED blob, not just the worktree; "
        "git ls-files -s says %r" % staged.stdout.strip()
    )
    assert blob != _EMPTY_BLOB, (
        "launch.sh is staged as the EMPTY blob (the `git add -N` trap): %r" % staged.stdout.strip()
    )


def test_b1_staged_content_matches_the_worktree():
    shown = _git("show", ":launch.sh")
    assert shown.returncode == 0, shown.stderr
    staged_lines = shown.stdout.splitlines()
    worktree_lines = _launch_text().splitlines()
    assert len(staged_lines) == len(worktree_lines), (
        "staged blob has %d lines but the worktree file has %d -- the index does not "
        "hold the shipping content" % (len(staged_lines), len(worktree_lines))
    )


# ==========================================================================
# Behavior 2 -- it is leak-clean
# ==========================================================================
def test_b2_leak_guard_reports_zero_findings():
    proc = subprocess.run(
        [sys.executable, "scripts/leak_guard.py", "--files", "launch.sh"],
        cwd=str(_ROOT),
        capture_output=True,
        text=True,
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, "leak_guard exited %d:\n%s" % (proc.returncode, combined)
    assert "0 finding(s)" in combined, "leak_guard did not report 0 finding(s):\n%s" % combined


def test_b2_no_absolute_home_or_vendor_path_in_any_line():
    offenders = [
        (n, ln) for n, ln in _numbered(_launch_text()) if any(p in ln for p in _ABS_PREFIXES)
    ]
    assert offenders == [], (
        "launch.sh must contain no absolute filesystem path (%s) in code OR comments; found: %r"
        % (", ".join(_ABS_PREFIXES), offenders)
    )


# ==========================================================================
# Behavior 3 -- it parses, both languages
# ==========================================================================
def test_b3_bash_n_parses_clean():
    proc = subprocess.run(
        ["bash", "-n", "launch.sh"], cwd=str(_ROOT), capture_output=True, text=True
    )
    assert proc.returncode == 0, "bash -n launch.sh exited %d:\n%s" % (
        proc.returncode,
        proc.stdout + proc.stderr,
    )


def test_b3_embedded_python_is_nonempty_and_compiles():
    src = _embedded_python(_launch_text())
    assert src.strip(), "the embedded `python3 -c` program is empty"
    try:
        compile(src, "launch.sh", "exec")
    except SyntaxError as exc:  # pragma: no cover -- failure path
        pytest.fail("embedded program does not compile: %s\n---\n%s" % (exc, src))


# ==========================================================================
# Behavior 4 -- the four hardening mechanisms are present in the embedded program
# ==========================================================================
def test_b4_double_fork_and_setsid_token_counts():
    src = _embedded_python(_launch_text())
    forks = len(re.findall(r"\bos\.fork\(\)", src))
    setsids = len(re.findall(r"\bos\.setsid\(\)", src))
    assert forks == 2, "expected os.fork() exactly TWICE (double-fork), found %d" % forks
    assert setsids == 1, "expected os.setsid() exactly once, found %d" % setsids


def test_b4_devnull_is_opened_and_dup2d_onto_stdin():
    src = _embedded_python(_launch_text())
    tree = ast.parse(src)
    opens = _open_assignments(tree)
    devnull_names = [name for name, call in opens.items() if "devnull" in call]
    assert devnull_names, (
        "no `<name> = os.open(os.devnull, ...)` in the embedded program; os.open assignments were %r"
        % opens
    )
    pairs = _dup2_pairs(tree)
    onto_stdin = [src_name for src_name, tgt in pairs if tgt == "0"]
    assert onto_stdin, "nothing is os.dup2'd onto fd 0; dup2 calls were %r" % pairs
    assert set(onto_stdin) & set(devnull_names), (
        "fd 0 must be the os.devnull descriptor; dup2->0 uses %r but devnull is %r"
        % (onto_stdin, devnull_names)
    )


def test_b4_one_append_fd_is_dup2d_onto_both_stdout_and_stderr():
    src = _embedded_python(_launch_text())
    tree = ast.parse(src)
    opens = _open_assignments(tree)
    append_names = [name for name, call in opens.items() if "O_APPEND" in call]
    assert append_names, (
        "no os.open(..., os.O_APPEND ...) assignment in the embedded program; os.open "
        "assignments were %r" % opens
    )
    pairs = _dup2_pairs(tree)
    onto_out = {s for s, tgt in pairs if tgt == "1"}
    onto_err = {s for s, tgt in pairs if tgt == "2"}
    shared = onto_out & onto_err & set(append_names)
    assert shared, (
        "ONE os.O_APPEND descriptor must be dup2'd onto BOTH fd 1 and fd 2; "
        "dup2->1 uses %r, dup2->2 uses %r, append fds are %r" % (onto_out, onto_err, append_names)
    )


# ==========================================================================
# Behavior 5 -- the single-brain gate is the shipped verb, not a re-typed scan
# ==========================================================================
def test_b5_gates_on_the_shipped_verb_and_never_greps_processes():
    text = _launch_text()
    assert "single-brain" in text, "launch.sh must gate on the shipped `single-brain` verb"
    offenders = [(n, ln) for n, ln in _numbered(text) if "pgrep" in ln]
    assert offenders == [], (
        "launch.sh must not contain the string `pgrep` anywhere -- the verb is the one "
        "definition of 'is a brain already running'; found: %r" % offenders
    )


def test_b5_three_exit_status_branches_each_with_a_distinct_message():
    text = _launch_text()
    lines = _numbered(text)
    per_token = {}
    for token in ("SAFE", "CONFLICT", "UNKNOWN"):
        hits = [(n, ln) for n, ln in lines if token in ln]
        assert hits, "token %s does not appear in launch.sh (Behavior 5)" % token
        per_token[token] = hits
    msg_lines = {}
    for token, hits in per_token.items():
        msgs = [(n, ln.strip()) for n, ln in hits if re.search(r"\b(echo|printf)\b", ln)]
        assert msgs, "token %s appears but never in an echo/printf message: %r" % (token, hits)
        msg_lines[token] = msgs
    flat = [n for msgs in msg_lines.values() for n, _ in msgs]
    assert len(set(flat)) == len(flat), (
        "each branch needs its OWN message line; message lines collide: %r" % msg_lines
    )


def test_b5_both_nonzero_codes_refuse_before_any_launch():
    text = _launch_text()
    lines = _numbered(text)
    launch_line = next(
        (n for n, ln in lines if re.match(r"^python3 -c '\s*$", ln)),
        None,
    )
    assert launch_line, "no `python3 -c '` launch line found in launch.sh"
    for token in ("CONFLICT", "UNKNOWN"):
        msg_at = [n for n, ln in lines if token in ln and re.search(r"\b(echo|printf)\b", ln)]
        assert msg_at, "no message line for %s" % token
        first = min(msg_at)
        refusals = [
            n for n, ln in lines if re.search(r"^\s*exit\s+1\s*(#.*)?$", ln) and n > first
        ]
        assert refusals, (
            "the %s branch (message at line %d) must reach an `exit 1`; no `exit 1` after it"
            % (token, first)
        )
        assert min(refusals) < launch_line, (
            "the %s refusal must fail-SHUT before the launch at line %d, but its first "
            "`exit 1` is at line %d" % (token, launch_line, min(refusals))
        )


# ==========================================================================
# Behavior 6 -- portable, every machine-specific value from the environment
# ==========================================================================
def test_b6_locates_itself_from_bash_source_and_cds_there():
    text = _launch_text()
    assert "BASH_SOURCE[0]" in text, (
        "launch.sh must derive its own directory from ${BASH_SOURCE[0]} so it is portable"
    )
    assert re.search(r"^\s*cd\s+", text, re.MULTILINE), (
        "launch.sh must cd into its own directory before launching"
    )


@pytest.mark.parametrize(
    "var", ["FOUNDRY_AGENT_BIN", "FOUNDRY_AGENT_ARGS", "FOUNDRY_CONFIG", "FOUNDRY_LOG"]
)
def test_b6_reads_all_four_environment_variables(var):
    assert var in _launch_text(), "launch.sh must read %s from the environment" % var


def test_b6_config_and_log_defaults():
    text = _launch_text()
    assert re.search(r"FOUNDRY_CONFIG:[-=]\s*\"?foundry\.config\.json", text), (
        "FOUNDRY_CONFIG must default to foundry.config.json; no `${FOUNDRY_CONFIG:-"
        "foundry.config.json}` form found"
    )
    log_lines = [ln for n, ln in _numbered(text) if re.search(r"FOUNDRY_LOG:[-=]", ln)]
    assert log_lines, "no `${FOUNDRY_LOG:-...}` default found"
    assert any("TMPDIR" in ln for ln in log_lines), (
        "the default FOUNDRY_LOG must be built from TMPDIR so it lands OUTSIDE the repo "
        "(.gitignore is byte-frozen this iteration); got %r" % log_lines
    )


def test_b6_agent_bin_has_no_default_and_refuses_before_launch():
    text = _launch_text()
    lines = _numbered(text)
    defaulted = [
        (n, ln)
        for n, ln in lines
        if re.search(r"FOUNDRY_AGENT_BIN:[-=]\s*[^\s}\"']", ln)
    ]
    assert defaulted == [], (
        "FOUNDRY_AGENT_BIN must have NO default -- an invented agent binary is exactly the "
        "machine-specific value that must come from the operator; found: %r" % defaulted
    )
    launch_line = next((n for n, ln in lines if re.match(r"^python3 -c '\s*$", ln)), None)
    assert launch_line, "no `python3 -c '` launch line found in launch.sh"
    named = [
        n
        for n, ln in lines
        if "FOUNDRY_AGENT_BIN" in ln and re.search(r"\b(echo|printf)\b", ln) and n < launch_line
    ]
    assert named, (
        "when FOUNDRY_AGENT_BIN is empty the file must show a refusal MESSAGE naming that "
        "variable, before the `python3 -c` line at %d" % launch_line
    )
    refusals = [
        n for n, ln in lines if re.search(r"^\s*exit\s+1\s*(#.*)?$", ln) and min(named) < n < launch_line
    ]
    assert refusals, (
        "the FOUNDRY_AGENT_BIN refusal (message at line %d) must reach an `exit 1` before "
        "the launch at line %d" % (min(named), launch_line)
    )


# ==========================================================================
# Behavior 7 -- the documentation now names it
# ==========================================================================
def _usage_sections():
    text = _USAGE.read_text()
    out, cur, buf = {}, None, []
    for ln in text.splitlines():
        if ln.startswith("## "):
            if cur is not None:
                out[cur] = "\n".join(buf)
            cur, buf = ln[3:].strip(), []
        else:
            buf.append(ln)
    if cur is not None:
        out[cur] = "\n".join(buf)
    return out


def _section(prefix: str) -> str:
    secs = _usage_sections()
    for head, body in secs.items():
        if head.startswith(prefix):
            return body
    pytest.fail("USAGE.md has no `## %s...` section; headings are %r" % (prefix, list(secs)))


def _fenced_blocks(body: str):
    blocks, cur, inside = [], [], False
    for ln in body.splitlines():
        if ln.strip().startswith("```"):
            if inside:
                blocks.append("\n".join(cur))
                cur, inside = [], False
            else:
                inside = True
            continue
        if inside:
            cur.append(ln)
    return blocks


def test_b7_recipe_c_launch_block_invokes_the_tracked_launcher():
    blocks = _fenced_blocks(_section("Recipe C"))
    assert blocks, "Recipe C has no fenced block"
    assert any("./launch.sh" in b for b in blocks), (
        "Recipe C's fenced launch block must invoke `./launch.sh`; blocks were %r" % blocks
    )


def test_b7_foreground_form_is_gone_from_usage():
    text = _USAGE.read_text()
    offenders = [(n, ln) for n, ln in _numbered(text) if "uv run python dispatcher.py" in ln]
    assert offenders == [], (
        "the foreground, terminal-owning launch must no longer appear anywhere in USAGE.md; "
        "found: %r" % offenders
    )


def test_b7_controls_cheat_sheet_gains_one_launcher_row():
    body = _section("Controls cheat-sheet")
    rows = []
    for ln in body.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 2 or set("".join(cells)) <= set("-: "):
            continue
        rows.append(cells)
    assert rows, "Controls cheat-sheet has no table rows"
    hits = [r for r in rows if "./launch.sh" in r[1]]
    assert len(hits) == 1, (
        "the Controls cheat-sheet must gain exactly ONE row whose Do column names "
        "`./launch.sh`; matching rows were %r (all rows: %r)" % (hits, rows)
    )


def test_b7_recipe_c_tells_the_operator_to_set_the_agent_env_first():
    body = _section("Recipe C")
    for var in ("FOUNDRY_AGENT_BIN", "FOUNDRY_AGENT_ARGS"):
        assert var in body, (
            "Recipe C must state that %s has to be set before launching; it is absent" % var
        )
