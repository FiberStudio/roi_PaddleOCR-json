# -*- coding: utf-8 -*-
# 区域识别插件 - 文本模板渲染 与 TXT/CSV 导出
# 模板占位符：{字段名} 会被替换为对应区域识别出的文本。
# 例：模板 "发票号码是《{发票号码}》，税额是《{增值税额}》"。

import csv
import os
import re


def renderTemplate(template, fieldMap):
    """按模板渲染文本。
    fieldMap: {区域名: 识别文本}
    未知字段名替换为空字符串。
    """
    if not template:
        return ""

    def repl(m):
        name = m.group(1)
        if name in fieldMap:
            return fieldMap[name]
        return ""

    return re.sub(r"\{([^{}]+)\}", repl, template)


class Exporter:
    """向导出目录追加写入 TXT / CSV 结果。"""

    TXT_FILE = "字段提取.txt"
    CSV_FILE = "字段提取.csv"

    def __init__(self, outDir):
        self.outDir = outDir

    def _ensureDir(self):
        os.makedirs(self.outDir, exist_ok=True)

    def exportTxt(self, line):
        """追加一行文本。"""
        self._ensureDir()
        path = os.path.join(self.outDir, self.TXT_FILE)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def exportCsv(self, header, row):
        """追加一行 CSV。首次写入时自动带表头；UTF-8 BOM，Excel 可直接打开。"""
        self._ensureDir()
        path = os.path.join(self.outDir, self.CSV_FILE)
        newFile = not os.path.exists(path)
        with open(path, "a", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            if newFile:
                writer.writerow(header)
            writer.writerow(row)
