"""control remote mouse cursor, clicks, drags, and scrolling"""
import ctypes
from ctypes import wintypes
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from skills.screenshot import capture_desktop_png
except Exception:
    capture_desktop_png = None

user32 = ctypes.windll.user32

desc = {
    "action": {
        "type": "string",
        "enum": ["click", "double_click", "right_click", "move", "down", "up", "scroll"],
        "description": "Mouse action to perform."
    },
    "x": {
        "type": "integer",
        "description": "Target X screen coordinate in pixels.",
        "default": 0
    },
    "y": {
        "type": "integer",
        "description": "Target Y screen coordinate in pixels.",
        "default": 0
    },
    "button": {
        "type": "string",
        "enum": ["left", "right", "middle"],
        "description": "Mouse button for click/down/up. Defaults to 'left'.",
        "default": "left"
    },
    "delta": {
        "type": "integer",
        "description": "Scroll wheel delta (e.g. 120 for scroll up, -120 for scroll down).",
        "default": 0
    },
    "required": ["action"]
}

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

# MOUSEEVENTF flags
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000

BUTTON_FLAGS = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}

def get_window_info_at(x, y):
    pt = POINT(x, y)
    hwnd = user32.WindowFromPoint(pt)
    if not hwnd:
        return "none", "none"
    title_buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, title_buf, 256)
    cls_buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, cls_buf, 256)
    return title_buf.value or "(no title)", cls_buf.value or "(unknown)"

def run(action="click", x=0, y=0, button="left", delta=0):
    w = user32.GetSystemMetrics(0)
    h = user32.GetSystemMetrics(1)
    if w <= 0 or h <= 0:
        return "error: invalid display metrics"

    # Clamp coordinates
    x = max(0, min(int(x), w - 1))
    y = max(0, min(int(y), h - 1))

    # Move cursor first if coordinate is provided or action is move/click
    if action in ("click", "double_click", "right_click", "move", "down", "up"):
        norm_x = int(x * 65535 / w)
        norm_y = int(y * 65535 / h)
        user32.mouse_event(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, norm_x, norm_y, 0, 0)

    btn = button.lower() if button in BUTTON_FLAGS else "left"
    down_flag, up_flag = BUTTON_FLAGS[btn]

    title, cls = get_window_info_at(x, y)

    res = ""
    if action == "move":
        res = f"mouse moved to ({x}, {y}) on window '{title}' [{cls}]"
    elif action == "click":
        user32.mouse_event(down_flag, 0, 0, 0, 0)
        time.sleep(0.02)
        user32.mouse_event(up_flag, 0, 0, 0, 0)
        res = f"mouse {btn}_click at ({x}, {y}) on window '{title}' [{cls}]"
    elif action == "double_click":
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.02)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        time.sleep(0.05)
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.02)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        res = f"mouse double_click at ({x}, {y}) on window '{title}' [{cls}]"
    elif action == "right_click":
        user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
        time.sleep(0.02)
        user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
        res = f"mouse right_click at ({x}, {y}) on window '{title}' [{cls}]"
    elif action == "down":
        user32.mouse_event(down_flag, 0, 0, 0, 0)
        res = f"mouse {btn}_down at ({x}, {y}) on window '{title}' [{cls}]"
    elif action == "up":
        user32.mouse_event(up_flag, 0, 0, 0, 0)
        res = f"mouse {btn}_up at ({x}, {y}) on window '{title}' [{cls}]"
    elif action == "scroll":
        d = int(delta) if delta else 120
        user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, d, 0)
        res = f"mouse scroll delta={d} at ({x}, {y}) on window '{title}' [{cls}]"
    else:
        return f"error: unknown action '{action}'"

    # Capture screen after mouse action so UI can preview new state
    shot_info = ""
    if capture_desktop_png:
        time.sleep(0.05)
        shot_url = capture_desktop_png()
        if shot_url:
            shot_info = f"\nscreenshot: {shot_url}"

    return res + shot_info
