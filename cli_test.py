# -*- coding: utf-8 -*-
"""
区域识别插件 - 独立命令行测试工具

在不打开 Umi-OCR 界面的情况下，直接调用本插件的核心逻辑进行测试：
指定（或框选）区域 -> 识别 -> 模板渲染 -> TXT/CSV 导出。

用法（在插件目录内运行，需 Python 3.8+ 且装有 Pillow；可用 Umi 自带的
python.exe：UmiOCR-data/runtime/python.exe）：

  # 真实引擎：识别指定图片，首次会弹出框选窗口
  python cli_test.py --images 图1.png 图2.png

  # 桩引擎（无需真实引擎文件，用于快速验证流程）
  python cli_test.py --stub --images 测试图.png

  # 不弹窗，直接用命令行指定区域（百分比坐标），可多次 --region
  python cli_test.py --region 12.5,8.3,37.5,15,发票号码 ^
                     --region 12.5,33.3,31.25,40,增值税额 ^
                     --images 图1.png

  # 指定模板与导出
  python cli_test.py --images 图1.png ^
                     --template "发票号码是《{发票号码}》，税额是《{增值税额}》" ^
                     --export-mode both

  # 使用已保存的区域预设（名称或 id）：不弹框选，直接用预设区域
  python cli_test.py --images 图1.png --preset 增值税发票

参数说明：
  --images      图片路径列表，支持文件夹（自动扫描常见图片格式）与通配符
  --region      x1,y1,x2,y2,名称 （百分比 0-100），可多次；优先于框选窗口
  --region-file 区域文件路径（默认 插件目录/regions.json）
  --template    导出模板
  --export-mode none|txt|csv|both（默认 csv）
  --export-dir  导出目录（默认 插件目录/导出结果）
  --mode        crop|filter（默认 crop）
  --exe         PaddleOCR-json.exe 路径（默认自动查找）
  --stub        使用桩引擎，不启动真实引擎
"""

import argparse
import importlib
import importlib.util
import os
import sys
import types

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
_PKG_NAME = "roi_ocr_plugin_pkg"

_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp")


def _install_fake_plugin_i18n():
    """Umi 之外的独立环境没有 plugin_i18n 模块，注入一个空翻译实现。"""
    if "plugin_i18n" in sys.modules:
        return
    fake = types.ModuleType("plugin_i18n")

    class _Translator:
        def __init__(self, *args, **kwargs):
            pass

        def __call__(self, original):
            return original

    fake.Translator = _Translator
    sys.modules["plugin_i18n"] = fake


def load_plugin():
    """以包形式加载本插件（插件目录名含连字符，不能直接 import）。"""
    _install_fake_plugin_i18n()
    spec = importlib.util.spec_from_file_location(
        _PKG_NAME,
        os.path.join(PLUGIN_DIR, "__init__.py"),
        submodule_search_locations=[PLUGIN_DIR],
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_PKG_NAME] = mod
    spec.loader.exec_module(mod)
    return mod


def expand_images(items):
    """展开图片路径：文件、文件夹、通配符 -> 文件列表。"""
    out = []
    for item in items:
        if os.path.isdir(item):
            for name in sorted(os.listdir(item)):
                p = os.path.join(item, name)
                if os.path.isfile(p) and name.lower().endswith(_IMAGE_EXTS):
                    out.append(p)
        elif os.path.isfile(item):
            out.append(item)
        elif any(ch in item for ch in "*?"):
            import glob

            out.extend(sorted(glob.glob(item)))
        else:
            print(f"[Warning] 忽略不存在的路径：{item}")
    return out


def main():
    ap = argparse.ArgumentParser(
        description="区域识别插件 - 独立命令行测试工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--images", nargs="+", default=[], help="图片路径/文件夹/通配符")
    ap.add_argument("--region", action="append", default=[], metavar="x1,y1,x2,y2,名称",
                    help="直接指定区域（百分比），可多次")
    ap.add_argument("--region-file", default="", help="区域文件路径")
    ap.add_argument("--preset", default="", help="区域预设（名称或 id），指定后直接用预设区域，不弹框选")
    ap.add_argument("--preset-file", default="", help="预设文件路径（默认 插件目录/presets.json）")
    ap.add_argument("--template", default="", help="导出模板")
    ap.add_argument("--export-mode", choices=["none", "txt", "csv", "both"], default="csv")
    ap.add_argument("--export-dir", default="", help="导出目录")
    ap.add_argument("--mode", choices=["crop", "filter"], default="crop")
    ap.add_argument("--exe", default="", help="PaddleOCR-json.exe 路径")
    ap.add_argument("--language", default="", help="语言/模型库（如 models/config_chinese.txt）")
    ap.add_argument("--stub", action="store_true", help="使用桩引擎（无需真实引擎文件）")
    ap.add_argument("--no-export", action="store_true", help="关闭导出（同 --export-mode none）")
    args = ap.parse_args()

    if args.no_export:
        args.export_mode = "none"
    if not args.images:
        ap.print_help()
        sys.exit(0)

    if args.stub:
        os.environ["ROI_STUB_ENGINE"] = "1"

    load_plugin()
    roi_ocr = importlib.import_module(f"{_PKG_NAME}.roi_ocr")
    roi_region = importlib.import_module(f"{_PKG_NAME}.roi_region")
    roi_preset = importlib.import_module(f"{_PKG_NAME}.roi_preset")

    # 区域预设：按名称或 id 解析（等价于全局设置里选择预设）
    presetFile = args.preset_file or roi_preset.DEFAULT_PRESET_FILE
    presetId = ""
    if args.preset:
        store = roi_preset.PresetStore(presetFile)
        preset = store.findByName(args.preset) or store.get(args.preset)
        if preset is None:
            print(f"[Error] 找不到区域预设：{args.preset}")
            briefs = store.briefs()
            if briefs:
                print("[Info] 现有预设：")
                for b in briefs:
                    remark = f"（{b['remark']}）" if b["remark"] else ""
                    print(f"   - {b['name']}{remark} {b['regionCount']} 个区域")
            sys.exit(1)
        presetId = preset["id"]

    # 组装全局配置（等价于 Umi 全局设置）
    globalArgd = {
        "enable_region": True,
        "mode": args.mode,
        "region_file": args.region_file or os.path.join(PLUGIN_DIR, "regions.json"),
        "force_reselect": False,
        "template": args.template,
        "export_mode": args.export_mode,
        "export_dir": args.export_dir or os.path.join(PLUGIN_DIR, "导出结果"),
        "engine_path": args.exe,
        "enable_mkldnn": True,
        "cpu_threads": 4,
        "join_sep": "",
        "filter_rule": "full",
        "preset": presetId,
        "preset_file": presetFile,
    }

    print(f"[Info] 插件目录：{PLUGIN_DIR}")
    print(f"[Info] 识别模式：{args.mode}，导出：{args.export_mode}")
    if presetId:
        print(f"[Info] 使用区域预设：{args.preset}（{presetFile}）")
    if args.stub:
        print("[Info] 使用桩引擎（测试模式）")

    try:
        api = roi_ocr.Api(globalArgd)
    except Exception as e:
        print(f"[Error] 初始化失败：{e}")
        sys.exit(1)

    startRes = api.start({"language": args.language} if args.language else {})
    if startRes.startswith("[Error]"):
        print(f"[Error] 引擎启动失败：{startRes}")
        sys.exit(1)
    print("[Info] 引擎启动成功")

    # 命令行指定区域：直接写入区域文件（后续 Umi 也会复用）
    if args.region:
        regions = []
        for item in args.region:
            parts = [p.strip() for p in item.split(",")]
            if len(parts) != 5:
                print(f"[Error] --region 格式应为 x1,y1,x2,y2,名称：{item}")
                sys.exit(1)
            try:
                x1, y1, x2, y2 = (float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3]))
            except ValueError:
                print(f"[Error] 区域坐标必须为数字：{item}")
                sys.exit(1)
            regions.append(roi_region.Region(parts[4], x1, y1, x2, y2))
        try:
            api.regionStore.save(regions)
            print(f"[Info] 已保存 {len(regions)} 个区域：{api.regionStore.path}")
        except Exception as e:
            print(f"[Error] 保存区域失败：{e}")
            sys.exit(1)

    images = expand_images(args.images)
    if not images:
        print("[Error] 没有找到任何图片。")
        sys.exit(1)
    print(f"[Info] 共 {len(images)} 张图片，开始识别...")

    for p in images:
        res = api.runPath(p)
        print("=" * 56)
        print(f"图片：{p}")
        code = res.get("code")
        if code == 100:
            for b in res.get("data", []):
                print(f"  文本：{b['text']}")
        elif code == 101:
            print("  结果：未识别到文字（code 101）")
        else:
            print(f"  失败（code {code}）：{res.get('data')}")

    api.stop()
    print("=" * 56)
    if args.export_mode in ("txt", "both"):
        print(f"[Info] TXT 导出：{os.path.join(globalArgd['export_dir'], '字段提取.txt')}")
    if args.export_mode in ("csv", "both"):
        print(f"[Info] CSV 导出：{os.path.join(globalArgd['export_dir'], '字段提取.csv')}")
    print("[OK] 完成。")


if __name__ == "__main__":
    main()
