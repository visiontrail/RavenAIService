"""对话 multipart 传输：标准文件上传及旧版 Base64 字段兼容。"""

import base64

from fastapi import HTTPException, Request, UploadFile, params
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.i18n.deps import LOCALE_HEADER, resolve_locale
from app.models.chat import (
    ImageAttachment,
    ImageValidationError,
    image_limits,
    parse_images_form,
    validate_image,
    validate_image_count,
    validate_images,
)

MIB = 1024 * 1024


def multipart_field_limit() -> int:
    """兼容全部已允许图片的 Base64 编码，并为 JSON 和历史消息预留余量。"""
    count, image_bytes = image_limits()
    return max(16 * MIB, count * (4 * ((image_bytes + 2) // 3)) + MIB)


class ChatUploadRoute(APIRoute):
    """仅调整对话表单解析；保留 FastAPI 文件生命周期和原生 SSE 传输。"""

    def get_route_handler(self):
        original = super().get_route_handler()
        if not self.body_field or not isinstance(self.body_field.field_info, params.Form):
            return original

        async def handle(request: Request):
            if request.headers.get("content-type", "").lower().startswith("multipart/form-data"):
                limit = multipart_field_limit()
                try:
                    # FastAPI 随后复用同一 Request 缓存的 FormData，并负责关闭文件。
                    await request.form(max_part_size=limit)
                except StarletteHTTPException as exc:
                    if exc.status_code != 400:
                        raise
                    locale = resolve_locale(
                        header_locale=request.headers.get(LOCALE_HEADER),
                        accept_language=request.headers.get("Accept-Language"),
                    )
                    if str(exc.detail).startswith("Part exceeded maximum size"):
                        message = (
                            f"本次提交的文字、历史记录或旧版图片字段超过 {limit / MIB:g} MiB 上限。"
                            "请刷新页面以使用文件方式上传图片，或缩短消息、开启新会话后重试。"
                            if locale == "zh" else
                            f"A message, history or legacy image field exceeds the {limit / MIB:g} MiB limit. "
                            "Refresh the page to upload images as files, shorten the message, or start a new conversation."
                        )
                        raise HTTPException(status_code=413, detail={
                            "reason": "multipart_field_too_large",
                            "message": message,
                            "max_bytes": limit,
                        }) from exc
                    # 不将解析器错误伪装成网络失败；不回显请求体或内部异常。
                    raise HTTPException(status_code=400, detail={
                        "reason": "invalid_multipart",
                        "message": (
                            "上传请求格式无效或附件字段过多，请减少附件或刷新页面后重新上传。"
                            if locale == "zh" else
                            "The upload is malformed or contains too many fields. Reduce attachments or refresh and upload again."
                        ),
                    }) from exc
            return await original(request)

        return handle


async def parse_image_uploads(
    legacy_images: str | None,
    image_files: list[UploadFile] | None,
    *,
    locale: str,
) -> list[ImageAttachment]:
    """有界读取标准文件；兼容旧字段，混合输入也遵守同一数量和大小设置。"""
    images = parse_images_form(legacy_images, locale=locale)
    uploads = image_files or []
    validate_image_count(len(images) + len(uploads), locale=locale)
    validate_images(images, locale=locale)
    _, max_bytes = image_limits()
    for upload in uploads:
        index = len(images) + 1
        media_type = (upload.content_type or "").strip().lower()
        # UploadFile.size 来自解析器实际统计，优先在读取前拒绝大文件。
        validate_image(media_type, upload.size or 0, index=index, locale=locale)
        content = await upload.read(max_bytes + 1)
        validate_image(media_type, len(content), index=index, locale=locale)
        if not content:
            raise ImageValidationError(
                "invalid_images_payload",
                f"第 {index} 张图片为空，请重新选择图片。" if locale == "zh" else
                f"Image {index} is empty. Select the image again.",
            )
        images.append(ImageAttachment(media_type=media_type, data=base64.b64encode(content).decode("ascii")))
    return images
