# -*- coding: utf-8 -*-
# 区域识别插件 - 区域数据模型
# 功能：定义命名区域（百分比坐标），负责 regions.json 的读写、
#       百分比坐标与像素坐标的换算、文块是否在区域内的判定。

import json
import os


class Region:
    """一个命名区域。坐标为百分比（0~100），相对图片宽高。"""

    __slots__ = ("name", "x1", "y1", "x2", "y2")

    def __init__(self, name, x1, y1, x2, y2):
        self.name = str(name)
        self.x1 = float(x1)
        self.y1 = float(y1)
        self.x2 = float(x2)
        self.y2 = float(y2)

    def toDict(self):
        return {
            "name": self.name,
            "x1": round(self.x1, 4),
            "y1": round(self.y1, 4),
            "x2": round(self.x2, 4),
            "y2": round(self.y2, 4),
        }

    @staticmethod
    def fromDict(d):
        return Region(
            d.get("name", ""),
            float(d.get("x1", 0)),
            float(d.get("y1", 0)),
            float(d.get("x2", 0)),
            float(d.get("y2", 0)),
        )

    def isValid(self):
        """有效性：有名称且面积不为0"""
        return bool(self.name) and self.x2 > self.x1 and self.y2 > self.y1

    def toPixel(self, w, h):
        """百分比 -> 像素矩形 (x1, y1, x2, y2)，自动归一化并裁剪到图片范围内。"""
        x1 = round(self.x1 / 100.0 * w)
        y1 = round(self.y1 / 100.0 * h)
        x2 = round(self.x2 / 100.0 * w)
        y2 = round(self.y2 / 100.0 * h)
        if x1 > x2:
            x1, x2 = x2, x1
        if y1 > y2:
            y1, y2 = y2, y1
        x1 = max(0, min(w, x1))
        x2 = max(0, min(w, x2))
        y1 = max(0, min(h, y1))
        y2 = max(0, min(h, y2))
        return x1, y1, x2, y2


class RegionStore:
    """区域集合的持久化存储（JSON 文件）。"""

    def __init__(self, path):
        self.path = path

    def exists(self):
        return os.path.exists(self.path)

    def load(self):
        """读取区域列表；文件不存在返回 []。"""
        regions = []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for d in data.get("regions", []):
                r = Region.fromDict(d)
                if r.isValid():
                    regions.append(r)
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"[Warning] 读取区域文件失败：{self.path}\n{e}")
        return regions

    def save(self, regions):
        """保存区域列表（原子写入）。"""
        data = {"regions": [r.toDict() for r in regions]}
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception as e:
            print(f"[Error] 保存区域文件失败：{self.path}\n{e}")
            raise


class RegionFilter:
    """基于像素矩形的文块过滤工具。"""

    @staticmethod
    def rectsInBox(a, b):
        """矩形 a 是否完全包含矩形 b（a、b 均为 (x1,y1,x2,y2)）"""
        return a[0] <= b[0] and a[1] <= b[1] and a[2] >= b[2] and a[3] >= b[3]

    @staticmethod
    def centerInBox(a, b):
        """矩形 b 的中心点是否在矩形 a 内"""
        cx = (b[0] + b[2]) / 2.0
        cy = (b[1] + b[3]) / 2.0
        return a[0] <= cx <= a[2] and a[1] <= cy <= a[3]

    @staticmethod
    def blockRect(box):
        """文块 box（4点）-> (x1,y1,x2,y2)"""
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        return min(xs), min(ys), max(xs), max(ys)

    @classmethod
    def keepBlocks(cls, blocks, regionPx, rule="full"):
        """按规则保留区域内的文块。regionPx: (x1,y1,x2,y2) 像素矩形。"""
        if rule == "center":
            check = cls.centerInBox
        else:  # full
            check = cls.rectsInBox
        out = []
        for b in blocks:
            r = cls.blockRect(b.get("box", []))
            if check(regionPx, r):
                out.append(b)
        return out
