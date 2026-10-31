#!/bin/sh
# Looks after a software update from Settings, for run.sh: it runs before any
# Python, because the app may be what's broken. backend/updater.py writes the
# .update-state file (it describes the phases); with no file this does nothing.
#
#   merging   the merge never finished (a power cut, say): back to the commit
#             it started from.
#   pending   the new version hasn't proved itself yet. Each start counts;
#             after MAX_STARTS without the dashboard removing the file, back
#             to the commit before it.
#
# Either way the file stays, with a new phase, for the dashboard to say what
# happened. Going back fails: the file stays too, and the next start tries
# again. It never stops the dashboard starting.
#
# Exits 75 when it changed the code, so run.sh starts over on what's there now.

MARKER=.update-state
MAX_STARTS=3

[ -f "$MARKER" ] || exit 0

field() {
    sed -n "s/^$1 //p" "$MARKER" | head -n 1
}

phase=$(field phase)
before=$(field before)
target=$(field target)
starts=$(field starts)

save() {
    printf 'phase %s\nbefore %s\ntarget %s\nstarts %s\n' "$1" "$before" "$target" "$2" \
        > "$MARKER.new" && mv "$MARKER.new" "$MARKER"
}

# A merge cut off by the power can leave its lock file, and a broken index.
# Nothing else is using the checkout this early.
go_back() {
    dir=$(git rev-parse --git-dir) || return 1
    rm -f "$dir/index.lock"
    git reset -q --hard "$before" || { rm -f "$dir/index"; git reset -q --hard "$before"; } || return 1
    sync
}

case "$phase" in
    merging|pending) ;;
    *) exit 0 ;;                        # the dashboard's to report
esac

if ! git cat-file -e "$before^{commit}" 2>/dev/null; then
    echo "update-guard: no commit '$before' to go back to; leaving the code alone" >&2
    rm -f "$MARKER"
    exit 0
fi

if [ "$phase" = pending ]; then
    case "$starts" in
        ''|*[!0-9]*) starts=0 ;;
    esac
    starts=$((starts + 1))
    if [ "$starts" -le "$MAX_STARTS" ]; then
        save pending "$starts"
        exit 0
    fi
    if [ "$(git rev-parse HEAD)" != "$target" ]; then
        echo "update-guard: HEAD was moved by hand; leaving it alone" >&2
        rm -f "$MARKER"
        exit 0
    fi
    echo "update-guard: ${target} didn't come up in $MAX_STARTS starts; back to ${before}" >&2
    go_back || { echo "update-guard: couldn't go back" >&2; exit 0; }
    save fell-back 0 || exit 0
else
    echo "update-guard: an update was cut off; back to ${before}" >&2
    go_back || { echo "update-guard: couldn't go back" >&2; exit 0; }
    # Files only the target has: the reset doesn't know them, and left there
    # they'd be "in the way" of the next try.
    git diff --name-only -z --no-renames --diff-filter=A "$before" "$target" 2>/dev/null | xargs -0 rm -f --
    save cut-off 0 || exit 0
fi
exit 75
