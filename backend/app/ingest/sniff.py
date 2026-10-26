"""Magic-byte media sniffing."""


def sniff_image(data: bytes) -> tuple[str, str] | None:
    """Returns (mime, ext) for accepted raster formats."""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg", "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png", "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif", "gif"
    return None


def sniff_video(data: bytes) -> tuple[str, str] | None:
    if data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand == b"qt  ":
            return "video/quicktime", "mov"
        return "video/mp4", "mp4"
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return "video/webm", "webm"
    return None
