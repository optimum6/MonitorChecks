# Monitor Check

A small Windows app for inspecting a **second-hand monitor** before you buy it. Plug the monitor into your laptop (HDMI or DisplayPort), run the app, and it reads the monitor's hardware details, runs automatic health checks, then walks you through fullscreen visual tests. At the end you get a scored report that is saved to a history list.

Ships as a **single `.exe`** - no installer, no Python needed on the machine you take to the meeting.

---

## Quick start (just want to use it)

1. Copy `dist\MonitorCheck.exe` to the laptop (USB stick is fine).
2. Plug in the monitor and set Windows to **Extend** (Win + P) so it appears as a second display.
3. Double-click `MonitorCheck.exe`.
4. Click **Run a new test**, pick the monitor from the dropdown, and follow the prompts.

Tips for best results:
- Dim the room lights and turn the monitor's brightness up before the visual tests.
- Use the monitor's native resolution and highest refresh rate (Windows Settings > Display).
- Test with the cable you will actually use; some adapters strip monitor info.

---

## Scope

**In scope**
- Reading monitor identity and specs from Windows (EDID, display settings, WMI, DDC/CI).
- Sanity-checking that data (valid checksum, plausible date, native resolution, etc.).
- Guided visual checks for dead/stuck pixels, backlight bleed, uniformity, banding, motion, sharpness.
- A scored, saved report per monitor.

**Out of scope**
- True colour accuracy or brightness measurement (needs a colorimeter).
- Physical checks: scratches, stand, ports, OSD buttons, speakers. Inspect these by hand.
- Detecting a deliberately edited EDID.
- Reading panel hours on monitors that don't report them over DDC/CI (many don't).
- Non-Windows operating systems.

---

## Features

### 1. Home screen
- Cards for every past test showing monitor name, date, score and colour-coded status.
- Click a card to reopen its full report.
- **Run a new test** button.

### 2. Hardware check
Shows what the monitor reports so you can confirm it matches the listing. Choose **Proceed** or **Cancel** if something looks wrong.

| Info | Source |
|---|---|
| Name, manufacturer, product code, serial number | EDID |
| Manufacture week / year and approximate age | EDID |
| Screen size (diagonal), native resolution and refresh | EDID |
| Supported refresh range, digital/analogue input, EDID version | EDID |
| Connection type (HDMI, DisplayPort, DVI, VGA...) | WMI |
| Current mode, colour depth, max refresh at this resolution | Windows display API |
| Brightness, contrast, panel technology, firmware, usage hours | DDC/CI (if supported) |

If more than one display is connected, a dropdown lets you choose which one to test.

### 3. Automatic checks
Each step shows a tick as it completes (pass / fail / info):

1. EDID data readable
2. EDID checksum valid
3. Manufacture date plausible
4. Digital connection
5. Native resolution in use
6. Colour depth 24-bit or better
7. Highest refresh rate selected
8. Measured refresh rate matches the setting
9. DDC/CI communication
10. Usage hours (fails at 30,000+ hours)

Checks the monitor can't answer are marked **info** and are **not scored**.

### 4. Visual checks (fullscreen on the chosen monitor)
A prompt bar at the bottom describes what to look for.

| Key | Action |
|---|---|
| `Y` | Mark test as passed, go to next |
| `N` | Mark test as failed, go to next |
| `H` | Hide / show the prompt bar (to inspect the bottom edge) |
| `Esc` twice | Cancel the whole test (nothing is saved) |

Tests: red, green, blue, white, black and grey screens; animated rainbow gradient with greyscale/red/green/blue ramps; 16-step greyscale; motion/refresh test with ghosting blocks; grid and text sharpness; fine 1-pixel lines.

### 5. Report
- Overall score %, verdict (Looks good / Some concerns / Not recommended), pass/fail/info counts.
- Result and detail for every step, plus the hardware details.
- Saved automatically; **Export .txt** to share it; **Delete** to remove a past test.

Score = passed / (passed + failed). Info items are excluded.

---

## Requirements

### To run the exe
- Windows 10 or 11.
- A monitor connected via HDMI or DisplayPort (or USB-C video).

### To build / modify from source
- Windows 10 or 11
- Python 3.10 or newer (developed on 3.12) with **tkinter** (included in the standard python.org installer)
- [PyInstaller](https://pyinstaller.org) (build step only)

The app itself uses **only the Python standard library** - there is nothing else to install to run it from source.

---

## Install and run from source

```powershell
cd "C:\Users\Chris\Claude Stuff\monitorChecks"
python monitor_check.py
```

## Build the single exe

```powershell
pip install pyinstaller
python -m PyInstaller --onefile --windowed --name MonitorCheck monitor_check.py
```

The result is `dist\MonitorCheck.exe`. The `build\` folder and `MonitorCheck.spec` are build leftovers and can be deleted.

To force a completely fresh build, add `--clean`:

```powershell
python -m PyInstaller --onefile --windowed --name MonitorCheck --clean monitor_check.py
```

---

## Where data is stored

Test history is saved to:

```
%APPDATA%\MonitorCheck\history.json
```

Delete that file to wipe all history.

---

## Troubleshooting

| Problem | Likely cause / fix |
|---|---|
| Monitor shows "Generic PnP Monitor" or no EDID | Cable, adapter or dock is hiding the monitor info. Try a direct cable. |
| DDC/CI "Not available" | The monitor doesn't support it, or it's disabled in the monitor's OSD menu. Not a fault. |
| Only one display listed | Press Win + P and choose Extend (or Duplicate), then restart the test. |
| Test screens appear on the wrong display | Pick the correct monitor in the dropdown on the hardware screen. |
| Keys don't respond in fullscreen test | Click once on the test screen to give it focus. |
| Windows SmartScreen warns on the exe | The exe is unsigned. Choose More info > Run anyway. |
| Antivirus flags the exe | Common false positive for PyInstaller builds. Run from source instead if needed. |
| "Measured refresh rate" shows info, not pass | Windows measured a different display's refresh. Check the Hz in Display settings. |

---

## Project layout

```
monitor_check.py   The whole application (single file)
README.md          This file
dist\              Built MonitorCheck.exe (after building)
```
