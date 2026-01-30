import './style.css';
import maplibregl from 'maplibre-gl';

const map = new maplibregl.Map({
  container: 'map',
  style: 'https://demotiles.maplibre.org/style.json',
  center: [-89.7, 44.6],
  zoom: 5.6
});
window.map = map;

const DEFAULTS = { cell: 500, knn: 32 };

const kSlider = document.getElementById('kSlider');
const kVal = document.getElementById('kVal');
const runBtn = document.getElementById('runBtn');
const runStatus = document.getElementById('runStatus');


const statsEl = document.getElementById('stats');

function fmt(x, d = 4) { return Number.isFinite(x) ? x.toFixed(d) : ''; }

async function setIdwOverlay(k) {
  const cell = DEFAULTS.cell;
  const knn = DEFAULTS.knn;

  const metaRes = await fetch(`/api/idw_meta?k=${k}&cell=${cell}&knn=${knn}`, { cache: 'no-store' });
  if (!metaRes.ok) throw new Error(`idw_meta failed: ${metaRes.status}`);
  const meta = await metaRes.json();

  const url = `${meta.url}&v=${Date.now()}`;

  // Remove old overlay if present
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
    paint: { 'raster-opacity': 0.5 }
  });

  if (map.getLayer('wi-mask-fill') && map.getLayer('idw-raster')) {
    map.moveLayer('wi-mask-fill');
    map.moveLayer('idw-raster', 'wi-mask-fill');
  }

  // Tracts above mask
  if (map.getLayer('tracts-fill')) map.moveLayer('tracts-fill');
  if (map.getLayer('tracts-outline')) map.moveLayer('tracts-outline');

  // Border on top of everything
  if (map.getLayer('wi-border-line')) map.moveLayer('wi-border-line');
}

async function updateRegression(k) {
  const cell = DEFAULTS.cell;
  const knn = DEFAULTS.knn;

  const r = await fetch(`/api/regression?k=${k}&cell=${cell}&knn=${knn}`, { cache: 'no-store' });
  if (!r.ok) throw new Error(`regression failed: ${r.status}`);
  const j = await r.json();

  statsEl.innerHTML = `
    <div><b>Regression</b> (tract canrate ~ mean nitrate)</div>
    <div>k=${k.toFixed(1)}  cell=${cell}m  knn=${knn}</div>
    <hr/>
    <div><b>slope</b>: ${fmt(j.params?.slope ?? j.slope, 6)}</div>
    <div><b>p</b>: ${Number.isFinite(j.p_value_slope) ? j.p_value_slope.toExponential(2) : ''}</div>
    <div><b>R²</b>: ${fmt(j.r2, 4)}</div>
    <div><b>n</b>: ${j.n}</div>
  `;
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
  // breaks length = colors length - 1
  const expr = ['step', ['to-number', ['get', field]], colors[0]];
  for (let i = 0; i < breaks.length; i++) expr.push(breaks[i], colors[i + 1]);
  return expr;
}

map.addControl(new maplibregl.NavigationControl(), 'top-right');

map.on('load', async () => {

  map.addSource('wi-border', {
    type: 'geojson',
    data: '/data/wi_mask/wi_border.geojson'
  });

  map.addSource('wi-mask', {
    type: 'geojson',
    data: '/data/wi_mask/wi_mask.geojson'
  });
  // Dim everything outside Wisconsin (above basemap)
  map.addLayer({
    id: 'wi-mask-fill',
    type: 'fill',
    source: 'wi-mask',
    paint: {
      'fill-color': '#0a0f18',   // dark navy/near-black
      'fill-opacity': 1
    }
  });

  // Wisconsin outline (we'll keep this on top)
  map.addLayer({
    id: 'wi-border-line',
    type: 'line',
    source: 'wi-border',
    paint: {
      'line-color': '#0b0b0b',
      'line-width': 2.0,
      'line-opacity': 0.9
    }
  });

  // Fetch tracts from backend (Vite proxy forwards /api/* to Flask)
  const { k, cell, knn } = DEFAULTS;
  const res = await fetch(`/api/tracts?k=${k}&cell=${cell}&knn=${knn}`, { cache: 'no-store' });

  if (!res.ok) throw new Error(`tracts fetch failed: ${res.status}`);
  const tracts = await res.json();

  map.addSource('tracts', {
    type: 'geojson',
    data: tracts
  });

  const b = new maplibregl.LngLatBounds();
  for (const f of tracts.features) {
    const coords = f.geometry.coordinates.flat(3);
    for (let i = 0; i < coords.length; i += 2) b.extend([coords[i], coords[i + 1]]);
  }
  map.fitBounds(b, { padding: 40, duration: 0 });

  const canrates = getNumeric(tracts.features.map(f => f.properties?.canrate));

  // want 6 colors => 5 thresholds
  const colors = ['#f7fbff', '#deebf7', '#c6dbef', '#9ecae1', '#6baed6', '#2171b5'];
  const needed = colors.length - 1;

  let breaks = [
    quantile(canrates, 0.20),
    quantile(canrates, 0.40),
    quantile(canrates, 0.60),
    quantile(canrates, 0.80),
  ].filter(Number.isFinite).sort((a, b) => a - b);

  // strict-ascending
  breaks = breaks.filter((v, i, arr) => i === 0 || v > arr[i - 1]);

  // If quantiles collapsed (ties), force equal-interval to fill out classes
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
      // start lower so raster can show through
      'fill-opacity': 0.50,
      'fill-color': buildStepExpr('canrate', breaks, colors)
    }
  });

  // Outline for readability
  map.addLayer({
    id: 'tracts-outline',
    type: 'line',
    source: 'tracts',
    paint: {
      'line-color': '#000',
      'line-opacity': 0.25,
      'line-width': 0.5
    }
  });

  // Hover tooltip 
  const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false });

  map.on('mousemove', 'tracts-fill', (e) => {
    map.getCanvas().style.cursor = 'pointer';
    const f = e.features?.[0];
    if (!f) return;

    const geoid = f.properties?.GEOID10;
    const canrate = Number(f.properties?.canrate);

    popup
      .setLngLat(e.lngLat)
      .setHTML(`<div style="font: 12px/1.2 sans-serif">
        <div><b>GEOID10:</b> ${geoid ?? ''}</div>
        <div><b>canrate:</b> ${Number.isFinite(canrate) ? canrate.toFixed(4) : ''}</div>
      </div>`)
      .addTo(map);
  });

  map.on('mouseleave', 'tracts-fill', () => {
    map.getCanvas().style.cursor = '';
    popup.remove();
  });

  // initial k from slider
  let selectedK = parseFloat(kSlider.value);
  kVal.textContent = selectedK.toFixed(1);
  runStatus.textContent = 'ready';

  kSlider.addEventListener('input', () => {
    selectedK = parseFloat(kSlider.value);
    kVal.textContent = selectedK.toFixed(1);
    runStatus.textContent = 'ready';
  });

  async function runAll(k) {
    runBtn.disabled = true;
    runStatus.textContent = 'computing…';

    try {
      await Promise.all([
        setIdwOverlay(k),
        updateRegression(k)
      ]);
      runStatus.textContent = 'done';
    } catch (err) {
      console.error(err);
      runStatus.textContent = 'error';
      statsEl.innerHTML = `<div style="color:#b00"><b>Error:</b> ${err.message}</div>`;
    } finally {
      runBtn.disabled = false;
    }
  }

  runBtn.addEventListener('click', () => runAll(selectedK));

  // run once on load (optional but recommended)
  await runAll(selectedK);


});
