from __future__ import annotations

import io
import pathlib
import sys

import pytest


@pytest.fixture(autouse=True)
def _clear_drift_cache():
    """Reset the per-iteration drift prompt cache between tests."""
    import foundry
    foundry.clear_drift_cache()
    yield
    foundry.clear_drift_cache()


def _invoke_main(argv: list[str]) -> tuple[int, str]:
    """Invoke foundry.main(argv), capturing stdout+stderr as a single string."""
    import foundry

    out, err = io.StringIO(), io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = foundry.main(argv)
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return rc, out.getvalue() + err.getvalue()


_smoke_cache: dict[tuple[str, ...], tuple[int, str]] = {}


@pytest.fixture(scope="session")
def live_smoke_result():
    """Session-scoped cache for ``foundry.main(["<verb>", ...])`` invocations.

    Returns a callable ``get(verb, as_json=True)`` that lazily invokes the verb
    exactly once per ``(verb, as_json)`` pair and caches ``(exit_code,
    captured_output)``.  The ``foundry.config.json`` guard is checked once at
    first use; all subsequent calls reuse that decision.
    """
    import foundry

    froot = pathlib.Path(foundry.__file__).resolve().parent
    if not (froot / "foundry.config.json").exists():
        pytest.skip(
            "machine-local foundry.config.json absent at repo root (gitignored); "
            "live smoke needs the operator's real dispatch config"
        )

    def get(verb: str, *, as_json: bool = True) -> tuple[int, str]:
        argv = [verb, "--json"] if as_json else [verb]
        key = tuple(argv)
        if key not in _smoke_cache:
            _smoke_cache[key] = _invoke_main(argv)
        return _smoke_cache[key]

    return get
