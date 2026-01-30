"""
软件包上传API路由
处理软件包的上传和管理
"""

import json
import logging
import os
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.config import settings
from app.utils.storage_utils import get_free_bytes

logger = logging.getLogger(__name__)
router = APIRouter()

# 软件包存储目录
PACKAGES_DIR = Path(settings.base_dir) / "packages"
PACKAGES_DIR.mkdir(parents=True, exist_ok=True)


class PackageMetadata(BaseModel):
    """软件包元数据"""
    id: str
    name: str
    version: str
    packageType: str
    size: int
    createdAt: str
    metadata: Optional[dict] = None


class PackageUploadResponse(BaseModel):
    """上传响应"""
    success: bool
    message: str
    data: Optional[dict] = None


@router.post("/upload", response_model=PackageUploadResponse, status_code=201)
async def upload_package(
    request: Request,
    file: UploadFile = File(..., description="要上传的软件包文件"),
    packageInfo: str = Form(..., description="软件包元数据JSON字符串")
):
    """
    上传软件包
    
    接收客户端上传的软件包文件和元数据信息。
    支持大文件上传，使用流式接收以节省内存。
    """
    try:
        # 解析包信息
        try:
            pkg_info = json.loads(packageInfo)
            logger.info(f"收到软件包上传请求: {pkg_info.get('name', 'unknown')}")
        except json.JSONDecodeError as e:
            logger.error(f"解析packageInfo失败: {e}")
            raise HTTPException(status_code=400, detail=f"无效的packageInfo JSON: {str(e)}")
        
        # 获取文件名
        filename = file.filename or pkg_info.get('name', f"package_{datetime.now().strftime('%Y%m%d_%H%M%S')}.tgz")
        
        # 创建保存路径
        save_path = PACKAGES_DIR / filename
        
        # 如果文件已存在，添加时间戳
        if save_path.exists():
            name_parts = filename.rsplit('.', 2)
            if len(name_parts) > 1:
                base_name = name_parts[0]
                extension = '.'.join(name_parts[1:])
                filename = f"{base_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{extension}"
            else:
                filename = f"{filename}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            save_path = PACKAGES_DIR / filename
        
        # 流式保存文件，计算SHA256
        sha256_hash = hashlib.sha256()
        total_bytes = 0
        chunk_size = 1024 * 1024  # 1MB chunks
        
        logger.info(f"开始保存软件包: {save_path}")
        
        with open(save_path, 'wb') as f:
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                # 检查磁盘空间，预留安全余量
                free_bytes = get_free_bytes(PACKAGES_DIR)
                if free_bytes - settings.disk_reserve_bytes < len(chunk):
                    os.remove(save_path)
                    logger.error("磁盘空间不足，终止软件包写入")
                    raise HTTPException(
                        status_code=507,
                        detail="磁盘空间不足，无法完成上传"
                    )
                f.write(chunk)
                sha256_hash.update(chunk)
                total_bytes += len(chunk)
        
        calculated_hash = sha256_hash.hexdigest()
        
        logger.info(f"软件包保存完成: {filename}, 大小: {total_bytes} bytes, SHA256: {calculated_hash}")
        
        # 验证SHA256（如果提供）
        expected_hash = pkg_info.get('metadata', {}).get('sha256')
        if expected_hash and expected_hash.lower() != calculated_hash.lower():
            # 删除已保存的文件
            os.remove(save_path)
            logger.error(f"SHA256校验失败: 期望 {expected_hash}, 实际 {calculated_hash}")
            raise HTTPException(
                status_code=400, 
                detail=f"SHA256校验失败: 文件可能在传输过程中损坏"
            )
        
        # 验证文件大小
        expected_size = pkg_info.get('size')
        if expected_size and expected_size != total_bytes:
            logger.warning(f"文件大小不匹配: 期望 {expected_size}, 实际 {total_bytes}")
        
        return PackageUploadResponse(
            success=True,
            message=f"软件包上传成功: {filename}",
            data={
                "id": pkg_info.get('id'),
                "filename": filename,
                "size": total_bytes,
                "sha256": calculated_hash,
                "path": str(save_path),
                "uploadedAt": datetime.now().isoformat()
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"软件包上传失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"软件包上传失败: {str(e)}")


@router.get("/packages", response_model=dict)
async def list_packages():
    """列出所有已上传的软件包"""
    try:
        packages = []
        for file_path in PACKAGES_DIR.glob("*.tgz"):
            stat = file_path.stat()
            packages.append({
                "name": file_path.name,
                "size": stat.st_size,
                "uploadedAt": datetime.fromtimestamp(stat.st_mtime).isoformat()
            })
        
        return {
            "success": True,
            "data": {
                "packages": packages,
                "total": len(packages)
            }
        }
    except Exception as e:
        logger.error(f"列出软件包失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
