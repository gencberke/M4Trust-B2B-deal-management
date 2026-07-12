"""Bounded streaming reads for multipart uploads."""

from __future__ import annotations

from fastapi import UploadFile

_READ_CHUNK_BYTES = 1024 * 1024


class UploadTooLargeError(ValueError):
    """The multipart body exceeded the configured content limit."""


class EmptyUploadError(ValueError):
    """The uploaded file contained no bytes."""


async def read_upload_bounded(file: UploadFile, *, max_bytes: int) -> bytes:
    """Read a multipart upload without ever calling unbounded ``read()``."""

    if max_bytes <= 0:
        raise UploadTooLargeError("Upload limiti pozitif olmalıdır.")
    content = bytearray()
    while True:
        chunk = await file.read(min(_READ_CHUNK_BYTES, max_bytes - len(content) + 1))
        if not chunk:
            break
        content.extend(chunk)
        if len(content) > max_bytes:
            raise UploadTooLargeError("Upload yapılandırılmış boyut sınırını aştı.")
    if not content:
        raise EmptyUploadError("Boş dosya yüklenemez.")
    return bytes(content)
