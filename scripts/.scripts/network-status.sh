#!/bin/bash
# Status for the bar's network button (JSON: alt, text, tooltip): Wayle's
# custom-network module, or HyprPanel's network modules.
#
# Both bars' built-in network modules show Wi-Fi whenever the primary
# connection isn't wired, which includes whenever a VPN is up. This reports the
# physical link actually carrying traffic instead, ignoring VPN/tun/bridges.
#
# Usage: network-status.sh [STATE]
#   With no argument, print the status. With STATE (wired, wifi-0..wifi-4, off),
#   print it only when that is the current state, else nothing. Each state has
#   its own HyprPanel module (hideOnEmpty), because a module's CSS class can't
#   change with its output and each state needs its own theme icon via CSS.
#   The result is cached for 2s so the modules share one lookup per poll.

cache="${XDG_RUNTIME_DIR:-/tmp}/network-status.json"

status() {
    declare -A kind
    local dev type state d metric best="" signal level ssid speed conn tip
    while IFS=: read -r dev type state; do
        if [[ $state == connected* && ( $type == ethernet || $type == wifi ) ]]; then
            kind[$dev]=$type
        fi
    done < <(nmcli -t -f DEVICE,TYPE,STATE device 2>/dev/null)

    # Of those, the one with the lowest-metric default route.
    dev=""
    while read -r d metric; do
        [[ -n ${kind[$d]} ]] || continue
        if [[ -z $best || $metric -lt $best ]]; then
            dev=$d
            best=$metric
        fi
    done < <({ ip -4 route show default; ip -6 route show default; } 2>/dev/null |
        awk '{ d = ""; m = 0; for (i = 1; i < NF; i++) { if ($i == "dev") d = $(i + 1); if ($i == "metric") m = $(i + 1) } if (d != "") print d, m }')

    # No default route on a physical link (e.g. mid-reconnect): prefer wired, then Wi-Fi.
    if [[ -z $dev ]]; then
        for d in "${!kind[@]}"; do [[ ${kind[$d]} == ethernet ]] && dev=$d && break; done
    fi
    if [[ -z $dev ]]; then
        for d in "${!kind[@]}"; do [[ ${kind[$d]} == wifi ]] && dev=$d && break; done
    fi

    if [[ -z $dev ]]; then
        jq -cn '{alt: "off", text: "Offline", tooltip: "No wired or Wi-Fi connection"}'
    elif [[ ${kind[$dev]} == ethernet ]]; then
        speed=$(cat "/sys/class/net/$dev/speed" 2>/dev/null)
        conn=$(nmcli -g GENERAL.CONNECTION device show "$dev" 2>/dev/null)
        tip="$conn ($dev)"
        [[ $speed =~ ^[0-9]+$ && $speed -gt 0 ]] && tip+=$'\n'"Speed: $speed Mb/s"
        jq -cn --arg tip "$tip" '{alt: "wired", text: "Wired", tooltip: $tip}'
    else
        ssid=$(nmcli -g GENERAL.CONNECTION device show "$dev" 2>/dev/null)
        signal=$(nmcli -t -f IN-USE,SIGNAL device wifi list ifname "$dev" --rescan no 2>/dev/null |
            awk -F: '$1 == "*" { print $2; exit }')
        signal=${signal:-0}
        level=$(( signal >= 80 ? 4 : signal >= 60 ? 3 : signal >= 40 ? 2 : signal >= 20 ? 1 : 0 ))
        jq -cn --arg ssid "$ssid" --arg alt "wifi-$level" \
            --arg tip "Network: $ssid"$'\n'"Signal Strength: $signal%" \
            '{alt: $alt, text: $ssid, tooltip: $tip}'
    fi
}

if [[ -s $cache && $(( $(date +%s) - $(stat -c %Y "$cache") )) -lt 2 ]]; then
    json=$(<"$cache")
else
    json=$(status)
    printf '%s\n' "$json" > "$cache.$$" && mv -f "$cache.$$" "$cache"
fi

if [[ -z $1 || $(jq -r .alt <<<"$json") == "$1" ]]; then
    printf '%s\n' "$json"
fi
