"""Black-box behaviour tests for iter 77 -- item 21, bite 1 of ~2: the DORMANT
pure CEO-escalation classifier `classify_escalation(text) -> EscalationClassification`
(a frozen result with five reserved-category booleans -- security / pii / money /
legal / visibility -- plus derived props `categories` / `escalate` / `verdict`),
driven by five patchable module-level keyword vocabularies
(`ESCALATION_{SECURITY,PII,MONEY,LEGAL,VISIBILITY}_KEYWORDS`), plus an on-demand
read-only `foundry escalation-check --file <path>` CLI. It generalizes the
committed `scripts/leak_guard.py` (ORG_DESIGN section-9's first instance, PII) to
all five reserved CEO-escalation categories. ZERO call site: nothing in the
pipeline invokes it this iteration.

ISOLATION CONTRACT (honored): this file was written from the PM spec (Expected
Behaviors 1-14) and the product's own OBSERVABLE behaviour only (running it). The
implementation source (foundry.py internals), the engineer's and reviewer's
notes, and `git diff` were NOT read to design these behaviour tests. Every check
drives the PUBLIC interface: the pure core via `foundry.classify_escalation`, the
patchable vocabularies via their module attributes, and the CLI via
`foundry.main(["escalation-check", ...])`. The dormancy / off-control-path checks
use only public RUNTIME introspection -- module attributes, compiled function
name tables (`__code__.co_names` recursed via `_co_names_deep`), `--help` output,
and a git `--quiet` exit-code probe -- plus, for the mechanical ASCII /
leak-clean acceptance criteria, `inspect.getsource` scoped to the NEW symbols only
(the established suite convention; never a whole-file scan / never `git diff`).
Fully offline and deterministic: NO subprocess/git/network/agent-run except the
fresh-import + `--help` regression probes and the control-path byte-unchanged git
`--quiet` probe. The dormancy proof is scoped to the SYMBOLS and the
`escalation-check` command string in dispatcher.py ONLY -- never a bare
`rg escalation-check foundry.py`, which now self-matches the new CLI code.
"""
import dataclasses
import importlib.util
import inspect
import io
import contextlib
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe)


# --------------------------------------------------------------------------
# runtime-built paths + constants (never a source-literal home path)
# --------------------------------------------------------------------------
_ROOT = pathlib.Path(foundry.__file__).resolve().parent
DISPATCHER_PY = _ROOT / "dispatcher.py"
THIS_TEST = pathlib.Path(__file__).resolve()

# The fixed section-9 category order (labels == field names).
ORDER = ("security", "pii", "money", "legal", "visibility")

# The symbols this iteration ADDS. They must be dormant: no orchestrator and
# dispatcher.py reference any of them by name.
NEW_SYMBOLS = (
    "classify_escalation",
    "EscalationClassification",
    "escalation_check_cli",
    "ESCALATION_SECURITY_KEYWORDS",
    "ESCALATION_PII_KEYWORDS",
    "ESCALATION_MONEY_KEYWORDS",
    "ESCALATION_LEGAL_KEYWORDS",
    "ESCALATION_VISIBILITY_KEYWORDS",
)

# The five patchable vocabularies, keyed by category label (read at RUNTIME from
# the module so a spec/vocab change surfaces here, not baked into a source copy).
VOCAB = {
    "security": lambda: foundry.ESCALATION_SECURITY_KEYWORDS,
    "pii": lambda: foundry.ESCALATION_PII_KEYWORDS,
    "money": lambda: foundry.ESCALATION_MONEY_KEYWORDS,
    "legal": lambda: foundry.ESCALATION_LEGAL_KEYWORDS,
    "visibility": lambda: foundry.ESCALATION_VISIBILITY_KEYWORDS,
}

# A benign proposal that triggers no category (grounded against OBSERVED
# behaviour, not source).
BENIGN = "just a normal harmless refactor of the loop scheduler for readability"

_GIT_OK = subprocess.run(
    ["git", "rev-parse", "--is-inside-work-tree"],
    cwd=str(_ROOT), capture_output=True, text=True,
).returncode == 0


def _co_names_deep(fn):
    """Every name referenced by fn's code, recursing into nested code objects.
    Pure runtime introspection -- does NOT read the module source text."""
    seen = set()
    stack = [fn.__code__]
    while stack:
        code = stack.pop()
        seen |= set(code.co_names)
        stack += [c for c in code.co_consts if hasattr(c, "co_names")]
    return seen


def _leak_guard():
    """Dynamically import the committed leak-guard, registering the module in
    sys.modules BEFORE exec so its own import machinery works."""
    gp = _ROOT / "scripts" / "leak_guard.py"
    spec = importlib.util.spec_from_file_location("leak_guard_iter77_probe", gp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _cli(args):
    """Drive the CLI via foundry.main, capturing stdout + exit code."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = foundry.main(list(args))
    return rc, buf.getvalue()


def _c(text):
    return foundry.classify_escalation(text)


def _fields(r):
    return (r.security, r.pii, r.money, r.legal, r.visibility)


def _write(tmp_path, text, name="proposal.txt"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


# ==========================================================================
# Behavior 1 -- pure, total, never-raises, offline, deterministic
# ==========================================================================
def test_b01_total_never_raises_and_typed():
    cases = ["", "password", BENIGN, "SSN and payment and license",
             "   ", "\n\t random \n unicode-free text \n"]
    for text in cases:
        r = _c(text)  # must not raise, including ""
        assert type(r).__name__ == "EscalationClassification", (
            f"classify_escalation did not return EscalationClassification for {text!r}"
        )


def test_b01_deterministic_value_equality():
    for text in ("", "password ssn", BENIGN, "go public with the invoice"):
        assert _c(text) == _c(text), f"not deterministic / value-equal for {text!r}"


def test_b01_empty_string_is_clear():
    r = _c("")
    assert _fields(r) == (False, False, False, False, False)
    assert r.categories == ()
    assert r.escalate is False
    assert r.verdict == "CLEAR"


def test_b01_no_filesystem_access(monkeypatch):
    """Pure: the core opens no file. Sabotage builtins.open; it still works."""
    def _boom(*a, **k):
        raise AssertionError("classify_escalation performed filesystem I/O")
    monkeypatch.setattr("builtins.open", _boom)
    r = _c("rotate the password")
    assert r.security is True
    assert r.verdict == "ESCALATE"


# ==========================================================================
# Behavior 2 -- frozen EscalationClassification
# ==========================================================================
def test_b02_frozen_dataclass():
    assert dataclasses.is_dataclass(foundry.EscalationClassification)
    r = _c("password")
    for field in ORDER:
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(r, field, not getattr(r, field))


# ==========================================================================
# Behavior 3 -- exactly five boolean fields in fixed order
# ==========================================================================
def test_b03_five_bool_fields_fixed_order():
    field_names = tuple(f.name for f in dataclasses.fields(foundry.EscalationClassification))
    assert field_names == ORDER, (
        f"EscalationClassification fields = {field_names}, expected {ORDER}"
    )
    r = _c("password ssn payment license open source")
    for field in ORDER:
        assert isinstance(getattr(r, field), bool), f"field {field} is not a bool"


# ==========================================================================
# Behavior 4 -- benign / empty text is CLEAR
# ==========================================================================
def test_b04_benign_text_is_clear():
    for text in ("", BENIGN, "refactor rename tidy loop", "the quick brown fox"):
        r = _c(text)
        assert _fields(r) == (False, False, False, False, False), f"benign text hit a category: {text!r} -> {r.categories}"
        assert r.categories == ()
        assert r.escalate is False
        assert r.verdict == "CLEAR"


# ==========================================================================
# Behaviors 5-9 -- each single category detected in isolation (via its own vocab)
# ==========================================================================
def _assert_single_category(label):
    """Every keyword in the category's vocabulary triggers exactly that one
    category (and no other), using the LIVE vocabulary read at runtime."""
    for kw in VOCAB[label]():
        text = "context around the " + kw + " token in a sentence"
        r = _c(text)
        assert getattr(r, label) is True, f"keyword {kw!r} did not set {label}=True"
        assert r.categories == (label,), (
            f"keyword {kw!r} triggered {r.categories}, expected ({label!r},)"
        )
        assert r.escalate is True
        assert r.verdict == "ESCALATE"


def test_b05_security_detection():
    assert "password" in foundry.ESCALATION_SECURITY_KEYWORDS
    assert "credential" in foundry.ESCALATION_SECURITY_KEYWORDS
    _assert_single_category("security")


def test_b06_pii_detection():
    assert "ssn" in foundry.ESCALATION_PII_KEYWORDS
    assert "social security" in foundry.ESCALATION_PII_KEYWORDS
    _assert_single_category("pii")


def test_b07_money_detection():
    assert "payment" in foundry.ESCALATION_MONEY_KEYWORDS
    assert "credit card" in foundry.ESCALATION_MONEY_KEYWORDS
    _assert_single_category("money")


def test_b08_legal_detection():
    assert "license" in foundry.ESCALATION_LEGAL_KEYWORDS
    assert "copyright" in foundry.ESCALATION_LEGAL_KEYWORDS
    _assert_single_category("legal")


def test_b09_visibility_detection():
    assert "make public" in foundry.ESCALATION_VISIBILITY_KEYWORDS
    assert "open source" in foundry.ESCALATION_VISIBILITY_KEYWORDS
    _assert_single_category("visibility")


# ==========================================================================
# Behavior 10 -- case-insensitive full-text match
# ==========================================================================
def test_b10_case_insensitive():
    cases = {
        "PASSWORD rotation required": "security",
        "Social Security number field": "pii",
        "add a PAYMENT step": "money",
        "update the LICENSE header": "legal",
        "Open-Source the module": "visibility",
    }
    for text, label in cases.items():
        r = _c(text)
        assert getattr(r, label) is True, f"case-insensitive match failed: {text!r} -> {r.categories}"
        assert r.categories == (label,)


def test_b10_full_text_scan_not_line_bounded():
    # a keyword can appear anywhere in a multi-line body (no diff/line parsing)
    text = "line one\nline two mentions the ssn field\nline three ok"
    r = _c(text)
    assert r.pii is True
    assert r.categories == ("pii",)


# ==========================================================================
# Behavior 11 -- multiple categories, fixed order regardless of appearance order
# ==========================================================================
def test_b11_multiple_categories_fixed_order():
    # keywords deliberately appear in REVERSE section-9 order in the text
    text = "go public, then wire transfer funds, cite the patent, store the ssn, rotate the password"
    r = _c(text)
    assert _fields(r) == (True, True, True, True, True)
    assert r.categories == ORDER, (
        f"categories not in fixed section-9 order: {r.categories}"
    )


def test_b11_two_categories_order_independent_of_text():
    # visibility keyword FIRST, security LAST -> categories must be security-first
    r = _c("make public and also rotate the password")
    assert r.categories == ("security", "visibility"), r.categories
    # the reverse text ordering yields the SAME category ordering
    r2 = _c("rotate the password and make public")
    assert r2.categories == ("security", "visibility")
    assert r.categories == r2.categories


def test_b11_middle_pair():
    r = _c("this touches billing and also the license terms")
    assert r.categories == ("money", "legal"), r.categories


# ==========================================================================
# Behavior 12 -- derived props consistent
# ==========================================================================
def test_b12_derived_props_consistent():
    for text in ("", "password", "ssn payment", BENIGN,
                 "go public, invoice, license, home address, api key"):
        r = _c(text)
        expected_cats = tuple(lbl for lbl, v in zip(ORDER, _fields(r)) if v)
        assert r.categories == expected_cats, (
            f"categories {r.categories} != labels of True fields {expected_cats} for {text!r}"
        )
        assert r.escalate == bool(r.categories)
        assert r.verdict == ("ESCALATE" if r.escalate else "CLEAR")
        assert r.verdict in ("ESCALATE", "CLEAR")


# ==========================================================================
# Behavior 13 -- call-time keyword reads (bare-name monkeypatch bites; restore reverts)
# ==========================================================================
def test_b13_call_time_keyword_read(monkeypatch):
    # default: "password" hits security, a novel word does not
    assert _c("password").security is True
    assert _c("has zznovelword here").security is False
    monkeypatch.setattr(foundry, "ESCALATION_SECURITY_KEYWORDS", ("zznovelword",))
    # the patched vocabulary is honored on a SUBSEQUENT call
    assert _c("has zznovelword here").security is True, (
        "monkeypatched ESCALATION_SECURITY_KEYWORDS not honored at call time"
    )
    # and the original keyword no longer hits (proves the read is not import-time)
    assert _c("password").security is False


def test_b13_call_time_keyword_restore_reverts():
    # after the previous test's monkeypatch is undone, defaults are back
    assert _c("password").security is True
    assert _c("has zznovelword here").security is False


def test_b13_each_vocab_is_patchable_at_call_time(monkeypatch):
    # every one of the five vocabularies is read at call time
    for label, attr in (("security", "ESCALATION_SECURITY_KEYWORDS"),
                        ("pii", "ESCALATION_PII_KEYWORDS"),
                        ("money", "ESCALATION_MONEY_KEYWORDS"),
                        ("legal", "ESCALATION_LEGAL_KEYWORDS"),
                        ("visibility", "ESCALATION_VISIBILITY_KEYWORDS")):
        monkeypatch.setattr(foundry, attr, ("qqzztoken" + label,))
        r = _c("body with qqzztoken" + label + " inside")
        assert getattr(r, label) is True, f"patched {attr} not honored at call time"
        monkeypatch.undo()
        # restored: the novel token no longer hits
        assert getattr(_c("body with qqzztoken" + label + " inside"), label) is False


# ==========================================================================
# Behavior 14 -- CLI: missing->2, ESCALATE->1, CLEAR->0, writes nothing
# ==========================================================================
def test_b14_cli_missing_file_exit2(tmp_path):
    missing = str(tmp_path / "does_not_exist.txt")
    rc, out = _cli(["escalation-check", "--file", missing])
    assert rc == 2, f"missing file returned {rc!r}, expected 2\n{out}"
    assert "not found" in out.lower(), f"not-found message absent:\n{out}"
    assert missing in out, f"not-found message did not name the path:\n{out}"


def test_b14_cli_missing_file_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    before = sorted(x.name for x in tmp_path.iterdir())
    missing = str(tmp_path / "nope.txt")
    rc, _ = _cli(["escalation-check", "--file", missing])
    after = sorted(x.name for x in tmp_path.iterdir())
    assert rc == 2
    assert before == after, f"CLI wrote to disk on missing file: {before} -> {after}"


def test_b14_cli_escalate_exit1(tmp_path):
    p = _write(tmp_path, "we must rotate the password and store the user ssn")
    rc, out = _cli(["escalation-check", "--file", str(p)])
    assert rc == 1, f"ESCALATE file returned {rc!r}, expected 1\n{out}"
    assert str(p) in out, f"CLI did not print the file path:\n{out}"
    low = out.lower()
    assert "security" in low and "pii" in low, f"triggered category labels absent:\n{out}"
    # a final line beginning 'verdict:' names ESCALATE
    assert "verdict: ESCALATE" in out, f"verdict line missing/wrong:\n{out}"


def test_b14_cli_clear_exit0(tmp_path):
    p = _write(tmp_path, BENIGN)
    rc, out = _cli(["escalation-check", "--file", str(p)])
    assert rc == 0, f"CLEAR file returned {rc!r}, expected 0\n{out}"
    assert str(p) in out
    assert "verdict: CLEAR" in out, f"verdict line missing/wrong:\n{out}"
    # a "(none)" indication for the empty category list
    assert "(none)" in out.lower(), f"'(none)' clear indication absent:\n{out}"


def test_b14_cli_present_file_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = _write(tmp_path, "rotate the password")
    before = sorted(x.name for x in tmp_path.iterdir())
    rc, _ = _cli(["escalation-check", "--file", str(p)])
    after = sorted(x.name for x in tmp_path.iterdir())
    assert rc == 1
    assert before == after, f"CLI wrote/removed a file: {before} -> {after}"


def test_b14_cli_verdict_matches_core(tmp_path):
    """The CLI is a THIN wrapper: its exit code + verdict track the pure core."""
    fixtures = {
        "rotate the password": ("ESCALATE", 1),
        "store the user ssn value": ("ESCALATE", 1),
        BENIGN: ("CLEAR", 0),
        "add a payment and go public": ("ESCALATE", 1),
    }
    for text, (verdict, code) in fixtures.items():
        assert _c(text).verdict == verdict, f"fixture assumption wrong for {text!r}"
        p = _write(tmp_path, text, name="f_" + str(abs(hash(text))) + ".txt")
        rc, out = _cli(["escalation-check", "--file", str(p)])
        assert rc == code, f"CLI exit {rc!r} != expected {code} for {text!r}\n{out}"
        assert f"verdict: {verdict}" in out, f"CLI verdict != core verdict {verdict}:\n{out}"


def test_b14_cli_dispatched_before_load_config(tmp_path):
    # no product --config is required; the CLI runs standalone (mirrors gate-precheck)
    p = _write(tmp_path, "rotate the password")
    rc, out = _cli(["escalation-check", "--file", str(p)])
    assert rc == 1, f"escalation-check needed a --config (not dispatched before load_config)?\n{out}"


# ==========================================================================
# Keyword-vocabulary disjointness precondition (load-bearing for a
# vocabulary-driven classifier: the per-category tests are vacuous if false)
# ==========================================================================
def test_precondition_keywords_lowercase():
    offenders = [(lbl, kw) for lbl in ORDER for kw in VOCAB[lbl]() if kw != kw.lower()]
    assert offenders == [], f"non-lowercase vocab members (would never match): {offenders}"


def test_precondition_cross_category_substring_disjoint():
    viol = []
    for ca in ORDER:
        for a in VOCAB[ca]():
            for cb in ORDER:
                if ca == cb:
                    continue
                for b in VOCAB[cb]():
                    if a in b:
                        viol.append((ca, a, cb, b))
    assert viol == [], f"cross-category substring collisions (break single-category tests): {viol}"


def test_precondition_each_keyword_maps_to_one_category():
    mis = []
    for lbl in ORDER:
        for kw in VOCAB[lbl]():
            r = _c(kw)
            if r.categories != (lbl,):
                mis.append((lbl, kw, r.categories))
    assert mis == [], f"keywords not mapping to exactly their own category: {mis}"


# ==========================================================================
# Acceptance-criteria / non-regression block (offline)
# ==========================================================================
def test_ac_public_surface_and_import_intact():
    assert callable(foundry.classify_escalation)
    assert callable(foundry.escalation_check_cli)
    assert dataclasses.is_dataclass(foundry.EscalationClassification)
    for name in ("ESCALATION_SECURITY_KEYWORDS", "ESCALATION_PII_KEYWORDS",
                 "ESCALATION_MONEY_KEYWORDS", "ESCALATION_LEGAL_KEYWORDS",
                 "ESCALATION_VISIBILITY_KEYWORDS"):
        assert isinstance(getattr(foundry, name), tuple), f"{name} is not a tuple"
    for fn in ("build_prompt", "run_iteration", "run_continuous", "run_stage", "run_execution_plan"):
        assert callable(getattr(foundry, fn)), f"foundry.{fn} missing/not callable (regression)"
    # reused prior-bite cores remain present (no regression to item-20 family)
    assert callable(foundry.product_gate_precheck)
    assert callable(foundry.aggregate_gate_verdict)
    assert dispatcher is not None


def test_ac_help_lists_escalation_check_and_prior_subcommands(capsys):
    with pytest.raises(SystemExit) as ei:
        foundry.main(["--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "escalation-check" in out, f"escalation-check missing from --help:\n{out}"
    for sub in ("run", "once", "gate-precheck", "gate-verdict", "role-model", "product-gate"):
        assert sub in out, f"subcommand {sub!r} missing from --help (regression)"


def test_ac_dormant_zero_call_site():
    """No orchestrator and no dispatcher-module reference references any new
    symbol by name (compiled name tables -- no source text read), nor names the
    `escalation-check` command string in dispatcher.py."""
    new = set(NEW_SYMBOLS)
    for fn in (foundry.build_prompt, foundry.run_stage, foundry.run_iteration,
               foundry.run_continuous, foundry.run_execution_plan):
        refs = _co_names_deep(fn) & new
        assert refs == set(), f"foundry.{fn.__name__} references dormant symbol(s): {refs}"
    dtext = DISPATCHER_PY.read_text(encoding="utf-8")
    for sym in NEW_SYMBOLS:
        assert sym not in dtext, f"dispatcher.py references dormant symbol {sym!r}"
    assert "escalation-check" not in dtext, "dispatcher.py names the 'escalation-check' command string"


def test_ac_fresh_subprocess_import_ok():
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


def test_ac_new_symbols_ascii():
    """The NEW code is pure ASCII. Scoped to the new symbols via
    inspect.getsource -- NOT a whole-file scan (foundry.py carries pre-existing
    non-ASCII elsewhere -- the iter-67 trap)."""
    new_sources = [
        inspect.getsource(foundry.classify_escalation),
        inspect.getsource(foundry.EscalationClassification),
        inspect.getsource(foundry.escalation_check_cli),
    ]
    for src in new_sources:
        offenders = [(i, c) for i, c in enumerate(src) if ord(c) >= 128]
        assert offenders == [], offenders[:5]


def test_ac_leak_clean_and_matcher_armed():
    mod = _leak_guard()
    denylist = mod.load_denylist(mod.DENYLIST_PATH.read_text())
    assert mod.scan_text(THIS_TEST.read_text(encoding="utf-8"), denylist) == (), \
        "this test file leaks a denylisted token"
    # matcher is ARMED (not inert): a RUNTIME-built home-path needle IS flagged.
    needle = "/" + "Users" + "/" + "nobody/secret.txt"
    assert mod.scan_text(needle, denylist), "leak matcher is inert (false-clean risk)"


def test_ac_this_test_file_ascii():
    ttext = THIS_TEST.read_text(encoding="utf-8")
    assert [(i, c) for i, c in enumerate(ttext) if ord(c) >= 128] == []


@pytest.mark.skipif(not _GIT_OK, reason="not inside a git work tree")
def test_ac_control_path_byte_unchanged():
    r = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", "dispatcher.py", "scripts/", ".gitignore"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, "dispatcher.py / scripts / .gitignore NOT byte-unchanged from HEAD"
