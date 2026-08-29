"""Black-box behaviour tests for iter 200 -- `running_dispatchers` counts BRAINS,
not MENTIONS.

Single-brain ("one foundry per model-API account") is a VISION hard constraint, and
`foundry single-brain` / `foundry preflight` are the only tools that report on it.
The scan used to match every process whose command line merely CONTAINED the
pattern -- the brain, the brain's own `uv run` launch wrapper, and unrelated
same-machine processes matching on prompt text -- so the count was false and `SAFE`
was unreachable from inside an agent stage (fail-SHUT for any launcher gated on
`preflight`). This iteration classifies process-table rows instead:

  * `dispatcher_proc_match(command, *, pattern="dispatcher.py") -> bool` -- a PURE,
    TOTAL classifier: first token must be a python INTERPRETER (basename) AND some
    LATER token's basename must EQUAL `pattern`,
  * `scan_process_rows() -> tuple[tuple[int, str], ...]` -- the new I/O seam that
    walks the process table,
  * `running_dispatchers(pattern="dispatcher.py")` -- signature UNCHANGED (pinned by
    tests/test_iter24_behavior.py); its body now composes the two above, called by
    BARE module name so each is independently monkeypatchable.

ISOLATION CONTRACT (honored): this file was written from the iter-200 PM spec's
Expected Behaviors (1-11) and from the product's own OBSERVABLE behaviour ONLY. The
implementation source (foundry.py / dispatcher.py internals), the engineer's and
reviewer's notes, the rescue patch and `git diff` were NOT read. Every check drives
the PUBLIC interface: the pure classifier, the `scan_process_rows` seam, the
`single_brain_cli` / `foundry.main(["single-brain", ...])` CLI with the seam
monkeypatched, public runtime introspection (`inspect.signature`, `__doc__`), and the
documented `import foundry, dispatcher` subprocess probe -- never the source text.

The one place the real seam is exercised end-to-end is driven from OUTSIDE the
process too: a scripted `ps` is installed earlier on `PATH`, which observes the
argv the seam actually asks for and the exact table it must parse, with no
knowledge of how the call is made. Public-safety: every fixture string here is
synthetic/generic -- no real agent-CLI product name, no real `/Applications/<app>`
path, no personal home-path prefix (iteration 199 was reverted for exactly that).
"""
import inspect
import io
import os
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

# --------------------------------------------------------------------------
# fixtures -- the three row SHAPES measured live in iteration 199, generic
# --------------------------------------------------------------------------
# a real brain: a python interpreter handed the entrypoint script
BRAIN_ROW = (
    "/opt/pyenv/versions/3.13.0/bin/Python -X utf8 dispatcher.py "
    "--config foundry.config.json"
)
# that SAME brain's launch wrapper -- one brain must count exactly ONCE
WRAPPER_ROW = "uv run python -X utf8 dispatcher.py --config foundry.config.json"
# the agent-stage bystander: a non-interpreter binary naming the pattern in prose
BYSTANDER_ROW = (
    "/Applications/SomeApp.app/Contents/MacOS/someapp agent run "
    "--task ... dispatcher.py ..."
)
UNRELATED_ROW = "/bin/zsh -l"
TOOL_ROW = "node /opt/tool/server.js --project dispatcher.py"

# exactly ONE brain (pid 101) among five rows; deliberately not pid-sorted
FIVE_ROWS = (
    (101, BRAIN_ROW),
    (202, WRAPPER_ROW),
    (303, BYSTANDER_ROW),
    (404, UNRELATED_ROW),
    (505, TOOL_ROW),
)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _capture(fn):
    """Run fn() with stdout/stderr captured SEPARATELY; return (rc, out, err)."""
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = fn()
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue(), err.getvalue()


def _set_rows(monkeypatch, rows=(), exc=None):
    """Force the process-table seam offline: return `rows`, or raise `exc`."""
    def fake():
        if exc is not None:
            raise exc
        return tuple(rows)
    monkeypatch.setattr(foundry, "scan_process_rows", fake)
    return fake


def _fake_ps(tmp_path, monkeypatch, table="", exit_code=0):
    """Install a scripted `ps` earlier on PATH; return its argv-log Path.

    Black-box by construction: this observes the seam from OUTSIDE the process,
    knowing only that a process table has to come from somewhere.
    """
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    table_file = bin_dir / "table.txt"
    table_file.write_text(table)
    argv_log = bin_dir / "argv.txt"
    src = (
        "#!" + sys.executable + "\n"
        "import sys, pathlib\n"
        "pathlib.Path(%r).write_text(chr(10).join(sys.argv[1:]))\n"
        "sys.stdout.write(pathlib.Path(%r).read_text())\n"
        "sys.exit(%d)\n"
    ) % (str(argv_log), str(table_file), exit_code)
    ps = bin_dir / "ps"
    ps.write_text(src)
    ps.chmod(0o755)
    monkeypatch.setenv(
        "PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    return argv_log


# ==========================================================================
# Behavior 1 -- dispatcher_proc_match exists, module-level, PURE and TOTAL
# ==========================================================================
def test_b1_classifier_exists_with_the_specified_shape():
    assert callable(getattr(foundry, "dispatcher_proc_match", None)), (
        "foundry.dispatcher_proc_match must exist as a module-level function")
    sig = inspect.signature(foundry.dispatcher_proc_match)
    params = list(sig.parameters)
    assert params[0] == "command", f"first arg must be `command`: {sig}"
    assert "pattern" in sig.parameters, f"must take a `pattern` arg: {sig}"
    pat = sig.parameters["pattern"]
    assert pat.default == "dispatcher.py", (
        f"pattern default must be 'dispatcher.py', got {pat.default!r}")
    assert pat.kind is inspect.Parameter.KEYWORD_ONLY, (
        f"pattern must be KEYWORD-ONLY (spec writes `*, pattern=`): {pat.kind}")


@pytest.mark.parametrize("command", [
    "",
    "   ",
    " \t \n ",
    "\u4f60\u597d \u4e16\u754c",                      # non-ASCII / CJK
    "python \u4f60\u597d dispatcher.py",              # CJK mid-command
    "/",
    "//////",
    "python\x00dispatcher.py",                        # NUL byte
    "-",
    "python " + "x" * 100_000,                        # 100k chars
    "x" * 100_000,
    "python " + "x" * 100_000 + " dispatcher.py",
])
def test_b1_classifier_is_total_returns_bool_and_never_raises(command):
    got = foundry.dispatcher_proc_match(command)
    assert type(got) is bool, (
        f"must return a real bool, got {type(got).__name__} for {command[:40]!r}")


def test_b1_classifier_is_pure_and_deterministic():
    # same input -> same answer, repeatedly, with no observable state carried over
    for _ in range(3):
        assert foundry.dispatcher_proc_match(BRAIN_ROW) is True
        assert foundry.dispatcher_proc_match(WRAPPER_ROW) is False
        assert foundry.dispatcher_proc_match("") is False


# ==========================================================================
# Behavior 2 -- True only when BOTH halves hold:
#   (a) first token's /-basename is python[version chars], case-insensitive
#   (b) some LATER token's /-basename EQUALS pattern
# ==========================================================================
@pytest.mark.parametrize("command,expected,why", [
    ("python dispatcher.py", True, "both halves hold"),
    ("dispatcher.py python", False, "(b) needs a LATER token, not an earlier one"),
    ("python", False, "(a) holds, (b) has no later token at all"),
    ("/opt/x/dispatcher.py --config y", False, "(b) holds only in first token; (a) fails"),
    ("uv run python -X utf8 dispatcher.py", False, "(a) fails: first token is uv"),
    ("python -X utf8 dispatcher.py --config c.json", True, "pattern in a later token"),
    ("PYTHON3.13 /a/b/dispatcher.py", True, "case-insensitive (a), basename (b)"),
    ("python dispatcher.py dispatcher.py", True, "repeats are harmless"),
])
def test_b2_both_halves_are_required(command, expected, why):
    assert foundry.dispatcher_proc_match(command) is expected, why


# ==========================================================================
# Behavior 3 -- the three row SHAPES measured live in iteration 199, in order.
#               Two-sided: 1 must match, 2 must NOT.
# ==========================================================================
def test_b3_brain_row_matches():
    assert foundry.dispatcher_proc_match(BRAIN_ROW) is True, (
        "a python interpreter handed dispatcher.py IS a brain")


def test_b3_launch_wrapper_does_not_match_so_one_brain_counts_once():
    assert foundry.dispatcher_proc_match(WRAPPER_ROW) is False, (
        "the brain's own `uv run` wrapper must not be counted a second time")


def test_b3_agent_stage_bystander_does_not_match():
    assert foundry.dispatcher_proc_match(BYSTANDER_ROW) is False, (
        "a non-interpreter binary naming the pattern in prose is not a brain")


def test_b3_oracle_is_two_sided_over_the_measured_shapes():
    verdicts = [foundry.dispatcher_proc_match(r)
                for r in (BRAIN_ROW, WRAPPER_ROW, BYSTANDER_ROW)]
    assert verdicts == [True, False, False], verdicts
    assert sum(verdicts) == 1, "exactly ONE of the three measured shapes is a brain"


# ==========================================================================
# Behavior 4 -- half (a) accept/reject list; half (b) is EQUALITY, not substring
# ==========================================================================
@pytest.mark.parametrize("first", [
    "python", "python3", "python3.13", "Python", "PYTHON", "PyThOn3.13",
    "/usr/bin/python3", "/opt/a/b/Python", "/opt/a/b/python3.13",
])
def test_b4a_accepts_python_interpreters(first):
    assert foundry.dispatcher_proc_match(f"{first} dispatcher.py") is True, first


@pytest.mark.parametrize("first", [
    "uv", "node", "bash", "zsh", "sh", "ruby", "someapp",
    "pythonx", "mypython", "py", "python-", "python3x", "",
    "/opt/tool/bin/uv", "/bin/zsh", "/opt/x/someapp",
])
def test_b4a_rejects_non_python_first_tokens(first):
    assert foundry.dispatcher_proc_match(f"{first} dispatcher.py") is False, first


@pytest.mark.parametrize("command,expected", [
    ("python predispatcher.py", False),      # token CONTAINS the pattern
    ("python dispatcher.pyc", False),        # token has the pattern as a prefix
    ("python xdispatcher.py", False),
    ("python dispatcher.py.bak", False),
    ("python /a/b/dispatcher.py", True),     # basename EQUALS the pattern
    ("python ./dispatcher.py", True),
    ("python", False),                       # no later token
    ("/opt/x/dispatcher.py --config y", False),  # fails half (a)
])
def test_b4b_pattern_match_is_basename_equality(command, expected):
    assert foundry.dispatcher_proc_match(command) is expected, command


# ==========================================================================
# Behavior 5 -- KNOWN LIMITATION, pinned deliberately so a later simplification
#               cannot drop half (a): half (b) alone does NOT reject a bystander,
#               because the pattern appears in prompt text as a real token.
# ==========================================================================
def test_b5_known_limitation_prompt_text_under_an_interpreter_still_matches():
    fixture = ("/usr/bin/python3 -c "
               "print('keep foundry.py and dispatcher.py importable')")
    # precondition FIRST -- without it the pin silently stops testing anything
    assert "dispatcher.py" in fixture.split(), (
        "fixture must carry `dispatcher.py` as a whitespace-delimited token, "
        "or this pin no longer exercises the limitation")
    assert foundry.dispatcher_proc_match(fixture) is True, (
        "documented limitation: half (b) cannot tell a script argument from "
        "prose, so half (a) is what discriminates today -- do not drop it")


def test_b5_half_a_is_what_discriminates_the_measured_bystander():
    # the bystander DOES satisfy half (b) on its own ...
    assert "dispatcher.py" in BYSTANDER_ROW.split(), (
        "the measured bystander carries the pattern as a real token")
    # ... so only half (a) can reject it, and it does.
    assert foundry.dispatcher_proc_match(BYSTANDER_ROW) is False


# ==========================================================================
# Behavior 6 -- `pattern` is honored
# ==========================================================================
def test_b6_pattern_is_honored():
    assert foundry.dispatcher_proc_match("python worker.py", pattern="worker.py") is True
    assert foundry.dispatcher_proc_match("python worker.py") is False, (
        "the same command under the DEFAULT pattern must not match")


def test_b6_pattern_is_honored_for_the_default_too():
    assert foundry.dispatcher_proc_match(
        "python dispatcher.py", pattern="worker.py") is False


# ==========================================================================
# Behavior 7 -- scan_process_rows: the new I/O seam
# ==========================================================================
def test_b7_seam_exists_and_takes_no_required_arguments():
    assert callable(getattr(foundry, "scan_process_rows", None)), (
        "foundry.scan_process_rows must exist as a module-level function")
    sig = inspect.signature(foundry.scan_process_rows)
    required = [n for n, p in sig.parameters.items()
                if p.default is inspect.Parameter.empty
                and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)]
    assert required == [], f"must take no required arguments: {sig}"


def test_b7_real_scan_returns_pid_command_rows_including_our_own_pid():
    rows = foundry.scan_process_rows()
    assert isinstance(rows, tuple), type(rows)
    assert rows, "a real process table is never empty"
    for row in rows:
        assert isinstance(row, tuple) and len(row) == 2, row
        assert isinstance(row[0], int), row
        assert isinstance(row[1], str), row
    assert os.getpid() in [pid for pid, _ in rows], (
        "the scan must see this very test process")


def test_b7_parses_a_scripted_table(tmp_path, monkeypatch):
    table = (
        "  101 /opt/py/bin/python3 -X utf8 dispatcher.py --config c.json\n"
        "\n"                                   # blank -> skipped
        "notanumber some command here\n"       # non-digit pid -> skipped
        "12a3 mixed digits then letters\n"     # not ALL digits -> skipped
        "-5 negative pid\n"                    # not all digits -> skipped
        "  \t \n"                              # whitespace-only -> skipped
        "707\n"                                # pid with no command remainder
        "202   uv run python dispatcher.py   --config c.json  \n"
    )
    _fake_ps(tmp_path, monkeypatch, table=table)
    rows = foundry.scan_process_rows()
    pids = [p for p, _ in rows]
    assert 101 in pids and 202 in pids, rows
    assert not any(p in (12, 5, -5) for p in pids), f"malformed rows leaked: {rows}"
    by_pid = dict(rows)
    assert by_pid[101] == (
        "/opt/py/bin/python3 -X utf8 dispatcher.py --config c.json")
    # VERBATIM apart from the trailing newline: internal AND trailing spaces kept
    assert by_pid[202] == "uv run python dispatcher.py   --config c.json  ", (
        f"command remainder must be preserved verbatim: {by_pid[202]!r}")


def test_b7_returns_empty_tuple_for_an_empty_table(tmp_path, monkeypatch):
    _fake_ps(tmp_path, monkeypatch, table="")
    assert foundry.scan_process_rows() == ()


def test_b7_returns_empty_tuple_for_a_wholly_unparseable_table(tmp_path, monkeypatch):
    _fake_ps(tmp_path, monkeypatch,
             table="header line\n\nnot a pid at all\n   \nalso nope\n")
    assert foundry.scan_process_rows() == ()


def test_b7_skips_malformed_lines_without_raising(tmp_path, monkeypatch):
    _fake_ps(tmp_path, monkeypatch,
             table="garbage\n999 python dispatcher.py\nmore garbage\n")
    assert foundry.scan_process_rows() == ((999, "python dispatcher.py"),)


def test_b7_raises_when_the_scan_itself_cannot_be_performed(monkeypatch):
    # no `ps` anywhere on PATH -- "I could not check", which maps to UNKNOWN/exit 2
    monkeypatch.setenv("PATH", "")
    with pytest.raises(Exception) as excinfo:
        foundry.scan_process_rows()
    assert isinstance(excinfo.value, (FileNotFoundError, OSError,
                                      subprocess.SubprocessError)), excinfo.value


def test_b7_asks_the_process_table_for_pid_and_command_only(tmp_path, monkeypatch):
    """Acceptance criterion: no `comm`, no `ucomm`, no fixed-width parsing.

    Measured by SPLITTING the format spec on commas -- a substring test for
    "comm" matches the compliant "command=" and would accuse correct code.
    """
    argv_log = _fake_ps(tmp_path, monkeypatch, table="1 python dispatcher.py\n")
    foundry.scan_process_rows()
    argv = [a for a in argv_log.read_text().split("\n") if a]
    assert argv, "the seam must actually invoke a process-table command"
    fields = []
    for arg in argv:
        if "=" in arg:
            fields += [chunk.split("=")[0].strip()
                       for chunk in arg.split(",") if "=" in chunk]
    assert fields, f"expected a `key=` format spec in argv: {argv}"
    assert set(fields) <= {"pid", "command"}, (
        f"only pid+command may be requested, got {fields} from {argv}")
    assert "comm" not in fields and "ucomm" not in fields, fields


# ==========================================================================
# Behavior 8 -- running_dispatchers keeps its PINNED signature and composes the
#               two collaborators by BARE module name (both seams must bite)
# ==========================================================================
def test_b8_running_dispatchers_signature_is_unchanged():
    sig = inspect.signature(foundry.running_dispatchers)
    assert list(sig.parameters) == ["pattern"], (
        f"pinned by tests/test_iter24_behavior.py: exactly one `pattern` arg: {sig}")
    assert sig.parameters["pattern"].default == "dispatcher.py", sig
    assert str(sig.return_annotation).replace(" ", "") in (
        "tuple[int,...]", "typing.Tuple[int,...]"), sig.return_annotation


def test_b8_scan_process_rows_seam_bites(monkeypatch):
    _set_rows(monkeypatch, rows=((77, BRAIN_ROW),))
    assert foundry.running_dispatchers() == (77,), (
        "running_dispatchers must call scan_process_rows by BARE module name")


def test_b8_dispatcher_proc_match_seam_bites(monkeypatch):
    _set_rows(monkeypatch, rows=FIVE_ROWS)
    monkeypatch.setattr(foundry, "dispatcher_proc_match",
                        lambda command, *, pattern="dispatcher.py": False)
    assert foundry.running_dispatchers() == (), (
        "running_dispatchers must call dispatcher_proc_match by BARE module name")
    monkeypatch.setattr(foundry, "dispatcher_proc_match",
                        lambda command, *, pattern="dispatcher.py": True)
    assert foundry.running_dispatchers() == (101, 202, 303, 404, 505)


def test_b8_pattern_is_threaded_through_to_the_classifier(monkeypatch):
    seen = []
    _set_rows(monkeypatch, rows=((1, "python worker.py"),))

    def spy(command, *, pattern="dispatcher.py"):
        seen.append(pattern)
        return pattern == "worker.py"
    monkeypatch.setattr(foundry, "dispatcher_proc_match", spy)
    assert foundry.running_dispatchers("worker.py") == (1,)
    assert seen == ["worker.py"], seen


def test_b8_still_returns_a_tuple_of_ints(monkeypatch):
    _set_rows(monkeypatch, rows=FIVE_ROWS)
    got = foundry.running_dispatchers()
    assert isinstance(got, tuple) and all(type(p) is int for p in got), got


# ==========================================================================
# Behavior 9 -- counting: one brain among five rows is ONE pid, not three or five
# ==========================================================================
def test_b9_five_row_table_with_one_brain_returns_exactly_that_pid(monkeypatch):
    _set_rows(monkeypatch, rows=FIVE_ROWS)
    assert foundry.running_dispatchers() == (101,), (
        "the brain, its wrapper and three bystanders must count as ONE brain")


def test_b9_pid_order_follows_scan_order_with_no_duplicates(monkeypatch):
    rows = ((900, BRAIN_ROW), (303, BYSTANDER_ROW),
            (100, BRAIN_ROW), (500, BRAIN_ROW))
    _set_rows(monkeypatch, rows=rows)
    got = foundry.running_dispatchers()
    assert got == (900, 100, 500), f"scan order must be preserved: {got}"
    assert len(got) == len(set(got)), f"no duplicates may be introduced: {got}"


def test_b9_no_brain_row_returns_empty_tuple(monkeypatch):
    _set_rows(monkeypatch, rows=(
        (202, WRAPPER_ROW), (303, BYSTANDER_ROW),
        (404, UNRELATED_ROW), (505, TOOL_ROW)))
    assert foundry.running_dispatchers() == ()


def test_b9_empty_table_returns_empty_tuple(monkeypatch):
    _set_rows(monkeypatch, rows=())
    assert foundry.running_dispatchers() == ()


def test_b9_scan_error_propagates_unchanged(monkeypatch):
    boom = FileNotFoundError("ps: not found")
    _set_rows(monkeypatch, exc=boom)
    with pytest.raises(FileNotFoundError) as excinfo:
        foundry.running_dispatchers()
    assert excinfo.value is boom, (
        "the exception must propagate UNCHANGED so the caller can report UNKNOWN")


def test_b9_timeout_error_also_propagates(monkeypatch):
    boom = subprocess.TimeoutExpired(cmd="ps", timeout=5)
    _set_rows(monkeypatch, exc=boom)
    with pytest.raises(subprocess.TimeoutExpired) as excinfo:
        foundry.running_dispatchers()
    assert excinfo.value is boom


# ==========================================================================
# Behavior 10 -- end-to-end through the UNCHANGED CLIs
# ==========================================================================
def test_b10_cli_reports_conflict_and_lists_exactly_one_pid(monkeypatch):
    _set_rows(monkeypatch, rows=FIVE_ROWS)
    rc, out, err = _capture(lambda: foundry.single_brain_cli())
    assert "CONFLICT" in out, out
    assert rc == 1, f"a running brain is a CONFLICT at exit 1, got {rc}"
    assert "101" in out, out
    for bogus in ("202", "303", "404", "505"):
        assert bogus not in out, (
            f"bogus pid {bogus} must not be reported as an offender: {out!r}")


def test_b10_safe_is_reachable_from_inside_an_agent_stage(monkeypatch):
    """THE regression that matters: a table holding ONLY the agent-stage bystander
    -- whose prompt text names the pattern -- must report SAFE, exit 0. It
    provably did not before, which made `preflight` fail-SHUT."""
    _set_rows(monkeypatch, rows=((303, BYSTANDER_ROW),))
    rc, out, err = _capture(lambda: foundry.single_brain_cli())
    assert "SAFE" in out, out
    assert rc == 0, f"zero brains must exit 0, got {rc}"
    assert "303" not in out, f"the bystander must not be listed: {out!r}"


def test_b10_wrapper_only_table_is_also_safe(monkeypatch):
    _set_rows(monkeypatch, rows=((202, WRAPPER_ROW),))
    rc, out, err = _capture(lambda: foundry.single_brain_cli())
    assert "SAFE" in out and rc == 0, (rc, out)


def test_b10_main_routes_single_brain_over_the_same_seam(monkeypatch):
    _set_rows(monkeypatch, rows=FIVE_ROWS)
    rc, out, err = _capture(lambda: foundry.main(["single-brain"]))
    assert "CONFLICT" in out and rc == 1, (rc, out)

    _set_rows(monkeypatch, rows=((303, BYSTANDER_ROW),))
    rc, out, err = _capture(lambda: foundry.main(["single-brain"]))
    assert "SAFE" in out and rc == 0, (rc, out)


def test_b10_main_pattern_flag_still_reaches_the_scan(monkeypatch):
    # pinned by tests/test_iter28_behavior.py -- assert it still holds end-to-end
    _set_rows(monkeypatch, rows=((42, "python worker.py"),))
    rc, out, err = _capture(lambda: foundry.main(["single-brain", "--pattern", "worker.py"]))
    assert "CONFLICT" in out and "42" in out and rc == 1, (rc, out)

    _set_rows(monkeypatch, rows=((42, "python worker.py"),))
    rc, out, err = _capture(lambda: foundry.main(["single-brain"]))
    assert "SAFE" in out and rc == 0, (rc, out)


def test_b10_scan_error_still_reports_unknown_at_exit_2(monkeypatch):
    _set_rows(monkeypatch, exc=FileNotFoundError("ps: not found"))
    rc, out, err = _capture(lambda: foundry.single_brain_cli())
    assert rc == 2, f"'I could not check' must stay UNKNOWN at exit 2, got {rc}"
    assert "UNKNOWN" in out, out


def test_b10_end_to_end_over_a_scripted_process_table(tmp_path, monkeypatch):
    """No seam monkeypatching at all: only a scripted `ps` on PATH."""
    _fake_ps(tmp_path, monkeypatch, table="".join(
        f"{pid} {cmd}\n" for pid, cmd in FIVE_ROWS))
    rc, out, err = _capture(lambda: foundry.main(["single-brain"]))
    assert "CONFLICT" in out and rc == 1, (rc, out)
    assert "101" in out and "303" not in out, out

    _fake_ps(tmp_path, monkeypatch, table=f"303 {BYSTANDER_ROW}\n")
    rc, out, err = _capture(lambda: foundry.main(["single-brain"]))
    assert "SAFE" in out and rc == 0, (rc, out)


# ==========================================================================
# Behavior 11 -- the falsified docstring claim is corrected
# ==========================================================================
def test_b11_docstring_no_longer_claims_the_pattern_never_matches():
    doc = foundry.running_dispatchers.__doc__ or ""
    assert doc.strip(), "running_dispatchers must keep a docstring"
    low = doc.lower()
    assert "never match" not in low, (
        "the falsified claim (the pattern 'never matches' the single-brain "
        "invocation) must be gone")


def test_b11_docstring_states_the_interpreter_requirement():
    low = (foundry.running_dispatchers.__doc__ or "").lower()
    assert "interpreter" in low, low


def test_b11_docstring_states_the_prompt_text_limitation():
    low = (foundry.running_dispatchers.__doc__ or "").lower()
    assert "prompt text" in low, (
        "the docstring must state that a same-machine agent process can match "
        "on prompt text alone")


def test_b11_docstring_preserves_the_empty_tuple_and_raise_contract():
    doc = foundry.running_dispatchers.__doc__ or ""
    low = doc.lower()
    assert "empty tuple" in low, doc
    assert "SAFE" in doc and "UNKNOWN" in doc, doc


# ==========================================================================
# Acceptance criteria that are not a single behavior
# ==========================================================================
def test_ac_modules_still_import_in_a_fresh_interpreter():
    proc = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)


def test_ac_single_brain_status_to_dict_still_has_its_seven_keys():
    status = foundry.summarize_single_brain((101,))
    d = status.to_dict()
    assert len(d) == 7, f"to_dict must keep exactly 7 keys, got {sorted(d)}"


def test_ac_no_machine_local_or_vendor_tokens_in_this_file():
    """Public-safety, self-check: iteration 199 was reverted for exactly this.

    Deliberately CATEGORY-based -- writing a banned literal into the rule that
    bans it is the self-defeating shape that tripped the PM's own first draft.
    The shipped `scripts/leak_guard.py` is the authority; this is only a cheap
    in-suite tripwire for the two categories expressible without quoting one.
    """
    text = pathlib.Path(__file__).read_text()
    home_prefix = "/" + "Users" + "/"
    assert home_prefix not in text, "no personal home-path prefix may appear"
    assert str(pathlib.Path.home()) not in text, "no real home path may appear"
