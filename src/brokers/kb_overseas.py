"""KB증권 증권계좌거래내역 Excel (해외주식) 파서."""

from __future__ import annotations

import re
from io import BytesIO
from typing import Any

import pandas as pd

from src.models import coerce_fx_rate


def _num(value: object) -> float:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return 0.0
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value).strip().replace(",", "").replace(" ", "")
    if not text or text.lower() in {"nan", "none", "-", "."}:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def _text(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none"}:
        return ""
    return text


def _to_date(value: object) -> str:
    text = _text(value).replace(".", "-").replace("/", "-")
    digits = re.sub(r"[^\d]", "", text)
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return text[:10]


def _is_header_pair(row0: list[object], row1: list[object]) -> bool:
    joined = " ".join(_text(x) for x in row0 + row1)
    return "거래일자" in joined and "거래종류" in joined and "종목명" in joined


# 엑셀 종목명이 잘리므로 알려진 약칭 → 티커
_NAME_TICKERS: list[tuple[str, str, str]] = [
    ("NEOS NASDAQ 100 HIGH", "QQQI", "NEOS Nasdaq-100 High Income ETF"),
    ("INVESCO NASDAQ 100", "QQQM", "Invesco NASDAQ 100 ETF"),
    ("JP MORGAN NASDAQ EQU", "JEPQ", "JPMorgan Nasdaq Equity Premium Income ETF"),
    ("JPMORGAN EQUITY PREMIUM", "JEPI", "JPMorgan Equity Premium Income ETF"),
    ("SCHWAB US DIVIDEND", "SCHD", "Schwab US Dividend Equity ETF"),
]


def resolve_ticker(name: str) -> tuple[str, str]:
    """잘린 종목명 → (종목코드, 표시명). 모르면 이름 기반 코드."""
    raw = (name or "").strip()
    if not raw:
        return "", ""
    key = re.sub(r"\s+", " ", raw).upper()
    for prefix, ticker, full in _NAME_TICKERS:
        if key.startswith(prefix) or prefix in key:
            return ticker, full
    slug = re.sub(r"[^A-Z0-9]", "", key)[:12] or "OVERSEAS"
    return slug, raw


def is_kb_overseas_excel(filename: str = "", df: pd.DataFrame | None = None) -> bool:
    fname = (filename or "").lower()
    if "kb" in fname or "kb증권" in (filename or "") or "증권계좌거래" in (filename or ""):
        return True
    if df is None or df.empty or df.shape[1] < 8:
        return False
    head = " ".join(str(c) for c in list(df.iloc[0]) + list(df.iloc[1] if len(df) > 1 else []))
    return "거래종류" in head and "국외수수료" in head and "환율" in head


def parse_kb_overseas_excel(file_bytes: bytes, filename: str = "") -> dict[str, Any]:
    """KB증권 증권계좌거래내역(2행 1건) → 해외주식 미리보기 행."""
    notes: list[str] = []
    try:
        raw = pd.read_excel(BytesIO(file_bytes), header=None)
    except Exception as exc:  # noqa: BLE001
        return {"rows": [], "notes": [f"엑셀 읽기 실패: {exc}"], "source": "kb-overseas-xlsx"}

    if raw is None or raw.empty:
        return {"rows": [], "notes": ["파일이 비어 있습니다."], "source": "kb-overseas-xlsx"}

    start = 0
    for i in range(min(6, len(raw) - 1)):
        if _is_header_pair(list(raw.iloc[i]), list(raw.iloc[i + 1])):
            start = i + 2
            break
    else:
        notes.append("헤더(거래일자·거래종류·종목명)를 찾지 못했습니다. 2행부터 읽습니다.")
        start = 2

    pairs: list[tuple[pd.Series, pd.Series]] = []
    i = start
    while i < len(raw):
        r1 = raw.iloc[i]
        date_txt = _text(r1.iloc[0]) if len(r1) else ""
        kind = _text(r1.iloc[1]) if len(r1) > 1 else ""
        if re.match(r"^\d{4}", date_txt) and kind:
            r2 = raw.iloc[i + 1] if i + 1 < len(raw) else pd.Series(dtype=object)
            pairs.append((r1, r2))
            i += 2
            continue
        i += 1

    rows: list[dict[str, Any]] = []
    skipped = 0

    def _pair_fields(r1: pd.Series, r2: pd.Series) -> dict[str, Any]:
        name = _text(r2.iloc[1] if len(r2) > 1 else "")
        ticker, full_name = resolve_ticker(name)
        ccy = _text(r1.iloc[11] if len(r1) > 11 else "") or "USD"
        if ccy.upper() in {"NAN", ""}:
            ccy = "USD"
        return {
            "date": _to_date(r1.iloc[0]),
            "kind": _text(r1.iloc[1] if len(r1) > 1 else ""),
            "qty": _num(r1.iloc[2] if len(r1) > 2 else 0),
            "price": _num(r2.iloc[2] if len(r2) > 2 else 0),
            "fee_fx": _num(r1.iloc[13] if len(r1) > 13 else 0),
            "fx": coerce_fx_rate(r1.iloc[12] if len(r1) > 12 else 0),
            "ccy": ccy.upper(),
            "name": full_name or name,
            "raw_name": name,
            "ticker": ticker,
            "amt_fx": _num(r2.iloc[13] if len(r2) > 13 else 0),
        }

    for idx, (r1, r2) in enumerate(pairs):
        f = _pair_fields(r1, r2)
        kind = f["kind"]

        if kind == "매수" or kind.startswith("매수"):
            if f["qty"] <= 0 or f["price"] <= 0:
                skipped += 1
                continue
            rows.append(
                {
                    "거래일자": f["date"],
                    "거래유형": "해외매수",
                    "종목코드": f["ticker"] or f["raw_name"],
                    "종목명": f["name"],
                    "수량": f["qty"],
                    "외화단가": f["price"],
                    "외화수수료": f["fee_fx"],
                    "외화제세금": 0.0,
                    "통화코드": f["ccy"],
                    "적용환율": f["fx"],
                    "증권사": "KB증권",
                    "메모": f"KB증권 {kind}",
                }
            )
            continue

        if kind == "매도" or kind.startswith("매도"):
            if f["qty"] <= 0 or f["price"] <= 0:
                skipped += 1
                continue
            rows.append(
                {
                    "거래일자": f["date"],
                    "거래유형": "해외매도",
                    "종목코드": f["ticker"] or f["raw_name"],
                    "종목명": f["name"],
                    "수량": f["qty"],
                    "외화단가": f["price"],
                    "외화수수료": f["fee_fx"],
                    "외화제세금": 0.0,
                    "통화코드": f["ccy"],
                    "적용환율": f["fx"],
                    "증권사": "KB증권",
                    "메모": f"KB증권 {kind}",
                }
            )
            continue

        if "배당금" in kind or "원천세" in kind:
            skipped += 1
            continue

        skipped += 1

    zero_fx = sum(1 for r in rows if float(r.get("적용환율") or 0) <= 0)
    notes.append(
        f"KB증권 증권계좌거래내역에서 해외 매매 {len(rows)}건을 추출했습니다"
        + (f" ({filename})" if filename else "")
        + f". 배당·입출금·환전 등 {skipped}건은 제외했습니다."
    )
    if zero_fx:
        notes.append(
            f"적용환율이 비어 0으로 둔 행 {zero_fx}건 — "
            "매수/매도 행에 환율이 없으면 추정하지 않습니다. 미리보기에서 직접 입력하세요."
        )
    return {"rows": rows, "notes": notes, "source": "kb-overseas-xlsx"}
