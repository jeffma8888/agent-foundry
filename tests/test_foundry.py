"""Behaviour tests for the foundry framework itself.

These give the _platform self-improvement team a fast, deterministic feedback
loop (the whole point of the loop -- see ARCHITECTURE.md). No agent runs, no
network: pure config/prompt logic.
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import foundry  # noqa: E402
import dispatcher  # noqa: E402


def _write_cfg(tmp_path, **over):
    data = {
        "name": "demo",
        "repo": "{FOUNDRY}/products/demo/repo",
        "allowed_push_repo": "demo",
        "vision": "{FOUNDRY}/products/demo/VISION.md",
        "work_root": str(tmp_path / "work"),
    }
    data.update(over)
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data))
    return p


def test_config_resolves_foundry_token(tmp_path):
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))
    assert str(foundry.FOUNDRY) in cfg.repo
    assert "{FOUNDRY}" not in cfg.repo


def test_config_defaults(tmp_path):
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))
    # roles_dir defaults under the foundry root
    assert cfg.roles_dir == str(foundry.FOUNDRY / "roles")
    # learnings defaults under work_root
    assert cfg.learnings.endswith("LEARNINGS.md")
    assert cfg.branch == "main"
    assert cfg.push_enabled is True


def test_config_derived_paths(tmp_path):
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))
    assert cfg.state == pathlib.Path(cfg.work_root) / "state"
    assert cfg.night_log == pathlib.Path(cfg.work_root) / "NIGHT_LOG.md"
    assert cfg.stop_file == pathlib.Path(cfg.work_root) / "STOP"
    # load_config creates the work_root + state dir
    assert cfg.state.is_dir()


def test_unknown_keys_rejected(tmp_path):
    # iter 128 INVERTED this contract: an unknown key used to be dropped into the
    # field default, so `"push_enable": false` silently pushed. It now fails closed.
    with pytest.raises(foundry.ConfigKeyError) as exc:
        foundry.load_config(str(_write_cfg(tmp_path, bogus_key="x")))
    assert "bogus_key" in str(exc.value)


def test_build_prompt_contains_context_and_guardrails(tmp_path):
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))
    it_dir = cfg.state / "iter-07"
    out = it_dir / "pm.md"
    prompt = foundry.build_prompt(cfg, 7, "pm", "pm.md", out, it_dir, "extra!")
    assert "product 'demo'" in prompt
    assert cfg.repo in prompt
    assert str(pathlib.Path(cfg.roles_dir) / "pm.md") in prompt
    assert "anti" in foundry.ANTI_DELEGATION.lower() or "HARD RULES" in prompt
    assert "re-delegate" in prompt  # anti-delegation clause present
    assert "extra!" in prompt
    assert cfg.learnings in prompt


def test_next_iteration_counts_from_state(tmp_path):
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))
    assert foundry.next_iteration(cfg) == 1
    (cfg.state / "iter-03").mkdir(parents=True)
    (cfg.state / "iter-09").mkdir(parents=True)
    assert foundry.next_iteration(cfg) == 10


def test_stopping_respects_global_and_local(tmp_path, monkeypatch):
    cfg = foundry.load_config(str(_write_cfg(tmp_path)))
    # Isolate from LIVE operator state: global_stop() reads the real repo-root
    # STOP sentinel, which legitimately exists whenever an operator quiesces the
    # company (e.g. a maintenance window) -- and this suite runs on the live
    # machine (the final gate re-runs it). Pin the global to False for the
    # local-file assertions; the monkeypatched-True branch below still covers
    # the global path.
    monkeypatch.setattr(foundry, "global_stop", lambda: False)
    assert foundry.stopping(cfg) is False
    cfg.stop_file.write_text("stop")
    assert foundry.stopping(cfg) is True
    cfg.stop_file.unlink()
    assert foundry.stopping(cfg) is False
    monkeypatch.setattr(foundry, "global_stop", lambda: True)
    assert foundry.stopping(cfg) is True


def test_contains_helper(tmp_path):
    f = tmp_path / "r.md"
    f.write_text("RESULT: FAIL\n")
    assert foundry.contains(f, "RESULT: FAIL")
    assert not foundry.contains(f, "RESULT: PASS")
    assert not foundry.contains(tmp_path / "missing.md", "x")


def test_dispatcher_config_loads_and_sorts(tmp_path):
    conf = {
        "work_items": [
            {"name": "b", "config": "x", "priority": 10},
            {"name": "a", "config": "y", "priority": 0},
            {"name": "c", "config": "z", "enabled": False},
        ]
    }
    p = tmp_path / "d.json"
    p.write_text(json.dumps(conf))
    loaded = dispatcher.load_dispatch(str(p))
    items = [w for w in loaded["work_items"] if w.get("enabled", True)]
    items.sort(key=lambda w: w.get("priority", 100))
    assert [w["name"] for w in items] == ["a", "b"]  # c disabled, sorted by prio


def test_shipped_config_examples_are_valid_json():
    root = foundry.FOUNDRY
    for rel in ["foundry.config.example.json",
                "products/repolens/config.json",
                "products/_platform/config.json"]:
        json.loads((root / rel).read_text())
