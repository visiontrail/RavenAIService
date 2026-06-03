"""Tests that the upload validator emits user-facing errors in the request locale."""

from __future__ import annotations

import io

import pytest
from fastapi import UploadFile

from app.utils.file_upload_validator import t04_file_validator


def _upload(name: str, data: bytes = b"") -> UploadFile:
    return UploadFile(filename=name, file=io.BytesIO(data))


@pytest.mark.asyncio
async def test_no_files_message_localized() -> None:
    ok_zh, msg_zh = await t04_file_validator.validate_upload_files([], "zh")
    ok_en, msg_en = await t04_file_validator.validate_upload_files([], "en")
    assert ok_zh is False and ok_en is False
    assert msg_zh == "没有选择文件"
    assert msg_en == "No file selected"


@pytest.mark.asyncio
async def test_unsafe_filename_message_localized() -> None:
    # An unsupported extension fails the filename-safety check first; both the
    # inner message and the per-file wrapper SHALL be in the request locale.
    _, msg_en = await t04_file_validator.validate_upload_files(
        [_upload("notes.txt", b"hello")], "en"
    )
    assert msg_en.startswith("File 1 (notes.txt):")
    assert "supported formats" in msg_en


@pytest.mark.asyncio
async def test_unsafe_filename_message_defaults_to_zh() -> None:
    _, msg_zh = await t04_file_validator.validate_upload_files(
        [_upload("notes.txt", b"hello")], "zh"
    )
    assert msg_zh.startswith("文件 1 (notes.txt):")
    assert "支持的格式" in msg_zh


@pytest.mark.asyncio
async def test_corrupt_archive_message_localized() -> None:
    # A valid extension with bogus content trips the magic-number check.
    _, msg_en = await t04_file_validator.validate_upload_files(
        [_upload("log.tar.gz", b"hello")], "en"
    )
    assert "Corrupted file" in msg_en
