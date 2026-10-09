-- 單向分享（2026-10-09）：網站目前為單向模式（TWO_WAY=false），分享連結 #s=<key> 直接回報告內容，
-- 不選名字、不登入；每次開啟寫一筆 share_opens 供日後查證「有沒有被打開」。

create table if not exists public.share_opens (
  id bigint generated always as identity primary key,
  report_id uuid not null references public.reports(id) on delete cascade,
  opened_at timestamptz not null default now()
);
create index if not exists share_opens_report_idx on public.share_opens (report_id, opened_at desc);
alter table public.share_opens enable row level security;
revoke all on table public.share_opens from anon, authenticated;

create or replace function public.rs_get_shared(p_key text)
returns jsonb
language plpgsql volatile security definer
set search_path = public, extensions
as $$
declare
  rep public.reports;
begin
  if p_key is null or length(p_key) < 16 then
    raise exception 'invalid token';
  end if;
  select * into rep from public.reports
   where share_key_sha256 = encode(digest(p_key, 'sha256'), 'hex');
  if not found then
    raise exception 'invalid token';
  end if;
  insert into public.share_opens (report_id) values (rep.id);
  return jsonb_build_object(
    'report_id', rep.id, 'period', rep.period, 'title', rep.title,
    'content', rep.content, 'version', rep.version,
    'published_at', rep.published_at, 'status_anchors', to_jsonb(rep.status_anchors));
end
$$;
revoke all on function public.rs_get_shared(text) from public;
grant execute on function public.rs_get_shared(text) to anon, authenticated;
