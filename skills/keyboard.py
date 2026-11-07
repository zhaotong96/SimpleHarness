"""send keystrokes, text input, and keyboard shortcuts to the remote active window"""
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
        "enum": ["type", "key", "hotkey"],
        "description": "Keyboard action to perform: 'type' for text string, 'key' for single key press, 'hotkey' for key combinations.",
        "default": "type"
    },
    "text": {
        "type": "string",
        "description": "Text to type when action='type'. Supports Unicode (English, Chinese, symbols).",
        "default": ""
    },
    "key": {
        "type": "string",
        "description": "Key name when action='key' (e.g. 'enter', 'tab', 'escape', 'backspace', 'up', 'down', 'f5').",
        "default": ""
    },
    "hotkey": {
        "type": "string",
        "description": "Key combination when action='hotkey' (e.g. 'ctrl+c', 'ctrl+v', 'alt+tab', 'win+r').",
        "default": ""
    },
    "required": ["action"]
}

# Win32 Key Flags
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

VK_MAP = {
    "enter": 0x0D, "return": 0x0D,
    "tab": 0x09,
    "backspace": 0x08, "bs": 0x08,
    "space": 0x20,
    "escape": 0x1B, "esc": 0x1B,
    "delete": 0x2E, "del": 0x2E,
    "insert": 0x2D, "ins": 0x2D,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21, "pgup": 0x21,
    "pagedown": 0x22, "pgdn": 0x22,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "capslock": 0x14,
    "ctrl": 0x11, "control": 0x11,
    "alt": 0x12,
    "shift": 0x10,
    "win": 0x5B, "windows": 0x5B,
    "printscreen": 0x2C, "prtsc": 0x2C,
}
for i in range(1, 13):
    VK_MAP[f"f{i}"] = 0x70 + (i - 1)
for i in range(10):
    VK_MAP[str(i)] = 0x30 + i
for ch in "abcdefghijklmnopqrstuvwxyz":
    VK_MAP[ch] = ord(ch.upper())

def get_foreground_info():
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return "none", "none"
    title_buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, title_buf, 256)
    cls_buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, cls_buf, 256)
    return title_buf.value or "(no title)", cls_buf.value or "(unknown)"

def press_vk(vk):
    user32.keybd_event(vk, 0, 0, 0)
    time.sleep(0.02)
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)

def type_unicode_text(text):
    for ch in text:
        if ch == "\n":
            press_vk(0x0D)
        elif ch == "\t":
            press_vk(0x09)
        else:
            code = ord(ch)
            user32.keybd_event(0, code, KEYEVENTF_UNICODE, 0)
            time.sleep(0.005)
            user32.keybd_event(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0)
            time.sleep(0.005)

def run(action="type", text="", key="", hotkey=""):
    title, cls = get_foreground_info()

    res = ""
    if action == "type":
        if not text:
            return "error: empty text"
        type_unicode_text(text)
        res = f"typed text ({len(text)} chars) on window '{title}' [{cls}]"

    elif action == "key":
        k = key.lower().strip()
        if not k:
            return "error: empty key name"
        vk = VK_MAP.get(k)
        if vk is None:
            return f"error: unknown key '{key}'"
        press_vk(vk)
        res = f"pressed key '{key}' on window '{title}' [{cls}]"

    elif action == "hotkey":
        hk = hotkey.lower().strip()
        if not hk:
            return "error: empty hotkey"
        parts = [p.strip() for p in hk.replace("+", " ").replace("-", " ").split()]
        vks = [VK_MAP.get(p) for p in parts]
        if any(v is None for v in vks):
            bad = [p for p, v in zip(parts, vks) if v is None]
            return f"error: unknown key(s) in hotkey: {bad}"

        for v in vks:
            user32.keybd_event(v, 0, 0, 0)
            time.sleep(0.01)

        time.sleep(0.05)

        for v in reversed(vks):
            user32.keybd_event(v, 0, KEYEVENTF_KEYUP, 0)
            time.sleep(0.01)

        res = f"pressed hotkey '{hotkey}' on window '{title}' [{cls}]"
    else:
        return f"error: unknown action '{action}'"

    # Capture screen after keyboard action so UI can preview new state
    shot_info = ""
    if capture_desktop_png:
        time.sleep(0.05)
        shot_url = capture_desktop_png()
        if shot_url:
            shot_info = f"\nscreenshot: {shot_url}"

    return res + shot_info
