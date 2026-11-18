#!/bin/bash

# Night mode toggle.
# hyprsunset can't reach mirrored outputs (they aren't exposed as wl_outputs),
# so the warm tint is a screen shader instead, on every screen (mirrors too,
# see the shader). Temperature is set in the shader file.
SHADER="$HOME/.config/hypr/shaders/warm.frag"
# Whether it's on, for the dashboard's Night Mode tile (~/.scripts/night-mode-tile).
TILE_STATE="$HOME/.config/wayle/styles/_night-mode.scss"

set_shader() {
    hyprctl eval "hl.config({ decoration = { screen_shader = \"$1\" } })" > /dev/null
}

# Never stack with hyprsunset, or the laptop panel gets tinted twice
pkill -x "hyprsunset"

enable() { set_shader "$SHADER"; }

is_on() { hyprctl getoption decoration:screen_shader | grep -qF "$SHADER"; }

# Write the state for the tile, only when it changed (each write restyles Wayle).
sync_tile() {
    [ -d "${TILE_STATE%/*}" ] || return 0
    local on=false
    is_on && on=true
    grep -qxF "\$night-mode: $on;" "$TILE_STATE" 2>/dev/null && return 0
    printf '%s\n%s\n' \
        "// Written by ~/.scripts/toggleHyprsunset.sh: is night mode on? (index.scss)" \
        "\$night-mode: $on;" > "$TILE_STATE"
}

# --sync: just write the state (night-mode-tile: at login, after a reload).
if [ "$1" = "--sync" ]; then
    sync_tile
    exit 0
fi

if is_on; then
    echo "Night mode is on. Turning it off..."
    set_shader ""
else
    echo "Night mode is off. Turning it on..."
    enable
fi
sync_tile
