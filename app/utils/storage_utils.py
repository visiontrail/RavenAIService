"""
存储相关的工具函数
"""

import os
from pathlib import Path

from app.exceptions import StorageError


def get_free_bytes(path: Path) -> int:
    """
    获取指定路径所在文件系统的可用字节数
    """
    try:
        stat = os.statvfs(str(path))
        return stat.f_bavail * stat.f_frsize
    except Exception as e:
        raise StorageError(f"获取磁盘剩余空间失败: {e}")


def ensure_free_space(path: Path, required_bytes: int, reserve_bytes: int = 0):
    """
    确保剩余空间满足需求
    - required_bytes: 当前操作至少需要的空间
    - reserve_bytes: 额外预留空间，防止磁盘被占满
    """
    free_bytes = get_free_bytes(path)
    need = required_bytes + max(reserve_bytes, 0)
    if free_bytes < need:
        raise StorageError(
            f"磁盘空间不足: 需要 {need / (1024*1024):.1f}MB, "
            f"仅剩 {free_bytes / (1024*1024):.1f}MB"
        )
