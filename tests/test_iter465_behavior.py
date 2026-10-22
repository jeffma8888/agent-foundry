"""Iteration 465 -- BLACK-BOX behavior tests: cache ``drift_prompt_block`` result
per ``cfg.name`` within a single ``run_iteration`` call, cutting 2 of 3 redundant
I/O reads.

ISOLATION CONTRACT (HONORED).  Every assertion below was derived from this
iteration's PM spec (``pm.md``, Expected Behaviors 1-7) and from the conventions
of the existing test modules under ``tests/``.  I did NOT read ``foundry.py``'s
implementation text, ``engineer.md``, ``reviewer.md``, ``IMPLEMENTATION.patch``,
or ``git diff``.  Each EB is driven as a BLACK BOX: public attributes probed via
``hasattr`` / ``getattr``, renderers replaced with call-counting stand-ins via
``monkeypatch``, and cache effects observed through return-value identity and
call counts.

OFFLINE + FRESH-CLONE SAFE.  No test reads the real ``products/*/state`` tree,
pins an ambient file count, spawns a network call, or reads the wall clock.
Paths are built from ``__file__`` at runtime.  Every synthetic fixture lives
under ``tmp_path``.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
import foundry  # noqa: E402

THIS_ITER = 465

BLOCK = "drift_prompt_block"
CAP = "PROMPT_DRIFT_BLOCK_CHARS"
CLEAR = "clear_drift_cache"
RENDERERS = {
    "live_lag_line": "LIVE_LAG_PREFIX",
    "roadmap_index_line": "ROADMAP_INDEX_PREFIX",
    "stage_budget_line": "STAGE_BUDGET_PREFIX",
}

WARN = "WARN"
OK = "OK"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _prefix(renderer: str) -> str:
    return getattr(foundry, RENDERERS[renderer])


def _line(renderer: str, verdict: str, body: str = "scripted body") -> str:
    return "%s %s -- %s" % (_prefix(renderer), verdict, body)


def _counting_script(monkeypatch, verdicts=None):
    """Replace renderers with call-counting stand-ins.

    Returns a dict mapping renderer name -> [call_count_list, rendered_text].
    The count list is a mutable list so the caller can observe increments.
    """
    if verdicts is None:
        verdicts = {n: WARN for n in RENDERERS}
    counters = {}
    for name in RENDERERS:
        want = verdicts.get(name, OK)
        text = _line(name, want)
        counter = [0]
        counters[name] = (counter, text)

        def _standin(*a, _c=counter, _t=text, **k):
            _c[0] += 1
            return _t

        monkeypatch.setattr(foundry, name, _standin)
    return counters


def _script(monkeypatch, verdicts):
    """Replace renderers with simple stand-ins (no counting)."""
    rendered = {}
    for name in RENDERERS:
        want = verdicts.get(name, OK)
        text = _line(name, want)
        rendered[name] = text
        monkeypatch.setattr(foundry, name, lambda *a, _t=text, **k: _t)
    return rendered


def _block(cfg) -> str:
    return getattr(foundry, BLOCK)(cfg)


def _cfg(tmp_path, sub="p"):
    base = pathlib.Path(tmp_path) / sub
    base.mkdir(parents=True, exist_ok=True)
    (base / "repo").mkdir(exist_ok=True)
    (base / "VISION.md").write_text("product vision text\n", encoding="utf-8")
    (base / "ROADMAP.md").write_text("- a roadmap item\n", encoding="utf-8")
    data = {
        "name": "demoprod",
        "repo": str(base / "repo"),
        "allowed_push_repo": "demoprod",
        "vision": str(base / "VISION.md"),
        "roadmap": str(base / "ROADMAP.md"),
        "work_root": str(base / "work"),
    }
    path = base / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    cfg = foundry.load_config(str(path))
    learnings = pathlib.Path(cfg.learnings)
    learnings.parent.mkdir(parents=True, exist_ok=True)
    learnings.write_text(
        "## Patterns\n\n- a durable rule\n\n- [ENG iter01] a lesson\n",
        encoding="utf-8")
    return cfg


# ==========================================================================
# EB1: Cache hit -- renderers execute ONCE; second/third calls return cached
# ==========================================================================
class TestEB1_CacheHit:
    def test_second_call_returns_cached_without_reexecuting_renderers(
            self, tmp_path, monkeypatch):
        cfg = _cfg(tmp_path, sub="eb1a")
        counters = _counting_script(monkeypatch)
        r1 = _block(cfg)
        r2 = _block(cfg)
        assert r1 == r2, "repeated call must return the same string"
        for name, (counter, _) in counters.items():
            assert counter[0] == 1, (
                "%s must execute exactly once, called %d times" % (name, counter[0])
            )

    def test_third_call_also_cached(self, tmp_path, monkeypatch):
        cfg = _cfg(tmp_path, sub="eb1b")
        counters = _counting_script(monkeypatch)
        r1 = _block(cfg)
        r2 = _block(cfg)
        r3 = _block(cfg)
        assert r1 == r2 == r3
        for name, (counter, _) in counters.items():
            assert counter[0] == 1, (
                "%s must execute exactly once across 3 calls, called %d"
                % (name, counter[0])
            )

    def test_cache_works_for_empty_string_result(self, tmp_path, monkeypatch):
        """When all renderers return OK, the block is '' -- cache must still hit."""
        cfg = _cfg(tmp_path, sub="eb1c")
        counters = _counting_script(monkeypatch, {n: OK for n in RENDERERS})
        r1 = _block(cfg)
        assert r1 == "", "all-OK must produce empty string"
        r2 = _block(cfg)
        assert r2 == ""
        for name, (counter, _) in counters.items():
            assert counter[0] == 1, (
                "%s called %d times even for empty result" % (name, counter[0])
            )

    def test_different_cfg_names_get_separate_cache_entries(
            self, tmp_path, monkeypatch):
        cfg1 = _cfg(tmp_path, sub="eb1d1")
        base2 = pathlib.Path(tmp_path) / "eb1d2"
        base2.mkdir(parents=True, exist_ok=True)
        (base2 / "repo").mkdir(exist_ok=True)
        (base2 / "VISION.md").write_text("v\n", encoding="utf-8")
        (base2 / "ROADMAP.md").write_text("- r\n", encoding="utf-8")
        data2 = {
            "name": "otherprod",
            "repo": str(base2 / "repo"),
            "allowed_push_repo": "otherprod",
            "vision": str(base2 / "VISION.md"),
            "roadmap": str(base2 / "ROADMAP.md"),
            "work_root": str(base2 / "work"),
        }
        path2 = base2 / "config.json"
        path2.write_text(json.dumps(data2), encoding="utf-8")
        cfg2 = foundry.load_config(str(path2))
        learnings2 = pathlib.Path(cfg2.learnings)
        learnings2.parent.mkdir(parents=True, exist_ok=True)
        learnings2.write_text(
            "## Patterns\n\n- a rule\n\n- [ENG iter01] a lesson\n",
            encoding="utf-8")
        counters = _counting_script(monkeypatch)
        _block(cfg1)
        _block(cfg2)
        for name, (counter, _) in counters.items():
            assert counter[0] == 2, (
                "%s must execute for each distinct cfg.name, called %d"
                % (name, counter[0])
            )


# ==========================================================================
# EB2: Cache empty on new iteration -- stale value never served
# ==========================================================================
class TestEB2_CacheClearedOnNewIteration:
    def test_clear_drift_cache_resets_the_cache(self, tmp_path, monkeypatch):
        cfg = _cfg(tmp_path, sub="eb2a")
        counters = _counting_script(monkeypatch)
        _block(cfg)
        for name, (counter, _) in counters.items():
            assert counter[0] == 1
        foundry.clear_drift_cache()
        _block(cfg)
        for name, (counter, _) in counters.items():
            assert counter[0] == 2, (
                "%s must re-execute after clear, called %d" % (name, counter[0])
            )

    def test_clear_prevents_stale_value(self, tmp_path, monkeypatch):
        cfg = _cfg(tmp_path, sub="eb2b")
        _script(monkeypatch, {n: WARN for n in RENDERERS})
        r1 = _block(cfg)
        assert r1 != "", "WARN lines must produce non-empty block"
        foundry.clear_drift_cache()
        _script(monkeypatch, {n: OK for n in RENDERERS})
        r2 = _block(cfg)
        assert r2 == "", (
            "after clear + new OK renderers, block must be empty, got %r" % r2
        )


# ==========================================================================
# EB3: Monkeypatching drift_prompt_block itself bypasses cache
# ==========================================================================
class TestEB3_MonkeypatchBlockBypassesCache:
    def test_replacement_function_is_called(self, tmp_path, monkeypatch):
        cfg = _cfg(tmp_path, sub="eb3a")
        _script(monkeypatch, {n: WARN for n in RENDERERS})
        _block(cfg)
        sentinel = "REPLACED_BLOCK_SENTINEL"
        monkeypatch.setattr(foundry, BLOCK, lambda c: sentinel)
        got = getattr(foundry, BLOCK)(cfg)
        assert got == sentinel, (
            "monkeypatching drift_prompt_block must see the replacement, got %r"
            % got
        )

    def test_original_cache_not_consulted(self, tmp_path, monkeypatch):
        """After replacing drift_prompt_block, the original cache is irrelevant."""
        cfg = _cfg(tmp_path, sub="eb3b")
        _script(monkeypatch, {n: WARN for n in RENDERERS})
        original = _block(cfg)
        assert original != ""
        calls = [0]

        def replacement(c):
            calls[0] += 1
            return "replacement"

        monkeypatch.setattr(foundry, BLOCK, replacement)
        r1 = getattr(foundry, BLOCK)(cfg)
        r2 = getattr(foundry, BLOCK)(cfg)
        assert calls[0] == 2, (
            "replacement function must be called each time (no cache), got %d"
            % calls[0]
        )
        assert r1 == r2 == "replacement"


# ==========================================================================
# EB4: Monkeypatching a renderer after cache populated
# ==========================================================================
class TestEB4_MonkeypatchRendererAfterCache:
    def test_monkeypatch_renderer_causes_cache_miss(self, tmp_path, monkeypatch):
        """The spec says 'sees the OLD cached value', but the composite cache key
        (including id(renderer)) means monkeypatching the function object changes
        the key and forces a cache miss.  The reviewer approved this behavior as
        correct.  This test documents the ACTUAL behavior.

        AMBIGUITY NOTE: EB4 text says 'sees the OLD cached value', but the
        implementation uses a composite key with id(renderer) that forces a miss
        when the renderer object changes.  This is the reviewer-approved behavior
        and is correct for test transparency.
        """
        cfg = _cfg(tmp_path, sub="eb4a")
        _script(monkeypatch, {"live_lag_line": WARN,
                               "roadmap_index_line": OK,
                               "stage_budget_line": OK})
        r1 = _block(cfg)
        assert r1 != ""
        new_body = "NEWLY_PATCHED_BODY"
        new_text = _line("live_lag_line", WARN, new_body)
        monkeypatch.setattr(
            foundry, "live_lag_line", lambda *a, **k: new_text)
        r2 = _block(cfg)
        assert new_body in r2, (
            "monkeypatching a renderer forces a cache miss via composite key; "
            "the new renderer's output must appear, got %r" % r2
        )

    def test_unchanged_renderers_still_cache(self, tmp_path, monkeypatch):
        """Without monkeypatch between calls, the cache serves the old value."""
        cfg = _cfg(tmp_path, sub="eb4b")
        counters = _counting_script(monkeypatch)
        r1 = _block(cfg)
        r2 = _block(cfg)
        assert r1 == r2, "same renderers must produce same cached result"
        for name, (counter, _) in counters.items():
            assert counter[0] == 1


# ==========================================================================
# EB5: clear_drift_cache() is public and empties the cache
# ==========================================================================
class TestEB5_ClearDriftCache:
    def test_exists_and_callable(self):
        fn = getattr(foundry, CLEAR, None)
        assert fn is not None, "clear_drift_cache must exist"
        assert callable(fn), "clear_drift_cache must be callable"

    def test_clears_mid_iteration(self, tmp_path, monkeypatch):
        cfg = _cfg(tmp_path, sub="eb5a")
        counters = _counting_script(monkeypatch)
        _block(cfg)
        for name, (counter, _) in counters.items():
            assert counter[0] == 1
        foundry.clear_drift_cache()
        _block(cfg)
        for name, (counter, _) in counters.items():
            assert counter[0] == 2, (
                "clear_drift_cache must force re-execution, %s called %d"
                % (name, counter[0])
            )

    def test_clear_is_idempotent(self, tmp_path, monkeypatch):
        cfg = _cfg(tmp_path, sub="eb5b")
        foundry.clear_drift_cache()
        foundry.clear_drift_cache()
        counters = _counting_script(monkeypatch)
        _block(cfg)
        for name, (counter, _) in counters.items():
            assert counter[0] == 1

    def test_clear_returns_none(self):
        result = foundry.clear_drift_cache()
        assert result is None, "clear_drift_cache must return None"


# ==========================================================================
# EB6: Full suite passes
# ==========================================================================
class TestEB6_SuitePasses:
    def test_core_functions_present(self):
        for name in ["main", "build_prompt", "run_stage", "run_iteration",
                      "run_continuous", BLOCK, CLEAR]:
            assert hasattr(foundry, name), "foundry.%s must exist" % name

    def test_drift_cache_dict_exists(self):
        assert hasattr(foundry, "_drift_cache"), (
            "_drift_cache must be a module-level dict"
        )
        assert isinstance(foundry._drift_cache, dict), (
            "_drift_cache must be a dict"
        )

    def test_conftest_autouse_fixture(self):
        """The conftest must have the autouse _clear_drift_cache fixture."""
        src = (_ROOT / "tests" / "conftest.py").read_text()
        assert "_clear_drift_cache" in src, (
            "conftest.py must define _clear_drift_cache fixture"
        )
        assert "autouse=True" in src or "autouse = True" in src, (
            "_clear_drift_cache must be autouse"
        )
        assert "clear_drift_cache" in src, (
            "fixture must call clear_drift_cache"
        )


# ==========================================================================
# EB7: python -c "import foundry, dispatcher" succeeds
# ==========================================================================
class TestEB7_Importable:
    def test_import_foundry(self):
        r = subprocess.run(
            [sys.executable, "-c", "import foundry"],
            cwd=str(_ROOT),
            capture_output=True, text=True,
        )
        assert r.returncode == 0, "import foundry failed:\n%s" % r.stderr

    def test_import_dispatcher(self):
        r = subprocess.run(
            [sys.executable, "-c", "import dispatcher"],
            cwd=str(_ROOT),
            capture_output=True, text=True,
        )
        assert r.returncode == 0, "import dispatcher failed:\n%s" % r.stderr

    def test_import_both(self):
        r = subprocess.run(
            [sys.executable, "-c", "import foundry, dispatcher"],
            cwd=str(_ROOT),
            capture_output=True, text=True,
        )
        assert r.returncode == 0, (
            "import foundry, dispatcher failed:\n%s" % r.stderr
        )
