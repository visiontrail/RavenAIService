"""日志归档文件上传验证器
支持所有 SUPPORTED_ARCHIVE_EXTS 格式的 magic number 校验、1GB 大小限制等。
"""

import re
import hashlib
from typing import List, Tuple, Optional
from pathlib import Path
from fastapi import UploadFile

from app.exceptions import (
    UnsupportedFileTypeError,
    FileSizeExceededError,
    ValidationError,
)
from app.tools.archive_tool import SUPPORTED_ARCHIVE_EXTS, check_archive_magic


# 1GB 文件大小限制
T04_MAX_FILE_SIZE = 1024 * 1024 * 1024

# 安全文件名基础字符集
_SAFE_NAME_BASE = r'[a-zA-Z0-9._\-\s()\[\]{}]+'
# 按扩展名长度降序排，确保 .tar.gz 先于 .gz 匹配
_EXT_PATTERN = '(' + '|'.join(
    re.escape(ext)
    for ext in sorted(SUPPORTED_ARCHIVE_EXTS, key=len, reverse=True)
) + ')'
SAFE_FILENAME_PATTERN = re.compile(r'^' + _SAFE_NAME_BASE + _EXT_PATTERN + r'$')


class T04FileUploadValidator:
    """日志归档文件上传验证器，支持所有 SUPPORTED_ARCHIVE_EXTS 格式。"""

    def __init__(self):
        self.max_file_size = T04_MAX_FILE_SIZE
    
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
        """验证文件名安全性。"""
        if not filename:
            raise ValidationError("文件名不能为空")

        if len(filename) > 255:
            raise ValidationError("文件名长度不能超过255个字符")

        if '..' in filename or '/' in filename or '\\' in filename:
            raise ValidationError("文件名不能包含路径分隔符")

        if filename.startswith('.'):
            raise ValidationError("不支持隐藏文件")

        if not SAFE_FILENAME_PATTERN.match(filename):
            supported = ', '.join(sorted(SUPPORTED_ARCHIVE_EXTS))
            raise ValidationError(
                f"文件名包含不安全的字符或格式不正确，支持的格式：{supported}"
            )

    def _validate_file_format(self, filename: str):
        """验证文件格式是否在支持列表内。"""
        fn = filename.lower()
        suffixes = "".join(Path(fn).suffixes)
        if suffixes not in SUPPORTED_ARCHIVE_EXTS:
            raise UnsupportedFileTypeError(
                suffixes or (filename.split('.')[-1] if '.' in filename else 'unknown'),
                sorted(SUPPORTED_ARCHIVE_EXTS),
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
        """按文件扩展名校验 magic number。"""
        await file.seek(0)
        # 读取足够覆盖所有格式的 magic（tar 的 ustar 在偏移 257，加上 5 字节）
        header = await file.read(512)
        await file.seek(0)

        if len(header) < 2:
            raise ValidationError("文件损坏：文件太小")

        fn = file.filename or ""
        ext = "".join(Path(fn.lower()).suffixes)
        if not check_archive_magic(header, ext):
            raise ValidationError(f"文件损坏：magic number 与扩展名 {ext!r} 不匹配")
    
    def determine_log_type_from_filename(self, filename: str) -> str:
        """根据文件名判断日志类型
        
        Args:
            filename: 文件名
            
        Returns:
            str: 日志类型 ('stack', 'oam_antenna', 或 'full')
        """
        filename_lower = filename.lower()
        
        # 检查是否为全量日志：同时包含stack和(oam或om)
        has_stack = 'stack' in filename_lower
        has_oam = 'oam' in filename_lower or 'om' in filename_lower
        
        if has_stack and has_oam:
            return 'full'
        elif has_stack:
            return 'stack'
        else:
            return 'oam_antenna'
    
    def sanitize_filename(self, filename: str) -> str:
        """安全化文件名，保留原始扩展名。"""
        if not filename:
            return "unnamed_file.tar.gz"

        # 移除路径
        filename = filename.split('/')[-1].split('\\')[-1]

        # 提取支持的扩展名（按长度降序匹配，确保 .tar.gz 先于 .gz）
        fn_lower = filename.lower()
        ext = ""
        for candidate in sorted(SUPPORTED_ARCHIVE_EXTS, key=len, reverse=True):
            if fn_lower.endswith(candidate):
                ext = candidate
                break
        if not ext:
            ext = ".tar.gz"

        base_name = filename[: len(filename) - len(ext)]

        # 替换不安全字符
        base_name = re.sub(r'[^\w.\-\s()\[\]{}]', '_', base_name)
        base_name = re.sub(r'[_\s]+', '_', base_name).strip('_')

        # 限制总长度
        max_base = 255 - len(ext)
        base_name = base_name[:max_base]

        return base_name + ext
    
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