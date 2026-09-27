"""Iteration 420 -- BLACK-BOX behavior tests: ``foundry ledger-key``.

The product ships one pinned RECIPE for the final gate's `VERIFIED:` ledger key
(`ledger_key`: `<HEAD sha[:7]>+<sha256[:16]>` over the `git diff HEAD` text followed by the
sorted untracked set as `path\\0contents\\0`), the constant `LEDGER_KEY_CLEAN_HEX` (the
sha256 of empty input, the ONLY hex a provably clean tree can carry), a pure classifier
`classify_ledger_lines` (`current` / `voided` / `malformed` per `VERIFIED:` line) and a
read-only, fail-CLOSED 0/2 verb (`ledger-key --config CFG [--check FILE] [--json]`) over
exactly three bare-name `run_cmd` git reads.

Spec under test (products/_platform/state/iter-420/pm.md), Expected Behaviors 1-13:
   1. `ledger_key` pure/total; recipe pinned; untracked ORDER never changes the result.
   2. `""` (never raises) on any bad input: non-str/empty/non-hex/wrong-length head,
      non-str diff, any untracked member that is not a `(str, bytes)` pair.
   3. `LEDGER_KEY_CLEAN_HEX == "e3b0c44298fc1c14"`; clean key pinned; a non-empty diff OR a
      non-empty untracked set never yields the clean hex.
   4. `classify_ledger_lines(text, key)` -> `((line_no, status, token), ...)`, 1-based, in
      file order, `VERIFIED:` lines only; `()` for non-str inputs.
   5. Verb, human line: exactly ONE `ledger-key: <key> -- clean|dirty (diff N chars,
      M untracked)` line, exit 0; `clean` iff N == 0 and M == 0.
   6. Exactly THREE `run_cmd` reads by BARE name in the pinned order and argv; untracked
      bytes via `Path(cfg.repo, rel).read_bytes()`; zero real git.
   7. FAIL-CLOSED: any not-ok read, an invalid head, or a raising `read_bytes` -> ONE line
      `ledger-key: UNKNOWN -- <reason>` naming the step, exit 2, NO key, never `clean`.
   8. `--check FILE`: `  L<n>: <status>` per `VERIFIED:` line + `ledger-check: <c> current,
      <v> voided, <m> malformed`; ABSENT file -> `ledger-check: ABSENT -- <path>`; exit 0.
   9. `--json`: ONE `json.dumps(..., indent=2)` object with the nine pinned keys (plus
      `reason` on exit 2); return value identical to the human mode.
  10. `roles/final.md`: the ledger paragraph ENDS with the one verb sentence, no blank line
      inside, `final_ledger_claim_gaps(card) == ()`, last non-empty line unchanged.
  11. `role_card_verbs(card)` lists `ledger-key` alongside the three older verbs and
      `role_card_verb_gaps(card, foundry_cli_verbs(source)) == ()`.
  12. README `# 62.` directly after `# 61.` in the two-line shape; `# 61.` untouched;
      `readme_verb_index_gaps` clean both ways.
  13. DORMANT: the four new names are absent from the five control-path roots and from
      dispatcher.py; `import foundry, dispatcher` OK; the verb writes nothing.

ISOLATION CONTRACT (HONORED): written ONLY from the iteration-420 PM spec, the
conventions of `tests/` (the scripted-seam `_install` + `_cfg_file(tmp_path)` + `_capture`
idiom of `tests/test_iter415_behavior.py`, the control-path dormancy idiom of
`tests/test_iter209_behavior.py`), the README, and the product's OWN OBSERVABLE surface
(importing the module, calling public functions, driving `foundry.main`).  The
implementation TEXT of `foundry.py` was NOT read by the author; `roles/final.md`,
`README.md` and `foundry.py` text are passed to PUBLIC oracles or machine scans only.
`engineer.md`, `reviewer.md`, `fix_review.md` and `git diff` were NOT read.

Offline and deterministic: no real git subprocess anywhere (`run_cmd` is scripted by
BARE module name), no network, no clock; untracked fixtures live under `tmp_path`.  No
absolute machine path appears as a literal.  No assertion reads a gitignored path or
counts files in the ambient `tests/` or `products/` tree.

Ambiguity notes for the PM (tested the most reasonable reading):
  * Behavior 11 says `EXPECTED_VERBS` gains the token "in sorted position" and then types
    `("ledger-key", "leak-check", ...)`, which is NOT sorted (`lea` < `led`).  The rule word
    is the contract: this module pins the SORTED tuple `("leak-check", "ledger-key",
    "preship", "staged-check")`, which is what `role_card_verbs` observably returns.
  * Behavior 7 gives the reason strings as examples ("e.g."); the tests require the line
    to name the failing STEP (`rev-parse`, `diff`, `ls-files`, `read failed: <rel>`) rather
    than pin the whole sentence.  Unlike iter 415's spec, Behavior 7 does NOT list a
    RAISING `run_cmd` among the fail-closed cases (only `.ok is False`, a bad head, and a
    raising `read_bytes`), so that case is not asserted here -- PM feedback, not a defect.
"""

import hashlib
import inspect
import io
import json
import pathlib
import re
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import foundry  # noqa: E402
import dispatcher  # noqa: E402  -- in-process import-safety probe (Behavior 13)

THIS_ITER = 420
VERB = "ledger-key"
CLEAN_HEX = "e3b0c44298fc1c14"
NUL = "\x00"  # NEVER an inline `\0` before a digit -- that is an octal escape

HEAD40 = "0123456789abcdef0123456789abcdef01234567"
HEAD7 = HEAD40[:7]
OTHER40 = "fedcba9876543210fedcba9876543210fedcba98"

README = _ROOT / "README.md"
SOURCE = _ROOT / "foundry.py"
FINAL_CARD = _ROOT / "roles" / "final.md"

NEW_NAMES = ("ledger_key", "classify_ledger_lines", "ledger_key_cli", "LEDGER_KEY_CLEAN_HEX")
CONTROL_PATH_FNS = ("run_iteration", "run_continuous", "run_stage",
                    "build_prompt", "postrelease_step")

JSON_KEYS = {"product", "key", "head", "digest", "clean", "diff_chars", "untracked",
             "exit_code", "check"}

CARD_SENTENCE = (
    "Compute the key with `python3 <checkout>/foundry.py ledger-key --config PRODUCT_CONFIG` "
    "(never by hand; the same PRODUCT_CONFIG path as the other gate verbs), and on attempt 2 "
    "or later add `--check <your output file>` so each existing `VERIFIED:` line is reported "
    "current, voided or malformed before you decide what to carry forward."
)
CARD_LAST_LINE = "Append lessons to the foundry learnings log as `- [FINAL iterNN] ...`."
README_62_USAGE = ("uv run python foundry.py ledger-key --config products/<name>/config.json"
                   "  # [--check FILE] [--json]; exit 0 key printed / 2 UNKNOWN")
README_61_USAGE = ("uv run python foundry.py staged-check --config products/<name>/config.json"
                   "  # [--json ...; same 0/1/2 exit code]")


# --------------------------------------------------------------------------- helpers
def _recipe(head: str, diff: str, untracked) -> str:
    """The spec's Behavior-1 recipe, computed INDEPENDENTLY of the product."""
    h = hashlib.sha256()
    h.update(diff.encode("utf-8"))
    for path, blob in sorted(untracked):
        h.update(path.encode("utf-8") + b"\0" + blob + b"\0")
    return f"{head.strip()[:7]}+{h.hexdigest()[:16]}"


def _install(monkeypatch, *, head=HEAD40 + "\n", diff="", ls="", fail=(), raises=()):
    """Script `run_cmd` by BARE module name, answering by git sub-verb; record every call."""
    calls: list[tuple[list[str], dict]] = []
    answers = {"rev-parse": head, "diff": diff, "ls-files": ls}

    def fake_run_cmd(args, *rest, **kw):
        argv = [str(a) for a in args]
        calls.append((argv, dict(kw)))
        step = argv[3] if len(argv) > 3 else "?"
        if step in raises:
            raise RuntimeError(f"{step}-boom-xyz")
        return foundry.CmdResult(step not in fail, answers.get(step, ""))

    monkeypatch.setattr(foundry, "run_cmd", fake_run_cmd)
    return calls


def _cfg_file(tmp_path):
    """A minimal on-disk product config, as tests/test_iter415_behavior.py builds one."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "placeholder.txt").write_text("x\n", encoding="utf-8")
    conf = tmp_path / "config.json"
    conf.write_text(
        json.dumps({
            "name": "t",
            "repo": str(repo),
            "allowed_push_repo": "unit-test-repo",
            "work_root": str(tmp_path / "work"),
        }),
        encoding="utf-8",
    )
    return conf, repo


def _capture(fn):
    """Run fn() with stdout captured; return (rc, stdout)."""
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        rc = fn()
    finally:
        sys.stdout = old
    return rc, buf.getvalue()


def _swallow(fn):
    try:
        return fn()
    except SystemExit as exc:  # argparse --help exits 0
        return exc.code


def _listing(root: pathlib.Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


def _cli(conf, check=None, as_json=False):
    cfg = foundry.load_config(str(conf))
    return _capture(lambda: foundry.ledger_key_cli(cfg, check_path=check, as_json=as_json))


def _ledger_paragraph(card: str) -> tuple[int, int, list[str]]:
    """(start_idx, end_idx, lines) of the contiguous non-blank run holding the first VERIFIED:."""
    lines = card.splitlines()
    first = next(i for i, ln in enumerate(lines) if "VERIFIED:" in ln)
    start = first
    while start > 0 and lines[start - 1].strip():
        start -= 1
    end = first
    while end + 1 < len(lines) and lines[end + 1].strip():
        end += 1
    return start, end, lines[start:end + 1]


def _readme_section(text: str, heading_no: int) -> list[str]:
    """The `# NN.` section lines, up to (not including) the next `# NN.` heading."""
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if re.match(rf"^#\s*{heading_no}\.", ln):
            start = i
            break
    assert start is not None, f"README has no `# {heading_no}.` section"
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if not lines[j].strip() or re.match(r"^#", lines[j]):
            end = j
            break
    return lines[start:end]


FIXTURE_LINES = [
    "VERIFIED: a=b key={key}",
    "VERIFIED: c=d key=fa350ae+41caec744641eeb4",
    "VERIFIED: e=f key=c7a1232+f",
    "VERIFIED: g=h",
    "ACTION: PUSHED 10ad7f7",
]


def _fixture(key: str) -> str:
    return "\n".join(ln.format(key=key) for ln in FIXTURE_LINES) + "\n"


# =========================================================================== Behavior 1
def test_b1_recipe_matches_the_spec_for_a_clean_tree():
    assert foundry.ledger_key(HEAD40, "", []) == _recipe(HEAD40, "", [])
    assert foundry.ledger_key(HEAD40, "", []) == HEAD7 + "+" + CLEAN_HEX


def test_b1_recipe_matches_the_spec_with_diff_and_untracked():
    un = [("b.txt", b"beta"), ("a.txt", b"alpha\n")]
    got = foundry.ledger_key(HEAD40, "diff --git a/x b/x\n+1\n", un)
    assert got == _recipe(HEAD40, "diff --git a/x b/x\n+1\n", un)
    assert re.fullmatch(r"[0-9a-f]{7}\+[0-9a-f]{16}", got)


def test_b1_head_is_stripped_and_truncated_to_seven():
    assert foundry.ledger_key("  " + HEAD40 + "\n", "", []) == HEAD7 + "+" + CLEAN_HEX
    assert foundry.ledger_key("abcdef0", "", []) == "abcdef0+" + CLEAN_HEX  # 7-char head OK


def test_b1_untracked_order_never_changes_the_result():
    a, b, c = ("a.txt", b"1"), ("b.txt", b"2"), ("c/d.txt", b"\x00\xff")
    k1 = foundry.ledger_key(HEAD40, "d", [a, b, c])
    k2 = foundry.ledger_key(HEAD40, "d", [c, a, b])
    k3 = foundry.ledger_key(HEAD40, "d", (x for x in (b, c, a)))  # any iterable
    assert k1 == k2 == k3 == _recipe(HEAD40, "d", [a, b, c])


def test_b1_equal_inputs_equal_results_and_distinct_inputs_differ():
    assert foundry.ledger_key(HEAD40, "x", [("p", b"q")]) == foundry.ledger_key(HEAD40, "x", [("p", b"q")])
    assert foundry.ledger_key(HEAD40, "x", []) != foundry.ledger_key(HEAD40, "y", [])
    assert foundry.ledger_key(HEAD40, "", [("p", b"q")]) != foundry.ledger_key(HEAD40, "", [("p", b"r")])
    assert foundry.ledger_key(HEAD40, "", [("p", b"q")]) != foundry.ledger_key(HEAD40, "", [("r", b"q")])
    assert foundry.ledger_key(HEAD40, "", []).split("+")[0] != foundry.ledger_key(OTHER40, "", []).split("+")[0]


def test_b1_path_and_blob_boundaries_are_nul_separated_not_concatenated():
    # `ab` + `c` vs `a` + `bc` must NOT collide: the recipe frames path\0blob\0.
    assert foundry.ledger_key(HEAD40, "", [("ab", b"c")]) != foundry.ledger_key(HEAD40, "", [("a", b"bc")])


# =========================================================================== Behavior 2
@pytest.mark.parametrize("head", [None, 7, b"abcdef0", "", "   ", "abcdef", "ABCDEF0",
                                  "g" * 7, "a" * 41, "abc def0"])
def test_b2_bad_head_gives_empty_string(head):
    assert foundry.ledger_key(head, "", []) == ""


@pytest.mark.parametrize("diff", [None, 0, b"diff", ["diff"]])
def test_b2_non_str_diff_gives_empty_string(diff):
    assert foundry.ledger_key(HEAD40, diff, []) == ""


@pytest.mark.parametrize("untracked", [
    [("a.txt", "text-not-bytes")],
    [(b"a.txt", b"x")],
    [("a.txt",)],
    [("a.txt", b"x", b"y")],
    ["a.txt"],
    [None],
    [("ok.txt", b"x"), ("bad.txt", 3)],
])
def test_b2_bad_untracked_member_gives_empty_string(untracked):
    assert foundry.ledger_key(HEAD40, "", untracked) == ""


def test_b2_never_raises_on_garbage():
    for args in [(object(), object(), object()), (HEAD40, "", 5), (HEAD40, "", None)]:
        try:
            out = foundry.ledger_key(*args)
        except Exception as exc:  # pragma: no cover -- the assertion below reports it
            pytest.fail(f"ledger_key raised {exc!r} on {args!r}")
        assert out == ""


# =========================================================================== Behavior 3
def test_b3_clean_key_is_head7_plus_empty_sha256_prefix():
    assert foundry.LEDGER_KEY_CLEAN_HEX == CLEAN_HEX
    assert foundry.LEDGER_KEY_CLEAN_HEX == hashlib.sha256(b"").hexdigest()[:16]
    assert foundry.ledger_key("abcdef0", "", []) == "abcdef0+" + CLEAN_HEX


def test_b3_dirty_diff_or_untracked_never_yields_the_clean_hex():
    assert foundry.ledger_key(HEAD40, " ", []).split("+")[1] != CLEAN_HEX
    assert foundry.ledger_key(HEAD40, "", [("f", b"")]).split("+")[1] != CLEAN_HEX
    assert foundry.ledger_key(HEAD40, "", [("f", b"x")]).split("+")[1] != CLEAN_HEX


# =========================================================================== Behavior 4
def test_b4_classifier_table_of_the_spec_fixture():
    key = HEAD7 + "+" + CLEAN_HEX
    got = foundry.classify_ledger_lines(_fixture(key), key)
    assert got == (
        (1, "current", key),
        (2, "voided", "fa350ae+41caec744641eeb4"),
        (3, "malformed", "c7a1232+f"),
        (4, "malformed", ""),
    )
    assert isinstance(got, tuple) and all(isinstance(row, tuple) for row in got)


def test_b4_line_numbers_are_one_based_in_file_order_and_skip_non_verified():
    text = "# report\n\n  VERIFIED: x=y key=abcdef0+" + CLEAN_HEX + "\nprose key=zzz\nVERIFIED: z key=abcdef0+0123456789abcdef\n"
    got = foundry.classify_ledger_lines(text, "abcdef0+" + CLEAN_HEX)
    assert [row[0] for row in got] == [3, 5]
    assert got[0][1:] == ("current", "abcdef0+" + CLEAN_HEX)
    assert got[1][1:] == ("voided", "abcdef0+0123456789abcdef")


def test_b4_token_is_after_the_first_key_equals_up_to_whitespace():
    text = "VERIFIED: a key=first+00000000 key=second+11111111 trailing\n"
    got = foundry.classify_ledger_lines(text, "nope")
    assert got == ((1, "malformed", "first+00000000"),)  # `first` is not hex -> malformed
    text2 = "VERIFIED: a key=abcdef0+0123456789abcdef\ttab-after\n"
    assert foundry.classify_ledger_lines(text2, "x") == ((1, "voided", "abcdef0+0123456789abcdef"),)


@pytest.mark.parametrize("token,status", [
    ("abcdef0+0123456789abcdef", "voided"),          # 7 + 16
    ("a" * 40 + "+" + "b" * 64, "voided"),            # 40 + 64 (upper bounds)
    ("abcdef0+01234567", "voided"),                   # 8-hex lower bound
    ("abcdef0+0123456", "malformed"),                 # 7-hex hash too short
    ("abcdef+0123456789abcdef", "malformed"),         # 6-char sha too short
    ("a" * 41 + "+" + "b" * 16, "malformed"),         # 41-char sha too long
    ("ABCDEF0+0123456789abcdef", "malformed"),        # uppercase
    ("abcdef0-0123456789abcdef", "malformed"),        # wrong separator
    ("", "malformed"),
])
def test_b4_voided_versus_malformed_boundaries(token, status):
    line = "VERIFIED: c=d" + (f" key={token}" if token else "") + "\n"
    assert foundry.classify_ledger_lines(line, "zzzzzzz+" + CLEAN_HEX) == ((1, status, token),)


def test_b4_current_wins_even_when_the_key_itself_is_odd_shaped():
    # `current` is decided FIRST by equality, before the shape regex is consulted.
    assert foundry.classify_ledger_lines("VERIFIED: q key=odd", "odd") == ((1, "current", "odd"),)


@pytest.mark.parametrize("text,key", [(None, "k"), ("VERIFIED: a key=b", None), (5, 5), (b"VERIFIED:", "k")])
def test_b4_non_str_inputs_give_empty_tuple(text, key):
    assert foundry.classify_ledger_lines(text, key) == ()


def test_b4_no_verified_lines_gives_empty_tuple():
    assert foundry.classify_ledger_lines("ACTION: PUSHED abc\nprose\n", "k") == ()
    assert foundry.classify_ledger_lines("", "k") == ()


# =========================================================================== Behavior 5
def test_b5_clean_tree_prints_one_clean_line_and_returns_0(tmp_path, monkeypatch):
    conf, _ = _cfg_file(tmp_path)
    _install(monkeypatch)
    rc, out = _cli(conf)
    assert rc == 0
    assert out == f"ledger-key: {HEAD7}+{CLEAN_HEX} -- clean (diff 0 chars, 0 untracked)\n"


def test_b5_dirty_diff_only_prints_dirty_with_char_count(tmp_path, monkeypatch):
    conf, _ = _cfg_file(tmp_path)
    diff = "diff --git a/p b/p\n-1\n+2\n"
    _install(monkeypatch, diff=diff)
    rc, out = _cli(conf)
    assert rc == 0
    key = _recipe(HEAD40, diff, [])
    assert out == f"ledger-key: {key} -- dirty (diff {len(diff)} chars, 0 untracked)\n"
    assert key.split("+")[1] != CLEAN_HEX


def test_b5_dirty_untracked_only_prints_dirty_with_untracked_count(tmp_path, monkeypatch):
    conf, repo = _cfg_file(tmp_path)
    (repo / "new.txt").write_bytes(b"hello\n")
    _install(monkeypatch, ls="new.txt" + NUL)
    rc, out = _cli(conf)
    assert rc == 0
    key = _recipe(HEAD40, "", [("new.txt", b"hello\n")])
    assert out == f"ledger-key: {key} -- dirty (diff 0 chars, 1 untracked)\n"


def test_b5_human_output_is_exactly_one_line(tmp_path, monkeypatch):
    conf, _ = _cfg_file(tmp_path)
    _install(monkeypatch, diff="x")
    _, out = _cli(conf)
    assert out.count("\n") == 1 and out.endswith("\n")
    assert out.startswith("ledger-key: ")


# =========================================================================== Behavior 6
def test_b6_exactly_three_bare_name_run_cmd_reads_in_pinned_order(tmp_path, monkeypatch):
    conf, repo = _cfg_file(tmp_path)
    calls = _install(monkeypatch)
    cfg = foundry.load_config(str(conf))
    rc, _ = _capture(lambda: foundry.ledger_key_cli(cfg))
    assert rc == 0
    assert [c[0] for c in calls] == [
        ["git", "-C", str(cfg.repo), "rev-parse", "HEAD"],
        ["git", "-C", str(cfg.repo), "diff", "HEAD"],
        ["git", "-C", str(cfg.repo), "ls-files", "--others", "--exclude-standard", "-z"],
    ]


def test_b6_untracked_bytes_are_read_from_cfg_repo_and_hashed(tmp_path, monkeypatch):
    conf, repo = _cfg_file(tmp_path)
    (repo / "sub").mkdir()
    (repo / "sub" / "b.bin").write_bytes(b"\x00\x01\x02")
    (repo / "a.txt").write_bytes(b"A")
    # listing order deliberately NOT sorted: the recipe sorts.
    _install(monkeypatch, ls="sub/b.bin" + NUL + "a.txt" + NUL)
    rc, out = _cli(conf)
    assert rc == 0
    key = _recipe(HEAD40, "", [("a.txt", b"A"), ("sub/b.bin", b"\x00\x01\x02")])
    assert out == f"ledger-key: {key} -- dirty (diff 0 chars, 2 untracked)\n"


def test_b6_trailing_nul_does_not_count_as_an_untracked_path(tmp_path, monkeypatch):
    conf, repo = _cfg_file(tmp_path)
    (repo / "one.txt").write_bytes(b"1")
    _install(monkeypatch, ls="one.txt" + NUL)  # trailing NUL is git's terminator, not a path
    rc, out = _cli(conf)
    assert rc == 0
    assert "1 untracked)" in out


def test_b6_diff_char_count_is_len_of_the_diff_text(tmp_path, monkeypatch):
    conf, _ = _cfg_file(tmp_path)
    diff = "é" * 5 + "\n"  # 6 chars, 11 utf-8 bytes: N counts CHARS
    _install(monkeypatch, diff=diff)
    _, out = _cli(conf)
    assert "(diff 6 chars, 0 untracked)" in out


# =========================================================================== Behavior 7
@pytest.mark.parametrize("step", ["rev-parse", "diff", "ls-files"])
def test_b7_not_ok_read_is_unknown_exit_2_naming_the_step(tmp_path, monkeypatch, step):
    conf, _ = _cfg_file(tmp_path)
    _install(monkeypatch, fail=(step,))
    rc, out = _cli(conf)
    assert rc == 2
    assert out.count("\n") == 1
    assert out.startswith("ledger-key: UNKNOWN -- ")
    assert step in out
    assert HEAD7 not in out and CLEAN_HEX not in out and "clean" not in out


def test_b7_invalid_head_output_is_unknown_exit_2(tmp_path, monkeypatch):
    conf, _ = _cfg_file(tmp_path)
    _install(monkeypatch, head="fatal: not a git repository\n")
    rc, out = _cli(conf)
    assert rc == 2
    assert out.startswith("ledger-key: UNKNOWN -- ") and out.count("\n") == 1
    assert "+" not in out.split("--")[0] and "clean" not in out


def test_b7_missing_untracked_file_is_unknown_exit_2_naming_the_path(tmp_path, monkeypatch):
    conf, repo = _cfg_file(tmp_path)
    _install(monkeypatch, ls="ghost.txt" + NUL)  # listed but never written -> read_bytes raises
    rc, out = _cli(conf)
    assert rc == 2
    assert out.startswith("ledger-key: UNKNOWN -- ") and out.count("\n") == 1
    assert "read failed" in out and "ghost.txt" in out
    assert HEAD7 not in out and "clean" not in out


def test_b7_unknown_path_with_check_still_prints_no_key(tmp_path, monkeypatch):
    conf, _ = _cfg_file(tmp_path)
    report = tmp_path / "final.md"
    report.write_text(_fixture(HEAD7 + "+" + CLEAN_HEX), encoding="utf-8")
    _install(monkeypatch, fail=("ls-files",))
    rc, out = _cli(conf, check=str(report))
    assert rc == 2
    assert out.startswith("ledger-key: UNKNOWN -- ")
    assert "current" not in out.splitlines()[0]


# =========================================================================== Behavior 8
def test_b8_check_present_prints_block_and_summary_exit_0(tmp_path, monkeypatch):
    conf, _ = _cfg_file(tmp_path)
    key = HEAD7 + "+" + CLEAN_HEX
    report = tmp_path / "final.md"
    report.write_text(_fixture(key), encoding="utf-8")
    _install(monkeypatch)
    rc, out = _cli(conf, check=str(report))
    assert rc == 0
    assert out.splitlines() == [
        f"ledger-key: {key} -- clean (diff 0 chars, 0 untracked)",
        "  L1: current",
        "  L2: voided",
        "  L3: malformed",
        "  L4: malformed",
        "ledger-check: 1 current, 1 voided, 2 malformed",
    ]


def test_b8_check_against_a_dirty_tree_voids_the_stale_clean_key(tmp_path, monkeypatch):
    conf, repo = _cfg_file(tmp_path)
    report = tmp_path / "final.md"
    report.write_text(_fixture(HEAD7 + "+" + CLEAN_HEX), encoding="utf-8")
    (repo / "u.txt").write_bytes(b"u")
    _install(monkeypatch, ls="u.txt" + NUL)
    rc, out = _cli(conf, check=str(report))
    assert rc == 0
    lines = out.splitlines()
    assert lines[1] == "  L1: voided"  # the clean key no longer matches a dirty tree
    assert lines[-1] == "ledger-check: 0 current, 2 voided, 2 malformed"  # L1 well-formed but stale


def test_b8_check_absent_prints_one_absent_line_exit_0(tmp_path, monkeypatch):
    conf, _ = _cfg_file(tmp_path)
    missing = tmp_path / "no-such-final.md"
    _install(monkeypatch)
    rc, out = _cli(conf, check=str(missing))
    assert rc == 0
    assert out.splitlines() == [
        f"ledger-key: {HEAD7}+{CLEAN_HEX} -- clean (diff 0 chars, 0 untracked)",
        f"ledger-check: ABSENT -- {missing}",
    ]


def test_b8_check_with_no_verified_lines_gives_zero_counts(tmp_path, monkeypatch):
    conf, _ = _cfg_file(tmp_path)
    report = tmp_path / "final.md"
    report.write_text("# gate\nACTION: PUSHED abc\n", encoding="utf-8")
    _install(monkeypatch)
    rc, out = _cli(conf, check=str(report))
    assert rc == 0
    assert out.splitlines()[1:] == ["ledger-check: 0 current, 0 voided, 0 malformed"]


# =========================================================================== Behavior 9
def test_b9_json_clean_shape_and_mode_equivalence(tmp_path, monkeypatch):
    conf, _ = _cfg_file(tmp_path)
    _install(monkeypatch)
    rc_h, _ = _cli(conf)
    _install(monkeypatch)
    rc, out = _cli(conf, as_json=True)
    assert rc == rc_h == 0
    obj = json.loads(out)
    assert out == json.dumps(obj, indent=2) + "\n" or out == json.dumps(obj, indent=2)
    assert set(obj) >= JSON_KEYS
    assert obj["product"] == "t"
    assert obj["key"] == f"{HEAD7}+{CLEAN_HEX}"
    assert obj["head"] == HEAD7 and obj["digest"] == CLEAN_HEX
    assert obj["clean"] is True
    assert obj["diff_chars"] == 0 and obj["untracked"] == 0
    assert obj["exit_code"] == 0
    assert obj["check"] is None
    assert "ledger-key:" not in out


def test_b9_json_dirty_with_check_present(tmp_path, monkeypatch):
    conf, repo = _cfg_file(tmp_path)
    (repo / "n.txt").write_bytes(b"n")
    diff = "+x\n"
    key = _recipe(HEAD40, diff, [("n.txt", b"n")])
    report = tmp_path / "final.md"
    report.write_text(_fixture(key), encoding="utf-8")
    _install(monkeypatch, diff=diff, ls="n.txt" + NUL)
    rc, out = _cli(conf, check=str(report), as_json=True)
    assert rc == 0
    obj = json.loads(out)
    assert obj["key"] == key and obj["clean"] is False
    assert obj["diff_chars"] == 3 and obj["untracked"] == 1
    chk = obj["check"]
    assert chk["path"] == str(report) and chk["present"] is True
    assert chk["lines"] == [
        {"line": 1, "status": "current", "token": key},
        {"line": 2, "status": "voided", "token": "fa350ae+41caec744641eeb4"},
        {"line": 3, "status": "malformed", "token": "c7a1232+f"},
        {"line": 4, "status": "malformed", "token": ""},
    ]
    assert (chk["current"], chk["voided"], chk["malformed"]) == (1, 1, 2)


def test_b9_json_check_absent(tmp_path, monkeypatch):
    conf, _ = _cfg_file(tmp_path)
    missing = tmp_path / "gone.md"
    _install(monkeypatch)
    rc, out = _cli(conf, check=str(missing), as_json=True)
    assert rc == 0
    chk = json.loads(out)["check"]
    assert chk == {"path": str(missing), "present": False, "lines": [],
                   "current": 0, "voided": 0, "malformed": 0}


@pytest.mark.parametrize("step", ["rev-parse", "diff", "ls-files"])
def test_b9_json_exit_2_shape_and_reason(tmp_path, monkeypatch, step):
    conf, _ = _cfg_file(tmp_path)
    _install(monkeypatch, fail=(step,))
    rc_h, human = _cli(conf)
    _install(monkeypatch, fail=(step,))
    rc, out = _cli(conf, as_json=True)
    assert rc == rc_h == 2
    obj = json.loads(out)
    assert set(obj) >= JSON_KEYS | {"reason"}
    assert obj["key"] is None and obj["head"] is None and obj["digest"] is None
    assert obj["clean"] is False
    assert obj["diff_chars"] is None and obj["untracked"] is None
    assert obj["exit_code"] == 2
    assert isinstance(obj["reason"], str) and step in obj["reason"]
    assert human.strip() == f"ledger-key: UNKNOWN -- {obj['reason']}"
    assert "ledger-key:" not in out


def test_b9_json_exit_2_on_read_failure_carries_the_path_in_reason(tmp_path, monkeypatch):
    conf, _ = _cfg_file(tmp_path)
    _install(monkeypatch, ls="ghost.txt" + NUL)
    rc, out = _cli(conf, as_json=True)
    assert rc == 2
    obj = json.loads(out)
    assert "ghost.txt" in obj["reason"] and obj["key"] is None


# ================================================================ Behavior 5/6/13 -- CLI wiring
def test_cli_main_routes_the_verb_human_mode(tmp_path, monkeypatch):
    conf, _ = _cfg_file(tmp_path)
    _install(monkeypatch)
    rc, out = _capture(lambda: foundry.main([VERB, "--config", str(conf)]))
    assert rc == 0
    assert out == f"ledger-key: {HEAD7}+{CLEAN_HEX} -- clean (diff 0 chars, 0 untracked)\n"


def test_cli_main_routes_the_verb_json_with_check(tmp_path, monkeypatch):
    conf, _ = _cfg_file(tmp_path)
    report = tmp_path / "final.md"
    report.write_text(_fixture(HEAD7 + "+" + CLEAN_HEX), encoding="utf-8")
    _install(monkeypatch)
    rc, out = _capture(lambda: foundry.main([VERB, "--config", str(conf), "--check", str(report), "--json"]))
    assert rc == 0
    obj = json.loads(out)
    assert obj["check"]["current"] == 1 and obj["check"]["malformed"] == 2


def test_cli_main_unknown_exit_2(tmp_path, monkeypatch):
    conf, _ = _cfg_file(tmp_path)
    _install(monkeypatch, fail=("rev-parse",))
    rc, out = _capture(lambda: foundry.main([VERB, "--config", str(conf)]))
    assert rc == 2
    assert out.startswith("ledger-key: UNKNOWN -- ")


def test_cli_config_is_required():
    with pytest.raises(SystemExit) as top:
        _capture(lambda: foundry.main([VERB]))
    assert top.value.code != 0


def test_cli_help_lists_the_verb_and_its_flags():
    _, out = _capture(lambda: _swallow(lambda: foundry.main(["--help"])))
    assert VERB in out
    _, sub = _capture(lambda: _swallow(lambda: foundry.main([VERB, "--help"])))
    assert "--config" in sub and "--check" in sub and "--json" in sub


def test_cli_verb_census_lists_ledger_key():
    verbs = foundry.foundry_cli_verbs(SOURCE.read_text(encoding="utf-8"))
    assert VERB in verbs
    assert "staged-check" in verbs


def test_b13_verb_writes_nothing(tmp_path, monkeypatch):
    conf, repo = _cfg_file(tmp_path)
    (repo / "u.txt").write_bytes(b"u")
    report = tmp_path / "final.md"
    report.write_text(_fixture("x"), encoding="utf-8")
    _install(monkeypatch, diff="+1\n", ls="u.txt" + NUL)
    foundry.load_config(str(conf))  # the config loader owns work_root; snapshot AFTER it
    before_repo, before_all = _listing(repo), _listing(tmp_path)
    rc, _ = _capture(lambda: foundry.main([VERB, "--config", str(conf), "--check", str(report), "--json"]))
    assert rc == 0
    assert _listing(repo) == before_repo
    assert _listing(tmp_path) == before_all
    assert report.read_text(encoding="utf-8") == _fixture("x")


# =========================================================================== Behavior 10
def test_b10_ledger_paragraph_ends_with_the_verb_sentence_and_has_no_blank_inside():
    card = FINAL_CARD.read_text(encoding="utf-8")
    start, end, para = _ledger_paragraph(card)
    assert all(ln.strip() for ln in para), "blank line inside the ledger paragraph"
    joined = " ".join(ln.strip() for ln in para)
    assert joined.endswith(CARD_SENTENCE), joined[-300:]
    assert "reads as REVERTED." in joined
    assert joined.index("reads as REVERTED.") < joined.index("Compute the key with")
    assert joined.count("ledger-key") == 1
    # the sentence closes the paragraph: the next line is blank
    assert end + 1 < len(card.splitlines()) and not card.splitlines()[end + 1].strip()


def test_b10_final_ledger_claim_gaps_still_empty():
    card = FINAL_CARD.read_text(encoding="utf-8")
    assert foundry.final_ledger_claim_gaps(card) == ()


def test_b10_card_last_non_empty_line_is_byte_identical():
    lines = [ln for ln in FINAL_CARD.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert lines[-1] == CARD_LAST_LINE


def test_b10_verb_sentence_uses_the_card_invocation_shape():
    card = FINAL_CARD.read_text(encoding="utf-8")
    assert "python3 <checkout>/foundry.py ledger-key --config PRODUCT_CONFIG" in card
    assert "--check <your output file>" in card


# =========================================================================== Behavior 11
def test_b11_role_card_verbs_lists_the_four_gate_verbs_sorted():
    card = FINAL_CARD.read_text(encoding="utf-8")
    verbs = foundry.role_card_verbs(card)
    assert tuple(verbs) == ("leak-check", "ledger-key", "preship", "staged-check")
    assert tuple(verbs) == tuple(sorted(verbs))


def test_b11_role_card_verb_gaps_is_empty():
    card = FINAL_CARD.read_text(encoding="utf-8")
    cli = foundry.foundry_cli_verbs(SOURCE.read_text(encoding="utf-8"))
    assert foundry.role_card_verb_gaps(card, cli) == ()


# =========================================================================== Behavior 12
def test_b12_readme_62_directly_after_61_in_two_line_shape():
    text = README.read_text(encoding="utf-8")
    lines = text.splitlines()
    i61 = next(i for i, ln in enumerate(lines) if re.match(r"^#\s*61\.", ln))
    i62 = next(i for i, ln in enumerate(lines) if re.match(r"^#\s*62\.", ln))
    assert i62 > i61
    assert not any(re.match(r"^#\s*\d+\.", ln) for ln in lines[i61 + 1:i62]), "a heading sits between 61 and 62"
    sec62 = [ln for ln in _readme_section(text, 62) if ln.strip()]
    assert len(sec62) == 2, sec62
    head, usage = sec62
    assert "`ledger-key`" in head
    headline = head.split("(`ledger-key`)")[0][len("# 62."):].strip()
    assert headline and headline == headline.upper(), headline
    assert usage == README_62_USAGE


def test_b12_readme_61_section_unchanged_two_line_shape():
    sec61 = [ln for ln in _readme_section(README.read_text(encoding="utf-8"), 61) if ln.strip()]
    assert len(sec61) == 2
    assert sec61[0].startswith("# 61. ASK WHETHER THE INDEX HOLDS WHAT THE WORKTREE HOLDS (`staged-check`)")
    assert sec61[1] == README_61_USAGE


def test_b12_readme_has_exactly_one_62_and_no_63():
    text = README.read_text(encoding="utf-8")
    assert len(re.findall(r"^#\s*62\.", text, flags=re.M)) == 1
    assert not re.search(r"^#\s*63\.", text, flags=re.M)


def test_b12_readme_verb_index_two_way_clean():
    audit = foundry.readme_verb_index_gaps(README.read_text(encoding="utf-8"),
                                           foundry.foundry_cli_verbs(SOURCE.read_text(encoding="utf-8")))
    assert audit.ok is True
    assert audit.missing_verbs == () and audit.unknown_invocations == ()
    assert audit.sections_without_invocation == ()


# =========================================================================== Behavior 13
def test_b13_the_new_names_are_all_present_on_foundry():
    for name in NEW_NAMES:
        assert hasattr(foundry, name), name
    assert callable(foundry.ledger_key) and callable(foundry.classify_ledger_lines)
    assert callable(foundry.ledger_key_cli)


@pytest.mark.parametrize("fn", CONTROL_PATH_FNS)
def test_b13_control_path_never_mentions_the_new_names_in_source(fn):
    src = inspect.getsource(getattr(foundry, fn))
    for name in NEW_NAMES:
        assert name not in src, f"{fn} mentions {name} -- resume semantics touched"


@pytest.mark.parametrize("fn", CONTROL_PATH_FNS)
def test_b13_control_path_never_references_the_new_names_in_code(fn):
    names = set(getattr(foundry, fn).__code__.co_names)
    for name in NEW_NAMES:
        assert name not in names, f"{fn}.__code__ references {name}"


def test_b13_dispatcher_neither_exposes_nor_mentions_the_new_names():
    src = inspect.getsource(dispatcher)
    for name in NEW_NAMES:
        assert not hasattr(dispatcher, name), f"dispatcher exposes {name}"
        assert name not in src, f"dispatcher.py mentions {name}"
    assert VERB not in src
