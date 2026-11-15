#!/bin/bash
# Toggle the on-screen keyboard (SUPER+O). wvkbd, styled like GNOME's
# keyboard (rounded keys, Adwaita Sans) in the current desktop theme's colours:
# keys are the background mixed a little towards the text colour, pressed keys
# the accent. Read on each start, so it follows theme-set.

if pgrep -x wvkbd-mobintl >/dev/null; then
    pkill -x wvkbd-mobintl
    exit 0
fi

colors=~/.local/state/theme/current/colors.toml
read -r bg key special accent text < <(python3 - "$colors" <<'EOF' 2>/dev/null
import re, sys
c = dict(re.findall(r'^(\w+)\s*=\s*"#([0-9a-fA-F]{6})"', open(sys.argv[1]).read(), re.M))
bg, fg, accent = c["background"], c["foreground"], c.get("accent", c.get("color4"))

def mix(a, b, f):
    a = [int(a[i:i + 2], 16) for i in (0, 2, 4)]
    b = [int(b[i:i + 2], 16) for i in (0, 2, 4)]
    return "".join(f"{round(x + (y - x) * f):02x}" for x, y in zip(a, b))

print(bg, mix(bg, fg, 0.16), mix(bg, fg, 0.08), accent, fg)
EOF
)
# Fallback: GNOME's dark keyboard colours.
[ -n "$text" ] || read -r bg key special accent text <<<"222226 3a3a3e 2e2e32 3584e4 ffffff"

wvkbd-mobintl -L 220 -R 8 --fn "Adwaita Sans 16" \
    --bg "$bg" --fg "$key" --fg-sp "$special" \
    --press "$accent" --press-sp "$accent" --swipe "$accent" --swipe-sp "$accent" \
    --text "$text" --text-sp "$text" --text-press "$bg" --text-press-sp "$bg" \
    --text-swipe "$bg" --text-swipe-sp "$bg" &
