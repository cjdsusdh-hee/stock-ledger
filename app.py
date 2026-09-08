"""법인 주식 매매일지 및 잔고 관리 웹앱 (Streamlit)."""

from __future__ import annotations

import html
import locale
import sys
from datetime import date
from pathlib import Path
from urllib.parse import quote

try:
    locale.setlocale(locale.LC_ALL, "ko_KR.UTF-8")
except Exception:
    try:
        locale.setlocale(locale.LC_ALL, "Korean_Korea.949")
    except Exception:
        pass

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.brokers import detect_and_parse, list_brokers
from src.brokers.pdf_parser import OCR_TIP, empty_trade_rows
from src.dedupe import classify_trades
from src.fifo import compute_positions
from src.legacy_journal import parse_legacy_journal_excel
from src.storage import UNASSIGNED_ACCOUNT_NAME

# Streamlit 핫리로드 시 stale sys.modules 방지
import importlib

import src.models as _models_mod
import src.storage as _storage_mod
import src.voucher_export as _voucher_mod
import src.income_parser as _income_parser_mod
import src.income_voucher as _income_voucher_mod
import src.import_export as _import_export_mod

_models_mod = importlib.reload(_models_mod)
_storage_mod = importlib.reload(_storage_mod)
_voucher_mod = importlib.reload(_voucher_mod)
_income_parser_mod = importlib.reload(_income_parser_mod)
_income_voucher_mod = importlib.reload(_income_voucher_mod)
_import_export_mod = importlib.reload(_import_export_mod)

AccountConfig = _models_mod.AccountConfig
IncomeAccountConfig = _models_mod.IncomeAccountConfig
Trade = _models_mod.Trade
MARKET_DOMESTIC = _models_mod.MARKET_DOMESTIC
MARKET_OVERSEAS = _models_mod.MARKET_OVERSEAS
FX_CURRENCIES = _models_mod.FX_CURRENCIES
normalize_market = _models_mod.normalize_market
normalize_currency = _models_mod.normalize_currency
coerce_fx_rate = _models_mod.coerce_fx_rate
now_str = _models_mod.now_str
Storage = _storage_mod.Storage
export_voucher_excel_bytes = _voucher_mod.export_voucher_excel_bytes
trades_to_voucher_lines = _voucher_mod.trades_to_voucher_lines
attach_fx_gross_memo = _voucher_mod.attach_fx_gross_memo
parse_income_file = _income_parser_mod.parse_income_file
rows_to_dataframe = _income_parser_mod.rows_to_dataframe
apply_income_fx_rates = _income_parser_mod.apply_income_fx_rates
ensure_income_preview_columns = _income_parser_mod.ensure_income_preview_columns
export_income_voucher_excel_bytes = _income_voucher_mod.export_income_voucher_excel_bytes
income_to_voucher_lines = _income_voucher_mod.income_to_voucher_lines
dataframe_to_trades = _import_export_mod.dataframe_to_trades
export_to_csv_bytes = _import_export_mod.export_to_csv_bytes
export_to_excel_bytes = _import_export_mod.export_to_excel_bytes
import_standard_file = _import_export_mod.import_standard_file
positions_to_dataframe = _import_export_mod.positions_to_dataframe
sell_results_to_dataframe = _import_export_mod.sell_results_to_dataframe
trades_to_dataframe = _import_export_mod.trades_to_dataframe

st.set_page_config(
    page_title="법인 주식 매매일지",
    page_icon="📈",
    layout="wide",
)

# 사이드바 작업 순서 메뉴
SIDEBAR_CUSTOM_CSS = """
<style>
    [data-testid="stSidebar"] [data-testid="stExpander"] {
        background-color: transparent !important;
        border: none !important;
        box-shadow: none !important;
        margin-bottom: 0.5rem !important;
    }

    [data-testid="stSidebar"] [data-testid="stExpander"] details {
        border: none !important;
        background: transparent !important;
    }

    [data-testid="stSidebar"] [data-testid="stExpander"] summary {
        font-weight: 700 !important;
        font-size: 0.95rem !important;
        color: #1f2937 !important;
        padding: 0.6rem 0.4rem !important;
        border-radius: 8px !important;
        list-style: none !important;
    }

    [data-testid="stSidebar"] [data-testid="stExpander"] summary:hover {
        background-color: #f3f4f6 !important;
    }

    [data-testid="stSidebar"] [data-testid="stExpander"] .stButton > button {
        width: 100% !important;
        border: none !important;
        border-width: 0 !important;
        box-shadow: none !important;
        background-color: transparent !important;
        color: #4b5563 !important;
        text-align: left !important;
        justify-content: flex-start !important;
        padding: 0.5rem 0.8rem !important;
        border-radius: 6px !important;
        font-size: 0.88rem !important;
        font-weight: 500 !important;
        transition: all 0.2s ease !important;
    }

    [data-testid="stSidebar"] [data-testid="stExpander"] .stButton > button:hover {
        background-color: #f3f4f6 !important;
        color: #111827 !important;
        border: none !important;
        box-shadow: none !important;
    }

    [data-testid="stSidebar"] [data-testid="stExpander"] .stButton > button:focus,
    [data-testid="stSidebar"] [data-testid="stExpander"] .stButton > button:active {
        box-shadow: none !important;
        outline: none !important;
    }

    [data-testid="stSidebar"] [data-testid="stExpander"] .stButton > button[kind="primary"],
    [data-testid="stSidebar"] [data-testid="stExpander"] .stButton > button[data-testid="baseButton-primary"] {
        background-color: #eff6ff !important;
        color: #2563eb !important;
        font-weight: 700 !important;
        border: none !important;
        border-left: 3px solid #2563eb !important;
        border-radius: 0 6px 6px 0 !important;
        box-shadow: none !important;
    }

    [data-testid="stSidebar"] [data-testid="stExpander"] .stButton > button[kind="primary"]:hover,
    [data-testid="stSidebar"] [data-testid="stExpander"] .stButton > button[data-testid="baseButton-primary"]:hover {
        background-color: #dbeafe !important;
        color: #1d4ed8 !important;
    }
</style>
"""


def inject_sidebar_styles() -> None:
    st.markdown(SIDEBAR_CUSTOM_CSS, unsafe_allow_html=True)


STORAGE_CACHE_VERSION = 21  # Storage API 변경 시 증가 → 캐시 무효화


@st.cache_resource
def _storage_singleton(_version: int) -> object:
    """버전 키가 바뀌면 models→storage 순으로 재로드 후 인스턴스를 만든다."""
    import importlib

    import src.models as models_mod
    import src.storage as storage_mod

    importlib.reload(models_mod)
    storage_mod = importlib.reload(storage_mod)
    instance = storage_mod.Storage()
    try:
        ok, _ = instance.probe_account_column()
        if ok:
            instance.backfill_unassigned_accounts()
    except Exception:  # noqa: BLE001
        pass
    return instance


def get_storage() -> Storage:
    """Supabase Storage. 핫리로드로 모델/메서드가 어긋나면 강제 갱신한다."""
    import importlib
    import inspect
    import types

    import src.models as models_mod
    import src.storage as storage_mod

    storage = _storage_singleton(STORAGE_CACHE_VERSION)
    required = (
        "update_trade_date",
        "get_all_stocks",
        "get_all_accounts",
        "delete_account",
        "get_trades_by_period",
        "get_account_config",
        "save_account_config",
        "update_stock_partner_codes",
        "get_income_account_config",
        "save_income_account_config",
        "list_income_records",
        "get_income_records_by_period",
        "list_broker_partners",
        "clear_trades_for_business",
        "clear_income_records_for_business",
        "get_or_create_account",
        "count_trades_for_account",
        "probe_account_column",
        "backfill_unassigned_accounts",
    )
    biz_ok = True
    stocks_ok = False
    try:
        # Business에 code 필드가 있는지 런타임 확인
        from dataclasses import fields as dc_fields

        biz_fields = {f.name for f in dc_fields(models_mod.Business)}
        trade_fields = {f.name for f in dc_fields(models_mod.Trade)}
        biz_ok = (
            "code" in biz_fields
            and "account_no" in biz_fields
            and "account_id" in trade_fields
        )
    except Exception:  # noqa: BLE001
        biz_ok = False

    try:
        # get_all_stocks(business_id=..., market=...) 시그니처 확인 (구버전 캐시 감지)
        sig = inspect.signature(type(storage).get_all_stocks)
        stocks_ok = "business_id" in sig.parameters and "market" in sig.parameters
        lt = inspect.signature(type(storage).list_trades)
        stocks_ok = stocks_ok and "market" in lt.parameters and "account_id" in lt.parameters
        ac = inspect.signature(type(storage).get_account_config)
        stocks_ok = stocks_ok and "market" in ac.parameters
    except Exception:  # noqa: BLE001
        stocks_ok = False

    if (
        biz_ok
        and stocks_ok
        and all(callable(getattr(storage, name, None)) for name in required)
    ):
        return storage  # type: ignore[return-value]

    importlib.reload(models_mod)
    storage_mod = importlib.reload(storage_mod)
    Latest = storage_mod.Storage
    _storage_singleton.clear()
    storage = _storage_singleton(STORAGE_CACHE_VERSION)

    for name in required:
        if not callable(getattr(storage, name, None)) and callable(
            getattr(Latest, name, None)
        ):
            setattr(
                storage,
                name,
                types.MethodType(getattr(Latest, name), storage),
            )
    return storage  # type: ignore[return-value]


def money(v: float) -> str:
    return f"{v:,.0f}"


def select_trade_account(
    storage: Storage,
    business_id: int,
    market: str,
    *,
    key: str,
    detected_name: str = "",
    help_text: str = "거래가 속할 증권사/계좌. FIFO 잔고는 증권사별로 분리됩니다.",
):
    """증권사 선택. 없으면 신규 생성."""
    accounts = storage.list_accounts(business_id, market=market)
    names = [a.name for a in accounts]
    create_opt = "➕ 증권사 직접 입력"
    options = [*names, create_opt] if names else [create_opt]
    default_idx = 0
    detected = (detected_name or "").strip()
    if detected and detected in names:
        default_idx = names.index(detected)
    elif detected:
        default_idx = options.index(create_opt)
    choice = st.selectbox(
        "증권사/계좌",
        options,
        index=min(default_idx, len(options) - 1),
        key=key,
        help=help_text,
    )
    if choice == create_opt:
        new_name = st.text_input(
            "증권사명",
            value=detected,
            key=f"{key}_new_name",
            placeholder="예: 키움증권",
        ).strip()
        if not new_name:
            return None
        return storage.get_or_create_account(
            int(business_id), new_name, market=market
        )
    return next((a for a in accounts if a.name == choice), None)


def persist_uploaded_file(widget_key: str, store_key: str) -> None:
    """업로더 on_change. Cloud가 위젯을 비워도 바이트는 남긴다."""
    up = st.session_state.get(widget_key)
    if up is None:
        return
    try:
        data = up.getvalue()
    except Exception:  # noqa: BLE001
        return
    st.session_state[store_key] = {
        "name": str(getattr(up, "name", None) or "upload"),
        "size": int(getattr(up, "size", 0) or len(data)),
        "bytes": data,
    }


def take_uploaded_file(widget, store_key: str) -> tuple[str | None, int, bytes | None]:
    """위젯 또는 저장된 파일. Cloud에서 위젯이 None이 되어도 복구."""
    if widget is not None:
        try:
            data = widget.getvalue()
        except Exception:  # noqa: BLE001
            data = None
        if data:
            name = str(getattr(widget, "name", None) or "upload")
            size = int(getattr(widget, "size", 0) or len(data))
            st.session_state[store_key] = {"name": name, "size": size, "bytes": data}
            return name, size, data
    saved = st.session_state.get(store_key) or {}
    data = saved.get("bytes")
    if data:
        return (
            str(saved.get("name") or "upload"),
            int(saved.get("size") or len(data)),
            data,
        )
    return None, 0, None


def show_uploaded_file(name: str | None, size: int = 0) -> None:
    if not name:
        return
    st.success(f"파일 선택됨: **{name}** ({int(size):,}바이트)")


def render_dedupe_controls(prefix: str) -> bool:
    """중복 제외가 기본. True면 중복도 강제 등록."""
    st.caption("같은 증권사·일자·종목·수량·단가·수수료는 중복으로 봅니다.")
    return st.checkbox(
        "중복 거래도 강제 등록",
        value=False,
        key=f"{prefix}_force_dup",
        help="기본은 신규만 등록합니다. 같은 행을 한 번 더 넣을 때만 선택하세요.",
    )


def save_trades_with_dedupe(
    storage: Storage,
    trades: list,
    *,
    market: str,
    force_duplicates: bool,
) -> tuple[int, int, int]:
    """신규 등록 건수, DB중복, 파일내부중복."""
    if not trades:
        return 0, 0, 0
    existing = storage.list_trades(
        business_id=trades[0].business_id,
        market=market,
        account_id=getattr(trades[0], "account_id", None),
    )
    classified = classify_trades(trades, existing)
    to_save = list(trades) if force_duplicates else classified.fresh
    if to_save:
        storage.add_trades_bulk(to_save)
    return len(to_save), classified.db_dup_count, classified.file_dup_count


def _is_opening_trade(trade) -> bool:
    return str(getattr(trade, "source", "") or "").strip().lower() in OPENING_TRADE_SOURCES


def _opening_cell_str(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:  # noqa: BLE001
        pass
    text = str(value).strip()
    if text.lower() in {"nan", "none", "nat"}:
        return ""
    return text


def _opening_cell_float(value) -> float:
    if value is None or value == "":
        return 0.0
    try:
        if pd.isna(value):
            return 0.0
    except Exception:  # noqa: BLE001
        pass
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = (
        str(value)
        .strip()
        .replace(",", "")
        .replace("주", "")
        .replace("원", "")
        .replace("$", "")
    )
    if not text:
        return 0.0
    return float(text)


def _opening_cell_date(value, fallback: date) -> str:
    from src.brokers.base import parse_trade_date

    parsed = parse_trade_date(value)
    if parsed:
        return parsed
    text = _opening_cell_str(value)
    if not text:
        return fallback.isoformat()
    parsed = parse_trade_date(text)
    return parsed or fallback.isoformat()


def _blank_opening_df(market: str, n: int = 8) -> pd.DataFrame:
    if normalize_market(market) == MARKET_OVERSEAS:
        return pd.DataFrame(
            {
                "취득일": [""] * n,
                "티커": [""] * n,
                "종목명": [""] * n,
                "수량": [0.0] * n,
                "외화단가": [0.0] * n,
                "환율": [0.0] * n,
                "통화": ["USD"] * n,
                "수수료(외화)": [0.0] * n,
            }
        )
    return pd.DataFrame(
        {
            "취득일": [""] * n,
            "종목명": [""] * n,
            "종목코드": [""] * n,
            "수량": [0] * n,
            "단가": [0] * n,
            "수수료": [0] * n,
        }
    )


def trade_table_column_config() -> dict:
    """거래 내역 테이블 숫자 컬럼 천단위 쉼표 포맷."""
    return {
        "수량": st.column_config.NumberColumn("수량", format="%,d"),
        "거래금액(원가)": st.column_config.NumberColumn(
            "거래금액(원가)", format="%,d 원", help="수량 × 단가"
        ),
        "단가": st.column_config.NumberColumn("단가", format="%,d 원"),
        "수수료": st.column_config.NumberColumn("수수료", format="%,d 원"),
        "제세금": st.column_config.NumberColumn("제세금", format="%,d 원"),
        "정산금액": st.column_config.NumberColumn("정산금액", format="%,d 원"),
        "ID": st.column_config.NumberColumn("ID", format="%d"),
    }


def _filter_stock_trades(
    trades: list,
    *,
    stock_name: str,
    business_name: str = "",
) -> pd.DataFrame:
    trades_df = trades_to_dataframe(trades)
    if trades_df.empty:
        return trades_df
    detail = trades_df.copy()
    if "종목명" in detail.columns:
        detail = detail[detail["종목명"].astype(str) == stock_name]
    if business_name and "사업자" in detail.columns:
        detail = detail[detail["사업자"].astype(str) == business_name]
    detail = detail.drop(columns=["출처"], errors="ignore")
    # 핫리로드 stale 모듈 대비: 원가 컬럼 없으면 수량×단가로 즉시 생성
    if "거래금액(원가)" not in detail.columns and {"수량", "단가"}.issubset(detail.columns):
        detail["거래금액(원가)"] = (
            pd.to_numeric(detail["수량"], errors="coerce").fillna(0)
            * pd.to_numeric(detail["단가"], errors="coerce").fillna(0)
        )
    for col in ("수량", "거래금액(원가)", "단가", "수수료", "제세금", "정산금액", "ID"):
        if col in detail.columns:
            detail[col] = pd.to_numeric(detail[col], errors="coerce")

    # 팝업: 시간순 정렬 (거래일자 → 거래일시 → ID)
    detail = _sort_trades_chronologically(detail)
    return detail.reset_index(drop=True)


def _sort_trades_chronologically(df: pd.DataFrame) -> pd.DataFrame:
    """거래일자·거래일시(있으면)·매수우선·ID 기준 오름차순.

    DB에 거래일시가 없어도, 시간순으로 넣은 거래는 ID 순서가 시간순에 대응한다.
    동일 일자에는 매수가 매도보다 먼저 오도록 한다.
    """
    if df is None or df.empty:
        return df
    work = df.copy()
    sort_by: list[str] = []
    drop_tmp: list[str] = []

    if "거래일자" in work.columns:
        work["_sort_date"] = pd.to_datetime(work["거래일자"], errors="coerce")
        sort_by.append("_sort_date")
        drop_tmp.append("_sort_date")

    if "거래일시" in work.columns:
        work["_sort_time"] = (
            work["거래일시"].fillna("00:00:00").astype(str).str.strip()
        )
        work.loc[
            work["_sort_time"].isin({"", "nan", "None", "NaT"}),
            "_sort_time",
        ] = "00:00:00"
        sort_by.append("_sort_time")
        drop_tmp.append("_sort_time")

    # 매수(0) → 매도(1)
    side_col = "거래유형" if "거래유형" in work.columns else None
    if side_col:
        work["_sort_side"] = work[side_col].map(
            lambda v: 0
            if ("매수" in str(v) or "매입" in str(v) or "입고" in str(v))
            else 1
        )
        sort_by.append("_sort_side")
        drop_tmp.append("_sort_side")

    if "ID" in work.columns:
        sort_by.append("ID")

    if not sort_by:
        return work

    work = work.sort_values(by=sort_by, ascending=True, kind="mergesort")
    return work.drop(columns=drop_tmp, errors="ignore")


DETAIL_TRADE_COLUMNS = [
    "거래일자",
    "종목명",
    "거래유형",
    "수량",
    "거래금액(원가)",
    "단가",
    "수수료",
    "제세금",
    "정산금액",
    "메모",
]


def _normalize_trade_date(value) -> str | None:
    """data_editor 날짜 값을 YYYY-MM-DD 문자열로 변환."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if hasattr(value, "isoformat") and not isinstance(value, str):
        try:
            return value.isoformat()[:10]
        except Exception:  # noqa: BLE001
            pass
    text = str(value).strip()
    if not text or text.lower() == "nat":
        return None
    parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date().isoformat()


def _dismiss_stock_detail_modal() -> None:
    """종목 상세 다이얼로그 닫힘 시 pending 제거 (query clear 후 rerun에서도 유지하다가 해제)."""
    st.session_state.pop("_pending_stock_detail", None)


def _highlight_trade_type(val) -> str:
    """종목 상세 표의 거래유형 글자색."""
    text = str(val).strip() if val is not None and not (isinstance(val, float) and pd.isna(val)) else ""
    if text == "매수":
        return "color: #dc2626; font-weight: 700;"
    if text == "매도":
        return "color: #2563eb; font-weight: 700;"
    if text == "배당":
        return "color: #16a34a; font-weight: 700;"
    return ""


@st.dialog(
    "📊 종목 상세 거래 내역",
    width="large",
    on_dismiss=_dismiss_stock_detail_modal,
)
def show_stock_detail_modal(
    storage: Storage,
    stock_name: str,
    df_stock_trades: pd.DataFrame,
    business_name: str = "",
) -> None:
    st.markdown(f"**종목명:** {stock_name}")
    if business_name:
        st.caption(f"사업자: {business_name}")

    if df_stock_trades is None or df_stock_trades.empty:
        st.info("해당 종목의 거래 내역이 없습니다.")
        return

    if "ID" not in df_stock_trades.columns:
        st.error("거래 ID가 없어 일자를 수정할 수 없습니다.")
        return

    display_cols = [c for c in DETAIL_TRADE_COLUMNS if c in df_stock_trades.columns]
    # 팝업 표시 직전 시간순 재정렬
    sorted_src = _sort_trades_chronologically(df_stock_trades)
    work = sorted_src.loc[:, [c for c in [*display_cols, "ID"] if c in sorted_src.columns]].copy()
    work["거래일자"] = pd.to_datetime(work["거래일자"], errors="coerce").dt.date
    work["ID"] = pd.to_numeric(work["ID"], errors="coerce").astype("Int64")
    original_dates = {
        int(tid): _normalize_trade_date(dt)
        for tid, dt in zip(work["ID"], work["거래일자"])
        if pd.notna(tid)
    }

    # 조회용 표: 매수(빨강) / 매도(파랑) / 배당(초록)
    view = work.loc[:, [c for c in display_cols if c in work.columns]].copy()
    detail_col_config = {
        "거래일자": st.column_config.DateColumn("거래일자", format="YYYY-MM-DD"),
        "수량": st.column_config.NumberColumn("수량", format="%,d"),
        "거래금액(원가)": st.column_config.NumberColumn(
            "거래금액(원가)", format="%,d 원", help="수량 × 단가"
        ),
        "단가": st.column_config.NumberColumn("단가", format="%,d 원"),
        "수수료": st.column_config.NumberColumn("수수료", format="%,d 원"),
        "제세금": st.column_config.NumberColumn("제세금", format="%,d 원"),
        "정산금액": st.column_config.NumberColumn("정산금액", format="%,d 원"),
    }
    if "거래유형" in view.columns:
        styled_df = view.style.map(_highlight_trade_type, subset=["거래유형"])
    else:
        styled_df = view
    st.dataframe(
        styled_df,
        use_container_width=True,
        hide_index=True,
        column_config=detail_col_config,
    )

    # data_editor는 Styler 색상을 지원하지 않아, 일자 수정만 별도 편집기로 유지
    with st.expander("✏️ 거래일자 수정", expanded=False):
        edit_cols = [c for c in ("거래일자", "거래유형", "ID") if c in work.columns]
        edited = st.data_editor(
            work.loc[:, edit_cols],
            use_container_width=True,
            hide_index=True,
            num_rows="fixed",
            disabled=[c for c in edit_cols if c != "거래일자"],
            column_config={
                "거래일자": st.column_config.DateColumn(
                    "거래일자",
                    format="YYYY-MM-DD",
                    required=True,
                ),
                "ID": st.column_config.NumberColumn("ID", format="%d"),
            },
            key=f"stock_detail_editor_{business_name}_{stock_name}",
        )

        if st.button("💾 수정사항 저장", type="primary", use_container_width=True):
            try:
                db = get_storage()
                updated = 0
                for _, row in edited.iterrows():
                    if pd.isna(row.get("ID")):
                        continue
                    trade_id = int(row["ID"])
                    new_date = _normalize_trade_date(row.get("거래일자"))
                    if not new_date:
                        st.error(f"거래 ID {trade_id}: 거래일자가 비어 있습니다.")
                        return
                    if original_dates.get(trade_id) == new_date:
                        continue
                    db.update_trade_date(trade_id, new_date)
                    updated += 1

                if updated == 0:
                    st.info("변경된 거래일자가 없습니다.")
                    return

                st.session_state["_pending_toast"] = "거래일자가 수정되었습니다."
                st.toast("거래일자가 수정되었습니다.")
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(str(exc))


def _open_stock_detail_from_query(storage: Storage, trades: list) -> None:
    """세션에 쌓인 종목 상세 요청(_pending_stock_detail)으로 모달을 연다.

    query_params.clear()로 추가 rerun이 나더라도 pending을 pop하지 않고
    다이얼로그 dismiss 때까지 유지한다.
    """
    pending = st.session_state.get("_pending_stock_detail")
    if not pending and "stock" in st.query_params:
        consume_stock_click_query()
        pending = st.session_state.get("_pending_stock_detail")
    if not pending:
        return

    stock_name = str(pending.get("stock") or "").strip()
    biz_name = str(pending.get("biz") or "").strip()
    if not stock_name:
        st.session_state.pop("_pending_stock_detail", None)
        return

    # 모달을 여는 매 렌더마다 메뉴/시장 컨텍스트 재고정
    menu = pending.get("menu")
    if menu in ALL_MENU_KEYS:
        st.session_state.active_menu = menu
        st.session_state.active_category = (
            "income" if menu == "income" else "work"
        )
        mkt = menu_market(menu)
        if mkt:
            st.session_state.active_market = mkt
    if biz_name and st.session_state.get("sidebar_business") != biz_name:
        # 사이드바 렌더 이후이므로 다음 rerun용 pending만 남김
        st.session_state._pending_business_label = biz_name

    detail = _filter_stock_trades(
        trades,
        stock_name=stock_name,
        business_name=biz_name,
    )
    show_stock_detail_modal(
        storage,
        stock_name,
        detail,
        business_name=biz_name,
    )


def _render_holdings_html_table(
    pos_df: pd.DataFrame,
    *,
    active_menu: str | None = None,
    market: str | None = None,
) -> None:
    """체크박스 없는 컴팩트 HTML 보유 잔고 표 (종목명 클릭 → query_params)."""
    rows: list[str] = []
    sum_qty = 0.0
    sum_cost = 0.0
    sum_pnl = 0.0

    menu = active_menu or st.session_state.get("active_menu", "ledger")
    mkt = market or menu_market(menu) or MARKET_DOMESTIC

    for _, row in pos_df.iterrows():
        biz = str(row.get("사업자", "")).strip()
        stock = str(row.get("종목명", "")).strip()
        qty = float(row.get("잔여수량", 0) or 0)
        cost = float(row.get("원가잔액", 0) or 0)
        pnl = float(row.get("누적실현손익", 0) or 0)
        sum_qty += qty
        sum_cost += cost
        sum_pnl += pnl

        # 메뉴·시장·사업자를 URL에 실어 세션 유실 시에도 복원 가능하게 함
        href = (
            f"?stock={quote(stock)}"
            f"&menu={quote(str(menu))}"
            f"&market={quote(normalize_market(mkt))}"
            f"&market_type={quote(_market_type_param(mkt) or 'DOMESTIC')}"
        )
        if biz:
            href += f"&biz={quote(biz)}"
        active_bid = st.session_state.get("active_business_id")
        if active_bid is not None:
            href += f"&business_id={int(active_bid)}"
        elif biz:
            # 행 사업자명으로 ID를 알 수 있으면 첨부 (전체 보기일 때)
            id_by_name = st.session_state.get("_biz_id_by_name") or {}
            row_bid = id_by_name.get(biz)
            if row_bid is not None:
                href += f"&business_id={int(row_bid)}"
        stock_link = (
            f'<a href="{html.escape(href)}" target="_self">'
            f"{html.escape(stock or '-')}</a>"
        )
        broker = str(row.get("증권사", "")).strip()
        rows.append(
            "<tr>"
            f"<td class='stock'>{stock_link}</td>"
            f"<td>{html.escape(broker or '-')}</td>"
            f"<td class='num'>{qty:,.0f} 주</td>"
            f"<td class='num'>{cost:,.0f} 원</td>"
            f"<td class='num'>{pnl:,.0f} 원</td>"
            "</tr>"
        )

    footer = (
        "<tr class='total'>"
        "<td>합계</td>"
        "<td></td>"
        f"<td class='num'>{sum_qty:,.0f} 주</td>"
        f"<td class='num'>{sum_cost:,.0f} 원</td>"
        f"<td class='num'>{sum_pnl:,.0f} 원</td>"
        "</tr>"
    )

    table_html = f"""
    <style>
    .holdings-html-wrap {{
        width: 100%;
        overflow-x: auto;
        margin: 0.25rem 0 0.75rem 0;
    }}
    table.holdings-html {{
        width: 100%;
        border-collapse: collapse;
        font-size: 0.875rem;
        line-height: 1.35;
        color: inherit;
    }}
    table.holdings-html th,
    table.holdings-html td {{
        padding: 0.4rem 0.65rem;
        border-bottom: 1px solid rgba(49, 51, 63, 0.18);
        text-align: left;
        vertical-align: middle;
        white-space: nowrap;
    }}
    table.holdings-html th {{
        font-weight: 600;
        opacity: 0.85;
    }}
    table.holdings-html td.num {{
        text-align: right;
        font-variant-numeric: tabular-nums;
    }}
    table.holdings-html td.stock a {{
        color: #1c83e1;
        text-decoration: none;
        font-weight: 600;
    }}
    table.holdings-html td.stock a:hover {{
        text-decoration: underline;
    }}
    table.holdings-html tbody tr:hover {{
        background: rgba(28, 131, 225, 0.06);
    }}
    table.holdings-html tfoot tr.total td {{
        font-weight: 700;
        border-top: 2px solid rgba(49, 51, 63, 0.35);
        border-bottom: none;
        padding-top: 0.55rem;
        background: rgba(49, 51, 63, 0.04);
    }}
    </style>
    <div class="holdings-html-wrap">
      <table class="holdings-html">
        <thead>
          <tr>
            <th>종목명</th>
            <th>증권사</th>
            <th>잔여수량</th>
            <th>원가잔액</th>
            <th>누적실현손익</th>
          </tr>
        </thead>
        <tbody>
          {''.join(rows)}
        </tbody>
        <tfoot>
          {footer}
        </tfoot>
      </table>
    </div>
    """
    st.markdown(table_html, unsafe_allow_html=True)


def refresh_fifo(
    storage: Storage,
    business_id: int | None = None,
    market: str | None = None,
    account_id: int | None = None,
):
    trades = storage.list_trades(
        business_id=business_id, market=market, account_id=account_id
    )
    return compute_positions(trades), trades


WORK_MENU_ITEMS = [
    ("setup", "1. 준비"),
    ("ingest", "2. 거래 넣기"),
    ("ledger", "3. 잔고·손익"),
    ("voucher", "4. 회계전표"),
]
EXTRA_MENU_ITEMS = [
    ("income", "이자·배당"),
    ("codes", "계정코드"),
]
WORK_MENU_KEYS = {k for k, _ in WORK_MENU_ITEMS}
MARKET_MENU_KEYS = WORK_MENU_KEYS | {"codes"}
INCOME_MENU_KEYS = {"income"}
ALL_MENU_KEYS = MARKET_MENU_KEYS | INCOME_MENU_KEYS
DEFAULT_MENU = "ledger"
INGEST_METHODS = (
    "증권사 파일",
    "기초데이터",
    "표준 엑셀",
    "예전 매매일지",
    "직접 입력",
)
OPENING_TRADE_SOURCES = frozenset({"opening", "base"})

MENU_PAGE_META: dict[str, tuple[str, str]] = {
    "setup": ("준비", "증권사·종목 마스터"),
    "ingest": ("거래 넣기", "기초잔고 · 파일 업로드 · 직접 입력"),
    "ledger": ("잔고·손익", "보유 잔고 · FIFO · 처분손익"),
    "voucher": ("회계전표", "기간별 전표 다운로드"),
    "income": ("이자·배당소득", "원천징수 업로드 · 전표"),
    "codes": ("계정코드", "전표용 계정과목 · 거래처코드"),
}

STEP_GUIDES: dict[str, tuple[str, str, str, str]] = {
    "setup": (
        "1/4 준비",
        "증권사(계좌)와 종목을 등록합니다. 없으면 올린 거래는 '미지정'으로 들어갑니다.",
        "ingest",
        "다음: 거래 넣기",
    ),
    "ingest": (
        "2/4 거래 넣기",
        "사용 전 보유분은 기초데이터로 넣고, 이후 거래는 증권사 파일·엑셀·직접 입력으로 넣으세요.",
        "ledger",
        "다음: 잔고·손익",
    ),
    "ledger": (
        "3/4 잔고·손익",
        "FIFO 잔고와 처분손익을 확인합니다. 같은 종목이어도 증권사별로 행이 갈립니다.",
        "voucher",
        "다음: 회계전표",
    ),
    "voucher": (
        "4/4 회계전표",
        "적요 형식과 기간을 골라 회계 전표를 받습니다. 계정코드가 비었으면 먼저 계정코드를 저장하세요.",
        "codes",
        "계정코드 확인",
    ),
    "income": (
        "이자·배당",
        "원천징수 파일을 올리고 전표를 받습니다. 계정코드는 아래 메뉴에서 관리합니다.",
        "codes",
        "계정코드",
    ),
    "codes": (
        "계정코드",
        "전표에 들어갈 계정과목과 거래처코드를 저장합니다.",
        "voucher",
        "회계전표로",
    ),
}

# 구 라벨/세션/URL 값 → 새 active_menu 키
_LEGACY_TO_MENU: dict[str, str] = {
    "setup": "setup",
    "ingest": "ingest",
    "ledger": "ledger",
    "voucher": "voucher",
    "income": "income",
    "codes": "codes",
    "dashboard": "ledger",
    "trade_input": "ingest",
    "import_export": "voucher",
    "converter": "ingest",
    "base_data": "ingest",
    "stock_masters": "setup",
    "stock_settings": "codes",
    "domestic_dashboard": "ledger",
    "overseas_dashboard": "ledger",
    "domestic_trade_input": "ingest",
    "overseas_trade_input": "ingest",
    "domestic_import_export": "voucher",
    "overseas_import_export": "voucher",
    "domestic_converter": "ingest",
    "overseas_converter": "ingest",
    "domestic_base_data": "ingest",
    "overseas_base_data": "ingest",
    "domestic_stock_masters": "setup",
    "overseas_stock_masters": "setup",
    "domestic_stock_settings": "codes",
    "overseas_stock_settings": "codes",
    "interest_list": "income",
    "interest_settings": "codes",
    "대시보드": "ledger",
    "📊 대시보드": "ledger",
    "매매 입력": "ingest",
    "📝 매매 입력": "ingest",
    "Import / Export": "voucher",
    "📤 Import / Export": "voucher",
    "증권사 변환기": "ingest",
    "🔄 증권사 변환기": "ingest",
    "기초 데이터 등록": "ingest",
    "📋 기초 데이터 등록": "ingest",
    "거래처 및 종목 관리": "setup",
    "🏢 거래처 및 종목 관리": "setup",
    "환경설정 (주식)": "codes",
    "⚙️ 환경설정 (주식)": "codes",
    "⚙️ 환경설정 (주식 계정코드)": "codes",
    "⚙️ 환경설정 (국내주식 계정코드)": "codes",
    "⚙️ 환경설정 (해외주식 계정코드)": "codes",
    "환경설정 / 계정과목 관리": "codes",
    "⚙️ 환경설정 (계정과목 코드)": "codes",
    "내역 업로드·전표": "income",
    "📄 이자·배당 내역 및 전표": "income",
    "환경설정 (이자·배당)": "codes",
    "⚙️ 거래처 및 계정과목 설정": "codes",
}

NEW_STOCK_OPTION = "➕ 신규 종목 직접 입력"


def current_market() -> str:
    return normalize_market(st.session_state.get("active_market") or MARKET_DOMESTIC)


def menu_market(menu: str) -> str | None:
    """작업 메뉴는 시장 스위치 값을 쓰고, 이자·배당은 시장이 없다."""
    if menu in MARKET_MENU_KEYS:
        return current_market()
    return None


def _legacy_market_hint(raw: str) -> str | None:
    text = str(raw or "")
    lowered = text.lower()
    if "overseas" in lowered or "해외" in text:
        return MARKET_OVERSEAS
    if "domestic" in lowered or "국내" in text:
        return MARKET_DOMESTIC
    return None


def market_label(market: str) -> str:
    return "해외주식" if normalize_market(market) == MARKET_OVERSEAS else "국내주식"


def _market_type_param(market: str | None) -> str | None:
    """세션 시장값 → URL market_type (DOMESTIC|OVERSEAS)."""
    if not market:
        return None
    return (
        "OVERSEAS"
        if normalize_market(market) == MARKET_OVERSEAS
        else "DOMESTIC"
    )


def sync_url_params() -> None:
    """세션의 사업자·메뉴·시장을 URL 쿼리에 반영 (값이 다를 때만 갱신)."""
    # business_id
    bid = st.session_state.get("active_business_id")
    desired_biz = "all" if bid is None else str(int(bid))
    if str(st.query_params.get("business_id", "") or "") != desired_biz:
        st.query_params["business_id"] = desired_biz

    # menu
    menu = str(st.session_state.get("active_menu") or DEFAULT_MENU)
    if menu in ALL_MENU_KEYS and str(st.query_params.get("menu", "") or "") != menu:
        st.query_params["menu"] = menu

    # market_type (메뉴에서 유도, 이자 메뉴는 마지막 active_market 유지)
    mkt = menu_market(menu) or st.session_state.get("active_market")
    desired_mt = _market_type_param(mkt)
    if desired_mt and str(st.query_params.get("market_type", "") or "") != desired_mt:
        st.query_params["market_type"] = desired_mt


def sync_business_to_query(business_id: int | None) -> None:
    """선택 사업자를 URL ?business_id= 에 반영 (F5 복원용). 전체는 all."""
    desired = "all" if business_id is None else str(int(business_id))
    current = str(st.query_params.get("business_id", "") or "")
    if current != desired:
        st.query_params["business_id"] = desired
    # 메뉴·시장도 함께 유지
    sync_url_params()


def restore_business_from_query(
    businesses: list,
) -> tuple[str, int | None] | None:
    """URL business_id → (라벨, id). 유효하지 않으면 None."""
    if "business_id" not in st.query_params:
        return None
    raw = str(st.query_params.get("business_id", "") or "").strip().lower()
    if raw in {"", "all", "none", "null"}:
        return ("전체", None)
    if not raw.isdigit():
        return None
    bid = int(raw)
    match = next((b for b in businesses if int(b.id) == bid), None)
    if match is None:
        return None
    return (match.name, int(match.id))


def _restore_menu_from_query() -> str | None:
    """URL menu → 유효한 active_menu 키. 없거나 무효면 None."""
    raw = str(st.query_params.get("menu", "") or "").strip()
    if not raw:
        return None
    hint = _legacy_market_hint(raw)
    if hint:
        st.session_state.active_market = hint
    mapped = _LEGACY_TO_MENU.get(raw, raw)
    if mapped in ALL_MENU_KEYS:
        return mapped
    return None


def _restore_market_from_query() -> str | None:
    """URL market_type|market → domestic|overseas."""
    raw = str(
        st.query_params.get("market_type")
        or st.query_params.get("market")
        or ""
    ).strip()
    if not raw:
        return None
    return normalize_market(raw)


def consume_stock_click_query() -> None:
    """보유잔고 종목 클릭(?stock=…) 시 메뉴·사업자·시장 세션을 먼저 복원한다.

    query_params 네비게이션으로 세션이 비어도 URL에 실린 컨텍스트로
    해외/국내 메뉴와 사업자가 기본값으로 덮이지 않도록 한다.
    """
    if "stock" not in st.query_params:
        return

    stock_name = str(st.query_params.get("stock", "") or "").strip()
    biz_name = str(st.query_params.get("biz", "") or "").strip()
    menu = str(st.query_params.get("menu", "") or "").strip()
    market_raw = str(
        st.query_params.get("market")
        or st.query_params.get("market_type")
        or ""
    ).strip()
    # F5 유지용 파라미터는 clear 대상에서 제외
    kept_business_id = str(st.query_params.get("business_id", "") or "").strip()
    kept_menu = menu
    kept_market_type = str(st.query_params.get("market_type", "") or "").strip()

    mapped_menu = _LEGACY_TO_MENU.get(menu, menu)
    hint = _legacy_market_hint(menu)
    if hint:
        st.session_state.active_market = hint
    if mapped_menu in ALL_MENU_KEYS:
        st.session_state.active_menu = mapped_menu
        kept_menu = mapped_menu
    elif market_raw:
        mkt = normalize_market(market_raw)
        st.session_state.active_menu = "ledger"
        st.session_state.active_market = mkt
        kept_menu = "ledger"
    elif st.session_state.get("active_menu") not in ALL_MENU_KEYS:
        pass

    if market_raw:
        st.session_state.active_market = normalize_market(market_raw)

    if biz_name:
        st.session_state.sidebar_business = biz_name
        st.session_state._pending_business_label = biz_name
    elif kept_business_id and kept_business_id.isdigit():
        st.session_state.active_business_id = int(kept_business_id)

    if stock_name:
        st.session_state["_pending_stock_detail"] = {
            "stock": stock_name,
            "biz": biz_name,
            "menu": st.session_state.get("active_menu"),
            "market": market_raw or (
                menu_market(st.session_state.get("active_menu", "")) or ""
            ),
        }

    # 종목 클릭 일회성 파라미터만 제거 (menu / market_type / business_id 유지)
    for key in ("stock", "biz", "market"):
        if key in st.query_params:
            del st.query_params[key]
    if kept_business_id and str(st.query_params.get("business_id", "") or "") != kept_business_id:
        st.query_params["business_id"] = kept_business_id
    if kept_menu in ALL_MENU_KEYS and str(st.query_params.get("menu", "") or "") != kept_menu:
        st.query_params["menu"] = kept_menu
    if kept_market_type and str(st.query_params.get("market_type", "") or "") != kept_market_type:
        st.query_params["market_type"] = kept_market_type


def init_session_state() -> None:
    # 종목 클릭 URL 컨텍스트를 기본값 적용보다 먼저 복원
    consume_stock_click_query()

    if "active_business_id" not in st.session_state:
        st.session_state.active_business_id = None

    from_query = _restore_menu_from_query()
    if from_query:
        st.session_state.active_menu = from_query
    elif "active_menu" not in st.session_state:
        # URL이 없을 때만 옛 세션 키를 새 메뉴로 옮긴다.
        candidates = [
            st.session_state.get("stock_sub_menu"),
            st.session_state.get("interest_sub_menu"),
            st.session_state.get("stock_sub_page"),
            st.session_state.get("income_sub_page"),
            st.session_state.get("active_page"),
            st.session_state.get("main_category_radio"),
            st.session_state.get("main_menu"),
        ]
        resolved = DEFAULT_MENU
        for raw in candidates:
            if raw is None:
                continue
            hint = _legacy_market_hint(str(raw))
            if hint:
                st.session_state.active_market = hint
            mapped = _LEGACY_TO_MENU.get(str(raw))
            if mapped in ALL_MENU_KEYS:
                resolved = mapped
                break
            if str(raw) in ALL_MENU_KEYS:
                resolved = str(raw)
                break
            if "이자" in str(raw) or "배당" in str(raw):
                resolved = "income"
                break
            if "해외" in str(raw):
                resolved = DEFAULT_MENU
                st.session_state.active_market = MARKET_OVERSEAS
                break
        st.session_state.active_menu = resolved

    cur = st.session_state.get("active_menu")
    if cur in _LEGACY_TO_MENU:
        hint = _legacy_market_hint(str(cur))
        if hint:
            st.session_state.active_market = hint
        st.session_state.active_menu = _LEGACY_TO_MENU[cur]
    if st.session_state.get("active_menu") not in ALL_MENU_KEYS:
        st.session_state.active_menu = DEFAULT_MENU

    st.session_state.active_category = (
        "income" if st.session_state.active_menu == "income" else "work"
    )
    from_mkt = _restore_market_from_query()
    if from_mkt:
        st.session_state.active_market = from_mkt
    elif "active_market" not in st.session_state:
        st.session_state.active_market = MARKET_DOMESTIC

    # 호환 키 (프롬프트의 market_type)
    if st.session_state.get("active_market"):
        st.session_state.market_type = _market_type_param(
            st.session_state.active_market
        )

    st.session_state.pop("_force_page", None)

def _clear_force_page() -> None:
    st.session_state.pop("_force_page", None)


def set_active_business(business_id: int | None, business_name: str | None = None) -> None:
    """활성 사업자 ID를 갱신하고, 다음 렌더에서 사이드바 선택을 반영."""
    st.session_state.active_business_id = business_id
    if business_name is not None:
        st.session_state._pending_business_label = business_name
    elif business_id is None:
        st.session_state._pending_business_label = "전체"
    sync_business_to_query(business_id)


def _on_sidebar_business_change() -> None:
    """사이드바 사업자 selectbox 변경 → 세션 + URL 동기화."""
    label = str(st.session_state.get("sidebar_business", "전체") or "전체")
    businesses = st.session_state.get("_biz_id_by_name") or {}
    if label == "전체":
        st.session_state.active_business_id = None
        sync_business_to_query(None)
        return
    bid = businesses.get(label)
    if bid is not None:
        st.session_state.active_business_id = int(bid)
        sync_business_to_query(int(bid))


@st.dialog("⚙️ 사업자 관리")
def manage_business_modal(
    storage: Storage,
    current_biz_id: int | None = None,
) -> None:
    """사업자 명칭 수정 및 삭제."""
    # 다이얼로그는 옛 Storage를 들고 있을 수 있어 항상 최신 인스턴스 사용
    db = get_storage()
    businesses = db.list_businesses()
    if not businesses:
        st.info("등록된 사업자가 없습니다. ＋ 버튼으로 추가해 주세요.")
        return

    st.caption("등록된 사업자 명칭을 수정하거나 삭제할 수 있습니다.")

    biz_by_id = {int(b.id): b for b in businesses if b.id is not None}  # type: ignore[arg-type]
    options = list(biz_by_id.keys())
    default_idx = 0
    if current_biz_id is not None and int(current_biz_id) in biz_by_id:
        default_idx = options.index(int(current_biz_id))

    selected_id = st.selectbox(
        "대상 사업자 선택",
        options=options,
        index=default_idx,
        format_func=lambda x: biz_by_id[int(x)].name,
        key="manage_biz_select",
    )
    selected = biz_by_id[int(selected_id)]
    current_name = selected.name

    st.divider()
    st.subheader("✏️ 사업자명 수정")
    new_name = st.text_input(
        "새 사업자 명칭",
        value=current_name,
        key=f"edit_biz_name_{selected_id}",
    )
    if st.button("💾 명칭 수정 저장", use_container_width=True, type="primary"):
        try:
            name = (new_name or "").strip()
            if not name:
                st.error("사업자명을 입력해 주세요.")
            elif name == current_name:
                st.warning("기존 명칭과 동일합니다.")
            elif any(
                b.name == name and int(b.id) != int(selected_id)
                for b in businesses
                if b.id is not None
            ):
                st.error("이미 사용 중인 사업자명입니다.")
            else:
                db.update_business(
                    int(selected_id),
                    name,
                    note=getattr(selected, "note", "") or "",
                    code=getattr(selected, "code", "") or "",
                    account_no=getattr(selected, "account_no", "") or "",
                )
                if st.session_state.get("active_business_id") == int(selected_id):
                    set_active_business(int(selected_id), name)
                st.session_state["_pending_toast"] = (
                    f"사업자명이 '{name}'(으)로 변경되었습니다."
                )
                st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))

    st.divider()
    st.subheader("🗑️ 사업자 삭제")
    st.caption(
        "⚠️ 사업자를 삭제하면 해당 사업자의 모든 매매 내역·잔고·이자/배당 데이터가 "
        "함께 삭제됩니다. 이 작업은 되돌릴 수 없습니다."
    )
    confirm_delete = st.checkbox(
        f"[{current_name}] 삭제를 확인했습니다.",
        key=f"confirm_delete_chk_{selected_id}",
    )
    if st.button(
        "🚨 사업자 삭제",
        use_container_width=True,
        disabled=not confirm_delete,
        key=f"manage_biz_delete_{selected_id}",
    ):
        try:
            db.delete_entity(int(selected_id))
            # 삭제한 사업자가 현재 선택이면 전체로 전환 (menu/market URL은 유지)
            if st.session_state.get("active_business_id") == int(selected_id):
                set_active_business(None, "전체")
            st.session_state["_pending_toast"] = (
                f"'{current_name}' 사업자가 삭제되었습니다."
            )
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))

    st.divider()
    st.subheader("거래 삭제")
    trade_n = len(db.list_trades(business_id=int(selected_id)))
    st.caption(
        f"매매 거래만 지웁니다. 종목·증권사 마스터와 이자·배당은 남습니다. "
        f"지금 {trade_n:,}건."
    )
    if st.button(
        "선택 사업자 거래 삭제",
        use_container_width=True,
        type="secondary",
        key="manage_biz_clear_trades",
        disabled=trade_n == 0,
    ):
        confirm_clear_business_trades_dialog(db, int(selected_id), current_name)


def sidebar_business_selector(storage: Storage) -> int | None:
    businesses = storage.list_businesses()
    labels = ["전체", *[b.name for b in businesses]]
    id_by_name = {b.name: b.id for b in businesses}
    # on_change 콜백에서 이름→ID 해석용
    st.session_state._biz_id_by_name = id_by_name

    # 세션이 비어 있을 때만 URL → 세션 복원 (F5). 매 렌더 적용 시 selectbox 변경을 덮어씀.
    if "sidebar_business" not in st.session_state:
        restored = restore_business_from_query(businesses)
        if restored is not None:
            label_from_q, bid_from_q = restored
            st.session_state.sidebar_business = label_from_q
            st.session_state.active_business_id = bid_from_q
        elif businesses:
            st.session_state.sidebar_business = businesses[0].name
            st.session_state.active_business_id = businesses[0].id
        else:
            st.session_state.sidebar_business = "전체"
            st.session_state.active_business_id = None

    # 등록/삭제·종목클릭 직후 강제 지정된 라벨 적용 (selectbox 생성 전에만)
    pending = st.session_state.pop("_pending_business_label", None)
    if pending is not None and pending in labels:
        st.session_state.sidebar_business = pending

    # 삭제된 사업자 등이 남아 있으면 보정
    if st.session_state.get("sidebar_business") not in labels:
        if businesses:
            st.session_state.sidebar_business = businesses[0].name
        else:
            st.session_state.sidebar_business = "전체"

    st.sidebar.subheader("🏢 사업자 관리")
    sel_col, add_col, cfg_col = st.sidebar.columns([4, 1, 1])
    with sel_col:
        label = st.selectbox(
            "사업자 선택",
            labels,
            key="sidebar_business",
            label_visibility="collapsed",
            on_change=_on_sidebar_business_change,
        )
    with add_col:
        with st.popover("＋"):
            st.caption("새 사업자 추가")
            new_biz = st.text_input(
                "사업자명",
                placeholder="예: 사업자 A",
                key="popover_new_business",
                label_visibility="collapsed",
            )
            if st.button("추가", type="primary", use_container_width=True, key="popover_add_biz"):
                try:
                    name = new_biz.strip()
                    if not name:
                        st.error("사업자명을 입력하세요.")
                    else:
                        bid = storage.add_business(name)
                        set_active_business(bid, name)
                        if "popover_new_business" in st.session_state:
                            del st.session_state["popover_new_business"]
                        st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(str(exc))

    if label == "전체":
        st.session_state.active_business_id = None
        selected_id = None
    else:
        selected_id = id_by_name[label]
        st.session_state.active_business_id = selected_id

    can_manage = bool(businesses)
    with cfg_col:
        if st.button(
            "⚙️",
            use_container_width=True,
            disabled=not can_manage,
            key="sidebar_manage_biz",
            help="사업자 수정·삭제, 거래 삭제" if can_manage else "사업자를 먼저 추가하세요",
        ):
            manage_business_modal(storage, current_biz_id=selected_id)

    # URL과 세션 최종 동기화 (콜백 외 경로·최초 진입 포함)
    sync_business_to_query(selected_id)
    return selected_id


@st.dialog("🗑️ 선택 사업자 거래 삭제")
def confirm_clear_business_trades_dialog(
    storage: Storage,
    business_id: int,
    business_name: str,
) -> None:
    """현재 선택 사업자의 매매 거래만 삭제 (종목·사업자 마스터는 유지)."""
    db = get_storage()
    trades = db.list_trades(business_id=int(business_id))
    st.warning(
        f"**[{business_name}]** 사업자의 매매 거래 **{len(trades):,}건**을 삭제합니다.\n\n"
        "사업자·종목 마스터와 이자·배당 내역은 유지됩니다. 되돌릴 수 없습니다."
    )
    confirm = st.checkbox(
        "위 안내를 확인했으며 삭제를 진행합니다.",
        key=f"confirm_clear_trades_{business_id}",
    )
    c1, c2 = st.columns(2)
    with c1:
        if st.button("취소", use_container_width=True, key="clear_trades_cancel"):
            st.rerun()
    with c2:
        if st.button(
            "🗑️ 삭제 실행",
            type="primary",
            use_container_width=True,
            disabled=not confirm,
            key="clear_trades_confirm",
        ):
            try:
                n = db.clear_trades_for_business(int(business_id))
                st.session_state["_pending_toast"] = (
                    f"[{business_name}] 거래 {n:,}건이 삭제되었습니다."
                )
                # 증권사 변환기 임시 상태도 비움
                for k in (
                    "broker_edit_df",
                    "broker_parse_token",
                    "broker_parse_notes",
                    "broker_parse_name",
                ):
                    st.session_state.pop(k, None)
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(str(exc))


def _activate_menu(menu_key: str) -> None:
    st.session_state.active_menu = menu_key
    st.session_state.active_category = "income" if menu_key == "income" else "work"
    st.session_state.market_type = _market_type_param(
        st.session_state.get("active_market")
    )
    sync_url_params()


def _on_sidebar_market_change() -> None:
    label = str(st.session_state.get("sidebar_market") or "국내주식")
    st.session_state.active_market = (
        MARKET_OVERSEAS if label == "해외주식" else MARKET_DOMESTIC
    )
    st.session_state.market_type = _market_type_param(st.session_state.active_market)
    sync_url_params()


def _sidebar_nav_button(label: str, menu_key: str) -> None:
    """작업 순서 메뉴 버튼. 현재 선택은 primary."""
    is_active = st.session_state.get("active_menu") == menu_key
    st.button(
        label,
        key=f"nav_{menu_key}",
        use_container_width=True,
        type="primary" if is_active else "secondary",
        on_click=_activate_menu,
        args=(menu_key,),
    )


def render_step_guide(menu: str) -> None:
    """페이지 상단: 지금 단계 + 다음 메뉴로 가는 버튼."""
    guide = STEP_GUIDES.get(menu)
    if not guide:
        return
    title, body, next_key, next_label = guide
    left, right = st.columns([4, 1])
    with left:
        st.info(f"**{title}** — {body}")
    with right:
        if next_key in ALL_MENU_KEYS:
            st.button(
                next_label,
                use_container_width=True,
                key=f"guide_next_{menu}",
                on_click=_activate_menu,
                args=(next_key,),
            )


def sidebar_tree_menu() -> str:
    """시장 스위치 + 번호 작업 메뉴."""
    menu = st.session_state.get("active_menu", DEFAULT_MENU)
    show_market = menu in MARKET_MENU_KEYS

    if "sidebar_market" not in st.session_state:
        mkt = current_market()
        st.session_state.sidebar_market = (
            "해외주식" if mkt == MARKET_OVERSEAS else "국내주식"
        )
    elif show_market:
        want = "해외주식" if current_market() == MARKET_OVERSEAS else "국내주식"
        if st.session_state.sidebar_market != want:
            st.session_state.sidebar_market = want

    if show_market:
        st.sidebar.radio(
            "시장",
            ["국내주식", "해외주식"],
            horizontal=True,
            key="sidebar_market",
            on_change=_on_sidebar_market_change,
        )
    else:
        st.sidebar.caption("이자·배당은 시장 구분이 없습니다.")

    with st.sidebar.expander("작업 순서", expanded=True):
        for key, label in WORK_MENU_ITEMS:
            _sidebar_nav_button(label, key)

    with st.sidebar.expander("그 외", expanded=(menu in {"income", "codes"})):
        for key, label in EXTRA_MENU_ITEMS:
            _sidebar_nav_button(label, key)

    return st.session_state.get("active_menu", DEFAULT_MENU)


def route_active_menu(
    storage: Storage,
    business_id: int | None,
    menu: str,
) -> None:
    """active_menu 키에 따라 본문 페이지 렌더."""
    market = menu_market(menu) or current_market()
    if menu == "setup":
        page_masters(storage, business_id, market=market)
    elif menu == "ingest":
        page_ingest(storage, business_id, market=market)
    elif menu == "ledger":
        page_dashboard(storage, business_id, market=market)
    elif menu == "voucher":
        page_voucher(storage, market=market)
    elif menu == "income":
        page_income(storage, business_id)
    elif menu == "codes":
        page_codes(storage, business_id)
    else:
        page_dashboard(storage, business_id, market=market)


def page_ingest(
    storage: Storage,
    business_id: int | None,
    market: str = MARKET_DOMESTIC,
) -> None:
    """증권사 파일 / 기초데이터 / 표준 엑셀 / 예전 매매일지 / 직접 입력."""
    market = normalize_market(market)
    render_step_guide("ingest")
    st.caption(f"시장: **{market_label(market)}**")
    # tabs는 숨은 탭까지 전부 그려 업로드 iframe이 여러 개 생긴다.
    # Cloud에서 파일을 받아도 화면이 안 바뀌는 경우가 있어 한 경로만 연다.
    method = st.radio(
        "넣는 방법",
        INGEST_METHODS,
        horizontal=True,
        key="ingest_method",
    )
    if method == "증권사 파일":
        st.caption(
            "키움·미래에셋·DB금융·한투 CSV/Excel/PDF, 해외는 미래에셋 PDF·KB 엑셀."
        )
        page_broker(storage, market=market)
    elif method == "기초데이터":
        st.caption(
            "이 프로그램을 쓰기 전에 매수해 둔 보유 수량·원가를 표에 입력합니다. "
            "엑셀 업로드가 아닙니다."
        )
        page_opening_lots(storage, business_id, market=market)
    elif method == "표준 엑셀":
        st.caption("필수 컬럼: 거래일자, 종목코드, 거래유형, 수량, 단가.")
        page_standard_import(storage, market=market)
    elif method == "예전 매매일지":
        st.caption("시트별 '주식 매매일지'로 만들어 둔 예전 엑셀.")
        page_legacy_journal(storage, business_id, market=market)
    else:
        st.caption("한 건씩 매수·매도를 직접 넣습니다.")
        page_trades(storage, business_id, market=market)


def page_codes(storage: Storage, business_id: int | None) -> None:
    render_step_guide("codes")
    kind = st.radio(
        "대상",
        ["주식 매매", "이자·배당"],
        horizontal=True,
        key="codes_kind",
    )
    if kind == "이자·배당":
        page_settings(storage, business_id, mode="income")
    else:
        page_settings(storage, business_id, mode="stock", market=current_market())


def page_dashboard(
    storage: Storage,
    business_id: int | None,
    market: str = MARKET_DOMESTIC,
) -> None:
    market = normalize_market(market)
    render_step_guide("ledger")
    st.caption(f"시장: **{market_label(market)}** · FIFO 잔고는 증권사별로 분리됩니다.")

    accounts = (
        storage.list_accounts(business_id, market=market) if business_id is not None else []
    )
    acc_labels = ["전체 증권사", *[a.name for a in accounts if a.name]]
    picked = st.selectbox(
        "증권사 필터",
        acc_labels,
        key=f"dash_account_{market}_{business_id}",
    )
    account_id = None
    if picked != "전체 증권사":
        account_id = next(
            (int(a.id) for a in accounts if a.name == picked and a.id is not None),
            None,
        )

    today = date.today()
    pkey = f"dash_{market}_{business_id}"
    if f"{pkey}_start" not in st.session_state:
        st.session_state[f"{pkey}_start"] = date(today.year, 1, 1)
    if f"{pkey}_end" not in st.session_state:
        st.session_state[f"{pkey}_end"] = today

    qb1, qb2, qb3 = st.columns(3)
    if qb1.button("이번 달", use_container_width=True, key=f"{pkey}_m"):
        st.session_state[f"{pkey}_start"] = date(today.year, today.month, 1)
        st.session_state[f"{pkey}_end"] = today
        st.rerun()
    if qb2.button("올해 (1월~현재)", use_container_width=True, key=f"{pkey}_y"):
        st.session_state[f"{pkey}_start"] = date(today.year, 1, 1)
        st.session_state[f"{pkey}_end"] = today
        st.rerun()
    if qb3.button("전체 기간", use_container_width=True, key=f"{pkey}_a"):
        st.session_state[f"{pkey}_start"] = date(2020, 1, 1)
        st.session_state[f"{pkey}_end"] = today
        st.rerun()

    d1, d2 = st.columns(2)
    with d1:
        start_date = st.date_input(
            "처분손익 시작일", format="YYYY-MM-DD", key=f"{pkey}_start"
        )
    with d2:
        end_date = st.date_input(
            "처분손익 종료일", format="YYYY-MM-DD", key=f"{pkey}_end"
        )
    if start_date > end_date:
        start_date, end_date = end_date, start_date

    (positions, sells, warnings), trades = refresh_fifo(
        storage, business_id, market=market, account_id=account_id
    )
    opening_n = sum(1 for t in trades if _is_opening_trade(t))
    if opening_n:
        st.caption(
            f"기초잔고 **{opening_n}건**이 FIFO 원가에 포함됩니다. "
            "회계전표 매수분개에는 다시 넣지 않습니다."
        )

    _open_stock_detail_from_query(storage, trades)

    start_s = start_date.isoformat()
    end_s = end_date.isoformat()
    period_sells = [
        s for s in sells if start_s <= str(s.trade_date)[:10] <= end_s
    ]
    period_trades = [
        t for t in trades if start_s <= str(t.trade_date)[:10] <= end_s
    ]

    held = [p for p in positions if p.quantity > 1e-12]
    total_cost = sum(p.total_cost for p in held)
    total_realized = sum(p.realized_pnl for p in positions)
    period_pnl = sum(s.realized_pnl for s in period_sells)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("거래 건수", f"{len(trades):,}")
    c2.metric("보유 종목 수", f"{len(held):,}")
    c3.metric("원가잔액", money(total_cost))
    c4.metric("기간 처분손익", money(period_pnl))
    c5.metric("누적 실현손익", money(total_realized))
    st.caption(
        f"기간 처분손익: {start_s} ~ {end_s} 매도 {len(period_sells)}건 "
        f"/ 기간 거래 {len(period_trades)}건. 원가잔액은 전체 이력 FIFO."
    )
    if warnings:
        with st.expander(f"FIFO 경고 {len(warnings)}건"):
            for w in warnings:
                st.warning(w)

    st.subheader("보유 잔고")
    st.caption("종목명을 클릭하면 상세 매매 내역이 열립니다. 같은 종목이어도 증권사가 다르면 행이 분리됩니다.")

    pos_df = positions_to_dataframe(positions)
    if pos_df.empty:
        st.info("보유 잔고가 없습니다.")
    else:
        pos_df = pos_df.drop(columns=["종목코드", "평단가"], errors="ignore").reset_index(
            drop=True
        )
        for col in ("잔여수량", "원가잔액", "누적실현손익"):
            if col in pos_df.columns:
                pos_df[col] = pd.to_numeric(pos_df[col], errors="coerce")
        if "원가잔액" in pos_df.columns:
            pos_df["원가잔액"] = pos_df["원가잔액"].round(0)
        if "누적실현손익" in pos_df.columns:
            pos_df["누적실현손익"] = pos_df["누적실현손익"].round(0)
        if "잔여수량" in pos_df.columns:
            pos_df["잔여수량"] = pos_df["잔여수량"].round(0)

        _render_holdings_html_table(
            pos_df,
            active_menu=st.session_state.get("active_menu"),
            market=market,
        )

    st.subheader("처분손익")
    sell_df = sell_results_to_dataframe(period_sells)
    if sell_df.empty:
        st.info("선택한 기간의 매도(처분) 내역이 없습니다.")
        return
    for col in ("매도수량", "매도단가", "매도금액", "FIFO원가", "수수료", "실현손익"):
        if col in sell_df.columns:
            sell_df[col] = pd.to_numeric(sell_df[col], errors="coerce")
    st.dataframe(
        sell_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "매도수량": st.column_config.NumberColumn("매도수량", format="%,.4f"),
            "매도단가": st.column_config.NumberColumn("매도단가", format="%,d 원"),
            "매도금액": st.column_config.NumberColumn("매도금액", format="%,d 원"),
            "FIFO원가": st.column_config.NumberColumn("FIFO원가", format="%,d 원"),
            "수수료": st.column_config.NumberColumn("수수료", format="%,d 원"),
            "실현손익": st.column_config.NumberColumn("실현손익", format="%,d 원"),
        },
    )


def _fx_to_krw(amount_fx: float, fx_rate: float) -> float:
    return float(amount_fx or 0) * float(fx_rate or 0)


def page_overseas_trades(storage: Storage, business_id: int | None) -> None:
    """해외주식 매매 입력 (외화·환율)."""
    st.caption("시장: **해외주식** · 단가/수수료는 외화, 장부는 환율 적용 원화로 저장합니다.")
    render_overseas_trade_input(storage, business_id)
    st.divider()
    _render_overseas_trade_list(storage, business_id)


def render_overseas_trade_input(storage: Storage, business_id: int | None) -> None:
    businesses = storage.list_businesses()
    stocks = storage.list_stocks(business_id, market=MARKET_OVERSEAS)

    if not businesses:
        st.warning("사이드바 ＋ 버튼으로 사업자를 먼저 추가하세요.")
        return
    if business_id is None:
        st.warning("사이드바에서 사업자를 선택한 뒤 입력해 주세요. (전체 제외)")
        return

    business = next(b for b in businesses if b.id == business_id)
    st.markdown(f"**선택된 사업자:** `{business.name}`")
    account = select_trade_account(
        storage, int(business_id), MARKET_OVERSEAS, key="ov_trade_account"
    )
    if account is None:
        st.warning("증권사/계좌를 선택하거나 이름을 입력하세요.")
        return

    if st.session_state.pop("_show_ov_trade_toast", False):
        st.toast(st.session_state.pop("_ov_trade_toast_msg", "저장되었습니다."))

    row1 = st.columns(3)
    with row1[0]:
        trade_date = st.date_input(
            "거래일자",
            value=date.today(),
            format="YYYY/MM/DD",
            key="ov_trade_date",
        )
    with row1[1]:
        currency = st.selectbox(
            "통화코드",
            list(FX_CURRENCIES),
            index=0,
            key="ov_currency",
        )
    with row1[2]:
        side_label = st.radio(
            "거래유형",
            ["해외매수", "해외매도", "외화배당"],
            horizontal=True,
            key="ov_trade_side",
        )

    ticker = st.text_input(
        "종목 선택 / 티커",
        value=st.session_state.get("_ov_preferred_ticker", ""),
        placeholder="예: NVDA, QQQ, VOO",
        key="ov_ticker",
    ).strip().upper()
    stock_name = st.text_input(
        "종목명 (선택)",
        value="",
        placeholder="비우면 티커를 종목명으로 사용",
        key="ov_stock_name",
    ).strip()

    c_qty, c_price, c_fee, c_tax = st.columns(4)
    with c_qty:
        quantity = st.number_input(
            "거래수량",
            min_value=0.0,
            value=0.0,
            step=0.01,
            format="%.4f",
            key="ov_qty",
        )
    with c_price:
        price_fx = st.number_input(
            f"외화 단가 ({currency})",
            min_value=0.0,
            value=0.0,
            step=0.0001,
            format="%.4f",
            key="ov_price_fx",
        )
    with c_fee:
        fee_fx = st.number_input(
            f"외화 수수료 ({currency})",
            min_value=0.0,
            value=0.0,
            step=0.01,
            format="%.4f",
            key="ov_fee_fx",
        )
    with c_tax:
        tax_fx = st.number_input(
            f"외화 제세금 ({currency})",
            min_value=0.0,
            value=0.0,
            step=0.01,
            format="%.4f",
            key="ov_tax_fx",
        )

    fx_rate = st.number_input(
        f"적용 환율 (₩/{currency})",
        min_value=0.0,
        value=float(st.session_state.get("_ov_last_fx", 1400.0)),
        step=0.1,
        format="%.2f",
        key="ov_fx_rate",
        help="예: 1467.30",
    )

    # 실시간 미리보기
    if side_label == "외화배당":
        gross_fx = float(price_fx) * (float(quantity) if quantity > 0 else 1.0)
        total_fx = gross_fx + float(fee_fx)  # tax는 원천징수로 별도 표기
        preview_note = "배당 총액(외화, 세전 단가×수량)"
    elif side_label == "해외매수":
        gross_fx = float(quantity) * float(price_fx)
        total_fx = gross_fx + float(fee_fx) + float(tax_fx)
        preview_note = "외화 총 지급액 = 수량×단가 + 수수료 + 제세금"
    else:
        gross_fx = float(quantity) * float(price_fx)
        total_fx = gross_fx - float(fee_fx) - float(tax_fx)
        preview_note = "외화 순수령액 = 수량×단가 − 수수료 − 제세금"

    total_krw = _fx_to_krw(total_fx, fx_rate)
    gross_krw = _fx_to_krw(gross_fx, fx_rate)

    p1, p2, p3 = st.columns(3)
    p1.info(f"**외화 총액**\n\n{total_fx:,.4f} {currency}\n\n_{preview_note}_")
    p2.info(f"**원화 환산 (총액)**\n\n₩ {total_krw:,.0f}\n\n_{total_fx:,.4f} × {fx_rate:,.2f}_")
    p3.info(f"**원화 환산 (원금)**\n\n₩ {gross_krw:,.0f}\n\n_{gross_fx:,.4f} × {fx_rate:,.2f}_")

    if st.button("💾 해외주식 거래 저장", type="primary", use_container_width=True, key="ov_save"):
        try:
            if not ticker:
                raise ValueError("티커(종목코드)를 입력하세요.")
            if fx_rate <= 0:
                raise ValueError("적용 환율을 입력하세요.")
            q = float(quantity)
            if side_label == "외화배당":
                if float(price_fx) <= 0:
                    raise ValueError("배당 금액(외화 단가)을 입력하세요.")
                if q <= 0:
                    q = 1.0
                side = "DIVIDEND"
            else:
                if q <= 0:
                    raise ValueError("거래수량을 입력하세요.")
                if float(price_fx) <= 0:
                    raise ValueError("외화 단가를 입력하세요.")
                side = "BUY" if side_label == "해외매수" else "SELL"

            name = stock_name or next(
                (s.name for s in stocks if s.code.upper() == ticker), ticker
            )
            stock = storage.get_or_create_stock(
                ticker, name, business_id=int(business_id), market=MARKET_OVERSEAS
            )

            price_krw = _fx_to_krw(price_fx, fx_rate)
            fee_krw = _fx_to_krw(fee_fx, fx_rate)
            tax_krw = _fx_to_krw(tax_fx, fx_rate)
            if side == "BUY":
                settle = q * price_krw + fee_krw + tax_krw
            elif side == "SELL":
                settle = q * price_krw - fee_krw - tax_krw
            else:
                settle = q * price_krw - tax_krw

            trade = Trade(
                id=None,
                trade_date=trade_date.isoformat(),
                business_id=int(business_id),
                stock_id=int(stock.id),  # type: ignore[arg-type]
                side=side,  # type: ignore[arg-type]
                quantity=q,
                price=price_krw,
                fee=fee_krw,
                tax=tax_krw,
                settlement_amount=settle,
                memo=f"{side_label} {currency}@{fx_rate:g}",
                source="manual-overseas",
                currency=normalize_currency(currency),
                fx_rate=float(fx_rate),
                price_fx=float(price_fx),
                fee_fx=float(fee_fx),
                tax_fx=float(tax_fx),
                account_id=int(account.id) if account.id is not None else None,
                account_name=account.name,
                account_code=account.code,
            )
            storage.add_trade(trade)
            st.session_state["_ov_last_fx"] = float(fx_rate)
            st.session_state["_ov_preferred_ticker"] = ticker
            st.session_state["_show_ov_trade_toast"] = True
            st.session_state["_ov_trade_toast_msg"] = (
                f"✅ {side_label} 저장 · {ticker} {q:g}주 · ₩{settle:,.0f}"
            )
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))


def _render_overseas_trade_list(storage: Storage, business_id: int | None) -> None:
    st.subheader("해외주식 거래 내역")
    trades = storage.list_trades(business_id=business_id, market=MARKET_OVERSEAS)
    if not trades:
        st.info("해외주식 거래 내역이 없습니다.")
        return
    rows = []
    for t in reversed(trades[-200:]):
        rows.append(
            {
                "ID": t.id,
                "거래일자": t.trade_date,
                "증권사": getattr(t, "account_name", "") or "",
                "유형": (
                    "매수"
                    if t.side == "BUY"
                    else ("매도" if t.side == "SELL" else "배당")
                ),
                "티커": t.stock_code,
                "종목명": t.stock_name,
                "수량": t.quantity,
                "거래금액(원가)": float(t.quantity or 0) * float(t.price or 0),
                "외화단가": getattr(t, "price_fx", 0) or 0,
                "환율": getattr(t, "fx_rate", 0) or 0,
                "통화": getattr(t, "currency", "") or "",
                "원화단가": t.price,
                "원화수수료": t.fee,
                "원화장산": t.settlement_amount,
            }
        )
    odf = pd.DataFrame(rows)
    st.dataframe(
        odf,
        use_container_width=True,
        hide_index=True,
        column_config={
            "수량": st.column_config.NumberColumn("수량", format="%,.4f"),
            "거래금액(원가)": st.column_config.NumberColumn(
                "거래금액(원가)", format="%,d 원", help="수량 × 원화단가"
            ),
            "외화단가": st.column_config.NumberColumn("외화단가", format="%.4f"),
            "환율": st.column_config.NumberColumn("환율", format="%.2f"),
            "원화단가": st.column_config.NumberColumn("원화단가", format="%,d 원"),
            "원화수수료": st.column_config.NumberColumn("원화수수료", format="%,d 원"),
            "원화장산": st.column_config.NumberColumn("원화장산", format="%,d 원"),
            "ID": st.column_config.NumberColumn("ID", format="%d"),
        },
    )

def page_trades(
    storage: Storage,
    business_id: int | None,
    market: str = MARKET_DOMESTIC,
) -> None:
    market = normalize_market(market)
    if market == MARKET_OVERSEAS:
        page_overseas_trades(storage, business_id)
        return
    st.caption(f"시장: **{market_label(market)}**")
    # 국내 매매 입력 (기존)
    # ---- 위젯 생성 전: 저장 직후 초기화/토스트 반영 ----
    pending = st.session_state.pop("_pending_trade_reset", None)
    if pending:
        for k in pending.get("clear_keys", []):
            st.session_state.pop(k, None)
        next_stock = pending.get("stock")
        if next_stock:
            st.session_state["_preferred_stock"] = next_stock

    if st.session_state.pop("_show_trade_toast", False):
        st.toast(
            st.session_state.pop(
                "_trade_toast_msg",
                "✅ 거래가 성공적으로 저장되었습니다!",
            )
        )

    businesses = storage.list_businesses()
    stocks = storage.list_stocks(business_id, market=market)

    st.subheader("매수/매도 입력")

    if not businesses:
        st.warning("사이드바 사업자 선택 옆 **＋** 버튼으로 사업자를 먼저 추가하세요.")
        return

    if business_id is None:
        st.warning("사이드바 **사업자 선택**에서 입력할 사업자를 먼저 선택해 주세요. (전체 제외)")
        _render_trade_list(storage, business_id, market=market)
        return

    business = next(b for b in businesses if b.id == business_id)

    st.markdown(
        f"""
        <div style="
            display:inline-flex;align-items:center;gap:0.5rem;
            padding:0.45rem 0.9rem;border-radius:999px;
            background:linear-gradient(90deg,#eef5ff,#f7faff);
            border:1px solid #c9dcff;color:#1f3b66;
            font-size:0.95rem;font-weight:600;margin-bottom:0.75rem;">
            <span style="opacity:0.75;font-weight:500;">선택된 사업자</span>
            <span>{business.name}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # 거래일자 / 거래유형 — 폼 밖 (연속 입력 시 유지)
    row1_l, row1_r = st.columns(2, gap="large")
    with row1_l:
        trade_date = st.date_input(
            "거래일자",
            value=date.today(),
            format="YYYY/MM/DD",
            key="trade_date",
        )
    with row1_r:
        side_label = st.radio(
            "거래 유형",
            ["매수", "매도"],
            horizontal=True,
            key="trade_side",
        )
    account = select_trade_account(
        storage, int(business.id), market, key="dom_trade_account"
    )
    if account is None:
        st.warning("증권사/계좌를 선택하거나 이름을 입력하세요.")
        _render_trade_list(storage, business_id, market=market)
        return

    stock_options = [NEW_STOCK_OPTION, *[f"{s.name} ({s.code})" for s in stocks]]
    preferred = st.session_state.get("_preferred_stock")
    default_idx = (
        stock_options.index(preferred) if preferred in stock_options else 0
    )

    # 수량·단가·수수료·메모 — 폼 안 (제출 시 clear_on_submit으로 초기화)
    with st.form("trade_input_form", clear_on_submit=True):
        st.markdown("**종목**")
        stock_label = st.selectbox(
            "종목 선택",
            stock_options,
            index=default_idx,
        )
        new_name = st.text_input(
            "신규 종목명",
            placeholder="신규 종목 선택 시에만 입력 (예: 삼성전자)",
            help="'➕ 신규 종목 직접 입력' 선택 시 필수입니다.",
        )
        is_new_stock = stock_label == NEW_STOCK_OPTION

        st.markdown("**수량 · 단가 · 수수료**" + (" · 제세금" if side_label == "매도" else ""))
        if side_label == "매도":
            q_col, p_col, f_col, t_col = st.columns(4, gap="large")
        else:
            q_col, p_col, f_col = st.columns(3, gap="large")
            t_col = None
        with q_col:
            quantity = st.number_input(
                "수량 (주)",
                min_value=0,
                step=1,
                value=0,
                format="%d",
            )
        with p_col:
            price = st.number_input(
                "단가 (원)",
                min_value=0,
                step=100,
                value=0,
                format="%d",
            )
        with f_col:
            fee = st.number_input(
                "수수료 (원)",
                min_value=0,
                step=10,
                value=0,
                format="%d",
            )
        tax = 0
        if t_col is not None:
            with t_col:
                tax = st.number_input(
                    "제세금 (원)",
                    min_value=0,
                    step=10,
                    value=0,
                    format="%d",
                    key="trade_tax_input",
                )

        memo = st.text_input("메모 (선택)", value="", placeholder="비고를 입력하세요")
        submitted = st.form_submit_button(
            "거래 저장",
            type="primary",
            use_container_width=True,
        )

    if submitted:
        try:
            if quantity <= 0:
                raise ValueError("수량은 1주 이상 입력하세요.")
            if price < 0:
                raise ValueError("단가를 확인하세요.")

            if is_new_stock:
                if not str(new_name).strip():
                    raise ValueError("신규 종목명을 입력하세요.")
                stock = storage.get_or_create_stock_by_name(
                    str(new_name).strip(),
                    business_id=int(business.id),
                    market=market,
                )
            else:
                stock = next(
                    s for s in stocks if f"{s.name} ({s.code})" == stock_label
                )

            side = "BUY" if side_label == "매수" else "SELL"
            tax_val = float(tax) if side == "SELL" else 0.0
            settlement = (
                float(quantity) * float(price) + float(fee)
                if side == "BUY"
                else float(quantity) * float(price) - float(fee)
            )

            trade = Trade(
                id=None,
                trade_date=trade_date.isoformat(),
                business_id=business.id,  # type: ignore[arg-type]
                stock_id=stock.id,  # type: ignore[arg-type]
                side=side,  # type: ignore[arg-type]
                quantity=float(quantity),
                price=float(price),
                fee=float(fee),
                tax=tax_val,
                settlement_amount=float(settlement),
                memo=str(memo or ""),
                source="manual",
                created_at=now_str(),
                account_id=int(account.id) if account.id is not None else None,
                account_name=account.name,
                account_code=account.code,
            )
            tid = storage.add_trade(trade)

            toast_msg = "✅ 거래가 성공적으로 저장되었습니다!"
            if side == "SELL":
                preview = storage.list_trades(
                    business_id=business.id, stock_id=stock.id
                )
                _, sells, _warnings = compute_positions(preview)
                if sells:
                    toast_msg += f" · 실현손익 {money(sells[-1].realized_pnl)}원"

            st.session_state["_trade_toast_msg"] = toast_msg
            st.session_state["_show_trade_toast"] = True
            # 일자/유형 유지 · 수량·단가·수수료·메모는 form clear_on_submit
            # 종목은 연속 입력을 위해 유지
            st.session_state["_pending_trade_reset"] = {
                "stock": f"{stock.name} ({stock.code})",
                "clear_keys": [],
            }
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))

    st.divider()
    _render_trade_list(storage, business_id, market=market)


def _render_trade_list(
    storage: Storage,
    business_id: int | None,
    market: str = MARKET_DOMESTIC,
) -> None:
    st.subheader("거래 내역")
    trades = storage.list_trades(business_id=business_id, market=market)
    df = trades_to_dataframe(trades)
    if df.empty:
        st.info("거래 내역이 없습니다.")
        return

    view = df.drop(columns=["출처"], errors="ignore").copy()
    for col in ("수량", "거래금액(원가)", "단가", "수수료", "제세금", "정산금액", "ID"):
        if col in view.columns:
            view[col] = pd.to_numeric(view[col], errors="coerce")

    # 표시 순서: 수량 → 거래금액(원가) → 단가 …
    preferred = [
        "거래일자",
        "사업자",
        "증권사",
        "종목코드",
        "종목명",
        "거래유형",
        "수량",
        "거래금액(원가)",
        "단가",
        "수수료",
        "제세금",
        "정산금액",
        "메모",
        "ID",
    ]
    ordered = [c for c in preferred if c in view.columns]
    ordered += [c for c in view.columns if c not in ordered]
    view = view.loc[:, ordered]

    st.dataframe(
        view,
        use_container_width=True,
        hide_index=True,
        column_config=trade_table_column_config(),
    )

    del_id = st.number_input("삭제할 거래 ID", min_value=0, step=1, value=0, key="del_trade_id")
    if st.button("선택 거래 삭제", type="secondary"):
        if del_id > 0:
            storage.delete_trade(int(del_id))
            st.success(f"거래 #{int(del_id)} 삭제")
            st.rerun()


def page_import_export(
    storage: Storage,
    market: str = MARKET_DOMESTIC,
) -> None:
    page_voucher(storage, market=market)
    st.divider()
    page_standard_import(storage, market=market)


_VOUCHER_MEMO_OPTIONS: dict[str, str] = {
    "옵션1: 종목명 / @수량 * 단가 * 환율": "stock",
    "옵션2: USD 거래/정산금액 / 수량*단가 * 환율": "amount",
}


def _resolve_voucher_memo_mode(market: str, label: object | None = None) -> str:
    """라디오·session_state에서 적요 모드(stock|amount) 확정."""
    key = f"ie_memo_fmt_v4_{normalize_market(market)}"
    raw = label if label is not None else st.session_state.get(key)
    if raw in _VOUCHER_MEMO_OPTIONS:
        return _VOUCHER_MEMO_OPTIONS[raw]
    text = str(raw or "")
    if "옵션2" in text or "외화총액" in text or "거래/정산" in text or "통화" in text:
        return "amount"
    return "stock"


def page_voucher(
    storage: Storage,
    market: str = MARKET_DOMESTIC,
) -> None:
    market = normalize_market(market)
    render_step_guide("voucher")
    st.caption(f"시장: **{market_label(market)}**")
    st.subheader("회계 전표")
    business_id = st.session_state.get("active_business_id")
    trades = storage.list_trades(business_id=business_id, market=market)
    positions, sells, _ = compute_positions(trades)
    trades_df = trades_to_dataframe(trades)
    pos_df = positions_to_dataframe(positions)
    sell_df = sell_results_to_dataframe(sells)

    company_name = ""
    if business_id is not None:
        for b in storage.list_businesses():
            if b.id == business_id:
                company_name = b.name
                break

    c1, c2, c3 = st.columns(3)
    with c1:
        st.download_button(
            "거래내역 CSV",
            data=export_to_csv_bytes(trades_df),
            file_name="trades.csv",
            mime="text/csv",
        )
    with c2:
        st.download_button(
            "잔고 CSV",
            data=export_to_csv_bytes(pos_df),
            file_name="positions.csv",
            mime="text/csv",
        )
    with c3:
        xlsx = export_to_excel_bytes(trades_df, pos_df, sell_df)
        st.download_button(
            "전체 Excel (거래/잔고/실현손익)",
            data=xlsx,
            file_name="stock_ledger.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    st.markdown("##### 회계 전표 전송 양식")
    st.caption(
        "원본 '엑셀자료일반전표전송.xls' 양식(헤더 10행 유지, 11행부터 분개)에 맞춰 "
        "지정 기간 거래를 생성합니다. FIFO 원가는 전체 이력을 반영합니다."
    )

    st.markdown("##### 적요 형식")
    radio_key = f"ie_memo_fmt_v4_{market}"
    memo_labels = list(_VOUCHER_MEMO_OPTIONS.keys())
    memo_mode_label = st.radio(
        "적요 형식",
        options=memo_labels,
        index=0,
        horizontal=False,
        key=radio_key,
        label_visibility="collapsed",
        help=(
            "회계 전표 엑셀의 적요에 적용됩니다. "
            "메리츠 해외주식은 옵션과 관계없이 엑셀 거래/정산금액을 앞 금액으로 씁니다."
        ),
    )
    remark_mode = _resolve_voucher_memo_mode(market, memo_mode_label)
    if normalize_market(market) == MARKET_OVERSEAS:
        st.caption(
            "메리츠: `USD {거래/정산금액} / {수량}주*{단가} * {환율}` "
            "(앞 금액은 엑셀 칸 그대로, 수량×단가 재계산 없음)"
        )
    if remark_mode == "stock":
        st.caption("예: INVESCO NASDAQ 100 매수 / @40주 * $247.67 * 1442.00원")
    else:
        st.caption("예: USD 20862.39 / 180주*115.9095 * 1441.1  (앞부분은 거래/정산금액)")

    today = date.today()
    # 구버전 range 키 → 분리 키 마이그레이션
    if "voucher_date_range" in st.session_state and "voucher_start_date" not in st.session_state:
        old = st.session_state.pop("voucher_date_range", None)
        if isinstance(old, (list, tuple)) and len(old) == 2:
            st.session_state["voucher_start_date"] = old[0]
            st.session_state["voucher_end_date"] = old[1]
        else:
            st.session_state.pop("voucher_date_range", None)
    if "voucher_start_date" not in st.session_state:
        st.session_state["voucher_start_date"] = date(today.year, 1, 1)
    if "voucher_end_date" not in st.session_state:
        st.session_state["voucher_end_date"] = today

    qb1, qb2, qb3 = st.columns(3)
    if qb1.button("이번 달", use_container_width=True, key="voucher_preset_month"):
        st.session_state["voucher_start_date"] = date(today.year, today.month, 1)
        st.session_state["voucher_end_date"] = today
        st.rerun()
    if qb2.button("올해 (1월~현재)", use_container_width=True, key="voucher_preset_year"):
        st.session_state["voucher_start_date"] = date(today.year, 1, 1)
        st.session_state["voucher_end_date"] = today
        st.rerun()
    if qb3.button("전체 기간", use_container_width=True, key="voucher_preset_all"):
        if trades:
            dates = sorted(str(t.trade_date)[:10] for t in trades)
            st.session_state["voucher_start_date"] = date.fromisoformat(dates[0])
            st.session_state["voucher_end_date"] = date.fromisoformat(dates[-1])
        else:
            st.session_state["voucher_start_date"] = date(2020, 1, 1)
            st.session_state["voucher_end_date"] = today
        st.rerun()

    col_d1, col_d2 = st.columns(2)
    with col_d1:
        start_date = st.date_input(
            "📅 시작일 선택",
            format="YYYY-MM-DD",
            key="voucher_start_date",
        )
    with col_d2:
        end_date = st.date_input(
            "📅 종료일 선택",
            format="YYYY-MM-DD",
            key="voucher_end_date",
        )
    if start_date > end_date:
        start_date, end_date = end_date, start_date
        st.caption("※ 시작일이 종료일보다 늦어 순서를 바꿔 조회합니다.")

    # 기간 내 전표용 거래 + 전체 이력 FIFO(매도 원가)
    period_trades = storage.get_trades_by_period(
        business_id, start_date, end_date, market=market
    )
    _, all_sells, _ = compute_positions(trades)
    account_config = storage.get_account_config(business_id, market=market)
    partner_by_stock_id = {
        int(s.id): (s.partner_code or "")
        for s in storage.list_stocks(business_id, market=market)
        if s.id is not None
    }
    line_count = (
        len(
            trades_to_voucher_lines(
                period_trades,
                all_sells,
                account_config=account_config,
                partner_by_stock_id=partner_by_stock_id,
                remark_mode=remark_mode,
            )
        )
        if period_trades
        else 0
    )

    st.info(
        f"선택된 기간: **{start_date.isoformat()} ~ {end_date.isoformat()}** "
        f"(총 {len(period_trades)}건의 거래, {line_count}줄의 분개 생성)"
    )

    if not period_trades:
        st.info("💡 선택한 기간에 해당하는 거래 내역이 없습니다.")
        st.download_button(
            f"📥 {start_date} ~ {end_date} 회계 전표 엑셀 다운로드",
            data=b"",
            file_name="empty.xlsx",
            disabled=True,
            use_container_width=True,
        )
    else:
        voucher_bytes = export_voucher_excel_bytes(
            period_trades,
            all_sells,
            company_name=company_name,
            account_config=account_config,
            partner_by_stock_id=partner_by_stock_id,
            remark_mode=remark_mode,
        )
        filename = (
            f"엑셀자료일반전표전송_주식매매_"
            f"{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}.xlsx"
        )
        st.download_button(
            f"📥 {start_date} ~ {end_date} 회계 전표 엑셀 다운로드",
            data=voucher_bytes,
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            use_container_width=True,
        )


def page_standard_import(
    storage: Storage,
    market: str = MARKET_DOMESTIC,
) -> None:
    market = normalize_market(market)
    st.subheader("표준 양식 Import (CSV/Excel)")
    st.caption(
        "필수 컬럼: 거래일자, 종목코드, 거래유형, 수량, 단가 / "
        "선택: 사업자, 종목명, 수수료, 정산금액, 메모"
    )

    businesses = storage.list_businesses()
    default_biz = st.selectbox(
        "사업자 컬럼이 없을 때 기본 사업자",
        [b.name for b in businesses] if businesses else ["(먼저 사업자 등록)"],
        key=f"std_import_biz_{market}",
    )
    import_account = None
    if businesses and default_biz and default_biz != "(먼저 사업자 등록)":
        biz_obj = next((b for b in businesses if b.name == default_biz), None)
        if biz_obj and biz_obj.id is not None:
            import_account = select_trade_account(
                storage,
                int(biz_obj.id),
                market,
                key=f"std_import_account_{market}",
            )
    force_dup = render_dedupe_controls(f"std_import_{market}")
    up = st.file_uploader(
        "매매일지 파일 업로드",
        type=["csv", "xlsx", "xls"],
        key="std_up",
        on_change=persist_uploaded_file,
        args=("std_up", "_std_up_file"),
    )
    up_name, up_size, up_bytes = take_uploaded_file(up, "_std_up_file")
    show_uploaded_file(up_name, up_size)
    if up_bytes and businesses:
        st.caption("파일이 올라갔습니다. 아래 버튼으로 등록하세요.")
        if st.button("표준 양식 일괄 등록", type="primary"):
            try:
                if import_account is None or import_account.id is None:
                    raise ValueError("증권사/계좌를 선택하세요.")
                count, errors = import_standard_file(
                    up_bytes,
                    up_name or "upload.csv",
                    storage,
                    default_business=default_biz,
                    market=market,
                    account_id=int(import_account.id),
                    skip_duplicates=not force_dup,
                )
                st.success(f"{count}건 등록 완료")
                if errors:
                    with st.expander(f"오류/스킵 {len(errors)}건"):
                        for e in errors:
                            st.write(e)
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(str(exc))


def page_broker_overseas(storage: Storage) -> None:
    """해외주식 증권사 변환기: 미래에셋 PDF · KB증권 엑셀 → 검수 후 일괄 등록."""
    from src.brokers.generic_overseas import (
        looks_like_columnar_overseas_excel,
        parse_generic_overseas_excel,
    )
    from src.brokers.kb_overseas import parse_kb_overseas_excel
    from src.brokers.mirae_overseas import (
        apply_overseas_preview_fx,
        ensure_overseas_preview_columns,
        mirae_rows_to_preview_df,
        parse_mirae_overseas_pdf,
        preview_settle_fx,
    )

    st.subheader("해외주식 증권사 변환기")
    st.caption(
        "미래에셋 해외주식 거래내역서 PDF, KB 증권계좌거래내역 엑셀, "
        "메리츠 등 **컬럼형 해외주식 거래내역 엑셀**을 읽습니다. "
        "메리츠 적요는 `USD {거래/정산금액} / {수량}주*{단가} * {환율}` 입니다. "
        "앞 금액은 엑셀 거래/정산금액을 그대로 넣습니다."
    )

    businesses = storage.list_businesses()
    if not businesses:
        st.warning("사이드바 ＋ 버튼으로 사업자를 먼저 등록하세요.")
        return

    biz_names = [b.name for b in businesses]
    default_idx = 0
    active_id = st.session_state.get("active_business_id")
    if active_id is not None:
        for i, b in enumerate(businesses):
            if b.id == active_id:
                default_idx = i
                break

    biz = st.selectbox("반영할 사업자", biz_names, index=default_idx, key="ov_broker_biz")
    ov_biz = next((b for b in businesses if b.name == biz), None)
    ov_account = None
    if ov_biz and ov_biz.id is not None:
        detected = ""
        src = str(st.session_state.get("ov_broker_source") or "")
        if "kb" in src.lower():
            detected = "KB증권"
        elif "mirae" in src.lower() or "미래" in src:
            detected = "미래에셋증권"
        elif "meritz" in src.lower() or "메리츠" in src:
            detected = "메리츠증권"
        ov_account = select_trade_account(
            storage,
            int(ov_biz.id),
            MARKET_OVERSEAS,
            key="ov_broker_account",
            detected_name=detected,
        )
    force_ov_dup = render_dedupe_controls("ov_broker")
    up = st.file_uploader(
        "해외주식 거래내역 (PDF / Excel)",
        type=["pdf", "xlsx", "xls"],
        key="ov_broker_up",
        help="미래에셋 PDF, KB·메리츠 등 해외주식 거래내역 엑셀",
        on_change=persist_uploaded_file,
        args=("ov_broker_up", "_ov_broker_file"),
    )
    up_name, up_size, up_bytes = take_uploaded_file(up, "_ov_broker_file")
    show_uploaded_file(up_name, up_size)

    if up_bytes and up_name:
        token = f"{up_name}:{up_size}:{biz}:settlefx3"
        if st.session_state.get("ov_broker_token") != token:
            ext = up_name.rsplit(".", 1)[-1].lower() if "." in up_name else ""
            try:
                with st.spinner("파일을 읽는 중…"):
                    if ext == "pdf" or up_bytes[:4] == b"%PDF":
                        result = parse_mirae_overseas_pdf(up_bytes, up_name)
                    elif looks_like_columnar_overseas_excel(up_bytes, up_name):
                        result = parse_generic_overseas_excel(up_bytes, up_name)
                    else:
                        result = parse_kb_overseas_excel(up_bytes, up_name)
                        if not (result.get("rows") or []):
                            result = parse_generic_overseas_excel(up_bytes, up_name)
                    if not (result.get("rows") or []):
                        notes = [n for n in (result.get("notes") or []) if n]
                        notes.append(
                            f"이 파일({up_name})에서 해외주식 거래를 찾지 못했습니다. "
                            "거래일자·매매구분·수량·단가 컬럼이 있는 엑셀인지 확인하세요."
                        )
                        result["rows"] = []
                        result["notes"] = list(dict.fromkeys(notes))
                        result["source"] = result.get("source") or "overseas-unknown"
            except Exception as exc:  # noqa: BLE001
                result = {
                    "rows": [],
                    "notes": [f"파일 처리 중 오류: {exc}"],
                    "source": "overseas-error",
                }
            st.session_state.ov_broker_token = token
            st.session_state.ov_broker_notes = result.get("notes") or []
            st.session_state.ov_broker_source = result.get("source") or "overseas"
            st.session_state.ov_broker_df = mirae_rows_to_preview_df(
                result.get("rows") or []
            )
            st.session_state.pop("ov_broker_editor", None)
            st.session_state.pop("ov_broker_editor_v3", None)
            st.session_state.pop("ov_broker_editor_v4", None)

    notes = st.session_state.get("ov_broker_notes") or []
    df = st.session_state.get("ov_broker_df")
    empty_df = df is None or getattr(df, "empty", True)
    if empty_df:
        if up_name or notes:
            for note in notes:
                st.error(note)
            if not notes:
                st.error(
                    "파일을 받았지만 거래를 추출하지 못했습니다. "
                    "거래일자·매매구분·수량·단가가 있는 엑셀인지 확인하세요."
                )
        else:
            st.info("PDF 또는 엑셀을 업로드하면 파싱 미리보기가 표시됩니다.")
        return
    for note in notes:
        st.info(note)

    st.markdown("### 파싱 미리보기 (검수 및 수정)")
    st.caption(
        "적용환율이 0인 행(외화배당 등)은 **적용환율** 칸에 직접 입력하세요. "
        "**거래/정산금액**은 엑셀 빨간칸 그대로이며, 적요 앞 금액이 됩니다."
    )
    df = ensure_overseas_preview_columns(df)
    edited = st.data_editor(
        df,
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key="ov_broker_editor_v4",
        column_config={
            "증권사": st.column_config.TextColumn("증권사", width="small"),
            "거래유형": st.column_config.SelectboxColumn(
                "거래유형",
                options=["해외매수", "해외매도", "외화배당"],
                required=True,
            ),
            "수량": st.column_config.NumberColumn("수량", format="%.4f"),
            "외화단가": st.column_config.NumberColumn("외화단가", format="%.4f"),
            "거래/정산금액": st.column_config.NumberColumn(
                "거래/정산금액",
                format="%.4f",
                help="엑셀 거래/정산금액. 적요: USD 이 금액 / 수량주*단가 * 환율",
            ),
            "외화수수료": st.column_config.NumberColumn("외화수수료", format="%.4f"),
            "외화제세금": st.column_config.NumberColumn("외화제세금", format="%.4f"),
            "적용환율": st.column_config.NumberColumn(
                "적용환율",
                format="%.2f",
                min_value=0.0,
                step=0.1,
                help="0이면 직접 입력 → 원화·메모 자동 환산",
            ),
            "원화단가": st.column_config.NumberColumn(
                "원화단가", format="%.0f", help="외화단가 × 적용환율"
            ),
            "원화수수료": st.column_config.NumberColumn(
                "원화수수료", format="%.0f", help="외화수수료 × 적용환율"
            ),
            "원화재세금": st.column_config.NumberColumn(
                "원화재세금", format="%.0f", help="외화제세금 × 적용환율"
            ),
            "거래금액(원)": st.column_config.NumberColumn(
                "거래금액(원)", format="%.0f", help="환율 반영 정산금액"
            ),
        },
        disabled=["원화단가", "원화수수료", "원화재세금", "거래금액(원)"],
    )

    recalced = apply_overseas_preview_fx(edited)
    fx_changed = False
    try:
        prev_fx = pd.to_numeric(df["적용환율"], errors="coerce").fillna(0.0).reset_index(drop=True)
        new_fx = pd.to_numeric(recalced["적용환율"], errors="coerce").fillna(0.0).reset_index(drop=True)
        prev_amt = pd.to_numeric(df["거래금액(원)"], errors="coerce").fillna(0.0).reset_index(drop=True)
        new_amt = pd.to_numeric(recalced["거래금액(원)"], errors="coerce").fillna(0.0).reset_index(drop=True)
        if len(prev_fx) == len(new_fx) and (
            not prev_fx.equals(new_fx) or not prev_amt.equals(new_amt)
        ):
            fx_changed = True
    except Exception:  # noqa: BLE001
        fx_changed = False

    st.session_state.ov_broker_df = recalced
    if fx_changed:
        st.session_state.pop("ov_broker_editor", None)
        st.session_state.pop("ov_broker_editor_v3", None)
        st.session_state.pop("ov_broker_editor_v4", None)
        st.rerun()

    edited = recalced

    if not st.button(
        "선택된 사업자로 해외주식 거래 일괄 등록",
        type="primary",
        use_container_width=True,
        key="ov_broker_apply",
    ):
        return

    try:
        business = storage.get_or_create_business(biz)
        bid = int(business.id)  # type: ignore[arg-type]
        if ov_account is None or ov_account.id is None:
            raise ValueError("증권사/계좌를 선택하세요.")
        trades: list = []
        errors: list[str] = []
        to_save = apply_overseas_preview_fx(edited)
        for idx, row in to_save.iterrows():
            try:
                ticker = str(row.get("종목코드") or "").strip().upper()
                name = str(row.get("종목명") or ticker).strip() or ticker
                if not ticker:
                    ticker = name[:12].upper() if name else ""
                if not ticker:
                    raise ValueError("종목코드 없음")
                qty = float(row.get("수량") or 0)
                price_fx = float(row.get("외화단가") or 0)
                fee_fx = float(row.get("외화수수료") or 0)
                tax_fx = float(row.get("외화제세금") or 0)
                gross_fx = preview_settle_fx(row, qty, price_fx)
                # 사용자가 입력한 최종 적용환율 (공란 → 0, 추정 없음)
                fx = coerce_fx_rate(row.get("적용환율"))
                ccy = normalize_currency(str(row.get("통화코드") or "USD"))
                kind = str(row.get("거래유형") or "")
                if "배당" in kind:
                    continue
                if kind == "해외매수":
                    side = "BUY"
                elif kind == "해외매도":
                    side = "SELL"
                else:
                    side = "DIVIDEND"
                    if qty <= 0:
                        qty = 1.0
                if qty <= 0 or price_fx < 0:
                    raise ValueError("수량/단가를 확인하세요.")

                stock = storage.get_or_create_stock(
                    ticker, name, business_id=bid, market=MARKET_OVERSEAS
                )
                price_krw = _fx_to_krw(price_fx, fx)
                fee_krw = _fx_to_krw(fee_fx, fx)
                tax_krw = _fx_to_krw(tax_fx, fx)
                if side == "BUY":
                    settle = qty * price_krw + fee_krw + tax_krw
                elif side == "SELL":
                    settle = qty * price_krw - fee_krw - tax_krw
                else:
                    settle = qty * price_krw - tax_krw

                broker_name = str(row.get("증권사") or "")
                src_blob = f"{broker_name} {st.session_state.get('ov_broker_source') or ''}"
                if "kb" in src_blob.lower() or "KB증권" in src_blob:
                    ov_source = "broker:kb-overseas"
                elif "메리츠" in src_blob or "meritz" in src_blob.lower():
                    ov_source = "broker:meritz-overseas"
                elif "generic" in src_blob.lower():
                    ov_source = "broker:overseas-xlsx"
                else:
                    ov_source = "broker:mirae-overseas"
                memo = attach_fx_gross_memo(
                    str(row.get("메모") or ov_source),
                    gross_fx,
                )
                trades.append(
                    Trade(
                        id=None,
                        trade_date=str(row.get("거래일자") or "")[:10],
                        business_id=bid,
                        stock_id=int(stock.id),  # type: ignore[arg-type]
                        side=side,  # type: ignore[arg-type]
                        quantity=qty,
                        price=price_krw,
                        fee=fee_krw,
                        tax=tax_krw,
                        settlement_amount=settle,
                        memo=memo,
                        source=ov_source,
                        currency=ccy,
                        fx_rate=fx,
                        price_fx=price_fx,
                        fee_fx=fee_fx,
                        tax_fx=tax_fx,
                        settlement_fx=gross_fx,
                        account_id=int(ov_account.id),
                        account_name=ov_account.name,
                        account_code=ov_account.code,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"행 {int(idx) + 1}: {exc}")

        saved_n, db_dup, file_dup = save_trades_with_dedupe(
            storage,
            trades,
            market=MARKET_OVERSEAS,
            force_duplicates=force_ov_dup,
        )
        zero_fx_n = sum(1 for t in trades if float(getattr(t, "fx_rate", 0) or 0) <= 0)
        msg = f"{saved_n}건 반영 완료 → {biz} / {ov_account.name}"
        if db_dup or file_dup:
            msg += f" (DB중복 {db_dup}건, 파일중복 {file_dup}건 제외)"
        if zero_fx_n:
            msg += f" (환율 0 등록 {zero_fx_n}건 · 임의 환산 없음)"
        st.success(msg)
        if errors:
            with st.expander(f"오류/스킵 {len(errors)}건"):
                for e in errors:
                    st.write(e)
        for k in (
            "ov_broker_token",
            "ov_broker_notes",
            "ov_broker_df",
            "ov_broker_editor",
            "ov_broker_editor_v3",
            "ov_broker_editor_v4",
            "ov_broker_source",
        ):
            st.session_state.pop(k, None)
        st.rerun()
    except Exception as exc:  # noqa: BLE001
        st.error(str(exc))


def page_broker(
    storage: Storage,
    market: str = MARKET_DOMESTIC,
) -> None:
    market = normalize_market(market)
    st.caption(f"시장: **{market_label(market)}**")
    if market == MARKET_OVERSEAS:
        page_broker_overseas(storage)
        return
    st.subheader("증권사 거래내역 변환기")
    st.caption(
        "키움 / 미래에셋 / DB금융투자 / 한국투자 등 CSV·Excel·PDF 거래내역을 변환한 뒤, "
        "검수·수정 후 매매일지에 반영합니다."
    )

    businesses = storage.list_businesses()
    if not businesses:
        st.warning("사이드바 ＋ 버튼으로 사업자를 먼저 등록하세요.")
        return

    # 사이드바 선택 사업자가 있으면 기본값으로 사용
    biz_names = [b.name for b in businesses]
    default_idx = 0
    active_id = st.session_state.get("active_business_id")
    if active_id is not None:
        for i, b in enumerate(businesses):
            if b.id == active_id:
                default_idx = i
                break

    c1, c2 = st.columns(2)
    with c1:
        biz = st.selectbox("반영할 사업자", biz_names, index=default_idx, key="dom_broker_biz")
    with c2:
        broker = st.selectbox("증권사", ["자동 감지", *list_brokers()])
    dom_biz = next((b for b in businesses if b.name == biz), None)
    detected_broker = st.session_state.get("broker_parse_name") or (
        "" if broker == "자동 감지" else broker
    )
    dom_account = None
    if dom_biz and dom_biz.id is not None:
        dom_account = select_trade_account(
            storage,
            int(dom_biz.id),
            market,
            key="dom_broker_account",
            detected_name=str(detected_broker or ""),
        )
    force_dom_dup = render_dedupe_controls("dom_broker")

    up = st.file_uploader(
        "증권사 거래내역 업로드",
        type=["csv", "xlsx", "xls", "pdf"],
        key="broker_up",
        help="CSV, Excel, PDF 거래내역/체결내역을 업로드하세요.",
        on_change=persist_uploaded_file,
        args=("broker_up", "_broker_file"),
    )
    up_name, up_size, up_bytes = take_uploaded_file(up, "_broker_file")
    show_uploaded_file(up_name, up_size)

    if up_bytes and up_name:
        file_ext = up_name.split(".")[-1].lower().strip()
        file_token = f"{up_name}:{up_size}:{broker}:{biz}:{file_ext}"
        if st.session_state.get("broker_parse_token") != file_token:
            try:
                with st.spinner("파일을 변환하는 중…"):
                    if file_ext not in {"csv", "xlsx", "xls", "pdf"}:
                        if up_bytes[:4] != b"%PDF":
                            st.error(f"지원하지 않는 파일 형식입니다: {file_ext}")
                            return
                        file_ext = "pdf"

                    result = detect_and_parse(
                        up_bytes,
                        up_name if file_ext != "pdf" or up_name.lower().endswith(".pdf") else f"{up_name}.pdf",
                        default_business=biz,
                        broker_hint=broker,
                    )
                edited = result.dataframe.copy()
                if "거래유형" in edited.columns:
                    kind = edited["거래유형"].astype(str)
                    drop_div = kind.str.contains("배당", na=False)
                    n_div = int(drop_div.sum())
                    if n_div:
                        edited = edited.loc[~drop_div].reset_index(drop=True)
                        result.notes.append(
                            f"배당 {n_div}건은 증권사 변환기에서 제외했습니다."
                        )
                # 0건이거나 컬럼만 있는 경우 → 수동 입력용 빈 행 5개
                if edited.empty or (
                    "수량" in edited.columns
                    and edited["수량"].isna().all()
                    and edited.get("종목명", pd.Series(dtype=str)).astype(str).str.strip().eq("").all()
                ):
                    if edited.empty or len(edited) < 5:
                        edited = empty_trade_rows(biz, n=5)
                if "사업자" in edited.columns:
                    edited["사업자"] = edited["사업자"].fillna(biz).replace("", biz)
                st.session_state.broker_parse_token = file_token
                st.session_state.broker_parse_notes = result.notes
                st.session_state.broker_parse_name = result.broker_name
                st.session_state.broker_edit_df = edited
            except Exception as exc:  # noqa: BLE001
                st.error(str(exc))
                return

    if "broker_edit_df" not in st.session_state:
        st.info("변환할 CSV / Excel / PDF 파일을 업로드하세요.")
        return

    for note in st.session_state.get("broker_parse_notes", []):
        if OCR_TIP in note or "이미지형 PDF" in note or "Tesseract" in note:
            st.warning(note)
        else:
            st.info(note)

    st.markdown("### 파싱 및 변환 결과 (검수 및 수정)")
    st.caption(
        "셀을 직접 수정하거나, 엑셀/PDF에서 복사한 값을 붙여넣기(Ctrl+V)할 수 있습니다. "
        "행 추가/삭제 후 아래 버튼으로 등록하세요."
    )

    # 사업자 컬럼을 현재 선택값으로 동기화 제안
    preview_df = st.session_state.broker_edit_df.copy()
    if "사업자" in preview_df.columns:
        preview_df["사업자"] = preview_df["사업자"].fillna(biz)
        preview_df.loc[preview_df["사업자"].astype(str).str.strip() == "", "사업자"] = biz

    column_config = {
        "거래일자": st.column_config.TextColumn("거래일자", help="YYYY-MM-DD"),
        "사업자": st.column_config.TextColumn("사업자"),
        "종목코드": st.column_config.TextColumn("종목코드"),
        "종목명": st.column_config.TextColumn("종목명"),
        "거래유형": st.column_config.SelectboxColumn(
            "거래유형", options=["매수", "매도"], required=True
        ),
        "수량": st.column_config.NumberColumn("수량", min_value=0, step=1, format="%g"),
        "유가금잔": st.column_config.NumberColumn(
            "유가금잔",
            format="%g",
            help="시간순 정렬 후 종목별 매수(+)/매도(-) 누적 잔여수량",
            disabled=True,
        ),
        "단가": st.column_config.NumberColumn("단가", min_value=0, step=1, format="%g"),
        "수수료": st.column_config.NumberColumn("수수료", min_value=0, step=1, format="%g"),
        "제세금": st.column_config.NumberColumn("제세금", min_value=0, step=1, format="%g"),
        "정산금액": st.column_config.NumberColumn("정산금액", step=1, format="%g"),
        "메모": st.column_config.TextColumn("메모"),
    }

    edited_df = st.data_editor(
        preview_df,
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        column_config=column_config,
        key="broker_data_editor",
    )
    st.session_state.broker_edit_df = edited_df

    st.markdown("")
    apply = st.button(
        "선택된 사업자로 거래 내역 일괄 등록",
        type="primary",
        use_container_width=True,
    )

    if not apply:
        return

    try:
        to_save = edited_df.copy()
        if to_save.empty:
            st.warning("등록할 행이 없습니다.")
            return

        # 빈 행 제거
        if "수량" in to_save.columns:
            to_save = to_save[to_save["수량"].notna()]
            to_save = to_save[pd.to_numeric(to_save["수량"], errors="coerce").fillna(0) > 0]

        if "사업자" not in to_save.columns:
            to_save["사업자"] = biz
        else:
            to_save["사업자"] = to_save["사업자"].fillna(biz).replace("", biz)

        if dom_account is None or dom_account.id is None:
            raise ValueError("증권사/계좌를 선택하세요.")
        source_name = st.session_state.get("broker_parse_name", "broker")
        trades, errors = dataframe_to_trades(
            to_save,
            storage,
            default_business=biz,
            source=f"broker:{source_name}",
            market=market,
            account_id=int(dom_account.id),
        )
        saved_n, db_dup, file_dup = save_trades_with_dedupe(
            storage,
            trades,
            market=market,
            force_duplicates=force_dom_dup,
        )
        msg = f"{saved_n}건 반영 완료 ({source_name} → {biz} / {dom_account.name})"
        if db_dup or file_dup:
            msg += f" (DB중복 {db_dup}건, 파일중복 {file_dup}건 제외)"
        st.success(msg)
        if errors:
            with st.expander(f"오류/스킵 {len(errors)}건"):
                for e in errors:
                    st.write(e)

        positions, _, _warnings = compute_positions(
            storage.list_trades(market=market)
        )
        st.write("업데이트된 잔고 요약")
        st.dataframe(
            positions_to_dataframe(positions),
            use_container_width=True,
            hide_index=True,
        )

        # 검수 상태 초기화
        for key in (
            "broker_parse_token",
            "broker_parse_notes",
            "broker_parse_name",
            "broker_edit_df",
            "broker_data_editor",
        ):
            st.session_state.pop(key, None)
        st.rerun()
    except Exception as exc:  # noqa: BLE001
        st.error(str(exc))


def page_opening_lots(
    storage: Storage,
    business_id: int | None,
    market: str = MARKET_DOMESTIC,
) -> None:
    """프로그램 사용 전 보유분(기초잔고)을 표로 입력해 FIFO 원가로 등록."""
    market = normalize_market(market)
    overseas = market == MARKET_OVERSEAS
    st.subheader("기초데이터 (사용 전 보유분)")
    st.caption(
        "엑셀 파일이 아니라 **지금 들고 있는 수량과 매수 원가**를 넣습니다. "
        "같은 종목을 여러 단가로 샀으면 행을 나눠 적으면 FIFO가 맞습니다. "
        "이후 증권사 파일로 같은 매수를 다시 올리면 수량이 중복되니 주의하세요. "
        "회계전표에는 기초잔고 매수분개를 넣지 않습니다."
    )
    if business_id is None:
        st.warning("사이드바에서 사업자를 선택한 뒤 입력해 주세요. (전체 제외)")
        return

    account = select_trade_account(
        storage,
        int(business_id),
        market,
        key=f"opening_account_{market}",
        help_text="기초잔고가 들어 있는 증권사. FIFO 잔고는 증권사별로 분리됩니다.",
    )
    if account is None or account.id is None:
        st.warning("증권사/계좌를 선택하거나 이름을 입력하세요.")
        return

    today = date.today()
    as_of = st.date_input(
        "기초 기준일 (취득일을 비우면 이 날짜로 넣습니다)",
        value=date(today.year, 1, 1),
        format="YYYY-MM-DD",
        key=f"opening_as_of_{market}",
        help="보통 장부를 이 프로그램으로 시작하는 날, 또는 그 전날입니다.",
    )

    editor_key = f"opening_grid_{market}_{business_id}"
    if st.session_state.pop("_opening_reset", False):
        st.session_state.pop(editor_key, None)

    if overseas:
        column_config = {
            "취득일": st.column_config.TextColumn(
                "취득일", help="비우면 위 기준일. YYYY-MM-DD"
            ),
            "티커": st.column_config.TextColumn("티커", help="예: SOXL"),
            "종목명": st.column_config.TextColumn("종목명", help="비우면 티커와 같게 저장"),
            "수량": st.column_config.NumberColumn("수량", min_value=0.0, step=1.0, format="%.4f"),
            "외화단가": st.column_config.NumberColumn(
                "외화단가", min_value=0.0, step=0.0001, format="%.4f"
            ),
            "환율": st.column_config.NumberColumn("환율", min_value=0.0, step=0.01, format="%.2f"),
            "통화": st.column_config.SelectboxColumn(
                "통화", options=list(FX_CURRENCIES)
            ),
            "수수료(외화)": st.column_config.NumberColumn(
                "수수료(외화)", min_value=0.0, step=0.01, format="%.2f"
            ),
        }
    else:
        column_config = {
            "취득일": st.column_config.TextColumn(
                "취득일", help="비우면 위 기준일. YYYY-MM-DD"
            ),
            "종목명": st.column_config.TextColumn("종목명", required=False),
            "종목코드": st.column_config.TextColumn("종목코드", help="모르면 비워도 됩니다"),
            "수량": st.column_config.NumberColumn("수량", min_value=0, step=1, format="%,d"),
            "단가": st.column_config.NumberColumn("단가", min_value=0, step=1, format="%,d 원"),
            "수수료": st.column_config.NumberColumn(
                "수수료", min_value=0, step=1, format="%,d 원"
            ),
        }

    edited = st.data_editor(
        _blank_opening_df(market),
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        column_config=column_config,
        key=editor_key,
    )

    force_dup = render_dedupe_controls(f"opening_{market}")
    if st.button("기초잔고 등록", type="primary", use_container_width=True):
        try:
            trades = _opening_df_to_trades(
                edited,
                storage,
                business_id=int(business_id),
                market=market,
                account=account,
                as_of=as_of,
            )
            if not trades:
                st.warning("수량과 종목이 있는 행이 없습니다.")
                return
            saved_n, db_dup, file_dup = save_trades_with_dedupe(
                storage,
                trades,
                market=market,
                force_duplicates=force_dup,
            )
            msg = f"✅ 기초잔고 {saved_n}건을 '{account.name}'에 등록했습니다."
            if db_dup or file_dup:
                msg += f" (중복 {db_dup + file_dup}건 제외)"
            st.session_state["_opening_toast"] = msg
            st.session_state["_opening_reset"] = True
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))

    toast = st.session_state.pop("_opening_toast", None)
    if toast:
        st.toast(toast)
        st.success(toast)

    existing = [
        t
        for t in storage.list_trades(business_id=business_id, market=market)
        if _is_opening_trade(t)
        and (
            getattr(t, "account_id", None) is None
            or int(getattr(t, "account_id", 0) or 0) == int(account.id)
        )
    ]
    st.markdown(f"##### 이미 등록된 기초잔고 (`{account.name}`)")
    if not existing:
        st.caption("아직 없습니다. 위 표에 종목·수량·단가를 적고 등록하세요.")
        return
    rows = []
    for t in existing:
        row = {
            "ID": t.id,
            "취득일": t.trade_date,
            "종목": t.stock_name or t.stock_code,
            "코드": t.stock_code,
            "수량": t.quantity,
            "단가": t.price,
            "수수료": t.fee,
        }
        if overseas:
            row["외화단가"] = getattr(t, "price_fx", 0) or 0
            row["환율"] = getattr(t, "fx_rate", 0) or 0
            row["통화"] = getattr(t, "currency", "") or ""
        rows.append(row)
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _opening_df_to_trades(
    edited: pd.DataFrame,
    storage: Storage,
    *,
    business_id: int,
    market: str,
    account,
    as_of: date,
) -> list:
    market = normalize_market(market)
    overseas = market == MARKET_OVERSEAS
    trades: list = []
    errors: list[str] = []
    if edited is None or edited.empty:
        return trades

    for idx, row in edited.iterrows():
        row_no = int(idx) + 1 if isinstance(idx, (int, float)) else idx
        qty = _opening_cell_float(row.get("수량"))
        if qty <= 0:
            continue
        try:
            trade_date = _opening_cell_date(row.get("취득일"), as_of)
            if overseas:
                ticker = _opening_cell_str(row.get("티커")).upper()
                name = _opening_cell_str(row.get("종목명")) or ticker
                if not ticker:
                    raise ValueError("티커를 입력하세요.")
                price_fx = _opening_cell_float(row.get("외화단가"))
                fx_rate = _opening_cell_float(row.get("환율"))
                if fx_rate <= 0:
                    raise ValueError("환율을 입력하세요.")
                fee_fx = _opening_cell_float(row.get("수수료(외화)"))
                currency = normalize_currency(
                    _opening_cell_str(row.get("통화")) or "USD"
                )
                stock = storage.get_or_create_stock(
                    ticker, name, business_id=business_id, market=market
                )
                price_krw = _fx_to_krw(price_fx, fx_rate)
                fee_krw = _fx_to_krw(fee_fx, fx_rate)
                settle = qty * price_krw + fee_krw
                trades.append(
                    Trade(
                        id=None,
                        trade_date=trade_date,
                        business_id=business_id,
                        stock_id=int(stock.id),  # type: ignore[arg-type]
                        side="BUY",
                        quantity=qty,
                        price=price_krw,
                        fee=fee_krw,
                        tax=0.0,
                        settlement_amount=settle,
                        memo="기초잔고",
                        source="opening",
                        created_at=now_str(),
                        currency=currency,
                        fx_rate=fx_rate,
                        price_fx=price_fx,
                        fee_fx=fee_fx,
                        tax_fx=0.0,
                        account_id=int(account.id),
                        account_name=account.name,
                        account_code=account.code,
                        stock_code=stock.code,
                        stock_name=stock.name,
                    )
                )
                continue

            name = _opening_cell_str(row.get("종목명"))
            code = _opening_cell_str(row.get("종목코드"))
            if not name and not code:
                raise ValueError("종목명 또는 종목코드를 입력하세요.")
            price = _opening_cell_float(row.get("단가"))
            fee = _opening_cell_float(row.get("수수료"))
            if name:
                stock = storage.get_or_create_stock_by_name(
                    name,
                    code=code or None,
                    business_id=business_id,
                    market=market,
                )
            else:
                stock = storage.get_or_create_stock(
                    code, code, business_id=business_id, market=market
                )
            settle = qty * price + fee
            trades.append(
                Trade(
                    id=None,
                    trade_date=trade_date,
                    business_id=business_id,
                    stock_id=int(stock.id),  # type: ignore[arg-type]
                    side="BUY",
                    quantity=qty,
                    price=price,
                    fee=fee,
                    tax=0.0,
                    settlement_amount=settle,
                    memo="기초잔고",
                    source="opening",
                    created_at=now_str(),
                    currency="KRW",
                    account_id=int(account.id),
                    account_name=account.name,
                    account_code=account.code,
                    stock_code=stock.code,
                    stock_name=stock.name,
                )
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{row_no}행: {exc}")

    if errors:
        raise ValueError("\n".join(errors))
    return trades


def page_legacy_journal(
    storage: Storage,
    business_id: int | None,
    market: str = MARKET_DOMESTIC,
) -> None:
    market = normalize_market(market)
    st.caption(f"시장: **{market_label(market)}**")
    st.subheader("예전 매매일지")
    st.caption(
        "기존 시트별 '주식 매매일지' 엑셀을 업로드하면 전 시트 거래를 추출·검수 후 "
        "선택한 사업자로 일괄 등록합니다. 프로그램 사용 전 보유분만 넣을 때는 "
        "거래 넣기 → **기초데이터**를 쓰세요."
    )

    businesses = storage.list_businesses()
    if not businesses:
        st.warning("사이드바 ＋ 버튼으로 사업자를 먼저 등록하세요.")
        return

    biz_names = [b.name for b in businesses]
    default_idx = 0
    if business_id is not None:
        for i, b in enumerate(businesses):
            if b.id == business_id:
                default_idx = i
                break

    biz = st.selectbox("등록할 사업자", biz_names, index=default_idx, key="legacy_biz")
    legacy_biz = next((b for b in businesses if b.name == biz), None)
    legacy_account = None
    if legacy_biz and legacy_biz.id is not None:
        legacy_account = select_trade_account(
            storage,
            int(legacy_biz.id),
            market,
            key=f"legacy_account_{market}",
        )
    force_legacy_dup = render_dedupe_controls(f"legacy_{market}")

    if st.session_state.pop("_legacy_toast", False):
        st.toast(
            st.session_state.pop(
                "_legacy_toast_msg",
                "✅ 기초 데이터가 일괄 등록되었습니다!",
            )
        )
    if st.session_state.pop("_legacy_parse_toast", False):
        st.toast(
            st.session_state.pop(
                "_legacy_parse_toast_msg",
                "✅ 거래 내역이 정상 추출되었습니다!",
            )
        )

    up = st.file_uploader(
        "기존 주식 매매일지 엑셀 일괄 업로드",
        type=["xlsx", "xls"],
        key="legacy_up",
        help="시트마다 종목 매매일지가 있는 엑셀 파일을 업로드하세요.",
        on_change=persist_uploaded_file,
        args=("legacy_up", "_legacy_file"),
    )
    up_name, up_size, up_bytes = take_uploaded_file(up, "_legacy_file")
    show_uploaded_file(up_name, up_size)

    if up_bytes and up_name:
        token = f"{up_name}:{up_size}:{biz}"
        if st.session_state.get("legacy_token") != token:
            try:
                with st.spinner("매매일지를 추출하는 중…"):
                    df, notes, stats = parse_legacy_journal_excel(
                        up_bytes, default_business=biz
                    )
                if "사업자" in df.columns:
                    df["사업자"] = biz
                st.session_state.legacy_token = token
                st.session_state.legacy_notes = notes
                st.session_state.legacy_df = df
                st.session_state.legacy_stats = stats
                st.session_state["_legacy_parse_toast"] = True
                st.session_state["_legacy_parse_toast_msg"] = (
                    f"총 {stats['trade_count']}건의 거래 내역"
                    f"({stats['sheet_count']}개 종목 시트)이 정상 추출되었습니다."
                )
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(str(exc))
                return

    if "legacy_df" not in st.session_state:
        st.info("매매일지 엑셀(.xlsx)을 업로드하세요. Summary 등 요약 시트는 자동 제외됩니다.")
        with st.expander("인식 컬럼 안내"):
            st.markdown(
                """
                - **종목명**: 시트명 또는 종목명 열 (병합 셀은 자동 채움)
                - **매매 구분** / **매수 일자** / **매도 일자**
                - **체결 단가**, **체결 수량** 또는 **매도수량**
                - **매매 비용(수수료+제세금)**
                """
            )
        return

    stats = st.session_state.get("legacy_stats") or {}
    if stats:
        st.success(
            f"총 {stats.get('trade_count', 0)}건의 거래 내역"
            f"({stats.get('sheet_count', 0)}개 종목 시트)이 정상 추출되었습니다."
        )

    for note in st.session_state.get("legacy_notes", [])[1:]:
        st.caption(note)

    st.markdown("### 추출된 매매 내역 (검수 및 수정)")
    preview = st.session_state.legacy_df.copy()
    if "사업자" in preview.columns:
        preview["사업자"] = biz

    edited = st.data_editor(
        preview,
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        column_config={
            "거래일자": st.column_config.TextColumn("거래일자", help="YYYY-MM-DD"),
            "사업자": st.column_config.TextColumn("사업자"),
            "종목코드": st.column_config.TextColumn("종목코드"),
            "종목명": st.column_config.TextColumn("종목명"),
            "거래유형": st.column_config.SelectboxColumn(
                "거래유형", options=["매수", "매도"], required=True
            ),
            "수량": st.column_config.NumberColumn("수량", min_value=0, step=1, format="%,d"),
            "단가": st.column_config.NumberColumn("단가", min_value=0, step=1, format="%,d 원"),
            "수수료": st.column_config.NumberColumn("수수료", min_value=0, step=1, format="%,d 원"),
            "정산금액": st.column_config.NumberColumn("정산금액", step=1, format="%,d 원"),
            "메모": st.column_config.TextColumn("메모"),
        },
        key="legacy_editor",
    )
    st.session_state.legacy_df = edited

    st.markdown("")
    if st.button("기초 데이터 일괄 등록", type="primary", use_container_width=True):
        try:
            to_save = edited.copy()
            if to_save.empty:
                st.warning("등록할 행이 없습니다.")
                return
            if "수량" in to_save.columns:
                to_save = to_save[to_save["수량"].notna()]
                to_save = to_save[
                    pd.to_numeric(to_save["수량"], errors="coerce").fillna(0) > 0
                ]
            to_save["사업자"] = biz

            if legacy_account is None or legacy_account.id is None:
                raise ValueError("증권사/계좌를 선택하세요.")
            trades, errors = dataframe_to_trades(
                to_save,
                storage,
                default_business=biz,
                source="legacy_journal",
                market=market,
                account_id=int(legacy_account.id),
            )
            saved_n, db_dup, file_dup = save_trades_with_dedupe(
                storage,
                trades,
                market=market,
                force_duplicates=force_legacy_dup,
            )

            st.session_state["_legacy_toast"] = True
            st.session_state["_legacy_toast_msg"] = (
                f"✅ 기초 데이터 {saved_n}건이 '{biz}' / '{legacy_account.name}'에 등록되었습니다!"
            )
            if db_dup or file_dup:
                st.session_state["_legacy_toast_msg"] += (
                    f" (DB중복 {db_dup}건, 파일중복 {file_dup}건 제외)"
                )
            if errors:
                st.session_state["_legacy_toast_msg"] += f" (스킵 {len(errors)}건)"

            for key in (
                "legacy_token",
                "legacy_notes",
                "legacy_df",
                "legacy_editor",
                "legacy_stats",
            ):
                st.session_state.pop(key, None)
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))


def page_masters(
    storage: Storage,
    business_id: int | None,
    market: str = MARKET_DOMESTIC,
) -> None:
    market = normalize_market(market)
    render_step_guide("setup")
    st.caption(f"시장: **{market_label(market)}**")
    st.subheader("종목 · 증권사/계좌")
    if business_id is None:
        st.warning("사이드바에서 사업자를 선택한 뒤 종목·거래처를 관리해 주세요.")
        return

    tab_stock, tab_account = st.tabs(["📈 종목 관리", "🏦 거래처(증권사/계좌) 관리"])

    with tab_stock:
        stocks = storage.get_all_stocks(business_id, market=market)
        st.markdown("##### 등록된 종목")
        st.caption("현재 선택된 사업자에 연결된 종목만 표시됩니다.")
        if stocks:
            stock_df = pd.DataFrame(
                [
                    {
                        "선택": False,
                        "ID": int(s.id),
                        "종목코드": s.code,
                        "종목명": s.name,
                        "회계거래처코드": s.partner_code or "",
                        "비고": s.note or "",
                        "거래건수": storage.count_trades_for_stock(int(s.id))
                        if s.id is not None
                        else 0,
                    }
                    for s in stocks
                    if s.id is not None
                ]
            )
            edited_stocks = st.data_editor(
                stock_df,
                use_container_width=True,
                hide_index=True,
                num_rows="fixed",
                disabled=[c for c in stock_df.columns if c != "선택"],
                column_config={
                    "선택": st.column_config.CheckboxColumn("선택", default=False),
                    "ID": st.column_config.NumberColumn("ID", format="%d"),
                    "거래건수": st.column_config.NumberColumn("거래건수", format="%d"),
                },
                column_order=[
                    "선택",
                    "ID",
                    "종목코드",
                    "종목명",
                    "회계거래처코드",
                    "비고",
                    "거래건수",
                ],
                key="master_stock_editor",
            )
            selected_stocks = edited_stocks[edited_stocks["선택"] == True]  # noqa: E712

            if st.button(
                "🗑️ 선택한 종목 삭제",
                type="primary",
                key="master_stock_bulk_delete",
            ):
                if selected_stocks.empty:
                    st.info("삭제할 종목을 선택해 주세요.")
                elif int(selected_stocks["거래건수"].fillna(0).gt(0).sum()) > 0:
                    st.warning("거래 내역이 존재하는 종목은 삭제할 수 없습니다.")
                else:
                    try:
                        ids = [int(x) for x in selected_stocks["ID"].tolist()]
                        for stock_id in ids:
                            storage.delete_stock(stock_id, force=False)
                        msg = f"{len(ids)}개 종목이 삭제되었습니다."
                        st.session_state["_pending_toast"] = msg
                        st.toast(msg)
                        st.rerun()
                    except Exception as exc:  # noqa: BLE001
                        st.error(str(exc))
        else:
            st.info("등록된 종목이 없습니다.")

        st.divider()
        st.markdown("##### 신규 종목 추가")
        with st.form("master_stock_add_form", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            new_code = c1.text_input("종목코드", placeholder="005930")
            new_name = c2.text_input("종목명", placeholder="삼성전자")
            new_partner = c3.text_input("회계 거래처코드", placeholder="선택")
            if st.form_submit_button("종목 등록", type="primary", use_container_width=True):
                try:
                    storage.add_stock(
                        new_code,
                        new_name,
                        partner_code=new_partner,
                        business_id=int(business_id),
                        market=market,
                    )
                    st.session_state["_pending_toast"] = (
                        f"종목 '{new_name.strip()}'이(가) 등록되었습니다."
                    )
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(str(exc))

    with tab_account:
        accounts = storage.get_all_accounts(business_id, market=market)
        st.markdown("##### 등록된 거래처(증권사/계좌)")
        st.caption("사이드바 사업자와 별개로, 해당 사업자 소속 증권사·계좌만 관리합니다.")
        if accounts:
            acc_df = pd.DataFrame(
                [
                    {
                        "선택": False,
                        "ID": int(a.id),
                        "거래처코드": a.code or "",
                        "거래처명": a.name,
                        "계좌번호": a.account_no or "",
                        "거래건수": storage.count_trades_for_account(int(a.id)),
                        "비고": a.note or "",
                    }
                    for a in accounts
                    if a.id is not None
                ]
            )
            edited_accounts = st.data_editor(
                acc_df,
                use_container_width=True,
                hide_index=True,
                num_rows="fixed",
                disabled=[c for c in acc_df.columns if c != "선택"],
                column_config={
                    "선택": st.column_config.CheckboxColumn("선택", default=False),
                    "ID": st.column_config.NumberColumn("ID", format="%d"),
                },
                column_order=[
                    "선택",
                    "ID",
                    "거래처코드",
                    "거래처명",
                    "계좌번호",
                    "거래건수",
                    "비고",
                ],
                key="master_account_editor",
            )
            selected_accounts = edited_accounts[
                edited_accounts["선택"] == True  # noqa: E712
            ]

            if st.button(
                "🗑️ 선택한 거래처 삭제",
                type="primary",
                key="master_account_bulk_delete",
            ):
                if selected_accounts.empty:
                    st.info("삭제할 거래처를 선택해 주세요.")
                elif "거래건수" in selected_accounts.columns and int(
                    selected_accounts["거래건수"].fillna(0).gt(0).sum()
                ) > 0:
                    st.warning("거래 내역이 있는 증권사/계좌는 삭제할 수 없습니다. 먼저 거래를 옮기세요.")
                else:
                    try:
                        ids = [int(x) for x in selected_accounts["ID"].tolist()]
                        for account_id in ids:
                            storage.delete_account(account_id)
                        msg = f"{len(ids)}개 거래처가 삭제되었습니다."
                        st.session_state["_pending_toast"] = msg
                        st.toast(msg)
                        st.rerun()
                    except Exception as exc:  # noqa: BLE001
                        st.error(str(exc))
        else:
            st.info("등록된 거래처가 없습니다. 아래에서 증권사를 만들면 미지정 거래를 옮길 수 있습니다.")

        unassigned = next(
            (a for a in accounts if a.name == UNASSIGNED_ACCOUNT_NAME and a.id),
            None,
        )
        targets = [
            a for a in accounts if a.id and a.name != UNASSIGNED_ACCOUNT_NAME
        ]
        if unassigned and targets:
            st.markdown("##### 미지정 거래 증권사 이전")
            dest_name = st.selectbox(
                "이전할 증권사",
                [a.name for a in targets],
                key=f"reassign_dest_{market}",
            )
            if st.button("미지정 거래를 선택한 증권사로 옮기기", key=f"reassign_{market}"):
                dest = next(a for a in targets if a.name == dest_name)
                n = storage.reassign_account_trades(int(unassigned.id), int(dest.id))
                st.toast(f"{n}건을 '{dest.name}'으로 옮겼습니다.")
                st.rerun()

        st.divider()
        st.markdown("##### 신규 거래처 추가")
        with st.form("master_account_add_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            new_acc_code = c1.text_input("거래처코드", placeholder="선택")
            new_acc_name = c2.text_input("거래처명", placeholder="예: KB증권")
            c3, c4 = st.columns(2)
            new_acc_no = c3.text_input("계좌번호", placeholder="선택")
            new_acc_note = c4.text_input("비고", placeholder="선택")
            if st.form_submit_button(
                "거래처 등록", type="primary", use_container_width=True
            ):
                try:
                    storage.add_account(
                        int(business_id),
                        new_acc_name,
                        code=new_acc_code,
                        account_no=new_acc_no,
                        note=new_acc_note,
                        market=market,
                    )
                    st.session_state["_pending_toast"] = (
                        f"거래처 '{new_acc_name.strip()}'이(가) 등록되었습니다."
                    )
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(str(exc))


def page_settings(
    storage: Storage,
    business_id: int | None,
    *,
    mode: str = "stock",
    market: str = MARKET_DOMESTIC,
) -> None:
    market = normalize_market(market)
    """사업자별 환경설정.

    mode='stock'  → 주식 계정과목 + 종목 거래처코드
    mode='income' → 이자·배당 계정과목 + 증권사 거래처코드
    """
    if business_id is None:
        st.warning("사이드바에서 사업자를 선택한 뒤 환경설정을 저장해 주세요.")
        return

    company_name = next(
        (b.name for b in storage.list_businesses() if b.id == business_id),
        "",
    )
    st.caption(f"선택된 사업자: **{company_name or business_id}**")

    cfg = storage.get_account_config(business_id, market=market)

    if mode == "income":
        tab_income, tab_broker = st.tabs(
            [
                "💰 이자·배당 계정과목 설정",
                "🏦 증권사 거래처코드 매핑",
            ]
        )
        with tab_income:
            st.subheader("💰 이자·배당소득용 계정과목 코드")
            with st.form("settings_income_account_form"):
                c1, c2, c3 = st.columns(3)
                interest_code = c1.text_input(
                    "이자수익 계정코드",
                    value=cfg.interest_code,
                    placeholder="0901",
                )
                prepaid_tax_code = c2.text_input(
                    "선납세금 계정코드",
                    value=cfg.prepaid_tax_code,
                    placeholder="0136",
                )
                bank_code = c3.text_input(
                    "보통예금 계정코드",
                    value=cfg.bank_code,
                    placeholder="0103",
                )
                if st.form_submit_button(
                    "💾 이자·배당 계정과목 저장",
                    type="primary",
                    use_container_width=True,
                ):
                    try:
                        storage.save_income_account_config(
                            business_id,
                            IncomeAccountConfig(
                                interest_code=interest_code,
                                prepaid_tax_code=prepaid_tax_code,
                                bank_code=bank_code,
                            ),
                        )
                        msg = "이자·배당 계정과목이 저장되었습니다."
                        st.toast(msg)
                        st.session_state["_pending_toast"] = msg
                        st.rerun()
                    except Exception as exc:  # noqa: BLE001
                        st.error(str(exc))

        with tab_broker:
            st.subheader("🏦 증권사별 거래처코드 (이자·배당 전표)")
            st.caption("이자·배당 전표의 거래처코드 칸에 사용됩니다.")
            partners = storage.list_broker_partners(business_id)
            if not partners:
                storage.upsert_broker_partner(
                    "KB증권", "99200", business_id=business_id
                )
                partners = storage.list_broker_partners(business_id)

            partner_df = pd.DataFrame(
                [
                    {
                        "선택": False,
                        "ID": int(p.id),
                        "증권사": p.broker_name,
                        "거래처코드": p.partner_code or "",
                    }
                    for p in partners
                    if p.id is not None
                ]
            )
            edited_p = st.data_editor(
                partner_df,
                use_container_width=True,
                hide_index=True,
                num_rows="fixed",
                key="settings_broker_partner_editor",
                disabled=["ID"],
                column_config={
                    "선택": st.column_config.CheckboxColumn("선택", default=False),
                },
            )
            p1, p2 = st.columns(2)
            if p1.button(
                "💾 증권사 거래처코드 저장",
                use_container_width=True,
                key="settings_bp_save",
            ):
                updates = {
                    int(row["ID"]): (
                        str(row["증권사"] or ""),
                        str(row["거래처코드"] or ""),
                    )
                    for _, row in edited_p.iterrows()
                }
                n = storage.update_broker_partners(
                    updates, business_id=business_id
                )
                st.toast(f"{n}건 저장했습니다.")
                st.rerun()
            if p2.button(
                "🗑️ 선택 삭제",
                use_container_width=True,
                key="settings_bp_del",
            ):
                ids = [
                    int(x)
                    for x in edited_p.loc[
                        edited_p["선택"] == True, "ID"  # noqa: E712
                    ].tolist()
                ]
                for pid in ids:
                    storage.delete_broker_partner(pid, business_id=business_id)
                st.toast(f"{len(ids)}건 삭제했습니다.")
                st.rerun()

            with st.form("settings_broker_partner_add", clear_on_submit=True):
                a1, a2 = st.columns(2)
                new_name = a1.text_input("증권사명", placeholder="KB증권")
                new_code = a2.text_input("거래처코드", placeholder="99200")
                if st.form_submit_button("증권사 추가", use_container_width=True):
                    try:
                        storage.upsert_broker_partner(
                            new_name, new_code, business_id=business_id
                        )
                        st.toast("증권사 매핑이 추가되었습니다.")
                        st.rerun()
                    except Exception as exc:  # noqa: BLE001
                        st.error(str(exc))
        return

    # mode == "stock" (기본)
    tab_stock, tab_partner = st.tabs(
        [
            "📈 주식매매 계정과목 설정",
            "🏦 종목 거래처코드 매핑",
        ]
    )

    with tab_stock:
        st.subheader("📈 주식 매매용 계정과목 코드")
        with st.form("settings_stock_account_form"):
            c1, c2 = st.columns(2)
            security_code = c1.text_input(
                "투자유가증권 계정코드",
                value=cfg.security_code,
                placeholder="0178",
            )
            fee_code = c2.text_input(
                "지급수수료 계정코드",
                value=cfg.fee_code,
                placeholder="0965",
            )
            deposit_code = c1.text_input(
                "기타제예금 계정코드",
                value=cfg.deposit_code,
                placeholder="0104",
            )
            gain_code = c2.text_input(
                "투자자산처분이익 계정코드",
                value=cfg.gain_code,
                placeholder="0915",
            )
            loss_code = c1.text_input(
                "투자자산처분손실 계정코드",
                value=cfg.loss_code,
                placeholder="0953",
            )
            if st.form_submit_button(
                "💾 주식 계정과목 저장",
                type="primary",
                use_container_width=True,
            ):
                try:
                    base = storage.get_account_config(business_id, market=market)
                    storage.save_account_config(
                        business_id,
                        {
                            "security_code": security_code,
                            "fee_code": fee_code,
                            "deposit_code": deposit_code,
                            "gain_code": gain_code,
                            "loss_code": loss_code,
                            "interest_code": base.interest_code,
                            "prepaid_tax_code": base.prepaid_tax_code,
                            "bank_code": base.bank_code,
                        },
                        market=market,
                    )
                    msg = "주식 매매 계정과목이 저장되었습니다."
                    st.toast(msg)
                    st.session_state["_pending_toast"] = msg
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(str(exc))

    with tab_partner:
        st.subheader("🏦 종목별 회계 거래처코드")
        st.caption("매매 전표의 거래처코드 칸에 사용됩니다. 비우면 종목코드를 사용합니다.")
        stocks = storage.get_all_stocks(business_id, market=market)
        if stocks:
            stock_df = pd.DataFrame(
                [
                    {
                        "ID": int(s.id),
                        "종목코드": s.code,
                        "종목명": s.name,
                        "회계거래처코드": s.partner_code or "",
                    }
                    for s in stocks
                    if s.id is not None
                ]
            )
            edited_stocks = st.data_editor(
                stock_df,
                use_container_width=True,
                hide_index=True,
                num_rows="fixed",
                disabled=["ID", "종목코드", "종목명"],
                column_config={
                    "ID": st.column_config.NumberColumn("ID", format="%d"),
                    "회계거래처코드": st.column_config.TextColumn(
                        "회계거래처코드",
                        help="예: 05418",
                        max_chars=20,
                    ),
                },
                column_order=["ID", "종목코드", "종목명", "회계거래처코드"],
                key="settings_stock_partner_editor",
            )
            if st.button(
                "💾 종목 거래처코드 저장",
                type="primary",
                use_container_width=True,
                key="settings_stock_partner_save",
            ):
                try:
                    original = {
                        int(r["ID"]): str(r["회계거래처코드"] or "").strip()
                        for _, r in stock_df.iterrows()
                    }
                    updates = {}
                    for _, row in edited_stocks.iterrows():
                        sid = int(row["ID"])
                        new_code = str(row["회계거래처코드"] or "").strip()
                        if original.get(sid, "") != new_code:
                            updates[sid] = new_code
                    n = storage.update_stock_partner_codes(
                        updates, business_id=business_id
                    )
                    msg = (
                        f"{n}개 종목의 거래처코드가 저장되었습니다."
                        if n
                        else "변경된 종목 거래처코드가 없습니다."
                    )
                    st.toast(msg)
                    st.session_state["_pending_toast"] = msg
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(str(exc))
        else:
            st.info(
                "등록된 종목이 없습니다. "
                "'거래처 및 종목 관리'에서 먼저 등록해 주세요."
            )


@st.dialog("🗑️ 이자·배당 내역 전체 삭제")
def confirm_clear_income_records_dialog(
    storage: Storage,
    business_id: int,
    business_name: str,
) -> None:
    """현재 선택 사업자의 이자·배당 내역 전체 삭제 확인."""
    db = get_storage()
    records = db.list_income_records(business_id=int(business_id))
    st.warning(
        f"**[{business_name}]** 사업자에 등록된 이자·배당 내역 "
        f"**{len(records):,}건**을 모두 삭제합니다.\n\n"
        "등록된 모든 거래 내역을 삭제하시겠습니까? 되돌릴 수 없습니다."
    )
    confirm = st.checkbox(
        "위 안내를 확인했으며 전체 삭제를 진행합니다.",
        key=f"confirm_clear_income_{business_id}",
    )
    c1, c2 = st.columns(2)
    with c1:
        if st.button("취소", use_container_width=True, key="clear_income_cancel"):
            st.rerun()
    with c2:
        if st.button(
            "🗑️ 전체 삭제 실행",
            type="primary",
            use_container_width=True,
            disabled=not confirm,
            key="clear_income_confirm",
        ):
            try:
                n = db.clear_income_records_for_business(int(business_id))
                st.session_state["_pending_toast"] = (
                    f"[{business_name}] 이자·배당 내역 {n:,}건이 삭제되었습니다."
                )
                for k in (
                    "income_preview_df",
                    "income_preview_source",
                    "income_records_editor",
                    "income_preview_editor",
                    "income_upload_token",
                ):
                    st.session_state.pop(k, None)
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(str(exc))


def page_income(storage: Storage, business_id: int | None) -> None:
    """이자·배당소득 업로드 · 조회 · 전표 다운로드."""
    render_step_guide("income")
    st.caption(
        "원천징수영수증 업로드 및 전표 생성. "
        "계정과목·증권사 거래처코드는 계정코드 메뉴에서 관리합니다."
    )

    if business_id is None:
        st.warning("사이드바에서 사업자를 먼저 선택해 주세요.")
        return

    company_name = ""
    for b in storage.list_businesses():
        if b.id == business_id:
            company_name = b.name
            break

    st.markdown("##### 원천징수영수증 업로드")
    st.caption(
        "Excel 권장 컬럼: 지급일, 지급액, 법인세, 지방소득세, 금융상품명, 증권사, 소득구분. "
        "KB증권 증권계좌 과세내역조회(원천징수영수증) 엑셀(원거래일자·과세표준)도 지원합니다. "
        "PDF는 KB 계좌별과세내역·미래에셋 거래실적증명서(배당·예탁금이용료)를 지원합니다. "
        "미리보기에서 수정 후 저장하세요."
    )
    uploaded = st.file_uploader(
        "PDF / Excel / CSV",
        type=["pdf", "xlsx", "xls", "csv"],
        key="income_uploader",
        on_change=persist_uploaded_file,
        args=("income_uploader", "_income_file"),
    )
    up_name, up_size, up_bytes = take_uploaded_file(uploaded, "_income_file")
    show_uploaded_file(up_name, up_size)
    if up_bytes and up_name:
        token = f"{up_name}:{up_size}"
        if st.session_state.get("income_upload_token") != token:
            with st.spinner("원천징수 파일을 읽는 중…"):
                result = parse_income_file(up_bytes, up_name)
            for note in result.notes:
                st.info(note)
            if result.rows:
                st.session_state["income_preview_df"] = rows_to_dataframe(result.rows)
                st.session_state["income_preview_source"] = result.source
                st.session_state["income_upload_token"] = token
                st.session_state.pop("income_preview_editor", None)
            else:
                for note in result.notes:
                    st.warning(note)
        else:
            # 동일 파일 유지 중 — 이전 파싱 노트만 필요 시 생략
            pass

    preview = st.session_state.get("income_preview_df")
    if preview is not None and not getattr(preview, "empty", True):
        st.markdown("##### 파싱 미리보기 (저장 전 수정)")
        st.caption(
            "환율이 0인 외화배당은 **환율** 칸에 직접 입력하세요. "
            "입력 즉시 지급액·법인세·메모가 재계산됩니다. "
            "(지급액 = 외화지급액 × 환율, 법인세 = 외화원천세 × 환율)"
        )
        preview = ensure_income_preview_columns(preview)
        edited_preview = st.data_editor(
            preview,
            use_container_width=True,
            hide_index=True,
            num_rows="dynamic",
            key="income_preview_editor",
            column_config={
                "지급일": st.column_config.TextColumn("지급일", help="YYYY-MM-DD"),
                "종목코드": st.column_config.TextColumn("종목코드", width="small"),
                "통화": st.column_config.TextColumn("통화", width="small"),
                "외화지급액": st.column_config.NumberColumn(
                    "외화지급액", format="%.2f", help="외화 기준 지급액"
                ),
                "외화원천세": st.column_config.NumberColumn(
                    "외화원천세", format="%.2f", help="외화 기준 원천세"
                ),
                "환율": st.column_config.NumberColumn(
                    "환율",
                    format="%.2f",
                    min_value=0.0,
                    step=0.1,
                    help="미기재(0)인 경우 직접 입력 → 원화 자동 환산",
                ),
                "지급액": st.column_config.NumberColumn(
                    "지급액(원)", format="%.0f", help="외화×환율 자동계산"
                ),
                "법인세": st.column_config.NumberColumn(
                    "법인세(원)", format="%.0f", help="외화원천세×환율 자동계산"
                ),
                "지방소득세": st.column_config.NumberColumn(
                    "지방소득세", format="%.0f"
                ),
                "소득구분": st.column_config.SelectboxColumn(
                    "소득구분", options=["이자", "배당"]
                ),
            },
            disabled=["종목코드", "통화"],
        )
        # 환율 변경 → 지급액·법인세·메모 즉시 재계산
        recalced = apply_income_fx_rates(edited_preview)
        fx_changed = False
        try:
            prev_fx = pd.to_numeric(preview["환율"], errors="coerce").fillna(0.0).reset_index(drop=True)
            new_fx = pd.to_numeric(recalced["환율"], errors="coerce").fillna(0.0).reset_index(drop=True)
            prev_pay = pd.to_numeric(preview["지급액"], errors="coerce").fillna(0.0).reset_index(drop=True)
            new_pay = pd.to_numeric(recalced["지급액"], errors="coerce").fillna(0.0).reset_index(drop=True)
            prev_tax = pd.to_numeric(preview["법인세"], errors="coerce").fillna(0.0).reset_index(drop=True)
            new_tax = pd.to_numeric(recalced["법인세"], errors="coerce").fillna(0.0).reset_index(drop=True)
            has_fx_rows = bool(
                (pd.to_numeric(recalced["외화지급액"], errors="coerce").fillna(0) > 0).any()
            )
            if has_fx_rows and len(prev_fx) == len(new_fx):
                if (
                    not prev_fx.equals(new_fx)
                    or not prev_pay.equals(new_pay)
                    or not prev_tax.equals(new_tax)
                ):
                    fx_changed = True
        except Exception:  # noqa: BLE001
            fx_changed = False

        st.session_state["income_preview_df"] = recalced
        if fx_changed:
            st.session_state.pop("income_preview_editor", None)
            st.rerun()

        edited_preview = recalced
        c_save, c_clear = st.columns(2)
        if c_save.button(
            "💾 미리보기 내역 DB 저장",
            type="primary",
            use_container_width=True,
            key="income_preview_save",
        ):
            try:
                src = st.session_state.get("income_preview_source", "excel")
                to_save = apply_income_fx_rates(edited_preview)
                n = 0
                skipped_fx = 0
                for _, row in to_save.iterrows():
                    pay = str(row.get("지급일") or "").strip()[:10]
                    gross = float(row.get("지급액") or 0)
                    amt_fx = float(row.get("외화지급액") or 0)
                    fx = float(row.get("환율") or 0)
                    if amt_fx > 0 and fx <= 0:
                        skipped_fx += 1
                        continue
                    if not pay or gross <= 0:
                        continue
                    itype = (
                        "DIVIDEND"
                        if str(row.get("소득구분") or "").strip() == "배당"
                        else "INTEREST"
                    )
                    storage.add_income_record(
                        pay_date=pay,
                        business_id=int(business_id),
                        product_name=str(row.get("금융상품명") or ""),
                        broker_name=str(row.get("증권사") or ""),
                        income_type=itype,
                        gross_amount=gross,
                        corp_tax=float(row.get("법인세") or 0),
                        local_tax=float(row.get("지방소득세") or 0),
                        memo=str(row.get("메모") or ""),
                        source=src,
                    )
                    n += 1
                st.session_state.pop("income_preview_df", None)
                st.session_state.pop("income_preview_editor", None)
                st.session_state.pop("income_upload_token", None)
                msg = f"{n}건의 이자·배당 내역을 저장했습니다."
                if skipped_fx:
                    msg += f" (환율 미입력 외화 {skipped_fx}건 제외)"
                st.session_state["_pending_toast"] = msg
                st.toast(msg)
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(str(exc))
        if c_clear.button("미리보기 지우기", use_container_width=True):
            st.session_state.pop("income_preview_df", None)
            st.session_state.pop("income_preview_editor", None)
            st.session_state.pop("income_upload_token", None)
            st.rerun()

    st.divider()
    head_l, head_r = st.columns([3, 1])
    with head_l:
        st.markdown("##### 등록된 내역")
    records = storage.list_income_records(business_id=business_id)
    with head_r:
        if st.button(
            "🗑️ 전체 삭제",
            use_container_width=True,
            type="secondary",
            disabled=not records,
            key="income_clear_all",
            help="현재 사업자의 이자·배당 내역을 모두 삭제합니다",
        ):
            confirm_clear_income_records_dialog(
                storage, int(business_id), company_name or str(business_id)
            )
    if records:
        rec_df = pd.DataFrame(
            [
                {
                    "선택": False,
                    "ID": int(r.id),
                    "지급일": r.pay_date,
                    "금융상품명": r.product_name,
                    "증권사": r.broker_name,
                    "소득구분": "배당" if r.income_type == "DIVIDEND" else "이자",
                    "지급액": r.gross_amount,
                    "법인세": r.corp_tax,
                    "지방소득세": r.local_tax,
                    "정산입금": r.net_amount,
                    "메모": r.memo,
                }
                for r in records
                if r.id is not None
            ]
        )
        edited_recs = st.data_editor(
            rec_df,
            use_container_width=True,
            hide_index=True,
            num_rows="fixed",
            key="income_records_editor",
            disabled=["ID", "정산입금"],
            column_config={
                "선택": st.column_config.CheckboxColumn("선택", default=False),
                "지급액": st.column_config.NumberColumn("지급액", format="%.0f"),
                "법인세": st.column_config.NumberColumn("법인세", format="%.0f"),
                "지방소득세": st.column_config.NumberColumn(
                    "지방소득세", format="%.0f"
                ),
                "정산입금": st.column_config.NumberColumn("정산입금", format="%.0f"),
                "소득구분": st.column_config.SelectboxColumn(
                    "소득구분", options=["이자", "배당"]
                ),
            },
        )
        b1, b2 = st.columns(2)
        if b1.button("💾 수정 내용 저장", use_container_width=True, key="income_upd"):
            try:
                for _, row in edited_recs.iterrows():
                    storage.update_income_record(
                        int(row["ID"]),
                        pay_date=str(row["지급일"]),
                        product_name=str(row.get("금융상품명") or ""),
                        broker_name=str(row.get("증권사") or ""),
                        income_type=(
                            "DIVIDEND"
                            if str(row.get("소득구분") or "") == "배당"
                            else "INTEREST"
                        ),
                        gross_amount=float(row.get("지급액") or 0),
                        corp_tax=float(row.get("법인세") or 0),
                        local_tax=float(row.get("지방소득세") or 0),
                        memo=str(row.get("메모") or ""),
                    )
                st.toast("이자·배당 내역이 저장되었습니다.")
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(str(exc))
        if b2.button("🗑️ 선택 삭제", use_container_width=True, key="income_del"):
            ids = [
                int(x)
                for x in edited_recs.loc[edited_recs["선택"] == True, "ID"].tolist()  # noqa: E712
            ]
            if not ids:
                st.info("삭제할 행을 선택해 주세요.")
            else:
                storage.delete_income_records(ids)
                st.toast(f"{len(ids)}건 삭제했습니다.")
                st.rerun()
    else:
        st.info("등록된 이자·배당 내역이 없습니다. 위에서 파일을 업로드해 주세요.")

    with st.expander("➕ 수동으로 1건 추가"):
        with st.form("income_manual_add", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            m_date = c1.date_input("지급일", value=date.today())
            m_product = c2.text_input("금융상품명", placeholder="RP / CMA 등")
            m_broker = c3.text_input("증권사", placeholder="KB증권")
            c4, c5, c6, c7 = st.columns(4)
            m_type = c4.selectbox("소득구분", ["이자", "배당"])
            m_gross = c5.number_input("지급액", min_value=0.0, step=1000.0)
            m_corp = c6.number_input("법인세", min_value=0.0, step=100.0)
            m_local = c7.number_input("지방소득세", min_value=0.0, step=10.0)
            if st.form_submit_button("추가", type="primary", use_container_width=True):
                try:
                    storage.add_income_record(
                        pay_date=m_date.isoformat(),
                        business_id=int(business_id),
                        product_name=m_product,
                        broker_name=m_broker,
                        income_type="DIVIDEND" if m_type == "배당" else "INTEREST",
                        gross_amount=m_gross,
                        corp_tax=m_corp,
                        local_tax=m_local,
                        source="manual",
                    )
                    st.toast("1건 추가했습니다.")
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(str(exc))

    st.divider()
    st.markdown("##### 회계 전표 다운로드")
    today = date.today()
    if "income_voucher_range" in st.session_state and "income_start_date" not in st.session_state:
        old = st.session_state.pop("income_voucher_range", None)
        if isinstance(old, (list, tuple)) and len(old) == 2:
            st.session_state["income_start_date"] = old[0]
            st.session_state["income_end_date"] = old[1]
        else:
            st.session_state.pop("income_voucher_range", None)
    if "income_start_date" not in st.session_state:
        st.session_state["income_start_date"] = date(today.year, 1, 1)
    if "income_end_date" not in st.session_state:
        st.session_state["income_end_date"] = today

    q1, q2, q3 = st.columns(3)
    if q1.button("이번 달", key="inc_preset_m", use_container_width=True):
        st.session_state["income_start_date"] = date(today.year, today.month, 1)
        st.session_state["income_end_date"] = today
        st.rerun()
    if q2.button("올해 (1월~현재)", key="inc_preset_y", use_container_width=True):
        st.session_state["income_start_date"] = date(today.year, 1, 1)
        st.session_state["income_end_date"] = today
        st.rerun()
    if q3.button("전체 기간", key="inc_preset_a", use_container_width=True):
        all_recs = storage.list_income_records(business_id=business_id)
        if all_recs:
            dates = sorted(str(r.pay_date)[:10] for r in all_recs)
            st.session_state["income_start_date"] = date.fromisoformat(dates[0])
            st.session_state["income_end_date"] = date.fromisoformat(dates[-1])
        else:
            st.session_state["income_start_date"] = date(2020, 1, 1)
            st.session_state["income_end_date"] = today
        st.rerun()

    col_d1, col_d2 = st.columns(2)
    with col_d1:
        start_date = st.date_input(
            "📅 시작일 선택",
            format="YYYY-MM-DD",
            key="income_start_date",
        )
    with col_d2:
        end_date = st.date_input(
            "📅 종료일 선택",
            format="YYYY-MM-DD",
            key="income_end_date",
        )
    if start_date > end_date:
        start_date, end_date = end_date, start_date
        st.caption("※ 시작일이 종료일보다 늦어 순서를 바꿔 조회합니다.")

    period_recs = storage.get_income_records_by_period(
        business_id, start_date, end_date
    )
    inc_cfg = storage.get_income_account_config(business_id)
    broker_map = storage.broker_partner_map(business_id)
    line_n = len(
        income_to_voucher_lines(
            period_recs,
            account_config=inc_cfg,
            broker_partner_map=broker_map,
        )
    )
    st.info(
        f"선택된 기간: **{start_date} ~ {end_date}** "
        f"(총 {len(period_recs)}건, {line_n}줄 분개)"
    )
    if not period_recs:
        st.info("💡 선택한 기간에 해당하는 이자·배당 내역이 없습니다.")
        st.download_button(
            "📥 이자·배당 회계 전표 엑셀 다운로드",
            data=b"",
            file_name="empty.xlsx",
            disabled=True,
            use_container_width=True,
        )
    else:
        xbytes = export_income_voucher_excel_bytes(
            period_recs,
            company_name=company_name,
            account_config=inc_cfg,
            broker_partner_map=broker_map,
        )
        fname = (
            f"엑셀자료일반전표전송_이자배당_"
            f"{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}.xlsx"
        )
        st.download_button(
            "📥 이자·배당 회계 전표 엑셀 다운로드",
            data=xbytes,
            file_name=fname,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            use_container_width=True,
        )


def main() -> None:
    init_session_state()
    inject_sidebar_styles()
    storage = get_storage()

    pending_toast = st.session_state.pop("_pending_toast", None)
    if pending_toast:
        st.toast(pending_toast)

    # 사이드바: 사업자 → 시장 → 작업 순서
    business_id = sidebar_business_selector(storage)
    st.sidebar.divider()
    menu = sidebar_tree_menu()
    st.sidebar.divider()
    st.sidebar.caption("DB: Supabase · 배포: Streamlit Cloud")

    # F5 복원용 URL 동기화 (사업자·메뉴·시장)
    sync_url_params()

    title, caption = MENU_PAGE_META.get(menu, MENU_PAGE_META[DEFAULT_MENU])
    market = menu_market(menu)
    if market:
        title = f"{market_label(market)} · {title}"
    st.title(title)
    st.caption(caption)
    route_active_menu(storage, business_id, menu)


if __name__ == "__main__":
    main()
