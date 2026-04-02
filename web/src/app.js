import maplibregl from 'maplibre-gl';

let map, data, buildings, popup;
let selectedId = null;
let colourMode = 'material';

// Kensington Market bounds
const CENTER = [-79.4015, 43.6545];
const ZOOM = 16;

// Colour palettes
const MATERIAL_COLORS = {
    'brick': '#B85A3A', 'mixed masonry': '#9A7A5A', 'stucco': '#D4C8B0',
    'clapboard': '#C8B080', 'concrete': '#9A9690', 'stone': '#8A8078',
    'paint': '#E8E0D0', 'painted': '#E8E0D0', 'glass': '#88AACC',
    'vinyl siding': '#C0C0C0', 'metal': '#7A7A7A', 'painted brick': '#C07050',
};
const ERA_COLORS = {
    'Pre-1889': '#8B0000', '1889-1903': '#CD853F',
    '1904-1913': '#4682B4', '1914-1930': '#2E8B57',
};
const CONDITION_COLORS = { 'good': '#22c55e', 'fair': '#eab308', 'poor': '#ef4444' };
const HERITAGE_COLORS = { 'Yes': '#22c55e', 'No': '#ef4444' };
const ROOF_COLORS = {
    'cross-gable': '#6B4226', 'flat': '#4A4A4A', 'gable': '#8B5A3A', 'hip': '#5A6B4A', 'mansard': '#3A3A5A',
};

async function init() {
    // Load data
    try {
        const [appResp, geoResp] = await Promise.all([
            fetch('/data/app_data.json'),
            fetch('/data/buildings.geojson'),
        ]);
        data = appResp.ok ? await appResp.json() : { buildings: [], stats: {}, streets: {} };
        const geojson = geoResp.ok ? await geoResp.json() : null;

        buildings = data.buildings || [];

        // Merge param data into geojson features
        if (geojson) {
            const paramMap = {};
            buildings.forEach(b => { paramMap[b.address] = b; });

            geojson.features.forEach(f => {
                const p = paramMap[f.properties.address] || {};
                Object.assign(f.properties, p);
                // Set colour based on mode
                f.properties._color = getColor(f.properties);
            });
        }

        // Init map
        map = new maplibregl.Map({
            container: 'map',
            style: {
                version: 8,
                sources: {
                    'osm-raster': {
                        type: 'raster',
                        tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
                        tileSize: 256,
                        attribution: '&copy; OpenStreetMap',
                    },
                },
                layers: [{
                    id: 'osm-tiles',
                    type: 'raster',
                    source: 'osm-raster',
                    minzoom: 0,
                    maxzoom: 19,
                    paint: {
                        'raster-saturation': -0.6,
                        'raster-brightness-max': 0.4,
                        'raster-contrast': 0.2,
                    },
                }],
            },
            center: CENTER,
            zoom: ZOOM,
            pitch: 45,
            bearing: -17,
            antialias: true,
        });

        map.addControl(new maplibregl.NavigationControl(), 'top-right');

        map.on('load', () => {
            if (geojson) {
                // Add building source
                map.addSource('buildings', { type: 'geojson', data: geojson });

                // 3D extruded buildings
                map.addLayer({
                    id: 'buildings-3d',
                    type: 'fill-extrusion',
                    source: 'buildings',
                    paint: {
                        'fill-extrusion-color': ['get', '_color'],
                        'fill-extrusion-height': ['coalesce', ['get', 'height'], 7],
                        'fill-extrusion-base': 0,
                        'fill-extrusion-opacity': 0.85,
                    },
                });

                // Building outlines (top-down)
                map.addLayer({
                    id: 'buildings-outline',
                    type: 'line',
                    source: 'buildings',
                    paint: {
                        'line-color': '#000000',
                        'line-width': 0.5,
                        'line-opacity': 0.3,
                    },
                });

                // Click handler
                map.on('click', 'buildings-3d', (e) => {
                    if (e.features.length > 0) {
                        const props = e.features[0].properties;
                        showBuilding(props);
                    }
                });

                // Hover cursor
                map.on('mouseenter', 'buildings-3d', () => { map.getCanvas().style.cursor = 'pointer'; });
                map.on('mouseleave', 'buildings-3d', () => { map.getCanvas().style.cursor = ''; });

                // Hover tooltip
                popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 10 });
                map.on('mousemove', 'buildings-3d', (e) => {
                    if (e.features.length > 0) {
                        const p = e.features[0].properties;
                        popup.setLngLat(e.lngLat)
                            .setHTML(`<strong>${p.address || '?'}</strong><br>${p.era || ''} | ${p.facade_material || ''}`)
                            .addTo(map);
                    }
                });
                map.on('mouseleave', 'buildings-3d', () => { popup.remove(); });
            }
        });

        // Populate UI
        updateStats();
        populateFilters();
        setupBarCharts();
        setupEventHandlers();
        updateLegend();
        populateBuildingList();

    } catch (e) {
        console.error('Init failed:', e);
        document.getElementById('map').innerHTML = `<div style="padding:40px;color:#888">Load error: ${e.message}</div>`;
    }
}

function getColor(props) {
    switch (colourMode) {
        case 'material': {
            const mat = (props.facade_material || '').toLowerCase();
            if (props.facade_hex) return props.facade_hex;
            return MATERIAL_COLORS[mat] || '#B85A3A';
        }
        case 'heritage':
            return HERITAGE_COLORS[props.contributing] || '#666666';
        case 'era': {
            const era = props.era || '';
            for (const [key, col] of Object.entries(ERA_COLORS)) {
                if (era.includes(key)) return col;
            }
            return '#666666';
        }
        case 'condition':
            return CONDITION_COLORS[(props.condition || '').toLowerCase()] || '#666666';
        case 'audit': {
            const score = props.gap_score || 50;
            if (score >= 70) return '#ef4444';
            if (score >= 50) return '#f59e0b';
            if (score >= 30) return '#eab308';
            if (score >= 15) return '#22c55e';
            return '#3b82f6';
        }
        case 'roof':
            return ROOF_COLORS[(props.roof_type || '').toLowerCase()] || '#666666';
        default:
            return '#B85A3A';
    }
}

function updateColors() {
    const source = map.getSource('buildings');
    if (!source) return;
    const geojson = source._data;
    if (!geojson || !geojson.features) return;
    geojson.features.forEach(f => {
        f.properties._color = getColor(f.properties);
    });
    source.setData(geojson);
}

function showBuilding(props) {
    // Parse JSON strings from geojson properties
    let decorative = props.decorative;
    if (typeof decorative === 'string') {
        try { decorative = JSON.parse(decorative); } catch { decorative = []; }
    }

    const body = document.getElementById('panel-body');
    const condClass = `badge-condition-${(props.condition || 'fair').toLowerCase()}`;
    const heritageClass = props.contributing === 'Yes' ? 'badge-contributing' : 'badge-non-contributing';
    const tierClass = props.audit_tier ? `tier-${props.audit_tier}` : '';

    body.innerHTML = `
        <div class="building-header">
            <div class="address">${props.address || '?'}</div>
            <div class="badges">
                <span class="badge ${heritageClass}">${props.contributing === 'Yes' ? 'Contributing' : 'Non-Contributing'}</span>
                ${props.era ? `<span class="badge badge-era">${props.era}</span>` : ''}
                ${props.facade_material ? `<span class="badge badge-material">${props.facade_material}</span>` : ''}
                ${props.condition ? `<span class="badge ${condClass}">${props.condition}</span>` : ''}
            </div>
        </div>

        <!-- Images -->
        <div class="image-compare">
            <div>
                ${props.has_render === true || props.has_render === 'true'
                    ? `<img src="/renders/${props.id}.png" alt="Render" onerror="this.style.display='none'">`
                    : `<div style="height:140px;background:var(--card);border-radius:6px;display:flex;align-items:center;justify-content:center;color:var(--dim);font-size:11px">No render</div>`}
                <div class="img-label">3D Render</div>
            </div>
            <div>
                ${props.has_photo === true || props.has_photo === 'true'
                    ? `<img src="/${props.photo_path}" alt="Photo" onerror="this.style.display='none'">`
                    : `<div style="height:140px;background:var(--card);border-radius:6px;display:flex;align-items:center;justify-content:center;color:var(--dim);font-size:11px">No photo</div>`}
                <div class="img-label">Field Photo</div>
            </div>
        </div>

        <!-- Audit -->
        ${props.gap_score != null ? `
        <div class="section-title">Visual Audit</div>
        <div class="audit-score">
            <div class="audit-bar">
                <div class="audit-fill" style="width:${Math.min(props.gap_score, 100)}%;background:${
                    props.gap_score >= 70 ? '#ef4444' : props.gap_score >= 40 ? '#f59e0b' : '#22c55e'
                }"></div>
            </div>
            <div class="audit-value">${Math.round(props.gap_score)}</div>
            ${props.audit_tier ? `<span class="audit-tier ${tierClass}">${props.audit_tier}</span>` : ''}
        </div>
        ${props.primary_issue ? `<div style="font-size:11px;color:var(--dim)">Issue: ${props.primary_issue}</div>` : ''}
        ` : ''}

        <!-- Colours -->
        ${props.facade_hex || props.trim_hex || props.roof_hex ? `
        <div class="section-title">Colour Palette</div>
        <div class="swatches">
            ${props.facade_hex ? `<div class="swatch"><div class="swatch-circle" style="background:${props.facade_hex}"></div><div class="swatch-label">Facade</div></div>` : ''}
            ${props.trim_hex ? `<div class="swatch"><div class="swatch-circle" style="background:${props.trim_hex}"></div><div class="swatch-label">Trim</div></div>` : ''}
            ${props.roof_hex ? `<div class="swatch"><div class="swatch-circle" style="background:${props.roof_hex}"></div><div class="swatch-label">Roof</div></div>` : ''}
        </div>
        ` : ''}

        <!-- Properties -->
        <div class="section-title">Properties</div>
        <table class="prop-table">
            <tr><td>Floors</td><td>${props.floors || '?'}</td></tr>
            <tr><td>Height</td><td>${props.total_height_m ? props.total_height_m + 'm' : '?'}</td></tr>
            <tr><td>Width</td><td>${props.facade_width_m ? props.facade_width_m + 'm' : '?'}</td></tr>
            <tr><td>Depth</td><td>${props.facade_depth_m ? props.facade_depth_m + 'm' : '?'}</td></tr>
            <tr><td>Roof</td><td>${props.roof_type || '?'}</td></tr>
            <tr><td>Storefront</td><td>${props.has_storefront === true || props.has_storefront === 'true' ? 'Yes' : 'No'}</td></tr>
            <tr><td>Party wall L</td><td>${props.party_wall_left === true || props.party_wall_left === 'true' ? 'Yes' : 'No'}</td></tr>
            <tr><td>Party wall R</td><td>${props.party_wall_right === true || props.party_wall_right === 'true' ? 'Yes' : 'No'}</td></tr>
        </table>

        <!-- Heritage -->
        ${props.typology ? `
        <div class="section-title">Heritage</div>
        <table class="prop-table">
            <tr><td>Typology</td><td>${props.typology}</td></tr>
            <tr><td>Style</td><td>${props.architectural_style || '?'}</td></tr>
            <tr><td>Street</td><td>${props.street || '?'}</td></tr>
        </table>
        ` : ''}

        <!-- Decorative -->
        ${decorative && decorative.length ? `
        <div class="section-title">Decorative Elements</div>
        <div class="decorative-list">
            ${decorative.map(d => `<span class="decorative-tag">${d.replace(/_/g, ' ')}</span>`).join('')}
        </div>
        ` : ''}

        <!-- Visual Comparison slider -->
        ${(props.has_render === true || props.has_render === 'true') && (props.has_photo === true || props.has_photo === 'true') ? (() => {
            const renderSrc = `/renders/${props.id}.png`;
            const photoSrc = `/${props.photo_path}`;
            return `<div class="section-title">Visual Comparison</div>
        <div style="position:relative;width:100%;height:200px;overflow:hidden;border-radius:8px;margin:8px 0;" id="compare-container">
            <img src="${renderSrc}" style="position:absolute;left:0;top:0;width:100%;height:100%;object-fit:cover;" id="compare-render">
            <div style="position:absolute;left:0;top:0;width:50%;height:100%;overflow:hidden;" id="compare-clip">
                <img src="${photoSrc}" style="width:200%;height:100%;object-fit:cover;" id="compare-photo">
            </div>
            <div style="position:absolute;left:50%;top:0;width:3px;height:100%;background:white;cursor:col-resize;z-index:10;" id="compare-divider"></div>
        </div>`;
        })() : ''}
    `;

    initCompareSlider();
}

function initCompareSlider() {
    const container = document.getElementById('compare-container');
    const divider = document.getElementById('compare-divider');
    const clip = document.getElementById('compare-clip');
    if (!container || !divider || !clip) return;

    let dragging = false;

    divider.addEventListener('mousedown', (e) => {
        dragging = true;
        e.preventDefault();
    });

    document.addEventListener('mousemove', (e) => {
        if (!dragging) return;
        const rect = container.getBoundingClientRect();
        let pct = (e.clientX - rect.left) / rect.width;
        pct = Math.max(0, Math.min(1, pct));
        const pctStr = (pct * 100) + '%';
        divider.style.left = pctStr;
        clip.style.width = pctStr;
    });

    document.addEventListener('mouseup', () => { dragging = false; });

    // Touch support
    divider.addEventListener('touchstart', (e) => { dragging = true; e.preventDefault(); }, { passive: false });
    document.addEventListener('touchmove', (e) => {
        if (!dragging) return;
        const rect = container.getBoundingClientRect();
        let pct = (e.touches[0].clientX - rect.left) / rect.width;
        pct = Math.max(0, Math.min(1, pct));
        const pctStr = (pct * 100) + '%';
        divider.style.left = pctStr;
        clip.style.width = pctStr;
    }, { passive: true });
    document.addEventListener('touchend', () => { dragging = false; });
}

function updateStats() {
    const s = data.stats || {};
    document.getElementById('s-buildings').textContent = s.total_buildings || buildings.length;
    document.getElementById('s-contributing').textContent = s.contributing || '?';
    document.getElementById('s-renders').textContent = s.with_renders || '?';
    document.getElementById('s-photos').textContent = s.with_photos || '?';
}

function populateFilters() {
    const streetSelect = document.getElementById('filter-street');
    const streets = data.stats?.streets || {};
    Object.keys(streets).sort().forEach(s => {
        if (!s || s === 'Unknown') return;
        const opt = document.createElement('option');
        opt.value = s;
        opt.textContent = `${s} (${streets[s]})`;
        streetSelect.appendChild(opt);
    });
}

function setupBarCharts() {
    const eras = data.stats?.eras || {};
    const eraChart = document.getElementById('era-chart');
    const maxEra = Math.max(...Object.values(eras), 1);
    const eraColors = { 'Pre-1889': '#8B0000', '1889-1903': '#CD853F', '1904-1913': '#4682B4', '1914-1930': '#2E8B57' };

    eraChart.innerHTML = Object.entries(eras)
        .filter(([k]) => k !== 'Unknown' && !k.match(/^\d{4}$/))
        .sort((a, b) => b[1] - a[1])
        .slice(0, 6)
        .map(([era, count]) => {
            const pct = (count / maxEra) * 100;
            const col = eraColors[era] || '#666';
            return `<div class="bar-row">
                <div class="bar-label">${era}</div>
                <div class="bar" style="width:${pct}%;background:${col}"></div>
                <div class="bar-value">${count}</div>
            </div>`;
        }).join('');

    const mats = data.stats?.materials || {};
    const matChart = document.getElementById('material-chart');
    const maxMat = Math.max(...Object.values(mats), 1);

    matChart.innerHTML = Object.entries(mats)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 6)
        .map(([mat, count]) => {
            const pct = (count / maxMat) * 100;
            const col = MATERIAL_COLORS[mat] || '#888';
            return `<div class="bar-row">
                <div class="bar-label">${mat}</div>
                <div class="bar" style="width:${pct}%;background:${col}"></div>
                <div class="bar-value">${count}</div>
            </div>`;
        }).join('');
}

const LEGEND_DATA = {
    material: { brick: '#B85A3A', stucco: '#D4C8B0', paint: '#E8E0D0', stone: '#8A8078', concrete: '#9A9690' },
    heritage: { Contributing: '#22c55e', 'Non-contributing': '#ef4444' },
    era: { 'Pre-1889': '#8B0000', '1889-1903': '#CD853F', '1904-1913': '#4682B4', '1914-1930': '#2E8B57' },
    condition: { Good: '#22c55e', Fair: '#eab308', Poor: '#ef4444' },
    audit: { 'Low risk': '#3b82f6', Medium: '#eab308', High: '#f59e0b', Critical: '#ef4444' },
    roof: { 'cross-gable': '#6B4226', flat: '#4A4A4A', gable: '#8B5A3A', hip: '#5A6B4A' },
};

function updateLegend() {
    const container = document.getElementById('legend-items');
    if (!container) return;
    const entries = LEGEND_DATA[colourMode];
    if (!entries) { container.innerHTML = ''; return; }
    container.innerHTML = Object.entries(entries).map(([label, colour]) =>
        `<div style="display:flex;align-items:center;gap:6px;margin:3px 0;">
            <div style="width:12px;height:12px;border-radius:2px;background:${colour};flex-shrink:0;"></div>
            <span style="font-size:11px;color:var(--text)">${label}</span>
        </div>`
    ).join('');
}

function populateBuildingList() {
    const list = document.getElementById('building-list');
    if (!list || !buildings.length) return;
    const sorted = [...buildings].filter(b => b.lon && b.lat).sort((a, b) => (b.gap_score || 0) - (a.gap_score || 0));
    const label = document.getElementById('building-count-label');
    if (label) label.textContent = `(${sorted.length})`;
    list.innerHTML = sorted.slice(0, 200).map(b => {
        const score = b.gap_score || 0;
        const barColor = score >= 70 ? '#ef4444' : score >= 40 ? '#f59e0b' : score >= 15 ? '#eab308' : '#22c55e';
        return `<div class="building-list-item" onclick="flyTo(${b.lon},${b.lat},'${(b.address || '').replace(/'/g, "\\'")}')" title="${b.address}">
            <span class="addr">${b.address}</span>
            <div style="width:40px;height:4px;background:var(--card);border-radius:2px;overflow:hidden;margin-left:8px;">
                <div style="width:${score}%;height:100%;background:${barColor};border-radius:2px;"></div>
            </div>
        </div>`;
    }).join('');
}

window.flyTo = function(lon, lat, address) {
    map.flyTo({ center: [lon, lat], zoom: 18, pitch: 60, duration: 1000 });
    const b = buildings.find(b => b.address === address);
    if (b) showBuilding(b);
};

function setupEventHandlers() {
    // Colour mode
    document.getElementById('colour-mode').addEventListener('change', (e) => {
        colourMode = e.target.value;
        updateColors();
        updateLegend();
    });

    // Street filter
    document.getElementById('filter-street').addEventListener('change', (e) => {
        const street = e.target.value;
        if (!street) {
            map.setFilter('buildings-3d', null);
            map.setFilter('buildings-outline', null);
        } else {
            map.setFilter('buildings-3d', ['==', ['get', 'street'], street]);
            map.setFilter('buildings-outline', ['==', ['get', 'street'], street]);
        }
    });

    // Search — filter building list and fly to first match
    let fullGeojson = null;
    document.getElementById('filter-search').addEventListener('input', (e) => {
        const q = e.target.value.toLowerCase();
        const source = map.getSource('buildings');
        if (!source || !source._data) return;

        // Cache full dataset on first search
        if (!fullGeojson) fullGeojson = JSON.parse(JSON.stringify(source._data));

        if (!q) {
            source.setData(fullGeojson);
            populateBuildingList();
        } else {
            const filtered = {
                type: 'FeatureCollection',
                features: fullGeojson.features.filter(f =>
                    (f.properties.address || '').toLowerCase().includes(q)
                ),
            };
            filtered.features.forEach(f => { f.properties._color = getColor(f.properties); });
            source.setData(filtered);

            // Update building list with filtered results
            const list = document.getElementById('building-list');
            const label = document.getElementById('building-count-label');
            const matches = buildings.filter(b => (b.address || '').toLowerCase().includes(q));
            if (label) label.textContent = `(${matches.length})`;
            if (list) {
                list.innerHTML = matches.slice(0, 100).map(b => {
                    const score = b.gap_score || 0;
                    const barColor = score >= 70 ? '#ef4444' : score >= 40 ? '#f59e0b' : score >= 15 ? '#eab308' : '#22c55e';
                    return `<div class="building-list-item" onclick="flyTo(${b.lon},${b.lat},'${(b.address || '').replace(/'/g, "\\'")}')" title="${b.address}">
                        <span class="addr">${b.address}</span>
                        <div style="width:40px;height:4px;background:var(--card);border-radius:2px;overflow:hidden;margin-left:8px;">
                            <div style="width:${score}%;height:100%;background:${barColor};border-radius:2px;"></div>
                        </div>
                    </div>`;
                }).join('');
            }
        }
    });

    // Scenario pills
    document.querySelectorAll('.pill').forEach(pill => {
        pill.addEventListener('click', async () => {
            document.querySelectorAll('.pill').forEach(p => p.classList.remove('active'));
            pill.classList.add('active');
            const scenario = pill.dataset.scenario;
            await loadScenario(scenario);
        });
    });

    // Panel close
    document.getElementById('panel-close').addEventListener('click', () => {
        document.getElementById('panel-body').innerHTML =
            '<p style="color:var(--dim);font-size:13px;">Click a building on the map to inspect it.</p>';
    });

    // Export PNG
    document.getElementById('export-btn')?.addEventListener('click', () => {
        map.getCanvas().toBlob(blob => {
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = `kensington_${colourMode}_${new Date().toISOString().split('T')[0]}.png`;
            a.click();
        });
    });
}

// ---------------------------------------------------------------------------
// Scenario System
// ---------------------------------------------------------------------------

let activeScenario = null;
let scenarioMarkers = [];
let originalHeights = {};

async function loadScenario(name) {
    // Reset previous scenario
    resetScenario();

    if (name === 'baseline') {
        showScenarioPanel(null);
        return;
    }

    try {
        const resp = await fetch(`/data/scenarios/${name}.json`);
        if (!resp.ok) {
            showScenarioPanel({ name: name, description: 'Not yet designed', interventions: [], impact: {} });
            return;
        }
        const scenario = await resp.json();
        activeScenario = scenario;
        applyScenario(scenario);
        showScenarioPanel(scenario);
    } catch (e) {
        console.log('Scenario load error:', e);
    }
}

function applyScenario(scenario) {
    const source = map.getSource('buildings');
    if (!source || !source._data) return;

    const geojson = source._data;
    const interventionMap = {};
    (scenario.interventions || []).forEach(i => {
        interventionMap[i.address] = i;
    });

    // Store original heights and apply changes
    geojson.features.forEach(f => {
        const addr = f.properties.address;
        const intervention = interventionMap[addr];
        if (!intervention) return;

        // Save original
        if (!originalHeights[addr]) {
            originalHeights[addr] = {
                height: f.properties.height,
                _color: f.properties._color,
            };
        }

        // Apply intervention visual
        switch (intervention.type) {
            case 'add_floor':
                f.properties.height = (f.properties.height || 7) + 3.0;
                f.properties._color = '#4488CC'; // blue = added height
                f.properties._scenario_type = 'add_floor';
                break;
            case 'convert_ground':
                f.properties._color = '#CC8844'; // orange = commercial conversion
                f.properties._scenario_type = 'convert_ground';
                break;
            case 'green_roof':
                f.properties._color = '#338833'; // green = green roof
                f.properties._scenario_type = 'green_roof';
                break;
            case 'heritage_restore':
                f.properties._color = '#DDAA33'; // gold = heritage restoration
                f.properties._scenario_type = 'heritage_restore';
                break;
            case 'facade_renovation':
                f.properties._color = '#8888CC'; // purple = renovation
                f.properties._scenario_type = 'facade_renovation';
                break;
            case 'demolish':
                f.properties.height = 0.1;
                f.properties._color = '#FF3333';
                f.properties._scenario_type = 'demolish';
                break;
        }
    });

    source.setData(geojson);

    // Add new builds as markers
    (scenario.interventions || []).filter(i => i.type === 'new_build' && i.lon && i.lat).forEach(i => {
        const el = document.createElement('div');
        el.style.cssText = 'width:14px;height:14px;background:#44AAFF;border:2px solid #fff;border-radius:50%;cursor:pointer;';
        el.title = i.params?.building_name || i.address;

        const marker = new maplibregl.Marker({ element: el })
            .setLngLat([i.lon, i.lat])
            .setPopup(new maplibregl.Popup({ offset: 10 }).setHTML(
                `<strong>${i.params?.building_name || 'New Build'}</strong><br>
                 ${i.params?.floors || 2} floors, ${i.params?.total_height_m || 7}m<br>
                 ${i.params?.facade_material || 'brick'}`
            ))
            .addTo(map);
        scenarioMarkers.push(marker);
    });
}

function resetScenario() {
    const source = map.getSource('buildings');
    if (source && source._data) {
        const geojson = source._data;
        geojson.features.forEach(f => {
            const addr = f.properties.address;
            if (originalHeights[addr]) {
                f.properties.height = originalHeights[addr].height;
                f.properties._color = originalHeights[addr]._color;
                delete f.properties._scenario_type;
            }
        });
        source.setData(geojson);
    }
    originalHeights = {};

    // Remove new build markers
    scenarioMarkers.forEach(m => m.remove());
    scenarioMarkers = [];
    activeScenario = null;
}

function showScenarioPanel(scenario) {
    const body = document.getElementById('panel-body');
    if (!scenario) {
        body.innerHTML = '<p style="color:var(--dim);font-size:13px;">Baseline view. Select a scenario to see proposed changes.</p>';
        return;
    }

    const impact = scenario.impact || {};
    const interventions = scenario.interventions || [];

    // Count by type
    const typeCounts = {};
    interventions.forEach(i => { typeCounts[i.type] = (typeCounts[i.type] || 0) + 1; });

    const typeLabels = {
        add_floor: 'Added floors', convert_ground: 'Commercial conversions',
        green_roof: 'Green roofs', heritage_restore: 'Heritage restorations',
        facade_renovation: 'Facade renovations', new_build: 'New buildings',
        demolish: 'Demolitions',
    };
    const typeColors = {
        add_floor: '#4488CC', convert_ground: '#CC8844', green_roof: '#338833',
        heritage_restore: '#DDAA33', facade_renovation: '#8888CC', new_build: '#44AAFF',
        demolish: '#FF3333',
    };

    body.innerHTML = `
        <div class="building-header">
            <div class="address">${scenario.name || scenario.scenario_id}</div>
            <div style="font-size:12px;color:var(--dim);margin-top:4px;">${scenario.description || ''}</div>
        </div>

        <div class="section-title">Impact Summary</div>
        <table class="prop-table">
            ${impact.dwelling_units_added ? `<tr><td>Dwelling units</td><td>+${impact.dwelling_units_added}</td></tr>` : ''}
            ${impact.fsi_change ? `<tr><td>FSI change</td><td>${impact.fsi_change}</td></tr>` : ''}
            ${impact.height_changes ? `<tr><td>Height changes</td><td>${impact.height_changes} buildings</td></tr>` : ''}
            ${impact.new_builds ? `<tr><td>New builds</td><td>${impact.new_builds}</td></tr>` : ''}
            ${impact.green_roofs ? `<tr><td>Green roofs</td><td>${impact.green_roofs}</td></tr>` : ''}
            ${impact.heritage_restorations ? `<tr><td>Heritage restored</td><td>${impact.heritage_restorations}</td></tr>` : ''}
            ${impact.commercial_conversions ? `<tr><td>Commercial conv.</td><td>${impact.commercial_conversions}</td></tr>` : ''}
        </table>

        <div class="section-title">Interventions (${interventions.length})</div>
        <div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:8px;">
            ${Object.entries(typeCounts).map(([type, count]) => `
                <div style="display:flex;align-items:center;gap:4px;padding:2px 8px;background:var(--card);border-radius:4px;font-size:10px;">
                    <div style="width:8px;height:8px;border-radius:2px;background:${typeColors[type] || '#666'}"></div>
                    ${typeLabels[type] || type}: ${count}
                </div>
            `).join('')}
        </div>

        <div style="max-height:300px;overflow-y:auto;">
            ${interventions.map(i => `
                <div class="building-list-item" ${i.lon && i.lat ? `onclick="flyTo(${i.lon},${i.lat},'${(i.address||'').replace(/'/g,"\\'")}')"` : ''}>
                    <div style="width:8px;height:8px;border-radius:2px;background:${typeColors[i.type] || '#666'};flex-shrink:0;"></div>
                    <span class="addr" style="margin-left:6px">${i.address}</span>
                    <span style="font-size:10px;color:var(--dim)">${typeLabels[i.type] || i.type}</span>
                </div>
            `).join('')}
        </div>

        ${scenario.principles ? `
        <div class="section-title">Design Principles</div>
        <ul style="font-size:11px;color:var(--dim);padding-left:16px;line-height:1.6;">
            ${(scenario.principles || []).map(p => `<li>${p}</li>`).join('')}
        </ul>
        ` : ''}
    `;
}

init();
