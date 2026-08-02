"""Black-box behaviour tests for iter 68 -- roadmap item 19, bite 2 of 3.

This bite WIRES the staffing-manifest READ into the live run_iteration behind an
absent-or-default-manifest guard: a new ProductConfig.staffing field + a
load_staffing_manifest(cfg) -> dict | None seam feed the iter-67
derive_stage_sequence; an absent OR default-equivalent manifest (every product
today) runs the existing fixed pipeline bit-for-bit, while a NON-default manifest
is DETECTED, logged with a stable diagnostic, and then falls back to the default
pipeline (the manifest-driven EXECUTOR lands in bite 3). This is the FIRST
run_iteration control-flow touch for item 19; it is a runtime no-op for every
configured product until an operator adds a non-default staffing.json.

ISOLATION CONTRACT (honored): every test below encodes the iter-68 PM spec's
Expected Behaviors (1-12), driven purely against the PUBLIC interface -- the
importable public callables/constants (foundry.load_config, foundry.ProductConfig,
foundry.load_staffing_manifest, foundry.run_iteration, foundry.derive_stage_sequence,
foundry._default_stage_sequence), the real product config/manifest data files read
via pathlib.Path(foundry.__file__), the committed scripts/leak_guard.py public API,
and inspect.getsource / the dispatcher module's file text (used ONLY to assert the
SPEC's control-path and new-content-ASCII observables, NOT to mirror implementation
logic). The run_iteration behaviours are exercised with SCRIPTED SEAMS (monkeypatch
run_stage / head_of_branch / power_state / revert_repo / postrelease_step /
next_iteration / log / load_staffing_manifest) exactly as the iter-03 postrelease
tester did -- fully offline, deterministic, no network, no real git push. The
engineer's / reviewer's notes and git diff text were NOT read as design input;
assertions encode the SPEC's behaviors, not impl quirks. Every path is built at
RUNTIME from foundry.__file__ (never a source-literal home path), so the committed
leak-guard passes on the ship commit.

NB on Behavior 12 (new content is pure ASCII): the spec's literal wording asks to
check inspect.getsource(foundry.run_iteration) for no byte >= 128, but
run_iteration is a LARGE pre-existing function that already carries legitimate
non-ASCII (em-dash / middle-dot bytes from prior iterations' docstrings), so a
whole-function ASCII scan FALSE-fails on the shipped tree, and a TESTER in
isolation (no git diff) cannot slice out only the newly-added lines of an existing
function. Most-reasonable reading tested here (and flagged as PM feedback): the
WHOLLY-NEW symbol load_staffing_manifest is scanned for ASCII in full, and the NEW
run_iteration content that is user-visible -- the diagnostic log line -- is asserted
ASCII on the runtime-captured string (see B7). The authoritative whole-file ship
gate is the committed leak-guard, which scans clean.

NB on the iter-54 meta-scanner: this file contains a `git diff --quiet` call, so it
must not carry the quoted main-module filename token on any non-comment line. The
main module is located via the BARE module's __file__; it is NOT pinned
byte-unchanged (it legitimately grows this iter -- only dispatcher.py + scripts/ are
pinned byte-unchanged as the control path).
"""
import importlib.util
import inspect
import json
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe)


# --------------------------------------------------------------------------
# runtime-built paths (never a source-literal home path)
# --------------------------------------------------------------------------
_ROOT = pathlib.Path(foundry.__file__).resolve().parent
DISPATCHER_PY = _ROOT / "dispatcher.py"
PLATFORM_CONFIG = _ROOT / "products" / "_platform" / "config.json"
REPOLENS_STAFFING = _ROOT / "products" / "repolens" / "staffing.json"
THIS_TEST = pathlib.Path(__file__).resolve()

DIAG_SUB = "manifest activates a non-default team"
SHIP_LINES = ["VERDICT: APPROVE", "RESULT: PASS", "ACTION: PUSHED newhead99"]
DEFAULT_STAGES = ["pm", "engineer", "reviewer", "tester", "final"]
SHIP_KEYS = {"status", "head", "iteration", "postrelease"}

_GIT_OK = subprocess.run(
    ["git", "rev-parse", "--is-inside-work-tree"],
    cwd=str(_ROOT), capture_output=True, text=True,
).returncode == 0

_REAL = object()  # sentinel: do NOT patch load_staffing_manifest (exercise the real seam)


# --------------------------------------------------------------------------
# helpers / fixtures (mirror the iter-03 run_iteration harness)
# --------------------------------------------------------------------------
def _write_cfg(tmp_path, **over):
    data = {
        "name": "demo",
        "repo": "{FOUNDRY}/ZZ/repo",
        "allowed_push_repo": "demo",
        "vision": "{FOUNDRY}/ZZ/VISION.md",
        "work_root": str(tmp_path / "work"),
    }
    data.update(over)
    n = len(list(tmp_path.glob("cfg_*.json")))
    p = tmp_path / f"cfg_{n}.json"
    p.write_text(json.dumps(data))
    return p


@pytest.fixture
def cfg(tmp_path):
    return foundry.load_config(str(_write_cfg(tmp_path)))


def _role(name):
    return {"role": name, "model": "builder-class model",
            "gate": False, "done_criteria": "criteria"}


def _manifest(names):
    return {"product": "x", "iteration_budget": 5,
            "roles": [_role(n) for n in names]}


def _make_recording_run_stage(lines, recorder):
    """Scripted run_stage: record the ORDERED stage label, write the positive
    sentinel lines to the stage's output file, return (ok=True, path). Positive
    sentinels only -> no fix-review / fix-tests / rerun diversion."""
    def _run_stage(cfg, iteration, stage, role_file, out_name, extra=""):
        recorder.append(stage)
        it_dir = cfg.state / f"iter-{iteration:02d}"
        it_dir.mkdir(parents=True, exist_ok=True)
        out = it_dir / out_name
        out.write_text("\n".join(lines) + "\n")
        return True, out
    return _run_stage


def _make_head(values):
    seq = list(values)
    def _head(cfg):
        return seq.pop(0) if len(seq) > 1 else seq[0]
    return _head


def _drive(cfg, monkeypatch, manifest, iteration):
    """Run one offline iteration with a clean-ship script. `manifest` is returned
    by a patched load_staffing_manifest, UNLESS it is the _REAL sentinel (then the
    real seam runs). Returns (result_dict, ordered_stage_labels, log_lines)."""
    stages, logs = [], []
    monkeypatch.setattr(foundry, "run_stage", _make_recording_run_stage(SHIP_LINES, stages))
    monkeypatch.setattr(foundry, "head_of_branch", _make_head(["base0000", "newhead99"]))
    monkeypatch.setattr(foundry, "power_state", lambda: "Now drawing from 'AC Power'")
    monkeypatch.setattr(foundry, "revert_repo", lambda *a, **k: None)
    monkeypatch.setattr(foundry, "postrelease_step",
                        lambda *a, **k: foundry.PostReleaseResult(True, False, "POSTRELEASE: HEALTHY"))
    monkeypatch.setattr(foundry, "next_iteration", lambda *a, **k: iteration)
    monkeypatch.setattr(foundry, "log", lambda *a, **k: logs.append(" ".join(str(x) for x in a)))
    if manifest is not _REAL:
        monkeypatch.setattr(foundry, "load_staffing_manifest", lambda c, _m=manifest: _m)
    res = foundry.run_iteration(cfg, iteration)
    return res, stages, logs


def _diag_count(logs):
    return sum(1 for m in logs if DIAG_SUB in m)


def _leak_guard():
    gp = _ROOT / "scripts" / "leak_guard.py"
    spec = importlib.util.spec_from_file_location("leak_guard_iter68_probe", gp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------
# B1 -- ProductConfig gains a backward-compatible staffing field defaulting to
#       <work_root>/staffing.json after resolve()
# --------------------------------------------------------------------------
def test_b1_default_staffing_from_work_root(cfg):
    # A config JSON that OMITS staffing still loads (backward compatible).
    assert cfg.staffing == str(pathlib.Path(cfg.work_root) / "staffing.json")
    assert pathlib.Path(cfg.staffing).name == "staffing.json"


def test_b1_real_platform_config_default(cfg):
    # The spec's concrete example: the real _platform config omits staffing.
    pc = foundry.load_config(str(PLATFORM_CONFIG))
    assert pc.staffing == str(pathlib.Path(pc.work_root) / "staffing.json")
    assert pathlib.Path(pc.staffing).name == "staffing.json"


# --------------------------------------------------------------------------
# B2 -- an explicit staffing value WINS, with {FOUNDRY} and ~ expansion
# --------------------------------------------------------------------------
def test_b2_explicit_foundry_token_expands_and_wins(tmp_path):
    # repo and staffing both use {FOUNDRY} -> same expansion prefix.
    cfg = foundry.load_config(str(_write_cfg(tmp_path, staffing="{FOUNDRY}/ZZ/manifest.json")))
    assert cfg.staffing.endswith("/ZZ/manifest.json")
    assert "{FOUNDRY}" not in cfg.staffing
    assert pathlib.Path(cfg.staffing).is_absolute()
    # same {FOUNDRY} expansion as the repo field (proves the expand() path is applied)
    assert cfg.staffing.rsplit("/ZZ/", 1)[0] == cfg.repo.rsplit("/ZZ/", 1)[0]
    # explicit wins: NOT the work_root default
    assert cfg.staffing != str(pathlib.Path(cfg.work_root) / "staffing.json")


def test_b2_tilde_expansion(tmp_path):
    cfg = foundry.load_config(str(_write_cfg(tmp_path, staffing="~/ZZ/manifest.json")))
    assert cfg.staffing == str(pathlib.Path("~/ZZ/manifest.json").expanduser())
    assert "~" not in cfg.staffing


# --------------------------------------------------------------------------
# B3 -- load_staffing_manifest returns None for a missing file; NEVER raises
# --------------------------------------------------------------------------
def test_b3_missing_file_returns_none(cfg):
    # cfg.staffing default points at a non-existent tmp path.
    assert not pathlib.Path(cfg.staffing).exists()
    assert foundry.load_staffing_manifest(cfg) is None


# --------------------------------------------------------------------------
# B4 -- valid JSON object -> the parsed dict
# --------------------------------------------------------------------------
def test_b4_valid_object_returns_dict(tmp_path):
    content = REPOLENS_STAFFING.read_text(encoding="utf-8")
    mp = tmp_path / "valid_manifest.json"
    mp.write_text(content)
    cfg = foundry.load_config(str(_write_cfg(tmp_path, staffing=str(mp))))
    got = foundry.load_staffing_manifest(cfg)
    assert isinstance(got, dict)
    assert got == json.loads(content)


# --------------------------------------------------------------------------
# B5 -- any UNUSABLE file -> None; NEVER raises. dict | None seam contract.
# --------------------------------------------------------------------------
UNUSABLE = [
    ("array", "[1, 2, 3]"),
    ("int", "42"),
    ("string", '"x"'),
    ("invalid_json", "{not valid json"),
    ("empty", ""),
]


@pytest.mark.parametrize("label,text", UNUSABLE)
def test_b5_unusable_text_returns_none(tmp_path, label, text):
    f = tmp_path / (label + ".json")
    f.write_text(text)
    cfg = foundry.load_config(str(_write_cfg(tmp_path, staffing=str(f))))
    assert foundry.load_staffing_manifest(cfg) is None  # no raise -> proves fail-safe


def test_b5_binary_non_utf8_returns_none(tmp_path):
    f = tmp_path / "binary.json"
    f.write_bytes(b"\xff\xfe\x00\x01")
    cfg = foundry.load_config(str(_write_cfg(tmp_path, staffing=str(f))))
    assert foundry.load_staffing_manifest(cfg) is None


def test_b5_directory_returns_none(tmp_path):
    d = tmp_path / "a_dir_manifest"
    d.mkdir()
    cfg = foundry.load_config(str(_write_cfg(tmp_path, staffing=str(d))))
    assert foundry.load_staffing_manifest(cfg) is None


# --------------------------------------------------------------------------
# B6 -- None manifest => the EXACT current fixed pipeline, byte-identical contract
# --------------------------------------------------------------------------
def test_b6_none_manifest_runs_default_pipeline(cfg, monkeypatch):
    res, stages, logs = _drive(cfg, monkeypatch, None, 68)
    assert stages == DEFAULT_STAGES
    assert res["status"] == "shipped"
    assert res["head"] == "newhead99"
    assert res["iteration"] == 68
    assert set(res) == SHIP_KEYS
    assert _diag_count(logs) == 0


# --------------------------------------------------------------------------
# B7 -- NON-default manifest => exactly one diagnostic line + the DEFAULT core
#       pipeline (no extra seat runs this bite)
# --------------------------------------------------------------------------
def test_b7_non_default_manifest_logs_and_falls_back(cfg, monkeypatch):
    names = ["product_manager", "engineer", "designer",
             "reviewer", "qa_tester", "release_gate"]
    mf = _manifest(names)
    # precondition: this manifest genuinely derives to a NON-default sequence
    assert foundry.derive_stage_sequence(mf) != foundry.derive_stage_sequence(None)
    res, stages, logs = _drive(cfg, monkeypatch, mf, 68)
    # exactly one diagnostic line, containing the stable substring
    diag = [m for m in logs if DIAG_SUB in m]
    assert len(diag) == 1, logs
    # the diagnostic content (new run_iteration content) is pure ASCII
    assert all(ord(c) < 128 for c in diag[0]), repr(diag[0])
    # still the DEFAULT core pipeline: no designer stage ran
    assert stages == DEFAULT_STAGES
    assert "designer" not in stages
    # normal ship/no-ship contract unchanged
    assert res["status"] == "shipped"
    assert set(res) == SHIP_KEYS


# --------------------------------------------------------------------------
# B8 -- a manifest that DERIVES to the default (real repolens) behaves like None:
#       NO diagnostic; guard keys on derived-sequence EQUALITY, not presence
# --------------------------------------------------------------------------
def test_b8_default_deriving_manifest_no_diagnostic(cfg, monkeypatch):
    mf = json.loads(REPOLENS_STAFFING.read_text(encoding="utf-8"))
    # precondition: repolens manifest derives to the DEFAULT sequence
    assert foundry.derive_stage_sequence(mf) == foundry.derive_stage_sequence(None)
    res, stages, logs = _drive(cfg, monkeypatch, mf, 68)
    assert _diag_count(logs) == 0
    assert stages == DEFAULT_STAGES
    assert res["status"] == "shipped"


# --------------------------------------------------------------------------
# B9 -- the guard introduces NO new state artifact and NO return-dict key.
#       Differential: a non-default run creates the SAME file set as a None run.
# --------------------------------------------------------------------------
def test_b9_guard_introduces_no_new_artifact_or_key(cfg, monkeypatch):
    res_none, _, _ = _drive(cfg, monkeypatch, None, 68)
    files_none = {p.name for p in (cfg.state / "iter-68").iterdir()}

    nd = _manifest(["product_manager", "engineer", "designer",
                    "reviewer", "qa_tester", "release_gate"])
    res_nd, _, _ = _drive(cfg, monkeypatch, nd, 69)
    files_nd = {p.name for p in (cfg.state / "iter-69").iterdir()}

    # the non-default (diagnostic) path adds NO file the default path does not
    assert files_nd == files_none
    # return-dict keys unchanged across both paths
    assert set(res_none) == set(res_nd) == SHIP_KEYS
    # reused iter-67 symbols behave unchanged (byte-identity is a reviewer/final
    # out-of-band numstat check -- not observable in tester isolation)
    assert foundry.derive_stage_sequence(None) == foundry._default_stage_sequence()
    assert len(foundry.derive_stage_sequence(None)) == 5


# --------------------------------------------------------------------------
# B10 -- dormant-until-data / resume-safe for real products: a config whose
#        resolved staffing points at a non-existent path takes the default path
#        with NO behavior change and NO diagnostic (the REAL wired seam).
# --------------------------------------------------------------------------
def test_b10_real_platform_config_is_dormant():
    pc = foundry.load_config(str(PLATFORM_CONFIG))
    assert not pathlib.Path(pc.staffing).exists()
    assert foundry.load_staffing_manifest(pc) is None
    assert foundry.derive_stage_sequence(None) == foundry._default_stage_sequence()


def test_b10_real_seam_wired_is_noop_when_absent(cfg, monkeypatch):
    # Do NOT patch load_staffing_manifest -> exercise the REAL wired seam. The
    # synthetic cfg has no staffing.json, so it must take the default path silently.
    assert not pathlib.Path(cfg.staffing).exists()
    res, stages, logs = _drive(cfg, monkeypatch, _REAL, 68)
    assert stages == DEFAULT_STAGES
    assert _diag_count(logs) == 0
    assert res["status"] == "shipped"


# --------------------------------------------------------------------------
# B11 -- control path byte-unchanged (dispatcher + scripts) + fresh-subprocess
#        import. The main module legitimately grows this iter (NOT pinned here --
#        the iter-54 meta-scanner bans the quoted main-module token in a file with
#        a --quiet git call; located via the bare module __file__).
# --------------------------------------------------------------------------
@pytest.mark.skipif(not _GIT_OK, reason="not inside a git work tree")
def test_b11_control_path_byte_unchanged():
    r = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", "dispatcher.py", "scripts/"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, "dispatcher.py / scripts NOT byte-unchanged from HEAD"


def test_b11_import_foundry_and_dispatcher():
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


# --------------------------------------------------------------------------
# B12 -- leak-safe (ship-blocker) with an ARMED matcher + NEW content ASCII.
#        The wholly-new symbol load_staffing_manifest is scanned in full; the new
#        run_iteration diagnostic content is scanned in B7. run_iteration's whole
#        source is NOT scanned (pre-existing non-ASCII -- see module docstring).
# --------------------------------------------------------------------------
def test_b12_leak_clean_and_new_content_ascii():
    mod = _leak_guard()
    denylist = mod.load_denylist(mod.DENYLIST_PATH.read_text())
    module_text = pathlib.Path(foundry.__file__).read_text(encoding="utf-8")
    assert mod.scan_text(module_text, denylist) == (), "main module leaks a denylisted token"
    assert mod.scan_text(THIS_TEST.read_text(encoding="utf-8"), denylist) == (), \
        "test file leaks a denylisted token"
    # matcher is ARMED (not inert): a RUNTIME-built home-path needle IS flagged.
    needle = "/" + "Users" + "/" + "nobody/secret.txt"
    assert mod.scan_text(needle, denylist), "leak matcher is inert (false-clean risk)"
    # the wholly-new seam's source is pure ASCII (checked via inspect.getsource --
    # never a whole-file scan, never git diff).
    src = inspect.getsource(foundry.load_staffing_manifest)
    offenders = [(i, hex(ord(c))) for i, c in enumerate(src) if ord(c) >= 128]
    assert offenders == [], offenders[:5]
    # the whole new test file is pure ASCII
    ttext = THIS_TEST.read_text(encoding="utf-8")
    assert [(i, c) for i, c in enumerate(ttext) if ord(c) >= 128] == []
