-- 0003_notifications.sql — notifications outbox 表與 trigger（v1 只寫不外送；Email/LINE 為 v2）
-- ⚠ SQL 未實測：撰寫時 Supabase 帳號未開、本機無 psql/docker，只做過靜態自檢（tests/test_sql_static.py）。
-- 規則（PLAN §5）：作者回覆讀者的留言 → 寫給該讀者（kind='reply'）；
--                  讀者留言（含回覆）→ 寫給所有 active author（kind='new_comment'）。
-- v1 站內未讀徽章由 rp_list_reports 現算，不讀本表；sent_at 留給 v2 外送 worker。

create table if not exists public.notifications (
  id          bigint generated always as identity primary key,
  reader_id   uuid not null references public.readers(id) on delete cascade,
  report_id   uuid not null references public.reports(id) on delete cascade,
  comment_id  uuid not null references public.comments(id) on delete cascade,
  kind        text not null check (kind in ('reply','new_comment')),
  created_at  timestamptz not null default now(),
  sent_at     timestamptz null
);
create index if not exists notifications_unsent_idx on public.notifications (created_at) where sent_at is null;

alter table public.notifications enable row level security;
revoke all on table public.notifications from anon, authenticated;

create or replace function public._rp_notify_on_comment()
returns trigger
language plpgsql security definer
set search_path = public, extensions
as $$
declare
  v_role text;
  v_parent_reader uuid;
  v_parent_role text;
begin
  select role into v_role from public.readers where id = new.reader_id;

  if v_role = 'author' then
    if new.parent_id is not null then
      select c.reader_id, r.role into v_parent_reader, v_parent_role
        from public.comments c join public.readers r on r.id = c.reader_id
       where c.id = new.parent_id;
      if v_parent_role = 'reader' and v_parent_reader <> new.reader_id then
        insert into public.notifications (reader_id, report_id, comment_id, kind)
        values (v_parent_reader, new.report_id, new.id, 'reply');
      end if;
    end if;
  else
    insert into public.notifications (reader_id, report_id, comment_id, kind)
    select a.id, new.report_id, new.id, 'new_comment'
      from public.readers a
     where a.role = 'author' and a.active and a.id <> new.reader_id;
  end if;
  return new;
end
$$;

revoke all on function public._rp_notify_on_comment() from public, anon, authenticated;

drop trigger if exists comments_notify on public.comments;
create trigger comments_notify
  after insert on public.comments
  for each row execute function public._rp_notify_on_comment();
