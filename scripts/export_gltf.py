"""Export the demo scene to GLTF/GLB for web viewing.

Creates a web-ready 3D model that can be loaded in Three.js, Babylon.js,
or any GLTF viewer. Optimizes materials and geometry for web performance.

Run: blender --background <scene.blend> --python scripts/export_gltf.py
"""

import bpy
import os
from pathlib import Path

SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__))).parent
OUT_DIR = SCRIPT_DIR / "outputs" / "demos" / "web"
OUT_DIR.mkdir(exist_ok=True)


def optimize_scene():
    """Optimize scene for web export."""
    print("Optimizing scene for web export...")

    # 1. Join small objects by collection to reduce draw calls
    collections_to_join = [
        "RoadMarkings", "SidewalkJoints", "Curbs", "StreetGutters",
        "Puddles", "Litter", "Weeds", "RoadPatches", "UtilityCovers"
    ]
    for col_name in collections_to_join:
        col = bpy.data.collections.get(col_name)
        if not col or len(col.objects) < 2:
            continue
        # Select all objects in collection
        bpy.ops.object.select_all(action='DESELECT')
        first = None
        for obj in col.objects:
            if obj.type == 'MESH':
                obj.select_set(True)
                if first is None:
                    first = obj
        if first:
            bpy.context.view_layer.objects.active = first
            try:
                bpy.ops.object.join()
                print(f"  Joined {col_name}")
            except:
                pass

    # 2. Apply all modifiers (solidify on lot boundaries etc.)
    for obj in bpy.data.objects:
        if obj.type != 'MESH':
            continue
        for mod in obj.modifiers:
            try:
                bpy.context.view_layer.objects.active = obj
                bpy.ops.object.modifier_apply(modifier=mod.name)
            except:
                pass

    # 3. Remove unused materials
    for mat in list(bpy.data.materials):
        if mat.users == 0:
            bpy.data.materials.remove(mat)

    print(f"  Objects: {len(bpy.data.objects)}")
    print(f"  Materials: {len(bpy.data.materials)}")


def export_glb(filename="bellevue_demo"):
    """Export scene as GLB (binary GLTF)."""
    filepath = str(OUT_DIR / f"{filename}.glb")

    bpy.ops.export_scene.gltf(
        filepath=filepath,
        export_format='GLB',
        use_selection=False,
        export_apply=True,
        export_materials='EXPORT',
        export_colors=True,
        export_cameras=True,
        export_lights=True,
        export_yup=True,  # Y-up for web
    )

    size_mb = os.path.getsize(filepath) / (1024 * 1024)
    print(f"Exported: {filepath} ({size_mb:.1f} MB)")
    return filepath


def export_gltf_separate(filename="bellevue_demo"):
    """Export scene as GLTF with separate .bin and textures."""
    filepath = str(OUT_DIR / f"{filename}.gltf")

    bpy.ops.export_scene.gltf(
        filepath=filepath,
        export_format='GLTF_SEPARATE',
        use_selection=False,
        export_apply=True,
        export_materials='EXPORT',
        export_colors=True,
        export_cameras=True,
        export_lights=True,
        export_yup=True,
    )

    print(f"Exported: {filepath}")
    return filepath


def create_viewer_html(glb_filename="bellevue_demo.glb"):
    """Create a simple Three.js HTML viewer."""
    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Kensington Market 3D — Bellevue Ave Demo</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * {{ margin: 0; padding: 0; }}
        body {{ overflow: hidden; background: #1a1a2e; }}
        canvas {{ display: block; }}
        #info {{
            position: absolute; top: 10px; left: 10px;
            color: #fff; font-family: 'Segoe UI', sans-serif;
            font-size: 14px; background: rgba(0,0,0,0.7);
            padding: 12px 16px; border-radius: 8px;
            max-width: 300px;
        }}
        #info h2 {{ margin-bottom: 8px; font-size: 16px; }}
        #info p {{ opacity: 0.8; line-height: 1.4; }}
        #loading {{
            position: absolute; top: 50%; left: 50%;
            transform: translate(-50%, -50%);
            color: #fff; font-family: 'Segoe UI', sans-serif;
            font-size: 18px; text-align: center;
        }}
        .spinner {{
            width: 40px; height: 40px; margin: 0 auto 16px;
            border: 3px solid rgba(255,255,255,0.2);
            border-top-color: #fff; border-radius: 50%;
            animation: spin 1s linear infinite;
        }}
        @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
    </style>
</head>
<body>
    <div id="loading">
        <div class="spinner"></div>
        Loading 3D scene...
    </div>
    <div id="info" style="display:none">
        <h2>Kensington Market 3D</h2>
        <p>Bellevue Ave block — 164 buildings with architectural detail
        from PostGIS + field photo analysis.</p>
        <p style="margin-top:8px; font-size:12px; opacity:0.6;">
            Drag to rotate · Scroll to zoom · Right-drag to pan
        </p>
    </div>

    <script type="importmap">
    {{
        "imports": {{
            "three": "https://cdn.jsdelivr.net/npm/three@0.170.0/build/three.module.js",
            "three/addons/": "https://cdn.jsdelivr.net/npm/three@0.170.0/examples/jsm/"
        }}
    }}
    </script>

    <script type="module">
        import * as THREE from 'three';
        import {{ OrbitControls }} from 'three/addons/controls/OrbitControls.js';
        import {{ GLTFLoader }} from 'three/addons/loaders/GLTFLoader.js';

        const scene = new THREE.Scene();
        scene.background = new THREE.Color(0x87CEEB);
        scene.fog = new THREE.Fog(0x87CEEB, 200, 500);

        const camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.1, 1000);
        camera.position.set(100, 80, 100);

        const renderer = new THREE.WebGLRenderer({{ antialias: true }});
        renderer.setSize(window.innerWidth, window.innerHeight);
        renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        renderer.shadowMap.enabled = true;
        renderer.shadowMap.type = THREE.PCFSoftShadowMap;
        renderer.toneMapping = THREE.ACESFilmicToneMapping;
        renderer.toneMappingExposure = 1.2;
        document.body.appendChild(renderer.domElement);

        // Lighting
        const ambientLight = new THREE.AmbientLight(0xffffff, 0.4);
        scene.add(ambientLight);

        const sunLight = new THREE.DirectionalLight(0xfff5e6, 1.5);
        sunLight.position.set(50, 80, 30);
        sunLight.castShadow = true;
        sunLight.shadow.mapSize.width = 4096;
        sunLight.shadow.mapSize.height = 4096;
        sunLight.shadow.camera.near = 0.1;
        sunLight.shadow.camera.far = 300;
        sunLight.shadow.camera.left = -150;
        sunLight.shadow.camera.right = 150;
        sunLight.shadow.camera.top = 150;
        sunLight.shadow.camera.bottom = -150;
        scene.add(sunLight);

        const fillLight = new THREE.DirectionalLight(0x8090b0, 0.5);
        fillLight.position.set(-40, 40, -20);
        scene.add(fillLight);

        // Controls
        const controls = new OrbitControls(camera, renderer.domElement);
        controls.enableDamping = true;
        controls.dampingFactor = 0.05;
        controls.maxPolarAngle = Math.PI / 2.1;
        controls.minDistance = 10;
        controls.maxDistance = 400;

        // Load model
        const loader = new GLTFLoader();
        loader.load('{glb_filename}',
            (gltf) => {{
                const model = gltf.scene;
                // Center model
                const box = new THREE.Box3().setFromObject(model);
                const center = box.getCenter(new THREE.Vector3());
                model.position.sub(center);
                model.traverse((child) => {{
                    if (child.isMesh) {{
                        child.castShadow = true;
                        child.receiveShadow = true;
                    }}
                }});
                scene.add(model);
                controls.target.set(0, 5, 0);
                controls.update();

                document.getElementById('loading').style.display = 'none';
                document.getElementById('info').style.display = 'block';
            }},
            (progress) => {{
                const pct = (progress.loaded / progress.total * 100).toFixed(0);
                document.getElementById('loading').innerHTML =
                    '<div class="spinner"></div>Loading... ' + pct + '%';
            }},
            (error) => {{
                document.getElementById('loading').innerHTML =
                    'Error loading model: ' + error.message;
            }}
        );

        // Resize
        window.addEventListener('resize', () => {{
            camera.aspect = window.innerWidth / window.innerHeight;
            camera.updateProjectionMatrix();
            renderer.setSize(window.innerWidth, window.innerHeight);
        }});

        // Animate
        function animate() {{
            requestAnimationFrame(animate);
            controls.update();
            renderer.render(scene, camera);
        }}
        animate();
    </script>
</body>
</html>"""

    html_path = OUT_DIR / "viewer.html"
    with open(html_path, "w") as f:
        f.write(html)
    print(f"Viewer: {html_path}")


def main():
    print("=== GLTF/GLB Web Export ===")
    optimize_scene()
    glb_path = export_glb()
    create_viewer_html()
    print("\nDone. To view:")
    print(f"  1. Open {OUT_DIR / 'viewer.html'} in a browser")
    print(f"  2. Or upload {glb_path} to https://gltf-viewer.donmccurdy.com/")


main()
