// 会话状态就是 messages 一个数组, 每次请求全量带上; 存哪个文件、叫什么名、要不要新建, 全在这里决定
const chat = document.getElementById("chat");
const sysBox = document.getElementById("sys");
const input = document.getElementById("input");
const sendBtn = document.getElementById("send");
const thinkBoxUI = document.getElementById("think");
const usageEl = document.getElementById("usage");
const serverEl = document.getElementById("server");
const modelEl = document.getElementById("model");
let messages = [];
let convo = "";
let systemPrompt = "";
let lastUsage = null;
let busy = false;

// 新对话名: 本地时间戳, 定长且字典序即时间序, 所以服务端只需按名字排序
function newName() {
  const d = new Date();
  const p = (n, w) => String(n).padStart(w || 2, "0");
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}-${p(d.getMilliseconds(), 3)}`;
}

// 往对话区追加一个普通消息块, 返回元素本身便于继续往里加字
function add(cls, text) {
  const el = document.createElement("div");
  el.className = cls;
  el.textContent = text || "";
  chat.appendChild(el);
  chat.scrollTop = chat.scrollHeight;
  return el;
}

// 追加一个默认收起的块, thinking / 工具结果 / 系统提示用它; 返回内部 pre 便于流式追加
function fold(cls, title, body, parent) {
  const box = document.createElement("details");
  box.className = cls;
  const sum = document.createElement("summary");
  sum.textContent = title;
  const pre = document.createElement("pre");
  pre.textContent = body || "";
  box.append(sum, pre);
  (parent || chat).appendChild(box);
  chat.scrollTop = chat.scrollHeight;
  return pre;
}

// call 文本形如 "技能名 参数JSON"; 技能名来自文件名不含空格, 故按首个空格切
function showCall(text) {
  const i = text.indexOf(" ");
  fold("call", "call " + (i < 0 ? text : text.slice(0, i)), i < 0 ? "" : text.slice(i + 1));
}

// 把 usage 折成一行: 上下文占用 + 本次生成 / 上限 · tok/s
function fmtUsage(u) {
  if (u.prompt_tokens === undefined) return "";
  return `${u.prompt_tokens}+${u.completion_tokens} / ${u.n_ctx}` + (u.tps ? ` · ${u.tps} tok/s` : "");
}

// 当用量达 n_ctx 80% 时压缩历史: 丢弃前半段, 截断点对齐至 user 消息以保证合法轮次
function compress(u) {
  if (!u || !u.n_ctx || (u.prompt_tokens + u.completion_tokens) < u.n_ctx * 0.8) return;
  const mid = Math.floor(messages.length / 2);
  const idx = messages.findIndex((m, i) => i >= mid && m.role === "user");
  const cut = idx > 0 ? idx : messages.findIndex((m, i) => i > 0 && m.role === "user");
  if (cut > 0) {
    messages = messages.slice(cut);
    add("bot", `[上下文用量已达 80%（${u.prompt_tokens}+${u.completion_tokens} / ${u.n_ctx}），已自动压缩早期历史]`);
  }
}

// 服务端每条 SSE 事件按类型落到不同的块里; done 回来的数组要滤掉 system, 那是发送时临时前置的
function paint(ev, st) {
  if (ev.type === "think") {
    if (!st.think) st.think = fold("think", "thinking", "");
    st.think.textContent += ev.text;
  } else if (ev.type === "ans") {
    if (!st.bubble) st.bubble = add("bot");
    st.bubble.textContent += ev.text;
    chat.scrollTop = chat.scrollHeight;
  } else if (ev.type === "call") {
    st.bubble = null;
    st.think = null;
    showCall(ev.text);
  } else if (ev.type === "result") {
    st.bubble = null;
    st.think = null;
    fold("result", "result", ev.text);
  } else if (ev.type === "usage") {
    lastUsage = ev.text;
    usageEl.textContent = fmtUsage(ev.text);
  } else if (ev.type === "done") {
    messages = ev.text.filter((m) => m.role !== "system");
    compress(lastUsage);
  } else if (ev.type === "error") {
    add("err", "error " + ev.text);
  }
}

// 发一轮对话: 把输入追加进 messages, 发送时临时前置 system 消息与选中的模型
async function run() {
  const text = input.value.trim();
  if (!text || busy) return;
  busy = true;
  sendBtn.disabled = true;
  messages.push({role: "user", content: text});
  add("me", text);
  input.value = "";
  const st = {bubble: null, think: null};
  try {
    const resp = await fetch("/chat", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        messages: [{role: "system", content: systemPrompt}].concat(messages),
        thinking: thinkBoxUI.checked,
        conversation: convo,
        server: serverEl.value,
        model: modelEl.value
      }),
    });
    const reader = resp.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    while (true) {
      const {value, done} = await reader.read();
      if (done) break;
      buf += dec.decode(value, {stream: true});
      let cut;
      while ((cut = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, cut).trim();
        buf = buf.slice(cut + 2);
        if (chunk.startsWith("data:")) paint(JSON.parse(chunk.slice(5)), st);
      }
    }
  } catch (e) {
    add("err", String(e));
  }
  busy = false;
  sendBtn.disabled = false;
}

// 把磁盘恢复出来的一条消息画成与实时流一致的样式
function history(m) {
  if (m.reasoning_content) fold("think", "thinking", m.reasoning_content);
  if (m.role === "user") add("me", m.content);
  else if (m.role === "tool") fold("result", "result", m.content);
  else if (m.tool_calls) for (const c of m.tool_calls) showCall(c.function.name + " " + (c.function.arguments || "{}"));
  else if (m.content) add("bot", m.content);
}

// 打开页面先要回磁盘上的对话: 列名字取最新的一个, 没有就新建; 读不到必须报错, 不能装成空对话
async function restore() {
  let names = [];
  try {
    names = await (await fetch("/conversation")).json();
  } catch (e) {
    add("err", "history list failed " + e);
    return;
  }
  convo = names.length ? names[names.length - 1] : newName();
  try {
    const resp = await fetch("/conversation/" + convo);
    const data = await resp.json();
    if (!resp.ok) {
      add("err", "conversation unreadable " + (data.error || resp.status));
      return;
    }
    messages = (data.messages || []).filter((m) => m.role !== "system");
  } catch (e) {
    add("err", "conversation unreadable " + e);
    return;
  }
  messages.forEach(history);
}

// 系统提示由 AGENTS.md 与启动时遍历的技能清单拼接而成, 发送时作为首条 system 消息
async function showSystem() {
  let text = "", skills = [];
  try {
    const r = await fetch("/agents.md");
    text = r.ok ? await r.text() : "";
  } catch (e) {
    text = "fetch failed " + e;
  }
  try {
    const r = await fetch("/skills");
    skills = r.ok ? await r.json() : [];
  } catch (e) {}
  const list = skills.map((s) => `- ${s.name}: ${s.description}\n  parameters: ${JSON.stringify(s.parameters)}`).join("\n");
  const sec = list ? `\n\n## Available Skills\n${list}` : "";
  systemPrompt = ((text.trim() || "(AGENTS.md is empty)") + sec).trim();
  fold("system", "system prompt · AGENTS.md + skills", systemPrompt, sysBox);
}

let cfgCache = null;

// 持久化当前选中的服务器与模型至 config.json
async function saveChoice(server, model) {
  if (!server) return;
  try {
    await fetch("/config", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({server, model: model || ""})
    });
  } catch (e) {}
}

// 联动拉取指定服务器下的模型列表并恢复已选模型
async function loadModels(serverId) {
  if (!serverId) return;
  modelEl.innerHTML = "<option>loading...</option>";
  try {
    const list = await (await fetch("/models?server=" + encodeURIComponent(serverId))).json();
    modelEl.innerHTML = "";
    for (const m of list) {
      const opt = document.createElement("option");
      opt.value = m;
      opt.textContent = m;
      modelEl.appendChild(opt);
    }
    const s = (cfgCache?.["llm-servers"] || []).find((x) => x.id === serverId);
    if (s && s.model && list.includes(s.model)) {
      modelEl.value = s.model;
    } else if (list.length) {
      modelEl.value = list[0];
      if (s) s.model = list[0];
      saveChoice(serverId, list[0]);
    }
  } catch (e) {
    modelEl.innerHTML = "<option value=''>load error</option>";
  }
}

// 读取 config.json 配置并填充服务器列表, 随后联动拉取可用模型
async function initServers() {
  try {
    cfgCache = await (await fetch("/config.json")).json();
    serverEl.innerHTML = "";
    for (const s of cfgCache["llm-servers"]) {
      const opt = document.createElement("option");
      opt.value = s.id;
      opt.textContent = s.id;
      if (s.id === cfgCache["current-llm"]) opt.selected = true;
      serverEl.appendChild(opt);
    }
    await loadModels(serverEl.value);
  } catch (e) {
    add("err", "read config.json failed " + e);
  }
}

serverEl.onchange = async () => {
  await loadModels(serverEl.value);
  const s = (cfgCache?.["llm-servers"] || []).find((x) => x.id === serverEl.value);
  if (s) s.model = modelEl.value;
  saveChoice(serverEl.value, modelEl.value);
};

modelEl.onchange = () => {
  const s = (cfgCache?.["llm-servers"] || []).find((x) => x.id === serverEl.value);
  if (s) s.model = modelEl.value;
  saveChoice(serverEl.value, modelEl.value);
};

initServers();
showSystem();
restore();

sendBtn.onclick = run;
input.onkeydown = (e) => {
  if (e.ctrlKey && e.key === "Enter") run();
};
