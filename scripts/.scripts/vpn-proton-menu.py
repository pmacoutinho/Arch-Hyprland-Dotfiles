#!/usr/bin/env python3
"""Proton VPN dropdown for the HyprPanel VPN modules (bound to right click).

Styled after HyprPanel's own network menu. Opens centred under the cursor,
closes on Esc, on a click outside it, or when launched again (toggle).

Runs in the background (`--daemon`, autostarted by hyprland.lua) with its
window ready, like HyprPanel's own dropdowns: launching the script just sends
it SIGUSR1, before even loading GTK, so the menu opens at once. If it isn't
running, the launch starts it and it opens the menu when ready.

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
import socket
import subprocess
import sys

DAEMON_PID = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "vpn-proton-menu-daemon.pid")

if __name__ == "__main__" and "--daemon" not in sys.argv:
    # Toggle the menu in the running daemon; start it if there's none.
    try:
        with open(DAEMON_PID) as f:
            os.kill(int(f.read().strip()), signal.SIGUSR1)
        sys.exit(0)
    except (OSError, ValueError):
        subprocess.Popen([sys.executable, os.path.abspath(__file__), "--daemon", "--show"],
                         start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        sys.exit(0)

import gi  # noqa: E402

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, Gio, GLib, Gtk, GtkLayerShell  # noqa: E402

CONNECT = os.path.expanduser("~/.scripts/vpn-proton-connect.sh")
OPENVPN3_CONNECT = os.path.expanduser("~/.scripts/openvpn3-connect.py")
NOTIFY = os.path.expanduser("~/.scripts/vpn-notify.sh")
CUSTOM_CONF = os.path.expanduser("~/.config/vpn-proton-menu/custom-vpn.conf")
CUSTOM_USER = os.path.join(
    os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")),
    "vpn-proton-menu", "custom-vpn-user")
DISCONNECT = os.path.expanduser("~/.scripts/vpn-proton-disconnect.sh")

WIDTH = 300
TOP = 50  # just below the bar, same as HyprPanel's dropdowns
BAR_HEIGHT = 48
POWER_ICON_SIZE = 16

# Accent colours, matching the VPN buttons in ~/.config/hyprpanel/modules.scss
# Colours follow the desktop theme: they're read from HyprPanel's config.json,
# where theme-set writes the theme's colours. The VPN accents are the colours
# modules.scss gives the VPN buttons. Defaults: Catppuccin Mocha (HyprPanel's).
HYPRPANEL_CONFIG = os.path.expanduser("~/.config/hyprpanel/config.json")
THEME_KEYS = {
    "BG": ("theme.bar.menus.background", "#11111b"),
    "CARD": ("theme.bar.menus.cards", "#1e1e2e"),
    "BORDER": ("theme.bar.menus.border.color", "#313244"),
    "TEXT": ("theme.bar.menus.text", "#cdd6f4"),
    "ICON": ("theme.bar.menus.menu.network.icons.passive", "#9399b2"),
    "RED": ("theme.bar.buttons.modules.cpu.text", "#f38ba8"),
    "VPN_ON": ("theme.bar.buttons.modules.netstat.text", "#a6e3a1"),
    "VPN_OFF": ("theme.bar.buttons.modules.cpu.text", "#f38ba8"),
    "VPN_IT": ("theme.bar.buttons.modules.weather.text", "#b4befe"),
}


def theme_colours():
    try:
        with open(HYPRPANEL_CONFIG) as f:
            config = json.load(f)
    except (OSError, ValueError):
        config = {}
    return {name: config.get(key, default) for name, (key, default) in THEME_KEYS.items()}


def rgb(colour):
    colour = colour.lstrip("#")
    return tuple(int(colour[i:i + 2], 16) for i in (0, 2, 4))

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
  background: @BG@; color: @TEXT@;
  border: 2px solid @BORDER@; border-radius: 0.7em;
  padding-bottom: 1em;
  box-shadow: 0 0 6px 1px rgba(0, 0, 0, 0.5);
  margin: 8px;
}
.label-container {
  background: @CARD@; border-radius: 0.4em 0.4em 0 0;
  margin: 1em 1em 0 1em; min-height: 2em;
}
.label-container.next { margin-top: 0.65em; }
.section-label { color: @ACCENT@; font-size: 14px; font-weight: bold; margin: 0.5em 1em; }
.section {
  background: @CARD@; border-radius: 0 0 0.4em 0.4em;
  padding: 0.9em; margin: 0 1em;
}
button { background: none; border: none; box-shadow: none; padding: 0; margin: 0; min-height: 0; min-width: 0; }
.item { padding: 0.3em 0; }
.item:not(:last-child), .row:not(:last-child) { margin-bottom: 0.4em; }
.icon { font-size: 17px; color: @ICON@; min-width: 1.4em; }
.item:hover .icon, .item.active .icon, .icon.active { color: @ACCENT@; }
.item:hover .title, .item.active .title { color: @ACCENT@; }
.title { color: @TEXT@; }
.dim { color: @TEXT@; opacity: 0.5; font-size: 0.9em; }
.icon-button { color: @TEXT@; padding: 0 0.3em; }
.icon-button:hover { color: @RED@; }
.login { margin-top: 0.6em; }
.field {
  background: @BG@; border-radius: 0.4em;
  padding: 0.45em 0.6em; margin: 0 0 0.45em 0;
}
.field entry { background: none; border: none; box-shadow: none; color: @TEXT@; padding: 0; min-height: 0; caret-color: @ACCENT@; }
.field-icon { color: @ICON@; font-size: 14px; min-width: 1.4em; }
.connect {
  background: @ACCENT@; color: @BG@; border-radius: 0.4em;
  padding: 0.4em 0; margin-top: 0.15em;
}
.connect:hover { opacity: 0.85; }
.login-error { color: @RED@; font-size: 0.9em; margin-bottom: 0.4em; }
.eye { color: @ICON@; font-size: 15px; min-width: 1.4em; }
.eye.hover, .eye.on { color: @ACCENT@; }
"""


def current_server():
    """Return e.g. 'PT#72' for an active Proton connection, '' otherwise.
    (Asks NetworkManager over D-Bus: a few ms, nmcli ~25ms.)"""
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM)

        def prop(path, iface, name):
            return bus.call_sync(
                "org.freedesktop.NetworkManager", path, "org.freedesktop.DBus.Properties", "Get",
                GLib.Variant("(ss)", (iface, name)), GLib.VariantType("(v)"),
                Gio.DBusCallFlags.NONE, 2000, None).unpack()[0]

        for path in prop("/org/freedesktop/NetworkManager",
                         "org.freedesktop.NetworkManager", "ActiveConnections"):
            iface = "org.freedesktop.NetworkManager.Connection.Active"
            name = prop(path, iface, "Id")
            if prop(path, iface, "Type") == "vpn" and name.startswith("ProtonVPN"):
                return name.removeprefix("ProtonVPN").strip()
    except GLib.Error:
        pass
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


def custom_vpn_state(custom):
    """The extra profile's session: 'connected', 'reconnecting' (e.g. after a
    suspend, while it retries) or None.

    Asks OpenVPN 3's session manager over D-Bus: `openvpn3 sessions-list`
    takes ~1.5s, which delayed the menu (and placed it wrong if the mouse
    moved meanwhile)."""
    if not custom:
        return None
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM)

        def call(path, iface, method, args, reply):
            return bus.call_sync("net.openvpn.v3.sessions", path, iface, method, args,
                                 GLib.VariantType(reply), Gio.DBusCallFlags.NONE, 2000, None).unpack()

        def prop(path, name):
            return call(path, "org.freedesktop.DBus.Properties", "Get",
                        GLib.Variant("(ss)", ("net.openvpn.v3.sessions", name)), "(v)")[0]

        for path in call("/net/openvpn/v3/sessions", "net.openvpn.v3.sessions",
                         "FetchAvailableSessions", None, "(ao)")[0]:
            if prop(path, "config_name") == custom["name"]:
                major, minor, _ = prop(path, "status")
                # StatusMajor CONNECTION (2), StatusMinor CONN_CONNECTED (7)
                return "connected" if (major, minor) == (2, 7) else "reconnecting"
    except GLib.Error:
        pass
    return None


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


def hyprctl(request):
    """Ask Hyprland directly over its socket (~1ms; the hyprctl CLI ~5ms)."""
    path = os.path.join(os.environ["XDG_RUNTIME_DIR"], "hypr",
                        os.environ["HYPRLAND_INSTANCE_SIGNATURE"], ".socket.sock")
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(2)
        sock.connect(path)
        sock.sendall(request.encode())
        data = b""
        while chunk := sock.recv(65536):
            data += chunk
    return data.decode()


def cursor_position():
    """Cursor x relative to its monitor, the monitor's origin and logical width."""
    try:
        cursor = json.loads(hyprctl("j/cursorpos"))
        cx, cy = cursor["x"], cursor["y"]
        monitors = json.loads(hyprctl("j/monitors"))
    except (OSError, KeyError, ValueError):
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
    """Run a VPN command after the menu closes, via vpn-notify.sh (notifications).

    stdin (e.g. credentials) is piped to the command, never put on its command line.
    """
    proc = subprocess.Popen(
        [NOTIFY, app, label, *cmd],
        start_new_session=True,
        stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if stdin is not None:
        proc.stdin.write(stdin.encode())
        proc.stdin.close()


class Menu(Gtk.Window):
    """The menu's window, kept between uses (hidden); open() fills it."""

    def __init__(self):
        super().__init__()
        self.provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), self.provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)

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
        self.backdrop = backdrop
        self.holder = None
        self.connect("key-press-event", self.on_key)
        self.connect("destroy", Gtk.main_quit)

    def toggle(self):
        if self.get_visible():
            self.close_menu()
        else:
            self.open()

    def open(self):
        # Where the click was, before anything that takes time.
        pos = cursor_position()
        self.server = server = current_server()
        self.custom = custom = load_custom_vpn()
        self.custom_state = custom_vpn_state(custom)
        custom_up = self.custom_state is not None
        # Both VPN buttons can be on the bar at once: use the colour of the one
        # that was clicked, found by its border colour under the cursor.
        # Colours are read each time: they follow the desktop theme.
        colours = theme_colours()
        on, it, off = rgb(colours["VPN_ON"]), rgb(colours["VPN_IT"]), rgb(colours["VPN_OFF"])
        candidates = [c for c, up in ((on, bool(server)), (it, custom_up)) if up] or [off]
        accent, center = candidates[0], None
        if pos:
            cx, origin, mon_width = pos
            for colour in candidates:
                found = module_center(cx, origin, mon_width, colour)
                if found is not None:
                    accent, center = colour, found
                    break
        css = CSS.replace("@ACCENT@", "#%02x%02x%02x" % accent)
        for name, value in colours.items():
            css = css.replace(f"@{name}@", value)
        self.provider.load_from_data(css.encode())
        # Opened from the IT VPN's button (its colour was found under the
        # cursor, or it's the only VPN up): show that VPN first.
        self.build(pos, center, from_it=custom_up and accent == it)
        self.show_all()

    def build(self, pos, center, from_it):
        if self.holder:
            self.holder.destroy()
        # The menu itself swallows clicks so they don't reach the backdrop.
        holder = self.holder = Gtk.EventBox()
        holder.connect("button-press-event", lambda *_: True)
        holder.set_halign(Gtk.Align.START)
        holder.set_valign(Gtk.Align.START)
        self.backdrop.add(holder)

        menu = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        menu.get_style_context().add_class("menu")
        menu.set_size_request(WIDTH, -1)
        holder.add(menu)

        if from_it and self.custom:
            # Opened from the IT VPN's button: that VPN first, then Proton.
            menu.add(self.custom_section(self.custom["label"]))
            menu.add(self.proton_section("next"))
        else:
            menu.add(self.proton_section())
            if self.custom:
                menu.add(self.custom_section("Other", "next"))

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

    def status_card(self, title_text, connected, on_disconnect, state_text=None):
        """A card row: lock icon, name and state, and a power button when up."""
        section = Gtk.Box(spacing=0)
        section.get_style_context().add_class("section")
        icon = Gtk.Label(label="󰌾" if connected else "󰌿")
        icon.get_style_context().add_class("icon")
        if connected:
            icon.get_style_context().add_class("active")
        section.pack_start(icon, False, False, 0)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        text.set_margin_start(10)
        title = Gtk.Label(label=title_text, xalign=0)
        title.get_style_context().add_class("title")
        sub = Gtk.Label(label=state_text or ("Connected" if connected else "Disconnected"), xalign=0)
        sub.get_style_context().add_class("dim")
        text.add(title)
        text.add(sub)
        section.pack_start(text, True, True, 0)
        if connected:
            section.pack_end(self.power_button(lambda *_: on_disconnect()), False, False, 0)
        return section

    def proton_section(self, extra_class=None):
        """Proton VPN: one row per server choice. The one in use says which
        server it's on and has the power button; a connection made some other
        way (Proton app) to a server not listed gets a row of its own."""
        wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        wrap.add(self.header("Proton VPN", extra_class))

        section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        section.get_style_context().add_class("section")
        current = active_choice(self.server)
        if self.server and current is None:
            section.add(self.server_item(None, "󰌾", self.server, "", True))
        for arg, glyph, name, subtitle in SERVERS:
            section.add(self.server_item(arg, glyph, name, subtitle, arg == current))
        wrap.add(section)
        return wrap

    def server_item(self, arg, glyph, name, subtitle, active):
        """A server row; the active one shows the server and a power button."""
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
        if active:
            subtitle = f"Connected · {self.server}" if arg else "Connected"
        sub = Gtk.Label(label=subtitle, xalign=0)
        sub.get_style_context().add_class("dim")
        text.add(title)
        text.add(sub)
        row.pack_start(text, True, True, 0)
        button.add(row)
        if arg:
            button.connect("clicked", lambda *_: self.choose(f"Connecting to {name}", CONNECT, arg))

        # The power button sits next to the row's button, not inside it.
        line = Gtk.Box()
        line.get_style_context().add_class("row")
        line.pack_start(button, True, True, 0)
        if active:
            line.pack_end(self.power_button(
                lambda *_: self.choose("Disconnecting", DISCONNECT)), False, False, 0)
        return line

    def custom_section(self, heading, extra_class=None):
        """The extra OpenVPN 3 profile: a card with a power button when it's up,
        otherwise an entry that opens the inline sign-in form."""
        wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        wrap.add(self.header(heading, extra_class))
        label = self.custom["label"]
        if self.custom_state:
            wrap.add(self.status_card(
                label, True, self.disconnect_custom,
                "Connected" if self.custom_state == "connected" else "Reconnecting…"))
            return wrap

        section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        section.get_style_context().add_class("section")
        button = Gtk.Button()
        button.get_style_context().add_class("item")
        row = Gtk.Box()
        icon = Gtk.Label(label="󰖂")
        icon.get_style_context().add_class("icon")
        row.pack_start(icon, False, False, 0)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        text.set_margin_start(10)
        title = Gtk.Label(label=label, xalign=0)
        title.get_style_context().add_class("title")
        sub = Gtk.Label(label="Sign in to connect", xalign=0)
        sub.get_style_context().add_class("dim")
        text.add(title)
        text.add(sub)
        row.pack_start(text, True, True, 0)
        button.add(row)
        section.add(button)
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
        # By session path: the profile is imported single-use, so once connected
        # its config is gone and `session-manage --config` can't find it.
        run_detached(
            "Disconnecting", "bash", "-c",
            'path=$(openvpn3 sessions-list | awk -v name="Config name: $1" '
            "'/Path:/ {p = $2} index($0, name) {print p; exit}'); "
            '[ -n "$path" ] || { echo "Error: no $2 session found"; exit 1; }; '
            'openvpn3 session-manage --session-path "$path" --disconnect >/dev/null '
            '&& echo "Disconnected from $2."',
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
        self.hide()
        return True


def main():
    """The daemon (the launcher part is at the top of the file)."""
    try:
        with open(DAEMON_PID) as f:
            os.kill(int(f.read().strip()), 0)
        return  # already running
    except (OSError, ValueError):
        pass
    with open(DAEMON_PID, "w") as f:
        f.write(str(os.getpid()))
    try:
        win = Menu()
        try:
            gi.require_version("GLibUnix", "2.0")
            from gi.repository import GLibUnix
            add_signal = GLibUnix.signal_add
        except (ImportError, ValueError):
            add_signal = GLib.unix_signal_add
        add_signal(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: Gtk.main_quit() or False)
        add_signal(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, lambda: win.toggle() or True)
        if "--show" in sys.argv:
            win.open()
        Gtk.main()
    finally:
        try:
            with open(DAEMON_PID) as f:
                if f.read().strip() == str(os.getpid()):
                    os.remove(DAEMON_PID)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
