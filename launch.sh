#!/bin/bash
# Portable, DURABLE launch for the agent-foundry dispatcher (the "brain").
#
# WHY this file exists rather than just running the dispatcher in a terminal:
# on 2026-08-03 a healthy dispatcher died after 68 completed shifts with an
# uncaught OSError(5, "Input/output error"). It had inherited stdout from the
# shell that launched it; when that shell was reaped, the next log write hit a
# dead terminal and EIO propagated out of the main loop. The logger itself is now
# hardened to swallow that condition, but the durable fix is to never own a
# terminal at all. So this launcher:
#
#   * sends stdout AND stderr to a FILE and stdin to /dev/null, so no write can
#     ever reach a terminal that might disappear;
#   * detaches with a double fork plus a new session, reparenting the brain away
#     from the launching shell so it survives that shell being torn down (macOS
#     ships no setsid(1), which is why the detach is an inline Python program);
#   * REFUSES to start unless the shipped "foundry.py preflight" composite gate
#     reports GO. The composite folds `doctor` (power, agent CLI, uv, remote)
#     and `single-brain` into ONE three-way GO / NO-GO / CAUTION verdict, so a
#     launch on battery, with a missing agent CLI, or with a dead remote is
#     caught BEFORE detaching -- not silently after. Gating on the composite
#     rather than bare `single-brain` closes the gap where 3 of the 4 shipped
#     preflight checks were skipped on every launch.
#
# Every machine-specific value is read from the ENVIRONMENT, so this file is
# byte-identical in every clone and contains no absolute filesystem path:
#
#   FOUNDRY_AGENT_BIN   REQUIRED. Executable of your agent CLI. No default: a
#                       wrong guess here fails every stage, so we refuse instead.
#   FOUNDRY_AGENT_ARGS  JSON argv list for it, containing a "{prompt}"
#                       placeholder. Left alone when unset so foundry.py applies
#                       its own documented default (one definition, not two).
#   FOUNDRY_CONFIG      Dispatcher config path. Default: foundry.config.json.
#   FOUNDRY_LOG         Detached log file. Default: under TMPDIR, i.e. OUTSIDE
#                       the repo, so this runtime artifact can never be swept
#                       into a commit by "git add -A".
#
# Usage:  FOUNDRY_AGENT_BIN=... FOUNDRY_AGENT_ARGS=... ./launch.sh
# Stop:   touch STOP        (the dispatcher finishes its shift, then exits)
set -u

# Run from the repo root no matter where the caller invoked us from: every path
# below (foundry.py, dispatcher.py, the default config) is repo-relative.
cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1

FOUNDRY_CONFIG="${FOUNDRY_CONFIG:-foundry.config.json}"
FOUNDRY_LOG="${FOUNDRY_LOG:-${TMPDIR:-/tmp}/agent-foundry-dispatcher.out}"
export FOUNDRY_CONFIG FOUNDRY_LOG

# Fail BEFORE detaching on the one value we cannot invent. Detached failures are
# invisible until someone reads the log; this one is visible immediately.
if [ -z "${FOUNDRY_AGENT_BIN:-}" ]; then
    echo "REFUSING: FOUNDRY_AGENT_BIN is empty."
    echo "  export FOUNDRY_AGENT_BIN=/path/to/your/agent-cli (and normally"
    echo "  FOUNDRY_AGENT_ARGS, a JSON argv list with a {prompt} placeholder),"
    echo "  then re-run ./launch.sh"
    exit 1
fi
export FOUNDRY_AGENT_BIN
# Only export when the caller actually set it: exporting an EMPTY value would
# shadow foundry.py's own default and crash the JSON parse.
if [ -n "${FOUNDRY_AGENT_ARGS:-}" ]; then
    export FOUNDRY_AGENT_ARGS
fi

# The composite preflight gate. Fail-SHUT on every non-zero code: NO-GO is a
# hard blocker (env not ready or a confirmed second brain), and CAUTION means
# the scan could not rule out a competitor -- neither is a licence to launch.
python3 foundry.py preflight --config "$FOUNDRY_CONFIG"
preflight_status=$?
case "$preflight_status" in
    0)
        echo "preflight: GO -- environment ready, no dispatcher running; launching."
        ;;
    1)
        echo "REFUSING: preflight reports NO-GO -- a hard blocker was found"
        echo "  (environment not ready or a competing brain is confirmed)."
        echo "  Fix the issue listed above, then re-run ./launch.sh"
        exit 1
        ;;
    2)
        echo "REFUSING: preflight reports CAUTION -- the brain scan could not"
        echo "  rule out a competing dispatcher. Check by hand, then re-run."
        exit 1
        ;;
    *)
        echo "REFUSING: preflight returned unexpected exit $preflight_status."
        echo "  Check by hand, then re-run ./launch.sh"
        exit 1
        ;;
esac

python3 -c '
import os, sys

# Detach in two stages: the first child leaves the process group of the caller
# and opens a new session (no controlling terminal), the second is reparented to
# init, so the brain outlives the shell that launched it.
if os.fork():
    sys.exit()
os.setsid()
if os.fork():
    sys.exit()

# Own no terminal: both output streams go to one append-mode log, and stdin is
# an empty device, so a reaped terminal can never turn a log write into EIO.
log_fd = os.open(os.environ["FOUNDRY_LOG"],
                 os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
null_fd = os.open(os.devnull, os.O_RDONLY)
os.dup2(null_fd, 0)
os.dup2(log_fd, 1)
os.dup2(log_fd, 2)

os.execvp("uv", ["uv", "run", "python", "-X", "utf8", "dispatcher.py",
                 "--config", os.environ["FOUNDRY_CONFIG"]])
'

# Confirm with the SAME oracle that gated the launch: a brain we just started
# must now make the preflight report CONFLICT (exit 1). Anything else means the
# detached child died before it could take the dispatcher lock.
sleep 3
python3 foundry.py single-brain >/dev/null 2>&1
if [ $? -eq 1 ]; then
    echo "dispatcher launched (detached; logging to $FOUNDRY_LOG)"
    exit 0
fi
echo "LAUNCH FAILED -- single-brain sees no dispatcher. Tail of $FOUNDRY_LOG:"
tail -20 "$FOUNDRY_LOG" 2>/dev/null
exit 1
