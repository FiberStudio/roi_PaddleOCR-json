// 区域识别插件 - 框选窗口（QtQuick / QML）
// 仅使用 QtQuick 2.15 基础组件，兼容 Umi-OCR 裁切版运行环境。
// Python 通过 context property "pyBridge" 与 QML 通信：
//   完成 -> pyBridge.submitRegions(JSON字符串)；取消 -> pyBridge.cancel()
//   预设 -> pyBridge.listPresets() / savePreset(json) / updatePreset(id, json) / deletePreset(id)
// 区域默认命名为"区域1、区域2..."，用户输入可覆盖。
//
// 预设（preset）：把当前这一组区域连同名称、备注保存下来，下次直接加载，
//                 无需重复框选。预设面板由底部「预设」按钮打开。

import QtQuick 2.15
import QtQuick.Window 2.15

Window {
    id: win
    visible: true
    title: "区域识别 - 框选区域"
    modality: Qt.ApplicationModal
    color: "#f0f2f5"
    minimumWidth: 420
    minimumHeight: 340

    // 由 Python 注入的属性
    property int dispW: 800            // 显示图片宽度（像素）
    property int dispH: 600            // 显示图片高度（像素）
    property string imagePath: ""      // 显示图片文件 URL
    property string existingJson: "[]" // 已有区域 JSON
    property string hintText: ""       // 顶部提示
    property string presetsJson: "[]"  // 已有预设摘要 JSON
    property string activePresetId: "" // 全局设置里当前选中的预设 id

    // 状态
    property var regions: JSON.parse(existingJson)  // 已有区域（Python 注入后自动解析）
    property var presets: JSON.parse(presetsJson)   // 预设摘要列表
    property string selectedPresetId: activePresetId
    property string presetMsg: ""        // 预设面板状态/错误提示
    property string pendingDeleteId: ""  // 二次确认删除
    property bool submitted: false
    property int selX1: 0
    property int selY1: 0
    property int selX2: 0
    property int selY2: 0

    width: Math.min(1100, dispW) + 40
    height: Math.min(760, dispH) + 250

    // ==================== 顶部提示 ====================
    Rectangle {
        id: hintBox
        x: 20
        y: 8
        width: win.width - 40
        height: 44
        color: "#eaf2ff"
        border.color: "#b8d4f8"
        radius: 4
        Text {
            anchors.fill: parent
            anchors.margins: 6
            text: hintText !== "" ? hintText
                  : "拖拽框选区域，松开后输入名称（默认自动编号）。可框选多个，完成后点「完成」。"
            wrapMode: Text.Wrap
            verticalAlignment: Text.AlignVCenter
            font.pixelSize: 13
            color: "#333333"
        }
    }

    // ==================== 画布 ====================
    Item {
        id: canvas
        x: 20
        y: 60
        width: win.dispW
        height: win.dispH
        clip: true

        Image {
            id: img
            anchors.fill: parent
            source: win.imagePath
            fillMode: Image.PreserveAspectFit
            cache: false
            smooth: true
        }

        // 已框选的区域（红色叠加框 + 名称标签）
        Repeater {
            model: win.regions
            delegate: Rectangle {
                x: modelData.x1 / 100 * canvas.width
                y: modelData.y1 / 100 * canvas.height
                width: Math.max(2, (modelData.x2 - modelData.x1) / 100 * canvas.width)
                height: Math.max(2, (modelData.y2 - modelData.y1) / 100 * canvas.height)
                color: "#38ff0000"
                border.color: "#ff0000"
                border.width: 2
                Text {
                    text: (index + 1) + ". " + modelData.name
                    color: "#ffffff"
                    style: Text.Outline
                    styleColor: "#000000"
                    font.pixelSize: 14
                    font.bold: true
                    y: -20
                }
            }
        }

        // 正在拖拽的选区
        Rectangle {
            id: dragRect
            visible: false
            color: "#220078ff"
            border.color: "#0078ff"
            border.width: 2
        }

        MouseArea {
            id: ma
            anchors.fill: parent
            cursorShape: Qt.CrossCursor
            property int sx: 0
            property int sy: 0

            onPressed: {
                if (nameEditor.visible) return
                sx = mouse.x
                sy = mouse.y
                dragRect.visible = true
                dragRect.x = sx
                dragRect.y = sy
                dragRect.width = 0
                dragRect.height = 0
            }
            onPositionChanged: {
                if (!dragRect.visible) return
                var x1 = Math.min(sx, mouse.x)
                var y1 = Math.min(sy, mouse.y)
                var x2 = Math.max(sx, mouse.x)
                var y2 = Math.max(sy, mouse.y)
                dragRect.x = x1
                dragRect.y = y1
                dragRect.width = x2 - x1
                dragRect.height = y2 - y1
            }
            onReleased: {
                if (!dragRect.visible) return
                dragRect.visible = false
                if (dragRect.width < 4 || dragRect.height < 4) return
                win.selX1 = dragRect.x
                win.selY1 = dragRect.y
                win.selX2 = dragRect.x + dragRect.width
                win.selY2 = dragRect.y + dragRect.height
                showNameEditor()
            }
        }
    }

    // ==================== 区域命名输入区 ====================
    Rectangle {
        id: nameEditor
        visible: false
        x: 20
        y: win.height - 190
        width: win.width - 40
        height: 88
        color: "#ffffff"
        border.color: "#999999"
        radius: 4

        Text {
            x: 10
            y: 26
            text: "区域名称："
            font.pixelSize: 14
            color: "#333333"
        }
        TextInput {
            id: nameInput
            x: 100
            y: 18
            width: parent.width - 310
            height: 32
            font.pixelSize: 14
            verticalAlignment: Text.AlignVCenter
            selectByMouse: true
            onAccepted: confirmName()
        }
        RegionBtn {
            x: parent.width - 180
            y: 19
            label: "确定"
            fillColor: "#4a90e2"
            onClicked: confirmName()
        }
        RegionBtn {
            x: parent.width - 88
            y: 19
            label: "放弃"
            fillColor: "#95a5a6"
            onClicked: hideNameEditor()
        }
        Text {
            id: nameErrLabel
            x: 10
            y: 56
            width: parent.width - 20
            height: 16
            text: ""
            color: "#c0392b"
            font.pixelSize: 12
            visible: false
        }
    }

    // ==================== 预设面板 ====================
    Rectangle {
        id: presetPanel
        visible: false
        x: 20
        y: win.height - 190
        width: win.width - 40
        height: 140
        color: "#ffffff"
        border.color: "#999999"
        radius: 4

        Text {
            x: 10
            y: 6
            text: "区域预设：点一行选中，再点「加载所选」把它载入本窗口；框选好后点「保存为预设」存下名称与备注。"
            font.pixelSize: 12
            color: "#333333"
        }

        ListView {
            id: presetList
            x: 10
            y: 28
            width: parent.width - 200
            height: 104
            clip: true
            spacing: 2
            model: win.presets

            delegate: Rectangle {
                width: presetList.width
                height: 24
                color: (win.selectedPresetId === modelData.id) ? "#cfe4ff" : "transparent"
                border.color: (win.selectedPresetId === modelData.id) ? "#4a90e2" : "transparent"
                Text {
                    anchors.fill: parent
                    anchors.leftMargin: 4
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                    font.pixelSize: 12
                    color: "#333333"
                    text: (index + 1) + ". " + modelData.name
                          + (modelData.remark ? "　—　" + modelData.remark : "")
                          + "（" + modelData.regionCount + " 个区域："
                          + modelData.regionNames.join("、") + "）"
                }
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        win.selectedPresetId = modelData.id
                        win.pendingDeleteId = ""
                        win.presetMsg = ""
                    }
                    onDoubleClicked: win.doLoadPreset()
                }
            }
        }

        Text {
            x: 10
            y: 30
            width: parent.width - 200
            visible: win.presets.length === 0
            wrapMode: Text.Wrap
            text: "（暂无预设。先拖拽框选区域，再点右侧「保存为预设」，填写名称和备注。）"
            font.pixelSize: 12
            color: "#888888"
        }

        RegionBtn {
            x: parent.width - 186
            y: 26
            label: "加载所选"
            onClicked: win.doLoadPreset()
        }
        RegionBtn {
            x: parent.width - 94
            y: 26
            label: "保存为预设"
            fillColor: "#27ae60"
            onClicked: win.showPresetEditor()
        }
        RegionBtn {
            x: parent.width - 186
            y: 62
            label: "更新所选"
            fillColor: "#4a90e2"
            onClicked: win.doUpdatePreset()
        }
        RegionBtn {
            x: parent.width - 94
            y: 62
            label: "删除所选"
            fillColor: "#c0392b"
            onClicked: win.doDeletePreset()
        }
        Text {
            x: parent.width - 186
            y: 98
            width: 176
            height: 36
            wrapMode: Text.Wrap
            font.pixelSize: 11
            color: "#c0392b"
            text: win.presetMsg
        }
    }

    // ==================== 保存预设（名称 + 备注） ====================
    Rectangle {
        id: presetEditor
        visible: false
        x: 20
        y: win.height - 190
        width: win.width - 40
        height: 140
        color: "#ffffff"
        border.color: "#999999"
        radius: 4

        Text {
            x: 10
            y: 12
            text: "预设名称："
            font.pixelSize: 13
            color: "#333333"
        }
        TextInput {
            id: presetNameInput
            objectName: "presetNameInput"
            x: 84
            y: 6
            width: Math.min(300, parent.width - 280)
            height: 30
            font.pixelSize: 13
            verticalAlignment: Text.AlignVCenter
            selectByMouse: true
            onAccepted: win.confirmSavePreset()
        }
        Text {
            x: 10
            y: 52
            text: "备注："
            font.pixelSize: 13
            color: "#333333"
        }
        TextInput {
            id: presetRemarkInput
            objectName: "presetRemarkInput"
            x: 84
            y: 46
            width: parent.width - 280
            height: 30
            font.pixelSize: 13
            verticalAlignment: Text.AlignVCenter
            selectByMouse: true
            onAccepted: win.confirmSavePreset()
        }
        Text {
            x: 84
            y: 80
            width: parent.width - 290
            wrapMode: Text.Wrap
            text: "备注写清这是什么单据/用途，例如「增值税发票：号码在右上角」。同名保存会覆盖旧预设。"
            font.pixelSize: 11
            color: "#888888"
        }
        Text {
            id: presetErrLabel
            x: 84
            y: 110
            width: parent.width - 290
            height: 24
            text: ""
            color: "#c0392b"
            font.pixelSize: 12
            wrapMode: Text.Wrap
            visible: false
        }
        RegionBtn {
            x: parent.width - 186
            y: 100
            label: "保存"
            fillColor: "#27ae60"
            onClicked: win.confirmSavePreset()
        }
        RegionBtn {
            x: parent.width - 94
            y: 100
            label: "取消"
            fillColor: "#95a5a6"
            onClicked: win.hidePresetEditor()
        }
    }

    // ==================== 底部操作按钮 ====================
    Row {
        x: 20
        y: win.height - 42
        spacing: 10

        RegionBtn {
            label: "撤销上一个"
            fillColor: "#7f8c8d"
            onClicked: doUndo()
        }
        RegionBtn {
            label: "清空全部"
            fillColor: "#7f8c8d"
            onClicked: doClear()
        }
        RegionBtn {
            label: "预设"
            fillColor: "#8e44ad"
            onClicked: togglePresetPanel()
        }
        Item {
            width: Math.max(10, win.width - 40 - 84 * 5 - 10 * 5)
            height: 1
        }
        RegionBtn {
            label: "取消"
            fillColor: "#e74c3c"
            onClicked: doCancel()
        }
        RegionBtn {
            label: "完成"
            fillColor: "#27ae60"
            onClicked: doDone()
        }
    }

    // ==================== JS 逻辑 ====================

    // 取下一个未使用的默认名称（区域1、区域2...）
    function nextDefaultName() {
        var n = 1
        while (true) {
            var candidate = "区域" + n
            var used = false
            for (var i = 0; i < regions.length; i++) {
                if (regions[i].name === candidate) {
                    used = true
                    break
                }
            }
            if (!used) return candidate
            n++
        }
    }

    function showNameEditor() {
        presetPanel.visible = false
        presetEditor.visible = false
        nameEditor.visible = true
        nameErrLabel.visible = false
        nameInput.text = nextDefaultName()
        nameInput.selectAll()   // 选中默认名，直接输入即可覆盖
        nameInput.forceActiveFocus()
    }
    function hideNameEditor() {
        nameEditor.visible = false
    }
    function confirmName() {
        var name = nameInput.text.trim()
        if (name === "") name = nextDefaultName()  // 空则用默认名
        for (var i = 0; i < regions.length; i++) {
            if (regions[i].name === name) {
                nameErrLabel.text = "名称重复，请换一个！"
                nameErrLabel.visible = true
                return
            }
        }
        regions.push({
            "name": name,
            "x1": selX1 / canvas.width * 100,
            "y1": selY1 / canvas.height * 100,
            "x2": selX2 / canvas.width * 100,
            "y2": selY2 / canvas.height * 100
        })
        nameInput.text = ""
        nameErrLabel.visible = false
        hideNameEditor()
    }
    function doUndo() {
        if (regions.length > 0) regions.pop()
    }
    function doClear() {
        regions = []
        pendingDeleteId = ""
    }
    function doDone() {
        if (regions.length === 0) return
        submitted = true
        pyBridge.submitRegions(JSON.stringify(regions))
        win.close()  // 从 QML 侧关闭窗口，确保自动消失
    }
    function doCancel() {
        submitted = true
        pyBridge.cancel()
        win.close()
    }

    // ==================== 预设逻辑 ====================

    function findPreset(id) {
        for (var i = 0; i < presets.length; i++) {
            if (presets[i].id === id) return presets[i]
        }
        return null
    }

    function refreshPresets(list) {
        if (typeof list === "string") {  // 兼容直接传入 JSON 字符串
            try {
                list = JSON.parse(list)
            } catch (e) {
                list = []
            }
        }
        presets = list ? list : []
        if (!findPreset(selectedPresetId)) selectedPresetId = ""
    }

    // 处理 Python 返回的 {"ok":bool,"message":str,"id":str,"presets":[...]}
    function applyResult(resJson) {
        var res = null
        try {
            res = JSON.parse(resJson)
        } catch (e) {
            res = null
        }
        if (res === null || typeof res.ok === "undefined") {
            presetMsg = "预设操作失败：返回数据异常。"
            return false
        }
        if (res.presets) refreshPresets(res.presets)
        presetMsg = res.message ? res.message : ""
        return res.ok === true
    }

    function togglePresetPanel() {
        nameEditor.visible = false
        presetEditor.visible = false
        presetErrLabel.visible = false
        pendingDeleteId = ""
        presetPanel.visible = !presetPanel.visible
        if (presetPanel.visible) {
            presetMsg = ""
            refreshPresets(JSON.parse(pyBridge.listPresets()))
        }
    }

    function showPresetEditor() {
        if (regions.length === 0) {
            nameEditor.visible = false
            presetPanel.visible = true
            presetEditor.visible = false
            presetMsg = "请先框选至少一个区域，再保存为预设。"
            return
        }
        nameEditor.visible = false
        presetPanel.visible = false
        presetEditor.visible = true
        presetNameInput.text = ""
        presetRemarkInput.text = ""
        presetErrLabel.text = ""
        presetErrLabel.visible = false
        presetNameInput.forceActiveFocus()
    }

    function hidePresetEditor() {
        presetEditor.visible = false
        presetErrLabel.visible = false
        presetPanel.visible = true
    }

    function confirmSavePreset() {
        var name = presetNameInput.text.trim()
        if (name === "") {
            presetErrLabel.text = "请填写预设名称。"
            presetErrLabel.visible = true
            return
        }
        var resJson = pyBridge.savePreset(JSON.stringify({
            "name": name,
            "remark": presetRemarkInput.text.trim(),
            "regions": regions
        }))
        var res = null
        try {
            res = JSON.parse(resJson)
        } catch (e) {
            res = null
        }
        if (res === null || res.ok !== true) {
            presetErrLabel.text = (res && res.message) ? res.message : "保存失败。"
            presetErrLabel.visible = true
            return
        }
        presetEditor.visible = false
        presetErrLabel.visible = false
        presetPanel.visible = true
        refreshPresets(res.presets)
        selectedPresetId = res.id ? res.id : ""
        presetMsg = res.message ? res.message : "已保存。"
    }

    function doLoadPreset() {
        var brief = findPreset(selectedPresetId)
        if (brief === null) {
            presetPanel.visible = true
            presetMsg = "请先在上方列表中点选一个预设。"
            return
        }
        // 列表里只有摘要，向 Python 取完整预设（含区域坐标）
        var preset = null
        try {
            var res = JSON.parse(pyBridge.getPreset(brief.id))
            if (res && res.ok === true && res.preset) preset = res.preset
            else presetMsg = (res && res.message) ? res.message : "读取预设失败。"
        } catch (e) {
            preset = null
            presetMsg = "读取预设失败：" + e
        }
        if (preset === null) {
            presetPanel.visible = true
            return
        }
        regions = preset.regions  // 每次都是新解析出来的对象，可直接使用
        presetPanel.visible = false
        nameEditor.visible = false
        pendingDeleteId = ""
        presetMsg = ""
        hintText = "已载入预设「" + preset.name + "」的 " + regions.length
                   + " 个区域。可直接点「完成」开始识别，或继续框选调整后点「预设」→「更新所选」。"
    }

    function doUpdatePreset() {
        var preset = findPreset(selectedPresetId)
        if (preset === null) {
            presetMsg = "请先在上方列表中点选一个预设。"
            return
        }
        if (regions.length === 0) {
            presetMsg = "当前没有区域，无法更新预设。"
            return
        }
        applyResult(pyBridge.updatePreset(preset.id, JSON.stringify(regions)))
    }

    function doDeletePreset() {
        var preset = findPreset(selectedPresetId)
        if (preset === null) {
            presetMsg = "请先在上方列表中点选一个预设。"
            return
        }
        if (pendingDeleteId !== preset.id) {
            pendingDeleteId = preset.id
            presetMsg = "再点一次「删除所选」确认删除「" + preset.name + "」。"
            return
        }
        pendingDeleteId = ""
        if (applyResult(pyBridge.deletePreset(preset.id))) selectedPresetId = ""
    }

    onClosing: {
        // 用户直接关闭窗口（点X）：未提交则视为取消
        if (!submitted) {
            submitted = true
            pyBridge.cancel()
        }
    }
}
