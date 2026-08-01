"""Black-box behaviour tests for iter 65 -- roadmap item 18, bite 2 of 3.

This bite is PURE DATA + DOCS (zero foundry.py/dispatcher.py/scripts change):
it mints the missing core-seat bench card `roles/bench/reviewer.md` (the 12th
card -- the ACTIVE code-Reviewer seat; the adjacent `product_gate_pm.md` is the
DORMANT adversarial product-gate reviewer, a DIFFERENT seat) and ships an example
staffing manifest `products/repolens/staffing.json`, so a real five-core-seat
manifest passes BOTH `foundry lint-bench` AND `foundry lint-manifest` against the
DEFAULT bench. The validators + schema already shipped in bites earlier (lint-bench
iter 63, lint-manifest iter 64); this bite only ADDS the data those linters consume.

ISOLATION CONTRACT (honored): every test below encodes the iter-65 PM spec's
Expected Behaviors (1-9) and is driven purely against the PUBLIC interface -- the
REAL shipped artifacts read via `pathlib.Path(foundry.__file__).parent` and the
ALREADY-SHIPPED pure cores `foundry.lint_bench_card`/`foundry.lint_bench`/
`foundry.lint_manifest` + their CLI wrappers + `foundry.main([...])`, plus the
committed `scripts/leak_guard.py` public API and the documented
`import foundry, dispatcher` subprocess probe. The implementation SOURCE
(foundry.py / dispatcher.py logic), the engineer's and reviewer's notes, and
`git diff` were NOT read as logic to mirror; assertions encode the SPEC's
behaviors, not impl quirks. Fully offline & deterministic: no network, no real
push. Every path is built at RUNTIME from `foundry.__file__` (never a
source-literal home path), so the committed leak-guard passes on the ship commit.
"""
import importlib.util
import json
import pathlib
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
BENCH_DIR = _ROOT / "roles" / "bench"
CARD_PATH = BENCH_DIR / "reviewer.md"
MANIFEST_PATH = _ROOT / "products" / "repolens" / "staffing.json"
# the five always-on core seats in the fixed run order the spec pins
CORE_SEATS = ["product_manager", "engineer", "reviewer", "qa_tester", "release_gate"]

_GIT_OK = subprocess.run(
    ["git", "rev-parse", "--is-inside-work-tree"],
    cwd=str(_ROOT), capture_output=True, text=True,
).returncode == 0


def _manifest():
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _leak_guard():
    """Dynamically import the committed leak-guard, registering the module in
    sys.modules BEFORE exec so its own relative-import machinery works."""
    gp = _ROOT / "scripts" / "leak_guard.py"
    spec = importlib.util.spec_from_file_location("leak_guard_iter65_probe", gp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------
# B1 -- the card exists and is a readable UTF-8 text file
# --------------------------------------------------------------------------
def test_b1_card_exists_and_readable_utf8():
    assert CARD_PATH.exists() and CARD_PATH.is_file()
    txt = CARD_PATH.read_text(encoding="utf-8")
    assert txt.strip(), "reviewer.md is empty"


# --------------------------------------------------------------------------
# B2 -- the card satisfies the fixed 7-marker card contract
# --------------------------------------------------------------------------
def test_b2_card_passes_lint_bench_card():
    txt = CARD_PATH.read_text(encoding="utf-8")
    assert foundry.lint_bench_card(txt, card="reviewer.md") == ()


def test_b2_card_has_each_of_the_seven_markers():
    txt = CARD_PATH.read_text(encoding="utf-8")
    lines = txt.splitlines()
    # title = the FIRST H1; its stripped form must start with the fixed prefix.
    # A `## ` heading is not an H1, so it can never be mistaken for the title.
    h1 = next((l.strip() for l in lines if l.strip().startswith("# ")), None)
    assert h1 is not None and h1.startswith("# Bench role card:"), repr(h1)
    # Status: / Model note: are line-START markers
    assert any(l.strip().startswith("Status:") for l in lines)
    assert any(l.strip().startswith("Model note:") for l in lines)
    # Activation: / Tenure: are raw SUBSTRINGS (they live inline on the Status: line)
    assert "Activation:" in txt
    assert "Tenure:" in txt
    # ## Mission / ## I/O contract are EXACT headings
    assert any(l.strip() == "## Mission" for l in lines)
    assert any(l.strip() == "## I/O contract" for l in lines)


# --------------------------------------------------------------------------
# B3 -- lint-bench stays green with 12 cards; no prior card perturbed
# --------------------------------------------------------------------------
def test_b3_lint_bench_default_twelve_cards_clean():
    bl = foundry.lint_bench(str(BENCH_DIR))
    assert bl.cards_scanned == 12
    assert "README.md" in bl.skipped
    assert bl.findings == ()
    assert bl.parse_errors == ()
    assert bl.clean is True
    assert bl.exit_code == 0
    assert bl.to_dict()["verdict"] == "OK"


def test_b3_lint_bench_cli_default_returns_zero():
    assert foundry.lint_bench_cli(bench_dir=None) == 0


def test_b3_every_bench_card_passes_individually():
    cards = sorted(p for p in BENCH_DIR.glob("*.md") if p.name != "README.md")
    names = [p.name for p in cards]
    assert len(cards) == 12, names
    assert "reviewer.md" in names
    for p in cards:
        assert foundry.lint_bench_card(p.read_text(encoding="utf-8"), card=p.name) == (), p.name


# --------------------------------------------------------------------------
# B4 -- the manifest exists and parses to a JSON object
# --------------------------------------------------------------------------
def test_b4_manifest_exists_and_is_dict():
    assert MANIFEST_PATH.exists() and MANIFEST_PATH.is_file()
    assert isinstance(_manifest(), dict)


# --------------------------------------------------------------------------
# B5 -- the manifest is schema-valid (strict bool / strict int discipline)
# --------------------------------------------------------------------------
def test_b5_manifest_is_schema_valid():
    m = _manifest()
    assert isinstance(m["product"], str) and m["product"]
    ib = m["iteration_budget"]
    assert type(ib) is int and ib > 0          # NOT a bool (bool subclasses int)
    assert type(ib) is not bool
    roles = m["roles"]
    assert isinstance(roles, list) and roles
    for r in roles:
        assert isinstance(r, dict)
        assert isinstance(r["role"], str) and r["role"]
        assert isinstance(r["model"], str) and r["model"]
        assert type(r["gate"]) is bool         # strict bool, never int 1/0
        assert isinstance(r["done_criteria"], str) and r["done_criteria"]


def test_b5_product_is_repolens():
    assert _manifest()["product"] == "repolens"


# --------------------------------------------------------------------------
# B6 -- the five core seats are staffed in run order and every one is carded
# --------------------------------------------------------------------------
def test_b6_five_core_seats_in_run_order():
    assert [r["role"] for r in _manifest()["roles"]] == CORE_SEATS


def test_b6_every_named_seat_has_a_bench_card():
    for name in CORE_SEATS:
        assert (BENCH_DIR / f"{name}.md").exists(), name


# --------------------------------------------------------------------------
# B7 -- lint-manifest is clean against the DEFAULT bench
# --------------------------------------------------------------------------
def test_b7_lint_manifest_clean_against_default_bench():
    ml = foundry.lint_manifest(
        _manifest(), str(BENCH_DIR),
        manifest_path="products/repolens/staffing.json",
    )
    assert ml.findings == ()
    assert ml.clean is True
    assert ml.core_seats_present is True
    assert ml.exit_code == 0
    assert ml.to_dict()["verdict"] == "OK"


def test_b7_lint_manifest_cli_default_returns_zero():
    assert foundry.lint_manifest_cli(str(MANIFEST_PATH), bench_dir=None) == 0


def test_b7_main_end_to_end_both_linters_green():
    assert foundry.main(["lint-bench"]) == 0
    assert foundry.main(["lint-manifest", "--file", str(MANIFEST_PATH)]) == 0


# --------------------------------------------------------------------------
# B8 -- purely additive; NO code change; imports still clean
#
# NB: this data+docs feature touches NO code. The routinely-extended main module
# is byte-unchanged THIS iteration (verified out-of-band: its `git diff --numstat
# HEAD` is empty), but a PERMANENT test may NOT pin that file as byte-unchanged --
# it would break the next iteration that extends it (the iter-54 invariant).
# .gitignore is likewise unchanged this iter but is excluded from the standing
# assertion because iterations legitimately add ignore entries for new runtime
# artifacts. What IS durable: the control path (dispatcher.py + the guard scripts)
# stays byte-unchanged, and both modules still import.
# --------------------------------------------------------------------------
@pytest.mark.skipif(not _GIT_OK, reason="not inside a git work tree")
def test_b8_control_path_byte_unchanged_from_head():
    r = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", "dispatcher.py", "scripts/"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, "dispatcher.py / scripts NOT byte-unchanged from HEAD"


def test_b8_import_foundry_and_dispatcher():
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


# --------------------------------------------------------------------------
# B9 -- leak-safety (ship-blocker): both artifacts clean under an ARMED matcher
# --------------------------------------------------------------------------
def test_b9_artifacts_leak_clean_with_armed_matcher():
    mod = _leak_guard()
    denylist = mod.load_denylist(mod.DENYLIST_PATH.read_text())
    for path in (CARD_PATH, MANIFEST_PATH):
        assert mod.scan_text(path.read_text(encoding="utf-8"), denylist) == (), path.name
    # prove the matcher is ARMED (not inert -> false-clean): a RUNTIME-built
    # home-path needle MUST be flagged. Never a source-literal home path.
    needle = "/" + "Users" + "/" + "nobody/secret.txt"
    assert mod.scan_text(needle, denylist), "leak matcher is inert (false-clean risk)"
