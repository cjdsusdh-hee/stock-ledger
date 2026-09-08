-- settlement_fx 추가 후 뷰가 t.*를 옛 컬럼으로 고정해 있어 다시 만든다.
drop view if exists public.trades_enriched;

create view public.trades_enriched
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
