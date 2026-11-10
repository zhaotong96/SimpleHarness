# 无参启动本地 http 服务: 客户端带完整 messages 来, 服务端跑 agent 环, 工具就是 skills/*.py
import importlib.util
import inspect
import json
import os
import re
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent


# 读 config.json 配置, 无全局缓存以便即改即用
def read_config():
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


# 按配置目录键定位文件, 每次从磁盘读新值并确保目录存在
def store_file(key, name, ext):
    p = ROOT / read_config()[key] / f"{name}.{ext}"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


# 构造标准库 opener: 显式代理、空串直连(阻断环境变量污染)、None跟随系统
def make_opener(proxy=None):
    if proxy:
        return urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    if proxy == "":
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener()


# 请求指定上游的 /models 列表, 返回完整原始数据
def fetch_models(s, timeout, proxy=None):
    base = s["host"].rstrip("/")
    hdrs = {"Authorization": f"Bearer {s['api-key']}"} if s.get("api-key") else {}
    req = urllib.request.Request(base + "/models", headers=hdrs)
    opener = make_opener(proxy)
    with opener.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode())["data"]


# 挑出上游节点与指定模型, 未指定模型时优先用配置的 model 或探测 /models
def upstream(cfg, server_id=None, model_id=None):
    sid = server_id or cfg["current-llm"]
    s = next(x for x in cfg["llm-servers"] if x["id"] == sid)
    base = s["host"].rstrip("/")
    hdrs = {"Authorization": f"Bearer {s['api-key']}"} if s.get("api-key") else {}
    proxy = s.get("proxy") if "proxy" in s else cfg.get("proxy")
    if model_id or s.get("model"):
        model = model_id or s["model"]
        n_ctx = s.get("n-ctx") or cfg.get("default-n-ctx")
    else:
        m = fetch_models(s, cfg["models-timeout"], proxy)[0]
        model = m["id"]
        n_ctx = m.get("meta", {}).get("n_ctx") or s.get("n-ctx") or cfg.get("default-n-ctx")
    return base, model, n_ctx, hdrs, proxy


# 遍历 skills 目录把 desc 翻成 tool schema; desc 与 run 形参不一致就直接报错
def load_skills():
    tools, runs = [], {}
    sdir = ROOT / read_config()["skills-dir"]
    for f in sorted(sdir.glob("*.py")):
        spec = importlib.util.spec_from_file_location(f.stem, f)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        props = {k: v for k, v in mod.desc.items() if k != "required"}
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


# 读上游一条 SSE 流: 实时产出 think/ans 事件, 结束后返回累计的 tool_calls、回答、思考和 usage
def stream_upstream(base, model, tools, messages, thinking, max_tokens, timeout, temp, headers, proxy=None):
    body = {"model": model, "messages": messages, "tools": tools, "temperature": temp, "stream": True,
            "max_tokens": max_tokens, "chat_template_kwargs": {"enable_thinking": thinking},
            "stream_options": {"include_usage": True}}
    req_headers = {"Content-Type": "application/json", **headers}
    req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode("utf-8"),
                                 headers=req_headers)
    calls, answer, thought, usage = {}, [], [], {}
    opener = make_opener(proxy)
    with opener.open(req, timeout=timeout) as r:
        for raw in r:
            line = raw.decode("utf-8").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            frame = json.loads(data)
            if frame.get("usage"):
                t = (frame.get("timings") or {}).get("predicted_per_second")
                usage = dict(frame["usage"], tps=round(t, 2) if t else None)
                continue
            d = frame["choices"][0].get("delta") or {}
            if d.get("reasoning_content"):
                thought.append(d["reasoning_content"])
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
    return [calls[k] for k in sorted(calls)], "".join(answer), "".join(thought), usage


# 跑一整轮: 增量持续外抛, 有工具就执行并续问, 结束时把用量和完整 messages 交回客户端
def round_events(messages, thinking=True, server=None, model=None):
    cfg = read_config()
    base, model, n_ctx, hdrs, proxy = upstream(cfg, server, model)
    tools, runs = load_skills()
    max_turns = cfg["max-turns"]
    max_tokens = cfg["max-tokens"]
    up_timeout = cfg["upstream-timeout"]
    temp = cfg["temperature"]
    last = {}
    prev_id = messages[-1].get("id") if messages else None
    for _ in range(max_turns):
        calls, answer, thought, usage = yield from stream_upstream(base, model, tools, messages, thinking, max_tokens, up_timeout, temp, hdrs, proxy)
        last = usage or last
        nid = f"m_{time.time_ns()}"
        asst = {"id": nid, "parent": prev_id, "role": "assistant"}
        prev_id = nid
        if thought:
            asst["reasoning_content"] = thought
        if not calls:
            asst["content"] = answer
            messages.append(asst)
            yield ("usage", {**last, "n_ctx": n_ctx})
            yield ("done", messages)
            return
        asst["content"] = None
        asst["tool_calls"] = calls
        messages.append(asst)
        for c in calls:
            fn = c["function"]
            yield ("call", f"{fn['name']} {fn['arguments'] or '{}'}")
            msg = do_call(runs, c)
            tid = f"m_{time.time_ns()}"
            msg["id"] = tid
            msg["parent"] = prev_id
            prev_id = tid
            messages.append(msg)
            yield ("result", msg["content"])
    asst = {"id": f"m_{time.time_ns()}", "parent": prev_id, "role": "assistant", "content": f"turns over {max_turns}"}
    if thought:
        asst["reasoning_content"] = thought
    messages.append(asst)
    yield ("usage", {**last, "n_ctx": n_ctx})
    yield ("done", messages)


# 对话名换成路径: 只允许文件名安全字符, 挡掉 / .. 这类穿越写法, 不合法就交 None
def convo_path(name):
    name = str(name or "")
    if not re.fullmatch(r"[0-9A-Za-z._-]+", name) or ".." in name:
        return None
    return store_file("conversation-dir", name, "json")


# 读一个对话块, 文件不存在返回 None; 内容坏了就抛给调用方, 不静默当空对话
def load_blob(path):
    return json.loads(path.read_text(encoding="utf-8")) if path and path.exists() else None


# 写一个对话块: 唯一临时名 + 原子改名; 失败返回错误文本而不是抛出, 免得打断整轮
def save_blob(path, messages):
    tmp = path.with_suffix(f".{os.getpid()}.{time.time_ns()}.tmp")
    try:
        tmp.write_text(json.dumps(messages, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as e:
        return f"{type(e).__name__} {e}"
    finally:
        tmp.unlink(missing_ok=True)
    return None


# 写配置: 原子替换写回 config.json; 保持缩进格式
def save_config(cfg):
    path = ROOT / "config.json"
    tmp = path.with_suffix(f".{os.getpid()}.{time.time_ns()}.tmp")
    try:
        tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=4), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


# 追加账本: 把本轮新增消息逐条写进 .agent/sessions/<name>.jsonl 并打标模型
def append_session(name, new_msgs, server, model):
    path = store_file("sessions-dir", name, "jsonl")
    now = time.time_ns() // 1_000_000
    with open(path, "a", encoding="utf-8") as f:
        for m in new_msgs:
            f.write(json.dumps({**m, "server": server, "model": model, "ts": now}, ensure_ascii=False) + "\n")


class Handler(BaseHTTPRequestHandler):
    # 客户端半截断开不该打断这一轮, 所以每个事件都容错, 只记一次标志后续静默
    dead = False

    # 每次 POST 跑一轮、持久化配置或切换分支快照
    def do_POST(self):
        if self.path == "/config":
            try:
                payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode("utf-8"))
            except Exception:
                return self.send(400, b'{"error":"bad json"}')
            cfg = read_config()
            server = payload.get("server")
            model = payload.get("model")
            if server:
                cfg["current-llm"] = server
                if model:
                    for s in cfg["llm-servers"]:
                        if s["id"] == server:
                            s["model"] = model
                            break
                save_config(cfg)
            return self.send(200, b'{"ok":true}')
        if self.path.startswith("/checkout/"):
            name = self.path[len("/checkout/"):]
            path = convo_path(name)
            if not path:
                return self.send(400, b'{"error":"bad conversation name"}')
            try:
                payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode("utf-8"))
                msgs = payload.get("messages", [])
            except Exception:
                return self.send(400, b'{"error":"need messages"}')
            err = save_blob(path, msgs)
            if err:
                return self.send(500, json.dumps({"error": err}).encode("utf-8"))
            return self.send(200, b'{"ok":true}')
        if self.path != "/chat":
            return self.send(404, b'{"error":"no path"}')
        try:
            payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode("utf-8"))
            msgs = payload["messages"]
        except Exception:
            return self.send(400, b'{"error":"need messages"}')
        name = payload.get("conversation", "")
        path = convo_path(name) if name else None
        if name and not path:
            return self.send(400, b'{"error":"bad conversation name"}')
        cfg = read_config()
        server = payload.get("server") or cfg["current-llm"]
        model = payload.get("model") or ""
        print(f"chat: server={server} model={model or '(auto)'} convo={name}", flush=True)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.end_headers()
        in_len = len(msgs)
        try:
            for ev in round_events(msgs, payload.get("thinking", True), server, model):
                self.emit(ev)
        except Exception as e:
            self.emit(("error", str(e)[:200]))
        finally:
            if path:
                err = save_blob(path, msgs)
                if err:
                    self.emit(("error", f"save fail {name} {err}"[:200]))
                if in_len > 1 and len(msgs) >= in_len:
                    append_session(name, msgs[in_len - 1:], server, model)
        self.emit(("end", None))

    # 一条 SSE 事件, 每条都 flush, 否则浏览器要等缓冲区满才见字
    def emit(self, ev):
        obj = {"type": ev[0], "text": ev[1] if len(ev) > 1 else None}
        try:
            self.wfile.write(f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode("utf-8"))
            self.wfile.flush()
        except OSError:
            self.dead = True

    # 定长响应统一走这里, 静态页与错误都用它
    def send(self, status, body, kind="application/json"):
        self.send_response(status)
        ctype = kind if kind.startswith("image/") else f"{kind}; charset=utf-8"
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # 读接口: 动态 API 优先分发, 其余走静态白名单
    def do_GET(self):
        cfg = read_config()
        if self.path.startswith("/models"):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            sid = query.get("server", [cfg["current-llm"]])[0]
            s = next((x for x in cfg["llm-servers"] if x["id"] == sid), None)
            if not s:
                return self.send(404, b'{"error":"no server"}')
            try:
                proxy = s.get("proxy") if "proxy" in s else cfg.get("proxy")
                models = [m["id"] for m in fetch_models(s, cfg["models-timeout"], proxy)]
                return self.send(200, json.dumps(models, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                return self.send(500, json.dumps({"error": str(e)[:120]}).encode("utf-8"))
        if self.path == "/skills":
            tools, _ = load_skills()
            return self.send(200, json.dumps([t["function"] for t in tools], ensure_ascii=False).encode("utf-8"))
        if self.path == "/conversation":
            root = ROOT / cfg["conversation-dir"]
            names = sorted(p.stem for p in root.glob("*.json")) if root.is_dir() else []
            return self.send(200, json.dumps(names).encode("utf-8"))
        if self.path.startswith("/sessions/"):
            name = self.path[len("/sessions/"):]
            if not convo_path(name):
                return self.send(400, b'{"error":"bad session name"}')
            spath = store_file("sessions-dir", name, "jsonl")
            lines = [json.loads(l) for l in spath.read_text(encoding="utf-8").splitlines()] if spath.exists() else []
            return self.send(200, json.dumps(lines, ensure_ascii=False).encode("utf-8"))
        if self.path.startswith("/screenshots/"):
            filename = Path(self.path[len("/screenshots/"):]).name
            file_path = ROOT / ".agent" / "screenshots" / filename
            if not file_path.is_file():
                return self.send(404, b'{"error":"not found"}')
            return self.send(200, file_path.read_bytes(), "image/png")
        if self.path.startswith("/conversation/"):
            path = convo_path(self.path[len("/conversation/"):])
            if not path:
                return self.send(400, b'{"error":"bad conversation name"}')
            try:
                msgs = load_blob(path) or []
            except (OSError, ValueError) as e:
                return self.send(500, json.dumps({"error": f"conversation unreadable {str(e)[:120]}"}).encode("utf-8"))
            return self.send(200, json.dumps({"messages": msgs}, ensure_ascii=False).encode("utf-8"))
        name = cfg["pages"].get(self.path)
        if not name:
            return self.send(404, b'{"error":"no page"}')
        self.send(200, (ROOT / name).read_bytes(), cfg["types"][Path(name).suffix])


if __name__ == "__main__":
    # 绑定配置 IP: 这服务能经 shell 技能执行任意命令, 暴露到局域网等于开放远程执行
    cfg = read_config()
    host, port = cfg["bind-host"], cfg["port"]
    print(f"tools={len(load_skills()[0])} model={upstream(cfg)[1]} url=http://{host}:{port}", flush=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()
