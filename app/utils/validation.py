"""
数据验证工具模块
"""

import mimetypes
import hashlib
import re
from typing import List, Optional, Tuple
from fastapi import UploadFile

from app.config import settings
from app.exceptions import (
    UnsupportedFileTypeError,
    FileSizeExceededError,
    ValidationError
)


# 支持的日志文件类型
SUPPORTED_LOG_EXTENSIONS = [
    '.log', '.txt', '.out', '.err', '.trace',
    '.json', '.xml', '.csv', '.tsv',
    '.gz', '.zip', '.tar', '.bz2', '.tgz'
]

SUPPORTED_MIME_TYPES = [
    'text/plain',
    'text/csv',
    'application/json',
    'application/xml',
    'text/xml',
    'application/gzip',
    'application/zip',
    'application/x-tar',
    'application/x-bzip2',
    'application/octet-stream'  # 允许二进制文件，但会进一步验证扩展名
]

# 文件名安全字符正则
SAFE_FILENAME_PATTERN = re.compile(r'^[a-zA-Z0-9._\-\s()[\]{}]+$')

# 最大文件名长度
MAX_FILENAME_LENGTH = 255


class FileValidator:
    """文件验证器"""
    
    def __init__(self):
        self.max_file_size = settings.max_file_size
        self.supported_extensions = SUPPORTED_LOG_EXTENSIONS
        self.supported_mime_types = SUPPORTED_MIME_TYPES

    async def validate_upload_file(self, file: UploadFile) -> Tuple[bool, str]:
        """
        验证上传的文件
        
        Args:
            file: FastAPI UploadFile对象
            
        Returns:
            Tuple[bool, str]: (是否有效, 错误信息)
        """
        try:
            # 验证文件名
            self._validate_filename(file.filename)
            
            # 验证文件类型
            self._validate_file_type(file.filename, file.content_type)
            
            # 验证文件大小
            await self._validate_file_size(file)
            
            return True, ""
            
        except Exception as e:
            return False, str(e)

    def _validate_filename(self, filename: str):
        """验证文件名"""
        if not filename:
            raise ValidationError("文件名不能为空")
        
        if len(filename) > MAX_FILENAME_LENGTH:
            raise ValidationError(f"文件名长度不能超过{MAX_FILENAME_LENGTH}个字符")
        
        # 检查危险字符
        if not SAFE_FILENAME_PATTERN.match(filename):
            raise ValidationError("文件名包含不安全的字符")
        
        # 检查是否为隐藏文件或系统文件
        if filename.startswith('.') or filename.startswith('~'):
            raise ValidationError("不支持隐藏文件或临时文件")
        
        # 检查路径遍历攻击
        if '..' in filename or '/' in filename or '\\' in filename:
            raise ValidationError("文件名不能包含路径分隔符")

    def _validate_file_type(self, filename: str, content_type: str):
        """验证文件类型"""
        # 获取文件扩展名
        if '.' not in filename:
            raise UnsupportedFileTypeError("unknown", self.supported_extensions)
        
        filename_lower = filename.lower()
        
        # 检查是否为.tar.gz格式
        if filename_lower.endswith('.tar.gz'):
            # .tar.gz格式是支持的
            return
        
        # 检查普通扩展名
        extension = '.' + filename.split('.')[-1].lower()
        
        # 验证扩展名
        if extension not in self.supported_extensions:
            raise UnsupportedFileTypeError(extension, self.supported_extensions)
        
        # 验证MIME类型（如果提供）
        if content_type and content_type not in self.supported_mime_types:
            # 尝试根据文件名推断MIME类型
            guessed_type, _ = mimetypes.guess_type(filename)
            if guessed_type and guessed_type not in self.supported_mime_types:
                raise UnsupportedFileTypeError(content_type, self.supported_mime_types)

    async def _validate_file_size(self, file: UploadFile):
        """验证文件大小"""
        # 重置文件指针
        await file.seek(0)
        
        # 读取文件内容计算大小
        content = await file.read()
        file_size = len(content)
        
        # 重置文件指针
        await file.seek(0)
        
        if file_size > self.max_file_size:
            raise FileSizeExceededError(file_size, self.max_file_size)

    def sanitize_filename(self, filename: str) -> str:
        """清理文件名"""
        if not filename:
            return "unnamed_file"
        
        # 移除路径
        filename = filename.split('/')[-1].split('\\')[-1]
        
        # 限制长度
        if len(filename) > MAX_FILENAME_LENGTH:
            name, ext = filename.rsplit('.', 1) if '.' in filename else (filename, '')
            max_name_length = MAX_FILENAME_LENGTH - len(ext) - 1 if ext else MAX_FILENAME_LENGTH
            filename = name[:max_name_length]
            if ext:
                filename += '.' + ext
        
        # 替换不安全字符
        filename = re.sub(r'[^\w.\-\s()[\]{}]', '_', filename)
        
        # 移除多余的空格和下划线
        filename = re.sub(r'[_\s]+', '_', filename).strip('_')
        
        return filename

    async def calculate_file_checksum(self, file: UploadFile, algorithm: str = 'sha256') -> str:
        """计算文件校验和"""
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


class RequestValidator:
    """请求验证器"""
    
    @staticmethod
    def validate_log_id(log_id: str) -> bool:
        """验证日志ID格式"""
        if not log_id:
            raise ValidationError("日志ID不能为空")
        
        # UUID格式验证
        uuid_pattern = re.compile(
            r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
            re.IGNORECASE
        )
        
        if not uuid_pattern.match(log_id):
            raise ValidationError("无效的日志ID格式")
        
        return True

    @staticmethod
    def validate_log_ids(log_ids: List[str]) -> bool:
        """验证日志ID列表"""
        if not log_ids:
            raise ValidationError("日志ID列表不能为空")
        
        if len(log_ids) > 100:
            raise ValidationError("单次操作的日志数量不能超过100个")
        
        # 检查重复ID
        if len(set(log_ids)) != len(log_ids):
            raise ValidationError("日志ID列表中不能有重复项")
        
        # 验证每个ID
        for log_id in log_ids:
            RequestValidator.validate_log_id(log_id)
        
        return True

    @staticmethod
    def validate_search_keyword(keyword: str) -> bool:
        """验证搜索关键词"""
        if not keyword:
            return True
        
        if len(keyword) < 2:
            raise ValidationError("搜索关键词至少需要2个字符")
        
        if len(keyword) > 100:
            raise ValidationError("搜索关键词不能超过100个字符")
        
        # 检查SQL注入等危险字符
        dangerous_patterns = [
            r"['\"`;]",  # SQL注入
            r"<script",  # XSS
            r"javascript:",  # JavaScript执行
        ]
        
        for pattern in dangerous_patterns:
            if re.search(pattern, keyword, re.IGNORECASE):
                raise ValidationError("搜索关键词包含不安全的字符")
        
        return True


# 创建全局验证器实例
file_validator = FileValidator()
request_validator = RequestValidator()
