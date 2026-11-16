#!/usr/bin/env python3
"""Vertical volume / microphone / brightness indicator in Wayle's style.

Wayle's own indicator is horizontal only (its layout is fixed in code), so it's
turned off in ~/.config/wayle/config.toml and this one runs instead
(autostarted by hyprland.lua), upright like HyprPanel's was. When the default
speaker's or microphone's volume or mute changes (pactl subscribe) or the
screen brightness does (udev), a panel appears at the focused screen's right
edge, at the middle of the screen: the value on top,
a bar filling upwards, the icon at the bottom. Over 100% the bar shows the part
above 100 in red, as in HyprPanel. Hides after 2.5 s; clicks go through it.

Looks like Wayle's indicator and dropdowns: its panel colours (from the
palette ~/.scripts/theme-set writes to ~/.config/wayle/theme.toml, read on
every show, so theme changes apply), its 8 px rounded bar and its icons.
"""
import glob
import json
import os
import re
import subprocess
import sys
import threading
import tomllib

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell  # noqa: E402

PIDFILE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "osd.pid")
DURATION = 2500  # ms
RIGHT = 12  # gap to the screen's right edge
SHADOW = 12  # room around the panel for its shadow (part of the window)
WAYLE_THEME = os.path.expanduser("~/.config/wayle/theme.toml")
PALETTE = {  # Wayle's Catppuccin Mocha, if theme.toml is missing
    "surface": "#181825", "elevated": "#1e1e2e", "fg": "#cdd6f4",
    "fg-muted": "#bac2de", "primary": "#b4befe", "red": "#f38ba8",
}
# Wayle's icons (lucide), as in its own indicator.
ICON_DIRS = [os.path.expanduser("~/.local/share/wayle/icons"), "/usr/share/wayle/icons"]
ICONS = {
    "brightness": "ld-sun-symbolic",
    "speaker": "ld-volume-2-symbolic", "speaker-muted": "ld-volume-x-symbolic",
    "microphone": "ld-mic-symbolic", "microphone-muted": "ld-mic-off-symbolic",
}

# Wayle's indicator/dropdown look: the elevated panel with a border, 12.6px
# corners and the dropdowns' shadow; bold value; 8px bar, accent on a faint
# track; accent icon.
CSS = """
* { font-family: "Noto Sans"; }
window { background: transparent; }
.osd {
  background: @ELEVATED@; border: 1px solid @BORDER@; border-radius: 12.6px;
  box-shadow: 0 0 5px rgba(0, 0, 0, 0.3), 0 4px 10px rgba(0, 0, 0, 0.3);
  margin: 12px; padding: 12px 0 11px 0; min-width: 52px;
}
.osd-value { font-size: 13.5px; font-weight: 700; color: @FG@; margin-bottom: 11px; }
.osd-bar trough { min-width: 8px; min-height: 150px; padding: 0; border: none;
                  border-radius: 4px; background: @TRACK@; }
.osd-bar block { border: none; border-radius: 4px; min-width: 8px; min-height: 0; }
.osd-bar block.empty { background: transparent; }
.osd-bar block.filled { background: @ACCENT@; }
.osd-bar.overflow trough { background: @ACCENT@; }
.osd-bar.overflow block.filled { background: @RED@; }
.osd-icon { color: @ACCENT@; margin-top: 12px; }
.osd-icon.muted { color: @FG_MUTED@; }
"""


def rgb(colour):
    colour = colour.lstrip("#")
    return tuple(int(colour[i:i + 2], 16) for i in (0, 2, 4))


def mix(a, b, amount):
    """CSS color-mix(in srgb, a, b amount)."""
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * amount) for x, y in zip(rgb(a), rgb(b)))


def colours():
    p = dict(PALETTE)
    try:
        with open(WAYLE_THEME, "rb") as f:
            p.update(tomllib.load(f).get("styling", {}).get("palette", {}))
    except (OSError, ValueError):
        pass
    return {
        "ELEVATED": p["elevated"], "FG": p["fg"], "FG_MUTED": p["fg-muted"],
        "ACCENT": p["primary"], "RED": p["red"],
        "BORDER": mix(p["elevated"], p["fg"], 0.10),  # Wayle's --border-default
        "TRACK": mix(p["elevated"], p["fg"], 0.18),   # its indicator's empty track
    }


def audio_state(kind):
    """(volume 0..1.5, muted) of the default sink or source, or None."""
    upper = "SINK" if kind == "sink" else "SOURCE"
    try:
        vol = subprocess.run(["pactl", f"get-{kind}-volume", f"@DEFAULT_{upper}@"],
                             capture_output=True, text=True, timeout=2).stdout
        mute = subprocess.run(["pactl", f"get-{kind}-mute", f"@DEFAULT_{upper}@"],
                              capture_output=True, text=True, timeout=2).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"(\d+)%", vol)
    if not m:
        return None
    return int(m.group(1)) / 100, "yes" in mute


def brightness():
    for dev in sorted(glob.glob("/sys/class/backlight/*")):
        try:
            with open(os.path.join(dev, "brightness")) as f:
                value = int(f.read())
            with open(os.path.join(dev, "max_brightness")) as f:
                top = int(f.read())
        except (OSError, ValueError):
            continue
        if top > 0:
            return value / top
    return None


def focused_monitor():
    """(GdkMonitor, Hyprland monitor info) of the focused screen, or None."""
    try:
        out = subprocess.run(["hyprctl", "monitors", "-j"], capture_output=True, text=True,
                             timeout=2).stdout
        mon = next(m for m in json.loads(out) if m.get("focused"))
    except (OSError, ValueError, StopIteration, subprocess.TimeoutExpired):
        return None
    display = Gdk.Display.get_default()
    for i in range(display.get_n_monitors()):
        g = display.get_monitor(i).get_geometry()
        if (g.x, g.y) == (mon["x"], mon["y"]):
            return display.get_monitor(i), mon
    return None


class Osd(Gtk.Window):
    def __init__(self):
        super().__init__()
        self.provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), self.provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)
        self.css = None
        theme = Gtk.IconTheme.get_default()
        for path in ICON_DIRS:
            theme.append_search_path(path)
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "indicator")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        # Placed by hand (place()): from the screen's top right corner.
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, True)
        GtkLayerShell.set_exclusive_zone(self, -1)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.get_style_context().add_class("osd")
        self.label = Gtk.Label()
        self.label.get_style_context().add_class("osd-value")
        self.bar = Gtk.LevelBar(orientation=Gtk.Orientation.VERTICAL)
        self.bar.set_inverted(True)  # fills upwards
        self.bar.set_halign(Gtk.Align.CENTER)
        for name in ("low", "high", "full"):
            self.bar.remove_offset_value(name)
        self.bar.get_style_context().add_class("osd-bar")
        self.icon = Gtk.Image()
        self.icon.get_style_context().add_class("osd-icon")
        for part in (self.label, self.bar, self.icon):
            box.add(part)
        self.add(box)
        box.show_all()
        self.hide_timer = None
        self.connect("realize", lambda *_: self.click_through())

    def click_through(self):
        import cairo
        self.input_shape_combine_region(cairo.Region())

    def place(self):
        """On the focused screen, at the middle of its right edge."""
        found = focused_monitor()
        if not found:
            return
        gdk_monitor, mon = found
        GtkLayerShell.set_monitor(self, gdk_monitor)
        scale = mon.get("scale", 1) or 1
        height = round(mon["height"] / scale)
        right = mon.get("reserved", [0, 0, 0, 0])[2]
        _min, natural = self.get_preferred_height()
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, max(0, round((height - natural) / 2)))
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.RIGHT, max(0, right + RIGHT - SHADOW))

    def show_value(self, icon, value):
        css = CSS
        for name, colour in colours().items():
            css = css.replace(f"@{name}@", colour)
        if css != self.css:
            self.provider.load_from_data(css.encode())
            self.css = css
        over = value > 1.005
        ctx = self.bar.get_style_context()
        (ctx.add_class if over else ctx.remove_class)("overflow")
        self.label.set_text(f"{round(value * 100)}%")
        self.bar.set_value(min(1.0, value - 1 if over else value))
        self.icon.set_from_icon_name(ICONS[icon], Gtk.IconSize.BUTTON)
        self.icon.set_pixel_size(22)
        ctx = self.icon.get_style_context()
        (ctx.add_class if icon.endswith("muted") else ctx.remove_class)("muted")
        if not self.get_visible():
            self.place()
            self.show()
        if self.hide_timer:
            GLib.source_remove(self.hide_timer)
        self.hide_timer = GLib.timeout_add(DURATION, self.hide_now)
        return False

    def hide_now(self):
        self.hide_timer = None
        self.hide()
        return False


def watch_audio(osd):
    """Show on volume/mute changes of the default speaker or microphone."""
    last = {kind: audio_state(kind) for kind in ("sink", "source")}
    while True:
        proc = subprocess.Popen(["pactl", "subscribe"], stdout=subprocess.PIPE, text=True)
        for line in proc.stdout:
            if "'change' on server" in line:
                # Another default device: remember its state, don't show.
                last = {kind: audio_state(kind) for kind in ("sink", "source")}
                continue
            m = re.search(r"'change' on (sink|source) #", line)
            if not m:
                continue
            kind = m.group(1)
            state = audio_state(kind)
            if state is None or state == last[kind]:
                continue
            last[kind] = state
            volume, muted = state
            name = "speaker" if kind == "sink" else "microphone"
            GLib.idle_add(osd.show_value, f"{name}-muted" if muted else name, volume)
        proc.wait()


def watch_brightness(osd):
    last = brightness()
    while True:
        proc = subprocess.Popen(["udevadm", "monitor", "--udev", "--subsystem-match=backlight"],
                                stdout=subprocess.PIPE, text=True)
        for line in proc.stdout:
            if not line.startswith("UDEV") or " change " not in line:
                continue
            value = brightness()
            if value is None or value == last:
                continue
            last = value
            GLib.idle_add(osd.show_value, "brightness", value)
        proc.wait()


def main():
    try:
        with open(PIDFILE) as f:
            os.kill(int(f.read().strip()), 0)
        return 0  # already running
    except (OSError, ValueError):
        pass
    with open(PIDFILE, "w") as f:
        f.write(str(os.getpid()))
    try:
        osd = Osd()
        for watch in (watch_audio, watch_brightness):
            threading.Thread(target=watch, args=(osd,), daemon=True).start()
        Gtk.main()
    finally:
        try:
            with open(PIDFILE) as f:
                if f.read().strip() == str(os.getpid()):
                    os.remove(PIDFILE)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
