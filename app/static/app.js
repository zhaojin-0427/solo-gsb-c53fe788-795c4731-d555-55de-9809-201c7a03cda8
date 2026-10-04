/* 雨水调蓄池推演前端（原生 JavaScript） */
"use strict";

const PALETTE = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
                 "#8c564b", "#e377c2", "#17becf", "#bcbd22", "#7f7f7f"];

/* ---------------- 动态输入表格 ---------------- */

const rows = { tank: [], interval: [], pipe: [], pump: [] };

function tankIdOptions(sel) {
  return rows.tank.map((r, i) =>
    `<option value="${i}" ${String(sel) === String(i) ? "selected" : ""}>${esc(r.id.value || `池${i + 1}`)}</option>`
  ).join("");
}
function esc(s) {
  return String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function refreshTankRefs() {
  document.querySelectorAll("#intervalBody select.tanksel").forEach(s => s.innerHTML = tankIdOptions(s.value));
  document.querySelectorAll("#pumpBody select.tanksel").forEach(s => s.innerHTML = tankIdOptions(s.value));
  document.querySelectorAll("#pipeBody select.fromsel").forEach(s => s.innerHTML = tankIdOptions(s.value));
  document.querySelectorAll("#pipeBody select.tosel").forEach(s => s.innerHTML = tankIdOptions(s.value));
}

function addTank(v = {}) {
  const tr = document.createElement("tr");
  tr.innerHTML = `
    <td><input class="id" value="${esc(v.id ?? `T${rows.tank.length + 1}`)}" style="width:70px"></td>
    <td><input type="number" step="any" class="bottom" value="${v.bottom ?? 0}"></td>
    <td><input type="number" step="any" class="area" value="${v.area ?? 100}"></td>
    <td><input type="number" step="any" class="capacity" value="${v.capacity ?? 500}"></td>
    <td><input type="number" step="any" class="initialVolume" value="${v.initialVolume ?? 0}"></td>
    <td><button class="danger">删除</button></td>`;
  tr.querySelector("button").onclick = () => { tr.remove(); pullRows(); refreshTankRefs(); };
  tr.querySelector(".id").oninput = refreshTankRefs;
  document.getElementById("tankBody").appendChild(tr);
  pullRows();
  refreshTankRefs();
}
function addInterval(v = {}) {
  const tr = document.createElement("tr");
  tr.innerHTML = `
    <td><select class="tanksel">${tankIdOptions(v.tank ?? 0)}</select></td>
    <td><input type="number" step="any" class="start" value="${v.start ?? 0}"></td>
    <td><input type="number" step="any" class="end" value="${v.end ?? 3600}"></td>
    <td><input type="number" step="any" class="flow" value="${v.flow ?? 0}"></td>
    <td><button class="danger">删除</button></td>`;
  tr.querySelector("button").onclick = () => tr.remove();
  document.getElementById("intervalBody").appendChild(tr);
}
function addPipe(v = {}) {
  const tr = document.createElement("tr");
  tr.innerHTML = `
    <td><input class="id" value="${esc(v.id ?? `P${rows.pipe.length + 1}`)}" style="width:70px"></td>
    <td><select class="fromsel">${tankIdOptions(v.from ?? 0)}</select></td>
    <td><select class="tosel">${tankIdOptions(v.to ?? 1)}</select></td>
    <td><input type="number" step="any" class="coeff" value="${v.coeff ?? 0.5}"></td>
    <td><button class="danger">删除</button></td>`;
  tr.querySelector("button").onclick = () => tr.remove();
  document.getElementById("pipeBody").appendChild(tr);
}
function addPump(v = {}) {
  const tr = document.createElement("tr");
  tr.innerHTML = `
    <td><input class="id" value="${esc(v.id ?? `PUMP${rows.pump.length + 1}`)}" style="width:80px"></td>
    <td><select class="tanksel">${tankIdOptions(v.tank ?? 0)}</select></td>
    <td><input type="number" step="any" class="flow" value="${v.flow ?? 0.2}"></td>
    <td><input type="number" step="any" class="onDepth" value="${v.onDepth ?? 3}"></td>
    <td><input type="number" step="any" class="offDepth" value="${v.offDepth ?? 1}"></td>
    <td><select class="initialOn">
      <option value="false" ${v.initialOn ? "" : "selected"}>关</option>
      <option value="true" ${v.initialOn ? "selected" : ""}>开</option>
    </select></td>
    <td><button class="danger">删除</button></td>`;
  tr.querySelector("button").onclick = () => tr.remove();
  document.getElementById("pumpBody").appendChild(tr);
}

function pullRows() {
  rows.tank = [...document.querySelectorAll("#tankBody tr")];
  rows.interval = [...document.querySelectorAll("#intervalBody tr")];
  rows.pipe = [...document.querySelectorAll("#pipeBody tr")];
  rows.pump = [...document.querySelectorAll("#pumpBody tr")];
}

function num(inp, label) {
  const v = parseFloat(inp.value);
  if (!Number.isFinite(v)) throw new Error(`${label} 必须为有限数值`);
  return v;
}

function collect() {
  pullRows();
  const duration = num(document.getElementById("duration"), "推演时长");
  if (duration <= 0) throw new Error("推演时长必须为正数");
  if (!rows.tank.length) throw new Error("至少需要一个调蓄池");

  const tanks = rows.tank.map((r, i) => ({
    id: r.querySelector(".id").value || `T${i + 1}`,
    bottom: num(r.querySelector(".bottom"), "池底高程"),
    area: num(r.querySelector(".area"), "截面积"),
    capacity: num(r.querySelector(".capacity"), "容量"),
    initialVolume: num(r.querySelector(".initialVolume"), "初始水量"),
  }));
  const idByRow = new Map(rows.tank.map((r, i) => [r, tanks[i].id]));

  const intervals = rows.interval.map(r => ({
    tank: idByRow.get(rows.tank[+r.querySelector("select.tanksel").value]),
    start: num(r.querySelector(".start"), "入流开始时刻"),
    end: num(r.querySelector(".end"), "入流结束时刻"),
    flow: num(r.querySelector(".flow"), "入流流量"),
  }));
  const pipes = rows.pipe.map(r => ({
    id: r.querySelector(".id").value,
    from: idByRow.get(rows.tank[+r.querySelector(".fromsel").value]),
    to: idByRow.get(rows.tank[+r.querySelector(".tosel").value]),
    coeff: num(r.querySelector(".coeff"), "管道系数"),
  }));
  const pumps = rows.pump.map(r => ({
    id: r.querySelector(".id").value,
    tank: idByRow.get(rows.tank[+r.querySelector("select.tanksel").value]),
    flow: num(r.querySelector(".flow"), "泵流量"),
    onDepth: num(r.querySelector(".onDepth"), "启泵水深"),
    offDepth: num(r.querySelector(".offDepth"), "停泵水深"),
    initialOn: r.querySelector(".initialOn").value === "true",
  }));
  return { duration, tanks, intervals, pipes, pumps };
}

/* ---------------- Canvas 绘图 ---------------- */

function setupCanvas(cv) {
  const dpr = window.devicePixelRatio || 1;
  const w = cv.clientWidth || cv.parentElement.clientWidth - 2;
  const h = parseInt(cv.getAttribute("height"), 10);
  cv.width = w * dpr; cv.height = h * dpr;
  const ctx = cv.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  return { ctx, w, h };
}

function fmtT(s) {
  if (s < 600 && s % 1 !== 0) return s.toFixed(0);
  const hh = Math.floor(s / 3600), mm = Math.floor((s % 3600) / 60), ss = Math.round(s % 60);
  return (hh > 0 ? `${hh}:` : "") + `${String(mm).padStart(2, "0")}:${String(ss).padStart(2, "0")}`;
}
function fmtV(v) {
  return Math.abs(v) >= 1000 ? v.toExponential(2) : (Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2));
}

function plotLines(cv, series, opts = {}) {
  const { ctx, w, h } = setupCanvas(cv);
  const ml = 62, mr = 16, mt = 14, mb = 34;
  const pw = w - ml - mr, ph = h - mt - mb;
  const xs = series[0].x;
  let xmin = Math.min(...xs), xmax = Math.max(...xs);
  let ymin = opts.yMin, ymax = opts.yMax;
  if (ymin === undefined || ymax === undefined) {
    let lo = Infinity, hi = -Infinity;
    series.forEach(s => s.y.forEach(v => { if (v < lo) lo = v; if (v > hi) hi = v; }));
    (opts.hlines || []).forEach(l => { if (isFinite(l.y)) { lo = Math.min(lo, l.y); hi = Math.max(hi, l.y); } });
    if (ymin === undefined) ymin = Math.min(0, lo);
    if (ymax === undefined) ymax = hi;
    if (ymax - ymin < 1e-12) ymax = ymin + 1;
    const pad = (ymax - ymin) * 0.05;
    ymin -= pad; ymax += pad;
  }
  const X = t => ml + (t - xmin) / (xmax - xmin || 1) * pw;
  const Y = v => mt + (1 - (v - ymin) / (ymax - ymin)) * ph;

  ctx.strokeStyle = "#e3e9ef"; ctx.fillStyle = "#8492a3";
  ctx.font = "11px sans-serif"; ctx.lineWidth = 1;
  for (let i = 0; i <= 5; i++) {
    const yv = ymin + (ymax - ymin) * i / 5, py = Y(yv);
    ctx.beginPath(); ctx.moveTo(ml, py); ctx.lineTo(w - mr, py); ctx.stroke();
    ctx.textAlign = "right"; ctx.fillText(fmtV(yv), ml - 6, py + 3);
  }
  for (let i = 0; i <= 6; i++) {
    const xv = xmin + (xmax - xmin) * i / 6, px = X(xv);
    ctx.beginPath(); ctx.strokeStyle = "#eef2f6";
    ctx.moveTo(px, mt); ctx.lineTo(px, mt + ph); ctx.stroke();
    ctx.fillStyle = "#8492a3"; ctx.textAlign = "center";
    ctx.fillText(fmtT(xv), px, mt + ph + 16);
  }
  ctx.strokeStyle = "#b9c5d1";
  ctx.beginPath(); ctx.moveTo(ml, mt); ctx.lineTo(ml, mt + ph); ctx.lineTo(w - mr, mt + ph); ctx.stroke();

  (opts.hlines || []).forEach(l => {
    ctx.save();
    ctx.setLineDash([6, 5]); ctx.strokeStyle = l.color; ctx.lineWidth = 1.2;
    ctx.beginPath(); ctx.moveTo(ml, Y(l.y)); ctx.lineTo(w - mr, Y(l.y)); ctx.stroke();
    ctx.restore();
  });
  (opts.vlines || []).forEach(v => {
    ctx.save();
    ctx.setLineDash(v.dash || [4, 4]); ctx.strokeStyle = v.color; ctx.lineWidth = 1.2;
    ctx.beginPath(); ctx.moveTo(X(v.x), mt); ctx.lineTo(X(v.x), mt + ph); ctx.stroke();
    ctx.restore();
  });

  series.forEach(s => {
    ctx.strokeStyle = s.color; ctx.lineWidth = s.width || 2;
    ctx.setLineDash(s.dash || []);
    ctx.beginPath();
    s.y.forEach((v, i) => { const px = X(s.x[i]), py = Y(v); i ? ctx.lineTo(px, py) : ctx.moveTo(px, py); });
    ctx.stroke();
  });
  ctx.setLineDash([]);
  if (opts.yLabel) {
    ctx.save(); ctx.translate(15, mt + ph / 2); ctx.rotate(-Math.PI / 2);
    ctx.fillStyle = "#5b6b7e"; ctx.textAlign = "center"; ctx.font = "12px sans-serif";
    ctx.fillText(opts.yLabel, 0, 0); ctx.restore();
  }
}

function legendHTML(items) {
  return items.map(i =>
    `<span><i style="background:${i.color}${i.dash ? ";height:0;border-top:2px dashed " + i.color : ""}"></i>${i.label}</span>`
  ).join("");
}

/* ---------------- 结果渲染 ---------------- */

let lastResult = null;

function renderLevel() {
  const r = lastResult;
  const mode = document.querySelector("input[name=levelMode]:checked").value;
  const ts = r.times;
  const series = r.tanks.map((t, i) => ({
    x: ts, y: mode === "depth" ? t.depth : t.head,
    color: PALETTE[i % PALETTE.length],
  }));
  const hlines = [];
  const vlines = r.switches.map((s, k) =>
    ({ x: s.time, color: k % 2 ? "#8c564b" : "#7f7f7f", dash: [5, 4] }));
  if (mode === "depth") {
    r.tanks.forEach((t, i) => {
      hlines.push({ y: t.capacity / t.area, color: PALETTE[i % PALETTE.length] + "88" });
    });
    r.pumps.forEach((p, u) => {
      const col = ["#c0392b", "#1e7d4f"][u % 2];
      hlines.push({ y: p.on_depth, color: col });
      hlines.push({ y: p.off_depth, color: col + "aa" });
    });
  }
  plotLines(document.getElementById("levelChart"), series, {
    yLabel: mode === "depth" ? "水深 (m)" : "水头高程 (m)",
    hlines, vlines,
  });
  const items = r.tanks.map((t, i) => ({ label: t.id, color: PALETTE[i % PALETTE.length] }));
  if (mode === "depth") {
    items.push({ label: "实线顶：满池水深", color: "#bbbbbb", dash: true });
    r.pumps.forEach((p, u) => items.push(
      { label: `${p.id} 启 ${p.on_depth}m / 停 ${p.off_depth}m`, color: ["#c0392b", "#1e7d4f"][u % 2], dash: true }));
  }
  items.push({ label: "竖虚线：泵切换时刻", color: "#7f7f7f", dash: true });
  document.getElementById("legend").innerHTML = legendHTML(items);
}

function renderPipes() {
  const r = lastResult;
  const cv = document.getElementById("pipeChart");
  if (!r.pipes.length) {
    const { ctx, w, h } = setupCanvas(cv);
    ctx.fillStyle = "#8492a3"; ctx.textAlign = "center";
    ctx.fillText("本方案未配置管道", w / 2, h / 2);
    document.getElementById("pipeLegend").innerHTML = "";
    return;
  }
  const series = r.pipes.map((p, i) => ({ x: r.times, y: p.cumulative, color: PALETTE[i % PALETTE.length] }));
  plotLines(cv, series, { yLabel: "累计过水量 (m³)" });
  document.getElementById("pipeLegend").innerHTML = legendHTML(
    r.pipes.map((p, i) => ({ label: `${p.id}（${p.from}→${p.to}）= ${fmtV(p.total)} m³`, color: PALETTE[i % PALETTE.length] })));
}

function renderFlows() {
  const r = lastResult;
  const cv = document.getElementById("flowChart");
  const series = [], items = [];
  let ci = 0;
  r.pumps.forEach((p, i) => {
    const c = ["#c0392b", "#d35400"][i % 2];
    series.push({ x: r.times, y: p.cumulative, color: c });
    items.push({ label: `泵 ${p.id} 排量 ${fmtV(p.total)} m³`, color: c });
    ci++;
  });
  r.tanks.forEach((t, i) => {
    if (t.overflow_total > 1e-9) {
      const c = "#7f0000";
      series.push({ x: r.times, y: t.overflow, color: c, dash: [7, 4], width: 2 });
      items.push({ label: `${t.id} 溢流 ${fmtV(t.overflow_total)} m³`, color: c, dash: true });
    }
  });
  if (series.length) {
    plotLines(cv, series, { yLabel: "累计 (m³)" });
  } else {
    const { ctx, w, h } = setupCanvas(cv);
    ctx.fillStyle = "#8492a3"; ctx.textAlign = "center";
    ctx.fillText("无泵排量与溢流", w / 2, h / 2);
  }
  document.getElementById("flowLegend").innerHTML = legendHTML(items);
}

function renderTables() {
  const r = lastResult;
  document.getElementById("switchBody").innerHTML = r.switches.length
    ? r.switches.map(s =>
        `<tr><td>${fmtT(s.time)} <span class="hint">(${s.time.toFixed(2)} s)</span></td><td>${esc(s.pump)}</td>` +
        `<td style="color:${s.action === "开启" ? "#1e7d4f" : "#c0392b"};font-weight:600">${s.action}</td></tr>`).join("")
    : `<tr><td colspan="3" class="hint">推演期间泵未发生切换</td></tr>`;

  document.getElementById("overflowBody").innerHTML = r.tanks.map(t =>
    `<tr><td>${esc(t.id)}</td><td style="color:${t.overflow_total > 1e-9 ? "#c0392b" : "#1e7d4f"}">${fmtV(t.overflow_total)} m³</td></tr>`
  ).join("") + `<tr style="font-weight:700"><td>合计</td><td>${fmtV(r.summary.total_overflow)} m³</td></tr>`;

  const s = r.summary;
  const closed = Math.abs(s.balance_residual) <
    1e-5 * Math.max(1, s.initial_storage + s.total_inflow) + 1e-6;
  document.getElementById("balance").innerHTML = `
    <div class="eq"><b>水量收支：</b>初存 + 入流 = 末存 + 泵排 + 溢流</div>
    <div>${fmtV(s.initial_storage)} + ${fmtV(s.total_inflow)} =
         ${fmtV(s.final_storage)} + ${fmtV(s.total_pumped)} + ${fmtV(s.total_overflow)}</div>
    <div>${fmtV(s.initial_storage + s.total_inflow)} =
         ${fmtV(s.final_storage + s.total_pumped + s.total_overflow)} m³</div>
    <div class="${closed ? "ok" : "bad"}">
      ${closed ? "✓ 收支闭合" : "✗ 收支残差偏大"}（残差 ${s.balance_residual.toExponential(2)} m³）</div>`;
}

function renderResults(r) {
  lastResult = r;
  document.getElementById("results").classList.remove("hidden");
  renderLevel(); renderPipes(); renderFlows(); renderTables();
}

function clearResults() {
  // 计算失败不得保留结果
  lastResult = null;
  document.getElementById("results").classList.add("hidden");
}

/* ---------------- 交互 ---------------- */

function setStatus(msg, kind) {
  const el = document.getElementById("status");
  el.textContent = msg || "";
  el.className = "status " + (kind || "");
}

document.querySelectorAll("[data-add]").forEach(btn => {
  btn.onclick = () => ({ tank: addTank, interval: addInterval, pipe: addPipe, pump: addPump })[btn.dataset.add]();
});
document.querySelectorAll('input[name="levelMode"]').forEach(r => r.onchange = () => lastResult && renderLevel());

document.getElementById("runBtn").onclick = async () => {
  setStatus("");
  let payload;
  try {
    payload = collect();
  } catch (e) {
    setStatus(e.message, "err");
    clearResults();
    return;
  }
  const btn = document.getElementById("runBtn");
  btn.disabled = true;
  setStatus("推演中…", "");
  try {
    const resp = await fetch("/api/simulate", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    if (!resp.ok) {
      clearResults();
      setStatus("推演被拒绝：" + (data.detail || "输入有误"), "err");
      return;
    }
    renderResults(data);
    setStatus("推演完成，水量收支残差 " + data.summary.balance_residual.toExponential(2) + " m³", "ok");
  } catch (e) {
    clearResults();
    setStatus("请求失败：" + e.message, "err");
  } finally {
    btn.disabled = false;
  }
};

document.getElementById("demoBtn").onclick = () => loadDemo();

function loadDemo() {
  document.getElementById("duration").value = 10800;
  ["tankBody", "intervalBody", "pipeBody", "pumpBody"].forEach(id => document.getElementById(id).innerHTML = "");
  rows.tank = rows.interval = rows.pipe = rows.pump = [];
  addTank({ id: "A池", bottom: 10, area: 100, capacity: 500, initialVolume: 0 });
  addTank({ id: "B池", bottom: 8, area: 80, capacity: 400, initialVolume: 40 });
  addInterval({ tank: 0, start: 0, end: 3600, flow: 0.30 });
  addInterval({ tank: 0, start: 3600, end: 7200, flow: 0.02 });
  addInterval({ tank: 0, start: 7200, end: 10800, flow: 0.0 });
  addPipe({ id: "P1", from: 0, to: 1, coeff: 0.35 });
  addPump({ tank: 1, flow: 0.15, onDepth: 3, offDepth: 1, initialOn: false });
  pullRows();
  refreshTankRefs();
  setStatus("已载入示例，点击“开始推演”", "");
}

window.addEventListener("resize", () => { if (lastResult) { renderLevel(); renderPipes(); renderFlows(); } });

loadDemo();
