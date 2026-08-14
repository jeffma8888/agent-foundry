"""Session-wide pytest configuration for this repo's own suite.

WHY THIS FILE EXISTS: the suite runs on all cores (`-n auto` in
`pyproject.toml` `addopts`, iter 177), and 26 permanent every-suite freeze
guards shell out to `git diff --quiet HEAD -- <pathspec>`. `git diff` REFRESHES
the index before comparing and, by default, takes `.git/index.lock` to write
the refreshed index back. With N worker processes on one working tree those
writes contend for a single lock, so a guard can fail for a reason that has
nothing to do with the diff it was asked about -- a spurious red that would
revert a whole verified iteration.

`GIT_OPTIONAL_LOCKS=0` is git's own documented answer: it tells git to skip
operations that merely OPTIMISE (writing the refreshed index back) while leaving
the CONTENT comparison exactly as correct, so `git diff --quiet` still answers
the same question. Setting it here, once, covers all 26 existing guards AND
every future git-invoking test without editing a single one of them.

`setdefault`, not assignment: an operator debugging index behaviour can export
their own value and it survives. Set at IMPORT time, which pytest does before
collection in the controller and in every xdist worker process, so the variable
is in place before any test -- or any collection-time module body -- shells out
to git.
"""
from __future__ import annotations

import os

os.environ.setdefault("GIT_OPTIONAL_LOCKS", "0")
