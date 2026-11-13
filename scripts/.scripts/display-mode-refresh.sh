#!/bin/bash
# Run by the mirror/extend toggle (Fn+F3 / SUPER+P in hyprland.lua) after the
# monitor layout has changed.

# Night mode's shader is built per-layout (it skips mirror outputs).
sh ~/.scripts/toggleHyprsunset.sh --refresh

# An extended screen should get its HyprPanel bar by itself (hyprland.lua makes
# sure apps know every screen). But a HyprPanel started while the screen was a
# mirror (e.g. restarted by theme-set) never puts a bar on it, while newly
# started apps do see it once it's extended. So if an extended screen still
# has no bar after ~2s, restart HyprPanel (the bars blink for a second).
bar_less() {
    local layers
    layers=$(hyprctl layers -j)
    for mon in $(hyprctl monitors all -j | jq -r '.[] | select(.mirrorOf == "none" and (.disabled | not)) | .name'); do
        # skip headless/virtual outputs (e.g. "tab")
        [[ $mon == HEADLESS* || $mon == tab ]] && continue
        # HyprPanel's bars are bar-0, bar-1…; bar-backdrop is ours, not a bar.
        jq -e --arg m "$mon" '[.[$m].levels[]?[]? | select(.namespace | test("^bar-[0-9]+$"))] | length > 0' \
            <<<"$layers" >/dev/null || echo "$mon"
    done
}

pgrep -f '^/usr/bin/bash /usr/share/hyprpanel/hyprpanel-app' >/dev/null || exit 0

for _ in 1 2 3 4; do
    [ -z "$(bar_less)" ] && exit 0
    sleep 0.5
done

~/.scripts/hyprpanel-quit  # (waits until it has quit)
hyprctl eval 'hl.dispatch(hl.dsp.exec_cmd("hyprpanel"))' >/dev/null
