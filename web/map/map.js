// The Baja OS map: MapLibre GL JS drawing the offline Protomaps extract that
// backend/maps.py serves from /data. Colours come from the dashboard's theme
// tokens (passed as ?theme={...} and on every style change), so the map
// always matches the UI. QML drives it through `window.baja` and listens for
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
// dashboard, so keep the names and drop the icons.
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
        layers: withoutPoiIcons(layers("protomaps", flavorFor(t), { lang: "en" })),
    };
}

// ---- the map ----------------------------------------------------------------

const query = new URLSearchParams(location.search);
let theme = { ...FALLBACK_THEME, ...JSON.parse(query.get("theme") || "{}") };
document.body.style.background = theme.bg;

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
        document.body.style.background = theme.bg;
        map.setStyle(styleFor(theme));
    },
    zoomIn() { map.zoomIn({ duration: 300 }); },
    zoomOut() { map.zoomOut({ duration: 300 }); },
    recenter() { map.easeTo({ center: SEATTLE, zoom: 12.5, bearing: 0, pitch: 0, duration: 800 }); },
    northUp() { map.easeTo({ bearing: 0, pitch: 0, duration: 500 }); },
    bench,
};
