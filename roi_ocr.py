# -*- coding: utf-8 -*-
# 区域识别插件 - 引擎接口类
#
# 职责：
# - 管理 PaddleOCR-json 引擎子进程（启动/停止/参数映射，带启动超时保护）
# - 首次识别时弹出框选窗口（QML），将命名区域保存为 regions.json（百分比坐标）
# - 每张图片：对每个命名区域执行「裁剪识别」或「整图识别后过滤」，
#   得到 字段名->文本 映射；按模板渲染汇总文本；按配置导出 TXT/CSV
# - 将汇总文本以单个文块返回给 Umi-OCR（坐标已偏移回原图，排序/合并正常）
# - 全程写调试日志 roi_debug.log，便于真机排查

import base64
import io
import os
import threading
import time

from PIL import Image
from PIL import ImageOps

from . import roi_debug as D
from . import roi_export
from . import roi_preset
from . import roi_region
from . import region_window
from .PPOCR_api import PPOCR_pipe
from .roi_region import Region, RegionFilter

# 引擎可执行文件（入口）名称
_EXE_NAME = "PaddleOCR-json.exe" if os.name == "nt" else "run.sh"

# 引擎启动超时（秒）。超时返回明确错误，避免无限挂起。
_ENGINE_START_TIMEOUT = 120

# 框选窗口显示图片的最大尺寸（像素）
_SELECT_MAX_W = 1100
_SELECT_MAX_H = 720

# 用户取消框选后的冷却时间（秒）：期间不再弹窗，本次识别停止区域提取；
# 冷却结束后（例如重新开始识别），允许再次弹窗。
_CANCEL_COOLDOWN = 60

# 测试用：ROI_STUB_ENGINE=1 时使用桩引擎，不启动真实 exe
_STUB = os.environ.get("ROI_STUB_ENGINE", "") == "1"

# 引擎启动参数映射表：{引擎参数: 配置项key}
_EXE_CONFIGS = [
    ("enable_mkldnn", "enable_mkldnn"),  # mkl加速
    ("config_path", "language"),  # 模型库配置文件路径
    ("cls", "cls"),  # 方向分类
    ("limit_side_len", "limit_side_len"),  # 长边压缩
    ("cpu_threads", "cpu_threads"),  # 线程数
]


def _pluginDir():
    return os.path.dirname(os.path.abspath(__file__))


class Api:  # 公开接口
    def __init__(self, globalArgd):
        self.globalArgd = globalArgd or {}
        # 引擎路径（桩引擎测试模式不需要真实 exe）
        if _STUB:
            self.exePath = ""
        else:
            self.exePath = self._resolveExe(self.globalArgd.get("engine_path", ""))
        D.log(f"Api 初始化完成，引擎路径：{self.exePath}")
        # 引擎对象
        self.api = None
        self.lock = threading.Lock()
        # 区域相关配置
        self.enableRegion = bool(self.globalArgd.get("enable_region", True))
        self.mode = self.globalArgd.get("mode", "crop")
        self.filterRule = self.globalArgd.get("filter_rule", "full")
        self.forceReselect = bool(self.globalArgd.get("force_reselect", False))
        # 重新框选区域：本次运行（引擎参数不变期间）只弹窗一次
        self._reselectDone = False
        # 用户取消框选：冷却期内不再弹窗，本次识别停止区域提取
        self._selectionCancelled = False
        self._cancelTime = 0.0
        regionFile = self.globalArgd.get("region_file", "") or os.path.join(
            _pluginDir(), "regions.json"
        )
        self.regionStore = roi_region.RegionStore(regionFile)
        # 区域预设：把一组命名区域存成具名预设（presets.json），下次可直接加载
        presetFile = self.globalArgd.get("preset_file", "") or roi_preset.DEFAULT_PRESET_FILE
        self.presetStore = roi_preset.PresetStore(presetFile)
        self.presetId = str(self.globalArgd.get("preset", "") or "")
        # 勾选「重新框选区域」并完成框选后：本次运行改用新框选的区域，忽略预设
        self._presetSkipped = False
        # 导出相关配置
        self.template = str(self.globalArgd.get("template", "") or "")
        self.exportMode = self.globalArgd.get("export_mode", "csv")
        exportDir = self.globalArgd.get("export_dir", "") or os.path.join(
            _pluginDir(), "导出结果"
        )
        self.exporter = roi_export.Exporter(exportDir)
        self.joinSep = str(self.globalArgd.get("join_sep", "") or "")
        # 引擎参数
        self.exeConfigs = {}
        self._updateExeConfigs(self.exeConfigs, self.globalArgd)

    # ========================= 【引擎路径】 =========================

    @staticmethod
    def _resolveExe(enginePath):
        """解析引擎可执行文件路径。手动指定优先，否则自动搜索。"""
        if enginePath:
            p = os.path.abspath(enginePath)
            if os.path.exists(p):
                return p
            raise ValueError(f"[Error] 引擎路径不存在：{enginePath}")
        candidates = [
            os.path.join(_pluginDir(), _EXE_NAME),
            os.path.join(_pluginDir(), "..", "win7_x64_PaddleOCR-json", _EXE_NAME),
            os.path.join(_pluginDir(), "..", "linux_x64_PaddleOCR-json", _EXE_NAME),
        ]
        for c in candidates:
            c = os.path.abspath(c)
            if os.path.exists(c):
                return c
        raise ValueError(
            "[Error] 未找到 PaddleOCR-json 引擎文件。\n"
            "请把引擎文件（PaddleOCR-json.exe 及 models 文件夹等）放入本插件目录，\n"
            "或在插件全局设置中手动指定「引擎路径」。\n"
            "如何获取引擎文件：见插件 README.md 或运行 assemble.bat。"
        )

    # ========================= 【引擎生命周期】 =========================

    def _updateExeConfigs(self, target, data):
        for c in _EXE_CONFIGS:
            if c[1] in data:
                target[c[0]] = data[c[1]]

    # 启动引擎。返回： "" 成功，"[Error] xxx" 失败
    def start(self, argd):
        with self.lock:
            tempConfigs = self.exeConfigs.copy()
            self._updateExeConfigs(tempConfigs, argd or {})
            # 若引擎已启动，且参数一致，则无需重启
            if self.api is not None and set(tempConfigs.items()) == set(
                self.exeConfigs.items()
            ):
                return ""
            self.exeConfigs = tempConfigs
            # 引擎参数变化（重新启动）时，重置"只弹一次"与"取消"标志，
            # 允许再次弹窗重新框选区域
            self._reselectDone = False
            self._selectionCancelled = False
            self._presetSkipped = False
            try:
                self.stop()
                D.log(f"启动引擎中... 参数：{tempConfigs}")
                self.api = self._createEngine(tempConfigs)
                D.log("引擎启动完成")
            except Exception as e:
                self.api = None
                D.log(f"引擎启动失败：{e}")
                return f"[Error] OCR init fail. Argd: {tempConfigs}\n{e}"
            return ""

    def _createEngine(self, configs):
        """创建引擎对象。带超时保护：引擎长时间无法初始化时返回明确错误，
        而不是让任务无限挂起。"""
        if _STUB:
            return _StubEngine()
        result = {"api": None, "error": None}

        def worker():
            try:
                result["api"] = PPOCR_pipe(self.exePath, argument=configs)
            except Exception as e:
                result["error"] = e

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        t.join(_ENGINE_START_TIMEOUT)
        if t.is_alive():
            raise TimeoutError(
                f"引擎启动超时（{_ENGINE_START_TIMEOUT}秒）。\n"
                "请检查插件目录内的引擎文件是否完整（PaddleOCR-json.exe、models、*.dll），\n"
                "可重新运行 assemble.bat；也可双击 PaddleOCR-json.exe 手动测试能否正常启动。"
            )
        if result["error"] is not None:
            raise result["error"]
        return result["api"]

    def stop(self):  # 停止引擎
        if self.api is None:
            return
        try:
            self.api.exit()
        except Exception as e:
            print(f"[Error] 停止引擎异常：{e}")
        self.api = None

    # ========================= 【OCR 入口】 =========================

    def runPath(self, imgPath: str):  # 路径识图
        return self._run(imgPath=imgPath)

    def runBytes(self, imageBytes):  # 字节流
        return self._run(imageBytes=imageBytes)

    def runBase64(self, imageBase64):  # base64字符串
        return self._run(imageBase64=imageBase64)

    # ========================= 【核心流程】 =========================

    def _run(self, imgPath=None, imageBytes=None, imageBase64=None):
        D.log(f"_run 进入：path={imgPath and os.path.basename(imgPath) or '(bytes/base64)'}")
        if self.api is None:
            return {"code": 102, "data": "[Error] 引擎未启动。"}
        try:
            pilImg = self._loadImage(imgPath, imageBytes, imageBase64)
        except Exception as e:
            D.log(f"图片加载失败：{e}")
            return {"code": 102, "data": f"[Error] 图片加载失败：{e}"}
        w, h = pilImg.size
        D.log(f"图片尺寸：{w}x{h}，区域识别={'开' if self.enableRegion else '关'}")

        # 未启用区域识别：退化为普通整图识别
        if not self.enableRegion:
            return self._ocrFullImage(pilImg, imgPath)

        # 获取区域（可能需要弹出框选窗口，仅首次/强制时）
        regions = self._getRegions(pilImg)
        if regions is None:  # 用户取消/已停止
            return {
                "code": 102,
                "data": "[Error] 已取消框选区域，本图片未提取。\n本次识别已停止（后续图片不再弹窗）。如需提取区域文本，请重新开始识别。",
            }
        if not regions:  # 无有效区域
            D.log("无有效区域，返回空结果")
            return {"code": 101, "data": ""}
        D.log(f"使用 {len(regions)} 个区域：{[r.name for r in regions]}")

        # 整图过滤模式：先整图识别一次，供所有区域复用
        allBlocks = None
        if self.mode == "filter":
            fullRes = self._ocrFullImage(pilImg, imgPath)
            allBlocks = self._extractBlocks(fullRes)

        # 逐区域识别
        fieldMap = {}
        for r in regions:
            x1, y1, x2, y2 = r.toPixel(w, h)
            if self.mode == "crop":
                text = self._ocrCrop(pilImg, r, x1, y1, x2, y2)
            else:
                text = self._filterBlocks(allBlocks, x1, y1, x2, y2)
            fieldMap[r.name] = text

        # 汇总文本：有模板则按模板渲染，否则按「字段名：值」分行
        if self.template:
            summary = roi_export.renderTemplate(self.template, fieldMap)
        else:
            summary = "\n".join(f"{k}：{v}" for k, v in fieldMap.items())

        # 导出
        try:
            self._export(imgPath, fieldMap, summary)
        except Exception as e:
            print(f"[Error] 导出失败：{e}")

        # 汇总块的包围盒：所有区域的并集（用于 Umi 界面展示与排序）
        box = self._summaryBox(regions, w, h)

        return {
            "code": 100,
            "data": [
                {"text": summary, "box": box, "score": 1},
            ],
        }

    # ========================= 【区域】 =========================

    def _getRegions(self, pilImg):
        """返回 list[Region]；None 表示用户取消/停止；[] 表示出错/无区域。"""
        # 用户取消框选后的冷却期内：不再弹窗，本次识别停止区域提取，
        # 每张图片都返回 None（_run 会给出明确的"已取消"提示）
        if self._selectionCancelled:
            if time.time() - self._cancelTime > _CANCEL_COOLDOWN:
                self._selectionCancelled = False  # 冷却结束，恢复正常
                D.log("取消冷却结束，允许再次框选")
            else:
                D.log("用户已取消框选，冷却期内不弹窗、不提取")
                return None
        if self.forceReselect and not self._reselectDone:
            # 勾选"重新框选区域"：本次运行只弹窗一次
            self._reselectDone = True
            # 本次运行改用新框选的区域，不再套用已选预设
            self._presetSkipped = True
            D.log("重新框选区域：本次运行仅弹窗一次")
            return self._askRegions(pilImg)
        # 已选预设：直接使用预设区域，不弹窗、不重复框选
        presetRegions = self._getPresetRegions()
        if presetRegions:
            return presetRegions
        if not self.regionStore.exists():
            D.log("区域文件不存在，准备弹窗")
            return self._askRegions(pilImg)
        regions = self.regionStore.load()
        D.log(f"已存在区域文件，直接复用 {len(regions)} 个区域：{[r.name for r in regions]}")
        return regions

    def _getPresetRegions(self):
        """返回全局设置所选预设的区域；未选预设/预设不存在/无有效区域时返回 None。"""
        if not self.presetId or self._presetSkipped:
            return None
        preset = self.presetStore.get(self.presetId)
        if not preset:
            print(f"[Warning] 未找到区域预设（{self.presetId}），改用区域文件。")
            D.log(f"未找到区域预设：{self.presetId}，回退到区域文件")
            return None
        regions = []
        for d in preset.get("regions", []):
            try:
                r = Region.fromDict(d)
            except Exception:
                continue
            if r.isValid():
                regions.append(r)
        if not regions:
            D.log(f"预设「{preset.get('name')}」没有有效区域，回退到区域文件")
            return None
        D.log(
            f"使用预设「{preset.get('name')}」：{len(regions)} 个区域 {[r.name for r in regions]}"
        )
        return regions

    def _askRegions(self, pilImg):
        """弹出框选窗口（只弹这一次，结果保存到区域文件）。"""
        tmpPath = os.path.join(_pluginDir(), "_select_tmp.png")
        try:
            # 生成显示图：超过最大尺寸则等比缩小（区域按百分比保存，不受影响）
            dw, dh = pilImg.size
            scale = min(1.0, _SELECT_MAX_W / dw, _SELECT_MAX_H / dh)
            if scale < 1.0:
                disp = pilImg.resize(
                    (max(1, round(dw * scale)), max(1, round(dh * scale))),
                    Image.Resampling.LANCZOS,
                )
            else:
                disp = pilImg
            disp.save(tmpPath, format="PNG")
            dispW, dispH = disp.size
            # 重新框选时从空白开始；否则叠加已有区域作参考
            if self.forceReselect:
                existing = []
            else:
                existing = self.regionStore.load()
            hint = (
                "拖拽框选一个区域，松开后输入名称（默认自动编号，可直接输入覆盖）。\n"
                "点「保存为预设」可把这一组区域连同名称、备注存下来；下次点「预设」→「加载所选」即可直接复用。"
            )
            presetsArg = {
                "store": self.presetStore,
                "list": self.presetStore.briefs(),
                "activeId": self.presetId,
            }
            D.log("准备弹出框选窗口...")
            res = None
            try:
                res = region_window.selectRegionsInteractive(
                    tmpPath, existing, hint, dispW, dispH, presets=presetsArg
                )
            except Exception as e:
                print(f"[Error] 框选窗口调用异常：{e}")
                D.log(f"框选窗口调用异常：{e}")
                return []
            if res is None:
                D.log("框选窗口返回：用户取消")
            elif "error" in res:
                D.log(f"框选窗口返回错误：{res['error']}")
            else:
                D.log(f"框选窗口返回：{len(res.get('regions', []))} 个区域")
        finally:
            try:
                os.remove(tmpPath)
            except Exception:
                pass
        if res is None:
            # 用户取消框选：进入冷却期，本次识别不再弹窗
            self._selectionCancelled = True
            self._cancelTime = time.time()
            D.log("用户取消框选，本次识别停止区域提取")
            return None  # 用户取消
        if "error" in res:
            print(f"[Error] 框选窗口异常：{res['error']}")
            return []
        regions = [Region.fromDict(d) for d in res.get("regions", [])]
        # 保存区域文件（失败则仅提示，本次仍使用该区域）
        try:
            self.regionStore.save(regions)
            print(f"[Info] 已保存 {len(regions)} 个区域：{self.regionStore.path}")
            D.log(f"区域已保存到 {self.regionStore.path}")
        except Exception as e:
            print(f"[Error] 保存区域文件失败：{e}")
        return regions

    # ========================= 【识别细节】 =========================

    @staticmethod
    def _loadImage(imgPath, imageBytes, imageBase64):
        if imgPath:
            img = Image.open(imgPath)
        elif imageBytes:
            img = Image.open(io.BytesIO(imageBytes))
        elif imageBase64:
            img = Image.open(io.BytesIO(base64.b64decode(imageBase64)))
        else:
            raise ValueError("无图片输入")
        return ImageOps.exif_transpose(img)  # 修正拍摄方向

    def _ocrCrop(self, pilImg, region, x1, y1, x2, y2):
        """裁剪识别：只把区域裁剪下来送引擎，文块坐标偏移回原图。"""
        if x2 <= x1 or y2 <= y1:
            return ""
        crop = pilImg.crop((x1, y1, x2, y2))
        buf = io.BytesIO()
        crop.save(buf, format="PNG")
        res = self.api.runBytes(buf.getvalue())
        blocks = self._extractBlocks(res)
        for b in blocks:
            box = b.get("box", [])
            b["box"] = [[p[0] + x1, p[1] + y1] for p in box]
        return self._joinBlocks(blocks)

    def _filterBlocks(self, blocks, x1, y1, x2, y2):
        """整图过滤：保留区域内的文块。"""
        keep = RegionFilter.keepBlocks(blocks, (x1, y1, x2, y2), self.filterRule)
        return self._joinBlocks(keep)

    def _joinBlocks(self, blocks):
        """将文块按阅读顺序（先上后下、先左后右）拼接。"""
        if not blocks:
            return ""

        def key(b):
            box = b.get("box", [])
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            return (min(ys), min(xs))

        ordered = sorted(blocks, key=key)
        return self.joinSep.join(b.get("text", "") for b in ordered)

    def _ocrFullImage(self, pilImg, imgPath=None):
        """整图识别。有路径时直接传路径，否则编码为字节流。"""
        if imgPath:
            return self.api.run(imgPath)
        buf = io.BytesIO()
        pilImg.save(buf, format="PNG")
        return self.api.runBytes(buf.getvalue())

    @staticmethod
    def _extractBlocks(res):
        if (
            isinstance(res, dict)
            and res.get("code") == 100
            and isinstance(res.get("data"), list)
        ):
            return res["data"]
        return []

    def _summaryBox(self, regions, w, h):
        """所有区域的像素并集包围盒（4点）。"""
        xs = []
        ys = []
        for r in regions:
            x1, y1, x2, y2 = r.toPixel(w, h)
            xs += [x1, x2]
            ys += [y1, y2]
        if not xs:
            return [[0, 0], [w, 0], [w, h], [0, h]]
        x1, x2 = min(xs), max(xs)
        y1, y2 = min(ys), max(ys)
        return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]

    # ========================= 【导出】 =========================

    def _export(self, imgPath, fieldMap, summary):
        """按配置导出 TXT / CSV。"""
        if self.exportMode not in ("txt", "csv", "both"):
            return
        fileName = (
            os.path.basename(imgPath)
            if imgPath
            else f"image_{int(time.time() * 1000)}.png"
        )
        if self.exportMode in ("txt", "both"):
            self.exporter.exportTxt(summary)
        if self.exportMode in ("csv", "both"):
            header = ["图片"] + list(fieldMap.keys())
            row = [fileName] + list(fieldMap.values())
            self.exporter.exportCsv(header, row)


class _StubEngine:
    """桩引擎（测试用）：按输入图片尺寸返回固定文字块。"""

    def __init__(self):
        self.calls = []

    def run(self, imgPath):
        with open(imgPath, "rb") as f:
            return self.runBytes(f.read())

    def runBytes(self, imageBytes):
        img = Image.open(io.BytesIO(imageBytes))
        w, h = img.size
        self.calls.append((w, h))
        table = {
            # 整图 800x600（原图坐标）
            (800, 600): [
                {
                    "text": "NO12345678",
                    "box": [[100, 50], [300, 50], [300, 90], [100, 90]],
                    "score": 0.99,
                },
                {
                    "text": "100.00",
                    "box": [[100, 200], [250, 200], [250, 240], [100, 240]],
                    "score": 0.98,
                },
                {
                    "text": "NOISE",
                    "box": [[500, 400], [700, 400], [700, 450], [500, 450]],
                    "score": 0.5,
                },
            ],
            # 发票号码区域裁剪图 200x40
            (200, 40): [
                {
                    "text": "NO12345678",
                    "box": [[0, 0], [200, 0], [200, 40], [0, 40]],
                    "score": 0.99,
                },
            ],
            # 增值税额区域裁剪图 150x40
            (150, 40): [
                {
                    "text": "100.00",
                    "box": [[0, 0], [150, 0], [150, 40], [0, 40]],
                    "score": 0.98,
                },
            ],
            # 噪声区域裁剪图 200x50（不应被识别到）
            (200, 50): [
                {
                    "text": "NOISE",
                    "box": [[0, 0], [200, 0], [200, 50], [0, 50]],
                    "score": 0.5,
                },
            ],
        }
        if (w, h) in table:
            return {"code": 100, "data": table[(w, h)]}
        return {"code": 101, "data": ""}

    def exit(self):
        pass
