"""Black-box behaviour tests for iter 87 -- RE-SHIP of `foundry escalation-check
--json` (item 21 bite 1, ORG_DESIGN section 9): a machine-readable JSON payload
for the read-only CEO-escalation predicate, added ON TOP of the iter-77 core.
The change is a clean ADD-A-METHOD + ADD-A-FLAG: a new
`EscalationClassification.to_dict()` + an `as_json: bool = False` kw param on the
existing `escalation_check_cli` + a `--json` store_true subparser arg + a
one-line dispatch edit. ZERO call site: nothing in the running loop invokes it.

ISOLATION CONTRACT (honored): this file was written from the PM spec (Expected
Behaviors 1-16) and the product's own OBSERVABLE behaviour only (running it). The
implementation source (foundry.py internals), the engineer's and reviewer's
notes, and `git diff` were NOT read to design these behaviour tests. Every check
drives the PUBLIC interface: the frozen value object via `foundry.classify_escalation`
+ `EscalationClassification.to_dict`, the CLI via `foundry.escalation_check_cli`
and `foundry.main(["escalation-check", ...])`, and the five patchable vocabularies
via their module attributes (fixtures are built from the LIVE vocabularies read at
runtime, never hard-coded category NAME labels -- the classifier matches specific
keyword vocabularies, not the labels). The dormancy proof uses only public runtime
introspection -- compiled function name tables (`__code__.co_names` recursed) +ing
a `dispatcher.py` source symbol-count -- and the mechanical ASCII acceptance check
uses `inspect.getsource` SCOPED to the two new/changed symbols only (the
established suite convention; never a whole-file scan / never `git diff`). Fully
offline and deterministic: no subprocess/git/network except the fresh-import
regression probe. There is deliberately NO `git diff --quiet HEAD` control-path
guard in this file -- the iter-86 fix removed that over-broad freeze anti-pattern.
"""
import contextlib
import dataclasses
import importlib.util
import inspect
import io
import json
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402  (import-safety probe)


# --------------------------------------------------------------------------
# runtime-built paths + constants (module located via the BARE __file__ object,
# never a quoted source-literal main-module name -- the iter-54 meta-scanner)
# --------------------------------------------------------------------------
_ROOT = pathlib.Path(foundry.__file__).resolve().parent
DISPATCHER_PY = _ROOT / "dispatcher.py"
THIS_TEST = pathlib.Path(__file__).resolve()

# The fixed section-9 category order (labels == field names == to_dict bool keys).
ORDER = ("security", "pii", "money", "legal", "visibility")

# The 8 keys to_dict() must expose, exactly.
EXPECTED_KEYS = {"security", "pii", "money", "legal", "visibility",
                 "categories", "escalate", "verdict"}

# The three PRE-EXISTING escalation symbols (they existed since iter-77, so a
# whole-file grep would FALSE-POSITIVE). Dormancy is proven ONLY against these
# specific symbols + the command string -- NOT the generic `to_dict` name (many
# other classes own a to_dict).
ESC_SYMBOLS = ("escalation_check_cli", "EscalationClassification", "classify_escalation")

# A benign body that triggers no category (grounded against OBSERVED behaviour).
BENIGN = "just a normal harmless refactor of the loop scheduler for readability"


def _kw(category_label):
    """First keyword of a category's LIVE vocabulary, read at runtime."""
    return getattr(foundry, "ESCALATION_" + category_label.upper() + "_KEYWORDS")[0]


def _escalating_text():
    """A body hitting security + pii + visibility, built from REAL keywords with
    the keywords placed in REVERSE section-9 order to prove ordering is fixed by
    the classifier, not by appearance order."""
    return "then {} the release, log the {}, first rotate the {}".format(
        _kw("visibility"), _kw("pii"), _kw("security"))


def _all_five_text():
    """A body hitting all five categories, keywords in reverse section-9 order."""
    return "{v} ; {l} terms ; a {m} step ; store the {p} ; rotate the {s}".format(
        v=_kw("visibility"), l=_kw("legal"), m=_kw("money"),
        p=_kw("pii"), s=_kw("security"))


def _mk(text):
    return foundry.classify_escalation(text)


def _cap(fn):
    """Run a callable, capturing stdout + the returned code."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn()
    return rc, buf.getvalue()


def _write(tmp_path, text, name="proposal.txt"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def _co_names_deep(fn):
    """Every name referenced by fn's code, recursing nested code objects. Pure
    runtime introspection -- does NOT read the module source text."""
    seen = set()
    stack = [fn.__code__]
    while stack:
        code = stack.pop()
        seen |= set(code.co_names)
        stack += [c for c in code.co_consts if hasattr(c, "co_names")]
    return seen


def _leak_guard():
    gp = _ROOT / "scripts" / "leak_guard.py"
    spec = importlib.util.spec_from_file_location("leak_guard_iter87_probe", gp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ==========================================================================
# Preconditions -- keep the value-object tests non-vacuous
# ==========================================================================
def test_precondition_fixtures_escalate_and_clear():
    e = _mk(_escalating_text())
    assert e.escalate is True and len(e.categories) >= 1, (
        "escalating fixture did not escalate -- vocab drift?"
    )
    assert _mk(BENIGN).escalate is False, "benign fixture unexpectedly escalated"
    allf = _mk(_all_five_text())
    assert allf.categories == ORDER, (
        "all-five fixture did not hit every category in order: %r" % (allf.categories,)
    )


# ==========================================================================
# Behavior 1 -- to_dict() has EXACTLY the 8 keys
# ==========================================================================
def test_b01_to_dict_exact_8_keys():
    for text in (_escalating_text(), BENIGN, _all_five_text()):
        d = _mk(text).to_dict()
        assert isinstance(d, dict)
        assert set(d.keys()) == EXPECTED_KEYS, (
            "to_dict keys %r != %r" % (set(d.keys()), EXPECTED_KEYS)
        )
        assert len(d) == 8


# ==========================================================================
# Behavior 2 -- five boolean keys equal the stored fields (by identity)
# ==========================================================================
def test_b02_bool_keys_by_identity():
    for text in (_escalating_text(), BENIGN, _all_five_text()):
        e = _mk(text)
        d = e.to_dict()
        for label in ORDER:
            assert d[label] is getattr(e, label), (
                "to_dict[%r] is not the stored field (identity) for %r" % (label, text)
            )
            assert isinstance(d[label], bool)


# ==========================================================================
# Behavior 3 -- categories is a LIST (not tuple), == list(E.categories),
#               section-9 ordered, empty iff nothing hit
# ==========================================================================
def test_b03_categories_is_list_in_fixed_order():
    e = _mk(_all_five_text())
    d = e.to_dict()
    assert type(d["categories"]) is list, "categories must be a list, not a tuple"
    assert d["categories"] == list(e.categories)
    assert d["categories"] == list(ORDER)


def test_b03_categories_subsequence_of_order():
    # a partial-hit fixture: categories preserve section-9 order regardless of
    # appearance order in the text
    e = _mk(_escalating_text())
    d = e.to_dict()
    assert type(d["categories"]) is list
    idx = [ORDER.index(c) for c in d["categories"]]
    assert idx == sorted(idx), "categories not in fixed section-9 order: %r" % (d["categories"],)
    assert d["categories"] == [lbl for lbl in ORDER if getattr(e, lbl)]


def test_b03_empty_list_iff_nothing_hit():
    d = _mk(BENIGN).to_dict()
    assert d["categories"] == []
    assert type(d["categories"]) is list


# ==========================================================================
# Behavior 4 -- escalate/verdict keys equal the derived properties
# ==========================================================================
def test_b04_escalate_and_verdict_match_props():
    for text in (_escalating_text(), BENIGN, _all_five_text()):
        e = _mk(text)
        d = e.to_dict()
        assert d["escalate"] is e.escalate
        assert isinstance(d["escalate"], bool)
        assert d["verdict"] == e.verdict
        assert isinstance(d["verdict"], str)
        assert d["verdict"] == ("ESCALATE" if any(d[l] for l in ORDER) else "CLEAR")


# ==========================================================================
# Behavior 5 -- json round-trip survives (list, not tuple) for BOTH states
# ==========================================================================
def test_b05_json_round_trip_escalating_and_clear():
    for text in (_escalating_text(), _all_five_text(), BENIGN):
        d = _mk(text).to_dict()
        s = json.dumps(d)  # must not raise
        assert json.loads(s) == d, (
            "to_dict did not round-trip through JSON for %r (tuple leaked?)" % text
        )


# ==========================================================================
# Behavior 6 -- to_dict() is read-only + returns a FRESH dict each call
# ==========================================================================
def test_b06_no_mutation_and_fresh_dict():
    e = _mk(_escalating_text())
    before = dataclasses.asdict(e)
    d1 = e.to_dict()
    # mutate the returned dict aggressively
    d1["categories"].append("BOGUS")
    d1["escalate"] = "TAMPERED"
    d1["security"] = "TAMPERED"
    d2 = e.to_dict()
    assert dataclasses.asdict(e) == before, "to_dict mutated the frozen instance"
    assert d2 == _mk(_escalating_text()).to_dict(), "second to_dict was affected by mutation"
    assert d2["categories"] is not d1["categories"], "categories list is shared across calls"


def test_b06_two_calls_equal():
    e = _mk(_all_five_text())
    assert e.to_dict() == e.to_dict()


# ==========================================================================
# Behavior 7 -- default == as_json=False, byte-for-byte + same code (human)
# ==========================================================================
def test_b07_default_equals_explicit_false(tmp_path):
    for text in (_escalating_text(), BENIGN):
        p = _write(tmp_path, text, name="b07_" + str(abs(hash(text))) + ".txt")
        rc_def, out_def = _cap(lambda: foundry.escalation_check_cli(str(p)))
        rc_false, out_false = _cap(lambda: foundry.escalation_check_cli(str(p), as_json=False))
        assert out_def == out_false, "default output != explicit as_json=False output"
        assert rc_def == rc_false
        # the default/human path is NOT JSON
        with pytest.raises(json.JSONDecodeError):
            json.loads(out_def)


def test_b07_as_json_default_is_false():
    sig = inspect.signature(foundry.escalation_check_cli)
    assert "as_json" in sig.parameters, "escalation_check_cli must gain an as_json param"
    assert sig.parameters["as_json"].default is False


# ==========================================================================
# Behavior 8 -- as_json=True prints EXACTLY json.dumps(to_dict(), indent=2)+nl,
#               and NONE of the human-report lines
# ==========================================================================
def test_b08_json_output_is_exact(tmp_path):
    for text in (_escalating_text(), BENIGN, _all_five_text()):
        p = _write(tmp_path, text, name="b08_" + str(abs(hash(text))) + ".txt")
        rc, out = _cap(lambda: foundry.escalation_check_cli(str(p), as_json=True))
        expected = json.dumps(foundry.classify_escalation(text).to_dict(), indent=2) + "\n"
        assert out == expected, "as_json output != json.dumps(to_dict(), indent=2)+newline"
        # whole stdout is exactly ONE JSON document
        assert json.loads(out) == foundry.classify_escalation(text).to_dict()


def test_b08_no_human_lines_leak_into_json(tmp_path):
    p = _write(tmp_path, _escalating_text(), name="b08leak.txt")
    _, out = _cap(lambda: foundry.escalation_check_cli(str(p), as_json=True))
    # the human report has a header line, a "  categories:" line, and a "verdict:"
    # line. None of those bare-label lines may appear in JSON (JSON lines strip to
    # a leading double-quote, e.g. '"categories": [', so this is a true discriminator).
    for ln in out.splitlines():
        s = ln.strip()
        assert not s.startswith("escalation-check:"), "human header leaked into JSON: %r" % ln
        assert not s.startswith("categories:"), "human categories line leaked into JSON: %r" % ln
        assert not s.startswith("verdict:"), "human verdict line leaked into JSON: %r" % ln


# ==========================================================================
# Behavior 9 -- --json changes ONLY output, never the verdict/exit code
# ==========================================================================
def test_b09_same_exit_code_both_modes(tmp_path):
    fixtures = [(_escalating_text(), 1), (_all_five_text(), 1), (BENIGN, 0)]
    for text, code in fixtures:
        p = _write(tmp_path, text, name="b09_" + str(abs(hash(text))) + ".txt")
        rc_h, _ = _cap(lambda: foundry.escalation_check_cli(str(p), as_json=False))
        rc_j, _ = _cap(lambda: foundry.escalation_check_cli(str(p), as_json=True))
        assert rc_h == rc_j == code, (
            "exit code diverged for %r: human=%r json=%r expected=%r" % (text, rc_h, rc_j, code)
        )


# ==========================================================================
# Behavior 10 -- missing file: byte-identical message in both modes, both 2,
#                no JSON emitted
# ==========================================================================
def test_b10_missing_file_identical_both_modes(tmp_path):
    missing = str(tmp_path / "does_not_exist.txt")
    rc_h, out_h = _cap(lambda: foundry.escalation_check_cli(missing))
    rc_j, out_j = _cap(lambda: foundry.escalation_check_cli(missing, as_json=True))
    assert rc_h == rc_j == 2, "missing-file must return 2 in both modes"
    assert out_h == out_j, "missing-file message differs between modes"
    assert "file not found" in out_h.lower()
    assert missing in out_h, "missing-file message did not name the path"
    # no JSON was emitted -- nothing to serialize
    with pytest.raises(json.JSONDecodeError):
        json.loads(out_j)


# ==========================================================================
# Behavior 11 -- writes NOTHING to disk in either mode (existing + missing)
# ==========================================================================
def test_b11_writes_nothing_present_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = _write(tmp_path, _escalating_text(), name="b11.txt")
    for as_json in (False, True):
        before = sorted(x.name for x in tmp_path.iterdir())
        _cap(lambda: foundry.escalation_check_cli(str(p), as_json=as_json))
        after = sorted(x.name for x in tmp_path.iterdir())
        assert before == after, "CLI wrote to disk (present, as_json=%s)" % as_json


def test_b11_writes_nothing_missing_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    missing = str(tmp_path / "nope.txt")
    for as_json in (False, True):
        before = sorted(x.name for x in tmp_path.iterdir())
        _cap(lambda: foundry.escalation_check_cli(missing, as_json=as_json))
        after = sorted(x.name for x in tmp_path.iterdir())
        assert before == after, "CLI wrote to disk (missing, as_json=%s)" % as_json


# ==========================================================================
# Behavior 12 -- end-to-end dispatch via foundry.main: --json routes as_json,
#                process code matches the direct-call verdict
# ==========================================================================
def test_b12_main_routes_as_json(monkeypatch):
    captured = {}

    def fake(path, as_json=False):
        captured["path"] = path
        captured["as_json"] = as_json
        return 0

    monkeypatch.setattr(foundry, "escalation_check_cli", fake)
    foundry.main(["escalation-check", "--file", "SENTINEL_PATH", "--json"])
    assert captured == {"path": "SENTINEL_PATH", "as_json": True}
    captured.clear()
    foundry.main(["escalation-check", "--file", "SENTINEL_PATH"])
    assert captured == {"path": "SENTINEL_PATH", "as_json": False}


def test_b12_main_exit_matches_verdict(tmp_path):
    esc = _write(tmp_path, _escalating_text(), name="b12e.txt")
    clr = _write(tmp_path, BENIGN, name="b12c.txt")
    missing = str(tmp_path / "b12_missing.txt")
    for args, code in (
        (["escalation-check", "--file", str(esc), "--json"], 1),
        (["escalation-check", "--file", str(esc)], 1),
        (["escalation-check", "--file", str(clr), "--json"], 0),
        (["escalation-check", "--file", str(clr)], 0),
        (["escalation-check", "--file", missing, "--json"], 2),
        (["escalation-check", "--file", missing], 2),
    ):
        rc, _ = _cap(lambda: foundry.main(args))
        assert rc == code, "main%r exit %r != %r" % (args, rc, code)


# ==========================================================================
# Behavior 13 -- subparser: --json is store_true; --file is required
# ==========================================================================
def test_b13_json_store_true_and_file_required(tmp_path):
    # --json present -> parsed json attr True (proven via the dispatch-spy above);
    # here confirm the flag takes NO value (store_true) and --file is required.
    p = _write(tmp_path, BENIGN, name="b13.txt")
    # store_true: providing a value to --json is rejected by argparse
    with pytest.raises(SystemExit):
        foundry.main(["escalation-check", "--file", str(p), "--json", "extra"])
    # --file omitted -> argparse exits non-zero
    with pytest.raises(SystemExit) as ei:
        with contextlib.redirect_stderr(io.StringIO()):
            foundry.main(["escalation-check", "--json"])
    assert ei.value.code != 0


# ==========================================================================
# Behavior 14 -- fresh subprocess import of foundry AND dispatcher succeeds
# ==========================================================================
def test_b14_fresh_subprocess_import_ok():
    r = subprocess.run(
        [sys.executable, "-c", "import foundry, dispatcher"],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


# ==========================================================================
# Behavior 15 -- DORMANCY: the running loop is unaffected
# ==========================================================================
def test_b15_orchestrators_do_not_reference_escalation_symbols():
    new = set(ESC_SYMBOLS)
    for fn in (foundry.build_prompt, foundry.run_stage, foundry.run_iteration,
               foundry.run_continuous, foundry.run_execution_plan):
        refs = _co_names_deep(fn) & new
        assert refs == set(), "foundry.%s references escalation symbol(s): %r" % (fn.__name__, refs)


def test_b15_dispatcher_has_zero_escalation_references():
    dtext = DISPATCHER_PY.read_text(encoding="utf-8")
    for sym in ESC_SYMBOLS:
        assert dtext.count(sym) == 0, "dispatcher.py references escalation symbol %r" % sym
    assert dtext.count("escalation-check") == 0, "dispatcher.py names the escalation-check command string"


# ==========================================================================
# Acceptance-criteria / non-regression block
# ==========================================================================
def test_ac_public_surface_intact():
    assert callable(foundry.classify_escalation)
    assert callable(foundry.escalation_check_cli)
    assert dataclasses.is_dataclass(foundry.EscalationClassification)
    assert callable(foundry.EscalationClassification.to_dict)
    for fn in ("build_prompt", "run_iteration", "run_continuous", "run_stage", "run_execution_plan"):
        assert callable(getattr(foundry, fn)), "foundry.%s missing (regression)" % fn
    assert dispatcher is not None


def test_ac_help_lists_escalation_check(capsys):
    with pytest.raises(SystemExit) as ei:
        foundry.main(["--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "escalation-check" in out


def test_ac_new_symbols_ascii():
    """The new/changed code is pure ASCII. Scoped to the two symbols via
    inspect.getsource -- NOT a whole-file scan (foundry.py carries pre-existing
    non-ASCII elsewhere -- the iter-67 divider-em-dash trap)."""
    srcs = [
        inspect.getsource(foundry.EscalationClassification.to_dict),
        inspect.getsource(foundry.escalation_check_cli),
    ]
    for src in srcs:
        offenders = [(i, c) for i, c in enumerate(src) if ord(c) >= 128]
        assert offenders == [], offenders[:5]


def test_ac_this_test_file_ascii():
    ttext = THIS_TEST.read_text(encoding="utf-8")
    assert [(i, c) for i, c in enumerate(ttext) if ord(c) >= 128] == []


def test_ac_leak_clean_and_matcher_armed():
    mod = _leak_guard()
    denylist = mod.load_denylist(mod.DENYLIST_PATH.read_text())
    assert mod.scan_text(THIS_TEST.read_text(encoding="utf-8"), denylist) == (), \
        "this test file leaks a denylisted token"
    # matcher is ARMED (not inert): a runtime-built home path IS flagged.
    needle = "/" + "Users" + "/" + "nobody/secret.txt"
    assert mod.scan_text(needle, denylist), "leak matcher is inert (false-clean risk)"
