# 无参启动本地 http 服务: 客户端带完整 messages 来, 服务端跑 agent 环, 工具就是 skills/*.py
import importlib.util
import inspect
import json
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PAGES = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css"}
TYPES = {".html": "text/html", ".js": "application/javascript", ".css": "text/css"}


# 读 config.json 配置, 无全局缓存以便即改即用
def read_config():
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


# 挑出上游地址并问 /v1/models 拿 model 名, 所以 config 里不用写模型
def upstream(cfg):
    s = next(x for x in cfg["llm-servers"] if x["id"] == cfg["default-llm"])
    base = f"http://{s['host']}:{s['port']}"
    with urllib.request.urlopen(base + "/v1/models", timeout=30) as r:
        return base, json.loads(r.read().decode())["data"][0]["id"]


# 遍历 skills/*.py 把 desc 翻成 tool schema; desc 与 run 形参不一致就直接报错
def load_skills():
    tools, runs = [], {}
    for f in sorted((ROOT / "skills").glob("*.py")):
        spec = importlib.util.spec_from_file_location(f.stem, f)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        props = {k: v for k, v in mod.desc.items() if k != "required"}
        # 不一致时模型照 desc 传参会撞 TypeError, 所以宁可启动就崩
        params = set(inspect.signature(mod.run).parameters)
        if set(props) != params:
            raise RuntimeError(f"{f.name}: desc {sorted(props)} != run {sorted(params)}")
        tools.append({"type": "function", "function": {
            "name": f.stem, "description": mod.__doc__ or "",
            "parameters": {"type": "object", "properties": props, "required": mod.desc.get("required", [])}}})
        runs[f.stem] = mod.run
    return tools, runs


# 执行一次工具调用, 参数不合法或技能抛异常都把错误原文回给模型, 服务不替它猜
def do_call(runs, call):
    fn = call.get("function") or {}
    name = fn.get("name") or ""
    if name not in runs:
        content = f"no tool {name}"
    else:
        try:
            content = str(runs[name](**json.loads(fn.get("arguments") or "{}")))
        except Exception as e:
            content = f"call error {type(e).__name__} {e}"
    return {"role": "tool", "tool_call_id": call["id"], "content": content}


# 读上游一条 SSE 流: 实时产出 think/ans 事件, 结束后返回累计的 tool_calls 和回答
def stream_upstream(base, model, tools, messages, thinking, max_tokens, timeout):
    body = {"model": model, "messages": messages, "tools": tools, "temperature": 0, "stream": True,
            "max_tokens": max_tokens, "chat_template_kwargs": {"enable_thinking": thinking}}
    req = urllib.request.Request(base + "/v1/chat/completions", data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    calls, answer = {}, []
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for raw in r:
            line = raw.decode("utf-8").strip()
            if not line.startswith("data:"):
                continue
            if line[5:].strip() == "[DONE]":
                break
            d = json.loads(line[5:])["choices"][0].get("delta") or {}
            if d.get("reasoning_content"):
                yield ("think", d["reasoning_content"])
            if d.get("content"):
                answer.append(d["content"])
                yield ("ans", d["content"])
            for tc in d.get("tool_calls") or []:
                slot = calls.setdefault(tc.get("index", 0), {
                    "id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                fn = tc.get("function") or {}
                slot["id"] += tc.get("id") or ""
                slot["function"]["name"] += fn.get("name") or ""
                slot["function"]["arguments"] += fn.get("arguments") or ""
    return [calls[k] for k in sorted(calls)], "".join(answer)


# 跑一整轮: 增量持续外抛, 有工具就执行并续问, 结束时把完整 messages 交回客户端
def round_events(messages, thinking=True):
    cfg = read_config()
    base, model = upstream(cfg)
    tools, runs = load_skills()
    max_turns = cfg["max-turns"]
    max_tokens = cfg["max-tokens"]
    up_timeout = cfg["upstream-timeout"]
    for _ in range(max_turns):
        calls, answer = yield from stream_upstream(base, model, tools, messages, thinking, max_tokens, up_timeout)
        if not calls:
            messages.append({"role": "assistant", "content": answer})
            yield ("done", messages)
            return
        messages.append({"role": "assistant", "content": None, "tool_calls": calls})
        for c in calls:
            fn = c["function"]
            yield ("call", f"{fn['name']} {fn['arguments'] or '{}'}")
            msg = do_call(runs, c)
            messages.append(msg)
            yield ("result", msg["content"])
    messages.append({"role": "assistant", "content": f"turns over {max_turns}"})
    yield ("done", messages)


class Handler(BaseHTTPRequestHandler):
    # 无会话状态: 每次 POST 只跑一轮, 全程 SSE 增量下发
    def do_POST(self):
        if self.path != "/chat":
            return self.send(404, b'{"error":"no path"}')
        try:
            payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode("utf-8"))
            msgs = payload["messages"]
        except Exception:
            return self.send(400, b'{"error":"need messages"}')
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.end_headers()
        try:
            for ev in round_events(msgs, payload.get("thinking", True)):
                self.emit(ev)
        except Exception as e:
            self.emit(("error", str(e)[:200]))
        self.emit(("end", None))

    # 一条 SSE 事件, 每条都 flush, 否则浏览器要等缓冲区满才见字
    def emit(self, ev):
        obj = {"type": ev[0], "text": ev[1] if len(ev) > 1 else None}
        self.wfile.write(f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode("utf-8"))
        self.wfile.flush()

    # 定长响应统一走这里, 静态页与错误都用它
    def send(self, status, body, kind="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", f"{kind}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # 静态只认 PAGES 里列死的三个名字, 不拼路径所以没有穿越风险
    def do_GET(self):
        name = PAGES.get(self.path)
        if not name:
            return self.send(404, b'{"error":"no page"}')
        self.send(200, (ROOT / name).read_bytes(), TYPES[Path(name).suffix])


if __name__ == "__main__":
    # 只绑 127.0.0.1: 这服务能经 shell 技能执行任意命令, 暴露到局域网等于开放远程执行
    cfg = read_config()
    port = cfg["port"]
    print(f"tools={len(load_skills()[0])} model={upstream(cfg)[1]} url=http://127.0.0.1:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
