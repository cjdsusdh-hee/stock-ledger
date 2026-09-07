"""Supabase 접속 설정."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from supabase import Client, create_client


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


@lru_cache(maxsize=1)
def get_supabase_client() -> Client:
    url, key = load_supabase_settings()
    if not url or not key:
        raise RuntimeError(
            "Supabase 설정이 없습니다. .streamlit/secrets.toml 의 "
            "[supabase] url, key 를 확인하세요."
        )
    return create_client(url, key)
