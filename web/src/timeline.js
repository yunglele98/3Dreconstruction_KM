/**
 * Timeline scrubber — filter buildings by construction era, animate through time
 */

export class Timeline {
    constructor(viewer, buildingData) {
        this.viewer = viewer;
        this.buildingData = buildingData;
        this.currentEra = null;
        this.element = document.getElementById('timeline');
        this.setup();
    }

    setup() {
        if (!this.element) return;

        this.element.innerHTML = `
            <label>Timeline</label>
            <input type="range" id="timeline-slider" min="1858" max="2036" value="2026" step="1"
                   style="width:200px;margin:6px 0;">
            <div class="era-display" id="timeline-year">2026</div>
            <div style="font-size:10px;opacity:0.4;margin-top:2px">
                <span>1858</span>
                <span style="float:right">2036</span>
            </div>
        `;

        const slider = document.getElementById('timeline-slider');
        const yearDisplay = document.getElementById('timeline-year');

        slider.addEventListener('input', () => {
            const year = parseInt(slider.value);
            yearDisplay.textContent = this.getEraLabel(year);
            this.filterByYear(year);
        });
    }

    getEraLabel(year) {
        if (year < 1889) return `${year} (Georgian / Early Victorian)`;
        if (year < 1904) return `${year} (Victorian)`;
        if (year < 1914) return `${year} (Edwardian)`;
        if (year < 1931) return `${year} (Late / Inter-war)`;
        if (year <= 2026) return `${year} (Present)`;
        return `${year} (Scenario Future)`;
    }

    filterByYear(targetYear) {
        if (!this.viewer) return;

        this.viewer.entities.values.forEach(entity => {
            if (!entity.properties) return;

            const hcd = entity.properties.hcd_data;
            if (!hcd) {
                entity.show = targetYear >= 2026;
                return;
            }

            const dateStr = hcd.getValue ? hcd.getValue().construction_date : '';
            const builtYear = this.parseYear(dateStr);

            if (builtYear === null) {
                entity.show = true;
                return;
            }

            // Show building if it was built by target year
            entity.show = builtYear <= targetYear;

            // Fade newer buildings
            if (entity.polygon && entity.polygon.material) {
                const age = targetYear - builtYear;
                if (age < 0) {
                    entity.show = false;
                } else if (age < 10) {
                    // Recently built — highlight
                    entity.polygon.material = Cesium.Color.fromCssColorString('#5588DD').withAlpha(0.9);
                }
            }
        });
    }

    parseYear(dateStr) {
        if (!dateStr) return null;
        // Handle ranges like "1889-1903", "Pre-1889", "1904-1913"
        const match = dateStr.match(/(\d{4})/);
        if (match) return parseInt(match[1]);
        if (dateStr.toLowerCase().includes('pre-1889')) return 1880;
        return null;
    }

    show() { if (this.element) this.element.style.display = 'block'; }
    hide() { if (this.element) this.element.style.display = 'none'; }
    toggle() {
        if (this.element) {
            this.element.style.display = this.element.style.display === 'none' ? 'block' : 'none';
        }
    }
}


/**
 * Street-level walk mode — first-person camera at pedestrian height
 */
export class StreetWalk {
    constructor(viewer) {
        this.viewer = viewer;
        this.active = false;
        this.walkHeight = 1.7; // metres
        this.moveSpeed = 0.00001; // degrees per frame
    }

    enter(lon, lat) {
        if (!this.viewer) return;
        this.active = true;

        this.viewer.camera.flyTo({
            destination: Cesium.Cartesian3.fromDegrees(lon, lat, this.walkHeight),
            orientation: {
                heading: Cesium.Math.toRadians(0),
                pitch: Cesium.Math.toRadians(0),
                roll: 0,
            },
            duration: 1.0,
        });

        // Add walk controls hint
        const hint = document.createElement('div');
        hint.id = 'walk-hint';
        hint.style.cssText = `
            position: fixed; bottom: 100px; left: 50%; transform: translateX(-50%);
            background: rgba(0,0,0,0.8); padding: 8px 16px; border-radius: 8px;
            font-size: 12px; color: white; z-index: 100;
        `;
        hint.textContent = 'WASD to move, mouse to look, Q to exit street view';
        document.body.appendChild(hint);

        // WASD movement
        this.keyHandler = (e) => {
            if (!this.active) return;
            const cam = this.viewer.camera;
            const heading = cam.heading;

            switch (e.key) {
                case 'w':
                    cam.moveForward(2);
                    break;
                case 's':
                    cam.moveBackward(2);
                    break;
                case 'a':
                    cam.moveLeft(2);
                    break;
                case 'd':
                    cam.moveRight(2);
                    break;
                case 'q':
                    this.exit();
                    break;
            }
        };
        document.addEventListener('keydown', this.keyHandler);
    }

    exit() {
        this.active = false;
        const hint = document.getElementById('walk-hint');
        if (hint) hint.remove();
        if (this.keyHandler) {
            document.removeEventListener('keydown', this.keyHandler);
        }

        // Fly back to overview
        this.viewer.camera.flyTo({
            destination: Cesium.Cartesian3.fromDegrees(-79.4015, 43.6545, 300),
            orientation: {
                heading: Cesium.Math.toRadians(30),
                pitch: Cesium.Math.toRadians(-35),
                roll: 0,
            },
            duration: 1.5,
        });
    }
}
