-- 해외주식 적요 앞 금액: 엑셀 '거래/정산금액'을 그대로 저장
alter table public.trades
  add column if not exists settlement_fx double precision not null default 0;
