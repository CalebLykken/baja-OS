import QtQuick
import QtQuick.Layouts
import "../components"

// At-a-glance screen: now playing on the left, the Baja and its key
// readouts on the right.
Item {
    id: page
    signal navigate(int index)

    RowLayout {
        anchors.fill: parent
        spacing: Theme.gap

        NowPlaying {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.preferredWidth: 1
            onOpenMusic: page.navigate(1)
        }

        VehicleCard {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.preferredWidth: 1
            onTapped: page.navigate(3)
        }
    }
}
