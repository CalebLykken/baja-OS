import QtQuick
import QtQuick.Layouts
import "../components"

// The Music page, full screen like Maps (the clock moves into the rail).
//
// - Left: what's playing. The cover, the song, the keys and the volume;
//   the equalizer key opens the EQ over the right-hand side.
// - Right: three tabs. Up next (Spotify's queue, or the Pi's songs playing
//   through); Albums (the Pi's own music by album: open one to play it, or
//   a song in it); Spotify (albums and playlists played here recently, one
//   tap to play again).
// - While navigating, the next turn sits on top of the right side; tap it
//   for Maps.
Item {
    id: page
    objectName: "musicPage"
    signal navigate(int index)

    property bool eqOpen: false
    property string tab: "next"                // "next", "albums" or "spotify"
    property int openAlbum: -1                 // the album shown in Albums, or -1 for all of them
    property var openKey: null                 // [artist, title] of the open album: a rescan can renumber albums
    onVisibleChanged: if (!visible) { eqOpen = false; openAlbum = -1 }
    Connections {
        target: media
        function onAlbumsChanged() {
            if (page.openAlbum < 0 || !page.openKey) return
            var list = media.albums, found = -1
            for (var i = 0; i < list.length; i++)
                if (list[i].artist.toLowerCase() === page.openKey[0].toLowerCase()
                        && list[i].title.toLowerCase() === page.openKey[1].toLowerCase()) { found = i; break }
            page.openAlbum = found      // closed if it's gone
        }
    }

    readonly property bool navigating: typeof routing !== "undefined" && routing.active
    readonly property var albums: media.albums
    readonly property bool idle: media.source === "local" && media.title === ""   // no music on the Pi, and the phone and Spotify aren't playing
    readonly property bool hasSpotify: typeof spotify !== "undefined" && spotify.available

    function mmss(s) {
        var m = Math.floor(s / 60), r = s % 60
        return m + ":" + (r < 10 ? "0" : "") + r
    }
    function albumLength(s) {
        var min = Math.round(s / 60)
        return min < 60 ? min + " min" : Math.floor(min / 60) + " h " + (min % 60) + " min"
    }

    RowLayout {
        anchors { fill: parent; margins: 20 }
        spacing: 20

        // ==== what's playing =============================================
        Card {
            id: nowCard
            Layout.fillHeight: true
            Layout.preferredWidth: 460

            ColumnLayout {
                anchors { fill: parent; margins: 24; topMargin: 14 }
                spacing: 6

                RowLayout {
                    Layout.fillWidth: true
                    SourceBadge {}
                    Item { Layout.fillWidth: true }
                    // The Pi's own music only: Spotify and the phone have no way to set these from here.
                    IconButton {
                        visible: media.hasModes
                        icon: "shuffle"
                        size: 60
                        active: media.shuffle
                        onClicked: media.toggleShuffle()
                    }
                    IconButton {
                        visible: media.hasModes
                        icon: media.repeat === "one" ? "repeat_one" : "repeat"
                        size: 60
                        active: media.repeat !== "off"
                        onClicked: media.cycleRepeat()
                    }
                    IconButton {
                        icon: "equalizer"
                        size: 60
                        active: page.eqOpen
                        onClicked: page.eqOpen = !page.eqOpen
                    }
                }
                AlbumArt {
                    Layout.alignment: Qt.AlignHCenter
                    Layout.topMargin: 4
                    Layout.preferredWidth: Math.min(nowCard.width - 60, 320)
                    Layout.preferredHeight: Layout.preferredWidth
                    source: media.artCard
                    placeholder: media.source === "phone" ? "phone" : "music"
                }
                Label {
                    Layout.fillWidth: true
                    Layout.topMargin: 18
                    text: page.idle ? (media.scanning ? "Reading your music" : "Nothing playing") : media.title
                    color: page.idle ? Theme.textDim : Theme.text
                    font.pixelSize: Theme.fontTitle
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
                }
                Label {
                    Layout.fillWidth: true
                    text: media.artist
                    color: Theme.textDim
                    font.pixelSize: Theme.fontBody
                    elide: Text.ElideRight
                }
                Item { Layout.fillHeight: true }

                // Tap or drag to seek. The touch area is much taller than the bar;
                // the song only jumps on release, so a drag doesn't re-decode.
                Item {
                    id: seekArea
                    Layout.fillWidth: true
                    Layout.preferredHeight: 48
                    readonly property bool canSeek: media.canSeek && media.duration > 0 && !page.idle
                    property real dragValue: 0
                    property bool dragging: false
                    function at(x) { return Math.max(0, Math.min(1, x / width)) }
                    ProgressBar {
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width
                        value: seekArea.dragging ? seekArea.dragValue
                                                 : (media.duration > 0 ? media.position / media.duration : 0)
                    }
                    MouseArea {
                        anchors.fill: parent
                        enabled: seekArea.canSeek
                        onPressed: (m) => { seekArea.dragValue = seekArea.at(m.x); seekArea.dragging = true }
                        onPositionChanged: (m) => seekArea.dragValue = seekArea.at(m.x)
                        onReleased: (m) => {
                            seekArea.dragging = false
                            media.seek(Math.round(seekArea.at(m.x) * media.duration))
                        }
                        onCanceled: seekArea.dragging = false
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Label { text: page.idle ? "" : page.mmss(seekArea.dragging ? Math.round(seekArea.dragValue * media.duration) : media.position); color: Theme.textDim; font.pixelSize: Theme.fontSmall }
                    Item { Layout.fillWidth: true }
                    Label { text: page.idle ? "" : page.mmss(media.duration); color: Theme.textDim; font.pixelSize: Theme.fontSmall }
                }
                Row {
                    Layout.alignment: Qt.AlignHCenter
                    spacing: 28
                    opacity: page.idle ? 0.4 : 1
                    enabled: !page.idle
                    IconButton { icon: "previous"; size: 84; anchors.verticalCenter: parent.verticalCenter; onClicked: media.previous() }
                    IconButton {
                        icon: media.playing ? "pause" : "play"
                        primary: true
                        size: 104
                        onClicked: media.togglePlay()
                    }
                    IconButton { icon: "next"; size: 84; anchors.verticalCenter: parent.verticalCenter; onClicked: media.next() }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Layout.topMargin: 8
                    spacing: 14
                    IconButton { icon: "remove"; size: 60; onClicked: media.volumeDown() }
                    LevelBar {
                        Layout.fillWidth: true
                        opacity: media.muted ? 0.35 : 1
                        value: media.volume / 100
                        onMoved: (v) => media.setVolume(Math.round(v * 100))
                    }
                    Label {
                        Layout.preferredWidth: 64
                        horizontalAlignment: Text.AlignRight
                        color: media.muted ? Theme.warn : Theme.text
                        text: media.muted ? "Mute" : media.volume
                        font.family: Theme.numFont
                        font.pixelSize: Theme.fontBody
                        font.weight: Font.DemiBold
                    }
                    IconButton { icon: "add"; size: 60; onClicked: media.volumeUp() }
                }
            }
        }

        // ==== the right side =============================================
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 16

            // While navigating: the next turn (tap for Maps).
            Rectangle {
                visible: page.navigating
                Layout.fillWidth: true
                Layout.preferredHeight: 92
                radius: Theme.radius
                color: turnTap.pressed ? Theme.panelHi : Theme.panel
                border.width: Theme.border
                border.color: Theme.accent
                RowLayout {
                    anchors { fill: parent; leftMargin: 20; rightMargin: 20 }
                    spacing: 16
                    Icon {
                        name: page.navigating ? routing.maneuverIcon || "straight" : "straight"
                        size: 56
                        color: Theme.accent
                    }
                    Label {
                        visible: page.navigating && !routing.arrived
                        text: page.navigating ? Units.distanceText(routing.distanceToTurn) : ""
                        font.family: Theme.numFont
                        font.pixelSize: Theme.fontTitle
                        font.weight: Font.DemiBold
                    }
                    Label {
                        Layout.fillWidth: true
                        text: page.navigating ? routing.instruction : ""
                        color: Theme.textDim
                        font.pixelSize: Theme.fontBody
                        elide: Text.ElideRight
                    }
                }
                TapHandler { id: turnTap; onTapped: page.navigate(2) }
            }

            SegmentedControl {
                Layout.fillWidth: true
                height: 72
                stretch: true
                options: [{ label: "Up next", value: "next" },
                          { label: "Albums", value: "albums" },
                          { label: "Spotify", value: "spotify" }]
                current: page.tab
                onPicked: (v) => { page.tab = v; page.openAlbum = -1; page.eqOpen = false }
            }

            Card {
                id: content
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                heading: page.eqOpen ? "Equalizer"
                         : page.tab === "next" ? (media.source === "spotify" ? "Up next on Spotify"
                                                  : page.albums[media.album] ? "Playing the album " + page.albums[media.album].title
                                                  : "All songs on this Pi")
                         : page.tab === "albums" ? (page.openAlbum >= 0 ? "" : "Albums on this Pi")
                         : "Played here recently"

                // ---- Up next ------------------------------------------------
                ListView {
                    id: queue
                    visible: page.tab === "next" && !page.eqOpen
                    readonly property bool spotifyQueue: media.source === "spotify"
                    anchors { fill: parent; margins: 10; topMargin: 52 }
                    clip: true
                    model: spotifyQueue ? media.upNext : media.queue
                    boundsBehavior: Flickable.StopAtBounds
                    // Open on the playing song, and follow it as it changes.
                    function showPlaying() {
                        if (visible && !spotifyQueue && media.index >= 0 && count > 0)
                            positionViewAtIndex(media.index, ListView.Center)
                    }
                    onVisibleChanged: Qt.callLater(showPlaying)
                    onCountChanged: Qt.callLater(showPlaying)
                    Connections {
                        target: media
                        function onTrackChanged() { Qt.callLater(queue.showPlaying) }
                    }
                    delegate: SongRow {
                        width: queue.width
                        number: index + 1
                        current: !queue.spotifyQueue && index === media.index
                        title: modelData.title
                        subtitle: modelData.artist
                        tappable: !queue.spotifyQueue
                        onHit: media.playIndex(index)
                    }
                    Label {
                        visible: queue.count === 0
                        anchors { left: parent.left; top: parent.top; leftMargin: 10; topMargin: 10 }
                        text: queue.spotifyQueue ? "Nothing queued in Spotify" : media.scanning ? "Reading your music..." : "No songs in ~/Music on the Pi"
                        color: Theme.textDim
                        font.pixelSize: Theme.fontBody
                    }
                }

                // ---- Albums: all of them ------------------------------------
                GridView {
                    id: albumGrid
                    visible: page.tab === "albums" && page.openAlbum < 0 && !page.eqOpen
                    anchors { fill: parent; margins: 14; topMargin: 56 }
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    cellWidth: Math.floor(width / 3)
                    cellHeight: cellWidth + 74
                    model: page.albums
                    delegate: CoverTile {
                        width: albumGrid.cellWidth
                        height: albumGrid.cellHeight
                        art: modelData.art
                        placeholder: "album"
                        title: modelData.title
                        subtitle: modelData.artist
                        current: index === media.album
                        onHit: { page.openKey = [modelData.artist, modelData.title]; page.openAlbum = index }
                    }
                    Label {
                        visible: albumGrid.count === 0
                        width: parent.width
                        wrapMode: Text.WordWrap
                        text: media.scanning ? "Reading your music..." : "No music on the Pi yet. Albums copied into ~/Music on the Pi show up here."
                        color: Theme.textDim
                        font.pixelSize: Theme.fontBody
                    }
                }

                // ---- Albums: one open ---------------------------------------
                Item {
                    id: albumView
                    visible: page.tab === "albums" && page.openAlbum >= 0 && !page.eqOpen
                    anchors { fill: parent; margins: 16 }
                    readonly property var album: page.openAlbum >= 0 ? page.albums[page.openAlbum] : null
                    readonly property var tracks: page.openAlbum >= 0 && page.albums ? media.albumTracks(page.openAlbum) : []   // page.albums: re-read when a rescan changes the songs

                    RowLayout {
                        id: albumHead
                        anchors { left: parent.left; right: parent.right; top: parent.top }
                        spacing: 18
                        IconButton {
                            Layout.alignment: Qt.AlignTop
                            icon: "back"
                            size: 72
                            onClicked: page.openAlbum = -1
                        }
                        Cover {
                            Layout.preferredWidth: 150
                            Layout.preferredHeight: 150
                            art: albumView.album ? albumView.album.art : ""
                            placeholder: "album"
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.preferredWidth: 1            // take what's left, not the title's length
                            Layout.alignment: Qt.AlignVCenter
                            spacing: 4
                            Label {
                                Layout.fillWidth: true
                                text: albumView.album ? albumView.album.title : ""
                                font.pixelSize: Theme.fontTitle
                                font.weight: Font.DemiBold
                                wrapMode: Text.WordWrap
                                maximumLineCount: 2
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
                            implicitWidth: 150
                            implicitHeight: 96
                            text: "Play"
                            icon: "play"
                            primary: true
                            onClicked: media.playAlbum(page.openAlbum, -1)
                        }
                    }
                    ListView {
                        id: albumSongs
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
                GridView {
                    id: spotifyGrid
                    visible: page.tab === "spotify" && !page.eqOpen
                    anchors { fill: parent; margins: 14; topMargin: 56 }
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    cellWidth: Math.floor(width / 3)
                    cellHeight: cellWidth + 74
                    model: media.spotifyRecents
                    delegate: CoverTile {
                        width: spotifyGrid.cellWidth
                        height: spotifyGrid.cellHeight
                        art: modelData.art
                        placeholder: modelData.kind === "playlist" ? "queue" : "album"
                        title: modelData.title
                        subtitle: modelData.subtitle
                        current: index === 0 && media.source === "spotify" && media.playing
                        onHit: media.playSpotify(modelData.uri)
                    }
                    Label {
                        visible: spotifyGrid.count === 0
                        width: parent.width
                        wrapMode: Text.WordWrap
                        text: !page.hasSpotify ? "Spotify isn't running on the Pi right now."
                              : "Albums and playlists you play here through Spotify show up here. "
                                + "In the Spotify app on your phone, pick " + (spotify.deviceName || "this Pi")
                                + " as the speaker and play something."
                        color: Theme.textDim
                        font.pixelSize: Theme.fontBody
                    }
                }

                // ---- the equalizer, over the right-hand side ----------------
                IconButton {
                    visible: page.eqOpen
                    anchors { right: parent.right; top: parent.top; margins: 14 }
                    icon: "close"
                    size: 56
                    onClicked: page.eqOpen = false
                }
                EqualizerPanel {
                    visible: page.eqOpen
                    anchors { fill: parent; margins: 20; topMargin: 84 }
                }
            }
        }
    }

    // ---- small parts ------------------------------------------------------
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
            sourceSize: Qt.size(360, 360)          // decode small: there are many
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
                font.pixelSize: Theme.fontSmall + 2
                font.weight: Font.DemiBold
                color: tile.current ? Theme.accent : Theme.text
                elide: Text.ElideRight
            }
            Label {
                width: parent.width
                text: tile.subtitle
                color: Theme.textDim
                font.pixelSize: Theme.fontSmall - 2
                elide: Text.ElideRight
            }
        }
        TapHandler { id: tileTap; onTapped: tile.hit() }
    }

    // A song in a list: its number (or a playing mark), title, and a second
    // line or a time on the right.
    component SongRow: Rectangle {
        id: row
        property int number
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
            width: 52
            height: parent.height
            anchors { left: parent.left; leftMargin: 10 }
            Icon {
                visible: row.current
                anchors.verticalCenter: parent.verticalCenter
                name: "equalizer"
                size: 24
                color: Theme.accent
            }
            Label {
                visible: !row.current
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
