"""T04任务专用文件上传验证器
支持tar.gz格式验证、magic number检查、1GB大小限制等
"""

import os
import re
import gzip
import tarfile
import hashlib
from typing import List, Tuple, Optional
from pathlib import Path
from fastapi import UploadFile

from app.config import settings
from app.exceptions import (
    UnsupportedFileTypeError,
    FileSizeExceededError,
    ValidationError,
    FileUploadError
)


# T04任务要求：1GB文件大小限制
T04_MAX_FILE_SIZE = 1024 * 1024 * 1024  # 1GB

# tar.gz文件的magic number
GZIP_MAGIC_NUMBERS = [
    b'\x1f\x8b',  # gzip magic number
]

# tar文件的magic number (在gzip解压后检查)
TAR_MAGIC_NUMBERS = [
    b'ustar\x00',  # POSIX tar format
    b'ustar  \x00',  # GNU tar format
]

# 安全文件名正则表达式
SAFE_FILENAME_PATTERN = re.compile(r'^[a-zA-Z0-9._\-\s()\[\]{}]+\.tar\.gz$')


class T04FileUploadValidator:
    """T04任务专用文件上传验证器"""
    
    def __init__(self):
        self.max_file_size = T04_MAX_FILE_SIZE
        self.required_extension = '.tar.gz'
    
    async def validate_upload_files(self, files: List[UploadFile]) -> Tuple[bool, str]:
        """验证多个上传文件
        
        Args:
            files: 上传的文件列表
            
        Returns:
            Tuple[bool, str]: (是否全部有效, 错误信息)
        """
        if not files:
            return False, "没有选择文件"
        
        # 验证每个文件
        for i, file in enumerate(files):
            is_valid, error_msg = await self.validate_single_file(file)
            if not is_valid:
                return False, f"文件 {i+1} ({file.filename}): {error_msg}"
        
        return True, ""
    
    async def validate_single_file(self, file: UploadFile) -> Tuple[bool, str]:
        """验证单个上传文件
        
        Args:
            file: 上传的文件
            
        Returns:
            Tuple[bool, str]: (是否有效, 错误信息)
        """
        try:
            # 1. 验证文件名
            self._validate_filename(file.filename)
            
            # 2. 验证文件格式
            self._validate_file_format(file.filename)
            
            # 3. 验证文件大小
            await self._validate_file_size(file)
            
            # 4. 验证文件完整性（magic number检查）
            await self._validate_file_integrity(file)
            
            return True, ""
            
        except Exception as e:
            return False, str(e)
    
    def _validate_filename(self, filename: str):
        """验证文件名安全性"""
        if not filename:
            raise ValidationError("文件名不能为空")
        
        # 检查文件名长度
        if len(filename) > 255:
            raise ValidationError("文件名长度不能超过255个字符")
        
        # 检查路径遍历攻击
        if '..' in filename or '/' in filename or '\\' in filename:
            raise ValidationError("文件名不能包含路径分隔符")
        
        # 检查危险字符
        if not SAFE_FILENAME_PATTERN.match(filename):
            raise ValidationError("文件名包含不安全的字符或格式不正确")
        
        # 检查隐藏文件
        if filename.startswith('.'):
            raise ValidationError("不支持隐藏文件")
    
    def _validate_file_format(self, filename: str):
        """验证文件格式（只允许tar.gz）"""
        if not filename.lower().endswith('.tar.gz'):
            raise UnsupportedFileTypeError(
                filename.split('.')[-1] if '.' in filename else 'unknown',
                ['.tar.gz']
            )
    
    async def _validate_file_size(self, file: UploadFile):
        """验证文件大小（1GB限制）"""
        # 重置文件指针
        await file.seek(0)
        
        # 读取文件内容计算大小
        content = await file.read()
        file_size = len(content)
        
        # 重置文件指针
        await file.seek(0)
        
        if file_size > self.max_file_size:
            raise FileSizeExceededError(file_size, self.max_file_size)
        
        if file_size == 0:
            raise ValidationError("文件不能为空")
    
    async def _validate_file_integrity(self, file: UploadFile):
        """验证文件完整性（magic number检查）"""
        # 重置文件指针
        await file.seek(0)
        
        # 读取文件头部用于magic number检查
        header = await file.read(512)  # 读取足够的字节进行检查
        
        # 重置文件指针
        await file.seek(0)
        
        if len(header) < 2:
            raise ValidationError("文件损坏：文件太小")
        
        # 检查gzip magic number
        if not header.startswith(GZIP_MAGIC_NUMBERS[0]):
            raise ValidationError("文件损坏：不是有效的gzip文件")
        
        # 尝试验证tar.gz文件的完整性
        try:
            # 重置文件指针并读取完整内容
            await file.seek(0)
            content = await file.read()
            await file.seek(0)
            
            # 验证gzip解压
            try:
                decompressed = gzip.decompress(content[:1024])  # 只解压前1KB用于验证
            except Exception:
                raise ValidationError("文件损坏：gzip解压失败")
            
            # 检查tar magic number
            tar_magic_found = False
            for magic in TAR_MAGIC_NUMBERS:
                if magic in decompressed:
                    tar_magic_found = True
                    break
            
            if not tar_magic_found:
                raise ValidationError("文件损坏：不是有效的tar文件")
                
        except ValidationError:
            raise
        except Exception as e:
            raise ValidationError(f"文件完整性验证失败: {str(e)}")
    
    def determine_log_type_from_filename(self, filename: str) -> str:
        """根据文件名判断日志类型
        
        Args:
            filename: 文件名
            
        Returns:
            str: 日志类型 ('stack' 或 'oam_antenna')
        """
        filename_lower = filename.lower()
        
        # 根据T04要求：包含"stack"为协议栈日志
        if 'stack' in filename_lower:
            return 'stack'
        else:
            return 'oam_antenna'
    
    def sanitize_filename(self, filename: str) -> str:
        """安全化文件名
        
        Args:
            filename: 原始文件名
            
        Returns:
            str: 安全化后的文件名
        """
        if not filename:
            return "unnamed_file.tar.gz"
        
        # 移除路径
        filename = filename.split('/')[-1].split('\\')[-1]
        
        # 确保以.tar.gz结尾
        if not filename.lower().endswith('.tar.gz'):
            if '.' in filename:
                base_name = filename.rsplit('.', 1)[0]
            else:
                base_name = filename
            filename = base_name + '.tar.gz'
        
        # 替换不安全字符
        filename = re.sub(r'[^\w.\-\s()\[\]{}]', '_', filename)
        
        # 移除多余的空格和下划线
        filename = re.sub(r'[_\s]+', '_', filename).strip('_')
        
        # 限制长度
        if len(filename) > 255:
            base_name = filename[:-7]  # 移除.tar.gz
            max_base_length = 255 - 7  # 为.tar.gz预留空间
            filename = base_name[:max_base_length] + '.tar.gz'
        
        return filename
    
    async def calculate_file_checksum(self, file: UploadFile, algorithm: str = 'sha256') -> str:
        """计算文件校验和
        
        Args:
            file: 上传的文件
            algorithm: 哈希算法
            
        Returns:
            str: 文件校验和
        """
        # 重置文件指针
        await file.seek(0)
        
        # 选择哈希算法
        if algorithm.lower() == 'md5':
            hasher = hashlib.md5()
        elif algorithm.lower() == 'sha1':
            hasher = hashlib.sha1()
        elif algorithm.lower() == 'sha256':
            hasher = hashlib.sha256()
        else:
            raise ValidationError(f"不支持的哈希算法: {algorithm}")
        
        # 分块读取文件计算哈希
        chunk_size = 8192
        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
        
        # 重置文件指针
        await file.seek(0)
        
        return hasher.hexdigest()
    
    def generate_unique_filename(self, original_filename: str, file_id: str) -> str:
        """生成唯一文件名（避免冲突）
        
        Args:
            original_filename: 原始文件名
            file_id: 文件ID
            
        Returns:
            str: 唯一文件名
        """
        sanitized_name = self.sanitize_filename(original_filename)
        return f"{file_id}_{sanitized_name}"


# 创建全局验证器实例
t04_file_validator = T04FileUploadValidator()