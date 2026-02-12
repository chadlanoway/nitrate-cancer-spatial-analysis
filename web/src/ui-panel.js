/**
 * UI PANEL (frontend)
 * ------------------
 * Manages the interactive control panel on the map page.
 * Handles user inputs (k slider, run button, layer toggles),
 * renders regression statistics returned from the backend,
 * and communicates user actions back to main.js via callbacks.
 *
 * UI-only: it does not fetch data or manipulate the map directly.
 */

export function initUiPanel({ defaults, onRun, onToggleLayers, onShowScatter }) {
    const kSlider = document.getElementById('kSlider');
    const kVal = document.getElementById('kVal');
    const runBtn = document.getElementById('runBtn');
    const runStatus = document.getElementById('runStatus');
    const statsEl = document.getElementById('stats');

    if (!kSlider || !kVal || !runBtn || !runStatus || !statsEl) {
        throw new Error('UI elements missing (kSlider/kVal/runBtn/runStatus/stats).');
    }
    const uiEl = document.getElementById('ui');
    if (!uiEl) throw new Error('Missing #ui container.');

    // top-right chart link (inside the panel)
    if (!document.getElementById('scatterLink')) {
        const a = document.createElement('a');
        a.id = 'scatterLink';
        a.href = '#';
        a.className = 'ui-scatter-link';
        a.textContent = 'Scatter';
        a.addEventListener('click', (e) => {
            e.preventDefault();
            onShowScatter?.();
        });
        uiEl.appendChild(a);
    }

    const slider = installSlidingWrapper(uiEl);

    let selectedK = parseFloat(kSlider.value);
    if (!Number.isFinite(selectedK)) selectedK = defaults.k ?? 2.0;

    // default on page load, both layers visible
    const layerState = {
        showTracts: true,
        showNitrate: true,
        showResidual: false
    };

    function setStatus(text) {
        runStatus.textContent = text;
    }

    function setRunEnabled(enabled) {
        runBtn.disabled = !enabled;
    }

    function renderStatsWithToggles(regressionHtml) {
        statsEl.innerHTML = `
  ${regressionHtml}
  <hr/>
  <div style="display:flex; flex-direction:column; gap:6px; margin-top:8px;">

    <div class="layer-row" id="tracts-row">
      <label style="display:flex; align-items:center; gap:8px; cursor:pointer;">
        <input
          id="toggleTracts"
          type="checkbox"
          ${layerState.showTracts ? 'checked' : ''}
        />
        <span>Cancer tracts</span>
      </label>
    </div>

    <div class="layer-row" id="nitrate-row">
      <label style="display:flex; align-items:center; gap:8px; cursor:pointer;">
        <input
          id="toggleNitrate"
          type="checkbox"
          ${layerState.showNitrate ? 'checked' : ''}
        />
        <span>Nitrate raster</span>
      </label>
    </div>

    <div class="layer-row" id="residual-row">
        <label style="display:flex; align-items:center; gap:8px; cursor:pointer;">
            <input id="toggleResidual" type="checkbox" />
            <span>Residuals</span>
        </label>
    </div>

  </div>
`;
        // cancer legend color ramp
        document.getElementById('tracts-row')?.appendChild(
            makeLegendPill({
                id: 'cancer',
                left: 'low',
                right: 'high',
                stops: [
                    { p: 0.0, c: '#f7f7f7' },
                    { p: 0.2, c: '#d9d9d9' },
                    { p: 0.4, c: '#bdbdbd' },
                    { p: 0.6, c: '#969696' },
                    { p: 0.8, c: '#636363' },
                    { p: 1.0, c: '#252525' }
                ]
            })
        );
        // nitrate legend ramp 
        document.getElementById('nitrate-row')?.appendChild(
            makeLegendPill({
                id: 'nitrate',
                left: '0',
                right: '16+',
                stops: [
                    { p: 0.0, c: '#0000ff' },
                    { p: 0.5, c: '#00ffff' },
                    { p: 0.75, c: '#ffff00' },
                    { p: 1.0, c: '#ff0000' }
                ]
            })
        );
        // residuals legend ramp 
        document.getElementById('residual-row')?.appendChild(
            makeLegendPill({
                id: 'residual',
                left: 'low',
                right: 'high',
                stops: [
                    { p: 0.0, c: '#2166ac' },
                    { p: 0.25, c: '#67a9cf' },
                    { p: 0.5, c: '#f7f7f7' },
                    { p: 0.75, c: '#f4a582' },
                    { p: 1.0, c: '#b2182b' }
                ]
            })
        );

        const tractsCb = document.getElementById('toggleTracts');
        const nitrateCb = document.getElementById('toggleNitrate');

        tractsCb.addEventListener('change', () => {
            layerState.showTracts = tractsCb.checked;
            document
                .querySelector('[data-legend-id="cancer"]')
                .style.display = tractsCb.checked ? '' : 'none';
            onToggleLayers?.(layerState);
        });

        nitrateCb.addEventListener('change', () => {
            layerState.showNitrate = nitrateCb.checked;
            document
                .querySelector('[data-legend-id="nitrate"]')
                .style.display = nitrateCb.checked ? '' : 'none';
            onToggleLayers?.(layerState);
        });

        const residualCb = document.getElementById('toggleResidual');

        residualCb.addEventListener('change', () => {
            layerState.showResidual = residualCb.checked;

            const leg = document.querySelector('[data-legend-id="residual"]');
            if (leg) leg.style.display = residualCb.checked ? '' : 'none';

            onToggleLayers?.(layerState);
        });

    }

    // initialize UI
    kVal.textContent = selectedK.toFixed(1);
    setStatus('ready');

    kSlider.addEventListener('input', () => {
        selectedK = parseFloat(kSlider.value);
        kVal.textContent = Number.isFinite(selectedK) ? selectedK.toFixed(1) : '';
        setStatus('ready');
    });

    runBtn.addEventListener('click', async () => {
        setRunEnabled(false);
        setStatus('computing…');

        try {
            const regressionHtml = await onRun(selectedK);
            renderStatsWithToggles(regressionHtml);
            setStatus('done');
        } catch (err) {
            console.error(err);
            setStatus('error');
            statsEl.innerHTML = `<div style="color:#b00"><b>Error:</b> ${err.message}</div>`;
        } finally {
            setRunEnabled(true);
        }
    });

    return {
        getSelectedK: () => selectedK,
        setStatus,
        setRunEnabled,
        renderStatsWithToggles,
        getLayerState: () => ({ ...layerState }),
        slider
    };
}

function installSlidingWrapper(uiEl) {
    const wrap = document.createElement('div');
    wrap.id = 'ui-wrap';
    document.body.classList.add('ui-booted');
    wrap.style.position = 'absolute';

    const btn = document.createElement('button');
    btn.id = 'ui-toggle';
    btn.type = 'button';
    btn.setAttribute('aria-label', 'Toggle panel');

    btn.innerHTML = `
    <span class="bar"></span>
    <span class="bar"></span>
    <span class="bar"></span>
  `;

    const parent = uiEl.parentNode;
    parent.insertBefore(wrap, uiEl);
    wrap.appendChild(uiEl);
    wrap.appendChild(btn);
    wrap.classList.add('is-ready');

    // default: collapsed on load
    wrap.classList.add('is-collapsed');

    btn.addEventListener('click', () => {
        wrap.classList.toggle('is-collapsed');
    });

    // ESC closes, Enter opens (nice, I've never used keydown before and it's pretty cool)
    window.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') wrap.classList.add('is-collapsed');
        if (e.key === 'Enter') wrap.classList.remove('is-collapsed');
    });

    return {
        collapse: () => wrap.classList.add('is-collapsed'),
        expand: () => wrap.classList.remove('is-collapsed'),
        toggle: () => wrap.classList.toggle('is-collapsed'),
        isCollapsed: () => wrap.classList.contains('is-collapsed')
    };
}

function makeLegendPill({ id, left, right, stops }) {
    const el = document.createElement('div');
    el.className = 'legend-pill';
    el.dataset.legendId = id;

    const grad = stops
        .map(s => `${s.c} ${Math.round(s.p * 100)}%`)
        .join(', ');

    el.innerHTML = `
    <div class="legend-pill-bar"
         style="background: linear-gradient(to right, ${grad});"></div>
    <div class="legend-pill-labels">
      <span>${left ?? ''}</span>
      <span>${right ?? ''}</span>
    </div>
  `;
    return el;
}

