import './style.css';
import maplibregl from 'maplibre-gl';

const map = new maplibregl.Map({
  container: 'map',
  style: 'https://demotiles.maplibre.org/style.json',
  center: [-89.7, 44.6],
  zoom: 5.6
});

map.addControl(new maplibregl.NavigationControl(), 'top-right');

map.on('load', async () => {
  // Fetch tracts from backend (Vite proxy forwards /api/* to Flask)
  const res = await fetch('/api/tracts?k=2.0&cell=500&knn=32', { cache: 'no-store' });
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

  // Add IDW raster overlay 
  const metaRes = await fetch('/api/idw_meta?k=2.0&cell=500&knn=32', { cache: 'no-store' });
  if (!metaRes.ok) throw new Error(`idw_meta failed: ${metaRes.status}`);
  const meta = await metaRes.json();

  map.addSource('idw', {
    type: 'image',
    url: meta.url,
    coordinates: meta.coordinates
  });

  map.addLayer({
    id: 'idw-raster',
    type: 'raster',
    source: 'idw',
    paint: {
      'raster-opacity': 0.55
    }
  });

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
});
