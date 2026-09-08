"""해외주식 엑셀 범용 파서 (메리츠 등 컬럼형 거래내역)."""

from __future__ import annotations

from io import BytesIO
from typing import Any

import pandas as pd

from src.brokers.base import clean_number, find_col
from src.models import coerce_fx_rate, normalize_currency, normalize_side


DATE_CANDS = ["거래일자", "체결일", "거래일", "매매일자", "일자", "날짜", "주문일"]
CODE_CANDS = ["종목코드", "단축코드", "종목번호", "티커", "Ticker", "Symbol"]
NAME_CANDS = ["종목명", "종목", "종목이름", "한글종목명"]
SIDE_CANDS = ["거래유형", "매매구분", "주문구분", "거래구분", "구분", "매수매도"]
QTY_CANDS = ["체결수량", "거래수량", "수량", "주문수량"]
PRICE_FX_CANDS = ["외화단가", "외화가격", "체결단가", "체결가", "단가", "가격"]
FEE_FX_CANDS = ["외화수수료", "수수료", "제비용"]
TAX_FX_CANDS = ["외화제세금", "제세금", "세금", "거래세"]
FX_CANDS = ["적용환율", "적용 환율", "환율", "매매환율"]
CCY_CANDS = ["통화코드", "통화", "화폐"]
BROKER_CANDS = ["증권사", "증권회사"]


def _guess_broker(filename: str, headers: str) -> str:
    blob = f"{filename} {headers}"
    low = blob.lower()
    if "메리츠" in blob or "meritz" in low:
        return "메리츠증권"
    if "kb증권" in blob or "kb " in low or "증권계좌거래" in blob:
        return "KB증권"
    if "미래에셋" in blob or "mirae" in low:
        return "미래에셋증권"
    return "해외주식"


def _read_candidates(file_bytes: bytes) -> list[pd.DataFrame]:
    frames: list[pd.DataFrame] = []
    for header in range(0, 12):
        try:
            df = pd.read_excel(BytesIO(file_bytes), header=header)
        except Exception:  # noqa: BLE001
            continue
        if df is None or df.empty or df.shape[1] < 4:
            continue
        frames.append(df)
    return frames


def _score_frame(df: pd.DataFrame) -> int:
    hits = 0
    for group in (DATE_CANDS, SIDE_CANDS, QTY_CANDS, PRICE_FX_CANDS):
        if find_col(df, group):
            hits += 1
    if find_col(df, CODE_CANDS) or find_col(df, NAME_CANDS):
        hits += 1
    return hits


def parse_generic_overseas_excel(
    file_bytes: bytes, filename: str = ""
) -> dict[str, Any]:
    """컬럼형 해외주식 엑셀 → 미리보기 행. 메리츠 HTS 거래내역 포함."""
    frames = _read_candidates(file_bytes)
    if not frames:
        return {
            "rows": [],
            "notes": ["엑셀을 읽지 못했습니다."],
            "source": "generic-overseas-xlsx",
        }

    best = max(frames, key=_score_frame)
    if _score_frame(best) < 4:
        return {
            "rows": [],
            "notes": ["거래일자·매매구분·수량·단가 컬럼을 찾지 못했습니다."],
            "source": "generic-overseas-xlsx",
        }

    date_c = find_col(best, DATE_CANDS)
    side_c = find_col(best, SIDE_CANDS)
    qty_c = find_col(best, QTY_CANDS)
    price_c = find_col(best, PRICE_FX_CANDS)
    code_c = find_col(best, CODE_CANDS)
    name_c = find_col(best, NAME_CANDS)
    fee_c = find_col(best, FEE_FX_CANDS)
    tax_c = find_col(best, TAX_FX_CANDS)
    fx_c = find_col(best, FX_CANDS)
    ccy_c = find_col(best, CCY_CANDS)
    broker_c = find_col(best, BROKER_CANDS)
    headers = " ".join(str(c) for c in best.columns)
    broker = ""
    if broker_c is not None:
        broker = str(best.iloc[0][broker_c] or "").strip()
    broker = broker or _guess_broker(filename, headers)

    rows: list[dict[str, Any]] = []
    skipped = 0
    for _, row in best.iterrows():
        try:
            raw_side = row[side_c] if side_c else ""
            if pd.isna(raw_side) or str(raw_side).strip() in {"", "-", "nan"}:
                skipped += 1
                continue
            side = normalize_side(raw_side)
            if side == "DIVIDEND":
                skipped += 1
                continue
            qty = clean_number(row[qty_c] if qty_c else 0)
            price = clean_number(row[price_c] if price_c else 0)
            if qty <= 0 or price <= 0:
                skipped += 1
                continue
            date_raw = row[date_c] if date_c else ""
            trade_date = pd.to_datetime(date_raw, errors="coerce")
            if pd.isna(trade_date):
                skipped += 1
                continue
            code = "" if code_c is None else str(row[code_c] or "").strip()
            if code.lower() in {"nan", "none"}:
                code = ""
            if code.endswith(".0"):
                code = code[:-2]
            name = "" if name_c is None else str(row[name_c] or "").strip()
            if name.lower() in {"nan", "none"}:
                name = ""
            kind = "해외매수" if side == "BUY" else "해외매도"
            rows.append(
                {
                    "거래일자": trade_date.strftime("%Y-%m-%d"),
                    "거래유형": kind,
                    "종목코드": code or name,
                    "종목명": name or code,
                    "수량": qty,
                    "외화단가": price,
                    "외화수수료": clean_number(row[fee_c] if fee_c else 0),
                    "외화제세금": clean_number(row[tax_c] if tax_c else 0),
                    "통화코드": normalize_currency(
                        str(row[ccy_c] or "USD") if ccy_c else "USD"
                    ),
                    "적용환율": coerce_fx_rate(row[fx_c] if fx_c else 0),
                    "증권사": broker,
                    "메모": f"{broker} {kind}",
                }
            )
        except Exception:  # noqa: BLE001
            skipped += 1

    notes = [
        f"{broker} 엑셀에서 해외 매매 {len(rows)}건을 추출했습니다"
        + (f" ({filename})" if filename else "")
        + (f". 제외 {skipped}건." if skipped else ".")
    ]
    if any(float(r.get("적용환율") or 0) <= 0 for r in rows):
        notes.append("환율이 비어 있는 행은 0으로 두었습니다. 미리보기에서 입력하세요.")
    return {"rows": rows, "notes": notes, "source": "generic-overseas-xlsx"}
