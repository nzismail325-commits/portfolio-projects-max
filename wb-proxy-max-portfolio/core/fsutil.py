# -*- coding: utf-8 -*-
"""core/fsutil.py —— 文件原子写（本地自研，上游无对应）

tmp 文件 + os.replace 的原子落盘是全仓统一口径：崩溃不会留下半截文件。
锁不在这里加——并发控制由调用方持有（不同数据各有自己的锁）。
"""
import json
import os


def atomic_write_json(path, data, indent=2):
    """原子写 JSON 文件：父目录不存在则创建；返回 path。"""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=indent)
    os.replace(tmp, path)
    return path
