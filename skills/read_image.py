"""analyze an image or screenshot file and answer questions about its visual content, UI elements, or text"""
import base64
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config.json"

desc = {
    "path": {
        "type": "string",
        "description": "Path or URL of the image file to read (e.g. /screenshots/xxx.png or .agent/screenshots/xxx.png)."
    },
    "question": {
        "type": "string",
        "description": "Question or prompt about what to identify or extract from the image.",
        "default": "详细描述图中的主要内容，并识别出图中的所有可见文字。"
    },
    "required": ["path"]
}

def read_config():
    return json.loads(CONFIG.read_text(encoding="utf-8"))

def resolve_image_path(path_str):
    if not path_str or not isinstance(path_str, str):
        return None
    s = path_str.strip()
    if s.startswith("/screenshots/"):
        fname = Path(s[len("/screenshots/"):]).name
        candidate = ROOT / ".agent" / "screenshots" / fname
        if candidate.is_file():
            return candidate
    p = Path(s)
    if p.is_file():
        return p
    if not p.is_absolute():
        cand = (ROOT / p).resolve()
        if cand.is_file():
            return cand
        cand_agent = (ROOT / ".agent" / p).resolve()
        if cand_agent.is_file():
            return cand_agent
    return None

def run(path="", question="详细描述图中的主要内容，并识别出图中的所有可见文字。"):
    img_path = resolve_image_path(path)
    if not img_path:
        return f"error: image file not found at '{path}'"

    ext = img_path.suffix.lower()
    mime = "image/png" if ext == ".png" else "image/jpeg" if ext in (".jpg", ".jpeg") else "application/octet-stream"

    try:
        raw_bytes = img_path.read_bytes()
        b64_str = base64.b64encode(raw_bytes).decode("utf-8")
        data_url = f"data:{mime};base64,{b64_str}"
    except Exception as e:
        return f"error: failed to read image bytes: {e}"

    cfg = read_config()
    server = next((x for x in cfg.get("llm-servers", []) if x.get("id") == "llm2"), None)
    if not server and cfg.get("llm-servers"):
        server = cfg["llm-servers"][0]
    if not server:
        return "error: no llm-servers found in config.json"

    base_url = server["host"].rstrip("/")
    api_key = server.get("api-key", "")
    vision_model = cfg.get("vision-model", "deepseek-v4-flash-vision")

    body = {
        "model": vision_model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": question or "详细描述图中的主要内容，并识别出图中的所有可见文字。"},
                    {"type": "image_url", "image_url": {"url": data_url}}
                ]
            }
        ],
        "max_tokens": cfg.get("max-tokens", 1024),
        "temperature": 0
    }

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(
        base_url + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers=headers
    )

    timeout = cfg.get("upstream-timeout", 60)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            res = json.loads(r.read().decode("utf-8"))
            msg = res["choices"][0]["message"]
            ans = msg.get("content") or msg.get("reasoning_content") or "(empty answer)"
            return ans.strip()
    except Exception as e:
        return f"error: vision API call failed: {e}"
