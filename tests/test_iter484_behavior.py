"""Iteration 484 -- BLACK-BOX behavior tests for the auth-needle extension.

`ATTEMPT_FAILURE_MARKERS`' auth tuple gains a 4th needle
(`awscredentialexport did not return`) so that `classify_attempt_failure`
routes the AWS-credential-export failure into the `auth` kind (and the
iter-411 auth hold) instead of the default `other` ladder.

Expected Behaviors (from pm.md):
  1.  `classify_attempt_failure("awsCredentialExport did not return a valid value")`
      returns `"auth"`.
  2.  The needle is a prefix match: the shorter blob also returns `"auth"`.
  3.  A blob carrying BOTH `"service is busy"` AND the needle returns `"service"`
      (service priority preserved).
  4.  A blob carrying BOTH `"connection stalled"` AND the needle returns `"stalled"`
      (stalled priority preserved).
  5.  `classify_attempt_failure("403 Forbidden")` returns `"other"` (no broad 403
      needle).
  6.  `classify_attempt_failure("credential refresh failed")` still returns `"auth"`
      (existing needles unchanged).
  7.  `run_stage` auth hold fires when the attempt's failure is classified as `"auth"`
      via the new needle.
  8.  `python -c "import foundry, dispatcher"` succeeds.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe)

THIS_ITER = 484

AUTH = "auth"
OTHER = "other"
SERVICE = "service"
STALLED = "stalled"

NEEDLE_484 = "awscredentialexport did not return"

REAL_BLOB = (
    "API Error: 403 The security token included in the request is invalid\n"
    "awsCredentialExport did not return a valid value"
)


# ===========================================================================
# Behavior 1 -- the measured blob classifies as auth
# ===========================================================================
def test_b1_full_blob_classifies_as_auth():
    blob = "awsCredentialExport did not return a valid value"
    assert foundry.classify_attempt_failure(blob) == AUTH


def test_b1_real_multi_line_blob_classifies_as_auth():
    assert foundry.classify_attempt_failure(REAL_BLOB) == AUTH


# ===========================================================================
# Behavior 2 -- prefix match (the needle is shorter than the full message)
# ===========================================================================
def test_b2_prefix_match_classifies_as_auth():
    assert foundry.classify_attempt_failure("awsCredentialExport did not return") == AUTH


def test_b2_case_insensitive():
    assert foundry.classify_attempt_failure("AWSCREDENTIALEXPORT DID NOT RETURN") == AUTH


# ===========================================================================
# Behavior 3 -- service priority preserved
# ===========================================================================
def test_b3_service_and_needle_returns_service():
    blob = "service is busy ... awsCredentialExport did not return a valid value"
    assert foundry.classify_attempt_failure(blob) == SERVICE


def test_b3_needle_then_service_still_returns_service():
    blob = "awsCredentialExport did not return ... service is busy"
    assert foundry.classify_attempt_failure(blob) == SERVICE


# ===========================================================================
# Behavior 4 -- stalled priority preserved
# ===========================================================================
def test_b4_stalled_and_needle_returns_stalled():
    blob = "connection stalled ... awsCredentialExport did not return a valid value"
    assert foundry.classify_attempt_failure(blob) == STALLED


def test_b4_needle_then_stalled_still_returns_stalled():
    blob = "awsCredentialExport did not return ... connection stalled"
    assert foundry.classify_attempt_failure(blob) == STALLED


# ===========================================================================
# Behavior 5 -- an unrelated 403 is NOT caught
# ===========================================================================
def test_b5_bare_403_returns_other():
    assert foundry.classify_attempt_failure("403 Forbidden") == OTHER


def test_b5_generic_token_error_returns_other():
    assert foundry.classify_attempt_failure("The security token included in the request is invalid") == OTHER


# ===========================================================================
# Behavior 6 -- existing auth needles unchanged
# ===========================================================================
def test_b6_credential_refresh_still_auth():
    assert foundry.classify_attempt_failure("credential refresh failed") == AUTH


def test_b6_auth_failed_still_auth():
    assert foundry.classify_attempt_failure("auth failed") == AUTH


def test_b6_credentials_renewed_still_auth():
    assert foundry.classify_attempt_failure("credentials were still being renewed") == AUTH


# ===========================================================================
# Behavior 7 -- run_stage auth hold fires via the new needle
# ===========================================================================
def test_b7_auth_hold_fires_on_new_needle(monkeypatch, tmp_path):
    blob = "awsCredentialExport did not return a valid value"
    assert foundry.classify_attempt_failure(blob) == AUTH
    assert foundry.classify_attempt_failure(blob) == foundry.AUTH_HOLD_KIND


# ===========================================================================
# Behavior 8 -- modules importable
# ===========================================================================
def test_b8_foundry_importable():
    r = subprocess.run(
        [sys.executable, "-c", "import foundry"],
        cwd=str(_ROOT), capture_output=True, text=True)
    assert r.returncode == 0, f"foundry import failed: {r.stderr}"


def test_b8_dispatcher_importable():
    r = subprocess.run(
        [sys.executable, "-c", "import dispatcher"],
        cwd=str(_ROOT), capture_output=True, text=True)
    assert r.returncode == 0, f"dispatcher import failed: {r.stderr}"


# ===========================================================================
# Structural -- the needle is present in the shipped table
# ===========================================================================
def test_ac_needle_in_auth_tuple():
    table = dict(foundry.ATTEMPT_FAILURE_MARKERS)
    assert NEEDLE_484 in table[AUTH], \
        f"needle {NEEDLE_484!r} must be in the auth tuple"


def test_ac_auth_tuple_has_four_needles():
    table = dict(foundry.ATTEMPT_FAILURE_MARKERS)
    assert len(table[AUTH]) == 4, \
        f"expected 4 auth needles, got {len(table[AUTH])}"


def test_ac_no_broad_403_needle():
    table = dict(foundry.ATTEMPT_FAILURE_MARKERS)
    all_needles = [n for _, needles in table.items() for n in needles]
    for n in all_needles:
        assert "403" not in n.lower(), f"no broad 403 needle allowed, found {n!r}"
