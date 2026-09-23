# -*- coding: utf-8 -*-
# 区域识别插件（roi_PaddleOCR-json）
# 功能：只提取框选区域内的文本。首次识别时弹窗框选并命名多个区域，
#       之后批量复用；支持模板渲染与 TXT/CSV 导出。
# 说明：引擎文件（PaddleOCR-json.exe 等）需自行组装，见 README.md 与 assemble.bat。

from . import roi_config
from . import roi_ocr

# 插件信息
PluginInfo = {
    # 插件组别
    "group": "ocr",
    # 全局配置
    "global_options": roi_config.globalOptions,
    # 局部配置
    "local_options": roi_config.localOptions,
    # 接口类
    "api_class": roi_ocr.Api,
}
