"""Supabase 기반 데이터 저장소."""

from __future__ import annotations

from dataclasses import MISSING, fields
from datetime import date
from typing import Any

from .models import (
    Account,
    AccountConfig,
    BrokerPartner,
    Business,
    IncomeAccountConfig,
    IncomeRecord,
    MARKET_DOMESTIC,
    MARKET_OVERSEAS,
    Stock,
    Trade,
    coerce_fx_rate,
    normalize_market,
    now_str,
)
from .supabase_client import get_supabase_client

DEFAULT_DB_PATH = None  # 호환용 (더 이상 SQLite 파일을 쓰지 않음)
UNASSIGNED_ACCOUNT_NAME = "미지정"
_PAGE = 1000


def _from_row(cls: type, row: Any) -> Any:
    """API/DB row를 dataclass 생성자 인자에만 맞게 변환한다."""
    raw = dict(row or {})
    kwargs: dict[str, Any] = {}
    for f in fields(cls):
        if f.name in raw and raw[f.name] is not None:
            kwargs[f.name] = raw[f.name]
        elif f.default is not MISSING:
            kwargs[f.name] = f.default
        elif f.default_factory is not MISSING:  # type: ignore[misc]
            kwargs[f.name] = f.default_factory()  # type: ignore[misc]
        else:
            kwargs[f.name] = raw.get(f.name)
    return cls(**kwargs)


class Storage:
    def __init__(self, db_path: str | None = None) -> None:  # noqa: ARG002
        self._client = get_supabase_client()

    def _sb(self):
        return self._client

    def close(self) -> None:
        return None

    def _fetch(
        self,
        table: str,
        *,
        eq: dict[str, Any] | None = None,
        order: str | None = None,
        desc: bool = False,
        extra: Any | None = None,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        start = 0
        while True:
            q = self._sb().table(table).select("*")
            if eq:
                for key, value in eq.items():
                    if value is not None:
                        q = q.eq(key, value)
            if extra is not None:
                q = extra(q)
            if order:
                q = q.order(order, desc=desc)
            res = q.range(start, start + _PAGE - 1).execute()
            chunk = list(res.data or [])
            rows.extend(chunk)
            if len(chunk) < _PAGE:
                break
            start += _PAGE
        return rows

    def _one(
        self,
        table: str,
        *,
        eq: dict[str, Any] | None = None,
        extra: Any | None = None,
    ) -> dict[str, Any] | None:
        q = self._sb().table(table).select("*")
        if eq:
            for key, value in eq.items():
                if value is not None:
                    q = q.eq(key, value)
        if extra is not None:
            q = extra(q)
        res = q.limit(1).execute()
        data = res.data or []
        return data[0] if data else None

    def _insert(self, table: str, payload: dict[str, Any]) -> dict[str, Any]:
        res = self._sb().table(table).insert(payload).select("*").execute()
        data = res.data or []
        if not data:
            raise RuntimeError(f"{table} 저장에 실패했습니다.")
        return data[0]

    def _update(
        self,
        table: str,
        payload: dict[str, Any],
        *,
        eq: dict[str, Any],
    ) -> int:
        q = self._sb().table(table).update(payload)
        for key, value in eq.items():
            q = q.eq(key, value)
        res = q.select("*").execute()
        return len(res.data or [])

    def _delete(self, table: str, *, eq: dict[str, Any]) -> int:
        q = self._sb().table(table).delete()
        for key, value in eq.items():
            q = q.eq(key, value)
        res = q.select("*").execute()
        return len(res.data or [])

    def _count(self, table: str, *, eq: dict[str, Any] | None = None) -> int:
        q = self._sb().table(table).select("id", count="exact")
        if eq:
            for key, value in eq.items():
                q = q.eq(key, value)
        res = q.limit(1).execute()
        return int(res.count or 0)

    # ------------------------------------------------------------------
    # Account config
    # ------------------------------------------------------------------
    def get_account_config(
        self,
        business_id: int | None,
        market: str | None = MARKET_DOMESTIC,
    ) -> AccountConfig:
        if business_id is None:
            return AccountConfig()
        mkt = normalize_market(market)
        row = self._one(
            "account_config",
            eq={"business_id": int(business_id), "market": mkt},
        )
        if row is None:
            return AccountConfig()
        return AccountConfig(
            security_code=str(row.get("security_code") or "0178"),
            fee_code=str(row.get("fee_code") or "0965"),
            deposit_code=str(row.get("deposit_code") or "0104"),
            gain_code=str(row.get("gain_code") or "0915"),
            loss_code=str(row.get("loss_code") or "0953"),
            interest_code=str(row.get("interest_code") or "0901"),
            prepaid_tax_code=str(row.get("prepaid_tax_code") or "0136"),
            bank_code=str(row.get("bank_code") or "0103"),
        ).normalize()

    def save_account_config(
        self,
        business_id: int | None,
        config: AccountConfig | dict[str, Any],
        market: str | None = MARKET_DOMESTIC,
    ) -> AccountConfig:
        if business_id is None:
            raise ValueError("사업자를 선택한 뒤 계정과목을 저장해 주세요.")
        mkt = normalize_market(market)
        if isinstance(config, dict):
            cfg = AccountConfig(
                security_code=str(
                    config.get("security_code")
                    or config.get("stock_code")
                    or "0178"
                ),
                fee_code=str(config.get("fee_code") or "0965"),
                deposit_code=str(config.get("deposit_code") or "0104"),
                gain_code=str(config.get("gain_code") or "0915"),
                loss_code=str(config.get("loss_code") or "0953"),
                interest_code=str(config.get("interest_code") or "0901"),
                prepaid_tax_code=str(config.get("prepaid_tax_code") or "0136"),
                bank_code=str(config.get("bank_code") or "0103"),
            ).normalize()
        else:
            cfg = config.normalize()
        for label, code in (
            ("투자유가증권", cfg.security_code),
            ("지급수수료", cfg.fee_code),
            ("기타제예금", cfg.deposit_code),
            ("투자자산처분이익", cfg.gain_code),
            ("투자자산처분손실", cfg.loss_code),
            ("이자수익", cfg.interest_code),
            ("선납세금", cfg.prepaid_tax_code),
            ("보통예금", cfg.bank_code),
        ):
            if not code:
                raise ValueError(f"{label} 계정코드는 필수입니다.")
        self._sb().table("account_config").upsert(
            {
                "business_id": int(business_id),
                "market": mkt,
                "security_code": cfg.security_code,
                "fee_code": cfg.fee_code,
                "deposit_code": cfg.deposit_code,
                "gain_code": cfg.gain_code,
                "loss_code": cfg.loss_code,
                "interest_code": cfg.interest_code,
                "prepaid_tax_code": cfg.prepaid_tax_code,
                "bank_code": cfg.bank_code,
            },
            on_conflict="business_id,market",
        ).execute()
        return cfg

    def update_stock_partner_codes(
        self,
        updates: dict[int, str],
        business_id: int | None = None,
    ) -> int:
        if not updates:
            return 0
        changed = 0
        for stock_id, partner_code in updates.items():
            eq: dict[str, Any] = {"id": int(stock_id)}
            if business_id is not None:
                eq["business_id"] = int(business_id)
            changed += self._update(
                "stocks",
                {"partner_code": str(partner_code or "").strip()},
                eq=eq,
            )
        return changed

    # ------------------------------------------------------------------
    # Business
    # ------------------------------------------------------------------
    def add_business(
        self,
        name: str,
        note: str = "",
        code: str = "",
        account_no: str = "",
    ) -> int:
        name = name.strip()
        if not name:
            raise ValueError("사업자명은 필수입니다.")
        row = self._insert(
            "businesses",
            {
                "name": name,
                "note": note.strip(),
                "created_at": now_str(),
                "code": code.strip(),
                "account_no": account_no.strip(),
            },
        )
        return int(row["id"])

    def update_business(
        self,
        business_id: int,
        name: str,
        note: str = "",
        code: str = "",
        account_no: str = "",
    ) -> None:
        self._update(
            "businesses",
            {
                "name": name.strip(),
                "note": note.strip(),
                "code": code.strip(),
                "account_no": account_no.strip(),
            },
            eq={"id": int(business_id)},
        )

    def delete_entity(self, business_id: int) -> None:
        bid = int(business_id)
        self._delete("trades", eq={"business_id": bid})
        self._delete("income_records", eq={"business_id": bid})
        self._delete("stocks", eq={"business_id": bid})
        self._delete("accounts", eq={"business_id": bid})
        self._delete("broker_partners", eq={"business_id": bid})
        self._delete("account_config", eq={"business_id": bid})
        self._delete("businesses", eq={"id": bid})

    def delete_business(self, business_id: int) -> None:
        self.delete_entity(business_id)

    def count_trades_for_business(self, business_id: int) -> int:
        return self._count("trades", eq={"business_id": int(business_id)})

    def delete_account(self, account_id: int, *, force: bool = False) -> None:
        used = self.count_trades_for_account(account_id)
        if used and not force:
            raise ValueError(
                f"이 증권사/계좌와 연결된 거래 내역이 {used}건 존재합니다. "
                "거래를 다른 증권사로 옮기거나 확인 후 강제 삭제해 주세요."
            )
        if force:
            self._update("trades", {"account_id": None}, eq={"account_id": int(account_id)})
        self._delete("accounts", eq={"id": int(account_id)})

    def get_all_accounts(
        self,
        business_id: int | None = None,
        market: str | None = None,
    ) -> list[Account]:
        return self.list_accounts(business_id, market=market)

    def list_accounts(
        self,
        business_id: int | None = None,
        market: str | None = None,
    ) -> list[Account]:
        if business_id is None:
            return []
        eq: dict[str, Any] = {"business_id": int(business_id)}
        if market is not None:
            eq["market"] = normalize_market(market)
        rows = self._fetch("accounts", eq=eq, order="name")
        return [_from_row(Account, r) for r in rows]

    def add_account(
        self,
        business_id: int,
        name: str,
        code: str = "",
        account_no: str = "",
        note: str = "",
        market: str | None = MARKET_DOMESTIC,
    ) -> int:
        name = name.strip()
        if not name:
            raise ValueError("거래처명은 필수입니다.")
        row = self._insert(
            "accounts",
            {
                "business_id": int(business_id),
                "name": name,
                "code": code.strip(),
                "account_no": account_no.strip(),
                "note": note.strip(),
                "created_at": now_str(),
                "market": normalize_market(market),
            },
        )
        return int(row["id"])

    def count_trades_for_account(self, account_id: int) -> int:
        return self._count("trades", eq={"account_id": int(account_id)})

    def get_account(self, account_id: int) -> Account | None:
        row = self._one("accounts", eq={"id": int(account_id)})
        return _from_row(Account, row) if row else None

    def get_account_by_name(
        self,
        business_id: int,
        name: str,
        market: str | None = MARKET_DOMESTIC,
    ) -> Account | None:
        eq: dict[str, Any] = {
            "business_id": int(business_id),
            "name": name.strip(),
        }
        if market is not None:
            eq["market"] = normalize_market(market)
        row = self._one("accounts", eq=eq)
        return _from_row(Account, row) if row else None

    def get_or_create_account(
        self,
        business_id: int,
        name: str,
        *,
        market: str | None = MARKET_DOMESTIC,
        code: str = "",
        account_no: str = "",
        note: str = "",
    ) -> Account:
        name = name.strip()
        if not name:
            raise ValueError("증권사/거래처명은 필수입니다.")
        mkt = normalize_market(market)
        existing = self.get_account_by_name(business_id, name, market=mkt)
        if existing:
            return existing
        aid = self.add_account(
            business_id,
            name,
            code=code,
            account_no=account_no,
            note=note,
            market=mkt,
        )
        return Account(
            id=aid,
            business_id=int(business_id),
            name=name,
            code=code.strip(),
            account_no=account_no.strip(),
            note=note.strip(),
            created_at=now_str(),
            market=mkt,
        )

    def get_or_create_unassigned_account(
        self,
        business_id: int,
        market: str | None = MARKET_DOMESTIC,
    ) -> Account:
        return self.get_or_create_account(
            business_id,
            UNASSIGNED_ACCOUNT_NAME,
            market=market,
            note="기존 거래 백필용 기본 증권사",
        )

    def probe_account_column(self) -> tuple[bool, str]:
        try:
            self._sb().table("trades").select("id,account_id").limit(1).execute()
            return True, ""
        except Exception as exc:  # noqa: BLE001
            text = str(exc)
            lowered = text.lower()
            if any(
                token in lowered
                for token in (
                    "account_id",
                    "pgrst204",
                    "does not exist",
                    "could not find",
                    "schema cache",
                )
            ):
                return False, text
            raise

    def backfill_unassigned_accounts(self) -> tuple[int, int]:
        """account_id가 비어 있는 거래를 사업자·시장별 미지정 계좌로 채운다."""
        ok, detail = self.probe_account_column()
        if not ok:
            raise RuntimeError(
                "trades.account_id 컬럼이 없습니다. "
                "supabase/migrations/20260907120000_trades_account_id.sql 을 "
                "Supabase SQL Editor에서 실행하세요. "
                f"({detail})"
            )
        created = 0
        updated = 0
        businesses = self.list_businesses()
        for biz in businesses:
            if biz.id is None:
                continue
            for market in (MARKET_DOMESTIC, MARKET_OVERSEAS):
                acc = self.get_or_create_unassigned_account(int(biz.id), market=market)
                created += 1
                stocks = {
                    int(s.id): s
                    for s in self.list_stocks(int(biz.id), market=market)
                    if s.id is not None
                }
                if not stocks or acc.id is None:
                    continue
                rows = self._fetch(
                    "trades",
                    eq={"business_id": int(biz.id)},
                )
                for row in rows:
                    if row.get("account_id"):
                        continue
                    sid = int(row.get("stock_id") or 0)
                    if sid not in stocks:
                        continue
                    updated += self._update(
                        "trades",
                        {"account_id": int(acc.id)},
                        eq={"id": int(row["id"])},
                    )
        return created, updated

    def update_trade_account(self, trade_id: int, account_id: int) -> None:
        n = self._update(
            "trades",
            {"account_id": int(account_id)},
            eq={"id": int(trade_id)},
        )
        if n == 0:
            raise ValueError(f"거래 ID {trade_id}를 찾을 수 없습니다.")

    def reassign_account_trades(
        self,
        from_account_id: int,
        to_account_id: int,
    ) -> int:
        rows = self._fetch("trades", eq={"account_id": int(from_account_id)})
        n = 0
        for row in rows:
            n += self._update(
                "trades",
                {"account_id": int(to_account_id)},
                eq={"id": int(row["id"])},
            )
        return n

    def list_businesses(self) -> list[Business]:
        rows = self._fetch("businesses", order="name")
        return [_from_row(Business, r) for r in rows]

    def get_business_by_name(self, name: str) -> Business | None:
        row = self._one("businesses", eq={"name": name.strip()})
        return _from_row(Business, row) if row else None

    def get_or_create_business(self, name: str) -> Business:
        existing = self.get_business_by_name(name)
        if existing:
            return existing
        bid = self.add_business(name)
        return Business(
            id=bid,
            name=name.strip(),
            note="",
            created_at=now_str(),
            code="",
            account_no="",
        )

    # ------------------------------------------------------------------
    # Stock
    # ------------------------------------------------------------------
    def add_stock(
        self,
        code: str,
        name: str,
        market: str = MARKET_DOMESTIC,
        note: str = "",
        partner_code: str = "",
        business_id: int | None = None,
    ) -> int:
        if business_id is None:
            raise ValueError("종목 등록 시 사업자가 필요합니다.")
        code = code.strip()
        name = name.strip()
        if not code or not name:
            raise ValueError("종목코드와 종목명은 필수입니다.")
        row = self._insert(
            "stocks",
            {
                "business_id": int(business_id),
                "code": code,
                "name": name,
                "market": normalize_market(market),
                "note": note.strip(),
                "partner_code": partner_code.strip(),
                "created_at": now_str(),
            },
        )
        return int(row["id"])

    def update_stock(
        self,
        stock_id: int,
        code: str,
        name: str,
        market: str = MARKET_DOMESTIC,
        note: str = "",
        partner_code: str = "",
        business_id: int | None = None,
    ) -> None:
        eq: dict[str, Any] = {"id": int(stock_id)}
        if business_id is not None:
            eq["business_id"] = int(business_id)
        self._update(
            "stocks",
            {
                "code": code.strip(),
                "name": name.strip(),
                "market": normalize_market(market),
                "note": note.strip(),
                "partner_code": partner_code.strip(),
            },
            eq=eq,
        )

    def count_trades_for_stock(self, stock_id: int) -> int:
        return self._count("trades", eq={"stock_id": int(stock_id)})

    def delete_stock(self, stock_id: int, *, force: bool = False) -> None:
        used = self.count_trades_for_stock(stock_id)
        if used and not force:
            raise ValueError(
                f"이 종목과 연결된 거래 내역이 {used}건 존재합니다. "
                "확인 후 강제 삭제해 주세요."
            )
        if force:
            self._delete("trades", eq={"stock_id": int(stock_id)})
        self._delete("stocks", eq={"id": int(stock_id)})

    def delete_stock_by_code(
        self,
        stock_code: str,
        *,
        force: bool = False,
        business_id: int | None = None,
        market: str | None = None,
    ) -> None:
        stock = self.get_stock_by_code(
            stock_code, business_id=business_id, market=market
        )
        if not stock or stock.id is None:
            raise ValueError(f"종목코드 '{stock_code}'를 찾을 수 없습니다.")
        self.delete_stock(int(stock.id), force=force)

    def list_stocks(
        self,
        business_id: int | None = None,
        market: str | None = None,
    ) -> list[Stock]:
        eq: dict[str, Any] = {}
        if business_id is not None:
            eq["business_id"] = int(business_id)
        if market is not None:
            eq["market"] = normalize_market(market)
        rows = self._fetch("stocks", eq=eq or None, order="name")
        return [_from_row(Stock, r) for r in rows]

    def get_all_stocks(
        self,
        business_id: int | None = None,
        market: str | None = None,
    ) -> list[Stock]:
        return self.list_stocks(business_id, market=market)

    def get_stock_by_code(
        self,
        code: str,
        business_id: int | None = None,
        market: str | None = None,
    ) -> Stock | None:
        eq: dict[str, Any] = {"code": code.strip()}
        if business_id is not None:
            eq["business_id"] = int(business_id)
        if market is not None:
            eq["market"] = normalize_market(market)
        row = self._one("stocks", eq=eq)
        return _from_row(Stock, row) if row else None

    def get_stock_by_name(
        self,
        name: str,
        business_id: int | None = None,
        market: str | None = None,
    ) -> Stock | None:
        eq: dict[str, Any] = {}
        if business_id is not None:
            eq["business_id"] = int(business_id)
        if market is not None:
            eq["market"] = normalize_market(market)

        def extra(q):
            return q.ilike("name", name.strip())

        row = self._one("stocks", eq=eq or None, extra=extra)
        return _from_row(Stock, row) if row else None

    def get_or_create_stock(
        self,
        code: str,
        name: str,
        business_id: int | None = None,
        market: str | None = MARKET_DOMESTIC,
    ) -> Stock:
        if business_id is None:
            raise ValueError("종목 조회/등록 시 사업자가 필요합니다.")
        mkt = normalize_market(market)
        existing = self.get_stock_by_code(code, business_id=business_id, market=mkt)
        if existing:
            if name and existing.name != name.strip():
                self.update_stock(
                    existing.id,  # type: ignore[arg-type]
                    existing.code,
                    name.strip(),
                    mkt,
                    existing.note,
                    existing.partner_code,
                    business_id=business_id,
                )
                existing.name = name.strip()
            return existing
        sid = self.add_stock(code, name, market=mkt, business_id=business_id)
        return Stock(
            id=sid,
            code=code.strip(),
            name=name.strip(),
            market=mkt,
            created_at=now_str(),
            business_id=int(business_id),
        )

    def get_or_create_stock_by_name(
        self,
        name: str,
        code: str | None = None,
        business_id: int | None = None,
        market: str | None = MARKET_DOMESTIC,
    ) -> Stock:
        if business_id is None:
            raise ValueError("종목 조회/등록 시 사업자가 필요합니다.")
        mkt = normalize_market(market)
        name = name.strip()
        if not name:
            raise ValueError("종목명은 필수입니다.")
        existing = self.get_stock_by_name(name, business_id=business_id, market=mkt)
        if existing:
            return existing
        clean_code = (code or "").strip()
        if clean_code:
            return self.get_or_create_stock(
                clean_code, name, business_id=business_id, market=mkt
            )
        n = 1
        while True:
            candidate = f"TMP{n:04d}"
            if not self.get_stock_by_code(
                candidate, business_id=business_id, market=mkt
            ):
                break
            n += 1
        sid = self.add_stock(candidate, name, market=mkt, business_id=business_id)
        return Stock(
            id=sid,
            code=candidate,
            name=name,
            market=mkt,
            created_at=now_str(),
            business_id=int(business_id),
        )

    # ------------------------------------------------------------------
    # Trade
    # ------------------------------------------------------------------
    def _trade_payload(self, trade: Trade) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "trade_date": trade.trade_date,
            "business_id": trade.business_id,
            "stock_id": trade.stock_id,
            "side": trade.side,
            "quantity": trade.quantity,
            "price": trade.price,
            "fee": trade.fee,
            "tax": float(getattr(trade, "tax", 0) or 0),
            "settlement_amount": trade.settlement_amount,
            "memo": trade.memo or "",
            "source": trade.source or "manual",
            "created_at": trade.created_at or now_str(),
            "currency": getattr(trade, "currency", None) or "KRW",
            "fx_rate": float(coerce_fx_rate(getattr(trade, "fx_rate", 0))),
            "price_fx": float(getattr(trade, "price_fx", 0) or 0),
            "fee_fx": float(getattr(trade, "fee_fx", 0) or 0),
            "tax_fx": float(getattr(trade, "tax_fx", 0) or 0),
        }
        account_id = getattr(trade, "account_id", None)
        if account_id:
            payload["account_id"] = int(account_id)
        return payload

    def add_trade(self, trade: Trade) -> int:
        row = self._insert("trades", self._trade_payload(trade))
        return int(row["id"])

    def add_trades_bulk(self, trades: list[Trade]) -> int:
        if not trades:
            return 0
        payload = [self._trade_payload(t) for t in trades]
        count = 0
        for i in range(0, len(payload), 80):
            batch = payload[i : i + 80]
            self._sb().table("trades").insert(batch).execute()
            count += len(batch)
        return count

    def delete_trade(self, trade_id: int) -> None:
        self._delete("trades", eq={"id": int(trade_id)})

    def update_trade_date(self, trade_id: int, new_date: str) -> None:
        date_str = str(new_date or "").strip()[:10]
        if not date_str:
            raise ValueError("거래일자는 필수입니다.")
        n = self._update("trades", {"trade_date": date_str}, eq={"id": int(trade_id)})
        if n == 0:
            raise ValueError(f"거래 ID {trade_id}를 찾을 수 없습니다.")

    def _enrich_trade_accounts(self, rows: list[dict[str, Any]]) -> None:
        """뷰에 account 컬럼이 없거나 비면 trades/accounts에서 보강."""
        missing_ids: set[int] = set()
        need_overlay: list[int] = []
        for row in rows:
            aid = row.get("account_id")
            if aid is None and row.get("id") is not None:
                need_overlay.append(int(row["id"]))
            elif aid and not (row.get("account_name") or "").strip():
                missing_ids.add(int(aid))
        if need_overlay:
            raw_by_id: dict[int, dict[str, Any]] = {}
            try:
                raw_rows = self._fetch("trades")
            except Exception:  # noqa: BLE001
                raw_rows = []
            for raw in raw_rows:
                if raw.get("id") is not None:
                    raw_by_id[int(raw["id"])] = raw
            for row in rows:
                rid = row.get("id")
                if rid is None:
                    continue
                src = raw_by_id.get(int(rid))
                if not src:
                    continue
                if row.get("account_id") is None and src.get("account_id") is not None:
                    row["account_id"] = src.get("account_id")
                    if src.get("account_id"):
                        missing_ids.add(int(src["account_id"]))
        if not missing_ids:
            return
        acc_rows = self._fetch("accounts")
        by_id = {int(a["id"]): a for a in acc_rows if a.get("id") is not None}
        for row in rows:
            aid = row.get("account_id")
            if not aid:
                continue
            acc = by_id.get(int(aid))
            if not acc:
                continue
            if not (row.get("account_name") or "").strip():
                row["account_name"] = acc.get("name") or ""
            if not (row.get("account_code") or "").strip():
                row["account_code"] = acc.get("code") or ""

    def list_trades(
        self,
        business_id: int | None = None,
        stock_id: int | None = None,
        market: str | None = None,
        account_id: int | None = None,
    ) -> list[Trade]:
        eq: dict[str, Any] = {}
        if business_id is not None:
            eq["business_id"] = int(business_id)
        if stock_id is not None:
            eq["stock_id"] = int(stock_id)
        if market is not None:
            eq["stock_market"] = normalize_market(market)
        account_filter = int(account_id) if account_id is not None else None
        try:
            rows = self._fetch("trades_enriched", eq=eq or None, order="trade_date")
        except Exception:
            raw_eq = {
                k: v
                for k, v in eq.items()
                if k != "stock_market"
            }
            rows = self._fetch("trades", eq=raw_eq or None, order="trade_date")
            if market is not None:
                mkt = normalize_market(market)
                stocks = {
                    int(s.id): s
                    for s in self.list_stocks(business_id, market=mkt)
                    if s.id is not None
                }
                rows = [r for r in rows if int(r.get("stock_id") or 0) in stocks]
        self._enrich_trade_accounts(rows)
        if account_filter is not None:
            rows = [
                r
                for r in rows
                if r.get("account_id") is not None
                and int(r.get("account_id") or 0) == account_filter
            ]
        rows.sort(key=lambda r: (str(r.get("trade_date") or ""), int(r.get("id") or 0)))
        return [_from_row(Trade, r) for r in rows]

    def get_trades_by_period(
        self,
        business_id: int | None,
        start_date: str | date,
        end_date: str | date,
        market: str | None = None,
    ) -> list[Trade]:
        def _as_ymd(v: str | date) -> str:
            if isinstance(v, date):
                return v.isoformat()
            return str(v).strip()[:10]

        start = _as_ymd(start_date)
        end = _as_ymd(end_date)
        if start > end:
            start, end = end, start
        trades = self.list_trades(business_id=business_id, market=market)
        return [t for t in trades if start <= str(t.trade_date)[:10] <= end]

    def clear_all_trades(self) -> None:
        self._sb().table("trades").delete().neq("id", 0).execute()

    def clear_trades_for_business(self, business_id: int) -> int:
        return self._delete("trades", eq={"business_id": int(business_id)})

    # ------------------------------------------------------------------
    # Income
    # ------------------------------------------------------------------
    def get_income_account_config(
        self, business_id: int | None
    ) -> IncomeAccountConfig:
        return self.get_account_config(business_id).to_income_config()

    def save_income_account_config(
        self,
        business_id: int | None,
        config: IncomeAccountConfig,
    ) -> IncomeAccountConfig:
        if business_id is None:
            raise ValueError("사업자를 선택한 뒤 계정과목을 저장해 주세요.")
        base = self.get_account_config(business_id)
        cfg = config.normalize()
        base.interest_code = cfg.interest_code
        base.prepaid_tax_code = cfg.prepaid_tax_code
        base.bank_code = cfg.bank_code
        saved = self.save_account_config(business_id, base)
        return saved.to_income_config()

    def list_broker_partners(
        self, business_id: int | None = None
    ) -> list[BrokerPartner]:
        if business_id is None:
            return []
        rows = self._fetch(
            "broker_partners",
            eq={"business_id": int(business_id)},
            order="broker_name",
        )
        return [_from_row(BrokerPartner, r) for r in rows]

    def upsert_broker_partner(
        self,
        broker_name: str,
        partner_code: str = "",
        business_id: int | None = None,
    ) -> int:
        if business_id is None:
            raise ValueError("증권사 매핑 저장 시 사업자가 필요합니다.")
        name = broker_name.strip()
        if not name:
            raise ValueError("증권사명은 필수입니다.")
        code = (partner_code or "").strip()
        existing = self._one(
            "broker_partners",
            eq={"business_id": int(business_id)},
            extra=lambda q: q.ilike("broker_name", name),
        )
        if existing:
            self._update(
                "broker_partners",
                {"partner_code": code, "broker_name": name},
                eq={"id": int(existing["id"]), "business_id": int(business_id)},
            )
            return int(existing["id"])
        row = self._insert(
            "broker_partners",
            {
                "business_id": int(business_id),
                "broker_name": name,
                "partner_code": code,
                "created_at": now_str(),
            },
        )
        return int(row["id"])

    def update_broker_partners(
        self,
        updates: dict[int, tuple[str, str]],
        business_id: int | None = None,
    ) -> int:
        if not updates:
            return 0
        changed = 0
        for pid, (broker_name, partner_code) in updates.items():
            name = str(broker_name or "").strip()
            if not name:
                continue
            eq: dict[str, Any] = {"id": int(pid)}
            if business_id is not None:
                eq["business_id"] = int(business_id)
            changed += self._update(
                "broker_partners",
                {
                    "broker_name": name,
                    "partner_code": str(partner_code or "").strip(),
                },
                eq=eq,
            )
        return changed

    def delete_broker_partner(
        self, partner_id: int, business_id: int | None = None
    ) -> None:
        eq: dict[str, Any] = {"id": int(partner_id)}
        if business_id is not None:
            eq["business_id"] = int(business_id)
        self._delete("broker_partners", eq=eq)

    def broker_partner_map(self, business_id: int | None = None) -> dict[str, str]:
        return {
            (b.broker_name or "").strip().lower(): (b.partner_code or "").strip()
            for b in self.list_broker_partners(business_id)
            if (b.broker_name or "").strip()
        }

    def add_income_record(
        self,
        *,
        pay_date: str,
        business_id: int,
        product_name: str = "",
        broker_name: str = "",
        income_type: str = "INTEREST",
        gross_amount: float = 0.0,
        corp_tax: float = 0.0,
        local_tax: float = 0.0,
        memo: str = "",
        source: str = "manual",
    ) -> int:
        itype = str(income_type or "INTEREST").strip().upper()
        if itype not in ("INTEREST", "DIVIDEND"):
            itype = "INTEREST"
        pay = str(pay_date).strip()[:10]
        if not pay:
            raise ValueError("지급일은 필수입니다.")
        row = self._insert(
            "income_records",
            {
                "pay_date": pay,
                "business_id": int(business_id),
                "product_name": (product_name or "").strip(),
                "broker_name": (broker_name or "").strip(),
                "income_type": itype,
                "gross_amount": float(gross_amount or 0),
                "corp_tax": float(corp_tax or 0),
                "local_tax": float(local_tax or 0),
                "memo": (memo or "").strip(),
                "source": (source or "manual").strip(),
                "created_at": now_str(),
            },
        )
        return int(row["id"])

    def add_income_records_bulk(self, records: list[dict[str, Any]]) -> int:
        n = 0
        for r in records:
            self.add_income_record(**r)
            n += 1
        return n

    def update_income_record(
        self,
        record_id: int,
        *,
        pay_date: str,
        product_name: str = "",
        broker_name: str = "",
        income_type: str = "INTEREST",
        gross_amount: float = 0.0,
        corp_tax: float = 0.0,
        local_tax: float = 0.0,
        memo: str = "",
    ) -> None:
        itype = str(income_type or "INTEREST").strip().upper()
        if itype not in ("INTEREST", "DIVIDEND"):
            itype = "INTEREST"
        self._update(
            "income_records",
            {
                "pay_date": str(pay_date).strip()[:10],
                "product_name": (product_name or "").strip(),
                "broker_name": (broker_name or "").strip(),
                "income_type": itype,
                "gross_amount": float(gross_amount or 0),
                "corp_tax": float(corp_tax or 0),
                "local_tax": float(local_tax or 0),
                "memo": (memo or "").strip(),
            },
            eq={"id": int(record_id)},
        )

    def delete_income_records(self, record_ids: list[int]) -> int:
        if not record_ids:
            return 0
        n = 0
        for rid in record_ids:
            n += self._delete("income_records", eq={"id": int(rid)})
        return n

    def clear_income_records_for_business(self, business_id: int) -> int:
        return self._delete("income_records", eq={"business_id": int(business_id)})

    def list_income_records(
        self, business_id: int | None = None
    ) -> list[IncomeRecord]:
        eq: dict[str, Any] = {}
        if business_id is not None:
            eq["business_id"] = int(business_id)
        rows = self._fetch(
            "income_records_enriched",
            eq=eq or None,
            order="pay_date",
        )
        rows.sort(key=lambda r: (str(r.get("pay_date") or ""), int(r.get("id") or 0)))
        return [_from_row(IncomeRecord, r) for r in rows]

    def get_income_records_by_period(
        self,
        business_id: int | None,
        start_date: str | date,
        end_date: str | date,
    ) -> list[IncomeRecord]:
        def _as_ymd(v: str | date) -> str:
            if isinstance(v, date):
                return v.isoformat()
            return str(v).strip()[:10]

        start = _as_ymd(start_date)
        end = _as_ymd(end_date)
        if start > end:
            start, end = end, start
        records = self.list_income_records(business_id=business_id)
        return [r for r in records if start <= str(r.pay_date)[:10] <= end]
