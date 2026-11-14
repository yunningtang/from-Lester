/* 留白：纸和墨的几何与纹理（不依赖数据）。由 app.js 使用。
   需要全局：ctx（画布 2D 上下文）、PAPER（纸色）。 */
"use strict";
// ---------- 几何 ----------
const area = p => { let s = 0; for (let i = 0; i < p.length; i++) { const a = p[i], b = p[(i + 1) % p.length]; s += a[0] * b[1] - b[0] * a[1]; } return Math.abs(s) / 2; };
function clip(p, n, c) {
  const out = [];
  for (let i = 0; i < p.length; i++) {
    const a = p[i], b = p[(i + 1) % p.length], da = n[0] * a[0] + n[1] * a[1] - c, db = n[0] * b[0] + n[1] * b[1] - c;
    if (da <= 0) out.push(a);
    if ((da < 0 && db > 0) || (da > 0 && db < 0)) { const t = da / (da - db); out.push([a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])]); }
  }
  return out;
}
function split(p, frac, ang) {
  const n = [Math.cos(ang), Math.sin(ang)], d = p.map(q => n[0] * q[0] + n[1] * q[1]);
  let lo = Math.min(...d), hi = Math.max(...d); const A = area(p) * frac;
  for (let i = 0; i < 32; i++) { const m = (lo + hi) / 2; area(clip(p, n, m)) < A ? lo = m : hi = m; }
  const c = (lo + hi) / 2; return [clip(p, n, c), clip(p, [-n[0], -n[1]], -c)];
}
// 固定的切分树：形状随大小连续变化，不会跳
function rng(seed) { return () => (seed = (seed * 16807) % 2147483647) / 2147483647; }
// 固定的切分树：形状随大小连续变化，不会跳。sizeOf(key) 给出当前大小
function buildTree(items, r) {
  if (items.length === 1) return { leaf: items[0].k };
  const tot = items.reduce((s, i) => s + i.v, 0);
  let acc = 0, best = 1, bd = 1e9;
  for (let i = 1; i < items.length; i++) { acc += items[i - 1].v; const d = Math.abs(acc - tot / 2); if (d < bd) { bd = d; best = i; } }
  let a = items.slice(0, best), b = items.slice(best);
  if (r() < .5) [a, b] = [b, a];
  return { a: buildTree(a, r), b: buildTree(b, r), tilt: (r() - .5) * .7 };
}
function layoutTree(node, poly, out, sizeOf) {
  const sum = n => n.leaf ? sizeOf(n.leaf) : sum(n.a) + sum(n.b);
  (function rec(n, p) {
    if (n.leaf) { out[n.leaf] = p; return; }
    const sa = sum(n.a), sb = sum(n.b);
    const xs = p.map(q => q[0]), ys = p.map(q => q[1]);
    const base = (Math.max(...xs) - Math.min(...xs)) >= (Math.max(...ys) - Math.min(...ys)) ? 0 : Math.PI / 2;
    const [pa, pb] = split(p, sa / (sa + sb || 1), base + n.tilt);
    rec(n.a, pa); rec(n.b, pb);
  })(node, poly);
}

// 边缘起伏：对所有点用同一个位移场，相邻块的公共边位移一致，所以不会出现缝
let W = 0, H = 0, portrait = false;
function disp(x, y, t) {
  const fall = Math.min(1, x / 40, y / 40, (W - x) / 40, (H - y) / 40);
  if (fall <= 0) return [x, y];
  const A = 13 * fall;
  return [x + A * Math.sin(y * .013 + t * .22 + Math.sin(x * .009 + t * .1) * 1.6),
          y + A * Math.cos(x * .012 - t * .19 + Math.sin(y * .008 - t * .12) * 1.6)];
}
function wobble(poly, t) {
  const out = [];
  for (let i = 0; i < poly.length; i++) {
    const a = poly[i], b = poly[(i + 1) % poly.length], L = Math.hypot(b[0] - a[0], b[1] - a[1]), n = Math.max(1, Math.ceil(L / 7));
    for (let j = 0; j < n; j++) { const u = j / n; out.push(disp(a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u, t)); }
  }
  return out;
}
const trace = pts => { ctx.beginPath(); pts.forEach((p, i) => i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1])); ctx.closePath(); };
function inside(pts, x, y) {
  let c = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const [xi, yi] = pts[i], [xj, yj] = pts[j];
    if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) c = !c;
  }
  return c;
}

// 纸纹 / 墨的颗粒
// 值噪声：小画布随机灰度，放大后自然平滑
function noiseLayer(g, w, h, cell, alpha, mode) {
  const nw = Math.ceil(w / cell) + 2, nh = Math.ceil(h / cell) + 2, n = document.createElement("canvas");
  n.width = nw; n.height = nh;
  const nx = n.getContext("2d"), im = nx.createImageData(nw, nh);
  for (let i = 0; i < im.data.length; i += 4) { const v = Math.random() * 255; im.data[i] = im.data[i + 1] = im.data[i + 2] = v; im.data[i + 3] = 255; }
  nx.putImageData(im, 0, 0);
  g.save(); g.globalCompositeOperation = mode; g.globalAlpha = alpha; g.imageSmoothingEnabled = true; g.imageSmoothingQuality = "high";
  g.drawImage(n, -cell, -cell, nw * cell, nh * cell); g.restore();
}
function fineGrain(g, w, h, amp) {
  const im = g.getImageData(0, 0, w, h), d = im.data;
  for (let i = 0; i < d.length; i += 4) { const r = (Math.random() - .5) * amp; d[i] += r; d[i + 1] += r; d[i + 2] += r * .9; }
  g.putImageData(im, 0, 0);
}
// 宣纸：暖白底 + 大小两层云絮 + 纤维 + 细点
function buildPaper(w, h) {
  const c = document.createElement("canvas"); c.width = w; c.height = h; const g = c.getContext("2d");
  g.fillStyle = PAPER; g.fillRect(0, 0, w, h);
  noiseLayer(g, w, h, 160, .12, "soft-light");
  noiseLayer(g, w, h, 48, .05, "soft-light");
  noiseLayer(g, w, h, 14, .05, "soft-light");
  const fibers = Math.round(w * h / 700);
  for (let i = 0; i < fibers; i++) {
    const x = Math.random() * w, y = Math.random() * h, L = 8 + Math.random() * Math.random() * 70, a = Math.random() * 6.3;
    const light = Math.random() < .45;
    g.strokeStyle = light ? `rgba(255,253,247,${.25 + Math.random() * .35})` : `rgba(150,136,110,${.03 + Math.random() * .05})`;
    g.lineWidth = .3 + Math.random() * .7;
    g.beginPath(); g.moveTo(x, y);
    g.quadraticCurveTo(x + Math.cos(a + .6) * L * .5, y + Math.sin(a + .6) * L * .5, x + Math.cos(a) * L, y + Math.sin(a) * L);
    g.stroke();
  }
  for (let i = 0; i < w * h / 2600; i++) {
    g.fillStyle = `rgba(120,108,86,${.05 + Math.random() * .12})`;
    g.beginPath(); g.arc(Math.random() * w, Math.random() * h, .3 + Math.random() * .8, 0, 7); g.fill();
  }
  fineGrain(g, w, h, 7);
  return c;
}
// 墨的浓淡：灰度云絮，用 soft-light 叠在墨上，同一块墨里有深有浅；再加一点墨粒
function buildWash(w, h) {
  const c = document.createElement("canvas"); c.width = w; c.height = h; const g = c.getContext("2d");
  g.fillStyle = "rgb(128,128,128)"; g.fillRect(0, 0, w, h);
  noiseLayer(g, w, h, 260, .7, "source-over");
  noiseLayer(g, w, h, 120, .25, "soft-light");
  return c;
}
let paperTex = null, washTex = null;
let grainPat = null;
const off = document.createElement("canvas"), octx = off.getContext("2d");
const off2 = document.createElement("canvas"), o2ctx = off2.getContext("2d");

