#!/bin/bash
# Run by the mirror/extend toggle (Fn+F3 / SUPER+P in hyprland.lua) after the
# monitor layout has changed.

# Night mode's shader is built per-layout (it skips mirror outputs).
sh ~/.scripts/toggleHyprsunset.sh --refresh

# An extended screen should get its HyprPanel bar by itself (hyprland.lua makes
# sure apps know every screen). If one still has none after ~2s, the screen
# isn't known to apps (it was a mirror from the start): switch it off and on
# again so Hyprland announces it, and HyprPanel adds the bar. That blanks it
# for a second, so it's only the fallback.
bar_less() {
    local layers
    layers=$(hyprctl layers -j)
    for mon in $(hyprctl monitors all -j | jq -r '.[] | select(.mirrorOf == "none" and (.disabled | not)) | .name'); do
        # skip headless/virtual outputs (e.g. "tab")
        [[ $mon == HEADLESS* || $mon == tab ]] && continue
        jq -e --arg m "$mon" '[.[$m].levels[]?[]? | select(.namespace | startswith("bar-"))] | length > 0' \
            <<<"$layers" >/dev/null || echo "$mon"
    done
}

pgrep -f '^/usr/bin/bash /usr/share/hyprpanel/hyprpanel-app' >/dev/null || exit 0

for _ in 1 2 3 4; do
    [ -z "$(bar_less)" ] && exit 0
    sleep 0.5
done

for mon in $(bar_less); do
    hyprctl eval "hl.monitor({ output = \"$mon\", disabled = true })" >/dev/null
    sleep 0.4
    hyprctl eval "hl.monitor({ output = \"$mon\", mode = \"1920x1080@144\", position = \"auto-right\", scale = 1, mirror = \"\", disabled = false })" >/dev/null
done
