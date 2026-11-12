#!/bin/bash
# Connect Proton VPN. Usage: vpn-proton-connect.sh [pt|fastest|<SERVER, e.g. ES#75>]  (default: pt)
# Records "<choice> <server>" in $XDG_RUNTIME_DIR/vpn-proton-choice so the
# HyprPanel dropdown (vpn-proton-menu.py) can highlight the option in use.
choice="${1:-pt}"
if pgrep -f protonvpn-app >/dev/null 2>&1; then
    pkill -f protonvpn-app
fi
case "$choice" in
    pt)      protonvpn connect --country PT ;;
    fastest) protonvpn connect ;;
    *)       protonvpn connect "$choice" ;;
esac
status=$?
server=$(nmcli -t -f NAME,TYPE connection show --active 2>/dev/null |
    awk -F: '$2 == "vpn" && $1 ~ /^ProtonVPN / { sub(/^ProtonVPN /, "", $1); print $1; exit }')
if [ -n "$server" ]; then
    printf '%s %s\n' "$choice" "$server" > "${XDG_RUNTIME_DIR:-/tmp}/vpn-proton-choice"
fi
exit $status
