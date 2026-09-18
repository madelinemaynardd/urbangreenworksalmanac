/* ════════════════════════════════════════════════════════════════
   chart-mini.js — offline fallback for Chart.js
   ----------------------------------------------------------------
   Loaded ONLY when the Chart.js CDN is unreachable (e.g. the farm has
   no internet). Implements the small subset of the Chart.js v4 API the
   AgriGrant dashboard actually uses: line, bar (vertical + horizontal),
   and doughnut/pie (incl. the gauge with circumference/rotation and an
   afterDraw plugin). Not a full reimplementation — just enough to keep
   every widget legible offline. When online, the real Chart.js loads
   instead and this file is never used.
   ════════════════════════════════════════════════════════════════ */
(function () {
  if (window.Chart) return; // real library already present

  const DPR = window.devicePixelRatio || 1;
  const FONT = "Segoe UI, system-ui, sans-serif";

  function resolve(v, fallback) { return v === undefined || v === null ? fallback : v; }

  // Lay out a canvas for crisp rendering at its CSS size.
  function prep(canvas) {
    const parent = canvas.parentElement;
    const cssW = (parent ? parent.clientWidth : canvas.clientWidth) || 320;
    // Height: honor an explicit CSS height, else derive a pleasant ratio.
    let cssH = canvas.clientHeight;
    if (!cssH || cssH < 40) cssH = Math.max(160, Math.round(cssW * 0.52));
    canvas.style.width = cssW + "px";
    canvas.style.height = cssH + "px";
    canvas.width = Math.round(cssW * DPR);
    canvas.height = Math.round(cssH * DPR);
    const ctx = canvas.getContext("2d");
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    ctx.clearRect(0, 0, cssW, cssH);
    return { ctx, w: cssW, h: cssH };
  }

  function niceMax(v) {
    if (v <= 0) return 1;
    const mag = Math.pow(10, Math.floor(Math.log10(v)));
    const n = v / mag;
    const step = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10;
    return step * mag;
  }

  function legendItems(data, type) {
    if (type === "doughnut" || type === "pie") {
      const ds = data.datasets[0] || { data: [], backgroundColor: [] };
      // Gauge (no labels) → no legend entries.
      if (!data.labels) return [];
      return data.labels.map((l, i) => ({
        text: l, color: (ds.backgroundColor || [])[i] || "#888",
      }));
    }
    return data.datasets.map((ds, i) => ({
      text: ds.label || ("Series " + (i + 1)),
      color: ds.borderColor || ds.backgroundColor || "#888",
    }));
  }

  function drawLegend(ctx, items, area, position) {
    if (!items.length) return area;
    ctx.font = "11px " + FONT;
    ctx.textBaseline = "middle";
    const box = 9, gap = 6, padX = 12;
    if (position === "right") {
      const colW = 100;
      let y = area.top + 4;
      items.forEach(it => {
        ctx.fillStyle = it.color;
        ctx.fillRect(area.right - colW, y, box, box);
        ctx.fillStyle = "#3a463d";
        ctx.textAlign = "left";
        ctx.fillText(it.text, area.right - colW + box + 5, y + box / 2, colW - box - 8);
        y += 18;
      });
      return { ...area, right: area.right - colW - 8 };
    }
    // top (default): center a wrapped row
    let totalW = 0;
    const measured = items.map(it => {
      const w = box + 4 + ctx.measureText(it.text).width + padX;
      totalW += w; return w;
    });
    let x = area.left + Math.max(0, (area.right - area.left - totalW) / 2);
    const y = area.top + 8;
    items.forEach((it, i) => {
      ctx.fillStyle = it.color;
      ctx.fillRect(x, y - box / 2, box, box);
      ctx.fillStyle = "#3a463d";
      ctx.textAlign = "left";
      ctx.fillText(it.text, x + box + 4, y);
      x += measured[i];
    });
    return { ...area, top: area.top + 22 };
  }

  function applyTickCallback(scale, val) {
    const cb = scale && scale.ticks && scale.ticks.callback;
    if (typeof cb === "function") { try { return cb(val); } catch (e) {} }
    return String(val);
  }

  // ── Chart class ───────────────────────────────────────────────
  function MiniChart(canvas, config) {
    this.canvas = canvas.canvas ? canvas.canvas : canvas; // accept ctx or el
    this.config = config || {};
    this.type = config.type || "line";
    this.data = config.data || { labels: [], datasets: [] };
    this.options = config.options || {};
    this.plugins = config.plugins || [];
    this.chartArea = { left: 0, top: 0, right: 0, bottom: 0 };
    this._raf = null;
    this.draw();
    // Redraw on container resize so responsive widgets stay crisp.
    if (typeof ResizeObserver !== "undefined" && this.canvas.parentElement) {
      this._ro = new ResizeObserver(() => {
        cancelAnimationFrame(this._raf);
        this._raf = requestAnimationFrame(() => this.draw());
      });
      this._ro.observe(this.canvas.parentElement);
    }
  }

  MiniChart.prototype.destroy = function () {
    if (this._ro) this._ro.disconnect();
    cancelAnimationFrame(this._raf);
    const ctx = this.canvas.getContext("2d");
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
  };

  MiniChart.prototype.draw = function () {
    const { ctx, w, h } = prep(this.canvas);
    this.ctx = ctx;
    let area = { left: 8, top: 8, right: w - 8, bottom: h - 8 };

    const legend = (this.options.plugins && this.options.plugins.legend) || {};
    const legendOn = legend.display !== false && this.type !== undefined;
    if (legendOn) {
      const items = legendItems(this.data, this.type);
      if (this.type === "doughnut" || this.type === "pie") {
        if (items.length) area = drawLegend(ctx, items, area, legend.position || "right");
      } else {
        area = drawLegend(ctx, items, area, legend.position || "top");
      }
    }

    if (this.type === "doughnut" || this.type === "pie") this._drawArc(ctx, area);
    else if (this.type === "bar") this._drawBar(ctx, area);
    else this._drawLine(ctx, area);

    this.chartArea = area;
    // afterDraw plugins (used by the gauge to paint its center label).
    this.plugins.forEach(p => { if (typeof p.afterDraw === "function") p.afterDraw(this); });
  };

  // ── Cartesian helpers ─────────────────────────────────────────
  MiniChart.prototype._axisFrame = function (ctx, area, opts) {
    // Reserve gutters for tick labels.
    const padL = opts.horizontal ? 78 : 44;
    const padB = 26;
    const plot = { left: area.left + padL, top: area.top + 4,
                   right: area.right - 10, bottom: area.bottom - padB };
    return plot;
  };

  MiniChart.prototype._drawLine = function (ctx, area) {
    const ds = this.data.datasets;
    const labels = this.data.labels || [];
    const plot = this._axisFrame(ctx, area, {});
    let max = 0, min = 0;
    ds.forEach(d => d.data.forEach(v => { if (v > max) max = v; if (v < min) min = v; }));
    max = niceMax(max || 1);
    const yScale = (this.options.scales && this.options.scales.y) || {};
    this._grid(ctx, plot, max, min, yScale, false);

    const n = labels.length;
    const xAt = i => plot.left + (n <= 1 ? 0 : (plot.right - plot.left) * i / (n - 1));
    const yAt = v => plot.bottom - (plot.bottom - plot.top) * (v - min) / (max - min || 1);

    // x labels
    ctx.fillStyle = "#6b7e72"; ctx.font = "10px " + FONT; ctx.textAlign = "center"; ctx.textBaseline = "top";
    const stepL = Math.ceil(n / 8);
    labels.forEach((l, i) => { if (i % stepL === 0) ctx.fillText(l, xAt(i), plot.bottom + 6); });

    ds.forEach(d => {
      const stroke = d.borderColor || "#2e7d46";
      // fill area
      if (d.fill) {
        ctx.beginPath();
        d.data.forEach((v, i) => { const x = xAt(i), y = yAt(v); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
        ctx.lineTo(xAt(d.data.length - 1), plot.bottom);
        ctx.lineTo(xAt(0), plot.bottom);
        ctx.closePath();
        ctx.fillStyle = hexA(stroke, 0.10);
        ctx.fill();
      }
      // line
      ctx.beginPath();
      ctx.lineWidth = 2; ctx.strokeStyle = stroke; ctx.lineJoin = "round";
      d.data.forEach((v, i) => { const x = xAt(i), y = yAt(v); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
      ctx.stroke();
      // points
      ctx.fillStyle = stroke;
      d.data.forEach((v, i) => { ctx.beginPath(); ctx.arc(xAt(i), yAt(v), 2.2, 0, 7); ctx.fill(); });
    });
  };

  MiniChart.prototype._drawBar = function (ctx, area) {
    const horizontal = (this.options.indexAxis === "y");
    const ds = this.data.datasets;
    const labels = this.data.labels || [];
    const plot = this._axisFrame(ctx, area, { horizontal });
    let max = 0, min = 0;
    ds.forEach(d => d.data.forEach(v => { if (v > max) max = v; if (v < min) min = v; }));
    max = niceMax(max || 1);
    if (min < 0) min = -niceMax(-min);

    const groups = labels.length, series = ds.length;

    if (!horizontal) {
      const valScale = (this.options.scales && this.options.scales.y) || {};
      this._grid(ctx, plot, max, min, valScale, false);
      const yAt = v => plot.bottom - (plot.bottom - plot.top) * (v - min) / (max - min || 1);
      const gW = (plot.right - plot.left) / groups;
      const bW = Math.min(40, gW * 0.7 / series);
      labels.forEach((l, gi) => {
        const gx = plot.left + gW * gi + gW / 2;
        ds.forEach((d, si) => {
          const v = d.data[gi] || 0;
          const x = gx - (series * bW) / 2 + si * bW;
          const y0 = yAt(0), y1 = yAt(v);
          ctx.fillStyle = colorAt(d.backgroundColor, gi, "#2e7d46");
          rrect(ctx, x, Math.min(y0, y1), bW - 2, Math.abs(y1 - y0), 3);
          ctx.fill();
        });
        ctx.fillStyle = "#6b7e72"; ctx.font = "10px " + FONT; ctx.textAlign = "center"; ctx.textBaseline = "top";
        ctx.fillText(trunc(l, 10), gx, plot.bottom + 6);
      });
    } else {
      const valScale = (this.options.scales && this.options.scales.x) || {};
      const xAt = v => plot.left + (plot.right - plot.left) * (v - min) / (max - min || 1);
      // vertical gridlines + value ticks
      ctx.strokeStyle = "#e8efe9"; ctx.fillStyle = "#9aa8a0"; ctx.font = "10px " + FONT;
      for (let t = 0; t <= 4; t++) {
        const v = min + (max - min) * t / 4, x = xAt(v);
        ctx.beginPath(); ctx.moveTo(x, plot.top); ctx.lineTo(x, plot.bottom); ctx.stroke();
        ctx.textAlign = "center"; ctx.textBaseline = "top";
        ctx.fillText(applyTickCallback(valScale, Math.round(v)), x, plot.bottom + 5);
      }
      const gH = (plot.bottom - plot.top) / groups;
      const bH = Math.min(26, gH * 0.7 / series);
      labels.forEach((l, gi) => {
        const gy = plot.top + gH * gi + gH / 2;
        ds.forEach((d, si) => {
          const v = d.data[gi] || 0;
          const y = gy - (series * bH) / 2 + si * bH;
          const x0 = xAt(0), x1 = xAt(v);
          ctx.fillStyle = colorAt(d.backgroundColor, gi, "#2e7d46");
          rrect(ctx, Math.min(x0, x1), y, Math.abs(x1 - x0), bH - 2, 3);
          ctx.fill();
        });
        ctx.fillStyle = "#3a463d"; ctx.font = "10px " + FONT; ctx.textAlign = "right"; ctx.textBaseline = "middle";
        ctx.fillText(trunc(l, 12), plot.left - 6, gy);
      });
    }
  };

  MiniChart.prototype._grid = function (ctx, plot, max, min, scale, horizontal) {
    ctx.strokeStyle = "#e8efe9"; ctx.lineWidth = 1;
    ctx.fillStyle = "#9aa8a0"; ctx.font = "10px " + FONT; ctx.textAlign = "right"; ctx.textBaseline = "middle";
    for (let t = 0; t <= 4; t++) {
      const v = min + (max - min) * t / 4;
      const y = plot.bottom - (plot.bottom - plot.top) * t / 4;
      ctx.beginPath(); ctx.moveTo(plot.left, y); ctx.lineTo(plot.right, y); ctx.stroke();
      ctx.fillText(applyTickCallback(scale, round1(v)), plot.left - 6, y);
    }
  };

  MiniChart.prototype._drawArc = function (ctx, area) {
    const ds = this.data.datasets[0] || { data: [] };
    const cx = (area.left + area.right) / 2;
    const cy = (area.top + area.bottom) / 2;
    const r = Math.min(area.right - area.left, area.bottom - area.top) / 2 - 6;
    const cutPct = parseFloat(String(this.options.cutout || "0")) || 0;
    const inner = (cutPct / 100) * r;
    const total = ds.data.reduce((a, b) => a + b, 0) || 1;

    const circ = resolve(ds.circumference, 360) * Math.PI / 180;
    const rot = (resolve(ds.rotation, 0) - 90) * Math.PI / 180;
    let start = rot;
    ds.data.forEach((v, i) => {
      const ang = circ * (v / total);
      ctx.beginPath();
      ctx.arc(cx, cy, r, start, start + ang);
      ctx.arc(cx, cy, inner, start + ang, start, true);
      ctx.closePath();
      ctx.fillStyle = colorAt(ds.backgroundColor, i, "#2e7d46");
      ctx.fill();
      if (ds.borderWidth) { ctx.lineWidth = ds.borderWidth; ctx.strokeStyle = "#fff"; ctx.stroke(); }
      start += ang;
    });
  };

  // ── small utils ───────────────────────────────────────────────
  function colorAt(c, i, fb) { return Array.isArray(c) ? (c[i] || fb) : (c || fb); }
  function round1(v) { return Math.round(v * 10) / 10; }
  function trunc(s, n) { s = String(s); return s.length > n ? s.slice(0, n - 1) + "…" : s; }
  function rrect(ctx, x, y, w, h, r) {
    r = Math.min(r, w / 2, h / 2); if (w < 0) { x += w; w = -w; } if (h < 0) { y += h; h = -h; }
    ctx.beginPath();
    ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r); ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
  }
  function hexA(hex, a) {
    const m = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex || "");
    if (!m) return "rgba(46,125,70," + a + ")";
    return `rgba(${parseInt(m[1],16)},${parseInt(m[2],16)},${parseInt(m[3],16)},${a})`;
  }

  window.Chart = MiniChart;
  console.info("[AgriGrant] Offline chart renderer active (Chart.js CDN unreachable).");
})();
