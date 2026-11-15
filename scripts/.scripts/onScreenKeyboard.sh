#!/bin/bash
# Toggle the on-screen keyboard (SUPER+O). wvkbd, styled like GNOME's
# keyboard (rounded keys, Adwaita Sans) in the current desktop theme's colours.
#
# Its background is transparent: bar-backdrop.py paints a blurred strip under
# it that continues the screen (kitty's translucent background, or the colour
# of the app filling the workspace) and follows workspace switches live, which
# wvkbd can't (its colours are fixed at start). The keys are the theme's text
# colour at low opacity, so they suit whatever is behind; pressed keys the
# accent. On the overlay layer, above that strip. theme-set reopens it.

if pgrep -x wvkbd-mobintl >/dev/null; then
    pkill -x wvkbd-mobintl
    exit 0
fi

colors=~/.local/state/theme/current/colors.toml
read -r bg accent text < <(python3 - "$colors" <<'EOF' 2>/dev/null
import re, sys
c = dict(re.findall(r'^(\w+)\s*=\s*"#([0-9a-fA-F]{6})"', open(sys.argv[1]).read(), re.M))
print(c["background"], c.get("accent", c.get("color4")), c["foreground"])
EOF
)
[ -n "$text" ] || read -r bg accent text <<<"222226 3584e4 ffffff"

wvkbd-mobintl -L 220 -R 8 --fn "Adwaita Sans 16" --wayland-layer overlay \
    --bg 00000000 --fg "${text}24" --fg-sp "${text}14" \
    --press "$accent" --press-sp "$accent" --swipe "$accent" --swipe-sp "$accent" \
    --text "$text" --text-sp "$text" --text-press "$bg" --text-press-sp "$bg" \
    --text-swipe "$bg" --text-swipe-sp "$bg" &
