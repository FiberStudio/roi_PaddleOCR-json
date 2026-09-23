# -*- coding: utf-8 -*-
# 区域识别插件 - 全局/局部配置项
# 全局配置：所有标签页一致（区域、导出、引擎性能等）
# 局部配置：不同标签页可不同（语言、方向纠正、边长限制等）

import os

from plugin_i18n import Translator

tr = Translator(__file__, "i18n.csv")


def _pluginDir():
    return os.path.dirname(os.path.abspath(__file__))


DEFAULT_REGION_FILE = os.path.join(_pluginDir(), "regions.json")
DEFAULT_EXPORT_DIR = os.path.join(_pluginDir(), "导出结果")


# 动态获取模型库列表（引擎文件组装后才有）。configs.txt 示例：
#   config_chinese.txt 简体中文
#   config_en.txt English
def _getLanguageList():
    optionsList = []
    bases = [
        _pluginDir(),
        os.path.join(_pluginDir(), "..", "win7_x64_PaddleOCR-json"),
        os.path.join(_pluginDir(), "..", "linux_x64_PaddleOCR-json"),
    ]
    for base in bases:
        configsPath = os.path.join(base, "models", "configs.txt")
        try:
            with open(configsPath, "r", encoding="utf-8") as f:
                for line in f.read().split("\n"):
                    parts = line.split(" ", 1)
                    if len(parts) == 2 and parts[0]:
                        optionsList.append([f"models/{parts[0]}", parts[1]])
        except (FileNotFoundError, IOError):
            continue
        if optionsList:
            return optionsList
    optionsList.append(["", tr("（未找到模型库，请先组装引擎文件）")])
    return optionsList


# 获取最佳线程数（借鉴官方 Paddle 插件）。无法获取时默认4。
def _getThreads():
    try:
        import psutil

        phyCore = psutil.cpu_count(logical=False)
        lgiCore = psutil.cpu_count(logical=True)
        if (
            not isinstance(phyCore, int)
            or not isinstance(lgiCore, int)
            or lgiCore < phyCore
        ):
            raise ValueError("核心数计算异常")
        if phyCore * 2 == lgiCore or phyCore == lgiCore:
            threadsCount = lgiCore
        else:
            big = lgiCore - phyCore
            threadsCount = big * 2
        if threadsCount > 16:
            threadsCount = 16
        return threadsCount
    except Exception:
        return 4


# 动态获取已保存的区域预设（presets.json）。下拉框 value 用预设 id，
# 显示文本包含名称、备注与区域数，便于快速辨认"这是什么单据"。
def _getPresetList():
    optionsList = [["", tr("（不使用预设，使用区域文件）")]]
    try:
        from . import roi_preset

        store = roi_preset.PresetStore(roi_preset.DEFAULT_PRESET_FILE)
        optionsList.extend(store.options())
    except Exception:
        pass
    return optionsList


_LanguageList = _getLanguageList()
_PresetList = _getPresetList()
_threads = _getThreads()

globalOptions = {
    "title": tr("区域识别（PaddleOCR-json）"),
    "type": "group",
    # ===== 区域 =====
    "enable_region": {
        "title": tr("启用区域识别"),
        "default": True,
        "toolTip": tr(
            "只提取框选区域内的文本。关闭后与普通 PaddleOCR 插件一致（整图识别）。"
        ),
    },
    "mode": {
        "title": tr("识别模式"),
        "optionsList": [
            ["crop", tr("裁剪识别（推荐）")],
            ["filter", tr("整图识别后过滤")],
        ],
        "toolTip": tr(
            "裁剪识别：只把每个区域裁剪下来识别，速度快。整图过滤：整图识别一遍，再只保留区域内的文字块。"
        ),
    },
    "region_file": {
        "title": tr("区域文件"),
        "type": "file",
        "default": DEFAULT_REGION_FILE,
        "selectExisting": True,
        "selectFolder": False,
        "dialogTitle": tr("选择区域文件"),
        "toolTip": tr(
            "保存框选区域的 JSON 文件（百分比坐标）。删除该文件，或勾选「重新框选区域」后，下次识别会重新弹出框选窗口。"
        ),
    },
    "force_reselect": {
        "title": tr("重新框选区域"),
        "default": False,
        "toolTip": tr(
            "勾选后，本次识别只弹出一次框选窗口，重新框选并覆盖已保存的区域（不会逐张弹窗）。引擎参数不变时不会再次弹窗；也可随时删除区域文件重新框选。"
        ),
    },
    "preset": {
        "title": tr("区域预设"),
        "optionsList": _PresetList,
        "toolTip": tr(
            "选择一个已保存的预设后，识别时直接使用该预设的区域，不再弹出框选窗口。新增或修改预设后，请重新打开本设置页（或重启 Umi-OCR）刷新列表。"
        ),
    },
    "filter_rule": {
        "title": tr("文块保留规则（整图过滤模式）"),
        "optionsList": [
            ["full", tr("完全在区域内")],
            ["center", tr("中心点在区域内")],
        ],
        "default": "full",
        "advanced": True,
        "toolTip": tr("整图过滤模式下，文字块满足何种条件才算“在区域内”。"),
    },
    "join_sep": {
        "title": tr("区域内文本连接符"),
        "default": "",
        "advanced": True,
        "toolTip": tr(
            "区域内识别到多个文字块时的连接符。默认无。例如识别地址等多段文本时，可填一个空格。"
        ),
    },
    # ===== 导出 =====
    "template": {
        "title": tr("导出模板"),
        "default": "",
        "toolTip": tr(
            "用 {区域名} 引用区域识别文本。留空则按「区域名：文本」分行输出。示例：发票号码是《{发票号码}》，税额是《{增值税额}》。"
        ),
    },
    "export_mode": {
        "title": tr("导出格式"),
        "optionsList": [
            ["none", tr("不导出")],
            ["txt", "TXT"],
            ["csv", "CSV"],
            ["both", tr("TXT + CSV")],
        ],
        "default": "csv",
        "toolTip": tr(
            "把每张图片的区域识别结果写入文件。CSV 为 UTF-8 BOM，Excel 可直接打开。"
        ),
    },
    "export_dir": {
        "title": tr("导出目录"),
        "type": "file",
        "default": DEFAULT_EXPORT_DIR,
        "selectExisting": True,
        "selectFolder": True,
        "dialogTitle": tr("选择导出目录"),
        "toolTip": tr("导出文件保存目录。默认在插件目录下的「导出结果」文件夹。"),
    },
    # ===== 引擎 =====
    "engine_path": {
        "title": tr("引擎路径"),
        "type": "file",
        "default": "",
        "selectExisting": True,
        "selectFolder": False,
        "dialogTitle": tr("选择 PaddleOCR-json.exe"),
        "toolTip": tr(
            "PaddleOCR-json.exe 的路径。留空时自动在本插件目录或官方 Paddle 插件目录中查找。"
        ),
    },
    "enable_mkldnn": {
        "title": tr("启用MKL-DNN加速"),
        "default": True,
        "toolTip": tr(
            "使用MKL-DNN数学库提高神经网络的计算速度。能大幅加快OCR识别速度，但也会增加内存占用。"
        ),
    },
    "cpu_threads": {
        "title": tr("线程数"),
        "default": _threads,
        "min": 1,
        "isInt": True,
    },
}

localOptions = {
    "title": tr("文字识别（区域识别）"),
    "type": "group",
    "language": {
        "title": tr("语言/模型库"),
        "optionsList": _LanguageList,
    },
    "cls": {
        "title": tr("纠正文本方向"),
        "default": False,
        "toolTip": tr("启用方向分类，识别倾斜或倒置的文本。可能降低识别速度。"),
    },
    "limit_side_len": {
        "title": tr("限制图像边长"),
        "optionsList": [
            [960, "960 " + tr("（默认）")],
            [2880, "2880"],
            [4320, "4320"],
            [999999, tr("无限制")],
        ],
        "toolTip": tr(
            "将边长大于该值的图片进行压缩，可以提高识别速度。可能降低识别精度。"
        ),
    },
}
