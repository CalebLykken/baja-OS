import QtQuick
import QtQuick.Layouts

// The Home screen's music card: the cover as a framed print beside where the
// music comes from, title and artist; progress and the transport keys run
// across underneath. No heading: a song explains itself. Tap the cover to
// open Music. With no music on the Pi (and nothing from the phone or
// Spotify) it says "Nothing playing" and how to get some, with the keys
// dimmed.
Card {
    id: np
    signal openMusic()

    readonly property bool idle: media.source === "local" && media.title === ""

    // What the labels show. They trail the live track by the length of the
    // slide, so the words can change while they are out of sight.
    property string shownTitle: ""
    property string shownArtist: ""
    property bool seeded: false
    // The title the running slide is heading to.
    property string slideTarget: ""
    // Which way the words travel: 1 slides them out to the left and in from
    // the right, -1 the other way round (after a tap on Previous).
    property int slideDir: 1
    // When Previous was last tapped, and how long that tap still counts. A
    // timestamp rather than a timer: a Previous that only restarts the song
    // changes no title, and the stale tap just expires.
    property real prevTappedAt: 0
    property int prevWindowMs: 1500
    readonly property real slideX: shift.x
    // With no song yet the title says why, and the line under it says what to
    // do: nothing on the Pi, the Pi's music still being read, or Spotify starting.
    readonly property string liveTitle: np.idle ? (media.scanning ? "Reading your music" : "Nothing playing")
                                        : media.title !== "" ? media.title
                                        : media.source === "spotify" ? "Starting Spotify..." : ""
    // The artist, then the album: "Boxer Rebellion · Bed Liner Sessions".
    // "Unknown artist" (untagged files) is left out.
    readonly property string liveArtist: {
        if (np.idle) return media.scanning ? "Songs show up as they're found"
                                           : "Pair a phone in Settings, or copy songs to ~/Music"
        var parts = []
        if (media.artist && media.artist !== "Unknown artist") parts.push(media.artist)
        if (media.albumTitle) parts.push(media.albumTitle)
        return parts.join(" \u00b7 ")
    }

    Component.onCompleted: {
        shownTitle = liveTitle
        shownArtist = liveArtist
        seeded = true
    }
    // Title and artist come from one notify signal, so both change handlers
    // fire for one track change. Deferred on purpose: one emission, one
    // decision, made after both values have settled.
    onLiveTitleChanged: Qt.callLater(np.trackChanged)
    onLiveArtistChanged: Qt.callLater(np.trackChanged)

    // A new song slides the words out to the left, swaps them while they
    // are invisible, and slides them back in from the right (a card being
    // moved along, pairing with the cover's crossfade). After a tap on
    // Previous the slide runs the other way (out to the right, in from the
    // left), so going back feels like moving the card back. A skip mid-slide
    // settles the words at once and starts over, so they never stay
    // half-faded or stale. Only the title starts the slide: an artist
    // change alone just updates in place.
    function tapPrevious() {
        prevTappedAt = Date.now()
        media.previous()
    }

    function trackChanged() {
        if (!seeded) return
        if (liveTitle === shownTitle) {
            shownArtist = liveArtist
            return
        }
        // Already sliding to this title: the midpoint script reads the live
        // values, so there is nothing to restart.
        if (slide.running && liveTitle === slideTarget) return
        if (slide.running) {
            slide.stop()
            words.opacity = 1
            shift.x = 0
            shownTitle = liveTitle
            shownArtist = liveArtist
        }
        slideTarget = liveTitle
        slideDir = (Date.now() - prevTappedAt < prevWindowMs) ? -1 : 1
        prevTappedAt = 0
        slide.start()
    }

    SequentialAnimation {
        id: slide
        ParallelAnimation {
            NumberAnimation { target: words; property: "opacity"; from: 1; to: 0; duration: 120; easing.type: Easing.InCubic }
            NumberAnimation { target: shift; property: "x"; from: 0; to: -28 * np.slideDir; duration: 120; easing.type: Easing.InCubic }
        }
        ScriptAction {
            script: {
                np.shownTitle = np.liveTitle
                np.shownArtist = np.liveArtist
                shift.x = 28 * np.slideDir
            }
        }
        ParallelAnimation {
            NumberAnimation { target: words; property: "opacity"; from: 0; to: 1; duration: 200; easing.type: Easing.OutCubic }
            NumberAnimation { target: shift; property: "x"; from: 28 * np.slideDir; to: 0; duration: 200; easing.type: Easing.OutCubic }
        }
    }

    function mmss(s) {
        var m = Math.floor(s / 60), r = s % 60
        return m + ":" + (r < 10 ? "0" : "") + r
    }

    ColumnLayout {
        anchors { fill: parent; margins: 20 }
        spacing: 6

        // A plain Item, so the cover can size itself from the space the
        // column gives this row without a layout loop.
        Item {
            id: top
            Layout.fillWidth: true
            Layout.fillHeight: true

            AlbumArt {
                id: art
                // Leave room for the print's offset shadow below and right.
                width: Math.min(top.height - 12, top.width * 0.52)
                height: width
                anchors { left: parent.left; verticalCenter: parent.verticalCenter; verticalCenterOffset: -4 }
                source: media.artCard
                placeholder: media.source === "phone" ? "phone" : "music"
                TapHandler { onTapped: np.openMusic() }
            }

            ColumnLayout {
                id: words
                // Translate moves the words without touching the anchors.
                transform: Translate { id: shift }
                anchors { left: art.right; leftMargin: 26; right: parent.right; verticalCenter: art.verticalCenter }
                spacing: 6

                SourceBadge { Layout.fillWidth: true }
                Label {
                    objectName: "nowTitle"
                    Layout.fillWidth: true
                    Layout.topMargin: 2
                    text: np.shownTitle
                    color: media.title === "" ? Theme.textDim : Theme.text
                    font.pixelSize: Theme.fontTitle
                    font.weight: Font.DemiBold
                    wrapMode: Text.WordWrap
                    maximumLineCount: 3
                    elide: Text.ElideRight
                }
                Label {
                    objectName: "nowArtist"
                    Layout.fillWidth: true
                    text: np.shownArtist
                    color: Theme.textDim
                    font.pixelSize: Theme.fontBody
                    // The hint with nothing to play may take two lines; a song's artist stays on one.
                    wrapMode: np.idle ? Text.WordWrap : Text.NoWrap
                    maximumLineCount: np.idle ? 2 : 1
                    elide: Text.ElideRight
                }
            }
        }

        ProgressBar {
            Layout.fillWidth: true
            Layout.topMargin: 14
            value: media.duration > 0 ? media.position / media.duration : 0
        }
        RowLayout {
            Layout.fillWidth: true
            Label { text: np.idle ? "" : np.mmss(media.position); color: Theme.textDim; font.pixelSize: Theme.fontSmall }
            Item { Layout.fillWidth: true }
            Label { text: np.idle ? "" : np.mmss(media.duration); color: Theme.textDim; font.pixelSize: Theme.fontSmall }
        }

        Row {
            Layout.alignment: Qt.AlignHCenter
            spacing: 20
            opacity: np.idle ? 0.4 : 1
            enabled: !np.idle
            IconButton { icon: "previous"; size: 76; anchors.verticalCenter: parent.verticalCenter; onClicked: np.tapPrevious() }
            IconButton {
                icon: media.playing ? "pause" : "play"
                primary: true
                size: 96
                onClicked: media.togglePlay()
            }
            IconButton { icon: "next"; size: 76; anchors.verticalCenter: parent.verticalCenter; onClicked: media.next() }
        }
    }
}
