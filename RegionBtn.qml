// 区域识别插件 - 通用按钮组件（QtQuick 2.15 基础组件）
// 用法：RegionBtn { label: "完成"; fillColor: "#27ae60"; onClicked: xxx() }
import QtQuick 2.15

Rectangle {
    id: root
    property string label: "按钮"
    property string fillColor: "#4a90e2"
    property string txtColor: "#ffffff"
    signal clicked()

    width: 84
    height: 30
    radius: 5
    color: fillColor
    border.color: Qt.darker(fillColor)
    border.width: 1

    Text {
        anchors.centerIn: parent
        text: root.label
        color: root.txtColor
        font.pixelSize: 13
        font.bold: true
    }
    MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }
}
