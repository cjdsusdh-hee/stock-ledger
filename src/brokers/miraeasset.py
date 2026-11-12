"""미래에셋증권 거래/체결내역 파서."""

from __future__ import annotations

import pandas as pd

from .base import (
    BrokerParseResult,
    BrokerParser,
    clean_code,
    clean_number,
    ensure_side,
    find_col,
    parse_trade_date,
    to_standard_frame,
)

# 국내 거래내역(입고/출고) — 체결내역(종목코드·매매구분)과 다른 포맷.
_LEDGER_CODE_COLS = {"종목코드", "종목번호", "단축코드", "종목CD"}
_LEDGER_BUY = "주식매수입고"
_LEDGER_SELL = "주식매도출고"
_LEDGER_MARGIN_SELL = "일반담보융자매도상환출고"
_LEDGER_SKIP = {
    "대금": {"주식매수출금", "주식매도입금", "일반담보융자매도상환입금"},
    "이자": {"예탁담보정기이자", "예탁담보정기이자출금(일반)", "예탁금이용료입금"},
    "배당": {"배당금입금"},
    "이체": {"은행이체대체송금"},
    "현금상환": {"일반담보융자현금상환출금"},
    "계좌대체": {"계좌대체출고"},
}


def _stripped_headers(df: pd.DataFrame) -> set[str]:
    return {str(c).strip() for c in df.columns}


def _exact_col(df: pd.DataFrame, name: str) -> str | None:
    for col in df.columns:
        if str(col).strip() == name:
            return col
    return None


def _cell_text(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "nat"}:
        return ""
    return text


def is_mirae_domestic_ledger(df: pd.DataFrame) -> bool:
    """미래에셋 국내 거래내역 CSV. 종목코드 없이 거래종류·입고/출고로 기록된다."""
    headers = _stripped_headers(df)
    if "거래종류" not in headers or "종목명" not in headers:
        return False
    if "제세금합" not in headers and "유가잔고" not in headers:
        return False
    if headers & _LEDGER_CODE_COLS:
        return False
    return True


def _skip_bucket(kind: str) -> str | None:
    for label, kinds in _LEDGER_SKIP.items():
        if kind in kinds:
            return label
    return None


class MiraeAssetParser(BrokerParser):
    name = "미래에셋증권"
    aliases = ["미래에셋", "mirae", "miraeasset", "주식주문체결"]

    DATE_CANDS = ["거래일", "체결일자", "주문일자", "매매일자", "일자", "기준일"]
    CODE_CANDS = ["종목코드", "종목번호", "단축코드", "종목CD", "코드"]
    NAME_CANDS = ["종목명", "종목", "종목이름"]
    SIDE_CANDS = ["매매구분", "거래구분", "주문구분", "매수매도구분", "구분"]
    QTY_CANDS = ["체결수량", "수량", "거래수량", "주문수량"]
    PRICE_CANDS = ["체결단가", "체결가", "단가", "매매단가", "평균단가"]
    FEE_CANDS = ["수수료", "위탁수수료"]
    TAX_CANDS = ["거래세", "농특세", "제세금", "세금"]
    AMT_CANDS = ["정산금액", "결제금액", "거래대금", "체결금액", "거래금액"]
    ACCT_CANDS = ["계좌번호", "계좌명", "계좌"]

    def score(self, df: pd.DataFrame, filename: str = "") -> float:
        if is_mirae_domestic_ledger(df):
            score = 0.95
            fname = filename.lower()
            if any(a in fname for a in ("mirae", "미래에셋", "미래")):
                score += 0.03
            return min(score, 1.0)

        score = 0.0
        fname = filename.lower()
        if any(a in fname for a in ("mirae", "미래에셋", "미래")):
            score += 0.45
        hits = 0
        for group in (
            self.DATE_CANDS,
            self.CODE_CANDS,
            self.SIDE_CANDS,
            self.QTY_CANDS,
            self.PRICE_CANDS,
        ):
            if find_col(df, group):
                hits += 1
        score += hits * 0.1
        headers = " ".join(str(c) for c in df.columns)
        if "위탁수수료" in headers or "농특세" in headers or "거래대금" in headers:
            score += 0.15
        return min(score, 1.0)

    def parse(self, df: pd.DataFrame, *, default_business: str) -> BrokerParseResult:
        if is_mirae_domestic_ledger(df):
            return self._parse_domestic_ledger(df, default_business=default_business)

        date_c = find_col(df, self.DATE_CANDS)
        code_c = find_col(df, self.CODE_CANDS)
        name_c = find_col(df, self.NAME_CANDS)
        side_c = find_col(df, self.SIDE_CANDS)
        qty_c = find_col(df, self.QTY_CANDS)
        price_c = find_col(df, self.PRICE_CANDS)
        fee_c = find_col(df, self.FEE_CANDS)
        tax_c = find_col(df, self.TAX_CANDS)
        amt_c = find_col(df, self.AMT_CANDS)
        acct_c = find_col(df, self.ACCT_CANDS)

        required = {
            "일자": date_c,
            "종목코드": code_c,
            "거래유형": side_c,
            "수량": qty_c,
            "단가": price_c,
        }
        missing = [k for k, v in required.items() if v is None]
        if missing:
            raise ValueError(f"미래에셋증권 파서: 필수 컬럼 인식 실패 ({', '.join(missing)})")

        rows = []
        notes: list[str] = []
        for _, row in df.iterrows():
            side_raw = row[side_c]
            side_text = str(side_raw)
            if any(tok in side_text for tok in ("취소", "정정", "거부", "조회")):
                continue
            try:
                side = ensure_side(side_raw)
            except ValueError:
                continue

            qty = abs(clean_number(row[qty_c]))
            price = clean_number(row[price_c])
            if qty <= 0:
                continue

            fee = clean_number(row[fee_c]) if fee_c else 0.0
            tax = clean_number(row[tax_c]) if tax_c else 0.0
            total_cost = fee + tax

            if amt_c:
                settlement = abs(clean_number(row[amt_c]))
            else:
                settlement = qty * price + total_cost if side == "매수" else qty * price - total_cost

            code = clean_code(row[code_c])
            name = str(row[name_c]).strip() if name_c else code
            date_val = pd.to_datetime(row[date_c], errors="coerce")
            if pd.isna(date_val):
                notes.append(f"날짜 스킵: {row[date_c]}")
                continue

            biz = default_business
            if acct_c and str(row[acct_c]).strip() not in {"", "nan"}:
                # 계좌정보가 있으면 메모에만 기록 (사업자는 선택값 유지)
                pass

            rows.append(
                {
                    "거래일자": date_val.strftime("%Y-%m-%d"),
                    "사업자": biz,
                    "종목코드": code,
                    "종목명": name,
                    "거래유형": side,
                    "수량": qty,
                    "단가": price,
                    "수수료": total_cost,
                    "정산금액": settlement,
                    "메모": "미래에셋증권"
                    + (
                        f" / 계좌:{row[acct_c]}"
                        if acct_c and str(row[acct_c]).strip() not in {"", "nan"}
                        else ""
                    ),
                }
            )

        out = to_standard_frame(rows)
        return BrokerParseResult(self.name, out, confidence=self.score(df), notes=notes)

    def _parse_domestic_ledger(
        self,
        df: pd.DataFrame,
        *,
        default_business: str,
    ) -> BrokerParseResult:
        date_c = _exact_col(df, "거래일자")
        kind_c = _exact_col(df, "거래종류")
        name_c = _exact_col(df, "종목명")
        qty_c = _exact_col(df, "수량")
        price_c = _exact_col(df, "단가")
        amt_c = _exact_col(df, "거래금액")
        fee_c = _exact_col(df, "수수료")
        tax_c = _exact_col(df, "제세금합")
        bal_c = _exact_col(df, "유가잔고")
        missing = [
            label
            for label, col in (
                ("거래일자", date_c),
                ("거래종류", kind_c),
                ("종목명", name_c),
                ("수량", qty_c),
                ("단가", price_c),
                ("거래금액", amt_c),
            )
            if col is None
        ]
        if missing:
            raise ValueError(
                f"미래에셋 국내 거래내역: 필수 컬럼 인식 실패 ({', '.join(missing)})"
            )

        rows: list[dict] = []
        notes: list[str] = []
        n_buy = 0
        n_sell = 0
        n_margin = 0
        skipped = {label: 0 for label in (*_LEDGER_SKIP, "기타")}
        skipped_incomplete = 0

        for _, row in df.iterrows():
            kind = _cell_text(row[kind_c])
            if not kind:
                continue
            if kind == _LEDGER_BUY:
                side = "매수"
            elif kind in {_LEDGER_SELL, _LEDGER_MARGIN_SELL}:
                side = "매도"
            else:
                bucket = _skip_bucket(kind) or "기타"
                skipped[bucket] += 1
                continue

            qty = abs(clean_number(row[qty_c]))
            price = clean_number(row[price_c])
            name = _cell_text(row[name_c])
            trade_date = parse_trade_date(row[date_c])
            if qty <= 0 or price <= 0 or not name or not trade_date:
                skipped_incomplete += 1
                continue

            fee = clean_number(row[fee_c]) if fee_c else 0.0
            tax = clean_number(row[tax_c]) if tax_c else 0.0
            amount = abs(clean_number(row[amt_c]))
            if side == "매수":
                settlement = amount + fee + tax
                n_buy += 1
            else:
                settlement = amount - fee - tax
                n_sell += 1
                if kind == _LEDGER_MARGIN_SELL:
                    n_margin += 1

            item = {
                "거래일자": trade_date,
                "사업자": default_business,
                "종목코드": "",
                "종목명": name,
                "거래유형": side,
                "수량": qty,
                "단가": price,
                "수수료": fee,
                "제세금": tax,
                "정산금액": settlement,
                "메모": f"미래에셋증권 {kind}",
            }
            if bal_c:
                item["유가금잔"] = clean_number(row[bal_c])
            rows.append(item)

        notes.append(
            f"미래에셋 국내 거래내역: 매수 {n_buy}건, 매도 {n_sell}건"
            f" (담보융자매도상환 {n_margin}건)."
        )
        excluded = [
            f"{label} {count}건" for label, count in skipped.items() if count
        ]
        if excluded:
            notes.append("매매에서 제외: " + ", ".join(excluded) + ".")
        if skipped_incomplete:
            notes.append(
                f"수량·단가·종목·날짜가 없는 체결 {skipped_incomplete}건은 건너뛰었습니다."
            )

        out = to_standard_frame(rows)
        return BrokerParseResult(
            self.name,
            out,
            confidence=self.score(df),
            notes=notes,
        )
