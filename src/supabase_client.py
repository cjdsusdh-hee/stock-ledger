"""Supabase 접속 설정."""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from supabase import Client, create_client

_PLACEHOLDER_MARKERS = ("YOUR_PROJECT", "YOUR_SUPABASE", "example.com", "xxx.supabase")
_SUPABASE_HOST_RE = re.compile(r"^[a-z0-9-]+\.supabase\.co$", re.I)


def _read_secrets_file() -> dict[str, Any]:
    path = Path(__file__).resolve().parent.parent / ".streamlit" / "secrets.toml"
    if not path.exists():
        return {}
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover
        return {}
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    block = data.get("supabase") or {}
    return dict(block) if isinstance(block, dict) else {}


def load_supabase_settings() -> tuple[str, str]:
    url = (os.environ.get("SUPABASE_URL") or "").strip()
    key = (
        os.environ.get("SUPABASE_KEY")
        or os.environ.get("SUPABASE_ANON_KEY")
        or ""
    ).strip()
    if not url or not key:
        file_cfg = _read_secrets_file()
        url = url or str(file_cfg.get("url") or "").strip()
        key = key or str(file_cfg.get("key") or "").strip()
    if not url or not key:
        try:
            import streamlit as st

            block = st.secrets.get("supabase", {})
            url = url or str(block.get("url") or "").strip()
            key = key or str(block.get("key") or "").strip()
        except Exception:  # noqa: BLE001
            pass
    return url, key


def normalize_supabase_url(url: str) -> str:
    """Supabase REST URL을 create_client 형식으로 정규화한다."""
    cleaned = url.strip().rstrip("/")
    if cleaned and not cleaned.startswith(("http://", "https://")):
        cleaned = f"https://{cleaned}"
    return cleaned


def validate_supabase_settings(url: str, key: str) -> None:
    """배포 전/실행 시 URL·키 형식을 검사한다."""
    if not url or not key:
        raise RuntimeError(
            "Supabase 설정이 없습니다.\n"
            "로컬: .streamlit/secrets.toml\n"
            "Streamlit Cloud: Manage app → Secrets\n"
            "아래 형식으로 [supabase] url, key 를 넣어 주세요."
        )
    if any(marker.lower() in url.lower() for marker in _PLACEHOLDER_MARKERS):
        raise RuntimeError(
            "Supabase URL이 예시 값(YOUR_PROJECT 등)입니다. "
            "Supabase Dashboard → Project Settings → API 의 Project URL 로 바꿔 주세요."
        )
    if any(marker.lower() in key.lower() for marker in _PLACEHOLDER_MARKERS):
        raise RuntimeError(
            "Supabase key가 예시 값입니다. "
            "Supabase Dashboard → Project Settings → API 의 anon public key 를 넣어 주세요."
        )
    parsed = urlparse(normalize_supabase_url(url))
    host = (parsed.hostname or "").strip()
    if parsed.scheme not in ("http", "https") or not host:
        raise RuntimeError(
            f"Supabase URL 형식이 올바르지 않습니다: {url!r}\n"
            "예: https://abcdefghijklmnop.supabase.co"
        )
    if host in ("localhost", "127.0.0.1") or host.endswith(".local"):
        raise RuntimeError(
            f"Supabase URL이 로컬 주소({host})입니다. "
            "Streamlit Cloud에서는 공개 Supabase Project URL 이 필요합니다."
        )
    if not _SUPABASE_HOST_RE.fullmatch(host):
        raise RuntimeError(
            f"Supabase 호스트가 예상과 다릅니다: {host}\n"
            "Project Settings → API 의 Project URL(…supabase.co)을 그대로 복사했는지 확인하세요."
        )


def is_connect_error(exc: BaseException) -> bool:
    """httpx/httpcore 연결 실패인지 판별한다."""
    name = type(exc).__name__
    if name in ("ConnectError", "ConnectTimeout", "ReadTimeout"):
        return True
    cause = getattr(exc, "__cause__", None)
    if cause is not None and cause is not exc:
        return is_connect_error(cause)
    msg = str(exc).lower()
    return "connecterror" in msg or "connection refused" in msg or "name or service not known" in msg


def format_supabase_error(exc: BaseException) -> RuntimeError:
    """Supabase API 호출 실패를 배포 환경에서 이해하기 쉬운 메시지로 바꾼다."""
    url, _ = load_supabase_settings()
    host = urlparse(normalize_supabase_url(url)).hostname or url
    if is_connect_error(exc):
        return RuntimeError(
            f"Supabase 서버({host})에 연결할 수 없습니다.\n\n"
            "아래를 순서대로 확인해 주세요.\n"
            "1. Streamlit Cloud → Manage app → Secrets 에 [supabase] url, key 가 있는지\n"
            "2. url 이 https://프로젝트ID.supabase.co 형식인지(끝 / 없음, REST URL 그대로)\n"
            "3. Supabase Dashboard 에서 프로젝트가 Paused(일시중지) 상태가 아닌지 → Restore project\n"
            "4. Supabase Dashboard → Project Settings → API 의 Project URL / anon key 를 다시 복사했는지\n\n"
            f"현재 설정 URL: {normalize_supabase_url(url)}"
        )
    text = str(exc).strip()
    lowered = text.lower()
    if "invalid api key" in lowered or "jwt" in lowered:
        return RuntimeError(
            "Supabase API key 가 올바르지 않습니다.\n"
            "Project Settings → API → anon public key 를 Secrets 의 key 에 넣어 주세요."
        )
    return RuntimeError(f"Supabase 요청 실패: {text}")


@lru_cache(maxsize=1)
def get_supabase_client() -> Client:
    url, key = load_supabase_settings()
    url = normalize_supabase_url(url)
    validate_supabase_settings(url, key)
    return create_client(url, key)
