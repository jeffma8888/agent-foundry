"""Black-box behaviour tests for iter 66 -- roadmap item 18, bite 3 of 3
(which COMPLETES item 18).

This bite is PURE DOCS (zero code change): it ships the static, committed
trigger-rubric doc `docs/TRIGGER_RUBRIC.md`, which maps each observable product
trait to the bench role that trait activates -- the mechanical, auditable
staffing aid the kickoff council uses (docs/ORG_DESIGN.md section 5). The
validators it leans on already shipped (lint_bench_card whole-run; lint-bench
iter 63; lint-manifest iter 64) and the referenced cards + example manifest
landed in bites 1-2 (iters 64-65); this bite only ADDS a doc that INDEXES the
already-valid bench cards. There is deliberately NO new `lint-rubric` CLI: the
"mechanical/auditable" property is enforced HERE by the tests (every referenced
card exists AND passes the already-shipped lint_bench_card), not by new runtime
code.

ISOLATION CONTRACT (honored): every test below encodes the iter-66 PM spec's
Expected Behaviors (1-11) and is driven purely against the PUBLIC interface --
the REAL shipped doc read via `pathlib.Path(foundry.__file__).parent` and the
ALREADY-SHIPPED pure core `foundry.lint_bench_card`, plus the committed
`scripts/leak_guard.py` public API and the documented `import foundry, dispatcher`
subprocess probe. The implementation SOURCE (foundry.py / dispatcher.py logic),
the engineer's and reviewer's notes, and `git diff` text were NOT read as logic
to mirror; assertions encode the SPEC's behaviors, not impl quirks. Fully
offline & deterministic: no network, no real push. Every path is built at
RUNTIME from `foundry.__file__` (never a source-literal home path), so the
committed leak-guard passes on the ship commit.

NB on Behavior 11: this pure-docs bite touches NO code. The routinely-extended
main module is byte-unchanged THIS iteration (verified out-of-band by the
reviewer / final gate: its `git diff --numstat HEAD` is empty, as is
`.gitignore`), but a PERMANENT test may NOT pin that file as byte-unchanged --
the shipped iter-54 meta-scanner bans it because that file grows nearly every
iteration (a latent suite-breaker). What IS durable and pinned here: the control
path (dispatcher.py + the guard scripts) stays byte-unchanged, and both modules
still import.
"""
import importlib.util
import pathlib
import re
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (dormancy / import-safety probe)


# --------------------------------------------------------------------------
# runtime-built paths (never a source-literal home path)
# --------------------------------------------------------------------------
_ROOT = pathlib.Path(foundry.__file__).resolve().parent
DOC_PATH = _ROOT / "docs" / "TRIGGER_RUBRIC.md"
BENCH_DIR = _ROOT / "roles" / "bench"
# the four trigger-activated specialist bench roles the rubric maps
SPECIALIST_ROLES = ("designer", "legal", "devrel_docs", "tpm")
BENCH_REF_RE = re.compile(r"roles/bench/[a-z_]+\.md")

_GIT_OK = subprocess.run(
    ["git", "rev-parse", "--is-inside-work-tree"],
    cwd=str(_ROOT), capture_output=True, text=True,
).returncode == 0


def _doc_text():
    return DOC_PATH.read_text(encoding="utf-8")


def _leak_guard():
    """Dynamically import the committed leak-guard, registering the module in
    sys.modules BEFORE exec so its own relative-import machinery works."""
    gp = _ROOT / "scripts" / "leak_guard.py"
    spec = importlib.util.spec_from_file_location("leak_guard_iter66_probe", gp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------
# B1 -- the doc exists and is a readable, non-empty UTF-8 text file
# --------------------------------------------------------------------------
def test_b1_doc_exists_and_non_empty():
    assert DOC_PATH.exists() and DOC_PATH.is_file()
    assert len(_doc_text()) > 0, "TRIGGER_RUBRIC.md is empty"


# --------------------------------------------------------------------------
# B2 -- well-formed H1 title mentioning "trigger rubric"
# --------------------------------------------------------------------------
def test_b2_first_line_is_h1_trigger_rubric():
    first = next((l.strip() for l in _doc_text().splitlines() if l.strip()), "")
    assert first.startswith("# "), repr(first)
    assert "trigger rubric" in first.lower(), repr(first)


# --------------------------------------------------------------------------
# B3 -- maps all four canonical specialist roles (verbatim path tokens)
# --------------------------------------------------------------------------
def test_b3_maps_all_four_specialist_role_tokens():
    text = _doc_text()
    for name in SPECIALIST_ROLES:
        assert f"roles/bench/{name}.md" in text, name


# --------------------------------------------------------------------------
# B4 -- no dangling bench reference: EXACTLY four refs, all resolving
# --------------------------------------------------------------------------
def test_b4_no_dangling_bench_reference():
    refs = BENCH_REF_RE.findall(_doc_text())
    assert len(refs) == 4, refs
    # the four are exactly the specialist set (order-independent)
    assert set(refs) == {f"roles/bench/{n}.md" for n in SPECIALIST_ROLES}, refs
    for ref in refs:
        assert (_ROOT / ref).exists(), f"dangling bench reference: {ref}"


# --------------------------------------------------------------------------
# B5 -- every referenced card is a VALID bench card (7-marker contract)
# --------------------------------------------------------------------------
def test_b5_every_referenced_card_passes_lint_bench_card():
    for name in SPECIALIST_ROLES:
        card = BENCH_DIR / f"{name}.md"
        assert card.exists(), name
        res = foundry.lint_bench_card(card.read_text(encoding="utf-8"),
                                      card=f"{name}.md")
        assert res == (), f"{name}.md failed lint_bench_card: {res}"


# --------------------------------------------------------------------------
# B6 -- trait keywords present (one per specialist row)
# --------------------------------------------------------------------------
def test_b6_trait_keywords_present():
    text = _doc_text()
    for kw in ("human-facing surface", "user data", "public API", "module"):
        assert kw in text, kw


# --------------------------------------------------------------------------
# B7 -- names the kickoff council + staffing manifest
# --------------------------------------------------------------------------
def test_b7_names_kickoff_council_and_manifest():
    text = _doc_text()
    assert "kickoff council" in text
    assert "staffing.json" in text
    assert "staffing manifest" in text


# --------------------------------------------------------------------------
# B8 -- forward-points to the runtime item (item 19)
# --------------------------------------------------------------------------
def test_b8_forward_points_to_item_19():
    assert "item 19" in _doc_text()


# --------------------------------------------------------------------------
# B9 -- pure ASCII (no non-ASCII bytes)
# --------------------------------------------------------------------------
def test_b9_doc_is_pure_ascii():
    offenders = [(i, c) for i, c in enumerate(_doc_text()) if ord(c) >= 128]
    assert offenders == [], f"non-ASCII characters present: {offenders[:5]}"


# --------------------------------------------------------------------------
# B10 -- leak-clean (ship-blocker) under an ARMED matcher
# --------------------------------------------------------------------------
def test_b10_doc_leak_clean_with_armed_matcher():
    mod = _leak_guard()
    denylist = mod.load_denylist(mod.DENYLIST_PATH.read_text())
    assert mod.scan_text(_doc_text(), denylist) == (), "doc contains a denylisted token"
    # prove the matcher is ARMED (not inert -> false-clean): a RUNTIME-built
    # home-path needle MUST be flagged. Never a source-literal home path.
    needle = "/" + "Users" + "/" + "nobody/secret.txt"
    assert mod.scan_text(needle, denylist), "leak matcher is inert (false-clean risk)"


# --------------------------------------------------------------------------
# B11 -- zero code change (durable control-path pin + import)
#
# This data+docs feature touches NO code. The routinely-extended main module is
# byte-unchanged THIS iteration (verified out-of-band: its `git diff --numstat
# HEAD` is empty), but a PERMANENT test may NOT pin that file as byte-unchanged
# -- it would break the next iteration that extends it (the iter-54 invariant).
# .gitignore is likewise unchanged this iter but is excluded from the standing
# assertion because iterations legitimately add ignore entries for new runtime
# artifacts. What IS durable: the control path (dispatcher.py + the guard
# scripts) stays byte-unchanged, and both modules still import.
# --------------------------------------------------------------------------
@pytest.mark.skipif(not _GIT_OK, reason="not inside a git work tree")
def test_b11_control_path_byte_unchanged_from_head():
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
