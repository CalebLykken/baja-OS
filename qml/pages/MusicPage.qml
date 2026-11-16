import QtQuick
import QtQuick.Layouts
import "../components"
import "../components/AlphaIndex.js" as AlphaIndex

// The Music page, full screen like Maps (the clock moves into the rail).
//
// Tabs across the top, with the next turn beside them while navigating (tap
// it for Maps):
// - Playing: the music has the page. The cover, the song, the next song, the
//   keys and the volume; the equalizer key opens the EQ.
// - Up next (Spotify's queue, or the Pi's songs playing through); Albums (the
//   Pi's own music by album: open one to play it, or a song in it); Spotify
//   (albums and playlists played here recently, one tap to play again; your
//   playlists, albums and Liked Songs once linked by a QR code; and the search
//   key, which types over the bottom of the page like Maps). These keep a
//   player bar along the bottom; tap it to go back to Playing.
Item {
    id: page
    objectName: "musicPage"
    signal navigate(int index)

    property bool eqOpen: false
    property string tab: "playing"             // "playing", "next", "albums", "songs" or "spotify"
    property int openAlbum: -1                 // the album shown in Albums, or -1 for all of them
    property string albumView: "all"           // "all" or "recent" on the Albums tab (kept while the app runs)
    property var openKey: null                 // [artist, title] of the open album: a rescan can renumber albums
    property bool searchOpen: false            // the Spotify tab shows search rather than recents
    property string spotifyView: "recent"      // "recent", "playlists", "albums" or "liked"
    readonly property bool hasAccount: typeof spotifyAccount !== "undefined"

    // The artist, then the album: "Boxer Rebellion · Bed Liner Sessions".
    // "Unknown artist" (untagged files) is left out.
    function artistLine(artist, album) {
        var parts = []
        if (artist && artist !== "Unknown artist") parts.push(artist)
        if (album) parts.push(album)
        return parts.join(" \u00b7 ")
    }
    readonly property bool libraryView: spotifyView !== "recent"
    readonly property bool needsLink: libraryView && hasAccount && !spotifyAccount.linked
    property bool typing: false                // the keyboard is up
    property string query: ""
    onVisibleChanged: if (!visible) show("playing")     // always come back to the music
    Connections {
        target: media
        function onAlbumsChanged() {
            if (page.openAlbum < 0 || !page.openKey) return
            var list = page.albums, found = -1
            for (var i = 0; i < list.length; i++)
                if (list[i].artist.toLowerCase() === page.openKey[0].toLowerCase()
                        && list[i].title.toLowerCase() === page.openKey[1].toLowerCase()) { found = i; break }
            page.openAlbum = found      // closed if it's gone
        }
    }

    readonly property bool navigating: typeof routing !== "undefined" && routing.active
    // Each read of media.songs / media.albums makes Python rebuild the list, so
    // everything on the page shares one read per change.
    readonly property var albums: media.albums
    readonly property var songs: media.songs
    // The songs that play after this one, in the true order (a shuffle's too);
    // read once per change so the bindings below share it.
    readonly property var upNext: media.upNext
    readonly property bool idle: media.source === "local" && media.title === ""   // no music on the Pi, and the phone and Spotify aren't playing
    // What the Playing card says in its title while there is no song yet: nothing
    // on the Pi, the Pi's music still being read, or Spotify just starting.
    readonly property string titleText: idle ? (media.scanning ? "Reading your music" : "Nothing playing")
                                        : media.title !== "" ? media.title
                                        : media.source === "spotify" ? "Starting Spotify..." : ""
    // The one-line hint under it when the Pi has nothing to play, so the
    // owner knows what to do next rather than guessing.
    readonly property string idleHint: media.scanning ? "Songs show up as they're found"
                                                      : "Pair a phone in Settings, or copy songs to ~/Music"
    readonly property bool hasSpotify: typeof spotify !== "undefined" && spotify.available
    // Only while Spotify is what's playing or being looked at.
    readonly property string spotifyError: typeof spotify !== "undefined"
                                           && (media.source === "spotify" || page.tab === "spotify") ? spotify.error : ""

    readonly property bool browsing: tab !== "playing" || eqOpen
    readonly property int barHeight: 84
    // The song after this one, or null when there isn't one or it isn't known
    // (the phone doesn't say).
    readonly property var nextSong: page.upNext.length > 0 ? page.upNext[0] : null

    function show(which) {
        tab = which
        openAlbum = -1
        eqOpen = false
        closeSearch()
    }
    function closeSearch() {
        searchOpen = typing = false
        query = ""
        if (typeof spotifySearch !== "undefined") spotifySearch.clear()
    }
    function runSearch() {
        typing = false
        spotifySearch.search(query)
    }

    function mmss(s) {
        var m = Math.floor(s / 60), r = s % 60
        return m + ":" + (r < 10 ? "0" : "") + r
    }
    function albumLength(s) {
        var min = Math.round(s / 60)
        return min < 60 ? min + " min" : Math.floor(min / 60) + " h " + (min % 60) + " min"
    }

    ColumnLayout {
        anchors { fill: parent; margins: Theme.gap }
        spacing: Theme.gap

        // ==== the tabs, and the next turn while navigating ===============
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: false            // its keys fill this row, not the page
            Layout.preferredHeight: page.barHeight
            spacing: Theme.gap

            SegmentedControl {
                Layout.fillWidth: true
                Layout.fillHeight: true
                stretch: true
                options: [{ label: "Playing", value: "playing" },
                          { label: "Up next", value: "next" },
                          { label: "Albums", value: "albums" },
                          { label: "Songs", value: "songs" },
                          { label: "Spotify", value: "spotify" }]
                current: page.tab
                onPicked: (v) => page.show(v)
            }

            // Tap for Maps.
            Rectangle {
                visible: page.navigating
                Layout.preferredWidth: 440
                Layout.fillHeight: true
                radius: Theme.radius
                color: turnTap.pressed ? Theme.panelHi : Theme.panel
                border.width: Theme.border
                border.color: Theme.accent
                RowLayout {
                    anchors { fill: parent; leftMargin: 20; rightMargin: 20 }
                    spacing: Theme.gap
                    Icon {
                        name: page.navigating ? routing.maneuverIcon || "straight" : "straight"
                        size: 56
                        color: Theme.accent
                    }
                    Column {
                        Layout.fillWidth: true
                        Layout.preferredWidth: 1
                        Label {
                            visible: page.navigating && !routing.arrived
                            text: page.navigating ? Units.distanceText(routing.distanceToTurn) : ""
                            font.family: Theme.numFont
                            font.pixelSize: Theme.fontBody
                            font.weight: Font.DemiBold
                        }
                        Label {
                            width: parent.width
                            text: page.navigating ? routing.instruction : ""
                            color: Theme.textDim
                            font.pixelSize: Theme.fontSmall
                            elide: Text.ElideRight
                        }
                    }
                }
                TapHandler { id: turnTap; onTapped: page.navigate(2) }
            }
        }

        // ==== what's playing =============================================
        // Two rows on one grid: the cover beside the song and the transport
        // keys, ending level; then the modes beside the volume.
        Card {
            id: nowCard
            visible: !page.browsing
            Layout.fillWidth: true
            Layout.fillHeight: true
            // Square, leaving the row of keys below it.
            readonly property int coverSize: height - 40 - Theme.touch - Theme.gap

            RowLayout {
                anchors { fill: parent; margins: 20 }
                spacing: 28

                ColumnLayout {
                    Layout.fillWidth: false             // its keys share the cover's width
                    Layout.preferredWidth: nowCard.coverSize
                    Layout.fillHeight: true
                    spacing: Theme.gap
                    AlbumArt {
                        Layout.preferredWidth: nowCard.coverSize
                        Layout.preferredHeight: nowCard.coverSize
                        source: media.artCard
                        placeholder: media.source === "phone" ? "phone" : "music"
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.preferredHeight: Theme.touch
                        spacing: Theme.gap
                        // The Pi's own music and Spotify: the phone has no way to set these from here.
                        ModeKey {
                            objectName: "shuffleKey"
                            visible: media.hasModes
                            icon: "shuffle"
                            text: "Shuffle"
                            active: media.shuffle
                            onClicked: media.toggleShuffle()
                        }
                        ModeKey {
                            objectName: "repeatKey"
                            visible: media.hasModes
                            icon: media.repeat === "one" ? "repeat_one" : "repeat"
                            text: media.repeat === "one" ? "Repeat 1" : (media.repeat === "off" ? "Repeat off" : "Repeat")
                            active: media.repeat !== "off"
                            onClicked: media.cycleRepeat()
                        }
                        ModeKey {
                            objectName: "eqKey"
                            icon: "equalizer"
                            text: eq.preset
                            active: eq.preset !== "Flat"
                            onClicked: page.eqOpen = true
                        }
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.preferredWidth: 1            // take what's left, not the title's length
                    spacing: Theme.gap

                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        spacing: 6
                        SourceBadge { Layout.fillWidth: true }
                        Label {
                            objectName: "nowTitle"
                            Layout.fillWidth: true
                            text: page.titleText
                            color: media.title === "" ? Theme.textDim : Theme.text
                            font.pixelSize: Theme.fontHero
                            font.weight: Font.DemiBold
                            lineHeight: 0.95
                            wrapMode: Text.Wrap
                            maximumLineCount: 2
                            elide: Text.ElideRight
                        }
                        Label {
                            objectName: "nowArtist"
                            Layout.fillWidth: true
                            text: page.spotifyError !== "" ? page.spotifyError
                                  : page.idle ? page.idleHint
                                  : page.artistLine(media.artist, media.albumTitle)
                            color: page.spotifyError !== "" ? Theme.warn : Theme.textDim
                            font.pixelSize: Theme.fontBody
                            wrapMode: Text.WordWrap          // the hint may take two lines
                            maximumLineCount: 2
                            elide: Text.ElideRight
                        }

                        // Other places to play from: the phone, or back to the Pi's songs.
                        // Not shown with nothing to switch to.
                        Row {
                            id: otherSources
                            visible: media.otherSources.length > 0
                            Layout.fillWidth: true
                            spacing: Theme.gap
                            Repeater {
                                model: media.otherSources
                                delegate: Rectangle {
                                    height: 64
                                    width: Math.min(chipRow.implicitWidth + 40, otherSources.width)
                                    radius: height / 2
                                    color: chipTap.pressed ? Theme.panelHi : Theme.panel
                                    border.width: 1
                                    border.color: Theme.line
                                    RowLayout {
                                        id: chipRow
                                        anchors { fill: parent; leftMargin: 20; rightMargin: 20 }
                                        spacing: 10
                                        Icon { name: modelData.name === "phone" ? "bluetooth" : "music"; size: 28; color: Theme.accent }
                                        Label {
                                            Layout.fillWidth: true
                                            text: modelData.label
                                            font.pixelSize: Theme.fontSmall
                                            elide: Text.ElideRight
                                        }
                                    }
                                    TapHandler { id: chipTap; onTapped: media.useSource(modelData.name) }
                                }
                            }
                        }
                        Item { Layout.fillHeight: true }

                        // The next song, when it's known: tap for the rest.
                        Rectangle {
                            visible: page.nextSong !== null
                            Layout.fillWidth: true
                            Layout.preferredHeight: 64
                            radius: Theme.radius
                            color: nextTap.pressed ? Theme.panelHi : "transparent"
                            RowLayout {
                                anchors { fill: parent; rightMargin: 8 }
                                spacing: 12
                                Label {
                                    text: "Next"
                                    color: Theme.textDim
                                    font.pixelSize: Theme.fontSmall
                                    font.weight: Font.DemiBold
                                }
                                Label {
                                    Layout.fillWidth: true
                                    Layout.preferredWidth: 1
                                    text: page.nextSong ? page.nextSong.title : ""
                                    font.pixelSize: Theme.fontSmall
                                    elide: Text.ElideRight
                                }
                                Icon { name: "queue"; size: 28; color: Theme.textDim }
                            }
                            TapHandler { id: nextTap; onTapped: page.show("next") }
                        }

                        // Tap or drag to seek. The touch area is much taller than the bar;
                        // the song only jumps on release, so a drag doesn't re-decode.
                        Item {
                            id: seekArea
                            objectName: "seekArea"
                            Layout.fillWidth: true
                            Layout.preferredHeight: 44
                            readonly property bool canSeek: media.canSeek && media.duration > 0 && !page.idle
                            property real dragValue: 0
                            property bool dragging: false
                            function at(x) { return Math.max(0, Math.min(1, x / width)) }
                            ProgressBar {
                                id: seekBar
                                anchors.verticalCenter: parent.verticalCenter
                                width: parent.width
                                height: 10
                                radius: 5
                                value: seekArea.dragging ? seekArea.dragValue
                                                         : (media.duration > 0 ? media.position / media.duration : 0)
                            }
                            // The handle: it shows the bar can be dragged, and it grows while a
                            // finger is on it. It sits on the end of the fill and is only drawn
                            // where seeking works (not on a phone or with nothing playing).
                            Rectangle {
                                id: seekThumb
                                objectName: "seekThumb"
                                anchors.verticalCenter: parent.verticalCenter
                                x: seekBar.width * seekBar.value - width / 2
                                width: seekArea.dragging ? 36 : 28
                                height: width
                                radius: width / 2
                                color: Theme.accent
                                border.width: 2
                                border.color: Theme.bg
                                visible: seekArea.canSeek
                                // Size changes only on press and release, so nothing runs at rest.
                                Behavior on width { NumberAnimation { duration: 80 } }
                            }
                            MouseArea {
                                anchors { fill: parent; bottomMargin: -28 }
                                enabled: seekArea.canSeek
                                onPressed: (m) => { seekArea.dragValue = seekArea.at(m.x); seekArea.dragging = true }
                                onPositionChanged: (m) => seekArea.dragValue = seekArea.at(m.x)
                                onReleased: (m) => {
                                    seekArea.dragging = false
                                    media.seek(Math.round(seekArea.at(m.x) * media.duration))
                                    seekBar.flashSeek()
                                }
                                onCanceled: seekArea.dragging = false
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            // While dragging, the elapsed time turns accent and bold, and the right
                            // side counts down the time left at the drag point.
                            Label {
                                objectName: "seekElapsed"
                                text: page.idle ? "" : page.mmss(seekArea.dragging ? Math.round(seekArea.dragValue * media.duration) : media.position)
                                color: seekArea.dragging ? Theme.accent : Theme.textDim
                                font.pixelSize: Theme.fontSmall
                                font.weight: seekArea.dragging ? Font.Bold : Font.Normal
                            }
                            Item { Layout.fillWidth: true }
                            Label {
                                objectName: "seekRemaining"
                                text: page.idle ? ""
                                      : seekArea.dragging
                                        ? "−" + page.mmss(Math.max(0, media.duration - Math.round(seekArea.dragValue * media.duration)))
                                        : page.mmss(media.duration)
                                color: Theme.textDim
                                font.pixelSize: Theme.fontSmall
                            }
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.fillHeight: false
                        Layout.preferredHeight: Theme.touch + 20
                        spacing: Theme.gap
                        opacity: page.idle ? 0.5 : 1
                        enabled: !page.idle
                        WideKey { icon: "previous"; size: Theme.touch + 20; onClicked: media.previous() }
                        WideKey {
                            icon: media.playing ? "pause" : "play"
                            primary: true
                            size: Theme.touch + 20
                            Layout.preferredWidth: 1.4
                            onClicked: media.togglePlay()
                        }
                        WideKey { icon: "next"; size: Theme.touch + 20; onClicked: media.next() }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.fillHeight: false
                        Layout.preferredHeight: Theme.touch
                        spacing: Theme.gap
                        IconButton { icon: "remove"; onClicked: media.volumeDown() }
                        LevelBar {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 44
                            opacity: media.muted ? 0.35 : 1
                            value: media.volume / 100
                            onMoved: (v) => media.setVolume(Math.round(v * 100))
                        }
                        // Tap to mute, as holding the knob does.
                        Label {
                            Layout.preferredWidth: 72
                            Layout.fillHeight: true
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            color: media.muted ? Theme.warn : Theme.text
                            text: media.muted ? "Mute" : media.volume
                            font.family: Theme.numFont
                            font.pixelSize: Theme.fontBody
                            font.weight: Font.DemiBold
                            TapHandler { onTapped: media.toggleMute() }
                        }
                        IconButton { icon: "add"; onClicked: media.volumeUp() }
                    }
                }
            }
        }

        // ==== browsing ===================================================
        ColumnLayout {
            visible: page.browsing
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: Theme.gap

            Card {
                id: content
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                heading: page.eqOpen ? "Equalizer"
                         : page.tab === "next" ? (media.source === "spotify" ? "Up next on Spotify"
                                                  : page.albums[media.album] ? "Playing the album " + page.albums[media.album].title
                                                  : media.source === "phone" ? "On your phone"
                                                  : media.shuffle ? "All songs, shuffled"
                                                  : "All songs, A to Z")
                         : ""

                // ---- Up next ------------------------------------------------
                // The song playing, pinned, then what follows it in the true
                // play order (a shuffle's too).
                SongRow {
                    id: nowRow
                    visible: page.tab === "next" && !page.eqOpen && media.title !== ""
                    anchors { top: parent.top; left: parent.left; right: parent.right; margins: 10; topMargin: 52 }
                    current: true
                    title: media.title
                    subtitle: "Now playing" + (page.artistLine(media.artist, "") !== "" ? "  \u00b7  " + page.artistLine(media.artist, "") : "")
                    tappable: false
                }
                ListView {
                    id: queue
                    reuseItems: true
                    visible: page.tab === "next" && !page.eqOpen
                    readonly property bool spotifyQueue: media.source === "spotify"
                    readonly property bool phoneQueue: media.source === "phone"
                    anchors {
                        fill: parent; margins: 10
                        topMargin: 52 + (nowRow.visible ? nowRow.height + 4 : 0)
                    }
                    clip: true
                    model: page.upNext
                    boundsBehavior: Flickable.StopAtBounds
                    delegate: SongRow {
                        width: queue.width
                        number: index + 1
                        title: modelData.title
                        subtitle: page.artistLine(modelData.artist, "")
                        tappable: !queue.spotifyQueue
                        onHit: media.playIndex(modelData.index)
                    }
                    EmptyState {
                        visible: queue.count === 0
                        width: parent.width
                        height: queue.height
                        icon: queue.spotifyQueue || queue.phoneQueue || nowRow.visible ? "queue"
                              : media.scanning ? "refresh" : "music"
                        title: queue.phoneQueue ? "Your phone picks what plays next"
                               : queue.spotifyQueue ? "Nothing queued"
                               : nowRow.visible ? "That is the last song"
                               : media.scanning ? "Reading your music" : "No songs yet"
                        hint: queue.phoneQueue ? ""
                              : queue.spotifyQueue ? "Songs you queue in Spotify line up here"
                              : nowRow.visible ? (media.repeat === "off" ? "Turn repeat on to start over" : "")
                              : media.scanning ? "Songs show up as they're found"
                              : "Copy albums into ~/Music on the Pi"
                    }
                }

                // ---- Albums: all of them ------------------------------------
                // All or just the albums played lately, then back to the whole
                // library in one tap.
                Row {
                    id: playKeys
                    visible: page.tab === "albums" && page.openAlbum < 0 && !page.eqOpen && page.albums.length > 0
                    anchors { left: parent.left; right: parent.right; top: parent.top; margins: 12
                              rightMargin: alphaRail.visible ? alphaRail.width + 24 : 12 }
                    height: 72
                    spacing: Theme.gap
                    SegmentedControl {
                        width: 320
                        height: parent.height
                        stretch: true
                        options: [{ label: "All", value: "all" }, { label: "Recent", value: "recent" }]
                        current: page.albumView
                        onPicked: (v) => page.albumView = v
                    }
                    TextButton {
                        width: (parent.width - parent.spacing * 2 - 320) / 2
                        height: parent.height
                        primary: true
                        icon: "shuffle"
                        text: "Shuffle all"
                        onClicked: media.shuffleAll()
                    }
                    TextButton {
                        width: (parent.width - parent.spacing * 2 - 320) / 2
                        height: parent.height
                        icon: "play"
                        text: "Play all"
                        onClicked: media.playAll()
                    }
                }

                GridView {
                    id: albumGrid
                    visible: page.tab === "albums" && page.openAlbum < 0 && !page.eqOpen
                    anchors { fill: parent; margins: 12; topMargin: playKeys.visible ? playKeys.height + 24 : 12
                              rightMargin: alphaRail.visible ? alphaRail.width + 24 : 12 }
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    cellWidth: Math.floor(width / 5)
                    cellHeight: cellWidth + 80
                    // Reused delegates, and about two rows kept ready past the edges.
                    reuseItems: true
                    cacheBuffer: cellHeight * 2
                    readonly property bool recent: page.albumView === "recent"
                    model: recent ? media.recentAlbums : page.albums
                    delegate: CoverTile {
                        // In Recent, `index` counts the list shown; modelData.index is the album's place.
                        readonly property int albumNo: albumGrid.recent ? modelData.index : index
                        width: albumGrid.cellWidth
                        height: albumGrid.cellHeight
                        art: modelData.art
                        placeholder: "album"
                        title: modelData.title
                        subtitle: modelData.artist
                        current: albumNo === media.album
                        onHit: { page.openKey = [modelData.artist, modelData.title]; page.openAlbum = albumNo }
                    }
                    EmptyState {
                        visible: albumGrid.count === 0
                        width: parent.width
                        height: albumGrid.height
                        icon: media.scanning ? "refresh" : "album"
                        title: media.scanning ? "Reading your music"
                               : albumGrid.recent && page.albums.length > 0 ? "Nothing played yet"
                               : "The shelf is empty"
                        hint: media.scanning ? "Songs show up as they're found"
                              : albumGrid.recent && page.albums.length > 0 ? "Albums you play show up here"
                              : "Albums copied into ~/Music on the Pi show up here"
                    }
                }

                // Jump rail: big letter buckets for a long library. It only
                // rebuilds when the album list changes.
                Column {
                    id: alphaRail
                    visible: page.tab === "albums" && page.openAlbum < 0 && !page.eqOpen && page.albumView === "all" && page.albums.length > 15
                    readonly property var buckets: AlphaIndex.buckets(page.albums.map(function (a) { return a.artist }))
                    width: 64
                    anchors { right: parent.right; rightMargin: 12; top: parent.top; topMargin: 12; bottom: parent.bottom; bottomMargin: 12 }
                    Repeater {
                        model: alphaRail.buckets
                        delegate: Item {
                            width: alphaRail.width
                            height: Math.max(56, alphaRail.height / 9)
                            Label {
                                anchors.centerIn: parent
                                text: modelData.label
                                font.pixelSize: Theme.fontSmall
                                font.bold: modelData.index >= 0
                                color: Theme.text
                                opacity: modelData.index >= 0 ? 1 : 0.3
                            }
                            MouseArea {
                                anchors.fill: parent
                                enabled: modelData.index >= 0
                                onClicked: albumGrid.positionViewAtIndex(Math.floor(modelData.index / 5) * 5, GridView.Beginning)
                            }
                        }
                    }
                }

                // ---- Songs: every song, A to Z ------------------------------
                // Tap one to play it; the rest of the library follows.
                ListView {
                    id: songList
                    reuseItems: true
                    visible: page.tab === "songs" && !page.eqOpen
                    anchors { fill: parent; margins: 10
                              rightMargin: songRail.visible ? songRail.width + 24 : 10 }
                    clip: true
                    model: page.songs
                    boundsBehavior: Flickable.StopAtBounds
                    delegate: SongRow {
                        width: songList.width
                        numbered: false
                        current: media.source === "local" && media.title === modelData.title
                                 && media.artist === modelData.artist
                        title: modelData.title
                        subtitle: page.artistLine(modelData.artist, "")
                        onHit: media.playSong(modelData.index)
                    }
                    EmptyState {
                        visible: songList.count === 0
                        width: parent.width
                        height: songList.height
                        icon: media.scanning ? "refresh" : "music"
                        title: media.scanning ? "Reading your music" : "No songs yet"
                        hint: media.scanning ? "Songs show up as they're found" : "Copy albums into ~/Music on the Pi"
                    }
                }

                // The same jump rail as Albums, on the song titles.
                Column {
                    id: songRail
                    visible: page.tab === "songs" && !page.eqOpen && page.songs.length > 15
                    readonly property var buckets: AlphaIndex.buckets(page.songs.map(function (s) { return s.title }), true)
                    width: 64
                    anchors { right: parent.right; rightMargin: 12; top: parent.top; topMargin: 12; bottom: parent.bottom; bottomMargin: 12 }
                    Repeater {
                        model: songRail.buckets
                        delegate: Item {
                            width: songRail.width
                            height: Math.max(56, songRail.height / 9)
                            Label {
                                anchors.centerIn: parent
                                text: modelData.label
                                font.pixelSize: Theme.fontSmall
                                font.bold: modelData.index >= 0
                                color: Theme.text
                                opacity: modelData.index >= 0 ? 1 : 0.3
                            }
                            MouseArea {
                                anchors.fill: parent
                                enabled: modelData.index >= 0
                                onClicked: songList.positionViewAtIndex(modelData.index, ListView.Beginning)
                            }
                        }
                    }
                }

                // ---- Albums: one open ---------------------------------------
                Item {
                    id: albumView
                    visible: page.tab === "albums" && page.openAlbum >= 0 && !page.eqOpen
                    anchors { fill: parent; margins: 20 }
                    readonly property var album: page.openAlbum >= 0 ? page.albums[page.openAlbum] : null
                    readonly property var tracks: page.openAlbum >= 0 && page.albums ? media.albumTracks(page.openAlbum) : []   // page.albums: re-read when a rescan changes the songs

                    RowLayout {
                        id: albumHead
                        anchors { left: parent.left; right: parent.right; top: parent.top }
                        spacing: 20
                        IconButton {
                            icon: "back"
                            onClicked: page.openAlbum = -1
                        }
                        Cover {
                            Layout.preferredWidth: 120
                            Layout.preferredHeight: 120
                            art: albumView.album ? albumView.album.art : ""
                            placeholder: "album"
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.preferredWidth: 1            // take what's left, not the title's length
                            Layout.alignment: Qt.AlignVCenter
                            spacing: 0
                            Label {
                                Layout.fillWidth: true
                                text: albumView.album ? albumView.album.title : ""
                                font.pixelSize: Theme.fontTitle
                                font.weight: Font.DemiBold
                                elide: Text.ElideRight
                            }
                            Label {
                                Layout.fillWidth: true
                                text: albumView.album ? albumView.album.artist : ""
                                color: Theme.textDim
                                font.pixelSize: Theme.fontBody
                                elide: Text.ElideRight
                            }
                            Label {
                                text: albumView.album ? albumView.album.count + (albumView.album.count === 1 ? " song, " : " songs, ")
                                                      + page.albumLength(albumView.album.duration) : ""
                                color: Theme.textDim
                                font.pixelSize: Theme.fontSmall
                            }
                        }
                        TextButton {
                            Layout.alignment: Qt.AlignVCenter
                            implicitWidth: 180
                            implicitHeight: Theme.touch
                            text: "Play"
                            icon: "play"
                            primary: true
                            onClicked: media.playAlbum(page.openAlbum, -1)
                        }
                    }
                    ListView {
                        id: albumSongs
                        reuseItems: true
                        anchors { left: parent.left; right: parent.right; top: albumHead.bottom; bottom: parent.bottom; topMargin: 14 }
                        clip: true
                        boundsBehavior: Flickable.StopAtBounds
                        model: albumView.tracks
                        delegate: SongRow {
                            width: albumSongs.width
                            number: index + 1
                            current: media.album === page.openAlbum && index === media.index
                            title: modelData.title
                            subtitle: ""
                            trailing: page.mmss(modelData.duration)
                            onHit: media.playAlbum(page.openAlbum, index)
                        }
                    }
                }

                // ---- Spotify: played here recently --------------------------
                SegmentedControl {
                    id: spotifyViews
                    visible: page.tab === "spotify" && !page.eqOpen && !page.searchOpen
                    anchors { left: parent.left; right: searchKey.left; top: parent.top; margins: 12 }
                    height: 72
                    stretch: true
                    options: [{ label: "Recent", value: "recent" }, { label: "Playlists", value: "playlists" },
                              { label: "Albums", value: "albums" }, { label: "Liked", value: "liked" }]
                    current: page.spotifyView
                    onPicked: (v) => page.spotifyView = v
                }
                GridView {
                    id: spotifyGrid
                    visible: page.tab === "spotify" && !page.eqOpen && !page.searchOpen
                             && !page.needsLink && page.spotifyView !== "liked"
                    anchors { fill: parent; margins: 12; topMargin: 96 }
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    cellWidth: Math.floor(width / 5)
                    cellHeight: cellWidth + 80
                    reuseItems: true
                    cacheBuffer: cellHeight * 2
                    model: page.spotifyView === "recent" || !page.hasAccount ? media.spotifyRecents
                           : page.spotifyView === "playlists" ? spotifyAccount.playlists : spotifyAccount.albums
                    delegate: CoverTile {
                        width: spotifyGrid.cellWidth
                        height: spotifyGrid.cellHeight
                        art: modelData.art
                        placeholder: modelData.kind === "playlist" ? "queue" : "album"
                        title: modelData.title
                        subtitle: modelData.subtitle
                        current: page.spotifyView === "recent" && index === 0 && media.source === "spotify" && media.playing
                        onHit: media.playSpotify(modelData.uri)
                    }
                    Label {
                        visible: spotifyGrid.count === 0
                        width: parent.width
                        wrapMode: Text.WordWrap
                        text: !page.hasSpotify || !spotify.linked ? spotify.statusText + "."
                              : page.libraryView ? (spotifyAccount.loading ? "Reading your library..."
                                                    : spotifyAccount.message || "Nothing here yet.")
                              : "Albums and playlists you play here through Spotify show up here. "
                                + "In the Spotify app on your phone, pick " + (spotify.deviceName || "this Pi")
                                + " as the speaker and play something."
                        color: Theme.textDim
                        font.pixelSize: Theme.fontBody
                    }
                }

                // ---- Spotify: Liked Songs -----------------------------------
                ListView {
                    id: likedList
                    reuseItems: true
                    visible: page.tab === "spotify" && !page.eqOpen && !page.searchOpen
                             && !page.needsLink && page.spotifyView === "liked"
                    anchors { fill: parent; margins: 12; topMargin: 96 }
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    model: page.hasAccount ? spotifyAccount.songs : []
                    delegate: ResultRow {
                        width: likedList.width
                        art: modelData.art
                        kind: modelData.kind
                        title: modelData.title
                        subtitle: modelData.subtitle
                        // This song, then the ones after it.
                        onHit: media.playSpotifyTracks(spotifyAccount.songs.slice(index, index + 20).map((s) => s.uri))
                        onQueued: media.queueSpotify(modelData.uri)
                    }
                    Label {
                        visible: likedList.count === 0
                        width: parent.width
                        wrapMode: Text.WordWrap
                        text: !page.hasAccount ? "" : spotifyAccount.loading ? "Reading your library..."
                              : spotifyAccount.message || "No Liked Songs yet."
                        color: Theme.textDim
                        font.pixelSize: Theme.fontBody
                    }
                }

                // ---- Spotify: linking your library --------------------------
                RowLayout {
                    id: linkView
                    visible: page.tab === "spotify" && !page.eqOpen && !page.searchOpen && page.needsLink
                    anchors { fill: parent; margins: 20; topMargin: 96 }
                    spacing: 28
                    readonly property string url: page.hasAccount ? spotifyAccount.linkUrl : ""
                    readonly property string ip: typeof network !== "undefined" ? network.ip : ""
                    onVisibleChanged: if (!visible && page.hasAccount) Qt.callLater(spotifyAccount.cancelLink)
                    Image {
                        visible: linkView.url !== ""
                        Layout.alignment: Qt.AlignVCenter
                        Layout.preferredWidth: Math.min(300, linkView.height)
                        Layout.preferredHeight: Layout.preferredWidth
                        source: linkView.visible && typeof phone !== "undefined" ? phone.qrFor(linkView.url) : ""
                        smooth: false
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.preferredWidth: 1
                        Layout.alignment: Qt.AlignVCenter
                        spacing: 20
                        Label {
                            Layout.fillWidth: true
                            wrapMode: Text.WordWrap
                            color: page.hasAccount && spotifyAccount.message !== "" ? Theme.warn : Theme.textDim
                            font.pixelSize: Theme.fontBody
                            text: !page.hasAccount ? ""
                                  : !spotifyAccount.available ? "This needs a Spotify app on this Pi: run deploy/spotify/set-spotify-search.sh."
                                  : spotifyAccount.message !== "" ? spotifyAccount.message
                                  : linkView.url !== "" ? "Scan this with your phone, on the same Wi-Fi or hotspot as the truck, and sign in. You only do this once."
                                  : "Link your Spotify account to see your playlists, albums and Liked Songs here. You only do this once."
                        }
                        TextButton {
                            visible: page.hasAccount && spotifyAccount.available && linkView.url === ""
                            implicitWidth: 340
                            implicitHeight: Theme.touch
                            text: linkView.ip !== "" ? "Link Spotify" : "Connect to Wi-Fi first"
                            primary: true
                            enabled: linkView.ip !== ""
                            onClicked: spotifyAccount.startLink(linkView.ip, phone.port)
                        }
                    }
                }

                IconButton {
                    id: searchKey
                    visible: page.tab === "spotify" && !page.eqOpen && !page.searchOpen
                    anchors { right: parent.right; top: parent.top; margins: 12 }
                    icon: "search"
                    size: 72
                    onClicked: { page.searchOpen = page.typing = true }
                }

                // ---- Spotify: search ----------------------------------------
                Item {
                    id: searchView
                    visible: page.tab === "spotify" && !page.eqOpen && page.searchOpen
                    anchors { fill: parent; margins: 12 }
                    readonly property bool ready: typeof spotifySearch !== "undefined" && spotifySearch.available

                    RowLayout {
                        id: searchHead
                        anchors { left: parent.left; right: parent.right; top: parent.top }
                        spacing: 12
                        IconButton { icon: "back"; size: 72; onClicked: page.closeSearch() }
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 72
                            radius: Theme.radius
                            color: Theme.panelHi
                            border.width: Theme.border
                            border.color: page.typing ? Theme.accent : Theme.line
                            Label {
                                anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; leftMargin: 16; rightMargin: 16 }
                                text: page.query !== "" ? page.query : "Search Spotify"
                                color: page.query !== "" ? Theme.text : Theme.textDim
                                font.pixelSize: Theme.fontBody
                                elide: Text.ElideLeft
                            }
                            TapHandler { onTapped: page.typing = true }
                        }
                    }
                    ListView {
                        id: resultList
                        reuseItems: true
                        anchors { left: parent.left; right: parent.right; top: searchHead.bottom; bottom: parent.bottom; topMargin: 10 }
                        clip: true
                        boundsBehavior: Flickable.StopAtBounds
                        model: searchView.ready ? spotifySearch.results : []
                        delegate: ResultRow {
                            width: resultList.width
                            art: modelData.art
                            kind: modelData.kind
                            title: modelData.title
                            subtitle: modelData.subtitle
                            onHit: media.playSpotify(modelData.uri)
                            onQueued: media.queueSpotify(modelData.uri)
                        }
                        EmptyState {
                            visible: resultList.count === 0
                            width: parent.width
                            height: resultList.height
                            // The keyboard covers the lower part of the list
                            // while typing, so keep this above it.
                            alignTop: page.typing
                            icon: "search"
                            title: !searchView.ready ? "Search isn't set up"
                                   : spotifySearch.searching ? "Searching"
                                   : spotifySearch.message !== "" ? spotifySearch.message
                                   : "Search Spotify"
                            hint: !searchView.ready ? "Run deploy/spotify/set-spotify-search.sh on the Pi to set up Spotify search."
                                  : spotifySearch.searching || spotifySearch.message !== "" ? ""
                                  : "Type a song, artist or album"
                        }
                    }
                }

                // ---- the equalizer ------------------------------------------
                IconButton {
                    visible: page.eqOpen
                    anchors { right: parent.right; top: parent.top; margins: 12 }
                    icon: "close"
                    size: 72
                    onClicked: page.eqOpen = false
                }
                EqualizerPanel {
                    visible: page.eqOpen
                    anchors { fill: parent; margins: 20; topMargin: 96 }
                }
            }

            // What's playing stays in reach, and a tap goes back to it. The
            // equalizer takes this room too.
            Card {
                id: playerBar
                visible: !page.eqOpen
                Layout.fillWidth: true
                Layout.preferredHeight: Theme.touch + 24

                RowLayout {
                    anchors { fill: parent; margins: 12 }
                    spacing: Theme.gap
                    Item {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        RowLayout {
                            anchors.fill: parent
                            spacing: Theme.gap
                            Cover {
                                Layout.preferredWidth: Theme.touch
                                Layout.preferredHeight: Theme.touch
                                art: media.artCard
                                placeholder: media.source === "phone" ? "phone" : "music"
                            }
                            Column {
                                Layout.fillWidth: true
                                Layout.preferredWidth: 1
                                Label {
                                    width: parent.width
                                    text: page.titleText
                                    color: media.title === "" ? Theme.textDim : Theme.text
                                    font.pixelSize: Theme.fontBody
                                    font.weight: Font.DemiBold
                                    elide: Text.ElideRight
                                }
                                Label {
                                    width: parent.width
                                    text: page.spotifyError !== "" ? page.spotifyError : media.artist
                                    color: page.spotifyError !== "" ? Theme.warn : Theme.textDim
                                    font.pixelSize: Theme.fontSmall
                                    elide: Text.ElideRight
                                }
                            }
                        }
                        TapHandler { onTapped: page.show("playing") }
                    }
                    Row {
                        spacing: Theme.gap
                        opacity: page.idle ? 0.5 : 1
                        enabled: !page.idle
                        IconButton { icon: "previous"; onClicked: media.previous() }
                        IconButton {
                            icon: media.playing ? "pause" : "play"
                            primary: true
                            onClicked: media.togglePlay()
                        }
                        IconButton { icon: "next"; onClicked: media.next() }
                    }
                    IconButton { icon: "remove"; onClicked: media.volumeDown() }
                    IconButton { icon: "add"; onClicked: media.volumeUp() }
                }
                ProgressBar {
                    anchors { left: parent.left; right: parent.right; bottom: parent.bottom; margins: Theme.border }
                    height: 4
                    radius: 0
                    value: media.duration > 0 ? media.position / media.duration : 0
                }
            }
        }
    }

    // Typing a Spotify search: the keyboard across the bottom, as on Maps.
    Keyboard {
        visible: page.typing
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom; margins: Theme.gap }
        height: 340
        doneLabel: "Search"
        doneEnabled: page.query.trim() !== ""
        onTyped: (ch) => page.query += ch
        onBackspace: page.query = page.query.slice(0, -1)
        onDone: page.runSearch()
    }

    // ---- small parts ------------------------------------------------------
    // A key that shares its row's width with the others.
    component WideKey: IconButton {
        Layout.fillWidth: true
        Layout.fillHeight: true
        Layout.preferredWidth: 1
    }

    // A mode key that says what it does: an icon over a short label. On, it is
    // filled with the accent and outlined; off, it is a plain key. Same press
    // travel as IconButton, so nothing animates except a touch.
    component ModeKey: Rectangle {
        id: key
        property string icon
        property string text
        property bool active: false
        signal clicked()
        Layout.fillWidth: true
        Layout.preferredWidth: 1
        Layout.preferredHeight: Theme.touch
        radius: Theme.radius
        border.width: Theme.border
        border.color: active ? Theme.accent : Theme.line
        color: active ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.22)
                      : (keyTap.pressed ? Theme.line : Theme.panelHi)
        scale: keyTap.pressed ? 0.97 : 1
        Behavior on scale { id: keySpring; NumberAnimation { duration: keySpring.targetValue < 1 ? 70 : 180; easing.type: keySpring.targetValue < 1 ? Easing.OutQuad : Easing.OutBack; easing.overshoot: 2.5 } }
        Column {
            anchors.centerIn: parent
            width: parent.width - 12
            spacing: 4
            Icon {
                anchors.horizontalCenter: parent.horizontalCenter
                name: key.icon
                size: 36
                color: key.active ? Theme.accent : Theme.textDim
            }
            Label {
                objectName: "modeKeyLabel"
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                text: key.text
                font.pixelSize: Theme.fontSmall
                font.weight: Font.DemiBold
                color: key.active ? Theme.accent : Theme.textDim
                elide: Text.ElideRight
            }
        }
        TapHandler { id: keyTap; onTapped: key.clicked() }
    }

    // A cover: the picture, or a quiet tile with an icon when there isn't one.
    component Cover: Rectangle {
        property string art
        property string placeholder: "album"
        radius: Theme.radius
        color: Theme.panelHi
        border.width: Theme.border
        border.color: Theme.line
        clip: true
        Icon {
            visible: coverImage.status !== Image.Ready
            anchors.centerIn: parent
            name: parent.placeholder
            size: parent.width * 0.4
            color: Theme.textDim
        }
        Image {
            id: coverImage
            anchors { fill: parent; margins: Theme.border }
            source: parent.art
            sourceSize: Qt.size(256, 256)          // decode small: there are many (tiles are about 210 px)
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
        }
    }

    // A cover with its name under it, for the album and Spotify grids.
    component CoverTile: Item {
        id: tile
        property string art
        property string placeholder: "album"
        property string title
        property string subtitle
        property bool current: false
        signal hit()
        Cover {
            id: tileCover
            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 8 }
            height: width
            art: tile.art
            placeholder: tile.placeholder
            border.color: tile.current ? Theme.accent : Theme.line
            border.width: tile.current ? 3 : Theme.border
            scale: tileTap.pressed ? 0.96 : 1
            Behavior on scale { NumberAnimation { duration: 80 } }
        }
        Column {
            anchors { left: parent.left; right: parent.right; top: tileCover.bottom; leftMargin: 10; rightMargin: 10; topMargin: 8 }
            Label {
                width: parent.width
                text: tile.title
                font.pixelSize: Theme.fontSmall
                font.weight: Font.DemiBold
                color: tile.current ? Theme.accent : Theme.text
                elide: Text.ElideRight
            }
            Label {
                width: parent.width
                text: tile.subtitle
                color: Theme.textDim
                font.pixelSize: Theme.fontSmall
                elide: Text.ElideRight
            }
        }
        TapHandler { id: tileTap; onTapped: tile.hit() }
    }

    // A Spotify search result: tap to play; songs can also go in the queue.
    component ResultRow: Rectangle {
        id: result
        property string art
        property string kind
        property string title
        property string subtitle
        signal hit()
        signal queued()
        height: 92
        radius: Theme.radius
        color: resultTap.pressed ? Theme.panelHi : "transparent"
        // The + key sits inside the row, and TapHandler's passive grab lets
        // both handlers see one tap, so the row ignores taps that land on it.
        TapHandler {
            id: resultTap
            onTapped: (point) => {
                const p = queueKey.mapFromItem(result, point.position.x, point.position.y)
                if (!(queueKey.visible && queueKey.contains(p)))
                    result.hit()
            }
        }
        RowLayout {
            anchors { fill: parent; leftMargin: 6; rightMargin: 6 }
            spacing: 14
            Cover {
                Layout.preferredWidth: 72
                Layout.preferredHeight: 72
                art: result.art
                placeholder: result.kind === "track" ? "music" : result.kind === "playlist" ? "queue" : "album"
            }
            Column {
                Layout.fillWidth: true
                Layout.preferredWidth: 1            // take what's left, not the title's length
                Label {
                    width: parent.width
                    text: result.title
                    font.pixelSize: Theme.fontBody
                    elide: Text.ElideRight
                }
                Label {
                    width: parent.width
                    text: result.subtitle
                    color: Theme.textDim
                    font.pixelSize: Theme.fontSmall
                    elide: Text.ElideRight
                }
            }
            IconButton {
                id: queueKey
                visible: result.kind === "track"
                icon: "add"
                size: 84
                onClicked: result.queued()
            }
        }
    }

    // A song in a list: its number (or a playing mark), title, and a second
    // line or a time on the right.
    component SongRow: Rectangle {
        id: row
        property int number
        property bool numbered: true           // false: no number column, the title starts at the edge
        property bool current: false
        property string title
        property string subtitle
        property string trailing: ""
        property bool tappable: true
        signal hit()
        height: 92
        radius: Theme.radius
        color: current || rowTap.pressed ? Theme.panelHi : "transparent"
        Item {
            id: num
            width: row.numbered ? 52 : 6
            height: parent.height
            anchors { left: parent.left; leftMargin: 10 }
            Icon {
                visible: row.numbered && row.current
                anchors.verticalCenter: parent.verticalCenter
                name: "equalizer"
                size: 24
                color: Theme.accent
            }
            Label {
                visible: row.numbered && !row.current
                anchors.verticalCenter: parent.verticalCenter
                text: row.number
                color: Theme.textDim
                font.pixelSize: Theme.fontSmall
            }
        }
        Column {
            anchors { left: num.right; right: time.left; rightMargin: 12; verticalCenter: parent.verticalCenter }
            Label {
                width: parent.width
                text: row.title
                font.pixelSize: Theme.fontBody
                font.weight: row.current ? Font.DemiBold : Font.Normal
                elide: Text.ElideRight
            }
            Label {
                visible: row.subtitle !== ""
                width: parent.width
                text: row.subtitle
                color: Theme.textDim
                font.pixelSize: Theme.fontSmall
                elide: Text.ElideRight
            }
        }
        Label {
            id: time
            anchors { right: parent.right; rightMargin: 16; verticalCenter: parent.verticalCenter }
            text: row.trailing
            color: Theme.textDim
            font.pixelSize: Theme.fontSmall
        }
        TapHandler { id: rowTap; enabled: row.tappable; onTapped: row.hit() }
    }
}
