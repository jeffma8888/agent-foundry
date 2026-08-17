"""Iteration 192 -- BLACK-BOX behavior tests: the gap-register seam goes LIVE.

Spec under test (products/_platform/state/iter-192/pm.md), Expected Behaviors 1-9:
   1. no opt-in, nothing moves -- every stage prompt is byte-identical to PRE
   2. opted in, the `pm` prompt gains EXACTLY the seam's output, in position
   3. opted in, only the `pm` stage moves
   4. exactly ONE call site, reached for EVERY stage (stage-IGNORING scripted seam)
   5. the real stage string is forwarded to the seam unmodified
   6. fail-soft survives the wiring (`gather_gaps` raising -> PRE, no propagation)
   7. a configured-but-absent register still ANNOUNCES itself (anti-fail-open)
   8. the tracked `_platform` config declares the opt-in, clone-safely
   9. invariants + prose parity (imports, signatures, docstring dormancy claim)

ISOLATION CONTRACT (HONORED): written from the iter-192 PM spec, the conventions of
`tests/test_iter188_behavior.py` (the seam's own iteration), and the product's OWN
OBSERVABLE surface -- calling its public functions and reading their docstrings /
signatures.  `foundry.py`'s implementation TEXT was not read, and neither were
`engineer.md`, `reviewer.md`, `fix_review.md`, `IMPLEMENTATION.patch`, nor `git diff`.

HOW `PRE` IS BUILT, AND WHY NOT WITH A TWIN CONFIG.  `PRE` is the prompt the
pre-192 `build_prompt` produced: it had NO call site, which is observationally
identical to a call site whose seam returns "".  So `PRE(stage)` here is built from
the SAME cfg with `pm_gap_block` monkeypatched to `lambda c, s: ""`.  Deriving both
sides from ONE cfg removes the fixture-path divergence that made an earlier
twin-cfg attempt report six false regressions (`_twin_cfgs`, test_iter188:532-538):
when EVERY case differs by one magnitude, suspect the harness, not the change.
The twin-config form is still exercised once, in `test_b2_twin_configs...`, with
both configs over the SAME tmp tree so only `gap_register` varies.

OFFLINE + FRESH-CLONE SAFE: every register fixture is built in `tmp_path`; no test
reads the real `~/projects/agent-gap-radar`, asserts an absolute machine path, pins
a record count, spawns a subprocess, or touches the network.  Behavior 8 asserts
the DECLARED config only -- never that the sibling register directory exists
(OPERATOR 2026-08-11: a fresh clone has only the tracked configs).
"""
from __future__ import annotations

import inspect
import json
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe -- the product quality bar)

THIS_ITER = 192

ITER_LINE = "- Iteration number for file naming:"
SENTINEL = "ZZ-ITER192-GAP-SEAM-SENTINEL-ZZ"
NOVELTY_SENTINEL = "ZZ-ITER192-NOVELTY-SENTINEL-ZZ\n"

# The role card each stage is served with.  Every value must be a file that really
# exists under `roles/`, because a stage is only "served" if a prompt can be built.
ROLE_FILE = {
    "pm": "pm.md",
    "engineer": "engineer.md",
    "reviewer": "reviewer.md",
    "tester": "tester.md",
    "final": "final.md",
    "fix": "fix.md",
    "reporter": "reporter.md",
    "pm_scout_a": "pm_scout.md",
    "pm_scout_b": "pm_scout.md",
    "fix-review": "reviewer.md",
    "fix-tests": "tester.md",
    "tester-rerun": "tester.md",
    "tester-retry": "tester.md",
    "tester-retry2": "tester.md",
}


def _stage_domain() -> tuple[str, ...]:
    """Every stage name `build_prompt` is asked to serve, derived STRUCTURALLY.

    Hardcoding a stage list is how a matrix silently shrinks to nothing; this reads
    the module's own sequence plus its own extra-stage output map, so a new stage
    joins the matrix automatically.  `test_b0_stage_domain_is_not_vacuous` prints
    the domain's SIZE into its own assertion message.
    """
    names = [spec.stage for spec in foundry.derive_stage_sequence(None)]
    names.extend(("fix", "pm_scout_a", "pm_scout_b"))
    names.extend(sorted(foundry.STAGE_OUTPUT_NAMES))
    out: list[str] = []
    for name in names:
        if name not in out:
            out.append(name)
    return tuple(out)


ALL_STAGES = _stage_domain()
NON_PM_STAGES = tuple(s for s in ALL_STAGES if s != "pm")


# --------------------------------------------------------------------------
# helpers -- mirror tests/test_iter188_behavior.py; `repo` and `work_root` are
# ALWAYS tmp dirs so the real foundry repo / state can never be touched
# --------------------------------------------------------------------------
def _record(gid, sev, freq, trac, layer="orchestration", status="open"):
    """A record spelled with the register's OWN stored keys and nothing else."""
    return {
        "id": gid,
        "title": "title of %s" % gid,
        "layer": layer,
        "gap_type": "missing-primitive",
        "status": status,
        "problem": "problem text",
        "symptom": "symptom text",
        "why_now": "why now text",
        "existing": "existing text",
        "severity": sev,
        "frequency": freq,
        "tractability": trac,
        "evidence": [{"source_class": "peer-reviewed",
                      "locator": "https://example.test/e",
                      "excerpt": "an excerpt"}],
        "build_hypothesis": "hypothesis text",
        "tags": ["a-tag"],
        "check": {"present_when": {"any_file_matches": ["x"]}},
    }


def _register(root, records=()):
    """Build `<root>/gaps/<id>.json` for each record. Returns `str(root)`."""
    root = pathlib.Path(root)
    gaps = root / "gaps"
    gaps.mkdir(parents=True, exist_ok=True)
    for rec in records:
        (gaps / ("%s.json" % rec["id"])).write_text(json.dumps(rec), encoding="utf-8")
    return str(root)


def _base_tree(tmp_path, sub="p"):
    base = pathlib.Path(tmp_path) / sub
    base.mkdir(parents=True, exist_ok=True)
    (base / "repo").mkdir(exist_ok=True)
    (base / "VISION.md").write_text("product vision text\n", encoding="utf-8")
    (base / "ROADMAP.md").write_text("- a roadmap item\n", encoding="utf-8")
    return base, {
        "name": "demoprod",
        "repo": str(base / "repo"),
        "allowed_push_repo": "demoprod",
        "vision": str(base / "VISION.md"),
        "roadmap": str(base / "ROADMAP.md"),
        "work_root": str(base / "work"),
    }


def _load(base, label, common, **over):
    data = dict(common)
    data.update(over)
    path = base / ("%s.json" % label)
    path.write_text(json.dumps(data), encoding="utf-8")
    cfg = foundry.load_config(str(path))
    lp = pathlib.Path(cfg.learnings)
    lp.parent.mkdir(parents=True, exist_ok=True)
    lp.write_text("## Patterns\n\n- a durable rule\n\n- [ENG iter01] a lesson\n",
                  encoding="utf-8")
    return cfg


def _cfg(tmp_path, sub="p", **over):
    base, common = _base_tree(tmp_path, sub=sub)
    return _load(base, "config", common, **over)


def _opted_in(tmp_path, sub="p", records=None):
    """A cfg whose `gap_register` points at a freshly built tmp register."""
    if records is None:
        records = [_record("GAP-001", 5, 5, 5), _record("GAP-002", 4, 4, 4)]
    base, common = _base_tree(tmp_path, sub=sub)
    reg = _register(base / "reg", records)
    return _load(base, "config", common, gap_register=reg), reg


def _prompt(cfg, stage):
    it_dir = pathlib.Path(cfg.work_root) / "state" / ("iter-%d" % THIS_ITER)
    it_dir.mkdir(parents=True, exist_ok=True)
    role = ROLE_FILE.get(stage, "pm.md")
    return foundry.build_prompt(cfg, THIS_ITER, stage, role,
                                it_dir / ("%s.md" % stage), it_dir, "extra!")


def _pre(cfg, stage, monkeypatch):
    """The pre-192 prompt: the same call site with the seam forced to ""."""
    with monkeypatch.context() as m:
        m.setattr(foundry, "pm_gap_block", lambda c, s: "")
        return _prompt(cfg, stage)


# --------------------------------------------------------------------------
# behavior 0 -- the matrix's DOMAIN, asserted before anything is measured over it
# --------------------------------------------------------------------------
def test_b0_stage_domain_is_not_vacuous() -> None:
    """FILE-FIRST oracle. A prompt matrix over an empty domain proves nothing."""
    core = tuple(spec.stage for spec in foundry.derive_stage_sequence(None))
    assert core, "derive_stage_sequence(None) served no stage -- vacuous domain"
    for stage in core:
        assert stage in ALL_STAGES, "core stage %r missing from the matrix" % stage
    assert "pm" in ALL_STAGES, "the pm stage is not in the matrix"
    assert len(NON_PM_STAGES) >= 4, (
        "only %d non-pm stage(s) in a domain of %d -- too thin to prove 'only pm moves'"
        % (len(NON_PM_STAGES), len(ALL_STAGES)))
    for stage in ALL_STAGES:
        assert (_ROOT / "roles" / ROLE_FILE.get(stage, "pm.md")).is_file(), (
            "stage %r maps to a role card that does not exist" % stage)


# --------------------------------------------------------------------------
# behavior 1 -- no opt-in, nothing moves
# --------------------------------------------------------------------------
def test_b1_unconfigured_seam_contributes_zero_chars_to_every_stage(
        tmp_path, monkeypatch) -> None:
    cfg = _cfg(tmp_path, sub="off")
    assert cfg.gap_register == "", "fixture must NOT be opted in"
    for stage in ALL_STAGES:
        assert foundry.pm_gap_block(cfg, stage) == "", (
            "stage %r renders a block with no register configured" % stage)
        assert _prompt(cfg, stage) == _pre(cfg, stage, monkeypatch), (
            "stage %r prompt moved with no register configured" % stage)


def test_b1_unconfigured_prompt_carries_no_register_announcement(tmp_path) -> None:
    """The feed's own header must be absent, not merely empty-ish."""
    cfg = _cfg(tmp_path, sub="off2")
    for stage in ALL_STAGES:
        assert "EXTERNAL GAP REGISTER" not in _prompt(cfg, stage), stage


# --------------------------------------------------------------------------
# behavior 2 -- opted in, the pm prompt gains EXACTLY the seam's output
# --------------------------------------------------------------------------
def test_b2_pm_prompt_is_pre_plus_exactly_the_seam_output(tmp_path,
                                                          monkeypatch) -> None:
    cfg, reg = _opted_in(tmp_path, sub="on")
    assert cfg.gap_register == reg
    block = foundry.pm_gap_block(cfg, "pm")
    assert block, "the opted-in fixture must render a non-empty block"
    pre = _pre(cfg, "pm", monkeypatch)
    post = _prompt(cfg, "pm")
    assert post != pre, "the pm prompt did not consume the configured register"
    assert len(post) == len(pre) + len(block), (
        "pm prompt grew by %d chars, the seam rendered %d"
        % (len(post) - len(pre), len(block)))
    assert post.count(block) == 1, "the seam's output appears %d times" % post.count(block)
    assert post.replace(block, "", 1) == pre, (
        "the pm delta is not EXACTLY one insertion of the seam's output")


def test_b2_insertion_sits_immediately_before_the_iteration_number_line(
        tmp_path) -> None:
    cfg, _ = _opted_in(tmp_path, sub="pos")
    block = foundry.pm_gap_block(cfg, "pm")
    post = _prompt(cfg, "pm")
    assert post.count(ITER_LINE) == 1, "the iteration-number line is not unique"
    tail = post[post.index(block) + len(block):]
    assert tail.startswith(ITER_LINE), (
        "the gap block is not immediately followed by %r -- it is followed by %r"
        % (ITER_LINE, tail[:80]))


def test_b2_insertion_sits_immediately_after_the_novelty_block(tmp_path,
                                                               monkeypatch) -> None:
    """Ordering proved with a scripted NOVELTY seam, so no history fixture is needed."""
    cfg, _ = _opted_in(tmp_path, sub="order")
    block = foundry.pm_gap_block(cfg, "pm")
    assert block
    monkeypatch.setattr(foundry, "pm_novelty_block",
                        lambda c, s: NOVELTY_SENTINEL if s == "pm" else "")
    post = _prompt(cfg, "pm")
    assert post.count(NOVELTY_SENTINEL) == 1, "the novelty seam is not consumed once"
    assert post.count(block) == 1
    assert post.index(block) == post.index(NOVELTY_SENTINEL) + len(NOVELTY_SENTINEL), (
        "the gap block does not start immediately after the novelty block")


def test_b2_twin_configs_over_one_tree_differ_only_by_the_pm_block(
        tmp_path) -> None:
    """The twin-config form, done safely: ONE tree, only `gap_register` varies.

    Both configs must share `repo`, `work_root`, `learnings` and `roles_dir`; an
    earlier version of this shape built them in two tmp subdirs and every stage
    'diverged' by the fixture's own path strings.
    """
    base, common = _base_tree(tmp_path, sub="twin")
    reg = _register(base / "reg", [_record("GAP-001", 5, 5, 5)])
    off = _load(base, "off", common)
    on = _load(base, "on", common, gap_register=reg)
    assert off.repo == on.repo and off.work_root == on.work_root
    assert off.learnings == on.learnings and off.roles_dir == on.roles_dir
    assert off.gap_register == "" and on.gap_register == reg
    block = foundry.pm_gap_block(on, "pm")
    assert block
    pm_off, pm_on = _prompt(off, "pm"), _prompt(on, "pm")
    assert len(pm_on) == len(pm_off) + len(block)
    assert pm_on.replace(block, "", 1) == pm_off


# --------------------------------------------------------------------------
# behavior 3 -- opted in, ONLY the pm stage moves
# --------------------------------------------------------------------------
def test_b3_no_non_pm_stage_moves_when_opted_in(tmp_path, monkeypatch) -> None:
    cfg, _ = _opted_in(tmp_path, sub="only")
    assert foundry.pm_gap_block(cfg, "pm"), "fixture must render a block for pm"
    for stage in NON_PM_STAGES:
        assert foundry.pm_gap_block(cfg, stage) == "", (
            "the seam rendered a block for non-pm stage %r" % stage)
        assert _prompt(cfg, stage) == _pre(cfg, stage, monkeypatch), (
            "stage %r prompt changed when a gap register was configured" % stage)
        assert "EXTERNAL GAP REGISTER" not in _prompt(cfg, stage), stage


# --------------------------------------------------------------------------
# behavior 4 -- exactly ONE call site, reached for EVERY stage
# --------------------------------------------------------------------------
def test_b4_stage_ignoring_seam_is_consumed_once_by_every_stage(tmp_path,
                                                                monkeypatch) -> None:
    """The gate lives INSIDE the seam: the call site is unconditional."""
    cfg, _ = _opted_in(tmp_path, sub="onecall")
    monkeypatch.setattr(foundry, "pm_gap_block", lambda c, s: SENTINEL + "\n")
    for stage in ALL_STAGES:
        assert _prompt(cfg, stage).count(SENTINEL) == 1, (
            "stage %r consumes pm_gap_block %d time(s), expected exactly 1"
            % (stage, _prompt(cfg, stage).count(SENTINEL)))


def test_b4_call_site_passes_the_live_cfg_object(tmp_path, monkeypatch) -> None:
    """The seam is handed the SAME cfg the prompt is built from, not a copy."""
    cfg, _ = _opted_in(tmp_path, sub="cfgid")
    seen: list[object] = []

    def spy(c, s):
        seen.append(c)
        return ""

    monkeypatch.setattr(foundry, "pm_gap_block", spy)
    _prompt(cfg, "pm")
    assert len(seen) == 1, "pm_gap_block was called %d times for one prompt" % len(seen)
    assert seen[0] is cfg, "the call site did not forward the live cfg object"


# --------------------------------------------------------------------------
# behavior 5 -- the real stage string is forwarded unmodified
# --------------------------------------------------------------------------
def test_b5_real_stage_is_forwarded_so_only_pm_renders(tmp_path,
                                                       monkeypatch) -> None:
    cfg, _ = _opted_in(tmp_path, sub="fwd")
    monkeypatch.setattr(foundry, "pm_gap_block",
                        lambda c, s: SENTINEL + "\n" if s == "pm" else "")
    assert SENTINEL in _prompt(cfg, "pm"), "the pm stage was not forwarded as 'pm'"
    for stage in NON_PM_STAGES:
        assert SENTINEL not in _prompt(cfg, stage), (
            "stage %r was forwarded to the seam as 'pm'" % stage)


def test_b5_every_stage_receives_its_own_name(tmp_path, monkeypatch) -> None:
    """Stronger than the sentinel form: record what each call actually received."""
    cfg, _ = _opted_in(tmp_path, sub="names")
    got: list[str] = []
    monkeypatch.setattr(foundry, "pm_gap_block",
                        lambda c, s: got.append(s) or "")
    for stage in ALL_STAGES:
        _prompt(cfg, stage)
    assert got == list(ALL_STAGES), (
        "the seam received %r, the prompts were built for %r" % (got, list(ALL_STAGES)))


# --------------------------------------------------------------------------
# behavior 6 -- fail-soft survives the wiring
# --------------------------------------------------------------------------
@pytest.mark.parametrize("seam", ("gather_gaps", "gap_advice"))
def test_b6_a_raising_inner_seam_degrades_the_pm_prompt_to_pre(tmp_path, monkeypatch,
                                                               seam) -> None:
    cfg, _ = _opted_in(tmp_path, sub="failsoft-" + seam)
    assert foundry.pm_gap_block(cfg, "pm"), "fixture must be non-empty before patching"
    pre = _pre(cfg, "pm", monkeypatch)

    def boom(*_a, **_k):
        raise RuntimeError("register exploded")

    monkeypatch.setattr(foundry, seam, boom)
    post = _prompt(cfg, "pm")          # must NOT raise
    assert post == pre, (
        "a raising %s changed the pm prompt instead of degrading to PRE" % seam)


def test_b6_a_raising_seam_leaves_every_other_stage_untouched(tmp_path,
                                                              monkeypatch) -> None:
    cfg, _ = _opted_in(tmp_path, sub="failsoft-all")
    pre = {stage: _pre(cfg, stage, monkeypatch) for stage in ALL_STAGES}

    def boom(*_a, **_k):
        raise RuntimeError("register exploded")

    monkeypatch.setattr(foundry, "gather_gaps", boom)
    for stage in ALL_STAGES:
        assert _prompt(cfg, stage) == pre[stage], stage


# --------------------------------------------------------------------------
# behavior 7 -- a configured-but-absent register still ANNOUNCES itself
# --------------------------------------------------------------------------
def test_b7_absent_register_announces_itself_and_is_not_suppressed(tmp_path,
                                                                   monkeypatch) -> None:
    """Anti-fail-open: an unconfigured feed and an unreadable one are DIFFERENT facts."""
    base, common = _base_tree(tmp_path, sub="absent")
    missing = base / "no-such-register"
    cfg = _load(base, "config", common, gap_register=str(missing))
    assert not missing.exists(), "fixture register must NOT exist"
    assert cfg.gap_register == str(missing)

    pre = _pre(cfg, "pm", monkeypatch)
    post = _prompt(cfg, "pm")
    assert post != pre, (
        "a configured-but-absent register rendered SILENTLY -- the fail-open shape")

    lines = post.splitlines()
    header = "EXTERNAL GAP REGISTER (read-only evidence feed): %s" % missing
    assert header in lines, (
        "the pm prompt does not name the configured register verbatim; expected %r"
        % header)
    zero = [ln for ln in lines if "0 record(s) survived" in ln]
    assert len(zero) == 1, (
        "expected exactly one line stating '0 record(s) survived', got %r" % zero)


def test_b7_absent_register_still_leaves_non_pm_prompts_alone(tmp_path,
                                                              monkeypatch) -> None:
    base, common = _base_tree(tmp_path, sub="absent2")
    cfg = _load(base, "config", common,
                gap_register=str(base / "no-such-register-2"))
    for stage in NON_PM_STAGES:
        assert _prompt(cfg, stage) == _pre(cfg, stage, monkeypatch), stage


# --------------------------------------------------------------------------
# behavior 8 -- the tracked `_platform` config declares the opt-in, CLONE-SAFELY
# --------------------------------------------------------------------------
def test_b8_tracked_platform_config_declares_the_opt_in() -> None:
    """DECLARED config only. Never asserts the sibling register EXISTS: a fresh
    clone has only the tracked configs (OPERATOR 2026-08-11)."""
    path = _ROOT / "products" / "_platform" / "config.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["gap_register"].startswith("~/"), (
        "the tracked opt-in must be a ~ path, not an absolute machine path")
    assert isinstance(data["gap_layers"], list) and data["gap_layers"]

    cfg = foundry.load_config(str(path))
    assert cfg.name == "_platform"
    assert cfg.gap_register, "load_config resolved the opt-in to an empty register"
    assert "~" not in cfg.gap_register, "the tilde survived expansion"
    assert isinstance(cfg.gap_layers, tuple) and cfg.gap_layers
    assert all(isinstance(x, str) and x for x in cfg.gap_layers)


def test_b8_no_other_tracked_product_is_opted_in_by_accident() -> None:
    seen = 0
    for cfg_path in sorted((_ROOT / "products").glob("*/config.json")):
        seen += 1
        if cfg_path.parent.name == "_platform":
            continue
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        assert "gap_register" not in data, "%s enables gap_register" % cfg_path.parent.name
        assert "gap_layers" not in data, "%s enables gap_layers" % cfg_path.parent.name
    assert seen >= 2, "only %d tracked product config(s) scanned -- vacuous" % seen


def test_b8_no_tracked_file_carries_the_machine_absolute_register_path() -> None:
    """The expanded path may exist only at RUNTIME, never in a tracked file."""
    cfg = foundry.load_config(str(_ROOT / "products" / "_platform" / "config.json"))
    needle = cfg.gap_register
    assert needle.startswith("/"), "expected an absolute expansion to search for"
    for name in ("products/_platform/config.json", "foundry.py", "dispatcher.py",
                 "tests/test_iter192_behavior.py", "tests/test_iter188_behavior.py"):
        text = (_ROOT / name).read_text(encoding="utf-8", errors="replace")
        assert needle not in text, "%s hardcodes the absolute register path" % name


# --------------------------------------------------------------------------
# behavior 9 -- invariants and prose parity
# --------------------------------------------------------------------------
def test_b9_both_modules_still_import() -> None:
    """The product quality bar, asserted in-process (no subprocess, no 120s risk)."""
    assert foundry.__name__ == "foundry"
    assert dispatcher.__name__ == "dispatcher"
    assert hasattr(dispatcher, "main")
    assert callable(foundry.build_prompt)


def test_b9_the_three_seam_signatures_are_unchanged() -> None:
    assert str(inspect.signature(foundry.gather_gaps)) == \
        "(cfg: 'ProductConfig') -> 'dict[str, object]'"
    assert str(inspect.signature(foundry.gap_advice)) == \
        "(feed: 'Mapping[str, object]') -> 'str'"
    assert str(inspect.signature(foundry.pm_gap_block)) == \
        "(cfg: 'ProductConfig', stage: 'str') -> 'str'"
    assert foundry.GAP_BLOCK_TOP_N == 5, "GAP_BLOCK_TOP_N was not left alone"


def test_b9_the_docstring_dormancy_claim_is_retired() -> None:
    """The claim became FALSE the moment the call site landed."""
    doc = foundry.pm_gap_block.__doc__ or ""
    assert doc.strip(), "pm_gap_block lost its docstring"
    assert "DORMANT" not in doc.upper(), (
        "pm_gap_block still claims to be DORMANT while build_prompt calls it")
    assert "build_prompt" in doc, "the docstring does not name its run-path caller"


def test_b9_the_seam_still_writes_nothing_to_disk(tmp_path) -> None:
    cfg, _ = _opted_in(tmp_path, sub="nowrite")
    _prompt(cfg, "pm")                      # create the state dir first
    root = pathlib.Path(tmp_path)
    before = sorted((str(p.relative_to(root)), p.stat().st_size)
                    for p in root.rglob("*") if p.is_file())
    assert foundry.pm_gap_block(cfg, "pm")
    after = sorted((str(p.relative_to(root)), p.stat().st_size)
                   for p in root.rglob("*") if p.is_file())
    assert before == after, "pm_gap_block wrote to disk"
