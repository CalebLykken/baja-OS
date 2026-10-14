# Baja OS design: Trail

Trail is the default and the reference style. The other styles (Cluster,
Rally, Amber) reuse the same structure with their own tokens.

**Concept: a switch panel bolted onto a topo map.** Matte, printed, utility:
olive panels with chunky borders, sand lettering, one safety-orange for what's
live or selected, and contour lines in the gutters. Nothing glows. The only
full-colour things on screen are the album cover and the 3D truck.

## Palette (Trail)

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

No colour is extracted from album art to drive the UI, and no brand colours are
used. Sources are named in text ("Spotify").

## Type (URW Gothic only)

| Token | Size / weight | Used for |
|---|---|---|
| Gauge numeral | auto, Bold | Gauge centres |
| Readout | 40 Bold | Readouts and the status-bar numbers |
| Hero | 40 DemiBold | Track title on the Music page |
| Title | 30 DemiBold | Page titles, track title on Home, card titles |
| Body | 22 Book | Artists, list rows, settings text |
| Small | 16 Book, Lichen | Times, units, secondary lines |
| Legend | 15 DemiBold, caps, tracking 2, Lichen | Instrument legends only: gauge and readout labels (RPM, BOOST) and nav labels |

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
  2 px Contour border and a hard offset shadow (Basin at 60 %, +6 px right,
  +8 px down). No glow, no blur.
- **No cover:** a Moss tile with a Lichen icon.
- **No album backdrop.** The topo map is the constant background on every page.

## Layout

All card content is inset 20 px. Gutters between cards are 14 px.

```
Home
┌─────────────────────────────────────┐ ┌──────────────────────┐
│ ┌──────────┐                        │ │                      │
│ │          │  Spotify               │ │        [map]         │
│ │  cover   │  make it to the end    │ │        Maps          │
│ │  (print) │  Forrest Nolan         │ │  An offline map of   │
│ │          │                        │ │  Seattle is coming   │
│ └──────────┘                        │ │  next                │
│ ▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▭▭▭▭▭▭▭▭▭▭▭▭▭▭▭ │ │                      │
│ 2:43                           3:31 │ │                      │
│          [⏮]  [ ⏸ ]  [⏭]            │ │                      │
└─────────────────────────────────────┘ └──────────────────────┘
┌──────────────────────────────────────────────────────────────┐
│ BOOST -5.9 psi   COOLANT 140 °F   BATTERY 14.3 V   SPEED 34   │
└──────────────────────────────────────────────────────────────┘

Music
┌────────────────────────┐ ┌──────────────────────────────────┐
│                        │ │ Spotify                          │
│     cover (print)      │ │ make it to the end (Hero)        │
│                        │ │ Forrest Nolan                    │
│                        │ │ ▬▬▬▬▬▬▬▬▬▬▬▬▭▭▭▭        2:43 3:31 │
│                        │ │      [⏮]   [  ⏸  ]   [⏭]         │
│                        │ │ [−] ▮▮▮▮▮▮▮▮▯▯▯▯▯▯ 40 [+]       │
└────────────────────────┘ ├──────────────────────────────────┤
                           │ Up next on Spotify               │
                           │ would you like to go on a date…  │
                           └──────────────────────────────────┘
```

Truck: the page title is the truck's name; the readouts sit in the same card
strip as Home.

## States

| State | Look |
|---|---|
| Pressed | Fill steps up one level (Olive → Moss → Contour) and scales to 0.97, like key travel |
| Selected | Blaze fill inside a segmented control, or a Blaze bar plus Blaze icon in the nav |
| Primary | The one main key per screen (play/pause, Pair phone) is Blaze with a Basin icon |
| Warning | Ember numerals and segments; the redline's unlit segments are Ember at 30 % |
| Disabled | 50 % Lichen |

## Motion

One deliberate moment per action: keys travel when pressed, pages crossfade,
needles and segments ease to new readings. No idle animation on the music
screens.
