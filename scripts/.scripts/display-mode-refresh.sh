#!/bin/bash
# Run by hyprland.lua after a mirror/extend switch (Fn+F3 / SUPER+P), when an
# external screen appears or goes away, and at login.
#  - A screen that just appeared is a normal screen at first, so apps get to
#    know it. In mirror mode, mirror it once its bar and wallpaper are on
#    it: a bar HyprPanel builds after that lands on the laptop panel
#    instead (two bars there), while one built before stays with the screen
#    and shows up instantly whenever it's extended.
#  - Extended: if the screen's bar isn't there right away, make HyprPanel
#    rebuild its bars at once (it isn't told about mirror <-> extend): add a
#    headless output for a moment (invisible; the panel's bar blinks).
#  - Once the monitors have settled: check every screen has a wallpaper and
#    one bar. No wallpaper means the screen was never announced to apps:
#    switch it off and on (reconnect_output in hyprland.lua; black for ~2s, so
#    only then). Bars wrong: rebuild them as above, else restart the bar.
# Bars: Wayle's wayle-bar-<screen> or HyprPanel's bar-0, bar-1… (whichever
# runs, see ~/.scripts/bar-switch). Wayle follows mirror <-> extend by itself;
# the HyprPanel-only nudge is skipped for it.
# A newer run (you switched again) makes this one stop, so it never acts on a
# layout you've already left.

RUN=${XDG_RUNTIME_DIR:-/tmp}
gen="$$.$(date +%s%N)"
echo "$gen" > "$RUN/display-mode-refresh.gen"
superseded() { [ "$(cat "$RUN/display-mode-refresh.gen" 2>/dev/null)" != "$gen" ]; }
mode=$(cat "$RUN/hypr-display-mode" 2>/dev/null)

layout() {
    cat "$RUN/hypr-display-mode" 2>/dev/null
    hyprctl monitors all -j | jq -c '[.[] | [.name, .mirrorOf, .disabled]]'
}

# Wait until the layout has stayed the same for 0.6s (at most ~6s).
settle() {
    local prev cur same=0
    prev=$(layout)
    for _ in $(seq 30); do
        sleep 0.2
        superseded && exit 0
        cur=$(layout)
        if [ "$cur" = "$prev" ]; then
            ((++same >= 3)) && return
        else
            same=0 prev=$cur
        fi
    done
}

# What's wrong, one per line: "wallpaper MON" (no hyprpaper layer) or
# "bar MON" (not exactly one bar-N layer; bar-backdrop is ours, not a bar).
# Only checked for the apps that are running; mirrors have no layers.
problems() {
    local bar=false wallpaper=false
    { pgrep -f '^/usr/bin/bash /usr/share/hyprpanel/hyprpanel-app' || pgrep -x wayle; } >/dev/null && bar=true
    pgrep -x hyprpaper >/dev/null && wallpaper=true
    hyprctl monitors all -j | jq -r --argjson layers "$(hyprctl layers -j)" \
        --argjson bar "$bar" --argjson wallpaper "$wallpaper" '
        .[] | select(.mirrorOf == "none" and (.disabled | not)) | .name
        | select(test("^(HEADLESS|tab$)") | not) as $m
        | [$layers[$m].levels[]?[]? | .namespace] as $ns
        | (if $wallpaper and ($ns | index("hyprpaper") | not) then "wallpaper \($m)" else empty end),
          (if $bar and ([$ns[] | select(test("^(bar-[0-9]+|wayle-bar-.+)$"))] | length) != 1 then "bar \($m)" else empty end)'
}

# External screens currently shown as normal screens.
extended() {
    hyprctl monitors all -j | jq -r '.[] | select(.mirrorOf == "none" and (.disabled | not)) | .name
        | select(test("^(eDP|HEADLESS|tab$)") | not)'
}

# Problems that last ~1.5s (HyprPanel takes a moment to add/move bars).
lasting() {
    local p
    for _ in $(seq 3); do
        p=$(problems)
        [ -z "$p" ] && return
        sleep 0.5
        superseded && exit 0
    done
    echo "$p"
}

# Repaint every screen in full once. After a screen is added or mirrored, the
# (software, NVIDIA) cursor could stay drawn where it was, a second "mouse"
# that only went away once something repainted that spot.
full_redraw() {
    hyprctl eval 'hl.config({ debug = { damage_tracking = 0 } })' >/dev/null
    sleep 0.1
    hyprctl eval 'hl.config({ debug = { damage_tracking = 2 } })' >/dev/null
}

# HyprPanel rebuilds all its bars ~0.3s after Hyprland reports a screen
# added/removed.
rebuild_bars() {
    [ "$(~/.scripts/bar-switch current)" = hyprpanel ] || return 0
    hyprctl output create headless HEADLESS-BARS >/dev/null
    sleep 0.2
    hyprctl output remove HEADLESS-BARS >/dev/null
}

if [ "$mode" != extend ] && [ -n "$(extended)" ]; then
    # Appeared as a normal screen: wait (≤5s) until bars and wallpapers are
    # all there and stay so for 0.6s, then mirror.
    ok=0
    for _ in $(seq 25); do
        sleep 0.2
        superseded && exit 0
        if [ -z "$(problems)" ]; then ((++ok >= 3)) && break; else ok=0; fi
    done
    hyprctl eval 'apply_mirrors()' >/dev/null
elif [ "$mode" = extend ]; then
    for _ in 1 2 3; do
        sleep 0.15
        superseded && exit 0
        p=$(problems)
        grep -q '^bar' <<<"$p" || break
    done
    # (A screen without wallpaper needs switching off/on, below.)
    grep -q '^bar' <<<"$p" && ! grep -q '^wallpaper' <<<"$p" && rebuild_bars
fi

settle
full_redraw

p=$(lasting)
[ -z "$p" ] && exit 0
trap full_redraw EXIT  # after the fixes below too
if [ "$mode" = extend ]; then
    for mon in $(awk '$1 == "wallpaper" && $2 !~ /^eDP/ {print $2}' <<<"$p"); do
        superseded && exit 0
        hyprctl eval "reconnect_output(\"$mon\")" >/dev/null
    done
    if grep -q '^wallpaper' <<<"$p"; then
        settle
        p=$(lasting)
    fi
fi
if grep -q '^bar' <<<"$p"; then
    superseded && exit 0
    rebuild_bars
    sleep 1
    p=$(lasting)
fi
if grep -q '^bar' <<<"$p"; then
    superseded && exit 0
    ~/.scripts/bar-switch restart
fi
