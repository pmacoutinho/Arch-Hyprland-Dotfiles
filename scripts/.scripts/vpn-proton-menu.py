#!/usr/bin/env python3
"""Proton VPN dropdown for the HyprPanel VPN modules (bound to right click).

Styled after HyprPanel's own network menu. Opens centred under the cursor,
closes on Esc, on a click outside it, or when launched again (toggle).

Optionally also offers one OpenVPN 3 profile (e.g. a work VPN), configured in
a local, untracked file:
    ~/.config/vpn-proton-menu/custom-vpn.conf
        label=Work VPN
        config=~/path/to/profile.ovpn
Clicking it asks for a username and password inside the menu, like HyprPanel's
Wi-Fi password prompt; they go to ~/.scripts/openvpn3-connect.py on stdin.
Only the username is remembered.
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
OPENVPN3_CONNECT = os.path.expanduser("~/.scripts/openvpn3-connect.py")
CUSTOM_CONF = os.path.expanduser("~/.config/vpn-proton-menu/custom-vpn.conf")
CUSTOM_USER = os.path.join(
    os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")),
    "vpn-proton-menu", "custom-vpn-user")
DISCONNECT = os.path.expanduser("~/.scripts/vpn-proton-disconnect.sh")
PIDFILE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "vpn-proton-menu.pid")

WIDTH = 300
TOP = 50  # just below the bar, same as HyprPanel's dropdowns
BAR_HEIGHT = 48
POWER_ICON_SIZE = 16

# Accent colours, matching the VPN buttons in ~/.config/hyprpanel/modules.scss
GREEN = (0xA6, 0xE3, 0xA1)  # custom/vpn-proton (connected)
PINK = (0xF3, 0x8B, 0xA8)   # custom/vpn-off (disconnected)
LAVENDER = (0xB4, 0xBE, 0xFE)  # custom/vpn-it (custom OpenVPN 3 profile connected)

# (connect-script argument, icon, title, subtitle)
SERVERS = [
    ("pt", "󰍎", "Portugal", "Fastest Lisbon server"),
    ("ES#75", "󰍎", "Spain · ES#75", "Madrid"),
    ("fastest", "󰓅", "Fastest", "Best server anywhere"),
]
# Written by vpn-proton-connect.sh as "<choice> <server>"
CHOICE_FILE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "vpn-proton-choice")

CSS = """
/* Sizes match HyprPanel's network menu (measured): 13px text, 0.9em subtitles,
   14px section titles, 17px icons. */
* { font-family: "Ubuntu Nerd Font"; font-weight: 600; font-size: 13px; }
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
.section-label { color: @ACCENT@; font-size: 14px; font-weight: bold; margin: 0.5em 1em; }
.section {
  background: #1e1e2e; border-radius: 0 0 0.4em 0.4em;
  padding: 0.9em; margin: 0 1em;
}
button { background: none; border: none; box-shadow: none; padding: 0; margin: 0; min-height: 0; min-width: 0; }
.item { padding: 0.3em 0; }
.item:not(:last-child) { margin-bottom: 0.4em; }
.icon { font-size: 17px; color: #9399b2; min-width: 1.4em; }
.item:hover .icon, .item.active .icon, .icon.active { color: @ACCENT@; }
.item:hover .title, .item.active .title { color: @ACCENT@; }
.title { color: #cdd6f4; }
.dim { color: #cdd6f4; opacity: 0.5; font-size: 0.9em; }
.icon-button { color: #cdd6f4; padding: 0 0.3em; }
.icon-button:hover { color: #f38ba8; }
.login { margin-top: 0.6em; }
.field {
  background: #14141f; border-radius: 0.4em;
  padding: 0.45em 0.6em; margin: 0 0 0.45em 0;
}
.field entry { background: none; border: none; box-shadow: none; color: #cdd6f4; padding: 0; min-height: 0; caret-color: @ACCENT@; }
.field-icon { color: #9399b2; font-size: 14px; min-width: 1.4em; }
.connect {
  background: @ACCENT@; color: #11111b; border-radius: 0.4em;
  padding: 0.4em 0; margin-top: 0.15em;
}
.connect:hover { opacity: 0.85; }
.login-error { color: #f38ba8; font-size: 0.9em; margin-bottom: 0.4em; }
.eye { color: #9399b2; font-size: 15px; min-width: 1.4em; }
.eye.hover, .eye.on { color: @ACCENT@; }
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


def load_custom_vpn():
    """The optional extra OpenVPN 3 profile: {'label', 'config', 'name'} or None."""
    conf = {}
    try:
        with open(CUSTOM_CONF) as f:
            for line in f:
                key, sep, value = line.strip().partition("=")
                if sep and not key.startswith("#"):
                    conf[key.strip()] = value.strip()
    except OSError:
        return None
    if "config" not in conf:
        return None
    path = os.path.expanduser(conf["config"])
    # openvpn3 names sessions started from a file after the file.
    return {"label": conf.get("label", "Custom VPN"), "config": path,
            "name": os.path.basename(path)}


def custom_vpn_up(custom):
    if not custom:
        return False
    try:
        return subprocess.run(
            ["openvpn3", "session-stats", "--config", custom["name"]],
            capture_output=True, timeout=3,
        ).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def remembered_user():
    try:
        with open(CUSTOM_USER) as f:
            return f.read().strip()
    except OSError:
        return ""


def remember_user(user):
    try:
        os.makedirs(os.path.dirname(CUSTOM_USER), mode=0o700, exist_ok=True)
        fd = os.open(CUSTOM_USER, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(user + "\n")
    except OSError:
        pass


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


def run_detached(label, *cmd, app="Proton VPN", stdin=None):
    """Run a VPN script after the menu closes, with start/finish notifications.

    stdin (e.g. credentials) is piped to the command, never put on its command line.
    """
    # The CLI prints "Connected to …" / "Disconnected." on stdout but errors on
    # stderr, so keep both, then drop its Python deprecation noise.
    script = r'''
app=$1; shift
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
notify() { notify-send -a "$app" "${icon_args[@]}" "$@"; }
id=$(notify -p "$app" "$1…" </dev/null); shift
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
    notify -u critical "$app: failed" "${msg:-Command exited with status $status}"
else
    notify "$app" "${msg:-Done}"
fi
'''
    proc = subprocess.Popen(
        ["bash", "-c", script, "vpn-menu", app, label, *cmd],
        start_new_session=True,
        stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if stdin is not None:
        proc.stdin.write(stdin.encode())
        proc.stdin.close()


class Menu(Gtk.Window):
    def __init__(self, server, custom=None, custom_up=False, pos=None, center=None):
        super().__init__()
        self.server = server
        self.custom = custom
        self.custom_up = custom_up

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
        if self.custom:
            menu.add(self.custom_section())

        if pos:
            cx, origin, mon_width = pos
            self.place_on_monitor(origin)
            # Centre on the button itself; fall back to the cursor.
            x = (center if center is not None else cx) - origin[0]
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

    def power_button(self, on_click):
        """Disconnect button with the icon theme's power icon (tinted by CSS colour)."""
        image = Gtk.Image.new_from_icon_name("system-shutdown-symbolic", Gtk.IconSize.BUTTON)
        image.set_pixel_size(POWER_ICON_SIZE)
        button = Gtk.Button()
        button.add(image)
        button.set_tooltip_text("Disconnect")
        button.get_style_context().add_class("icon-button")
        button.set_valign(Gtk.Align.CENTER)
        button.connect("clicked", on_click)
        return button

    def status_section(self):
        wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        custom_on = self.custom_up and not self.server
        wrap.add(self.header(self.custom["label"] if custom_on else "Proton VPN"))
        connected = self.server or (self.custom["label"] if custom_on else "")

        section = Gtk.Box(spacing=0)
        section.get_style_context().add_class("section")

        icon = Gtk.Label(label="󰌾" if connected else "󰌿")
        icon.get_style_context().add_class("icon")
        if connected:
            icon.get_style_context().add_class("active")
        section.pack_start(icon, False, False, 0)

        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        text.set_margin_start(10)
        title = Gtk.Label(label=connected or "Not connected", xalign=0)
        title.get_style_context().add_class("title")
        sub = Gtk.Label(label="Connected" if connected else "Disconnected", xalign=0)
        sub.get_style_context().add_class("dim")
        text.add(title)
        text.add(sub)
        section.pack_start(text, True, True, 0)

        if connected:
            if self.server:
                off = self.power_button(lambda *_: self.choose("Disconnecting", DISCONNECT))
            else:
                off = self.power_button(lambda *_: self.disconnect_custom())
            section.pack_end(off, False, False, 0)

        wrap.add(section)
        return wrap

    def servers_section(self):
        wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        wrap.add(self.header("Proton VPN Servers", "next"))

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

    def custom_section(self):
        """The extra OpenVPN 3 profile, with an inline sign-in form."""
        wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        wrap.add(self.header("Other", "next"))

        section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        section.get_style_context().add_class("section")

        label = self.custom["label"]
        button = Gtk.Button()
        ctx = button.get_style_context()
        ctx.add_class("item")
        if self.custom_up:
            ctx.add_class("active")
        row = Gtk.Box()
        icon = Gtk.Label(label="󰖂")
        icon.get_style_context().add_class("icon")
        row.pack_start(icon, False, False, 0)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        text.set_margin_start(10)
        title = Gtk.Label(label=label, xalign=0)
        title.get_style_context().add_class("title")
        sub = Gtk.Label(label="Connected" if self.custom_up else "Sign in to connect", xalign=0)
        sub.get_style_context().add_class("dim")
        text.add(title)
        text.add(sub)
        row.pack_start(text, True, True, 0)
        button.add(row)
        section.add(button)

        # With Proton also up, the status card shows Proton, so put this
        # profile's disconnect button on its own row.
        if self.custom_up and self.server:
            row.pack_end(self.power_button(lambda *_: self.disconnect_custom()), False, False, 0)

        if not self.custom_up:
            self.login = Gtk.Revealer()
            self.login.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
            self.login.set_transition_duration(150)
            self.login.add(self.login_form())
            section.add(self.login)
            button.connect("clicked", lambda *_: self.toggle_login())

        wrap.add(section)
        return wrap

    def field(self, glyph, placeholder, secret=False):
        box = Gtk.Box()
        box.get_style_context().add_class("field")
        icon = Gtk.Label(label=glyph)
        icon.get_style_context().add_class("field-icon")
        box.pack_start(icon, False, False, 0)
        entry = Gtk.Entry()
        entry.set_placeholder_text(placeholder)
        entry.set_has_frame(False)
        if secret:
            entry.set_visibility(False)
            entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        box.pack_start(entry, True, True, 6)
        if secret:
            # Show/hide toggle, like HyprPanel's Wi-Fi password prompt. A plain
            # label in an event box: a GtkButton whose label changes under the
            # pointer ignores the next click until the mouse moves.
            eye = Gtk.Label(label="󰈈")
            eye.get_style_context().add_class("eye")
            area = Gtk.EventBox()
            area.set_tooltip_text("Show password")
            area.add(eye)
            area.connect("button-press-event", self.toggle_secret, eye, entry)
            area.connect("enter-notify-event", lambda *_: eye.get_style_context().add_class("hover"))
            area.connect("leave-notify-event", lambda *_: eye.get_style_context().remove_class("hover"))
            box.pack_end(area, False, False, 0)
        return box, entry

    def toggle_secret(self, area, event, eye, entry):
        if event.button != Gdk.BUTTON_PRIMARY or event.type != Gdk.EventType.BUTTON_PRESS:
            return True  # also swallows the extra events of a double click
        shown = not entry.get_visibility()
        entry.set_visibility(shown)
        eye.set_label("󰈉" if shown else "󰈈")
        area.set_tooltip_text("Hide password" if shown else "Show password")
        ctx = eye.get_style_context()
        (ctx.add_class if shown else ctx.remove_class)("on")
        entry.grab_focus_without_selecting()
        return True

    def login_form(self):
        form = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        form.get_style_context().add_class("login")
        self.login_error = Gtk.Label(xalign=0)
        self.login_error.get_style_context().add_class("login-error")
        self.login_error.set_no_show_all(True)
        form.add(self.login_error)

        user_box, self.user_entry = self.field("󰀄", "Username")
        self.user_entry.set_text(remembered_user())
        pass_box, self.pass_entry = self.field("󰌋", "Password", secret=True)
        form.add(user_box)
        form.add(pass_box)

        connect = Gtk.Button(label="Connect")
        connect.get_style_context().add_class("connect")
        connect.connect("clicked", lambda *_: self.submit_login())
        form.add(connect)

        self.user_entry.connect("activate", lambda *_: self.pass_entry.grab_focus())
        self.pass_entry.connect("activate", lambda *_: self.submit_login())
        return form

    def toggle_login(self):
        opening = not self.login.get_reveal_child()
        self.login.set_reveal_child(opening)
        if opening:
            (self.pass_entry if self.user_entry.get_text() else self.user_entry).grab_focus()

    def submit_login(self):
        user = self.user_entry.get_text().strip()
        password = self.pass_entry.get_text()
        if not user or not password:
            self.login_error.set_text("Enter your username and password")
            self.login_error.show()
            (self.pass_entry if user else self.user_entry).grab_focus()
            return
        remember_user(user)
        label = self.custom["label"]
        run_detached(f"Connecting to {label}", OPENVPN3_CONNECT, self.custom["config"], label,
                     app=label, stdin=f"{user}\n{password}\n")
        self.pass_entry.set_text("")
        self.close_menu()

    def disconnect_custom(self):
        label = self.custom["label"]
        run_detached(
            "Disconnecting", "bash", "-c",
            'openvpn3 session-manage -D --config "$1" >/dev/null && echo "Disconnected from $2."',
            "disconnect", self.custom["name"], label, app=label)
        self.close_menu()

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
        custom = load_custom_vpn()
        custom_up = custom_vpn_up(custom)
        # Both VPN buttons can be on the bar at once: use the colour of the one
        # that was clicked, found by its border colour under the cursor.
        candidates = [c for c, on in ((GREEN, bool(server)), (LAVENDER, custom_up)) if on] or [PINK]
        accent, center = candidates[0], None
        pos = cursor_position()
        if pos:
            cx, origin, mon_width = pos
            for colour in candidates:
                found = module_center(cx, origin, mon_width, colour)
                if found is not None:
                    accent, center = colour, found
                    break
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
        win = Menu(server, custom, custom_up, pos, center)
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
