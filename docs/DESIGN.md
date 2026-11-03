# Baja OS design: Trail

Trail is the default and the reference style. The other styles (Cluster,
Rally, Amber) reuse the same structure with their own tokens.

**Concept: a switch panel bolted onto a topo map.** Matte, printed, utility:
olive panels with chunky borders, sand lettering, one safety-orange for what's
live or selected, and contour lines in the gutters. Nothing glows. The only
full-colour things on screen are the album cover, the 3D truck and the map
itself; everything over the map is Trail (see Map).

## Palette (Trail, night)

| Name | Hex | Used for |
|---|---|---|
| Basin | `#14160f` | Window background and gutters (with the topo lines) |
| Olive | `#1e2118` | Cards, always opaque |
| Moss | `#2c3123` | Idle keys, the active nav plate, pressed cards |
| Contour | `#4a4a35` | Every border, track, empty segment and contour line |
| Sand | `#e9dfc4` | Text and numerals |
| Lichen | `#9c9478` | Captions, units, times |
| Blaze | `#ff7a1a` | Selected or active state, the one primary key per screen, fills you set or that move (progress, levels), the leading block of a gauge |
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
| Hero | 56 DemiBold | Place names (Maps), the track title on Music, the Baja OS title in Settings |
| Title | 40 DemiBold | The truck's name, track titles (Home), card titles |
| Body | 30 Book | Artists, list rows, settings text |
| Small | 24 Book, Lichen | Times, units, secondary lines |
| Legend | 20 DemiBold, caps, tracking 2, Lichen | Instrument legends only: gauge and readout labels (RPM, BOOST) and nav labels |

The map's own labels are Overpass (after US highway-sign lettering, as glyphs
in `web/map`). Every other label, the cards over the map included, is the
style's font.
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

The map itself looks like Apple Maps, so it reads at a glance and matches the
car maps people know. It has its own fixed day and night palettes (in
`web/map/map.js`), not the style's tokens. It follows day/night with the rest
of the dashboard. Everything over it is Trail.

- **Full screen beside the rail** on Maps. On Home the same map sits small in a tile with the standard
  radius and border, and any tap opens Maps.
- **Colours:** day is warm off-white land, pale-blue water, soft-green parks,
  white streets with amber highways; night is charcoal land, deep-blue water,
  dark-green parks, grey streets with dim amber highways.
- **The route is blue** (`#1a7cf5` day, `#2f8cff` night, with a darker casing);
  the destination pin is red. Nothing else on the map is that colour.
- **Labels in Overpass,** scaled 1.1 to 1.35x the stock size (roads largest) so
  they read at arm's length. Roads are drawn 1.25x wider.
- **No coloured POI icons;** POI names only, in grey.
- **Cards over the map are Trail cards:** Olive with the 2 px Contour border
  and radius 6, on the album cover's hard offset shadow so they stand off a
  busy map. Blaze for what's active and for **Go**, Ember for **End** and for
  a speed over the limit. The next turn is on the night Olive card in both
  modes, so it's the clearest thing on screen by day too. The speed-limit
  sign stays a real sign (white, black border).
- **Keys:** one strip on the bottom right (zoom only after touching the map,
  overview and spoken directions while navigating, recentre), the speed limit
  and speed on the right, and a small "© OpenStreetMap" credit beside the keys.

## Layout

There is no status bar: the highlighted rail key says which page this is, so
every page gets the full height. The rail carries what must show on every
page: the clock at the top, **Demo** under it (Blaze legend) while the engine
data is made up, and at the foot an engine warning (see States) or, while
driving a route, the next turn (a framed chip, Blaze arrow and distance) on
the pages that don't show it themselves (Gauges, Truck, Settings). A warning
takes the turn chip's place. Tap either to go to Gauges or Maps.

Pages sit 20 px in from the rail and the window edges. All card content is
inset 20 px. Gutters between cards are 14 px.

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

Music, Playing (full screen, no status bar)
┌────────────────────────────────────────────────────────────┐
│ [Playing | Up next | Albums | Spotify]      [turn, if any] │
└────────────────────────────────────────────────────────────┘
┌────────────────────────────────────────────────────────────┐
│ ┌────────────────────┐  Spotify                            │
│ │                    │  make it to the end                 │
│ │                    │  Forrest Nolan                      │
│ │   cover (print)    │  Next  would you like to go on…  ≡  │
│ │                    │  ▬▬▬▬▬▬▬▬▬▬▬▭▭▭▭▭▭▭▭                │
│ │                    │  2:43                          3:31 │
│ │                    │  [  ⏮  ]  [    ⏸    ]  [  ⏭  ]      │
│ └────────────────────┘                                     │
│ [ ⇄ ]  [ ↻ ]  [ ≡ ]     [−] ▮▮▮▮▮▮▮▯▯▯▯▯ 40 [+]            │
└────────────────────────────────────────────────────────────┘

Music, browsing (Up next, Albums, Spotify)
┌────────────────────────────────────────────────────────────┐
│ [Playing | Up next | Albums | Spotify]      [turn, if any] │
└────────────────────────────────────────────────────────────┘
┌────────────────────────────────────────────────────────────┐
│ five covers across, or a list                              │
└────────────────────────────────────────────────────────────┘
┌────────────────────────────────────────────────────────────┐
│ [▣] make it to the end        [⏮] [⏸] [⏭]  [−] [+]         │
└────────────────────────────────────────────────────────────┘
```

Truck: the truck's name at the top; under the truck, this trip since start-up
(distance, driving time, average speed, peak boost) in the same card strip as
Home's readouts.

Music: the cover takes whatever height is left on the card (up to 320 px), so
the keys and volume always fit.

## States

| State | Look |
|---|---|
| Pressed | Fill steps up one level (Olive → Moss → Contour) and scales to 0.97, like key travel |
| Selected | Blaze fill inside a segmented control, or a Blaze bar plus Blaze icon in the nav |
| Primary | The one main key per screen (play/pause, Pair phone) is Blaze with a Basin icon |
| In range (gauges) | Lit segments in Lichen with only the leading one in Blaze, like a needle's tip, so six healthy gauges read as calm and a bad one stands out |
| Warning | Ember numerals and segments; the redline's unlit segments are Ember at 30 %. An engine warning from the car is an Ember chip with a Basin icon and reading at the foot of the nav rail, on every page |
| Disabled | 50 % opacity |

## Motion

One deliberate moment per action: keys travel when pressed, pages crossfade,
needles and segments ease to new readings. No idle animation on the music
screens. The gauges sweep once to full scale and back the first time Gauges
opens, like a cluster's key-on test.
