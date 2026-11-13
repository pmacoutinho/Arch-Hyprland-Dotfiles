#!/usr/bin/env python3
"""Omarchy-style carousel picker for themes and wallpapers.

    theme-menu.py              pick a theme       (SUPER+CTRL+T)
    theme-menu.py --backgrounds pick a wallpaper for the current theme (SUPER+CTRL+SPACE)

Modelled on Omarchy's image picker (shell/plugins/image-picker/ImagePicker.qml):
the selected preview is shown large in the middle with its name underneath,
the others as dimmed, slanted slices either side. Left/Right (or h/l, Tab,
scroll) move, Enter or a click on the selected preview applies, typing
filters, Esc or a click outside closes. Running it again closes it.
Previews are each theme's chosen wallpaper (or a preview.png in its folder).
"""
import hashlib
import json
import math
import os
import signal
import subprocess
import sys
import tomllib

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, GtkLayerShell, Pango, PangoCairo  # noqa: E402

HOME = os.path.expanduser("~")
THEMES = os.path.join(HOME, ".config/themes")
STATE = os.path.join(HOME, ".local/state/theme")
THEME_SET = os.path.join(HOME, ".scripts/theme-set")
CACHE = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.join(HOME, ".cache")), "theme-menu")
PIDFILE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "theme-menu.pid")
IMAGE_EXT = (".png", ".jpg", ".jpeg")

# Omarchy's carousel, made smaller and rounded to match HyprPanel.
EXPANDED_W, EXPANDED_H = 560, 340
SLICE_W, SLICE_H = 52, 290
SLICE_SPACING = 10
STEP = SLICE_W + SLICE_SPACING
SIDE = 6               # slices shown on each side; they fade out towards the ends
RADIUS = 14            # preview corners (slices: SLICE_RADIUS)
SLICE_RADIUS = 12
TOP_MARGIN = 0
LABEL_GAP = 14
LABEL_SIZE = 15
FILTER_SIZE = 13
PILL_PAD_X, PILL_PAD_Y = 16, 7
BORDER = 2
UNSELECTED_DIM = 0.45
FONT = "sans Medium"


# --- data ------------------------------------------------------------------

def load_toml(path):
    with open(path, "rb") as f:
        return tomllib.load(f)


def hex_rgb(colour):
    colour = colour.lstrip("#")
    return tuple(int(colour[i:i + 2], 16) / 255 for i in (0, 2, 4))


def current_theme():
    return os.path.basename(os.path.realpath(os.path.join(STATE, "current")))


def palette():
    try:
        p = load_toml(os.path.join(STATE, "current", "colors.toml"))
    except OSError:
        p = {}
    return {
        "dim": hex_rgb(p.get("background", "#191724")),
        "text": hex_rgb(p.get("foreground", "#e0def4")),
        "selected": hex_rgb(p.get("accent", "#c4a7e7")),
        "unselected": hex_rgb(p.get("selection", "#403d52")),
    }


def theme_backgrounds(meta):
    folder = os.path.expanduser(meta.get("backgrounds", ""))
    try:
        return sorted(os.path.join(folder, f) for f in os.listdir(folder)
                      if f.lower().endswith(IMAGE_EXT))
    except OSError:
        return []


def theme_preview(name, meta):
    for ext in IMAGE_EXT:
        path = os.path.join(THEMES, name, "preview" + ext)
        if os.path.isfile(path):
            return path
    files = theme_backgrounds(meta)
    try:
        with open(os.path.join(STATE, "backgrounds.json")) as f:
            chosen = json.load(f).get(name)
        if chosen in files:
            return chosen
    except (OSError, ValueError):
        pass
    default = meta.get("background")
    if default:
        path = os.path.join(os.path.expanduser(meta["backgrounds"]), default)
        if path in files:
            return path
    return files[0] if files else None


def theme_items():
    items = []
    for name in sorted(os.listdir(THEMES)):
        try:
            meta = load_toml(os.path.join(THEMES, name, "theme.toml"))
        except OSError:
            continue
        items.append({"label": meta.get("name", name), "image": theme_preview(name, meta),
                      "value": name, "last": meta.get("last", False)})
    # Default first, the rest alphabetically, like Omarchy lists stock themes;
    # themes marked `last = true` (the monochrome ones) at the end.
    items.sort(key=lambda i: (i["value"] != "default", i["last"], i["label"].lower()))
    current = current_theme()
    selected = next((n for n, i in enumerate(items) if i["value"] == current), 0)
    return items, selected


def background_items():
    meta = load_toml(os.path.join(STATE, "current", "theme.toml"))
    current = os.path.realpath(os.path.join(STATE, "background"))
    items = []
    for path in theme_backgrounds(meta):
        stem = os.path.splitext(os.path.basename(path))[0]
        words = stem.split("-")
        if words[0].isdigit():
            words = words[1:]
        label = " ".join(words).replace("_", " ").title() or stem
        items.append({"label": label, "image": path, "value": path})
    selected = next((n for n, i in enumerate(items) if os.path.realpath(i["value"]) == current), 0)
    return items, selected


def thumbnail(path):
    """Cover-cropped EXPANDED_W x EXPANDED_H preview, cached on disk."""
    if not path:
        return None
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    key = hashlib.sha1(f"{path}:{mtime}:{EXPANDED_W}x{EXPANDED_H}".encode()).hexdigest()
    cached = os.path.join(CACHE, key + ".png")
    if os.path.exists(cached):
        return GdkPixbuf.Pixbuf.new_from_file(cached)
    try:
        info, w, h = GdkPixbuf.Pixbuf.get_file_info(path)
        scale = max(EXPANDED_W / w, EXPANDED_H / h)
        sw, sh = math.ceil(w * scale), math.ceil(h * scale)
        full = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, sw, sh, False)
        pix = full.new_subpixbuf((sw - EXPANDED_W) // 2, (sh - EXPANDED_H) // 2,
                                 EXPANDED_W, EXPANDED_H).copy()
        os.makedirs(CACHE, exist_ok=True)
        pix.savev(cached, "png", [], [])
        return pix
    except GLib.Error:
        return None


# --- window ----------------------------------------------------------------

class Picker(Gtk.Window):
    def __init__(self, items, selected, on_pick):
        super().__init__()
        self.all_items = items
        for item in items:
            item["pixbuf"] = thumbnail(item["image"])
            item["rect"] = None
        self.filter = ""
        self.visible_items = list(items)
        self.selected = selected
        self.on_pick = on_pick
        self.colours = palette()
        self.card = (0, 0, 0, 0)

        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "theme-menu")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_exclusive_zone(self, -1)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                     GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, edge, True)
        self.place_on_cursor_monitor()

        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)

        area = Gtk.DrawingArea()
        area.connect("draw", self.on_draw)
        self.add(area)
        self.area = area
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.SCROLL_MASK
                        | Gdk.EventMask.SMOOTH_SCROLL_MASK)
        self.connect("button-press-event", self.on_click)
        self.connect("scroll-event", self.on_scroll)
        self.connect("key-press-event", self.on_key)
        self.connect("destroy", Gtk.main_quit)
        self.add_tick_callback(self.on_tick)

    def place_on_cursor_monitor(self):
        try:
            cx, cy = (int(v) for v in subprocess.run(
                ["hyprctl", "cursorpos"], capture_output=True, text=True, timeout=2).stdout.split(","))
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return
        display = Gdk.Display.get_default()
        monitor = display.get_monitor_at_point(cx, cy)
        if monitor:
            GtkLayerShell.set_monitor(self, monitor)

    # layout

    def targets(self, width, height):
        """Target rect (x, y, w, h) of every visible item, and the card rect."""
        carousel_w = EXPANDED_W + 2 * (SIDE * STEP + SLICE_SPACING)
        card_w = min(width - 80, carousel_w + 40)
        bottom = LABEL_GAP + LABEL_SIZE + 2 * PILL_PAD_Y + (FILTER_SIZE + 2 * PILL_PAD_Y + 8 if self.filter else 0)
        card_h = TOP_MARGIN + EXPANDED_H + bottom
        card_x, card_y = (width - card_w) / 2, (height - card_h) / 2
        preview_x = (width - EXPANDED_W) / 2
        top = card_y + TOP_MARGIN
        rects = {}
        for n, item in enumerate(self.visible_items):
            d = n - self.selected
            if d == 0:
                rects[id(item)] = (preview_x, top, EXPANDED_W, EXPANDED_H)
                continue
            if d < 0:
                x = preview_x + d * STEP
            else:
                x = preview_x + EXPANDED_W + SLICE_SPACING + (d - 1) * STEP
            y = top + (EXPANDED_H - SLICE_H) / 2
            rects[id(item)] = (x, y, SLICE_W, SLICE_H)
        return rects, (card_x, card_y, card_w, card_h)

    def on_tick(self, widget, clock):
        alloc = self.get_allocation()
        rects, self.card = self.targets(alloc.width, alloc.height)
        moving = False
        for item in self.visible_items:
            target = rects[id(item)]
            if item["rect"] is None:
                item["rect"] = target
                continue
            new = tuple(c + (t - c) * 0.28 for c, t in zip(item["rect"], target))
            if any(abs(t - c) > 0.5 for c, t in zip(new, target)):
                moving = True
                item["rect"] = new
            else:
                item["rect"] = target
        if moving or not getattr(self, "_drawn", False):
            self.area.queue_draw()
        return GLib.SOURCE_CONTINUE

    # drawing

    @staticmethod
    def shape(cr, x, y, w, h, r):
        r = min(r, w / 2, h / 2)
        cr.new_path()
        cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()

    def fade(self, n):
        """Slices fade out towards the ends of the carousel."""
        d = abs(n - self.selected)
        return 1.0 if d <= SIDE - 2 else max(0.0, 1 - (d - SIDE + 2) / 3)

    def draw_item(self, cr, item, selected, alpha):
        x, y, w, h = item["rect"]
        # Animated: the corners follow the size between slice and preview.
        r = SLICE_RADIUS + (RADIUS - SLICE_RADIUS) * max(0.0, min(1.0, (w - SLICE_W) / (EXPANDED_W - SLICE_W)))
        dim, sel = self.colours["dim"], self.colours["selected"]
        cr.push_group()
        cr.save()
        self.shape(cr, x, y, w, h, r)
        cr.clip()
        pix = item["pixbuf"]
        if pix:
            # The preview stays full size and centred on the item: a slice
            # shows the middle strip of it, like Omarchy.
            Gdk.cairo_set_source_pixbuf(cr, pix, x + w / 2 - EXPANDED_W / 2, y + h / 2 - EXPANDED_H / 2)
            cr.paint()
        else:
            cr.set_source_rgb(*dim)
            cr.paint()
        if not selected:
            cr.set_source_rgba(*dim, UNSELECTED_DIM)
            cr.paint()
        cr.restore()
        if selected:
            # Border inside the edge, so it doesn't grow the rounded shape.
            i = BORDER / 2
            self.shape(cr, x + i, y + i, w - BORDER, h - BORDER, r - i)
            cr.set_line_width(BORDER)
            cr.set_source_rgb(*sel)
            cr.stroke()
        cr.pop_group_to_source()
        cr.paint_with_alpha(alpha)

    def draw_text(self, cr, text, size, y, alpha=1.0):
        """Text in a rounded pill of the theme background (like HyprPanel's
        bar buttons); returns the pill height."""
        layout = PangoCairo.create_layout(cr)
        font = Pango.FontDescription.from_string(FONT)
        font.set_absolute_size(size * Pango.SCALE)
        layout.set_font_description(font)
        layout.set_text(text, -1)
        layout.set_width((EXPANDED_W - 2 * PILL_PAD_X) * Pango.SCALE)
        layout.set_ellipsize(Pango.EllipsizeMode.END)
        _, logical = layout.get_pixel_extents()
        tw, th = logical.width, logical.height
        pw, ph = tw + 2 * PILL_PAD_X, th + 2 * PILL_PAD_Y
        alloc = self.get_allocation()
        px = (alloc.width - pw) / 2
        self.shape(cr, px, y, pw, ph, ph / 2)
        cr.set_source_rgba(*self.colours["dim"], 0.9 * alpha)
        cr.fill()
        cr.move_to(px + PILL_PAD_X - logical.x, y + PILL_PAD_Y)
        cr.set_source_rgba(*self.colours["text"], alpha)
        PangoCairo.show_layout(cr, layout)
        return ph

    def on_draw(self, widget, cr):
        self._drawn = True
        if not self.visible_items:
            card_x, card_y, card_w, card_h = self.card
            self.draw_text(cr, f"No match for “{self.filter}”", LABEL_SIZE, card_y + card_h / 2)
            return
        # Furthest slices first, so nearer ones (and the selected) overlap them.
        order = sorted(range(len(self.visible_items)), key=lambda n: -abs(n - self.selected))
        for n in order:
            item = self.visible_items[n]
            alpha = self.fade(n)
            if item["rect"] and alpha > 0:
                self.draw_item(cr, item, n == self.selected, alpha)
        card_x, card_y, card_w, card_h = self.card
        label_y = card_y + TOP_MARGIN + EXPANDED_H + LABEL_GAP
        ph = self.draw_text(cr, self.visible_items[self.selected]["label"], LABEL_SIZE, label_y)
        if self.filter:
            self.draw_text(cr, f"/ {self.filter}", FILTER_SIZE, label_y + ph + 8, 0.85)

    # input

    def move(self, delta):
        if self.visible_items:
            self.selected = max(0, min(len(self.visible_items) - 1, self.selected + delta))

    def refilter(self):
        current = self.visible_items[self.selected] if self.visible_items else None
        needle = self.filter.lower()
        self.visible_items = [i for i in self.all_items if needle in i["label"].lower()]
        if current in self.visible_items:
            self.selected = self.visible_items.index(current)
        else:
            self.selected = 0
        for item in self.all_items:
            if item not in self.visible_items:
                item["rect"] = None

    def pick(self):
        if self.visible_items:
            value = self.visible_items[self.selected]["value"]
            self.destroy()
            self.on_pick(value)

    def on_key(self, widget, event):
        key = event.keyval
        if key == Gdk.KEY_Escape:
            self.destroy()
        elif key in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.pick()
        elif key in (Gdk.KEY_Left, Gdk.KEY_ISO_Left_Tab, Gdk.KEY_Up):
            self.move(-1)
        elif key in (Gdk.KEY_Right, Gdk.KEY_Tab, Gdk.KEY_Down):
            self.move(1)
        elif key == Gdk.KEY_Home:
            self.selected = 0
        elif key == Gdk.KEY_End:
            self.selected = max(0, len(self.visible_items) - 1)
        elif key == Gdk.KEY_BackSpace:
            if self.filter:
                self.filter = self.filter[:-1]
                self.refilter()
        elif key in (Gdk.KEY_h, Gdk.KEY_l) and not self.filter:
            self.move(-1 if key == Gdk.KEY_h else 1)
        else:
            char = chr(Gdk.keyval_to_unicode(key)) if Gdk.keyval_to_unicode(key) else ""
            if char.isprintable() and char:
                self.filter += char
                self.refilter()
        self.area.queue_draw()
        return True

    def on_scroll(self, widget, event):
        if event.direction in (Gdk.ScrollDirection.UP, Gdk.ScrollDirection.LEFT):
            self.move(-1)
        elif event.direction in (Gdk.ScrollDirection.DOWN, Gdk.ScrollDirection.RIGHT):
            self.move(1)
        elif event.direction == Gdk.ScrollDirection.SMOOTH:
            dx, dy = event.delta_x, event.delta_y
            delta = dy if abs(dy) >= abs(dx) else dx
            if abs(delta) >= 0.5:
                self.move(1 if delta > 0 else -1)
        return True

    def on_click(self, widget, event):
        if event.button != Gdk.BUTTON_PRIMARY:
            return True
        # Topmost (nearest) items first.
        order = sorted(range(len(self.visible_items)), key=lambda n: abs(n - self.selected))
        for n in order:
            rect = self.visible_items[n]["rect"]
            if not rect:
                continue
            x, y, w, h = rect
            if self.fade(n) > 0 and y <= event.y <= y + h:
                if x <= event.x <= x + w:
                    if n == self.selected:
                        self.pick()
                    else:
                        self.selected = n
                    return True
        cx, cy, cw, ch = self.card
        if not (cx <= event.x <= cx + cw and cy <= event.y <= cy + ch):
            self.destroy()
        return True


def toggle_existing():
    try:
        with open(PIDFILE) as f:
            os.kill(int(f.read().strip()), signal.SIGTERM)
        return True
    except (OSError, ValueError):
        return False


def main():
    backgrounds = "--backgrounds" in sys.argv[1:]
    if toggle_existing():
        return 0
    with open(PIDFILE, "w") as f:
        f.write(str(os.getpid()))
    try:
        if backgrounds:
            items, selected = background_items()

            def on_pick(value):
                subprocess.Popen([THEME_SET, "--background", value], start_new_session=True)
        else:
            items, selected = theme_items()

            def on_pick(value):
                subprocess.Popen([THEME_SET, value], start_new_session=True)
        if not items:
            subprocess.run(["notify-send", "-a", "Theme", "Theme",
                            "No wallpapers for this theme: run theme-install-backgrounds"])
            return 1
        try:
            gi.require_version("GLibUnix", "2.0")
            from gi.repository import GLibUnix
            add_signal = GLibUnix.signal_add
        except (ImportError, ValueError):
            add_signal = GLib.unix_signal_add
        add_signal(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: Gtk.main_quit() or False)
        Picker(items, selected, on_pick).show_all()
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
