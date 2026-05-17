// --- 1. Setup --------------------------------------------------------------

const container = document.getElementById('canvas-container');

// Scene
const scene = new THREE.Scene();
scene.background = new THREE.Color('#0a0a0a');

// Camera (Orthographic)
const VIEW_SIZE = 10;
const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 1000);

const spherical = {
    radius: 30,
    theta: Math.PI / 4,
    phi: Math.PI / 4,
};

const target = new THREE.Vector3();

// Renderer
const renderer = new THREE.WebGLRenderer({ antialias: true });
container.appendChild(renderer.domElement);

// --- 2. Lighting & Helpers -------------------------------------------------

scene.add(new THREE.AmbientLight(0xffffff, 0.6));

const dirLight = new THREE.DirectionalLight(0xffffff, 0.4);
dirLight.position.set(10, 20, 0);
scene.add(dirLight);

scene.add(new THREE.GridHelper(20, 20, 0x444444, 0x222222));

// Interaction plane
const interactionPlane = new THREE.Mesh(
    new THREE.PlaneGeometry(20, 20).rotateX(-Math.PI / 2),
    new THREE.MeshBasicMaterial({ visible: false })
);
scene.add(interactionPlane);

// --- 3. Tools & Objects ----------------------------------------------------

let currentTool = 'wall';
let mapObjects = [];

// Geometries & Materials
const wallGeo = new THREE.BoxGeometry(1, 1, 1);
const wallMat = new THREE.MeshLambertMaterial({ color: 0x9ca3af });

const targetGeo = new THREE.CylinderGeometry(0.3, 0.3, 1, 16);
const targetMat = new THREE.MeshLambertMaterial({ color: 0xf59e0b });

// E-Puck visual (Green cylinder to represent the robot)
const epuckGeo = new THREE.CylinderGeometry(0.4, 0.4, 0.5, 16);
const epuckMat = new THREE.MeshLambertMaterial({ color: 0x10b981 });
const droneGeo = new THREE.BoxGeometry(0.7, 0.3, 0.7);
const droneMat = new THREE.MeshLambertMaterial({
    color: 0x3b82f6
});

let epuckCounter = 0;
let currentDrone = null;

// --- 4. Camera Controls ----------------------------------------------------

let isOrbiting = false;
let isPanning = false;
let isDrawing = false;

const mouse = new THREE.Vector2();
const mouseStart = { x: 0, y: 0 };

function updateCamera() {
    camera.position.set(
        spherical.radius * Math.sin(spherical.phi) * Math.cos(spherical.theta),
        spherical.radius * Math.cos(spherical.phi),
        spherical.radius * Math.sin(spherical.phi) * Math.sin(spherical.theta)
    );

    camera.lookAt(target);
}

function resize() {
    const aspect = container.clientWidth / container.clientHeight;

    camera.left = -VIEW_SIZE * aspect;
    camera.right = VIEW_SIZE * aspect;
    camera.top = VIEW_SIZE;
    camera.bottom = -VIEW_SIZE;

    camera.updateProjectionMatrix();
    renderer.setSize(container.clientWidth, container.clientHeight);
}

resize();
updateCamera();
window.addEventListener('resize', resize);

// --- 5. Interaction (Raycasting) ------------------------------------------

const raycaster = new THREE.Raycaster();

function getMouseNDC(event) {
    const rect = container.getBoundingClientRect();

    mouse.x = ((event.clientX - rect.left) / container.clientWidth) * 2 - 1;
    mouse.y = -((event.clientY - rect.top) / container.clientHeight) * 2 + 1;
}

function handleInteraction(event) {
    getMouseNDC(event);

    raycaster.setFromCamera(mouse, camera);

    const intersects = raycaster.intersectObjects([
        ...mapObjects,
        interactionPlane,
    ]);

    if (!intersects.length) return;

    const hit = intersects[0];

    // Erase
    if (currentTool === 'erase') {
        if (hit.object !== interactionPlane) {
            if (hit.object.userData.type === 'drone') {
                currentDrone = null;
            }
            scene.remove(hit.object);
            mapObjects = mapObjects.filter(
                obj => obj !== hit.object
            );
        }
        return;
    }

    // Placement
    if (hit.object === interactionPlane) {
        const x = Math.round(hit.point.x);
        const z = Math.round(hit.point.z);

        const exists = mapObjects.some(
            obj => obj.position.x === x && obj.position.z === z
        );
        if (exists) return;

        if (hit.object === interactionPlane) {
            const x = Math.round(hit.point.x);
            const z = Math.round(hit.point.z);

            const exists = mapObjects.some(
                obj => obj.position.x === x && obj.position.z === z
            );

            // Prevent stacking (except epuck replacement logic)
            if (exists && currentTool !== 'epuck') return;

            let mesh = null;

            if (currentTool === 'wall') {
                mesh = new THREE.Mesh(wallGeo, wallMat);
                mesh.position.set(x, 0.5, z);
                mesh.userData = { type: 'wall' };
            }
            else if (currentTool === 'target') {
                mesh = new THREE.Mesh(targetGeo, targetMat);
                mesh.position.set(x, 0.5, z);
                mesh.userData = { type: 'target' };
            }
            else if (currentTool === 'epuck') {

                epuckCounter++;

                mesh = new THREE.Mesh(
                    epuckGeo,
                    epuckMat
                );

                mesh.position.set(x, 0.25, z);

                mesh.userData = {
                    type: 'epuck',
                    id: `epuck_${epuckCounter}`
                };
            }

            else if (currentTool === 'drone') {

                // Highlander Rule
                if (currentDrone) {

                    scene.remove(currentDrone);

                    mapObjects = mapObjects.filter(
                        obj => obj !== currentDrone
                    );
                }

                mesh = new THREE.Mesh(
                    droneGeo,
                    droneMat
                );

                mesh.position.set(x, 2.0, z);

                mesh.userData = {
                    type: 'drone',
                    id: 'drone_1'
                };

                currentDrone = mesh;
            }

            if (mesh) {
                scene.add(mesh);
                mapObjects.push(mesh);
            }
        }
    }
}

// --- 6. Mouse Events -------------------------------------------------------

container.addEventListener('contextmenu', e => e.preventDefault());

container.addEventListener('mousedown', (e) => {
    mouseStart.x = e.clientX;
    mouseStart.y = e.clientY;

    if (e.button === 0) {
        // LEFT CLICK → DRAW ONLY
        isDrawing = true;
        handleInteraction(e);
    }

    if (e.button === 2) {
        // RIGHT CLICK → ORBIT
        isOrbiting = true;
    }

    if (e.button === 1) {
        // MIDDLE CLICK → PAN
        isPanning = true;
    }
});

container.addEventListener('mousemove', (e) => {
    const dx = (e.clientX - mouseStart.x) * 0.005;
    const dy = (e.clientY - mouseStart.y) * 0.005;

    if (isOrbiting) {
        spherical.theta -= dx;
        spherical.phi = Math.max(0.1, Math.min(Math.PI - 0.1, spherical.phi - dy));
        updateCamera();
    }
    else if (isPanning) {
        target.x -= dx * 10;
        target.z += dy * 10;
        updateCamera();
    }
    else if (isDrawing) {
        handleInteraction(e);
    }

    mouseStart.x = e.clientX;
    mouseStart.y = e.clientY;
});

container.addEventListener('mouseup', () => {
    isOrbiting = false;
    isPanning = false;
    isDrawing = false;
});

container.addEventListener('mouseleave', () => {
    isOrbiting = false;
    isPanning = false;
    isDrawing = false;
});

container.addEventListener('wheel', (e) => {
    e.preventDefault();

    const zoomSpeed = 0.001;
    camera.zoom *= (1 - e.deltaY * zoomSpeed);

    // clamp zoom
    camera.zoom = Math.min(5, Math.max(0.2, camera.zoom));

    camera.updateProjectionMatrix();
}, { passive: false });

// --- 7. UI -----------------------------------------------------------------

document.querySelectorAll('.tool-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
        document.querySelectorAll('.tool-btn')
            .forEach(b => b.classList.remove('active'));

        e.currentTarget.classList.add('active');
        currentTool = e.currentTarget.dataset.tool;
    });
});

document.getElementById('clear-map-btn').addEventListener('click', () => {
    mapObjects.forEach(obj => scene.remove(obj));
    mapObjects = [];
    currentDrone = null;
    epuckCounter = 0;
});

// --- 8. Render Loop --------------------------------------------------------

function animate() {
    requestAnimationFrame(animate);
    renderer.render(scene, camera);
}

animate();

// --- 9. Data Export API ----------------------------------------------------
// Expose a function to grab the map configuration for the Flask backend
window.exportMapData = function () {
    const mapData = { walls: [], targets: [], epucks: [], drone: null };

    mapObjects.forEach(obj => {
        if (obj.userData.type === 'wall') {
            mapData.walls.push({ x: obj.position.x, z: obj.position.z });
        }
        else if (obj.userData.type === 'target') {
            mapData.targets.push({ x: obj.position.x, z: obj.position.z });
        }
        else if (obj.userData.type === 'epuck') {
            mapData.epucks.push({ id: obj.userData.id, x: obj.position.x, z: obj.position.z });
        }

        else if (obj.userData.type === 'drone') {
            mapData.drone = { id: obj.userData.id, x: obj.position.x, z: obj.position.z };
        }
    });

    // Safety fallback
    if (mapData.epucks.length === 0) {
        mapData.epucks.push({ id: 'epuck_1', x: 0, z: 0 });
    }

    return mapData;
};


// --- 10. VIEWPORT SWAP LOGIC ----------------------------------------------
// const socket = io("http://localhost:5000");
socket.on("connect", () => {
    console.log("CONNECTED TO SERVER");
});

if (typeof socket !== 'undefined') {
    socket.on('simulation_ready', (data) => {
        console.log("SIMULATION READY RECEIVED", data);
        const threeCanvas = document.getElementById('canvas-container');
        const webotsIframe = document.getElementById('webots-stream');

        webotsIframe.src = data.url;
        console.log(data.url, 'test');


        threeCanvas.style.display = 'none';
        webotsIframe.style.display = 'block';
        webotsIframe.classList.remove('hidden');


        // threeCanvas.classList.add('hidden');

        // webotsIframe.classList.remove('z-0');
        // webotsIframe.classList.add('z-20');
        setTimeout(() => {
            if (!webotsIframe.contentWindow) {
                console.error('Webots stream failed to load');
                console.log(data.url);
            }
        }, 5000);
    });
}