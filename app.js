// 会话状态就是 messages 一个数组, 每次请求全量带上; 存哪个文件、叫什么名、要不要新建, 全在这里决定
const chat = document.getElementById("chat");
const input = document.getElementById("input");
const sendBtn = document.getElementById("send");
const thinkBoxUI = document.getElementById("think");
let messages = [];
let convo = "";
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

// 追加一个默认收起的块, thinking 与工具结果用它, 返回内部 pre 便于流式追加
function fold(cls, title, body) {
  const box = document.createElement("details");
  box.className = cls;
  const sum = document.createElement("summary");
  sum.textContent = title;
  const pre = document.createElement("pre");
  pre.textContent = body || "";
  box.append(sum, pre);
  chat.appendChild(box);
  chat.scrollTop = chat.scrollHeight;
  return pre;
}

// call 文本形如 "技能名 参数JSON"; 技能名来自文件名不含空格, 故按首个空格切
function showCall(text) {
  const i = text.indexOf(" ");
  fold("call", "call " + (i < 0 ? text : text.slice(0, i)), i < 0 ? "" : text.slice(i + 1));
}

// 服务端每条 SSE 事件按类型落到不同的块里
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
  } else if (ev.type === "done") {
    messages = ev.text;
  } else if (ev.type === "error") {
    add("err", "error " + ev.text);
  }
}

// 发一轮对话: 把输入追加进 messages, 逐条消费服务端 SSE 事件渲染
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
      body: JSON.stringify({messages, thinking: thinkBoxUI.checked, conversation: convo}),
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
    messages = data.messages || [];
  } catch (e) {
    add("err", "conversation unreadable " + e);
    return;
  }
  messages.forEach(history);
}

restore();

sendBtn.onclick = run;
input.onkeydown = (e) => {
  if (e.ctrlKey && e.key === "Enter") run();
};
