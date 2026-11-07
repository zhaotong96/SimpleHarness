
// 全屏图片灯箱 (Lightbox)
const lightbox = document.createElement("div");
lightbox.id = "lightbox";
lightbox.className = "hidden";
lightbox.innerHTML = `<img id="lightbox-img" alt="enlarged view"><button id="lightbox-close">&times;</button>`;
document.body.appendChild(lightbox);

const lightboxImg = lightbox.querySelector("#lightbox-img");
const lightboxClose = lightbox.querySelector("#lightbox-close");

function openLightbox(src) {
  if (!src) return;
  lightboxImg.src = src;
  lightbox.classList.remove("hidden");
}

function closeLightbox() {
  lightbox.classList.add("hidden");
  lightboxImg.src = "";
}

lightbox.onclick = (e) => {
  if (e.target === lightbox || e.target === lightboxClose || e.target === lightboxImg) {
    closeLightbox();
  }
};

window.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !lightbox.classList.contains("hidden")) {
    closeLightbox();
  }
});

// 会话状态就是 messages 一个数组, 每次请求全量带上; 存哪个文件、叫什么名、要不要新建, 全在这里决定
const chat = document.getElementById("chat");
const sysBox = document.getElementById("sys");
const input = document.getElementById("input");
const sendBtn = document.getElementById("send");
const thinkBoxUI = document.getElementById("think");
const usageEl = document.getElementById("usage");
const serverEl = document.getElementById("server");
const modelEl = document.getElementById("model");
const previewEl = document.getElementById("preview");
const fileInput = document.getElementById("file");
const graphEl = document.getElementById("graph");
const newBranchBtn = document.getElementById("new-branch-btn");
let currentId = null;
let sessionRecords = [];
let stagedImages = [];
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

// 渲染消息内容: 支持纯文本字符串或包含文本与 image_url 的 parts 数组
function renderContent(el, content) {
  if (typeof content === "string") {
    el.textContent = content;
  } else if (Array.isArray(content)) {
    el.textContent = "";
    for (const part of content) {
      if (part.type === "text") {
        const p = document.createElement("p");
        p.textContent = part.text;
        el.appendChild(p);
      } else if (part.type === "image_url") {
        const img = document.createElement("img");
        img.src = part.image_url?.url || "";
        img.className = "chat-img";
        img.style.cursor = "zoom-in";
        img.title = "点击放大查看";
        img.onclick = () => openLightbox(img.src);
        el.appendChild(img);
      }
    }
  }
}

// 渲染待发送图片的预览缩略图列表
function renderPreview() {
  previewEl.textContent = "";
  stagedImages.forEach((url, i) => {
    const item = document.createElement("div");
    item.className = "preview-item";
    const img = document.createElement("img");
    img.src = url;
    img.className = "preview-thumb";
    const del = document.createElement("span");
    del.className = "preview-del";
    del.textContent = "×";
    del.onclick = () => {
      stagedImages.splice(i, 1);
      renderPreview();
    };
    item.append(img, del);
    previewEl.appendChild(item);
  });
}

// 读取图片文件转为 Base64 Data URL 并加入待发送清单
function stageImageFile(file) {
  if (!file || !file.type.startsWith("image/")) return;
  const reader = new FileReader();
  reader.onload = (e) => {
    stagedImages.push(e.target.result);
    renderPreview();
  };
  reader.readAsDataURL(file);
}

// 从服务端加载不可变账本流并构建分支图谱
async function loadGraph() {
  if (!convo) return;
  try {
    const resp = await fetch("/sessions/" + convo);
    if (!resp.ok) return;
    sessionRecords = await resp.json();
    sessionRecords.forEach((m, i) => {
      if (!m.id) m.id = "m_legacy_" + i;
      if (!m.parent && i > 0) m.parent = sessionRecords[i - 1].id;
    });
    if (!currentId && sessionRecords.length) {
      currentId = sessionRecords[sessionRecords.length - 1].id;
    }
    renderGraph();
  } catch (e) {}
}

// 切换检出至指定历史节点, 从账本重建祖先路径并在前端重绘
async function checkout(targetId) {
  if (!targetId) return;
  const nodeMap = new Map(sessionRecords.map((m) => [m.id, m]));
  if (!nodeMap.has(targetId)) return;

  const chain = [];
  let curr = nodeMap.get(targetId);
  while (curr) {
    chain.unshift(curr);
    curr = curr.parent ? nodeMap.get(curr.parent) : null;
  }

  messages = chain.filter((m) => m.role !== "system").map((m) => {
    const copy = {...m};
    delete copy.server;
    delete copy.model;
    delete copy.ts;
    return copy;
  });
  currentId = targetId;

  chat.textContent = "";
  messages.forEach(history);
  chat.scrollTop = chat.scrollHeight;

  try {
    await fetch("/checkout/" + convo, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({messages})
    });
  } catch (e) {}

  renderGraph();
}

// 渲染分支图谱节点列表: 计算泳道、分支着色、贝塞尔连接线与 SourceGit 风格树状图
function renderGraph() {
  graphEl.textContent = "";
  if (!sessionRecords || !sessionRecords.length) return;

  const nodes = sessionRecords.filter((m) => m.role !== "system");
  if (!nodes.length) return;

  // 确保所有节点具备有效 id 与 parent
  nodes.forEach((m, i) => {
    if (!m.id) m.id = "m_legacy_" + i;
    if (!m.parent && i > 0) m.parent = nodes[i - 1].id;
  });

  const nodeMap = new Map(nodes.map((m) => [m.id, m]));
  const idToIdx = new Map(nodes.map((m, i) => [m.id, i]));

  // 追踪当前检出节点的祖先链 (用于高亮活跃路径)
  const activeChainIds = new Set();
  let curr = currentId ? nodeMap.get(currentId) : null;
  while (curr) {
    activeChainIds.add(curr.id);
    curr = curr.parent ? nodeMap.get(curr.parent) : null;
  }

  // 构建父子拓扑映射
  const childrenMap = new Map();
  for (const m of nodes) {
    const pid = m.parent || "root";
    if (!childrenMap.has(pid)) childrenMap.set(pid, []);
    childrenMap.get(pid).push(m.id);
  }

  // 1. 识别分支 (Branch Detection)
  const branchOfNode = new Map();
  let nextBranchId = 0;

  for (let i = 0; i < nodes.length; i++) {
    const m = nodes[i];
    const pid = m.parent;
    if (!pid || !nodeMap.has(pid)) {
      branchOfNode.set(m.id, nextBranchId++);
    } else {
      const sibs = childrenMap.get(pid);
      if (sibs && sibs[0] === m.id) {
        branchOfNode.set(m.id, branchOfNode.get(pid));
      } else {
        branchOfNode.set(m.id, nextBranchId++);
      }
    }
  }

  // 2. 计算各分支生命周期区间 [startIdx, endIdx] (startIdx 取父节点索引以确保分叉点预先占用泳道)
  const branchSpans = new Map();
  for (let i = 0; i < nodes.length; i++) {
    const m = nodes[i];
    const bId = branchOfNode.get(m.id);
    const pid = m.parent;
    const pIdx = pid && idToIdx.has(pid) ? idToIdx.get(pid) : i;

    if (!branchSpans.has(bId)) {
      branchSpans.set(bId, [pIdx, i]);
    } else {
      branchSpans.get(bId)[1] = i;
    }
  }

  // 3. 贪心区间着色算法分配泳道 (Lane Allocation)
  const laneOfBranch = new Map();
  const sortedBranches = Array.from(branchSpans.entries()).sort((a, b) => a[1][0] - b[1][0]);

  for (const [bId, [start, end]] of sortedBranches) {
    const usedLanes = new Set();
    for (const [otherB, otherLane] of laneOfBranch.entries()) {
      const [oStart, oEnd] = branchSpans.get(otherB);
      if (Math.max(start, oStart) <= Math.min(end, oEnd)) {
        usedLanes.add(otherLane);
      }
    }
    let lane = 0;
    while (usedLanes.has(lane)) lane++;
    laneOfBranch.set(bId, lane);
  }

  // SourceGit 经典分支色盘
  const BRANCH_COLORS = [
    "#4a90e2", // 0: 经典蓝
    "#50b870", // 1: 翡翠绿
    "#f59e0b", // 2: 暖琥珀
    "#a855f7", // 3: 紫罗兰
    "#06b6d4", // 4: 湖蓝青
    "#f43f5e", // 5: 珊瑚红
    "#ec4899", // 6: 霓虹粉
    "#14b8a6", // 7: 薄荷绿
    "#84cc16", // 8: 鲜柠檬
    "#eab308"  // 9: 暖金
  ];

  const ROW_H = 26;
  const LANE_W = 16;
  const PAD_L = 14;

  let maxLane = 0;
  for (const l of laneOfBranch.values()) {
    if (l > maxLane) maxLane = l;
  }
  const svgWidth = PAD_L + (maxLane + 1) * LANE_W + 8;
  const totalHeight = nodes.length * ROW_H;

  // 4. 绘制内联 SVG 泳道图谱画布
  const svgNS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(svgNS, "svg");
  svg.setAttribute("class", "graph-svg-canvas");
  svg.setAttribute("width", String(svgWidth));
  svg.setAttribute("height", String(totalHeight));

  for (let i = 0; i < nodes.length; i++) {
    const m = nodes[i];
    const pid = m.parent;
    if (!pid || !idToIdx.has(pid)) continue;

    const pIdx = idToIdx.get(pid);
    const pLane = laneOfBranch.get(branchOfNode.get(pid)) || 0;
    const cLane = laneOfBranch.get(branchOfNode.get(m.id)) || 0;
    const bId = branchOfNode.get(m.id);
    const color = BRANCH_COLORS[bId % BRANCH_COLORS.length];

    const px = PAD_L + pLane * LANE_W;
    const py = pIdx * ROW_H + ROW_H / 2;
    const cx = PAD_L + cLane * LANE_W;
    const cy = i * ROW_H + ROW_H / 2;

    const isActiveEdge = activeChainIds.has(m.id) && activeChainIds.has(pid);
    const strokeWidth = isActiveEdge ? "2.5" : "1.8";
    const opacity = isActiveEdge ? "1" : "0.45";

    const path = document.createElementNS(svgNS, "path");
    if (px === cx) {
      path.setAttribute("d", `M ${px} ${py} L ${cx} ${cy}`);
    } else {
      if (i === pIdx + 1) {
        path.setAttribute("d", `M ${px} ${py} C ${px} ${py + 13}, ${cx} ${cy - 13}, ${cx} ${cy}`);
      } else {
        const yCurveEnd = py + ROW_H;
        path.setAttribute("d", `M ${px} ${py} C ${px} ${py + 13}, ${cx} ${yCurveEnd - 10}, ${cx} ${yCurveEnd} L ${cx} ${cy}`);
      }
    }
    path.setAttribute("stroke", color);
    path.setAttribute("stroke-width", strokeWidth);
    path.setAttribute("stroke-linecap", "round");
    path.setAttribute("opacity", opacity);
    path.setAttribute("fill", "none");
    svg.appendChild(path);
  }

  graphEl.appendChild(svg);

  // 5. 渲染各节点行
  for (let i = 0; i < nodes.length; i++) {
    const m = nodes[i];
    const isCurrent = m.id === currentId;
    const inPath = activeChainIds.has(m.id);
    const bId = branchOfNode.get(m.id);
    const lane = laneOfBranch.get(bId) || 0;
    const color = BRANCH_COLORS[bId % BRANCH_COLORS.length];
    const dotX = PAD_L + lane * LANE_W;

    const row = document.createElement("div");
    row.className = "graph-node" + (isCurrent ? " checked-out" : inPath ? " in-path" : "");
    row.style.height = `${ROW_H}px`;

    const spacer = document.createElement("div");
    spacer.className = "graph-spacer";
    spacer.style.width = `${svgWidth}px`;

    const dot = document.createElement("span");
    dot.className = "graph-dot";
    dot.style.left = `${dotX - 4}px`;
    dot.style.backgroundColor = color;
    dot.style.color = color;
    spacer.appendChild(dot);

    const roleTag = document.createElement("span");
    roleTag.className = "graph-role " + (m.role || "user");
    roleTag.textContent = m.role === "user" ? "U" : m.role === "assistant" ? "A" : "T";

    let preview = "";
    if (typeof m.content === "string") {
      preview = m.content.replace(/\s+/g, " ").trim();
    } else if (Array.isArray(m.content)) {
      const textPart = m.content.find((p) => p.type === "text");
      preview = (textPart ? textPart.text : "[图片]").trim();
    } else if (m.tool_calls) {
      preview = "call " + m.tool_calls.map((c) => c.function?.name).join(", ");
    }
    if (!preview) preview = m.role || "msg";
    if (preview.length > 20) preview = preview.slice(0, 20) + "...";

    const text = document.createElement("span");
    text.className = "graph-text";
    text.textContent = preview;

    row.title = `ID: ${m.id}\nRole: ${m.role}\nBranch: ${bId} (Lane ${lane})\nParent: ${m.parent || "root"}\n${preview}`;

    row.append(spacer, roleTag, text);
    row.onclick = () => checkout(m.id);
    graphEl.appendChild(row);
  }

  const checkedOutRow = graphEl.querySelector(".graph-node.checked-out");
  if (checkedOutRow) {
    checkedOutRow.scrollIntoView({ block: "nearest" });
  }
}

// 往对话区追加一个普通消息块, 返回元素本身便于继续往里加字
function add(cls, content) {
  const el = document.createElement("div");
  el.className = cls;
  if (content !== undefined && content !== null) renderContent(el, content);
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

  // 若结果包含截图路径 /screenshots/*.png，自动附带缩略图并支持点击放大
  if (cls === "result" && body) {
    const match = body.match(/\/screenshots\/[a-zA-Z0-9_\-\.]+\.png/);
    if (match) {
      box.open = true;
      const url = match[0];
      const thumbWrap = document.createElement("div");
      thumbWrap.className = "tool-thumb-wrap";
      const thumb = document.createElement("img");
      thumb.className = "tool-thumb";
      thumb.src = url;
      thumb.alt = "操作截图";
      thumb.title = "点击放大查看";
      thumb.onclick = (e) => {
        e.stopPropagation();
        openLightbox(url);
      };
      thumbWrap.appendChild(thumb);
      box.appendChild(thumbWrap);
    }
  }

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

// 行内标记渲染: 代码、加粗、斜体, 纯 DOM 操作彻底免疫 XSS
function renderInline(parent, text) {
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*)/g);
  for (const part of parts) {
    if (!part) continue;
    if (part.startsWith("`") && part.endsWith("`") && part.length >= 2) {
      const code = document.createElement("code");
      code.textContent = part.slice(1, -1);
      parent.appendChild(code);
    } else if (part.startsWith("**") && part.endsWith("**") && part.length >= 4) {
      const strong = document.createElement("strong");
      strong.textContent = part.slice(2, -2);
      parent.appendChild(strong);
    } else if (part.startsWith("*") && part.endsWith("*") && part.length >= 2) {
      const em = document.createElement("em");
      em.textContent = part.slice(1, -1);
      parent.appendChild(em);
    } else {
      parent.appendChild(document.createTextNode(part));
    }
  }
}

// 块级 Markdown 渲染: 标题、代码块、列表、引用与段落, 全走 createElement/textContent
function renderMarkdown(container, text) {
  container.textContent = "";
  const lines = text.split("\n");
  let inCode = false, codeLang = "", codeLines = [];
  let currentList = null;
  let paraLines = [];

  const flushPara = () => {
    if (!paraLines.length) return;
    const p = document.createElement("p");
    renderInline(p, paraLines.join("\n"));
    container.appendChild(p);
    paraLines = [];
  };

  const flushList = () => {
    currentList = null;
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (inCode) {
      if (line.startsWith("```")) {
        const pre = document.createElement("pre");
        pre.className = "code-block";
        if (codeLang) {
          const badge = document.createElement("div");
          badge.className = "code-lang";
          badge.textContent = codeLang;
          pre.appendChild(badge);
        }
        const code = document.createElement("code");
        code.textContent = codeLines.join("\n");
        pre.appendChild(code);
        container.appendChild(pre);
        inCode = false;
        codeLines = [];
        codeLang = "";
      } else {
        codeLines.push(line);
      }
      continue;
    }
    if (line.startsWith("```")) {
      flushPara();
      flushList();
      inCode = true;
      codeLang = line.slice(3).trim();
      codeLines = [];
      continue;
    }
    if (!line.trim()) {
      flushPara();
      flushList();
      continue;
    }
    const hMatch = line.match(/^(#{1,6})\s+(.*)$/);
    if (hMatch) {
      flushPara();
      flushList();
      const level = Math.min(5, hMatch[1].length + 2);
      const h = document.createElement("h" + level);
      renderInline(h, hMatch[2]);
      container.appendChild(h);
      continue;
    }
    if (line.startsWith("> ")) {
      flushPara();
      flushList();
      const bq = document.createElement("blockquote");
      renderInline(bq, line.slice(2));
      container.appendChild(bq);
      continue;
    }
    const ulMatch = line.match(/^[\*\-]\s+(.*)$/);
    if (ulMatch) {
      flushPara();
      if (!currentList || currentList.tagName !== "UL") {
        currentList = document.createElement("ul");
        container.appendChild(currentList);
      }
      const li = document.createElement("li");
      renderInline(li, ulMatch[1]);
      currentList.appendChild(li);
      continue;
    }
    const olMatch = line.match(/^(\d+)\.\s+(.*)$/);
    if (olMatch) {
      flushPara();
      if (!currentList || currentList.tagName !== "OL") {
        currentList = document.createElement("ol");
        container.appendChild(currentList);
      }
      const li = document.createElement("li");
      renderInline(li, olMatch[2]);
      currentList.appendChild(li);
      continue;
    }
    flushList();
    paraLines.push(line);
  }

  if (inCode) {
    const pre = document.createElement("pre");
    pre.className = "code-block";
    if (codeLang) {
      const badge = document.createElement("div");
      badge.className = "code-lang";
      badge.textContent = codeLang;
      pre.appendChild(badge);
    }
    const code = document.createElement("code");
    code.textContent = codeLines.join("\n");
    pre.appendChild(code);
    container.appendChild(pre);
  }
  flushPara();
}

// 服务端每条 SSE 事件按类型落到不同的块里; done 回来的数组要滤掉 system, 那是发送时临时前置的
function paint(ev, st) {
  if (ev.type === "think") {
    if (!st.think) st.think = fold("think", "thinking", "");
    st.think.textContent += ev.text;
  } else if (ev.type === "ans") {
    if (!st.bubble) {
      st.bubble = add("bot");
      st.raw = "";
    }
    st.raw += ev.text;
    renderMarkdown(st.bubble, st.raw);
    chat.scrollTop = chat.scrollHeight;
  } else if (ev.type === "call") {
    st.bubble = null;
    st.raw = "";
    st.think = null;
    showCall(ev.text);
  } else if (ev.type === "result") {
    st.bubble = null;
    st.raw = "";
    st.think = null;
    fold("result", "result", ev.text);
  } else if (ev.type === "usage") {
    lastUsage = ev.text;
    usageEl.textContent = fmtUsage(ev.text);
  } else if (ev.type === "done") {
    messages = ev.text.filter((m) => m.role !== "system");
    if (messages.length) currentId = messages[messages.length - 1].id;
    compress(lastUsage);
    loadGraph();
  } else if (ev.type === "error") {
    add("err", "error " + ev.text);
  }
}

// 发一轮对话: 把输入追加进 messages, 发送时临时前置 system 消息与选中的模型
async function run() {
  const text = input.value.trim();
  if ((!text && !stagedImages.length) || busy) return;
  busy = true;
  sendBtn.disabled = true;

  let userContent = text;
  if (stagedImages.length) {
    const parts = [];
    if (text) parts.push({type: "text", text});
    for (const url of stagedImages) {
      parts.push({type: "image_url", image_url: {url}});
    }
    userContent = parts;
    stagedImages = [];
    renderPreview();
  }

  const userMsgId = "m_" + Date.now();
  const userMsg = {id: userMsgId, parent: currentId, role: "user", content: userContent};
  messages.push(userMsg);
  currentId = userMsgId;
  add("me", userContent);
  input.value = "";
  const st = {bubble: null, think: null, raw: ""};
  try {
    const resp = await fetch("/chat", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        messages: [{role: "system", content: systemPrompt}].concat(messages),
        thinking: thinkBoxUI.checked,
        conversation: convo,
        server: serverEl.value,
        model: modelEl.value,
        parent_id: userMsg.parent,
        node_id: userMsg.id
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
  else if (m.content) renderMarkdown(add("bot"), m.content);
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
  if (messages.length) {
    currentId = messages[messages.length - 1].id || null;
  }
  await loadGraph();
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

fileInput.onchange = () => {
  if (fileInput.files.length) {
    stageImageFile(fileInput.files[0]);
    fileInput.value = "";
  }
};

input.onpaste = (e) => {
  const items = e.clipboardData?.items;
  if (!items) return;
  for (const item of items) {
    if (item.type.startsWith("image/")) {
      e.preventDefault();
      stageImageFile(item.getAsFile());
    }
  }
};

input.ondragover = (e) => e.preventDefault();
input.ondrop = (e) => {
  e.preventDefault();
  const files = e.dataTransfer?.files;
  if (files && files.length) {
    for (const f of files) stageImageFile(f);
  }
};

newBranchBtn.onclick = () => {
  convo = newName();
  messages = [];
  currentId = null;
  sessionRecords = [];
  chat.textContent = "";
  graphEl.textContent = "";
  renderGraph();
};

sendBtn.onclick = run;
input.onkeydown = (e) => {
  if (e.ctrlKey && e.key === "Enter") run();
};
