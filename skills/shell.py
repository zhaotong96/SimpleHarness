"""run one command in bash|python|powershell|cmd, return exit code, pwd, stdout, stderr"""
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config.json"
AGENT = ROOT / ".agent"
LOGS = AGENT / "logs"

desc = {
    "interpreter": {
        "type": "string",
        "enum": ["bash", "python", "powershell", "cmd"]
    },
    "command":{
        "type": "string"
    },
    "pwd": {
        "type": "string",
        "default": "."
    },
    "timeout": {
        "type": "integer",
        "default": 60
    },
    "required": ["interpreter", "command"]
}


# 读 config.json 配置, 无全局缓存以便即改即用
def read_config():
    return json.loads(CONFIG.read_text(encoding="utf-8"))


# 把 stdout / stderr 拼成分段正文, 供报告与落盘复用
def streams(out, err):
    text = ""
    for label, body in (("stdout", out), ("stderr", err)):
        text += f"--- {label} ---\n{(body or '').strip()}\n"
    return text


# 逐逻辑行按 wrap 硬折, 只插换行不改字符, 空行照留
def fold(text, wrap):
    return "\n".join(
        piece
        for line in text.splitlines()
        for piece in [line[i:i + wrap] for i in range(0, len(line), wrap)] or [""]
    )


# 超限报告折行后落盘为独立文本文件, 只返回文件路径; 写不进去就回 dump fail
def dump(report, wrap):
    # 秒 + 微秒, 同一秒内连续调用也不互相覆盖
    path = LOGS / f"{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns() % 1000000:06d}.txt"
    try:
        LOGS.mkdir(parents=True, exist_ok=True)
        path.write_text(fold(report, wrap), encoding="utf-8")
    except OSError:
        return "dump fail"
    return path.as_posix()


# 执行一条命令并把报告回给模型: 入参先校验, 报告超 max-output 时不给正文只给回读路径
def run(interpreter="bash", command="", pwd=".", timeout=60):
    argv = {
        "bash": ("bash", "-lc"),
        "python": (sys.executable, "-c"),
        "powershell": ("powershell", "-NoProfile", "-Command"),
        "cmd": ("cmd", "/c"),
    }.get(interpreter)
    if argv is None:
        return "bad enum"

    # 兜住模型传 null / 数字 / bool, 不让 AttributeError 逃成裸栈
    if not isinstance(command, str) or not command.strip():
        return "empty command"

    # bool 是 int 的子类, 单用 isinstance 会放行 timeout=True
    if isinstance(timeout, bool) or not isinstance(timeout, int):
        return "timeout must int"

    # 带冒号无根的 drive-relative 写法不会替换 AGENT, 而是被拼接到它后面
    if ":" in pwd and not (Path(pwd).drive and Path(pwd).root):
        return "bad pwd"

    workdir = (AGENT / pwd).resolve()
    try:
        workdir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return f"bad pwd {e.winerror}"

    try:
        p = subprocess.run(
            [*argv, command],
            cwd=str(workdir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError:
        return f"no {argv[0]}"
    except subprocess.TimeoutExpired as e:
        report = f"timeout {timeout}s\n" + streams(e.stdout, e.stderr)
    else:
        report = f"exit={p.returncode} pwd={workdir}\n" + streams(p.stdout, p.stderr)

    cfg = read_config()
    if len(report) > cfg["max-output"]:
        return "output over length " + dump(report, cfg["wrap"])
    return report
