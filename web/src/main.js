/**
 * MAIN FRONTEND ENTRY POINT
 * ------------------------
 * Initializes the MapLibre map, wires up the UI panel,
 * fetches spatial/statistical results from the backend API,
 * and updates map layers (tracts + IDW nitrate raster).
 *
 * Acts as the coordinator between UI (ui-panel.js),
 * backend endpoints (Flask API), and map rendering.
 */

import './style.css';
import maplibregl from 'maplibre-gl';
import { initUiPanel } from './ui-panel.js';

const API_BASE = import.meta.env.VITE_API_BASE;

const blankStyle = {
  version: 8,
  sources: {},
  layers: [
    {
      id: 'background',
      type: 'background',
      paint: {
        'background-color': '#0a0f18'
      }
    }
  ]
};

const map = new maplibregl.Map({
  container: 'map',
  style: blankStyle,
  center: [-89.7, 44.6],
  zoom: 5.6,
  attributionControl: false
});

// keeping this for console debug
window.map = map;

// Info button stuff
const infoBtn = document.getElementById('infoBtn');
const infoModal = document.getElementById('infoModal');
const infoClose = document.getElementById('infoClose');

function openInfo() {
  infoModal.removeAttribute('hidden');
  infoModal.classList.add('is-open');
  infoModal.setAttribute('aria-hidden', 'false');
}

function closeInfo() {
  infoModal.classList.remove('is-open');
  infoModal.setAttribute('aria-hidden', 'true');
  infoModal.setAttribute('hidden', '');
}

infoBtn?.addEventListener('click', (e) => {
  e.preventDefault();
  openInfo();
});

infoClose?.addEventListener('click', (e) => {
  e.preventDefault();
  closeInfo();
});

infoModal?.addEventListener('click', (e) => {
  if (e.target === infoModal) closeInfo();
});

// Esc closes!
window.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') closeInfo();
});

document.body.classList.add('ui-booted');
openInfo();

const DEFAULTS = { k: 2.0, cell: 500, knn: 32 };
let wasPanelCollapsedBeforeScatter = false;
let uiRef = null;
let latestTracts = null;
let latestRegression = null;
let currentLayerState = { showTracts: true, showNitrate: true };
function fmt(x, d = 4) { return Number.isFinite(x) ? x.toFixed(d) : ''; }
function setIdwOpacity(opacity) {
  if (!map.getLayer('idw-raster')) return;
  map.setPaintProperty('idw-raster', 'raster-opacity', opacity);
}
function enforceLayerOrder() {
  // bottom → top order
  const order = [
    'tracts-fill',
    'idw-raster',
    'tracts-residual',
    'tracts-outline',
    'wi-mask-fill',
    'wi-border-line'
  ];

  for (const id of order) {
    if (map.getLayer(id)) map.moveLayer(id);
  }
}
// Make the layers
async function setIdwOverlay(k) {
  const cell = DEFAULTS.cell;
  const knn = DEFAULTS.knn;
  // form the url and cache bust
  const metaRes = await fetch(`${API_BASE}/api/idw_meta?k=${k}&cell=${cell}&knn=${knn}`, { cache: 'no-store' });
  if (!metaRes.ok) throw new Error(`idw_meta failed: ${metaRes.status}`);
  const meta = await metaRes.json();

  const url = `${API_BASE}${meta.url}`;

  if (map.getLayer('idw-raster')) map.removeLayer('idw-raster');
  if (map.getSource('idw')) map.removeSource('idw');

  map.addSource('idw', {
    type: 'image',
    url,
    coordinates: meta.coordinates
  });

  map.addLayer({
    id: 'idw-raster',
    type: 'raster',
    source: 'idw',
    paint: { 'raster-opacity': 1 }
  });
  setIdwOpacity(1);

  setNitrateVisible(currentLayerState.showNitrate);
  enforceLayerOrder();


}

async function fetchRegression(k) {
  const cell = DEFAULTS.cell;
  const knn = DEFAULTS.knn;

  const r = await fetch(`${API_BASE}/api/regression?k=${k}&cell=${cell}&knn=${knn}`, { cache: 'no-store' });
  if (!r.ok) throw new Error(`regression failed: ${r.status}`);
  return await r.json();
}

function regressionHtml(j, k) {
  const cell = DEFAULTS.cell;
  const knn = DEFAULTS.knn;

  const tip = (text) =>
    `<span class="ui-tip" tabindex="0" role="img"
      aria-label="${text.replace(/"/g, '&quot;')}"
      data-tip="${text.replace(/"/g, '&quot;')}">?</span>`;

  return `
    <div class="reg-title">
      ${tip("Simple linear regression: tract canrate is modeled as a function of mean nitrate (one value per tract).")}
      <b>Regression</b>
      <div class="reg-sub">(tract canrate ~ mean nitrate)</div>
    </div>

    <div class="reg-line">
      ${tip(
    "Settings used to build the nitrate surface:\n\n" +
    "k = distance decay exponent (higher = more local influence)\n" +
    "cell = raster pixel size in meters\n" +
    "knn = number of nearest wells used per pixel"
  )}
      k=${k.toFixed(1)}&nbsp;&nbsp; cell=${cell}m&nbsp;&nbsp; knn=${knn}
    </div>

    <hr/>

    <div class="reg-line">
      ${tip("Estimated change in canrate per 1 unit increase in mean nitrate (sign tells direction; magnitude tells strength).")}
      <b>slope</b>: ${fmt(j.params?.slope ?? j.slope, 6)}
    </div>

    <div class="reg-line">
      ${tip("p value for the slope. Smaller means stronger evidence nitrate is associated with canrate in this model.")}
      <b>p</b>: ${Number.isFinite(j.p_value_slope) ? j.p_value_slope.toExponential(2) : ''}
    </div>

    <div class="reg-line">
      ${tip("Coefficient of determination: fraction of variation in canrate explained by mean nitrate (0-1).")}
      <b>R²</b>: ${fmt(j.r2, 4)}
    </div>
  `;
}

function setResidualVisible(visible) {
  setLayerVisibility('tracts-residual', visible);
}

function getNumeric(values) {
  return values.map(Number).filter(v => Number.isFinite(v)).sort((a, b) => a - b);
}

function quantile(sorted, q) {
  if (!sorted.length) return NaN;
  const pos = (sorted.length - 1) * q;
  const base = Math.floor(pos);
  const rest = pos - base;
  const a = sorted[base];
  const b = sorted[Math.min(base + 1, sorted.length - 1)];
  return a + (b - a) * rest;
}
function buildStepExpr(field, breaks, colors) {
  const expr = ['step', ['to-number', ['get', field]], colors[0]];
  for (let i = 0; i < breaks.length; i++) expr.push(breaks[i], colors[i + 1]);
  return expr;
}

function setLayerVisibility(layerId, visible) {
  if (!map.getLayer(layerId)) return;
  map.setLayoutProperty(layerId, 'visibility', visible ? 'visible' : 'none');
}

function setTractsVisible(visible) {
  setLayerVisibility('tracts-fill', visible);
  setLayerVisibility('tracts-outline', visible);
}

function setNitrateVisible(visible) {
  setLayerVisibility('idw-raster', visible);
}
// Loader stuff
const globalLoader = document.getElementById('globalLoader');

function showLoader() {
  globalLoader?.removeAttribute('hidden');
}

function hideLoader() {
  globalLoader?.setAttribute('hidden', '');
}
showLoader();

// -------- Scatter plot modal --------
let scatterModalEl = null;

function ensureScatterModal() {
  if (scatterModalEl) return scatterModalEl;

  const el = document.createElement('div');
  el.id = 'scatterModal';
  el.className = 'scatter-modal';
  el.setAttribute('aria-hidden', 'true');
  el.setAttribute('hidden', '');

  el.innerHTML = `
    <div class="scatter-panel" role="dialog" aria-modal="true" aria-labelledby="scatterTitle">
      <button id="scatterClose" class="info-close" type="button" aria-label="Close">×</button>
      <div id="scatterTitle" class="scatter-title">Scatter: mean nitrate vs canrate</div>

      <div class="scatter-canvas-wrap">
        <canvas id="scatterCanvas"></canvas>
      </div>

      <div style="margin-top:10px; font:12px/1.35 sans-serif; opacity:0.9;">
        Each point is a census tract. X = mean nitrate, Y = observed canrate.
      </div>
    </div>
  `;

  document.body.appendChild(el);

  const closeBtn = el.querySelector('#scatterClose');
  closeBtn?.addEventListener('click', () => closeScatter());

  // click outside closes
  el.addEventListener('click', (e) => {
    if (e.target === el) closeScatter();
  });

  // ESC closes
  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeScatter();
  });

  scatterModalEl = el;
  return el;
}

function openScatter() {
  const el = ensureScatterModal();

  // remember panel state
  const wrap = document.getElementById('ui-wrap');
  wasPanelCollapsedBeforeScatter =
    wrap?.classList.contains('is-collapsed');

  // collapse panel if not already collapsed
  if (uiRef && !wasPanelCollapsedBeforeScatter) {
    uiRef.slider.collapse();
  }

  el.removeAttribute('hidden');
  el.classList.add('is-open');
  el.setAttribute('aria-hidden', 'false');
  drawScatter();
}

function closeScatter() {
  if (!scatterModalEl) return;

  scatterModalEl.classList.remove('is-open');
  scatterModalEl.setAttribute('aria-hidden', 'true');
  scatterModalEl.setAttribute('hidden', '');

  // restore panel state
  if (uiRef && !wasPanelCollapsedBeforeScatter) {
    uiRef.slider.expand();
  }
}

function getInterceptAndSlope(reg) {
  const slope = reg?.params?.slope ?? reg?.slope;
  const intercept = reg?.params?.intercept ?? reg?.intercept;
  return { slope, intercept };
}

function drawScatter() {
  const el = ensureScatterModal();
  const canvas = el.querySelector('#scatterCanvas');
  if (!canvas) return;
  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width;
  canvas.height = rect.height;

  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  const pts = (latestTracts?.features ?? [])
    .map(f => ({
      x: Number(f.properties?.mean_nitrate),
      y: Number(f.properties?.canrate)
    }))
    .filter(p => Number.isFinite(p.x) && Number.isFinite(p.y));

  // nothing to draw
  if (!pts.length) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = 'rgba(255,255,255,0.45)';
    ctx.font = '14px sans-serif';
    ctx.fillText('No data available to plot.', 20, 30);
    return;
  }

  // ranges
  let xmin = Math.min(...pts.map(p => p.x));
  let xmax = Math.max(...pts.map(p => p.x));
  let ymin = Math.min(...pts.map(p => p.y));
  let ymax = Math.max(...pts.map(p => p.y));

  // pad ranges a bit
  const xpad = (xmax - xmin) * 0.05 || 1;
  const ypad = (ymax - ymin) * 0.05 || 1;
  xmin -= xpad; xmax += xpad;
  ymin -= ypad; ymax += ypad;

  const W = canvas.width, H = canvas.height;
  const m = { l: 52, r: 18, t: 18, b: 44 };
  const px = (x) => m.l + (x - xmin) * (W - m.l - m.r) / (xmax - xmin);
  const py = (y) => H - m.b - (y - ymin) * (H - m.t - m.b) / (ymax - ymin);

  // clear
  ctx.clearRect(0, 0, W, H);

  // axes
  ctx.strokeStyle = 'rgba(255,255,255,0.55)';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(m.l, m.t);
  ctx.lineTo(m.l, H - m.b);
  ctx.lineTo(W - m.r, H - m.b);
  ctx.stroke();

  // labels
  ctx.fillStyle = 'rgba(255,255,255,0.9)';
  ctx.font = '12px sans-serif';
  ctx.fillText('mean_nitrate', W / 2 - 35, H - 16);
  ctx.save();
  ctx.translate(14, H / 2 + 35);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText('canrate', 0, 0);
  ctx.restore();

  // points
  ctx.fillStyle = 'rgba(255,255,255,0.75)';
  for (const p of pts) {
    ctx.beginPath();
    ctx.arc(px(p.x), py(p.y), 2.2, 0, Math.PI * 2);
    ctx.fill();
  }

  // regression line (prefer backend params; fallback to simple least squares)
  let { slope, intercept } = getInterceptAndSlope(latestRegression);

  if (!Number.isFinite(slope) || !Number.isFinite(intercept)) {
    // compute quick OLS from points
    const n = pts.length;
    const mx = pts.reduce((s, p) => s + p.x, 0) / n;
    const my = pts.reduce((s, p) => s + p.y, 0) / n;
    let num = 0, den = 0;
    for (const p of pts) {
      num += (p.x - mx) * (p.y - my);
      den += (p.x - mx) * (p.x - mx);
    }
    slope = den ? num / den : 0;
    intercept = my - slope * mx;
  }

  const y1 = slope * xmin + intercept;
  const y2 = slope * xmax + intercept;

  ctx.strokeStyle = 'rgba(120,180,255,0.95)';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(px(xmin), py(y1));
  ctx.lineTo(px(xmax), py(y2));
  ctx.stroke();
}

map.addControl(new maplibregl.NavigationControl(), 'top-right');

map.on('load', async () => {
  const ui = initUiPanel({

    defaults: DEFAULTS,

    onToggleLayers: (state) => {
      currentLayerState = state;
      setTractsVisible(state.showTracts);
      setNitrateVisible(state.showNitrate);
      setResidualVisible(state.showResidual);
      enforceLayerOrder();
    },

    onRun: async (k) => {
      showLoader();

      try {
        const cell = DEFAULTS.cell;
        const knn = DEFAULTS.knn;

        const tractsRes = await fetch(`${API_BASE}/api/tracts?k=${k}&cell=${cell}&knn=${knn}`, { cache: 'no-store' });
        if (!tractsRes.ok) throw new Error(`tracts fetch failed: ${tractsRes.status}`);
        const tracts = await tractsRes.json();

        map.getSource('tracts').setData(tracts);

        await setIdwOverlay(k);

        const reg = await fetchRegression(k);
        latestRegression = reg;
        latestTracts = tracts;

        setTractsVisible(currentLayerState.showTracts);
        setNitrateVisible(currentLayerState.showNitrate);

        return regressionHtml(reg, k);

      } finally {
        hideLoader();
      }
    },
    onShowScatter: () => openScatter()
  });
  uiRef = ui;

  // initial run on load
  ui.slider.collapse();
  ui.setRunEnabled(false);
  ui.setStatus('computing…');
  const uiVis = document.getElementById('ui');
  uiVis.removeAttribute('hidden');
  const BASE = (import.meta.env.BASE_URL || '/').replace(/\/?$/, '/'); // ensure trailing /
  const pub = (p) => BASE + p.replace(/^\//, '');


  const WI_MASK_URL = pub('data/wi_mask/wi_mask.geojson');
  const WI_BORDER_URL = pub('data/wi_mask/wi_border.geojson');

  // sources/layers
  map.addSource('wi-mask', { type: 'geojson', data: WI_MASK_URL });
  map.addSource('wi-border', { type: 'geojson', data: WI_BORDER_URL });


  map.addLayer({
    id: 'wi-mask-fill',
    type: 'fill',
    source: 'wi-mask',
    paint: { 'fill-color': '#0a0f18', 'fill-opacity': 1 }
  });


  map.addLayer({
    id: 'wi-border-line',
    type: 'line',
    source: 'wi-border',
    paint: { 'line-color': '#f3efef', 'line-width': 2.0, 'line-opacity': 0.9 }
  });

  // tracts fetch
  const { k, cell, knn } = DEFAULTS;
  const res = await fetch(`${API_BASE}/api/tracts?k=${k}&cell=${cell}&knn=${knn}`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`tracts fetch failed: ${res.status}`);
  const tracts = await res.json();
  latestTracts = tracts;

  map.addSource('tracts', { type: 'geojson', data: tracts });

  const b = new maplibregl.LngLatBounds();
  for (const f of tracts.features) {
    const coords = f.geometry.coordinates.flat(3);
    for (let i = 0; i < coords.length; i += 2) b.extend([coords[i], coords[i + 1]]);
  }
  map.fitBounds(b, { padding: 40, duration: 0 });

  // cancer ramp
  const canrates = getNumeric(tracts.features.map(f => f.properties?.canrate));
  const colors = [
    '#f7f7f7',
    '#d9d9d9',
    '#bdbdbd',
    '#969696',
    '#636363',
    '#252525'
  ];

  const needed = colors.length - 1;

  let breaks = [
    quantile(canrates, 0.20),
    quantile(canrates, 0.40),
    quantile(canrates, 0.60),
    quantile(canrates, 0.80),
  ].filter(Number.isFinite).sort((a, b) => a - b);

  breaks = breaks.filter((v, i, arr) => i === 0 || v > arr[i - 1]);

  if (breaks.length < needed) {
    const min = canrates[0];
    const max = canrates[canrates.length - 1];
    if (Number.isFinite(min) && Number.isFinite(max) && max > min) {
      breaks = Array.from({ length: needed }, (_, i) =>
        min + (max - min) * ((i + 1) / (needed + 1))
      );
    }
  }

  map.addLayer({
    id: 'tracts-fill',
    type: 'fill',
    source: 'tracts',
    paint: {
      'fill-opacity': 0.90,
      'fill-color': buildStepExpr('canrate', breaks, colors)
    }
  });

  // Residual layer (hidden by default)
  const residuals = getNumeric(
    tracts.features.map(f => f.properties?.resid_canrate)
  );

  const q20 = quantile(residuals, 0.20);
  const q40 = quantile(residuals, 0.40);
  const q60 = quantile(residuals, 0.60);
  const q80 = quantile(residuals, 0.80);

  const resBreaks = [q20, q40, q60, q80];

  const resColors = [
    '#2166ac',  // strong negative
    '#67a9cf',
    '#f7f7f7',
    '#f4a582',
    '#b2182b'   // strong positive
  ];


  map.addLayer({
    id: 'tracts-residual',
    type: 'fill',
    source: 'tracts',
    layout: { visibility: 'none' },
    paint: {
      'fill-opacity': 0.7,
      'fill-color': buildStepExpr('resid_canrate', resBreaks, resColors)
    }
  });

  map.addLayer({
    id: 'tracts-outline',
    type: 'line',
    source: 'tracts',
    paint: { 'line-color': '#000', 'line-opacity': 0.25, 'line-width': 0.5 }
  });

  enforceLayerOrder();

  // hover tooltip 
  const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false });

  map.on('mousemove', 'tracts-fill', (e) => {
    map.getCanvas().style.cursor = 'pointer';
    const f = e.features?.[0];
    if (!f) return;

    const geoid = f.properties?.GEOID10;
    const canrate = Number(f.properties?.canrate);
    const nitrate = Number(f.properties?.mean_nitrate);
    const pred = Number(f.properties?.pred_canrate);
    const resid = Number(f.properties?.resid_canrate);

    popup
      .setLngLat(e.lngLat)
      .setHTML(`<div style="font: 12px/1.2 sans-serif">
        <div><b>GEOID10:</b> ${geoid ?? ''}</div>
  <div><b>Observed canrate:</b> ${Number.isFinite(canrate) ? canrate.toFixed(4) : ''}</div>
  <div><b>Mean nitrate:</b> ${Number.isFinite(nitrate) ? nitrate.toFixed(2) : ''}</div>
  <hr/>
  <div><b>Predicted canrate:</b> ${Number.isFinite(pred) ? pred.toFixed(4) : ''}</div>
  <div><b>Residual (obs-pred):</b> ${Number.isFinite(resid) ? resid.toFixed(4) : ''}</div>
</div>`)
      .addTo(map);
  });
  map.on('mouseleave', 'tracts-fill', () => {
    map.getCanvas().style.cursor = '';
    popup.remove();
  });

  try {
    const html = await (async () => {
      await setIdwOverlay(ui.getSelectedK());
      const reg = await fetchRegression(ui.getSelectedK());
      latestRegression = reg;
      return regressionHtml(reg, ui.getSelectedK());
    })();

    // render stats + toggles
    ui.renderStatsWithToggles(html);

    // default layer visibility 
    currentLayerState = ui.getLayerState();
    setTractsVisible(currentLayerState.showTracts);
    setNitrateVisible(currentLayerState.showNitrate);

    ui.setStatus('done');
  } finally {
    ui.setRunEnabled(true);
    hideLoader();
  }

});
