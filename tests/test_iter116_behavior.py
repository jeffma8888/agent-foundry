"""Black-box behaviour tests for iter 116 -- discovery bite 4b: a LIVE, TRACKED,
committed decision log `DIRECTIONS.md`, wired into run_iteration.

New public surface under test (all module-level in foundry.py, resolved by BARE
name so monkeypatch.setattr(foundry, ...) bites, matching bite-4a conventions):

  * render_directions_doc(digest) -> str   (pure, total; header + digest.render())
  * iteration_is_scouted(cfg, n) -> bool    (a scout file exists for iter-0n)
  * refresh_directions_file(cfg) -> bool    (writes <repo>/DIRECTIONS.md; swallow-safe)

and the WIRING of a single guarded call
  if iteration_is_scouted(cfg, iteration): refresh_directions_file(cfg)
into run_iteration immediately BEFORE the final stage.

ISOLATION CONTRACT (HONORED as an original tester deliverable): this file was
written ONLY from the iter-116 PM spec's Expected Behaviors (1-12), the existing
tests/ conventions (esp. tests/test_iter115_behavior.py for the bite-4a cores and
tests/test_iter072_behavior.py / tests/test_iter113_behavior.py for the
run_iteration seam-recorder harness), and the product's own OBSERVABLE behaviour
by driving its PUBLIC interface. The implementation SOURCE of foundry.py, the
engineer's/reviewer's notes, and `git diff` were NOT read. Every check drives the
public surface: the pure fns via foundry.render_directions_doc(...) /
foundry.iteration_is_scouted(...) / foundry.refresh_directions_file(...) against a
TMP work_root config with real temp files, and the wiring via
foundry.run_iteration(cfg, N) with ALL external effects patched through their
bare-name module seams (run_stage / head_of_branch / power_state / revert_repo /
postrelease_step / next_iteration / log, plus iteration_is_scouted /
refresh_directions_file). The real foundry repo/state is NEVER touched. Fully
offline & deterministic: real temp files only; ZERO real subprocess/git/network
(except the fresh-import regression probe, which only imports the two modules).
"""
import io
import json
import pathlib
import subprocess
import sys
import types

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402


# em-dash constructed rather than embedded so the source stays pure-ASCII bytes.
EMDASH = "\u2014"

# fixed values for the offline run_iteration ship path (never a source-literal
# home path). Mirrors tests/test_iter072_behavior.py.
BASE = "base0000"
NEWHEAD = "newhead99"
POST_SENTINEL = "POSTRELEASE: HEALTHY"
SHIP_LINES = ["VERDICT: APPROVE", "RESULT: PASS", "ACTION: PUSHED " + NEWHEAD]
SHIP_KEYS = {"status", "head", "iteration", "postrelease"}
DEFAULT_STAGES = ["pm", "engineer", "reviewer", "tester", "final"]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _write_cfg(tmp_path, **over):
    """A minimal product config in a tmp dir. `repo`/`work_root` are TMP dirs so
    the real foundry repo/state is NEVER touched."""
    pathlib.Path(tmp_path).mkdir(parents=True, exist_ok=True)
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
    n = len(list(tmp_path.glob("cfg_*.json")))
    p = tmp_path / f"cfg_{n}.json"
    p.write_text(json.dumps(data))
    return p


def _cfg(tmp_path, **over):
    return foundry.load_config(str(_write_cfg(tmp_path, **over)))


def _snapshot_tree(root):
    """Map {relative-path: bytes} for every file under root (no-write proof)."""
    root = pathlib.Path(root)
    if not root.exists():
        return {}
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in root.rglob("*") if p.is_file()
    }


def _entry(**over):
    base = dict(iteration=5, lenses=("new-capability", "hardening/DX"),
                candidates=("Candidate C1 -- alpha", "Candidate B1 -- beta"),
                winner="C1", action="PUSHED", sha="abc123")
    base.update(over)
    return foundry.DirectionsEntry(**base)


def _digest(entries=(), product="demoprod"):
    return foundry.DirectionsDigest(product=product, entries=tuple(entries))


def _iter_dir(cfg, iteration):
    return pathlib.Path(cfg.state) / f"iter-{iteration:02d}"


def _boom(*a, **k):
    raise RuntimeError("seam raised on purpose")


def _fn_names_deep(fn):
    """Every name referenced by fn's code, recursing into nested code objects.
    Pure runtime introspection -- does NOT read the module source text."""
    seen = set()
    stack = [fn.__code__]
    names = set()
    while stack:
        code = stack.pop()
        if id(code) in seen:
            continue
        seen.add(id(code))
        names |= set(code.co_names)
        stack += [c for c in code.co_consts if isinstance(c, types.CodeType)]
    return names


# --------------------------------------------------------------------------
# run_iteration offline seam-recorder harness (mirrors iter-72 / iter-113).
# Records the ORDERED event stream: ("stage", <name>) for each run_stage call and
# ("refresh",) for each refresh_directions_file call, plus every revert_repo call.
# --------------------------------------------------------------------------
class _Drive:
    def __init__(self, res, events, reverts):
        self.res = res
        self.events = events
        self.reverts = reverts

    @property
    def stages(self):
        return [e[1] for e in self.events if e[0] == "stage"]

    @property
    def refresh_count(self):
        return sum(1 for e in self.events if e[0] == "refresh")


def _base_patches(monkeypatch, events, reverts):
    def run_stage(cfg, iteration, stage, role_file, out_name, extra=""):
        events.append(("stage", stage))
        it_dir = _iter_dir(cfg, iteration)
        it_dir.mkdir(parents=True, exist_ok=True)
        out = it_dir / out_name
        out.write_text("\n".join(SHIP_LINES) + "\n")
        return True, out

    seq = [BASE, NEWHEAD]

    def head(cfg):
        return seq.pop(0) if len(seq) > 1 else seq[0]

    monkeypatch.setattr(foundry, "run_stage", run_stage)
    monkeypatch.setattr(foundry, "head_of_branch", head)
    monkeypatch.setattr(foundry, "power_state",
                        lambda: "Now drawing from 'AC Power'")
    monkeypatch.setattr(foundry, "revert_repo",
                        lambda *a, **k: reverts.append(a))
    monkeypatch.setattr(
        foundry, "postrelease_step",
        lambda *a, **k: foundry.PostReleaseResult(True, False, POST_SENTINEL))
    monkeypatch.setattr(foundry, "next_iteration", lambda *a, **k: 116)
    monkeypatch.setattr(foundry, "log", lambda *a, **k: None)


def _drive(cfg, monkeypatch, iteration, *, scouted=None, refresh_ret=True,
           refresh=None):
    """Drive one offline iteration through the DEFAULT fixed pipeline (manifest
    absent). `scouted`: None -> use the REAL iteration_is_scouted (live wiring);
    True/False -> patch it. `refresh`: None -> a recorder returning refresh_ret;
    else the supplied callable is installed as refresh_directions_file."""
    events, reverts = [], []
    _base_patches(monkeypatch, events, reverts)
    if scouted is not None:
        monkeypatch.setattr(foundry, "iteration_is_scouted",
                            lambda c, n, _v=scouted: _v)
    if refresh is None:
        def refresh(c):
            events.append(("refresh",))
            return refresh_ret
    monkeypatch.setattr(foundry, "refresh_directions_file", refresh)
    res = foundry.run_iteration(cfg, iteration)
    return _Drive(res, events, reverts)


# ==========================================================================
# Behavior 1 -- render_directions_doc: header + full digest.render(); total.
# ==========================================================================
def test_b01_doc_contains_header_and_full_render_body():
    d = _digest((_entry(),))
    doc = foundry.render_directions_doc(d)
    assert isinstance(doc, str)
    assert "# Foundry directions" in doc
    assert d.render() in doc


def test_b01_doc_empty_digest_has_header_and_empty_sentinel():
    d = _digest(())
    doc = foundry.render_directions_doc(d)
    assert "# Foundry directions" in doc
    assert "no scouted iterations yet" in doc
    assert d.render() in doc


def test_b01_doc_never_raises_across_digests():
    for entries in ((), (_entry(),), (_entry(), _entry(iteration=2))):
        out = foundry.render_directions_doc(_digest(entries))
        assert isinstance(out, str) and "# Foundry directions" in out


# ==========================================================================
# Behavior 2 -- header title strictly BEFORE the rendered body line.
# ==========================================================================
def test_b02_header_strictly_before_render_body_line():
    for entries in ((), (_entry(),)):
        doc = foundry.render_directions_doc(_digest(entries))
        hi = doc.index("# Foundry directions")
        bi = doc.index("foundry directions -- ")
        assert hi < bi, "header must appear before the rendered body"


# ==========================================================================
# Behavior 3 -- deterministic: equal digests -> byte-identical output.
# ==========================================================================
def test_b03_deterministic_for_equal_digests():
    a = _digest((_entry(), _entry(iteration=2)))
    b = _digest((_entry(), _entry(iteration=2)))
    assert a == b  # equal DirectionsDigests
    assert foundry.render_directions_doc(a) == foundry.render_directions_doc(b)
    # empty case too
    assert foundry.render_directions_doc(_digest()) == \
        foundry.render_directions_doc(_digest())


# ==========================================================================
# Behavior 4 -- iteration_is_scouted(cfg, n).
# ==========================================================================
def test_b04_true_when_scout_a_exists(tmp_path):
    cfg = _cfg(tmp_path)
    d = _iter_dir(cfg, 7)
    d.mkdir(parents=True)
    (d / "pm_scout_a.md").write_text("# scout a")
    assert foundry.iteration_is_scouted(cfg, 7) is True


def test_b04_true_when_only_scout_b_exists(tmp_path):
    cfg = _cfg(tmp_path)
    d = _iter_dir(cfg, 3)
    d.mkdir(parents=True)
    (d / "pm_scout_b.md").write_text("# scout b")
    assert foundry.iteration_is_scouted(cfg, 3) is True


def test_b04_false_when_neither_scout_present(tmp_path):
    cfg = _cfg(tmp_path)
    d = _iter_dir(cfg, 4)
    d.mkdir(parents=True)
    (d / "pm.md").write_text("# pm only")
    assert foundry.iteration_is_scouted(cfg, 4) is False


def test_b04_false_when_iter_dir_absent(tmp_path):
    cfg = _cfg(tmp_path)
    # never create iter-09/ at all
    assert foundry.iteration_is_scouted(cfg, 9) is False


def test_b04_never_raises_on_missing_state(tmp_path):
    cfg = _cfg(tmp_path)
    import shutil
    shutil.rmtree(cfg.state, ignore_errors=True)
    assert foundry.iteration_is_scouted(cfg, 1) is False


def test_b04_two_digit_zero_pad_matches_gather(tmp_path):
    cfg = _cfg(tmp_path)
    # zero-padded single-digit dir name (iter-05), matching gather_directions.
    d = _iter_dir(cfg, 5)
    assert d.name == "iter-05"
    d.mkdir(parents=True)
    (d / "pm_scout_a.md").write_text("x")
    assert foundry.iteration_is_scouted(cfg, 5) is True


# ==========================================================================
# Behavior 5 -- refresh writes <repo>/DIRECTIONS.md == render(gather); True.
# ==========================================================================
def test_b05_writes_repo_root_directions_md_and_returns_true(tmp_path):
    cfg = _cfg(tmp_path)
    # seed one scouted iteration so the digest is non-trivial
    d = _iter_dir(cfg, 3)
    d.mkdir(parents=True)
    (d / "pm_scout_a.md").write_text(
        f"# PM_SCOUT_A {EMDASH} iteration 3 {EMDASH} lens: cap\n## Candidate C1 -- x\n")
    (d / "pm.md").write_text("## Triage\nPick: C1\n")
    (d / "final.md").write_text("ACTION: PUSHED s3\n")
    ret = foundry.refresh_directions_file(cfg)
    assert ret is True
    target = pathlib.Path(cfg.repo) / "DIRECTIONS.md"
    assert target.exists()
    expected = foundry.render_directions_doc(foundry.gather_directions(cfg))
    assert target.read_text() == expected


# ==========================================================================
# Behavior 6 -- refresh resolves gather_directions AND render_directions_doc by
#               BARE module name (monkeypatch bites the bytes written).
# ==========================================================================
def test_b06_render_monkeypatch_bites(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(foundry, "render_directions_doc", lambda dg: "PATCHED-DOC")
    assert foundry.refresh_directions_file(cfg) is True
    assert (pathlib.Path(cfg.repo) / "DIRECTIONS.md").read_text() == "PATCHED-DOC"


def test_b06_gather_monkeypatch_bites(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(foundry, "gather_directions", lambda c: "SENTINEL_DIGEST")
    monkeypatch.setattr(foundry, "render_directions_doc",
                        lambda dg: "GOT:" + str(dg))
    assert foundry.refresh_directions_file(cfg) is True
    assert (pathlib.Path(cfg.repo) / "DIRECTIONS.md").read_text() == "GOT:SENTINEL_DIGEST"


# ==========================================================================
# Behavior 7 -- SWALLOW-SAFE: a raise in gather/render -> returns False, no
#               propagation, pre-existing file unchanged, no file when absent.
# ==========================================================================
def test_b07_gather_raise_returns_false_and_writes_nothing_when_absent(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(foundry, "gather_directions", _boom)
    assert foundry.refresh_directions_file(cfg) is False
    assert not (pathlib.Path(cfg.repo) / "DIRECTIONS.md").exists()


def test_b07_render_raise_returns_false_and_leaves_preexisting_unchanged(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    target = pathlib.Path(cfg.repo) / "DIRECTIONS.md"
    target.write_text("PRE-EXISTING")
    monkeypatch.setattr(foundry, "render_directions_doc", _boom)
    assert foundry.refresh_directions_file(cfg) is False
    assert target.read_text() == "PRE-EXISTING"


# ==========================================================================
# Behavior 8 -- touches ONLY DIRECTIONS.md at the repo root.
# ==========================================================================
def test_b08_only_directions_md_created_at_repo_root(tmp_path):
    cfg = _cfg(tmp_path)
    repo = pathlib.Path(cfg.repo)
    before = _snapshot_tree(repo)
    assert before == {}
    foundry.refresh_directions_file(cfg)
    after = _snapshot_tree(repo)
    assert list(after.keys()) == ["DIRECTIONS.md"], after


# ==========================================================================
# Behavior 9 -- idempotent: two consecutive calls -> byte-identical file.
# ==========================================================================
def test_b09_idempotent(tmp_path):
    cfg = _cfg(tmp_path)
    d = _iter_dir(cfg, 2)
    d.mkdir(parents=True)
    (d / "pm_scout_a.md").write_text(
        f"# PM_SCOUT_A {EMDASH} iteration 2 {EMDASH} lens: cap\n")
    target = pathlib.Path(cfg.repo) / "DIRECTIONS.md"
    foundry.refresh_directions_file(cfg)
    first = target.read_bytes()
    foundry.refresh_directions_file(cfg)
    assert target.read_bytes() == first


# ==========================================================================
# Behavior 10 -- run_iteration invokes refresh_directions_file exactly ONCE on a
#                SCOUTED iteration, recorded BEFORE the final stage.
# ==========================================================================
def test_b10_refresh_once_before_final_on_scouted_patched(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    d = _drive(cfg, monkeypatch, 116, scouted=True)
    assert d.stages == DEFAULT_STAGES
    assert d.refresh_count == 1
    ri = d.events.index(("refresh",))
    fi = d.events.index(("stage", "final"))
    assert ri < fi, f"refresh must precede the final stage: {d.events}"
    assert set(d.res) == SHIP_KEYS and d.res["status"] == "shipped"
    assert d.reverts == []


def test_b10_refresh_wiring_live_with_real_scout_file(tmp_path, monkeypatch):
    """Strongest wiring proof: use the REAL iteration_is_scouted (scouted=None)
    with a pre-seeded pm_scout_a.md so run_iteration's own guard fires."""
    cfg = _cfg(tmp_path)
    d = _iter_dir(cfg, 116)
    d.mkdir(parents=True)
    (d / "pm_scout_a.md").write_text("# scout")
    drv = _drive(cfg, monkeypatch, 116, scouted=None)
    assert drv.refresh_count == 1
    assert drv.events.index(("refresh",)) < drv.events.index(("stage", "final"))


# ==========================================================================
# Behavior 11 -- NO refresh on a scout-less iteration; stage sequence unchanged
#                (disabled path byte-identical).
# ==========================================================================
def test_b11_no_refresh_on_scoutless_patched(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    d = _drive(cfg, monkeypatch, 116, scouted=False)
    assert d.refresh_count == 0
    assert d.stages == DEFAULT_STAGES
    assert set(d.res) == SHIP_KEYS and d.res["status"] == "shipped"


def test_b11_no_refresh_live_without_scout_files(tmp_path, monkeypatch):
    """Real iteration_is_scouted with NO scout file present -> no refresh."""
    cfg = _cfg(tmp_path)
    drv = _drive(cfg, monkeypatch, 116, scouted=None)
    assert drv.refresh_count == 0
    assert drv.stages == DEFAULT_STAGES


# ==========================================================================
# Behavior 12 -- a refresh failure never changes run_iteration's outcome: status
#                and the (non-)call to revert_repo are identical whether refresh
#                succeeds or returns False; the refresh is off the gate/revert path.
# ==========================================================================
def test_b12_refresh_return_value_off_gate_and_revert_path(tmp_path, monkeypatch):
    cfg_ok = _cfg(tmp_path / "ok")
    ok = _drive(cfg_ok, monkeypatch, 116, scouted=True, refresh_ret=True)
    monkeypatch.undo()
    cfg_bad = _cfg(tmp_path / "bad")
    bad = _drive(cfg_bad, monkeypatch, 116, scouted=True, refresh_ret=False)
    assert ok.res == bad.res
    assert ok.reverts == bad.reverts == []
    assert ok.stages == bad.stages == DEFAULT_STAGES


def test_b12_real_refresh_swallows_internal_raise_no_outcome_change(tmp_path, monkeypatch):
    """Use the REAL refresh_directions_file (unpatched, swallow-safe per B7): a
    raise in its internal gather_directions returns False and must not change
    run_iteration's status or revert behaviour vs a successful refresh."""
    # success run: real refresh, real gather
    cfg_ok = _cfg(tmp_path / "ok")
    events_ok, reverts_ok = [], []
    _base_patches(monkeypatch, events_ok, reverts_ok)
    monkeypatch.setattr(foundry, "iteration_is_scouted", lambda c, n: True)
    res_ok = foundry.run_iteration(cfg_ok, 116)
    monkeypatch.undo()
    # failure run: real refresh, gather patched to raise (refresh swallows -> False)
    cfg_bad = _cfg(tmp_path / "bad")
    events_bad, reverts_bad = [], []
    _base_patches(monkeypatch, events_bad, reverts_bad)
    monkeypatch.setattr(foundry, "iteration_is_scouted", lambda c, n: True)
    monkeypatch.setattr(foundry, "gather_directions", _boom)
    res_bad = foundry.run_iteration(cfg_bad, 116)
    assert res_ok == res_bad
    assert reverts_ok == reverts_bad == []


# ==========================================================================
# Wiring proof + dormancy of the NEW symbols on the dispatcher + import safety.
# ==========================================================================
def test_wiring_run_iteration_references_new_symbols():
    names = _fn_names_deep(foundry.run_iteration)
    assert "iteration_is_scouted" in names, \
        "run_iteration must reference iteration_is_scouted (bite-4b guard)"
    assert "refresh_directions_file" in names, \
        "run_iteration must reference refresh_directions_file (bite-4b guard)"


def test_new_symbols_absent_from_dispatcher():
    for sym in ("render_directions_doc", "iteration_is_scouted",
                "refresh_directions_file"):
        assert not hasattr(dispatcher, sym), f"dispatcher must not expose {sym!r}"


def test_new_surface_present_and_callable():
    for s in ("render_directions_doc", "iteration_is_scouted",
              "refresh_directions_file", "gather_directions",
              "render_directions_doc"):
        assert callable(getattr(foundry, s)), f"foundry.{s} missing/not callable"
    # bite-4a cores reused unchanged
    assert hasattr(foundry, "DirectionsEntry") and hasattr(foundry, "DirectionsDigest")


def test_fresh_subprocess_import_ok():
    root = str(pathlib.Path(__file__).resolve().parents[1])
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, f"`import foundry, dispatcher` failed:\n{r.stderr}"


def test_this_test_file_is_ascii():
    ttext = pathlib.Path(__file__).resolve().read_text(encoding="utf-8")
    assert [(i, c) for i, c in enumerate(ttext) if ord(c) >= 128] == []
