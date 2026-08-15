"""Black-box behaviour tests for iter 99 -- `foundry agents --json`: a read-only,
machine-readable JSON envelope of a product's rendered AGENTS.md house-rules doc
(title + banner + the bounded learnings digest), on a NEW dormant frozen value
object `AgentsView` + a NEW pure function `agents_view(learnings_text,
product_name, recent=12)` + an `as_json` flag on the existing `agents_cli`. The
wired `render_agents_md` renderer is NOT modified; the human default-write and
`--print` paths keep calling it verbatim.

`agents` was the ONE remaining flagless read-only CLI, and the only one that
WRITES a file by default. The clean resolution: the `--json` branch is checked
BEFORE the render, BEFORE the default write, and BEFORE `--print`, so `--json`
is pure read-only observability -- it prints the 2-key JSON, returns 0, and
never writes AGENTS.md nor creates the repo dir. Like `learnings --json` this
CLI is EXIT-0-ALWAYS in every mode: there is NO 0/1/2 exit shape and no error
path, even when `cfg.learnings` is absent (defensive read -> empty-text
placeholder digest).

The value object is the FIRST str-only view of the whole `--json` cadence: two
plain-`str` stored fields `product_name` then `doc`, NO str-list/tuple bucket,
NO derived properties -> the 2-key to_dict is ["product_name", "doc"], and
`json.loads(json.dumps(d)) == d` holds DIRECTLY (no `list(...)` coercion, unlike
iters 95-98's tuple buckets).

ISOLATION CONTRACT (honored): this file was written from the PM spec (Expected
Behaviors 1-18) and the product's own OBSERVABLE behaviour only (running it),
plus the pre-existing agents/render core test file under tests/
(test_iter09_behavior.py). The implementation source (foundry.py internals), the
engineer's and reviewer's notes, and `git diff` (and `git show HEAD:foundry.py`)
were NOT read. Every check drives the PUBLIC interface: the pure core via
`foundry.agents_view(...)` + `AgentsView.to_dict`, parity against the public
`foundry.render_agents_md(...)` oracle (byte-unchanged this iteration), and the
CLI via `foundry.agents_cli` / `foundry.main(["agents", ...])` against a TMP
config whose repo + learnings live under a temp dir (the real foundry repo is
NEVER touched). The dormancy proof uses only public runtime introspection --
compiled function name tables (`co_names` recursed via `_co_names_deep`) of the
five orchestrators plus a deep scan of the `dispatcher` module -- never a source
read, never `git diff`. Behavior 8 uses ASCII-safe substrings only (the runtime
title carries an em-dash that is deliberately NOT hardcoded). Fully offline and
deterministic: real temp files only, no subprocess/git/network (except the fresh
import + `--help` regression probes). There is deliberately NO
`git diff --quiet HEAD` control-path guard here (the iter-86 fix removed that
over-broad freeze anti-pattern).
"""
import dataclasses
import inspect
import json
import pathlib
import sys
import types

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402


# --------------------------------------------------------------------------
# helpers -- config points at a TMP repo + TMP work_root so the `agents`
# command can never write into the real foundry repo.
# --------------------------------------------------------------------------
def _write_cfg(tmp_path, **over):
    pathlib.Path(tmp_path).mkdir(parents=True, exist_ok=True)
    data = {
        "name": "demoprod",
        "repo": str(tmp_path / "repo"),
        "allowed_push_repo": "demoprod",
        "vision": str(tmp_path / "VISION.md"),
        "work_root": str(tmp_path / "work"),
    }
    data.update(over)
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data))
    return p


def _cfg_with_learnings(tmp_path, file_text, **over):
    """Load a config + seed cfg.learnings (under work_root) with text."""
    cfg = foundry.load_config(str(_write_cfg(tmp_path, **over)))
    lp = pathlib.Path(cfg.learnings)
    lp.parent.mkdir(parents=True, exist_ok=True)
    lp.write_text(file_text)
    return cfg


def _learnings_text(n_lessons, *patterns):
    """A realistic LEARNINGS.md: patterns head + chronological lessons tail."""
    pats = patterns or ("a durable rule",)
    head = ["## Patterns", "", "Read the head first; the tail is the history.", ""]
    head += [f"- {b}" for b in pats]
    tail = "\n".join(f"- [ENG iter{i:02d}] UNIQMARK-{i:03d} durable detail" for i in range(1, n_lessons + 1))
    return "\n".join(head) + "\n\n## Chronological lessons\n\n" + tail + "\n"


def _co_names_deep(code):
    """All global names referenced by a code object, recursing nested code."""
    names = set(code.co_names)
    for c in code.co_consts:
        if isinstance(c, types.CodeType):
            names |= _co_names_deep(c)
    return names


def _module_deep_names(mod):
    """Union of co_names over every function/method code object in a module."""
    names = set()
    for obj in vars(mod).values():
        code = getattr(obj, "__code__", None)
        if code is not None:
            names |= _co_names_deep(code)
        if isinstance(obj, type):
            for m in vars(obj).values():
                c = getattr(m, "__code__", None)
                if c is not None:
                    names |= _co_names_deep(c)
    return names


def _json_lines_all_structural(text):
    """Every non-blank line, stripped, begins with a JSON-structural char."""
    return all(ln.strip()[0] in '{}[]"' for ln in text.splitlines() if ln.strip())


RICH = _learnings_text(6, "pattern alpha", "pattern beta")


# ==========================================================================
# A. Value object AgentsView (Behaviors 1-5)
# ==========================================================================

# --- Behavior 1 -- frozen dataclass, EXACTLY two stored fields, NO props ---
def test_b01_agentsview_frozen_two_fields_no_props():
    AV = foundry.AgentsView
    assert dataclasses.is_dataclass(AV)
    assert AV.__dataclass_params__.frozen is True, "AgentsView must be frozen"
    assert [f.name for f in dataclasses.fields(AV)] == ["product_name", "doc"], (
        "stored fields must be exactly product_name then doc, in that order"
    )
    props = [n for n, v in vars(AV).items() if isinstance(v, property)]
    assert props == [], f"AgentsView must have NO properties, found {props!r}"


def test_b01_frozen_is_immutable():
    v = foundry.AgentsView(product_name="p", doc="d")
    with pytest.raises(dataclasses.FrozenInstanceError):
        v.product_name = "other"


# --- Behavior 2 -- to_dict key order + verbatim str values -----------------
def test_b02_to_dict_key_order_and_verbatim_str():
    v = foundry.AgentsView(product_name="MyProd", doc="# MyProd\n\nbody line\n")
    d = v.to_dict()
    assert isinstance(d, dict)
    assert list(d.keys()) == ["product_name", "doc"], (
        f"to_dict key ORDER must be [product_name, doc], got {list(d.keys())!r}"
    )
    assert d["product_name"] == v.product_name and d["doc"] == v.doc, "values not verbatim"
    assert type(d["product_name"]) is str and type(d["doc"]) is str, "both values must be str"


def test_b02_no_tuple_coercion_needed():
    # First str-only view of the cadence: values emitted verbatim, not wrapped.
    v = foundry.AgentsView(product_name="p", doc="d")
    d = v.to_dict()
    assert d["product_name"] is v.product_name or d["product_name"] == v.product_name
    assert d["doc"] == v.doc


# --- Behavior 3 -- no exit_code (no error exit) ----------------------------
def test_b03_no_exit_code():
    AV = foundry.AgentsView
    assert not hasattr(AV, "exit_code"), "AgentsView must NOT expose exit_code"
    d = AV(product_name="p", doc="d").to_dict()
    assert "exit_code" not in d, "to_dict must NOT carry an exit_code key"


# --- Behavior 4 -- JSON round-trip holds DIRECTLY --------------------------
def test_b04_json_roundtrip_direct():
    views = [
        foundry.AgentsView(product_name="p", doc="d"),
        foundry.AgentsView(product_name="", doc=""),
        # a real rendered doc: multi-line, and (at runtime) carries a unicode
        # em-dash in the title -- ensure_ascii round-trip must still hold.
        foundry.agents_view(RICH, "RoundTripProd", recent=4),
        foundry.agents_view("", "EmptyRT"),
    ]
    for v in views:
        d = v.to_dict()
        assert json.loads(json.dumps(d)) == d, "to_dict does not round-trip through JSON"


# --- Behavior 5 -- fresh dict per call; mutation isolated ------------------
def test_b05_to_dict_fresh_and_mutation_isolated():
    v = foundry.agents_view(RICH, "FreshProd")
    a = v.to_dict()
    b = v.to_dict()
    assert a == b and a is not b, "two to_dict calls must be equal but distinct objects"
    a["product_name"] = "MUTATED"
    a["doc"] = "MUTATED"
    assert v.to_dict()["product_name"] == "FreshProd", "mutating a returned dict changed the view"
    assert v.to_dict() == b, "mutating one dict must not affect a later to_dict()"


# ==========================================================================
# B. Pure function agents_view (Behaviors 6-8)
# ==========================================================================

# --- Behavior 6 -- signature + .doc == render_agents_md byte-for-byte ------
def test_b06_agents_view_signature():
    params = inspect.signature(foundry.agents_view).parameters
    assert list(params) == ["learnings_text", "product_name", "recent"], (
        f"agents_view signature params wrong: {list(params)!r}"
    )
    assert params["recent"].default == 12, "recent default must be 12"


def test_b06_doc_equals_render_oracle_and_name_verbatim():
    cases = [(RICH, "NameA", 12), ("", "EmptyP", 12), (RICH, "NameB", 3)]
    for text, name, recent in cases:
        av = foundry.agents_view(text, name, recent=recent)
        assert av.doc == foundry.render_agents_md(text, name, recent=recent), (
            f"agents_view(...,recent={recent}).doc != render_agents_md oracle (byte mismatch)"
        )
        assert av.product_name == name, "product_name not carried verbatim"
        assert av.doc.encode("utf-8") == foundry.render_agents_md(text, name, recent=recent).encode("utf-8")


# --- Behavior 7 -- pure + writes nothing -----------------------------------
def test_b07_agents_view_pure_deterministic():
    a = foundry.agents_view(RICH, "PureProd", recent=5)
    b = foundry.agents_view(RICH, "PureProd", recent=5)
    assert isinstance(a, foundry.AgentsView)
    assert a.doc == b.doc and a.product_name == b.product_name, "agents_view is not deterministic"


def test_b07_agents_view_writes_nothing(tmp_path, monkeypatch):
    empty = tmp_path / "emptycwd"
    empty.mkdir()
    monkeypatch.chdir(empty)
    foundry.agents_view(RICH, "NoFileProd", recent=4)
    assert list(empty.iterdir()) == [], "agents_view created a file in the cwd (must be pure)"


# --- Behavior 8 -- empty learnings -> stable placeholder doc ---------------
def test_b08_empty_learnings_placeholder_ascii_safe():
    doc = foundry.agents_view("", "demo").doc
    assert doc.startswith("# demo"), f"doc must start with '# demo', got {doc[:20]!r}"
    assert "house rules for agents" in doc, "banner substring missing"
    assert "(none recorded yet)" in doc, "empty-text placeholder digest missing"


# ==========================================================================
# C. CLI agents_cli / foundry.main (Behaviors 9-18)
# ==========================================================================

# --- Behavior 9 -- agents_cli signature + defaults -------------------------
def test_b09_agents_cli_signature_defaults():
    params = inspect.signature(foundry.agents_cli).parameters
    assert list(params) == ["cfg", "recent", "print_only", "as_json", "force"], (
        f"agents_cli signature params wrong: {list(params)!r}"
    )
    assert params["recent"].default == 12
    assert params["print_only"].default is False
    assert params["as_json"].default is False
    # iter 182: the non-destructive default is the SAFE one, so `force` must
    # opt IN. A default of True would silently restore the clobbering write.
    assert params["force"].default is False


# --- Behavior 10 -- as_json prints exact json.dumps + newline, rc 0 --------
def test_b10_json_exact_output_and_parse(tmp_path, capsys):
    cfg = _cfg_with_learnings(tmp_path, RICH)
    rc = foundry.agents_cli(cfg, as_json=True)
    out = capsys.readouterr().out
    assert rc == 0, f"as_json returned {rc!r}, expected 0"
    expected = json.dumps(foundry.agents_view(RICH, cfg.name, recent=12).to_dict(), indent=2) + "\n"
    assert out == expected, "as_json stdout is not exactly json.dumps(view.to_dict(), indent=2) + newline"
    parsed = json.loads(out)
    assert list(parsed.keys()) == ["product_name", "doc"]
    assert parsed["product_name"] == cfg.name
    assert parsed["doc"] == foundry.render_agents_md(RICH, cfg.name, recent=12)


def test_b10_json_recent_passthrough(tmp_path, capsys):
    cfg = _cfg_with_learnings(tmp_path, RICH)
    foundry.agents_cli(cfg, recent=3, as_json=True)
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["doc"] == foundry.render_agents_md(RICH, cfg.name, recent=3)


# --- Behavior 11 -- as_json WRITES NO FILE; overrides default write --------
def test_b11_json_writes_no_file(tmp_path, monkeypatch, capsys):
    nonexist = tmp_path / "no" / "such" / "repo"
    cfg = _cfg_with_learnings(tmp_path, RICH, repo=str(nonexist))
    assert not nonexist.exists(), "precondition: repo dir must not exist"
    empty = tmp_path / "cwd"
    empty.mkdir()
    monkeypatch.chdir(empty)

    rc = foundry.agents_cli(cfg, as_json=True)
    out = capsys.readouterr().out
    assert rc == 0
    assert not (nonexist / "AGENTS.md").exists(), "--json wrote AGENTS.md (must not)"
    assert not nonexist.exists(), "--json created the repo dir (must not)"
    assert list(empty.iterdir()) == [], "--json created a file in the cwd (must not)"
    assert json.loads(out)["product_name"] == cfg.name, "stdout is the only product"


# --- Behavior 12 -- --json overrides --print -------------------------------
def test_b12_json_overrides_print(tmp_path, monkeypatch, capsys):
    nonexist = tmp_path / "no" / "repo"
    cfg = _cfg_with_learnings(tmp_path, RICH, repo=str(nonexist))
    empty = tmp_path / "cwd"
    empty.mkdir()
    monkeypatch.chdir(empty)

    rc = foundry.agents_cli(cfg, print_only=True, as_json=True)
    out = capsys.readouterr().out
    assert rc == 0
    parsed = json.loads(out)  # must be valid JSON, not raw markdown
    assert list(parsed.keys()) == ["product_name", "doc"]
    # the raw human markdown (title line) must NOT be emitted as a bare doc
    assert not out.lstrip().startswith("# "), "--json+--print leaked the raw markdown title"
    assert not (nonexist / "AGENTS.md").exists() and not nonexist.exists(), "wrote a file"


# --- Behavior 13 -- default mode still WRITES AGENTS.md (oracle) -----------
def test_b13_default_writes_agents_md_oracle(tmp_path, capsys):
    cfg = _cfg_with_learnings(tmp_path, RICH)
    am = pathlib.Path(cfg.repo) / "AGENTS.md"
    assert not am.exists(), "precondition"
    rc = foundry.agents_cli(cfg)
    capsys.readouterr()
    assert rc == 0
    assert am.exists(), "default mode did not write <cfg.repo>/AGENTS.md"
    assert am.read_text() == foundry.render_agents_md(RICH, cfg.name, recent=12), (
        "written AGENTS.md != render_agents_md(text, name, 12) oracle"
    )


def test_b13_default_recent_passthrough(tmp_path, capsys):
    cfg = _cfg_with_learnings(tmp_path, RICH)
    am = pathlib.Path(cfg.repo) / "AGENTS.md"
    rc = foundry.agents_cli(cfg, recent=3)
    capsys.readouterr()
    assert rc == 0
    assert am.read_text() == foundry.render_agents_md(RICH, cfg.name, recent=3)


# --- Behavior 14 -- --print prints render + newline, no file ---------------
def test_b14_print_mode_render_plus_newline_no_file(tmp_path, capsys):
    cfg = _cfg_with_learnings(tmp_path, RICH)
    am = pathlib.Path(cfg.repo) / "AGENTS.md"
    rc = foundry.agents_cli(cfg, print_only=True)
    out = capsys.readouterr().out
    assert rc == 0
    assert out == foundry.render_agents_md(RICH, cfg.name, recent=12) + "\n", (
        "--print stdout is not exactly the rendered doc + a single trailing newline"
    )
    assert not am.exists(), "--print wrote a file (must not)"


# --- Behavior 15 -- rc 0 in ALL modes incl. missing learnings (no 0/1/2) ---
def test_b15_rc_zero_all_modes_missing_learnings(tmp_path, capsys):
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))
    assert not pathlib.Path(cfg.learnings).exists(), "learnings file must be absent"
    # json
    assert foundry.agents_cli(cfg, as_json=True) == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["product_name"] == cfg.name
    assert "(none recorded yet)" in parsed["doc"], "missing learnings -> placeholder digest"
    # print
    assert foundry.agents_cli(cfg, print_only=True) == 0
    capsys.readouterr()
    # default write
    assert foundry.agents_cli(cfg) == 0
    assert (pathlib.Path(cfg.repo) / "AGENTS.md").exists()


# --- Behavior 16 -- as_json has NO human-doc line leak (armed complement) --
def test_b16_json_no_human_line_leak_armed(tmp_path, capsys):
    cfg = _cfg_with_learnings(tmp_path, RICH)
    foundry.agents_cli(cfg, as_json=True)
    json_out = capsys.readouterr().out
    assert _json_lines_all_structural(json_out), (
        "as_json stdout leaked a non-JSON-structural line"
    )
    # ARM the check: the --print human render for the SAME input has >= 1
    # non-blank line whose stripped lead is NOT a JSON-structural char.
    foundry.agents_cli(cfg, print_only=True)
    human_out = capsys.readouterr().out
    assert not _json_lines_all_structural(human_out), (
        "complement not armed: the human render has no non-JSON-structural line"
    )
    leads = {ln.strip()[0] for ln in human_out.splitlines() if ln.strip()}
    assert "#" in leads, "the human title line should lead with '#'"


# --- Behavior 17 -- dispatch flag mapping via a spy ------------------------
def test_b17_dispatch_spy_flag_mapping(tmp_path, monkeypatch):
    cfg_path = str(_write_cfg(tmp_path))
    calls = []

    def spy(cfg, recent=12, print_only=False, as_json=False, force=False):
        calls.append({"recent": recent, "print_only": print_only,
                      "as_json": as_json, "force": force})
        return 0

    monkeypatch.setattr(foundry, "agents_cli", spy)
    assert foundry.main(["agents", "--config", cfg_path, "--json"]) == 0
    assert calls[-1]["as_json"] is True
    foundry.main(["agents", "--config", cfg_path])
    assert calls[-1]["as_json"] is False
    foundry.main(["agents", "--config", cfg_path, "--print"])
    assert calls[-1]["print_only"] is True
    foundry.main(["agents", "--config", cfg_path, "--recent", "7"])
    assert calls[-1]["recent"] == 7


def test_b17_missing_config_systemexit():
    with pytest.raises(SystemExit) as ei:
        foundry.main(["agents", "--json"])
    assert ei.value.code == 2, "omitting the required --config must raise SystemExit(2)"


# --- Behavior 18 -- e2e via foundry.main, dormancy, imports ----------------
def test_b18_e2e_main_three_modes(tmp_path, capsys):
    cfg = _cfg_with_learnings(tmp_path, RICH)
    cfg_path = str(tmp_path / "config.json")
    am = pathlib.Path(cfg.repo) / "AGENTS.md"

    # --json: exit 0, 2-key dict, no repo write
    rc = foundry.main(["agents", "--config", cfg_path, "--json"])
    parsed = json.loads(capsys.readouterr().out)
    assert rc == 0 and parsed["product_name"] == cfg.name
    assert not am.exists(), "--json e2e wrote AGENTS.md (must not)"

    # bare: exit 0, writes AGENTS.md
    rc = foundry.main(["agents", "--config", cfg_path])
    capsys.readouterr()
    assert rc == 0 and am.exists(), "bare e2e did not write AGENTS.md"

    # --print: exit 0, human doc to stdout
    rc = foundry.main(["agents", "--config", cfg_path, "--print"])
    out = capsys.readouterr().out
    assert rc == 0 and "house rules for agents" in out


def test_b18_dormancy_orchestrators_and_dispatcher():
    orchestrators = ["build_prompt", "run_stage", "run_iteration",
                     "run_continuous", "run_execution_plan"]
    for fn in orchestrators:
        names = _co_names_deep(getattr(foundry, fn).__code__)
        assert "agents_view" not in names, f"{fn} references agents_view (must be dormant)"
        assert "AgentsView" not in names, f"{fn} references AgentsView (must be dormant)"
    dnames = _module_deep_names(dispatcher)
    assert "agents_view" not in dnames and "AgentsView" not in dnames, (
        "dispatcher references the new symbols (must be dormant)"
    )
    assert not hasattr(dispatcher, "agents_view"), "dispatcher imported agents_view"
    assert not hasattr(dispatcher, "AgentsView"), "dispatcher imported AgentsView"


def test_b18_imports_ok():
    assert foundry is not None and dispatcher is not None
    assert callable(foundry.agents_view)
    assert callable(foundry.agents_cli)
    assert callable(foundry.render_agents_md)


def test_b18_help_lists_agents(capsys):
    with pytest.raises(SystemExit) as ei:
        foundry.main(["--help"])
    assert ei.value.code == 0
    assert "agents" in capsys.readouterr().out
