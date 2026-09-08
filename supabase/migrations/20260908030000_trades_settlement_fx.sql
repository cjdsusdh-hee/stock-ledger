-- 컬럼 추가만. 기존 거래 수치 UPDATE 금지. 재적용하지 말 것.
alter table public.trades
  add column if not exists settlement_fx double precision not null default 0;
