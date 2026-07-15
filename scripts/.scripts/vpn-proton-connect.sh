#!/bin/bash
if pgrep -f protonvpn-app >/dev/null 2>&1; then
    pkill -f protonvpn-app
fi
protonvpn connect
