# -*- coding: utf-8 -*-
# 区域识别插件 - 区域框选窗口（基于 Qt Quick / QML）
#
# 重要：Umi-OCR 运行时的 PySide2 是手动裁切版，只有 QtCore/QtGui/QtQml，
# 没有 QtWidgets（QWidget/QDialog 不可用），因此框选窗口必须用 QML 实现。
#
# 线程模型：
# - 批量 OCR / 批量文档任务运行在 QThreadPool 子线程，Qt 控件必须在主线程
#   创建/显示。本模块采用与 Umi 官方 CallFunc 相同的模式：工作线程通过
#   Qt 信号把"弹窗任务"投递到主线程执行（队列连接），再用 threading.Event
#   等待用户完成框选。不使用 QMetaObject.invokeMethod / Q_ARG，避免跨线程
#   参数封送抛异常导致工作线程静默死亡（表现为"卡住且无窗口"）。
# - 若运行环境没有 PySide2（如纯命令行测试），本模块可被安全导入，
#   仅在实际弹窗时报错提示。

import json
import os
import threading

from . import roi_debug as D

_HAS_QT = True
try:
    from PySide2.QtCore import QObject, Qt, QThread, QUrl, Slot, Signal
    from PySide2.QtGui import QGuiApplication
    from PySide2.QtQml import QQmlComponent, QQmlEngine
except Exception as _e:  # pragma: no cover - 无 Qt 环境
    _HAS_QT = False
    _QT_ERROR = str(_e)
    QObject = object
    Qt = None
    QThread = object
    QUrl = object
    Slot = lambda *a, **k: (lambda f: f)
    Signal = lambda *a, **k: None
    QGuiApplication = object
    QQmlComponent = object
    QQmlEngine = object

from .roi_region import Region


def _requireQt():
    if not _HAS_QT:
        raise RuntimeError(
            f"[Error] 当前环境没有 PySide2，无法弹出框选窗口。{_QT_ERROR}"
        )


class _RegionSelectBridge(QObject):
    """常驻主线程的调度桥：把弹窗任务投递到主线程，用 QML 窗口框选区域。

    工作线程调用 selectRegionsInteractive() 后，通过 Qt 信号（队列连接）
    让 _onRequested 在主线程运行：创建 QML 窗口。用户在窗口内框选命名后，
    QML 调用本对象的 submitRegions/cancel（@Slot），结果存入 _result，
    并设置 threading.Event 唤醒等待的工作线程。
    """

    # imagePath, regionsJson, hint, w, h, presetsJson, activePresetId
    _requested = Signal(str, str, str, int, int, str, str)

    def __init__(self):
        super().__init__()
        self._result = None
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._engine = None  # QQmlEngine（保持引用，防止被回收）
        self._win = None  # QQuickWindow
        self._presetStore = None  # 预设存储（由 Api 在弹窗前注入）
        if self._requested is not None:  # 无 Qt 环境时 _requested 为 None
            self._requested.connect(self._onRequested)

    # ==================== QML 回调（主线程执行） ====================

    @Slot(str)
    def submitRegions(self, jsonStr):
        """QML 调用：用户点击「完成」，提交区域 JSON。"""
        try:
            regions = json.loads(jsonStr)
            self._result = {"regions": regions}
            D.log(f"QML 提交区域：{len(regions)} 个")
        except Exception as e:
            self._result = {"error": f"区域数据解析失败：{e}"}
            D.log(f"QML 提交区域解析失败：{e}")
        self._closeView()

    @Slot()
    def cancel(self):
        """QML 调用：用户取消框选。"""
        self._result = None
        D.log("QML 取消框选")
        self._closeView()

    # ==================== 预设（QML 调用，主线程执行） ====================

    def _requirePresetStore(self):
        if self._presetStore is None:
            raise ValueError("预设存储未初始化，请重新打开框选窗口。")
        return self._presetStore

    @staticmethod
    def _presetResult(ok, message="", presetId="", presets=None):
        """统一的预设操作结果（JSON 字符串，QML 侧 JSON.parse）。"""
        return json.dumps(
            {
                "ok": bool(ok),
                "message": message,
                "id": presetId,
                "presets": presets if presets is not None else [],
            },
            ensure_ascii=False,
        )

    @Slot(result=str)
    def listPresets(self):
        """QML 调用：返回预设摘要列表 JSON。"""
        try:
            store = self._presetStore
            if store is None:
                return "[]"
            return json.dumps(store.briefs(), ensure_ascii=False)
        except Exception as e:
            D.log(f"读取预设列表失败：{e}")
            return "[]"

    @Slot(str, result=str)
    def getPreset(self, presetId):
        """QML 调用：取单个预设的完整内容（含区域坐标）。

        列表用的 briefs() 不含坐标，加载预设时必须走这里取完整数据。
        """
        try:
            store = self._requirePresetStore()
            preset = store.get(presetId)
            if not preset:
                return self._presetResult(False, "找不到该预设（可能已被删除），请刷新列表。")
            return json.dumps(
                {"ok": True, "message": "", "id": preset["id"], "preset": preset},
                ensure_ascii=False,
            )
        except Exception as e:
            return self._presetResult(False, str(e))

    @Slot(str, result=str)
    def savePreset(self, jsonStr):
        """QML 调用：把当前区域保存为预设（同名则覆盖）。
        入参 JSON：{"name": str, "remark": str, "regions": [区域dict, ...]}"""
        try:
            data = json.loads(jsonStr or "{}")
        except Exception as e:
            return self._presetResult(False, f"预设数据解析失败：{e}")
        try:
            store = self._requirePresetStore()
            preset, overwrote = store.saveAs(
                data.get("name", ""), data.get("remark", ""), data.get("regions", [])
            )
            msg = ("已覆盖同名预设「%s」" if overwrote else "已保存预设「%s」") % preset["name"]
            D.log(
                f"保存预设：{preset['name']}（{len(preset['regions'])} 个区域，覆盖={overwrote}）"
            )
            return self._presetResult(True, msg, preset["id"], store.briefs())
        except Exception as e:
            return self._presetResult(False, str(e))

    @Slot(str, str, result=str)
    def updatePreset(self, presetId, regionsJson):
        """QML 调用：用当前区域更新所选预设（名称、备注不变）。"""
        try:
            regions = json.loads(regionsJson or "[]")
        except Exception as e:
            return self._presetResult(False, f"区域数据解析失败：{e}")
        try:
            store = self._requirePresetStore()
            preset = store.updateRegions(presetId, regions)
            D.log(f"更新预设：{preset['name']}（{len(preset['regions'])} 个区域）")
            return self._presetResult(
                True, "已更新预设「%s」" % preset["name"], preset["id"], store.briefs()
            )
        except Exception as e:
            return self._presetResult(False, str(e))

    @Slot(str, result=str)
    def deletePreset(self, presetId):
        """QML 调用：删除所选预设。"""
        try:
            store = self._requirePresetStore()
            preset = store.get(presetId)
            name = preset["name"] if preset else ""
            if not store.remove(presetId):
                return self._presetResult(
                    False, "找不到该预设（可能已被删除）。", "", store.briefs()
                )
            D.log(f"删除预设：{name or presetId}")
            return self._presetResult(True, "已删除预设「%s」" % name, "", store.briefs())
        except Exception as e:
            return self._presetResult(False, str(e))

    # ==================== 窗口管理 ====================

    def _closeView(self):
        try:
            if self._win is not None:
                self._win.close()
                self._win.deleteLater()
                self._win = None
        except Exception as e:
            D.log(f"关闭窗口异常：{e}")
        try:
            if self._engine is not None:
                self._engine.deleteLater()
                self._engine = None
        except Exception as e:
            D.log(f"释放引擎异常：{e}")
        finally:
            self._event.set()  # 唤醒等待的工作线程

    def _onWindowClosing(self, event):
        """用户直接关闭窗口（点 X）：未提交则视为取消。"""
        D.log("窗口关闭事件")
        if self._result is None:
            self._result = None
            self._event.set()

    # ==================== 主线程：创建并显示窗口 ====================

    @Slot(str, str, str, int, int, str, str)
    def _onRequested(
        self, imagePath, regionsJson, hint, w, h, presetsJson="[]", activePresetId=""
    ):
        try:
            D.log("主线程：创建 QML 框选窗口")
            qmlPath = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "region_select.qml"
            )
            if not os.path.exists(qmlPath):
                raise RuntimeError(f"[Error] 找不到 QML 文件：{qmlPath}")
            engine = QQmlEngine()
            engine.rootContext().setContextProperty("pyBridge", self)
            comp = QQmlComponent(engine)
            comp.loadUrl(QUrl.fromLocalFile(qmlPath))
            if comp.isError():
                errors = [e.toString() for e in comp.errors()]
                raise RuntimeError(f"[Error] QML 加载失败：{'；'.join(errors)}")
            win = comp.create()
            if win is None:
                raise RuntimeError("[Error] QML 窗口创建失败")
            win.setProperty("imagePath", QUrl.fromLocalFile(imagePath).toString())
            win.setProperty("existingJson", regionsJson)
            win.setProperty("hintText", hint)
            win.setProperty("dispW", int(w))
            win.setProperty("dispH", int(h))
            win.setProperty("presetsJson", presetsJson or "[]")
            win.setProperty("activePresetId", activePresetId or "")
            self._engine = engine
            self._win = win
            win.closing.connect(self._onWindowClosing)
            win.show()
            win.requestActivate()
            D.log("QML 窗口已显示")
        except Exception as e:
            self._result = {"error": str(e)}
            print(f"[Error] 区域框选窗口异常：{e}")
            D.log(f"主线程：框选窗口异常：{e}")
            self._event.set()


_bridge = None


def _getBridge():
    """获取（并确保位于主线程的）调度桥。"""
    global _bridge
    if not _HAS_QT:
        _requireQt()
    if _bridge is None:
        _bridge = _RegionSelectBridge()
    app = QGuiApplication.instance()
    if app is not None:
        mainThread = app.thread()
        if _bridge.thread() is not mainThread:
            _bridge.moveToThread(mainThread)
    return _bridge


def selectRegionsInteractive(imagePath, existingRegions, hint="", w=0, h=0, presets=None):
    """弹出框选窗口（可在子线程调用）。

    presets: {"store": PresetStore, "list": [预设摘要...], "activeId": str}
             用于在窗口内列出/保存/更新/删除区域预设，可为 None。

    返回：
      {"regions": [区域dict, ...]}  - 用户完成框选
      {"error": "..."}              - 出错
      None                          - 用户取消
    """
    _requireQt()
    app = QGuiApplication.instance()
    if app is None:
        return {"error": "[Error] 未找到 QGuiApplication，无法弹出框选窗口。"}
    presets = presets or {}
    presetsJson = json.dumps(presets.get("list", []), ensure_ascii=False)
    activePresetId = str(presets.get("activeId", "") or "")
    bridge = _getBridge()
    # 预设存储先注入桥（QML 的预设操作槽随后在主线程使用它）
    bridge._presetStore = presets.get("store")
    with bridge._lock:  # 同一时刻只允许一个框选请求
        bridge._result = None
        bridge._event.clear()
        regionsJson = json.dumps(
            [r.toDict() if isinstance(r, Region) else r for r in existingRegions],
            ensure_ascii=False,
        )
        cur = QThread.currentThread()
        main = app.thread()
        D.log(f"selectRegionsInteractive: 当前线程是否主线程={cur is main}")
        if cur is main:
            # 已在主线程：直接执行
            bridge._onRequested(imagePath, regionsJson, hint, w, h, presetsJson, activePresetId)
        else:
            # 投递到主线程执行，然后阻塞等待用户完成
            D.log("已投递弹窗任务到主线程，等待用户框选...")
            bridge._requested.emit(
                imagePath, regionsJson, hint, int(w), int(h), presetsJson, activePresetId
            )
            bridge._event.wait()
            D.log("框选窗口已关闭，继续处理")
    return bridge._result
