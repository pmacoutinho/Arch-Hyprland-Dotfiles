#!/usr/bin/env python3
"""Backdrop behind the (transparent) bar while an app fills the screen.

The bar (Wayle, or HyprPanel: ~/.scripts/bar-switch) is transparent. When the
focused workspace of a monitor has a window filling it (fullscreen/maximised,
or a tiled window covering the whole area under the bar), this paints the bar's
strip to continue that app upwards: for kitty, the theme's kitty background at
kitty's background_opacity (times the window's opacity rule); for other apps,
the colour of their own top row (e.g. Firefox's tab strip), sampled from the
screen just under the bar. It's a layer-shell strip just under the bar: no
window can be under it, and it takes no clicks.

The on-screen keyboard (wvkbd, onScreenKeyboard.sh) has a transparent
background: while it's open, a second strip under it continues the screen the
same way, following workspace switches live (wvkbd can't change colours while
running): the bar strip's colour, or kitty's when no app fills the screen.

Started at login from hyprland.lua; theme-set sends it SIGUSR1 to re-read the
colour. Listens to Hyprland's event socket.
"""
import json
import os
import re
import signal
import socket
import subprocess
import threading

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell  # noqa: E402

HOME = os.path.expanduser("~")
THEME_KITTY = os.path.join(HOME, ".local/state/theme/current/kitty.conf")
KITTY_CONF = os.path.join(HOME, ".config/kitty/kitty.conf")
CACHE = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.join(HOME, ".cache")), "bar-backdrop.json")
EVENTS = {"workspace", "workspacev2", "focusedmon", "focusedmonv2", "activewindowv2",
          "openwindow", "closewindow", "movewindow", "movewindowv2", "fullscreen",
          "changefloatingmode", "monitoradded", "monitoraddedv2", "monitorremoved",
          "monitorremovedv2", "configreloaded", "activespecial", "activespecialv2",
          "openlayer", "closelayer"}
KEYBOARD = "wvkbd"


HYPR_DIR = os.path.join(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"), "hypr",
                        os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", ""))


def hypr_request(command):
    """Query Hyprland over its socket (much faster than spawning hyprctl)."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(2)
            sock.connect(os.path.join(HYPR_DIR, ".socket.sock"))
            sock.sendall(command.encode())
            chunks = []
            while chunk := sock.recv(65536):
                chunks.append(chunk)
        return b"".join(chunks).decode(errors="replace")
    except OSError:
        return ""


def hyprctl(what):
    try:
        return json.loads(hypr_request(f"j/{what}"))
    except ValueError:
        return None


def kitty_colour():
    """(r, g, b) of the theme's kitty background, and kitty's background_opacity."""
    colour, opacity = (0x19, 0x17, 0x24), 1.0
    try:
        with open(THEME_KITTY) as f:
            m = re.search(r"(?m)^background\s+#([0-9a-fA-F]{6})", f.read())
        if m:
            colour = tuple(int(m.group(1)[i:i + 2], 16) for i in (0, 2, 4))
    except OSError:
        pass
    try:
        with open(KITTY_CONF) as f:
            m = re.search(r"(?m)^background_opacity\s+([0-9.]+)", f.read())
        if m:
            opacity = float(m.group(1))
    except OSError:
        pass
    return colour, opacity


def window_opacity(client, kitty_opacity):
    try:
        opacity = float(hypr_request(f"getprop address:{client['address']} opacity").split()[0])
    except (ValueError, IndexError):
        opacity = 1.0
    if client.get("class") == "kitty":
        opacity *= kitty_opacity
    return opacity


def sample_top_colour(window):
    """Most common colour of the right quarter of the window's top pixel row,
    from the screen: the header's background. (The whole row isn't safe: in
    Nautilus the path bar can be wider than the header around it.)"""
    x, y = window["at"]
    width = window["size"][0] // 4
    x += window["size"][0] - width
    try:
        ppm = subprocess.run(["grim", "-s", "1", "-t", "ppm", "-g", f"{x},{y + 1} {width}x1", "-"],
                             capture_output=True, timeout=2).stdout
        _magic, _size, _maxval, data = ppm.split(b"\n", 3)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    pixels = [tuple(data[i:i + 3]) for i in range(0, len(data) - 2, 3)]
    if not pixels:
        return None
    colour = max(set(pixels), key=pixels.count)
    return tuple(c / 255 for c in colour) + (1.0,)


def filling_window(monitor, clients):
    """The window filling the monitor's focused workspace, if any."""
    workspace = monitor["activeWorkspace"]["id"]
    special = monitor.get("specialWorkspace", {}).get("id")
    left, top, right, bottom = monitor.get("reserved", [0, 0, 0, 0])
    scale = monitor.get("scale", 1) or 1
    width, height = round(monitor["width"] / scale), round(monitor["height"] / scale)
    area = (monitor["x"] + left, monitor["y"] + top, width - left - right, height - top - bottom)
    for client in clients:
        ws = client.get("workspace", {}).get("id")
        if ws not in (workspace, special) or client.get("hidden") or not client.get("mapped", True):
            continue
        if client.get("fullscreen", 0) >= 1:
            return client
        if not client.get("floating") and tuple(client["at"]) + tuple(client["size"]) == area:
            return client
    return None


class Strip(Gtk.Window):
    def __init__(self, gdk_monitor, height, edge=GtkLayerShell.Edge.TOP, namespace="bar-backdrop"):
        super().__init__()
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, namespace)
        # TOP layer, under the bar: windows' blur samples the background and
        # bottom layers, so a strip there would bleed into the top rows of a
        # translucent window below it. Within a layer, later surfaces draw on
        # top, so the strip must exist before HyprPanel's bar (see
        # keep_under_bar and the autostart order in hyprland.lua).
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
        GtkLayerShell.set_monitor(self, gdk_monitor)
        # The keyboard's strip is TOP too, under wvkbd (overlay layer).
        GtkLayerShell.set_exclusive_zone(self, -1)  # sit at the very edge, over the bar's/keyboard's area
        for anchor in (edge, GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, anchor, True)
        self.set_size_request(-1, height)
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)
        self.rgba = None
        self.connect("draw", self.on_draw)
        self.show_all()
        # Clicks pass straight through.
        import cairo
        self.input_shape_combine_region(cairo.Region())

    def on_draw(self, widget, cr):
        cr.set_operator(1)  # SOURCE: replace, so "off" is fully transparent
        cr.set_source_rgba(*(self.rgba or (0, 0, 0, 0)))
        cr.paint()
        return True

    def set_colour(self, rgba):
        if rgba != self.rgba:
            self.rgba = rgba
            self.queue_draw()


def keyboard_layer():
    """(monitor name, height) of the open on-screen keyboard, or None."""
    for name, monitor in (hyprctl("layers") or {}).items():
        for level in monitor.get("levels", {}).values():
            for layer in level:
                if layer["namespace"] == KEYBOARD:
                    return name, layer["h"]
    return None


def gdk_monitor_for(m):
    display = Gdk.Display.get_default()
    return next((display.get_monitor(i) for i in range(display.get_n_monitors())
                 if display.get_monitor(i).get_model() == m["name"]
                 or (display.get_monitor(i).get_geometry().x,
                     display.get_monitor(i).get_geometry().y) == (m["x"], m["y"])), None)


class Backdrop:
    def __init__(self):
        self.strips = {}
        self.keyboard = None  # (monitor name, height, Strip) while the keyboard is open
        self.colour, self.kitty_opacity = kitty_colour()
        self.pending = False
        self.settle_pending = False
        self.sampled = {}   # window address -> sampled rgba
        # app class -> last sampled rgba, kept across restarts: instant for new windows
        try:
            with open(CACHE) as f:
                self.by_class = {k: tuple(v) for k, v in json.load(f).items()}
        except (OSError, ValueError):
            self.by_class = {}
        self.rebuild()
        threading.Thread(target=self.listen, daemon=True).start()

    def rebuild(self):
        for strip in self.strips.values():
            strip.destroy()
        self.strips = {}
        monitors = hyprctl("monitors") or []
        for m in monitors:
            gdk_monitor = gdk_monitor_for(m)
            height = m.get("reserved", [0, 0, 0, 0])[1]
            if gdk_monitor and height > 0:
                self.strips[m["name"]] = Strip(gdk_monitor, height)
        self.update()
        GLib.timeout_add(1500, self.keep_under_bar)

    def keep_under_bar(self, attempt=0):
        """If a bar was created before the strip (so it's drawn under it), hide
        and show that bar: shown again, it's created on top. Only happens when
        the strip is (re)created after the bar (e.g. a screen added or
        extended), not at login. Restarts the bar if that fails. Bars: Wayle's
        wayle-bar-<screen>, HyprPanel's bar-0, bar-1…"""
        below = []  # (namespace, screen)
        for screen, monitor in (hyprctl("layers") or {}).items():
            for level in monitor.get("levels", {}).values():
                names = [layer["namespace"] for layer in level]
                if "bar-backdrop" in names:
                    below += [(n, screen) for n in names[:names.index("bar-backdrop")]
                              if re.match(r"^(bar-\d+|wayle-bar-.+)$", n)]
        if not below:
            return False
        if attempt == 0:
            for bar, screen in below:
                if bar.startswith("wayle-bar-"):
                    for action in ("hide", "show"):
                        subprocess.run(["wayle", "panel", action, screen], capture_output=True, timeout=10)
                else:
                    for _ in range(2):  # hide, show
                        # (the hyprpanel wrapper joins its arguments into one, so call astal)
                        subprocess.run(["astal", "-i", "hyprpanel", "-t", bar], capture_output=True, timeout=10)
            GLib.timeout_add(700, self.keep_under_bar, 1)
        else:
            subprocess.run([os.path.expanduser("~/.scripts/bar-switch"), "restart"],
                           capture_output=True, timeout=20)
        return False

    def update(self):
        self.pending = False
        monitors = hyprctl("monitors") or []
        clients = hyprctl("clients") or []
        # Strips only where a bar reserves space: a screen that lost its bar
        # (e.g. extended while HyprPanel didn't know it) must lose its strip
        # too, or the strip covers the top of its windows.
        if {m["name"] for m in monitors if m.get("reserved", [0, 0])[1] > 0} != set(self.strips):
            self.rebuild()
            return False
        for m in monitors:
            strip = self.strips.get(m["name"])
            if not strip:
                continue
            window = filling_window(m, clients)
            if not window:
                strip.set_colour(None)
            elif window.get("class") == "kitty":
                alpha = window_opacity(window, self.kitty_opacity)
                strip.set_colour(tuple(c / 255 for c in self.colour) + (alpha,))
            else:
                # Use what we know right away (this window's colour, else the
                # last one of the same app), then confirm from the screen once
                # the window has settled (animations) and again a bit later.
                address = window["address"]
                known = self.sampled.get(address) or self.by_class.get(window.get("class"))
                if known:
                    strip.set_colour(known)
                # (Not before ~230ms: workspace switches fade for ~200ms.)
                for delay in (230, 900):
                    GLib.timeout_add(delay, self.resample, m["name"], address)
        self.update_keyboard(monitors)
        return False

    def update_keyboard(self, monitors=None):
        """The strip under the on-screen keyboard: the bar strip's colour on
        that screen, or kitty's background when no app fills it."""
        found = keyboard_layer()
        if self.keyboard and (not found or found != self.keyboard[:2]):
            self.keyboard[2].destroy()
            self.keyboard = None
        if not found:
            return
        name, height = found
        if not self.keyboard:
            m = next((m for m in monitors or hyprctl("monitors") or [] if m["name"] == name), None)
            gdk_monitor = gdk_monitor_for(m) if m else None
            if not gdk_monitor:
                return
            self.keyboard = (name, height, Strip(gdk_monitor, height, GtkLayerShell.Edge.BOTTOM,
                                                 "keyboard-backdrop"))
        bar = self.strips.get(name)
        colour = bar.rgba if bar and bar.rgba else tuple(c / 255 for c in self.colour) + (self.kitty_opacity,)
        self.keyboard[2].set_colour(colour)

    def remember(self, key, colour):
        """Keep an app's sampled colour across restarts (instant next time)."""
        if self.by_class.get(key) != colour:
            self.by_class[key] = colour
            try:
                os.makedirs(os.path.dirname(CACHE), exist_ok=True)
                with open(CACHE, "w") as f:
                    json.dump(self.by_class, f)
            except OSError:
                pass

    def resample(self, monitor_name, address):
        monitors = hyprctl("monitors") or []
        clients = hyprctl("clients") or []
        monitor = next((m for m in monitors if m["name"] == monitor_name), None)
        strip = self.strips.get(monitor_name)
        window = filling_window(monitor, clients) if monitor else None
        if strip and window and window["address"] == address:
            colour = sample_top_colour(window)
            if colour:
                self.sampled[address] = colour
                self.remember(window.get("class"), colour)
                strip.set_colour(colour)
                self.update_keyboard()
        return False

    def schedule(self):
        if not self.pending:
            self.pending = True
            GLib.timeout_add(10, self.update)
        # And again once the windows have their new size: e.g. switching to a
        # workspace while the on-screen keyboard is open, its windows are only
        # then resized to the smaller area, so the first look finds none
        # filling it (Hyprland sends no event for that).
        if not self.settle_pending:
            self.settle_pending = True
            GLib.timeout_add(450, self.settled)
        return False

    def settled(self):
        self.settle_pending = False
        self.update()
        return False

    def reload_colour(self):
        self.colour, self.kitty_opacity = kitty_colour()
        for strip in self.strips.values():
            strip.rgba = None
        if self.keyboard:
            self.keyboard[2].rgba = None
        self.update()
        return GLib.SOURCE_CONTINUE

    def listen(self):
        path = os.path.join(HYPR_DIR, ".socket2.sock")
        while True:
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                    sock.connect(path)
                    buf = b""
                    while chunk := sock.recv(4096):
                        buf += chunk
                        *lines, buf = buf.split(b"\n")
                        if any(line.split(b">>", 1)[0].decode(errors="ignore") in EVENTS for line in lines):
                            GLib.idle_add(self.schedule)
            except OSError:
                pass
            threading.Event().wait(2)  # Hyprland restarting: retry


PIDFILE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "bar-backdrop.pid")


def main():
    with open(PIDFILE, "w") as f:  # theme-set signals this pid
        f.write(str(os.getpid()))
    backdrop = Backdrop()
    try:
        gi.require_version("GLibUnix", "2.0")
        from gi.repository import GLibUnix
        add_signal = GLibUnix.signal_add
    except (ImportError, ValueError):
        add_signal = GLib.unix_signal_add
    add_signal(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, backdrop.reload_colour)
    add_signal(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: Gtk.main_quit() or False)
    Gtk.main()


if __name__ == "__main__":
    main()
