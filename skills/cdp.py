"""control and automate Chrome browser via Chrome DevTools Protocol (CDP)"""
import base64
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import time
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
AGENT = ROOT / ".agent"
SCREENSHOTS = AGENT / "screenshots"

desc = {
    "action": {
        "type": "string",
        "enum": ["navigate", "eval", "click", "type", "screenshot", "tabs", "new_tab", "close_tab", "raw"],
        "description": "CDP action to perform.",
        "default": "eval"
    },
    "url": {
        "type": "string",
        "description": "URL to navigate to or open in a new tab.",
        "default": ""
    },
    "expression": {
        "type": "string",
        "description": "JavaScript expression to evaluate on the active page.",
        "default": ""
    },
    "selector": {
        "type": "string",
        "description": "CSS selector of element to click, type into, or inspect.",
        "default": ""
    },
    "text": {
        "type": "string",
        "description": "Text to type into the target element.",
        "default": ""
    },
    "tab_id": {
        "type": "string",
        "description": "Target tab ID (optional, defaults to active page tab).",
        "default": ""
    },
    "method": {
        "type": "string",
        "description": "Raw CDP method name (e.g. Page.captureScreenshot, DOM.getDocument) when action='raw'.",
        "default": ""
    },
    "params_json": {
        "type": "string",
        "description": "JSON string of parameters for raw CDP method call.",
        "default": "{}"
    },
    "required": ["action"]
}

class SimpleWebSocket:
    """Minimal RFC 6455 WebSocket client using pure Python standard library."""
    def __init__(self, ws_url):
        u = urllib.parse.urlparse(ws_url)
        host = u.hostname
        port = u.port or 80
        path = u.path or "/"
        if u.query:
            path += "?" + u.query
        self.sock = socket.create_connection((host, port), timeout=15)
        key = base64.b64encode(os.urandom(16)).decode("utf-8")
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(req.encode("utf-8"))
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("WebSocket handshake closed prematurely")
            buf += chunk
        if b" 101 " not in buf[:buf.index(b"\r\n")]:
            raise ConnectionError(f"WebSocket handshake failed: {buf[:100]}")

    def send(self, data_str):
        payload = data_str.encode("utf-8")
        length = len(payload)
        mask = os.urandom(4)
        if length <= 125:
            header = bytes([0x81, 0x80 | length])
        elif length <= 65535:
            header = bytes([0x81, 0x80 | 126]) + struct.pack("!H", length)
        else:
            header = bytes([0x81, 0x80 | 127]) + struct.pack("!Q", length)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(header + mask + masked)

    def recv(self):
        while True:
            head = self._recv_exact(2)
            b1, b2 = head[0], head[1]
            opcode = b1 & 0x0F
            is_masked = bool(b2 & 0x80)
            length = b2 & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._recv_exact(8))[0]
            mask_key = self._recv_exact(4) if is_masked else None
            payload = self._recv_exact(length)
            if is_masked:
                payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
            if opcode == 0x08:
                self.sock.close()
                raise ConnectionResetError("WebSocket closed by server")
            elif opcode == 0x09:
                pong = bytes([0x8A, 0x80]) + os.urandom(4)
                self.sock.sendall(pong)
                continue
            elif opcode == 0x01:
                return payload.decode("utf-8")

    def _recv_exact(self, num_bytes):
        buf = bytearray()
        while len(buf) < num_bytes:
            chunk = self.sock.recv(num_bytes - len(buf))
            if not chunk:
                raise ConnectionError("Socket closed while reading frame")
            buf.extend(chunk)
        return bytes(buf)

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass

def ensure_chrome(port=9222):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as r:
            return True
    except Exception:
        pass

    chrome_candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    exe = next((p for p in chrome_candidates if os.path.exists(p)), None)
    if not exe:
        return False

    cmd = [
        exe,
        f"--remote-debugging-port={port}",
        "--remote-allow-origins=*",
        f"--user-data-dir={Path.home() / \'.browser-profile\'}",
        "--no-first-run",
        "--no-default-browser-check",
        "about:blank"
    ]
    try:
        subprocess.Popen(cmd)
        for _ in range(12):
            time.sleep(0.5)
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as r:
                    return True
            except Exception:
                pass
    except Exception:
        pass
    return False

def get_tabs(port=9222):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=3) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return []

def get_target_page(port=9222, tab_id=None):
    tabs = get_tabs(port)
    if not tabs:
        return None
    if tab_id:
        return next((t for t in tabs if t.get("id") == tab_id), None)
    pages = [t for t in tabs if t.get("type") == "page"]
    return pages[0] if pages else tabs[0]

def cdp_call(page, method, params=None):
    ws_url = page.get("webSocketDebuggerUrl")
    if not ws_url:
        return {"error": "no webSocketDebuggerUrl"}
    ws = SimpleWebSocket(ws_url)
    try:
        msg_id = int(time.time_ns() % 1000000)
        ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
        start_t = time.time()
        while time.time() - start_t < 15:
            res_str = ws.recv()
            res = json.loads(res_str)
            if res.get("id") == msg_id:
                return res
        return {"error": "timeout waiting for CDP response"}
    finally:
        ws.close()

def run(action="eval", url="", expression="", selector="", text="", tab_id="", method="", params_json="{}"):
    port = 9222
    if not ensure_chrome(port):
        return f"error: cannot connect to Chrome CDP on 127.0.0.1:{port} and failed to auto-launch Chrome."

    if action == "tabs":
        tabs = get_tabs(port)
        if not tabs:
            return "no open tabs"
        lines = [f"- [{t.get('type')}] id={t.get('id')} title='{t.get('title')}' url={t.get('url')}" for t in tabs]
        return f"open tabs ({len(tabs)}):\n" + "\n".join(lines)

    elif action == "new_tab":
        target_url = url or "about:blank"
        req = urllib.request.Request(f"http://127.0.0.1:{port}/json/new?{urllib.parse.quote(target_url)}", method="PUT")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                data = json.loads(r.read().decode("utf-8"))
                return f"new tab created: id={data.get('id')} url={data.get('url')} title='{data.get('title')}'"
        except Exception as e:
            return f"error creating new tab: {e}"

    elif action == "close_tab":
        target = get_target_page(port, tab_id)
        if not target:
            return f"error: tab '{tab_id}' not found"
        tid = target.get("id")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/close/{tid}", timeout=5) as r:
                return f"tab closed: id={tid}"
        except Exception as e:
            return f"error closing tab: {e}"

    # Actions below require target page WebSocket
    page = get_target_page(port, tab_id)
    if not page:
        return "error: no active browser page tab found"

    if action == "navigate":
        if not url:
            return "error: empty url for navigate"
        res = cdp_call(page, "Page.navigate", {"url": url})
        time.sleep(1.5)
        title_res = cdp_call(page, "Runtime.evaluate", {"expression": "document.title", "returnByValue": True})
        cur_title = title_res.get("result", {}).get("result", {}).get("value", "")
        return f"navigated to: {url}\ntitle: {cur_title}\nframeId: {res.get('result', {}).get('frameId')}"

    elif action == "eval":
        expr = expression or "document.title"
        res = cdp_call(page, "Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True})
        result_obj = res.get("result", {})
        if "exceptionDetails" in result_obj:
            return f"eval error: {json.dumps(result_obj.get('exceptionDetails'), ensure_ascii=False)}"
        val = result_obj.get("result", {}).get("value")
        return json.dumps(val, ensure_ascii=False, indent=2) if isinstance(val, (dict, list)) else str(val)

    elif action == "click":
        if not selector:
            return "error: empty selector for click"
        click_js = f"""
        (() => {{
            const el = document.querySelector({json.dumps(selector)});
            if (!el) return 'element not found: ' + {json.dumps(selector)};
            el.scrollIntoView({{block: 'center', inline: 'center'}});
            el.click();
            return 'clicked: ' + {json.dumps(selector)};
        }})()
        """
        res = cdp_call(page, "Runtime.evaluate", {"expression": click_js, "returnByValue": True})
        return res.get("result", {}).get("result", {}).get("value", "")

    elif action == "type":
        if not selector:
            return "error: empty selector for type"
        type_js = f"""
        (() => {{
            const el = document.querySelector({json.dumps(selector)});
            if (!el) return 'element not found: ' + {json.dumps(selector)};
            el.focus();
            el.value = {json.dumps(text)};
            el.dispatchEvent(new Event('input', {{bubbles: true}}));
            el.dispatchEvent(new Event('change', {{bubbles: true}}));
            return 'typed ' + {json.dumps(text)}.length + ' chars into ' + {json.dumps(selector)};
        }})()
        """
        res = cdp_call(page, "Runtime.evaluate", {"expression": type_js, "returnByValue": True})
        return res.get("result", {}).get("result", {}).get("value", "")

    elif action == "screenshot":
        res = cdp_call(page, "Page.captureScreenshot", {"format": "png"})
        b64_data = res.get("result", {}).get("data")
        if not b64_data:
            return "error: Page.captureScreenshot returned no data"
        filename = f"{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns() % 1000000:06d}.png"
        out_file = SCREENSHOTS / filename
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_bytes(base64.b64decode(b64_data))
        return f"screenshot: /screenshots/{filename}\nsaved: {out_file.as_posix()} ({len(b64_data)} b64 bytes)"

    elif action == "raw":
        if not method:
            return "error: empty method for raw action"
        try:
            params = json.loads(params_json) if params_json else {}
        except Exception as e:
            return f"error parsing params_json: {e}"
        res = cdp_call(page, method, params)
        return json.dumps(res, ensure_ascii=False, indent=2)

    return f"error: unknown action '{action}'"
