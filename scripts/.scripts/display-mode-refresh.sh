#!/bin/bash
# Run by the mirror/extend toggle (Fn+F3 / SUPER+P in hyprland.lua) after the
# monitor layout has changed.

# Night mode's shader is built per-layout (it skips mirror outputs).
sh ~/.scripts/toggleHyprsunset.sh --refresh

# HyprPanel only creates bars for monitors it saw unmirrored while running.
# If it started while the external was mirrored (e.g. at login), an extended
# monitor never gets a bar, so restart it in that case. Give it ~2s first,
# since it does re-add bars for monitors it already knows.
missing_bar() {
    local layers
    layers=$(hyprctl layers -j)
    for mon in $(hyprctl monitors all -j | jq -r '.[] | select(.mirrorOf == "none" and (.disabled | not)) | .name'); do
        # skip headless/virtual outputs (e.g. "tab")
        [[ $mon == HEADLESS* || $mon == tab ]] && continue
        if ! jq -e --arg m "$mon" '[.[$m].levels[]?[]? | select(.namespace | startswith("bar-"))] | length > 0' <<<"$layers" >/dev/null; then
            return 0
        fi
    done
    return 1
}

pgrep -f hyprpanel-app >/dev/null || exit 0

for _ in 1 2 3 4; do
    missing_bar || exit 0
    sleep 0.5
done

hyprpanel -q
sleep 1
hyprctl eval 'hl.dispatch(hl.dsp.exec_cmd("hyprpanel"))' >/dev/null
