"""Black-box behaviour tests for iter 16 -- the read-only, offline, one-command
company-health probe surface, ALL additive in foundry.py:

  * a PURE total `parse_postrelease_verdict(text) -> str | None`
    (last-non-empty-line `POSTRELEASE: HEALTHY|BROKEN` parse; else None; never raises),
  * a FROZEN dataclass `StatusSummary(product, repo, branch, latest_iter,
    postrelease, hotfix, speed_story, prd_line)` with `attention`/`ok`/`exit_code`
    props + a `render()` string,
  * a PURE keyword-only `summarize_status(...) -> StatusSummary`,
  * a `status_cli(cfg) -> int` wired to a new argparse subcommand `status`.

ISOLATION CONTRACT (honored): this file was written from the iter-16 PM spec's
Expected Behaviors (1-13) and the product's own OBSERVABLE behaviour ONLY. The
implementation source (foundry.py / dispatcher.py internals), the engineer's and
reviewer's notes, and `git diff` were NOT read. Every check drives the PUBLIC
interface: the pure fns via `foundry.parse_postrelease_verdict(...)` /
`foundry.summarize_status(...)`, the dataclass via `foundry.StatusSummary(...)`,
and the CLI via `foundry.main(["status", "--config", <cfg>])` against a
TMP-`work_root` config with real `state/iter-NN/postrelease.md` + optional flag /
`prd.json` files (the real foundry repo/state is NEVER touched). The additivity /
off-control-path checks (Behavior 13) use only public RUNTIME introspection --
module attributes, `--help` output, and compiled name/const tables
(`__code__.co_names` / `co_consts`) -- NOT the source text. Fully offline &
deterministic: real temp files only; ZERO real subprocess / git / network / clock
(except the `import`/`--help` regression probes, which only import + print usage).
"""
import dataclasses
import io
import json
import pathlib
import re
import subprocess
import sys
import types

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _write_cfg(tmp_path, **over):
    """A minimal product config in a tmp dir (mirrors the suite's convention).
    `repo`/`work_root` are TMP dirs so the real foundry repo/state is NEVER
    touched."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    data = {
        "name": "demoprod",
        "repo": str(repo),
        "allowed_push_repo": "demoprod",
        "vision": str(tmp_path / "VISION.md"),
        "work_root": str(tmp_path / "work"),
    }
    data.update(over)
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data))
    return p


def _snapshot_tree(root):
    """Map {relative-path: bytes} for every file under root (no-write proof)."""
    root = pathlib.Path(root)
    if not root.exists():
        return {}
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in root.rglob("*") if p.is_file()
    }


def _run_cli(argv):
    """Drive foundry.main capturing (rc, stdout+stderr)."""
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = foundry.main(argv)
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue() + err.getvalue()


def _iter_dir(cfg, iteration):
    return pathlib.Path(cfg.state) / f"iter-{iteration:02d}"


def _write_postrelease(cfg, iteration, verdict, *, trailing_blanks=True):
    """Create state/iter-NN/postrelease.md whose LAST non-empty line is the
    `POSTRELEASE: <verdict>` sentinel (with optional trailing blank lines)."""
    d = _iter_dir(cfg, iteration)
    d.mkdir(parents=True, exist_ok=True)
    body = f"post-release verification report\n\nPOSTRELEASE: {verdict}"
    if trailing_blanks:
        body += "\n\n   \n"
    (d / "postrelease.md").write_text(body)
    return d / "postrelease.md"


def _stories_text(stories, wrap=False):
    """JSON text for a story list (mirrors iter11/iter12)."""
    return json.dumps({"stories": stories} if wrap else stories)


def _fn_names_consts(fn):
    """Recursively gather (co_names set, str-consts set) reachable from fn's
    compiled code object -- public runtime introspection, not source text."""
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


def _module_names_consts(module):
    """Union of names/str-consts across every function/method reachable from a
    module's public namespace (recursively into nested code objects)."""
    names, consts = set(), set()
    for v in vars(module).values():
        if isinstance(v, types.FunctionType):
            n, c = _fn_names_consts(v)
            names |= n
            consts |= c
        elif isinstance(v, type):
            for m in vars(v).values():
                if isinstance(m, types.FunctionType):
                    n, c = _fn_names_consts(m)
                    names |= n
                    consts |= c
    return names, consts


NEW_SYMBOLS = (
    "parse_postrelease_verdict", "StatusSummary", "summarize_status", "status_cli",
)
CONTROL_FLOW_FNS = ("build_prompt", "run_stage", "run_iteration", "run_continuous")


def _mk(product="demoprod", repo="/tmp/repo", branch="main", latest_iter=1,
        postrelease="HEALTHY", hotfix=False, speed_story=False, prd_line=None):
    """Build a StatusSummary positionally in the spec's field order."""
    return foundry.StatusSummary(product, repo, branch, latest_iter,
                                 postrelease, hotfix, speed_story, prd_line)


# ==========================================================================
# A. Pure  parse_postrelease_verdict(text) -> str | None   (Behaviors 1-2)
# ==========================================================================

# --- Behavior 1 -- recognized verdict on the last non-empty line -----------
def test_b01_healthy_and_broken_recognized():
    assert foundry.parse_postrelease_verdict("POSTRELEASE: HEALTHY") == "HEALTHY"
    assert foundry.parse_postrelease_verdict("POSTRELEASE: BROKEN") == "BROKEN"


def test_b01_trailing_blank_lines_ignored_last_nonempty_wins():
    body = "some report prose\n\nPOSTRELEASE: BROKEN\n\n   \n\t\n"
    assert foundry.parse_postrelease_verdict(body) == "BROKEN", \
        "trailing blank/whitespace lines must be ignored; last NON-empty line wins"
    body_h = "line1\nline2\nPOSTRELEASE: HEALTHY\n"
    assert foundry.parse_postrelease_verdict(body_h) == "HEALTHY"


def test_b01_surrounding_whitespace_tolerated():
    assert foundry.parse_postrelease_verdict("  POSTRELEASE:  BROKEN  ") == "BROKEN", \
        "leading/trailing whitespace on the sentinel line must be tolerated"
    assert foundry.parse_postrelease_verdict("\tPOSTRELEASE:   HEALTHY\t\n") == "HEALTHY"


# --- Behavior 2 -- no verdict -> None, never raises ------------------------
def test_b02_none_cases():
    cases = {
        "empty": "",
        "whitespace-only": "   \n\t\n  ",
        "no POSTRELEASE line": "just some prose\nwith no sentinel at all\n",
        "unrecognized token": "POSTRELEASE: MAYBE",
        "sentinel-not-last (prose follows)":
            "POSTRELEASE: HEALTHY\nbut then more prose follows here\n",
    }
    for label, text in cases.items():
        assert foundry.parse_postrelease_verdict(text) is None, \
            f"{label!r} must parse to None, got {foundry.parse_postrelease_verdict(text)!r}"


def test_b02_never_raises_for_any_string():
    weird = [
        "POSTRELEASE:", "POSTRELEASE", "postrelease: healthy",
        "POSTRELEASE: HEALTHY BROKEN", "\x00\x01", "POSTRELEASE: " + "X" * 500,
        "POSTRELEASE: HEALTHY\r\nPOSTRELEASE: BROKEN\r\n", "un\u00efcode POSTRELEASE: BROKEN",
    ]
    for t in weird:
        try:
            foundry.parse_postrelease_verdict(t)  # must not raise
        except Exception as e:  # noqa: BLE001
            pytest.fail(f"parse_postrelease_verdict raised on {t!r}: {e!r}")


def test_b02_case_sensitive_lowercase_is_none():
    # The spec's recognized tokens are the upper-case HEALTHY/BROKEN; a lower-case
    # variant is an unrecognized token -> None (most reasonable reading).
    assert foundry.parse_postrelease_verdict("POSTRELEASE: healthy") is None


# ==========================================================================
# B. Frozen StatusSummary + attention / exit_code / ok / render  (3-6)
# ==========================================================================

# --- Behavior 3 -- frozen + attention semantics ----------------------------
def test_b03_frozen_dataclass():
    s = _mk()
    assert dataclasses.is_dataclass(s) and type(s).__name__ == "StatusSummary"
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.hotfix = True  # frozen: any attribute assignment must raise
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.postrelease = "BROKEN"


def test_b03_attention_is_hotfix_or_broken():
    # attention True iff hotfix True OR postrelease == "BROKEN"
    assert _mk(hotfix=True, postrelease="HEALTHY").attention is True
    assert _mk(hotfix=True, postrelease=None).attention is True
    assert _mk(hotfix=False, postrelease="BROKEN").attention is True
    # False otherwise
    assert _mk(hotfix=False, postrelease="HEALTHY").attention is False
    assert _mk(hotfix=False, postrelease=None).attention is False


def test_b03_speed_story_never_affects_attention():
    for hotfix in (True, False):
        for pr in ("HEALTHY", "BROKEN", None):
            base = _mk(hotfix=hotfix, postrelease=pr, speed_story=False).attention
            withflag = _mk(hotfix=hotfix, postrelease=pr, speed_story=True).attention
            assert base == withflag, \
                f"speed_story flipped attention for hotfix={hotfix} pr={pr!r} (must be advisory only)"


# --- Behavior 4 -- exit_code precedence ------------------------------------
def test_b04_exit_code_precedence():
    # attention -> 1 (even when latest_iter == 0)
    assert _mk(postrelease="BROKEN", latest_iter=5, hotfix=False).exit_code == 1
    assert _mk(hotfix=True, latest_iter=0, postrelease=None).exit_code == 1
    # else latest_iter <= 0 -> 2
    assert _mk(latest_iter=0, postrelease=None, hotfix=False).exit_code == 2
    # else -> 0
    assert _mk(postrelease="HEALTHY", latest_iter=3, hotfix=False).exit_code == 0


def test_b04_attention_beats_zero_iters():
    # a hotfix at iter 0 is attention (1), NOT "nothing shipped" (2)
    assert _mk(hotfix=True, latest_iter=0, postrelease=None).exit_code == 1


# --- Behavior 5 -- ok mirror -----------------------------------------------
def test_b05_ok_mirrors_not_attention():
    for hotfix in (True, False):
        for pr in ("HEALTHY", "BROKEN", None):
            for li in (0, 3):
                s = _mk(hotfix=hotfix, postrelease=pr, latest_iter=li)
                assert s.ok is (not s.attention), \
                    f"ok must be (not attention) for hotfix={hotfix} pr={pr!r} li={li}"


# --- Behavior 6 -- render() key facts --------------------------------------
def _assert_render(s):
    """Assert render() contains every spec-mandated substring for summary s."""
    out = s.render()
    assert s.product in out, f"product name missing:\n{out}"
    assert f"branch {s.branch}" in out, f"'branch {{branch}}' missing:\n{out}"
    if s.latest_iter <= 0:
        assert "latest iteration: none" in out, f"'latest iteration: none' missing:\n{out}"
    else:
        assert f"latest iteration: {s.latest_iter}" in out, \
            f"'latest iteration: {s.latest_iter}' missing:\n{out}"
    pr_word = "unknown" if s.postrelease is None else s.postrelease
    assert f"post-release: {pr_word}" in out, f"'post-release: {pr_word}' missing:\n{out}"
    assert (f"hotfix flag: {'RAISED' if s.hotfix else 'clear'}") in out, \
        f"hotfix flag line wrong:\n{out}"
    assert (f"speed-story flag: {'RAISED' if s.speed_story else 'clear'}") in out, \
        f"speed-story flag line wrong:\n{out}"
    if s.prd_line is None:
        assert "no prd.json" in out, f"'no prd.json' missing:\n{out}"
    else:
        assert s.prd_line in out, f"prd_line verbatim missing:\n{out}"
    # final verdict token matches exit_code (word-boundary for OK: 'BROKEN' contains 'OK')
    if s.exit_code == 0:
        assert re.search(r"\bOK\b", out), f"exit 0 must render 'OK':\n{out}"
        assert "ATTENTION" not in out and "no iterations yet" not in out
    elif s.exit_code == 1:
        assert "ATTENTION" in out, f"exit 1 must render 'ATTENTION':\n{out}"
        assert not re.search(r"\bOK\b", out) and "no iterations yet" not in out
    else:
        assert "no iterations yet" in out, f"exit 2 must render 'no iterations yet':\n{out}"
        assert not re.search(r"\bOK\b", out) and "ATTENTION" not in out
    return out


def test_b06_render_ok_case():
    _assert_render(_mk(postrelease="HEALTHY", latest_iter=3, hotfix=False,
                       speed_story=False, prd_line=None))


def test_b06_render_unknown_and_none_iter():
    # postrelease None -> 'unknown'; latest_iter 0 -> 'none' + exit 2 verdict
    _assert_render(_mk(postrelease=None, latest_iter=0, hotfix=False, prd_line=None))


def test_b06_render_broken_attention_and_prd_line():
    prd = "demoprod: 2/2 stories pass (COMPLETE)"
    _assert_render(_mk(postrelease="BROKEN", latest_iter=7, hotfix=False,
                       speed_story=True, prd_line=prd))


def test_b06_render_hotfix_raised():
    _assert_render(_mk(postrelease="HEALTHY", latest_iter=2, hotfix=True,
                       speed_story=False, prd_line="demoprod: 1/3 stories pass (in progress)"))


def test_b06_render_broken_contains_ok_substring_but_not_word():
    # regression guard for the tester's own gotcha: 'BROKEN' literally contains
    # the chars 'OK', so a naive substring check would misread the verdict.
    out = _mk(postrelease="BROKEN", latest_iter=1).render()
    assert "OK" in out                       # substring: BR-OK-EN
    assert not re.search(r"\bOK\b", out)     # but NOT a standalone OK verdict token
    assert "ATTENTION" in out


# ==========================================================================
# C. Pure keyword-only  summarize_status(...) -> StatusSummary  (Behavior 7)
# ==========================================================================
def test_b07_fields_equal_inputs():
    s = foundry.summarize_status(
        product="prodX", repo="/r", branch="release", latest_iter=9,
        postrelease="BROKEN", hotfix=True, speed_story=False,
        prd_line="prodX: 4/9 stories pass (in progress)")
    assert isinstance(s, foundry.StatusSummary)
    assert (s.product, s.repo, s.branch, s.latest_iter, s.postrelease,
            s.hotfix, s.speed_story, s.prd_line) == \
        ("prodX", "/r", "release", 9, "BROKEN", True, False,
         "prodX: 4/9 stories pass (in progress)")


def test_b07_is_keyword_only():
    with pytest.raises(TypeError):
        foundry.summarize_status("p", "/r", "main", 1, "HEALTHY", False, False, None)


def test_b07_never_raises_on_edge_inputs():
    try:
        s = foundry.summarize_status(
            product="", repo="", branch="", latest_iter=-5,
            postrelease=None, hotfix=False, speed_story=True, prd_line=None)
    except Exception as e:  # noqa: BLE001
        pytest.fail(f"summarize_status raised on edge inputs: {e!r}")
    assert s.latest_iter == -5 and s.postrelease is None and s.speed_story is True


# ==========================================================================
# D. CLI  foundry status --config <cfg>   (Behaviors 8-12)
# ==========================================================================

# --- Behavior 8 -- healthy latest ship -> exit 0, read-only ----------------
def test_b08_healthy_latest_ship_exit0_no_write(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_postrelease(cfg, 3, "HEALTHY")           # latest = iter-03, HEALTHY
    before = _snapshot_tree(tmp_path)               # snapshot the WHOLE temp tree
    rc, out = _run_cli(["status", "--config", str(cfg_path)])
    assert rc == 0, f"healthy latest ship + no flags must exit 0, got {rc}\n{out}"
    for sub in ("latest iteration: 3", "post-release: HEALTHY",
                "hotfix flag: clear", "no prd.json"):
        assert sub in out, f"report missing {sub!r}:\n{out}"
    assert re.search(r"\bOK\b", out), f"report must contain verdict 'OK':\n{out}"
    # read-only: nothing written anywhere under the temp tree
    assert _snapshot_tree(tmp_path) == before, "status wrote a file (must be read-only)"


def test_b08_latest_iter_without_postrelease_is_unknown_exit0(tmp_path):
    # latest iter dir exists but has NO postrelease.md (in-progress / no-ship)
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    (_iter_dir(cfg, 4)).mkdir(parents=True)          # iter-04, no postrelease.md
    (_iter_dir(cfg, 4) / "pm.md").write_text("spec in progress")
    before = _snapshot_tree(tmp_path)
    rc, out = _run_cli(["status", "--config", str(cfg_path)])
    assert rc == 0, f"no-ship latest iter + no flags = no-news-is-good-news (exit 0), got {rc}\n{out}"
    assert "post-release: unknown" in out, f"absent postrelease.md must show 'unknown':\n{out}"
    assert "latest iteration: 4" in out, f"latest iter dir must be read as 4:\n{out}"
    assert _snapshot_tree(tmp_path) == before, "status wrote a file (must be read-only)"


# --- Behavior 9 -- hotfix flag present -> exit 1 ---------------------------
def test_b09_hotfix_flag_exit1(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_postrelease(cfg, 3, "HEALTHY")            # latest HEALTHY ...
    foundry.hotfix_flag_path(cfg).parent.mkdir(parents=True, exist_ok=True)
    foundry.hotfix_flag_path(cfg).write_text("hotfix needed: iter-03 broke prod")
    before = _snapshot_tree(tmp_path)
    rc, out = _run_cli(["status", "--config", str(cfg_path)])
    assert rc == 1, f"a raised hotfix flag must exit 1 even with HEALTHY latest, got {rc}\n{out}"
    assert "hotfix flag: RAISED" in out, f"report must show 'hotfix flag: RAISED':\n{out}"
    assert "ATTENTION" in out, f"report must show verdict 'ATTENTION':\n{out}"
    assert _snapshot_tree(tmp_path) == before, "status wrote a file (must be read-only)"


# --- Behavior 10 -- latest postrelease BROKEN -> exit 1 --------------------
def test_b10_latest_broken_exit1(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_postrelease(cfg, 3, "BROKEN")             # latest BROKEN, no hotfix
    before = _snapshot_tree(tmp_path)
    rc, out = _run_cli(["status", "--config", str(cfg_path)])
    assert rc == 1, f"a BROKEN latest postrelease must exit 1, got {rc}\n{out}"
    assert "post-release: BROKEN" in out, f"report must show 'post-release: BROKEN':\n{out}"
    assert "ATTENTION" in out, f"report must show verdict 'ATTENTION':\n{out}"
    assert "hotfix flag: clear" in out, f"no hotfix expected here:\n{out}"
    assert _snapshot_tree(tmp_path) == before, "status wrote a file (must be read-only)"


# --- Behavior 11 -- no iterations -> exit 2 --------------------------------
def test_b11_no_iterations_exit2(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    pathlib.Path(cfg.state).mkdir(parents=True, exist_ok=True)   # state/ exists, no iter-* dirs
    before = _snapshot_tree(tmp_path)
    rc, out = _run_cli(["status", "--config", str(cfg_path)])
    assert rc == 2, f"no iterations shipped yet must exit 2, got {rc}\n{out}"
    assert "latest iteration: none" in out, f"report must show 'latest iteration: none':\n{out}"
    assert "no iterations yet" in out, f"report must show verdict 'no iterations yet':\n{out}"
    # iter 217: `gather_status` now composes the report-only live-lag sentence,
    # which carries its OWN verdict vocabulary (WARN/OK/UNKNOWN) behind a
    # `live-lag:` prefix. This pin is about THIS report's verdict vocabulary, so
    # it is SCOPED to the report's own lines rather than weakened -- and the
    # scoping is also what makes it DETERMINISTIC: the composed line reads the
    # ambient, UNTRACKED `dispatcher.out`, so it renders `OK` on a machine with a
    # running brain and `UNKNOWN` in the throwaway fresh clone every ship is
    # re-verified from -- an unscoped whole-output pin flips with local state.
    lag = [ln for ln in out.splitlines() if ln.lstrip().startswith("live-lag:")]
    assert len(lag) == 1, f"expected exactly ONE composed live-lag line:\n{out}"
    own = "\n".join(ln for ln in out.splitlines()
                    if not ln.lstrip().startswith("live-lag:"))
    assert not re.search(r"\bOK\b", own) and "ATTENTION" not in own
    assert _snapshot_tree(tmp_path) == before, "status wrote a file (must be read-only)"


# --- Behavior 12 -- reads the LATEST iter; advisory + prd surfaced ---------
def test_b12_reads_highest_iter_not_first(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_postrelease(cfg, 1, "HEALTHY")            # older, healthy
    _write_postrelease(cfg, 5, "BROKEN")             # newest, broken -> should win
    rc, out = _run_cli(["status", "--config", str(cfg_path)])
    assert rc == 1, f"CLI must read iter-05 (BROKEN) not iter-01 (HEALTHY), got {rc}\n{out}"
    assert "latest iteration: 5" in out, f"latest must be 5:\n{out}"
    assert "post-release: BROKEN" in out, f"must report iter-05's BROKEN verdict:\n{out}"


def test_b12_speed_story_advisory_still_exit0(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_postrelease(cfg, 3, "HEALTHY")            # healthy latest, no hotfix
    foundry.speed_story_flag_path(cfg).parent.mkdir(parents=True, exist_ok=True)
    foundry.speed_story_flag_path(cfg).write_text("suite is slow; add a speed story")
    rc, out = _run_cli(["status", "--config", str(cfg_path)])
    assert rc == 0, f"an advisory speed-story flag must NOT change the exit code, got {rc}\n{out}"
    assert "speed-story flag: RAISED" in out, f"report must show 'speed-story flag: RAISED':\n{out}"
    assert re.search(r"\bOK\b", out), f"advisory-only state is still OK:\n{out}"


def test_b12_prd_complete_line_surfaced(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_postrelease(cfg, 3, "HEALTHY")
    # a valid prd.json at cfg.prd whose stories all pass -> COMPLETE line
    pathlib.Path(cfg.prd).write_text(
        _stories_text([{"passes": True}, {"passes": True}]))
    expected = foundry.dispatch_progress_line(cfg)   # existing helper == source of truth
    assert expected == "demoprod: 2/2 stories pass (COMPLETE)", \
        f"precondition: dispatch_progress_line unexpected: {expected!r}"
    rc, out = _run_cli(["status", "--config", str(cfg_path)])
    assert rc == 0, f"healthy + complete prd + no flags -> exit 0, got {rc}\n{out}"
    assert expected in out, f"report must contain the exact dispatch_progress_line text {expected!r}:\n{out}"


# ==========================================================================
# E. Behavior 13 -- additive & off the control path (public introspection)
# ==========================================================================
def test_b13_both_modules_import():
    root = str(pathlib.Path(__file__).resolve().parents[1])
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, f"`import foundry, dispatcher` failed:\n{r.stderr}"


def test_b13_new_surface_present_and_callable():
    assert callable(foundry.parse_postrelease_verdict)
    assert callable(foundry.summarize_status)
    assert callable(foundry.status_cli)
    assert hasattr(foundry, "StatusSummary")
    # pre-existing control-flow entry points remain present + callable (regression)
    for fn in CONTROL_FLOW_FNS:
        assert callable(getattr(foundry, fn)), f"foundry.{fn} missing/not callable (regression)"


def test_b13_new_symbols_absent_from_foundry_control_flow():
    for fn_name in CONTROL_FLOW_FNS:
        names, _ = _fn_names_consts(getattr(foundry, fn_name))
        for sym in NEW_SYMBOLS:
            assert sym not in names, \
                f"{fn_name} references new symbol {sym!r} (must stay off the control path)"


def test_b13_new_symbols_absent_from_dispatcher():
    for sym in NEW_SYMBOLS:
        assert not hasattr(dispatcher, sym), f"dispatcher must not expose {sym!r}"
    names, _ = _module_names_consts(dispatcher)
    for sym in NEW_SYMBOLS:
        assert sym not in names, f"dispatcher references new symbol {sym!r}"


def test_b13_help_lists_existing_plus_status(capsys):
    with pytest.raises(SystemExit) as ei:
        foundry.main(["--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    for sub in ("run", "once", "doctor", "learnings", "agents",
                "lint-spec", "prd", "gate-scope", "status"):
        assert sub in out, f"subcommand {sub!r} missing from --help:\n{out}"


def test_b13_sentinels_and_status_values_unchanged():
    # Non-regression: the additive bite must not remove/rename the release
    # sentinels or the ship-outcome status vocabulary. Public compiled-const
    # introspection (not source text).
    _, consts = _module_names_consts(foundry)
    for sentinel in ("VERDICT:", "RESULT:", "ACTION:", "POSTRELEASE:"):
        assert any(sentinel in c for c in consts), \
            f"sentinel prefix {sentinel!r} vanished from foundry"
    for status in ("shipped", "no-ship", "infra-fail"):
        assert status in consts, f"res['status'] value {status!r} vanished from foundry"
    # AMBIGUITY / PM FEEDBACK: the spec's Behavior 13 says the subcommand string
    # "status" appears only in the new helper/CLI/argparse+tests, NEVER in the
    # control-flow fns. But the bare literal "status" is ALSO the pre-existing
    # res["status"] run-result dict KEY -- an unavoidably shared literal that
    # legitimately lives in run_continuous. We therefore assert the discriminating,
    # UNIQUE new symbols are off the control path (test above) and confirm the
    # status-producing entry points remain intact, rather than a brittle scan for
    # the ambiguous bare "status" literal.
    for fn in ("run_iteration", "run_continuous"):
        assert callable(getattr(foundry, fn)), f"foundry.{fn} missing (status-producer regression)"
