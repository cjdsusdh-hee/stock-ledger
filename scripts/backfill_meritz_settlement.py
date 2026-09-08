"""메리츠 엑셀 거래/정산금액을 DB에 넣고, 기준 기간 전표를 다시 만든다."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.brokers.generic_overseas import parse_generic_overseas_excel
from src.fifo import compute_positions
from src.models import MARKET_OVERSEAS
from src.storage import Storage
from src.voucher_export import attach_fx_gross_memo, export_voucher_excel_bytes


def _find_meritz() -> Path:
    for f in ROOT.iterdir():
        if f.suffix.lower() in {".xls", ".xlsx"} and "메리츠" in f.name and not f.name.startswith("~$"):
            return f
    raise FileNotFoundError("메리츠 거래내역(해외) 파일을 찾지 못했습니다.")


def _side(kind: str) -> str:
    return "BUY" if "매수" in str(kind) else "SELL"


def _key(date_s: str, side: str, code: str, qty: float, price: float) -> tuple:
    return (
        str(date_s or "")[:10],
        str(side or "").upper(),
        str(code or "").strip().upper(),
        round(float(qty or 0), 4),
        round(float(price or 0), 4),
    )


def main() -> None:
    meritz = _find_meritz()
    parsed = parse_generic_overseas_excel(meritz.read_bytes(), meritz.name)
    rows = parsed.get("rows") or []
    by_key: dict[tuple, float] = {}
    for r in rows:
        settle = float(r.get("거래/정산금액") or r.get("외화총액") or 0)
        if settle <= 0:
            continue
        key = _key(
            str(r.get("거래일자") or ""),
            _side(str(r.get("거래유형") or "")),
            str(r.get("종목코드") or ""),
            float(r.get("수량") or 0),
            float(r.get("외화단가") or 0),
        )
        by_key[key] = settle
    print(f"엑셀 매매 {len(rows)}건, 정산금액 {len(by_key)}건")

    storage = Storage()
    patched = 0
    missing = 0
    sample_ok = []
    for biz in storage.list_businesses():
        if biz.id is None:
            continue
        trades = storage.list_trades(business_id=int(biz.id), market=MARKET_OVERSEAS)
        for trade in trades:
            acct = str(getattr(trade, "account_name", "") or "")
            if "메리츠" not in acct and "meritz" not in acct.lower():
                continue
            if trade.id is None:
                continue
            key = _key(
                trade.trade_date,
                str(trade.side),
                str(getattr(trade, "stock_code", "") or ""),
                float(trade.quantity or 0),
                float(getattr(trade, "price_fx", 0) or 0),
            )
            settle = by_key.get(key, 0)
            if settle <= 0:
                missing += 1
                continue
            storage.update_trade_settlement_fx(
                int(trade.id),
                settlement_fx=settle,
                memo=attach_fx_gross_memo(trade.memo or "", settle),
                source=trade.source or "broker:meritz-overseas",
            )
            patched += 1
            if str(trade.trade_date)[:10] == "2026-08-04":
                sample_ok.append((trade.id, trade.side, settle))
    print(f"DB 갱신 {patched}건, 엑셀과 안 맞는 메리츠 {missing}건")
    print("2026-08-04", sample_ok)

    # 전표 재생성 (2026-08-01 ~ 2026-09-08, 메리츠 사업자)
    start = date(2026, 8, 1)
    end = date(2026, 9, 8)
    out_path = ROOT / "엑셀자료일반전표전송_주식매매_20260801_20260908_재생성.xlsx"
    for biz in storage.list_businesses():
        if biz.id is None:
            continue
        trades = storage.list_trades(business_id=int(biz.id), market=MARKET_OVERSEAS)
        meritz_trades = [
            t
            for t in trades
            if "메리츠" in str(getattr(t, "account_name", "") or "")
        ]
        if not meritz_trades:
            continue
        period = [
            t
            for t in meritz_trades
            if start.isoformat() <= str(t.trade_date)[:10] <= end.isoformat()
        ]
        if not period:
            continue
        _, sells, _ = compute_positions(meritz_trades)
        cfg = storage.get_account_config(int(biz.id), market=MARKET_OVERSEAS)
        partners = {
            int(s.id): (s.partner_code or "")
            for s in storage.list_stocks(int(biz.id), market=MARKET_OVERSEAS)
            if s.id is not None
        }
        data = export_voucher_excel_bytes(
            period,
            sells,
            company_name=biz.name,
            account_config=cfg,
            partner_by_stock_id=partners,
            remark_mode="amount",
        )
        out_path.write_bytes(data)
        print(f"전표 저장: {out_path.name} ({biz.name}, {len(period)}건, {len(data)} bytes)")
        break


if __name__ == "__main__":
    main()
