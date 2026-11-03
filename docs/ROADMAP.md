# Baja OS roadmap

Revised 2026-10-14 after three reviews: technical feasibility, services and
terms, and in-car safety and hardware. What changed, and why, is at the end.

## Decisions

- **Spotify built in** (instead of CarPlay), using Spotify's official headless
  player, **Soloist**. The open-source **go-librespot** is the fallback.
  Spotify is **Premium**.
- **Maps run on OpenStreetMap stored on the Pi**, with routing by **Valhalla**
  on the Pi. This works with no signal and has no licence limits for personal
  use.
- **TomTom is optional, for live traffic and search, and only with written
  permission.** Its standard developer terms reportedly exclude in-vehicle use
  and turn-by-turn navigation unless TomTom agrees in writing; the free tier is
  for evaluation. We're asking TomTom in writing (draft in
  `docs/tomtom-request.md`). If they say no, we go without live traffic, or
  check traffic on the phone.
- **Internet:** the phone's Wi-Fi hotspot first, Bluetooth tethering as backup,
  car Wi-Fi later.
- **GPS:** a GT-U7 (u-blox 7) USB module for development; upgrade to an enclosed
  u-blox 8 puck if city reception is poor.
- Bluetooth audio from the phone and local files stay as fallbacks.
- **Calls stay on the phone** (decided 2026-10-14): no microphone or
  hands-free calling; the Pi stays a music receiver only (A2DP).
- **No parked/moving lockouts** (decided 2026-10-14): this is a personal
  project, so typing, lists and 3D stay available all the time. Big
  driving-mode sizes, the hardware mute and night dimming stay.

## Where things stand

Running on the Pi 5: dashboard (Home, Music, Maps, Gauges, Truck, Settings),
four styles with Trail as the default, settings saved, network status, 55-60
fps, Baja OS boot screen, start at boot, crash and freeze recovery (service
watchdog plus the Pi's hardware watchdog), local music, Bluetooth phone audio
with track info and two-way volume, Spotify through Soloist, an offline
map of the Seattle area, a 5-band equalizer, Wi-Fi joining from Settings with
an on-screen keyboard (for the phone's hotspot) and Bluetooth tethering as the
backup, and Settings in sections (display, sound, Wi-Fi, Bluetooth, map,
system health and power, about) with working units and clock options.

Known issues:

- **Brightness:** only software dimming on the Pi 5. The backlight stays fully
  on, so the screen still glows a little at night. It does now dim by itself
  after sunset (the sun's position where the truck is) to a saved night
  level, and back to the daylight level after sunrise.
- **No working GPS receiver yet:** the first one never got a fix and is going
  back. gpsd and the map are ready for a replacement; until then the map
  follows a simulated drive around Seattle, but only on a Mac, a bench Pi or
  with --demo, never once the car has answered.
- **Vehicle data is real once the OBD-II adapter answers.** Until the car has
  answered on this install (a Mac, a bench Pi, or --demo) the gauges show a
  simulated drive.

## Milestone M1: first drive

The first time Baja OS replaces the factory radio for real driving. It needs
exactly:

- **Software:** S0 and S1 (Spotify), plus Bluetooth audio (done).
- **Hardware:** H1 (audio), H2 (knob with hardware mute), H4 (car power and
  safe shutdown) and H5 (secure mount).
- **Before it counts:** read-only system files switched on (from S0), hardware
  brightness dimming working, and the whole system bench-tested on a fused 12 V
  supply before the factory radio comes out.

Until S4, navigation stays on the phone in a phone mount.

---

## Software track

### S0. Foundations

The groundwork every later phase depends on, done first.

- **Fix the service bug:** `Restart=always`, a systemd watchdog the app pings,
  and the Pi's hardware watchdog. A crash brings the dashboard back within
  seconds.
- **Where saved data lives:**
  - Make an ext4 `/data` partition (or use the NVMe) and move everything that
    must survive a reboot onto it. That covers Bluetooth pairings
    (`/var/lib/bluetooth`), Wi-Fi connections, `~/.config/baja-os`,
    WirePlumber state, Spotify tokens and player state, and maps.
  - Prepare the read-only overlay for the system files (`overlayroot`, leaving
    `/data` writable), and test it on this Pi 5. Switch it on for M1.
- **Connectivity:**
  - The phone hotspot is the main connection, with Bluetooth tethering as
    backup. Both retry forever, plus a watchdog that brings them back up.
  - Use NetworkManager's own connectivity check as the app's "online" signal.
  - Test with the phone locked in a pocket. Done when the Pi is online within
    about a minute with no phone handling.
- **GPS, moved up from S3:**
  - gpsd with the GT-U7 on a USB 2 port, with u-blox settings re-applied at
    every boot (automotive mode, update rate).
  - Feeds position, speed (shown until OBD-II arrives) and heading.
  - chrony uses it for the clock, along with the Pi 5 RTC battery, so the clock
    is right with no internet.
- **Brightness:** load `i2c-dev` and find DDC/CI on the Pi 5. Real backlight
  dimming down to near-off, plus a screen-off action. Required before night
  driving.
- **Pages load on demand:** load heavy pages (Truck, later Map) the first time
  they're opened, and preload the 3D model during the splash. Done
  differently: the Truck page's 7 s first-open freeze was Qt filtering the
  studio lighting on the CPU, so it now loads a pre-filtered cubemap (70 ms);
  the map starts in the background 6 s after start-up.
- **Secrets file:** `/data/baja-os/secrets.json`, never in git.
- **Deploy script:** `deploy/push.sh` syncs to the Pi and restarts it. Done.

**Done when:** pulling the plug and rebooting 20 times loses nothing; a forced
crash recovers by itself; the Pi gets online and gets a GPS fix with no phone
handling.

### S1. Spotify playback

- **Spike first, both players on your account:**
  - Soloist, Spotify's official player. It needs a key from the Spotify
    developer dashboard, and builds expire after 90 days.
  - go-librespot, the open-source fallback. Spotify has been refusing audio to
    it on some accounts since late 2025.
  - Keep whichever works reliably. `push.sh` fetches a fresh Soloist build
    before it expires, and the binary never goes in git.
- **Run it** as a service in the user audio session, with its control API
  reachable only from the Pi itself.
- **Media hub `spotify` source:** title, artist, album art (with the colour and
  backdrop treatment), progress, play, pause, skip, seek and volume. Show
  Spotify attribution.
- **Source rules:**
  - The most recently started source takes over.
  - After the phone reconnects over Bluetooth, ignore its "playing" events for
    about 10 s, because iPhones auto-resume and would otherwise pause Spotify.
- **Audio routing for later voice prompts:** all music goes into a "music" sink
  whose volume the hub can lower; prompts go straight to the output.
- **Streaming quality setting:** Normal (about 70 MB/h) on mobile data.

**Done when:** "Baja" appears in the Spotify app; playback continues with the
phone locked; the dashboard controls work; it comes back after a reboot.

### S2. Spotify library on the dashboard

- **Browse through the player where possible:** playlists, Liked Songs, albums
  and the current context. This avoids most of the Web API's 2026 limits.
- **Spotify Web API only for search:**
  - Developer-mode limits: the app owner needs Premium; up to 5 users; 10
    search results per page; playlist track lists only for playlists you own or
    collaborate on. Followed playlists still play by their link.
  - Respect rate limits and back off when Spotify says so.
- **Sign-in on the Pi** with a QR code (loopback redirect rules permitting).
  Spotify sign-ins expire after 6 months; the dashboard warns ahead of time and
  re-links from the dashboard.

### S3. Live map

- **Base map:** OpenStreetMap for Washington, stored on `/data` (Protomaps /
  MBTiles), with fonts and icons stored locally too. Works with no signal.
  Keep a local copy of the extract.
- **Map engine, decided by a spike:**
  - First choice: MapLibre Native's Qt plugin. It runs inside the app with the
    least memory, but needs compiling for the Pi; hold the Qt package versions
    so updates don't break it.
  - Pass criteria: at least 30 fps in tilted follow mode, under 250 MB extra
    memory, cold start under 2 s, also checked after the Truck page has been
    opened.
  - Fallback after about 2 days: MapLibre GL JS in Qt WebEngine (check hardware
    WebGL works under eglfs).
  - Last resort: raster tiles through QtLocation.
- **Spike result (2026-10-14): MapLibre GL JS in Qt WebEngine, kept.** It was
  already installed and WebGL runs on the Pi 5's GPU (V3D 7.1) under eglfs, so
  it was measured first. On the Pi 5, with the Seattle-area extract:
  - Cold start, page opened to map drawn: 0.99 s (target under 2 s).
  - Tilted follow mode at 30 m/s, zoom 16.5, pitch 60: 59.5 fps, 95th
    percentile frame 16.8 ms, no frames over 50 ms (target 30 fps). The same
    after opening the Truck page: 59.6 fps.
  - Memory over the Home screen: +220 MB with the map open, +284 MB while
    following (target 250 MB). A smaller tile cache didn't change it; it's the
    web engine's own processes. With 7.4 GB free on the 8 GB Pi this is
    acceptable, so MapLibre Native isn't worth two days of compiling now.
    Revisit only if memory becomes a problem.
- **Look:** styles matching each Baja OS style, day and night (night is light
  text on dark). Follow mode, recentre, and smooth motion between GPS updates.
  Done so far: the map's palette is derived from the current style's tokens
  and recolours live when the style changes; labels are drawn 1.4x for arm's
  length reading; the truck is a Blaze arrow that glides between fixes;
  follow mode (tilted, heading-up, truck low on screen, zooming out with
  speed, shop labels hidden) starts with the first fix, stops when the map
  is touched and comes back with the follow key; a speed chip sits on the
  map. In demo mode (no GPS receiver and no engine data) the truck drives
  a 20 km loop through Seattle (backend/demo_route.json). gpsd is installed and
  read by backend/gps.py; it needs the GT-U7 plugged in to be tested.
- **Attribution:** "© OpenStreetMap contributors" on the map.
- **Traffic overlay (optional):** TomTom flow tiles, only if TomTom approves in
  writing.

### S4a. Basic navigation

- **Routing:** Valhalla on the Pi, with routing data for Washington (and maybe
  Oregon, Idaho and BC) built on the Mac using the same version.
  - Done differently: the pyvalhalla wheel (3.9.0, pinned and hash-checked)
    runs Valhalla in user space on the Pi, no sudo, and builds Washington's
    road graph on the Pi itself (`deploy/maps/install-routing.sh`: 365 MB
    download, 549 MB graph). It runs as a user service on 127.0.0.1:8002
    only; a 5.5 km city route takes 0.22 s.
- **Destinations:**
  - Done: offline search of everything named in the map (about 51,000
    businesses and places plus every street, indexed in 16 s on the Pi,
    searches in under 20 ms), with results ranked by name match and
    distance, a pin, and the truck and the place framed together.
  - Saved places and recent places. Done: Home (set from the destination
    card) and the last six places picked, listed when the search box is
    empty. Work is still to do.
  - Offline address and place search. Done for places, businesses and
    streets (house-number addresses aren't in the map tiles).
  - "Send to Baja": share a place from the phone.
- **Guidance:**
  - Next-turn banner with distance countdown, progress, ETA, off-route
    detection and rerouting. Done: banner with the turn arrow and countdown,
    arrival time with time and distance left, the driven part of the line
    trimmed away, a new route after three fixes more than 60 m off it, the
    next turn at the foot of the nav rail on the other pages (tap it for the map) and
    on the Home map tile. In demo mode the simulated truck drives the route.
  - One route and turn model, so a different routing provider can be swapped in
    later.
- **Voice:**
  - Piper, a persistent process with the voice loaded, using public-domain
    voices (kristin or norman). Done (`deploy/audio/install-voice.sh`, kristin;
    loads in 2.3 s once, then 0.5 s a line on the Pi): the route's first
    step, a warning a quarter mile (or a mile at highway speed) before each
    turn, the turn about six seconds before it, rerouting and arrival.
  - Music ducks under prompts. Done: the other audio streams dip to 30% and
    come back to exactly where they were; Spotify's own volume never moves.
  - "Repeat last instruction" on the knob.

**Done when:** you can drive a familiar route and a new one with the
dashboard alone, including a missed turn, in airplane mode.

**Redesign (2026-10-14), from research on CarPlay, Android Auto, Google
Maps, Apple Maps and Waze, NHTSA's glance guidelines and ISO 15008:**
full-screen map beside the rail with the clock in the rail; light by day
and dark at night for the whole dashboard (by the sun, or Settings); a
simplified warm-neutral map palette with a blue route; Overpass (highway-sign lettering) for the map labels and controls,
with glyphs made by tools/make_glyphs.py; type and keys sized for 70-90 cm;
search panel with Home, recents and categories; street-address search
(910,000 addresses from OpenStreetMap); route preview with Go at the bottom;
turn card top-left, arrival bottom-left; speed limit (Valhalla map
matching) and speed on the right; traffic lights, stop and yield signs;
overview, voice and follow keys in one strip; Re-center, automatic after
10 s while driving a route; the route draws itself in; a live mini-map on
Home; destinations sent from the iPhone (Shortcut or QR page). Voice stays
off by default, at the owner's request.

### S4b. Navigation polish

- Lane hints and better maneuver wording.
- Live traffic and faster-route offers that need no tap, if TomTom approves.
  Otherwise, use the phone for traffic-heavy trips.
- Online place search: TomTom Suggest if approved, otherwise an OSM-based
  service.

### S5. Resilience

- Switch on the read-only overlay. It is required for M1, prepared in S0.
- Data-use counter and a monthly cap; maximum map zoom capped to limit data.
- Fall back to offline gracefully when any online service fails or hits a
  limit (HTTP 429).

### S6. Polish

- A combined Home view: now playing plus the next turn.
- Voice commands for maps only. Spotify's developer policy bans voice control
  of Spotify.
- Optional FM radio (USB tuner or RTL-SDR), to replace the factory radio and
  for emergency broadcasts.

---

## Hardware track

All 12 V signals into the RP2040 (dimmer, speed sensor, reverse) go through
opto-isolators. Relay coils are driven by a transistor with a flyback diode.

- **H1. Audio:**
  - DAC HAT as the default output.
  - TDA7850 amp on **its own fused feed from the source**, through a 30/40 A
    automotive relay, not the shared 15 A radio fuse.
  - The amp switches on after the Pi is up, to avoid a turn-on thump.
  - Star ground; speaker negatives stay floating (the amp's outputs are
    bridged).
  - Whine test with the engine running across the RPM range; a ground loop
    isolator in reserve.
- **H2. Controls and safety inputs (RP2040):**
  - EC11 knob and LED halo. The halo follows the dash dimmer and stays dim at
    night.
  - **Hardware mute:** the RP2040 drives the amp's mute/standby pin directly.
    It mutes on a long-press of the knob, or by itself if the Pi stops sending a
    heartbeat.
  - **Reverse input:** duck audio in reverse; an optional backup camera later.
  - Lower-panel buttons for play/pause, skip and mute (the Baja has no
    steering-wheel controls).
- **H3. Real vehicle data:**
  - The OBDLink EX replaces the simulated data and GPS speed.
  - Stop OBD polling before shutdown so the adapter sleeps.
  - Later, the speed/tach tap through the RP2040.
- **H4. Car power and safe shutdown** (replanned 2026-10-20: the CarPiHAT
  PRO 5 power board is no longer sold, so it's built from screw-terminal
  modules; wiring in the README, under Wiring):
  - **Relay:** a 12 V off-delay relay feeds the Pi's converter from an
    always-on feed (a fuse tap on an always-on fuse, or harness yellow; 5 A
    fuse) while the key is on (the cigarette lighter's wire, tapped), and
    holds about 2 minutes after key-off. The Pi is off the amp's circuit.
  - **Converter:** 12 V→5 V 5 A with USB-C, with transient protection. It
    doesn't do USB PD, so the bootloader is told it's a 5 A supply:
    `PSU_MAX_CURRENT=5000` (USB gets 1.6 A, not 600 mA; replaces
    `usb_max_current_enable=1`). Plus `POWER_OFF_ON_HALT=1`, so a shut-down
    Pi draws about 0.01 W, not 1-1.4 W.
  - **Key sense (replanned 2026-10-22):** no module: the OBD adapter. The
    engine computer goes quiet when the key goes off; after 15 s of quiet
    the dashboard counts down 10 s with Keep on, then runs `systemctl
    poweroff` (`backend/ignition.py`, in the dashboard, which owns the
    adapter). Not before the car has answered once, not when the adapter
    is unplugged, not while moving (the car's last speed or the GPS). Off
    until turned on in Settings > System. Limit: ACC looks like off (the
    ECU is off at ACC); Keep on covers it. Done and tested on the Pi's
    screen without powering off; waiting on the relay.
  - **Amp:** stays on the harness (yellow to 12 V through its own fuse, red
    to REM), so it switches off with the key by itself. The OBD adapter
    sleeps by itself once polling stops (H3).
  - Known limit: if the key comes back on during a shutdown, the Pi stays
    off until the relay drops out (key off for its hold time) or its power
    button is pressed.
  - Bench test on a fused 12 V supply: key-off shutdown, a 2-3 s drop like
    cranking, and the key back on mid-shutdown.
  - Target: measured key-off drain in single-digit mA (mostly the relay
    module's standby current: check it).
  - Check the clock and chimes still work with the radio unplugged.
- **H5. Mount and enclosure:**
  - Print in ASA, not PETG, for anything in the sun; metal hinge hardware and
    heat-set inserts.
  - Detented or lockable friction hinges, and strain relief on the HDMI and USB
    cables.
  - Clear of the passenger airbag and its deployment path, the vents and the
    hazard switch. Within 30° below the driver's line of sight.
  - The Pi goes somewhere cooler than the pod, out of direct sun, with its
    active cooler fitted (done). It slows itself down past about 80 °C, so check
    temperatures on a hot day.
  - High-endurance SD card or NVMe.
  - Anti-glare film or a small hood for daylight.
  - Done so far (2026-10-15): a test-fit version in `hardware/case/`: a
    panel for the radio part of the bezel opening (the climate controls stay
    below it), the screen fixed on four posts, the volume knob under it, a Pi
    case on the back with the amp on a plate behind it (2026-10-20), and four
    slotted adapter plates for Subaru's radio brackets (66201AE17A/18A). Built by a Fusion script with every size a
    named parameter; the bracket spacing and hole positions still need
    measuring after the test print.
- **H6. Optional:** backup camera, FM tuner, u-blox 8 GPS puck.

---

## Safety and driving rules

Informed by NHTSA's visual-manual driver distraction guidelines (written for
manufacturers; this personal build skips their parked/moving lockouts):

- **Driving-mode sizes:**
  - Touch targets at least about 90 px (about 12 mm on this panel).
  - Main text at least about 38 px, secondary text at least about 28 px.
  - Contrast at least 4.5:1.
  - Today's 76 px targets and 22/16 px text are too small.
- **Always reachable:** volume and full mute, including when the Pi has
  crashed, through the RP2040.
- **At night:** real backlight dimming, nothing bright on boot or error screens,
  and a screen-off action.
- **The phone:** zero handling on the road. Connecting, Spotify and navigation
  all work with the phone in a pocket.

## Services, terms and cost

| Service | Use | Terms | Cost |
|---|---|---|---|
| Spotify Soloist | Playback | Official; developer key per user; builds expire every 90 days; no redistribution | Premium |
| go-librespot | Fallback player | Unofficial; Spotify blocking on some accounts | Free |
| Spotify Web API | Search | Developer mode: owner Premium, 5 users, 10 results per page; 6-month sign-in | Free |
| OpenStreetMap / Protomaps | Base map | ODbL attribution | Free |
| Valhalla | Routing | MIT | Free |
| Piper voices | Speech | GPL-3 code; use public-domain voices (kristin, norman) | Free |
| TomTom (optional) | Traffic, online search | **Needs written permission for in-car use**; free tier is for evaluation; no offline caching; keep separate from OSM data; "© TomTom" attribution | 200K tiles, 20K routes, 10K suggest per month free |
| Mobile data | Streaming, traffic | — | ~70 MB/h Spotify (Normal) + ~10-60 MB/h maps |

## Open decisions

None right now.

Answered 2026-10-14: Spotify Premium; buy the GPS (GT-U7); internet is the
hotspot first, Bluetooth tethering second; ask TomTom for written permission
(draft in `docs/tomtom-request.md`); calls stay on the phone; no
parked/moving lockouts; the Pi goes in a cooler spot with its active cooler.

---

## What changed after review

- **TomTom became optional.** Its standard terms reportedly exclude in-car use
  and turn-by-turn navigation without written permission. We could not read the
  clause text directly, but TomTom's docs put automotive navigation outside the
  free plan. Maps and routing moved to OpenStreetMap and Valhalla on the Pi.
- **Spotify uses the official Soloist player** (released Aug 2026), with
  go-librespot as the fallback, because Spotify has been blocking go-librespot
  on some accounts.
- **Spotify library comes mainly from the player,** because the Web API's
  2026 developer-mode limits are tight. Sign-in happens on the Pi, since tokens
  expire every 6 months.
- **Added an M1 "first drive" milestone** with the hardware and safety items
  real driving needs.
- **Moved the data partition, read-only prep, GPS, clock and real dimming into
  S0;** fixed the service-restart bug.
- **Added a hardware mute through the RP2040** that works if the Pi crashes, a
  parking-brake input for the "parked" definition, and reverse sensing.
- **Power:** the amp gets its own fused feed; cranking-safe ignition sensing;
  all 12 V cut after shutdown, with a key-off drain target.
- **Navigation split into S4a and S4b.** Offline search added, music ducking
  moved into the media hub, a reconnect guard against the iPhone auto-resuming,
  and public-domain voices.
- **Safety rules rewritten** against NHTSA's guidelines, with larger
  driving-mode sizes.
- **Follow-up (2026-10-14):** dropped the parked/moving lockouts and the
  parking-brake input at your request; calls stay on the phone (no microphone
  or hands-free calling); Pi placement is flexible since it has an active
  cooler.
- **Power, replanned (2026-10-20):** the CarPiHAT PRO 5 is no longer sold,
  so H4 uses screw-terminal modules: an off-delay relay for the Pi only (the
  amp keeps its own REM switching), a non-PD 5 V 5 A converter with
  `PSU_MAX_CURRENT=5000`, and the key sensed by the Pi through an
  optocoupler instead of by the RP2040.
- **Key sense, replanned (2026-10-22):** no optocoupler: the Pi learns the
  key is off from the car going quiet on the OBD adapter, and powers the Pi
  from its own feeds (the lighter wire for the key, an always-on fuse tap),
  so the amp keeps the radio harness to itself.
