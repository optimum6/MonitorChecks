"""
Monitor Check - a second-hand monitor inspection tool (Windows).

Flow:  Home (history)  ->  Hardware info  ->  Automatic checks  ->
       Fullscreen visual checks (Y / N)  ->  Report (saved to history)

Only the Python standard library is used, so it packages into one small .exe.
"""
import colorsys
import ctypes
import datetime
import json
import math
import os
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
import winreg
from ctypes import wintypes
from tkinter import filedialog, messagebox, ttk

APP_NAME = "Monitor Check"
FONT = "Segoe UI"

# ----------------------------------------------------------------- theme ----
BG = "#12141a"
PANEL = "#1c1f29"
PANEL2 = "#262b3a"
FG = "#e8eaf0"
MUTED = "#8b93a7"
ACCENT = "#4f8cff"
GOOD = "#3ecf8e"
BAD = "#ff5c6c"
WARN = "#f5b942"

# ------------------------------------------------------------- Win32 API ----
try:  # real pixel coordinates, no DPI virtualisation (must happen before Tk())
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

user32 = ctypes.windll.user32
dxva2 = ctypes.windll.dxva2
dwmapi = ctypes.windll.dwmapi


class DEVMODEW(ctypes.Structure):
    _fields_ = [
        ("dmDeviceName", wintypes.WCHAR * 32),
        ("dmSpecVersion", wintypes.WORD),
        ("dmDriverVersion", wintypes.WORD),
        ("dmSize", wintypes.WORD),
        ("dmDriverExtra", wintypes.WORD),
        ("dmFields", wintypes.DWORD),
        ("dmPositionX", wintypes.LONG),
        ("dmPositionY", wintypes.LONG),
        ("dmDisplayOrientation", wintypes.DWORD),
        ("dmDisplayFixedOutput", wintypes.DWORD),
        ("dmColor", ctypes.c_short),
        ("dmDuplex", ctypes.c_short),
        ("dmYResolution", ctypes.c_short),
        ("dmTTOption", ctypes.c_short),
        ("dmCollate", ctypes.c_short),
        ("dmFormName", wintypes.WCHAR * 32),
        ("dmLogPixels", wintypes.WORD),
        ("dmBitsPerPel", wintypes.DWORD),
        ("dmPelsWidth", wintypes.DWORD),
        ("dmPelsHeight", wintypes.DWORD),
        ("dmDisplayFlags", wintypes.DWORD),
        ("dmDisplayFrequency", wintypes.DWORD),
        ("dmICMMethod", wintypes.DWORD),
        ("dmICMIntent", wintypes.DWORD),
        ("dmMediaType", wintypes.DWORD),
        ("dmDitherType", wintypes.DWORD),
        ("dmReserved1", wintypes.DWORD),
        ("dmReserved2", wintypes.DWORD),
        ("dmPanningWidth", wintypes.DWORD),
        ("dmPanningHeight", wintypes.DWORD),
    ]


class DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("DeviceName", wintypes.WCHAR * 32),
        ("DeviceString", wintypes.WCHAR * 128),
        ("StateFlags", wintypes.DWORD),
        ("DeviceID", wintypes.WCHAR * 128),
        ("DeviceKey", wintypes.WCHAR * 128),
    ]


class PHYSICAL_MONITOR(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("hPhysicalMonitor", wintypes.HANDLE),
        ("szPhysicalMonitorDescription", wintypes.WCHAR * 128),
    ]


user32.EnumDisplaySettingsW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(DEVMODEW)]
user32.EnumDisplayDevicesW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                       ctypes.POINTER(DISPLAY_DEVICEW), wintypes.DWORD]
user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
user32.MonitorFromPoint.restype = wintypes.HANDLE
dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
dxva2.GetPhysicalMonitorsFromHMONITOR.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                  ctypes.POINTER(PHYSICAL_MONITOR)]
dxva2.DestroyPhysicalMonitors.argtypes = [wintypes.DWORD, ctypes.POINTER(PHYSICAL_MONITOR)]
dxva2.GetVCPFeatureAndVCPFeatureReply.argtypes = [wintypes.HANDLE, wintypes.BYTE,
                                                  ctypes.POINTER(wintypes.DWORD),
                                                  ctypes.POINTER(wintypes.DWORD),
                                                  ctypes.POINTER(wintypes.DWORD)]

ENUM_CURRENT_SETTINGS = 0xFFFFFFFF
NO_WINDOW = 0x08000000


def _mode(device, index):
    dm = DEVMODEW()
    dm.dmSize = ctypes.sizeof(DEVMODEW)
    if user32.EnumDisplaySettingsW(device, index, ctypes.byref(dm)):
        return dm
    return None


def list_modes(device):
    """All (width, height, hz, bpp) modes the adapter offers for this display."""
    modes, i = set(), 0
    while True:
        dm = _mode(device, i)
        if dm is None:
            break
        modes.add((dm.dmPelsWidth, dm.dmPelsHeight, dm.dmDisplayFrequency, dm.dmBitsPerPel))
        i += 1
    return modes


# ------------------------------------------------------------------ EDID ----
MANUFACTURERS = {
    "ACR": "Acer", "AOC": "AOC", "AUS": "ASUS", "BNQ": "BenQ", "DEL": "Dell",
    "GSM": "LG", "HWP": "HP", "HPN": "HP", "LEN": "Lenovo", "MSI": "MSI",
    "GBT": "Gigabyte", "PHL": "Philips", "SAM": "Samsung", "SNY": "Sony",
    "VSC": "ViewSonic", "NEC": "NEC", "IVM": "iiyama", "EIZ": "EIZO",
    "MEI": "Panasonic", "CMN": "Chimei Innolux (panel)", "BOE": "BOE (panel)",
    "LGD": "LG Display (panel)", "SDC": "Samsung Display (panel)",
    "AUO": "AU Optronics (panel)", "APP": "Apple", "TOS": "Toshiba",
    "ENC": "EIZO", "SHP": "Sharp", "MSI ": "MSI", "XMI": "Xiaomi",
    "KOG": "Koninklijke Philips", "HKC": "HKC", "KSI": "KTC", "TCL": "TCL",
}


def _registry_edid(code, inst):
    base = r"SYSTEM\CurrentControlSet\Enum\DISPLAY\%s" % code
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            base + "\\" + inst + "\\Device Parameters") as k:
            return bytes(winreg.QueryValueEx(k, "EDID")[0])
    except OSError:
        pass
    try:  # fall back to any instance of this monitor type that has an EDID
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as k:
            i = 0
            while True:
                sub = winreg.EnumKey(k, i)
                i += 1
                try:
                    with winreg.OpenKey(k, sub + "\\Device Parameters") as p:
                        return bytes(winreg.QueryValueEx(p, "EDID")[0])
                except OSError:
                    continue
    except OSError:
        pass
    return None


def parse_edid(d):
    if not d or len(d) < 128 or d[:8] != b"\x00\xff\xff\xff\xff\xff\xff\x00":
        return None
    v = (d[8] << 8) | d[9]
    mfr = "".join(chr(((v >> s) & 31) + 64) for s in (10, 5, 0))
    e = {
        "mfr_code": mfr,
        "manufacturer": MANUFACTURERS.get(mfr, mfr),
        "product_code": d[10] | (d[11] << 8),
        "serial_num": int.from_bytes(d[12:16], "little"),
        "week": d[16],
        "year": d[17] + 1990,
        "version": "%d.%d" % (d[18], d[19]),
        "digital": bool(d[20] & 0x80),
        "w_cm": d[21], "h_cm": d[22],
        "gamma": (d[23] + 100) / 100 if d[23] != 255 else None,
        "ext": d[126],
        "name": None, "serial_text": None,
        "native": None, "size_mm": None, "vrange": None, "hrange": None,
    }
    blocks = [d[i:i + 128] for i in range(0, len(d), 128)]
    e["checksum_ok"] = all(len(b) == 128 and sum(b) % 256 == 0 for b in blocks)
    for off in (54, 72, 90, 108):
        b = d[off:off + 18]
        if b[0] == 0 and b[1] == 0:
            tag = b[3]
            text = b[5:18].split(b"\n")[0].decode("cp437", "ignore").strip()
            if tag == 0xFC:
                e["name"] = text
            elif tag == 0xFF:
                e["serial_text"] = text
            elif tag == 0xFD:
                min_v, max_v, min_h, max_h = b[5], b[6], b[7], b[8]
                if b[4] & 0x03 == 0x03:
                    min_v += 255; max_v += 255
                elif b[4] & 0x03 == 0x02:
                    max_v += 255
                if b[4] & 0x0C == 0x0C:
                    min_h += 255; max_h += 255
                elif b[4] & 0x0C == 0x08:
                    max_h += 255
                e["vrange"] = (min_v, max_v)
                e["hrange"] = (min_h, max_h)
        elif e["native"] is None:
            pclk = (b[0] | (b[1] << 8)) * 10000
            ha = b[2] | ((b[4] & 0xF0) << 4)
            hb = b[3] | ((b[4] & 0x0F) << 8)
            va = b[5] | ((b[7] & 0xF0) << 4)
            vb = b[6] | ((b[7] & 0x0F) << 8)
            if ha and va and (ha + hb) and (va + vb):
                hz = pclk / ((ha + hb) * (va + vb))
                e["native"] = (ha, va, round(hz, 1))
                wmm = b[12] | ((b[14] & 0xF0) << 4)
                hmm = b[13] | ((b[14] & 0x0F) << 8)
                if wmm and hmm:
                    e["size_mm"] = (wmm, hmm)
    return e


def diagonal_inches(e):
    if not e:
        return None
    if e["size_mm"]:
        w, h = e["size_mm"]
        return math.hypot(w, h) / 25.4
    if e["w_cm"] and e["h_cm"]:
        return math.hypot(e["w_cm"], e["h_cm"]) / 2.54
    return None


# --------------------------------------------------- monitor enumeration ----
def enum_monitors():
    """Every monitor currently attached to the desktop."""
    out = []
    i = 0
    while True:
        ad = DISPLAY_DEVICEW()
        ad.cb = ctypes.sizeof(ad)
        if not user32.EnumDisplayDevicesW(None, i, ctypes.byref(ad), 0):
            break
        i += 1
        if not ad.StateFlags & 0x1:  # attached to desktop
            continue
        cur = _mode(ad.DeviceName, ENUM_CURRENT_SETTINGS)
        if cur is None:
            continue
        rect = (cur.dmPositionX, cur.dmPositionY, cur.dmPelsWidth, cur.dmPelsHeight)
        j = 0
        while True:
            md = DISPLAY_DEVICEW()
            md.cb = ctypes.sizeof(md)
            if not user32.EnumDisplayDevicesW(ad.DeviceName, j, ctypes.byref(md), 1):
                break
            idx = j
            j += 1
            if not md.StateFlags & 0x1:
                continue
            m = re.match(r"^\\\\\?\\DISPLAY#([^#]+)#([^#]+)#", md.DeviceID, re.I)
            code, inst = (m.group(1), m.group(2)) if m else (None, None)
            mon = {
                "device": ad.DeviceName, "adapter": ad.DeviceString,
                "string": md.DeviceString, "interface": md.DeviceID,
                "hwid": code, "inst": inst, "index": idx,
                "rect": rect, "primary": bool(ad.StateFlags & 0x4),
                "cur": (cur.dmPelsWidth, cur.dmPelsHeight,
                        cur.dmDisplayFrequency, cur.dmBitsPerPel),
            }
            raw = _registry_edid(code, inst) if code else None
            mon["edid"] = parse_edid(raw)
            out.append(mon)
    return out


def monitor_label(m, n):
    e = m["edid"]
    name = (e and e["name"]) or (e and e["mfr_code"] + " monitor") or m["string"]
    w, h = m["rect"][2], m["rect"][3]
    return "Display %d: %s  (%d x %d%s)" % (n, name, w, h, ", primary" if m["primary"] else "")


VIDEO_OUTPUT = {
    -1: "Unknown", 0: "VGA (analogue)", 1: "S-Video", 2: "Composite", 3: "Component",
    4: "DVI", 5: "HDMI", 6: "LVDS (internal)", 8: "D-Jpn", 9: "SDI",
    10: "DisplayPort", 11: "DisplayPort (embedded)", 12: "UDI", 13: "UDI (embedded)",
    14: "SDTV dongle", 15: "Miracast", 16: "Indirect wired", 2147483648: "Internal",
}
_WMI_CACHE = None


def wmi_connections():
    """{ 'DISPLAY\\XXX1234\\inst': technology } via WMI (one PowerShell call)."""
    global _WMI_CACHE
    if _WMI_CACHE is not None:
        return _WMI_CACHE
    result = {}
    try:
        cmd = ("Get-CimInstance -Namespace root\\wmi -ClassName WmiMonitorConnectionParams | "
               "ForEach-Object { $_.InstanceName + '|' + $_.VideoOutputTechnology }")
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
                           capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW)
        for line in r.stdout.splitlines():
            if "|" in line:
                name, tech = line.rsplit("|", 1)
                try:
                    result[name.strip().upper()] = int(tech)
                except ValueError:
                    pass
    except Exception:
        pass
    _WMI_CACHE = result
    return result


def connection_for(mon):
    if not mon["hwid"]:
        return None
    key = ("DISPLAY\\%s\\%s" % (mon["hwid"], mon["inst"])).upper()
    for name, tech in wmi_connections().items():
        if name.startswith(key):
            return VIDEO_OUTPUT.get(tech, "Other (%d)" % tech)
    return None


PANEL_TECH = {1: "CRT (shadow mask)", 2: "CRT (aperture grille)", 3: "TFT LCD",
              4: "LCD", 5: "OLED", 6: "EL", 7: "MEM"}


def ddc_read(mon):
    """Read what the monitor reports over DDC/CI. Returns None if it won't talk."""
    x, y, w, h = mon["rect"]
    hmon = user32.MonitorFromPoint(wintypes.POINT(x + w // 2, y + h // 2), 0)
    if not hmon:
        return None
    n = wintypes.DWORD()
    if not dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR(hmon, ctypes.byref(n)) or n.value == 0:
        return None
    arr = (PHYSICAL_MONITOR * n.value)()
    if not dxva2.GetPhysicalMonitorsFromHMONITOR(hmon, n.value, arr):
        return None
    try:
        handle = arr[min(mon["index"], n.value - 1)].hPhysicalMonitor

        def vcp(code):
            t, cur, mx = wintypes.DWORD(), wintypes.DWORD(), wintypes.DWORD()
            if dxva2.GetVCPFeatureAndVCPFeatureReply(handle, code, ctypes.byref(t),
                                                     ctypes.byref(cur), ctypes.byref(mx)):
                return cur.value, mx.value
            return None

        probe = vcp(0x10)  # brightness - near-universal
        if probe is None:
            return None
        info = {"brightness": probe}
        for key, code in (("contrast", 0x12), ("hours", 0xC0), ("firmware", 0xC9),
                          ("tech", 0xB6), ("mccs", 0xDF)):
            info[key] = vcp(code)
        return info
    finally:
        dxva2.DestroyPhysicalMonitors(n.value, arr)


def measure_refresh(seconds=1.5):
    """Measure how often the desktop compositor presents frames (Hz)."""
    try:
        flush = dwmapi.DwmFlush
        flush()
        n, t0 = 0, time.perf_counter()
        while time.perf_counter() - t0 < seconds:
            flush()
            n += 1
        return n / (time.perf_counter() - t0)
    except Exception:
        return None


# ---------------------------------------------------------- hardware info ----
def gather_specs(mon):
    e = mon["edid"]
    cw, ch, chz, cbpp = mon["cur"]
    modes = list_modes(mon["device"])
    max_hz = max([hz for (w, h, hz, b) in modes if (w, h) == (cw, ch)] or [chz])
    s = {
        "monitor": mon, "edid": e,
        "name": (e and e["name"]) or (e and "%s %04X" % (e["manufacturer"], e["product_code"]))
                or mon["string"],
        "conn": connection_for(mon),
        "cur": mon["cur"], "max_hz": max_hz,
        "ddc": ddc_read(mon),
    }
    return s


def specs_rows(s):
    """Human-readable (label, value) pairs for the hardware screen / report."""
    e, ddc = s["edid"], s["ddc"]
    cw, ch, chz, cbpp = s["cur"]
    rows = [("Monitor name", s["name"])]
    if e:
        rows.append(("Manufacturer", "%s  (%s)" % (e["manufacturer"], e["mfr_code"])))
        rows.append(("Product code", "%04X" % e["product_code"]))
        serial = e["serial_text"] or (str(e["serial_num"]) if e["serial_num"] else None)
        rows.append(("Serial number", serial or "Not reported"))
        if e["week"] == 255:
            made = "Model year %d" % e["year"]
        elif e["week"]:
            made = "Week %d of %d" % (e["week"], e["year"])
        else:
            made = "%d" % e["year"]
        age = datetime.date.today().year - e["year"]
        rows.append(("Manufactured", "%s  (about %d years old)" % (made, age) if age > 0 else made))
        d = diagonal_inches(e)
        rows.append(("Screen size", '%.1f"  diagonal' % d if d else "Not reported"))
        if e["native"]:
            nw, nh, nhz = e["native"]
            rows.append(("Native resolution", "%d x %d @ %.0f Hz" % (nw, nh, nhz)))
        if e["vrange"]:
            rows.append(("Refresh range (EDID)", "%d - %d Hz" % e["vrange"]))
        rows.append(("Input type", "Digital" if e["digital"] else "Analogue"))
        rows.append(("EDID version", e["version"]))
    else:
        rows.append(("EDID", "Could not be read"))
    rows.append(("Connection", s["conn"] or "Unknown"))
    rows.append(("Current mode", "%d x %d @ %d Hz, %d-bit colour" % (cw, ch, chz, cbpp)))
    rows.append(("Max refresh at this res", "%d Hz" % s["max_hz"]))
    if ddc:
        rows.append(("DDC/CI", "Responding"))
        b = ddc["brightness"]
        rows.append(("Brightness (OSD)", "%d / %d" % b))
        if ddc.get("contrast"):
            rows.append(("Contrast (OSD)", "%d / %d" % ddc["contrast"]))
        if ddc.get("tech") and ddc["tech"][0] in PANEL_TECH:
            rows.append(("Panel technology", PANEL_TECH[ddc["tech"][0]]))
        if ddc.get("firmware") and ddc["firmware"][0]:
            fw = ddc["firmware"][0]
            rows.append(("Firmware", "v%d.%d" % ((fw >> 8) & 0xFF, fw & 0xFF)))
        if ddc.get("hours") and 0 < ddc["hours"][0] < 500000:
            rows.append(("Reported usage", "%d hours" % ddc["hours"][0]))
    else:
        rows.append(("DDC/CI", "Not available"))
    return rows


# -------------------------------------------------------- automatic tests ----
PASS, FAIL, INFO = "pass", "fail", "info"


def t_edid(s):
    if s["edid"]:
        return PASS, "Monitor identity read: %s" % s["name"]
    return FAIL, "No valid EDID found - monitor may be faulty, or cable/adapter strips it"


def t_checksum(s):
    if not s["edid"]:
        return INFO, "Skipped (no EDID)"
    if s["edid"]["checksum_ok"]:
        return PASS, "EDID data is intact"
    return FAIL, "EDID checksum is wrong - corrupted or edited data"


def t_date(s):
    e = s["edid"]
    if not e:
        return INFO, "Skipped (no EDID)"
    now = datetime.date.today().year
    ok = 1995 <= e["year"] <= now and (e["week"] <= 54 or e["week"] == 255)
    age = now - e["year"]
    txt = "Made %s%d (about %s)" % (
        "week %d of " % e["week"] if 0 < e["week"] <= 54 else "", e["year"],
        "under a year old" if age <= 0 else "%d years old" % age)
    return (PASS, txt) if ok else (FAIL, "Implausible date: " + txt)


def t_conn(s):
    c = s["conn"] or ""
    e = s["edid"]
    if any(k in c for k in ("HDMI", "DisplayPort", "DVI", "UDI", "Internal", "LVDS")):
        return PASS, "Digital link over %s" % c
    if "VGA" in c or (e and not e["digital"]):
        return INFO, "Analogue input - expect softer image quality"
    return INFO, "Connection type not reported by Windows"


def t_native(s):
    e = s["edid"]
    cw, ch = s["cur"][0], s["cur"][1]
    if not e or not e["native"]:
        return INFO, "Native resolution unknown"
    nw, nh = e["native"][0], e["native"][1]
    if (cw, ch) in ((nw, nh), (nh, nw)):
        return PASS, "Running at native %d x %d" % (cw, ch)
    return FAIL, "Running %d x %d, native is %d x %d - set it in Display settings" % (cw, ch, nw, nh)


def t_depth(s):
    bpp = s["cur"][3]
    return (PASS, "%d-bit colour" % bpp) if bpp >= 24 else (FAIL, "Only %d-bit colour" % bpp)


def t_maxhz(s):
    hz, mx = s["cur"][2], s["max_hz"]
    if hz >= mx:
        return PASS, "Running at the highest available: %d Hz" % hz
    return INFO, "Running %d Hz but %d Hz is available (change in Display settings)" % (hz, mx)


def t_measure(s):
    m = measure_refresh()
    hz = s["cur"][2]
    if not m:
        return INFO, "Could not measure"
    if abs(m - hz) / hz < 0.05:
        return PASS, "Measured %.0f Hz (matches %d Hz setting)" % (m, hz)
    return INFO, "Measured %.0f Hz vs %d Hz set - measurement may be from another display" % (m, hz)


def t_ddc(s):
    if s["ddc"]:
        return PASS, "Monitor responds to DDC/CI commands"
    return INFO, "No response (many monitors disable DDC/CI or don't support it)"


def t_hours(s):
    d = s["ddc"]
    h = d and d.get("hours")
    if not h or not (0 < h[0] < 500000):
        return INFO, "Monitor does not report usage hours"
    if h[0] >= 30000:
        return FAIL, "%d hours of use - heavy wear" % h[0]
    return PASS, "%d hours of use" % h[0]


AUTO_TESTS = [
    ("EDID data readable", t_edid),
    ("EDID checksum valid", t_checksum),
    ("Manufacture date plausible", t_date),
    ("Digital connection", t_conn),
    ("Native resolution in use", t_native),
    ("Colour depth 24-bit or better", t_depth),
    ("Highest refresh rate selected", t_maxhz),
    ("Measured refresh rate", t_measure),
    ("DDC/CI communication", t_ddc),
    ("Usage hours", t_hours),
]

# ----------------------------------------------------------- manual tests ----
MANUAL_TESTS = [
    {"title": "Colour: RED", "draw": "solid", "color": "#ff0000",
     "desc": "Check all pixels are red and the same brightness. No white, black or off-colour dots."},
    {"title": "Colour: GREEN", "draw": "solid", "color": "#00ff00",
     "desc": "Check all pixels are green and the same brightness. No white, black or off-colour dots."},
    {"title": "Colour: BLUE", "draw": "solid", "color": "#0000ff",
     "desc": "Check all pixels are blue and the same brightness. No white, black or off-colour dots."},
    {"title": "Colour: WHITE", "draw": "solid", "color": "#ffffff",
     "desc": "Check for an even white. Look for dark dots, yellow/blue tint, dim patches or uneven brightness."},
    {"title": "Colour: BLACK", "draw": "solid", "color": "#000000",
     "desc": "Best in a dim room. Look for bright dots, glowing corners/edges (backlight bleed) or cloudy patches."},
    {"title": "Colour: GREY", "draw": "solid", "color": "#808080",
     "desc": "Check for an even grey - no stripes, blotches, vertical banding or tinted areas."},
    {"title": "Gradient", "draw": "gradient",
     "desc": "Colours should blend smoothly. No hard bands or steps, and the grey ramp should have no colour tint."},
    {"title": "Greyscale steps", "draw": "steps",
     "desc": "16 steps from black to white. Every step should be distinct - especially the darkest and brightest."},
    {"title": "Motion / refresh", "draw": "motion",
     "desc": "Blocks should glide smoothly - no stutter, tearing or long ghost trails behind them."},
    {"title": "Grid and text", "draw": "grid",
     "desc": "Lines straight and evenly spaced, circle round, all four edges visible, text crisp."},
    {"title": "Fine pixel lines", "draw": "lines",
     "desc": "1-pixel lines should look crisp and steady. No flicker, shimmer or colour fringes."},
]


# ---------------------------------------------------------------- storage ----
def data_dir():
    d = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "MonitorCheck")
    os.makedirs(d, exist_ok=True)
    return d


def load_history():
    try:
        with open(os.path.join(data_dir(), "history.json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_history(hist):
    with open(os.path.join(data_dir(), "history.json"), "w", encoding="utf-8") as f:
        json.dump(hist, f, indent=1)


def score_of(results):
    p = sum(1 for r in results if r["status"] == PASS)
    f = sum(1 for r in results if r["status"] == FAIL)
    return p, f, (round(100 * p / (p + f)) if p + f else 0)


def verdict_of(pct, fails):
    if pct >= 90 and fails <= 1:
        return "Looks good", GOOD
    if pct >= 70:
        return "Some concerns - inspect the failed items", WARN
    return "Not recommended", BAD


def text_report(rec):
    p, f, pct = score_of(rec["results"])
    v, _ = verdict_of(pct, f)
    lines = ["MONITOR CHECK REPORT", "=" * 52,
             "Monitor : %s" % rec["name"], "Date    : %s" % rec["date"],
             "Score   : %d%%  (%d passed, %d failed)" % (pct, p, f),
             "Verdict : %s" % v, "", "HARDWARE", "-" * 52]
    lines += ["%-24s %s" % (a + ":", b) for a, b in rec["specs"]]
    for kind, head in (("auto", "AUTOMATIC CHECKS"), ("manual", "VISUAL CHECKS")):
        lines += ["", head, "-" * 52]
        for r in rec["results"]:
            if r["kind"] == kind:
                lines.append("[%s] %s" % (r["status"].upper().ljust(4), r["title"]))
                if r["detail"]:
                    lines.append("       %s" % r["detail"])
    return "\n".join(lines)


# --------------------------------------------------------------------- UI ----
def make_button(parent, text, cmd, kind="primary", **kw):
    palette = {"primary": (ACCENT, "#ffffff", "#6aa0ff"),
               "ghost": (PANEL2, FG, "#323950"),
               "danger": ("#4a2530", "#ff9aa6", "#62303f"),
               "good": (GOOD, "#06210f", "#5fe0a8")}
    bg, fg, hover = palette[kind]
    b = tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg, activebackground=hover,
                  activeforeground=fg, relief="flat", bd=0, padx=kw.pop("padx", 22),
                  pady=kw.pop("pady", 10), font=(FONT, 11, "bold"), cursor="hand2",
                  disabledforeground="#5b6174", **kw)
    b.bind("<Enter>", lambda e: b["state"] != "disabled" and b.configure(bg=hover))
    b.bind("<Leave>", lambda e: b.configure(bg=bg))
    return b


class ScrollFrame(tk.Frame):
    def __init__(self, parent, bg=BG, on_resize=None):
        super().__init__(parent, bg=bg)
        self.on_resize = on_resize
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        sb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._resized)
        self.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._wheel))
        self.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

    def _resized(self, e):
        self.canvas.itemconfigure(self._win, width=e.width)
        if self.on_resize:
            self.on_resize(e.width)

    def _wheel(self, e):
        self.canvas.yview_scroll(int(-e.delta / 120) * 2, "units")


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.configure(bg=BG)
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        w, h = min(1100, sw - 100), min(760, sh - 100)
        self.root.geometry("%dx%d+%d+%d" % (w, h, (sw - w) // 2, (sh - h) // 2))
        self.root.minsize(860, 600)
        self._style()
        self.container = tk.Frame(self.root, bg=BG)
        self.container.pack(fill="both", expand=True)
        self.q = queue.Queue()
        self.token = 0          # invalidates stale background results
        self.win = None         # fullscreen test window
        self.root.after(30, self._pump)
        self.screen_home()

    # ---- infrastructure -------------------------------------------------
    def _style(self):
        st = ttk.Style()
        st.theme_use("clam")
        st.configure("Vertical.TScrollbar", background=PANEL2, troughcolor=BG,
                     bordercolor=BG, arrowcolor=MUTED, lightcolor=PANEL2, darkcolor=PANEL2)
        st.configure("TCombobox", fieldbackground=PANEL2, background=PANEL2, foreground=FG,
                     arrowcolor=FG, bordercolor=PANEL2, lightcolor=PANEL2, darkcolor=PANEL2)
        st.map("TCombobox", fieldbackground=[("readonly", PANEL2)],
               foreground=[("readonly", FG)], selectbackground=[("readonly", PANEL2)],
               selectforeground=[("readonly", FG)])
        self.root.option_add("*TCombobox*Listbox.background", PANEL2)
        self.root.option_add("*TCombobox*Listbox.foreground", FG)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)

    def _pump(self):
        try:
            while True:
                fn = self.q.get_nowait()
                try:
                    fn()
                except tk.TclError:
                    pass
        except queue.Empty:
            pass
        self.root.after(30, self._pump)

    def post(self, fn):
        self.q.put(fn)

    def clear(self):
        self.token += 1
        self.root.unbind_all("<MouseWheel>")
        for w in self.container.winfo_children():
            w.destroy()

    def label(self, parent, text, size=11, color=FG, bold=False, **kw):
        return tk.Label(parent, text=text, bg=kw.pop("bg", parent["bg"]), fg=color,
                        font=(FONT, size, "bold" if bold else "normal"), **kw)

    # ---- HOME -------------------------------------------------------------
    def screen_home(self):
        self.clear()
        c = self.container
        head = tk.Frame(c, bg=BG)
        head.pack(fill="x", padx=36, pady=(30, 14))
        left = tk.Frame(head, bg=BG)
        left.pack(side="left")
        self.label(left, APP_NAME, 26, bold=True).pack(anchor="w")
        self.label(left, "Check a second-hand monitor before you buy it", 11, MUTED).pack(anchor="w")
        make_button(head, "+  Run a new test", self.screen_hardware, "primary",
                    padx=28, pady=14).pack(side="right")

        hist = load_history()
        self.label(c, "PAST TESTS", 9, MUTED, bold=True).pack(anchor="w", padx=38, pady=(10, 6))
        if not hist:
            box = tk.Frame(c, bg=PANEL)
            box.pack(fill="x", padx=36, pady=6)
            self.label(box, "No tests yet.\nPlug in the monitor you want to check, then click "
                       "'Run a new test'.", 11, MUTED, justify="left").pack(padx=24, pady=28)
            return

        cards = []
        sf = ScrollFrame(c, on_resize=lambda w: self._grid_cards(cards, w))
        sf.pack(fill="both", expand=True, padx=(30, 20), pady=(0, 20))
        for rec in hist:
            cards.append(self._card(sf.inner, rec))
        self._grid_cards(cards, 1000)

    def _grid_cards(self, cards, width):
        cols = max(1, (width - 10) // 330)
        for i, card in enumerate(cards):
            card.grid_forget()
            card.grid(row=i // cols, column=i % cols, padx=8, pady=8, sticky="nsew")

    def _card(self, parent, rec):
        p, f, pct = score_of(rec["results"])
        _, col = verdict_of(pct, f)
        card = tk.Frame(parent, bg=PANEL, cursor="hand2", width=310, height=130)
        card.grid_propagate(False)
        card.pack_propagate(False)
        stripe = tk.Frame(card, bg=col, width=6)
        stripe.pack(side="left", fill="y")
        body = tk.Frame(card, bg=PANEL)
        body.pack(side="left", fill="both", expand=True, padx=16, pady=14)
        name = rec["name"] if len(rec["name"]) < 26 else rec["name"][:24] + "..."
        self.label(body, name, 13, bold=True).pack(anchor="w")
        try:
            d = datetime.datetime.fromisoformat(rec["date"]).strftime("%d %b %Y, %H:%M")
        except ValueError:
            d = rec["date"]
        self.label(body, d, 10, MUTED).pack(anchor="w", pady=(2, 8))
        row = tk.Frame(body, bg=PANEL)
        row.pack(anchor="w", fill="x")
        self.label(row, "%d%%" % pct, 22, col, bold=True).pack(side="left")
        self.label(row, "  %d passed · %d failed" % (p, f), 10, MUTED).pack(side="left", pady=(10, 0))

        def bind_all(w):
            w.bind("<Button-1>", lambda e: self.screen_report(rec, fresh=False))
            w.bind("<Enter>", lambda e: self._tint(card, PANEL2))
            w.bind("<Leave>", lambda e: self._tint(card, PANEL))
            for ch in w.winfo_children():
                bind_all(ch)
        bind_all(card)
        return card

    def _tint(self, card, color):
        for w in [card] + self._descend(card):
            if w.winfo_class() in ("Frame", "Label") and w["bg"] != self._stripe_color(w):
                w.configure(bg=color)

    def _descend(self, w):
        out = []
        for c in w.winfo_children():
            out.append(c)
            out += self._descend(c)
        return out

    def _stripe_color(self, w):
        return w["bg"] if w.winfo_class() == "Frame" and int(w["width"]) == 6 else None

    # ---- HARDWARE -----------------------------------------------------------
    def screen_hardware(self):
        self.clear()
        mons = enum_monitors()
        if not mons:
            messagebox.showerror(APP_NAME, "No monitors were detected.")
            return self.screen_home()
        self.mons = mons
        c = self.container
        wrap = tk.Frame(c, bg=BG)
        wrap.pack(fill="both", expand=True, padx=36, pady=28)
        self.label(wrap, "Step 1 · Hardware check", 22, bold=True).pack(anchor="w")
        self.label(wrap, "Compare this with the listing. If anything looks wrong or unexpected, "
                   "cancel.", 11, MUTED).pack(anchor="w", pady=(2, 16))

        sel = tk.Frame(wrap, bg=BG)
        sel.pack(fill="x", pady=(0, 14))
        self.label(sel, "Monitor to test:", 11, MUTED).pack(side="left", padx=(0, 10))
        labels = [monitor_label(m, i + 1) for i, m in enumerate(mons)]
        self.combo = ttk.Combobox(sel, values=labels, state="readonly", width=70,
                                  font=(FONT, 11))
        non_primary = [i for i, m in enumerate(mons) if not m["primary"]]
        self.combo.current(non_primary[0] if non_primary else 0)
        self.combo.pack(side="left")
        self.combo.bind("<<ComboboxSelected>>", lambda e: self._load_specs())

        self.spec_box = tk.Frame(wrap, bg=PANEL)
        self.spec_box.pack(fill="both", expand=True)

        bar = tk.Frame(wrap, bg=BG)
        bar.pack(fill="x", pady=(16, 0))
        make_button(bar, "Cancel", self.screen_home, "ghost").pack(side="left")
        self.proceed_btn = make_button(bar, "Proceed  →", self._proceed, "primary", state="disabled")
        self.proceed_btn.pack(side="right")
        self.specs = None
        self._load_specs()

    def _load_specs(self):
        mon = self.mons[self.combo.current()]
        self.specs = None
        self.proceed_btn.configure(state="disabled")
        for w in self.spec_box.winfo_children():
            w.destroy()
        self.label(self.spec_box, "Reading hardware details...  (can take a few seconds)",
                   12, MUTED).pack(padx=24, pady=24, anchor="w")
        self.token += 1
        my = self.token

        def work():
            s = gather_specs(mon)
            self.post(lambda: self._show_specs(s, my))
        threading.Thread(target=work, daemon=True).start()

    def _show_specs(self, s, my):
        if my != self.token:
            return
        self.specs = s
        for w in self.spec_box.winfo_children():
            w.destroy()
        sf = ScrollFrame(self.spec_box, bg=PANEL)
        sf.pack(fill="both", expand=True, padx=12, pady=12)
        sf.inner.grid_columnconfigure(1, weight=1)
        for i, (k, v) in enumerate(specs_rows(s)):
            big = i == 0
            self.label(sf.inner, k, 11, MUTED, bg=PANEL).grid(row=i, column=0, sticky="nw",
                                                              padx=(14, 30), pady=5)
            self.label(sf.inner, v, 16 if big else 11, FG, bold=big, bg=PANEL,
                       wraplength=600, justify="left").grid(row=i, column=1, sticky="nw", pady=5)
        self.proceed_btn.configure(state="normal")

    def _proceed(self):
        if self.specs:
            self.screen_auto(self.specs)

    # ---- AUTOMATIC TESTS ----------------------------------------------------
    def screen_auto(self, specs):
        self.clear()
        my = self.token
        c = self.container
        wrap = tk.Frame(c, bg=BG)
        wrap.pack(fill="both", expand=True, padx=36, pady=28)
        self.label(wrap, "Step 2 · Automatic checks", 22, bold=True).pack(anchor="w")
        self.label(wrap, specs["name"], 11, MUTED).pack(anchor="w", pady=(2, 16))
        box = tk.Frame(wrap, bg=PANEL)
        box.pack(fill="both", expand=True)
        box.grid_columnconfigure(2, weight=1)
        rows = []
        for i, (title, _) in enumerate(AUTO_TESTS):
            icon = self.label(box, "·", 16, MUTED, bg=PANEL, width=3)
            icon.grid(row=i, column=0, padx=(14, 4), pady=7, sticky="n")
            t = self.label(box, title, 11, FG, bold=True, bg=PANEL, anchor="w")
            t.grid(row=i, column=1, sticky="nw", padx=(0, 24), pady=7)
            d = self.label(box, "", 10, MUTED, bg=PANEL, anchor="w", justify="left", wraplength=560)
            d.grid(row=i, column=2, sticky="nw", pady=7)
            rows.append((icon, d))

        bar = tk.Frame(wrap, bg=BG)
        bar.pack(fill="x", pady=(16, 0))
        make_button(bar, "Cancel", self.screen_home, "ghost").pack(side="left")
        self.label(bar, "Tip: dim the room lights and turn the monitor brightness up before "
                   "the visual tests.", 10, MUTED).pack(side="left", padx=20)
        nxt = make_button(bar, "Start visual tests  →", lambda: None, "primary", state="disabled")
        nxt.pack(side="right")
        results = []

        def set_row(i, status, detail):
            if my != self.token:
                return
            icon, d = rows[i]
            sym, col = {PASS: ("✔", GOOD), FAIL: ("✘", BAD), INFO: ("ℹ", WARN)}[status]
            icon.configure(text=sym, fg=col)
            d.configure(text=detail)

        def spin(i):
            if my != self.token:
                return
            rows[i][0].configure(text="…", fg=ACCENT)

        def finished():
            if my != self.token:
                return
            nxt.configure(state="normal",
                          command=lambda: self.run_manual(specs, results))

        def work():
            for i, (title, fn) in enumerate(AUTO_TESTS):
                self.post(lambda i=i: spin(i))
                time.sleep(0.35)
                try:
                    status, detail = fn(specs)
                except Exception as ex:  # a broken check must never kill the run
                    status, detail = INFO, "Check could not run (%s)" % ex
                results.append({"title": title, "kind": "auto", "status": status, "detail": detail})
                self.post(lambda i=i, s=status, d=detail: set_row(i, s, d))
            self.post(finished)
        threading.Thread(target=work, daemon=True).start()

    # ---- MANUAL (FULLSCREEN) TESTS --------------------------------------------
    def run_manual(self, specs, auto_results):
        self.m_specs = specs
        self.m_results = list(auto_results)
        self.m_idx = 0
        self.m_last_key = 0
        self.m_esc = 0
        self.m_size = None
        x, y, w, h = specs["monitor"]["rect"]
        self.root.withdraw()
        win = tk.Toplevel(self.root)
        win.configure(bg="black")
        win.overrideredirect(True)
        win.geometry("%dx%d+%d+%d" % (w, h, x, y))
        win.attributes("-topmost", True)
        c = tk.Canvas(win, bg="black", highlightthickness=0, bd=0, cursor="none")
        c.pack(fill="both", expand=True)
        win.bind("<Key>", self._m_key)
        c.bind("<Button-1>", lambda e: win.focus_force())
        c.bind("<Configure>", self._m_configure)
        self.win, self.canvas = win, c
        win.update()
        win.focus_force()
        c.focus_set()

    def _m_configure(self, e):
        if self.m_size != (e.width, e.height) and e.width > 100:
            self.m_size = (e.width, e.height)
            self.render()

    def render(self):
        c = self.canvas
        W, H = c.winfo_width(), c.winfo_height()
        self.token += 1
        my = self.token
        c.delete("all")
        t = MANUAL_TESTS[self.m_idx]
        c.configure(bg=t.get("color", "black"))
        getattr(self, "draw_" + t["draw"])(c, W, H, t, my)
        self._prompt(c, W, H, t)

    def _prompt(self, c, W, H, t):
        bh = 108
        c.create_rectangle(0, H - bh, W, H, fill="#15171d", outline="#4a5066", tags="ui")
        c.create_text(30, H - bh + 12, anchor="nw", fill="#ffffff", tags="ui",
                      font=(FONT, -24, "bold"),
                      text="%d / %d    %s" % (self.m_idx + 1, len(MANUAL_TESTS), t["title"]))
        c.create_text(30, H - bh + 46, anchor="nw", fill="#d6dae6", tags="ui",
                      font=(FONT, -18), width=W - 60, text=t["desc"])
        c.create_text(30, H - 12, anchor="sw", fill="#8b93a7", tags="ui", font=(FONT, -16),
                      text="[Y] Pass      [N] Fail      [H] Hide/show this bar      "
                           "[Esc][Esc] Cancel test")

    def _m_key(self, e):
        k = e.keysym.lower()
        now = time.time()
        if k == "h":
            state = self.canvas.itemcget("ui", "state") if self.canvas.find_withtag("ui") else ""
            self.canvas.itemconfigure("ui", state="normal" if state == "hidden" else "hidden")
        elif k == "escape":
            if now - self.m_esc < 3:
                self._m_close()
                self.root.deiconify()
                self.screen_home()
            else:
                self.m_esc = now
                self._toast("Press Esc again to cancel the test")
        elif k in ("y", "n") and now - self.m_last_key > 0.25:
            self.m_last_key = now
            t = MANUAL_TESTS[self.m_idx]
            self.m_results.append({
                "title": t["title"], "kind": "manual",
                "status": PASS if k == "y" else FAIL,
                "detail": "Looks fine" if k == "y" else "Problem spotted by you"})
            self.m_idx += 1
            if self.m_idx >= len(MANUAL_TESTS):
                self._m_finish()
            else:
                self.render()

    def _toast(self, text):
        c = self.canvas
        c.delete("toast")
        W = c.winfo_width()
        c.create_rectangle(W // 2 - 260, 20, W // 2 + 260, 76, fill="#15171d",
                           outline="#4a5066", tags="toast")
        c.create_text(W // 2, 48, text=text, fill="white", font=(FONT, -20, "bold"), tags="toast")
        self.win.after(2500, lambda: c.delete("toast"))

    def _m_close(self):
        self.token += 1  # stops animations
        if self.win:
            self.win.destroy()
            self.win = None

    def _m_finish(self):
        self._m_close()
        self.root.deiconify()
        self.root.lift()
        s = self.m_specs
        rec = {"name": s["name"], "date": datetime.datetime.now().isoformat(timespec="seconds"),
               "specs": [list(r) for r in specs_rows(s)], "results": self.m_results}
        hist = load_history()
        hist.insert(0, rec)
        save_history(hist)
        self.screen_report(rec, fresh=True)

    # -- patterns --
    def draw_solid(self, c, W, H, t, my):
        pass  # background colour already set

    def draw_gradient(self, c, W, H, t, my):
        top = int(H * 0.5)
        sw = 6
        n = W // sw + 2
        strips = [c.create_rectangle(i * sw, 0, (i + 1) * sw, top, outline="", fill="#000")
                  for i in range(n)]
        bands = [(0.5, (1, 1, 1)), (0.6, (1, 0, 0)), (0.7, (0, 1, 0)), (0.8, (0, 0, 1))]
        for y0, mask in bands:
            for i in range(256):
                v = i
                col = "#%02x%02x%02x" % (v * mask[0], v * mask[1], v * mask[2])
                c.create_rectangle(i * W // 256, int(H * y0), (i + 1) * W // 256 + 1,
                                   int(H * (y0 + 0.1)), outline="", fill=col)
        phase = [0.0]

        def spin():
            if my != self.token or not self.win:
                return
            phase[0] = (phase[0] + 0.006) % 1
            for i, s in enumerate(strips):
                r, g, b = colorsys.hsv_to_rgb((i / n * 1.0 + phase[0]) % 1, 1, 1)
                c.itemconfigure(s, fill="#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255)))
            c.tag_raise("ui")
            self.win.after(33, spin)
        spin()

    def draw_steps(self, c, W, H, t, my):
        for i in range(16):
            v = i * 17
            col = "#%02x%02x%02x" % (v, v, v)
            c.create_rectangle(i * W // 16, 0, (i + 1) * W // 16 + 1, H, outline="", fill=col)
            c.create_text(i * W // 16 + W // 32, H // 2, text=str(i + 1),
                          fill="#ffffff" if v < 128 else "#000000", font=(FONT, -28, "bold"))

    def draw_motion(self, c, W, H, t, my):
        half = H // 2
        c.create_rectangle(0, 0, W, half, fill="#202020", outline="")
        c.create_rectangle(0, half, W, H, fill="#d8d8d8", outline="")
        size = max(60, H // 11)
        speeds = (500, 1000, 1800)
        blocks = []
        for row, (fill, y0) in enumerate((("#ffffff", 0), ("#000000", half))):
            for k, sp in enumerate(speeds):
                y = y0 + 60 + k * (half - 150) // 3
                blocks.append((c.create_rectangle(0, y, size, y + size, fill=fill, outline=""),
                               sp, y))
        hz = self.m_specs["cur"][2]
        info = c.create_text(W // 2, 22, fill="#ffffff", font=(FONT, -22, "bold"),
                             text="Reported refresh: %d Hz" % hz)
        t0 = last = time.perf_counter()
        frames = [0]
        flush = dwmapi.DwmFlush

        def step():
            if my != self.token or not self.win:
                return
            now = time.perf_counter()
            el = now - t0
            for item, sp, y in blocks:
                x = (el * sp) % (W + size) - size
                c.coords(item, x, y, x + size, y + size)
            frames[0] += 1
            nonlocal last
            if now - last >= 0.5:
                c.itemconfigure(info, text="Reported refresh: %d Hz     Drawing: %.0f fps"
                                % (hz, frames[0] / (now - last)))
                frames[0], last = 0, now
            c.tag_raise("ui")
            c.update_idletasks()
            flush()
            self.win.after(1, step)
        step()

    def draw_grid(self, c, W, H, t, my):
        c.create_rectangle(0, 0, W, H, fill="#000000", outline="")
        step = 100
        for x in range(0, W, step):
            c.create_line(x, 0, x, H, fill="#555555")
        for y in range(0, H, step):
            c.create_line(0, y, W, y, fill="#555555")
        c.create_line(0, 0, W - 1, H - 1, fill="#888888")
        c.create_line(0, H - 1, W - 1, 0, fill="#888888")
        c.create_rectangle(0, 0, W - 1, H - 1, outline="#ffffff", width=3)
        r = min(W, H) // 3
        c.create_oval(W // 2 - r, H // 2 - r, W // 2 + r, H // 2 + r, outline="#00ffff", width=2)
        x = W // 2 - 220
        y = H // 2 - 160
        c.create_rectangle(x - 20, y - 10, x + 460, y + 330, fill="#000000", outline="")
        for i, sz in enumerate((-9, -11, -13, -16, -20, -26)):
            c.create_text(x, y + i * 52, anchor="nw", fill="#ffffff", font=(FONT, sz),
                          text="The quick brown fox jumps over 0123456789")

    def draw_lines(self, c, W, H, t, my):
        c.create_rectangle(0, 0, W, H, fill="#000000", outline="")
        half = W // 2
        for x in range(0, half, 2):
            c.create_line(x, 0, x, H, fill="#ffffff")
        for y in range(0, H, 2):
            c.create_line(half, y, W, y, fill="#ffffff")
        c.create_line(half, 0, half, H, fill="#ff0000")

    # ---- REPORT ----------------------------------------------------------------
    def screen_report(self, rec, fresh):
        self.clear()
        c = self.container
        p, f, pct = score_of(rec["results"])
        verdict, col = verdict_of(pct, f)
        info = sum(1 for r in rec["results"] if r["status"] == INFO)

        head = tk.Frame(c, bg=BG)
        head.pack(fill="x", padx=36, pady=(26, 6))
        make_button(head, "←  Home", self.screen_home, "ghost", padx=16, pady=7).pack(side="left")
        make_button(head, "Export .txt", lambda: self._export(rec), "ghost",
                    padx=16, pady=7).pack(side="right")
        if not fresh:
            make_button(head, "Delete", lambda: self._delete(rec), "danger",
                        padx=16, pady=7).pack(side="right", padx=8)

        sf = ScrollFrame(c)
        sf.pack(fill="both", expand=True, padx=(30, 20), pady=(4, 20))
        body = sf.inner
        top = tk.Frame(body, bg=PANEL)
        top.pack(fill="x", padx=8, pady=8)
        l = tk.Frame(top, bg=PANEL)
        l.pack(side="left", padx=26, pady=22)
        self.label(l, rec["name"], 20, bold=True, bg=PANEL).pack(anchor="w")
        try:
            d = datetime.datetime.fromisoformat(rec["date"]).strftime("%A %d %B %Y, %H:%M")
        except ValueError:
            d = rec["date"]
        self.label(l, d, 10, MUTED, bg=PANEL).pack(anchor="w", pady=(2, 10))
        self.label(l, verdict, 14, col, bold=True, bg=PANEL).pack(anchor="w")
        self.label(l, "%d passed   ·   %d failed   ·   %d info (not scored)" % (p, f, info),
                   10, MUTED, bg=PANEL).pack(anchor="w", pady=(4, 0))
        bar = tk.Canvas(l, width=360, height=10, bg=PANEL2, highlightthickness=0)
        bar.pack(anchor="w", pady=(12, 0))
        bar.create_rectangle(0, 0, 360 * pct / 100, 10, fill=col, outline="")
        self.label(top, "%d%%" % pct, 54, col, bold=True, bg=PANEL).pack(side="right", padx=34)

        for kind, title in (("auto", "AUTOMATIC CHECKS"), ("manual", "VISUAL CHECKS")):
            items = [r for r in rec["results"] if r["kind"] == kind]
            if not items:
                continue
            self.label(body, title, 9, MUTED, bold=True).pack(anchor="w", padx=12, pady=(18, 6))
            box = tk.Frame(body, bg=PANEL)
            box.pack(fill="x", padx=8)
            box.grid_columnconfigure(2, weight=1)
            for i, r in enumerate(items):
                bg_, fg_, txt = {PASS: (GOOD, "#06210f", "PASS"), FAIL: (BAD, "#2a0509", "FAIL"),
                                 INFO: (WARN, "#2b1d00", "INFO")}[r["status"]]
                tk.Label(box, text=txt, bg=bg_, fg=fg_, font=(FONT, 9, "bold"), width=6,
                         pady=2).grid(row=i, column=0, padx=(14, 14), pady=6, sticky="n")
                self.label(box, r["title"], 11, bold=True, bg=PANEL, anchor="w").grid(
                    row=i, column=1, sticky="nw", padx=(0, 24), pady=6)
                self.label(box, r["detail"], 10, MUTED, bg=PANEL, anchor="w", justify="left",
                           wraplength=520).grid(row=i, column=2, sticky="nw", pady=6)

        self.label(body, "HARDWARE DETAILS", 9, MUTED, bold=True).pack(anchor="w", padx=12, pady=(18, 6))
        box = tk.Frame(body, bg=PANEL)
        box.pack(fill="x", padx=8, pady=(0, 10))
        box.grid_columnconfigure(1, weight=1)
        for i, (k, v) in enumerate(rec["specs"]):
            self.label(box, k, 10, MUTED, bg=PANEL).grid(row=i, column=0, sticky="nw",
                                                         padx=(14, 30), pady=3)
            self.label(box, v, 10, FG, bg=PANEL, wraplength=560, justify="left").grid(
                row=i, column=1, sticky="nw", pady=3)

    def _export(self, rec):
        stamp = rec["date"][:10]
        safe = re.sub(r"[^\w\-]+", "_", rec["name"])
        path = filedialog.asksaveasfilename(
            defaultextension=".txt", initialfile="MonitorCheck_%s_%s.txt" % (safe, stamp),
            filetypes=[("Text file", "*.txt")])
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text_report(rec))

    def _delete(self, rec):
        if messagebox.askyesno(APP_NAME, "Delete this test from history?"):
            save_history([r for r in load_history() if r["date"] != rec["date"]
                          or r["name"] != rec["name"]])
            self.screen_home()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    App().run()
