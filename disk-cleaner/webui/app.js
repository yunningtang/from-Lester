/* 留白：界面逻辑。数据全部来自后端（core/api.py），这里只负责显示和把用户的选择传回去。
   删除流程：选择 → plan()（只读预检）→ 原地确认 → execute() → 结果。界面从不直接删文件。 */
"use strict";

const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
const app = $("app"), cv = $("cv"), ctx = cv.getContext("2d");
const PAPER = "#FCFBF8";
const GB = 1024 ** 3;

// ---------------------------------------------------------------- 和后端说话
let viaWebview = false;
function call(name, ...args) {
  if (viaWebview) return window.pywebview.api[name](...args);
  return fetch("/api/" + name, { method: "POST", body: JSON.stringify(args) }).then(r => r.json());
}

// ---------------------------------------------------------------- 状态
const S = {
  st: null, version: -1,
  picked: new Set(), seen: new Set(), open: new Set(),   // 缓存：已选、见过的、展开的分组
  focus: null, detail: null, marks: new Set(),             // 细看
  act: { where: null, phase: "idle", plan: null },         // 操作区：idle / checking / ask / running / done
  hover: null, cur: {}, target: {}, free: 0, freeT: 0,
  tree: null, treeKeys: "", blocks: [], t0: performance.now(),
};

// ---------------------------------------------------------------- 格式
const fmt = b => { const g = (b || 0) / GB; return g >= 10 ? g.toFixed(0) + " G" : g >= .1 ? g.toFixed(1) + " G" : Math.round((b || 0) / 1024 ** 2) + " M"; };
const fmtG = g => g >= 10 ? g.toFixed(0) : g.toFixed(1);

// 墨色分五级：大小相近的块用同一种墨
const TIERS = [
  { min: 40, c: [32, 30, 28], label: "40 G 以上" },
  { min: 20, c: [82, 79, 74], label: "20–40 G" },
  { min: 8, c: [120, 116, 109], label: "8–20 G" },
  { min: 3, c: [162, 158, 150], label: "3–8 G" },
  { min: 0, c: [204, 200, 191], label: "3 G 以下" },
];
const tierOf = g => TIERS.findIndex(t => g >= t.min);
const jit = k => { let h = 0; for (const ch of k) h = (h * 31 + ch.charCodeAt(0)) % 997; return (h % 11 - 5) * 1.6; };
const toneOf = (g, k) => TIERS[tierOf(g)].c.map(v => Math.max(0, Math.min(255, Math.round(v + jit(k)))));
const rgb = c => `rgb(${c[0]},${c[1]},${c[2]})`;
const isDark = c => c[0] < 128;
const cacheKey = k => k.startsWith("c:") ? k.slice(2) : null;

// ---------------------------------------------------------------- 收到新状态
function applyState(st) {
  S.st = st;
  // 缓存默认勾选：只在第一次见到时按默认值设，之后尊重用户的选择
  for (const c of st.cleanables) if (!S.seen.has(c.key)) { S.seen.add(c.key); if (c.default) S.picked.add(c.key); }
  // 画里的块：目标大小（GB），新出现的从 0 长出来
  S.blocks = st.blocks;
  const keys = new Set();
  for (const b of st.blocks) {
    keys.add(b.key);
    S.target[b.key] = b.size / GB;
    if (!(b.key in S.cur)) S.cur[b.key] = reduce ? b.size / GB : 0;
  }
  for (const k in S.target) if (!keys.has(k)) S.target[k] = 0;
  S.freeT = st.free / GB;
  if (!S.free) S.free = S.freeT;
  // 块的集合变了才重新切分（扫描过程中会变几次）
  const sig = st.blocks.map(b => b.key).sort().join("|");
  if (sig !== S.treeKeys) {
    S.treeKeys = sig;
    const items = st.blocks.map(b => ({ k: b.key, v: Math.max(b.size, 1) })).sort((a, b) => b.v - a.v);
    S.tree = items.length ? buildTree(items, rng(20261114)) : null;
  }
  // 后台的清理结束了
  if (st.job && st.job.done && S.act.phase === "running") {
    S.act.phase = "done";
    if (S.focus) reloadDetail();
  }
  render();
}

// ---------------------------------------------------------------- 画
// W、H、portrait 在 ink.js 里声明
let shapes = {}, paperPoly = null, ripples = [], lastProbe = -1e9;
function resize() {
  const r = app.getBoundingClientRect(), d = Math.min(2, devicePixelRatio || 1);
  W = r.width; H = r.height; portrait = H > W * .95;
  cv.width = Math.round(W * d); cv.height = Math.round(H * d);
  ctx.setTransform(d, 0, 0, d, 0, 0);
  const tw = Math.max(1, Math.round(W)), th = Math.max(1, Math.round(H));
  if (!paperTex || Math.abs(paperTex.width - tw - 40) > 40 || Math.abs(paperTex.height - th - 40) > 40) {
    paperTex = buildPaper(tw + 40, th + 40); washTex = buildWash(tw + 40, th + 40);
  }
}
const center = s => [s.reduce((a, p) => a + p[0], 0) / s.length, s.reduce((a, p) => a + p[1], 0) / s.length];
const blockOf = k => S.blocks.find(b => b.key === k);

function frame(now) {
  const t = reduce ? 3 : (now - S.t0) / 1000;
  const used = Object.values(S.cur).reduce((a, b) => a + b, 0);
  const minFrac = portrait ? .55 : .36;
  const paperFrac = Math.max(S.free / (S.free + used || 1), minFrac);
  const all = [[0, 0], [W, 0], [W, H], [0, H]];
  const [pp, rest] = split(all, paperFrac, (portrait ? Math.PI / 2 : 0) + .12);
  paperPoly = pp;
  shapes = {};
  if (S.tree) {
    const raw = {}; layoutTree(S.tree, rest, raw, k => Math.max(S.cur[k] || 0, 1e-6));
    for (const b of S.blocks) if (raw[b.key] && raw[b.key].length > 2 && S.cur[b.key] > .02) shapes[b.key] = wobble(raw[b.key], t);
  }
  const unionPath = () => { ctx.beginPath(); for (const k in shapes) { shapes[k].forEach((p, i) => i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1])); ctx.closePath(); } };
  const picked = k => { const c = cacheKey(k); return c && S.picked.has(c); };

  ctx.drawImage(paperTex, 0, 0);
  // 墨：正片叠底画在纸上，纸纹透出来
  ctx.save(); ctx.globalCompositeOperation = "multiply";
  for (const b of S.blocks) {
    const s = shapes[b.key]; if (!s) continue;
    trace(s); ctx.fillStyle = rgb(toneOf(S.cur[b.key], b.key));
    ctx.globalAlpha = picked(b.key) ? .72 : 1; ctx.fill(); ctx.globalAlpha = 1;
  }
  ctx.restore();
  ctx.save(); unionPath(); ctx.clip();
  ctx.globalCompositeOperation = "soft-light"; ctx.globalAlpha = .45; ctx.drawImage(washTex, -20 + (reduce ? 0 : Math.sin(t * .05) * 12), -20);
  ctx.globalCompositeOperation = "screen"; ctx.globalAlpha = .07; ctx.drawImage(paperTex, 0, 0);
  ctx.restore();
  for (const b of S.blocks) {
    const s = shapes[b.key]; if (!s) continue;
    const dark = isDark(toneOf(S.cur[b.key], b.key));
    ctx.save(); trace(s); ctx.clip();
    for (const [w, a] of [[12, .03], [4, .06]]) { ctx.lineWidth = w; ctx.strokeStyle = `rgba(10,9,8,${a})`; trace(s); ctx.stroke(); }
    if (S.hover === b.key) { trace(s); ctx.fillStyle = dark ? "rgba(252,251,248,.12)" : "rgba(10,9,8,.08)"; ctx.fill(); }
    if (picked(b.key)) {
      const [cx, cy] = center(s);
      for (let j = 0; j < 4; j++) {
        const r = ((t * 22 + j * 26) % 104) + 6;
        ctx.strokeStyle = `rgba(252,251,248,${.5 * (1 - r / 110)})`; ctx.lineWidth = 1.1; ctx.beginPath(); ctx.arc(cx, cy, r, 0, 7); ctx.stroke();
      }
    }
    ctx.restore();
  }
  ctx.save(); unionPath(); if ("filter" in ctx) ctx.filter = "blur(.7px)";
  ctx.strokeStyle = "rgba(252,251,248,.13)"; ctx.lineWidth = 1.2; ctx.stroke(); ctx.restore();
  // 细看时其余的墨淡下去
  if (S.focus && shapes[S.focus]) {
    for (const k in shapes) if (k !== S.focus) { trace(shapes[k]); ctx.fillStyle = "rgba(252,251,248,.62)"; ctx.fill(); }
  }
  // 纸盖回来，边缘洇开
  const pw = wobble(paperPoly, t).map(([x, y]) => [x <= .5 ? -30 : x >= W - .5 ? W + 30 : x, y <= .5 ? -30 : y >= H - .5 ? H + 30 : y]);
  ctx.save(); trace(pw); ctx.clip(); ctx.drawImage(paperTex, 0, 0); ctx.restore();
  ctx.save(); trace(pw); ctx.clip(); if ("filter" in ctx) ctx.filter = "blur(4px)";
  ctx.lineWidth = 10; ctx.strokeStyle = "rgba(60,56,50,.16)"; trace(pw); ctx.stroke(); ctx.restore();
  ctx.save(); if ("filter" in ctx) ctx.filter = "blur(5px)";
  ctx.globalAlpha = .55; ctx.lineWidth = 8; ctx.strokeStyle = PAPER; trace(pw); ctx.stroke(); ctx.restore();
  // 标签：块越大字越大
  const NAME = [19, 16, 14, 13, 12], SIZE = [14, 12.5, 12, 11, 11];
  for (const b of S.blocks) {
    const s = shapes[b.key]; if (!s) continue;
    const xs = s.map(p => p[0]), ys = s.map(p => p[1]);
    const bw = (Math.max(...xs) - Math.min(...xs)) * .7, bh = (Math.max(...ys) - Math.min(...ys)) * .7;
    const [cx, cy] = center(s), g = S.cur[b.key], ti = tierOf(g);
    const dim = S.focus && S.focus !== b.key, dark = isDark(toneOf(g, b.key)) && !dim;
    ctx.globalAlpha = dim ? .35 : 1; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    const label = `${fmtG(g)} G`;
    ctx.font = `${ti < 2 ? 500 : 400} ${NAME[ti]}px "Noto Serif SC", serif`;
    if (bh > NAME[ti] * 2.6 && ctx.measureText(b.name).width < bw) {
      ctx.fillStyle = dark ? "#F7F4EC" : "#141413"; ctx.fillText(b.name, cx, cy - NAME[ti] * .62);
      ctx.font = `300 ${SIZE[ti]}px "Noto Serif SC", serif`; ctx.fillStyle = dark ? "rgba(247,244,236,.72)" : "rgba(20,20,19,.62)";
      ctx.fillText(picked(b.key) ? `${label} · 已选` : label, cx, cy + NAME[ti] * .72);
    } else {
      ctx.font = `300 ${SIZE[ti]}px "Noto Serif SC", serif`; ctx.fillStyle = dark ? "rgba(247,244,236,.8)" : "rgba(20,20,19,.7)";
      if (bh > 16 && ctx.measureText(label).width < bw) ctx.fillText(label, cx, cy);
    }
    ctx.globalAlpha = 1;
  }
  const nowms = performance.now();
  ripples = ripples.filter(r => nowms - r.t < 2400);
  for (const r of ripples) {
    const k = (nowms - r.t) / 2400;
    for (let j = 0; j < 3; j++) { const kk = k - j * .1; if (kk <= 0) continue; ctx.strokeStyle = `rgba(22,22,22,${.2 * (1 - kk)})`; ctx.lineWidth = 1; ctx.beginPath(); ctx.arc(r.x, r.y, 8 + kk * 140, 0, 7); ctx.stroke(); }
  }
  placePaper();
  if (now - lastProbe > 400) { lastProbe = now; probeCtrl(); }
}

// 文字放在纸上
function placePaper() {
  const box = $("paper"), pad = Math.max(24, Math.min(W, H) * .045), TB = 32;
  box.style.left = pad + "px"; box.style.top = (TB + pad * .5) + "px";
  if (!portrait) {
    const rightX = Math.min(...paperPoly.filter(p => p[0] > 1).map(p => p[0]));
    box.style.width = Math.max(240, Math.min(420, rightX - pad * 1.4 - 14)) + "px";
    box.style.height = (H - TB - pad * 1.5) + "px";
  } else {
    const bottomY = Math.min(...paperPoly.filter(p => p[1] > 1).map(p => p[1]));
    box.style.width = (W - pad * 2) + "px";
    box.style.height = Math.max(240, bottomY - TB - pad) + "px";
  }
}

// 右上角三个按钮：看底下墨的深浅，自动变浅或变深
function probeCtrl() {
  const d = Math.min(2, devicePixelRatio || 1), x = Math.round((W - 138) * d), y = Math.round(6 * d), w = Math.round(132 * d), h = Math.round(20 * d);
  if (x < 0) return;
  try {
    const px = ctx.getImageData(x, y, w, h).data; let s = 0;
    for (let i = 0; i < px.length; i += 16) s += px[i] * .3 + px[i + 1] * .59 + px[i + 2] * .11;
    $("tbCtrl").classList.toggle("on-dark", s / (px.length / 16) < 140);
  } catch (e) { /* 忽略 */ }
}

// ---------------------------------------------------------------- 全貌
const GROUP_ORDER = ["系统", "浏览器", "聊天和办公", "开发工具"];
const GROUP_NAME = { "系统": "系统临时文件", "浏览器": "浏览器缓存", "聊天和办公": "聊天和办公软件", "开发工具": "开发工具缓存" };

function renderHome() {
  const st = S.st; if (!st) return;
  const pct = st.total ? Math.round(st.used / st.total * 100) : 0;
  const drv = st.drive.replace(/[:\\/]+$/, "");
  $("meta").textContent = `${drv ? drv + " 盘" : "磁盘"} · 共 ${fmt(st.total)} · 已用 ${pct}%`;
  // 状态：一句话说清现在是什么情况、下一步可以做什么
  const cl = st.cleanables, sel = cl.filter(c => S.picked.has(c.key));
  if (st.error) $("status").textContent = st.error;
  else if (st.scanning) $("status").innerHTML = `${esc(st.phase || "正在扫描…")}<span class="bar"><i></i></span>`;
  else if (!cl.length && !st.suggest.length) $("status").textContent = "没有发现需要清理的。";
  else $("status").innerHTML = cl.length
    ? `有 <b>${fmt(st.safe_total)}</b> 可以放心清掉${st.suggest.length ? `，另有 ${st.suggest.length} 块值得看看` : ""}。`
    : `能放心清的都清了。${st.suggest.length ? "下面几块值得看看。" : ""}`;

  // 可放心清理：按分组显示，一组一行；点“展开”看每一项
  $("safeBlock").hidden = !cl.length;
  $("safeSum").textContent = cl.length ? fmt(st.safe_total) : "";
  $("all").textContent = cl.length && cl.every(c => S.picked.has(c.key)) ? "全不选" : "全选";
  const groups = GROUP_ORDER.map(g => [g, cl.filter(c => (c.group || "系统") === g)]).filter(([, cs]) => cs.length);
  $("groups").innerHTML = groups.map(([g, cs]) => {
    const on = cs.filter(c => S.picked.has(c.key)).length, size = cs.reduce((a, c) => a + c.size, 0), open = S.open.has(g);
    const dot = on === cs.length ? "on" : on ? "half" : "";
    return `<div class="grp"><button class="row${on ? "" : " off"}" data-g="${g}" aria-pressed="${on === cs.length}">
      <span class="dot ${dot}"></span><span>${GROUP_NAME[g]}<span class="sub">${cs.length} 项</span></span><span class="size">${fmt(size)}</span><span class="more" data-more="${g}">${open ? "收起" : "展开"}</span></button>
      ${open ? `<div class="items">${cs.map(c => `<button class="row${S.picked.has(c.key) ? "" : " off"}" data-c="${c.key}" aria-pressed="${S.picked.has(c.key)}"><span class="dot ${S.picked.has(c.key) ? "on" : ""}"></span><span>${esc(c.name)}</span><span class="size">${fmt(c.size)}</span><span class="note">${esc(c.note)}</span></button>`).join("")}</div>` : ""}</div>`;
  }).join("");

  // 值得看看：最大的几块“你的文件”
  $("lookBlock").hidden = !st.suggest.length;
  $("looks").innerHTML = st.suggest.map(s => `<button class="look" data-open="${s.key}"><span class="n">${esc(s.name)}</span><span class="s">${fmt(s.size)}</span>
    <span class="h">${s.maybe === null ? "正在看里面…" : s.maybe > 0 ? `约 <b>${fmt(s.maybe)}</b> 可能不再需要` : "没发现明显不需要的"}</span></button>`).join("");

  $("num").textContent = fmtG(S.free || st.free / GB);
  $("binLine").innerHTML = st.bin > 0 ? `回收站里有 ${fmt(st.bin)}，清空后才会空出来 · <button class="link u" data-act="openbin">打开回收站</button>` : "";
  renderAct($("homeAct"), "home", sel.length, sel.reduce((a, c) => a + c.size, 0));
}

// ---------------------------------------------------------------- 操作区（两个视图共用）
function renderAct(el, where, n, bytes) {
  const a = S.act, mine = a.where === where;
  const st = S.st, job = st && st.job;
  if (mine && a.phase === "checking") { el.innerHTML = `<div class="card"><p>正在检查每一项能不能安全地移到回收站…</p></div>`; return; }
  if (mine && a.phase === "ask" && a.plan) {
    const p = a.plan;
    if (!p.count) {
      el.innerHTML = `<div class="card"><p class="lead">这些都不能移。</p>${refusedList(p)}<div class="btns"><button class="link u" data-act="no">好</button></div></div>`;
      return;
    }
    el.innerHTML = `<div class="card" role="group" aria-label="确认">
      <p class="lead">把 ${p.count} 项移到回收站，共 <b>${fmt(p.total)}</b>。</p>
      ${p.then.map(x => `<p>${esc(x)}</p>`).join("")}
      ${p.refused_count ? refusedList(p) : ""}
      ${p.warnings.map(w => `<p class="fine">${esc(w)}</p>`).join("")}
      <div class="btns"><button class="yes" data-act="yes">确定</button><button class="link u" data-act="no">再想想</button></div></div>`;
    return;
  }
  if (mine && job && (a.phase === "running" || a.phase === "done")) {
    if (job.running) {
      const pc = job.count ? Math.round((job.index + 1) / job.count * 100) : 0;
      el.innerHTML = `<div class="card"><p>正在移到回收站 ${Math.min(job.index + 1, job.count)} / ${job.count}</p><div class="progress"><i style="width:${pc}%"></i></div></div>`;
    } else {
      el.innerHTML = `<div class="card"><p class="lead">已移到回收站 ${job.moved} 项，共 <b>${fmt(job.trashed)}</b>。</p>
        <p class="fine">清空回收站后，这些空间才会空出来。想找回，也在回收站里。</p>
        ${job.failed.length ? `<details><summary>${job.failed.length} 项没有移动</summary><ul>${job.failed.map(([p, w]) => `<li>${esc(base(p))}：${esc(w)}</li>`).join("")}</ul></details>` : ""}
        ${job.log_unsaved ? `<p class="fine">有 ${job.log_unsaved} 条清理记录没写进文件。</p>` : ""}
        <div class="btns"><button class="yes" data-act="openbin">打开回收站</button><button class="link u" data-act="ok">好</button></div></div>`;
    }
    return;
  }
  const busy = st && (st.scanning || (job && job.running));
  el.innerHTML = `<button class="go" data-act="ask"${n && !busy ? "" : " disabled"}>移到回收站${n ? `（${n} 项 · ${fmt(bytes)}）` : ""}</button>`;
}
const base = p => p.split(/[\\/]/).filter(Boolean).pop() || p;
// 只有文件夹名看不出是什么时（比如 “http”），带上上一级：pip / http
const base2 = p => { const parts = p.split(/[\\/]/).filter(Boolean); return parts.length > 1 ? parts.slice(-2).join(" / ") : (parts[0] || p); };
function refusedList(p) {
  return `<details><summary>另有 ${p.refused_count} 项不会动</summary><ul>${p.refused.map(([x, w]) => `<li>${esc(base(x))}：${esc(w)}</li>`).join("")}</ul></details>`;
}

async function askPlan() {
  const where = S.focus ? "detail" : "home";
  S.act = { where, phase: "checking", plan: null }; render();
  const plan = where === "home"
    ? await call("plan", "caches", [...S.picked])
    : await call("plan", "files", [...S.marks]);
  if (S.act.where !== where || S.act.phase !== "checking") return;   // 用户已经走开了
  S.act = { where, phase: "ask", plan }; render();
  const y = app.querySelector(".card .yes"); if (y) y.focus({ preventScroll: true });
}
async function confirmPlan() {
  const { where, plan } = S.act;
  const r = await call("execute", plan.id);
  if (!r.started) { S.act = { where, phase: "idle", plan: null }; render(); $("status").textContent = r.why || "没有开始"; return; }
  S.act = { where, phase: "running", plan };
  // 在画上标出要化开的墨
  if (where === "home") for (const k of S.picked) { const s = shapes["c:" + k]; if (s) { const [x, y] = center(s); ripples.push({ x, y, t: performance.now() }); } }
  else if (shapes[S.focus]) { const [x, y] = center(shapes[S.focus]); ripples.push({ x, y, t: performance.now() }); }
  if (where === "detail") S.marks.clear();
  render(); poll(true);
}

// ---------------------------------------------------------------- 细看
async function openDetail(key) {
  S.focus = key; S.detail = null; S.marks.clear();
  if (S.act.where === "detail") S.act = { where: null, phase: "idle", plan: null };
  $("home").hidden = true; const d = $("detail"); d.hidden = false; d.classList.remove("enter"); void d.offsetWidth; d.classList.add("enter");
  render(); $("back").focus({ preventScroll: true });
  const res = await call("inspect", key);
  if (S.focus !== key) return;
  S.detail = res; render();
}
async function reloadDetail() {
  if (!S.focus || S.focus === "history") return;
  const res = await call("inspect", S.focus);
  S.detail = res; render();
}
function closeDetail() {
  S.focus = null; S.detail = null; S.marks.clear();
  if (S.act.where === "detail" && S.act.phase !== "running") S.act = { where: null, phase: "idle", plan: null };
  $("detail").hidden = true; const h = $("home"); h.hidden = false; h.classList.remove("enter"); void h.offsetWidth; h.classList.add("enter");
  render();
}

const OPEN_BY_DEFAULT = new Set(["maybe", "mine"]);
function renderDetail() {
  const d = S.detail, b = blockOf(S.focus);
  if (S.focus === "history") return renderHistory();
  $("dname").textContent = (d && d.name) || (b && b.name) || "";
  if (!d) {
    $("dmeta").textContent = b ? fmt(b.size) : "";
    $("dsum").textContent = ""; $("dbody").innerHTML = `<div class="loading">正在看里面有什么…</div>`; $("detailAct").innerHTML = ""; return;
  }
  if (d.missing) { $("dbody").innerHTML = `<div class="loading">这一块已经不在了。</div>`; $("dsum").textContent = ""; $("detailAct").innerHTML = ""; return; }
  const where = d.paths && d.paths.length ? ` · ${d.paths[0]}${d.paths.length > 1 ? ` 等 ${d.paths.length} 处` : ""}` : "";
  // 路径太长时从左边省略，留住最后的文件夹名
  $("dmeta").innerHTML = `<bdi>${esc(fmt(d.size) + where)}</bdi>`;
  if (!d.groups.length) {
    $("dsum").textContent = "";
    $("dbody").innerHTML = `<div class="info">${(d.info || "").split(/\n+/).map(p => `<p>${esc(p)}</p>`).join("")}
      ${d.key === "bin" ? `<p><button class="link u" data-act="openbin">打开回收站</button></p>` : ""}
      ${d.kind === "sys" ? `<p><button class="link u" data-act="storage">打开“存储”设置</button></p>` : ""}
      ${d.kind === "cache" ? `<p>在全貌里勾选它，会和其他缓存一起清理。</p>` : ""}</div>`;
    $("detailAct").innerHTML = ""; return;
  }
  $("dsum").innerHTML = d.maybe > 0 ? `约 <b>${fmt(d.maybe)}</b> 可能不再需要。` : "没发现明显不需要的东西。";
  const body = $("dbody"), keep = body.scrollTop;
  body.innerHTML = d.groups.map(g => {
    const open = OPEN_BY_DEFAULT.has(g.lvl) || S.open.has("d:" + g.lvl);
    const allMarked = g.lvl === "maybe" && g.items.every(f => S.marks.has(f.id));
    const right = g.lvl === "maybe" ? `<button class="link u" data-allmarks="1">${allMarked ? "全不移" : "全部移走"}</button>`
      : `<button class="link" data-dopen="${g.lvl}">${open ? "收起" : "展开"}</button>`;
    return `<div class="gh"><span>${g.title}</span><span class="gs">${g.items.length} 项 · ${fmt(g.size)}</span>${right}</div>` +
      (open ? g.items.map(f => fileRow(f, g.lvl)).join("") : "");
  }).join("") + (d.rest && d.rest.count ? `<div class="rest">其余 ${d.rest.count} 个文件 · ${fmt(d.rest.size)} · 都不大，或者看不出该怎么处理</div>` : "");
  body.scrollTop = keep;
  const sel = d.groups.flatMap(g => g.items).filter(f => S.marks.has(f.id));
  // 有可以移走的，或者刚移完（要显示结果），就显示操作区
  if (d.groups.some(g => g.lvl === "maybe") || S.act.where === "detail") renderAct($("detailAct"), "detail", sel.length, sel.reduce((a, f) => a + f.size, 0));
  else $("detailAct").innerHTML = "";
}
function fileRow(f, lvl) {
  const marked = S.marks.has(f.id);
  const acts = lvl === "maybe"
    ? `<button class="link${marked ? " on" : ""}" data-mark="${f.id}" aria-pressed="${marked}">移走</button><button class="link" data-keep="${f.id}">留着</button>`
    : "";
  return `<div class="file${lvl === "keep" || lvl === "lock" ? " muted" : ""}${marked ? " marked" : ""}">
    <div class="l1"><span title="${esc(f.path)}">${esc(f.name)}</span><span>${fmt(f.size)}</span></div>
    <div class="why">${esc(f.why)}</div>
    <div class="do">${acts}<button class="link" data-reveal="${esc(f.path)}">在文件夹中显示</button></div></div>`;
}

// 清理记录
async function openHistory() {
  S.focus = "history"; S.detail = null;
  $("home").hidden = true; $("detail").hidden = false;
  render();
  S.detail = await call("history"); render();
}
function renderHistory() {
  $("dname").textContent = "清理记录";
  const recs = (S.detail && S.detail.records) || [];
  const ok = recs.filter(r => r.ok);
  $("dmeta").textContent = recs.length ? `移到回收站 ${ok.length} 项 · ${fmt(ok.reduce((a, r) => a + (r.size || 0), 0))}` : "";
  $("dsum").textContent = recs.length ? "想找回，到回收站里右键“还原”。" : "";
  $("dbody").innerHTML = S.detail ? (recs.length ? recs.map(r => `<div class="file${r.ok ? "" : " muted"}">
      <div class="l1"><span title="${esc(r.path)}">${esc(base2(r.path))}</span><span>${r.size ? fmt(r.size) : ""}</span></div>
      <div class="why">${esc((r.time || "").replace("T", " "))} · ${r.ok ? "移到回收站" : "没有移动：" + esc(r.error)}</div></div>`).join("") : `<div class="loading">还没有清理过。</div>`)
    : `<div class="loading">正在读取…</div>`;
  $("detailAct").innerHTML = recs.length ? `<button class="go" data-act="openbin">打开回收站</button>` : "";
}

function render() {
  if (S.focus) renderDetail(); else renderHome();
  if (reduce) frame(performance.now());
}

// ---------------------------------------------------------------- 交互
const slip = $("slip");
const KIND = { user: "你的文件", app: "程序和应用数据", sys: "系统", cache: "可放心清理", bin: "回收站" };
const TIP = { user: "点开看看里面有什么", app: "点开看说明", sys: "点开看说明", cache: "点一下选上或取消", bin: "点开看说明" };
function pickAt(x, y) { for (const k in shapes) if (inside(shapes[k], x, y)) return blockOf(k); return null; }
cv.addEventListener("mousemove", e => {
  const r = cv.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top, b = pickAt(x, y);
  S.hover = b ? b.key : null;
  cv.classList.toggle("pointer", !!b && b.key !== "pending");
  if (!b || b.key === "pending") { slip.classList.remove("on"); return; }
  slip.innerHTML = `${esc(b.name)}　${fmt(b.size)}<em>${KIND[b.kind] || ""}</em><span class="tip">${S.focus === b.key ? "正在细看" : TIP[b.kind] || ""}</span>`;
  slip.style.left = Math.min(x + 16, W - 270) + "px"; slip.style.top = (y + 18 + 80 > H ? y - 80 : y + 18) + "px";
  slip.classList.add("on");
});
cv.addEventListener("mouseleave", () => { S.hover = null; slip.classList.remove("on"); });
cv.addEventListener("click", e => {
  const r = cv.getBoundingClientRect(), b = pickAt(e.clientX - r.left, e.clientY - r.top);
  if (!b || b.key === "pending") return;
  const c = cacheKey(b.key);
  if (c && !S.focus) { togglePick([c]); return; }
  openDetail(b.key);
});
function togglePick(keys, on) {
  const all = on ?? !keys.every(k => S.picked.has(k));
  keys.forEach(k => all ? S.picked.add(k) : S.picked.delete(k));
  if (S.act.where === "home" && S.act.phase !== "running") S.act = { where: null, phase: "idle", plan: null };
  render();
}

document.addEventListener("click", e => {
  const more = e.target.closest("[data-more]");
  if (more) { const g = more.dataset.more; S.open.has(g) ? S.open.delete(g) : S.open.add(g); render(); return; }
  const t = e.target.closest("button"); if (!t) return;
  const d = t.dataset;
  if (d.g) { togglePick(S.st.cleanables.filter(c => (c.group || "系统") === d.g).map(c => c.key)); return; }
  if (d.c) { togglePick([d.c]); return; }
  if (d.open) { openDetail(d.open); return; }
  if (d.dopen) { const k = "d:" + d.dopen; S.open.has(k) ? S.open.delete(k) : S.open.add(k); render(); return; }
  if (d.mark) { S.marks.has(d.mark) ? S.marks.delete(d.mark) : S.marks.add(d.mark); resetDetailAct(); render(); return; }
  if (d.allmarks) { const g = S.detail.groups.find(g => g.lvl === "maybe"); const all = g.items.every(f => S.marks.has(f.id)); g.items.forEach(f => all ? S.marks.delete(f.id) : S.marks.add(f.id)); resetDetailAct(); render(); return; }
  if (d.keep) { S.marks.delete(d.keep); call("set_keep", d.keep, true).then(reloadDetail); return; }
  if (d.reveal) { call("reveal", d.reveal); return; }
  if (d.act === "ask") askPlan();
  else if (d.act === "yes") confirmPlan();
  else if (d.act === "no") { S.act = { where: null, phase: "idle", plan: null }; render(); }
  else if (d.act === "ok") { S.act = { where: null, phase: "idle", plan: null }; call("clear_job"); render(); }
  else if (d.act === "openbin") call("open_recycle_bin");
  else if (d.act === "storage") call("open_storage_settings");
});
function resetDetailAct() { if (S.act.where === "detail" && S.act.phase === "ask") S.act = { where: null, phase: "idle", plan: null }; }
$("all").addEventListener("click", () => togglePick(S.st.cleanables.map(c => c.key)));
$("back").addEventListener("click", closeDetail);
$("mRescan").addEventListener("click", () => { S.act = { where: null, phase: "idle", plan: null }; if (S.focus) closeDetail(); call("scan").then(() => poll(true)); });
$("mHistory").addEventListener("click", openHistory);
$("bMin").addEventListener("click", () => call("win_minimize"));
$("bMax").addEventListener("click", async () => {
  const r = await call("win_toggle_max");
  $("maxIcon").innerHTML = r && r.maxed ? '<rect x=".5" y="2.5" width="7" height="7"/><path d="M2.5 2.5V.5h7v7h-2"/>' : '<rect x=".5" y=".5" width="9" height="9"/>';
});
$("bClose").addEventListener("click", () => call("win_close"));
document.addEventListener("keydown", e => {
  if (e.key !== "Escape") return;
  if (S.act.phase === "ask") { S.act = { where: null, phase: "idle", plan: null }; render(); }
  else if (S.focus) closeDetail();
});

// ---------------------------------------------------------------- 循环
let pollTimer = null;
async function poll(now) {
  clearTimeout(pollTimer);
  try {
    const st = await call("state");
    if (st && st.version !== S.version) { S.version = st.version; applyState(st); }
  } catch (e) { /* 后端暂时没响应，下次再试 */ }
  const busy = S.st && (S.st.scanning || (S.st.job && S.st.job.running));
  pollTimer = setTimeout(poll, busy ? 250 : 1500);
}
let last = performance.now();
function loop(now) {
  const dt = Math.min(.05, (now - last) / 1000); last = now;
  const k = Math.min(1, dt * 1.8);
  for (const key in S.target) {
    const d = S.target[key] - (S.cur[key] || 0);
    S.cur[key] = Math.abs(d) < .001 ? S.target[key] : (S.cur[key] || 0) + d * k;
    if (S.target[key] === 0 && S.cur[key] < .001) { delete S.cur[key]; delete S.target[key]; }
  }
  const df = S.freeT - S.free;
  S.free = Math.abs(df) < .001 ? S.freeT : S.free + df * k;
  if (S.st) $("num").textContent = fmtG(S.free);
  frame(now);
  requestAnimationFrame(loop);
}

async function boot() {
  // 在 pywebview 里，api 准备好会发 pywebviewready；在浏览器里（devserver）直接用 HTTP
  await new Promise(res => {
    if (window.pywebview && window.pywebview.api) { viaWebview = true; return res(); }
    window.addEventListener("pywebviewready", () => { viaWebview = true; res(); }, { once: true });
    setTimeout(res, 400);
  });
  $("legend").innerHTML = TIERS.map(t => `<span><i style="background:${rgb(t.c)}"></i>${t.label}</span>`).join("");
  resize();
  new ResizeObserver(() => { resize(); frame(performance.now()); }).observe(app);
  await call("scan");
  poll(true);
  if (reduce) frame(performance.now()); else requestAnimationFrame(loop);
  document.fonts && document.fonts.ready.then(() => frame(performance.now()));
}
boot();
