#!/bin/sh
# install_hooks.sh -- arm the committed portable leak-guard as a git pre-push hook.
#
# WHY this exists (roadmap item 16, bite 2b of 3): agent-foundry is a PUBLIC repo
# whose autonomous dispatcher auto-pushes on every successful ship with no human in
# the review loop. iter 49/50 shipped a committed, portable, RUNNABLE scanner
# (scripts/leak_guard.py + a base64 scripts/leak_denylist.txt) -- but nothing ARMS
# it as a hook, and git does NOT clone hooks, so a fresh checkout / a new operator /
# CI / the post-release fresh-clone verify all run with ZERO leak protection. This
# one command closes that "hooks aren't cloned" gap: it installs a pre-push hook
# that runs the committed guard over every pushed commit tree, blocking a push whose
# tree carries a denylisted internal/personal token.
#
# Run ONCE from the repository top-level:   sh scripts/install_hooks.sh
# Idempotent (re-running is safe). A FOREIGN existing pre-push hook is preserved:
# it is copied to pre-push.backup exactly once before being replaced, and that first
# backup is never overwritten by a later run.
#
# STILL off the pipeline control path: this is a standalone script that nothing
# imports, and the armed hook invokes scripts/leak_guard.py unchanged. Wiring the
# guard into the in-loop final gate (belt-and-suspenders) is item 16 bite 3.
set -eu

# A fixed substring written into every hook we create. A re-run greps for it to tell
# OUR hook (overwrite in place, no backup) from a foreign operator-authored one
# (back up first). Also the marker Behavior 1/2/3 assert on.
MARKER="installed by agent-foundry"

# Resolve the repo root + hooks dir via git itself, so the installer works from any
# checkout layout AND fails LOUDLY (non-zero, STDERR, writes nothing) when it is run
# outside a git repository.
if ! root=$(git rev-parse --show-toplevel 2>/dev/null); then
    echo "install_hooks.sh: not inside a git repository; nothing to arm" >&2
    exit 1
fi
hooks_dir=$(git rev-parse --git-path hooks)
mkdir -p "$hooks_dir"
target="$hooks_dir/pre-push"
backup="$target.backup"

# Preserve a FOREIGN existing hook exactly once: back it up only if a pre-push hook
# already exists, it is NOT one of ours (lacks the marker), and no backup is there
# yet -- so a re-run never clobbers the first operator-authored hook, and re-running
# over our own marked hook leaves no spurious backup.
if [ -e "$target" ] && ! grep -q "$MARKER" "$target" 2>/dev/null && [ ! -e "$backup" ]; then
    cp "$target" "$backup"
    echo "install_hooks.sh: preserved existing pre-push hook at $backup" >&2
fi

# Write the armed hook. SINGLE-QUOTED heredoc delimiter ('HOOK') so $root /
# $local_sha are resolved at PUSH time inside the hook, never here at install time.
cat > "$target" <<'HOOK'
#!/bin/sh
# pre-push hook installed by agent-foundry (scripts/install_hooks.sh).
# Blocks any push whose commit tree carries a denylisted token, by running the
# committed portable leak-guard (scripts/leak_guard.py) over each pushed
# non-deletion local sha. A guard finding OR error blocks the push (fail CLOSED);
# it fails OPEN only if the guard script is entirely absent (an old checkout that
# predates the scanner must not be silently unpushable).
# stdin lines from git: <local ref> <local sha> <remote ref> <remote sha>
set -u
root=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
guard="$root/scripts/leak_guard.py"
[ -f "$guard" ] || exit 0
fail=0
while read -r local_ref local_sha remote_ref remote_sha; do
    # A branch deletion pushes an all-zeros local sha -- nothing to scan. Portable
    # test (a non-'0' char anywhere == a real commit); no hardcoded 40-zero sha, so
    # a SHA-256 repo works too.
    case "$local_sha" in
        "") continue ;;
        *[!0]*) : ;;
        *) continue ;;
    esac
    python3 "$guard" --ref "$local_sha" --repo "$root" || fail=1
done
exit $fail
HOOK

chmod +x "$target"
echo "install_hooks.sh: armed pre-push leak-guard hook at $target"
