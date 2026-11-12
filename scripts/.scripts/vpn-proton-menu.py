#!/usr/bin/env python3
"""Proton VPN dropdown for the HyprPanel VPN modules (bound to right click).

Styled after HyprPanel's own network menu. Opens centred under the cursor,
closes on Esc, on a click outside it, or when launched again (toggle).
"""
import json
import os
import signal
import subprocess
import sys

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell  # noqa: E402

CONNECT = os.path.expanduser("~/.scripts/vpn-proton-connect.sh")
DISCONNECT = os.path.expanduser("~/.scripts/vpn-proton-disconnect.sh")
PIDFILE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "vpn-proton-menu.pid")

WIDTH = 300
TOP = 50  # just below the bar, same as HyprPanel's dropdowns
BAR_HEIGHT = 48

# Accent colours, matching the VPN buttons in ~/.config/hyprpanel/modules.scss
GREEN = (0xA6, 0xE3, 0xA1)  # custom/vpn-proton (connected)
PINK = (0xF3, 0x8B, 0xA8)   # custom/vpn-off (disconnected)

# (connect-script argument, icon, title, subtitle)
SERVERS = [
    ("pt", "󰍎", "Portugal", "Fastest Lisbon server"),
    ("ES#75", "󰍎", "Spain · ES#75", "Madrid"),
    ("fastest", "󰓅", "Fastest", "Best server anywhere"),
]
# Written by vpn-proton-connect.sh as "<choice> <server>"
CHOICE_FILE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "vpn-proton-choice")

CSS = """
* { font-family: "Ubuntu Nerd Font"; font-weight: 600; font-size: 14px; }
window, .backdrop { background: transparent; }
.menu {
  background: #11111b; color: #cdd6f4;
  border: 2px solid #313244; border-radius: 0.7em;
  padding-bottom: 1em;
  box-shadow: 0 0 6px 1px rgba(0, 0, 0, 0.5);
  margin: 8px;
}
.label-container {
  background: #1e1e2e; border-radius: 0.4em 0.4em 0 0;
  margin: 1em 1em 0 1em; min-height: 2em;
}
.label-container.next { margin-top: 0.65em; }
.section-label { color: @ACCENT@; font-size: 15px; font-weight: bold; margin: 0.5em 1em; }
.section {
  background: #1e1e2e; border-radius: 0 0 0.4em 0.4em;
  padding: 0.9em; margin: 0 1em;
}
button { background: none; border: none; box-shadow: none; padding: 0; margin: 0; min-height: 0; min-width: 0; }
.item { padding: 0.3em 0; }
.item:not(:last-child) { margin-bottom: 0.4em; }
.icon { font-size: 19px; color: #9399b2; min-width: 1.4em; }
.item:hover .icon, .item.active .icon, .icon.active { color: @ACCENT@; }
.item:hover .title, .item.active .title { color: @ACCENT@; }
.title { color: #cdd6f4; }
.dim { color: #cdd6f4; opacity: 0.5; font-size: 12px; }
.icon-button { color: #cdd6f4; font-size: 21px; padding: 0 0.3em; }
.icon-button:hover { color: #f38ba8; }
"""


def toggle_existing():
    """If a menu is already open, close it and report True."""
    try:
        with open(PIDFILE) as f:
            pid = int(f.read().strip())
        os.kill(pid, signal.SIGTERM)
        return True
    except (OSError, ValueError):
        return False


def current_server():
    """Return e.g. 'PT#72' for an active Proton connection, '' otherwise."""
    try:
        out = subprocess.run(
            ["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show", "--active"],
            capture_output=True, text=True, timeout=3,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""
    for line in out.splitlines():
        name, _, kind = line.rpartition(":")
        if kind == "vpn" and name.startswith("ProtonVPN"):
            return name.removeprefix("ProtonVPN").strip()
    return ""


def active_choice(server):
    """Which SERVERS option the current connection came from, if any."""
    if not server:
        return None
    try:
        with open(CHOICE_FILE) as f:
            choice, chosen_server = f.read().split()
        if chosen_server == server:
            return choice
    except (OSError, ValueError):
        pass
    # Connected some other way (Proton app, CLI): match by server name.
    if server.startswith("PT#"):
        return "pt"
    if server == "ES#75":
        return "ES#75"
    return None


def cursor_position():
    """Cursor x relative to its monitor, the monitor's origin and logical width."""
    try:
        cx, cy = (int(v) for v in subprocess.run(
            ["hyprctl", "cursorpos"], capture_output=True, text=True, timeout=2,
        ).stdout.split(","))
        monitors = json.loads(subprocess.run(
            ["hyprctl", "monitors", "-j"], capture_output=True, text=True, timeout=2,
        ).stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    for m in monitors:
        w = round(m["width"] / m["scale"])
        h = round(m["height"] / m["scale"])
        if m["x"] <= cx < m["x"] + w and m["y"] <= cy < m["y"] + h:
            return cx, (m["x"], m["y"]), w
    return None


def module_center(cx, origin, mon_width, color):
    """Global x of the centre of the bar button under the cursor.

    HyprPanel doesn't expose widget positions, so grab the bar strip around the
    cursor and find the button's top border (drawn in its accent colour): the
    first matching pixel in the cursor's column, then the run of matching
    pixels along that row.
    """
    mx, my = origin
    x0 = max(mx, cx - 250)
    width = min(mx + mon_width, cx + 250) - x0
    try:
        ppm = subprocess.run(
            ["grim", "-s", "1", "-t", "ppm", "-g", f"{x0},{my} {width}x{BAR_HEIGHT}", "-"],
            capture_output=True, timeout=2,
        ).stdout
        _magic, size, _maxval, data = ppm.split(b"\n", 3)
        w, h = (int(v) for v in size.split())
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None

    def matches(x, y):
        i = (y * w + x) * 3
        return all(abs(a - b) <= 24 for a, b in zip(data[i:i + 3], color))

    col = cx - x0
    if not 0 <= col < w:
        return None
    row = next((y for y in range(h) if matches(col, y)), None)
    if row is None:
        return None
    left = right = col
    while left > 0 and matches(left - 1, row):
        left -= 1
    while right < w - 1 and matches(right + 1, row):
        right += 1
    if right - left < 20:
        return None
    return x0 + (left + right) / 2


def run_detached(label, *cmd):
    """Run a VPN script after the menu closes, with start/finish notifications."""
    # The CLI prints "Connected to …" / "Disconnected." on stdout but errors on
    # stderr, so keep both, then drop its Python deprecation noise.
    script = r'''
# The logo SVG is only 36x36, which HyprPanel stretches; use a 256px render.
svg=/usr/share/icons/hicolor/scalable/apps/proton-vpn-logo.svg
icon="${XDG_CACHE_HOME:-$HOME/.cache}/vpn-proton-menu/proton-vpn-logo-256.png"
if [ ! -s "$icon" ]; then
    mkdir -p "${icon%/*}"
    rsvg-convert -w 256 -h 256 "$svg" -o "$icon" 2>/dev/null || icon=$svg
fi
notify() { notify-send -a "Proton VPN" -i "$icon" "$@"; }
id=$(notify -p "Proton VPN" "$1…"); shift
out=$("$@" 2>&1); status=$?
# HyprPanel ignores replace-ids, so close the "…" notification explicitly.
gdbus call --session --dest org.freedesktop.Notifications \
    --object-path /org/freedesktop/Notifications \
    --method org.freedesktop.Notifications.CloseNotification "$id" >/dev/null 2>&1
msg=$(printf '%s\n' "$out" | grep -E '^(Connected to|Disconnected|Error)' | tail -1)
if [ -z "$msg" ]; then
    msg=$(printf '%s\n' "$out" | grep -viE 'warning|eventlet|framework|migration|monkey|sentry|^[[:space:]]*$' | tail -1)
fi
if [ "$status" -ne 0 ] || [[ "$msg" == Error* ]]; then
    notify -u critical "Proton VPN: failed" "${msg:-Command exited with status $status}"
else
    notify "Proton VPN" "${msg:-Done}"
fi
'''
    subprocess.Popen(
        ["bash", "-c", script, "vpn-menu", label, *cmd],
        start_new_session=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


class Menu(Gtk.Window):
    def __init__(self, server, accent):
        super().__init__()
        self.server = server

        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "vpn-proton-menu")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_exclusive_zone(self, -1)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                     GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, edge, True)

        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)

        # Transparent full-screen backdrop: a click on it closes the menu.
        backdrop = Gtk.EventBox()
        backdrop.get_style_context().add_class("backdrop")
        backdrop.connect("button-press-event", lambda *_: self.close_menu())
        self.add(backdrop)

        # The menu itself swallows clicks so they don't reach the backdrop.
        holder = Gtk.EventBox()
        holder.connect("button-press-event", lambda *_: True)
        holder.set_halign(Gtk.Align.START)
        holder.set_valign(Gtk.Align.START)
        backdrop.add(holder)

        menu = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        menu.get_style_context().add_class("menu")
        menu.set_size_request(WIDTH, -1)
        holder.add(menu)

        menu.add(self.status_section())
        menu.add(self.servers_section())

        pos = cursor_position()
        if pos:
            cx, origin, mon_width = pos
            self.place_on_monitor(origin)
            # Centre on the button itself; fall back to the cursor.
            x = (module_center(cx, origin, mon_width, accent) or cx) - origin[0]
            # WIDTH already includes the .menu margin that holds the shadow.
            total = WIDTH
            left = max(4, min(round(x - total / 2), mon_width - total - 4))
            holder.set_margin_start(left)
        holder.set_margin_top(TOP - 8)

        self.connect("key-press-event", self.on_key)
        self.connect("destroy", Gtk.main_quit)

    def place_on_monitor(self, origin):
        display = Gdk.Display.get_default()
        for i in range(display.get_n_monitors()):
            mon = display.get_monitor(i)
            g = mon.get_geometry()
            if (g.x, g.y) == origin:
                GtkLayerShell.set_monitor(self, mon)
                return

    def header(self, text, extra_class=None):
        box = Gtk.Box()
        ctx = box.get_style_context()
        ctx.add_class("label-container")
        if extra_class:
            ctx.add_class(extra_class)
        label = Gtk.Label(label=text, xalign=0)
        label.get_style_context().add_class("section-label")
        box.pack_start(label, True, True, 0)
        return box

    def status_section(self):
        wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        wrap.add(self.header("Proton VPN"))

        section = Gtk.Box(spacing=0)
        section.get_style_context().add_class("section")

        icon = Gtk.Label(label="󰌾" if self.server else "󰌿")
        icon.get_style_context().add_class("icon")
        if self.server:
            icon.get_style_context().add_class("active")
        section.pack_start(icon, False, False, 0)

        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        text.set_margin_start(10)
        title = Gtk.Label(label=self.server or "Not connected", xalign=0)
        title.get_style_context().add_class("title")
        sub = Gtk.Label(label="Connected" if self.server else "Disconnected", xalign=0)
        sub.get_style_context().add_class("dim")
        text.add(title)
        text.add(sub)
        section.pack_start(text, True, True, 0)

        if self.server:
            off = Gtk.Button(label="󰐥")
            off.set_tooltip_text("Disconnect")
            off.get_style_context().add_class("icon-button")
            off.set_valign(Gtk.Align.CENTER)
            off.connect("clicked", lambda *_: self.choose("Disconnecting", DISCONNECT))
            section.pack_end(off, False, False, 0)

        wrap.add(section)
        return wrap

    def servers_section(self):
        wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        wrap.add(self.header("Servers", "next"))

        section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        section.get_style_context().add_class("section")
        current = active_choice(self.server)
        for arg, glyph, name, subtitle in SERVERS:
            section.add(self.server_item(arg, glyph, name, subtitle, arg == current))
        wrap.add(section)
        return wrap

    def server_item(self, arg, glyph, name, subtitle, active):
        button = Gtk.Button()
        ctx = button.get_style_context()
        ctx.add_class("item")
        if active:
            ctx.add_class("active")

        row = Gtk.Box()
        icon = Gtk.Label(label=glyph)
        icon.get_style_context().add_class("icon")
        row.pack_start(icon, False, False, 0)

        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        text.set_margin_start(10)
        title = Gtk.Label(label=name, xalign=0)
        title.get_style_context().add_class("title")
        sub = Gtk.Label(label="Connected" if active else subtitle, xalign=0)
        sub.get_style_context().add_class("dim")
        text.add(title)
        text.add(sub)
        row.pack_start(text, True, True, 0)

        button.add(row)
        button.connect("clicked", lambda *_: self.choose(f"Connecting to {name}", CONNECT, arg))
        return button

    def choose(self, label, *cmd):
        run_detached(label, *cmd)
        self.close_menu()

    def on_key(self, _widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.close_menu()
        return False

    def close_menu(self):
        self.destroy()
        return True


def main():
    if toggle_existing():
        return
    with open(PIDFILE, "w") as f:
        f.write(str(os.getpid()))
    try:
        provider = Gtk.CssProvider()
        server = current_server()
        accent = GREEN if server else PINK
        provider.load_from_data(CSS.replace("@ACCENT@", "#%02x%02x%02x" % accent).encode())
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)
        try:
            gi.require_version("GLibUnix", "2.0")
            from gi.repository import GLibUnix
            add_signal = GLibUnix.signal_add
        except (ImportError, ValueError):
            add_signal = GLib.unix_signal_add
        add_signal(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: Gtk.main_quit() or False)
        win = Menu(server, accent)
        win.show_all()
        Gtk.main()
    finally:
        try:
            with open(PIDFILE) as f:
                if f.read().strip() == str(os.getpid()):
                    os.remove(PIDFILE)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
