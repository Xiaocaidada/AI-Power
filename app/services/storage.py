import hashlib
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile
from uuid6 import uuid7

from app.services.parsing import detect_mime


class UploadTooLarge(Exception):
    pass


class EmptyUpload(Exception):
    pass


@dataclass(frozen=True)
class SavedUpload:
    path: Path
    storage_name: str
    size_bytes: int
    content_hash: str
    mime: str


async def save_upload(upload: UploadFile, upload_dir: str, max_bytes: int) -> SavedUpload:
    filename = upload.filename or ""
    mime = detect_mime(filename, upload.content_type)
    suffix = Path(filename).suffix.lower()

    directory = Path(upload_dir)
    directory.mkdir(parents=True, exist_ok=True)
    storage_name = f"{uuid7()}{suffix}"
    destination = directory / storage_name
    hasher = hashlib.sha256()
    size = 0

    try:
        with destination.open("wb") as output:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise UploadTooLarge
                hasher.update(chunk)
                output.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise

    if size == 0:
        destination.unlink(missing_ok=True)
        raise EmptyUpload

    return SavedUpload(
        path=destination,
        storage_name=storage_name,
        size_bytes=size,
        content_hash=hasher.hexdigest(),
        mime=mime,
    )
