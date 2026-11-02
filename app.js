// 会话状态只有 messages 这一个数组, 每次请求全量带上, 服务端不留任何东西
const chat = document.getElementById("chat");
const input = document.getElementById("input");
const sendBtn = document.getElementById("send");
const thinkBoxUI = document.getElementById("think");
let messages = [];
let busy = false;

function add(cls, text) {
  const el = document.createElement("div");
  el.className = cls;
  el.textContent = text || "";
  chat.appendChild(el);
  chat.scrollTop = chat.scrollHeight;
  return el;
}

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
    add("call", "call " + ev.text);
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
      body: JSON.stringify({messages, thinking: thinkBoxUI.checked}),
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

sendBtn.onclick = run;
input.onkeydown = (e) => {
  if (e.ctrlKey && e.key === "Enter") run();
};
