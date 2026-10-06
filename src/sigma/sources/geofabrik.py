from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

from ..config import (
    DEFAULT_DOWNLOAD_USER_AGENT,
    DEFAULT_GEOFABRIK_MAX_AGE_DAYS,
    DEFAULT_GEOFABRIK_PAGE_URL,
)

ProgressCallback = Callable[[str], None]

_DATED_PBF_RE = re.compile(r"philippines-(\d{6})\.osm\.pbf")


def _emit(progress: ProgressCallback | None, message: str) -> None:
    if progress is not None:
        progress(message)


def _page_url() -> str:
    return (
        os.getenv("SIGMA_GEOFABRIK_PAGE_URL", DEFAULT_GEOFABRIK_PAGE_URL).strip()
        or DEFAULT_GEOFABRIK_PAGE_URL
    )


def _user_agent() -> str:
    return (
        os.getenv("SIGMA_DOWNLOAD_USER_AGENT", DEFAULT_DOWNLOAD_USER_AGENT).strip()
        or DEFAULT_DOWNLOAD_USER_AGENT
    )


def _parse_iso_date(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _version_date(version: str | None) -> datetime | None:
    if not version:
        return None
    try:
        return datetime.strptime(version, "%y%m%d").replace(tzinfo=UTC)
    except ValueError:
        return None


def _read_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _latest_from_philippines_page(html: str) -> str:
    versions = sorted(set(_DATED_PBF_RE.findall(html)))
    if not versions:
        raise RuntimeError(
            "Could not find a dated Philippines .osm.pbf link on the "
            "Geofabrik Philippines download page."
        )
    return versions[-1]


def _is_geofabrik_https(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold()
    return parsed.scheme == "https" and (
        host == "geofabrik.de" or host.endswith(".geofabrik.de")
    )


@dataclass(frozen=True, slots=True)
class RemoteInfo:
    version: str
    source_date: datetime
    url: str
    content_length: int | None = None


@dataclass(frozen=True, slots=True)
class GeofabrikStatus:
    pbf_path: Path
    exists: bool
    cache_age_days: float | None
    source_gap_days: float | None
    local_source_modified: datetime | None
    remote_source_modified: datetime | None
    remote_size_bytes: int | None
    stale: bool
    max_age_days: float
    remote_checked: bool

    @property
    def age_description(self) -> str:
        if self.source_gap_days is not None:
            return f"{self.source_gap_days:.1f} day(s) behind Geofabrik"
        if self.cache_age_days is not None:
            return f"{self.cache_age_days:.1f} day(s) since download"
        return "age unknown"


def paths(cache_root: Path) -> tuple[Path, Path]:
    directory = cache_root / "geofabrik"
    return (
        directory / "philippines-latest.osm.pbf",
        directory / "philippines-latest.meta.json",
    )


def _discover_latest(session: requests.Session) -> RemoteInfo:
    page_url = _page_url()
    session.max_redirects = 5

    try:
        response = session.get(
            page_url,
            timeout=(15, 60),
            headers={"User-Agent": _user_agent()},
            allow_redirects=True,
        )
        response.raise_for_status()
    except requests.TooManyRedirects as exc:
        raise RuntimeError(f"Geofabrik download-page redirect loop: {exc}") from exc
    except requests.RequestException as exc:
        raise RuntimeError(
            f"Could not read the Geofabrik Philippines page: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    if not _is_geofabrik_https(response.url):
        raise RuntimeError(
            f"Geofabrik Philippines page redirected to an unexpected URL: {response.url}"
        )

    version = _latest_from_philippines_page(response.text)
    source_date = _version_date(version)
    if source_date is None:
        raise RuntimeError(f"Invalid Geofabrik Philippines version date: {version}")

    filename = f"philippines-{version}.osm.pbf"
    file_url = urljoin(response.url, filename)

    content_length: int | None = None
    try:
        head = session.head(
            file_url,
            timeout=(15, 30),
            headers={"User-Agent": _user_agent()},
            allow_redirects=False,
        )
        if head.status_code == 200:
            size_text = head.headers.get("Content-Length")
            if size_text:
                content_length = int(size_text)
    except (requests.RequestException, ValueError):
        content_length = None

    return RemoteInfo(
        version=version,
        source_date=source_date,
        url=file_url,
        content_length=content_length,
    )


def probe_remote(*, timeout: float = 20.0) -> RemoteInfo | None:
    del timeout
    try:
        with requests.Session() as session:
            return _discover_latest(session)
    except RuntimeError:
        return None


def cache_status(
    cache_root: Path,
    *,
    max_age_days: float = DEFAULT_GEOFABRIK_MAX_AGE_DAYS,
    check_remote: bool = True,
) -> GeofabrikStatus:
    pbf_path, meta_path = paths(cache_root)
    now = datetime.now(UTC)
    remote = probe_remote() if check_remote else None

    if not pbf_path.exists():
        return GeofabrikStatus(
            pbf_path=pbf_path,
            exists=False,
            cache_age_days=None,
            source_gap_days=None,
            local_source_modified=None,
            remote_source_modified=remote.source_date if remote else None,
            remote_size_bytes=remote.content_length if remote else None,
            stale=True,
            max_age_days=max_age_days,
            remote_checked=remote is not None,
        )

    meta = _read_json(meta_path)
    downloaded_at = _parse_iso_date(meta.get("downloaded_at"))
    if downloaded_at is None:
        downloaded_at = datetime.fromtimestamp(pbf_path.stat().st_mtime, tz=UTC)
    cache_age_days = max(0.0, (now - downloaded_at).total_seconds() / 86400.0)

    local_source_modified = (
        _version_date(str(meta.get("source_version") or ""))
        or _parse_iso_date(meta.get("source_date"))
        or _parse_iso_date(meta.get("source_last_modified"))
    )

    source_gap_days: float | None = None
    if remote and local_source_modified:
        source_gap_days = max(
            0.0,
            (remote.source_date - local_source_modified).total_seconds() / 86400.0,
        )

    stale_metric = source_gap_days if source_gap_days is not None else cache_age_days
    return GeofabrikStatus(
        pbf_path=pbf_path,
        exists=True,
        cache_age_days=cache_age_days,
        source_gap_days=source_gap_days,
        local_source_modified=local_source_modified,
        remote_source_modified=remote.source_date if remote else None,
        remote_size_bytes=remote.content_length if remote else None,
        stale=stale_metric >= max_age_days,
        max_age_days=max_age_days,
        remote_checked=remote is not None,
    )


def _open_stream(
    session: requests.Session,
    url: str,
    *,
    max_redirects: int = 5,
    extra_headers: dict[str, str] | None = None,
) -> tuple[requests.Response, str]:
    """Follow a small, explicit Geofabrik-only redirect chain."""
    current = url
    visited: list[str] = []
    headers = {"User-Agent": _user_agent()}
    if extra_headers:
        headers.update(extra_headers)

    for _ in range(max_redirects + 1):
        if current in visited:
            chain = " -> ".join(visited + [current])
            raise RuntimeError(f"Geofabrik redirect loop detected: {chain}")
        visited.append(current)

        try:
            response = session.get(
                current,
                stream=True,
                timeout=(30, 900),
                headers=headers,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise RuntimeError(
                f"Geofabrik download request failed: {type(exc).__name__}: {exc}"
            ) from exc

        if response.is_redirect or response.is_permanent_redirect:
            location = response.headers.get("Location")
            response.close()
            if not location:
                raise RuntimeError("Geofabrik returned a redirect without Location.")
            target = urljoin(current, location)
            if not _is_geofabrik_https(target):
                raise RuntimeError(
                    f"Geofabrik redirected to an unexpected URL: {target}"
                )
            current = target
            continue

        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            response.close()
            raise RuntimeError(
                f"Geofabrik download failed: {type(exc).__name__}: {exc}"
            ) from exc
        return response, current

    chain = " -> ".join(visited)
    raise RuntimeError(
        f"Geofabrik exceeded {max_redirects} explicit redirects: {chain}"
    )


def _expected_md5(url: str, *, session: requests.Session) -> str | None:
    try:
        response, _ = _open_stream(session, url + ".md5", max_redirects=3)
        with response:
            text = response.content.decode("utf-8", errors="replace")
    except RuntimeError:
        return None

    token = text.strip().split()
    if not token:
        return None
    digest = token[0].lower()
    if len(digest) == 32 and all(ch in "0123456789abcdef" for ch in digest):
        return digest
    return None


def _hash_existing(path: Path, digest) -> int:
    total = 0
    if not path.exists():
        return 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(8 * 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            total += len(chunk)
    return total


def _content_total(response: requests.Response, fallback: int | None) -> int | None:
    content_range = response.headers.get("Content-Range", "")
    if "/" in content_range:
        total_text = content_range.rsplit("/", 1)[-1].strip()
        if total_text.isdigit():
            return int(total_text)

    size_text = response.headers.get("Content-Length")
    if size_text and size_text.isdigit():
        size = int(size_text)
        if response.status_code == 206:
            return None if fallback is None else fallback
        return size
    return fallback


def download(
    cache_root: Path,
    *,
    progress: ProgressCallback | None = None,
) -> Path:
    pbf_path, meta_path = paths(cache_root)
    pbf_path.parent.mkdir(parents=True, exist_ok=True)

    with requests.Session() as session:
        remote = _discover_latest(session)
        url = remote.url
        partial = pbf_path.parent / f"philippines-{remote.version}.osm.pbf.part"

        _emit(
            progress,
            f"Geofabrik: newest Philippines extract is "
            f"philippines-{remote.version}.osm.pbf",
        )

        expected_md5 = _expected_md5(url, session=session)
        digest = hashlib.md5(usedforsecurity=False)
        resume_from = _hash_existing(partial, digest)

        if resume_from:
            _emit(
                progress,
                f"Geofabrik: resuming partial download at "
                f"{resume_from / 2**20:,.0f} MiB",
            )
            response, final_url = _open_stream(
                session,
                url,
                extra_headers={"Range": f"bytes={resume_from}-"},
            )

            if response.status_code == 206:
                file_mode = "ab"
                written = resume_from
            else:
                # Server ignored Range. Restart safely rather than append duplicate bytes.
                response.close()
                _emit(
                    progress,
                    "Geofabrik: server did not honor resume request; restarting download",
                )
                partial.unlink(missing_ok=True)
                digest = hashlib.md5(usedforsecurity=False)
                response, final_url = _open_stream(session, url)
                file_mode = "wb"
                written = 0
        else:
            _emit(progress, f"Geofabrik: downloading {url}")
            response, final_url = _open_stream(session, url)
            file_mode = "wb"
            written = 0

        with response:
            total = _content_total(response, remote.content_length)
            next_report = ((written // (64 * 1024 * 1024)) + 1) * (64 * 1024 * 1024)

            with partial.open(file_mode) as handle:
                for chunk in response.iter_content(chunk_size=8 * 1024 * 1024):
                    if not chunk:
                        continue
                    handle.write(chunk)
                    digest.update(chunk)
                    written += len(chunk)

                    if written >= next_report:
                        if total:
                            pct = 100.0 * written / total
                            _emit(
                                progress,
                                f"Geofabrik: {written / 2**20:,.0f} MiB / "
                                f"{total / 2**20:,.0f} MiB ({pct:.1f}%)",
                            )
                        else:
                            _emit(
                                progress,
                                f"Geofabrik: {written / 2**20:,.0f} MiB downloaded",
                            )
                        next_report += 64 * 1024 * 1024

        actual_md5 = digest.hexdigest().lower()
        if expected_md5 and actual_md5 != expected_md5:
            partial.unlink(missing_ok=True)
            raise RuntimeError(
                "Geofabrik download checksum mismatch. The partial file was deleted "
                "because it cannot be resumed safely."
            )

        partial.replace(pbf_path)
        metadata = {
            "source_version": remote.version,
            "source_date": remote.source_date.isoformat(),
            "source_url": url,
            "final_url": final_url,
            "downloaded_at": datetime.now(UTC).isoformat(),
            "content_length": written,
            "md5": actual_md5,
            "md5_verified": bool(expected_md5),
        }

        tmp_meta = meta_path.with_suffix(meta_path.suffix + ".tmp")
        tmp_meta.write_text(
            json.dumps(metadata, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp_meta.replace(meta_path)

    # A new national extract invalidates node locations from the previous PBF.
    node_cache = pbf_path.parent / "node-locations.cache"
    if node_cache.exists():
        node_cache.unlink()

    _emit(
        progress,
        f"Geofabrik: download complete — {pbf_path} "
        f"({pbf_path.stat().st_size / 2**20:,.0f} MiB)",
    )
    return pbf_path


def ensure(
    cache_root: Path,
    *,
    refresh: bool = False,
    progress: ProgressCallback | None = None,
) -> Path:
    pbf_path, _ = paths(cache_root)
    if refresh or not pbf_path.exists():
        return download(cache_root, progress=progress)

    _emit(
        progress,
        f"Geofabrik: using cached Philippines PBF — "
        f"{pbf_path.stat().st_size / 2**20:,.0f} MiB",
    )
    return pbf_path
