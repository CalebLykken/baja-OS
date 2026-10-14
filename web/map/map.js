// The Baja OS map: MapLibre GL JS drawing the offline Protomaps extract that
// backend/maps.py serves from /data.
//
// Two looks after Apple Maps: a light one by day and a dark one at night
// (QML picks by the sun, or Settings forces one). Labels are drawn larger
// than stock to read from the driver's seat, and while following the truck
// the map drops what doesn't help driving (shops, buildings, footpaths,
// one-way arrows). Traffic lights and stop signs show only on a route.
//
// The truck is a 3D model of the Baja drawn by three.js in the map's own
// frame; it rolls on smoothly between GPS fixes and leans into turns.
// Following tilts the map heading-up with the truck low on screen and
// clear of the dashboard's panels (setInsets), the camera turning a beat
// after the truck. QML drives it all through `window.baja` and listens for
// console messages that start with "baja:".

import * as maplibregl from "./vendor/maplibre-gl.mjs";
import { layers, namedFlavor } from "./vendor/basemaps.mjs";
import * as THREE from "three";
import { GLTFLoader } from "./vendor/three/loaders/GLTFLoader.js";

const started = performance.now();
const origin = location.origin;
const SEATTLE = [-122.3321, 47.6062];

function post(kind, data = {}) {
    console.log("baja:" + JSON.stringify({ kind, ...data }));
}

// ---- the two looks ----------------------------------------------------------------

// After Apple Maps: soft green parks, clear blue water, white streets and
// yellow freeways by day; the same in deep greys, navy and amber at night.
// The route is Apple's blue; nothing else on the map is that colour.

const NL = "#212225";                // night land
const NIGHT = {
    background: "#1a1b1d", earth: NL,
    park_a: "#1f2d24", park_b: "#20342a", wood_a: "#1f2d24", wood_b: "#20342a",
    scrub_a: "#212a24", scrub_b: "#212a24",
    water: "#162538",
    buildings: "#2c2d31",
    hospital: "#2b2326", industrial: "#242528", school: "#28262a", pedestrian: "#26272a",
    beach: "#2a2924", sand: "#2a2924", aerodrome: "#26252d", zoo: "#1f2d24", military: "#26262a",
    glacier: "#2a2b2e",
    runway: "#333439", pier: "#34353a",
    other: "#2e2f33", minor_service: "#36373c", minor_a: "#3b3c41", minor_b: "#46474d",
    link: "#7a6236", major: "#55575e", highway: "#94733a",
    minor_service_casing: NL, minor_casing: NL, link_casing: "#2a2418",
    major_casing_early: "#1a1b1d", major_casing_late: "#1a1b1d",
    highway_casing_early: "#3a2c14", highway_casing_late: "#3a2c14",
    tunnel_other: "#2a2b2e", tunnel_minor: "#2f3034", tunnel_link: "#4a3f2b", tunnel_major: "#3c3d42",
    tunnel_highway: "#5a4a2e",
    tunnel_other_casing: NL, tunnel_minor_casing: NL, tunnel_link_casing: NL, tunnel_major_casing: NL,
    tunnel_highway_casing: NL,
    bridges_other: "#2e2f33", bridges_minor: "#46474d", bridges_link: "#7a6236", bridges_major: "#55575e",
    bridges_highway: "#94733a",
    bridges_other_casing: "#151618", bridges_minor_casing: "#151618", bridges_link_casing: "#151618",
    bridges_major_casing: "#151618", bridges_highway_casing: "#151618",
    railway: "#45464b", boundaries: "#55565c",
    roads_label_minor: "#a2a3a8", roads_label_minor_halo: NL,
    roads_label_major: "#d8d8dc", roads_label_major_halo: "#1a1b1d",
    ocean_label: "#5d7a99",
    subplace_label: "#8e8e93", subplace_label_halo: "#1a1b1d",
    city_label: "#efeff2", city_label_halo: "#1a1b1d",
    state_label: "#77787d", state_label_halo: "#1a1b1d", country_label: "#8e8e93",
    address_label: "#7c7d82", address_label_halo: NL,
    pois: { blue: "#a2a3a8", green: "#a2a3a8", lapis: "#a2a3a8", pink: "#a2a3a8", red: "#a2a3a8",
            slategray: "#a2a3a8", tangerine: "#a2a3a8", turquoise: "#a2a3a8" },
    landcover: { grassland: "#212a24", barren: NL, urban_area: NL, farmland: "#212a24", glacier: NL,
                 scrub: "#212a24", forest: "#1f2d24" },
};

const DL = "#f3f0ea";                // day land
const DAY = {
    background: "#ebe7df", earth: DL,
    park_a: "#d2e9c8", park_b: "#c6e4bb", wood_a: "#d6eacc", wood_b: "#cbe6c0",
    scrub_a: "#dfeed6", scrub_b: "#dfeed6",
    water: "#a5d0f3",
    buildings: "#e3dfd7",
    hospital: "#f6e0e0", industrial: "#ebe8e3", school: "#f2eadb", pedestrian: "#efece6",
    beach: "#f6efd6", sand: "#f4eedb", aerodrome: "#e9e5ef", zoo: "#d2e9c8", military: "#ece8e4",
    glacier: "#ffffff",
    runway: "#dcd9e2", pier: "#ffffff",
    other: "#f7f5f1", minor_service: "#fbfaf8", minor_a: "#fdfcfa", minor_b: "#ffffff",
    link: "#fcd98c", major: "#ffffff", highway: "#f9c45a",
    minor_service_casing: "#dcd7ce", minor_casing: "#d6d1c7", link_casing: "#dfac52",
    major_casing_early: "#cbc5b9", major_casing_late: "#cbc5b9",
    highway_casing_early: "#d99a35", highway_casing_late: "#d99a35",
    tunnel_other: "#f1efea", tunnel_minor: "#f1efea", tunnel_link: "#f7e2b4", tunnel_major: "#f1efea",
    tunnel_highway: "#f5d79c",
    tunnel_other_casing: "#d6d1c7", tunnel_minor_casing: "#d6d1c7", tunnel_link_casing: "#e2c48c",
    tunnel_major_casing: "#d6d1c7", tunnel_highway_casing: "#e2c48c",
    bridges_other: "#ffffff", bridges_minor: "#ffffff", bridges_link: "#fcd98c", bridges_major: "#ffffff",
    bridges_highway: "#f9c45a",
    bridges_other_casing: "#bdb7ab", bridges_minor_casing: "#bdb7ab", bridges_link_casing: "#d09030",
    bridges_major_casing: "#b3ada1", bridges_highway_casing: "#c98a2a",
    railway: "#c4bfb6", boundaries: "#b5afa5",
    roads_label_minor: "#5f5f63", roads_label_minor_halo: "#ffffff",
    roads_label_major: "#3a3a3d", roads_label_major_halo: "#ffffff",
    ocean_label: "#4a7fb0",
    subplace_label: "#7c7c80", subplace_label_halo: DL,
    city_label: "#1d1d1f", city_label_halo: "#f8f6f2",
    state_label: "#8e8e93", state_label_halo: DL, country_label: "#6e6e73",
    address_label: "#86868b", address_label_halo: "#ffffff",
    pois: { blue: "#5f5f63", green: "#5f5f63", lapis: "#5f5f63", pink: "#5f5f63", red: "#5f5f63",
            slategray: "#5f5f63", tangerine: "#5f5f63", turquoise: "#5f5f63" },
    landcover: { grassland: "#dfeed6", barren: DL, urban_area: DL, farmland: "#e4efd9", glacier: "#ffffff",
                 scrub: "#dfeed6", forest: "#d6eacc" },
};

// Labels in Overpass, after the US highway-sign lettering: made for
// reading roads at a glance (glyphs from tools/make_glyphs.py).
const FONTS = { regular: "Overpass Regular", bold: "Overpass SemiBold", italic: "Overpass Italic" };

const LOOKS = {
    night: { flavor: { ...namedFlavor("dark"), ...NIGHT, ...FONTS }, sprite: "dark", page: "#1a1b1d",
             route: "#2f8cff", routeCasing: "#0a4296", pin: "#ff453a", pinEdge: "#ffffff",
             shadow: "rgba(0, 0, 0, 0.6)" },
    day: { flavor: { ...namedFlavor("light"), ...DAY, ...FONTS }, sprite: "light", page: "#ebe7df",
           route: "#1a7cf5", routeCasing: "#0b52b8", pin: "#ff3b30", pinEdge: "#ffffff",
           shadow: "rgba(0, 0, 0, 0.3)" },
};

// Stock label sizes are for a phone in the hand; these read from the seat.
const LABEL_SCALE = {
    roads_labels_major: 1.35, roads_labels_minor: 1.3, roads_shields: 1.25,
    places_locality: 1.2, places_subplace: 1.2, places_region: 1.1,
    water_label_ocean: 1.1, water_label_lakes: 1.1, water_waterway_label: 1.1,
};

// Hidden while following the truck: nothing here helps you drive.
const DRIVING_HIDDEN = [
    "pois", "address_label", "roads_oneway", "buildings",
    "roads_other", "roads_tunnels_other", "roads_tunnels_other_casing",
    "roads_bridges_other", "roads_bridges_other_casing",
    "roads_pier", "landuse_pier", "landuse_runway", "roads_runway", "roads_taxiway",
    "boundaries", "places_subplace", "water_label_lakes", "water_waterway_label", "earth_label_islands",
];

// Multiply a size, including zoom-interpolated ones (whose outputs must be
// scaled inside the interpolation, not wrapped around it).
function scaled(v, f) {
    if (typeof v === "number") return +(v * f).toFixed(2);
    if (Array.isArray(v) && /^interpolate/.test(v[0])) {
        return v.map((x, i) => (i >= 4 && i % 2 === 0 ? scaled(x, f) : x));
    }
    if (Array.isArray(v) && v[0] === "step") {
        return v.map((x, i) => (i === 2 || (i >= 4 && i % 2 === 0) ? scaled(x, f) : x));
    }
    return Array.isArray(v) ? ["*", v, f] : v;
}

function tidy(layer) {
    let l = layer;
    if (l.id === "pois") {
        // Stock POI icons come in fixed colours; keep the names only.
        const layout = { ...l.layout };
        delete layout["icon-image"];
        delete layout["text-offset"];
        delete layout["text-variable-anchor"];
        l = { ...l, layout };
    }
    const f = LABEL_SCALE[l.id];
    if (f && l.layout && l.layout["text-size"] !== undefined) {
        l = { ...l, layout: { ...l.layout, "text-size": scaled(l.layout["text-size"], f) } };
    }
    if (/^roads_labels/.test(l.id) && l.paint && l.paint["text-halo-width"] !== undefined) {
        l = { ...l, paint: { ...l.paint, "text-halo-width": scaled(l.paint["text-halo-width"], 1.5) } };
    }
    // Roads a little wider than stock, so streets read clearly.
    if (/^roads_/.test(l.id) && l.type === "line" && l.paint && l.paint["line-width"] !== undefined) {
        l = { ...l, paint: { ...l.paint, "line-width": scaled(l.paint["line-width"], 1.25) } };
    }
    if (DRIVING_HIDDEN.includes(l.id)) {
        l = { ...l, layout: { ...l.layout, visibility: following ? "none" : "visible" } };
    }
    return l;
}

function styleFor(m) {
    const look = LOOKS[m];
    return {
        version: 8,
        glyphs: `${origin}/fonts/{fontstack}/{range}.pbf`,
        sprite: `${origin}/data/sprites/v4/${look.sprite}`,
        sources: {
            protomaps: {
                type: "vector",
                url: `pmtiles://${origin}/data/basemap.pmtiles`,
                attribution: "© OpenStreetMap contributors",
            },
        },
        layers: layers("protomaps", look.flavor, { lang: "en" }).map(tidy),
    };
}

function applyPageColours(m) {
    const look = LOOKS[m], css = document.documentElement.style;
    document.body.style.background = look.page;
    css.setProperty("--pin", look.pin);
    css.setProperty("--pin-edge", look.pinEdge);
    css.setProperty("--shadow", look.shadow);
}

// ---- the map ----------------------------------------------------------------------

const query = new URLSearchParams(location.search);
let following = false;       // the camera rides with the truck
let mode = query.get("mode") === "day" ? "day" : "night";
applyPageColours(mode);

const region = await fetch(`${origin}/data/region.json`).then(r => r.json()).catch(() => null);
// Keep the camera over the extract, with a little room past its edges.
const [w, s, e, n] = region ? region.bbox : [-122.7, 47.1, -121.7, 48.1];
const pad = 0.15;

const protocol = new pmtiles.Protocol();
maplibregl.addProtocol("pmtiles", protocol.tile);

const map = new maplibregl.Map({
    container: "map",
    style: styleFor(mode),
    center: SEATTLE,
    zoom: 12.5,
    minZoom: 8,
    maxZoom: 19,
    maxPitch: 70,
    maxBounds: [[w - pad, s - pad], [e + pad, n + pad]],
    attributionControl: false,
    fadeDuration: 150,
    // Smooth edges on the 3D truck.
    canvasContextAttributes: { antialias: true },
});

map.on("load", () => post("ready", { ms: Math.round(performance.now() - started) }));
map.on("error", (ev) => post("error", { message: String(ev.error && ev.error.message || ev.error) }));
// The dashboard only needs to know when the bearing really changes.
let postedBearing = null;
map.on("rotate", () => {
    const b = map.getBearing();
    if (postedBearing === null || Math.abs(((b - postedBearing + 540) % 360) - 180) > 0.5) {
        postedBearing = b;
        post("bearing", { bearing: b });
    }
});

// What the dashboard's panels cover, in this page's pixels. Framing and
// the follow camera keep the truck, the route and places out from under them.
let insets = { left: 0, top: 0, right: 0, bottom: 0 };
function area() {
    const c = map.getContainer();
    return { w: c.clientWidth, h: c.clientHeight };
}
function followPadding() {
    // Truck low on screen: the camera centres it in the lower part.
    return { left: insets.left, right: insets.right, bottom: insets.bottom,
             top: Math.max(insets.top, area().h * 0.42) };
}
function framePadding() {
    return { left: insets.left + 40, right: insets.right + 40, top: insets.top + 40,
             bottom: insets.bottom + 40 };
}

// ---- the truck and follow mode ----------------------------------------------------

// The truck is a 3D model of the Baja (truck.glb, from
// tools/make_map_truck.py) that three.js draws inside the map's own frame
// (a custom layer): exactly on its spot, in the map's perspective, so it
// never jitters against the streets. Like the car in Google Maps it keeps
// one size on screen at any zoom. Its wheels roll, the front ones steer
// through turns, and the body leans a little in corners and dips when
// braking.
const TRUCK_PX = 80;                 // its length on screen, CSS px
const TRUCK_M = 4.85;                // its real length, m
const WHEELBASE_M = 2.65;

const truckScene = new THREE.Scene();
const truckCamera = new THREE.Camera();
const truckRoot = new THREE.Group();          // on its spot, facing its heading
const truckBody = new THREE.Group();          // leans and dips, about its middle
truckBody.position.y = 0.6;
truckRoot.add(truckBody);
truckScene.add(truckRoot);

// Sky light and a high sun behind the viewer's left shoulder. The rig
// turns with the map, so the truck is lit the same way on screen
// whichever way it faces.
const lightRig = new THREE.Group();
lightRig.add(new THREE.HemisphereLight(0xffffff, 0x6f6a60, 1.9));
const sun = new THREE.DirectionalLight(0xffffff, 2.6);
sun.position.set(0.7, 1.6, -1.1);
lightRig.add(sun);
truckScene.add(lightRig);

// A soft shadow on the road under it.
function blob() {
    const c = document.createElement("canvas");
    c.width = c.height = 128;
    const g = c.getContext("2d");
    const grad = g.createRadialGradient(64, 64, 6, 64, 64, 62);
    grad.addColorStop(0, "rgba(0, 0, 0, 0.75)");
    grad.addColorStop(1, "rgba(0, 0, 0, 0)");
    g.fillStyle = grad;
    g.fillRect(0, 0, 128, 128);
    return new THREE.CanvasTexture(c);      // stretched to an oval by its plane
}
const shadowMesh = new THREE.Mesh(new THREE.PlaneGeometry(3.0, 6.2),
    new THREE.MeshBasicMaterial({ map: blob(), transparent: true, depthWrite: false, opacity: 0.6 }));
shadowMesh.rotation.x = -Math.PI / 2;
shadowMesh.position.y = 0.02;
truckRoot.add(shadowMesh);

let wheels = [], wheelRadius = 0.33, truckLoaded = false;
let wheelTurn = 0, steer = 0, roll = 0, dip = 0;
new GLTFLoader().load("truck.glb", (gltf) => {
    const model = gltf.scene;
    model.position.y = -0.6;
    // One side of each surface: the model marks them all two-sided, and
    // once simplified their backs poke through the fronts as speckles.
    model.traverse((o) => { if (o.isMesh) o.material.side = THREE.FrontSide; });
    truckBody.add(model);
    // The wheels stay on the road while the body leans.
    model.traverse((o) => {
        if (/^wheel_(FL|FR|RL|RR)$/.test(o.name) && !/^wheel_/.test(o.parent.name)) wheels.push(o);
    });
    for (const wheel of wheels) {
        truckRoot.attach(wheel);
        wheel.rotation.order = "YXZ";        // steer, then roll
        wheel.userData.front = /F/.test(wheel.name);
    }
    if (wheels.length) {
        const size = new THREE.Box3().setFromObject(wheels[0]).getSize(new THREE.Vector3());
        wheelRadius = size.y / 2;
    }
    truckLoaded = true;
    map.triggerRepaint();
}, undefined, (err) => post("error", { message: "Truck model: " + err }));

// The map's depth range spans a whole city, too coarse for a truck: its
// bed liner and floor flicker through each other. Re-aim the depth at just
// the few metres around the truck (m: model space to clip space).
function tightDepth(m) {
    const e = m.elements;
    const w = (x, y, z) => e[3] * x + e[7] * y + e[11] * z + e[15];
    const centre = w(0, 0.8, 0);
    const reach = 1.2 * Math.max(Math.abs(w(4, 0.8, 0) - centre), Math.abs(w(0, 4, 0) - centre),
                                 Math.abs(w(0, 0.8, 4) - centre));
    const near = Math.max(1e-6, centre - reach), far = centre + reach;
    const a = (far + near) / (far - near), b = -2 * far * near / (far - near);
    for (const i of [2, 6, 10, 14]) e[i] = a * e[i + 1];
    e[14] += b;
}

let truckRenderer = null;
const truckLayer = {
    id: "truck", type: "custom", renderingMode: "3d",
    onAdd(m, gl) {
        if (!truckRenderer) {
            truckRenderer = new THREE.WebGLRenderer({ canvas: m.getCanvas(), context: gl, antialias: true });
            truckRenderer.autoClear = false;
        }
    },
    render(gl, args) {
        if (!shown || !truckLoaded) return;
        const merc = maplibregl.MercatorCoordinate.fromLngLat([shown.lon, shown.lat], 0);
        // Metres per screen pixel here at this zoom, so it stays TRUCK_PX long.
        const mpp = 40075016.686 * Math.cos(shown.lat * Math.PI / 180) / (512 * 2 ** map.getZoom());
        const s = merc.meterInMercatorCoordinateUnits() * (TRUCK_PX * mpp / TRUCK_M);
        const view = (args.defaultProjectionData && args.defaultProjectionData.mainMatrix) || args.modelViewProjectionMatrix;
        const p = new THREE.Matrix4().fromArray(view).multiply(
            new THREE.Matrix4().makeTranslation(merc.x, merc.y, merc.z)
                .scale(new THREE.Vector3(s, -s, s))
                .multiply(new THREE.Matrix4().makeRotationX(Math.PI / 2)));
        tightDepth(p);
        truckCamera.projectionMatrix = p;
        // The model's nose is +Z; compass bearings turn clockwise from north.
        truckRoot.rotation.y = Math.PI - shown.heading * Math.PI / 180;
        lightRig.rotation.y = Math.PI - map.getBearing() * Math.PI / 180;
        truckBody.rotation.set(dip, 0, roll);
        for (const wheel of wheels) {
            wheel.rotation.x = wheelTurn;
            wheel.rotation.y = wheel.userData.front ? steer : 0;
        }
        truckRenderer.resetState();
        truckRenderer.clearDepth();        // it's drawn last, over everything
        truckRenderer.render(truckScene, truckCamera);
    },
};

function drawTruck() {
    try {
        if (!map.getLayer("truck")) map.addLayer(truckLayer);       // on top of everything
    } catch (err) {
        setTimeout(drawTruck, 250);
    }
}
map.on("load", drawTruck);
let truckPending = false;
map.on("styledata", () => {
    if (truckPending || map.getLayer("truck")) return;
    truckPending = true;
    setTimeout(() => { truckPending = false; drawTruck(); }, 0);
});

// ---- where the truck is, and follow mode --------------------------------------------

let shown = null;            // where the truck is drawn: {lon, lat, heading, speed}
let fix = null, fixAt = 0;   // the latest GPS fix, and when it came
let frame = 0, lastStep = 0;
let yawRate = 0, accel = 0;  // rad/s (clockwise +) and m/s², smoothed
let touched = false, easingUntil = 0;
let followZoom = 16.4, zoomBias = 0, approach = Infinity;
let camBearing = 0;
const FOLLOW_PITCH = 55;

function turn(a, b, f) {                     // shortest way round
    const d = ((b - a + 540) % 360) - 180;
    return (a + d * f + 360) % 360;
}
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

let speedZoom = 16.4;
function followCamera(now, dt) {
    if (now < easingUntil) {
        camBearing = map.getBearing();
        return;
    }
    // Zoom out at speed to see further ahead, with some hysteresis so it
    // doesn't pump, and in a little as a turn comes up.
    const v = shown.speed;
    if (v > 24) speedZoom = 15.3;
    else if (v < 20 && v > 13) speedZoom = 15.9;
    else if (v < 10) speedZoom = 16.4;
    const target = speedZoom + zoomBias + (approach < 250 ? 0.6 : 0);
    followZoom += (target - followZoom) * 0.01;
    // The camera turns a beat after the truck, so through a turn you see
    // the truck swing round before the road straightens out ahead.
    camBearing = turn(camBearing, shown.heading, 1 - Math.exp(-dt / 0.8));
    map.jumpTo({ center: [shown.lon, shown.lat], bearing: camBearing, pitch: FOLLOW_PITCH,
                 zoom: followZoom, padding: followPadding() });
}

// The name of the road under the truck, checked about once a second.
let road = "", roadCheckedAt = 0;
const ROAD_LAYERS = ["roads_minor", "roads_minor_service", "roads_link", "roads_major",
                     "roads_highway", "roads_bridges_minor", "roads_bridges_link",
                     "roads_bridges_major", "roads_bridges_highway", "roads_tunnels_minor",
                     "roads_tunnels_link", "roads_tunnels_major", "roads_tunnels_highway"];

function checkRoad(now) {
    if (now - roadCheckedAt < 1000) return;
    roadCheckedAt = now;
    const p = map.project([shown.lon, shown.lat]);
    const ids = ROAD_LAYERS.filter(id => map.getLayer(id));
    const hits = map.queryRenderedFeatures([[p.x - 10, p.y - 10], [p.x + 10, p.y + 10]], { layers: ids });
    // At junctions prefer the bigger road.
    const rank = (id) => /highway/.test(id) ? 0 : /major/.test(id) ? 1 : /link/.test(id) ? 2
                       : /minor/.test(id) && !/service/.test(id) ? 3 : 4;
    const named = hits.filter(f => f.properties.name || f.properties.ref)
                      .sort((a, b) => rank(a.layer.id) - rank(b.layer.id))[0];
    const name = named ? (named.properties.name || named.properties.ref) : "";
    if (name !== road) {
        road = name;
        post("road", { name });
    }
}

function step(now) {
    frame = 0;
    if (!fix) return;
    const dt = lastStep ? Math.min(0.1, (now - lastStep) / 1000) : 1 / 60;
    lastStep = now;
    // Where the truck should be now: the last fix, carried on at its speed
    // and heading (for up to 2 s if the next fix is late), so it never
    // stops between fixes. The drawn truck glides after that point, which
    // also smooths out the GPS's small jumps.
    const ahead = Math.min(2, (now - fixAt) / 1000) * fix.speed;
    const rad = fix.heading * Math.PI / 180;
    const target = { lon: fix.lon + Math.sin(rad) * ahead / (Math.cos(fix.lat * Math.PI / 180) * 111320),
                     lat: fix.lat + Math.cos(rad) * ahead / 110540 };
    const glide = 1 - Math.exp(-dt / 0.25);
    const before = shown;
    shown = { lon: before.lon + (target.lon - before.lon) * glide,
              lat: before.lat + (target.lat - before.lat) * glide,
              heading: turn(before.heading, fix.heading, 1 - Math.exp(-dt / 0.3)),
              speed: before.speed + (fix.speed - before.speed) * glide };

    // How hard it's turning and braking, for the wheels and the body.
    const dHeading = ((shown.heading - before.heading + 540) % 360) - 180;
    yawRate += (dHeading * Math.PI / 180 / dt - yawRate) * Math.min(1, dt / 0.3);
    accel += ((shown.speed - before.speed) / dt - accel) * Math.min(1, dt / 0.5);
    wheelTurn = (wheelTurn + Math.min(0.5, shown.speed * dt / wheelRadius)) % (Math.PI * 2);
    steer = clamp(Math.atan(WHEELBASE_M * yawRate / Math.max(shown.speed, 2)), -0.5, 0.5);
    roll = clamp(-0.012 * shown.speed * yawRate, -0.05, 0.05);      // leans out of a turn
    dip = clamp(-0.008 * accel, -0.03, 0.03);                      // nose down braking

    trimRoute(now);
    refreshControls(false);
    if (following) {
        followCamera(now, dt);
        checkRoad(now);
    } else {
        map.triggerRepaint();
    }
    // Keep going while it's moving or settling; rest when parked.
    const settling = Math.abs(target.lon - shown.lon) + Math.abs(target.lat - shown.lat) > 1e-7
        || Math.abs(((fix.heading - shown.heading + 540) % 360) - 180) > 0.05
        || (following && Math.abs(((shown.heading - camBearing + 540) % 360) - 180) > 0.05);
    if (fix.speed > 0.2 || settling) frame = requestAnimationFrame(step);
    else lastStep = 0;
}

function setPosition(lon, lat, heading, speed) {
    // Below walking pace the GPS heading wanders; keep the last one.
    if (fix && speed < 1) heading = fix.heading;
    fix = { lon, lat, heading, speed };
    fixAt = performance.now();
    if (!shown) {
        shown = { ...fix };
        camBearing = heading;
        if (!touched) startFollowing(true);
    }
    if (!frame) frame = requestAnimationFrame(step);
}

function setFollowing(on) {
    if (on !== following) {
        following = on;
        for (const id of DRIVING_HIDDEN) {
            if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", on ? "none" : "visible");
        }
        post("follow", { on });
    }
}

function startFollowing(animate) {
    if (!shown) return;
    zoomBias = 0;
    setFollowing(true);
    if (animate) {
        easingUntil = performance.now() + 1200;
        map.easeTo({ center: [shown.lon, shown.lat], bearing: shown.heading, pitch: FOLLOW_PITCH,
                     zoom: followZoom, padding: followPadding(), duration: 1200 });
    }
}

// Touching the map takes over from follow mode; the follow key gives it back.
for (const ev of ["dragstart", "rotatestart", "pitchstart", "zoomstart"]) {
    map.on(ev, (e) => {
        if (e.originalEvent) {
            touched = true;
            setFollowing(false);
            post("touched");
        }
    });
}
map.on("mousedown", () => post("touched"));
map.on("touchstart", () => post("touched"));

// ---- a picked place ----------------------------------------------------------------

const pin = document.createElement("div");
pin.className = "pin";
pin.innerHTML = '<svg viewBox="0 0 22 28" width="44" height="56"><path d="M11 1C5.5 1 1 5.4 1 10.9 1 18.3 11 27 11 27s10-8.7 10-16.1C21 5.4 16.5 1 11 1z"/><circle cx="11" cy="10.5" r="3.6"/></svg>';
const pinMarker = new maplibregl.Marker({ element: pin, anchor: "bottom" });

function frameAll(points, maxZoom = 16, duration = 1200) {
    // Drop follow mode's offset first, or it adds to the framing margins.
    map.jumpTo({ padding: { top: 0, bottom: 0, left: 0, right: 0 } });
    const b = new maplibregl.LngLatBounds(points[0], points[0]);
    for (const p of points) b.extend(p);
    map.fitBounds(b, { padding: framePadding(), bearing: 0, pitch: 0, maxZoom, duration });
}

function showPlace(lon, lat) {
    touched = true;
    setFollowing(false);
    pinMarker.setLngLat([lon, lat]).addTo(map);
    // The truck and the place together, so you can see which way it is.
    frameAll(shown ? [[shown.lon, shown.lat], [lon, lat]] : [[lon, lat]], 16);
}

// ---- traffic lights, stop signs and yield signs ---------------------------------------

// The real things: the US STOP and YIELD signs (the federal sign manual's
// artwork) and Noto's 3D traffic light, made into icons by
// tools/make_sign_icons.py (sources and licences in tools/sign-icons).
// Loaded once; a day/night style change asks for them again.
const SIGN_ICONS = { "ctl-signal": "icons/signal.png", "ctl-stop": "icons/stop.png", "ctl-yield": "icons/yield.png" };
const signImages = {};
for (const [id, src] of Object.entries(SIGN_ICONS)) {
    const img = new Image();
    img.src = src;
    img.decode().then(() => { signImages[id] = img; }).catch(() => {});
}
map.on("styleimagemissing", (ev) => {
    const img = signImages[ev.id];
    if (img && !map.hasImage(ev.id)) map.addImage(ev.id, img, { pixelRatio: 2 });
});

// Like Apple Maps, only while driving a route, and only the lights and
// signs along it (the next few km): exactly the ones you'll meet.
let allControls = [];
const grid = new Map();                    // ~400 m cells -> indexes into allControls
const CELL = 0.004;
const cellOf = (lon, lat) => `${Math.floor(lon / CELL)},${Math.floor(lat / CELL)}`;
let shownControls = [], controlsAt = 0;
let guiding = false;                       // driving a route (not just looking at one)

fetch(`${origin}/data/controls.geojson`).then(r => r.json()).then(fc => {
    allControls = fc.features.map(f => ({ lon: f.geometry.coordinates[0], lat: f.geometry.coordinates[1], k: f.properties.k }));
    allControls.forEach((c, i) => {
        const key = cellOf(c.lon, c.lat);
        if (!grid.has(key)) grid.set(key, []);
        grid.get(key).push(i);
    });
    refreshControls(true);
}).catch(() => {});

function metres(aLon, aLat, bLon, bLat) {
    const k = Math.cos(aLat * Math.PI / 180) * 111320;
    return Math.hypot((bLon - aLon) * k, (bLat - aLat) * 110540);
}

function around(lon, lat, radius, into) {
    const reach = Math.ceil(radius / 300);
    const cx = Math.floor(lon / CELL), cy = Math.floor(lat / CELL);
    for (let x = cx - reach; x <= cx + reach; x++) {
        for (let y = cy - reach; y <= cy + reach; y++) {
            for (const i of grid.get(`${x},${y}`) || []) {
                const c = allControls[i];
                if (metres(lon, lat, c.lon, c.lat) <= radius) into.add(i);
            }
        }
    }
    return into;
}

// Lights and signs within ~18 m of the route, for the next 4 km of it.
function alongRoute(coords, from) {
    const found = new Set();
    let ahead = 0;
    for (let i = Math.max(0, from); i < coords.length - 1 && ahead < 4000; i++) {
        const [ax, ay] = coords[i], [bx, by] = coords[i + 1];
        const len = metres(ax, ay, bx, by);
        ahead += len;
        // Check points every ~20 m along the segment.
        const steps = Math.max(1, Math.ceil(len / 20));
        for (let s = 0; s <= steps; s++) {
            const f = s / steps;
            around(ax + (bx - ax) * f, ay + (by - ay) * f, 18, found);
        }
    }
    return found;
}

function refreshControls(force) {
    const now = performance.now();
    if (!allControls.length || (!force && now - controlsAt < 2000)) return;
    controlsAt = now;
    let list = [];
    if (guiding && routeCoords) {
        // From the truck on, so lights it has passed drop away.
        const ahead = shown ? [[shown.lon, shown.lat], ...routeCoords.slice(trimFrom + 1)] : routeCoords;
        list = [...alongRoute(ahead, 0)].map(i => allControls[i]);
    }
    if (!force && list.length === shownControls.length && list.every((c, j) => c === shownControls[j])) return;
    shownControls = list;
    const src = map.getSource("controls");
    if (src) src.setData({ type: "FeatureCollection", features: list.map(c => (
        { type: "Feature", properties: { k: c.k }, geometry: { type: "Point", coordinates: [c.lon, c.lat] } })) });
}

function addControls() {
    if (!map.getSource("controls")) {
        map.addSource("controls", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
    }
    if (!map.getLayer("controls")) {
        const firstLabel = map.getStyle().layers.find(l => l.type === "symbol");
        map.addLayer({
            id: "controls", type: "symbol", source: "controls", minzoom: 13,
            layout: {
                "icon-image": ["match", ["get", "k"], "signal", "ctl-signal", "stop", "ctl-stop", "ctl-yield"],
                "icon-size": ["interpolate", ["linear"], ["zoom"], 13, 0.55, 15, 0.78, 17, 1, 19, 1.2],
                // Always drawn, and never in the way of street names: they
                // matter more than any label collision rule.
                "icon-allow-overlap": true,
                "icon-ignore-placement": true,
                "symbol-sort-key": ["match", ["get", "k"], "signal", 0, "stop", 1, 2],
            },
        }, firstLabel ? firstLabel.id : undefined);
    }
}

function drawControls() {
    try {
        addControls();
        refreshControls(true);
    } catch (err) {
        setTimeout(drawControls, 250);
    }
}
map.on("load", drawControls);
// A style change (day/night) drops added layers; put them back. (Not
// waiting for map.loaded(): while following, tiles are always loading.)
let controlsPending = false;
map.on("styledata", () => {
    if (controlsPending || map.getLayer("controls")) return;
    controlsPending = true;
    setTimeout(() => { controlsPending = false; drawControls(); }, 0);
});

// ---- the route --------------------------------------------------------------------

// The line is a gradient along its length, so it can draw itself in from
// the start when a route first appears.
function routeGradient(colour, upTo) {
    if (upTo >= 1) return ["interpolate", ["linear"], ["line-progress"], 0, colour, 1, colour];
    const p = Math.max(0.0001, upTo);
    return ["interpolate", ["linear"], ["line-progress"], 0, colour, p, colour,
            Math.min(1, p + 0.0001), "rgba(0, 0, 0, 0)"];
}

let reveal = 1;
function paintRoute() {
    const look = LOOKS[mode];
    if (map.getLayer("route-line")) map.setPaintProperty("route-line", "line-gradient", routeGradient(look.route, reveal));
    if (map.getLayer("route-casing")) map.setPaintProperty("route-casing", "line-gradient", routeGradient(look.routeCasing, reveal));
}

function revealRoute(ms = 900) {
    const t0 = performance.now();
    function tick(now) {
        const f = Math.min(1, (now - t0) / ms);
        reveal = 1 - Math.pow(1 - f, 3);            // ease out
        paintRoute();
        if (f < 1) requestAnimationFrame(tick);
    }
    reveal = 0;
    requestAnimationFrame(tick);
}

let routeCoords = null;
let trimFrom = 0, trimmedAt = 0;      // the route segment the truck is on

// Once a second, drop the part of the line the truck has already driven:
// snap the truck to the nearest route segment just ahead of the last one
// and draw from there.
function trimRoute(now) {
    if (!routeCoords || !shown || now - trimmedAt < 1000 || !map.getSource("route")) return;
    trimmedAt = now;
    const k = Math.cos(shown.lat * Math.PI / 180);
    let best = trimFrom, bestD = Infinity;
    const end = Math.min(routeCoords.length - 1, trimFrom + 300);
    for (let i = trimFrom; i < end; i++) {
        const [ax, ay] = routeCoords[i], [bx, by] = routeCoords[i + 1];
        const dx = (bx - ax) * k, dy = by - ay;
        const px = (shown.lon - ax) * k, py = shown.lat - ay;
        const len = dx * dx + dy * dy;
        const t = len ? Math.max(0, Math.min(1, (px * dx + py * dy) / len)) : 0;
        const ex = px - t * dx, ey = py - t * dy;
        const d = ex * ex + ey * ey;
        if (d < bestD) { bestD = d; best = i; }
    }
    trimFrom = best;
    map.getSource("route").setData({ type: "Feature", properties: {},
        geometry: { type: "LineString", coordinates: [[shown.lon, shown.lat]].concat(routeCoords.slice(best + 1)) } });
}

// isStyleLoaded() is false whenever tiles are still loading (nearly always
// while following), so just try, and retry shortly if the style itself is
// mid-change ("Style is not done loading").
function drawRoute() {
    if (!routeCoords) return;
    try {
        addRoute();
    } catch (err) {
        setTimeout(drawRoute, 250);
    }
}

function addRoute() {
    const data = { type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: routeCoords } };
    if (map.getSource("route")) {
        map.getSource("route").setData(data);
    } else {
        map.addSource("route", { type: "geojson", data, lineMetrics: true });
    }
    const look = LOOKS[mode];
    if (!map.getLayer("route-line")) {
        // Under the labels and signs, over the roads.
        const firstLabel = map.getStyle().layers.find(l => l.type === "symbol");
        const before = firstLabel ? firstLabel.id : undefined;
        const round = { "line-join": "round", "line-cap": "round" };
        map.addLayer({ id: "route-casing", type: "line", source: "route", layout: round,
                       paint: { "line-gradient": routeGradient(look.routeCasing, reveal),
                                "line-width": ["interpolate", ["exponential", 1.5], ["zoom"], 10, 7, 13, 11, 16, 19, 19, 28] } },
                     before);
        map.addLayer({ id: "route-line", type: "line", source: "route", layout: round,
                       paint: { "line-gradient": routeGradient(look.route, reveal),
                                "line-width": ["interpolate", ["exponential", 1.5], ["zoom"], 10, 5, 13, 8, 16, 14, 19, 21] } },
                     before);
    }
}

function clearRoute() {
    guiding = false;
    routeCoords = null;
    refreshControls(true);
    for (const id of ["route-line", "route-casing"]) if (map.getLayer(id)) map.removeLayer(id);
    if (map.getSource("route")) map.removeSource("route");
}

// A style change (day/night) drops added layers; put the route back.
map.on("styledata", () => { if (routeCoords && !map.getLayer("route-line")) drawRoute(); });

// ---- the engine benchmark ------------------------------------------------------------

// Simulated tilted follow mode for the engine pass criteria: drive I-5
// north through downtown at highway speed for `seconds`, then report frame
// times. Nothing else uses this.
const I5 = [
    [-122.3207, 47.5615], [-122.3218, 47.5810], [-122.3250, 47.5960], [-122.3270, 47.6070],
    [-122.3245, 47.6200], [-122.3225, 47.6300], [-122.3220, 47.6450], [-122.3270, 47.6600],
    [-122.3195, 47.6760],
];

function along(path, metres) {
    const R = 6371000, rad = Math.PI / 180;
    for (let i = 0; i < path.length - 1; i++) {
        const [x0, y0] = path[i], [x1, y1] = path[i + 1];
        const dx = (x1 - x0) * rad * R * Math.cos(y0 * rad), dy = (y1 - y0) * rad * R;
        const len = Math.hypot(dx, dy);
        if (metres <= len) {
            const f = metres / len;
            return { center: [x0 + (x1 - x0) * f, y0 + (y1 - y0) * f],
                     bearing: Math.atan2(dx, dy) / rad };
        }
        metres -= len;
    }
    return null;
}

function bench(seconds = 20, speed = 30) {
    setFollowing(false);
    touched = true;
    const times = [];
    let last = null, startT = null;
    function next(now) {
        if (startT === null) startT = now;
        if (last !== null) times.push(now - last);
        last = now;
        const pos = along(I5, (now - startT) / 1000 * speed);
        if (pos && now - startT < seconds * 1000) {
            map.jumpTo({ center: pos.center, bearing: pos.bearing, pitch: 60, zoom: 16.5 });
            requestAnimationFrame(next);
        } else {
            times.sort((a, b) => a - b);
            const avg = times.reduce((a, b) => a + b, 0) / times.length;
            post("bench", {
                fps: +(1000 / avg).toFixed(1),
                p95ms: +times[Math.floor(times.length * 0.95)].toFixed(1),
                over50ms: times.filter(t => t > 50).length,
                frames: times.length,
            });
        }
    }
    requestAnimationFrame(next);
}

// ---- what the dashboard can call ---------------------------------------------------------

window.baja = {
    map,                    // for poking at from a desktop browser's console
    // "day" or "night"
    setMode(m) {
        if (!LOOKS[m] || m === mode) return;
        mode = m;
        applyPageColours(mode);
        map.setStyle(styleFor(mode));
        paintRoute();
    },
    // {left, top, right, bottom} in this page's pixels
    setInsets(i) {
        insets = { left: 0, top: 0, right: 0, bottom: 0, ...i };
    },
    setPosition,
    // Metres to the next turn while navigating (zooms in a little as it nears).
    setApproach(m) { approach = m; },
    showPlace,
    clearPlace() { pinMarker.remove(); },
    // The whole route, framed beside the place card, before Go.
    previewRoute(coords) {
        guiding = false;
        routeCoords = coords;
        trimFrom = 0;
        trimmedAt = 0;
        drawRoute();
        revealRoute();
        touched = true;
        setFollowing(false);
        frameAll(coords, 17);
    },
    // Driving it: draw it; QML starts following.
    showRoute(coords) {
        guiding = true;
        routeCoords = coords;
        trimFrom = 0;
        trimmedAt = 0;
        drawRoute();
        refreshControls(true);
    },
    clearRoute,
    // The rest of the route in one view (the Overview key).
    overview() {
        if (!routeCoords) return;
        setFollowing(false);
        const rest = routeCoords.slice(trimFrom);
        frameAll(shown ? [[shown.lon, shown.lat], ...rest] : rest, 17, 900);
    },
    // While following, the zoom keys nudge the follow zoom instead of
    // breaking out of follow mode.
    zoomIn() {
        if (following) zoomBias = Math.min(3, zoomBias + 1);
        else map.zoomIn({ duration: 300 });
    },
    zoomOut() {
        if (following) zoomBias = Math.max(-4, zoomBias - 1);
        else map.zoomOut({ duration: 300 });
    },
    // Follow the truck if there's a position, else go back to Seattle.
    recenter() {
        if (shown) { startFollowing(true); return; }
        map.easeTo({ center: SEATTLE, zoom: 12.5, bearing: 0, pitch: 0,
                     padding: { top: 0, bottom: 0, left: 0, right: 0 }, duration: 800 });
    },
    northUp() {
        setFollowing(false);
        map.easeTo({ bearing: 0, pitch: 0, duration: 500 });
    },
    bench,
    // What the map's WebGL is doing (for checking a new device).
    glInfo() {
        const gl = map.painter.context.gl;
        post("info", { antialias: gl.getContextAttributes().antialias, samples: gl.getParameter(gl.SAMPLES),
                       renderer: gl.getParameter(gl.RENDERER), version: gl.getParameter(gl.VERSION) });
    },
};
