"""trades.account_id 컬럼·뷰가 없으면 SQL 안내. 있으면 미지정 계좌 백필."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.storage import Storage


def main() -> None:
    storage = Storage()
    try:
        ok, detail = storage.probe_account_column()
    except Exception as exc:  # noqa: BLE001
        print(f"Supabase 접속 실패: {exc}")
        sys.exit(2)
    if not ok:
        sql_path = (
            ROOT / "supabase" / "migrations" / "20260907120000_trades_account_id.sql"
        )
        print("trades.account_id 컬럼이 없습니다.")
        print("Supabase SQL Editor에서 아래 파일을 실행하세요:")
        print(f"  {sql_path}")
        print(detail)
        sys.exit(1)

    n_acc, n_trade = storage.backfill_unassigned_accounts()
    print(f"account_id 준비됨. 미지정 계좌 확인 {n_acc}개, 백필 거래 {n_trade}건")


if __name__ == "__main__":
    main()
