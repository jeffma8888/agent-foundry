"""Black-box behaviour tests for iter 176 -- `roles/pm.md`'s `## Size self-check` must quote the
platform's own MEASURED worst-stage headroom from the shipped `doctor` verb, and must state that
doctor's exit code is ADVISORY.

Spec: products/_platform/state/iter-176/pm.md, Expected Behaviors 1-9.

  1. REGION cites the DERIVED anchor `foundry.STAGE_BUDGET_PREFIX`; negative control on a near-miss.
  2. REGION carries the token `ADVISORY` in the SAME region as the anchor (they cannot drift apart).
  3. REGION carries an invocable form and the card's own verified-path convention name.
  4. `doctor` is a really routable verb: `main(["doctor", ...])` -> `run_doctor_cli(cfg)`; two-sided.
  5. `stage_budget_line` is TOTAL -- three degenerate inputs still yield one prefixed line.
  6. The ADVISORY claim is true of the SHIPPED CODE: a failing probe -> nonzero exit, drift line
     still printed; all probes passing -> exit 0, same line still printed.
  7. Additive, not a rewrite: the pre-existing region content and the card's WRITE-EARLY head remain.
  8. Repo-agnostic + public-safe: no machine paths, no product name, in a card every product shares.
  9. The card points at a READ-ONLY verb, never at a loop-launching or file-planting one.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-176 PM spec's Expected Behaviors, the
conventions of the existing `tests/test_iter17*_behavior.py` modules, and the product's OWN
OBSERVABLE surface -- CALLING its public functions, reading its public constants and signatures,
and reading the SHIPPED prose of `roles/pm.md` (the artifact under test).  The implementation TEXT
of `foundry.py` / `dispatcher.py` was NOT read by the author, and neither were the engineer's notes,
the reviewer's notes, `fix_review.md`, `IMPLEMENTATION.patch`, nor `git diff`.

Offline and deterministic: no network, no agent run, no subprocess, no sleeps, no clock.  Every
input is either a tracked repo file or a `tmp_path` fixture; NOTHING in the repo is mutated.

CLONE-SAFETY (OPERATOR 2026-08-11): no assertion depends on gitignored ambient state.  `roles/pm.md`
and `products/_platform/config.json` are tracked; the product-name set of behavior 8 is derived by
GLOB, so an extra untracked product in a working tree only makes the check STRICTER, never weaker,
and its anti-vacuous control names a TRACKED config.  Behavior 5 asserts nothing about the ambient
(gitignored) `dispatcher.out`: it passes an explicit `log_path` in every case.

SELF-DOMAIN NOTE: every string this module asserts the ABSENCE of is ASSEMBLED FROM FRAGMENTS or
DERIVED from a shipped constant, so no forbidden literal ever appears contiguously in this file's
own text (the `_LAST_INDEX` technique of `tests/test_iter166_behavior.py`).

AMBIGUITY NOTED (PM feedback), Behavior 6: the spec says "the four drift-line helpers monkeypatched
to sentinel strings" without naming them.  The reading tested here is the four public
`*_line(cfg)` roll-up helpers that `run_doctor_cli` composes (`stage_budget_line`, `live_lag_line`,
`learnings_head_line`, `roadmap_index_line`); each is replaced by a constant-returning stub, which
is what makes the case offline.  Only the `stage_budget_line` sentinel is ASSERTED, per the spec.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402

THIS_ITER = 176
ROLES = _ROOT / "roles"
PM_CARD = ROLES / "pm.md"
PRODUCTS = _ROOT / "products"
SECTION_MARKER = "## Size self-check"

# The four public roll-up helpers doctor composes (see AMBIGUITY note).
DRIFT_LINE_HELPERS = ("stage_budget_line", "live_lag_line", "learnings_head_line",
                      "roadmap_index_line")
PROBE_SEAMS = ("check_power", "check_agent", "check_uv", "check_remote")


# --------------------------------------------------------------------------- helpers

def _card_text() -> str:
    assert PM_CARD.is_file(), f"tracked role card missing: {PM_CARD}"
    return PM_CARD.read_text(encoding="utf-8")


def _region(text: str) -> str:
    """`## Size self-check` marker up to the next `\\n## ` heading (the spec's REGION)."""
    assert text.count(SECTION_MARKER) == 1, (
        f"expected exactly one {SECTION_MARKER!r} heading in the card, "
        f"found {text.count(SECTION_MARKER)}"
    )
    start = text.index(SECTION_MARKER)
    rest = text[start + len(SECTION_MARKER):]
    nxt = rest.find("\n## ")
    return SECTION_MARKER + (rest if nxt < 0 else rest[:nxt])


def _write_cfg(tmp_path, **over):
    """A minimal product config in a tmp dir; repo/work_root are TMP dirs so the real foundry
    repo and its gitignored state are NEVER touched."""
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


def _cfg(tmp_path, **over):
    return foundry.load_config(str(_write_cfg(tmp_path, **over)))


def _product_names() -> set[str]:
    names = set()
    for cfg_path in sorted(PRODUCTS.glob("*/config.json")):
        try:
            name = json.loads(cfg_path.read_text(encoding="utf-8")).get("name")
        except Exception:  # pragma: no cover - a malformed sibling config must not fail this test
            continue
        if isinstance(name, str) and name.strip():
            names.add(name.strip())
    return names


# --------------------------------------------------------------------------- behavior 1

def test_behavior1_region_cites_the_derived_stage_budget_anchor():
    region = _region(_card_text())
    anchor = foundry.STAGE_BUDGET_PREFIX
    assert isinstance(anchor, str) and anchor.strip(), "STAGE_BUDGET_PREFIX must be a real string"
    assert anchor in region, (
        f"{SECTION_MARKER} region must cite the anchor foundry.STAGE_BUDGET_PREFIX ({anchor!r}) "
        "so the card and the shipped line cannot drift apart"
    )


def test_behavior1_negative_control_near_miss_anchor_is_absent():
    """Derived, never spelled: the plural near-miss of the shipped prefix must NOT appear."""
    near_miss = foundry.STAGE_BUDGET_PREFIX.replace(":", "s:")
    assert near_miss != foundry.STAGE_BUDGET_PREFIX, "near-miss construction is vacuous"
    assert near_miss not in _card_text(), (
        f"card must cite the exact shipped prefix, not the near-miss {near_miss!r}"
    )


# --------------------------------------------------------------------------- behavior 2

def test_behavior2_advisory_clause_shares_the_region_with_the_anchor():
    region = _region(_card_text())
    assert foundry.STAGE_BUDGET_PREFIX in region, "precondition: anchor is in the region"
    assert "ADVISORY" in region, (
        "the requirement and its safety clause must live in ONE region: the uppercase token "
        "ADVISORY is missing from the Size self-check region"
    )


# --------------------------------------------------------------------------- behavior 3

def test_behavior3_region_carries_an_invocable_form_and_the_path_convention():
    region = _region(_card_text())
    invocation = "foundry.py doctor --config"
    assert invocation in region, f"region must show the invocable form {invocation!r}"
    assert "PRODUCT_CONFIG" in region, (
        "region must name PRODUCT_CONFIG -- the verified-path convention the card already uses"
    )


# --------------------------------------------------------------------------- behavior 4

def test_behavior4_doctor_is_a_routable_verb_delegating_to_run_doctor_cli(tmp_path, monkeypatch):
    cfg_path = _write_cfg(tmp_path, name="probeprod")
    seen: list = []

    def _spy(cfg):
        seen.append(cfg)
        return 7

    monkeypatch.setattr(foundry, "run_doctor_cli", _spy)
    rc = foundry.main(["doctor", "--config", str(cfg_path)])
    assert rc == 7, f"main must return run_doctor_cli's value, got {rc!r}"
    assert len(seen) == 1, f"run_doctor_cli must be called exactly once, got {len(seen)}"
    assert isinstance(seen[0], foundry.ProductConfig), (
        f"doctor must receive a ProductConfig, got {type(seen[0]).__name__}"
    )
    assert seen[0].name == "probeprod", f"wrong config routed: {seen[0].name!r}"


def test_behavior4_two_sided_unknown_verb_is_rejected(tmp_path):
    cfg_path = _write_cfg(tmp_path)
    typo = "doctor" + "x"
    with pytest.raises(SystemExit) as exc:
        foundry.main([typo, "--config", str(cfg_path)])
    assert exc.value.code == 2, f"argparse must reject {typo!r} with code 2, got {exc.value.code!r}"


# --------------------------------------------------------------------------- behavior 5

def _assert_one_prefixed_line(line, label):
    assert isinstance(line, str), f"{label}: expected str, got {type(line).__name__}"
    assert line.strip(), f"{label}: line must be non-empty"
    assert "\n" not in line, f"{label}: must be ONE line, got {line!r}"
    assert line.startswith(foundry.STAGE_BUDGET_PREFIX), (
        f"{label}: must start with {foundry.STAGE_BUDGET_PREFIX!r}, got {line!r}"
    )


def test_behavior5_stage_budget_line_is_total_for_a_missing_log(tmp_path):
    cfg = _cfg(tmp_path)
    missing = tmp_path / "no-such-dispatcher.out"
    assert not missing.exists(), "precondition: the log path must not exist"
    _assert_one_prefixed_line(foundry.stage_budget_line(cfg, log_path=missing), "missing log")


def test_behavior5_stage_budget_line_is_total_for_unparsable_text(tmp_path):
    cfg = _cfg(tmp_path)
    junk = tmp_path / "junk.out"
    junk.write_text("not a dispatcher log\n\x00\x01 lorem ipsum 12345\n" * 3, encoding="utf-8",
                    errors="replace")
    _assert_one_prefixed_line(foundry.stage_budget_line(cfg, log_path=junk), "unparsable log")


def test_behavior5_stage_budget_line_is_total_when_the_gatherer_raises(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    log = tmp_path / "any.out"
    log.write_text("whatever\n", encoding="utf-8")

    def _boom(*a, **k):
        raise RuntimeError("gatherer exploded")

    monkeypatch.setattr(foundry, "gather_stage_times", _boom)
    _assert_one_prefixed_line(foundry.stage_budget_line(cfg, log_path=log), "raising gatherer")


# --------------------------------------------------------------------------- behavior 6

_SENTINELS = {name: f"{name}-SENTINEL-{THIS_ITER}" for name in DRIFT_LINE_HELPERS}


def _offline_doctor(monkeypatch, failing: str | None):
    """Force every probe and every drift line offline.  `failing` names the ONE probe that fails."""
    for seam in PROBE_SEAMS:
        ok = seam != failing
        detail = "(unset)" if not ok else "fine"
        monkeypatch.setattr(
            foundry, seam,
            (lambda *a, _s=seam, _ok=ok, _d=detail, **k: foundry.Check(_s, _ok, _d)),
        )
    for name, sentinel in _SENTINELS.items():
        monkeypatch.setattr(foundry, name, (lambda *a, _v=sentinel, **k: _v))


def test_behavior6_one_failing_probe_yields_nonzero_but_still_prints_the_drift_line(
        tmp_path, monkeypatch, capsys):
    cfg = _cfg(tmp_path)
    _offline_doctor(monkeypatch, failing="check_agent")
    rc = foundry.run_doctor_cli(cfg)
    out = capsys.readouterr().out
    assert isinstance(rc, int) and rc != 0, (
        f"a FAILING environment probe must make doctor exit nonzero, got {rc!r}"
    )
    assert _SENTINELS["stage_budget_line"] in out, (
        "the stage-budget drift line must still be reported when a probe fails -- otherwise the "
        f"card's ADVISORY advice is unsound. stdout was: {out!r}"
    )


def test_behavior6_two_sided_all_probes_passing_yields_zero_and_the_same_line(
        tmp_path, monkeypatch, capsys):
    cfg = _cfg(tmp_path)
    _offline_doctor(monkeypatch, failing=None)
    rc = foundry.run_doctor_cli(cfg)
    out = capsys.readouterr().out
    assert rc == 0, f"all probes passing must exit 0, got {rc!r}"
    assert _SENTINELS["stage_budget_line"] in out, (
        f"the stage-budget drift line must be reported on the green path too: {out!r}"
    )


# --------------------------------------------------------------------------- behavior 7

def test_behavior7_the_edit_is_additive_not_a_rewrite():
    text = _card_text()
    region = _region(text)
    for token in ("lint-spec", "SPEC_MAX_BEHAVIORS"):
        assert token in region, (
            f"pre-existing Size self-check content {token!r} was displaced -- the new text must be "
            "ADDED inside the section, deleting nothing"
        )
    assert "WRITE-EARLY (checkpoint-first)" in text, (
        "the card's WRITE-EARLY head must survive this iteration untouched"
    )


# --------------------------------------------------------------------------- behavior 8

def test_behavior8_region_is_repo_agnostic_and_public_safe():
    region = _region(_card_text())
    for machine_path in ("/Users" + "/", "/home" + "/"):
        assert machine_path not in region, (
            f"a shared role card must carry no machine path, found {machine_path!r}"
        )
    names = _product_names()
    assert "_platform" in names, (
        "anti-vacuous control: the tracked _platform config must be discoverable, "
        f"got {sorted(names)!r}"
    )
    for name in sorted(names):
        assert name not in region, (
            f"every product shares this card, so the product-specific name {name!r} must not "
            "appear in the Size self-check region"
        )


# --------------------------------------------------------------------------- behavior 9

def test_behavior9_the_card_points_at_a_read_only_verb_only():
    region = _region(_card_text())
    prefix = "foundry" + ".py "
    assert prefix + "doctor" in region, "region must name the read-only doctor verb"
    for verb in ("run", "once", "agents"):
        assert prefix + verb not in region, (
            f"the card must not invoke {prefix + verb!r}: it is registered in the same argparse "
            "loop as doctor but is NOT read-only (loop-launching, or it plants an unignored file)"
        )
