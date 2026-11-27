#!/usr/bin/env python3
"""

OSKewl -=- Joystick Lunatic Software (JLsoft) - 2026
======
Windows-style On-Screen Keyboard for Linux (Bazzite)

Clicking a key types it system-wide through a virtual /dev/uinput keyboard,
exactly like pressing the physical key.

WHAT IT NEEDS (all of it ships with a stock Bazzite / Fedora Atomic image)
  • Python 3 + PyGObject + GTK 3
  • Write access to /dev/uinput (input group membership or a udev rule)
  • Nothing to pip/rpm-install: uinput is driven directly with fcntl/struct,
    and sound uses whichever of pw-play / paplay / aplay is already present.

LAYOUT
  Mirrors the Windows OSK: Esc shares the number row, Del/Home/PgUp/... on the
  right, arrow cluster beside the space bar, plus the OSK's own keys:
    Fn      number row becomes F1–F12
    Fade / Numpad     two half-height keys sharing one key slot: toggle
                      translucency / show or hide the numeric keypad
    Options / Layout  two half-height keys sharing one key slot: settings
                      dialog / switch between the Windows OSK and the
                      standard 104-key layout
    Mv Up / Mv Dn / Dock  move the window

MODIFIERS (Shift, Ctrl, Alt, ⊞ Super, Fn)
  click once  → sticky: applies to the next key, then releases itself
  click twice → held: stays pressed until you click it a third time
  A sticky/held key is drawn highlighted (held ones also get a bar underneath).

CAVEATS
  • On Wayland, GTK cannot keep a window on top or stop it taking focus, and
    cannot move it (Mv Up / Mv Dn / Dock do nothing). Use an X11 session or a
    layer-shell build if that matters.
  • uinput sends scancodes, so the typed character follows the session's xkb
    layout. Key legends assume US ANSI.
"""
import configparser
import fcntl
import glob
import math
import os
import random
import re
import shutil
import struct
import subprocess
import sys
import wave

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib, Pango  # noqa: E402  (Gtk first!)
try:                                              # ships with GTK 3; optional here
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf           # noqa: E402
except (ValueError, ImportError):
    GdkPixbuf = None

CONFIG_DIR = os.path.expanduser("~/.config/oskewl")
CONFIG_FILE = os.path.join(CONFIG_DIR, "settings.conf")

# --------------------------------------------------------------------------
# evdev key codes (linux/input-event-codes.h)
# --------------------------------------------------------------------------
KEY = {
    "ESC": 1, "1": 2, "2": 3, "3": 4, "4": 5, "5": 6, "6": 7, "7": 8, "8": 9,
    "9": 10, "0": 11, "MINUS": 12, "EQUAL": 13, "BACKSPACE": 14, "TAB": 15,
    "Q": 16, "W": 17, "E": 18, "R": 19, "T": 20, "Y": 21, "U": 22, "I": 23,
    "O": 24, "P": 25, "LEFTBRACE": 26, "RIGHTBRACE": 27, "ENTER": 28,
    "LEFTCTRL": 29, "A": 30, "S": 31, "D": 32, "F": 33, "G": 34, "H": 35,
    "J": 36, "K": 37, "L": 38, "SEMICOLON": 39, "APOSTROPHE": 40, "GRAVE": 41,
    "LEFTSHIFT": 42, "BACKSLASH": 43, "Z": 44, "X": 45, "C": 46, "V": 47,
    "B": 48, "N": 49, "M": 50, "COMMA": 51, "DOT": 52, "SLASH": 53,
    "RIGHTSHIFT": 54, "KPASTERISK": 55, "LEFTALT": 56, "SPACE": 57,
    "CAPSLOCK": 58, "NUMLOCK": 69, "SCROLLLOCK": 70,
    "KP7": 71, "KP8": 72, "KP9": 73, "KPMINUS": 74, "KP4": 75, "KP5": 76,
    "KP6": 77, "KPPLUS": 78, "KP1": 79, "KP2": 80, "KP3": 81, "KP0": 82,
    "KPDOT": 83, "KPENTER": 96, "RIGHTCTRL": 97, "KPSLASH": 98, "SYSRQ": 99,
    "RIGHTALT": 100, "HOME": 102, "UP": 103, "PAGEUP": 104, "LEFT": 105,
    "RIGHT": 106, "END": 107, "DOWN": 108, "PAGEDOWN": 109, "INSERT": 110,
    "DELETE": 111, "PAUSE": 119, "LEFTMETA": 125, "RIGHTMETA": 126,
    "COMPOSE": 127,
}
for _n, _c in enumerate(list(range(59, 69)) + [87, 88], 1):   # F1..F12
    KEY["F%d" % _n] = _c

MOD_CODES = [KEY["LEFTSHIFT"], KEY["RIGHTSHIFT"], KEY["LEFTCTRL"],
             KEY["RIGHTCTRL"], KEY["LEFTALT"], KEY["RIGHTALT"],
             KEY["LEFTMETA"], KEY["RIGHTMETA"]]
SHIFT_CODES = (KEY["LEFTSHIFT"], KEY["RIGHTSHIFT"])


# --------------------------------------------------------------------------
# /dev/uinput without the python-uinput package
# --------------------------------------------------------------------------
def _ioc(direction, nr, size):
    return (direction << 30) | (size << 16) | (ord("U") << 8) | nr


UI_DEV_CREATE = _ioc(0, 1, 0)
UI_DEV_DESTROY = _ioc(0, 2, 0)
UI_DEV_SETUP = _ioc(1, 3, 92)       # struct uinput_setup is 92 bytes
UI_SET_EVBIT = _ioc(1, 100, 4)
UI_SET_KEYBIT = _ioc(1, 101, 4)
EV_SYN, EV_KEY = 0, 1
BUS_VIRTUAL = 0x06


class UInput:
    """A virtual keyboard. emit(code, 1/0) presses / releases a key."""

    def __init__(self, codes, name="OSKewl"):
        self.fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        try:
            fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_KEY)
            for code in codes:
                fcntl.ioctl(self.fd, UI_SET_KEYBIT, code)
            setup = struct.pack("HHHH80sI", BUS_VIRTUAL, 0, 0, 1,
                                name.encode(), 0)
            fcntl.ioctl(self.fd, UI_DEV_SETUP, setup)
            fcntl.ioctl(self.fd, UI_DEV_CREATE)
        except OSError:
            os.close(self.fd)
            raise
        self._warned = False

    def emit(self, code, value):
        data = (struct.pack("llHHi", 0, 0, EV_KEY, code, value)
                + struct.pack("llHHi", 0, 0, EV_SYN, 0, 0))
        try:
            os.write(self.fd, data)
        except OSError as e:
            if not self._warned:
                print("Warning: uinput write failed (%s)" % e, file=sys.stderr)
                self._warned = True

    def tap(self, code, mods=()):
        for m in mods:
            self.emit(m, 1)
        self.emit(code, 1)
        self.emit(code, 0)
        for m in reversed(mods):
            self.emit(m, 0)

    def close(self):
        try:
            fcntl.ioctl(self.fd, UI_DEV_DESTROY)
        except OSError:
            pass
        os.close(self.fd)


def read_led(name):
    """True/False from the keyboard LED for 'capslock' / 'numlock', or None
    when the system exposes no such LED (then we just track state ourselves)."""
    paths = glob.glob("/sys/class/leds/*::%s/brightness" % name)
    if not paths:
        return None
    for p in paths:
        try:
            with open(p) as f:
                if int((f.read() or "0").strip()) > 0:
                    return True
        except (OSError, ValueError):
            pass
    return False


# --------------------------------------------------------------------------
# Click sound — stdlib only; plays through whatever CLI player is installed
# --------------------------------------------------------------------------
SOUND_VERSION = 1       # bump when a preset's recipe changes so caches regenerate
DEFAULT_SOUND = "click"
# Subtle, short key sounds, synthesised on first use (no files shipped).
#   tones : (Hz, decay seconds, amplitude) decaying sines
#   sweep : (start Hz, end Hz, sweep time, decay, amplitude) for a pitch drop
#   noise : (amplitude, decay, low-pass 0..1 — smaller = duller)
#   level : final peak volume, kept low on purpose
SOUNDS = {
    "click": dict(label="Soft click", len=0.035, level=0.40,
                  tones=[(2600, 0.0035, 0.50), (190, 0.009, 0.45)],
                  noise=(0.35, 0.0035, 1.0)),
    "tick":  dict(label="Tick", len=0.022, level=0.32,
                  tones=[(4200, 0.0012, 0.60)], noise=(0.25, 0.0010, 1.0)),
    "dink":  dict(label="Dink", len=0.10, level=0.30,
                  tones=[(1850, 0.028, 0.55), (5500, 0.010, 0.18)],
                  noise=(0.10, 0.0015, 1.0)),
    "tap":   dict(label="Wood tap", len=0.055, level=0.40,
                  tones=[(720, 0.007, 0.60), (1450, 0.004, 0.25)],
                  noise=(0.20, 0.003, 0.25)),
    "thock": dict(label="Thock", len=0.075, level=0.42,
                  tones=[(210, 0.013, 0.70), (430, 0.006, 0.20)],
                  noise=(0.18, 0.004, 0.12)),
    "pop":   dict(label="Pop", len=0.055, level=0.36, tones=[],
                  sweep=(1100, 320, 0.009, 0.012, 0.80),
                  noise=(0.08, 0.002, 1.0)),
    "tink":  dict(label="Glass tink", len=0.09, level=0.28,
                  tones=[(3300, 0.016, 0.50), (4950, 0.010, 0.25),
                         (7400, 0.005, 0.10)]),
    "ping":  dict(label="Soft ping", len=0.12, level=0.26,
                  tones=[(2400, 0.040, 0.60), (3600, 0.015, 0.12)]),
    "blip":  dict(label="Blip", len=0.03, level=0.30,
                  tones=[(1500, 0.006, 0.60), (3000, 0.003, 0.25)]),
    "bubble": dict(label="Bubble", len=0.06, level=0.32, tones=[],
                   sweep=(420, 1500, 0.012, 0.016, 0.80)),
    "drop":  dict(label="Water drop", len=0.07, level=0.30, tones=[],
                  sweep=(2200, 650, 0.006, 0.014, 0.80),
                  noise=(0.05, 0.001, 1.0)),
    "snap":  dict(label="Finger snap", len=0.03, level=0.34,
                  tones=[(3200, 0.0018, 0.35)], noise=(0.70, 0.0022, 1.0)),
    "rubber": dict(label="Rubber dome", len=0.06, level=0.40,
                   tones=[(140, 0.014, 0.70), (300, 0.005, 0.15)],
                   noise=(0.12, 0.004, 0.08)),
    "keycap": dict(label="Keycap", len=0.05, level=0.40,
                   tones=[(480, 0.008, 0.55), (960, 0.004, 0.20)],
                   noise=(0.25, 0.003, 0.35)),
    "typewriter": dict(label="Typewriter", len=0.06, level=0.38,
                       tones=[(900, 0.006, 0.40), (2100, 0.003, 0.25)],
                       noise=(0.50, 0.003, 0.7)),
    "clack": dict(label="Clack (down + up)", len=0.03, level=0.38,
                  tones=[(2600, 0.0035, 0.50), (190, 0.009, 0.45)],
                  noise=(0.35, 0.0035, 1.0), echo=[(0.028, 0.45)]),
}


def synth_sound(p, rate=44100):
    rng = random.Random(7)
    n = int(rate * p["len"])
    out, phase, lp = [], 0.0, 0.0
    tail = int(rate * 0.002)
    for i in range(n):
        t = i / rate
        s = 0.0
        for f, d, a in p["tones"]:
            s += a * math.sin(2 * math.pi * f * t) * math.exp(-t / d)
        if "sweep" in p:
            f0, f1, tau, d, a = p["sweep"]
            phase += 2 * math.pi * (f1 + (f0 - f1) * math.exp(-t / tau)) / rate
            s += a * math.sin(phase) * math.exp(-t / d)
        if "noise" in p:
            a, d, alpha = p["noise"]
            lp += alpha * ((rng.random() * 2 - 1) - lp)
            s += a * lp * math.exp(-t / d)
        if i < 16:
            s *= i / 16.0
        if n - i <= tail:
            s *= (n - i) / tail
        out.append(s)
    echoes = p.get("echo")
    if echoes:                      # extra delayed, quieter copies (e.g. key-up)
        mixed = out + [0.0] * int(rate * max(d for d, _ in echoes))
        for delay, gain in echoes:
            off = int(rate * delay)
            for i, v in enumerate(out):
                mixed[off + i] += v * gain
        out = mixed
    k = p["level"] / max(1e-9, max(abs(x) for x in out)) * 32767
    return b"".join(struct.pack("<h", int(x * k)) for x in out)


class ClickPlayer:
    CANDIDATES = (["pw-play"], ["paplay"], ["aplay", "-q"])

    def __init__(self):
        self.cmds = [c for c in self.CANDIDATES if shutil.which(c[0])]
        self._procs = []                 # (Popen, start time)

    @property
    def cmd(self):                       # truthy while some player is usable
        return self.cmds[0] if self.cmds else None

    def preset_file(self, preset):
        if preset not in SOUNDS:
            preset = DEFAULT_SOUND
        path = os.path.join(CONFIG_DIR, "sounds",
                            "%s_v%d.wav" % (preset, SOUND_VERSION))
        if os.path.isfile(path) and os.path.getsize(path) > 44:
            return path                  # (a 44-byte file is a header with no audio)
        tmp = path + ".tmp"
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with wave.open(tmp, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(44100)
                w.writeframes(synth_sound(SOUNDS[preset]))
            os.replace(tmp, path)        # atomic: never leaves a half-written wav
            return path
        except OSError:
            return None

    def _reap(self):
        """Drop finished players; kill hung ones; fall back to the next player
        if the current one exits with an error (e.g. pw-play without PipeWire)."""
        now = GLib.get_monotonic_time() / 1e6
        alive = []
        for proc, t0 in self._procs:
            rc = proc.poll()
            if rc is None:
                if now - t0 > 3.0:       # a click is milliseconds; this is hung
                    proc.kill()
                    proc.wait()
                else:
                    alive.append((proc, t0))
            elif rc != 0 and len(self.cmds) > 1:
                self.cmds.pop(0)
        self._procs = alive

    def play(self, path="", preset=DEFAULT_SOUND):
        """Play a custom file if given and readable, else the built-in preset."""
        if not self.cmds:
            return
        if not (path and os.path.isfile(path)):
            path = self.preset_file(preset)
        if not path:
            return
        self._reap()
        if len(self._procs) >= 8:        # don't pile up on rapid key repeat
            return
        try:
            self._procs.append((subprocess.Popen(
                self.cmds[0] + [path], stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
                GLib.get_monotonic_time() / 1e6))
        except OSError:
            if len(self.cmds) > 1:       # try the next player next time
                self.cmds.pop(0)


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------
DEFAULTS = {
    "layout": "windows",      # "windows" or "standard"
    "bg": "#1a1a1a",          # window background (what shows between keys)
    "key": "#303030",         # key face
    "text": "#ffffff",        # legends
    "border": "#5e5e5e",      # key borders
    "highlight": "#0078d7",   # sticky / held / lock-on keys
    "border_px": 1,
    "spacing": 4,             # gap between keys, px
    "font": "Sans",
    "font_scale": 100,        # % of the auto-fit legend size
    "opacity": 1.0,           # key faces
    "bg_opacity": 1.0,        # window + gaps between keys (own setting)
    "numpad": False,
    "sound": False,
    "sound_preset": DEFAULT_SOUND,   # built-in sound
    "sound_file": "",         # custom file; overrides the preset when set
    "bg_image": "",           # png / jpeg behind the keys
    "bg_scale": "cover",      # cover (fill + crop) | stretch | contain (fit)
    "keycap_image": "",       # png / jpeg used as every key's face
    "keycap_mode": "slice",   # slice (keep edges, stretch middle) | stretch
    "keycap_slice": 0,        # edge size in image px for "slice"; 0 = auto
    "title": "OSKewl",   # title bar text (empty = none)
    "title_px": 13,
    "title_h": 30,            # title bar height, px
    "width": 1100,
    "height": 340,
}
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def load_config():
    cfg = dict(DEFAULTS)
    p = configparser.ConfigParser(interpolation=None)
    try:
        p.read(CONFIG_FILE)
    except configparser.Error:
        return cfg
    for k, d in DEFAULTS.items():
        try:
            if isinstance(d, bool):
                cfg[k] = p.getboolean("oskewl", k)
            elif isinstance(d, int):
                cfg[k] = p.getint("oskewl", k)
            elif isinstance(d, float):
                cfg[k] = p.getfloat("oskewl", k)
            else:
                cfg[k] = p.get("oskewl", k)
        except (configparser.Error, ValueError):
            pass
    for k in ("bg", "key", "text", "border", "highlight"):
        if not _HEX.match(str(cfg[k])):
            cfg[k] = DEFAULTS[k]
    cfg["border_px"] = max(0, min(8, cfg["border_px"]))
    cfg["spacing"] = max(0, min(16, cfg["spacing"]))
    cfg["font_scale"] = max(50, min(200, cfg["font_scale"]))
    cfg["opacity"] = max(0.2, min(1.0, cfg["opacity"]))
    cfg["bg_opacity"] = max(0.0, min(1.0, cfg["bg_opacity"]))
    if cfg["bg_scale"] not in ("cover", "stretch", "contain"):
        cfg["bg_scale"] = "cover"
    if cfg["keycap_mode"] not in ("slice", "stretch"):
        cfg["keycap_mode"] = "slice"
    cfg["keycap_slice"] = max(0, min(400, cfg["keycap_slice"]))
    if cfg["layout"] not in LAYOUTS:
        cfg["layout"] = "windows"
    if cfg["sound_preset"] not in SOUNDS:
        cfg["sound_preset"] = DEFAULT_SOUND
    cfg["title_px"] = max(8, min(24, cfg["title_px"]))
    cfg["title_h"] = max(18, min(60, cfg["title_h"]))
    cfg["width"] = max(300, cfg["width"])
    cfg["height"] = max(150, cfg["height"])
    return cfg


def save_config(cfg):
    p = configparser.ConfigParser(interpolation=None)
    p["oskewl"] = {k: str(v) for k, v in cfg.items()}
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            p.write(f)
    except OSError as e:
        print("Warning: could not write settings (%s)" % e, file=sys.stderr)


# --------------------------------------------------------------------------
# Colour helpers
# --------------------------------------------------------------------------
def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rgb_hex(t):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(c)))) for c in t)


def mix_hex(a, b, t):
    return rgb_hex([x + t * (y - x) for x, y in zip(hex_rgb(a), hex_rgb(b))])


def contrast_hex(bg):
    r, g, b = hex_rgb(bg)
    return "#000000" if 0.299 * r + 0.587 * g + 0.114 * b > 150 else "#ffffff"


def rgba_css(h, a):
    r, g, b = hex_rgb(h)
    return "rgba(%d,%d,%d,%.2f)" % (r, g, b, a)


def hex_to_rgba(h):
    c = Gdk.RGBA()
    c.parse(h)
    return c


def rgba_to_hex(c):
    return rgb_hex((c.red * 255, c.green * 255, c.blue * 255))


# --------------------------------------------------------------------------
# Layouts. Grid units: 1 column = 1/4 of a standard key; a key row is 2 grid
# rows, so half-height gaps and tall keys (numpad + / Enter) are possible.
#   "windows"   Windows On-Screen Keyboard
#   "standard"  US 104-key hardware layout (F-row, 3×2 nav block, inverted-T
#               arrows, full numpad)
# --------------------------------------------------------------------------
LAYOUTS = {"windows": "Windows OSK", "standard": "Standard 104-key"}
MOD_TIP = "Click: next key only · again: hold · again: release"
X11_ONLY = ("mvup", "mvdn", "dock")      # window-moving keys, useless on Wayland


def is_wayland():
    d = Gdk.Display.get_default()
    name = type(d).__name__ if d is not None else ""
    if "Wayland" in name:
        return True
    if "X11" in name:
        return False
    return os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"


def _ch(name, base, alt=None, w=4, **kw):
    return dict(kind="char", code=KEY[name], base=base, alt=alt, w=w, **kw)


def _letter(c):
    return _ch(c, c.lower(), c, letter=True)


def _mod(name, label, w=4, tip=MOD_TIP):
    return dict(kind="mod", code=KEY[name], base=label, alt=None, w=w, tip=tip)


def _act(name, label, tip, w=4, **kw):
    return dict(kind="action", code=None, action=name, base=label, alt=None,
                w=w, tip=tip, **kw)


def _split(L, r, col, top, bottom):
    """Two half-height keys stacked in the space of one normal key."""
    L.row(r, col, [top], rs=1)
    L.row(r + 1, col, [bottom], rs=1)


def _fade_numpad():
    return (_act("fade", "Fade", "Toggle translucent keyboard", rs=1),
            _act("numpad", "Numpad", "Show / hide the numeric keypad", rs=1))


def _opt_layout():
    return (_act("options", "Options", "Colours, spacing, font, sound", rs=1),
            _act("layout", "Layout", "Switch between the Windows OSK and the "
                 "standard 104-key layout", rs=1))


def _special(kind, name, label, w=4, tip=None):
    return dict(kind=kind, code=KEY[name], base=label, alt=None, w=w, tip=tip)


class _Layout:
    def __init__(self, cols, cols_num, units, wayland):
        self.cols, self.cols_num, self.units = cols, cols_num, units
        self.wayland = wayland
        self.keys = []       # (spec, col, row, colspan, rowspan, group)
        self.spacers = []    # (col, row, colspan, rowspan, group)

    def row(self, r, col, items, group="main", rs=2, expect=None):
        start = col
        for it in items:
            w = it if isinstance(it, int) else it["w"]
            if not isinstance(it, int) and not (
                    self.wayland and it.get("action") in X11_ONLY):
                self.keys.append((it, col, r, w, it.get("rs", rs), group))
            col += w
        if expect is not None:
            assert col - start == expect, (r, col - start, expect)

    def spacer(self, col, row, cs, rs, group="main"):
        self.spacers.append((col, row, cs, rs, group))


def _numrow():
    return [("GRAVE", "`", "~"), ("1", "1", "!"), ("2", "2", "@"),
            ("3", "3", "#"), ("4", "4", "$"), ("5", "5", "%"),
            ("6", "6", "^"), ("7", "7", "&"), ("8", "8", "*"),
            ("9", "9", "("), ("0", "0", ")"), ("MINUS", "-", "_"),
            ("EQUAL", "=", "+")]


def _layout_windows(wayland):
    L = _Layout(75, 88, 10, wayland)
    r0 = [_ch("ESC", "Esc")]
    for i, (n, b, a) in enumerate(_numrow()):
        kw = {"fn": ("F%d" % i, KEY["F%d" % i])} if i >= 1 else {}
        r0.append(_ch(n, b, a, **kw))
    r0.append(_ch("BACKSPACE", "⌫", w=6))
    r1 = ([_ch("TAB", "Tab", w=6)] + [_letter(c) for c in "QWERTYUIOP"]
          + [_ch("LEFTBRACE", "[", "{"), _ch("RIGHTBRACE", "]", "}"),
             _ch("BACKSLASH", "\\", "|"), _ch("DELETE", "Del")])
    r2 = ([_special("caps", "CAPSLOCK", "Caps", 8)]
          + [_letter(c) for c in "ASDFGHJKL"]
          + [_ch("SEMICOLON", ";", ":"), _ch("APOSTROPHE", "'", '"'),
             _ch("ENTER", "Enter", w=10)])
    r3 = ([_mod("LEFTSHIFT", "Shift", w=10)] + [_letter(c) for c in "ZXCVBNM"]
          + [_ch("COMMA", ",", "<"), _ch("DOT", ".", ">"), _ch("SLASH", "/", "?"),
             _ch("UP", "↑"), _mod("RIGHTSHIFT", "Shift", w=8)])
    r4 = [dict(kind="fn", code=None, base="Fn", alt=None, w=4,
               tip="Fn: number row becomes F1–F12. " + MOD_TIP),
          _mod("LEFTCTRL", "Ctrl"),
          _mod("LEFTMETA", "⊞", tip="Super / Windows key. " + MOD_TIP),
          _mod("LEFTALT", "Alt"),
          _ch("SPACE", "", w=22),
          _mod("RIGHTALT", "Alt"), _mod("RIGHTCTRL", "Ctrl"),
          _ch("LEFT", "←"), _ch("DOWN", "↓"), _ch("RIGHT", "→"),
          _ch("COMPOSE", "☰", tip="Menu")]
    for i, row in enumerate([r0, r1, r2, r3, r4]):
        L.row(2 * i, 0, row, expect=62)
    nav = [
        [_ch("HOME", "Home"), _ch("PAGEUP", "PgUp")],
        [_ch("END", "End"), _ch("PAGEDOWN", "PgDn"),
         _act("mvup", "Mv Up", "Move the keyboard up (X11 only)")],
        [_ch("INSERT", "Insert"), _ch("PAUSE", "Pause"),
         _act("mvdn", "Mv Dn", "Move the keyboard down (X11 only)")],
        [_ch("SYSRQ", "PrtScn"), _ch("SCROLLLOCK", "ScrLk")],
    ]
    L.spacer(62, 0, 1, 10)
    for i, row in enumerate(nav):
        L.row(2 * i, 63, row, expect=8 if i in (0, 3) else 12)
    # right-hand column = keyboard controls
    _split(L, 0, 71, *_fade_numpad())
    _split(L, 6, 71, *_opt_layout())
    L.row(8, 71, [_act("dock", "Dock", "Dock to the bottom of the screen (X11 only)")],
          expect=4)
    L.spacer(75, 0, 1, 10, "numpad")
    kp = lambda n, b, w=3: _ch(n, b, w=w)          # noqa: E731
    numpad = [
        [kp("KP7", "7"), kp("KP8", "8"), kp("KP9", "9"), kp("KPSLASH", "/")],
        [kp("KP4", "4"), kp("KP5", "5"), kp("KP6", "6"), kp("KPASTERISK", "*")],
        [kp("KP1", "1"), kp("KP2", "2"), kp("KP3", "3"), kp("KPMINUS", "-")],
        [kp("KP0", "0", 6), kp("KPDOT", "."), kp("KPPLUS", "+")],
        [kp("KPENTER", "Enter", 6), _special("numlock", "NUMLOCK", "NumLock", 6)],
    ]
    for i, row in enumerate(numpad):
        L.row(2 * i, 76, row, "numpad", expect=12)
    return L


def _layout_std(wayland):
    L = _Layout(74, 92, 13, wayland)
    fk = lambda a, b: [_ch("F%d" % i, "F%d" % i) for i in range(a, b + 1)]  # noqa: E731
    L.row(0, 0, [_ch("ESC", "Esc"), 4] + fk(1, 4) + [2] + fk(5, 8) + [2] + fk(9, 12),
          expect=60)
    L.row(3, 0, [_ch(n, b, a) for n, b, a in _numrow()]
          + [_ch("BACKSPACE", "Backspace", w=8)], expect=60)
    L.row(5, 0, [_ch("TAB", "Tab", w=6)] + [_letter(c) for c in "QWERTYUIOP"]
          + [_ch("LEFTBRACE", "[", "{"), _ch("RIGHTBRACE", "]", "}"),
             _ch("BACKSLASH", "\\", "|", w=6)], expect=60)
    L.row(7, 0, [_special("caps", "CAPSLOCK", "Caps Lock", 7)]
          + [_letter(c) for c in "ASDFGHJKL"]
          + [_ch("SEMICOLON", ";", ":"), _ch("APOSTROPHE", "'", '"'),
             _ch("ENTER", "Enter", w=9)], expect=60)
    L.row(9, 0, [_mod("LEFTSHIFT", "Shift", w=9)] + [_letter(c) for c in "ZXCVBNM"]
          + [_ch("COMMA", ",", "<"), _ch("DOT", ".", ">"), _ch("SLASH", "/", "?"),
             _mod("RIGHTSHIFT", "Shift", w=11)], expect=60)
    L.row(11, 0, [_mod("LEFTCTRL", "Ctrl", 5),
                  _mod("LEFTMETA", "⊞", 5, "Super / Windows key. " + MOD_TIP),
                  _mod("LEFTALT", "Alt", 5), _ch("SPACE", "", w=25),
                  _mod("RIGHTALT", "Alt", 5),
                  _mod("RIGHTMETA", "⊞", 5, "Super / Windows key. " + MOD_TIP),
                  _ch("COMPOSE", "☰", w=5, tip="Menu"),
                  _mod("RIGHTCTRL", "Ctrl", 5)], expect=60)
    # nav block: PrtSc/ScrLk/Pause, Ins/Home/PgUp, Del/End/PgDn, arrows below.
    # The empty Caps-row cells carry the keyboard's own controls.
    L.row(0, 62, [_ch("SYSRQ", "PrtScn"), _ch("SCROLLLOCK", "ScrLk"),
                  _ch("PAUSE", "Pause")], expect=12)
    L.row(3, 62, [_ch("INSERT", "Insert"), _ch("HOME", "Home"),
                  _ch("PAGEUP", "PgUp")], expect=12)
    L.row(5, 62, [_ch("DELETE", "Del"), _ch("END", "End"),
                  _ch("PAGEDOWN", "PgDn")], expect=12)
    _split(L, 7, 62, *_opt_layout())
    _split(L, 7, 66, *_fade_numpad())
    L.row(9, 62, [4,
                  _ch("UP", "↑"),
                  _act("dock", "Dock", "Dock to the bottom of the screen (X11 only)")],
          expect=12)
    L.row(11, 62, [_ch("LEFT", "←"), _ch("DOWN", "↓"), _ch("RIGHT", "→")], expect=12)
    L.spacer(60, 0, 2, 13)
    L.spacer(0, 2, 74, 1)
    L.spacer(74, 0, 2, 13, "numpad")
    L.spacer(74, 2, 18, 1, "numpad")
    kp = lambda n, b, w=4, **kw: _ch(n, b, w=w, **kw)      # noqa: E731
    L.row(3, 76, [_special("numlock", "NUMLOCK", "NumLock", 4), kp("KPSLASH", "/"),
                  kp("KPASTERISK", "*"), kp("KPMINUS", "-")], "numpad", expect=16)
    L.row(5, 76, [kp("KP7", "7"), kp("KP8", "8"), kp("KP9", "9"),
                  kp("KPPLUS", "+", rs=4)], "numpad", expect=16)
    L.row(7, 76, [kp("KP4", "4"), kp("KP5", "5"), kp("KP6", "6"), 4],
          "numpad", expect=16)
    L.row(9, 76, [kp("KP1", "1"), kp("KP2", "2"), kp("KP3", "3"),
                  kp("KPENTER", "Enter", rs=4)], "numpad", expect=16)
    L.row(11, 76, [kp("KP0", "0", 8), kp("KPDOT", "."), 4], "numpad", expect=16)
    return L


def build_layout(name, wayland):
    return (_layout_std if name == "standard" else _layout_windows)(wayland)


# --------------------------------------------------------------------------
# Keycap image scaling (GdkPixbuf; GTK 3 CSS can't draw a 9-slice centre)
# --------------------------------------------------------------------------
def render_keycap(src, w, h, mode, slice_px, unit_h):
    """Scale `src` to w×h. "stretch" squashes it whole. "slice" cuts it into a
    3×3 grid: the four corners and four edges keep their proportions (edge
    size shown on screen = slice scaled as if the image were one key tall,
    unit_h px) and only the middle stretches — so bevels stay crisp on wide
    keys like Space and Enter."""
    interp = GdkPixbuf.InterpType.BILINEAR
    sw, sh = src.get_width(), src.get_height()
    if mode != "slice" or w < 6 or h < 6:
        return src.scale_simple(w, h, interp)
    sl = slice_px or round(min(sw, sh) * 0.25)
    sl = max(1, min(sl, (sw - 1) // 2, (sh - 1) // 2))
    e = max(1, round(sl * unit_h / sh))
    ex, ey = min(e, w // 2), min(e, h // 2)
    xs, ys = [0, sl, sw - sl, sw], [0, sl, sh - sl, sh]
    xd, yd = [0, ex, w - ex, w], [0, ey, h - ey, h]
    dst = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, w, h)
    dst.fill(0)
    for iy in range(3):
        for ix in range(3):
            sx, sy = xs[ix], ys[iy]
            cw, chh = xs[ix + 1] - sx, ys[iy + 1] - sy
            dx, dy = xd[ix], yd[iy]
            dw, dh = xd[ix + 1] - dx, yd[iy + 1] - dy
            if cw <= 0 or chh <= 0 or dw <= 0 or dh <= 0:
                continue
            sub = src.new_subpixbuf(sx, sy, cw, chh)
            sub.scale(dst, dx, dy, dw, dh, dx, dy, dw / cw, dh / chh, interp)
    return dst


# --------------------------------------------------------------------------
# One on-screen key
# --------------------------------------------------------------------------
class KeyButton:
    def __init__(self, spec):
        self.spec = spec
        base = spec["base"]
        self.is_text = len(base) > 1
        self.dual = bool(spec.get("alt")) and not spec.get("letter")
        self.half = spec.get("rs") == 1          # half-height key: small, centred

        self.button = Gtk.Button()
        self.button.set_can_focus(False)
        self.button.get_style_context().add_class("key")
        if spec.get("tip"):
            self.button.set_tooltip_text(spec["tip"])

        self.main = Gtk.Label(label=base)
        self.main.set_ellipsize(Pango.EllipsizeMode.END)
        self.main.get_style_context().add_class(
            "key-half" if self.half else
            ("key-text" if self.is_text else "key-main"))
        if self.half:
            self.main.set_halign(Gtk.Align.CENTER)
            self.main.set_valign(Gtk.Align.CENTER)
        elif self.dual:                          # dual keys: main at the bottom
            self.main.set_halign(Gtk.Align.CENTER)
            self.main.set_valign(Gtk.Align.END)
            self.main.set_margin_bottom(5)
        elif self.is_text:                     # named keys: top-left, like Windows
            self.main.set_halign(Gtk.Align.START)
            self.main.set_valign(Gtk.Align.START)
            self.main.set_margin_start(8)
            self.main.set_margin_top(6)
        else:
            self.main.set_halign(Gtk.Align.CENTER)
            self.main.set_valign(Gtk.Align.CENTER)

        self.alt = Gtk.Label(label="")
        self.alt.get_style_context().add_class("key-alt")
        self.alt.set_halign(Gtk.Align.START)
        self.alt.set_valign(Gtk.Align.START)
        self.alt.set_margin_start(7)
        self.alt.set_margin_top(4)
        self.alt.set_no_show_all(True)
        self.alt.set_visible(False)

        # Stack: keycap image (optional) < tint (hover/active feedback over
        # the image) < main legend < small legend.
        # The cap must be a WINDOWLESS widget (an empty Box, not a DrawingArea):
        # a DrawingArea owns a GdkWindow that sits above the button's event
        # window and swallows the pointer, so only the border strip around it
        # still reached the button (no hover, no click on the key's middle).
        self.cap = Gtk.Box()                     # draws the keycap; has no size of its own
        self.cap.set_size_request(1, 1)
        self.cap.set_no_show_all(True)
        self.cap.set_visible(False)
        self.tint = Gtk.Box()
        self.tint.get_style_context().add_class("key-tint")
        overlay = Gtk.Overlay()
        overlay.add(self.cap)
        for w in (self.tint, self.main, self.alt):
            overlay.add_overlay(w)
            overlay.set_overlay_pass_through(w, True)
        self.button.add(overlay)

        self._shown = (base, None)
        self._classes = set()

    def legends(self, shift, caps, fn_on):
        s = self.spec
        f = s.get("fn")
        if f and fn_on:
            return f[0], None
        if s.get("letter"):
            return (s["alt"] if shift != caps else s["base"]), None
        if self.dual:
            return (s["alt"], s["base"]) if shift else (s["base"], s["alt"])
        return s["base"], None

    def refresh_legends(self, shift, caps, fn_on):
        main, alt = self.legends(shift, caps, fn_on)
        if (main, alt) == self._shown:
            return
        self._shown = (main, alt)
        self.main.set_text(main)
        self.alt.set_text(alt or "")
        self.alt.set_visible(bool(alt))

    def set_cap_active(self, on):
        self.cap.set_visible(on)
        self.set_classes(capped=on)
        self.cap.queue_draw()

    def set_classes(self, **flags):
        ctx = self.button.get_style_context()
        for name, on in flags.items():
            if on and name not in self._classes:
                ctx.add_class(name)
                self._classes.add(name)
            elif not on and name in self._classes:
                ctx.remove_class(name)
                self._classes.discard(name)


# --------------------------------------------------------------------------
# The keyboard window
# --------------------------------------------------------------------------
class OSKewl(Gtk.Window):
    def __init__(self, uin, player):
        super().__init__(title="OSKewl", name="toplevel")
        self.uin = uin
        self.player = player
        self.cfg = load_config()

        self.state = {c: 0 for c in MOD_CODES}      # 0 off · 1 sticky · 2 held
        self.state["fn"] = 0
        self.caps_on = False
        self.num_on = False
        self.faded = False
        self._lock_hold_until = 0.0
        self._px = (22, 14, 13)                     # main / text / alt legend px
        self._css_pending = False
        self._opt = None
        self._numpad_chk = None
        self._layout_cmb = None
        self._delay_src = self._repeat_src = None
        self._repeat_code, self._repeat_mods = None, []
        self.keys, self.by_button, self.numpad_widgets = [], {}, []
        self.wayland = is_wayland()
        self._cap_src, self._cap_cache, self._unit_h = None, {}, 50.0
        self._cols = self._cols_num = 1
        self._units = 1

        self.set_border_width(0)
        self.set_resizable(True)
        self.set_keep_above(True)
        self.set_modal(False)
        self.set_focus_on_map(False)
        self.set_can_focus(False)
        self.set_accept_focus(False)
        self.set_default_size(self.cfg["width"], self.cfg["height"])
        self.set_default_icon_name("preferences-desktop-keyboard")
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual is not None and screen.is_composited():
            # RGBA visual so CSS alpha works. Do NOT set_app_paintable(True):
            # that stops GTK painting the window background at all, which made
            # the gaps between keys transparent whatever the opacity said.
            self.set_visual(visual)

        self.header = Gtk.HeaderBar()
        self.header.set_show_close_button(True)
        self.header.set_decoration_layout(":minimize,maximize,close")
        self._apply_title()
        self.set_titlebar(self.header)

        self.grid = Gtk.Grid()
        self.grid.set_name("grid")
        self.grid.set_row_homogeneous(True)
        self.grid.set_column_homogeneous(True)
        for side in ("start", "end", "top", "bottom"):
            getattr(self.grid, "set_margin_" + side)(4)
        # The background image lives on this box (not the window) so it covers
        # exactly the key area, margins included, and scales with it.
        self.area = Gtk.Box()
        self.area.set_name("kbarea")
        self.area.pack_start(self.grid, True, True, 0)
        # User handlers run before the Box's own draw, so the image is painted
        # first and the keys land on top of it.
        self.area.connect("draw", self._on_bg_draw)
        self.add(self.area)
        self._bg_src, self._bg_cache = None, None
        self._load_bg()
        self._load_keycap()

        self._build_grid()

        self.provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(
            screen, self.provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)
        self.apply_css()

        self.grid.connect("size-allocate", self.on_grid_alloc)
        self.connect("configure-event", self.on_configure)
        GLib.timeout_add(500, self._sync_leds)

    # ------------------------------------------------------------- building
    def _build_grid(self):
        lay = build_layout(self.cfg["layout"], self.wayland)
        self._cols, self._cols_num, self._units = lay.cols, lay.cols_num, lay.units
        self.keys, self.by_button, self.numpad_widgets = [], {}, []
        for spec, col, row, cs, rs, group in lay.keys:
            kb = KeyButton(spec)
            self.keys.append(kb)
            self.by_button[kb.button] = kb
            b = kb.button
            if spec["kind"] == "action":
                b.connect("clicked", self.on_action, kb)
            else:
                b.connect("pressed", self.on_pressed)
                b.connect("released", self.on_released)
                b.connect("leave-notify-event", self.on_released)
                b.connect("touch-event", self.on_touch)
            kb.cap.connect("draw", self._on_cap_draw)
            kb.set_cap_active(self._cap_src is not None)
            self.grid.attach(b, col, row, cs, rs)
            if group == "numpad":
                self.numpad_widgets.append(b)
        # Invisible boxes hold the gaps open: an empty grid column/row collapses.
        for col, row, cs, rs, group in lay.spacers:
            box = Gtk.Box()
            self.grid.attach(box, col, row, cs, rs)
            if group == "numpad":
                self.numpad_widgets.append(box)
        for w in self.numpad_widgets:
            w.show_all()                 # show the labels inside the keys first:
            w.set_no_show_all(True)      # no_show_all would otherwise skip them
        self._apply_cap_opacity()

    # ------------------------------------------------------ background image
    def _load_bg(self):
        self._bg_src, self._bg_cache = None, None
        path = self.cfg["bg_image"]
        if GdkPixbuf is not None and path and os.path.isfile(path):
            try:
                self._bg_src = GdkPixbuf.Pixbuf.new_from_file(path)
            except GLib.GError as e:
                print("Warning: cannot load background image (%s)" % e.message,
                      file=sys.stderr)
        self.area.queue_draw()

    def _bg_alpha(self):
        c = self.cfg
        return min(c["bg_opacity"], 0.35) if self.faded else c["bg_opacity"]

    def _on_bg_draw(self, widget, cr):
        src = self._bg_src
        alpha = self._bg_alpha()
        if src is None or alpha <= 0:
            return False
        w, h = widget.get_allocated_width(), widget.get_allocated_height()
        if w < 2 or h < 2:
            return False
        sw, sh = src.get_width(), src.get_height()
        mode = self.cfg["bg_scale"]
        if mode == "stretch":
            dw, dh = w, h
        else:
            f = (max if mode == "cover" else min)(w / sw, h / sh)
            dw, dh = max(1, round(sw * f)), max(1, round(sh * f))
        key = (dw, dh)
        if self._bg_cache is None or self._bg_cache[0] != key:
            try:
                pb = src.scale_simple(dw, dh, GdkPixbuf.InterpType.BILINEAR)
            except Exception as e:
                print("Warning: background draw failed (%s)" % e, file=sys.stderr)
                return False
            self._bg_cache = (key, pb)
        pb = self._bg_cache[1]
        cr.save()
        cr.rectangle(0, 0, w, h)
        cr.clip()
        Gdk.cairo_set_source_pixbuf(cr, pb, (w - dw) // 2, (h - dh) // 2)
        cr.paint_with_alpha(alpha)      # <- the background-opacity slider
        cr.restore()
        return False

    # ---------------------------------------------------------- keycap image
    def _load_keycap(self):
        self._cap_src, self._cap_cache = None, {}
        path = self.cfg["keycap_image"]
        if GdkPixbuf is None or not path or not os.path.isfile(path):
            return
        try:
            self._cap_src = GdkPixbuf.Pixbuf.new_from_file(path)
        except GLib.GError as e:
            print("Warning: cannot load keycap image (%s)" % e.message,
                  file=sys.stderr)

    def _apply_keycaps(self):
        on = self._cap_src is not None
        for kb in self.keys:
            kb.set_cap_active(on)
        self._apply_cap_opacity()
        self.apply_css()
        self.queue_resize()

    def _apply_cap_opacity(self):
        if self._cap_src is None:
            return
        c = self.cfg
        a = min(c["opacity"], 0.35) if self.faded else c["opacity"]
        for kb in self.keys:
            kb.cap.set_opacity(a)

    def _on_cap_draw(self, widget, cr):
        if self._cap_src is None:
            return False
        w, h = widget.get_allocated_width(), widget.get_allocated_height()
        if w < 2 or h < 2:
            return False
        mode, sl = self.cfg["keycap_mode"], self.cfg["keycap_slice"]
        key = (w, h, mode, sl, int(self._unit_h))
        pb = self._cap_cache.get(key)
        try:
            if pb is None:
                pb = render_keycap(self._cap_src, w, h, mode, sl, self._unit_h)
                if len(self._cap_cache) > 300:
                    self._cap_cache.clear()
                self._cap_cache[key] = pb
            Gdk.cairo_set_source_pixbuf(cr, pb, 0, 0)
            cr.paint()
        except Exception as e:
            print("Warning: keycap draw failed (%s)" % e, file=sys.stderr)
        return False

    def _rerender_caps(self):
        self._cap_cache.clear()
        for kb in self.keys:
            kb.cap.queue_draw()

    def rebuild_layout(self):
        self._cancel_repeat()
        for child in self.grid.get_children():
            self.grid.remove(child)
        self.state["fn"] = 0
        self._build_grid()
        self.grid.show_all()
        self._apply_numpad()
        self.refresh()
        self._px = (0, 0, 0)
        self.queue_resize()

    def _cols_now(self):
        return self._cols_num if self.cfg["numpad"] else self._cols

    def _set_layout(self, name):
        if name not in LAYOUTS or name == self.cfg["layout"]:
            return
        try:
            w, h = self.get_size()
            chrome = h - self.grid.get_allocated_height()
        except Exception:
            chrome = None
        self.cfg["layout"] = name
        save_config(self.cfg)
        self.rebuild_layout()
        if chrome is not None and not self.is_maximized():
            # keep the keys roughly square in the new layout
            body = (w - 8) * 2.0 * self._units / self._cols_now() + 8
            self.resize(w, int(body + chrome))
        if self._layout_cmb is not None:
            self._layout_cmb.set_active_id(name)

    def finish_show(self):
        """Call right after show_all()."""
        self._apply_numpad()
        self._sync_leds(force=True)
        self.refresh()

    def _apply_title(self):
        t = self.cfg["title"]
        self.header.set_title(t)
        self.set_title(t or "OSKewl")

    def _apply_numpad(self):
        for w in self.numpad_widgets:
            w.set_visible(self.cfg["numpad"])

    # ----------------------------------------------------------------- CSS
    def build_css(self):
        c = self.cfg
        a = min(c["opacity"], 0.35) if self.faded else c["opacity"]
        ab = min(c["bg_opacity"], 0.35) if self.faded else c["bg_opacity"]
        bg, key, text, hi = c["bg"], c["key"], c["text"], c["highlight"]
        edge = c["border"]
        hover = mix_hex(key, text, 0.12)
        hi_fg, press_fg = contrast_hex(hi), contrast_hex(text)

        desc = Pango.FontDescription.from_string(c["font"])
        fam = (desc.get_family() or "Sans").split(",")[0]
        fam = re.sub(r'["\\;{}]', "", fam).strip() or "Sans"
        weight = int(desc.get_weight())
        style = "normal" if desc.get_style() == Pango.Style.NORMAL else "italic"

        bw, sp = c["border_px"], c["spacing"]
        lo, hi_m = sp // 2, sp - sp // 2
        m_px, t_px, a_px = self._px
        h_px = max(7, int(t_px * 0.9))
        # The background image is NOT set in CSS: GTK 3 CSS cannot fade an
        # image, so it is painted by _on_bg_draw() with the background opacity.

        return f"""
        #toplevel {{ background-color: {rgba_css(bg, ab)}; }}
        headerbar {{
            background-image: none; background-color: {rgba_css(bg, ab)};
            border: 0px; box-shadow: none;
            min-height: {c["title_h"]}px; padding: 0px 2px; margin: 0px;
        }}
        headerbar .title {{
            color: {text}; font-size: {c["title_px"]}px; padding: 0px;
        }}
        headerbar button {{
            background-image: none; background-color: transparent;
            border: 0px; box-shadow: none; color: {text};
            min-height: 0px; min-width: 0px; padding: 0px 6px; margin: 0px;
        }}
        headerbar button:hover {{ background-color: alpha({text}, 0.15); }}
        #grid {{ background-color: transparent; }}
        #kbarea {{ background-color: transparent; }}

        #grid button.key {{
            background-image: none;
            background-color: {rgba_css(key, a)};
            border: {bw}px solid {rgba_css(edge, a)};
            border-radius: 0px;
            box-shadow: none; text-shadow: none; outline: none;
            padding: 0px;
            margin: {lo}px {hi_m}px {hi_m}px {lo}px;
            min-width: 0px; min-height: 0px;
        }}
        #grid button.key:hover, #grid button.key:focus {{
            background-image: none;
            background-color: {rgba_css(hover, a)};
            border-color: {hi};
        }}
        #grid button.key.latched, #grid button.key.latched:hover {{
            background-color: {rgba_css(hi, a)}; border-color: {hi};
        }}
        #grid button.key.locked, #grid button.key.locked:hover {{
            background-color: {rgba_css(hi, a)}; border-color: {hi};
            box-shadow: inset 0 -4px 0 0 {hi_fg};
        }}
        #grid button.key.pressed, #grid button.key.pressed:hover,
        #grid button.key:active {{
            background-color: {rgba_css(text, a)}; border-color: {text};
        }}

        /* keycap image supplies the key face; tint gives state feedback over it */
        #grid button.key.capped, #grid button.key.capped:hover,
        #grid button.key.capped:focus, #grid button.key.capped:active,
        #grid button.key.capped.latched, #grid button.key.capped.latched:hover,
        #grid button.key.capped.locked, #grid button.key.capped.locked:hover,
        #grid button.key.capped.pressed, #grid button.key.capped.pressed:hover {{
            background-image: none; background-color: transparent;
            border-color: transparent; box-shadow: none;
        }}
        #grid button.key .key-tint {{ background-color: transparent; }}
        #grid button.key.capped:hover .key-tint {{
            background-color: alpha({hi}, 0.28);
        }}
        #grid button.key.capped.latched .key-tint,
        #grid button.key.capped.locked .key-tint {{
            background-color: alpha({hi}, 0.65);
        }}
        #grid button.key.capped.locked .key-tint {{
            box-shadow: inset 0 -4px 0 0 {hi_fg};
        }}
        #grid button.key.capped.pressed .key-tint,
        #grid button.key.capped:active .key-tint {{
            background-color: alpha({text}, 0.55);
        }}

        #grid button.key label {{
            color: {text}; font-family: "{fam}";
            font-weight: {weight}; font-style: {style};
        }}
        #grid button.key label.key-main {{ font-size: {m_px}px; }}
        #grid button.key label.key-text {{ font-size: {t_px}px; }}
        #grid button.key label.key-half {{ font-size: {h_px}px; }}
        #grid button.key label.key-alt {{
            font-size: {a_px}px; color: alpha({text}, 0.55);
        }}
        #grid button.key.latched label, #grid button.key.locked label {{
            color: {hi_fg};
        }}
        #grid button.key.latched label.key-alt,
        #grid button.key.locked label.key-alt {{
            color: alpha({hi_fg}, 0.6);
        }}
        #grid button.key.pressed label, #grid button.key:active label {{
            color: {press_fg};
        }}
        #grid button.key.pressed label.key-alt,
        #grid button.key:active label.key-alt {{
            color: alpha({press_fg}, 0.6);
        }}
        """

    def apply_css(self):
        try:
            self.provider.load_from_data(self.build_css().encode("utf-8"))
        except GLib.GError as e:
            print("CSS error: %s" % e.message, file=sys.stderr)
        self._apply_cap_opacity()
        self.area.queue_draw()          # background image follows opacity / fade / scaling

    def _schedule_css(self):
        if not self._css_pending:
            self._css_pending = True
            GLib.idle_add(self._css_idle)

    def _css_idle(self):
        self._css_pending = False
        self.apply_css()
        return False

    def on_grid_alloc(self, grid, alloc):
        """Scale the legends with the keys so resizing the window stays tidy."""
        key_px = max(10.0, min(4.0 * alloc.width / self._cols_now(),
                               2.0 * alloc.height / self._units))
        self._unit_h = 2.0 * alloc.height / self._units
        s = self.cfg["font_scale"] / 100.0
        px = (max(8, int(key_px * 0.34 * s)), max(7, int(key_px * 0.21 * s)),
              max(7, int(key_px * 0.20 * s)))
        if px != self._px:
            self._px = px
            self._schedule_css()

    def on_configure(self, widget, event):
        if not self.is_maximized():
            self.cfg["width"], self.cfg["height"] = self.get_size()
        return False

    # ------------------------------------------------------ state → visuals
    def refresh(self):
        shift = any(self.state[c] for c in SHIFT_CODES)
        fn_on = bool(self.state["fn"])
        for kb in self.keys:
            kb.refresh_legends(shift, self.caps_on, fn_on)
            kind = kb.spec["kind"]
            if kind == "mod":
                st = self.state[kb.spec["code"]]
            elif kind == "fn":
                st = self.state["fn"]
            else:
                st = 0
            on = (kind == "caps" and self.caps_on) or \
                 (kind == "numlock" and self.num_on)
            kb.set_classes(latched=(st == 1) or on, locked=(st == 2))

    def _sync_leds(self, force=False):
        """Follow the real Caps/Num Lock LEDs so labels stay right when a
        physical keyboard toggles them. No LED exposed → local tracking only."""
        if force or GLib.get_monotonic_time() / 1e6 >= self._lock_hold_until:
            changed = False
            for attr, name in (("caps_on", "capslock"), ("num_on", "numlock")):
                v = read_led(name)
                if v is not None and v != getattr(self, attr):
                    setattr(self, attr, v)
                    changed = True
            if changed:
                self.refresh()
        return True

    # ------------------------------------------------------------ key input
    def play(self):
        if self.cfg["sound"]:
            self.player.play(self.cfg["sound_file"], self.cfg["sound_preset"])

    def on_pressed(self, widget):
        kb = self.by_button[widget]
        kind = kb.spec["kind"]
        self.play()
        if kind in ("mod", "fn"):
            self.cycle_modifier(kb)
        elif kind in ("caps", "numlock"):
            self.toggle_lock(kind)
        else:
            kb.set_classes(pressed=True)
            self.type_key(kb)
            self._cancel_repeat()
            self._delay_src = GLib.timeout_add(400, self._start_repeat)

    def on_released(self, widget, *args):
        self._cancel_repeat()
        kb = self.by_button.get(widget)
        if kb is not None:
            kb.set_classes(pressed=False)
        return False

    def on_touch(self, widget, event):
        # A cancelled touch fires neither "released" nor leave-notify, which
        # would leave the key stuck highlighted — treat it as a release.
        if event.type in (Gdk.EventType.TOUCH_END, Gdk.EventType.TOUCH_CANCEL):
            self.on_released(widget)
            widget.set_state_flags(Gtk.StateFlags.NORMAL, True)
        return False

    def type_key(self, kb):
        code = kb.spec["code"]
        fn = kb.spec.get("fn")
        if fn and self.state["fn"]:
            code = fn[1]
        sticky = [m for m in MOD_CODES if self.state[m] == 1]
        self.uin.tap(code, sticky)
        self._repeat_code, self._repeat_mods = code, sticky
        for m in list(self.state):                    # sticky keys fire once
            if self.state[m] == 1:
                self.state[m] = 0
        self.refresh()

    def _start_repeat(self):
        self._delay_src = None
        self._repeat_src = GLib.timeout_add(100, self._repeat_tick)
        return False

    def _repeat_tick(self):
        self.uin.tap(self._repeat_code, self._repeat_mods)
        self.play()
        return True

    def _cancel_repeat(self):
        for attr in ("_delay_src", "_repeat_src"):
            src = getattr(self, attr)
            if src:
                GLib.source_remove(src)
                setattr(self, attr, None)

    def cycle_modifier(self, kb):
        key = "fn" if kb.spec["kind"] == "fn" else kb.spec["code"]
        old = self.state[key]
        new = (old + 1) % 3
        self.state[key] = new
        if key != "fn":                 # "held" = really holding the key down
            if new == 2:
                self.uin.emit(key, 1)
            elif old == 2:
                self.uin.emit(key, 0)
        self.refresh()

    def toggle_lock(self, which):
        if which == "caps":
            self.caps_on = not self.caps_on
            code = KEY["CAPSLOCK"]
        else:
            self.num_on = not self.num_on
            code = KEY["NUMLOCK"]
        self._lock_hold_until = GLib.get_monotonic_time() / 1e6 + 0.8
        self.uin.tap(code)
        self.refresh()

    # ------------------------------------------------- OSK-specific keys
    def on_action(self, widget, kb):
        self.play()
        {"mvup": lambda: self._nudge(-1),
         "mvdn": lambda: self._nudge(1),
         "dock": self.dock,
         "options": self.show_options,
         "fade": self.toggle_fade,
         "numpad": self.toggle_numpad,
         "layout": self.toggle_layout}[kb.spec["action"]]()

    def set_numpad(self, on):
        if on == self.cfg["numpad"]:
            return
        self.cfg["numpad"] = on
        self._apply_numpad()
        if self._numpad_chk is not None:
            self._numpad_chk.set_active(on)
        save_config(self.cfg)

    def toggle_numpad(self):
        self.set_numpad(not self.cfg["numpad"])

    def toggle_layout(self):
        new = "standard" if self.cfg["layout"] == "windows" else "windows"
        GLib.idle_add(self._set_layout, new)   # after this key's click finishes

    def toggle_fade(self):
        self.faded = not self.faded
        self.apply_css()

    def _nudge(self, direction):
        try:
            x, y = self.get_position()
            self.move(x, y + direction * max(40, self.get_size()[1] // 3))
        except Exception:
            pass

    def dock(self):
        try:
            mon = Gdk.Display.get_default().get_monitor_at_window(self.get_window())
            geo = mon.get_workarea()
            w, h = self.get_size()
            self.move(geo.x + (geo.width - w) // 2, geo.y + geo.height - h)
        except Exception:
            pass

    # ------------------------------------------------------------- options
    def _set(self, key, value):
        self.cfg[key] = value
        if key == "font_scale":
            self._px = (0, 0, 0)             # force a recompute on next allocate
            self.queue_resize()
        if key == "title":
            self._apply_title()
        if key == "bg_image":
            self._load_bg()
        if key == "keycap_image":
            self._load_keycap()
            self._apply_keycaps()
        elif key in ("keycap_mode", "keycap_slice"):
            self._rerender_caps()
        self.apply_css()
        save_config(self.cfg)

    def _screen_height(self):
        try:
            d = Gdk.Display.get_default()
            gw = self.get_window()
            m = (d.get_monitor_at_window(gw) if gw is not None
                 else (d.get_primary_monitor() or d.get_monitor(0)))
            return m.get_geometry().height
        except Exception:
            return 768

    def show_options(self):
        if self._opt is not None:
            self._opt.present()
            return
        dlg = Gtk.Dialog(title="Keyboard Options", transient_for=self, flags=0)
        dlg.add_button("Reset to defaults", Gtk.ResponseType.REJECT)
        dlg.add_button("Close", Gtk.ResponseType.CLOSE)
        grid = Gtk.Grid(column_spacing=12, row_spacing=8, margin=16)
        # Scrollable so every option stays reachable on short screens; the
        # Reset / Close buttons live outside it and are always visible.
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        sw.set_min_content_height(120)
        sw.set_vexpand(True)
        sw.add(grid)
        dlg.get_content_area().pack_start(sw, True, True, 0)
        dlg.set_default_size(700, min(680, max(260, self._screen_height() - 160)))
        row = [0]

        def heading(text):
            lbl = Gtk.Label(xalign=0)
            lbl.set_markup("<b>%s</b>" % text)
            lbl.set_margin_top(6 if row[0] else 0)
            grid.attach(lbl, 0, row[0], 2, 1)
            row[0] += 1

        def add(label, widget):
            if label:
                grid.attach(Gtk.Label(label=label, xalign=0), 0, row[0], 1, 1)
                widget.set_hexpand(True)
                grid.attach(widget, 1, row[0], 1, 1)
            else:
                grid.attach(widget, 0, row[0], 2, 1)
            row[0] += 1

        def spin(key, lo, hi, step=1):
            sb = Gtk.SpinButton.new_with_range(lo, hi, step)
            sb.set_value(self.cfg[key])
            sb.connect("value-changed", lambda w: self._set(key, int(w.get_value())))
            return sb

        def color(key):
            b = Gtk.ColorButton.new_with_rgba(hex_to_rgba(self.cfg[key]))
            b.connect("color-set",
                      lambda w: self._set(key, rgba_to_hex(w.get_rgba())))
            return b

        heading("Layout")
        lc = Gtk.ComboBoxText()
        for lid, lname in LAYOUTS.items():
            lc.append(lid, lname)
        lc.set_active_id(self.cfg["layout"])
        lc.connect("changed", lambda w: self._set_layout(w.get_active_id()))
        self._layout_cmb = lc
        add("Keyboard layout", lc)
        chk = Gtk.CheckButton(label="Show numeric keypad")
        chk.set_active(self.cfg["numpad"])
        chk.connect("toggled", lambda w: self.set_numpad(w.get_active()))
        self._numpad_chk = chk
        add(None, chk)

        heading("Keys")
        add("Border thickness (px)", spin("border_px", 0, 8))
        add("Key spacing (px)", spin("spacing", 0, 16))
        fb = Gtk.FontButton.new_with_font(self.cfg["font"])
        fb.set_use_font(True)
        fb.set_show_size(False)
        fb.connect("font-set", lambda w: self._set("font", w.get_font()))
        add("Legend font", fb)
        add("Legend size (%)", spin("font_scale", 50, 200, 5))

        heading("Colours")
        add("Background", color("bg"))
        add("Key", color("key"))
        add("Text", color("text"))
        add("Key border", color("border"))
        add("Sticky / held highlight", color("highlight"))
        sc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 20, 100, 5)
        sc.set_value(self.cfg["opacity"] * 100)
        sc.set_digits(0)
        sc.connect("value-changed",
                   lambda w: self._set("opacity", round(w.get_value() / 100, 2)))
        add("Key opacity (%)", sc)
        sb = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 5)
        sb.set_value(self.cfg["bg_opacity"] * 100)
        sb.set_digits(0)
        sb.set_tooltip_text("Window background and the gaps between keys")
        sb.connect("value-changed",
                   lambda w: self._set("bg_opacity", round(w.get_value() / 100, 2)))
        add("Background opacity (%)", sb)

        heading("Images (PNG / JPEG)")

        def image_picker(key):
            box = Gtk.Box(spacing=6)
            btn, clr = Gtk.Button(), Gtk.Button(label="Clear")
            btn.set_hexpand(True)

            def lab():
                f = self.cfg[key]
                btn.set_label(os.path.basename(f) if f and os.path.isfile(f)
                              else "Choose an image…")
            lab()

            def pick(_w):
                d = Gtk.FileChooserDialog(title="Choose a PNG or JPEG image",
                                          transient_for=dlg,
                                          action=Gtk.FileChooserAction.OPEN)
                d.add_button("Cancel", Gtk.ResponseType.CANCEL)
                d.add_button("Open", Gtk.ResponseType.ACCEPT)
                flt = Gtk.FileFilter()
                flt.set_name("PNG / JPEG images")
                flt.add_mime_type("image/png")
                flt.add_mime_type("image/jpeg")
                d.add_filter(flt)
                cur = self.cfg[key]
                d.set_current_folder(os.path.dirname(cur) if cur and os.path.isfile(cur)
                                     else os.path.expanduser("~"))
                if d.run() == Gtk.ResponseType.ACCEPT and d.get_filename():
                    self._set(key, d.get_filename())
                    lab()
                d.destroy()

            def clear(_w):
                self._set(key, "")
                lab()
            btn.connect("clicked", pick)
            clr.connect("clicked", clear)
            box.pack_start(btn, True, True, 0)
            box.pack_start(clr, False, False, 0)
            return box

        def combo_for(key, choices):
            cb = Gtk.ComboBoxText()
            for cid, text in choices:
                cb.append(cid, text)
            cb.set_active_id(self.cfg[key])
            cb.connect("changed", lambda w: self._set(key, w.get_active_id()))
            return cb

        add("Background image", image_picker("bg_image"))
        add("Background scaling", combo_for("bg_scale", [
            ("cover", "Fill (keep proportions, crop)"),
            ("stretch", "Stretch to window"),
            ("contain", "Fit (keep proportions, letterbox)")]))
        add("Keycap image", image_picker("keycap_image"))
        add("Keycap scaling", combo_for("keycap_mode", [
            ("slice", "Keep edges, stretch middle (9-slice)"),
            ("stretch", "Stretch whole image")]))
        add("Keycap edge size (image px, 0 = auto)", spin("keycap_slice", 0, 400))
        if GdkPixbuf is None:
            add(None, Gtk.Label(xalign=0, label="GdkPixbuf is not available — "
                                "keycap images are disabled."))

        heading("Title bar")
        ent = Gtk.Entry()
        ent.set_text(self.cfg["title"])
        ent.set_placeholder_text("(no title)")
        ent.connect("changed", lambda w: self._set("title", w.get_text()))
        add("Title text", ent)
        tbox = Gtk.Box(spacing=6)
        t_default = Gtk.Button(label="Reset to default")
        t_default.set_tooltip_text('Set the title back to "%s"' % DEFAULTS["title"])
        t_default.connect("clicked", lambda w: ent.set_text(DEFAULTS["title"]))
        t_blank = Gtk.Button(label="Blank")
        t_blank.set_tooltip_text("Remove the title text entirely")
        t_blank.connect("clicked", lambda w: ent.set_text(""))
        for b in (t_default, t_blank):
            b.set_relief(Gtk.ReliefStyle.NORMAL)
            tbox.pack_start(b, False, False, 0)
        add(None, tbox)
        note = Gtk.Label(xalign=0)
        note.set_line_wrap(True)
        note.set_max_width_chars(70)
        note.set_markup(
            "<small><b>Note:</b> this box usually can't be typed into while "
            "OSKewl is running, because the keyboard deliberately never takes "
            "focus (required for it to work correctly in Plasma). To set a "
            "custom title, close OSKewl and edit the <tt>title =</tt> line in "
            "<tt>%s</tt> by hand — the file is rewritten on exit, so edit it "
            "while OSKewl is closed. The buttons above work normally.</small>"
            % GLib.markup_escape_text(CONFIG_FILE))
        add(None, note)
        add("Title text size (px)", spin("title_px", 8, 24))
        add("Title bar height (px)", spin("title_h", 18, 60))

        heading("Sound")
        snd = Gtk.CheckButton(label="Play a click on every key")
        snd.set_active(self.cfg["sound"])
        snd.connect("toggled", lambda w: self._set("sound", w.get_active()))
        add(None, snd)
        # A plain button that opens a file dialog on demand. (GtkFileChooserButton
        # builds its dialog eagerly, starting in a location GTK can't measure,
        # which logs "Failed to measure available space".)
        fc = Gtk.Button()

        def fc_label():
            f = self.cfg["sound_file"]
            fc.set_label(os.path.basename(f) if f and os.path.isfile(f)
                         else "Choose a file…")
        fc_label()

        def pick_file(_w):
            d = Gtk.FileChooserDialog(title="Choose a click sound",
                                      transient_for=dlg,
                                      action=Gtk.FileChooserAction.OPEN)
            d.add_button("Cancel", Gtk.ResponseType.CANCEL)
            d.add_button("Open", Gtk.ResponseType.ACCEPT)
            flt = Gtk.FileFilter()
            flt.set_name("Audio files (wav, ogg, flac…)")
            flt.add_mime_type("audio/*")
            d.add_filter(flt)
            cur = self.cfg["sound_file"]
            d.set_current_folder(os.path.dirname(cur) if cur and os.path.isfile(cur)
                                 else os.path.expanduser("~"))
            if d.run() == Gtk.ResponseType.ACCEPT and d.get_filename():
                self._set("sound_file", d.get_filename())
                fc_label()
            d.destroy()
        fc.connect("clicked", pick_file)

        combo = Gtk.ComboBoxText()
        for sid, sp in SOUNDS.items():
            combo.append(sid, sp["label"])
        combo.set_active_id(self.cfg["sound_preset"])

        def on_preset(w):
            self._set("sound_file", "")          # picking a built-in drops the custom file
            fc_label()
            self._set("sound_preset", w.get_active_id())
            self.player.play("", self.cfg["sound_preset"])
        combo.connect("changed", on_preset)
        add("Built-in sound", combo)

        add("Custom file (optional)", fc)
        btns = Gtk.Box(spacing=8)
        builtin = Gtk.Button(label="Use built-in sound")

        def use_builtin(_w):
            self._set("sound_file", "")
            fc_label()
        builtin.connect("clicked", use_builtin)
        test = Gtk.Button(label="Test")
        test.connect("clicked", lambda w: self.player.play(
            self.cfg["sound_file"], self.cfg["sound_preset"]))
        btns.pack_start(builtin, False, False, 0)
        btns.pack_start(test, False, False, 0)
        add(None, btns)
        if not self.player.cmd:
            note = Gtk.Label(xalign=0, label="No audio player found "
                             "(pw-play, paplay or aplay) — sound is unavailable.")
            add(None, note)

        def on_response(d, resp):
            if resp == Gtk.ResponseType.REJECT:
                keep = {k: self.cfg[k] for k in ("width", "height")}
                self.cfg = dict(DEFAULTS)
                self.cfg.update(keep)
                self._apply_title()
                self._load_bg()
                self._load_keycap()
                self.rebuild_layout()
                self.apply_css()
                save_config(self.cfg)
                d.destroy()
                GLib.idle_add(self.show_options)
            else:
                d.destroy()

        def on_destroy(_d):
            self._opt = None
            self._numpad_chk = None
            self._layout_cmb = None

        dlg.connect("response", on_response)
        dlg.connect("destroy", on_destroy)
        self._opt = dlg
        dlg.show_all()

    # ------------------------------------------------------------ shutdown
    def on_destroy(self, *_):
        self._cancel_repeat()
        for m in MOD_CODES:                  # never leave a key stuck down
            if self.state[m] == 2:
                self.uin.emit(m, 0)
        save_config(self.cfg)
        self.uin.close()
        Gtk.main_quit()


def main():
    GLib.set_prgname("oskewl")
    GLib.set_application_name("OSKewl")
    try:
        uin = UInput(sorted(set(KEY.values())))
    except OSError as e:
        msg = ("Could not open /dev/uinput (%s).\n\nOSKewl needs write "
               "access to /dev/uinput (input group + udev rule)." % e)
        print(msg, file=sys.stderr)
        d = Gtk.MessageDialog(message_type=Gtk.MessageType.ERROR,
                              buttons=Gtk.ButtonsType.CLOSE,
                              text="OSKewl is unavailable")
        d.format_secondary_text(msg)
        d.run()
        return 1
    win = OSKewl(uin, ClickPlayer())
    win.connect("destroy", win.on_destroy)
    win.show_all()
    win.finish_show()
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
