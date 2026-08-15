#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GPU 监测小工具 —— 单文件、零第三方依赖（仅 Python 标准库）
==============================================================
功能：
  1. 实时绘制 GPU 利用率 / 显存 / 温度 / 功耗 曲线（保留最近 15 分钟）
  2. 显示当前正在 GPU 上运行的进程（任务）数量与列表
  3. 多卡支持：多块 GPU 时自动出现"多卡总览"与 GPU 切换标签；
     单卡时界面与之前完全一致（多卡功能不显式出现）

数据来源：nvidia-smi（驱动自带，无需安装任何东西）

用法：
  python gpu_monitor.py            # 启动并自动打开浏览器
  python gpu_monitor.py --no-browser   # 不自动打开浏览器
访问 http://127.0.0.1:8770
"""
import json
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8770
SAMPLE_SEC = 1.0        # 采样间隔（秒）
MAX_POINTS = 900        # 曲线保留点数（约 15 分钟）

GPU_QUERY = "index,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw"


class Sampler:
    """后台线程：每秒采样一次 nvidia-smi"""

    def __init__(self):
        self._lock = threading.Lock()
        self.history = []          # [{t, gpus:[{util,memUsed,memTotal,temp,power},...]}]
        self.processes = []        # 当前 GPU 计算进程
        self.gpu_names = []        # 每块卡的名称
        self.gpu_count = 1
        self._uuid2index = None    # uuid -> GPU index 映射（懒加载）
        self.error = None

    def _smi(self, args, timeout=6):
        p = subprocess.run(["nvidia-smi", *args],
                           capture_output=True, text=True, timeout=timeout)
        if p.returncode != 0:
            raise RuntimeError((p.stderr or p.stdout or "nvidia-smi 执行失败").strip()[:200])
        return p.stdout

    def _uuid_map(self):
        """构建 GPU uuid -> index 映射（仅构建一次）"""
        if self._uuid2index is None:
            m = {}
            try:
                out = self._smi(["--query-gpu=index,uuid", "--format=csv,noheader,nounits"])
                for line in out.strip().splitlines():
                    parts = [x.strip() for x in line.split(",")]
                    if len(parts) == 2 and parts[1] not in ("", "[N/A]"):
                        m[parts[1]] = int(parts[0])
            except Exception:
                pass
            self._uuid2index = m
        return self._uuid2index

    def sample(self, now):
        gpus = []
        err = None
        try:
            out = self._smi(["--query-gpu=" + GPU_QUERY, "--format=csv,noheader,nounits"])
            for line in out.strip().splitlines():
                parts = [x.strip() for x in line.split(",")]
                if len(parts) >= 6:
                    gpus.append({"util": float(parts[1]), "memUsed": float(parts[2]),
                                 "memTotal": float(parts[3]), "temp": float(parts[4]),
                                 "power": float(parts[5])})
        except Exception as e:
            err = str(e)

        # 进程列表（含 GPU 归属）
        procs = []
        have_uuid = True
        try:
            out = self._smi(["--query-compute-apps=pid,process_name,used_memory,gpu_uuid",
                             "--format=csv,noheader"])
        except Exception:
            have_uuid = False
            try:
                out = self._smi(["--query-compute-apps=pid,process_name,used_memory",
                                 "--format=csv,noheader"])
            except Exception:
                out = ""
        umap = self._uuid_map() if have_uuid else {}
        for line in out.strip().splitlines():
            parts = [x.strip() for x in line.split(",")]
            if len(parts) >= 3:
                p = {"pid": parts[0], "name": parts[1] or "(未知)",
                     "memMiB": float(parts[2]), "gpuIndex": None}
                if have_uuid and len(parts) == 4:
                    p["gpuIndex"] = umap.get(parts[3])
                procs.append(p)

        if not self.gpu_names:
            try:
                out = self._smi(["--query-gpu=index,name", "--format=csv,noheader,nounits"])
                names = {}
                for line in out.strip().splitlines():
                    parts = [x.strip() for x in line.split(",")]
                    if len(parts) == 2:
                        names[int(parts[0])] = parts[1]
                self.gpu_names = [names[i] for i in sorted(names)]
                self.gpu_count = len(self.gpu_names) or 1
            except Exception:
                self.gpu_names = ["NVIDIA GPU"]
                self.gpu_count = 1

        with self._lock:
            if gpus:
                self.history.append({"t": now, "gpus": gpus})
                if len(self.history) > MAX_POINTS:
                    del self.history[: len(self.history) - MAX_POINTS]
            self.processes = procs
            self.error = err

    def state(self):
        with self._lock:
            return {"gpuNames": list(self.gpu_names), "gpuCount": self.gpu_count,
                    "history": list(self.history), "processes": list(self.processes),
                    "error": self.error}


sampler = Sampler()


def sampler_loop():
    while True:
        t0 = time.time()
        sampler.sample(t0)
        time.sleep(max(0.0, SAMPLE_SEC - (time.time() - t0)))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/state":
            self._send(200, "application/json; charset=utf-8",
                       json.dumps(sampler.state()).encode("utf-8"))
        elif self.path in ("/", "/index.html"):
            self._send(200, "text/html; charset=utf-8",
                       PAGE.replace("__PORT__", str(PORT)).encode("utf-8"))
        else:
            self._send(404, "text/plain; charset=utf-8", b"not found")


PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>GPU 监测</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; background: #0d1117; color: #c9d1d9;
         font: 14px/1.5 "Segoe UI", "Microsoft YaHei", sans-serif; }
  .wrap { max-width: 1000px; margin: 0 auto; padding: 16px; }
  h1 { font-size: 18px; margin: 0 0 12px; display: flex; align-items: center; gap: 10px; }
  .dot { width: 9px; height: 9px; border-radius: 50%; background: #3fb950; display: inline-block; }
  .dot.err { background: #f85149; }
  .gpu { color: #8b949e; font-size: 13px; font-weight: normal; }
  .sec { font-size: 14px; font-weight: 600; color: #e6edf3; margin: 14px 0 8px; }
  .cards { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 12px; }
  .card { background: #161b22; border: 1px solid #21262d; border-radius: 8px; padding: 10px 12px; }
  .card .k { color: #8b949e; font-size: 12px; }
  .card .v { font-size: 22px; font-weight: 600; margin-top: 2px; }
  .card .v small { font-size: 12px; color: #8b949e; font-weight: normal; }
  .ocard { background: #161b22; border: 1px solid #21262d; border-radius: 8px; padding: 10px 12px; }
  .ocard .otitle { display: flex; align-items: center; gap: 8px; font-weight: 600; margin-bottom: 4px; }
  .ocard .badge { margin-left: auto; background: #1f6feb22; color: #58a6ff; border: 1px solid #1f6feb44;
                  border-radius: 10px; font-size: 12px; padding: 1px 8px; font-weight: normal; }
  .ocard .ospark { display: block; width: 100%; height: 40px; }
  .ocard .onums { color: #8b949e; font-size: 12px; margin-top: 4px; }
  .overview { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 10px; }
  .tabs { display: flex; gap: 6px; margin-bottom: 10px; }
  .tab { background: #161b22; color: #8b949e; border: 1px solid #21262d; border-radius: 6px;
         padding: 5px 14px; cursor: pointer; font-size: 13px; }
  .tab.on { background: #1f6feb; border-color: #1f6feb; color: #fff; }
  .charts { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 12px; }
  .chart { background: #161b22; border: 1px solid #21262d; border-radius: 8px; padding: 10px 12px; }
  .chart .head { display: flex; justify-content: space-between; color: #8b949e; font-size: 12px; margin-bottom: 4px; }
  .chart .head b { color: #e6edf3; font-size: 15px; }
  .chart svg { display: block; width: 100%; height: 150px; }
  .tasks { background: #161b22; border: 1px solid #21262d; border-radius: 8px; padding: 10px 12px; }
  .tasks .head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
  .tasks .count { font-size: 22px; font-weight: 600; color: #58a6ff; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { text-align: left; padding: 5px 8px; border-bottom: 1px solid #21262d; }
  th { color: #8b949e; font-weight: normal; }
  td.num { font-variant-numeric: tabular-nums; }
  .none { color: #8b949e; padding: 8px 0; }
  .err { color: #f85149; font-size: 12px; }
  .foot { color: #484f58; font-size: 12px; margin-top: 10px; text-align: center; }
  @media (max-width: 800px) { .cards { grid-template-columns: repeat(2, 1fr); } .charts { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<div class="wrap">
  <h1><span class="dot" id="dot"></span>GPU 监测 <span class="gpu" id="gpuName">…</span></h1>

  <!-- 单卡模式：顶部当前值卡片 -->
  <div class="cards" id="cards">
    <div class="card"><div class="k">利用率</div><div class="v" id="v-util">--<small> %</small></div></div>
    <div class="card"><div class="k">显存</div><div class="v" id="v-mem">--<small> GB</small></div></div>
    <div class="card"><div class="k">温度</div><div class="v" id="v-temp">--<small> °C</small></div></div>
    <div class="card"><div class="k">功耗</div><div class="v" id="v-power">--<small> W</small></div></div>
  </div>

  <!-- 多卡模式：总览（仅多卡时显示） -->
  <div id="overview" style="display:none">
    <div class="sec">多卡总览</div>
    <div class="overview" id="overviewGrid"></div>
  </div>

  <!-- 多卡模式：GPU 切换标签（仅多卡时显示） -->
  <div class="tabs" id="gpuTabs" style="display:none"></div>

  <div class="charts">
    <div class="chart"><div class="head"><span>利用率 %</span><b id="c-util-val">--</b></div><svg id="c-util"></svg></div>
    <div class="chart"><div class="head"><span>显存 GB</span><b id="c-mem-val">--</b></div><svg id="c-mem"></svg></div>
    <div class="chart"><div class="head"><span>温度 °C</span><b id="c-temp-val">--</b></div><svg id="c-temp"></svg></div>
    <div class="chart"><div class="head"><span>功耗 W</span><b id="c-power-val">--</b></div><svg id="c-power"></svg></div>
  </div>

  <div class="tasks">
    <div class="head">
      <span>GPU 上的计算任务</span>
      <span class="count" id="taskCount">0</span>
    </div>
    <div id="taskList"><div class="none">无运行中的 GPU 计算任务</div></div>
  </div>

  <div class="foot">每 1 秒刷新 · 曲线保留最近 15 分钟 · 数据来自 nvidia-smi</div>
</div>

<script>
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = v => (v >= 100 ? v.toFixed(0) : v.toFixed(1));
let hist = [], procs = [], meta = {}, sel = 0;

async function tick() {
  try {
    const s = await (await fetch('/api/state')).json();
    hist = s.history || []; procs = s.processes || []; meta = s;
    render();
  } catch (e) {
    document.getElementById('dot').className = 'dot err';
  }
  setTimeout(tick, 1000);
}

function drawChart(id, series, color, opts = {}) {
  const svg = document.getElementById(id);
  const withTime = !opts.spark && opts.times && opts.times.length > 1;
  const bottomPad = withTime ? 18 : 0;
  const H = opts.height || 150, P = opts.spark ? 2 : 8;
  const W = Math.max(opts.spark ? 120 : 300, svg.parentElement.clientWidth - (opts.spark ? 4 : 24));
  const plotH = H - 2 * P - bottomPad;
  const vals = series.filter(v => v !== null && v !== undefined);
  let min = vals.length ? Math.min(...vals) : 0;
  let max = vals.length ? Math.max(...vals) : 1;
  if (opts.min != null) min = Math.min(min, opts.min);
  if (opts.max != null) max = Math.max(max, opts.max);
  if (max === min) max = min + 1;
  const span = max - min;
  const x = i => P + (series.length > 1 ? i / (series.length - 1) : 0) * (W - 2 * P);
  const y = v => P + (1 - (v - min) / span) * plotH;
  let grid = '';
  if (!opts.spark) {
    [0, 0.5, 1].forEach(f => {
      const yy = P + (1 - f) * plotH, vv = min + f * span;
      grid += '<line x1="' + P + '" y1="' + yy + '" x2="' + (W - P) + '" y2="' + yy + '" stroke="#1f2733"/>';
      grid += '<text x="' + (P + 2) + '" y="' + (yy - 3) + '" fill="#5c6b80" font-size="10">' + fmt(vv) + '</text>';
    });
    if (withTime) {
      const pad2 = n => (n < 10 ? '0' : '') + n;
      const t0 = opts.times[0], t1 = opts.times[opts.times.length - 1];
      for (let k = 0; k < 5; k++) {
        const f = k / 4;
        const xx = P + f * (W - 2 * P);
        const d = new Date((t0 + f * (t1 - t0)) * 1000);
        const label = pad2(d.getHours()) + ':' + pad2(d.getMinutes()) + ':' + pad2(d.getSeconds());
        grid += '<line x1="' + xx + '" y1="' + (P + plotH) + '" x2="' + xx + '" y2="' + (P + plotH + 5) + '" stroke="#30363d"/>';
        grid += '<text x="' + (xx - 15) + '" y="' + (H - 5) + '" fill="#5c6b80" font-size="9">' + label + '</text>';
      }
    }
  }
  const pts = series.map((v, i) => v == null ? null : x(i).toFixed(1) + ',' + y(v).toFixed(1)).filter(Boolean).join(' ');
  const last = series[series.length - 1];
  svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
  svg.innerHTML = grid
    + '<polyline points="' + pts + '" fill="none" stroke="' + color + '" stroke-width="1.5"/>'
    + (last != null && !opts.spark
        ? '<circle cx="' + x(series.length - 1) + '" cy="' + y(last) + '" r="2.5" fill="' + color + '"/>' : '');
  if (!opts.spark) document.getElementById(id + '-val').textContent = last == null ? '--' : fmt(last);
}

const gpuOf = s => (s && s.gpus && s.gpus[sel]) || null;
const gpuSeries = field => hist.map(h => (h.gpus && h.gpus[sel]) ? h.gpus[sel][field] : null);

function render() {
  const multi = (meta.gpuCount || 1) > 1;
  document.getElementById('cards').style.display = multi ? 'none' : '';
  document.getElementById('overview').style.display = multi ? '' : 'none';
  document.getElementById('gpuTabs').style.display = multi ? '' : 'none';
  document.getElementById('gpuName').textContent =
    multi ? ('共 ' + meta.gpuCount + ' 块 GPU') : (meta.gpuNames[0] || 'NVIDIA GPU');

  if (multi) {
    if (sel >= (meta.gpuCount || 1)) sel = 0;
    renderOverview();
    renderTabs();
  }
  renderCharts();
  renderTasks();
}

function renderOverview() {
  const grid = document.getElementById('overviewGrid');
  const last = hist[hist.length - 1];
  const cards = meta.gpuNames.map((name, i) => {
    const g = last && last.gpus[i];
    const n = procs.filter(p => p.gpuIndex === i).length;
    const spark = hist.map(h => (h.gpus && h.gpus[i]) ? h.gpus[i].util : null);
    const svgId = 'spark-' + i;
    setTimeout(() => drawChart(svgId, spark, '#4fc3f7', { spark: true, min: 0, max: 100 }), 0);
    return '<div class="ocard">'
      + '<div class="otitle">GPU ' + i + ' <span class="gpu">' + esc(name) + '</span>'
      + '<span class="badge">' + n + ' 任务</span></div>'
      + '<svg class="ospark" id="' + svgId + '"></svg>'
      + '<div class="onums">占用 ' + (g ? fmt(g.util) + '%' : '--')
      + ' · 显存 ' + (g ? fmt(g.memUsed / 1024) + '/' + fmt(g.memTotal / 1024) + ' GB' : '--')
      + ' · ' + (g ? fmt(g.temp) + '°C' : '--')
      + ' · ' + (g ? fmt(g.power) + 'W' : '--') + '</div></div>';
  }).join('');
  grid.innerHTML = cards;
}

function renderTabs() {
  const bar = document.getElementById('gpuTabs');
  bar.innerHTML = meta.gpuNames.map((name, i) =>
    '<button class="tab' + (i === sel ? ' on' : '') + '" data-i="' + i + '">GPU ' + i
    + ' <span class="gpu">' + esc(name) + '</span></button>').join('');
  bar.querySelectorAll('.tab').forEach(b => b.onclick = () => { sel = +b.dataset.i; render(); });
}

function renderCharts() {
  const g = gpuOf(hist[hist.length - 1]);
  const set = (id, v, unit) => {
    document.getElementById(id).innerHTML = v == null ? '--<small> ' + unit + '</small>'
      : fmt(v) + '<small> ' + unit + '</small>';
  };
  set('v-util', g && g.util, '%');
  set('v-mem', g && g.memUsed / 1024, 'GB');
  set('v-temp', g && g.temp, '°C');
  set('v-power', g && g.power, 'W');
  const memTotal = g ? g.memTotal / 1024 : null;
  drawChart('c-util', gpuSeries('util'), '#4fc3f7', { min: 0, max: 100, times: hist.map(h => h.t) });
  drawChart('c-mem', gpuSeries('memUsed').map(v => v == null ? null : v / 1024), '#81c784', { min: 0, max: memTotal, times: hist.map(h => h.t) });
  drawChart('c-temp', gpuSeries('temp'), '#ffb74d', { min: 0, times: hist.map(h => h.t) });
  drawChart('c-power', gpuSeries('power'), '#f06292', { min: 0, times: hist.map(h => h.t) });
}

function renderTasks() {
  const multi = (meta.gpuCount || 1) > 1;
  document.getElementById('taskCount').textContent = procs.length;
  const box = document.getElementById('taskList');
  if (!procs.length) {
    box.innerHTML = '<div class="none">无运行中的 GPU 计算任务</div>';
  } else {
    const head = '<tr><th>#</th><th>PID</th><th>进程</th>'
      + (multi ? '<th>GPU</th>' : '') + '<th>显存</th></tr>';
    const rows = procs.map((p, i) => '<tr><td class="num">' + (i + 1) + '</td><td class="num">' + esc(p.pid)
      + '</td><td>' + esc(p.name) + '</td>'
      + (multi ? '<td class="num">' + (p.gpuIndex == null ? '—' : 'GPU ' + p.gpuIndex) + '</td>' : '')
      + '<td class="num">' + fmt(p.memMiB / 1024) + ' GB</td></tr>').join('');
    box.innerHTML = '<table>' + head + rows + '</table>';
  }
  const dot = document.getElementById('dot');
  dot.className = 'dot' + (meta.error ? ' err' : '');
  dot.title = meta.error ? meta.error : '数据正常';
}

tick();
</script>
</body>
</html>
"""


def main():
    no_browser = "--no-browser" in sys.argv
    threading.Thread(target=sampler_loop, daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = "http://127.0.0.1:%d" % PORT
    print("GPU 监测已启动: %s  (Ctrl+C 退出)" % url)
    if not no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出")


if __name__ == "__main__":
    main()
