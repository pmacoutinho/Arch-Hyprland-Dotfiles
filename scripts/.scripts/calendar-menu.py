#!/usr/bin/env python3
"""Calendar dropdown for the bar's clock (left click), with Proton Calendar events.

Looks like Wayle's own calendar dropdown (which can't show events): the time,
the date, the month grid; plus a dot under each day with events, and below the
grid the events of the selected day (today at first), and for today the next
few upcoming ones. Clicking a day selects it; clicking an event opens Proton
Calendar in the browser. Closes on Esc, on a click outside, or when launched
again (toggle).

Events come from a Proton Calendar share link (Settings > Calendars > Share >
"Share via link", full details), kept as a secret in the local file
    ~/.config/proton-calendar/feed-url   (mode 600, never in a repo)
fetched every 15 minutes and cached in ~/.cache/proton-calendar/ (mode 600).
Without the link, it's just the calendar. Needs python-icalendar and
python-recurring-ical-events.

Runs in the background (`--daemon`, autostarted by hyprland.lua) like the VPN
menu: launching the script sends it SIGUSR1, so it opens at once.
"""
import datetime as dt
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import tomllib

RUN = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
DAEMON_PID = os.path.join(RUN, "calendar-menu-daemon.pid")

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
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell  # noqa: E402

FEED_URL = os.path.expanduser("~/.config/proton-calendar/feed-url")
CACHE_DIR = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")),
                         "proton-calendar")
CACHE = os.path.join(CACHE_DIR, "calendar.ics")
REFRESH = 15 * 60  # s
PROTON_CALENDAR = "https://calendar.proton.me/"
UPCOMING = 4  # events listed under "Upcoming" (today only)

WIDTH = 378 + 2 * 14  # Wayle's calendar dropdown, plus the margins for the shadow
TOP = 52  # the dropdowns' top edge (styles/index.scss)
SHADOW_TOP = 10
BAR_HEIGHT = 48

WAYLE_THEME = os.path.expanduser("~/.config/wayle/theme.toml")
PALETTE = {
    "surface": "#181825", "elevated": "#1e1e2e", "fg": "#cdd6f4", "fg-muted": "#bac2de",
    "primary": "#b4befe",
}
ICON_DIRS = [os.path.expanduser("~/.local/share/wayle/icons"), "/usr/share/wayle/icons"]


def rgb(colour):
    colour = colour.lstrip("#")
    return tuple(int(colour[i:i + 2], 16) for i in (0, 2, 4))


def mix(a, b, amount):
    """CSS color-mix(in srgb, a, b amount)."""
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * amount) for x, y in zip(rgb(a), rgb(b)))


def alpha(colour, amount):
    return "rgba(%d, %d, %d, %s)" % (*rgb(colour), amount)


def theme():
    """Wayle's palette, and the clock button's colours: its border (to find it
    on the bar) and its icon colour, the dropdown's accent (as Wayle's own
    dropdowns now take their button's, styles/index.scss)."""
    p, clock = dict(PALETTE), {}
    try:
        with open(WAYLE_THEME, "rb") as f:
            data = tomllib.load(f)
        p.update(data.get("styling", {}).get("palette", {}))
        clock = data.get("modules", {}).get("clock", {})
    except (OSError, ValueError):
        pass
    accent = clock.get("icon-color") or p["primary"]
    colours = {
        "SURFACE": p["surface"], "ELEVATED": p["elevated"], "FG": p["fg"],
        "FG_MUTED": p["fg-muted"], "ACCENT": accent,
        "BORDER": mix(p["elevated"], p["fg"], 0.10),
        "OVERLAY": mix(p["elevated"], p["fg"], 0.08),
        "FG_SUBTLE": alpha(p["fg"], 0.5),
        "BORDER_SUBTLE": alpha(p["fg"], 0.12),
        # Wayle's calendar: weekend headers/days in the accent over the card,
        # other months' days faint.
        "WEEKEND_HEAD": mix(p["elevated"], accent, 0.75),
        "WEEKEND": mix(p["elevated"], accent, 0.65),
        "DAY": mix(p["elevated"], p["fg"], 0.75),  # weekdays: clearer than Wayle's
        "OTHER": mix(p["elevated"], p["fg"], 0.18),
        "HEAD": mix(p["elevated"], p["fg"], 0.5),
    }
    return colours, clock.get("border-color") or accent


CSS = """
/* Wayle's calendar dropdown (its stylesheet at its 14.4px rem). */
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
  border-radius: 11.6px 11.6px 0 0; padding: 7px 14px; margin-bottom: 2px;
}
.dropdown-title { font-size: 15px; font-weight: 700; color: @FG@; }
.dropdown-title-icon { color: @ACCENT@; margin-right: 6px; }
.dropdown-content { padding: 11px; }
.time { font-size: 60px; font-weight: 300; color: @FG@; margin-top: 4px; }
.date { color: @FG_SUBTLE@; margin-bottom: 11px; }
.date-day { color: @FG@; font-weight: 700; }
.divider { border-top: 1px solid @BORDER@; margin-bottom: 11px; }
.month { font-weight: 700; color: @FG@; margin-left: 4px; }
.nav { color: @FG_MUTED@; padding: 2px 6px; border-radius: 7px; }
.nav:hover { background: @OVERLAY@; color: @FG@; }
.nav image { color: @FG_MUTED@; }
.card { background: @ELEVATED@; border-radius: 9px; }
.grid { padding: 10px 7px 8px 7px; margin-top: 9px; }
.weekday { font-size: 12.6px; font-weight: 700; color: @HEAD@; min-height: 30px; }
.weekday.weekend { color: @WEEKEND_HEAD@; }
.day { border-radius: 9px; min-height: 36px; min-width: 44px; margin: 1px 2px; }
.day:hover { background: @OVERLAY@; }
.day .num { color: @DAY@; }
.day.weekend .num { color: @WEEKEND@; font-weight: 700; }
.day.other .num { color: @OTHER@; font-weight: 500; }
.day.selected { box-shadow: inset 0 0 0 1px @ACCENT@; }
.day.today { background: @ACCENT@; }
.day.today .num { color: @SURFACE@; font-weight: 700; }
.dot { background: @ACCENT@; border-radius: 2px; min-width: 4px; min-height: 4px; margin-top: 1px; }
.day.today .dot { background: @SURFACE@; }
.dot.none { background: transparent; }
.section-label { font-size: 12.6px; font-weight: 700; color: @FG_SUBTLE@; margin: 18px 0 7px 0; }
.sep { border-top: 1px solid @BORDER_SUBTLE@; }
.event { padding: 7px 10px; border-radius: 9px; }
.event:hover { background: @OVERLAY@; }
.event-time { font-size: 12px; color: @FG_SUBTLE@; min-width: 46px; margin-right: 10px; }
.event-bar { background: @ACCENT@; border-radius: 2px; min-width: 3px; margin-right: 10px; }
.title { color: @FG@; }
.subtitle { font-size: 11.7px; color: @FG_SUBTLE@; }
.empty { color: @FG_SUBTLE@; padding: 12px; }
"""


# --- events -----------------------------------------------------------------

class Feed:
    """The calendar from the share link: fetched in the background, cached."""

    def __init__(self, on_update):
        self.on_update = on_update
        self.calendar = None
        self.fetched = 0.0
        self.lock = threading.Lock()
        self.load_cache()

    def url(self):
        try:
            with open(FEED_URL) as f:
                return f.read().strip()
        except OSError:
            return None

    def load_cache(self):
        try:
            with open(CACHE, "rb") as f:
                self.parse(f.read())
            self.fetched = os.path.getmtime(CACHE)
        except (OSError, ValueError):
            pass

    def parse(self, data):
        import icalendar
        calendar = icalendar.Calendar.from_ical(data)
        with self.lock:
            self.calendar = calendar

    def refresh(self, force=False):
        if not force and dt.datetime.now().timestamp() - self.fetched < 5 * 60:
            return
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        import urllib.request
        url = self.url()
        if not url:
            return
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "calendar-menu"})
            data = urllib.request.urlopen(req, timeout=20).read()
            self.parse(data)
        except Exception:  # offline, link revoked…: keep what we have
            return
        self.fetched = dt.datetime.now().timestamp()
        try:
            os.makedirs(CACHE_DIR, mode=0o700, exist_ok=True)
            tmp = CACHE + ".tmp"
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, CACHE)
        except OSError:
            pass
        GLib.idle_add(self.on_update)

    def events(self, start, end):
        """Events overlapping [start, end) (dates), as dicts, sorted."""
        with self.lock:
            calendar = self.calendar
        if calendar is None:
            return []
        import recurring_ical_events
        out = []
        try:
            components = recurring_ical_events.of(calendar).between(start, end)
        except Exception:
            return []
        for c in components:
            begin = c.get("DTSTART")
            if begin is None:
                continue
            begin = begin.dt
            all_day = not isinstance(begin, dt.datetime)
            if c.get("DTEND") is not None:
                finish = c.get("DTEND").dt
            elif c.get("DURATION") is not None:
                finish = begin + c.get("DURATION").dt
            else:
                finish = begin + (dt.timedelta(days=1) if all_day else dt.timedelta(0))
            if not all_day:
                begin, finish = local(begin), local(finish)
            out.append({
                "start": begin, "end": finish, "all_day": all_day,
                "title": str(c.get("SUMMARY") or "(No title)"),
                "where": str(c.get("LOCATION") or ""),
            })
        out.sort(key=lambda e: (day_of(e["start"]), not e["all_day"], sort_key(e["start"])))
        return out


def local(t):
    """Aware local datetime (naive ones are taken as local time)."""
    return t.astimezone() if t.tzinfo else t.replace(tzinfo=dt.datetime.now().astimezone().tzinfo)


def day_of(t):
    return t.date() if isinstance(t, dt.datetime) else t


def sort_key(t):
    return t.timestamp() if isinstance(t, dt.datetime) else 0


def days_covered(event):
    """The dates an event shows on (all-day ends are exclusive)."""
    first = day_of(event["start"])
    last = day_of(event["end"])
    if event["all_day"] or (isinstance(event["end"], dt.datetime) and event["end"].time() == dt.time(0)
                            and last > first):
        last -= dt.timedelta(days=1)
    last = max(first, last)
    return [first + dt.timedelta(days=i) for i in range((last - first).days + 1)]


# --- placement (as the VPN menu) ---------------------------------------------

def hyprctl(request):
    path = os.path.join(RUN, "hypr", os.environ["HYPRLAND_INSTANCE_SIGNATURE"], ".socket.sock")
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
    """Global x of the centre of the bar button under the cursor, found by its
    top border (drawn in its colour)."""
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


# --- the menu ------------------------------------------------------------------

def icon(name, size, *classes):
    image = Gtk.Image.new_from_icon_name(name, Gtk.IconSize.BUTTON)
    image.set_pixel_size(size)
    for c in classes:
        image.get_style_context().add_class(c)
    return image


def label(text, *classes, **kwargs):
    kwargs.setdefault("xalign", 0)
    widget = Gtk.Label(label=text, **kwargs)
    for c in classes:
        widget.get_style_context().add_class(c)
    return widget


class Menu(Gtk.Window):
    def __init__(self):
        super().__init__()
        self.provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), self.provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)
        theme_icons = Gtk.IconTheme.get_default()
        for path in ICON_DIRS:
            theme_icons.append_search_path(path)

        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "calendar-menu")
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

        backdrop = Gtk.EventBox()
        backdrop.get_style_context().add_class("backdrop")
        backdrop.connect("button-press-event", lambda *_: self.close_menu())
        self.add(backdrop)
        self.backdrop = backdrop
        self.holder = None
        self.ticker = None
        self.connect("key-press-event", self.on_key)
        self.connect("destroy", Gtk.main_quit)

        self.feed = Feed(self.on_feed_update)
        self.feed.refresh(force=True)
        GLib.timeout_add_seconds(REFRESH, lambda: self.feed.refresh(force=True) or True)

    # open / close

    def toggle(self):
        if self.get_visible():
            self.close_menu()
        else:
            self.open()

    def open(self):
        pos = cursor_position()
        colours, clock = theme()
        css = CSS
        for name, value in colours.items():
            css = css.replace(f"@{name}@", value)
        self.provider.load_from_data(css.encode())
        center = None
        if pos:
            center = module_center(pos[0], pos[1], pos[2], rgb(clock))
        today = dt.date.today()
        self.month = today.replace(day=1)
        self.selected = today
        self.build(pos, center)
        self.show_all()
        self.feed.refresh()
        self.ticker = GLib.timeout_add(1000, self.tick)

    def close_menu(self):
        if self.ticker:
            GLib.source_remove(self.ticker)
            self.ticker = None
        self.hide()
        return True

    def on_key(self, _widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.close_menu()
        return False

    def on_feed_update(self):
        if self.get_visible():
            self.fill()
        return False

    # layout

    def build(self, pos, center):
        if self.holder:
            self.holder.destroy()
        holder = self.holder = Gtk.EventBox()
        holder.connect("button-press-event", lambda *_: True)
        holder.set_halign(Gtk.Align.START)
        holder.set_valign(Gtk.Align.START)
        self.backdrop.add(holder)

        menu = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        menu.get_style_context().add_class("dropdown")
        menu.set_size_request(WIDTH, -1)  # (GTK3 counts the CSS margins in it)
        holder.add(menu)

        header = Gtk.Box()
        header.get_style_context().add_class("dropdown-header")
        header.pack_start(icon("tb-calendar-time-symbolic", 22, "dropdown-title-icon"), False, False, 0)
        header.pack_start(label("Calendar", "dropdown-title"), True, True, 0)
        menu.add(header)

        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.content.get_style_context().add_class("dropdown-content")
        menu.add(self.content)
        self.fill()

        if pos:
            cx, origin, mon_width = pos
            self.place_on_monitor(origin)
            x = (center if center is not None else cx) - origin[0]
            holder.set_margin_start(max(4, min(round(x - WIDTH / 2), mon_width - WIDTH - 4)))
        holder.set_margin_top(TOP - SHADOW_TOP)

    def place_on_monitor(self, origin):
        display = Gdk.Display.get_default()
        for i in range(display.get_n_monitors()):
            mon = display.get_monitor(i)
            g = mon.get_geometry()
            if (g.x, g.y) == origin:
                GtkLayerShell.set_monitor(self, mon)
                return

    def fill(self):
        for child in self.content.get_children():
            child.destroy()
        now = dt.datetime.now()

        self.time_label = label(now.strftime("%H:%M:%S"), "time", xalign=0.5)
        self.content.add(self.time_label)
        date = Gtk.Box(halign=Gtk.Align.CENTER)
        self.date_day = label(now.strftime("%A"), "date-day")
        self.date_rest = label(now.strftime(", %B %-d, %Y"), "date")
        self.date_day.get_style_context().add_class("date")
        date.add(self.date_day)
        date.add(self.date_rest)
        self.content.add(date)
        divider = Gtk.Box()
        divider.get_style_context().add_class("divider")
        self.content.add(divider)

        # Month row: "November 2026", Today, < >
        row = Gtk.Box()
        row.pack_start(label(self.month.strftime("%B %Y"), "month"), True, True, 0)
        today_button = Gtk.Button(label="Today")
        today_button.get_style_context().add_class("nav")
        today_button.connect("clicked", lambda *_: self.go(dt.date.today(), select=True))
        prev = Gtk.Button()
        prev.add(icon("ld-chevron-left-symbolic", 16))
        prev.get_style_context().add_class("nav")
        prev.connect("clicked", lambda *_: self.go(add_months(self.month, -1)))
        nxt = Gtk.Button()
        nxt.add(icon("ld-chevron-right-symbolic", 16))
        nxt.get_style_context().add_class("nav")
        nxt.connect("clicked", lambda *_: self.go(add_months(self.month, 1)))
        for w in (nxt, prev, today_button):
            row.pack_end(w, False, False, 2)
        self.content.add(row)

        # The grid, Sunday first like Wayle's.
        first = self.month - dt.timedelta(days=(self.month.weekday() + 1) % 7)
        last = first + dt.timedelta(days=41)
        events = self.feed.events(first, last + dt.timedelta(days=1))
        busy = {d for e in events for d in days_covered(e)}
        grid = Gtk.Grid(column_homogeneous=True)
        grid.get_style_context().add_class("card")
        grid.get_style_context().add_class("grid")
        for col, name in enumerate(("Su", "Mo", "Tu", "We", "Th", "Fr", "Sa")):
            head = label(name, "weekday", xalign=0.5)
            if col in (0, 6):
                head.get_style_context().add_class("weekend")
            grid.attach(head, col, 0, 1, 1)
        today = dt.date.today()
        for i in range(42):
            day = first + dt.timedelta(days=i)
            grid.attach(self.day_cell(day, today, day in busy), i % 7, 1 + i // 7, 1, 1)
        self.content.add(grid)

        # The selected day's events, then (today) what's next.
        day_events = [e for e in events if self.selected in days_covered(e)]
        if self.selected == today:
            heading = "Today"
        elif self.selected == today + dt.timedelta(days=1):
            heading = "Tomorrow"
        else:
            heading = self.selected.strftime("%A, %-d %B")
        self.content.add(label(heading.upper(), "section-label"))
        self.content.add(self.event_card(day_events, show_date=False))
        if self.selected == today and self.feed.calendar is not None:
            later = [e for e in self.feed.events(today + dt.timedelta(days=1), today + dt.timedelta(days=60))
                     if day_of(e["start"]) > today][:UPCOMING]
            if later:
                self.content.add(label("UPCOMING", "section-label"))
                self.content.add(self.event_card(later, show_date=True))
        self.content.show_all()

    def day_cell(self, day, today, busy):
        button = Gtk.Button()
        ctx = button.get_style_context()
        ctx.add_class("day")
        if day.month != self.month.month:
            ctx.add_class("other")
        elif day.weekday() in (5, 6):
            ctx.add_class("weekend")
        if day == today:
            ctx.add_class("today")
        if day == self.selected and day != today:
            ctx.add_class("selected")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        box.add(label(str(day.day), "num", xalign=0.5))
        dot = Gtk.Box(halign=Gtk.Align.CENTER)
        dot.get_style_context().add_class("dot")
        if not busy:
            dot.get_style_context().add_class("none")
        box.add(dot)
        button.add(box)
        button.connect("clicked", lambda *_: self.go(day.replace(day=1), select=day))
        return button

    def event_card(self, events, show_date):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        card.get_style_context().add_class("card")
        if self.feed.calendar is None:
            card.add(label("Calendar not loaded yet" if self.feed.url() else
                           "No calendar link (see calendar-menu.py)", "empty", xalign=0.5))
            return card
        if not events:
            card.add(label("No events", "empty", xalign=0.5))
            return card
        for i, event in enumerate(events):
            if i:
                sep = Gtk.Box()
                sep.get_style_context().add_class("sep")
                card.add(sep)
            card.add(self.event_row(event, show_date))
        return card

    def event_row(self, event, show_date):
        button = Gtk.Button()
        button.get_style_context().add_class("event")
        row = Gtk.Box()
        when = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        if show_date:
            when.add(label(day_of(event["start"]).strftime("%a %-d"), "event-time"))
        if event["all_day"]:
            when.add(label("All day", "event-time"))
        else:
            when.add(label(event["start"].strftime("%H:%M"), "event-time"))
            if not show_date:
                when.add(label(event["end"].strftime("%H:%M"), "event-time"))
        row.pack_start(when, False, False, 0)
        bar = Gtk.Box()
        bar.get_style_context().add_class("event-bar")
        row.pack_start(bar, False, False, 0)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        text.add(label(event["title"], "title", ellipsize=3, max_width_chars=30))
        if event["where"]:
            text.add(label(event["where"], "subtitle", ellipsize=3, max_width_chars=34))
        row.pack_start(text, True, True, 0)
        button.add(row)
        button.set_tooltip_text(event["title"])
        button.connect("clicked", lambda *_: self.open_proton())
        return button

    # actions

    def go(self, month, select=None):
        self.month = month.replace(day=1)
        if select:
            self.selected = select if isinstance(select, dt.date) else dt.date.today()
        self.fill()

    def tick(self):
        if not self.get_visible():
            self.ticker = None
            return False
        now = dt.datetime.now()
        self.time_label.set_text(now.strftime("%H:%M:%S"))
        self.date_day.set_text(now.strftime("%A"))
        self.date_rest.set_text(now.strftime(", %B %-d, %Y"))
        return True

    def open_proton(self):
        subprocess.Popen(["xdg-open", PROTON_CALENDAR], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.close_menu()


def add_months(month, n):
    y, m = divmod(month.month - 1 + n, 12)
    return month.replace(year=month.year + y, month=m + 1, day=1)


def main():
    try:
        with open(DAEMON_PID) as f:
            os.kill(int(f.read().strip()), 0)
        return 0  # already running
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
