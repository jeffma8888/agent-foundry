"""Black-box behaviour tests for iter 175 -- ONE shared README-index rule in `foundry.py`, plus a
`tests/`-WIDE snapshot-pin scanner whose domain is not a single file.

Spec: products/_platform/state/iter-175/pm.md, Expected Behaviors 1-11.

  1. `foundry.readme_index_number_violations(numbers)` is a PURE rule; `()` on the live README.
  2. It is two-sided and preserves the exact message substrings iteration 174's samples assert.
  3. GROWTH is accepted -- no result may depend on the LENGTH of the list or on its maximum.
  4. `required` / `adjacent` / `contiguous` are opt-in keyword-only params, defaults unchanged.
  5. `tests/test_iter169_behavior.py` keeps the NAME `index_numbers_pin_violations` and DELEGATES.
  6. `foundry.readme_index_pin_shape_hits(sources)` is a pure `tests/`-wide scanner over a mapping.
  7. It is calibrated two-sided BOTH directions: shape+token fires, shape-only and token-only do not.
  8. The live `tests/` domain scans clean, and that domain PROVABLY contains THIS file.
  9. The two iteration-174 position pins are gone from `tests/test_iter173_behavior.py`, and their
     real intent (uniqueness / presence / ascending / no gap) is preserved via the shared rule.
 10. The `filecmp` byte-identity freeze is retired for a fresh-clone-decidable successor.
 11. Nothing on a control path changes: zero call sites, no new verb, both modules still import.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-175 PM spec's Expected Behaviors, the
conventions of `tests/test_iter169_behavior.py` / `tests/test_iter166_behavior.py` /
`tests/test_iter174_behavior.py`, and the product's OWN OBSERVABLE surface -- CALLING its public
functions, reading its public constants, RUNNING `git` and fresh-interpreter import probes, and
reading the SHIPPED prose of README.md.  `foundry.py`'s and `dispatcher.py`'s implementation TEXT
was NOT read by the author, and neither were the engineer's notes, the reviewer's notes, nor
`git diff`.  Behaviors 5 and 11 must look AT source text; both do so MECHANICALLY inside the test
(`ast` / `inspect.getsource`) -- machine checks the author never read.

Offline and deterministic: no network, no agent run, no sleeps, no clock.  Subprocesses are only
read-only `git` verbs and two `python -c "import ..."` probes.  NOTHING in the repo is mutated.

CLONE-SAFETY (OPERATOR 2026-08-11): no assertion depends on gitignored ambient state.  Every input
is either a tracked file, a value assembled in memory, or a `tmp_path` fixture.

SELF-DOMAIN NOTE: this module carries a README-index-extraction token (`SECTION_RE`), so it is
INSIDE the domain behavior 8 scans.  Every planted known-bad sample is therefore ASSEMBLED FROM
FRAGMENTS at runtime (the `tests/test_iter166_behavior.py` `_LAST_INDEX` technique) so no forbidden
shape ever appears contiguously in this file's own text.

AMBIGUITY NOTED (PM feedback), Behavior 6: the spec says the scanner returns "a sorted tuple of
`(name, shape_label)` pairs" but does not say whether one source may yield MORE than one label.
The reading tested here is that it may -- a source carrying two distinct shapes yields two pairs --
because a scanner that stopped at the first shape would hide the second from the operator.
"""
from __future__ import annotations

import ast
import builtins
import importlib.util
import inspect
import pathlib
import re
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402

THIS_ITER = 175
README = _ROOT / "README.md"
TESTS = _ROOT / "tests"
ROLES = _ROOT / "roles"

# Pinned HERE, never imported from the module under test.
SECTION_RE = re.compile(r"^#\s+\d+\.", re.MULTILINE)
CONTROL_PATH = ("run_stage", "run_iteration", "build_prompt", "postrelease_step")
NEW_NAMES = ("readme_index_number_violations", "readme_index_pin_shape_hits")
STRICT = dict(required=("0", "42", "49", "50", "51"), contiguous=True)

# ---------------------------------------------------------------- fragment-assembled samples
# Assembled so the forbidden shapes never appear contiguously in THIS file (see SELF-DOMAIN NOTE).
_EQ = "=" + "="
_TOKEN = "^# " + "(" + chr(92) + "d+)" + chr(92) + "."
_MAX_SHAPE = "    assert max(int(n) for n in nums) " + _EQ + " 51\n"
_RANGE_SHAPE = "    assert sorted(nums) " + _EQ + " list(range(52))\n"
_SLICE_SHAPE = "    assert nums" + "[" + "-2:" + "] " + _EQ + " [" + '"49", "50"' + "]\n"
_SHAPES = (("max-int-pin", _MAX_SHAPE),
           ("sorted-range-pin", _RANGE_SHAPE),
           ("trailing-slice-pin", _SLICE_SHAPE))

_MAX_NEEDLE = re.compile(r"max\s*\(\s*int[^\n]*?" + _EQ + r"\s*-?\d+")
_RANGE_NEEDLE = re.compile(r"sorted\s*\([^\n]*?\)\s*" + _EQ + r"\s*list\s*\(\s*range")
_SLICE_NEEDLE = re.compile(r"\[\s*-\s*\d+\s*:\s*\]\s*" + _EQ + r"\s*\[")
_NEEDLES = (("max-int-pin", _MAX_NEEDLE),
            ("sorted-range-pin", _RANGE_NEEDLE),
            ("trailing-slice-pin", _SLICE_NEEDLE))


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(_ROOT), capture_output=True, text=True)


def _load_test_helper(module_stem: str):
    """Load a sibling test module by PATH -- `tests/` is not a package."""
    path = TESTS / (module_stem + ".py")
    assert path.is_file(), "missing sibling test module: %s" % module_stem
    spec = importlib.util.spec_from_file_location("_h175_" + module_stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _readme_numbers() -> list[str]:
    text = README.read_text(encoding="utf-8")
    return [h.strip().lstrip("#").strip().rstrip(".") for h in SECTION_RE.findall(text)]


def _tests_domain() -> dict:
    """Every `tests/**/*.py` by DIRECTORY GLOB -- deliberately not `git ls-files`, so a module
    created in this iteration is inside the domain immediately (no `git add -N` needed)."""
    return {str(p.relative_to(_ROOT)): p.read_text(encoding="utf-8")
            for p in sorted(TESTS.rglob("*.py"))}


def _forbid_io(monkeypatch) -> None:
    def boom(*_a, **_k):  # pragma: no cover - the point is that it never runs
        raise AssertionError("a PURE rule must perform no I/O")
    monkeypatch.setattr(builtins, "open", boom)
    monkeypatch.setattr(pathlib.Path, "read_text", boom)
    monkeypatch.setattr(pathlib.Path, "open", boom)
    monkeypatch.setattr(subprocess, "run", boom)


# =========================================================== 1. the hoisted rule is pure & clean

def test_b1_the_rule_is_a_public_module_level_function_of_foundry():
    rule = getattr(foundry, "readme_index_number_violations", None)
    assert inspect.isfunction(rule), "the README section-number contract must live in foundry.py"
    assert rule.__module__ == "foundry"


def test_b1_the_rule_accepts_the_live_readme_number_list():
    numbers = _readme_numbers()
    assert len(numbers) >= 49, "the live README index shrank unexpectedly: %d" % len(numbers)
    assert foundry.readme_index_number_violations(numbers) == ()


def test_b1_the_rule_does_no_io(monkeypatch):
    numbers = _readme_numbers()  # read BEFORE the I/O ban
    _forbid_io(monkeypatch)
    assert foundry.readme_index_number_violations(numbers) == ()
    assert foundry.readme_index_number_violations(["49", "50", "42"]) != ()


def test_b1_the_rule_is_deterministic_and_does_not_mutate_its_input():
    numbers = _readme_numbers()
    before = list(numbers)
    first = foundry.readme_index_number_violations(numbers)
    second = foundry.readme_index_number_violations(numbers)
    assert first == second == ()
    assert numbers == before, "the rule mutated the list it was handed"


# =========================================================== 2. two-sided, message substrings kept

_BAD_SAMPLES = (
    (["42", "42", "49", "50"], "duplicate"),
    (["49", "50"], "'42' missing"),
    (["49", "50", "42"], "ascending"),
    (["42", "49", "50", "fifty-one"], "non-integer"),
    (["42", "49", "51", "50"], "does not immediately follow"),
    (["42", "50", "49"], "does not immediately follow"),
)


@pytest.mark.parametrize("numbers,needle", _BAD_SAMPLES)
def test_b2_each_known_bad_sample_is_rejected_with_its_named_substring(numbers, needle):
    out = foundry.readme_index_number_violations(numbers)
    assert out, "sample %r must be rejected" % (numbers,)
    assert any(needle in v for v in out), \
        "sample %r -> %r, expected a message containing %r" % (numbers, out, needle)


@pytest.mark.parametrize("dropped", ["49", "50"])
def test_b2_dropping_a_required_number_from_the_live_list_is_rejected(dropped):
    numbers = [n for n in _readme_numbers() if n != dropped]
    out = foundry.readme_index_number_violations(numbers)
    assert any(("'%s' missing" % dropped) in v for v in out), out


def test_b2_a_non_integer_entry_never_raises_from_a_later_check():
    for numbers in (["42", "49", "50", "fifty-one"], ["x", "42", "49", "50"], ["42", "", "49", "50"]):
        out = foundry.readme_index_number_violations(numbers)
        assert isinstance(out, tuple) and out, numbers
        assert all(isinstance(v, str) for v in out)


# =========================================================== 3. growth is ACCEPTED

@pytest.mark.parametrize("extra", [["52"], ["52", "53", "54"], [str(n) for n in range(52, 70)]])
def test_b3_appending_new_sections_stays_clean(extra):
    numbers = _readme_numbers() + extra
    assert foundry.readme_index_number_violations(numbers) == ()
    assert foundry.readme_index_number_violations(numbers, **STRICT) == ()


def test_b3_no_result_depends_on_the_length_or_the_maximum():
    """The defect this iteration retires is 'the last section when I was written is last forever'.
    So growing the list must not change the verdict, in either the clean or the dirty direction."""
    live = _readme_numbers()
    grown = live + [str(n) for n in range(52, 60)]
    assert foundry.readme_index_number_violations(live) \
        == foundry.readme_index_number_violations(grown) == ()
    dirty_live = [n for n in live if n != "50"]
    dirty_grown = [n for n in grown if n != "50"]
    assert foundry.readme_index_number_violations(dirty_live) \
        == foundry.readme_index_number_violations(dirty_grown)


# =========================================================== 4. opt-in keyword-only parameters

def test_b4_the_extra_checks_are_keyword_only_with_the_specified_defaults():
    sig = inspect.signature(foundry.readme_index_number_violations)
    params = list(sig.parameters.values())
    assert params[0].name == "numbers"
    by_name = {p.name: p for p in params[1:]}
    assert set(by_name) == {"required", "adjacent", "contiguous"}, sorted(by_name)
    for p in by_name.values():
        assert p.kind is inspect.Parameter.KEYWORD_ONLY, "%s must be keyword-only" % p.name
    assert tuple(by_name["required"].default) == ("42", "49", "50")
    assert tuple(by_name["adjacent"].default) == ("49", "50")
    assert by_name["contiguous"].default is False


def test_b4_an_interior_gap_is_tolerated_by_default_and_rejected_when_contiguous():
    live = _readme_numbers()
    interior = next(n for n in live if n not in ("0", "42", "49", "50", "51"))
    gapped = [n for n in live if n != interior]
    assert foundry.readme_index_number_violations(gapped) == (), \
        "the DEFAULT rule must stay byte-semantically what iteration 174 shipped"
    out = foundry.readme_index_number_violations(gapped, contiguous=True)
    assert any("gap" in v for v in out), out


# =========================================================== 5. iteration 169 keeps the NAME

def test_b5_the_iteration_169_name_survives_and_returns_the_same_results():
    mod = _load_test_helper("test_iter169_behavior")
    pin = getattr(mod, "index_numbers_pin_violations", None)
    assert callable(pin), "the published helper name must stay in test_iter169_behavior.py"
    live = _readme_numbers()
    assert pin(live) == foundry.readme_index_number_violations(live) == ()
    for numbers, needle in _BAD_SAMPLES:
        assert pin(numbers) == foundry.readme_index_number_violations(numbers)
        assert any(needle in v for v in pin(numbers))


def test_b5_the_rule_body_is_not_duplicated_in_that_module():
    """MECHANICAL: parse the helper and assert its executable body is a single delegating
    `return`, so there is no second copy of the checks to drift out of step."""
    source = (TESTS / "test_iter169_behavior.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    fn = next((n for n in tree.body
               if isinstance(n, ast.FunctionDef) and n.name == "index_numbers_pin_violations"), None)
    assert fn is not None, "index_numbers_pin_violations must be module-level in that file"
    body = [n for n in fn.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
                                       and isinstance(n.value.value, str))]
    assert len(body) == 1 and isinstance(body[0], ast.Return), \
        "the body must delegate, not re-implement: %r" % [type(n).__name__ for n in body]
    assert "readme_index_number_violations" in ast.unparse(body[0])


# =========================================================== 6/7. the tests-wide scanner

def test_b6_the_scanner_is_a_public_pure_function_over_a_mapping():
    scan = getattr(foundry, "readme_index_pin_shape_hits", None)
    assert inspect.isfunction(scan) and scan.__module__ == "foundry"
    assert scan({}) == ()
    labels = {label for label, _ in _SHAPES}
    got = scan({"z.py": _TOKEN + _MAX_SHAPE, "a.py": _TOKEN + _SLICE_SHAPE})
    assert isinstance(got, tuple) and all(isinstance(pair, tuple) and len(pair) == 2 for pair in got)
    assert got == tuple(sorted(got)), "hits must come back SORTED: %r" % (got,)
    assert {name for name, _ in got} == {"a.py", "z.py"}
    assert {label for _, label in got} <= labels, got


def test_b6_the_scanner_does_no_io(monkeypatch):
    sample = {"planted.py": _TOKEN + _MAX_SHAPE}
    _forbid_io(monkeypatch)
    assert foundry.readme_index_pin_shape_hits(sample) == (("planted.py", "max-int-pin"),)
    assert foundry.readme_index_pin_shape_hits({"clean.py": _TOKEN}) == ()


@pytest.mark.parametrize("label,shape", _SHAPES)
def test_b7_the_scanner_fires_on_a_shape_carrying_an_index_token(label, shape):
    assert foundry.readme_index_pin_shape_hits({"planted.py": _TOKEN + shape}) \
        == (("planted.py", label),)


@pytest.mark.parametrize("label,shape", _SHAPES)
def test_b7_the_scanner_is_silent_on_the_same_shape_with_no_token(label, shape):
    """The FALSE-POSITIVE control: a legitimate `tmp_path` fixture walk that never reads the
    README index may pin whatever it likes."""
    assert foundry.readme_index_pin_shape_hits({"fixture.py": shape}) == ()


def test_b7_the_scanner_is_silent_on_a_token_with_no_shape():
    body = _TOKEN + "\n    assert numbers == sorted(numbers, key=int)\n"
    assert foundry.readme_index_pin_shape_hits({"reader.py": body}) == ()


def test_b7_the_token_tuple_is_read_at_call_time_with_an_unpatched_positive_control(monkeypatch):
    """Patching the constant must change the verdict (proving a CALL-time read) WITHOUT being the
    fail-open lever: an unpatched plant stays visible in the same call, so a silenced scanner
    cannot be mistaken for a clean tree."""
    assert tuple(foundry.README_INDEX_EXTRACTION_TOKENS), "the token tuple must be non-empty"
    other = "ZZ" + "_INDEX_TOKEN_" + chr(92) + "d+"
    monkeypatch.setattr(foundry, "README_INDEX_EXTRACTION_TOKENS", (other, _TOKEN))
    got = foundry.readme_index_pin_shape_hits({"custom.py": other + "\n" + _MAX_SHAPE,
                                              "control.py": _TOKEN + _MAX_SHAPE})
    assert got == (("control.py", "max-int-pin"), ("custom.py", "max-int-pin")), got


# =========================================================== 8. the live domain, including THIS file

def test_b8_the_live_tests_domain_scans_clean():
    hits = foundry.readme_index_pin_shape_hits(_tests_domain())
    assert hits == (), "live snapshot pins under tests/: %r" % (hits,)


def test_b8_the_domain_contains_the_module_being_written_right_now():
    """The explicit proof this guard is not blind to its own file the way iteration 174's was."""
    domain = _tests_domain()
    mine = str(pathlib.Path(__file__).resolve().relative_to(_ROOT))
    assert mine in domain, "this module must be inside the scanned domain: %r" % mine
    assert len(domain) >= 100, "the domain collapsed to %d files" % len(domain)
    tracked = _git("ls-files", "--error-unmatch", mine)
    assert tracked.returncode != 0 or tracked.stdout.strip(), tracked.stderr
    assert SECTION_RE.pattern in domain[mine], \
        "this module must carry an index token, else behavior 8 proves nothing about it"


# =========================================================== 9. the two live pins are gone

@pytest.mark.parametrize("label,needle", _NEEDLES)
def test_b9_no_fragile_shape_remains_in_the_iteration_173_module(label, needle):
    source = (TESTS / "test_iter173_behavior.py").read_text(encoding="utf-8")
    found = needle.findall(source)
    assert found == [], "%s still present in test_iter173_behavior.py: %r" % (label, found)


def test_b9_the_iteration_173_module_asserts_the_intent_through_the_shared_rule():
    source = (TESTS / "test_iter173_behavior.py").read_text(encoding="utf-8")
    assert source.count("readme_index_number_violations") >= 2, \
        "both relaxed asserts must route through the shared rule"
    assert 'contiguous=True' in source
    for kept in ('"foundry.py losses" in readme', 'sections_scanned >= 49'):
        assert kept in source, "surrounding assert must stay untouched: %s" % kept
    for section in ("49", "50", "51"):
        assert ('"' + chr(92) + "n# " + section + '."') in source, \
            "the presence loop for # %s. must stay" % section


def test_b9_the_preserved_intent_actually_rejects_the_regressions_it_names():
    live = _readme_numbers()
    for broken in ([n for n in live if n != "51"], live + ["51"], list(reversed(live))):
        assert foundry.readme_index_number_violations(broken, **STRICT) != (), broken


# =========================================================== 10. the byte-identity freeze is retired

_RELANDED = ((172, "kill_rate"), (173, "attempt_loss_summary"))


def _b4_source() -> str:
    """Iteration 174's re-land behaviour as EXECUTABLE code -- decorators included, docstring and
    comments excluded.  Behavior 10 is about what the test READS, and the retired freeze is still
    described in that test's own prose (correctly: it records why it retired).  Asserting over the
    raw segment would score that explanation as the defect it explains."""
    source = (TESTS / "test_iter174_behavior.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    fn = next((n for n in tree.body
               if isinstance(n, ast.FunctionDef) and n.name.startswith("test_b4_relanded")), None)
    assert fn is not None, "iteration 174's re-land behaviour test disappeared entirely"
    fn.body = [n for n in fn.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
                                          and isinstance(n.value.value, str))]
    assert fn.body, "the re-land behaviour test has no executable body"
    return ast.unparse(fn)


@pytest.mark.parametrize("iteration,marker", _RELANDED)
def test_b10_the_relanded_module_is_asserted_without_any_gitignored_path(iteration, marker):
    """Behavior 10: the successor must be decidable from a bare checkout."""
    live = TESTS / ("test_iter%d_behavior.py" % iteration)
    assert live.is_file() and live.read_text(encoding="utf-8").strip()
    tracked = _git("ls-files", "--error-unmatch", str(live.relative_to(_ROOT)))
    assert tracked.returncode == 0, tracked.stderr
    source = live.read_text(encoding="utf-8")
    assert source.count("def test_") >= 20, source.count("def test_")
    assert marker in source, "re-land content marker %r is missing" % marker


def test_b10_the_byte_identity_freeze_is_gone_from_that_behaviour():
    body = _b4_source()
    assert body, "could not locate the re-land behaviour test"
    for banned in ("filecmp", "products/_platform/state", "state/iter-172", "state/iter-173",
                   "pytest.skip"):
        assert banned not in body, \
            "the retired freeze still references %r:\n%s" % (banned, body)
    assert "ls-files" in body, "the successor must ask git what it tracks"
    assert ">= 20" in body, "the >= 20 test-function FLOOR must be the assertion"
    for marker in ("kill_rate", "attempt_loss_summary"):
        assert marker in body, "content marker %r must still be asserted" % marker


def test_b10_that_behaviour_is_still_wired_as_a_two_case_parametrisation():
    mod = _load_test_helper("test_iter174_behavior")
    fn = next((v for k, v in vars(mod).items() if k.startswith("test_b4_relanded")), None)
    assert fn is not None
    for iteration, marker in _RELANDED:
        fn(iteration, marker)   # drives iteration 174's own successor assertion, live


# =========================================================== 11. nothing on a control path changes

@pytest.mark.parametrize("fn_name", CONTROL_PATH)
def test_b11_no_control_path_function_calls_either_new_function(fn_name):
    fn = getattr(foundry, fn_name, None)
    assert fn is not None, "control-path function %s vanished" % fn_name
    body = inspect.getsource(fn)
    for name in NEW_NAMES:
        assert name not in body, "%s must stay DORMANT, but %s calls it" % (name, fn_name)


def test_b11_the_other_entry_point_and_the_role_cards_are_untouched():
    other = _ROOT / foundry.README_INDEX_OTHER_ENTRY_POINT
    assert other.is_file(), other
    text = other.read_text(encoding="utf-8")
    for name in NEW_NAMES:
        assert name not in text, "%s leaked into %s" % (name, other.name)
    cards = sorted(ROLES.glob("*.md"))
    assert cards, "role cards vanished"
    for card in cards:
        card_text = card.read_text(encoding="utf-8")
        for name in NEW_NAMES:
            assert name not in card_text, "%s leaked into roles/%s" % (name, card.name)


def test_b11_no_new_cli_verb_and_the_readme_index_brake_is_green():
    text = README.read_text(encoding="utf-8")
    verbs = foundry.foundry_cli_verbs((_ROOT / "foundry.py").read_text(encoding="utf-8"))
    for name in NEW_NAMES:
        assert name not in verbs, "%s must not be a CLI verb" % name
    audit = foundry.readme_verb_index_gaps(text, verbs)
    assert audit.missing_verbs == (), audit.missing_verbs
    assert audit.unknown_invocations == (), audit.unknown_invocations
    assert audit.sections_without_invocation == (), audit.sections_without_invocation
    assert audit.ok is True
    numbers = _readme_numbers()
    assert numbers == sorted(numbers, key=int) and len(numbers) == len(set(numbers))


@pytest.mark.parametrize("module", ["foundry", "dispatcher"])
def test_b11_module_still_imports_from_a_clean_interpreter(module):
    proc = subprocess.run([sys.executable, "-c", "import " + module],
                          cwd=str(_ROOT), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
