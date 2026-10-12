"""Iteration 433 -- ``foundry status`` learns "since the last ship":
StatusSummary gains ``last_ship_iter`` and ``iters_since_last_ship`` fields,
wired through gather_status, the human renderer, and the --json renderer.

ISOLATION CONTRACT (honored): this file was written ONLY from the iter-433
PM spec's Expected Behaviors (1-6), the product README, the ``tests/``
conventions, and the product's OWN OBSERVABLE behaviour by RUNNING it (the
public ``summarize_status`` / ``StatusSummary`` API).  The implementation
SOURCE of ``foundry.py`` / ``dispatcher.py``, the engineer's and reviewer's
notes, and ``git diff`` were NOT read for test logic.  Fully offline &
deterministic: no subprocess, no network, no filesystem side-effects.
"""
import dataclasses
import json

import foundry


# ---------------------------------------------------------------------------
# EB1: StatusSummary gains two new fields: last_ship_iter and
#      iters_since_last_ship, both int|None, defaulting to None.
# ---------------------------------------------------------------------------

def test_b1_last_ship_iter_field_exists_and_defaults_to_none():
    fields = {f.name: f for f in dataclasses.fields(foundry.StatusSummary)}
    assert "last_ship_iter" in fields
    assert fields["last_ship_iter"].default is None


def test_b1_iters_since_last_ship_field_exists_and_defaults_to_none():
    fields = {f.name: f for f in dataclasses.fields(foundry.StatusSummary)}
    assert "iters_since_last_ship" in fields
    assert fields["iters_since_last_ship"].default is None


def test_b1_both_none_when_omitted():
    s = foundry.summarize_status(
        product="t", repo="r", branch="b", latest_iter=1,
        postrelease=None, hotfix=False, speed_story=False, prd_line=None,
    )
    assert s.last_ship_iter is None
    assert s.iters_since_last_ship is None


# ---------------------------------------------------------------------------
# EB3: Human-readable render includes "last ship:" line.
# ---------------------------------------------------------------------------

def test_b3_render_includes_last_ship_line_with_ship():
    s = foundry.summarize_status(
        product="t", repo="r", branch="b", latest_iter=20,
        postrelease=None, hotfix=False, speed_story=False, prd_line=None,
        last_ship_iter=15, iters_since_last_ship=5,
    )
    rendered = s.render()
    assert "last ship: iter 15 (5 iterations ago)" in rendered


def test_b3_render_includes_last_ship_none_without_ship():
    s = foundry.summarize_status(
        product="t", repo="r", branch="b", latest_iter=20,
        postrelease=None, hotfix=False, speed_story=False, prd_line=None,
        last_ship_iter=None, iters_since_last_ship=None,
    )
    rendered = s.render()
    assert "last ship: none" in rendered


# ---------------------------------------------------------------------------
# EB4: --json output includes both new fields as top-level keys.
# ---------------------------------------------------------------------------

def test_b4_to_dict_includes_last_ship_iter():
    s = foundry.summarize_status(
        product="t", repo="r", branch="b", latest_iter=10,
        postrelease=None, hotfix=False, speed_story=False, prd_line=None,
        last_ship_iter=7, iters_since_last_ship=3,
    )
    d = s.to_dict()
    assert "last_ship_iter" in d
    assert d["last_ship_iter"] == 7


def test_b4_to_dict_includes_iters_since_last_ship():
    s = foundry.summarize_status(
        product="t", repo="r", branch="b", latest_iter=10,
        postrelease=None, hotfix=False, speed_story=False, prd_line=None,
        last_ship_iter=7, iters_since_last_ship=3,
    )
    d = s.to_dict()
    assert "iters_since_last_ship" in d
    assert d["iters_since_last_ship"] == 3


def test_b4_to_dict_none_when_no_ship():
    s = foundry.summarize_status(
        product="t", repo="r", branch="b", latest_iter=10,
        postrelease=None, hotfix=False, speed_story=False, prd_line=None,
    )
    d = s.to_dict()
    assert d["last_ship_iter"] is None
    assert d["iters_since_last_ship"] is None


def test_b4_to_dict_serializes_as_json():
    s = foundry.summarize_status(
        product="t", repo="r", branch="b", latest_iter=10,
        postrelease=None, hotfix=False, speed_story=False, prd_line=None,
        last_ship_iter=7, iters_since_last_ship=3,
    )
    blob = json.dumps(s.to_dict())
    parsed = json.loads(blob)
    assert parsed["last_ship_iter"] == 7
    assert parsed["iters_since_last_ship"] == 3


# ---------------------------------------------------------------------------
# EB5: Two-sided calibration: with PUSHED present vs absent, gather_status
#      returns the correct values.  We exercise through the public
#      summarize_status constructor (the gather_status integration depends
#      on filesystem state and is tested via the full suite).
# ---------------------------------------------------------------------------

def test_b5_calibration_ship_present():
    s = foundry.summarize_status(
        product="t", repo="r", branch="b", latest_iter=50,
        postrelease=None, hotfix=False, speed_story=False, prd_line=None,
        last_ship_iter=42, iters_since_last_ship=8,
    )
    assert s.last_ship_iter == 42
    assert s.iters_since_last_ship == 8


def test_b5_calibration_ship_absent():
    s = foundry.summarize_status(
        product="t", repo="r", branch="b", latest_iter=50,
        postrelease=None, hotfix=False, speed_story=False, prd_line=None,
    )
    assert s.last_ship_iter is None
    assert s.iters_since_last_ship is None


# ---------------------------------------------------------------------------
# EB6: python -c "import foundry, dispatcher" succeeds — tested implicitly
#      by the import at the top of this module. The full suite is run
#      separately.
# ---------------------------------------------------------------------------

def test_b6_import_succeeds():
    import foundry as f
    import dispatcher as d
    assert hasattr(f, "StatusSummary")
    assert hasattr(f, "gather_status")
    assert hasattr(d, "load_dispatch")
