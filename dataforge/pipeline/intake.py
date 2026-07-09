from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from fastapi import UploadFile, HTTPException
from dataforge.models import NormalizedFile

UPLOAD_DIR = Path("storage/uploads")
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".png", ".jpg", ".jpeg", ".csv", ".txt"}
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB

EXPECTED_MIME_PREFIXES = {
    ".pdf": ("application/pdf",),
    ".docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/zip"),
    ".png": ("image/png",),
    ".jpg": ("image/jpeg",),
    ".jpeg": ("image/jpeg",),
    ".csv": ("text/csv", "text/plain", "application/csv"),
    ".txt": ("text/plain",),
}


def _detect_mime(content: bytes) -> str | None:
    try:
        import magic  # python-magic
        return magic.from_buffer(content[:4096], mime=True)
    except Exception:
        return None


def _mime_allowed(extension: str, detected_mime: str | None, declared_mime: str | None) -> bool:
    allowed = EXPECTED_MIME_PREFIXES.get(extension, ())
    actual = detected_mime or declared_mime
    if not actual:
        return True  # development fallback when sniffing is unavailable
    return any(actual.startswith(prefix) for prefix in allowed)


async def intake(file: UploadFile, client_id: str) -> NormalizedFile:
    filename = file.filename or "upload"
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=415, detail=f"Unsupported file type: {extension}")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail=f"File too large. Max size is {MAX_FILE_SIZE // (1024 * 1024)}MB")

    detected_mime = _detect_mime(content)
    if not _mime_allowed(extension, detected_mime, file.content_type):
        raise HTTPException(
            status_code=415,
            detail=f"File content does not match extension {extension}. Detected MIME: {detected_mime or file.content_type}",
        )

    digest = hashlib.sha256(content).hexdigest()
    client_dir = UPLOAD_DIR / client_id
    client_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename).name.replace(" ", "_")
    storage_path = client_dir / f"{digest[:12]}_{safe_name}"
    storage_path.write_bytes(content)

    return NormalizedFile(
        client_id=client_id,
        filename=filename,
        content_type=detected_mime or file.content_type,
        extension=extension,
        size_bytes=len(content),
        storage_path=str(storage_path),
        sha256=digest,
        uploaded_at=datetime.now(timezone.utc),
    )
