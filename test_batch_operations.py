#!/usr/bin/env python3
"""
批量操作功能测试脚本
测试T08要求的批量删除和批量下载功能
"""

import asyncio
import aiohttp
import json
import tempfile
import os
import uuid
from pathlib import Path

# API基础URL
BASE_URL = "http://localhost:8085/api/v1/logs"

async def test_batch_operations():
    """测试批量操作功能"""
    
    async with aiohttp.ClientSession() as session:
        print("🚀 开始测试批量操作功能...")
        
        # 1. 首先上传一些测试文件
        print("\n📤 步骤1: 上传测试文件...")
        uploaded_ids = []
        
        for i in range(3):
            # 创建临时测试文件
            with tempfile.NamedTemporaryFile(mode='w', suffix=f'_test_{i}.log', delete=False) as f:
                f.write(f"这是测试日志文件 {i}\n")
                f.write(f"时间戳: {i}\n")
                f.write("测试内容...\n" * 10)
                temp_file_path = f.name
            
            # 上传文件
            with open(temp_file_path, 'rb') as f:
                data = aiohttp.FormData()
                data.add_field('file', f, filename=f'test_log_{i}.log')
                data.add_field('log_type', 'stack')
                data.add_field('log_level', 'info')
                
                async with session.post(f"{BASE_URL}/upload", data=data) as resp:
                    if resp.status == 201:
                        result = await resp.json()
                        log_id = result['data']['id']
                        uploaded_ids.append(log_id)
                        print(f"  ✅ 上传成功: {log_id}")
                    else:
                        print(f"  ❌ 上传失败: {resp.status}")
                        text = await resp.text()
                        print(f"     错误信息: {text}")
            
            # 清理临时文件
            os.unlink(temp_file_path)
        
        if not uploaded_ids:
            print("❌ 没有成功上传任何文件，无法继续测试")
            return
        
        print(f"✅ 成功上传 {len(uploaded_ids)} 个文件")
        
        # 2. 测试批量下载功能
        print("\n📥 步骤2: 测试批量下载功能...")
        
        # 测试普通批量下载
        download_request = {
            "log_ids": uploaded_ids,
            "compress": True,
            "include_metadata": True
        }
        
        async with session.post(f"{BASE_URL}/batch/download", 
                               json=download_request) as resp:
            if resp.status == 200:
                result = await resp.json()
                print("  ✅ 批量下载请求成功")
                print(f"     下载URL: {result['data']['download_url']}")
                print(f"     文件大小: {result['data']['file_size']} bytes")
                print(f"     过期时间: {result['data']['expires_at']}")
                
                # 测试实际下载
                download_url = result['data']['download_url']
                async with session.get(f"http://localhost:8085{download_url}") as download_resp:
                    if download_resp.status == 200:
                        content = await download_resp.read()
                        print(f"  ✅ 文件下载成功，大小: {len(content)} bytes")
                    else:
                        print(f"  ❌ 文件下载失败: {download_resp.status}")
            else:
                print(f"  ❌ 批量下载失败: {resp.status}")
                text = await resp.text()
                print(f"     错误信息: {text}")
        
        # 测试流式批量下载
        print("\n📥 步骤3: 测试流式批量下载功能...")
        
        stream_request = {
            "log_ids": uploaded_ids[:2],  # 只下载前两个
            "compress": True,
            "include_metadata": False
        }
        
        async with session.post(f"{BASE_URL}/batch/download-stream", 
                               json=stream_request) as resp:
            if resp.status == 200:
                content = await resp.read()
                print(f"  ✅ 流式下载成功，大小: {len(content)} bytes")
                
                # 验证是否为有效的zip文件
                import zipfile
                import io
                try:
                    with zipfile.ZipFile(io.BytesIO(content), 'r') as zf:
                        files = zf.namelist()
                        print(f"     ZIP文件包含 {len(files)} 个文件:")
                        for file in files:
                            print(f"       - {file}")
                except Exception as e:
                    print(f"  ❌ ZIP文件验证失败: {e}")
            else:
                print(f"  ❌ 流式下载失败: {resp.status}")
                text = await resp.text()
                print(f"     错误信息: {text}")
        
        # 3. 测试批量删除功能（软删除）
        print("\n🗑️  步骤4: 测试批量删除功能（软删除）...")
        
        delete_request = {
            "log_ids": uploaded_ids[:2],  # 删除前两个
            "force": False  # 软删除
        }
        
        async with session.post(f"{BASE_URL}/batch/delete", 
                               json=delete_request) as resp:
            if resp.status == 200:
                result = await resp.json()
                print("  ✅ 批量删除成功")
                print(f"     删除数量: {result['data']['deleted_count']}")
                print(f"     失败数量: {result['data']['failed_count']}")
                if result['data']['failed_logs']:
                    print("     失败详情:")
                    for failed in result['data']['failed_logs']:
                        print(f"       - {failed['log_id']}: {failed['reason']}")
            else:
                print(f"  ❌ 批量删除失败: {resp.status}")
                text = await resp.text()
                print(f"     错误信息: {text}")
        
        # 4. 测试错误处理 - 使用不存在的UUID格式ID
        print("\n🔍 步骤5: 测试错误处理...")
        
        error_request = {
            "log_ids": [str(uuid.uuid4()), str(uuid.uuid4())],  # 使用正确的UUID格式
            "force": False
        }
        
        async with session.post(f"{BASE_URL}/batch/delete", 
                               json=error_request) as resp:
            if resp.status == 200:
                result = await resp.json()
                print("  ✅ 错误处理测试成功")
                print(f"     删除数量: {result['data']['deleted_count']}")
                print(f"     失败数量: {result['data']['failed_count']}")
                print("     失败详情:")
                for failed in result['data']['failed_logs']:
                    print(f"       - {failed['log_id']}: {failed['reason']}")
            else:
                print(f"  ❌ 错误处理测试失败: {resp.status}")
                text = await resp.text()
                print(f"     错误信息: {text}")
        
        # 5. 测试批量删除功能（硬删除）
        print("\n🗑️  步骤6: 测试批量删除功能（硬删除）...")
        
        if len(uploaded_ids) > 2:
            hard_delete_request = {
                "log_ids": uploaded_ids[2:],  # 删除剩余的
                "force": True  # 硬删除
            }
            
            async with session.post(f"{BASE_URL}/batch/delete", 
                                   json=hard_delete_request) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    print("  ✅ 硬删除成功")
                    print(f"     删除数量: {result['data']['deleted_count']}")
                    print(f"     失败数量: {result['data']['failed_count']}")
                else:
                    print(f"  ❌ 硬删除失败: {resp.status}")
                    text = await resp.text()
                    print(f"     错误信息: {text}")
        
        print("\n🎉 批量操作功能测试完成！")

async def test_performance():
    """测试性能 - 大批量操作"""
    print("\n⚡ 性能测试...")
    
    async with aiohttp.ClientSession() as session:
        # 测试大量UUID的批量删除请求
        large_request = {
            "log_ids": [str(uuid.uuid4()) for i in range(50)],  # 使用正确的UUID格式
            "force": False
        }
        
        import time
        start_time = time.time()
        
        async with session.post(f"{BASE_URL}/batch/delete", 
                               json=large_request) as resp:
            end_time = time.time()
            
            if resp.status == 200:
                result = await resp.json()
                print(f"  ✅ 大批量删除测试完成")
                print(f"     处理时间: {end_time - start_time:.2f}秒")
                print(f"     失败数量: {result['data']['failed_count']}")
            else:
                print(f"  ❌ 大批量删除测试失败: {resp.status}")
                text = await resp.text()
                print(f"     错误信息: {text}")

if __name__ == "__main__":
    print("🧪 T08批量操作功能测试")
    print("=" * 50)
    
    try:
        asyncio.run(test_batch_operations())
        asyncio.run(test_performance())
    except KeyboardInterrupt:
        print("\n⏹️  测试被用户中断")
    except Exception as e:
        print(f"\n❌ 测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()