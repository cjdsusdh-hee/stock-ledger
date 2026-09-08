"""메리츠 원본 vs 기준 전표(2026-08-04) 대조."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.brokers.generic_overseas import parse_generic_overseas_excel
from src.models import Trade
from src.voucher_export import (
    _fee_summary,
    _trade_summary_buy,
    _trade_summary_sell,
    attach_fx_gross_memo,
    build_overseas_remark_amount,
)

ROOT = Path(__file__).resolve().parents[1]


def _find(pred):
    for f in ROOT.iterdir():
        if pred(f):
            return f
    raise FileNotFoundError(pred)


def main() -> None:
    meritz = _find(lambda f: f.suffix.lower() == ".xls" and "메리츠" in f.name)
    voucher = _find(
        lambda f: f.suffix.lower() == ".xlsx"
        and "20260801" in f.name
        and not f.name.startswith("~$")
    )
    print("원본:", meritz.name)
    print("기준전표:", voucher.name)

    raw = pd.read_excel(meritz, header=0)
    raw.columns = [str(c).replace("\n", "/").replace("\r", "") for c in raw.columns]
    print("원본 컬럼:", list(raw.columns))

    date_c = next(c for c in raw.columns if "거래일자" in c)
    side_c = next(c for c in raw.columns if "거래구분" in c)
    settle_c = next(c for c in raw.columns if "거래/정산" in c.replace(" ", "") or "거래정산" in c.replace("/", "").replace(" ", ""))
    qty_c = next(c for c in raw.columns if "거래수량" in c or c == "수량")
    px_c = next(c for c in raw.columns if "거래단가(외화)" in c or "단가(외화)" in c)
    code_c = next(c for c in raw.columns if "종목코드" in c)
    name_c = next(c for c in raw.columns if "종목명" in c)
    fx_c = next((c for c in raw.columns if "적용환율" in c or c == "환율"), None)
    fee_c = next((c for c in raw.columns if "수수료(외화)" in c), None)
    tax_c = next((c for c in raw.columns if "제세금(외화)" in c), None)

    def ymd(v) -> str:
        s = "".join(ch for ch in str(v) if ch.isdigit())
        return s[:8]

    src_rows = raw[raw[date_c].map(ymd) == "20260804"].copy()
    print("\n=== 원본 20260804 전체 행 ===")
    show_cols = [date_c, side_c, code_c, name_c, qty_c, px_c, settle_c]
    if fx_c:
        show_cols.append(fx_c)
    if fee_c:
        show_cols.append(fee_c)
    if tax_c:
        show_cols.append(tax_c)
    print(src_rows[show_cols].to_string(index=False))

    parsed = parse_generic_overseas_excel(meritz.read_bytes(), meritz.name)
    parsed_rows = [r for r in parsed["rows"] if str(r.get("거래일자") or "").replace("-", "")[:8] == "20260804"]
    print("\n=== 파서 20260804 ===")
    for r in parsed_rows:
        print(
            r.get("거래유형"),
            r.get("종목코드"),
            "qty", r.get("수량"),
            "px", r.get("외화단가"),
            "settle", r.get("거래/정산금액"),
            "fee", r.get("외화수수료"),
            "tax", r.get("외화제세금"),
            "fx", r.get("적용환율"),
        )

    # 기준 전표
    vdf = pd.read_excel(voucher, header=None)
    print("\n=== 기준전표 앞 12행(헤더) ===")
    print(vdf.head(12).iloc[:, :10].to_string())
    data = vdf.iloc[10:].copy()
    data = data[data[0].map(lambda x: "".join(ch for ch in str(x) if ch.isdigit())[:8] == "20260804")]
    print("\n=== 기준전표 20260804 분개 ===")
    for _, row in data.iterrows():
        vals = [row.iloc[i] if i < len(row) else "" for i in range(9)]
        print(vals)

    print("\n=== 파서 행 → 우리 적요 vs 기준전표 적요 ===")
    ref_memos = [
        str(row.iloc[7]).strip()
        for _, row in data.iterrows()
        if pd.notna(row.iloc[7]) and str(row.iloc[7]).strip()
    ]

    our_memos: list[str] = []
    for r in parsed_rows:
        kind = str(r.get("거래유형") or "")
        side = "BUY" if "매수" in kind else "SELL"
        qty = float(r.get("수량") or 0)
        px = float(r.get("외화단가") or 0)
        settle = float(r.get("거래/정산금액") or r.get("외화총액") or 0)
        fx = float(r.get("적용환율") or 0)
        fee = float(r.get("외화수수료") or 0)
        tax = float(r.get("외화제세금") or 0)
        trade = Trade(
            id=None,
            trade_date=str(r.get("거래일자")),
            business_id=1,
            stock_id=1,
            side=side,
            quantity=qty,
            price=px * fx,
            fee=fee * fx,
            tax=tax * fx,
            memo=attach_fx_gross_memo("메리츠증권 해외매도" if side == "SELL" else "메리츠증권 해외매수", settle),
            source="broker:meritz-overseas",
            currency=str(r.get("통화코드") or "USD"),
            fx_rate=fx,
            price_fx=px,
            fee_fx=fee,
            tax_fx=tax,
            settlement_fx=settle,
            account_name="메리츠증권(외화)",
            stock_code=str(r.get("종목코드") or ""),
            stock_name=str(r.get("종목명") or ""),
        )
        from src.voucher_export import _deposit_summary

        trade_memo = (
            _trade_summary_sell(trade, "amount")
            if side == "SELL"
            else _trade_summary_buy(trade, "amount")
        )
        deposit_memo = _deposit_summary(trade, "amount", trade_memo)
        fee_memo = _fee_summary(trade, "amount", kind="fee")
        tax_memo = _fee_summary(trade, "amount", kind="tax")
        print("---", kind, r.get("종목코드"), "qty*px", round(qty * px, 6), "엑셀정산", settle)
        print("  종목적요:", trade_memo)
        print("  증권사적요:", deposit_memo)
        if fee > 0:
            print("  수수료적요:", fee_memo)
        if tax > 0:
            print("  제세금적요:", tax_memo)
        our_memos.append(trade_memo)
        if fee > 0:
            our_memos.append(fee_memo)
        if tax > 0:
            our_memos.append(tax_memo)

    print("\n=== 기준전표 적요 목록 ===")
    for m in ref_memos:
        print(" REF:", m)

    print("\n=== 매매 적요 일치 여부 (앞 금액) ===")
    def front(text: str) -> str:
        t = " ".join(str(text).split())
        return t.split("/")[0].strip() if "/" in t else t

    our_trade_fronts = [front(m) for m in our_memos if "주*" in m]
    ref_trade_fronts = [front(m) for m in ref_memos if "주*" in m]
    print("우리 앞금액:", our_trade_fronts)
    print("기준 앞금액:", ref_trade_fronts)

    # 수량*단가 실수 검출
    bad = []
    for r in parsed_rows:
        qty = float(r.get("수량") or 0)
        px = float(r.get("외화단가") or 0)
        settle = float(r.get("거래/정산금액") or 0)
        memo = build_overseas_remark_amount(
            Trade(
                id=None,
                trade_date="2026-08-04",
                business_id=1,
                stock_id=1,
                side="SELL" if "매도" in str(r.get("거래유형")) else "BUY",
                quantity=qty,
                price=0,
                currency="USD",
                fx_rate=float(r.get("적용환율") or 0),
                price_fx=px,
                settlement_fx=settle,
                memo=attach_fx_gross_memo("메리츠", settle),
                source="broker:meritz-overseas",
                account_name="메리츠증권(외화)",
            )
        )
        qty_amt = abs(qty * px)
        if abs(settle - qty_amt) > 0.001 and f"{qty_amt:.6f}".rstrip("0").rstrip(".") in memo.split("/")[0]:
            bad.append((r.get("종목코드"), memo, settle, qty_amt))
        print("CHECK", r.get("종목코드"), memo, "| excel", settle, "qty*px", qty_amt, "OK" if settle > 0 and abs(float(memo.split()[1]) - settle) < 0.001 else "FAIL")

    if bad:
        print("FAIL 수량×단가를 쓴 적요:", bad)
    else:
        print("파서+적요: 엑셀 거래/정산금액을 앞 금액으로 사용함")


if __name__ == "__main__":
    main()
