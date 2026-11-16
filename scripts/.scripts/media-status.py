#!/usr/bin/env python3
"""The bar's media button (Wayle custom module "media", watch mode), in place
of Wayle's own media module, which can only cut a long title.

Shows "artist - title" of the current player (MPRIS over D-Bus: the playing
one, else the last one that changed) in at most WIDTH px. A longer one is cut
with "..." (as HyprPanel did), and scrolls through, smoothly, while it plays
or while the pointer is over the button. Its icon: nerd-icons.toml's media
player-icons (as Wayle's media module used), sent as "alt" (config.toml's
icon-map for this module lists the ones Wayle shows), else a music note.
Nothing (button hidden) without a player.

Smooth scrolling: Wayle's label can only change a character at a time, and
its buttons don't clip, so a long title is drawn by a transparent,
click-through layer right over the label (a "ticker", GTK layer shell,
namespace media-ticker): still and cut, or scrolling pixel by pixel, clipped
to the label's area with faded ends. It draws the still text too, so starting
and stopping the scroll never swaps one renderer for another; the label
underneath (the cut text, giving the button its width) is invisible (class
"ticking", styles/index.scss). The button is found on
the bar by its border colour (the theme's media one, styles/_theme.scss),
which also tells when the pointer is over it. With a bar on several screens,
one of the watchers (a lock) draws the tickers for all of them.

One JSON line per change: {"text": ..., "alt": icon name, "class": "ticking"
while scrolling}. Exits when Wayle
(the parent) is gone or stops reading.
"""
import fcntl
import fnmatch
import json
import os
import re
import socket
import subprocess
import sys
import time
import tomllib

import cairo
import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, Gio, GLib, Gtk, GtkLayerShell, Pango, PangoCairo  # noqa: E402

WIDTH = 160  # px: the text's widest
FONT = "Noto Sans SemiBold 13.5px"  # the bar labels' (config.toml, styles/index.scss)
SPEED = 30  # px/s
PAUSE = 1.5  # s at the start of each pass
FIRST_PAUSE = 0.4  # s before the first pass (on hover, on play)
HANDOVER = 60  # ms between the ticker and the label taking over from each other
GAP = 40  # px between the end of the text and its start again
FADE = 10  # px of fading at the ticker's ends
# Where Wayle draws the label, measured on the bar: from the button's outer
# left edge, and the text's top (Pango's layout top) from the screen's top.
TEXT_X = 29
TEXT_Y = 17
TICKER_PAD = 3  # px of room above/below the text in the ticker
BUTTON_TOP = 12  # the buttons' top border row (styles/index.scss)
BAR_HEIGHT = 48
HOVER_POLL = 100  # ms
HOVER_POLL_NEAR = 25  # ms, while the pointer is on the bar
ICONS = os.path.expanduser("~/.config/wayle/nerd-icons.toml")
THEME_SCSS = os.path.expanduser("~/.config/wayle/styles/_theme.scss")
DEFAULT_ICON = "ld-music-symbolic"
MPRIS = "org.mpris.MediaPlayer2"
PATH = "/org/mpris/MediaPlayer2"
RUN = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
LOCK = os.path.join(RUN, "media-status.lock")

FONT_DESC = Pango.FontDescription.from_string(FONT)
# Text laid out as GTK4 (Wayle) does: unhinted metrics and glyphs at
# fractional positions. GTK3/cairo's default (hinted, rounded) spaces the
# letters wider, which showed when the ticker took over from the label.
FONT_OPTIONS = cairo.FontOptions()
FONT_OPTIONS.set_hint_metrics(cairo.HINT_METRICS_OFF)
FONT_OPTIONS.set_hint_style(cairo.HINT_STYLE_SLIGHT)
FONT_OPTIONS.set_antialias(cairo.ANTIALIAS_GRAY)


def like_gtk4(context):
    PangoCairo.context_set_font_options(context, FONT_OPTIONS)
    context.set_round_glyph_positions(False)
    return context


layout = Pango.Layout(like_gtk4(PangoCairo.FontMap.get_default().create_context()))
layout.set_font_description(FONT_DESC)


def width(text):
    layout.set_text(text, -1)
    return layout.get_extents()[1].width / Pango.SCALE


HAIR = width(" " * 10) / 10  # a hair space's width, to pad with


def pad(text):
    """Text padded with hair spaces to (almost exactly) WIDTH."""
    missing = WIDTH - width(text)
    return text + " " * max(0, int(missing / HAIR)) if HAIR > 0 else text


def cut(text):
    """The text cut to WIDTH with "...", padded to WIDTH."""
    out = ""
    for ch in text:
        if width(out + ch + "...") > WIDTH:
            break
        out += ch
    return pad(out.rstrip() + "...")


def player_icons():
    try:
        with open(ICONS, "rb") as f:
            return tomllib.load(f).get("modules", {}).get("media", {}).get("player-icons", {})
    except (OSError, ValueError):
        return {}


def theme_colours():
    """The media button's border and text colours (RGB 0..255)."""
    found = {}
    try:
        with open(THEME_SCSS) as f:
            for name, value in re.findall(r"\$(media-[\w-]+):\s*#([0-9a-fA-F]{6})", f.read()):
                found[name] = tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))
    except OSError:
        pass
    border = found.get("media-border", (0xb4, 0xbe, 0xfe))
    return border, found.get("media-text", border)


# --- Hyprland ------------------------------------------------------------------

def hyprctl(request):
    path = os.path.join(RUN, "hypr", os.environ["HYPRLAND_INSTANCE_SIGNATURE"], ".socket.sock")
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(1)
        sock.connect(path)
        sock.sendall(request.encode())
        data = b""
        while chunk := sock.recv(65536):
            data += chunk
    return data.decode()


def monitors():
    """[(name, x, y, logical width)]"""
    try:
        return [(m["name"], m["x"], m["y"], round(m["width"] / (m.get("scale") or 1)))
                for m in json.loads(hyprctl("j/monitors"))]
    except (OSError, KeyError, ValueError):
        return []


def cursor():
    try:
        c = json.loads(hyprctl("j/cursorpos"))
        return c["x"], c["y"]
    except (OSError, KeyError, ValueError):
        return None


def find_button(mon, border):
    """The media button's (left, right) on that screen (global x), by its top
    border's colour (plain or brightened by Wayle's hover), or None."""
    _name, mx, my, mw = mon
    try:
        ppm = subprocess.run(["grim", "-s", "1", "-t", "ppm", "-g", f"{mx},{my + BUTTON_TOP} {mw}x1", "-"],
                             capture_output=True, timeout=1).stdout
        _magic, dims, _maxval, data = ppm.split(b"\n", 3)
        w = int(dims.split()[0])
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return None
    bright = tuple(min(255, round(c * 1.15)) for c in border)

    def matches(x):
        p = data[x * 3:x * 3 + 3]
        return any(all(abs(a - b) <= 24 for a, b in zip(p, c)) for c in (border, bright))

    x = 0
    while x < w:
        if matches(x):
            start = x
            while x < w and matches(x):
                x += 1
            # The button: label (WIDTH) + icon and paddings (~40 px).
            if WIDTH + 25 <= x - start <= WIDTH + 60:
                return mx + start, mx + x - 1
        x += 1
    return None


# --- the ticker (smooth scrolling over the label) ---------------------------------

class Ticker(Gtk.Window):
    """Stays mapped once made (showing and hiding a layer makes Hyprland fade
    it, a flash): transparent when there's nothing to scroll."""

    def __init__(self, gdk_monitor):
        super().__init__()
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "media-ticker")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)  # the bar's layer, above it
        GtkLayerShell.set_monitor(self, gdk_monitor)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, True)
        GtkLayerShell.set_exclusive_zone(self, -1)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, TEXT_Y - TICKER_PAD)
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)
        layout.set_text("Ag", -1)
        self.height = layout.get_pixel_extents()[1].height + 2 * TICKER_PAD
        self.area = Gtk.DrawingArea()
        self.area.set_size_request(WIDTH, self.height)
        self.area.connect("draw", self.draw)
        self.add(self.area)
        # Click-through (the button under it gets the clicks and the hover),
        # set again whenever it's mapped.
        for signal_name in ("realize", "map-event"):
            self.connect(signal_name, lambda *_: self.click_through())
        self.text = None  # None: nothing drawn
        self.moving = False
        self.still = None  # the still (cut) text's layout
        self.colour = (255, 255, 255)
        self.start = 0.0
        self.pause = PAUSE
        self.timer = None
        self.lay = None  # the text's Pango layout, made once per text
        self.loop = 0.0  # its width + GAP
        self.left = None
        self.area.show()
        self.show()

    def click_through(self):
        window = self.get_window()
        if window:
            window.input_shape_combine_region(cairo.Region(), 0, 0)
        return False

    def place(self, left, mon_x):
        if left != self.left:
            self.left = left
            GtkLayerShell.set_margin(self, GtkLayerShell.Edge.LEFT, left + TEXT_X - mon_x)

    def run(self, text, colour, moving):
        """Draw text: still and cut with "..." (as the label would), or moving."""
        if text != self.text:
            self.lay = self.still = None
            self.loop = width(text) + GAP
            self.text = text
            self.moving = False
            self.area.queue_draw()
        if moving and not self.moving:  # from the start, after a short pause
            self.start = time.monotonic()
            self.pause = FIRST_PAUSE
        if moving != self.moving or colour != self.colour:
            self.moving, self.colour = moving, colour
            self.area.queue_draw()
        if moving and not self.timer:
            self.timer = GLib.timeout_add(round(1000 / SPEED), self.on_tick)
        elif not moving and self.timer:
            GLib.source_remove(self.timer)
            self.timer = None

    def stop(self):
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = None
        if self.text is not None:
            self.text = None
            self.area.queue_draw()

    def on_tick(self):
        # A 1 px step per frame while moving (SPEED frames a second); none
        # during the pauses.
        if time.monotonic() - self.start > self.pause:
            self.area.queue_draw()
        return True

    @staticmethod
    def layout(cr, text):
        lay = PangoCairo.create_layout(cr)
        like_gtk4(lay.get_context())
        lay.context_changed()
        lay.set_font_description(FONT_DESC)
        lay.set_text(text, -1)
        return lay

    def offset(self):
        moved = float(int(max(0.0, time.monotonic() - self.start - self.pause) * SPEED))  # whole px
        if moved >= self.loop:  # a pass done: from the start again, after a pause
            self.start = time.monotonic()
            self.pause = PAUSE
            return 0.0
        return moved

    def draw(self, _area, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        if self.text is None:
            return True
        cr.set_operator(cairo.OPERATOR_OVER)
        cr.set_source_rgb(*(c / 255 for c in self.colour))
        if not self.moving:
            if self.still is None:
                self.still = self.layout(cr, cut(self.text).rstrip("\u200a"))
            cr.move_to(0, TICKER_PAD)
            PangoCairo.show_layout(cr, self.still)
            return True
        offset = self.offset()
        cr.push_group()
        if self.lay is None:
            self.lay = self.layout(cr, self.text)
            self.loop = self.lay.get_extents()[1].width / Pango.SCALE + GAP
        cr.set_source_rgb(*(c / 255 for c in self.colour))
        for x in (-offset, -offset + self.loop):
            cr.move_to(x, TICKER_PAD)
            PangoCairo.show_layout(cr, self.lay)
        cr.pop_group_to_source()
        # Faded ends: the right one always, the left one once the text moves.
        mask = cairo.LinearGradient(0, 0, WIDTH, 0)
        left = min(1.0, offset / FADE)
        mask.add_color_stop_rgba(0, 0, 0, 0, 1 - left)
        mask.add_color_stop_rgba(FADE / WIDTH, 0, 0, 0, 1)
        mask.add_color_stop_rgba(1 - FADE / WIDTH, 0, 0, 0, 1)
        mask.add_color_stop_rgba(1, 0, 0, 0, 0)
        cr.mask(mask)
        return True


# --- players -------------------------------------------------------------------

class Players:
    def __init__(self, on_change):
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        self.on_change = on_change
        self.changed = {}  # bus name -> when it last changed (to pick the latest)
        self.owners = {}  # unique name -> bus name
        self.bus.signal_subscribe(None, "org.freedesktop.DBus.Properties", "PropertiesChanged",
                                  PATH, None, Gio.DBusSignalFlags.NONE, self.on_properties)
        self.bus.signal_subscribe("org.freedesktop.DBus", "org.freedesktop.DBus",
                                  "NameOwnerChanged", "/org/freedesktop/DBus", None,
                                  Gio.DBusSignalFlags.NONE, self.on_owner)
        for name in self.names():
            self.changed[name] = 0
            self.remember_owner(name)

    def call(self, dest, path, iface, method, args=None, reply=None):
        return self.bus.call_sync(dest, path, iface, method, args,
                                  GLib.VariantType(reply) if reply else None,
                                  Gio.DBusCallFlags.NONE, 1000, None).unpack()

    def names(self):
        try:
            names = self.call("org.freedesktop.DBus", "/org/freedesktop/DBus",
                              "org.freedesktop.DBus", "ListNames", None, "(as)")[0]
        except GLib.Error:
            return []
        return [n for n in names if n.startswith(MPRIS + ".")]

    def remember_owner(self, name):
        try:
            owner = self.call("org.freedesktop.DBus", "/org/freedesktop/DBus",
                              "org.freedesktop.DBus", "GetNameOwner",
                              GLib.Variant("(s)", (name,)), "(s)")[0]
            self.owners[owner] = name
        except GLib.Error:
            pass

    def on_owner(self, _bus, _sender, _path, _iface, _signal, params):
        name, _old, new = params.unpack()
        if not name.startswith(MPRIS + "."):
            return
        if new:
            self.owners[new] = name
            self.changed[name] = time.monotonic()
        else:
            self.changed.pop(name, None)
        self.on_change()

    def on_properties(self, _bus, sender, _path, _iface, _signal, _params):
        name = self.owners.get(sender)
        if name:
            self.changed[name] = time.monotonic()
        self.on_change()

    def props(self, name, iface):
        try:
            return self.call(name, PATH, "org.freedesktop.DBus.Properties", "GetAll",
                             GLib.Variant("(s)", (iface,)), "(a{sv})")[0]
        except GLib.Error:
            return {}

    def current(self):
        """(bus name, status, artist, title, identity) of the player to show, or None."""
        found = []
        for name in self.names():
            p = self.props(name, MPRIS + ".Player")
            meta = p.get("Metadata", {})
            title = meta.get("xesam:title", "")
            if not title:
                continue
            artist = meta.get("xesam:artist", [])
            artist = ", ".join(artist) if isinstance(artist, list) else str(artist)
            found.append((p.get("PlaybackStatus") == "Playing", self.changed.get(name, 0),
                          name, p.get("PlaybackStatus", ""), artist, title))
        if not found:
            return None
        _playing, _when, name, status, artist, title = max(found)
        root = self.props(name, MPRIS)
        ident = " ".join(str(root.get(k, "")) for k in ("DesktopEntry", "Identity"))
        return name, status, artist, title, ident


# --- the button ----------------------------------------------------------------

class Button:
    def __init__(self):
        self.icons = player_icons()
        self.text = self.icon = None
        self.playing = self.hovered = False
        self.ticking = False  # the label hidden (the ticker draws the text)
        self.last = None
        self.lock = None
        self.tickers = {}  # monitor name -> Ticker
        self.buttons = {}  # monitor name -> ((left, right) or None, when found)
        self.mons = []
        self.mons_at = 0.0
        self.followed = 0.0
        self.handover = None
        self.players = Players(self.refresh)
        self.refresh()
        GLib.timeout_add(HOVER_POLL, self.poll)

    # state

    def icon_for(self, name, ident):
        subject = name[len(MPRIS) + 1:] + " " + ident
        for pattern, icon in self.icons.items():
            if fnmatch.fnmatchcase(subject, pattern):
                return icon
        return DEFAULT_ICON

    def refresh(self):
        player = self.players.current()
        if not player:
            self.text = self.icon = None
            self.playing = False
        else:
            name, status, artist, title, ident = player
            self.text = f"{artist} - {title}" if artist else title
            self.icon = self.icon_for(name, ident)
            self.playing = status == "Playing"
        self.update()

    def long(self):
        return bool(self.text) and width(self.text) > WIDTH

    def update(self):
        """A long text is drawn by the ticker all the time, still or moving,
        and the label (giving the button its width) is hidden: one renderer,
        so starting and stopping the scroll changes nothing else. The label
        shows only for a short text, or while the ticker can't be placed.
        Taking over, the ticker draws first and the label hides a moment
        later (and the other way round), so there's never a gap."""
        if self.handover:
            GLib.source_remove(self.handover)
            self.handover = None
        if self.long():
            placed = self.update_tickers()
            if placed and not self.ticking:
                self.handover = GLib.timeout_add(HANDOVER, self.set_ticking, True)
            elif not placed and self.ticking:
                self.ticking = False
        else:
            self.ticking = False
            self.handover = GLib.timeout_add(HANDOVER, self.stop_tickers)
        self.output()

    def set_ticking(self, ticking):
        self.handover = None
        self.ticking = ticking
        self.output()
        return False

    def stop_tickers(self):
        self.handover = None
        for ticker in self.tickers.values():
            ticker.stop()
        return False

    def output(self):
        if not self.text:
            line = ""
        else:
            data = {"text": cut(self.text) if self.long() else self.text, "alt": self.icon}
            if self.ticking:
                data["class"] = "ticking"  # the label hidden: the ticker draws over it
            line = json.dumps(data, ensure_ascii=False)
        if line != self.last:
            self.last = line
            try:
                print(line, flush=True)
            except BrokenPipeError:
                Gtk.main_quit()

    # where the button is, the pointer, the tickers

    def leader(self):
        """One watcher draws the tickers (a bar per screen: a watcher each)."""
        if self.lock is None:
            fd = os.open(LOCK, os.O_RDWR | os.O_CREAT, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.lock = fd
            except OSError:
                os.close(fd)
        return self.lock is not None

    def screens(self):
        if time.monotonic() - self.mons_at > 3:
            self.mons, self.mons_at = monitors(), time.monotonic()
        return self.mons

    def button_on(self, mon, max_age):
        found = self.buttons.get(mon[0])
        if not found or time.monotonic() - found[1] > max_age:
            border, _text = theme_colours()
            found = (find_button(mon, border), time.monotonic())
            self.buttons[mon[0]] = found
        return found[0]

    def poll(self):
        """The pointer over the button? (Only matters for a long text.) Checked
        often while it's on the bar, so the text brightens with the button."""
        hovered = near = False
        if self.long():
            pos = cursor()
            if pos:
                cx, cy = pos
                for mon in self.screens():
                    _name, mx, my, mw = mon
                    if mx <= cx < mx + mw and my <= cy < my + BAR_HEIGHT:
                        near = True
                        found = self.button_on(mon, max_age=2.0)
                        hovered = bool(found) and found[0] <= cx <= found[1] \
                            and my + BUTTON_TOP <= cy <= my + BUTTON_TOP + 30
        if hovered != self.hovered:
            self.hovered = hovered
            self.update()
        elif self.long() and time.monotonic() - self.followed > 2:
            self.followed = time.monotonic()
            self.update()  # follow the button if it moved (or place it at last)
        GLib.timeout_add(HOVER_POLL_NEAR if near else HOVER_POLL, self.poll)
        return False

    def update_tickers(self):
        """Draw the text on each screen's button; True if placed somewhere (a
        watcher that isn't the one drawing assumes it is)."""
        if not self.leader():
            return True
        _border, colour = theme_colours()
        if self.hovered:  # Wayle brightens a hovered button
            colour = tuple(min(255, round(c * 1.15)) for c in colour)
        moving = self.playing or self.hovered
        display = Gdk.Display.get_default()
        placed = False
        for mon in self.screens():
            name, mx, my, _mw = mon
            found = self.button_on(mon, max_age=2.0)
            ticker = self.tickers.get(name)
            if not found:
                if ticker:
                    ticker.stop()
                continue
            if not ticker:
                gdk_mon = None
                for i in range(display.get_n_monitors()):
                    g = display.get_monitor(i).get_geometry()
                    if (g.x, g.y) == (mx, my):
                        gdk_mon = display.get_monitor(i)
                if not gdk_mon:
                    continue
                ticker = self.tickers[name] = Ticker(gdk_mon)
            ticker.place(found[0], mx)
            ticker.run(self.text, colour, moving)
            placed = True
        return placed


def main():
    parent = os.getppid()
    Button()

    def check_parent():
        if os.getppid() != parent:
            Gtk.main_quit()
            return False
        return True

    GLib.timeout_add_seconds(2, check_parent)
    try:
        Gtk.main()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
