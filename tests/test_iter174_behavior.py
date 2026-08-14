"""Black-box behaviour tests for iter 174 -- LAND the twice-lost iter-172 + iter-173 work and
remove the two structural traps that destroyed it.

Spec: products/_platform/state/iter-174/pm.md, Expected Behaviors 1-11.

  1. The re-landed iter-172 metric: `kill_rate` on `RescueRow` and `RescueSummary`, in `to_dict()`,
     emitted by `render()` AFTER the existing rescue-rate token, `None` when `attempts == 0`.
  2. The re-landed iter-173 verb: the frozen `LossRow` / `LossSummary`, keyword-only
     `attempt_loss_summary`, the total `_loss_fields` reader, the one `gather_losses` seam and
     `losses_cli`; the `losses` subcommand prints ONE JSON document, exits 0 / 1 / 2, honours
     `--limit N`, and writes no file and creates no directory.
  3. Every `LossRow.kind` is a label `classify_attempt_failure` returns; that classifier is
     unmodified; `lost <= attempts` with `attempts` a STORED field.
  4. Both re-landed test modules are present, TRACKED by git, non-trivial (a >= 20 test-function
     floor) and carry their re-land content marker.  RETIRED iter 175: the original byte-identity
     comparison against copies under gitignored state was undecidable in a fresh clone AND froze
     two live modules against repair; the re-land is now settled by git history.
  5. README carries a `# 51.` section titled for `losses` with a runnable invocation, and
     `readme_verb_index_gaps` over the LIVE README + LIVE verb set is clean.
  6. The section pin no longer depends on POSITION: iteration 169's rule is a pure function that
     accepts the live README, and its position assert is gone from that module's text.
  7. That rewritten pin is two-sided: it REJECTS seven named known-bad number lists and ACCEPTS
     the good one.
  8. The 5th team's config is ignored by `products/.gitignore` (not by a local exclude file), in
     the live repo and in a hermetic `git init` fixture built in `tmp_path`.
  9. The two tracked configs stay SOURCE: still in `git ls-files`, NOT ignored, and the new rule
     names exactly ONE literal path with no wildcard.
 10. Every landing iteration owns a durable record in THIS commit: ledger rows and archive
     bullets for 172 / 173 / 174, no ledger or archive gaps, index inside both budgets.
 11. No new call site on the running control path; `foundry` and `dispatcher` both import in a
     FRESH interpreter.

ISOLATION CONTRACT (HONORED): written ONLY from the iter-174 PM spec's Expected Behaviors, the
conventions of `tests/test_iter169_behavior.py` and `tests/test_iter173_behavior.py`, and the
product's OWN OBSERVABLE surface -- constructing its public dataclasses, CALLING its public
functions, RUNNING its CLI and `git`, and reading the SHIPPED prose of README.md /
PLATFORM_ROADMAP.md / PLATFORM_ROADMAP_ARCHIVE.md / products/.gitignore, which Behaviors 5, 8, 9
and 10 make the deliverable itself.  `foundry.py`'s and `dispatcher.py`'s implementation TEXT was
NOT read by the author, and neither were the engineer's notes, the reviewer's notes, the fix
notes, nor `git diff`.  Behaviors 3 and 11 must look AT source text; both do so MECHANICALLY
through `inspect.getsource` INSIDE the test -- a machine check the author never read.

Offline and deterministic: no network, no agent run, no sleeps, no clock.  Subprocesses are only
`git` (read-only verbs, plus a throwaway `git init` inside `tmp_path`), the product's own CLI, and
two fresh-interpreter import probes.  NOTHING in the repo is mutated.

CLONE-SAFETY (OPERATOR 2026-08-11, tightened iter 175): no assertion depends on gitignored ambient
state.  Behavior 4 no longer reads `products/_platform/state/` at all -- it asks git what it tracks,
which answers identically in a fresh clone; the `losses` CLI probe accepts exit 2 ("nothing to
scan"), which is exactly what a fresh clone with no state dir returns, and compares the state dir
only against ITSELF; every other fixture is built in `tmp_path` or in memory.

AMBIGUITY NOTED (PM feedback), Behavior 1: the spec calls `kill_rate` a "field ... derived as
`kills / attempts` (one decimal)".  Observably it is a `@property` (not a `dataclasses.field`) and
it is a PERCENTAGE -- `84/200 -> 42.0`, matching the sibling `rescue_rate` token in the same
rendered line.  The percentage reading is the one asserted here, because the two rates share a
line and a `render()` suffix and a ratio-vs-percent mismatch between them would be the defect.
"""
from __future__ import annotations

import dataclasses
import importlib.util
import inspect
import json
import pathlib
import re
import shutil
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402

THIS_ITER = 174
README = _ROOT / "README.md"
ROADMAP = _ROOT / "PLATFORM_ROADMAP.md"
ARCHIVE = _ROOT / "PLATFORM_ROADMAP_ARCHIVE.md"
PRODUCTS_IGNORE = _ROOT / "products" / ".gitignore"
PLATFORM_CFG = "products/_platform/config.json"
REPOLENS_CFG = "products/repolens/config.json"
FIFTH_CFG = "products/agent-gap-radar/config.json"

# Pinned HERE, never imported from the module under test.
SECTION_RE = re.compile(r"^#\s+\d+\.", re.MULTILINE)
LOSS_KINDS = ("cli-error", "other", "service", "stalled", "timeout")
CONTROL_PATH = ("run_stage", "run_iteration", "build_prompt", "postrelease_step")
NEW_NAMES = ("gather_losses", "losses_cli", "attempt_loss_summary")
LANDED_ITERS = (172, 173, 174)


def _git(*args: str, cwd: pathlib.Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd or _ROOT), capture_output=True, text=True)


def _load_test_helper(module_stem: str):
    """Load a sibling test module by PATH -- `tests/` is not a package, and the helpers these
    behaviours are defined against (the iteration-169 pin, the iteration-167 index allowance)
    live in those modules rather than in `foundry.py`."""
    path = _ROOT / "tests" / (module_stem + ".py")
    assert path.is_file(), "missing sibling test module: %s" % module_stem
    spec = importlib.util.spec_from_file_location("_helper_" + module_stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _readme_numbers(text: str) -> list[str]:
    return [h.strip().lstrip("#").strip().rstrip(".") for h in SECTION_RE.findall(text)]


def _sections(text: str) -> dict:
    out, starts = {}, [m.start() for m in SECTION_RE.finditer(text)]
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(text)
        chunk = text[start:end]
        out[chunk.split(".", 1)[0].lstrip("#").strip()] = chunk
    return out


# ------------------------------------------------------- 1. the re-landed iter-172 kill_rate

def _row(**kw):
    base = dict(stage="engineer", attempts=200, kills=84, rescued=75, lost=9)
    base.update(kw)
    return foundry.RescueRow(**base)


def test_b1_kill_rate_is_exposed_by_both_rescue_classes():
    for cls in (foundry.RescueRow, foundry.RescueSummary):
        assert dataclasses.is_dataclass(cls) and cls.__dataclass_params__.frozen
        member = vars(cls).get("kill_rate")
        assert isinstance(member, property), \
            "%s must expose kill_rate as a derived property, not a stored field" % cls.__name__


def test_b1_kill_rate_is_kills_over_attempts_to_one_decimal():
    assert _row().kill_rate == 42.0, "84 of 200 kills is 42.0%"
    assert _row(attempts=3, kills=1).kill_rate == 33.3, "one decimal, rounded"
    summary = foundry.RescueSummary(product="p", rows=(_row(), _row(stage="tester", attempts=100,
                                                              kills=60, rescued=55, lost=5)))
    assert summary.kill_rate == round(144 / 300 * 100, 1) == 48.0


def test_b1_kill_rate_is_none_when_there_are_no_attempts():
    assert _row(attempts=0, kills=0, rescued=0, lost=0).kill_rate is None
    assert foundry.RescueSummary(product="p", rows=()).kill_rate is None


def test_b1_kill_rate_is_in_both_to_dicts():
    assert "kill_rate" in _row().to_dict()
    assert "kill_rate" in foundry.RescueSummary(product="p", rows=(_row(),)).to_dict()


def test_b1_render_emits_kill_rate_after_the_rescue_rate_token():
    # distinct values so position is unambiguous: rescue rate 89.3, kill rate 42.0
    text = foundry.RescueSummary(product="p", rows=(_row(),)).render()
    assert "89.3" in text and "42.0" in text, text
    for line in text.splitlines():
        if "89.3" in line:
            assert "42.0" in line, "both rates belong on the same line: %r" % line
            assert line.index("42.0") > line.index("89.3"), \
                "kill rate must follow the rescue-rate token: %r" % line


# ------------------------------------------------------- 2. the re-landed iter-173 losses verb

def _sa(stage="tester", produced=False, kind="stalled"):
    return foundry.StageAttempt(team="p", iteration=1, stage=stage, attempt=1, duration_s=1.0,
                                produced=produced, kind=kind)


def test_b2_the_specced_names_exist_with_the_specced_shapes():
    assert tuple(f.name for f in dataclasses.fields(foundry.LossRow)) == ("kind", "lost", "stages")
    assert tuple(f.name for f in dataclasses.fields(foundry.LossSummary)) == (
        "product", "rows", "attempts")
    for cls in (foundry.LossRow, foundry.LossSummary):
        assert cls.__dataclass_params__.frozen, "%s must be frozen" % cls.__name__
    params = inspect.signature(foundry.attempt_loss_summary).parameters
    assert [p.kind for p in params.values()] == [inspect.Parameter.KEYWORD_ONLY] * 2, \
        "attempt_loss_summary must be keyword-only: %s" % list(params)
    assert list(inspect.signature(foundry.gather_losses).parameters) == ["cfg", "limit"]
    assert list(inspect.signature(foundry.losses_cli).parameters) == ["cfg", "limit", "as_json"]


def test_b2_loss_fields_is_a_total_reader():
    assert foundry._loss_fields(_sa()) == ("tester", False, "stalled")
    for junk in (None, 7, "text", object(), {}):
        assert foundry._loss_fields(junk) is None, "a total reader returns None, never raises"


def test_b2_exit_codes_are_zero_one_two():
    nothing = foundry.attempt_loss_summary(product="p", records=())
    assert (nothing.attempts, nothing.lost, nothing.exit_code) == (0, 0, 2), nothing.to_dict()
    clean = foundry.attempt_loss_summary(product="p", records=[_sa(produced=True, kind="ok")])
    assert (clean.lost, clean.exit_code) == (0, 0), clean.to_dict()
    lossy = foundry.attempt_loss_summary(product="p", records=[_sa(), _sa(produced=True,
                                                                     kind="ok")])
    assert (lossy.attempts, lossy.lost, lossy.exit_code) == (2, 1, 1), lossy.to_dict()


def test_b2_cli_prints_one_json_document_and_writes_nothing(tmp_path):
    state = _ROOT / "products" / "_platform" / "state"
    before = sorted(p.name for p in state.iterdir()) if state.is_dir() else None
    proc = subprocess.run([sys.executable, "foundry.py", "losses", "--config", PLATFORM_CFG,
                           "--json"], cwd=str(_ROOT), capture_output=True, text=True)
    assert proc.returncode in (0, 1, 2), (proc.returncode, proc.stderr[-400:])
    if proc.returncode != 2 or proc.stdout.strip():
        doc = json.loads(proc.stdout)  # ONE document: a second would raise here
        assert doc["product"] == "_platform"
        assert doc["lost"] <= doc["attempts"]
    after = sorted(p.name for p in state.iterdir()) if state.is_dir() else None
    assert after == before, "a read-only verb must create no file and no directory"


def test_b2_limit_restricts_the_scan():
    def run(*extra):
        return subprocess.run([sys.executable, "foundry.py", "losses", "--config", PLATFORM_CFG,
                               "--json", *extra], cwd=str(_ROOT), capture_output=True, text=True)
    full, limited = run(), run("--limit", "1")
    if full.returncode == 2 and not full.stdout.strip():
        pytest.skip("no iteration dirs to scan in this checkout (fresh clone)")
    a, b = json.loads(full.stdout), json.loads(limited.stdout)
    assert b["attempts"] <= a["attempts"], "--limit must never widen the scan"


# ------------------------------------------------------- 3. every kind is a classifier label

def test_b3_kind_labels_come_from_the_shipped_classifier():
    """Derived from the classifier's OWN public rule table, not from a source scan: the labels are
    data (`ATTEMPT_FAILURE_MARKERS` + `ATTEMPT_FAILURE_DEFAULT`), so the pin can be checked against
    the shipped table and every label proven REACHABLE by its own first token."""
    labelled = tuple(label for label, _tokens in foundry.ATTEMPT_FAILURE_MARKERS)
    found = sorted(set(labelled) | {foundry.ATTEMPT_FAILURE_DEFAULT})
    assert found == sorted(LOSS_KINDS), "classifier labels drifted from the pin: %s" % found
    assert len(set(labelled)) == len(labelled), "duplicate label in the rule table: %s" % (labelled,)
    for label, tokens in foundry.ATTEMPT_FAILURE_MARKERS:
        blob = "prefix " + tokens[0] + " suffix"
        assert foundry.classify_attempt_failure(blob) == label, (label, blob)
    assert foundry.classify_attempt_failure("") == foundry.ATTEMPT_FAILURE_DEFAULT == "other"
    assert foundry.classify_attempt_failure("nothing recognisable here") == "other"


def test_b3_rows_are_classified_and_lost_never_exceeds_stored_attempts():
    summary = foundry.attempt_loss_summary(
        product="p", records=[_sa(), _sa(stage="pm", kind="timeout"),
                              _sa(stage="final", kind="cli-error"),
                              _sa(stage="pm", produced=True, kind="ok")])
    assert all(r.kind in LOSS_KINDS for r in summary.rows), [r.kind for r in summary.rows]
    assert summary.lost <= summary.attempts
    assert "attempts" in {f.name for f in dataclasses.fields(foundry.LossSummary)}, \
        "attempts must be STORED: a rescued attempt owns no row to derive it from"
    assert summary.attempts == 4 and summary.lost == 3


# ------------------------------------------------------- 4. both re-landed modules are present

@pytest.mark.parametrize("iteration,marker", [(172, "kill_rate"), (173, "attempt_loss_summary")])
def test_b4_relanded_test_module_is_tracked_and_carries_its_re_land_content(iteration, marker):
    """Behavior 4: prove the re-land LANDED -- decidably, in a FRESH CLONE.

    RETIRED iter 175.  This assertion used to demand byte-identity against a preserved copy under
    `products/_platform/state/`, and that is two defects in one line.  (1) The path is GITIGNORED,
    so the check was only meaningful on the machine that ran the re-land and degraded to a skip
    anywhere else -- the ambient-tree precondition class that turned iteration 154 post-release
    BROKEN.  (2) Byte-identity froze two LIVE test modules, so the snapshot pins inside them could
    not be fixed at all; iteration 174's own engineer hit exactly that wall and correctly flagged
    instead of silently editing.

    Its purpose -- prove the re-land was VERBATIM rather than a paraphrase -- was ONE-SHOT and is
    spent: both modules shipped in the release commit and `git ls-files` tracks them, so the
    verbatim question is settled in git history and cannot regress silently.  The successor asserts
    what still matters and is decidable from a bare checkout: the module exists, is TRACKED, is
    non-trivial, and carries the content marker of the feature it re-landed.
    """
    live = _ROOT / "tests" / ("test_iter%d_behavior.py" % iteration)
    assert live.is_file(), "the re-landed iter-%d module must be under tests/" % iteration
    source = live.read_text(encoding="utf-8")
    assert source.strip(), "the re-landed iter-%d module is empty" % iteration
    tracked = _git("ls-files", "--error-unmatch", str(live))
    assert tracked.returncode == 0, \
        "git must TRACK the re-landed iter-%d module: %r" % (iteration, tracked.stderr)
    # A FLOOR, deliberately well under the live counts (31 and 64).  Pinning the live count would
    # re-commit the very snapshot-as-law defect this iteration retires.
    assert source.count("def test_") >= 20, \
        "iter-%d module holds only %d test functions" % (iteration, source.count("def test_"))
    assert marker in source, \
        "iter-%d re-land content marker %r is missing" % (iteration, marker)


# ------------------------------------------------------- 5. the README index is green with # 51

def test_b5_readme_has_a_losses_section_with_a_runnable_invocation():
    text = README.read_text(encoding="utf-8")
    body = _sections(text).get("51")
    assert body, "expected a '# 51.' section, saw %s" % _readme_numbers(text)[-4:]
    assert "losses" in body.splitlines()[0], "section 51 must be titled for losses"
    assert "foundry.py losses" in body, "section 51 needs a runnable invocation"


def test_b5_live_readme_index_audit_is_clean():
    text = README.read_text(encoding="utf-8")
    verbs = foundry.foundry_cli_verbs((_ROOT / "foundry.py").read_text(encoding="utf-8"))
    assert "losses" in verbs, "losses must be a real CLI verb"
    audit = foundry.readme_verb_index_gaps(text, verbs)
    assert audit.missing_verbs == (), audit.missing_verbs
    assert audit.unknown_invocations == (), audit.unknown_invocations
    assert audit.sections_without_invocation == (), audit.sections_without_invocation
    assert audit.ok is True


# ------------------------------------------------------- 6. the pin no longer depends on POSITION

def test_b6_the_iteration_169_pin_accepts_the_live_readme():
    pin = _load_test_helper("test_iter169_behavior").index_numbers_pin_violations
    numbers = _readme_numbers(README.read_text(encoding="utf-8"))
    assert numbers[-1] != "50", "the README has grown past iteration 169's snapshot"
    assert pin(numbers) == (), pin(numbers)


def test_b6_the_position_assert_is_gone_from_that_module():
    src = (_ROOT / "tests" / "test_iter169_behavior.py").read_text(encoding="utf-8")
    forbidden = "numbers[" + "-2:]"          # built, not written, so this file cannot BE the hit
    assert forbidden not in src, "the position pin is still in test_iter169_behavior.py"
    for claim in ("are the last two", "must be last", "are last"):
        assert claim not in src.lower(), "stale prose still claims the sections are last: %r" % claim


# ------------------------------------------------------- 7. the rewritten pin is two-sided

GOOD = [str(n) for n in range(1, 52)]


def test_b7_the_pin_accepts_the_good_list():
    pin = _load_test_helper("test_iter169_behavior").index_numbers_pin_violations
    assert pin(GOOD) == (), pin(GOOD)
    assert pin(GOOD + ["52", "53"]) == (), "growth past the pinned pair must stay ACCEPTED"


@pytest.mark.parametrize("name,numbers,needle", [
    ("49 absent", [n for n in GOOD if n != "49"], "'49' missing"),
    ("50 absent", [n for n in GOOD if n != "50"], "'50' missing"),
    ("not adjacent", ["42", "49", "51", "50"], "does not immediately follow"),
    ("50 before 49", ["42", "50", "49"], "does not immediately follow"),
    ("duplicate", ["42", "42", "49", "50"], "duplicate"),
    ("not ascending", ["49", "50", "42"], "ascending"),
    ("42 absent", ["49", "50"], "'42' missing"),
    ("non-integer", ["42", "49", "50", "fifty-one"], "non-integer"),
])
def test_b7_the_pin_rejects_each_known_bad_sample(name, numbers, needle):
    pin = _load_test_helper("test_iter169_behavior").index_numbers_pin_violations
    out = pin(numbers)
    assert out, "%s must be REJECTED -- a fail-open pin is worse than none" % name
    assert any(needle in v for v in out), (name, needle, out)


# ------------------------------------------------------- 8. the 5th team's config is ignored

def test_b8_live_repo_ignores_the_fifth_config_via_the_nested_gitignore():
    proc = _git("check-ignore", "-v", FIFTH_CFG)
    assert proc.returncode == 0, "the 5th team's config must be IGNORED: %r" % proc.stdout
    source = proc.stdout.split(":", 1)[0]
    assert source == "products/.gitignore", \
        "the rule must ship in products/.gitignore, not a local exclude: %r" % proc.stdout
    # check-ignore answers from the RULES, so the verdict holds whether the file exists or not
    assert (_ROOT / FIFTH_CFG).exists() in (True, False)


def test_b8_hermetic_fixture_never_stages_the_fifth_config(tmp_path):
    repo = tmp_path / "fixture"
    (repo / "products").mkdir(parents=True)
    shutil.copyfile(_ROOT / ".gitignore", repo / ".gitignore")
    shutil.copyfile(PRODUCTS_IGNORE, repo / "products" / ".gitignore")
    teams = ["_platform", "repolens", "proactive-loop-agent",
             "resilient-agent-loop-primitives", "agent-gap-radar"]
    for team in teams:
        d = repo / "products" / team
        d.mkdir()
        (d / "config.json").write_text("{}\n", encoding="utf-8")
    assert _git("init", "-q", cwd=repo).returncode == 0

    status = _git("status", "--porcelain", cwd=repo)
    assert status.returncode == 0, status.stderr
    assert FIFTH_CFG not in status.stdout, status.stdout
    dry = _git("add", "-A", "--dry-run", cwd=repo)
    assert dry.returncode == 0, dry.stderr
    assert FIFTH_CFG not in dry.stdout, "add -A would sweep the 5th team's config: %s" % dry.stdout
    # two-sided: the fixture is not vacuous -- a sibling team's config IS visible to add -A
    assert "products/repolens/config.json" in dry.stdout, dry.stdout


# ------------------------------------------------------- 9. the two tracked configs stay SOURCE

def test_b9_tracked_configs_are_still_tracked_and_not_ignored():
    tracked = _git("ls-files", "products").stdout.split()
    for path in (PLATFORM_CFG, REPOLENS_CFG):
        assert path in tracked, "%s must stay TRACKED SOURCE" % path
        assert _git("check-ignore", "-q", path).returncode != 0, "%s must NOT be ignored" % path


def test_b9_the_new_rule_names_exactly_one_path_and_uses_no_wildcard():
    lines = [ln.strip() for ln in PRODUCTS_IGNORE.read_text(encoding="utf-8").splitlines()]
    rules = [ln for ln in lines if ln and not ln.startswith("#")]
    hits = [ln for ln in rules if "config.json" in ln]
    assert hits == ["agent-gap-radar/config.json"], \
        "exactly ONE literal config path, no wildcard over every team: %s" % hits
    assert not any("*" in ln and "config.json" in ln for ln in rules)
    assert any("clean" in ln for ln in lines if ln.startswith("#")), \
        "the entry must carry a comment saying WHY (add -A sweep, clean -fd deletion)"


# ------------------------------------------------------- 10. durable records in THIS commit

def test_b10_ledger_rows_exist_for_every_landed_iteration():
    text = ROADMAP.read_text(encoding="utf-8")
    for iteration in LANDED_ITERS:
        rows = [ln for ln in text.splitlines() if ln.startswith("- iter %d " % iteration)]
        assert len(rows) == 1, "expected exactly one ledger row for iter %d: %s" % (iteration, rows)
        assert len(rows[0]) <= 120, "row over the 120-char cap (%d): %r" % (len(rows[0]), rows[0])


def test_b10_archive_bullets_exist_for_every_landed_iteration():
    text = ARCHIVE.read_text(encoding="utf-8")
    for iteration in LANDED_ITERS:
        marker = "- **iter %d " % iteration
        assert text.count(marker) == 1, "expected one archive bullet for iter %d" % iteration


def test_b10_no_ledger_or_archive_gaps():
    index, archive = ROADMAP.read_text(encoding="utf-8"), ARCHIVE.read_text(encoding="utf-8")
    assert foundry.roadmap_archive_gaps(index, archive) == []
    assert foundry.roadmap_ledger_gaps(index, archive, LANDED_ITERS) == []


def test_b10_index_stays_inside_both_budgets():
    index = ROADMAP.read_text(encoding="utf-8")
    helper = _load_test_helper("test_iter167_behavior")
    allowance = helper.index_growth_allowance(index)
    bound = helper.ACCEPTED_INDEX_CHARS + allowance
    assert len(index) <= bound, "index %d chars over the derived bound %d (%d + %d allowed)" % (
        len(index), bound, helper.ACCEPTED_INDEX_CHARS, allowance)
    assert len(index) < foundry.ROADMAP_INDEX_HARD_CHARS


# ------------------------------------------------------- 11. dormancy + fresh-interpreter imports

@pytest.mark.parametrize("module", ["foundry", "dispatcher"])
def test_b11_module_imports_in_a_fresh_interpreter(module):
    proc = subprocess.run([sys.executable, "-c", "import " + module], cwd=str(_ROOT),
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-600:]


@pytest.mark.parametrize("func", CONTROL_PATH)
def test_b11_no_new_name_is_called_from_the_running_control_path(func):
    src = inspect.getsource(getattr(foundry, func))  # machine check, never read by me
    for name in NEW_NAMES:
        assert name not in src, "%s must stay dormant: referenced inside %s()" % (name, func)


def test_b11_dispatcher_never_references_the_new_names():
    text = (_ROOT / "dispatcher.py").read_text(encoding="utf-8")  # scanned as DATA, not read
    for name in NEW_NAMES:
        assert name not in text, "%s must not reach dispatcher.py -- no restart may be owed" % name
