# -*- coding: utf-8 -*-
"""
区域识别插件 - 安装诊断脚本

作用：检查插件目录结构、引擎文件，并模拟 Umi-OCR 的加载方式导入插件，
      输出具体失败原因。运行后把完整输出发给开发者即可定位问题。

用法（用 Umi 自带的 Python 运行，把 <Umi目录> 换成你的 Umi-OCR 安装目录）：
    UmiOCR-data\runtime\python.exe  check_install.py  <Umi目录>

如果不知道安装目录，也可以把本脚本放到 Umi 的 UmiOCR-data 目录里运行：
    runtime\python.exe  check_install.py
"""

import importlib
import os
import sys
import traceback

# ============================ 定位 plugins 目录 ============================

def find_plugins_dir():
    candidates = []
    # 1) 命令行参数
    if len(sys.argv) > 1:
        candidates.append(os.path.join(sys.argv[1], "UmiOCR-data", "plugins"))
    # 2) 从 python.exe 位置推断（.../UmiOCR-data/runtime/python.exe）
    exeDir = os.path.dirname(os.path.abspath(sys.executable))
    if os.path.basename(exeDir) == "runtime":
        candidates.append(os.path.join(os.path.dirname(exeDir), "plugins"))
    # 3) 当前目录向上找 UmiOCR-data/plugins
    cur = os.path.abspath(os.getcwd())
    for _ in range(6):
        candidates.append(os.path.join(cur, "UmiOCR-data", "plugins"))
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    seen = set()
    for c in candidates:
        c = os.path.abspath(c)
        if c in seen:
            continue
        seen.add(c)
        if os.path.isdir(c):
            return c
    print("[FAIL] 找不到插件目录 UmiOCR-data/plugins")
    print("       请用命令行参数指定 Umi 安装目录，如：")
    print("       python check_install.py  D:\\Umi-OCR")
    return None

# ============================ 主流程 ============================

def main():
    print("=" * 50)
    print(" 区域识别插件 安装诊断")
    print(" Python:", sys.version.split()[0], sys.executable)
    print("=" * 50)

    pluginsDir = find_plugins_dir()
    if not pluginsDir:
        return 1
    print("[OK] 插件目录：", pluginsDir)
    umiDataDir = os.path.dirname(pluginsDir)  # UmiOCR-data

    # ---- 1. 插件目录内容 ----
    print("\n---- 1. 插件目录内容 ----")
    try:
        names = sorted(os.listdir(pluginsDir))
    except Exception as e:
        print(f"[FAIL] 无法读取插件目录：{e}")
        return 1
    if not names:
        print("[FAIL] 插件目录为空！请把 roi_PaddleOCR-json 文件夹放进来。")
        return 1
    for n in names:
        full = os.path.join(pluginsDir, n)
        if os.path.isdir(full):
            inner = os.path.join(full, "__init__.py")
            mark = "[Pkg]" if os.path.exists(inner) else "[dir]"
            print(f"  {mark} {n}")
        else:
            print(f"  [file] {n}")

    # ---- 2. 检查本插件 ----
    print("\n---- 2. 检查 roi_PaddleOCR-json ----")
    pluginDir = os.path.join(pluginsDir, "roi_PaddleOCR-json")
    if not os.path.isdir(pluginDir):
        print("[FAIL] 插件目录 plugins\\roi_PaddleOCR-json 不存在！")
        print("       请把整个 roi_PaddleOCR-json 文件夹复制到：", pluginsDir)
        return 1
    # 嵌套检测
    nested = os.path.join(pluginDir, "roi_PaddleOCR-json")
    if os.path.isdir(nested):
        print("[FAIL] 发现嵌套目录：plugins\\roi_PaddleOCR-json\\roi_PaddleOCR-json")
        print("       说明复制时多套了一层。正确结构应为：")
        print("       plugins\\roi_PaddleOCR-json\\__init__.py")
        return 1
    initFile = os.path.join(pluginDir, "__init__.py")
    if not os.path.exists(initFile):
        print(f"[FAIL] 缺少插件入口文件：{initFile}")
        return 1
    print("[OK] 插件入口存在：", initFile)
    # 检查入口文件是否被官方插件文件覆盖（旧版 assemble.bat 的 bug）
    try:
        with open(initFile, "r", encoding="utf-8") as f:
            initContent = f.read()
        if "roi_ocr" not in initContent:
            print("[FAIL] 插件的 __init__.py 内容异常，疑似被官方 Paddle 插件的文件覆盖！")
            print("       这是旧版 assemble.bat 的 bug 导致的（它把官方插件所有文件复制了过来）。")
            print("       请按以下步骤修复：")
            print("       1. 删除 plugins\\roi_PaddleOCR-json 整个文件夹；")
            print("       2. 重新复制一份干净的 roi_PaddleOCR-json 插件文件夹；")
            print("       3. 重新运行修复后的 assemble.bat（只复制引擎文件，不再覆盖控制文件）。")
            return 1
        print("[OK] 插件入口内容正常（未被覆盖）")
    except Exception as e:
        print(f"[WARN] 无法读取 __init__.py 内容：{e}")
    # 关键文件完整性
    for need in ("roi_ocr.py", "roi_config.py", "roi_region.py", "roi_preset.py",
                 "region_window.py", "region_select.qml", "i18n.csv"):
        if not os.path.exists(os.path.join(pluginDir, need)):
            print(f"[FAIL] 缺少插件文件：{need}（插件文件夹不完整，请重新复制干净的插件目录）")
            return 1
    print("[OK] 插件文件完整")
    # 引擎文件
    exeFile = os.path.join(pluginDir, "PaddleOCR-json.exe")
    if os.path.exists(exeFile):
        print("[OK] 引擎文件存在：PaddleOCR-json.exe")
    else:
        print("[WARN] 未找到 PaddleOCR-json.exe（不影响插件加载，但识别时会报错）")
        print("       请运行插件目录内的 assemble.bat，或手动复制引擎文件。")
    modelsDir = os.path.join(pluginDir, "models")
    print("[", "OK" if os.path.isdir(modelsDir) else "WARN",
          "] models 目录：", "存在" if os.path.isdir(modelsDir) else "不存在")

    # ---- 3. 模拟 Umi 加载插件 ----
    print("\n---- 3. 模拟 Umi 加载插件 ----")
    sys.path.insert(0, pluginsDir)
    # 依赖环境：site-packages（PIL、psutil、PySide2 等都在这里）
    sitePkgs = os.path.join(umiDataDir, "site-packages")
    if os.path.isdir(sitePkgs):
        sys.path.insert(0, sitePkgs)
        print("[OK] site-packages 已加入搜索路径：", sitePkgs)
    else:
        print("[WARN] 未找到 site-packages 目录（Umi 安装可能不完整）：", sitePkgs)
    # plugin_i18n 位于 UmiOCR-data/py_src/imports
    importsDir = os.path.join(umiDataDir, "py_src", "imports")
    if os.path.isdir(importsDir):
        sys.path.insert(0, importsDir)
    try:
        import plugin_i18n
        print("[OK] plugin_i18n 模块可用")
    except Exception as e:
        print(f"[FAIL] 无法导入 plugin_i18n：{e}")
        print("       你的 Umi-OCR 版本可能过旧或不完整，请升级到最新版：")
        print("       https://github.com/hiroi-sora/Umi-OCR/releases")
    try:
        mod = importlib.import_module("roi_PaddleOCR-json")
        info = mod.PluginInfo
        print("[OK] 插件加载成功！")
        print("  group =", info.get("group"))
        print("  global_options =", list((info.get("global_options") or {}).keys()))
        print("  local_options =", list((info.get("local_options") or {}).keys()))
        print("  api_class =", info.get("api_class"))
        print("\n[OK] 插件会被 Umi 识别。请重启 Umi-OCR，在「全局设置」拉到最底部，")
        print("     应能看到「区域识别（PaddleOCR-json）」配置组；")
        print("     在「批量OCR/截图OCR」标签页的引擎下拉框中，应能选择「文字识别（区域识别）」。")
    except Exception:
        print("[FAIL] 插件加载失败，具体错误如下（请完整复制发给我）：")
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
