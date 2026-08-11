"""Black-box behaviour tests for iter 157 -- `build_prompt` emits ONE guarded
`Product config` Context line naming this product's own config file, so the
`--config` verbs that role cards already invoke are runnable instead of derived.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-157 PM spec's Expected
Behaviors 1-12, the conventions found under `tests/`, the two role cards the
spec's behaviors 9-11 are ABOUT (card text is the deliverable under test, not
implementation source), and the product's own OBSERVABLE behaviour (importing
the public names, reading their signatures, calling them, scripting the
documented module seams, and running the prompt verb). `foundry.py` /
`dispatcher.py` SOURCE was not read -- behavior 11 feeds `foundry.py`'s bytes to
`foundry_cli_verbs` as INPUT DATA (the iter-142 convention) without inspecting
them. Neither the engineer's notes, the reviewer's notes, the fix notes, nor any
`git diff` was consulted.

Every test here is OFFLINE and builds its own fixtures in `tmp_path`: no real
subprocess, git, clone or network call, and -- per the 2026-08-11 operator rule
-- no assertion depends on gitignored local state. The only ambient files read
are git-TRACKED ones the spec names (`roles/pm.md`, `roles/final.md`,
`roles/**/*.md`, `foundry.py` as opaque input bytes).
"""

from __future__ import annotations

import io
import contextlib
import json
import pathlib
import shutil
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402
import dispatcher  # noqa: E402

THIS_ITER = 157

ROLES_DIR = _ROOT / "roles"
FOUNDRY_SRC = _ROOT / "foundry.py"
PM_CARD = ROLES_DIR / "pm.md"
FINAL_CARD = ROLES_DIR / "final.md"

# behavior 3 -- the literal label, backtick-free and greppable so the card and
# the test can both name it verbatim.
LABEL = "- Product config (read-only reference for --config verbs): "

# behavior 4 -- the two anchors the new line must sit between.
QC_PREFIX = "- Quality-check command (full suite must pass): "
STATE_PREFIX = "- This iteration's state dir (all stage outputs live here): "

# behavior 5 -- every stage, including `fix`, which is not in prompt_stage_options().
ALL_STAGES = ("pm", "engineer", "reviewer", "tester", "fix", "final")

# behavior 12 -- the field set must be UNCHANGED by this iteration.
FROZEN_FIELDS = (
    "name", "repo", "allowed_push_repo", "branch", "vision", "roadmap", "prd",
    "quality_ref", "test_cmd", "roles_dir", "work_root", "learnings", "staffing",
    "quality_bar", "push_enabled", "postrelease_enabled", "setup_cmd", "smoke_cmd",
    "dual_pm_scouts",
)

# behavior 10 -- the state-dir-relative derivation clause the spec retires.
RETIRED_DERIVATION = "../../config.json"


# --------------------------------------------------------------------------
# fixtures -- every product is built from scratch under tmp_path
# --------------------------------------------------------------------------
def _cfg(tmp_path, sub="p", name="demo", work_root_suffix=""):
    """A loaded ProductConfig rooted entirely under tmp_path.

    `load_config` itself creates the work/state dirs, so a caller that wants a
    MISSING work_root must remove it after this returns.
    """
    root = tmp_path / sub
    (root / "repo").mkdir(parents=True, exist_ok=True)
    (root / "VISION.md").write_text("product vision text\n", encoding="utf-8")
    roles = root / "roles"
    roles.mkdir(exist_ok=True)
    for label in ALL_STAGES:
        (roles / ("%s.md" % label)).write_text("# ROLE %s\ncard body\n" % label,
                                               encoding="utf-8")
    learnings = root / "LEARNINGS.md"
    learnings.write_text("## Patterns\n\n- a durable pattern\n\n- [X iter1] a lesson\n",
                         encoding="utf-8")
    data = {
        "name": name,
        "repo": str(root / "repo"),
        "allowed_push_repo": "demo",
        "vision": str(root / "VISION.md"),
        "work_root": str(root / "work") + work_root_suffix,
        "learnings": str(learnings),
        "roles_dir": str(roles),
    }
    p = root / "config.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return foundry.load_config(str(p))


def _place(cfg, payload, *, as_dir=False, raw_bytes=None):
    """Put something at the CONVENTIONAL location `<work_root>/config.json`."""
    target = pathlib.Path(cfg.work_root) / "config.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if as_dir:
        target.mkdir()
        return target
    if raw_bytes is not None:
        target.write_bytes(raw_bytes)
        return target
    target.write_text(payload if isinstance(payload, str) else json.dumps(payload),
                      encoding="utf-8")
    return target


def _matching(tmp_path, sub="p", name="demo", work_root_suffix=""):
    """A product whose work_root holds a config.json that NAMES it."""
    cfg = _cfg(tmp_path, sub=sub, name=name, work_root_suffix=work_root_suffix)
    written = _place(cfg, {"name": name, "repo": cfg.repo})
    return cfg, written


def _prompt(cfg, stage="pm", iteration=7):
    return foundry.build_prompt(
        cfg,
        iteration,
        stage,
        str(pathlib.Path(cfg.roles_dir) / ("%s.md" % stage)),
        pathlib.Path(cfg.state) / ("iter-%02d" % iteration) / ("%s.md" % stage),
        pathlib.Path(cfg.state) / ("iter-%02d" % iteration),
        "extra text",
    )


def _line_of(text, prefix):
    hits = [ln for ln in text.splitlines() if ln.startswith(prefix)]
    return hits


# --------------------------------------------------------------------------
# behavior 1 -- product_config_path: exists AND JSON object AND name matches
# --------------------------------------------------------------------------
def test_b1_public_callables_exist_with_documented_shapes():
    import inspect
    assert callable(getattr(foundry, "product_config_path", None))
    assert callable(getattr(foundry, "config_path_line", None))
    assert list(inspect.signature(foundry.product_config_path).parameters) == ["cfg"]
    assert list(inspect.signature(foundry.config_path_line).parameters) == ["cfg"]


def test_b1_returns_the_absolute_path_when_the_object_names_this_product(tmp_path):
    cfg, written = _matching(tmp_path)
    got = foundry.product_config_path(cfg)
    assert isinstance(got, str)
    assert pathlib.Path(got).is_absolute()
    assert pathlib.Path(got) == written


def test_b1_none_when_the_conventional_file_is_absent(tmp_path):
    cfg = _cfg(tmp_path)
    assert not (pathlib.Path(cfg.work_root) / "config.json").exists()
    assert foundry.product_config_path(cfg) is None


def test_b1_none_when_a_stale_file_names_a_different_product(tmp_path):
    """The name match is what makes the emitted claim VERIFIED, not conventional."""
    cfg = _cfg(tmp_path, name="demo")
    _place(cfg, {"name": "some-other-product"})
    assert foundry.product_config_path(cfg) is None


def test_b1_the_name_match_is_exact_not_a_prefix_or_case_fold(tmp_path):
    for n, stale in enumerate(("demo2", "Demo", " demo", "dem", "demo ")):
        cfg = _cfg(tmp_path, sub="exact%d" % n, name="demo")
        _place(cfg, {"name": stale})
        assert foundry.product_config_path(cfg) is None, stale


# --------------------------------------------------------------------------
# behavior 2 -- TOTAL: raises for no input (BLOCKING criterion)
# --------------------------------------------------------------------------
def test_b2_missing_work_root_returns_none_without_raising(tmp_path):
    cfg = _cfg(tmp_path)
    shutil.rmtree(cfg.work_root, ignore_errors=True)
    assert not pathlib.Path(cfg.work_root).exists()
    assert foundry.product_config_path(cfg) is None


def test_b2_a_directory_in_place_of_the_file_returns_none(tmp_path):
    cfg = _cfg(tmp_path)
    _place(cfg, None, as_dir=True)
    assert (pathlib.Path(cfg.work_root) / "config.json").is_dir()
    assert foundry.product_config_path(cfg) is None


def test_b2_undecodable_bytes_return_none(tmp_path):
    cfg = _cfg(tmp_path)
    _place(cfg, None, raw_bytes=b'{"name": "\xff\xfe demo"}')
    assert foundry.product_config_path(cfg) is None


@pytest.mark.parametrize("body", [
    "",                      # empty file
    "   \n",                 # whitespace only
    "not json at all",       # invalid JSON
    '{"name": "demo"',       # truncated object
    "[]",                    # valid JSON, not an object
    '["demo"]',              # list
    '"demo"',                # bare string
    "3",                     # number
    "null",                  # null
    "true",                  # bool
    "{}",                    # object with no "name"
    '{"repo": "x"}',         # object with other keys only
    '{"name": 3}',           # "name" of the wrong type
    '{"name": null}',
    '{"name": ["demo"]}',
    '{"name": {"n": "demo"}}',
])
def test_b2_totality_every_malformed_payload_returns_none(tmp_path, body):
    cfg = _cfg(tmp_path)
    _place(cfg, body)
    assert foundry.product_config_path(cfg) is None, body


def test_b2_totality_holds_inside_build_prompt_too(tmp_path):
    """The BLOCKING criterion: the helper must never raise inside build_prompt."""
    for i, body in enumerate(("", "not json", "[]", "{}", '{"name": 3}')):
        cfg = _cfg(tmp_path, sub="bp%d" % i)
        _place(cfg, body)
        text = _prompt(cfg)
        assert LABEL not in text
        assert QC_PREFIX in text


# --------------------------------------------------------------------------
# behavior 3 -- config_path_line: pure renderer over behavior 1
# --------------------------------------------------------------------------
def test_b3_renders_exactly_one_line_with_the_literal_label(tmp_path):
    cfg, written = _matching(tmp_path)
    got = foundry.config_path_line(cfg)
    assert got == LABEL + str(written) + "\n"
    assert got.endswith("\n") and not got.endswith("\n\n")
    assert got.count("\n") == 1


def test_b3_returns_empty_string_with_no_newline_when_unresolved(tmp_path):
    cfg = _cfg(tmp_path)
    assert foundry.config_path_line(cfg) == ""


def test_b3_reads_product_config_path_as_a_module_global_by_bare_name(tmp_path,
                                                                     monkeypatch):
    cfg = _cfg(tmp_path)          # no conventional config on disk at all
    monkeypatch.setattr(foundry, "product_config_path", lambda c: "/scripted/cfg.json")
    assert foundry.config_path_line(cfg) == LABEL + "/scripted/cfg.json\n"
    monkeypatch.setattr(foundry, "product_config_path", lambda c: None)
    assert foundry.config_path_line(cfg) == ""


def test_b3_the_label_is_backtick_free_and_greppable():
    assert "`" not in LABEL
    assert LABEL.startswith("- ") and LABEL.endswith(": ")


# --------------------------------------------------------------------------
# behavior 4 -- position inside the Context block + bare-name seam
# --------------------------------------------------------------------------
def test_b4_sits_immediately_after_quality_check_and_before_the_state_dir(tmp_path):
    cfg, written = _matching(tmp_path)
    lines = _prompt(cfg).splitlines()
    idx = [i for i, ln in enumerate(lines) if ln.startswith(LABEL)]
    assert len(idx) == 1, lines
    i = idx[0]
    assert lines[i - 1].startswith(QC_PREFIX), lines[i - 3:i + 2]
    assert lines[i + 1].startswith(STATE_PREFIX), lines[i - 1:i + 3]


def test_b4_build_prompt_calls_config_path_line_by_bare_module_name(tmp_path,
                                                                   monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(foundry, "config_path_line", lambda c: "- SCRIPTED SEAM LINE\n")
    lines = _prompt(cfg).splitlines()
    idx = [i for i, ln in enumerate(lines) if ln == "- SCRIPTED SEAM LINE"]
    assert len(idx) == 1
    assert lines[idx[0] - 1].startswith(QC_PREFIX)
    assert lines[idx[0] + 1].startswith(STATE_PREFIX)


def test_b4_every_other_context_line_keeps_its_text_and_order(tmp_path):
    cfg, _ = _matching(tmp_path)
    text = _prompt(cfg)
    ordered = [
        "- Product repo: ",
        "- Push target (final gate only): ",
        "- Product vision (fixed intent, stay inside it): ",
        "- Product roadmap file (PM owns): ",
        "- Quality-reference repo (mirror its conventions): ",
        "- Product quality bar: ",
        QC_PREFIX,
        LABEL,
        STATE_PREFIX,
        "- Foundry learnings log (append your role lessons here): ",
        "- Recent foundry learnings (bounded digest; read this, do not slurp the whole log):",
        "- Iteration number for file naming: ",
        "- YOUR REQUIRED OUTPUT FILE: ",
    ]
    positions = []
    for prefix in ordered:
        assert prefix in text, "Context line vanished: %r" % prefix
        positions.append(text.index(prefix))
    assert positions == sorted(positions), "Context lines reordered: %r" % ordered


def test_b4_the_learnings_label_and_digest_stay_adjacent(tmp_path):
    cfg, _ = _matching(tmp_path)
    lines = _prompt(cfg).splitlines()
    log = [i for i, ln in enumerate(lines)
           if ln.startswith("- Foundry learnings log (append your role lessons here): ")]
    assert len(log) == 1
    assert lines[log[0] + 1].startswith("- Recent foundry learnings (bounded digest;")


# --------------------------------------------------------------------------
# behavior 5 -- present for EVERY stage, exactly once
# --------------------------------------------------------------------------
@pytest.mark.parametrize("stage", ALL_STAGES)
def test_b5_exactly_one_occurrence_for_every_stage(tmp_path, stage):
    cfg, written = _matching(tmp_path)
    text = _prompt(cfg, stage=stage)
    assert text.count(LABEL) == 1, stage
    assert _line_of(text, LABEL) == [LABEL + str(written)]


def test_b5_the_six_stages_named_here_cover_the_shipped_prompt_options():
    """Guard: if a new stage label ships, this iteration's coverage must notice."""
    assert set(foundry.prompt_stage_options()) <= set(ALL_STAGES)


# --------------------------------------------------------------------------
# behavior 6 -- BYTE-IDENTICAL fallback (BLOCKING criterion)
# --------------------------------------------------------------------------
@pytest.mark.parametrize("stage", ALL_STAGES)
def test_b6_no_config_prompt_is_byte_identical_to_the_empty_line_render(tmp_path,
                                                                       monkeypatch,
                                                                       stage):
    cfg = _cfg(tmp_path)
    live = _prompt(cfg, stage=stage)
    monkeypatch.setattr(foundry, "config_path_line", lambda c: "")
    silenced = _prompt(cfg, stage=stage)
    assert live == silenced
    assert live.encode("utf-8") == silenced.encode("utf-8")


@pytest.mark.parametrize("stage", ALL_STAGES)
def test_b6_fallback_keeps_quality_check_and_state_dir_adjacent(tmp_path, stage):
    """No blank line, no stray text where the guarded line would have gone."""
    cfg = _cfg(tmp_path)
    lines = _prompt(cfg, stage=stage).splitlines()
    qc = [i for i, ln in enumerate(lines) if ln.startswith(QC_PREFIX)]
    assert len(qc) == 1
    assert lines[qc[0] + 1].startswith(STATE_PREFIX), lines[qc[0]:qc[0] + 3]


def test_b6_the_equality_is_not_vacuous_the_seam_really_moves_the_output(tmp_path,
                                                                        monkeypatch):
    """Control: with a MATCHING config the silenced render must DIFFER."""
    cfg, _ = _matching(tmp_path)
    live = _prompt(cfg)
    monkeypatch.setattr(foundry, "config_path_line", lambda c: "")
    silenced = _prompt(cfg)
    assert live != silenced
    assert LABEL in live and LABEL not in silenced
    # the ONLY difference is the guarded line: deleting it from `live` recovers
    # the silenced render byte-for-byte.
    assert live.replace(foundry.product_config_path(cfg), "", 1) != live


# --------------------------------------------------------------------------
# behavior 7 -- the emitted path is absolute and is the REAL file
# --------------------------------------------------------------------------
def test_b7_the_emitted_path_samefile_matches_the_written_config(tmp_path):
    import os
    cfg, written = _matching(tmp_path)
    line = _line_of(_prompt(cfg), LABEL)[0]
    emitted = line[len(LABEL):]
    assert os.path.isabs(emitted), emitted
    assert os.path.samefile(emitted, str(written))
    assert json.loads(pathlib.Path(emitted).read_text(encoding="utf-8"))["name"] == cfg.name


def test_b7_the_emitted_path_survives_a_work_root_given_with_a_trailing_slash(tmp_path):
    """Ambiguity noted for the PM: work_root normalisation is not spec'd."""
    import os
    cfg, written = _matching(tmp_path, sub="slash", work_root_suffix="/")
    emitted = _line_of(_prompt(cfg), LABEL)[0][len(LABEL):]
    assert os.path.samefile(emitted, str(written))
    assert "//" not in emitted


# --------------------------------------------------------------------------
# behavior 8 -- the iter-144 `prompt` verb renders through build_prompt
# --------------------------------------------------------------------------
def test_b8_the_prompt_verb_prints_the_line_exactly_once(tmp_path, capsys):
    cfg, written = _matching(tmp_path)
    rc = foundry.prompt_cli(cfg, "pm", iteration=THIS_ITER)
    out = capsys.readouterr().out
    assert rc == 0, out
    assert out.count(LABEL) == 1, out[:2000]
    assert LABEL + str(written) in out


def test_b8_render_stage_prompt_carries_the_line_for_every_stage(tmp_path):
    cfg, written = _matching(tmp_path)
    for stage in foundry.prompt_stage_options():
        rendered = foundry.render_stage_prompt(cfg, THIS_ITER, stage)
        assert rendered is not None, stage
        assert rendered.count(LABEL) == 1, stage


def test_b8_the_prompt_verb_omits_the_line_for_a_product_without_one(tmp_path, capsys):
    cfg = _cfg(tmp_path)
    rc = foundry.prompt_cli(cfg, "pm", iteration=THIS_ITER)
    out = capsys.readouterr().out
    assert rc == 0, out
    assert LABEL not in out


# --------------------------------------------------------------------------
# behavior 9 -- roles/pm.md drops the unresolved placeholder
# --------------------------------------------------------------------------
def test_b9_pm_card_no_longer_carries_the_unresolved_placeholder():
    text = PM_CARD.read_text(encoding="utf-8")
    assert "<this product's config>" not in text
    assert "<this product’s config>" not in text  # curly-apostrophe variant


def test_b9_pm_card_points_at_the_product_config_context_line():
    text = PM_CARD.read_text(encoding="utf-8")
    assert "Product config" in text
    assert "--config" in text
    lower = text.lower()
    assert "context" in lower


# --------------------------------------------------------------------------
# behavior 10 -- roles/final.md names the Context line, keeps ONE fallback
# --------------------------------------------------------------------------
def test_b10_final_card_names_the_product_config_line_for_preship():
    text = FINAL_CARD.read_text(encoding="utf-8")
    preship = [ln for ln in text.splitlines() if "preship --config" in ln]
    assert len(preship) == 1, preship
    line = preship[0]
    assert "Product config" in line
    assert "Context" in line


def test_b10_the_state_dir_relative_derivation_clause_is_gone():
    text = FINAL_CARD.read_text(encoding="utf-8")
    assert RETIRED_DERIVATION not in text, \
        "the retired state-dir-relative derivation is still in roles/final.md"


def test_b10_exactly_one_short_fallback_clause_remains():
    text = FINAL_CARD.read_text(encoding="utf-8")
    preship = [ln for ln in text.splitlines() if "preship --config" in ln][0]
    assert preship.lower().count("fall back") == 1, preship
    assert "no such line" in preship.lower()


# --------------------------------------------------------------------------
# behavior 11 -- the iter-142 bare-CLI brake stays green (two-sided)
# --------------------------------------------------------------------------
def _verbs():
    """foundry.py's bytes are INPUT DATA for the function under test, never read here."""
    return foundry.foundry_cli_verbs(FOUNDRY_SRC.read_text(encoding="utf-8"))


def test_b11_both_edited_cards_yield_zero_findings():
    verbs = _verbs()
    assert len(verbs) >= 20, len(verbs)
    for card in (PM_CARD, FINAL_CARD):
        found = foundry.bare_foundry_cli_findings(card.read_text(encoding="utf-8"), verbs)
        assert found == [], "%s: %r" % (card.name, found)


def test_b11_the_live_brake_over_every_role_card_stays_green():
    verbs = _verbs()
    offenders = {}
    cards = sorted(p for p in ROLES_DIR.rglob("*.md") if p.is_file())
    assert cards, "no role cards found"
    for card in cards:
        found = foundry.bare_foundry_cli_findings(card.read_text(encoding="utf-8"), verbs)
        if found:
            offenders[str(card.relative_to(_ROOT))] = found
    assert offenders == {}, offenders


def test_b11_the_brake_is_two_sided_it_still_fires_on_a_bare_invocation():
    """Control: a green result above must not be a fail-open matcher."""
    assert foundry.bare_foundry_cli_findings("run `foundry preship` now", _verbs())


# --------------------------------------------------------------------------
# behavior 12 -- no schema change
# --------------------------------------------------------------------------
def test_b12_config_field_names_is_unchanged():
    assert tuple(foundry.config_field_names()) == FROZEN_FIELDS


def test_b12_unknown_config_keys_gains_no_new_accepted_key():
    assert foundry.unknown_config_keys({k: "x" for k in FROZEN_FIELDS}) == ()
    for candidate in ("config_path", "product_config", "config_path_line"):
        assert candidate in foundry.unknown_config_keys({"name": "d", candidate: "x"}), \
            candidate


def test_b12_an_existing_product_config_still_loads(tmp_path):
    cfg, _ = _matching(tmp_path)
    assert cfg.name == "demo"
    assert pathlib.Path(cfg.work_root).exists()


# --------------------------------------------------------------------------
# acceptance criteria -- importability + no new runtime artifact
# --------------------------------------------------------------------------
def test_ac_fresh_interpreter_import_probe():
    import subprocess
    r = subprocess.run([sys.executable, "-c", "import foundry, dispatcher"],
                       cwd=str(_ROOT), capture_output=True, text=True, timeout=90)
    assert r.returncode == 0, r.stderr[-2000:]


def test_ac_neither_new_function_writes_anything_to_disk(tmp_path):
    cfg, written = _matching(tmp_path, sub="nowrite")
    root = tmp_path / "nowrite"
    before = {str(p.relative_to(root)): (p.read_bytes() if p.is_file() else None)
              for p in root.rglob("*")}
    foundry.product_config_path(cfg)
    foundry.config_path_line(cfg)
    _prompt(cfg)
    after = {str(p.relative_to(root)): (p.read_bytes() if p.is_file() else None)
             for p in root.rglob("*")}
    assert before == after


def test_ac_control_flow_functions_still_exist_untouched_in_shape():
    import inspect
    for name in ("run_iteration", "run_stage", "run_continuous"):
        assert callable(getattr(foundry, name)), name
    assert callable(getattr(dispatcher, "main", None)) or hasattr(dispatcher, "__file__")
    assert "cfg" in inspect.signature(foundry.build_prompt).parameters

# --------------------------------------------------------------------------
# acceptance criterion -- the iteration's roadmap records exist in BOTH files
# --------------------------------------------------------------------------
def test_ac_roadmap_records_exist_in_both_files():
    ledger = (_ROOT / "PLATFORM_ROADMAP.md").read_text(encoding="utf-8")
    rows = [ln for ln in ledger.splitlines()
            if ln.startswith("- iter %d " % THIS_ITER)]
    assert len(rows) == 1, rows
    assert len(rows[0]) <= 120, "ledger row is %d chars: %r" % (len(rows[0]), rows[0])
    archive = (_ROOT / "PLATFORM_ROADMAP_ARCHIVE.md").read_text(encoding="utf-8")
    detail = [ln for ln in archive.splitlines()
              if ln.startswith("- **iter %d " % THIS_ITER)]
    assert len(detail) == 1, detail
