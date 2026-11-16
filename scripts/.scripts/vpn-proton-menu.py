#!/usr/bin/env python3
"""VPN dropdown for the bar's VPN buttons (bound to right click).

Looks like the bar's own (Wayle's) dropdowns. Opens centred under the button,
closes on Esc, on a click outside it, or when launched again (toggle).

Runs in the background (`--daemon`, autostarted by hyprland.lua) with its
window ready, like the bar's own dropdowns: launching the script just sends
it SIGUSR1, before even loading GTK, so the menu opens at once. If it isn't
running, the launch starts it and it opens the menu when ready.

Optionally also offers one OpenVPN 3 profile (e.g. a work VPN), configured in
a local, untracked file:
    ~/.config/vpn-proton-menu/custom-vpn.conf
        label=Work VPN
        config=~/path/to/profile.ovpn
Clicking it asks for a username and password inside the menu, like the bar's
Wi-Fi password prompt; they go to ~/.scripts/openvpn3-connect.py on stdin.
Only the username is remembered.
"""
import json
import os
import signal
import socket
import subprocess
import sys
import tomllib

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

WIDTH = 354 + 2 * 14  # Wayle's dropdown width, plus the margins holding the shadow
TOP = 52  # the dropdown's top edge, where Wayle's own dropdowns start (styles/index.scss)
SHADOW_TOP = 10  # .dropdown's top margin
BAR_HEIGHT = 48

# Colours follow the desktop theme: Wayle's palette, which theme-set writes to
# ~/.config/wayle/theme.toml, with the other colours derived from it the way
# Wayle's own stylesheet does. Defaults: Wayle's Catppuccin Mocha.
WAYLE_THEME = os.path.expanduser("~/.config/wayle/theme.toml")
PALETTE = {
    "bg": "#11111b", "surface": "#181825", "elevated": "#1e1e2e", "fg": "#cdd6f4",
    "fg-muted": "#bac2de", "primary": "#b4befe", "red": "#f38ba8", "yellow": "#f9e2af",
    "green": "#a6e3a1", "blue": "#74c7ec",
}
# The VPN buttons' colours, to find the clicked one on the bar: Wayle's are the
# palette's green/blue/red (config.toml); HyprPanel's (if it's the bar,
# ~/.scripts/bar-switch) are these keys of its config.json.
BAR_STATE = os.path.join(os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")), "bar")
HYPRPANEL_CONFIG = os.path.expanduser("~/.config/hyprpanel/config.json")
HYPRPANEL_VPN = {
    "VPN_ON": ("theme.bar.buttons.modules.netstat.text", "#a6e3a1"),
    "VPN_IT": ("theme.bar.buttons.modules.weather.text", "#b4befe"),
    "VPN_OFF": ("theme.bar.buttons.modules.cpu.text", "#f38ba8"),
}


def rgb(colour):
    colour = colour.lstrip("#")
    return tuple(int(colour[i:i + 2], 16) for i in (0, 2, 4))


def mix(a, b, amount):
    """CSS color-mix(in srgb, a, b amount)."""
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * amount) for x, y in zip(rgb(a), rgb(b)))


def alpha(colour, amount):
    return "rgba(%d, %d, %d, %s)" % (*rgb(colour), amount)


def theme_colours():
    palette = dict(PALETTE)
    try:
        with open(WAYLE_THEME, "rb") as f:
            palette.update(tomllib.load(f).get("styling", {}).get("palette", {}))
    except (OSError, ValueError):
        pass
    p = palette
    colours = {
        "SURFACE": p["surface"], "ELEVATED": p["elevated"], "FG": p["fg"],
        "FG_MUTED": p["fg-muted"], "ACCENT": p["primary"], "RED": p["red"],
        "BORDER": mix(p["elevated"], p["fg"], 0.10),        # --border-default
        "OVERLAY": mix(p["elevated"], p["fg"], 0.08),       # --bg-overlay
        "FG_SUBTLE": alpha(p["fg"], 0.5),                   # --fg-subtle
        "BORDER_SUBTLE": alpha(p["fg"], 0.12),              # --border-subtle
        "ACCENT_SUBTLE": alpha(p["primary"], 0.15),         # --accent-subtle
        "VPN_ON": p["green"], "VPN_IT": p["blue"], "VPN_OFF": p["red"],
    }
    try:
        with open(BAR_STATE) as f:
            hyprpanel = f.read().strip() == "hyprpanel"
    except OSError:
        hyprpanel = False
    if hyprpanel:
        try:
            with open(HYPRPANEL_CONFIG) as f:
                config = json.load(f)
        except (OSError, ValueError):
            config = {}
        colours.update({name: config.get(key, default) for name, (key, default) in HYPRPANEL_VPN.items()})
    return colours


# (connect-script argument, icon, title, subtitle)
SERVERS = [
    ("pt", "ld-globe-symbolic", "Portugal", "Fastest Lisbon server"),
    ("ES#75", "ld-globe-symbolic", "Spain · ES#75", "Madrid"),
    ("fastest", "ld-zap-symbolic", "Fastest", "Best server anywhere"),
]
# Written by vpn-proton-connect.sh as "<choice> <server>"
CHOICE_FILE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "vpn-proton-choice")

# Wayle's icons (lucide), so the menu matches its dropdowns.
ICON_DIRS = [os.path.expanduser("~/.local/share/wayle/icons"), "/usr/share/wayle/icons"]

CSS = """
/* Wayle's dropdowns (its stylesheet, at its 14.4px rem): a header bar, then
   uppercase section labels over rounded cards of rows. */
* { font-family: "Noto Sans"; font-size: 13.5px; font-weight: 500; }
window, .backdrop { background: transparent; }
button { background: none; border: none; box-shadow: none; padding: 0; margin: 0;
         min-height: 0; min-width: 0; outline: none; }
.dropdown {
  background: @SURFACE@; color: @FG@;
  border: 1px solid @BORDER@; border-radius: 12.6px;
  box-shadow: 0 0 5px rgba(0, 0, 0, 0.3), 0 4px 10px rgba(0, 0, 0, 0.3);
  margin: 10px 14px 18px 14px;
}
.dropdown-header {
  background: @ELEVATED@; border-bottom: 1px solid @BORDER@;
  border-radius: 11.6px 11.6px 0 0;
  padding: 7px 14px; margin-bottom: 2px;
}
.dropdown-title { font-size: 15px; font-weight: 700; color: @FG@; }
.dropdown-title-icon { color: @ACCENT@; margin-right: 6px; }
.dropdown-content { padding: 11px; }
.section-label { font-size: 12.6px; font-weight: 700; color: @FG_SUBTLE@; margin: 22px 0 7px 0; }
.section-label.first { margin-top: 0; }
.card { background: @ELEVATED@; border-radius: 9px; }
.sep { border-top: 1px solid @BORDER_SUBTLE@; }
.item { padding: 7px; border-radius: 9px; }
.item:hover { background: @OVERLAY@; }
.row-icon { color: @FG_MUTED@; margin: 0 14px 0 7px; }
.icon-square { background: @ACCENT_SUBTLE@; border-radius: 9px; margin-right: 7px; }
.icon-square image { color: @ACCENT@; margin: 11px; }
.title { color: @FG@; }
.active .title { font-weight: 700; }
.subtitle { font-size: 11.7px; color: @FG_SUBTLE@; }
.icon-button { color: @FG_MUTED@; padding: 6px; border-radius: 9px; margin-right: 4px; }
.icon-button:hover { color: @RED@; background: @OVERLAY@; }
.login { padding: 4px 7px 7px 7px; }
.field {
  background: @SURFACE@; border: 1px solid @BORDER@; border-radius: 9px;
  padding: 6px 10px; margin-bottom: 7px;
}
.field entry { background: none; border: none; box-shadow: none; color: @FG@; padding: 0;
               min-height: 0; caret-color: @ACCENT@; }
.field-icon { color: @FG_MUTED@; }
.connect { background: @ACCENT@; color: @SURFACE@; border-radius: 9px; padding: 7px 0; font-weight: 600; }
.connect:hover { opacity: 0.85; }
.login-error { color: @RED@; font-size: 11.7px; margin-bottom: 7px; }
.eye { color: @FG_MUTED@; }
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

    The bar doesn't expose widget positions, so grab the bar strip around the
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


def icon(name, size, *classes):
    """One of Wayle's symbolic icons, tinted by the CSS colour."""
    image = Gtk.Image.new_from_icon_name(name, Gtk.IconSize.BUTTON)
    image.set_pixel_size(size)
    for c in classes:
        image.get_style_context().add_class(c)
    return image


def label(text, *classes, **kwargs):
    widget = Gtk.Label(label=text, xalign=0, **kwargs)
    for c in classes:
        widget.get_style_context().add_class(c)
    return widget


class Menu(Gtk.Window):
    """The menu's window, kept between uses (hidden); open() fills it."""

    def __init__(self):
        super().__init__()
        self.provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), self.provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)
        theme = Gtk.IconTheme.get_default()
        for path in ICON_DIRS:
            theme.append_search_path(path)

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
        # Both VPN buttons can be on the bar at once: centre on the one that
        # was clicked, found by its border colour under the cursor.
        # Colours are read each time: they follow the desktop theme.
        colours = theme_colours()
        on, it, off = rgb(colours["VPN_ON"]), rgb(colours["VPN_IT"]), rgb(colours["VPN_OFF"])
        candidates = [c for c, up in ((on, bool(server)), (it, custom_up)) if up] or [off]
        clicked, center = candidates[0], None
        if pos:
            cx, origin, mon_width = pos
            for colour in candidates:
                found = module_center(cx, origin, mon_width, colour)
                if found is not None:
                    clicked, center = colour, found
                    break
        css = CSS
        for name, value in colours.items():
            css = css.replace(f"@{name}@", value)
        self.provider.load_from_data(css.encode())
        # Opened from the IT VPN's button (its colour was found under the
        # cursor, or it's the only VPN up): show that VPN first.
        self.build(pos, center, from_it=custom_up and clicked == it)
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
        menu.get_style_context().add_class("dropdown")
        menu.set_size_request(WIDTH, -1)  # (GTK3 counts the CSS margins in it)
        holder.add(menu)

        # Header, like Wayle's: an accent icon and the title.
        up = bool(self.server) or self.custom_state is not None
        header = Gtk.Box()
        header.get_style_context().add_class("dropdown-header")
        header.pack_start(icon("ld-lock-symbolic" if up else "cm-nf-lock-open-symbolic", 22,
                               "dropdown-title-icon"), False, False, 0)
        header.pack_start(label("VPN", "dropdown-title"), True, True, 0)
        menu.add(header)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content.get_style_context().add_class("dropdown-content")
        menu.add(content)
        if from_it and self.custom:
            # Opened from the IT VPN's button: that VPN first, then Proton.
            content.add(self.custom_section(first=True))
            content.add(self.proton_section())
        else:
            content.add(self.proton_section(first=True))
            if self.custom:
                content.add(self.custom_section())

        if pos:
            cx, origin, mon_width = pos
            self.place_on_monitor(origin)
            # Centre on the button itself; fall back to the cursor.
            x = (center if center is not None else cx) - origin[0]
            left = max(4, min(round(x - WIDTH / 2), mon_width - WIDTH - 4))
            holder.set_margin_start(left)
        holder.set_margin_top(TOP - SHADOW_TOP)

    def place_on_monitor(self, origin):
        display = Gdk.Display.get_default()
        for i in range(display.get_n_monitors()):
            mon = display.get_monitor(i)
            g = mon.get_geometry()
            if (g.x, g.y) == origin:
                GtkLayerShell.set_monitor(self, mon)
                return

    def section(self, title, first=False):
        """An uppercase section label over a card; returns (box, card)."""
        wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        heading = label(title.upper(), "section-label")
        if first:
            heading.get_style_context().add_class("first")
        wrap.add(heading)
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        card.get_style_context().add_class("card")
        wrap.add(card)
        return wrap, card

    def add_row(self, card, widget):
        """Rows in a card are separated by a faint line."""
        if card.get_children():
            sep = Gtk.Box()
            sep.get_style_context().add_class("sep")
            card.add(sep)
        card.add(widget)

    def row_content(self, icon_name, title, subtitle, active):
        """Icon (in an accent square when active), title and subtitle."""
        row = Gtk.Box()
        if active:
            row.get_style_context().add_class("active")
            square = Gtk.Box()
            square.get_style_context().add_class("icon-square")
            square.add(icon(icon_name, 18))
            square.set_valign(Gtk.Align.CENTER)
            row.pack_start(square, False, False, 0)
        else:
            image = icon(icon_name, 22, "row-icon")
            image.set_valign(Gtk.Align.CENTER)
            row.pack_start(image, False, False, 0)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        text.set_valign(Gtk.Align.CENTER)
        text.add(label(title, "title", ellipsize=3))
        if subtitle:
            text.add(label(subtitle, "subtitle", ellipsize=3))
        row.pack_start(text, True, True, 0)
        return row

    def power_button(self, on_click):
        button = Gtk.Button()
        button.add(icon("ld-power-symbolic", 18))
        button.set_tooltip_text("Disconnect")
        button.get_style_context().add_class("icon-button")
        button.set_valign(Gtk.Align.CENTER)
        button.connect("clicked", on_click)
        return button

    def item(self, content, on_click=None, power=None):
        """A row: clickable (hover highlight) when on_click; a power button
        beside it when power."""
        line = Gtk.Box()
        if on_click:
            button = Gtk.Button()
            button.get_style_context().add_class("item")
            button.add(content)
            button.connect("clicked", lambda *_: on_click())
            line.pack_start(button, True, True, 0)
        else:
            content.get_style_context().add_class("item")
            line.pack_start(content, True, True, 0)
        if power:
            line.pack_end(self.power_button(lambda *_: power()), False, False, 0)
        return line

    def proton_section(self, first=False):
        """Proton VPN: one row per server choice. The one in use says which
        server it's on and has the power button; a connection made some other
        way (Proton app) to a server not listed gets a row of its own."""
        wrap, card = self.section("Proton VPN", first)
        current = active_choice(self.server)
        disconnect = lambda: self.choose("Disconnecting", DISCONNECT)  # noqa: E731
        if self.server and current is None:
            self.add_row(card, self.item(self.row_content(
                "ld-lock-symbolic", self.server, "Connected", True), power=disconnect))
        for arg, icon_name, name, subtitle in SERVERS:
            active = arg == current
            content = self.row_content(icon_name, name,
                                       f"Connected · {self.server}" if active else subtitle, active)
            connect = (lambda a=arg, n=name: self.choose(f"Connecting to {n}", CONNECT, a))
            self.add_row(card, self.item(content, None if active else connect,
                                         disconnect if active else None))
        return wrap

    def custom_section(self, first=False):
        """The extra OpenVPN 3 profile: its row with a power button when it's
        up, otherwise a row that opens the inline sign-in form."""
        label_text = self.custom["label"]
        wrap, card = self.section(label_text, first)
        if self.custom_state:
            state = "Connected" if self.custom_state == "connected" else "Reconnecting…"
            self.add_row(card, self.item(self.row_content("ld-lock-symbolic", label_text, state, True),
                                         power=self.disconnect_custom))
            return wrap
        self.add_row(card, self.item(
            self.row_content("cm-nf-lock-open-symbolic", label_text, "Sign in to connect", False),
            self.toggle_login))
        self.login = Gtk.Revealer()
        self.login.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.login.set_transition_duration(150)
        self.login.add(self.login_form())
        card.add(self.login)
        return wrap

    def field(self, icon_name, placeholder, secret=False):
        box = Gtk.Box()
        box.get_style_context().add_class("field")
        box.pack_start(icon(icon_name, 16, "field-icon"), False, False, 0)
        entry = Gtk.Entry()
        entry.set_placeholder_text(placeholder)
        entry.set_has_frame(False)
        if secret:
            entry.set_visibility(False)
            entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        box.pack_start(entry, True, True, 8)
        if secret:
            # Show/hide toggle. An image in an event box: a GtkButton whose
            # content changes under the pointer ignores the next click until
            # the mouse moves.
            eye = icon("ld-eye-symbolic", 16, "eye")
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
        eye.set_from_icon_name("ld-eye-off-symbolic" if shown else "ld-eye-symbolic", Gtk.IconSize.BUTTON)
        eye.set_pixel_size(16)
        area.set_tooltip_text("Hide password" if shown else "Show password")
        ctx = eye.get_style_context()
        (ctx.add_class if shown else ctx.remove_class)("on")
        entry.grab_focus_without_selecting()
        return True

    def login_form(self):
        form = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        form.get_style_context().add_class("login")
        self.login_error = label("", "login-error")
        self.login_error.set_no_show_all(True)
        form.add(self.login_error)

        user_box, self.user_entry = self.field("ld-user-symbolic", "Username")
        self.user_entry.set_text(remembered_user())
        pass_box, self.pass_entry = self.field("ld-lock-symbolic", "Password", secret=True)
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
