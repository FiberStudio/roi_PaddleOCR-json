# -*- coding: utf-8 -*-
# 区域识别插件 - 区域预设（Preset）数据模型与存储
#
# 预设 = 一组命名区域 + 名称 + 备注，单独保存在 presets.json。
# 用途：把本次框选好的区域组存成具名预设，下次直接选择加载即可复用，
#       不用重复框选；备注用于快速辨认"这是什么单据/场景"。
#
# presets.json 结构：
# {
#   "presets": [
#     {
#       "id": "p1757654321000",
#       "name": "增值税发票",
#       "remark": "号码在右上角，价税合计在右下角",
#       "createdAt": "2026-09-13 10:00:00",
#       "updatedAt": "2026-09-13 10:00:00",
#       "regions": [
#         {"name": "发票号码", "x1": 12.5, "y1": 8.3, "x2": 37.5, "y2": 15}
#       ]
#     }
#   ]
# }
#
# 兼容性：本模块同时被 Umi 运行时（Python 3.8）与命令行测试环境加载，
#         因此不使用 3.9+ 的语法。

import json
import os
import time

from .roi_region import Region

MAX_NAME_LEN = 60
MAX_REMARK_LEN = 200


def _pluginDir():
    return os.path.dirname(os.path.abspath(__file__))


# 默认预设文件（与插件同目录；Api 可用 globalArgd["preset_file"] 覆盖，便于测试）
DEFAULT_PRESET_FILE = os.path.join(_pluginDir(), "presets.json")


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def normalizeRegions(regions):
    """规范化区域列表：接受 Region 或 dict，过滤无效项，返回 dict 列表。"""
    out = []
    for item in regions or []:
        try:
            region = item if isinstance(item, Region) else Region.fromDict(item)
        except Exception:
            continue
        if region.isValid():
            out.append(region.toDict())
    return out


def regionNames(preset):
    """预设内的区域名列表。"""
    return [d.get("name", "") for d in (preset or {}).get("regions", [])]


def labelOf(brief):
    """预设摘要 -> 下拉框/列表用的显示文本（名称 + 备注 + 区域数）。"""
    label = str(brief.get("name", ""))
    remark = str(brief.get("remark", "") or "")
    if remark:
        label = "%s（%s）" % (label, remark)
    return "%s [%d个区域]" % (label, int(brief.get("regionCount", 0)))


class PresetStore:
    """预设集合的持久化存储（JSON 文件，原子写入）。"""

    def __init__(self, path):
        self.path = path or DEFAULT_PRESET_FILE

    # ==================== 读写 ====================

    def exists(self):
        return os.path.exists(self.path)

    def load(self):
        """读取预设列表；文件不存在或损坏时返回 []。"""
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return []
        except Exception as e:
            print(f"[Warning] 读取预设文件失败：{self.path}\n{e}")
            return []
        rawList = data.get("presets", []) if isinstance(data, dict) else []
        presets = []
        for raw in rawList:
            preset = self._normalize(raw)
            if preset:
                presets.append(preset)
        return presets

    def save(self, presets):
        """保存预设列表（先写 .tmp 再原子替换）。"""
        data = {"presets": list(presets or [])}
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception as e:
            print(f"[Error] 保存预设文件失败：{self.path}\n{e}")
            raise

    def _normalize(self, raw):
        """把磁盘上的一条记录规范化为预设 dict；无效返回 None。"""
        if not isinstance(raw, dict):
            return None
        name = str(raw.get("name", "") or "").strip()
        regions = normalizeRegions(raw.get("regions", []))
        if not name or not regions:
            return None
        pid = str(raw.get("id", "") or "").strip()
        if not pid:
            pid = "name:" + name  # 没有 id 的旧数据 -> 用名称生成稳定 id
        remark = str(raw.get("remark", "") or "").strip()
        return {
            "id": pid,
            "name": name[:MAX_NAME_LEN],
            "remark": remark[:MAX_REMARK_LEN],
            "createdAt": str(raw.get("createdAt", "") or ""),
            "updatedAt": str(raw.get("updatedAt", "") or ""),
            "regions": regions,
        }

    @staticmethod
    def _newId(presets):
        """生成不与现有预设冲突的 id。"""
        base = "p%d" % int(time.time() * 1000)
        used = set(p.get("id", "") for p in (presets or []))
        pid = base
        n = 1
        while pid in used:
            pid = "%s_%d" % (base, n)
            n += 1
        return pid

    # ==================== 查询 ====================

    def get(self, presetId):
        """按 id 查找预设；找不到返回 None。"""
        pid = str(presetId or "").strip()
        if not pid:
            return None
        for preset in self.load():
            if preset["id"] == pid:
                return preset
        return None

    def findByName(self, name):
        """按名称查找预设；找不到返回 None。"""
        target = str(name or "").strip()
        if not target:
            return None
        for preset in self.load():
            if preset["name"] == target:
                return preset
        return None

    def briefs(self):
        """界面用的摘要列表（不含坐标）。"""
        out = []
        for preset in self.load():
            out.append(
                {
                    "id": preset["id"],
                    "name": preset["name"],
                    "remark": preset["remark"],
                    "regionCount": len(preset.get("regions", [])),
                    "regionNames": regionNames(preset),
                    "createdAt": preset.get("createdAt", ""),
                    "updatedAt": preset.get("updatedAt", ""),
                }
            )
        return out

    def options(self):
        """全局设置下拉框用的 [[id, 显示文本], ...]（不含"不使用预设"项）。"""
        return [[b["id"], labelOf(b)] for b in self.briefs()]

    # ==================== 修改 ====================

    @staticmethod
    def _checkName(name):
        if not name:
            raise ValueError("预设名称不能为空。")
        if len(name) > MAX_NAME_LEN:
            raise ValueError("预设名称最长 %d 个字符。" % MAX_NAME_LEN)
        return name

    @staticmethod
    def _checkRemark(remark):
        if len(remark) > MAX_REMARK_LEN:
            raise ValueError("备注最长 %d 个字符。" % MAX_REMARK_LEN)
        return remark

    def saveAs(self, name, remark, regions):
        """按名称保存预设：同名则覆盖其区域与备注，否则新建。
        返回 (preset, overwrote)。"""
        name = self._checkName(str(name or "").strip())
        remark = self._checkRemark(str(remark or "").strip())
        regionDicts = normalizeRegions(regions)
        if not regionDicts:
            raise ValueError("当前没有可保存的区域，请先框选至少一个区域。")
        presets = self.load()
        now = _now()
        for preset in presets:
            if preset["name"] == name:
                preset["remark"] = remark
                preset["regions"] = regionDicts
                preset["updatedAt"] = now
                self.save(presets)
                return preset, True
        preset = {
            "id": self._newId(presets),
            "name": name,
            "remark": remark,
            "createdAt": now,
            "updatedAt": now,
            "regions": regionDicts,
        }
        presets.append(preset)
        self.save(presets)
        return preset, False

    def updateRegions(self, presetId, regions):
        """用当前区域覆盖已有预设（名称、备注、创建时间保持不变）。"""
        regionDicts = normalizeRegions(regions)
        if not regionDicts:
            raise ValueError("当前没有可保存的区域，请先框选至少一个区域。")
        presets = self.load()
        pid = str(presetId or "").strip()
        for preset in presets:
            if preset["id"] == pid:
                preset["regions"] = regionDicts
                preset["updatedAt"] = _now()
                self.save(presets)
                return preset
        raise ValueError("找不到该预设（可能已被删除），请刷新列表后重试。")

    def remove(self, presetId):
        """删除预设；返回是否真的删除了。"""
        pid = str(presetId or "").strip()
        presets = self.load()
        kept = [p for p in presets if p["id"] != pid]
        if len(kept) == len(presets):
            return False
        self.save(kept)
        return True
