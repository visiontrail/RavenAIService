"""
文件操作工具函数
"""

import os
import shutil
from typing import Optional
from pathlib import Path

from app.config import settings


def ensure_directory_exists(directory: str) -> bool:
    """确保目录存在，如果不存在则创建"""
    try:
        os.makedirs(directory, exist_ok=True)
        return True
    except Exception as e:
        print(f"创建目录失败: {directory}, 错误: {e}")
        return False


def get_file_size(file_path: str) -> Optional[int]:
    """获取文件大小（字节）"""
    try:
        return os.path.getsize(file_path)
    except (OSError, FileNotFoundError):
        return None


def is_file_size_valid(file_size: int) -> bool:
    """检查文件大小是否在允许范围内"""
    return 0 < file_size <= settings.max_file_size


def cleanup_temp_files(temp_dir: Optional[str] = None) -> int:
    """清理临时文件，返回清理的文件数量"""
    if temp_dir is None:
        temp_dir = settings.temp_dir
    
    if not os.path.exists(temp_dir):
        return 0
    
    cleaned_count = 0
    try:
        for filename in os.listdir(temp_dir):
            file_path = os.path.join(temp_dir, filename)
            if os.path.isfile(file_path):
                os.remove(file_path)
                cleaned_count += 1
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)
                cleaned_count += 1
    except Exception as e:
        print(f"清理临时文件失败: {e}")
    
    return cleaned_count


def format_file_size(size_bytes: int) -> str:
    """将文件大小转换为人类可读格式
    
    Args:
        size_bytes: 文件大小（字节）
        
    Returns:
        str: 格式化后的文件大小字符串，如 "1.5 MB"
    """
    if size_bytes == 0:
        return "0 B"
    
    # 定义单位
    units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
    unit_index = 0
    size = float(size_bytes)
    
    # 计算合适的单位
    while size >= 1024.0 and unit_index < len(units) - 1:
        size /= 1024.0
        unit_index += 1
    
    # 格式化数字
    if unit_index == 0:  # 字节不需要小数
        return f"{int(size)} {units[unit_index]}"
    elif size >= 100:
        return f"{size:.0f} {units[unit_index]}"
    elif size >= 10:
        return f"{size:.1f} {units[unit_index]}"
    else:
        return f"{size:.2f} {units[unit_index]}"


def get_safe_filename(filename: str) -> str:
    """获取安全的文件名，移除或替换危险字符"""
    # 移除路径分隔符和其他危险字符
    unsafe_chars = ['/', '\\', '..', '<', '>', ':', '"', '|', '?', '*']
    safe_name = filename
    
    for char in unsafe_chars:
        safe_name = safe_name.replace(char, '_')
    
    # 限制文件名长度
    if len(safe_name) > 255:
        name_part = Path(safe_name).stem[:200]
        ext_part = Path(safe_name).suffix
        safe_name = name_part + ext_part
    
    return safe_name
