"""view and edit files by line numbers with atomic writes and safety locks"""
import os
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parent.parent

desc = {
    "action": {
        "type": "string",
        "enum": ["view", "replace", "insert", "delete", "append"],
        "description": "Action to perform: view, replace, insert, delete, or append.",
        "default": "view"
    },
    "path": {
        "type": "string",
        "description": "Relative file path from project root."
    },
    "start_line": {
        "type": "integer",
        "description": "Start line number (1-based, inclusive) for view, replace, or delete.",
        "default": 1
    },
    "end_line": {
        "type": "integer",
        "description": "End line number (1-based, inclusive) for view, replace, or delete. Use -1 for default range.",
        "default": -1
    },
    "after_line": {
        "type": "integer",
        "description": "Line number after which to insert content (0 for beginning of file).",
        "default": 0
    },
    "content": {
        "type": "string",
        "description": "New content for replace, insert, or append.",
        "default": ""
    },
    "expected": {
        "type": "string",
        "description": "Optional expected original content for replace/delete safety verification.",
        "default": ""
    },
    "required": ["action", "path"]
}

def resolve_path(rel_path):
    if not rel_path or not isinstance(rel_path, str):
        return None
    p = Path(rel_path.strip())
    if not p.is_absolute():
        p = (ROOT / p).resolve()
    # Prevent editing .git internals
    try:
        if ".git" in p.parts:
            return None
    except Exception:
        pass
    return p

def read_file_lines(path):
    raw = path.read_bytes()
    # Detect CRLF vs LF
    newline = "\r\n" if b"\r\n" in raw else "\n"
    text = raw.decode("utf-8", errors="replace")
    lines = text.split(newline)
    if lines and lines[-1] == "":
        lines.pop()
    return lines, newline

def write_file_atomic(path, lines, newline):
    path.parent.mkdir(parents=True, exist_ok=True)
    out_text = newline.join(lines) + (newline if lines else "")
    out_bytes = out_text.encode("utf-8")
    
    tmp_path = path.with_suffix(f".{os.getpid()}.{time_id()}.tmp")
    try:
        tmp_path.write_bytes(out_bytes)
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass

def time_id():
    import time
    return time.time_ns() % 1000000

def run(action="view", path="", start_line=1, end_line=-1, after_line=0, content="", expected=""):
    target = resolve_path(path)
    if not target:
        return f"error: invalid or restricted path '{path}'"

    if action == "append":
        newline = "\n"
        lines = []
        if target.is_file():
            lines, newline = read_file_lines(target)
        new_lines = content.splitlines() if content else []
        lines.extend(new_lines)
        write_file_atomic(target, lines, newline)
        return f"appended {len(new_lines)} lines to {path} (total {len(lines)} lines)"

    if not target.is_file():
        return f"error: file not found '{path}'"

    lines, newline = read_file_lines(target)
    total = len(lines)

    if action == "view":
        s = max(1, int(start_line))
        e = int(end_line)
        if e <= 0 or e < s:
            e = min(total, s + 49) # default view up to 50 lines
        s = min(s, max(1, total))
        e = min(e, total)
        out_lines = [f"{i}: {lines[i - 1]}" for i in range(s, e + 1)]
        header = f"[{path} lines {s}-{e} of {total}]:\n"
        return header + "\n".join(out_lines)

    elif action == "insert":
        pos = int(after_line)
        if pos < 0 or pos > total:
            return f"error: after_line {pos} out of range [0, {total}]"
        new_lines = content.splitlines() if content else []
        lines[pos:pos] = new_lines
        write_file_atomic(target, lines, newline)
        return f"inserted {len(new_lines)} lines after line {pos} in {path} (total {len(lines)} lines)"

    elif action == "replace":
        s = int(start_line)
        e = int(end_line) if int(end_line) > 0 else s
        if s < 1 or s > total:
            return f"error: start_line {s} out of range [1, {total}]"
        if e < s or e > total:
            return f"error: end_line {e} out of range [{s}, {total}]"

        original_slice = lines[s - 1 : e]
        if expected:
            # Check expected against original slice
            exp_lines = [l.strip() for l in expected.splitlines()]
            act_lines = [l.strip() for l in original_slice]
            if exp_lines != act_lines:
                act_preview = "\n".join(f"{s + idx}: {original_slice[idx]}" for idx in range(len(original_slice)))
                return f"safety lock error: expected content mismatch at lines {s}-{e}.\nActual file lines:\n{act_preview}\nExpected:\n{expected}"

        new_lines = content.splitlines() if content else []
        lines[s - 1 : e] = new_lines
        write_file_atomic(target, lines, newline)
        return f"replaced lines {s}-{e} with {len(new_lines)} lines in {path} (total {len(lines)} lines)"

    elif action == "delete":
        s = int(start_line)
        e = int(end_line) if int(end_line) > 0 else s
        if s < 1 or s > total:
            return f"error: start_line {s} out of range [1, {total}]"
        if e < s or e > total:
            return f"error: end_line {e} out of range [{s}, {total}]"

        original_slice = lines[s - 1 : e]
        if expected:
            exp_lines = [l.strip() for l in expected.splitlines()]
            act_lines = [l.strip() for l in original_slice]
            if exp_lines != act_lines:
                act_preview = "\n".join(f"{s + idx}: {original_slice[idx]}" for idx in range(len(original_slice)))
                return f"safety lock error: expected content mismatch at lines {s}-{e}.\nActual file lines:\n{act_preview}\nExpected:\n{expected}"

        del lines[s - 1 : e]
        write_file_atomic(target, lines, newline)
        return f"deleted lines {s}-{e} from {path} (total {len(lines)} lines)"

    return f"error: unknown action '{action}'"
