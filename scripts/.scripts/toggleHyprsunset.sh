#!/bin/bash

# Night mode toggle.
# hyprsunset can't reach mirrored outputs (they aren't exposed as wl_outputs),
# so the warm tint is done with a screen shader instead. Temperature is set in
# the template shader file.
TEMPLATE="$HOME/.config/hypr/shaders/warm.frag"
SHADER="$HOME/.cache/hypr/night-mode.frag"

set_shader() {
    hyprctl eval "hl.config({ decoration = { screen_shader = \"$1\" } })" > /dev/null
}

# Never stack with hyprsunset, or the laptop panel gets tinted twice
pkill -x "hyprsunset"

enable() {
    # Only tint non-mirror monitors; mirrors inherit the tinted frame
    cond=$(hyprctl monitors all -j | jq -r '[.[] | select(.mirrorOf == "none") | "wl_output == \(.id)"] | join(" || ")')
    mkdir -p "$(dirname "$SHADER")"
    sed "s/^#define TINT_OUTPUT .*/#define TINT_OUTPUT (${cond:-true})/" "$TEMPLATE" > "$SHADER"
    set_shader "$SHADER"
}

is_on() { hyprctl getoption decoration:screen_shader | grep -qF "$SHADER"; }

# --refresh: monitor layout changed (mirror <-> extend); rebuild the shader
# for the new layout if night mode is on, otherwise do nothing.
if [ "$1" = "--refresh" ]; then
    if is_on; then
        set_shader ""   # force a recompile; same path wouldn't reload
        enable
    fi
    exit 0
fi

if is_on; then
    echo "Night mode is on. Turning it off..."
    set_shader ""
else
    echo "Night mode is off. Turning it on..."
    enable
fi
