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
  for evaluation. We ask TomTom before relying on it. If they say no, we go
  without live traffic, or check traffic on the phone.
- **Internet:** the phone's Wi-Fi hotspot first, Bluetooth tethering as backup,
  car Wi-Fi later.
- **GPS:** a GT-U7 (u-blox 7) USB module for development; upgrade to an enclosed
  u-blox 8 puck if city reception is poor.
- Bluetooth audio from the phone and local files stay as fallbacks.

## Where things stand

Running on the Pi 5: dashboard (Home, Music, Maps placeholder, Gauges, Truck,
Settings), four styles, settings saved, network status, 55-60 fps, Baja OS boot
screen, start at boot, local music, Bluetooth phone audio with track info and
two-way volume.

Known issues:

- **Bug:** a Python crash exits with code 1, which the service treats as a
  normal stop (`SuccessExitStatus=1` with `Restart=on-failure`), so the
  dashboard would not come back after a crash.
- **Brightness:** only software dimming on the Pi 5. The backlight stays fully
  on, so the screen glows at night.
- **Truck page:** stalls about 3 s the first time it opens.
- **No GPS yet.**
- **Vehicle data is simulated.**

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
  - Feeds position, speed (for the "moving or parked" decision) and heading.
  - chrony uses it for the clock, along with the Pi 5 RTC battery, so the clock
    is right with no internet.
- **Brightness:** load `i2c-dev` and find DDC/CI on the Pi 5. Real backlight
  dimming down to near-off, plus a screen-off action. Required before night
  driving.
- **Pages load on demand:** load heavy pages (Truck, later Map) the first time
  they're opened, and preload the 3D model during the splash.
- **Secrets file:** `/data/baja-os/secrets.json`, never in git.
- **Deploy script:** `deploy/push.sh` syncs to the Pi and restarts it.

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
  re-links while parked.
- **While moving:** only pinned and recent items and big playback controls. No
  search and no long scrolling lists.

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
- **Look:** styles matching each Baja OS style, day and night (night is light
  text on dark). Flat 2D while moving. Follow mode, recentre, and smooth motion
  between GPS updates.
- **Attribution:** "© OpenStreetMap contributors" on the map.
- **Traffic overlay (optional):** TomTom flow tiles, only if TomTom approves in
  writing.

### S4a. Basic navigation

- **Routing:** Valhalla on the Pi, with routing data for Washington (and maybe
  Oregon, Idaho and BC) built on the Mac using the same version.
- **Destinations:**
  - Saved places (home, work) and recent places.
  - Offline address and place search, from an index built on the Mac.
  - "Send to Baja": share a place from the phone.
- **Guidance:**
  - Next-turn banner with distance countdown, progress, ETA, off-route
    detection and rerouting.
  - One route and turn model, so a different routing provider can be swapped in
    later.
- **Voice:**
  - Piper, a persistent process with the voice loaded, using public-domain
    voices (kristin or norman).
  - Music ducks under prompts.
  - "Repeat last instruction" on the knob.

**Done when:** you can drive a familiar route and a new one with the
dashboard alone, including a missed turn, in airplane mode.

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
- Hands-free calls (HFP) with a microphone and echo cancellation; at minimum,
  duck the music during calls.

---

## Hardware track

All 12 V signals into the RP2040 (ignition, dimmer, speed sensor, parking
brake, reverse) go through opto-isolators. Relay coils are driven by a
transistor with a flyback diode.

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
  - **Parking brake input:** "parked" means brake on and under 5 mph. If speed
    is unknown, treat the truck as moving.
  - **Reverse input:** duck audio in reverse; an optional backup camera later.
  - Lower-panel buttons for play/pause, skip and mute (the Baja has no
    steering-wheel controls).
- **H3. Real vehicle data:**
  - The OBDLink EX replaces the simulated data and GPS speed.
  - Stop OBD polling before shutdown so the adapter sleeps.
  - Later, the speed/tach tap through the RP2040.
- **H4. Car power:**
  - Wide-input 12 V→5 V 5 A converter with transient protection, plus
    `usb_max_current_enable=1`.
  - Ignition sense with debounce, so cranking (when the accessory feed drops)
    doesn't trigger a shutdown.
  - Clean shutdown on key-off, then **cut all 12 V power** to the Pi, amp,
    RP2040, LED ring and OBD adapter. Set `POWER_OFF_ON_HALT=1`.
  - Target: measured key-off drain in single-digit mA.
  - Check the clock and chimes still work with the radio unplugged.
- **H5. Mount and enclosure:**
  - Print in ASA, not PETG, for anything in the sun; metal hinge hardware and
    heat-set inserts.
  - Detented or lockable friction hinges, and strain relief on the HDMI and USB
    cables.
  - Clear of the passenger airbag and its deployment path, the vents and the
    hazard switch. Within 30° below the driver's line of sight.
  - The Pi mounts low in the radio cavity, not in the pod, because it's rated
    to 50 °C and slows itself down past about 80 °C.
  - Active cooler; high-endurance SD card or NVMe.
  - Anti-glare film or a small hood for daylight.
- **H6. Optional:** microphone (calls and voice), backup camera, FM tuner, u-blox
  8 GPS puck.

---

## Safety and driving rules

Based on NHTSA's visual-manual driver distraction guidelines:

- **Moving vs parked:** "parked" means the parking brake is on and speed is
  under 5 mph. If speed is unknown, the truck counts as moving.
- **Blocked while moving:**
  - Typing.
  - Video, including the Truck page's animation.
  - Scrolling text and long lists.
  - 3D or tilted maps.
- **Glance limits:** every task you can do while driving must fit within 2 s per
  glance and 12 s in total.
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

1. **TomTom:** do you want me to draft a short email asking for written
   permission (personal, non-commercial, one vehicle) to use traffic tiles and
   search in the car?
2. **Calls:** add a microphone and hands-free calling (S6), or keep calls on the
   phone?

Answered 2026-10-14: Spotify Premium; buy the GPS (GT-U7); internet is the
hotspot first, Bluetooth tethering second.

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
