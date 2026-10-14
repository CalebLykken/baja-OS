import QtQuick

// Top strip: current screen, clock, and the two numbers worth always seeing.
Item {
    id: bar
    property string title
    property bool showTurn: false       // the next turn while navigating (not on Maps)
    signal turnTapped()
    height: 64

    Label {
        id: titleLabel
        anchors { left: parent.left; verticalCenter: parent.verticalCenter }
        text: bar.title
        color: Theme.text
        font.pixelSize: Theme.fontTitle
        font.weight: Font.DemiBold
    }

    // While navigating: the next turn, between the title and the clock.
    Rectangle {
        id: turnPill
        visible: bar.showTurn && typeof routing !== "undefined" && routing.active
        anchors { left: titleLabel.right; leftMargin: 24; right: clock.left; rightMargin: 24; verticalCenter: parent.verticalCenter }
        height: 48
        radius: Theme.radius
        color: Theme.panel
        border.width: Theme.border
        border.color: Theme.accent
        Row {
            anchors { left: parent.left; leftMargin: 12; right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter }
            spacing: 10
            Icon {
                anchors.verticalCenter: parent.verticalCenter
                name: routing.maneuverIcon || "straight"
                size: 30
                color: Theme.accent
            }
            Label {
                id: turnDist
                anchors.verticalCenter: parent.verticalCenter
                visible: !routing.arrived
                text: Units.distanceText(routing.distanceToTurn)
                font.pixelSize: Theme.fontBody
                font.weight: Font.DemiBold
            }
            Label {
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width - 30 - (turnDist.visible ? turnDist.width : 0) - 20
                elide: Text.ElideRight
                text: routing.instruction
                color: Theme.textDim
                font.pixelSize: Theme.fontSmall
            }
        }
        TapHandler { onTapped: bar.turnTapped() }
    }

    Label {
        id: clock
        anchors.centerIn: parent
        color: Theme.text
        font.pixelSize: Theme.fontTitle
        property date now: new Date()
        text: Units.timeText(now)
        Timer {
            interval: 5000; running: true; repeat: true
            onTriggered: clock.now = new Date()
        }
    }

    Row {
        anchors { right: parent.right; verticalCenter: parent.verticalCenter }
        spacing: 24

        Rectangle {
            visible: typeof demoMode !== "undefined" && demoMode
            anchors.verticalCenter: parent.verticalCenter
            width: demoText.width + 20; height: 30; radius: Theme.radius
            color: Theme.accentDim
            Legend {
                id: demoText
                anchors.centerIn: parent
                text: "Demo data"
                color: Theme.accent
                font.letterSpacing: 1.5
            }
        }
        Label {
            anchors.verticalCenter: parent.verticalCenter
            text: Math.round(Units.temp(vehicle.coolant)) + Units.tempUnit
            color: vehicle.coolant > 230 ? Theme.warn : Theme.textDim
            font.pixelSize: Theme.fontBody
        }
        Label {
            anchors.verticalCenter: parent.verticalCenter
            text: vehicle.voltage.toFixed(1) + " V"
            color: Theme.textDim
            font.pixelSize: Theme.fontBody
        }
    }
}
