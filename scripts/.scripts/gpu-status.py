#!/usr/bin/env python3
"""The bar's GPU usage (Wayle custom module "gpu", watch mode, in the resources
group next to Wayle's own CPU and RAM modules): one JSON line every 2 s,
{"text": "12%"}, or an empty line (hidden) without a GPU
whose usage can be read.

NVIDIA: one nvidia-smi kept running in its own loop (not started while the
card sleeps, so a laptop's hybrid graphics aren't woken). AMD: sysfs.
Exits when Wayle (the parent) is gone or stops reading.
"""
import glob
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time

INTERVAL = 2.0


def read(path, default=None):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


class Gpu:
    def __init__(self):
        self.kind = self.dev = None
        self.proc = None
        self.reading = None  # (usage %, VRAM used MiB, VRAM total MiB)
        for card in sorted(glob.glob("/sys/class/drm/card[0-9]")):
            dev = os.path.realpath(os.path.join(card, "device"))
            if read(os.path.join(dev, "vendor")) == "0x10de" and shutil.which("nvidia-smi"):
                self.kind, self.dev = "nvidia", dev
                return
            if os.path.exists(os.path.join(dev, "gpu_busy_percent")):
                self.kind, self.dev = "amd", dev
                return

    def asleep(self):
        return read(os.path.join(self.dev, "power", "runtime_status")) == "suspended"

    def usage(self):
        """GPU usage %, or None (no GPU, asleep, no reading yet)."""
        if self.kind == "amd":
            busy = read(os.path.join(self.dev, "gpu_busy_percent"))
            return int(busy) if busy and busy.isdigit() else None
        if self.kind != "nvidia":
            return None
        if self.asleep():
            self.stop()
            return None
        if not self.proc:
            self.start()
        return self.reading[0] if self.reading else None

    def start(self):
        try:
            self.proc = subprocess.Popen(
                ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total",
                 "--format=csv,noheader,nounits", "-lms", str(int(INTERVAL * 1000))],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        except OSError:
            self.kind = None
            return
        threading.Thread(target=self.follow, args=(self.proc,), daemon=True).start()

    def follow(self, proc):
        for line in proc.stdout:
            try:
                self.reading = tuple(float(v) for v in line.split(","))
            except ValueError:
                pass
        self.reading = None

    def stop(self):
        if self.proc:
            self.proc.terminate()
            self.proc = None
            self.reading = None




def main():
    parent = os.getppid()
    gpu = Gpu()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        # Wait (a little) for the first reading, so the button starts complete.
        gpu.usage()
        for _ in range(15):
            if gpu.kind != "nvidia" or gpu.reading:
                break
            time.sleep(0.1)
        while os.getppid() == parent:
            usage = gpu.usage()
            if usage is None:
                line = ""
            else:
                # Two digits (09%, 00%), like CPU/RAM in config.toml: a steady width.
                line = json.dumps({"text": f"{round(usage):02d}%"})
            print(line, flush=True)
            time.sleep(INTERVAL)
    except (BrokenPipeError, KeyboardInterrupt):
        pass
    finally:
        gpu.stop()
    return 0

if __name__ == "__main__":
    sys.exit(main())
