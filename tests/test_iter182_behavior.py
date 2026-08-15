"""Black-box behaviour tests for iter 182 -- `foundry agents` refuses to clobber a
hand-written `AGENTS.md`, `--force` overrides, and regenerating our OWN output is
still free (provenance, not difference).

Spec: products/_platform/state/iter-182/pm.md, Expected Behaviors 1-14.

  1.  `AGENTS_GENERATED_BANNER` is a non-empty `str` and EVERY `render_agents_md`
      output carries it verbatim (empty/rich text, several `recent` values, odd
      names). SINGLE SOURCE, proved two ways: (a) behaviourally -- rebinding the
      module constant changes BOTH the rendered doc and the refusal message, so
      neither holds a private copy; (b) mechanically -- no 3-word fragment of the
      banner occurs more than once in `foundry.py`.
  2.  `agents_doc_is_generated(text)` is PURE (no filesystem/subprocess/network/
      clock -- proved by poisoning `open`/`subprocess`/`time` AND by an AST scan
      with the docstring node removed), total, round-trips `render_agents_md` for
      two different `recent` values, and is False for "", a hand-written doc, and
      a decoy containing "auto-generated" but not the banner.
  3.  Target ABSENT -> default mode writes it, bytes == `render_agents_md(text,
      cfg.name, recent=recent)`, rc 0 (default `recent` and an explicit one).
  4.  Target PRESENT + banner-bearing + DIFFERENT from a fresh render -> default
      mode overwrites, bytes == fresh render, rc 0 (a refresh is the point).
  5.  Target PRESENT + no banner -> rc 2 and the file is BYTE-identical (bytes
      compared, not mtime); a zero-byte write.
  6.  The refusal names the target PATH, says the file looks hand-written / not
      foundry-generated, and contains the literal `--force`.
  7.  `force=True` overwrites a hand-written target with the fresh render, rc 0.
  8.  READ-ONLY modes never refuse and never write: `print_only` and `as_json`
      each return 0 against a hand-written target and leave it byte-identical;
      `as_json` outranks both the default write and `print_only`.
  9.  `agents_cli` signature is exactly ["cfg","recent","print_only","as_json",
      "force"]; `force` defaults to False, and 12/False/False are unchanged.
  10. CLI wiring: `--force` reaches `agents_cli` as `force=True` (spy), a bare
      invocation passes `force=False`, and `--force` appears in `agents --help`.
  11. End-to-end through `main`: rc 2 + bytes identical, then rc 0 + overwritten
      with `--force` (no spy, the real callee).
  12. NOT MET -- see the tester report. `git check-ignore -q AGENTS.md` at the repo
      root exits 1, so a root `AGENTS.md` is still UNIGNORED. Deliberately NOT
      asserted here: the fix is blocked by every-suite freeze guards over
      `.gitignore`, so a pin would be permanently red and would assert the ambient
      tree. Measured in the report instead.
  13. Roadmap index paydown: the four `### Migration note ... iter 03/14/26/52`
      sections are ABSENT from `PLATFORM_ROADMAP.md`, PRESENT in
      `PLATFORM_ROADMAP_ARCHIVE.md` INSIDE the block opened by its own (unique)
      `## Compacted from the index by iter 182` heading -- membership, never a
      LAST-heading pin, which iter 166's rule forbids -- and the index has >= 4,000
      chars of headroom under `ROADMAP_INDEX_HARD_CHARS`.
  14. NOT MET -- see the tester report. `products/*/STATUS_REPORT.md` is still on
      BOTH .gitignore line 5 and line 7. Same freeze-guard block as 12; measured
      in the report, not pinned here.
  Plus acceptance-criteria oracles: `foundry`/`dispatcher` still import, the
  docstrings no longer claim an error-free CLI, and the new symbols stay dormant
  (unreferenced by `dispatcher.py`).

ISOLATION CONTRACT (HONORED): written ONLY from the iter-182 PM spec, the repo's
`tests/` conventions, the tracked roadmap documents, and the product's OBSERVABLE
surface -- importing the module, CALLING its public functions, driving
`foundry.main`, `inspect` introspection, and reading `__doc__`. The implementation
BODIES of `foundry.py` / `dispatcher.py`, the engineer's notes, the reviewer's
notes, the fix-review notes and `git diff` were NOT read. Two checks do a purely
MECHANICAL token census over the shipped source text (banner-duplication in
behavior 1b, dormancy) -- counting occurrences of a string derived at RUNTIME from
the public constant, never reading logic.

Offline and deterministic: `tmp_path` files and synthetic strings only, NO subprocess,
no network, no clock dependence. Nothing is written outside `tmp_path` -- the real
repo's `AGENTS.md` is never created, because every config points `repo` at a tmp dir.
The two repo documents read (roadmap index + archive) are TRACKED, so the assertions
over them hold in the gate's fresh clone too.
"""
import ast
import contextlib
import inspect
import io
import json
import pathlib
import re
import subprocess
import sys
import time

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe -- the product quality bar)

EM = "\u2014"          # em dash
SECT = "\u00a7"        # section sign
ARCHIVE_HEADING = "## Compacted from the index by iter 182"
MIGRATION_HEADS = [
    f"### Migration note (per {SECT}6 self-mod guardrail) {EM} iter {n}"
    for n in ("03", "14", "26", "52")
]


# --------------------------------------------------------------------------
# helpers -- mirror tests/test_iter09_behavior.py's conventions; `repo` is
# ALWAYS a tmp dir so the real foundry repo can never be written to
# --------------------------------------------------------------------------
def _write_cfg(tmp_path, **over):
    tmp_path = pathlib.Path(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
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


def _learnings_text(n_lessons=6, *patterns):
    head = ["## Patterns", "", "Read the head first.", ""]
    head += [f"- {b}" for b in (patterns or ("a durable rule",))]
    tail = "\n".join(
        f"- [ENG iter{i:02d}] MARK-{i:03d} some durable detail text here"
        for i in range(1, n_lessons + 1)
    )
    return "\n".join(head) + "\n\n## Chronological lessons\n\n" + tail + "\n"


def _cfg_with_learnings(tmp_path, file_text=None, **over):
    cfg = foundry.load_config(str(_write_cfg(tmp_path, **over)))
    lp = pathlib.Path(cfg.learnings)
    lp.parent.mkdir(parents=True, exist_ok=True)
    lp.write_text(_learnings_text() if file_text is None else file_text)
    return cfg


def _seed_target(cfg, content):
    """Pre-create <cfg.repo>/AGENTS.md with exactly `content`."""
    repo = pathlib.Path(cfg.repo)
    repo.mkdir(parents=True, exist_ok=True)
    t = repo / "AGENTS.md"
    t.write_text(content)
    return t


def _target(cfg):
    return pathlib.Path(cfg.repo) / "AGENTS.md"


def _fresh_render(cfg, recent=12):
    text = pathlib.Path(cfg.learnings).read_text()
    return foundry.render_agents_md(text, cfg.name, recent=recent)


def _call(fn, *a, **kw):
    """Call `fn`, returning (rc, stdout+stderr) -- the refusal stream is an
    implementation detail, so behaviour is asserted over the COMBINED output."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = fn(*a, **kw)
    return rc, out.getvalue() + err.getvalue()


# ==========================================================================
# Behavior 1 -- the banner constant is the SINGLE source of the provenance mark
# ==========================================================================
def test_b01_banner_constant_emitted_by_every_render():
    banner = foundry.AGENTS_GENERATED_BANNER
    assert isinstance(banner, str), f"AGENTS_GENERATED_BANNER is {type(banner)!r}, want str"
    assert banner.strip(), "AGENTS_GENERATED_BANNER is empty/whitespace"

    cases = [
        ("", "demoprod", 12),
        ("", "x", 1),
        (_learnings_text(1), "demoprod", 1),
        (_learnings_text(30), "demoprod", 12),
        (_learnings_text(6, "pat one", "pat two"), "Weird Name 42", 99),
        ("no head, just a lesson\n- [PM iter02] tail only\n", "p", 3),
    ]
    for text, name, recent in cases:
        doc = foundry.render_agents_md(text, name, recent=recent)
        assert banner in doc, (
            f"render_agents_md(name={name!r}, recent={recent!r}) output lacks "
            "AGENTS_GENERATED_BANNER verbatim"
        )


def test_b01b_banner_is_read_from_the_constant_not_copied(tmp_path, monkeypatch):
    """Rebind the module constant: BOTH the renderer and the refusal path must
    follow it, which is only possible if neither holds a private literal."""
    sentinel = "ZZ-BANNER-SENTINEL-182-ZZ"
    monkeypatch.setattr(foundry, "AGENTS_GENERATED_BANNER", sentinel)

    doc = foundry.render_agents_md(_learnings_text(3), "demoprod", recent=5)
    assert sentinel in doc, (
        "render_agents_md ignored a rebound AGENTS_GENERATED_BANNER -- the renderer "
        "holds its own copy of the banner literal"
    )
    assert foundry.agents_doc_is_generated(doc) is True, (
        "the predicate does not accept a doc rendered under the rebound banner"
    )
    # ...and the file whose banner is the REAL one is now, correctly, foreign.
    cfg = _cfg_with_learnings(tmp_path)
    real_doc = _fresh_render(cfg).replace(sentinel, "")
    _seed_target(cfg, real_doc)
    rc, out = _call(foundry.agents_cli, cfg)
    assert rc == 2, f"refusal path did not follow the rebound banner (rc={rc!r})"
    assert "--force" in out, f"the refusal lost its --force hint: {out!r}"


def test_b01c_no_duplicate_banner_literal_in_source():
    """MECHANICAL census: every 3-word fragment of the RUNTIME banner occurs at
    most once in foundry.py, so there is exactly one copy of the sentence."""
    src = (_ROOT / "foundry.py").read_text()
    words = foundry.AGENTS_GENERATED_BANNER.split()
    assert len(words) >= 4, "banner too short for a 3-word fragment census"
    found, dupes = 0, {}
    for i in range(len(words) - 2):
        frag = " ".join(words[i:i + 3])
        n = src.count(frag)
        if n >= 1:
            found += 1
            if n > 1:
                dupes[frag] = n
    assert found > 0, (
        "anti-vacuous check FAILED: no 3-word banner fragment appears in foundry.py "
        "at all, so this census could never detect a duplicate"
    )
    assert not dupes, f"banner sentence is duplicated in foundry.py: {dupes!r}"


# ==========================================================================
# Behavior 2 -- agents_doc_is_generated is pure, total, and banner-based
# ==========================================================================
def test_b02_predicate_round_trip_and_negatives():
    p = foundry.agents_doc_is_generated
    text = _learnings_text(8, "a pattern")
    for recent in (2, 12):
        doc = foundry.render_agents_md(text, "demoprod", recent=recent)
        assert p(doc) is True, f"round-trip failed for recent={recent}"
    assert foundry.render_agents_md(text, "demoprod", recent=2) != \
        foundry.render_agents_md(text, "demoprod", recent=12), \
        "fixture not armed: the two renders must differ for the round-trip to mean anything"

    assert p("") is False, 'p("") must be False'
    assert p("# hand written notes\n") is False, "a hand-written doc must be False"
    decoy = ("# notes\n\nThis file is auto-generated, honestly, by a person.\n"
             "Do not hand-edit.\n")
    assert foundry.AGENTS_GENERATED_BANNER not in decoy, "decoy accidentally holds the banner"
    assert p(decoy) is False, (
        "a text containing the words 'auto-generated' but NOT the banner must be False"
    )
    # exactly-the-banner and banner-embedded-in-noise are both True
    assert p(foundry.AGENTS_GENERATED_BANNER) is True
    assert p("junk\n" + foundry.AGENTS_GENERATED_BANNER + "\nmore junk\n") is True
    # total: never raises on odd input, always a bool
    for odd in ("", "\n", "\x00", "a" * 5000, EM, "# ", "\u4e2d\u6587"):
        assert isinstance(p(odd), bool)


def test_b02b_predicate_is_pure_no_io(tmp_path, monkeypatch):
    """Poison every I/O door, then call the predicate: it must not knock."""
    def boom(*a, **kw):  # pragma: no cover - must never run
        raise AssertionError("agents_doc_is_generated performed I/O")

    monkeypatch.setattr("builtins.open", boom)
    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(subprocess, "check_output", boom)
    monkeypatch.setattr(time, "time", boom)
    monkeypatch.setattr(time, "sleep", boom)
    monkeypatch.chdir(tmp_path)
    doc = foundry.render_agents_md(_learnings_text(2), "demoprod", recent=3)
    assert foundry.agents_doc_is_generated(doc) is True
    assert foundry.agents_doc_is_generated("plain\n") is False
    assert list(tmp_path.iterdir()) == [], "the predicate created a file in the cwd"


def test_b02c_predicate_source_has_no_io_tokens():
    """AST scan with the DOCSTRING NODE REMOVED -- the docstring legitimately
    contains the words 'filesystem/subprocess/network/clock' in its own purity
    claim, and a substring scan over raw source would fail on that."""
    tree = ast.parse(inspect.getsource(foundry.agents_doc_is_generated).lstrip())
    fn = tree.body[0]
    if (fn.body and isinstance(fn.body[0], ast.Expr)
            and isinstance(fn.body[0].value, ast.Constant)
            and isinstance(fn.body[0].value.value, str)):
        fn.body = fn.body[1:]
    body_src = ast.dump(ast.Module(body=[fn], type_ignores=[]))
    for tok in ("subprocess", "Popen", "open", "Path", "pathlib", "requests",
                "urllib", "socket", "datetime", "sleep", "getenv", "environ"):
        assert tok not in body_src, f"purity: predicate body references {tok!r}"
    assert not any(isinstance(n, (ast.Import, ast.ImportFrom))
                   for n in ast.walk(fn)), "purity: predicate body imports a module"


# ==========================================================================
# Behavior 3 -- target ABSENT: unchanged create semantics
# ==========================================================================
@pytest.mark.parametrize("recent", [None, 3])
def test_b03_absent_target_is_written(tmp_path, recent):
    cfg = _cfg_with_learnings(tmp_path, _learnings_text(6))
    t = _target(cfg)
    assert not t.exists(), "precondition: AGENTS.md must not exist yet"
    kw = {} if recent is None else {"recent": recent}
    rc, _ = _call(foundry.agents_cli, cfg, **kw)
    assert rc == 0, f"create case returned {rc!r}, expected 0"
    assert t.exists(), "default mode did not write <cfg.repo>/AGENTS.md"
    expect = _fresh_render(cfg, recent=12 if recent is None else recent)
    assert t.read_text() == expect, "written bytes != render_agents_md(text, name, recent)"
    assert foundry.agents_doc_is_generated(t.read_text()) is True


# ==========================================================================
# Behavior 4 -- regeneration of OUR OWN output is preserved
# ==========================================================================
def test_b04_regenerates_banner_bearing_target(tmp_path):
    cfg = _cfg_with_learnings(tmp_path, _learnings_text(6))
    stale = _fresh_render(cfg, recent=3)
    fresh = _fresh_render(cfg, recent=12)
    assert stale != fresh, "fixture not armed: stale and fresh renders must differ"
    assert foundry.agents_doc_is_generated(stale) is True
    t = _seed_target(cfg, stale)

    rc, _ = _call(foundry.agents_cli, cfg)
    assert rc == 0, f"regeneration returned {rc!r}, expected 0 (a refresh must be free)"
    assert t.read_text() == fresh, "banner-bearing target was not refreshed to the new render"


def test_b04b_regenerates_banner_plus_foreign_noise(tmp_path):
    """A file that carries the banner is OURS even if somebody appended to it."""
    cfg = _cfg_with_learnings(tmp_path)
    t = _seed_target(cfg, _fresh_render(cfg) + "\n\nsomebody appended this\n")
    rc, _ = _call(foundry.agents_cli, cfg)
    assert rc == 0, f"banner-bearing target refused with rc={rc!r}"
    assert t.read_text() == _fresh_render(cfg)


# ==========================================================================
# Behavior 5 + 6 -- a hand-written target is protected, and the refusal explains
# ==========================================================================
HANDWRITTEN = [
    "# my own house rules\n\nbe nice to the linter\n",
    "",
    "auto-generated? no. hand written by a person.\n",
]


@pytest.mark.parametrize("content", HANDWRITTEN)
def test_b05_handwritten_target_is_byte_identical_after_refusal(tmp_path, content):
    cfg = _cfg_with_learnings(tmp_path)
    t = _seed_target(cfg, content)
    before = t.read_bytes()
    assert foundry.agents_doc_is_generated(content) is False, "fixture is not hand-written"

    rc, _ = _call(foundry.agents_cli, cfg)
    assert rc == 2, f"hand-written target: rc={rc!r}, expected exactly 2"
    assert t.read_bytes() == before, (
        "REFUSAL WROTE BYTES -- the hand-written AGENTS.md was modified"
    )


def test_b06_refusal_message_names_path_provenance_and_force(tmp_path):
    cfg = _cfg_with_learnings(tmp_path)
    t = _seed_target(cfg, "# mine\n")
    rc, out = _call(foundry.agents_cli, cfg)
    assert rc == 2
    assert out.strip(), "the refusal printed nothing at all"
    assert str(t) in out, f"refusal does not name the target path {str(t)!r}: {out!r}"
    low = out.lower()
    assert re.search(r"hand[- ]?(written|edit)", low), (
        f"refusal does not say the file looks hand-written: {out!r}"
    )
    assert ("banner" in low) or ("not" in low and "generated" in low), (
        f"refusal does not explain the missing generated-provenance: {out!r}"
    )
    assert "--force" in out, f"refusal does not name the literal '--force': {out!r}"


# ==========================================================================
# Behavior 7 -- force overrides
# ==========================================================================
def test_b07_force_overwrites_handwritten(tmp_path):
    cfg = _cfg_with_learnings(tmp_path)
    t = _seed_target(cfg, "# my own notes, about to be replaced\n")
    rc, _ = _call(foundry.agents_cli, cfg, force=True)
    assert rc == 0, f"force=True returned {rc!r}, expected 0"
    assert t.read_text() == _fresh_render(cfg), "force did not write the fresh render"
    # force is harmless on the create case too
    cfg2 = _cfg_with_learnings(tmp_path / "b", _learnings_text(4))
    rc2, _ = _call(foundry.agents_cli, cfg2, force=True)
    assert rc2 == 0
    assert _target(cfg2).read_text() == _fresh_render(cfg2)


# ==========================================================================
# Behavior 8 -- read-only modes never refuse and never write
# ==========================================================================
def test_b08_readonly_modes_never_refuse_never_write(tmp_path):
    cfg = _cfg_with_learnings(tmp_path)
    t = _seed_target(cfg, "# hand written, keep me\n")
    before = t.read_bytes()

    rc, out = _call(foundry.agents_cli, cfg, print_only=True)
    assert rc == 0, f"print_only returned {rc!r} against a hand-written target"
    assert _fresh_render(cfg) in out, "print_only did not print the rendered doc"
    assert t.read_bytes() == before, "print_only modified the target"

    rc, out = _call(foundry.agents_cli, cfg, as_json=True)
    assert rc == 0, f"as_json returned {rc!r} against a hand-written target"
    obj = json.loads(out)
    assert isinstance(obj, dict) and obj, f"as_json did not print one JSON object: {out[:120]!r}"
    assert t.read_bytes() == before, "as_json modified the target"


def test_b08b_as_json_outranks_print_only_and_the_write(tmp_path):
    cfg = _cfg_with_learnings(tmp_path)
    t = _seed_target(cfg, "# hand written\n")
    before = t.read_bytes()
    rc, out = _call(foundry.agents_cli, cfg, print_only=True, as_json=True)
    assert rc == 0
    json.loads(out)  # raises if print_only won
    assert t.read_bytes() == before, "as_json+print_only wrote the target"
    # and on the ABSENT-target create case as_json still writes nothing
    cfg2 = _cfg_with_learnings(tmp_path / "c")
    rc2, out2 = _call(foundry.agents_cli, cfg2, as_json=True)
    assert rc2 == 0
    json.loads(out2)
    assert not _target(cfg2).exists(), "as_json created <cfg.repo>/AGENTS.md"


# ==========================================================================
# Behavior 9 -- signature + defaults
# ==========================================================================
def test_b09_signature_and_defaults():
    params = inspect.signature(foundry.agents_cli).parameters
    assert list(params) == ["cfg", "recent", "print_only", "as_json", "force"], (
        f"agents_cli params are {list(params)!r}"
    )
    assert params["recent"].default == 12
    assert params["print_only"].default is False
    assert params["as_json"].default is False
    assert params["force"].default is False, (
        "force must default to False -- a True default silently restores the clobber"
    )


# ==========================================================================
# Behavior 10 -- CLI wiring
# ==========================================================================
def test_b10_force_flag_reaches_agents_cli(tmp_path, monkeypatch):
    cfg_path = str(_write_cfg(tmp_path))
    calls = []

    def spy(cfg, recent=12, print_only=False, as_json=False, force=False):
        calls.append({"recent": recent, "print_only": print_only,
                      "as_json": as_json, "force": force})
        return 0

    monkeypatch.setattr(foundry, "agents_cli", spy)
    assert foundry.main(["agents", "--config", cfg_path, "--force"]) == 0
    assert calls[-1]["force"] is True, f"--force did not reach agents_cli: {calls[-1]!r}"
    assert foundry.main(["agents", "--config", cfg_path]) == 0
    assert calls[-1]["force"] is False, f"bare invocation set force={calls[-1]['force']!r}"
    # the other flags are undisturbed by the new one
    foundry.main(["agents", "--config", cfg_path, "--print", "--recent", "4"])
    assert calls[-1] == {"recent": 4, "print_only": True, "as_json": False, "force": False}


def test_b10b_force_in_agents_help(capsys):
    with pytest.raises(SystemExit) as exc:
        foundry.main(["agents", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--force" in out, f"'--force' missing from `agents --help`:\n{out}"


# ==========================================================================
# Behavior 11 -- end to end through main (no spy)
# ==========================================================================
def test_b11_end_to_end_refuse_then_force(tmp_path):
    cfg = _cfg_with_learnings(tmp_path)
    cfg_path = str(tmp_path / "config.json")
    t = _seed_target(cfg, "# hand written, do not clobber\n")
    before = t.read_bytes()

    rc, out = _call(foundry.main, ["agents", "--config", cfg_path])
    assert rc == 2, f"main(agents) returned {rc!r} against a hand-written target"
    assert t.read_bytes() == before, "main(agents) clobbered a hand-written target"
    assert "--force" in out

    rc, _ = _call(foundry.main, ["agents", "--config", cfg_path, "--force"])
    assert rc == 0, f"main(agents --force) returned {rc!r}"
    assert t.read_text() == _fresh_render(cfg), "main(agents --force) did not overwrite"


# ==========================================================================
# Behavior 13 -- roadmap index paydown (tracked docs only)
# ==========================================================================
def test_b13_migration_notes_moved_to_archive():
    idx = (_ROOT / "PLATFORM_ROADMAP.md").read_text()
    arch = (_ROOT / "PLATFORM_ROADMAP_ARCHIVE.md").read_text()

    for head in MIGRATION_HEADS:
        assert head not in idx, f"section still in the index (iter 140 brake): {head!r}"
        assert arch.count(head) == 1, (
            f"archive holds {arch.count(head)} copies of {head!r}, want exactly 1"
        )

    # NOT a positional pin: iter 166's rule (and iter 158's) forbids asserting that
    # any compaction heading is the archive's LAST one -- the next iteration appends
    # its own and such a pin would go red for free. Assert MEMBERSHIP in iter 182's
    # own block instead: the slice from this heading to the next `## ` heading.
    assert arch.count(ARCHIVE_HEADING) == 1, (
        f"archive holds {arch.count(ARCHIVE_HEADING)} copies of {ARCHIVE_HEADING!r}, want 1"
    )
    after = arch[arch.index(ARCHIVE_HEADING) + len(ARCHIVE_HEADING):]
    nxt_top = after.find("\n## ")
    block = after if nxt_top == -1 else after[:nxt_top]
    for head in MIGRATION_HEADS:
        assert head in block, (
            f"{head!r} is not inside iter 182's own archive block (it may sit above "
            f"{ARCHIVE_HEADING!r} or under a later heading)"
        )
        body = block[block.index(head) + len(head):]
        ends = [q for q in (body.find("\n### "), body.find("\n## ")) if q != -1]
        assert body[:min(ends) if ends else len(body)].strip(), (
            f"{head!r} was moved as an EMPTY section"
        )


def test_b13b_index_headroom_at_least_4000():
    idx = (_ROOT / "PLATFORM_ROADMAP.md").read_text()
    hard = foundry.ROADMAP_INDEX_HARD_CHARS
    headroom = hard - len(idx)
    assert headroom >= 4000, (
        f"index is {len(idx)} chars against a {hard}-char wall -- headroom {headroom} < 4000"
    )


# ==========================================================================
# Acceptance-criteria oracles
# ==========================================================================
def test_ac_docstrings_no_longer_claim_an_error_free_cli():
    docs = {"agents_cli": foundry.agents_cli.__doc__ or "",
            "AgentsView.to_dict": foundry.AgentsView.to_dict.__doc__ or ""}
    for name, doc in docs.items():
        low = " ".join(doc.lower().split())
        assert "no error path" not in low, f"{name} still claims 'no error path'"
        assert not re.search(r"every mode\s+(always\s+)?returns?\s+0", low), (
            f"{name} still claims every mode always returns 0"
        )
    cli = " ".join(docs["agents_cli"].lower().split())
    assert "refus" in cli and "2" in cli, (
        "anti-vacuous: agents_cli's docstring must document the refusal and its exit code 2"
    )


def test_ac_new_symbols_are_dormant_on_the_pipeline_path():
    disp = (_ROOT / "dispatcher.py").read_text()
    for sym in ("agents_doc_is_generated", "AGENTS_GENERATED_BANNER", "agents_cli"):
        assert sym not in disp, f"dispatcher.py references {sym!r} -- not dormant"


def test_ac_modules_still_import():
    assert foundry.__name__ == "foundry" and dispatcher.__name__ == "dispatcher"
    for sym in ("AGENTS_GENERATED_BANNER", "agents_doc_is_generated",
                "render_agents_md", "agents_cli", "main"):
        assert hasattr(foundry, sym), f"foundry lost the public symbol {sym!r}"
