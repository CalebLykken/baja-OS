// The Baja OS map: MapLibre GL JS drawing the offline Protomaps extract that
// backend/maps.py serves from /data. Colours come from the dashboard's theme
// tokens (passed as ?theme={...} and on every style change), so the map
// always matches the UI. The truck is an arrow that glides between position
// fixes; in follow mode the map tilts, turns heading-up and keeps the truck
// low on screen. QML drives it through `window.baja` and listens for
// console messages that start with "baja:".

import * as maplibregl from "./vendor/maplibre-gl.mjs";
import { layers, namedFlavor } from "./vendor/basemaps.mjs";

const started = performance.now();
const origin = location.origin;
const SEATTLE = [-122.3321, 47.6062];

// Trail's tokens, for a desktop browser opened without ?theme.
const FALLBACK_THEME = {
    bg: "#14160f", panel: "#1e2118", panelHi: "#2c3123", line: "#4a4a35",
    text: "#e9dfc4", textDim: "#9c9478", accent: "#ff7a1a", warn: "#ff4530", ok: "#a8c66c",
};

function post(kind, data = {}) {
    console.log("baja:" + JSON.stringify({ kind, ...data }));
}

// ---- colour helpers ---------------------------------------------------------

function rgb(hex) {
    const h = hex.replace("#", "").slice(-6);      // QML may send #aarrggbb
    return [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16));
}

function mix(a, b, t) {
    const x = rgb(a), y = rgb(b);
    return "#" + x.map((v, i) => Math.round(v + (y[i] - v) * t).toString(16).padStart(2, "0")).join("");
}

// The map's palette, derived from the dashboard's. Land is the card colour,
// water and greenery are quiet tints of it, roads step up from the border
// colour toward the caption colour by importance, and labels use the text
// colours. The accent is left for the route and the truck's position.
function flavorFor(t) {
    const land = t.panel, bg = t.bg, line = t.line, dim = t.textDim, text = t.text;
    const water = mix(bg, "#2d5866", 0.32);
    const green = mix(land, t.ok, 0.07);
    const scrub = mix(land, t.ok, 0.04);
    const minor = mix(line, land, 0.25);
    const major = mix(line, dim, 0.35);
    const highway = mix(line, dim, 0.65);
    const tunnel = mix(minor, land, 0.5);
    const casing = bg;

    return {
        ...namedFlavor("dark"),
        background: bg,
        earth: land,
        park_a: green, park_b: green, wood_a: green, wood_b: green, zoo: green,
        scrub_a: scrub, scrub_b: scrub,
        hospital: land, school: land, military: land,
        industrial: mix(land, bg, 0.35),
        pedestrian: mix(land, line, 0.2),
        glacier: mix(land, text, 0.08),
        sand: mix(land, dim, 0.1), beach: mix(land, dim, 0.12),
        aerodrome: mix(land, line, 0.15), runway: mix(land, line, 0.5),
        pier: mix(land, line, 0.4),
        water,
        buildings: mix(land, line, 0.3),

        tunnel_other_casing: casing, tunnel_minor_casing: casing, tunnel_link_casing: casing,
        tunnel_major_casing: casing, tunnel_highway_casing: casing,
        tunnel_other: tunnel, tunnel_minor: tunnel, tunnel_link: tunnel,
        tunnel_major: tunnel, tunnel_highway: tunnel,

        minor_service_casing: casing, minor_casing: casing, link_casing: casing,
        major_casing_late: casing, highway_casing_late: casing,
        major_casing_early: casing, highway_casing_early: casing,
        other: minor, minor_service: minor, minor_a: minor, minor_b: minor,
        link: major, major, highway,
        railway: mix(line, bg, 0.2),
        boundaries: dim,

        bridges_other_casing: casing, bridges_minor_casing: casing, bridges_link_casing: casing,
        bridges_major_casing: casing, bridges_highway_casing: casing,
        bridges_other: minor, bridges_minor: minor, bridges_link: major,
        bridges_major: major, bridges_highway: highway,

        roads_label_minor: mix(dim, land, 0.25), roads_label_minor_halo: land,
        roads_label_major: dim, roads_label_major_halo: land,
        ocean_label: mix(water, dim, 0.6),
        subplace_label: dim, subplace_label_halo: bg,
        city_label: text, city_label_halo: bg,
        state_label: dim, state_label_halo: bg,
        country_label: dim,
        address_label: mix(dim, land, 0.3), address_label_halo: land,

        pois: {
            blue: dim, green: mix(dim, t.ok, 0.5), lapis: dim, pink: dim,
            red: dim, slategray: dim, tangerine: dim, turquoise: dim,
        },
        landcover: {
            grassland: mix(land, t.ok, 0.05), barren: land, urban_area: mix(land, line, 0.08),
            farmland: mix(land, t.ok, 0.04), glacier: mix(land, text, 0.08),
            scrub, forest: mix(land, t.ok, 0.09),
        },
    };
}

// Point-of-interest icons come in fixed colours that clash with the
// dashboard, so keep the names and drop the icons. While following the
// truck the names are hidden too: shop names are clutter when driving.
const DRIVING_HIDDEN = ["pois", "address_label"];

function withoutPoiIcons(list) {
    return list.map(layer => {
        if (layer.id !== "pois") return layer;
        const layout = { ...layer.layout };
        delete layout["icon-image"];
        delete layout["text-offset"];
        delete layout["text-variable-anchor"];
        return { ...layer, layout };
    });
}

function forDriving(list, driving) {
    return list.map(layer => DRIVING_HIDDEN.includes(layer.id)
        ? { ...layer, layout: { ...layer.layout, visibility: driving ? "none" : "visible" } }
        : layer);
}

function styleFor(t) {
    return {
        version: 8,
        glyphs: `${origin}/data/fonts/{fontstack}/{range}.pbf`,
        sprite: `${origin}/data/sprites/v4/dark`,
        sources: {
            protomaps: {
                type: "vector",
                url: `pmtiles://${origin}/data/basemap.pmtiles`,
                attribution: "© OpenStreetMap contributors",
            },
        },
        layers: forDriving(withoutPoiIcons(layers("protomaps", flavorFor(t), { lang: "en" })),
                           following),
    };
}

// ---- the map ----------------------------------------------------------------

const query = new URLSearchParams(location.search);
let following = false;       // follow mode: the camera rides with the truck
let theme = { ...FALLBACK_THEME, ...JSON.parse(query.get("theme") || "{}") };

function applyPageColours(t) {
    document.body.style.background = t.bg;
    document.documentElement.style.setProperty("--accent", t.accent);
    document.documentElement.style.setProperty("--bg", t.bg);
}
applyPageColours(theme);

const region = await fetch(`${origin}/data/region.json`).then(r => r.json()).catch(() => null);
// Keep the camera over the extract, with a little room past its edges.
const [w, s, e, n] = region ? region.bbox : [-122.7, 47.1, -121.7, 48.1];
const pad = 0.15;

const protocol = new pmtiles.Protocol();
maplibregl.addProtocol("pmtiles", protocol.tile);

const map = new maplibregl.Map({
    container: "map",
    style: styleFor(theme),
    center: SEATTLE,
    zoom: 12.5,
    minZoom: 8,
    maxZoom: 19,
    maxPitch: 70,
    maxBounds: [[w - pad, s - pad], [e + pad, n + pad]],
    attributionControl: false,
    fadeDuration: 150,
});

map.on("load", () => post("ready", { ms: Math.round(performance.now() - started) }));

// ---- the truck and follow mode ----------------------------------------------

const puck = document.createElement("div");
puck.className = "puck";
puck.innerHTML = '<svg viewBox="0 0 46 46" width="46" height="46"><path d="M23 4 L38 40 L23 32 L8 40 Z"/></svg>';
const marker = new maplibregl.Marker({ element: puck, rotationAlignment: "map", pitchAlignment: "map" });

let shown = null;            // where the arrow is drawn: {lon, lat, heading, speed}
let from = null, to = null, fixAt = 0, span = 1000, frame = 0;
let touched = false, easingUntil = 0;
let followZoom = 16.4, zoomBias = 0;
const FOLLOW_PITCH = 55;

function turn(a, b, f) {                     // shortest way round
    const d = ((b - a + 540) % 360) - 180;
    return (a + d * f + 360) % 360;
}

function followPadding() {
    return { top: map.getContainer().clientHeight * 0.35, bottom: 0, left: 0, right: 0 };
}

function followCamera(now) {
    if (now < easingUntil) return;
    // Zoom out a little at speed to see further ahead.
    const s = shown.speed;
    const target = (s > 22 ? 15.4 : s > 12 ? 15.9 : 16.4) + zoomBias;
    followZoom += (target - followZoom) * 0.02;
    map.jumpTo({ center: [shown.lon, shown.lat], bearing: shown.heading, pitch: FOLLOW_PITCH,
                 zoom: followZoom, padding: followPadding() });
}

// The name of the road under the arrow, checked about once a second.
let road = "", roadCheckedAt = 0;
const ROAD_LAYERS = ["roads_minor", "roads_minor_service", "roads_link", "roads_major",
                     "roads_highway", "roads_other", "roads_bridges_minor", "roads_bridges_link",
                     "roads_bridges_major", "roads_bridges_highway", "roads_tunnels_minor",
                     "roads_tunnels_link", "roads_tunnels_major", "roads_tunnels_highway"];

function checkRoad(now) {
    if (now - roadCheckedAt < 1000) return;
    roadCheckedAt = now;
    const p = map.project([shown.lon, shown.lat]);
    const layers = ROAD_LAYERS.filter(id => map.getLayer(id));
    const hits = map.queryRenderedFeatures([[p.x - 10, p.y - 10], [p.x + 10, p.y + 10]], { layers });
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
    if (!to) return;
    const f = Math.min(1, (now - fixAt) / span);
    shown = { lon: from.lon + (to.lon - from.lon) * f, lat: from.lat + (to.lat - from.lat) * f,
              heading: turn(from.heading, to.heading, f), speed: to.speed };
    marker.setLngLat([shown.lon, shown.lat]).setRotation(shown.heading);
    trimRoute(now);
    if (following) {
        followCamera(now);
        checkRoad(now);
    }
    if (f < 1) frame = requestAnimationFrame(step);
}

function setPosition(lon, lat, heading, speed) {
    const now = performance.now();
    const fix = { lon, lat, heading, speed };
    if (!shown) {
        shown = fix;
        marker.setLngLat([lon, lat]).setRotation(heading).addTo(map);
        if (!touched) startFollowing(true);
    }
    // Glide from where the arrow is now to the new fix over about the time
    // between fixes, so it never stops and never jumps.
    span = fixAt ? Math.min(2000, Math.max(300, now - fixAt)) : 1000;
    from = { ...shown };
    to = fix;
    fixAt = now;
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
        easingUntil = performance.now() + 900;
        map.easeTo({ center: [shown.lon, shown.lat], bearing: shown.heading, pitch: FOLLOW_PITCH,
                     zoom: followZoom, padding: followPadding(), duration: 900 });
    }
}

// ---- a searched-for place ----------------------------------------------------

const pin = document.createElement("div");
pin.className = "pin";
pin.innerHTML = '<svg viewBox="0 0 22 28" width="44" height="56"><path d="M11 1C5.5 1 1 5.4 1 10.9 1 18.3 11 27 11 27s10-8.7 10-16.1C21 5.4 16.5 1 11 1z"/><circle cx="11" cy="10.5" r="3.6"/></svg>';
const pinMarker = new maplibregl.Marker({ element: pin, anchor: "bottom" });

function showPlace(lon, lat) {
    touched = true;
    setFollowing(false);
    pinMarker.setLngLat([lon, lat]).addTo(map);
    // Drop follow mode's offset first, or it adds to the framing margins.
    map.jumpTo({ padding: { top: 0, bottom: 0, left: 0, right: 0 } });
    const flat = { bearing: 0, pitch: 0, padding: { top: 130, bottom: 80, left: 80, right: 120 } };
    if (shown) {
        // Show the truck and the place together, so you can see which way it is.
        const b = new maplibregl.LngLatBounds([shown.lon, shown.lat], [shown.lon, shown.lat]).extend([lon, lat]);
        map.fitBounds(b, { ...flat, maxZoom: 16, duration: 1400 });
    } else {
        map.flyTo({ center: [lon, lat], zoom: 15.5, ...flat, duration: 1400 });
    }
}

// ---- the route ---------------------------------------------------------------

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
    } catch (e) {
        setTimeout(drawRoute, 250);
    }
}

function addRoute() {
    const data = { type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: routeCoords } };
    if (map.getSource("route")) {
        map.getSource("route").setData(data);
    } else {
        map.addSource("route", { type: "geojson", data });
    }
    if (!map.getLayer("route-line")) {
        // Under the labels, over the roads.
        const firstLabel = map.getStyle().layers.find(l => l.type === "symbol");
        const before = firstLabel ? firstLabel.id : undefined;
        const round = { "line-join": "round", "line-cap": "round" };
        map.addLayer({ id: "route-casing", type: "line", source: "route", layout: round,
                       paint: { "line-color": theme.bg,
                                "line-width": ["interpolate", ["linear"], ["zoom"], 10, 7, 16, 18] } }, before);
        map.addLayer({ id: "route-line", type: "line", source: "route", layout: round,
                       paint: { "line-color": theme.accent,
                                "line-width": ["interpolate", ["linear"], ["zoom"], 10, 4, 16, 11] } }, before);
    }
}

function clearRoute() {
    routeCoords = null;
    for (const id of ["route-line", "route-casing"]) if (map.getLayer(id)) map.removeLayer(id);
    if (map.getSource("route")) map.removeSource("route");
}

// A style change (a new theme) drops added layers; put the route back.
map.on("styledata", () => { if (routeCoords && !map.getLayer("route-line")) drawRoute(); });

// Touching the map takes over from follow mode; the follow key gives it back.
for (const ev of ["dragstart", "rotatestart", "pitchstart", "zoomstart"]) {
    map.on(ev, (e) => {
        if (e.originalEvent) {
            touched = true;
            setFollowing(false);
        }
    });
}
map.on("error", (ev) => post("error", { message: String(ev.error && ev.error.message || ev.error) }));
map.on("rotate", () => post("bearing", { bearing: map.getBearing() }));

// ---- what the dashboard can call ------------------------------------------------

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
    function frame(now) {
        if (startT === null) startT = now;
        if (last !== null) times.push(now - last);
        last = now;
        const pos = along(I5, (now - startT) / 1000 * speed);
        if (pos && now - startT < seconds * 1000) {
            map.jumpTo({ center: pos.center, bearing: pos.bearing, pitch: 60, zoom: 16.5 });
            requestAnimationFrame(frame);
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
    requestAnimationFrame(frame);
}

window.baja = {
    map,                    // for poking at from a desktop browser's console
    setTheme(t) {
        theme = { ...FALLBACK_THEME, ...t };
        applyPageColours(theme);
        map.setStyle(styleFor(theme));
        for (const [id, colour] of [["route-casing", theme.bg], ["route-line", theme.accent]]) {
            if (map.getLayer(id)) map.setPaintProperty(id, "line-color", colour);
        }
    },
    setPosition,
    showPlace,
    clearPlace() { pinMarker.remove(); },
    showRoute(coords) {
        routeCoords = coords;
        trimFrom = 0;
        trimmedAt = 0;
        drawRoute();
    },
    clearRoute,
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
};
