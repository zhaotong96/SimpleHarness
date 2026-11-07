"""capture full desktop screen or a specific window to a PNG file, returning file path and visible windows"""
import ctypes
from ctypes import wintypes
import os
import time
from pathlib import Path
import uuid

ROOT = Path(__file__).resolve().parent.parent
AGENT = ROOT / ".agent"
SCREENSHOTS = AGENT / "screenshots"

desc = {
    "path": {
        "type": "string",
        "description": "Optional relative path to save the PNG screenshot. Defaults to .agent/screenshots/<timestamp>.png.",
        "default": ""
    },
    "window": {
        "type": "string",
        "description": "Optional window title substring to capture only that window. Defaults to full desktop.",
        "default": ""
    }
}

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
gdiplus = ctypes.windll.gdiplus

class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]

class BITMAPFILEHEADER(ctypes.Structure):
    _pack_ = 2
    _fields_ = [
        ("bfType", wintypes.WORD),
        ("bfSize", wintypes.DWORD),
        ("bfReserved1", wintypes.WORD),
        ("bfReserved2", wintypes.WORD),
        ("bfOffBits", wintypes.DWORD),
    ]

class GdiplusStartupInput(ctypes.Structure):
    _fields_ = [
        ("GdiplusVersion", wintypes.DWORD),
        ("DebugEventCallback", ctypes.c_void_p),
        ("SuppressBackgroundThread", wintypes.BOOL),
        ("SuppressExternalCodecs", wintypes.BOOL),
    ]

CLSID_PNG = uuid.UUID("{557cf406-1a04-11d3-9a73-0000f81ef32e}").bytes_le

def get_visible_windows():
    wins = []
    hwnd = user32.GetWindow(user32.GetDesktopWindow(), 5) # GW_CHILD
    while hwnd:
        if user32.IsWindowVisible(hwnd):
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            cw = rect.right - rect.left
            ch = rect.bottom - rect.top
            if cw > 0 and ch > 0:
                title_buf = ctypes.create_unicode_buffer(256)
                user32.GetWindowTextW(hwnd, title_buf, 256)
                cls_buf = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, cls_buf, 256)
                wins.append({
                    "hwnd": hwnd,
                    "title": title_buf.value,
                    "class": cls_buf.value,
                    "x": rect.left,
                    "y": rect.top,
                    "w": cw,
                    "h": ch
                })
        hwnd = user32.GetWindow(hwnd, 2) # GW_HWNDNEXT
    return wins

def save_hbm_to_png(hbm, out_path):
    token = ctypes.c_ulong()
    st_in = GdiplusStartupInput(1, None, False, False)
    if gdiplus.GdiplusStartup(ctypes.byref(token), ctypes.byref(st_in), None) != 0:
        return False
    try:
        p_img = ctypes.c_void_p()
        if gdiplus.GdipCreateBitmapFromHBITMAP(hbm, None, ctypes.byref(p_img)) != 0:
            return False
        try:
            clsid_buf = (ctypes.c_ubyte * 16).from_buffer_copy(CLSID_PNG)
            ret = gdiplus.GdipSaveImageToFile(p_img, str(out_path), clsid_buf, None)
            return ret == 0
        finally:
            gdiplus.GdipDisposeImage(p_img)
    finally:
        gdiplus.GdiplusShutdown(token)

def capture_desktop_png(out_path=None):
    """Capture full desktop and save to PNG, returning /screenshots/<filename> web URL."""
    w = user32.GetSystemMetrics(0)
    h = user32.GetSystemMetrics(1)
    if w <= 0 or h <= 0:
        return None

    if not out_path:
        filename = f"{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns() % 1000000:06d}.png"
        out_file = SCREENSHOTS / filename
    else:
        out_file = Path(out_path)
        if not out_file.is_absolute():
            out_file = (ROOT / out_file).resolve()
        filename = out_file.name

    out_file.parent.mkdir(parents=True, exist_ok=True)
    dc_screen = user32.GetDC(0)
    if not dc_screen:
        return None

    try:
        wins = get_visible_windows()
        mem_dc = gdi32.CreateCompatibleDC(dc_screen)
        hbm = gdi32.CreateCompatibleBitmap(dc_screen, w, h)
        old = gdi32.SelectObject(mem_dc, hbm)

        for win in reversed(wins):
            cw, ch = win["w"], win["h"]
            wnd_dc = gdi32.CreateCompatibleDC(dc_screen)
            wnd_bm = gdi32.CreateCompatibleBitmap(dc_screen, cw, ch)
            old_w = gdi32.SelectObject(wnd_dc, wnd_bm)
            if not user32.PrintWindow(win["hwnd"], wnd_dc, 2):
                user32.PrintWindow(win["hwnd"], wnd_dc, 0)
            gdi32.BitBlt(mem_dc, win["x"], win["y"], cw, ch, wnd_dc, 0, 0, 0x00CC0020)
            gdi32.SelectObject(wnd_dc, old_w)
            gdi32.DeleteObject(wnd_bm)
            gdi32.DeleteDC(wnd_dc)

        ok = save_hbm_to_png(hbm, out_file)
        gdi32.SelectObject(mem_dc, old)
        gdi32.DeleteObject(hbm)
        gdi32.DeleteDC(mem_dc)
        return f"/screenshots/{filename}" if ok else None
    finally:
        user32.ReleaseDC(0, dc_screen)

def run(path="", window=""):
    w = user32.GetSystemMetrics(0)
    h = user32.GetSystemMetrics(1)
    if w <= 0 or h <= 0:
        return "error: invalid display metrics"

    wins = get_visible_windows()
    target_win = None
    if window:
        target_win = next((x for x in wins if window.lower() in x["title"].lower()), None)
        if not target_win:
            win_titles = [x["title"] for x in wins if x["title"]]
            return f"error: window '{window}' not found. Visible: {win_titles}"

    if target_win:
        filename = f"{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns() % 1000000:06d}.png"
        out_file = Path(path) if path else SCREENSHOTS / filename
        if not out_file.is_absolute():
            out_file = (ROOT / out_file).resolve()
        out_file.parent.mkdir(parents=True, exist_ok=True)

        dc_screen = user32.GetDC(0)
        if not dc_screen:
            return "error: cannot get screen DC"
        try:
            cw, ch = target_win["w"], target_win["h"]
            mem_dc = gdi32.CreateCompatibleDC(dc_screen)
            hbm = gdi32.CreateCompatibleBitmap(dc_screen, cw, ch)
            old = gdi32.SelectObject(mem_dc, hbm)
            if not user32.PrintWindow(target_win["hwnd"], mem_dc, 2):
                user32.PrintWindow(target_win["hwnd"], mem_dc, 0)
            ok = save_hbm_to_png(hbm, out_file)
            gdi32.SelectObject(mem_dc, old)
            gdi32.DeleteObject(hbm)
            gdi32.DeleteDC(mem_dc)
            if not ok:
                return "error: failed to encode PNG"
            return f"saved: /screenshots/{out_file.name} ({cw}x{ch})\nwindow: {target_win['title']}"
        finally:
            user32.ReleaseDC(0, dc_screen)
    else:
        url = capture_desktop_png(path)
        if not url:
            return "error: failed to capture desktop"
        win_summary = "\n".join(f"- [{x['class']}] '{x['title']}' at ({x['x']},{x['y']},{x['w']}x{x['h']})" for x in wins if x['title'])
        return f"saved: {url} ({w}x{h})\nvisible windows:\n{win_summary}"
