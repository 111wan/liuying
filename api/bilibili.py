"""Keep Bilibili's standard CDN alternatives before yt-dlp discards them."""

from yt_dlp.extractor.bilibili import BiliBiliIE

from .errors import AppError
from .security import safe_url


def prefer_standard_cdn(value):
    """Copy play-info, choosing only upstream URLs accepted by our network policy.

    Bilibili may put a PCDN address on port 4483/8082 first and a standard
    HTTPS CDN in backupUrl. yt-dlp otherwise keeps only the first address.
    Never rewrite hosts, ports, paths, or the signed query of a media URL.
    """
    if isinstance(value, list):
        return [prefer_standard_cdn(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: prefer_standard_cdn(item) for key, item in value.items()}
    primary_keys = [key for key in ("baseUrl", "base_url", "url") if key in value]
    if not primary_keys:
        return result
    candidates = [value[key] for key in primary_keys]
    for key in ("backupUrl", "backup_url"):
        backups = value.get(key) or []
        candidates.extend(backups if isinstance(backups, list) else [backups])
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        try:
            safe_url(candidate)
        except AppError:
            continue
        for key in primary_keys:
            result[key] = candidate
        break
    return result


class BiliBiliCDNIE(BiliBiliIE):
    @classmethod
    def ie_key(cls):
        # Replace the existing extractor, including redirects with its explicit key.
        return BiliBiliIE.ie_key()

    def extract_formats(self, play_info):
        upstream_formats = super().extract_formats(prefer_standard_cdn(play_info))
        if not upstream_formats:
            # Keep yt-dlp's login/paid-content errors and legacy format fallback.
            return []
        formats = []
        for fmt in upstream_formats:
            url = fmt.get("url")
            if not isinstance(url, str):
                continue
            try:
                safe_url(url)
            except AppError:
                continue
            formats.append(fmt)
        if not formats:
            raise AppError(
                "UNSUPPORTED_FORMAT", "B站暂未返回可用的标准视频下载地址，请稍后重新解析。", 422, True
            )
        return formats
