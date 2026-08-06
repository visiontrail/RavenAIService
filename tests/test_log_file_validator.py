"""通用日志上传文件名校验测试。"""

from __future__ import annotations

import pytest

from app.exceptions import ValidationError
from app.utils.validation import file_validator


@pytest.mark.parametrize(
    "name",
    ["鹏城核心网.rar", "银河核心网.rar", "测试日志 (1).tar.gz"],
)
def test_localized_filename_is_accepted(name: str) -> None:
    file_validator._validate_filename(name)


@pytest.mark.parametrize(
    "name",
    ["../鹏城核心网.rar", "目录/日志.rar", "日志\t副本.rar", "日志💥.rar"],
)
def test_localized_filename_still_rejects_unsafe_names(name: str) -> None:
    with pytest.raises(ValidationError):
        file_validator._validate_filename(name)
