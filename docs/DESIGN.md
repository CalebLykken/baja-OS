# Baja OS design: Trail

Trail is the default and the reference style. The other styles (Cluster,
Rally, Amber) reuse the same structure with their own tokens.

**Concept: a switch panel bolted onto a topo map.** Matte, printed, utility:
olive panels with chunky borders, sand lettering, one safety-orange for what's
live or selected, and contour lines in the gutters. Nothing glows. The only
full-colour things on screen are the album cover, the 3D truck and the map,
which is the one deliberate exception to Trail (see Map).

## Palette (Trail, night)

| Name | Hex | Used for |
|---|---|---|
| Basin | `#14160f` | Window background and gutters (with the topo lines) |
| Olive | `#1e2118` | Cards, always opaque |
| Moss | `#2c3123` | Idle keys, the active nav plate, pressed cards |
| Contour | `#4a4a35` | Every border, track, empty segment and contour line |
| Sand | `#e9dfc4` | Text and numerals |
| Lichen | `#9c9478` | Captions, units, times |
| Blaze | `#ff7a1a` | Selected or active state, the one primary key per screen, live fills (segments, progress, levels) |
| Ember | `#ff4530` | Thresholds only (redline, overheating, low battery) |
| Sage | `#a8c66c` | Status only (online) |

No colour is extracted from album art to drive the UI. Outside the map, no
brand colours are used; sources are named in text ("Spotify").

**Day:** the same roles in a light set, switched by the sun where the truck is
(or Settings > Display > Appearance), for the whole dashboard and the map together:
Basin `#e8e3d4`, Olive `#f6f2e7`, Moss `#e5dfcc`, Contour `#c8bfa4`, text
`#23261b`, Lichen `#696450`, Blaze `#e2650c`, Ember `#c4321f`, Sage `#4c7c29`.

## Type (URW Gothic; Overpass on the map)

| Token | Size / weight | Used for |
|---|---|---|
| Gauge numeral | auto, Bold | Gauge centres |
| Readout | 56 Bold | Readouts (Truck and Home), the speed on the map |
| Huge | 88 DemiBold | Distance to the next turn (Maps) |
| Hero | 56 DemiBold | Place names (Maps), the Baja OS title in Settings |
| Title | 40 DemiBold | Page titles, track titles (Home and Music), card titles |
| Body | 30 Book | Artists, list rows, settings text |
| Small | 24 Book, Lichen | Times, units, secondary lines |
| Legend | 20 DemiBold, caps, tracking 2, Lichen | Instrument legends only: gauge and readout labels (RPM, BOOST) and nav labels |

The map, its labels and the text on its cards are Overpass (Regular,
SemiBold, Bold, bundled), after US highway-sign lettering. Every other label is
the style's font.
Everything else is sentence case. Card headings are dropped where the content
explains itself (a song doesn't need "Now playing" above it). Where a heading
earns its place, it carries information ("Up next on Spotify") in sentence case.

## Shapes

- **Radius 6 for everything rectangular,** with a 2 px Contour border: cards,
  the album cover, keys, segmented controls, list highlights.
- **Keys are rounded squares** (switch-panel style), not circles. Circles are
  used only for status dots.
- **Choices are one joined segmented control** (Style, Units), so "selected"
  (Blaze fill inside the control) never looks like an action key.
- **Levels are segmented bars** (volume, brightness), echoing the gauges:
  Blaze segments on, Moss segments off.

## Album art

- **A framed print on the card:** the cover cropped square at radius 6, with a
  2 px Contour border and a hard offset shadow (darkened Basin at 70 %, +6 px
  right, +8 px down). No glow, no blur.
- **No cover:** a Moss tile with a Lichen icon.
- **No album backdrop.** The topo lines are the constant background on every page except Maps, where the map fills the screen.

## Map

The map is the exception to Trail: it looks like Apple Maps, so it reads at a
glance and matches the car maps people know. It has its own fixed day and night
palettes (in `web/map/map.js`), not the style's tokens. It follows day/night
with the rest of the dashboard.

- **Full screen beside the rail** on Maps (no status bar; the clock moves into
  the rail). On Home the same map sits small in a tile with the standard
  radius and border, and any tap opens Maps.
- **Colours:** day is warm off-white land, pale-blue water, soft-green parks,
  white streets with amber highways; night is charcoal land, deep-blue water,
  dark-green parks, grey streets with dim amber highways.
- **The route is blue** (`#1a7cf5` day, `#2f8cff` night, with a darker casing);
  the destination pin is red. Nothing else on the map is that colour.
- **Labels in Overpass,** scaled 1.1 to 1.35x the stock size (roads largest) so
  they read at arm's length. Roads are drawn 1.25x wider.
- **No coloured POI icons;** POI names only, in grey.
- **Cards over the map are Apple-style:** white by day, dark grey (`#2c2c2e`)
  at night, radius 26, soft shadow, system blue for what's active, a green
  **Go** and a red **End**. The next turn is a dark banner in both modes.
  Text on them is Overpass.
- **Keys:** one strip on the bottom right (zoom only after touching the map,
  overview and spoken directions while navigating, recentre), the speed limit
  and speed on the right, and a small "© OpenStreetMap" credit beside the keys.

## Layout

All card content is inset 20 px. Gutters between cards are 14 px.

```
Home
┌─────────────────────────────────────┐ ┌──────────────────────┐
│ ┌──────────┐                        │ │                      │
│ │          │  Spotify               │ │                      │
│ │  cover   │  make it to the end    │ │     [live map,       │
│ │  (print) │  Forrest Nolan         │ │      follows the     │
│ │          │                        │ │      truck]          │
│ └──────────┘                        │ │                      │
│ ▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▭▭▭▭▭▭▭▭▭▭▭▭▭▭▭ │ │                      │
│ 2:43                           3:31 │ │                      │
│          [⏮]  [ ⏸ ]  [⏭]            │ │                      │
└─────────────────────────────────────┘ └──────────────────────┘
┌──────────────────────────────────────────────────────────────┐
│ BOOST -5.9 psi   COOLANT 140 °F   BATTERY 14.3 V   SPEED 34   │
└──────────────────────────────────────────────────────────────┘

Music (full screen, no status bar)
┌────────────────────────┐ ┌──────────────────────────────────┐
│ Spotify      [⇄][↻][≡] │ │ [Up next | Albums | Spotify]     │
│     cover (print)      │ │ Up next on Spotify               │
│ make it to the end     │ │ would you like to go on a date…  │
│ Forrest Nolan          │ │ …                                │
│ ▬▬▬▬▬▬▬▬▭▭▭▭ 2:43 3:31 │ │                                  │
│   [⏮]   [  ⏸  ]   [⏭]   │ │                                  │
│ [−] ▮▮▮▮▮▮▮▯▯▯▯▯ 40 [+] │ │                                  │
└────────────────────────┘ └──────────────────────────────────┘
```

Truck: the page title is the truck's name; the readouts sit in the same card
strip as Home.

## States

| State | Look |
|---|---|
| Pressed | Fill steps up one level (Olive → Moss → Contour) and scales to 0.97, like key travel |
| Selected | Blaze fill inside a segmented control, or a Blaze bar plus Blaze icon in the nav |
| Primary | The one main key per screen (play/pause, Pair phone) is Blaze with a Basin icon |
| Warning | Ember numerals and segments; the redline's unlit segments are Ember at 30 %. An engine warning from the car is an Ember chip with a Basin icon and reading at the foot of the nav rail, on every page |
| Disabled | 50 % opacity |

## Motion

One deliberate moment per action: keys travel when pressed, pages crossfade,
needles and segments ease to new readings. No idle animation on the music
screens.
