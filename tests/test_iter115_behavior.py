"""Black-box behaviour tests for iter 115 -- the read-only, offline, one-command
per-iteration DECISION LOG surface (`foundry directions`, discovery bite 4a),
ALL additive-dormant in foundry.py:

  * four PURE total parsers over committed state artifacts:
      - parse_scout_lens(text) -> str | None
      - parse_scout_candidates(text) -> tuple[str, ...]
      - parse_triage_winner(text) -> str | None
      - parse_ship_sha(text) -> str | None
  * a FROZEN dataclass DirectionsEntry(iteration, lenses, candidates, winner,
    action, sha) with a 6-key to_dict(),
  * a FROZEN dataclass DirectionsDigest(product, entries) with total/exit_code
    props + render() + a 4-key to_dict(),
  * a PURE keyword-only summarize_directions(*, product, entries),
  * an I/O seam gather_directions(cfg, limit=None),
  * a directions_cli(cfg, limit=None, as_json=False) -> int wired to a new
    argparse subcommand `directions`.

ISOLATION CONTRACT (HONORED as an original tester deliverable): this file was
written ONLY from the iter-115 PM spec's Expected Behaviors (1-15), the tests/
conventions (esp. tests/test_iter100_behavior.py, the `outcomes` template this
iteration mirrors), and the product's own OBSERVABLE behaviour by driving its
PUBLIC interface. Every check drives the public surface: the pure fns via
foundry.parse_scout_lens(...) etc., the frozen cores via
foundry.DirectionsEntry(...) / foundry.DirectionsDigest(...) /
foundry.summarize_directions(...), the seam via foundry.gather_directions(cfg)
against a TMP work_root config with real state/iter-NN/ files, and the CLI via
foundry.main(["directions", "--config", <cfg>]) / foundry.directions_cli(...).
The real foundry repo/state is NEVER touched. Dormancy (Behavior 15) uses only
public RUNTIME introspection (compiled co_names / co_consts + module attrs), not
the source text. Fully offline & deterministic: real temp files only; ZERO real
subprocess-for-work / git / network / clock (except the `import` regression
probe, which only imports the two modules).
"""
import dataclasses
import io
import json
import pathlib
import shutil
import subprocess
import sys
import types

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402


# em-dash constructed rather than embedded so the source stays pure-ASCII bytes.
EMDASH = "\u2014"


# --------------------------------------------------------------------------
# helpers  (mirror tests/test_iter100_behavior.py, the `outcomes` template)
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
    """Drive foundry.main capturing (rc, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = foundry.main(argv)
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue(), err.getvalue()


def _capture_stdout(fn, *args, **kw):
    """Run fn capturing ONLY stdout, returning (rc, stdout_text)."""
    out = io.StringIO()
    old = sys.stdout
    sys.stdout = out
    try:
        rc = fn(*args, **kw)
    finally:
        sys.stdout = old
    return rc, out.getvalue()


def _iter_dir(cfg, iteration):
    return pathlib.Path(cfg.state) / f"iter-{iteration:02d}"


def _write_iteration(cfg, iteration, *, lens_a=None, lens_b=None,
                     cands_a=(), cands_b=(), winner=None, action=None,
                     scout_a=True, scout_b=False, trailing_blanks=True):
    """Create a state/iter-NN/ dir with the requested artifacts.

    scout_a/scout_b toggle whether pm_scout_a.md / pm_scout_b.md EXIST (the
    SCOUTED gate). lens_*/cands_* fill each scout's title + candidate headings.
    winner (a bare id like "C1") is placed in a pm.md `## Triage` section.
    action ("PUSHED <sha>" / "REVERTED") becomes final.md's last sentinel line.
    Any None/False leaves that artifact / field absent.
    """
    d = _iter_dir(cfg, iteration)
    d.mkdir(parents=True, exist_ok=True)
    tail = "\n\n   \n\t\n" if trailing_blanks else ""

    def _scout_body(which, lens, cands):
        lines = []
        title = f"# PM_SCOUT_{which} {EMDASH} iteration {iteration}"
        if lens is not None:
            title += f" {EMDASH} lens: {lens}"
        lines.append(title)
        lines.append("")
        lines.append("## Slate")
        for c in cands:
            lines.append(f"## Candidate {c}")
        lines.append("")
        lines.append("## Note to the PM lead")
        lines.append("prose that must be ignored by the candidate parser")
        return "\n".join(lines) + "\n"

    if scout_a:
        (d / "pm_scout_a.md").write_text(_scout_body("A", lens_a, cands_a))
    if scout_b:
        (d / "pm_scout_b.md").write_text(_scout_body("B", lens_b, cands_b))
    if winner is not None:
        (d / "pm.md").write_text(
            f"# PM spec {EMDASH} iteration {iteration}\n\n"
            f"## Triage\n**Pick: {winner}** for reasons.\n\n"
            f"## Feature\nbody\n")
    if action is not None:
        (d / "final.md").write_text(f"final gate report\n\nACTION: {action}{tail}")
    return d


def _fn_names_consts(fn):
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
    "parse_scout_lens", "parse_scout_candidates", "parse_triage_winner",
    "parse_ship_sha", "DirectionsEntry", "DirectionsDigest",
    "summarize_directions", "gather_directions", "directions_cli",
)
ORCHESTRATORS = (
    "build_prompt", "run_stage", "run_iteration", "run_continuous",
)


# ==========================================================================
# A. parse_scout_lens(text) -> str | None                       (Behavior 1)
# ==========================================================================
def test_b01_lens_dashdash_title():
    t = "# PM_SCOUT_A -- iteration 115 -- lens: new-capability"
    assert foundry.parse_scout_lens(t) == "new-capability"


def test_b01_lens_emdash_title():
    t = f"# PM Scout B {EMDASH} iteration 115 {EMDASH} lens: hardening/DX"
    assert foundry.parse_scout_lens(t) == "hardening/DX"


def test_b01_lens_last_token_wins_on_same_line():
    t = "# title lens: foo -- lens: bar"
    assert foundry.parse_scout_lens(t) == "bar"


def test_b01_lens_case_insensitive_marker_preserves_value_case():
    t = "# Heading LENS: Mixed-Case-Value"
    assert foundry.parse_scout_lens(t) == "Mixed-Case-Value"


def test_b01_lens_uses_first_hash_heading_carrying_marker():
    body = "# first-heading no marker here\n# second lens: winner\n"
    assert foundry.parse_scout_lens(body) == "winner"


def test_b01_lens_none_when_empty_or_no_heading_or_no_marker_or_blank():
    assert foundry.parse_scout_lens("") is None
    assert foundry.parse_scout_lens("just prose\nmore prose") is None
    assert foundry.parse_scout_lens("# Title without the token\n\nbody") is None
    assert foundry.parse_scout_lens("# Title lens:   ") is None
    assert foundry.parse_scout_lens("# Title lens:") is None


def test_b01_lens_never_raises_on_adversarial_input():
    for bad in (None, "\x00\x01\x02", "#\n#\n#", "###", "lens: not-a-heading",
                "   \n\t\n", "#" * 5000):
        assert foundry.parse_scout_lens(bad) is None or isinstance(
            foundry.parse_scout_lens(bad), str)


# ==========================================================================
# B. parse_scout_candidates(text) -> tuple[str, ...]            (Behavior 2)
# ==========================================================================
def test_b02_candidates_in_file_order_hash_and_spaces_stripped():
    t = ("# title\n\n"
         "## Candidate C1 -- foundry directions: render decision log\n"
         "## Candidate C2 -- foundry init scaffolder\n")
    assert foundry.parse_scout_candidates(t) == (
        "Candidate C1 -- foundry directions: render decision log",
        "Candidate C2 -- foundry init scaffolder",
    )


def test_b02_candidates_case_insensitive_and_non_candidate_headings_skipped():
    t = ("## Slate\n"
         "## candidate lower one\n"
         "## Note to the PM lead\n"
         "## Candidate B1 upper two\n"
         "### Candidate not-a-double-hash\n")
    assert foundry.parse_scout_candidates(t) == (
        "candidate lower one", "Candidate B1 upper two")


def test_b02_candidates_empty_tuple_when_none_or_empty():
    assert foundry.parse_scout_candidates("") == ()
    assert foundry.parse_scout_candidates("# title\n## Note\nbody") == ()


def test_b02_candidates_never_raises_on_adversarial_input():
    for bad in (None, "\x00\x01", "## Candidate", "   ", "#" * 3000):
        r = foundry.parse_scout_candidates(bad)
        assert isinstance(r, tuple)


# ==========================================================================
# C. parse_triage_winner(text) -> str | None                   (Behavior 3)
# ==========================================================================
def test_b03_winner_first_id_after_triage_heading():
    t = ("# PM spec -- iteration 115\n\n"
         "## Triage\n**Pick: C1 (Scout A)** for sequencing reasons.\n\n"
         "## Feature\nbody mentioning A4 later\n")
    assert foundry.parse_triage_winner(t) == "C1"


def test_b03_winner_ignores_ids_before_the_triage_heading():
    t = ("Candidate A9 was rejected earlier in prose.\n"
         "## Triage\nPick: C1\n")
    assert foundry.parse_triage_winner(t) == "C1"


def test_b03_winner_none_without_heading_or_without_id():
    assert foundry.parse_triage_winner("no triage here\nPick: C1") is None
    assert foundry.parse_triage_winner("## Triage\nno id token at all") is None


def test_b03_winner_case_insensitive_heading():
    t = "## triage\nPick: B2\n"
    assert foundry.parse_triage_winner(t) == "B2"


def test_b03_winner_never_raises_on_adversarial_input():
    for bad in (None, "", "\x00## Triage\x00", "## Triage", "#" * 4000):
        r = foundry.parse_triage_winner(bad)
        assert r is None or isinstance(r, str)


# ==========================================================================
# D. parse_ship_sha(text) -> str | None                        (Behavior 4)
# ==========================================================================
def test_b04_sha_from_last_pushed_line():
    assert foundry.parse_ship_sha("ACTION: PUSHED abc123") == "abc123"


def test_b04_sha_trailing_blanks_and_prose_above_ignored():
    body = "final gate report\n\nACTION: PUSHED deadbeef\n\n   \n\t\n"
    assert foundry.parse_ship_sha(body) == "deadbeef"


def test_b04_sha_whitespace_tolerated():
    assert foundry.parse_ship_sha("   ACTION:   PUSHED   xyz789  ") == "xyz789"


def test_b04_sha_none_for_reverted_bare_pushed_and_non_last_action():
    assert foundry.parse_ship_sha("ACTION: REVERTED") is None
    assert foundry.parse_ship_sha("ACTION: PUSHED") is None
    assert foundry.parse_ship_sha("ACTION: PUSHED abc\nprose after") is None


def test_b04_sha_none_for_empty_or_unrecognized():
    assert foundry.parse_ship_sha("") is None
    assert foundry.parse_ship_sha("   \n\t\n") is None
    assert foundry.parse_ship_sha("random text with no action") is None


def test_b04_sha_never_raises_on_adversarial_input():
    for bad in (None, "\x00\x01\x02", "ACTION:", "#" * 2000):
        r = foundry.parse_ship_sha(bad)
        assert r is None or isinstance(r, str)


# ==========================================================================
# E. DirectionsEntry frozen + to_dict()                        (Behavior 5)
# ==========================================================================
def _entry(**over):
    base = dict(iteration=1, lenses=("l1",), candidates=("c1",),
                winner="C1", action="PUSHED", sha="abc")
    base.update(over)
    return foundry.DirectionsEntry(**base)


def test_b05_entry_is_frozen():
    e = _entry()
    with pytest.raises(dataclasses.FrozenInstanceError):
        e.iteration = 99


def test_b05_entry_to_dict_exactly_six_keys_in_declaration_order():
    e = _entry()
    d = e.to_dict()
    assert list(d.keys()) == [
        "iteration", "lenses", "candidates", "winner", "action", "sha"]
    assert d["lenses"] == ["l1"] and d["candidates"] == ["c1"]
    assert isinstance(d["lenses"], list) and isinstance(d["candidates"], list)


def test_b05_entry_to_dict_round_trips_json_including_nulls():
    e = _entry(winner=None, action=None, sha=None)
    rt = json.loads(json.dumps(e.to_dict()))
    assert rt["winner"] is None and rt["action"] is None and rt["sha"] is None
    assert rt == e.to_dict()


# ==========================================================================
# F. DirectionsDigest frozen + total/exit_code/to_dict         (Behavior 6)
# ==========================================================================
def test_b06_digest_total_and_exit_code():
    empty = foundry.DirectionsDigest(product="p", entries=())
    assert empty.total == 0 and empty.exit_code == 2
    one = foundry.DirectionsDigest(product="p", entries=(_entry(),))
    assert one.total == 1 and one.exit_code == 0


def test_b06_digest_is_frozen():
    d = foundry.DirectionsDigest(product="p", entries=())
    with pytest.raises(dataclasses.FrozenInstanceError):
        d.product = "q"


def test_b06_digest_to_dict_exact_keys_and_round_trip():
    d = foundry.DirectionsDigest(product="demoprod", entries=(_entry(), _entry(iteration=2)))
    dd = d.to_dict()
    assert list(dd.keys()) == ["product", "total", "exit_code", "entries"]
    assert dd["product"] == "demoprod" and dd["total"] == 2 and dd["exit_code"] == 0
    assert isinstance(dd["entries"], list) and len(dd["entries"]) == 2
    assert dd["entries"][0] == _entry().to_dict()
    assert json.loads(json.dumps(dd)) == dd


# ==========================================================================
# G. render()                                            (Behaviors 7-8)
# ==========================================================================
def test_b07_render_carries_all_required_substrings():
    e = foundry.DirectionsEntry(
        iteration=5,
        lenses=("new-capability", "hardening/DX"),
        candidates=("Candidate C1 -- alpha", "Candidate B1 -- beta"),
        winner="C1", action="PUSHED", sha="abc123")
    out = foundry.DirectionsDigest(product="demoprod", entries=(e,)).render()
    assert "foundry directions -- demoprod" in out
    assert "iter-05" in out
    assert "lenses: new-capability, hardening/DX" in out
    assert "Candidate C1 -- alpha" in out and "Candidate B1 -- beta" in out
    assert "winner: C1" in out
    assert "ship: PUSHED abc123" in out
    assert "1 scouted iterations" in out


def test_b07_render_ship_and_lens_and_winner_fallbacks():
    pushed_no_sha = foundry.DirectionsEntry(1, (), (), None, "PUSHED", None)
    reverted = foundry.DirectionsEntry(2, (), (), None, "REVERTED", None)
    unknown = foundry.DirectionsEntry(3, (), (), None, None, None)
    out = foundry.DirectionsDigest(
        product="p", entries=(pushed_no_sha, reverted, unknown)).render()
    assert "ship: PUSHED\n" in out or out.rstrip().endswith("ship: PUSHED")
    assert "ship: REVERTED" in out
    assert "ship: unknown" in out
    assert "lenses: unknown" in out
    assert "winner: unknown" in out
    assert "3 scouted iterations" in out


def test_b08_render_empty_digest_has_no_iterations_sentinel():
    out = foundry.DirectionsDigest(product="demoprod", entries=()).render()
    assert "foundry directions -- demoprod" in out
    assert "no scouted iterations yet" in out
    assert "0 scouted iterations" in out


def test_b07_render_zero_pad_two_digits():
    e = foundry.DirectionsEntry(7, (), (), None, None, None)
    out = foundry.DirectionsDigest(product="p", entries=(e,)).render()
    assert "iter-07" in out


# ==========================================================================
# H. summarize_directions(*, product, entries)                 (Behavior 9)
# ==========================================================================
def test_b09_summarize_is_keyword_only():
    with pytest.raises(TypeError):
        foundry.summarize_directions("p", [])


def test_b09_summarize_materializes_tuple_and_never_raises():
    it = iter([_entry(), _entry(iteration=2)])
    d = foundry.summarize_directions(product="p", entries=it)
    assert isinstance(d.entries, tuple) and d.total == 2 and d.product == "p"
    empty = foundry.summarize_directions(product="p", entries=[])
    assert empty.entries == () and empty.exit_code == 2


# ==========================================================================
# I. gather_directions(cfg, limit=None)               (Behaviors 10-12)
# ==========================================================================
def test_b10_gather_missing_state_yields_empty_digest(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    shutil.rmtree(cfg.state, ignore_errors=True)
    d = foundry.gather_directions(cfg)
    assert d.product == cfg.name and d.total == 0 and d.exit_code == 2


def test_b10_gather_keeps_only_scouted_iterations(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    # iter 1: scouted via scout_a only
    _write_iteration(cfg, 1, lens_a="lensA", scout_a=True, scout_b=False)
    # iter 2: NOT scouted -- only pm.md/final.md, no scout files
    _write_iteration(cfg, 2, scout_a=False, scout_b=False,
                     winner="C1", action="PUSHED x")
    # iter 3: scouted via scout_b only
    _write_iteration(cfg, 3, lens_b="lensB", scout_a=False, scout_b=True)
    d = foundry.gather_directions(cfg)
    kept = [e.iteration for e in d.entries]
    assert 2 not in kept
    assert sorted(kept) == [1, 3]


def test_b11_gather_builds_entry_from_all_artifacts(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_iteration(
        cfg, 5,
        lens_a="new-capability", lens_b="hardening/DX",
        cands_a=("C1 -- alpha", "C2 -- beta"), cands_b=("B1 -- gamma",),
        winner="C1", action="PUSHED sha5xyz",
        scout_a=True, scout_b=True)
    d = foundry.gather_directions(cfg)
    assert d.total == 1
    e = d.entries[0]
    assert e.iteration == 5
    assert e.lenses == ("new-capability", "hardening/DX")
    assert e.candidates == (
        "Candidate C1 -- alpha", "Candidate C2 -- beta", "Candidate B1 -- gamma")
    assert e.winner == "C1"
    assert e.action == "PUSHED"
    assert e.sha == "sha5xyz"


def test_b11_gather_omits_unparsed_lens(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    # scout_a has a lens, scout_b's title carries NO lens marker -> omitted.
    _write_iteration(cfg, 4, lens_a="onlyA", lens_b=None,
                     scout_a=True, scout_b=True)
    d = foundry.gather_directions(cfg)
    assert d.entries[0].lenses == ("onlyA",)


def test_b11_gather_uses_bare_name_parsers_so_monkeypatch_bites(tmp_path, monkeypatch):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_iteration(cfg, 6, lens_a="real", cands_a=("C1 -- x",),
                     winner="C1", action="PUSHED s6", scout_a=True, scout_b=True,
                     lens_b="realb")
    monkeypatch.setattr(foundry, "parse_triage_winner", lambda t: "ZZ")
    monkeypatch.setattr(foundry, "parse_scout_lens", lambda t: "PATCHED")
    d = foundry.gather_directions(cfg)
    e = d.entries[0]
    assert e.winner == "ZZ"
    assert e.lenses == ("PATCHED", "PATCHED")


def test_b12_gather_newest_first_and_limit(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    for n in (1, 2, 10):
        _write_iteration(cfg, n, lens_a=f"lens{n}", scout_a=True)
    d = foundry.gather_directions(cfg)
    assert [e.iteration for e in d.entries] == [10, 2, 1]
    assert [e.iteration for e in foundry.gather_directions(cfg, limit=1).entries] == [10]
    assert [e.iteration for e in foundry.gather_directions(cfg, limit=2).entries] == [10, 2]
    # None / non-positive -> all
    for lim in (None, 0, -3):
        assert [e.iteration for e in foundry.gather_directions(cfg, limit=lim).entries] == [10, 2, 1]


def test_b10_gather_never_raises_and_writes_nothing(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_iteration(cfg, 1, lens_a="lensA", scout_a=True)
    before = _snapshot_tree(cfg.state)
    foundry.gather_directions(cfg)
    assert _snapshot_tree(cfg.state) == before


# ==========================================================================
# J. directions_cli + main dispatch                   (Behaviors 13-14)
# ==========================================================================
def test_b13_cli_human_render_returns_exit_code_and_writes_nothing(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_iteration(cfg, 3, lens_a="cap", cands_a=("C1 -- z",),
                     winner="C1", action="PUSHED s3", scout_a=True)
    before = _snapshot_tree(pathlib.Path(cfg.work_root))
    rc, out = _capture_stdout(foundry.directions_cli, cfg)
    assert rc == 0
    assert "foundry directions -- demoprod" in out and "iter-03" in out
    assert _snapshot_tree(pathlib.Path(cfg.work_root)) == before


def test_b13_cli_json_is_single_document_matching_to_dict(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_iteration(cfg, 3, lens_a="cap", cands_a=("C1 -- z",),
                     winner="C1", action="PUSHED s3", scout_a=True)
    rc, out = _capture_stdout(foundry.directions_cli, cfg, as_json=True)
    payload = json.loads(out)  # a single JSON document -> no raise
    assert payload == foundry.gather_directions(cfg).to_dict()
    assert rc == 0


def test_b13_cli_empty_exits_2(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    rc, out = _capture_stdout(foundry.directions_cli, cfg)
    assert rc == 2 and "no scouted iterations yet" in out


def test_b14_main_dispatches_and_returns_exit_code(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_iteration(cfg, 1, lens_a="cap", scout_a=True)
    rc, out, _ = _run_cli(["directions", "--config", str(cfg_path)])
    assert rc == 0 and "iter-01" in out and "foundry directions -- demoprod" in out
    # empty -> exit 2
    shutil.rmtree(cfg.state, ignore_errors=True)
    pathlib.Path(cfg.state).mkdir(parents=True, exist_ok=True)
    rc2, out2, _ = _run_cli(["directions", "--config", str(cfg_path)])
    assert rc2 == 2


def test_b14_main_limit_and_json_passthrough_via_spy(tmp_path, monkeypatch):
    cfg_path = _write_cfg(tmp_path)
    captured = {}

    def spy(cfg, limit=None, as_json=False):
        captured["limit"] = limit
        captured["as_json"] = as_json
        return 0

    monkeypatch.setattr(foundry, "directions_cli", spy)
    _run_cli(["directions", "--config", str(cfg_path), "--limit", "7", "--json"])
    assert captured == {"limit": 7, "as_json": True}
    captured.clear()
    _run_cli(["directions", "--config", str(cfg_path)])
    assert captured == {"limit": None, "as_json": False}


def test_b14_main_config_required_systemexit2():
    with pytest.raises(SystemExit) as ei:
        foundry.main(["directions"])
    assert ei.value.code == 2


def test_b14_help_lists_directions_subcommand(capsys):
    with pytest.raises(SystemExit) as ei:
        foundry.main(["--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "directions" in out


# ==========================================================================
# K. Dormancy + import regression                              (Behavior 15)
# ==========================================================================
def test_b15_new_symbols_absent_from_orchestrators():
    for fn_name in ORCHESTRATORS:
        assert callable(getattr(foundry, fn_name)), \
            f"orchestrator foundry.{fn_name} missing (regression)"
        names, consts = _fn_names_consts(getattr(foundry, fn_name))
        for sym in NEW_SYMBOLS:
            assert sym not in names, \
                f"{fn_name} references new symbol {sym!r} (must stay off the control path)"
        assert "directions" not in consts, \
            f"{fn_name} contains the 'directions' subcommand literal"


def test_b15_new_symbols_absent_from_dispatcher():
    for sym in NEW_SYMBOLS:
        assert not hasattr(dispatcher, sym), f"dispatcher must not expose {sym!r}"
    names, consts = _module_names_consts(dispatcher)
    for sym in NEW_SYMBOLS:
        assert sym not in names, f"dispatcher references new symbol {sym!r}"


def test_b15_no_directions_md_written_anywhere(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    cfg = foundry.load_config(str(cfg_path))
    _write_iteration(cfg, 1, lens_a="cap", scout_a=True)
    foundry.gather_directions(cfg)
    _capture_stdout(foundry.directions_cli, cfg)
    _capture_stdout(foundry.directions_cli, cfg, as_json=True)
    leaked = list(pathlib.Path(cfg.work_root).rglob("DIRECTIONS.md"))
    assert leaked == [], f"no DIRECTIONS.md must be written this iteration: {leaked}"


def test_b15_both_modules_import():
    root = str(pathlib.Path(__file__).resolve().parents[1])
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, f"`import foundry, dispatcher` failed:\n{r.stderr}"


def test_b15_new_surface_present_and_callable():
    for s in ("parse_scout_lens", "parse_scout_candidates", "parse_triage_winner",
              "parse_ship_sha", "summarize_directions", "gather_directions",
              "directions_cli"):
        assert callable(getattr(foundry, s)), f"foundry.{s} missing/not callable"
    assert hasattr(foundry, "DirectionsEntry") and hasattr(foundry, "DirectionsDigest")
    # gather_directions reuses the existing ship-action parser for final.md
    assert callable(foundry.parse_ship_action)
