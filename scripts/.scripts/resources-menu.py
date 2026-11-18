#!/usr/bin/env python3
"""Resources dropdown for the bar's resources group (left click on CPU, GPU or RAM).

Wayle's dashboard shows CPU, RAM and disk only as percentage rings; this one
gives the values too, like HyprPanel's dashboard did: CPU (usage, frequency,
temperature), the GPU (usage, VRAM, temperature; NVIDIA via nvidia-smi, run
only while open, or AMD), RAM (used / total GiB), each disk (used / total),
and the network speed of each connected Wi-Fi or wired link (download,
upload, and the Wi-Fi network and link rate). Updated every second while open.

CPU and RAM expand, one at a time (click the row; folded again when the menu
closes): CPU to
each thread's usage, the cores' temperatures, load average and uptime; RAM to
where it goes (apps, shared, cache, free), swap (for zram also how much it
holds in how little RAM) and the apps using the most (their PSS, so shared
pages aren't counted twice).
Looks like Wayle's dropdowns, in the button's colour. Closes on Esc, on a
click outside, or when launched again (toggle).

Runs in the background (`--daemon`, autostarted by hyprland.lua) like the
calendar and VPN menus: launching the script sends it SIGUSR1, so it opens
at once.
"""
import glob
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import tomllib

RUN = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
DAEMON_PID = os.path.join(RUN, "resources-menu-daemon.pid")

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
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, Gio, GLib, Gtk, GtkLayerShell, Pango  # noqa: E402

WIDTH = 378 + 2 * 14  # as the calendar dropdown, plus the margins for the shadow
TOP = 52  # the dropdowns' top edge (styles/index.scss)
SHADOW_TOP = 10
BAR_HEIGHT = 48
BUTTON_COLOUR = "green"  # the palette colour of the bar button (config.toml)
MOUNTS = ["/", "/home"]  # disks shown (each filesystem once)

WAYLE_THEME = os.path.expanduser("~/.config/wayle/theme.toml")
PALETTE = {
    "surface": "#181825", "elevated": "#1e1e2e", "fg": "#cdd6f4", "fg-muted": "#bac2de",
    "primary": "#b4befe", "green": "#a6e3a1",
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
    """Wayle's palette, and the button's colour: the dropdown's accent (as
    Wayle's own dropdowns take their button's, styles/index.scss) and how the
    button is found on the bar."""
    p = dict(PALETTE)
    try:
        with open(WAYLE_THEME, "rb") as f:
            p.update(tomllib.load(f).get("styling", {}).get("palette", {}))
    except (OSError, ValueError):
        pass
    accent = p.get(BUTTON_COLOUR) or p["primary"]
    colours = {
        "SURFACE": p["surface"], "ELEVATED": p["elevated"], "FG": p["fg"],
        "FG_MUTED": p["fg-muted"], "ACCENT": accent,
        "BORDER": mix(p["elevated"], p["fg"], 0.10),
        "TRACK": mix(p["elevated"], p["fg"], 0.18),
        "OVERLAY": mix(p["elevated"], p["fg"], 0.08),
        "INSET": mix(p["elevated"], p["surface"], 0.45),
        "FG_SUBTLE": alpha(p["fg"], 0.5),
        "BORDER_SUBTLE": alpha(p["fg"], 0.12),
    }
    return colours, accent


CSS = """
/* Wayle's dropdowns (its stylesheet at its 14.4px rem), as calendar-menu.py. */
* { font-family: "Noto Sans"; font-size: 13.5px; font-weight: 500; }
window, .backdrop { background: transparent; }
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
.card { background: @ELEVATED@; border-radius: 9px; padding: 12px 14px; margin-bottom: 9px; }
.card.last { margin-bottom: 0; }
.section { font-size: 12.6px; font-weight: 700; color: @FG_SUBTLE@; margin-bottom: 10px; }
.section-icon { color: @FG_SUBTLE@; margin-right: 7px; }
.item { margin-bottom: 12px; }
.item.last { margin-bottom: 0; }
.item-icon { color: @ACCENT@; margin-right: 9px; }
.name { color: @FG@; font-weight: 700; }
.value { color: @FG@; font-weight: 700; }
.percent { color: @FG_SUBTLE@; margin-left: 8px; min-width: 34px; }
.detail { font-size: 12px; color: @FG_SUBTLE@; margin-top: 5px; }
.meter trough { min-height: 6px; padding: 0; border: none; border-radius: 3px;
                background: @TRACK@; margin-top: 7px; }
.meter block { border: none; border-radius: 3px; min-height: 6px; min-width: 0; }
.meter block.empty { background: transparent; }
.meter block.filled { background: @ACCENT@; }
.speed { color: @FG@; font-weight: 700; font-size: 15px; }
.speed-icon { color: @ACCENT@; margin-right: 6px; }
.speed-label { font-size: 12px; color: @FG_SUBTLE@; margin-left: 6px; }
.sep { border-top: 1px solid @BORDER_SUBTLE@; margin: 12px 0; }
.empty { color: @FG_SUBTLE@; }
button { background: none; border: none; box-shadow: none; padding: 0; margin: 0;
         min-height: 0; min-width: 0; outline: none; }
/* Expandable rows (CPU, RAM): the row is a button, a chevron at its end. */
button.expander-row { padding: 3px 6px; margin: -3px -6px; border-radius: 7px; }
button.expander-row:hover { background: @OVERLAY@; }
.chevron { color: @FG_SUBTLE@; margin-left: 8px; }
button.expander-row:hover .chevron { color: @FG@; }
.extra { background: @INSET@; border-radius: 8px; padding: 10px 12px 11px 12px; margin-top: 10px; }
.sub-head { font-size: 11.7px; font-weight: 700; color: @FG_SUBTLE@; margin: 12px 0 6px 0; }
.sub-head.first { margin-top: 0; }
.kv { margin-top: 3px; }
.kv-key { font-size: 12.6px; color: @FG_SUBTLE@; }
.kv-value { font-size: 12.6px; color: @FG@; font-weight: 600; }
.thread-name { font-size: 11.7px; color: @FG_SUBTLE@; min-width: 18px; }
.thread-value { font-size: 11.7px; color: @FG@; font-weight: 600; min-width: 34px; }
.mini trough { min-height: 4px; padding: 0; border: none; border-radius: 2px;
               background: @TRACK@; margin: 0 8px; }
.mini block { border: none; border-radius: 2px; min-height: 4px; min-width: 0; }
.mini block.empty { background: transparent; }
.mini block.filled { background: @ACCENT@; }
.mini.swap trough { margin: 6px 0 0 0; }
"""


# --- readings ------------------------------------------------------------------

def read(path, default=None):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def cpu_times():
    """{"cpu": (idle, total), "cpu0": …, "cpu1": …} jiffies: all CPUs, each thread."""
    out = {}
    for line in read("/proc/stat", "").splitlines():
        if not line.startswith("cpu"):
            break
        name, *values = line.split()
        fields = [int(v) for v in values]
        out[name] = (fields[3] + (fields[4] if len(fields) > 4 else 0), sum(fields))
    return out


def usage_between(old, new):
    """CPU usage (0..1) between two (idle, total) readings."""
    if not old or not new or new[1] <= old[1]:
        return 0.0
    return max(0.0, 1 - (new[0] - old[0]) / (new[1] - old[1]))


def core_temps():
    """The cores' temperature files (coretemp's "Core N"), in core order."""
    for hwmon in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        if read(os.path.join(hwmon, "name")) != "coretemp":
            continue
        cores = []
        for path in glob.glob(os.path.join(hwmon, "temp*_label")):
            name = read(path, "")
            if name.startswith("Core "):
                cores.append((int(name.split()[1]), path.replace("_label", "_input")))
        return [path for _n, path in sorted(cores)]
    return []


def uptime():
    seconds = int(float(read("/proc/uptime", "0").split()[0]))
    days, rest = divmod(seconds, 86400)
    hours, minutes = rest // 3600, rest % 3600 // 60
    return (f"{days} d " if days else "") + f"{hours} h {minutes} min"


def swap_info():
    """(kind, used, total) of the first swap, kind "zram", "partition" or "file"."""
    lines = read("/proc/swaps", "").splitlines()[1:]
    if not lines:
        return None
    name, kind, size_kib, used_kib = lines[0].split()[:4]
    if os.path.basename(name).startswith("zram"):
        kind = "zram"
    return kind, int(used_kib) * 1024, int(size_kib) * 1024, name


def zram_stats(device):
    """(data stored, RAM it takes, compressor) of a zram device, or None."""
    block = os.path.join("/sys/block", os.path.basename(device))
    stats = read(os.path.join(block, "mm_stat"), "").split()
    if len(stats) < 3:
        return None
    algo = read(os.path.join(block, "comp_algorithm"), "")
    algo = next((a.strip("[]") for a in algo.split() if a.startswith("[")), "")
    return int(stats[0]), int(stats[2]), algo


PAGE = os.sysconf("SC_PAGE_SIZE")


def top_memory(count=4):
    """The apps using the most memory: [(name, bytes)], each app's processes
    together (by program name), counted by PSS (shared pages split between
    the processes sharing them), or RSS where that can't be read."""
    totals = {}
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                argv0 = f.read().split(b"\0", 1)[0].decode(errors="replace")
            if not argv0:
                continue  # kernel threads
            used = None
            try:
                with open(f"/proc/{pid}/smaps_rollup") as f:
                    for line in f:
                        if line.startswith("Pss:"):
                            used = int(line.split()[1]) * 1024
                            break
            except OSError:
                with open(f"/proc/{pid}/statm") as f:
                    used = int(f.read().split()[1]) * PAGE
        except (OSError, ValueError, IndexError):
            continue
        if used:
            name = os.path.basename(argv0.split(" ")[0])
            totals[name] = totals.get(name, 0) + used
    return sorted(totals.items(), key=lambda item: -item[1])[:count]


def thread_freqs():
    """{"cpu0": GHz, …}"""
    out = {}
    for path in glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq"):
        value = read(path)
        if value and value.isdigit():
            out[path.split("/")[5]] = int(value) / 1e6
    return out


def cpu_freq_ghz():
    values = [int(v) for v in (read(p) for p in glob.glob(
        "/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq")) if v and v.isdigit()]
    return sum(values) / len(values) / 1e6 if values else None


def find_cpu_temp():
    """The CPU package temperature's sysfs file, or None."""
    for hwmon in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        if read(os.path.join(hwmon, "name")) not in ("coretemp", "k10temp", "zenpower", "cpu_thermal"):
            continue
        inputs = sorted(glob.glob(os.path.join(hwmon, "temp*_input")))
        for path in inputs:
            label = read(path.replace("_input", "_label"), "")
            if label.startswith(("Package", "Tctl", "Tdie")):
                return path
        if inputs:
            return inputs[0]
    for zone in glob.glob("/sys/class/thermal/thermal_zone*"):
        if read(os.path.join(zone, "type")) == "x86_pkg_temp":
            return os.path.join(zone, "temp")
    return None


def meminfo():
    info = {}
    for line in read("/proc/meminfo", "").splitlines():
        key, _, rest = line.partition(":")
        info[key] = int(rest.split()[0]) * 1024 if rest.split() else 0
    return info


def disks():
    """(mount, used, total) bytes of each filesystem in MOUNTS, once each."""
    seen, out = set(), []
    for mount in MOUNTS:
        try:
            st = os.statvfs(mount)
            dev = os.stat(mount).st_dev
        except OSError:
            continue
        if dev in seen or not os.path.ismount(mount):
            continue
        seen.add(dev)
        total = st.f_blocks * st.f_frsize
        out.append((mount, total - st.f_bfree * st.f_frsize, total))
    return out


def links():
    """Connected Wi-Fi and wired links: [(device, type, connection name)]."""
    try:
        out = subprocess.run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"],
                             capture_output=True, text=True, timeout=2).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    found = []
    for line in out.splitlines():
        parts = line.replace("\\:", "\0").split(":")
        if len(parts) < 4:
            continue
        dev, kind, state, name = (p.replace("\0", ":") for p in parts[:4])
        if state == "connected" and kind in ("wifi", "ethernet"):
            found.append((dev, kind, name))
    found.sort(key=lambda link: link[1] != "wifi")  # Wi-Fi first
    return found


def net_bytes():
    """{device: (received, sent)} bytes."""
    out = {}
    for line in read("/proc/net/dev", "").splitlines()[2:]:
        dev, _, rest = line.partition(":")
        fields = rest.split()
        if len(fields) >= 9:
            out[dev.strip()] = (int(fields[0]), int(fields[8]))
    return out


def find_gpu():
    """The GPU to show: ("nvidia", its sysfs device) when nvidia-smi is there,
    ("amd", its sysfs device) for an AMD card, or None (Intel's usage needs
    root)."""
    for card in sorted(glob.glob("/sys/class/drm/card[0-9]")):
        dev = os.path.realpath(os.path.join(card, "device"))
        vendor = read(os.path.join(dev, "vendor"))
        if vendor == "0x10de" and shutil.which("nvidia-smi"):
            return "nvidia", dev
        if os.path.exists(os.path.join(dev, "gpu_busy_percent")):
            return "amd", dev
    return None


class NvidiaReader:
    """nvidia-smi in its own loop (one reading a second) while the menu is
    open: name, usage %, VRAM used/total MiB, temperature. Not started while
    the card sleeps (a laptop's hybrid graphics), so it isn't woken up."""

    QUERY = "name,utilization.gpu,memory.used,memory.total,temperature.gpu"

    def __init__(self, dev):
        self.dev = dev
        self.proc = None
        self.reading = None

    def asleep(self):
        return read(os.path.join(self.dev, "power", "runtime_status")) == "suspended"

    def start(self):
        self.reading = None
        if self.proc or self.asleep():
            return
        try:
            self.proc = subprocess.Popen(
                ["nvidia-smi", f"--query-gpu={self.QUERY}", "--format=csv,noheader,nounits",
                 "-lms", "1000"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        except OSError:
            return
        threading.Thread(target=self.follow, args=(self.proc,), daemon=True).start()

    def follow(self, proc):
        for line in proc.stdout:
            fields = [f.strip() for f in line.split(",")]
            if len(fields) == 5:
                self.reading = fields

    def stop(self):
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None


def wifi_bitrate(dev):
    """The Wi-Fi link rate in Mb/s (NetworkManager), or None."""
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM)
        path = bus.call_sync(
            "org.freedesktop.NetworkManager", "/org/freedesktop/NetworkManager",
            "org.freedesktop.NetworkManager", "GetDeviceByIpIface",
            GLib.Variant("(s)", (dev,)), GLib.VariantType("(o)"),
            Gio.DBusCallFlags.NONE, 1000, None).unpack()[0]
        rate = bus.call_sync(
            "org.freedesktop.NetworkManager", path, "org.freedesktop.DBus.Properties", "Get",
            GLib.Variant("(ss)", ("org.freedesktop.NetworkManager.Device.Wireless", "Bitrate")),
            GLib.VariantType("(v)"), Gio.DBusCallFlags.NONE, 1000, None).unpack()[0]
        return rate / 1000 if rate else None
    except GLib.Error:
        return None


def gib(n):
    return f"{n / 2 ** 30:.1f}"


def size(n):
    """Disk sizes: GiB, or TiB from 1000 GiB."""
    return f"{n / 2 ** 40:.2f} TiB" if n >= 1000 * 2 ** 30 else f"{n / 2 ** 30:.1f} GiB"


def speed(bytes_per_s):
    """In Mbps (megabits per second, as connection speeds are given):
    two decimals below 1, one below 100."""
    mbps = bytes_per_s * 8 / 1e6
    if mbps >= 100:
        return f"{mbps:.0f} Mbps"
    if mbps >= 1:
        return f"{mbps:.1f} Mbps"
    return f"{mbps:.2f} Mbps"


# --- bar button position (as calendar-menu.py) -----------------------------------

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
        _magic, dims, _maxval, data = ppm.split(b"\n", 3)
        w, h = (int(v) for v in dims.split())
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


def styled(widget, *classes):
    for c in classes:
        widget.get_style_context().add_class(c)
    return widget


class Meter:
    """A row: icon, name, value (and percentage) on the right, a bar, a detail line."""

    def __init__(self, parent, icon_name, name, last=False, percent=True,
                 expanded=None, on_toggle=None):
        """With on_toggle: the row expands (a chevron; click to toggle) to show
        self.extra, a box to fill; on_toggle(True/False) on every change."""
        box = styled(Gtk.Box(orientation=Gtk.Orientation.VERTICAL), "item", *(["last"] if last else []))
        row = Gtk.Box()
        row.pack_start(icon(icon_name, 16, "item-icon"), False, False, 0)
        row.pack_start(label(name, "name"), True, True, 0)
        self.value = label("", "value", xalign=1)
        self.percent = label("", "percent", xalign=1)
        row.pack_start(self.value, False, False, 0)
        if percent:
            row.pack_start(self.percent, False, False, 0)
        self.extra = self.revealer = None
        if on_toggle:
            self.on_toggle = on_toggle
            self.chevron = icon("ld-chevron-down-symbolic", 14, "chevron")
            row.pack_start(self.chevron, False, False, 0)
            header = styled(Gtk.Button(), "expander-row")
            header.add(row)
            header.connect("clicked", lambda *_: self.toggle())
            box.add(header)
        else:
            box.add(row)
        self.bar = styled(Gtk.LevelBar(), "meter")
        for offset in ("low", "high", "full"):
            self.bar.remove_offset_value(offset)
        box.add(self.bar)
        self.detail = label("", "detail")
        self.detail.set_no_show_all(True)
        box.add(self.detail)
        if on_toggle:
            self.revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN,
                                         transition_duration=150)
            self.extra = styled(Gtk.Box(orientation=Gtk.Orientation.VERTICAL), "extra")
            self.revealer.add(self.extra)
            box.add(self.revealer)
            self.set_expanded(bool(expanded), animate=False)
        parent.add(box)

    def expanded(self):
        return bool(self.revealer and self.revealer.get_reveal_child())

    def set_expanded(self, expanded, animate=True):
        if not animate:
            duration = self.revealer.get_transition_duration()
            self.revealer.set_transition_duration(0)
        self.revealer.set_reveal_child(expanded)
        if not animate:
            self.revealer.set_transition_duration(duration)
        self.chevron.set_from_icon_name(
            "ld-chevron-up-symbolic" if expanded else "ld-chevron-down-symbolic", Gtk.IconSize.BUTTON)
        self.chevron.set_pixel_size(14)

    def toggle(self):
        self.set_expanded(not self.expanded())
        self.on_toggle(self.expanded())

    def set(self, fraction, value, detail=None):
        fraction = max(0.0, min(1.0, fraction))
        self.bar.set_value(fraction)
        self.value.set_text(value)
        self.percent.set_text(f"{round(fraction * 100)}%")
        if detail:
            self.detail.set_text(detail)
            self.detail.show()
        else:
            self.detail.hide()


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
        GtkLayerShell.set_namespace(self, "resources-menu")
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

        self.temp_path = find_cpu_temp()
        self.core_temp_paths = core_temps()
        self.expanded = {"cpu": False, "ram": False}  # one at a time; folded on closing
        self.ticks = 0
        self.top_busy = False
        self.cores = os.cpu_count() or 1
        self.last = None  # (time, cpu times, net bytes) of the previous reading
        self.gpu = find_gpu()
        self.nvidia = NvidiaReader(self.gpu[1]) if self.gpu and self.gpu[0] == "nvidia" else None

    # open / close

    def toggle(self):
        if self.get_visible():
            self.close_menu()
        else:
            self.open()

    def open(self):
        pos = cursor_position()
        colours, accent = theme()
        css = CSS
        for name, value in colours.items():
            css = css.replace(f"@{name}@", value)
        self.provider.load_from_data(css.encode())
        center = module_center(pos[0], pos[1], pos[2], rgb(accent)) if pos else None
        self.last = (time.monotonic(), cpu_times(), net_bytes())
        if self.nvidia:
            self.nvidia.start()
        self.build(pos, center)
        self.show_all()
        self.update()
        # A first reading soon (usage needs two samples), then every second.
        GLib.timeout_add(300, lambda: self.get_visible() and self.update() and False)
        self.ticker = GLib.timeout_add(1000, self.tick)

    def close_menu(self):
        if self.ticker:
            GLib.source_remove(self.ticker)
            self.ticker = None
        if self.nvidia:
            self.nvidia.stop()
        # CPU and RAM open folded again next time.
        self.expanded = {key: False for key in self.expanded}
        self.hide()
        return True

    def on_key(self, _widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.close_menu()
        return False

    def tick(self):
        if not self.get_visible():
            self.ticker = None
            return False
        self.update()
        return True

    # layout

    def build(self, pos, center):
        if self.holder:
            self.holder.destroy()
        holder = self.holder = Gtk.EventBox()
        holder.connect("button-press-event", lambda *_: True)
        holder.set_halign(Gtk.Align.START)
        holder.set_valign(Gtk.Align.START)
        self.backdrop.add(holder)

        menu = styled(Gtk.Box(orientation=Gtk.Orientation.VERTICAL), "dropdown")
        menu.set_size_request(WIDTH, -1)  # (GTK3 counts the CSS margins in it)
        holder.add(menu)

        header = styled(Gtk.Box(), "dropdown-header")
        header.pack_start(icon("ld-activity-symbolic", 20, "dropdown-title-icon"), False, False, 0)
        header.pack_start(label("Resources", "dropdown-title"), True, True, 0)
        menu.add(header)

        content = styled(Gtk.Box(orientation=Gtk.Orientation.VERTICAL), "dropdown-content")
        menu.add(content)

        system = styled(Gtk.Box(orientation=Gtk.Orientation.VERTICAL), "card")
        title = Gtk.Box()
        title.pack_start(icon("ld-cpu-symbolic", 15, "section-icon"), False, False, 0)
        title.pack_start(label("SYSTEM", "section"), True, True, 0)
        system.add(title)
        self.cpu = Meter(system, "ld-cpu-symbolic", "CPU", percent=False,
                         expanded=self.expanded["cpu"], on_toggle=self.remember("cpu"))
        self.build_cpu_extra(self.cpu.extra)
        self.gpu_meter = Meter(system, "ld-monitor-symbolic", "GPU", percent=False) if self.gpu else None
        self.ram = Meter(system, "ld-memory-stick-symbolic", "RAM",
                         expanded=self.expanded["ram"], on_toggle=self.remember("ram"))
        self.build_ram_extra(self.ram.extra)
        self.disks = []
        found = disks()
        for i, (mount, _used, _total) in enumerate(found):
            name = "Disk" if mount == "/" else f"Disk {mount}"
            self.disks.append((mount, Meter(system, "ld-hard-drive-symbolic", name,
                                            last=i == len(found) - 1)))
        content.add(system)

        network = styled(Gtk.Box(orientation=Gtk.Orientation.VERTICAL), "card", "last")
        title = Gtk.Box()
        title.pack_start(icon("ld-wifi-symbolic", 15, "section-icon"), False, False, 0)
        title.pack_start(label("NETWORK", "section"), True, True, 0)
        network.add(title)
        self.net_rows = []
        self.links = links()
        if not self.links:
            network.add(label("Not connected", "empty"))
        for i, (dev, kind, name) in enumerate(self.links):
            if i:
                network.add(styled(Gtk.Box(), "sep"))
            row = Gtk.Box()
            row.pack_start(icon("ld-wifi-symbolic" if kind == "wifi" else "network-wired-symbolic",
                                16, "item-icon"), False, False, 0)
            row.pack_start(label(name if kind == "wifi" else "Wired", "name",
                                 ellipsize=Pango.EllipsizeMode.END), True, True, 0)
            rate = label("", "detail")
            row.pack_start(rate, False, False, 0)
            network.add(row)
            speeds = Gtk.Box(homogeneous=True)
            speeds.set_margin_top(8)
            down = label("", "speed")
            up = label("", "speed")
            for arrow, value, text in (("ld-arrow-down-symbolic", down, "down"),
                                       ("ld-arrow-up-symbolic", up, "up")):
                cell = Gtk.Box()
                cell.pack_start(icon(arrow, 15, "speed-icon"), False, False, 0)
                cell.pack_start(value, False, False, 0)
                cell.pack_start(label(text, "speed-label"), False, False, 0)
                speeds.pack_start(cell, True, True, 0)
            network.add(speeds)
            self.net_rows.append((dev, kind, rate, down, up))
        content.add(network)

        if pos:
            cx, origin, mon_width = pos
            self.place_on_monitor(origin)
            x = (center if center is not None else cx) - origin[0]
            holder.set_margin_start(max(4, min(round(x - WIDTH / 2), mon_width - WIDTH - 4)))
        holder.set_margin_top(TOP - SHADOW_TOP)

    def remember(self, key):
        """One section open at a time (both would make the menu taller than
        the screen)."""
        def on_toggle(expanded):
            self.expanded[key] = expanded
            if expanded:
                for other, meter in (("cpu", self.cpu), ("ram", self.ram)):
                    if other != key and meter.expanded():
                        meter.set_expanded(False)
                        self.expanded[other] = False
                self.update()  # fill it at once (top apps included)
        return on_toggle

    def kv(self, parent, key):
        """A key: value line in an expanded section; returns the value label."""
        row = styled(Gtk.Box(), "kv")
        row.pack_start(label(key, "kv-key"), True, True, 0)
        value = label("", "kv-value", xalign=1)
        row.pack_start(value, False, False, 0)
        parent.add(row)
        return value

    def build_cpu_extra(self, extra):
        """Each thread's usage (two columns), then temperatures, load, uptime."""
        extra.add(label("THREADS", "sub-head", "first"))
        grid = Gtk.Grid(column_spacing=0, row_spacing=5)
        grid.set_column_homogeneous(False)
        threads = sorted((n for n in cpu_times() if n != "cpu"), key=lambda n: int(n[3:]))
        rows = (len(threads) + 1) // 2
        self.thread_cells = []
        for i, name in enumerate(threads):
            col, row = divmod(i, rows)
            number = label(name[3:], "thread-name", xalign=1)
            bar = styled(Gtk.LevelBar(), "mini")
            for offset in ("low", "high", "full"):
                bar.remove_offset_value(offset)
            bar.set_hexpand(True)
            bar.set_valign(Gtk.Align.CENTER)
            value = label("", "thread-value", xalign=1)
            if col:
                number.set_margin_start(14)
            grid.attach(number, col * 3, row, 1, 1)
            grid.attach(bar, col * 3 + 1, row, 1, 1)
            grid.attach(value, col * 3 + 2, row, 1, 1)
            self.thread_cells.append((name, bar, value, number))
        extra.add(grid)
        extra.add(label("DETAILS", "sub-head"))
        self.core_temps_label = self.kv(extra, "Core temperatures") if self.core_temp_paths else None
        self.load_label = self.kv(extra, "Load average (1, 5, 15 min)")
        self.uptime_label = self.kv(extra, "Uptime")

    def build_ram_extra(self, extra):
        """Where the memory goes, swap, and the apps using the most."""
        extra.add(label("MEMORY", "sub-head", "first"))
        self.mem_labels = {key: self.kv(extra, text) for key, text in (
            ("apps", "Apps"), ("shared", "Shared (tmpfs, graphics)"),
            ("cache", "Cache (given back when needed)"), ("free", "Free"))}
        info = swap_info()
        self.swap_widgets = None
        if info:
            kind, _used, _total, _name = info
            extra.add(label("SWAP" + (" · ZRAM, COMPRESSED IN RAM" if kind == "zram" else ""),
                            "sub-head"))
            row = Gtk.Box()
            row.pack_start(label("Used", "kv-key"), True, True, 0)
            value = label("", "kv-value", xalign=1)
            row.pack_start(value, False, False, 0)
            extra.add(row)
            bar = styled(Gtk.LevelBar(), "mini", "swap")
            for offset in ("low", "high", "full"):
                bar.remove_offset_value(offset)
            extra.add(bar)
            zram = self.kv(extra, "Holds") if kind == "zram" else None
            self.swap_widgets = (value, bar, zram)
        extra.add(label("USING THE MOST", "sub-head"))
        self.top_labels = []
        for _ in range(4):
            row = styled(Gtk.Box(), "kv")
            name = label("", "kv-key", ellipsize=Pango.EllipsizeMode.END)
            value = label("", "kv-value", xalign=1)
            row.pack_start(name, True, True, 0)
            row.pack_start(value, False, False, 0)
            extra.add(row)
            self.top_labels.append((name, value))

    def place_on_monitor(self, origin):
        display = Gdk.Display.get_default()
        for i in range(display.get_n_monitors()):
            mon = display.get_monitor(i)
            g = mon.get_geometry()
            if (g.x, g.y) == origin:
                GtkLayerShell.set_monitor(self, mon)
                return

    # values

    def update(self):
        now, times, net = time.monotonic(), cpu_times(), net_bytes()
        then, old_times, old_net = self.last
        self.last = (now, times, net)
        elapsed = max(now - then, 0.05)

        usage = usage_between(old_times.get("cpu"), times.get("cpu"))
        parts = [f"{self.cores} threads"]
        freq = cpu_freq_ghz()
        if freq:
            parts.append(f"{freq:.1f} GHz")
        temp = read(self.temp_path) if self.temp_path else None
        if temp and temp.lstrip("-").isdigit():
            parts.append(f"{int(temp) / 1000:.0f} °C")
        self.cpu.set(usage, f"{usage * 100:.0f}%", " · ".join(parts))
        self.ticks += 1
        if self.cpu.expanded():
            self.update_cpu_extra(times, old_times)

        if self.gpu_meter:
            self.update_gpu()

        mem = meminfo()
        total = mem.get("MemTotal", 0)
        used = total - mem.get("MemAvailable", 0)
        if total:
            self.ram.set(used / total, f"{gib(used)} / {gib(total)} GiB",
                         f"{gib(mem.get('MemAvailable', 0))} GiB available")
        if self.ram.expanded():
            self.update_ram_extra(mem)

        sizes = {mount: (used, total) for mount, used, total in disks()}
        for mount, meter in self.disks:
            if mount in sizes:
                used, total = sizes[mount]
                meter.set(used / total if total else 0, f"{size(used)} / {size(total)}",
                          f"{size(total - used)} free")

        for dev, kind, rate, down, up in self.net_rows:
            new, old = net.get(dev), old_net.get(dev)
            if new and old:
                down.set_text(speed(max(0, new[0] - old[0]) / elapsed))
                up.set_text(speed(max(0, new[1] - old[1]) / elapsed))
            if kind == "wifi":
                mbps = wifi_bitrate(dev)
                rate.set_text(f"link {mbps:.0f} Mbps" if mbps else "")
        return True

    def update_cpu_extra(self, times, old_times):
        freqs = thread_freqs()
        for name, bar, value, number in self.thread_cells:
            usage = usage_between(old_times.get(name), times.get(name))
            bar.set_value(usage)
            value.set_text(f"{usage * 100:.0f}%")
            if name in freqs:
                number.set_tooltip_text(f"Thread {name[3:]}: {freqs[name]:.1f} GHz")
        if self.core_temps_label:
            temps = [read(p) for p in self.core_temp_paths]
            temps = [f"{int(t) / 1000:.0f}" for t in temps if t and t.isdigit()]
            self.core_temps_label.set_text(" · ".join(temps) + " °C" if temps else "")
        self.load_label.set_text(" · ".join(f"{v:.2f}" for v in os.getloadavg()))
        self.uptime_label.set_text(uptime())

    def update_ram_extra(self, mem):
        # Adds up to the total, and apps + shared to the row's "used" (total
        # minus available): the cache is what the kernel would give back.
        total, free = mem.get("MemTotal", 0), mem.get("MemFree", 0)
        available, shared = mem.get("MemAvailable", 0), mem.get("Shmem", 0)
        cache = max(0, available - free)
        apps = total - available - shared
        for key, value in (("apps", apps), ("shared", shared),
                           ("cache", cache), ("free", free)):
            self.mem_labels[key].set_text(f"{gib(max(0, value))} GiB")
        info = swap_info()
        if self.swap_widgets and info:
            kind, used, total_swap, device = info
            value, bar, zram = self.swap_widgets
            value.set_text(f"{gib(used)} / {gib(total_swap)} GiB · "
                           f"{round(100 * used / total_swap) if total_swap else 0}%")
            bar.set_value(used / total_swap if total_swap else 0)
            stats = zram_stats(device) if zram else None
            if stats:
                stored, ram_used, algo = stats
                ratio = f" ({stored / ram_used:.1f}×{', ' + algo if algo else ''})" if ram_used else ""
                zram.set_text(f"{gib(stored)} GiB in {gib(ram_used)} GiB of RAM{ratio}")
        # The apps: a heavier read (every process, ~0.25 s), every 3 s, in
        # the background so the menu doesn't stutter.
        if (self.ticks % 3 == 1 or not self.top_labels[0][0].get_text()) and not self.top_busy:
            self.top_busy = True
            threading.Thread(target=self.read_top, daemon=True).start()

    def read_top(self):
        top = top_memory(len(self.top_labels))
        GLib.idle_add(self.show_top, top)

    def show_top(self, top):
        self.top_busy = False
        for i, (name, value) in enumerate(self.top_labels):
            name.set_text(top[i][0] if i < len(top) else "")
            value.set_text(f"{gib(top[i][1])} GiB" if i < len(top) else "")
        return False

    def update_gpu(self):
        kind, dev = self.gpu
        if kind == "nvidia":
            if self.nvidia.asleep():
                self.gpu_meter.set(0, "Off", "Sleeping (hybrid graphics)")
                return
            if not self.nvidia.proc:
                self.nvidia.start()  # woke up while the menu was open
            r = self.nvidia.reading
            if not r:
                return
            name, usage, used, total, temp = r
            try:
                usage, used, total = float(usage), float(used), float(total)
            except ValueError:
                return
            parts = [_gpu_name(name), f"{used / 1024:.1f} / {total / 1024:.1f} GiB VRAM"]
            if temp.isdigit():
                parts.append(f"{temp} °C")
        else:  # amd
            busy = read(os.path.join(dev, "gpu_busy_percent"))
            if not (busy and busy.isdigit()):
                return
            usage = float(busy)
            parts = []
            used = read(os.path.join(dev, "mem_info_vram_used"))
            total = read(os.path.join(dev, "mem_info_vram_total"))
            if used and total and used.isdigit() and total.isdigit() and int(total):
                parts.append(f"{gib(int(used))} / {gib(int(total))} GiB VRAM")
            for temp in glob.glob(os.path.join(dev, "hwmon", "hwmon*", "temp1_input")):
                value = read(temp)
                if value and value.isdigit():
                    parts.append(f"{int(value) / 1000:.0f} °C")
        self.gpu_meter.set(usage / 100, f"{usage:.0f}%", " · ".join(parts))


def _gpu_name(name):
    for prefix in ("NVIDIA ", "GeForce ", "AMD ", "Radeon "):
        name = name.removeprefix(prefix)
    return name


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
