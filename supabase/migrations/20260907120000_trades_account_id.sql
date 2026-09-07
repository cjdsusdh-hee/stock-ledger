-- 증권사(계좌)별 원장: trades.account_id + 조회 뷰/인덱스

alter table public.trades
  add column if not exists account_id bigint references public.accounts(id);

create index if not exists trades_account_id_idx
  on public.trades (account_id);

create index if not exists trades_dedupe_idx
  on public.trades (
    business_id,
    account_id,
    trade_date,
    stock_id,
    side,
    quantity,
    price
  );

-- 기존 행은 사업자·시장별 '미지정' 계좌로 백필
insert into public.accounts (business_id, name, code, account_no, note, created_at, market)
select
  s.business_id,
  '미지정',
  '',
  '',
  '기존 거래 백필용 기본 증권사',
  now()::text,
  s.market
from (
  select distinct t.business_id, coalesce(st.market, 'domestic') as market
  from public.trades t
  left join public.stocks st on st.id = t.stock_id
  where t.account_id is null
) s
where not exists (
  select 1 from public.accounts a
  where a.business_id = s.business_id
    and a.market = s.market
    and a.name = '미지정'
);

update public.trades t
set account_id = a.id
from public.stocks st, public.accounts a
where t.account_id is null
  and st.id = t.stock_id
  and a.business_id = t.business_id
  and a.market = coalesce(st.market, 'domestic')
  and a.name = '미지정';

-- 남는 행(종목 조인 실패)은 국내 미지정으로
update public.trades t
set account_id = a.id
from public.accounts a
where t.account_id is null
  and a.business_id = t.business_id
  and a.market = 'domestic'
  and a.name = '미지정';

create or replace view public.trades_enriched
with (security_invoker = true)
as
select
  t.*,
  b.name as business_name,
  s.code as stock_code,
  s.name as stock_name,
  s.market as stock_market,
  a.name as account_name,
  a.code as account_code
from public.trades t
left join public.businesses b on b.id = t.business_id
left join public.stocks s on s.id = t.stock_id
left join public.accounts a on a.id = t.account_id;

grant select on public.trades_enriched to anon, authenticated;
