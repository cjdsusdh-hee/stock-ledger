"""업로드 거래 중복 판정."""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import Trade


def _round_amt(value: float | None, ndigits: int = 4) -> float:
    try:
        return round(float(value or 0), ndigits)
    except (TypeError, ValueError):
        return 0.0


def trade_fingerprint(trade: Trade) -> tuple:
    """동일 증권사·일자·종목·유형·수량·단가·수수료(+외화)면 같은 거래."""
    fx = _round_amt(getattr(trade, "fx_rate", 0), 2)
    price_fx = _round_amt(getattr(trade, "price_fx", 0), 4)
    return (
        int(trade.business_id or 0),
        int(getattr(trade, "account_id", 0) or 0),
        str(trade.trade_date or "")[:10],
        int(trade.stock_id or 0),
        str(trade.side or "").upper(),
        _round_amt(trade.quantity, 4),
        _round_amt(trade.price, 2),
        _round_amt(trade.fee, 2),
        fx,
        price_fx,
    )


@dataclass
class DedupeResult:
    fresh: list[Trade] = field(default_factory=list)
    db_duplicates: list[Trade] = field(default_factory=list)
    file_duplicates: list[Trade] = field(default_factory=list)

    @property
    def new_count(self) -> int:
        return len(self.fresh)

    @property
    def db_dup_count(self) -> int:
        return len(self.db_duplicates)

    @property
    def file_dup_count(self) -> int:
        return len(self.file_duplicates)


def match_existing_trades(
    incoming: list[Trade],
    existing: list[Trade],
) -> list[tuple[Trade, Trade]]:
    """들어온 거래와 DB에 이미 있는 같은 거래를 짝짓는다."""
    buckets: dict[tuple, list[Trade]] = {}
    for trade in existing:
        buckets.setdefault(trade_fingerprint(trade), []).append(trade)
    used: set[int] = set()
    pairs: list[tuple[Trade, Trade]] = []
    for trade in incoming:
        for old in buckets.get(trade_fingerprint(trade), []):
            oid = int(old.id or 0)
            if oid and oid not in used:
                used.add(oid)
                pairs.append((trade, old))
                break
    return pairs


def classify_trades(
    incoming: list[Trade],
    existing: list[Trade],
) -> DedupeResult:
    existing_keys = {trade_fingerprint(t) for t in existing}
    seen_in_file: set[tuple] = set()
    result = DedupeResult()
    for trade in incoming:
        key = trade_fingerprint(trade)
        if key in existing_keys:
            result.db_duplicates.append(trade)
            continue
        if key in seen_in_file:
            result.file_duplicates.append(trade)
            continue
        seen_in_file.add(key)
        result.fresh.append(trade)
    return result
