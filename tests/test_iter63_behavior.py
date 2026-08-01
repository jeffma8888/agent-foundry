"""Black-box behaviour tests for iter 63 -- the NEW read-only
`foundry lint-bench [--dir <path>] [--json]` bench role-card linter.

It validates every hand-written role-card in `roles/bench/*.md` against the
fixed 7-marker card contract (title + `Status:`/`Activation:`/`Tenure:`/
`Model note:` header fields + `## Mission` and `## I/O contract` sections),
reporting `card:line` findings with a scriptable 0/1/2 exit code and an optional
`--json` document. It is the BENCH-facing sibling of `doctor` (#0 env),
`lint-spec` (#6 spec), and `lint-config` (#27 config). Purely additive / dormant.

ISOLATION CONTRACT (honored): every test below encodes the iter-63 PM spec's
Expected Behaviors (1-16) and is driven purely against the PUBLIC interface --
the pure `foundry.lint_bench_card(text, card=...)` core over SYNTHETIC card
strings, the `foundry.lint_bench(bench_dir)` dir-walker over tmp `.md` dirs, the
`BenchLint` dataclass properties / `render()` / `to_dict()`, the
`foundry.lint_bench_cli(...)` / `foundry.main(["lint-bench", ...])` CLI, plus
public RUNTIME introspection (compiled `__code__.co_names`, `dispatcher`
attributes) and the documented `import foundry, dispatcher` subprocess probe.
The implementation SOURCE (foundry.py / dispatcher.py logic), the engineer's and
reviewer's notes, and `git diff` were NOT read as logic to mirror; assertions
encode the SPEC's behaviors, not impl quirks. Fully offline & deterministic: no
network, no git subprocess, no real push; the sole subprocess is the
`import foundry, dispatcher` dormancy probe. Every card string is SYNTHETIC and
every path is built at RUNTIME from the pytest `tmp_path` fixture (never a
source-literal home path), so the committed leak-guard passes on the ship commit.
"""
import io
import json
import os
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402


# --------------------------------------------------------------------------
# constants / helpers
# --------------------------------------------------------------------------
NEW_SYMBOLS = ("BenchCardFinding", "BenchLint", "lint_bench_card",
               "lint_bench", "lint_bench_cli")
CONTROL_FLOW_FNS = ("build_prompt", "run_stage", "run_iteration", "run_continuous")
TO_DICT_KEYS = ("bench_dir", "cards_scanned", "skipped", "findings",
                "parse_errors", "total_findings", "clean", "exit_code", "verdict")
# the FIXED marker order the spec pins for a multi-miss / empty card
FIXED_ORDER = ("title", "Status:", "Activation:", "Tenure:", "Model note:",
               "## Mission", "## I/O contract")


def _valid_lines():
    """A fully-compliant synthetic card. Activation:/Tenure: are SUBSTRINGS that
    live INLINE on the Status: line (mirroring the real cards); a third section
    (## Non-goals) is present but NOT required by the contract."""
    return [
        "# Bench role card: Sample Role",
        "",
        "Status: standing | Activation: on-demand | Tenure: rotating",
        "",
        "Model note: default model tier",
        "",
        "## Mission",
        "Do the sample thing well.",
        "",
        "## I/O contract",
        "input -> output",
        "",
        "## Non-goals",
        "nothing else",
    ]


def _valid_card():
    return "\n".join(_valid_lines())


def _drop(marker):
    """Return a card text that is compliant EXCEPT the one named marker.
    Uses replacements that remove ONLY the target marker and leave the others
    intact (Activation:/Tenure: share the Status: line, so removing one leaves
    the others as substrings)."""
    text = _valid_card()
    subs = {
        "title": ("# Bench role card: Sample Role", "# The bench"),
        "Status:": ("Status:", "Stat:"),
        "Activation:": ("Activation:", "Act:"),
        "Tenure:": ("Tenure:", "Ten:"),
        "Model note:": ("Model note:", "Model:"),
        # exact-heading contract: a `# Mission` H1 (not `## Mission`) must
        # STILL be flagged -- proves it is not a substring match
        "## Mission": ("## Mission", "# Mission"),
        "## I/O contract": ("## I/O contract", "## IO"),
    }
    old, new = subs[marker]
    return text.replace(old, new, 1)


def _reqs(findings):
    return [f.requirement for f in findings]


def _mk_card(d, name, text):
    p = pathlib.Path(d) / name
    p.write_text(text)
    return p


def _capture(fn):
    """Run fn() with stdout/stderr captured SEPARATELY; return (rc, out, err).
    Separate capture matters for --json: the JSON must be the ENTIRE stdout,
    uncontaminated by any stderr message."""
    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = fn()
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue(), err.getvalue()


def _co_names_deep(fn):
    """Every name referenced by fn's code, recursing into nested code objects."""
    seen = set()
    stack = [fn.__code__]
    while stack:
        code = stack.pop()
        seen |= set(code.co_names)
        stack += [c for c in code.co_consts if hasattr(c, "co_names")]
    return seen


# ==========================================================================
# Behavior 1 -- a fully-compliant card returns an EMPTY tuple
# ==========================================================================
def test_b1_compliant_card_no_findings():
    findings = foundry.lint_bench_card(_valid_card(), card="good.md")
    assert findings == (), f"expected no findings; got {_reqs(findings)}"


# ==========================================================================
# Behavior 2 -- missing `## Mission` (exact-heading, not substring)
# ==========================================================================
def test_b2_missing_mission_one_finding():
    findings = foundry.lint_bench_card(_drop("## Mission"), card="m.md")
    assert len(findings) == 1, f"expected exactly one finding; got {_reqs(findings)}"
    f = findings[0]
    assert f.requirement == "## Mission"
    assert f.card == "m.md"
    assert f.line == 1


def test_b2_prose_mission_word_still_flagged():
    # a card that merely contains the WORD Mission (no `## Mission` heading) is
    # STILL flagged -- exact-heading match, not substring
    text = _valid_card().replace("## Mission", "Mission matters a great deal")
    findings = foundry.lint_bench_card(text, card="p.md")
    assert _reqs(findings) == ["## Mission"], f"got {_reqs(findings)}"


def test_b2_h1_mission_heading_still_flagged():
    # a `# Mission` H1 (single hash) is NOT the exact `## Mission` heading
    text = _valid_card().replace("## Mission", "# Mission")
    findings = foundry.lint_bench_card(text, card="h.md")
    assert "## Mission" in _reqs(findings), f"got {_reqs(findings)}"


# ==========================================================================
# Behavior 3 -- missing `## I/O contract`
# ==========================================================================
def test_b3_missing_io_contract_one_finding():
    findings = foundry.lint_bench_card(_drop("## I/O contract"), card="io.md")
    assert _reqs(findings) == ["## I/O contract"], f"got {_reqs(findings)}"


# ==========================================================================
# Behavior 4 -- each header field, missing individually, is one finding
# ==========================================================================
@pytest.mark.parametrize("marker", ["Status:", "Activation:", "Tenure:", "Model note:"])
def test_b4_missing_header_field_one_finding(marker):
    findings = foundry.lint_bench_card(_drop(marker), card="c.md")
    assert _reqs(findings) == [marker], (
        f"dropping {marker!r} should yield exactly that one finding; got {_reqs(findings)}"
    )


# ==========================================================================
# Behavior 5 -- a wrong / missing title H1 is a `title` finding
# ==========================================================================
def test_b5_wrong_title_flagged():
    findings = foundry.lint_bench_card(_drop("title"), card="t.md")
    assert _reqs(findings) == ["title"], f"got {_reqs(findings)}"


def test_b5_no_h1_at_all_flagged_title():
    # a card with NO H1 line at all -> title finding (## headings are not H1s)
    text = "\n".join([
        "Status: x | Activation: y | Tenure: z",
        "Model note: m",
        "## Mission",
        "m",
        "## I/O contract",
        "io",
    ])
    findings = foundry.lint_bench_card(text, card="nohdr.md")
    assert "title" in _reqs(findings), f"got {_reqs(findings)}"


# ==========================================================================
# Behavior 6 -- multiple / all missing markers, in the FIXED order
# ==========================================================================
def test_b6_multi_miss_fixed_order():
    # drop Status: AND ## I/O contract -> findings ordered Status: then ## I/O contract
    text = _valid_card().replace("Status:", "Stat:").replace("## I/O contract", "## IO")
    findings = foundry.lint_bench_card(text, card="multi.md")
    assert _reqs(findings) == ["Status:", "## I/O contract"], f"got {_reqs(findings)}"


def test_b6_empty_string_all_seven_in_fixed_order():
    findings = foundry.lint_bench_card("", card="empty.md")
    assert _reqs(findings) == list(FIXED_ORDER), f"got {_reqs(findings)}"


# ==========================================================================
# Behavior 7 -- every finding: line == 1, non-empty message, card == passed name
# ==========================================================================
def test_b7_every_finding_line1_message_and_card():
    findings = foundry.lint_bench_card("", card="named.md")
    assert findings, "empty card should produce findings"
    for f in findings:
        assert f.line == 1, f"{f.requirement} line was {f.line}"
        assert isinstance(f.message, str) and f.message.strip(), f"empty message on {f.requirement}"
        assert f.card == "named.md", f"card was {f.card!r}"


# ==========================================================================
# Behavior 8 -- dir-walker: compliant cards + README skip -> clean
# ==========================================================================
def test_b8_dir_of_compliant_cards_readme_skipped(tmp_path):
    _mk_card(tmp_path, "alpha.md", _valid_card())
    _mk_card(tmp_path, "beta.md", _valid_card())
    _mk_card(tmp_path, "README.md", "# Docs\nnot a card at all")
    r = foundry.lint_bench(str(tmp_path))
    assert "README.md" in r.skipped, f"README must be skipped; skipped={r.skipped}"
    assert r.cards_scanned == 2, f"cards_scanned={r.cards_scanned}"
    assert r.findings == ()
    assert r.exit_code == 0
    assert r.verdict == "OK"
    assert r.clean is True


# ==========================================================================
# Behavior 9 -- a non-compliant card among compliant -> findings, exit 1
# ==========================================================================
def test_b9_bad_card_among_good_exit_1(tmp_path):
    _mk_card(tmp_path, "ok.md", _valid_card())
    _mk_card(tmp_path, "bad.md", _drop("## Mission"))
    _mk_card(tmp_path, "README.md", "# docs")
    r = foundry.lint_bench(str(tmp_path))
    assert r.total_findings >= 1
    # every finding's card is the BASENAME, not an absolute path
    cards = {f.card for f in r.findings}
    assert cards == {"bad.md"}, f"finding cards must be basenames; got {cards}"
    assert "## Mission" in {f.requirement for f in r.findings}
    assert r.exit_code == 1
    assert r.verdict == "CARD ISSUES FOUND"
    assert r.clean is False


# ==========================================================================
# Behavior 10 -- no card files (empty, or README-only) -> exit 2
# ==========================================================================
def test_b10_empty_dir_no_cards(tmp_path):
    r = foundry.lint_bench(str(tmp_path))
    assert r.cards_scanned == 0
    assert r.findings == ()
    assert r.exit_code == 2
    assert r.verdict == "NO CARDS"


def test_b10_readme_only_dir_no_cards(tmp_path):
    _mk_card(tmp_path, "README.md", "# docs only")
    r = foundry.lint_bench(str(tmp_path))
    assert r.cards_scanned == 0
    assert r.exit_code == 2
    assert r.verdict == "NO CARDS"


# ==========================================================================
# Behavior 11 -- render() is deterministic, names the dir, lists findings, and
#                its last non-empty line is `verdict: <VERDICT>`
# ==========================================================================
def test_b11_render_clean_last_line_verdict_ok(tmp_path):
    _mk_card(tmp_path, "a.md", _valid_card())
    r = foundry.lint_bench(str(tmp_path))
    text = r.render()
    assert text == r.render(), "render must be deterministic across calls"
    assert str(tmp_path) in text, "render must name the bench dir"
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert lines[-1] == "verdict: OK", f"last non-empty line: {lines[-1]!r}"


def test_b11_render_lists_findings_and_verdict_token(tmp_path):
    _mk_card(tmp_path, "bad.md", _drop("## I/O contract"))
    r = foundry.lint_bench(str(tmp_path))
    text = r.render()
    # each finding on its own line as `<card>:<line>` with its message
    assert "bad.md:1" in text, f"render missing card:line marker:\n{text}"
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert lines[-1] == "verdict: CARD ISSUES FOUND", f"last line: {lines[-1]!r}"


def test_b11_render_carries_no_source_home_path(tmp_path):
    # build the home prefix at RUNTIME (never a source literal) so this
    # self-leak-safety assertion does not itself trip the committed leak-guard
    home_prefix = "/" + "Users" + "/"
    _mk_card(tmp_path, "a.md", _valid_card())
    text = foundry.lint_bench(str(tmp_path)).render()
    assert home_prefix not in text, "render must not carry a home-path literal"


# ==========================================================================
# Behavior 12 -- to_dict() key order, finding/parse_error shape, JSON round-trip
# ==========================================================================
def test_b12_to_dict_key_order(tmp_path):
    _mk_card(tmp_path, "bad.md", _drop("## Mission"))
    d = foundry.lint_bench(str(tmp_path)).to_dict()
    assert tuple(d.keys()) == TO_DICT_KEYS, f"key order wrong: {list(d.keys())}"


def test_b12_findings_and_parse_errors_shape_and_roundtrip(tmp_path):
    _mk_card(tmp_path, "bad.md", _drop("## Mission"))
    _mk_card(tmp_path, "ok.md", _valid_card())
    d = foundry.lint_bench(str(tmp_path)).to_dict()
    assert isinstance(d["findings"], list) and d["findings"], "expected >=1 finding dict"
    for entry in d["findings"]:
        assert tuple(entry.keys()) == ("card", "line", "requirement", "message"), entry
    assert isinstance(d["parse_errors"], list)
    assert json.loads(json.dumps(d)) == d, "to_dict must round-trip through JSON"


def test_b12_parse_error_shape_when_present(tmp_path):
    # an unreadable card records a parse_error {card,message} and gates exit 1
    p = _mk_card(tmp_path, "locked.md", _valid_card())
    os.chmod(p, 0o000)
    if os.access(p, os.R_OK):  # running as root -> chmod is a no-op; skip
        os.chmod(p, 0o644)
        pytest.skip("cannot make a file unreadable (running as root)")
    try:
        r = foundry.lint_bench(str(tmp_path))
        assert r.cards_scanned == 1, "an unreadable *.md still counts as a scanned card"
        assert r.parse_errors, "expected a parse_error for the unreadable card"
        assert r.exit_code == 1, "a parse error is a real problem, not 'no cards'"
        d = r.to_dict()
        for pe in d["parse_errors"]:
            assert tuple(pe.keys()) == ("card", "message"), pe
        assert json.loads(json.dumps(d)) == d
    finally:
        os.chmod(p, 0o644)


# ==========================================================================
# Behavior 13 -- lint_bench_cli prints render / one JSON doc, returns exit code
# ==========================================================================
def test_b13_cli_human_prints_render_returns_exit_code(tmp_path):
    _mk_card(tmp_path, "a.md", _valid_card())
    rc, out, err = _capture(lambda: foundry.lint_bench_cli(bench_dir=str(tmp_path)))
    assert rc == 0, f"stderr={err!r}"
    assert out.splitlines()[0].startswith("foundry lint-bench")
    assert out.strip().splitlines()[-1] == "verdict: OK"


def test_b13_cli_json_is_one_parseable_doc_same_exit(tmp_path):
    _mk_card(tmp_path, "bad.md", _drop("## Mission"))
    rc, out, err = _capture(lambda: foundry.lint_bench_cli(bench_dir=str(tmp_path), as_json=True))
    assert rc == 1
    doc = json.loads(out)  # the ENTIRE stdout must be one parseable JSON document
    assert tuple(doc.keys()) == TO_DICT_KEYS
    assert doc["verdict"] == "CARD ISSUES FOUND"


# ==========================================================================
# Behavior 14 -- main dispatch + exit codes + nonexistent --dir never raises
# ==========================================================================
def test_b14_main_bad_dir_returns_1(tmp_path):
    _mk_card(tmp_path, "bad.md", _drop("## Mission"))
    rc, out, _ = _capture(lambda: foundry.main(["lint-bench", "--dir", str(tmp_path)]))
    assert rc == 1


def test_b14_main_empty_dir_returns_2(tmp_path):
    rc, out, _ = _capture(lambda: foundry.main(["lint-bench", "--dir", str(tmp_path)]))
    assert rc == 2


def test_b14_main_nonexistent_dir_returns_2_no_raise(tmp_path):
    missing = str(tmp_path / "does-not-exist")
    rc, out, err = _capture(lambda: foundry.main(["lint-bench", "--dir", missing]))
    assert rc == 2, "a nonexistent --dir is treated as 'no cards' (exit 2), never raises"


def test_b14_main_dispatched_before_load_config(tmp_path):
    # lint-bench needs NO product --config; if it were dispatched AFTER the
    # top-level load_config, the missing default config would raise instead of
    # returning a clean exit code.
    _mk_card(tmp_path, "a.md", _valid_card())
    rc, out, err = _capture(lambda: foundry.main(["lint-bench", "--dir", str(tmp_path)]))
    assert rc == 0, f"stderr={err!r}"
    assert isinstance(rc, int)


# ==========================================================================
# Behavior 15 -- default --dir validates the real bench (all 11 cards pass);
#                --help lists lint-bench
# ==========================================================================
def test_b15_default_dir_real_bench_exits_0():
    rc, out, err = _capture(lambda: foundry.main(["lint-bench"]))
    assert rc == 0, (
        "all shipped roles/bench cards must pass the linter (roadmap item 17 "
        f"acceptance); stdout=\n{out}\nstderr={err}"
    )
    assert "verdict: OK" in out


def test_b15_help_lists_lint_bench():
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        foundry.main(["--help"])
    except SystemExit:
        pass
    finally:
        sys.stdout = old
    assert "lint-bench" in buf.getvalue()


# ==========================================================================
# Behavior 16 -- dormancy + positive wiring + import health
# ==========================================================================
def test_b16_control_flow_fns_do_not_reference_new_symbols():
    for fn_name in CONTROL_FLOW_FNS:
        refs = _co_names_deep(getattr(foundry, fn_name)) & set(NEW_SYMBOLS)
        assert not refs, f"{fn_name} unexpectedly references {refs}"


def test_b16_positive_wiring_chain():
    assert "lint_bench_cli" in _co_names_deep(foundry.main)
    assert "lint_bench" in _co_names_deep(foundry.lint_bench_cli)
    assert "lint_bench_card" in _co_names_deep(foundry.lint_bench)


def test_b16_dispatcher_has_none_of_the_new_symbols():
    for s in NEW_SYMBOLS:
        assert not hasattr(dispatcher, s), f"dispatcher unexpectedly exposes {s}"


def test_b16_import_foundry_and_dispatcher_ok():
    root = str(pathlib.Path(__file__).resolve().parents[1])
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=root, capture_output=True, text=True,
    )
    assert r.returncode == 0, f"import failed: {r.stderr}"
