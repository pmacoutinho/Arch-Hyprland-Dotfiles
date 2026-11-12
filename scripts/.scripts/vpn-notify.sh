#!/bin/bash
# Run a VPN command with "…" and result notifications.
# Usage: vpn-notify.sh APP LABEL COMMAND [ARGS…]
#   APP    notification title, e.g. "Proton VPN" (which also gets the Proton logo)
#   LABEL  progress text, e.g. "Connecting to Portugal" (shown as "LABEL…")
# stdin is passed through to COMMAND (the VPN menu pipes credentials this way).
# Used by the HyprPanel VPN buttons and ~/.scripts/vpn-proton-menu.py.
# Each run's full output and exit status is appended to
# ~/.local/state/vpn-notify.log (last 400 lines kept) for troubleshooting.

app=$1
label=$2
shift 2

icon_args=()
if [ "$app" = "Proton VPN" ]; then
    # The logo SVG is only 36x36, which HyprPanel stretches; use a 256px render.
    svg=/usr/share/icons/hicolor/scalable/apps/proton-vpn-logo.svg
    icon="${XDG_CACHE_HOME:-$HOME/.cache}/vpn-proton-menu/proton-vpn-logo-256.png"
    if [ ! -s "$icon" ]; then
        mkdir -p "${icon%/*}"
        rsvg-convert -w 256 -h 256 "$svg" -o "$icon" 2>/dev/null || icon=$svg
    fi
    icon_args=(-i "$icon")
fi
notify() { notify-send -a "$app" "${icon_args[@]}" "$@" </dev/null; }

id=$(notify -p "$app" "$label…")
# The Proton CLI prints "Connected to …" / "Disconnected." on stdout but errors
# on stderr, so keep both.
out=$("$@" 2>&1)
status=$?
# HyprPanel ignores replace-ids, so close the "…" notification explicitly.
gdbus call --session --dest org.freedesktop.Notifications \
    --object-path /org/freedesktop/Notifications \
    --method org.freedesktop.Notifications.CloseNotification "$id" >/dev/null 2>&1

log="${XDG_STATE_HOME:-$HOME/.local/state}/vpn-notify.log"
mkdir -p "${log%/*}"
{
    printf '=== %s  %s: %s (exit %s)\n' "$(date '+%F %T')" "$app" "$label" "$status"
    printf '%s\n' "$out"
} >> "$log"
tail -n 400 "$log" > "$log.tmp" 2>/dev/null && mv -f "$log.tmp" "$log"

# A definite result line decides the outcome: e.g. `protonvpn disconnect` prints
# "Disconnected." and can then still exit non-zero from post-disconnect cleanup,
# though the disconnect itself worked.
msg=$(printf '%s\n' "$out" | grep -E '^(Connected to|Disconnected|Error)' | tail -1)
if [[ $msg == Error* ]]; then
    ok=false
elif [ -n "$msg" ]; then
    ok=true
else
    # No result line: go by the exit status, showing the last real line minus
    # the CLI's Python deprecation noise.
    msg=$(printf '%s\n' "$out" | grep -viE 'warning|eventlet|framework|migration|monkey|sentry|^[[:space:]]*$' | tail -1)
    [ "$status" -eq 0 ] && ok=true || ok=false
fi
if $ok; then
    notify "$app" "${msg:-Done}"
else
    notify -u critical "$app: failed" "${msg:-Command exited with status $status}"
fi
exit "$status"
