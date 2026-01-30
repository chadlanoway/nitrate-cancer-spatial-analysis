import './style.css';
import maplibregl from 'maplibre-gl';

const map = new maplibregl.Map({
  container: 'map',
  style: 'https://demotiles.maplibre.org/style.json',
  center: [-89.7, 44.6],
  zoom: 5.6
});

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

  // cache-bust the PNG so dragging always updates
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
    paint: { 'raster-opacity': 0.55 }
  });

  // Ensure tracts draw on top
  if (map.getLayer('tracts-fill')) map.moveLayer('tracts-fill');
  if (map.getLayer('tracts-outline')) map.moveLayer('tracts-outline');
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

map.addControl(new maplibregl.NavigationControl(), 'top-right');

map.on('load', async () => {
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

  // Fill layer styled by canrate
  map.addLayer({
    id: 'tracts-fill',
    type: 'fill',
    source: 'tracts',
    paint: {
      'fill-opacity': 0.55,
      'fill-color': [
        'step',
        ['to-number', ['get', 'canrate']],
        '#f7fbff', 0.02,
        '#c6dbef', 0.05,
        '#6baed6', 0.08,
        '#2171b5', 0.12,
        '#08306b'
      ]
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
