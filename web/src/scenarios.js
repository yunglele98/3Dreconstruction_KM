/**
 * Scenario comparison — A/B split view, diff highlighting, impact metrics
 */

export class ScenarioManager {
    constructor(viewer, buildingData) {
        this.viewer = viewer;
        this.buildingData = buildingData;
        this.baseline = buildingData;
        this.currentScenario = null;
        this.compareMode = false;
    }

    async loadScenario(name) {
        if (name === 'baseline') {
            this.currentScenario = null;
            this.resetBuildings();
            return { name: 'baseline', changes: 0 };
        }

        try {
            const resp = await fetch(`/data/scenarios/${name}.json`);
            if (!resp.ok) return null;
            const scenario = await resp.json();
            this.currentScenario = scenario;
            this.applyScenario(scenario);
            return scenario;
        } catch (e) {
            console.log(`Scenario ${name} not available`);
            return null;
        }
    }

    applyScenario(scenario) {
        const interventions = scenario.interventions || [];
        let changed = 0;

        interventions.forEach(intervention => {
            const entity = this.findEntity(intervention.address);
            if (!entity) return;

            switch (intervention.type) {
                case 'add_floor':
                    this.addFloor(entity, intervention.params_override);
                    changed++;
                    break;
                case 'convert_ground':
                    this.convertGround(entity, intervention.params_override);
                    changed++;
                    break;
                case 'demolish':
                    entity.show = false;
                    changed++;
                    break;
                case 'new_build':
                    this.addNewBuilding(intervention);
                    changed++;
                    break;
                case 'green_roof':
                    this.addGreenRoof(entity);
                    changed++;
                    break;
                case 'facade_renovation':
                    this.renovateFacade(entity, intervention.params_override);
                    changed++;
                    break;
            }
        });

        return changed;
    }

    addFloor(entity, params) {
        if (!entity.polygon) return;
        const currentHeight = entity.polygon.extrudedHeight.getValue();
        const newHeight = currentHeight + (params.floor_height || 3.0);
        entity.polygon.extrudedHeight = newHeight;
        // Highlight modified building
        entity.polygon.material = Cesium.Color.fromCssColorString('#4488CC').withAlpha(0.8);
    }

    convertGround(entity, params) {
        // Visual indicator: change ground floor color
        entity.polygon.material = Cesium.Color.fromCssColorString('#CC8844').withAlpha(0.8);
    }

    addGreenRoof(entity) {
        entity.polygon.material = Cesium.Color.fromCssColorString('#448844').withAlpha(0.8);
    }

    renovateFacade(entity, params) {
        if (params && params.facade_colour_hex) {
            entity.polygon.material = Cesium.Color.fromCssColorString(params.facade_colour_hex).withAlpha(0.85);
        }
    }

    addNewBuilding(intervention) {
        if (!intervention.lon || !intervention.lat) return;
        const p = intervention.params || {};

        this.viewer.entities.add({
            position: Cesium.Cartesian3.fromDegrees(intervention.lon, intervention.lat, 0),
            polygon: {
                hierarchy: Cesium.Cartesian3.fromDegreesArray([
                    intervention.lon - 0.00003, intervention.lat - 0.00006,
                    intervention.lon + 0.00003, intervention.lat - 0.00006,
                    intervention.lon + 0.00003, intervention.lat + 0.00006,
                    intervention.lon - 0.00003, intervention.lat + 0.00006,
                ]),
                height: 0,
                extrudedHeight: p.total_height_m || 8,
                material: Cesium.Color.fromCssColorString('#6688BB').withAlpha(0.7),
                outline: true,
                outlineColor: Cesium.Color.WHITE,
            },
            properties: { ...p, is_new: true, scenario: intervention.scenario },
        });
    }

    findEntity(address) {
        const entities = this.viewer.entities.values;
        for (let i = 0; i < entities.length; i++) {
            const props = entities[i].properties;
            if (props) {
                const name = props.building_name ? props.building_name.getValue() : '';
                const addr = props.address ? props.address.getValue() : '';
                if (name === address || addr === address) return entities[i];
            }
        }
        return null;
    }

    resetBuildings() {
        // Remove scenario-added entities and reset modified ones
        const toRemove = [];
        this.viewer.entities.values.forEach(entity => {
            if (entity.properties && entity.properties.is_new) {
                toRemove.push(entity);
            }
        });
        toRemove.forEach(e => this.viewer.entities.remove(e));

        // Reset colors and heights to baseline
        // Full implementation would store original values
    }

    getImpactMetrics(scenario) {
        if (!scenario || !scenario.interventions) return {};

        let addedFloors = 0;
        let demolitions = 0;
        let newBuilds = 0;
        let greenRoofs = 0;
        let conversions = 0;

        scenario.interventions.forEach(i => {
            switch (i.type) {
                case 'add_floor': addedFloors++; break;
                case 'demolish': demolitions++; break;
                case 'new_build': newBuilds++; break;
                case 'green_roof': greenRoofs++; break;
                case 'convert_ground': conversions++; break;
            }
        });

        return {
            total_changes: scenario.interventions.length,
            added_floors: addedFloors,
            demolitions: demolitions,
            new_builds: newBuilds,
            green_roofs: greenRoofs,
            conversions: conversions,
            density_change: `+${addedFloors * 2 + newBuilds * 3} units`,
        };
    }
}


/**
 * A/B Split comparison view
 */
export class SplitView {
    constructor(container) {
        this.container = container;
        this.splitPosition = 0.5;
        this.active = false;
    }

    activate(leftLabel, rightLabel) {
        this.active = true;

        // Create split overlay
        const overlay = document.createElement('div');
        overlay.id = 'split-overlay';
        overlay.style.cssText = `
            position: fixed; top: 56px; left: 0; right: 0; bottom: 0;
            pointer-events: none; z-index: 50;
        `;

        // Split line
        const line = document.createElement('div');
        line.style.cssText = `
            position: absolute; top: 0; bottom: 0; width: 3px;
            background: white; left: 50%; transform: translateX(-50%);
            box-shadow: 0 0 10px rgba(0,0,0,0.5); pointer-events: auto; cursor: col-resize;
        `;

        // Labels
        const leftLbl = document.createElement('div');
        leftLbl.textContent = leftLabel;
        leftLbl.style.cssText = `
            position: absolute; top: 10px; left: 20px;
            background: rgba(0,0,0,0.7); padding: 4px 12px; border-radius: 4px;
            font-size: 13px; color: white;
        `;

        const rightLbl = document.createElement('div');
        rightLbl.textContent = rightLabel;
        rightLbl.style.cssText = `
            position: absolute; top: 10px; right: 400px;
            background: rgba(0,0,0,0.7); padding: 4px 12px; border-radius: 4px;
            font-size: 13px; color: white;
        `;

        overlay.appendChild(line);
        overlay.appendChild(leftLbl);
        overlay.appendChild(rightLbl);
        document.body.appendChild(overlay);

        // Drag handler
        line.addEventListener('mousedown', (e) => {
            const onMove = (ev) => {
                this.splitPosition = ev.clientX / window.innerWidth;
                line.style.left = `${this.splitPosition * 100}%`;
            };
            const onUp = () => {
                document.removeEventListener('mousemove', onMove);
                document.removeEventListener('mouseup', onUp);
            };
            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
        });
    }

    deactivate() {
        this.active = false;
        const overlay = document.getElementById('split-overlay');
        if (overlay) overlay.remove();
    }
}
