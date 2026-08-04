"""Black-box behaviour tests for iter 106 -- discovery bite 3b: WIRE the
iter-105 novelty RUT/VARIED verdict into the PM lead's stage prompt (the
"pedal" for the read-only brake), plus a roles/pm.md shape-break rule.

New symbols (all in foundry.py): a pure renderer `novelty_advice(report:
NoveltyReport) -> str` (branches on report.verdict; NO trailing newline; no
I/O), and an encapsulating read-only seam `pm_novelty_block(cfg, stage) -> str`
("" for every non-pm stage; for the pm stage returns
`novelty_advice(gather_novelty(cfg)) + "\\n"` wrapped defensively so a gather
hiccup degrades to ""). `build_prompt` is wired to inline
`pm_novelty_block(cfg, stage)` so the pm-stage prompt carries the verdict while
every other stage prompt stays byte-identical. `roles/pm.md` gains a
RUT-shape-break rule.

ISOLATION CONTRACT (HONORED): this file was written ONLY from the iter-106 PM
spec's Expected Behaviors (1-12), the product README / roadmap, the tests/
conventions (esp. the read-only-seam + build_prompt tests in
test_iter104_behavior.py and the value-object / seam tests in
test_iter105_behavior.py), and the product's own OBSERVABLE behaviour (running
it / public RUNTIME introspection -- module attrs, compiled `__code__.co_names`
/ `co_consts` tables, `roles/pm.md` read from disk). The implementation SOURCE
(foundry.py / dispatcher.py source text), the engineer's and reviewer's notes,
and `git diff` (and `git show HEAD:foundry.py`) were NOT read. Every check
drives the PUBLIC interface: the pure renderer via `foundry.novelty_advice`, the
seam via `foundry.pm_novelty_block` with monkeypatched bare-name
`foundry.gather_novelty` / `foundry.novelty_advice`, and the prompt builder via
`foundry.build_prompt(...)` against a TMP-`work_root` / TMP-`repo` config (the
real foundry repo / state / git / network are NEVER touched). Fully offline and
deterministic: real temp files only, no subprocess / git / network / agent-run.
"""
import dataclasses
import pathlib
import sys
import types

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402


# --------------------------------------------------------------------------
# helpers (mirror the suite's conventions; repo/work_root are TMP dirs so the
# real foundry repo / state is NEVER touched)
# --------------------------------------------------------------------------
def _write_cfg(tmp_path, roadmap_text="- x\n- y\n", **over):
    import json
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    rm = tmp_path / "ROADMAP.md"
    if roadmap_text is not None:
        rm.write_text(roadmap_text)
    data = {
        "name": "demoprod",
        "repo": str(repo),
        "allowed_push_repo": "demoprod",
        "vision": str(tmp_path / "VISION.md"),
        "work_root": str(tmp_path / "work"),
        "roadmap": str(rm),
    }
    data.update(over)
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data))
    return p


def _cfg(tmp_path, **kw):
    """A loaded config with a seeded learnings file so build_prompt is happy."""
    cfg = foundry.load_config(str(_write_cfg(tmp_path, **kw)))
    lp = pathlib.Path(cfg.learnings)
    lp.parent.mkdir(parents=True, exist_ok=True)
    lp.write_text(
        "## Patterns\n\n- a durable rule\n\n"
        "## Chronological lessons\n\n- [ENG iter01] a lesson\n"
    )
    return cfg


def _report(commits=(), roadmap=()):
    return foundry.NoveltyReport(commit_subjects=tuple(commits),
                                 roadmap_entries=tuple(roadmap))


def _rut_report():
    return _report(["a --json", "b --json", "c --json"])


def _varied_report():
    return _report(["alpha", "beta"], [])


def _snapshot_tree(root):
    root = pathlib.Path(root)
    if not root.exists():
        return {}
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in root.rglob("*") if p.is_file()
    }


def _deep(code, names):
    """Recursively collect co_names over nested code objects."""
    names.update(code.co_names)
    for c in code.co_consts:
        if isinstance(c, types.CodeType):
            _deep(c, names)
    return names


def _it_dir(tmp_path):
    d = tmp_path / "iterdir"
    d.mkdir(parents=True, exist_ok=True)
    return d


NON_PM_STAGES = ("engineer", "reviewer", "tester", "final", "reporter",
                 "pm_scout_a", "pm_scout_b")

PRIMITIVES = (
    "novelty_shape", "novelty_verdict", "NoveltyReport", "gather_novelty",
    "novelty_check_cli", "NOVELTY_RUT_THRESHOLD", "NOVELTY_DEFAULT_N",
    "NOVELTY_SELF_DESCRIBE_PHRASES",
)

HEADER = "NOVELTY CHECK (repetition brake):"


# ==========================================================================
# Behavior 1 -- novelty_advice is a pure str renderer (no I/O, idempotent)
# ==========================================================================
def test_b01_advice_returns_str():
    assert isinstance(foundry.novelty_advice(_rut_report()), str)
    assert isinstance(foundry.novelty_advice(_varied_report()), str)


def test_b01_advice_is_idempotent():
    r = _rut_report()
    assert foundry.novelty_advice(r) == foundry.novelty_advice(r)
    v = _varied_report()
    assert foundry.novelty_advice(v) == foundry.novelty_advice(v)


def test_b01_advice_writes_nothing(tmp_path, monkeypatch):
    # PURE: calling it must not create/modify any file in a temp cwd.
    monkeypatch.chdir(tmp_path)
    before = _snapshot_tree(tmp_path)
    foundry.novelty_advice(_rut_report())
    foundry.novelty_advice(_varied_report())
    assert _snapshot_tree(tmp_path) == before


# ==========================================================================
# Behavior 2 -- RUT advice content
# ==========================================================================
def test_b02_rut_advice_contains_all_required_substrings():
    r = _rut_report()
    adv = foundry.novelty_advice(r)
    assert HEADER in adv
    assert "verdict=RUT" in adv
    assert "REPETITION RUT" in adv
    assert "MUST break" in adv
    assert "## Triage" in adv
    assert "shape '%s'" % r.dominant_shape in adv
    assert "count %d" % r.dominant_count in adv
    assert "no rut detected" not in adv


def test_b02_rut_advice_names_the_actual_dominant_shape():
    # a different dominant shape must be echoed verbatim
    r = _report(["chore: tidy up imports", "chore: tidy up files",
                 "chore: tidy up docs"])
    assert r.verdict == "RUT"
    adv = foundry.novelty_advice(r)
    assert "shape '%s'" % r.dominant_shape in adv
    assert "count %d" % r.dominant_count in adv


# ==========================================================================
# Behavior 3 -- VARIED advice content
# ==========================================================================
def test_b03_varied_advice_contains_and_excludes():
    v = _varied_report()
    assert v.verdict == "VARIED"
    adv = foundry.novelty_advice(v)
    assert HEADER in adv
    assert "verdict=VARIED" in adv
    assert "no rut detected" in adv
    assert "Proceed" in adv
    assert "REPETITION RUT" not in adv
    assert "MUST break" not in adv


# ==========================================================================
# Behavior 4 -- pm_novelty_block is "" for every non-pm stage
# ==========================================================================
def test_b04_block_empty_for_non_pm_stages(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    # even if gather_novelty would return a RUT report, non-pm stages get ""
    monkeypatch.setattr(foundry, "gather_novelty", lambda cfg, limit=None: _rut_report())
    for st in NON_PM_STAGES:
        assert foundry.pm_novelty_block(cfg, st) == "", st


# ==========================================================================
# Behavior 5 -- pm stage: block == novelty_advice(report) + "\n"
# ==========================================================================
def test_b05_pm_block_is_advice_plus_newline_rut(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    rep = _rut_report()
    monkeypatch.setattr(foundry, "gather_novelty", lambda cfg, limit=None: rep)
    block = foundry.pm_novelty_block(cfg, "pm")
    assert block == foundry.novelty_advice(rep) + "\n"
    assert block.endswith("\n")
    assert not block.endswith("\n\n")


def test_b05_pm_block_is_advice_plus_newline_varied(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    rep = _varied_report()
    monkeypatch.setattr(foundry, "gather_novelty", lambda cfg, limit=None: rep)
    block = foundry.pm_novelty_block(cfg, "pm")
    assert block == foundry.novelty_advice(rep) + "\n"
    assert block.endswith("\n")


# ==========================================================================
# Behavior 6 -- both seams read by BARE module name at call time
# ==========================================================================
def test_b06_block_reads_both_seams_by_bare_name_rut(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(foundry, "gather_novelty", lambda cfg, limit=None: _rut_report())
    monkeypatch.setattr(foundry, "novelty_advice", lambda r: "ADVICE:" + r.verdict)
    assert foundry.pm_novelty_block(cfg, "pm") == "ADVICE:RUT\n"


def test_b06_block_reads_both_seams_by_bare_name_varied(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(foundry, "gather_novelty", lambda cfg, limit=None: _varied_report())
    monkeypatch.setattr(foundry, "novelty_advice", lambda r: "ADVICE:" + r.verdict)
    assert foundry.pm_novelty_block(cfg, "pm") == "ADVICE:VARIED\n"


# ==========================================================================
# Behavior 7 -- defensive: gather_novelty raising -> "" (never propagates)
# ==========================================================================
def test_b07_block_swallows_gather_exception(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)

    def boom(cfg, limit=None):
        raise RuntimeError("gather blew up")
    monkeypatch.setattr(foundry, "gather_novelty", boom)
    assert foundry.pm_novelty_block(cfg, "pm") == ""


def test_b07_block_swallows_advice_exception(tmp_path, monkeypatch):
    # a hiccup anywhere in the pm branch degrades to "" -- never crashes the stage
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(foundry, "gather_novelty", lambda cfg, limit=None: _rut_report())

    def bad_advice(r):
        raise RuntimeError("render blew up")
    monkeypatch.setattr(foundry, "novelty_advice", bad_advice)
    assert foundry.pm_novelty_block(cfg, "pm") == ""


# ==========================================================================
# Behavior 8 -- pm_novelty_block writes NOTHING to disk
# ==========================================================================
def test_b08_block_writes_nothing(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(foundry, "gather_novelty", lambda cfg, limit=None: _rut_report())
    before = _snapshot_tree(tmp_path)
    foundry.pm_novelty_block(cfg, "pm")
    assert _snapshot_tree(tmp_path) == before, "pm_novelty_block wrote to disk"


# ==========================================================================
# Behavior 9 -- build_prompt (pm stage) carries the block
# ==========================================================================
def test_b09_build_prompt_pm_contains_header(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(foundry, "gather_novelty", lambda cfg, limit=None: _rut_report())
    out = tmp_path / "pm.md"
    prompt = foundry.build_prompt(cfg, 7, "pm", "pm.md", out, _it_dir(tmp_path), "extra!")
    assert HEADER in prompt


def test_b09_build_prompt_pm_rut_vs_varied(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    out = tmp_path / "pm.md"
    itd = _it_dir(tmp_path)

    monkeypatch.setattr(foundry, "gather_novelty", lambda cfg, limit=None: _rut_report())
    rut_prompt = foundry.build_prompt(cfg, 7, "pm", "pm.md", out, itd, "extra!")
    assert "REPETITION RUT" in rut_prompt

    monkeypatch.setattr(foundry, "gather_novelty", lambda cfg, limit=None: _varied_report())
    var_prompt = foundry.build_prompt(cfg, 7, "pm", "pm.md", out, itd, "extra!")
    assert "no rut detected" in var_prompt
    assert "REPETITION RUT" not in var_prompt


# ==========================================================================
# Behavior 10 -- non-pm prompt has NO block, byte-identical across the patch
# ==========================================================================
def test_b10_engineer_prompt_never_carries_block(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    out = tmp_path / "engineer.md"
    itd = _it_dir(tmp_path)

    monkeypatch.setattr(foundry, "gather_novelty", lambda cfg, limit=None: _rut_report())
    eng_rut = foundry.build_prompt(cfg, 7, "engineer", "engineer.md", out, itd, "extra!")
    monkeypatch.setattr(foundry, "gather_novelty", lambda cfg, limit=None: _varied_report())
    eng_var = foundry.build_prompt(cfg, 7, "engineer", "engineer.md", out, itd, "extra!")

    assert HEADER not in eng_rut
    assert HEADER not in eng_var
    # PM-stage-only: the block cannot leak into a non-pm prompt regardless of verdict
    assert eng_rut == eng_var, "engineer prompt changed with the novelty verdict"


def test_b10_other_context_substrings_present_in_both(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    itd = _it_dir(tmp_path)
    monkeypatch.setattr(foundry, "gather_novelty", lambda cfg, limit=None: _rut_report())

    pm_prompt = foundry.build_prompt(cfg, 7, "pm", "pm.md", tmp_path / "pm.md", itd, "extra!")
    eng_prompt = foundry.build_prompt(cfg, 7, "engineer", "engineer.md", tmp_path / "e.md", itd, "extra!")

    repo_path = str(pathlib.Path(cfg.repo))
    for prompt in (pm_prompt, eng_prompt):
        assert "demoprod" in prompt            # product name
        assert repo_path in prompt             # repo
        assert "re-delegate" in prompt.lower()  # anti-delegation clause
        assert "extra!" in prompt              # per-stage extra passthrough


# ==========================================================================
# Behavior 11 -- wiring + encapsulation via deep co_names walk
# ==========================================================================
def test_b11_build_prompt_references_only_the_seam():
    names = _deep(foundry.build_prompt.__code__, set())
    assert "pm_novelty_block" in names, "build_prompt does not call pm_novelty_block"
    leaked = [p for p in PRIMITIVES if p in names]
    assert leaked == [], "primitives leaked into build_prompt: %r" % leaked


def test_b11_both_modules_import():
    assert foundry is not None and dispatcher is not None


def test_b11_iter105_b10_stays_green():
    # the iter-105 invariant (orchestrators reference no novelty PRIMITIVE) must
    # still hold: build_prompt references the seam, not the primitives.
    orchestrators = ("build_prompt", "run_stage", "run_iteration",
                     "run_continuous", "run_execution_plan")
    for fn in orchestrators:
        names = _deep(getattr(foundry, fn).__code__, set())
        for p in PRIMITIVES:
            assert p not in names, "%s references primitive %s" % (fn, p)


# ==========================================================================
# Behavior 12 -- roles/pm.md carries the human-facing shape-break rule
# ==========================================================================
def test_b12_roles_pm_md_has_rule():
    repo_root = pathlib.Path(__file__).resolve().parents[1]
    pm_md = (repo_root / "roles" / "pm.md").read_text()
    assert "NOVELTY CHECK" in pm_md
    assert "RUT" in pm_md


# ==========================================================================
# meta -- this test file is pure ASCII
# ==========================================================================
def test_meta_this_file_is_pure_ascii():
    pathlib.Path(__file__).read_bytes().decode("ascii")
