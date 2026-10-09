-- 0002_rpc.sql — 全部 rp_* RPC（security definer，第一參數 p_token）
-- ⚠ SQL 未實測：撰寫時 Supabase 帳號未開、本機無 psql/docker，只做過靜態自檢（tests/test_sql_static.py）。
-- 契約：docs/CONTRACTS.md §5.2（名稱／參數／回傳鍵）、§5.3（raise 字串逐字）。
-- 檢查順序（與 web/js/api.js mock 一致）：token → 報告存在(not found) → 權限(forbidden) → 內容(body/parent/status)。
-- 內部 helper（_rp_*）一律 revoke from public，anon 無法直接呼叫。

-- ── helpers ────────────────────────────────────────────────────────────

create or replace function public._rp_auth(p_token text)
returns public.readers
language plpgsql stable security definer
set search_path = public, extensions
as $$
declare
  me public.readers;
begin
  if p_token is null or p_token = '' then
    raise exception 'invalid token';
  end if;
  select * into me from public.readers
   where token_sha256 = encode(digest(p_token, 'sha256'), 'hex') and active;
  if not found then
    raise exception 'invalid token';
  end if;
  return me;
end
$$;

create or replace function public._rp_require_report(p_me public.readers, p_report_id uuid)
returns public.reports
language plpgsql stable security definer
set search_path = public, extensions
as $$
declare
  rep public.reports;
begin
  select * into rep from public.reports where id = p_report_id;
  if not found then
    raise exception 'not found';
  end if;
  if p_me.role <> 'author' and not exists (
       select 1 from public.report_access a
        where a.report_id = rep.id and a.reader_id = p_me.id) then
    raise exception 'forbidden';
  end if;
  return rep;
end
$$;

-- JS String.prototype.trim 等價（含換行、全形空白以外的 \s）
create or replace function public._rp_clean_body(p_body text)
returns text
language plpgsql immutable security definer
set search_path = public, extensions
as $$
declare
  b text := regexp_replace(coalesce(p_body, ''), '^[\s ﻿]+|[\s ﻿]+$', '', 'g');
begin
  if b = '' then
    raise exception 'body empty';
  end if;
  if char_length(b) > 2000 then
    raise exception 'body too long';
  end if;
  return b;
end
$$;

create or replace function public._rp_comment_json(c public.comments)
returns jsonb
language sql stable security definer
set search_path = public, extensions
as $$
  select jsonb_build_object(
    'id', c.id, 'anchor', c.anchor, 'reader_id', c.reader_id,
    'reader_name', r.name, 'role', r.role, 'parent_id', c.parent_id,
    'body', case when c.deleted then '' else c.body end,
    'created_at', c.created_at, 'edited_at', c.edited_at,
    'deleted', c.deleted, 'orphaned', c.orphaned)
  from public.readers r where r.id = c.reader_id
$$;

create or replace function public._rp_own_live_comment(p_me public.readers, p_comment_id uuid)
returns public.comments
language plpgsql stable security definer
set search_path = public, extensions
as $$
declare
  c public.comments;
begin
  select * into c from public.comments where id = p_comment_id;
  if not found then
    raise exception 'not found';
  end if;
  perform public._rp_require_report(p_me, c.report_id);
  if c.reader_id <> p_me.id or c.deleted then
    raise exception 'forbidden';
  end if;
  return c;
end
$$;

-- ── RPC ────────────────────────────────────────────────────────────────

create or replace function public.rp_whoami(p_token text)
returns jsonb
language plpgsql stable security definer
set search_path = public, extensions
as $$
declare
  me public.readers := public._rp_auth(p_token);
begin
  return jsonb_build_object('reader_id', me.id, 'name', me.name, 'role', me.role);
end
$$;

create or replace function public.rp_list_reports(p_token text)
returns jsonb
language plpgsql stable security definer
set search_path = public, extensions
as $$
declare
  me public.readers := public._rp_auth(p_token);
  result jsonb;
begin
  select coalesce(jsonb_agg(x.obj order by x.period desc), '[]'::jsonb) into result
  from (
    select rep.period, jsonb_build_object(
      'report_id', rep.id, 'period', rep.period, 'title', rep.title,
      'published_at', rep.published_at, 'version', rep.version,
      'first_at', rd.first_at, 'last_at', rd.last_at,
      'comment_count', (select count(*) from public.comments c
                         where c.report_id = rep.id and not c.deleted),
      'unread_count', (select count(*) from public.comments c
                        where c.report_id = rep.id and not c.deleted
                          and c.reader_id <> me.id
                          and (sn.last_seen_comment_at is null or c.created_at > sn.last_seen_comment_at)),
      'unread_replies', (select count(*) from public.comments c
                          join public.comments p on p.id = c.parent_id
                         where c.report_id = rep.id and not c.deleted
                           and c.reader_id <> me.id and p.reader_id = me.id
                           and (sn.last_seen_comment_at is null or c.created_at > sn.last_seen_comment_at)),
      'readers', case when me.role = 'author' then (
          select coalesce(jsonb_agg(jsonb_build_object(
                   'reader_id', r.id, 'name', r.name,
                   'first_at', r2.first_at, 'last_at', r2.last_at) order by r.created_at), '[]'::jsonb)
            from public.report_access a
            join public.readers r on r.id = a.reader_id and r.role = 'reader'
            left join public.reads r2 on r2.report_id = rep.id and r2.reader_id = r.id
           where a.report_id = rep.id)
        else '[]'::jsonb end
    ) as obj
    from public.reports rep
    left join public.reads rd on rd.report_id = rep.id and rd.reader_id = me.id
    left join public.seen sn on sn.report_id = rep.id and sn.reader_id = me.id
    where me.role = 'author'
       or exists (select 1 from public.report_access a
                   where a.report_id = rep.id and a.reader_id = me.id)
  ) x;
  return result;
end
$$;

create or replace function public.rp_get_report(p_token text, p_period text)
returns jsonb
language plpgsql stable security definer
set search_path = public, extensions
as $$
declare
  me public.readers := public._rp_auth(p_token);
  rid uuid;
  rep public.reports;
begin
  select id into rid from public.reports where period = p_period;
  if rid is null then
    raise exception 'not found';
  end if;
  rep := public._rp_require_report(me, rid);
  return jsonb_build_object(
    'report_id', rep.id, 'period', rep.period, 'title', rep.title,
    'content', rep.content, 'version', rep.version,
    'published_at', rep.published_at, 'status_anchors', to_jsonb(rep.status_anchors));
end
$$;

create or replace function public.rp_mark_read(p_token text, p_report_id uuid)
returns jsonb
language plpgsql volatile security definer
set search_path = public, extensions
as $$
declare
  me public.readers := public._rp_auth(p_token);
  rep public.reports := public._rp_require_report(me, p_report_id);
  v_first timestamptz;
  v_last timestamptz;
begin
  insert into public.reads (report_id, reader_id, first_at, last_at)
  values (rep.id, me.id, now(), now())
  on conflict (report_id, reader_id) do update set last_at = now()
  returning first_at, last_at into v_first, v_last;
  return jsonb_build_object('first_at', v_first, 'last_at', v_last);
end
$$;

create or replace function public.rp_list_comments(p_token text, p_report_id uuid, p_since timestamptz default null)
returns jsonb
language plpgsql stable security definer
set search_path = public, extensions
as $$
declare
  me public.readers := public._rp_auth(p_token);
  rep public.reports := public._rp_require_report(me, p_report_id);
begin
  return jsonb_build_object(
    'server_time', now(),
    'comments', coalesce((
      select jsonb_agg(public._rp_comment_json(c) order by c.created_at, c.id)
        from public.comments c
       where c.report_id = rep.id
         and (p_since is null
              or greatest(c.created_at, coalesce(c.edited_at, c.created_at)) > p_since)
    ), '[]'::jsonb),
    'statuses', coalesce((
      select jsonb_agg(jsonb_build_object(
               'anchor', s.anchor, 'reader_id', s.reader_id, 'reader_name', r.name,
               'status', s.status, 'updated_at', s.updated_at) order by s.updated_at)
        from public.statuses s
        join public.readers r on r.id = s.reader_id
       where s.report_id = rep.id
         and (p_since is null or s.updated_at > p_since)
    ), '[]'::jsonb));
end
$$;

create or replace function public.rp_add_comment(p_token text, p_report_id uuid, p_anchor text, p_body text, p_parent_id uuid)
returns jsonb
language plpgsql volatile security definer
set search_path = public, extensions
as $$
declare
  me public.readers := public._rp_auth(p_token);
  rep public.reports := public._rp_require_report(me, p_report_id);
  v_body text := public._rp_clean_body(p_body);
  par public.comments;
  c public.comments;
begin
  if p_anchor is null or p_anchor = '' or char_length(p_anchor) > 200 then
    raise exception 'not found';
  end if;
  if p_parent_id is not null then
    select * into par from public.comments where id = p_parent_id and report_id = rep.id;
    if not found then
      raise exception 'not found';
    end if;
    if par.parent_id is not null then
      raise exception 'reply depth';
    end if;
    p_anchor := par.anchor;  -- 回覆一律掛在父留言的錨點，避免跨錨點回覆在前端看不到
  end if;
  insert into public.comments (report_id, anchor, reader_id, parent_id, body)
  values (rep.id, p_anchor, me.id, p_parent_id, v_body)
  returning * into c;
  return public._rp_comment_json(c);
end
$$;

create or replace function public.rp_edit_comment(p_token text, p_comment_id uuid, p_body text)
returns jsonb
language plpgsql volatile security definer
set search_path = public, extensions
as $$
declare
  me public.readers := public._rp_auth(p_token);
  c public.comments := public._rp_own_live_comment(me, p_comment_id);
  v_body text := public._rp_clean_body(p_body);
begin
  update public.comments set body = v_body, edited_at = now()
   where id = c.id
  returning * into c;
  return public._rp_comment_json(c);
end
$$;

create or replace function public.rp_delete_comment(p_token text, p_comment_id uuid)
returns jsonb
language plpgsql volatile security definer
set search_path = public, extensions
as $$
declare
  me public.readers := public._rp_auth(p_token);
  c public.comments := public._rp_own_live_comment(me, p_comment_id);
begin
  -- edited_at 一併更新，讓 rp_list_comments(p_since) 增量輪詢收得到刪除
  update public.comments set deleted = true, body = '', edited_at = now()
   where id = c.id;
  return jsonb_build_object('id', c.id, 'deleted', true);
end
$$;

create or replace function public.rp_set_status(p_token text, p_report_id uuid, p_anchor text, p_status text)
returns jsonb
language plpgsql volatile security definer
set search_path = public, extensions
as $$
declare
  me public.readers := public._rp_auth(p_token);
  rep public.reports := public._rp_require_report(me, p_report_id);
  s public.statuses;
begin
  if me.role <> 'reader' then
    raise exception 'forbidden';
  end if;
  if p_anchor is null or not (p_anchor = any (rep.status_anchors)) then
    raise exception 'anchor not statusable';
  end if;
  if p_status is null then
    delete from public.statuses
     where report_id = rep.id and anchor = p_anchor and reader_id = me.id;
    return null;
  end if;
  if p_status not in ('同意', '再議', '請補資料') then
    raise exception 'invalid status';
  end if;
  insert into public.statuses (report_id, anchor, reader_id, status, updated_at)
  values (rep.id, p_anchor, me.id, p_status, now())
  on conflict (report_id, anchor, reader_id)
  do update set status = excluded.status, updated_at = excluded.updated_at
  returning * into s;
  return jsonb_build_object('anchor', s.anchor, 'reader_id', s.reader_id, 'reader_name', me.name,
                            'status', s.status, 'updated_at', s.updated_at);
end
$$;

create or replace function public.rp_mark_seen(p_token text, p_report_id uuid)
returns jsonb
language plpgsql volatile security definer
set search_path = public, extensions
as $$
declare
  me public.readers := public._rp_auth(p_token);
  rep public.reports := public._rp_require_report(me, p_report_id);
  v_at timestamptz;
begin
  select coalesce(max(created_at), now()) into v_at
    from public.comments where report_id = rep.id;
  insert into public.seen (reader_id, report_id, last_seen_comment_at)
  values (me.id, rep.id, v_at)
  on conflict (reader_id, report_id) do update set last_seen_comment_at = excluded.last_seen_comment_at;
  return jsonb_build_object('last_seen_comment_at', v_at);
end
$$;

-- ── 權限 ───────────────────────────────────────────────────────────────
-- Supabase 預設會把 public schema 的函式 EXECUTE 給 anon/authenticated，先全部收回再逐一開放。

revoke all on function public._rp_auth(text) from public, anon, authenticated;
revoke all on function public._rp_require_report(public.readers, uuid) from public, anon, authenticated;
revoke all on function public._rp_clean_body(text) from public, anon, authenticated;
revoke all on function public._rp_comment_json(public.comments) from public, anon, authenticated;
revoke all on function public._rp_own_live_comment(public.readers, uuid) from public, anon, authenticated;

revoke all on function public.rp_whoami(text) from public;
revoke all on function public.rp_list_reports(text) from public;
revoke all on function public.rp_get_report(text, text) from public;
revoke all on function public.rp_mark_read(text, uuid) from public;
revoke all on function public.rp_list_comments(text, uuid, timestamptz) from public;
revoke all on function public.rp_add_comment(text, uuid, text, text, uuid) from public;
revoke all on function public.rp_edit_comment(text, uuid, text) from public;
revoke all on function public.rp_delete_comment(text, uuid) from public;
revoke all on function public.rp_set_status(text, uuid, text, text) from public;
revoke all on function public.rp_mark_seen(text, uuid) from public;

grant execute on function public.rp_whoami(text) to anon, authenticated;
grant execute on function public.rp_list_reports(text) to anon, authenticated;
grant execute on function public.rp_get_report(text, text) to anon, authenticated;
grant execute on function public.rp_mark_read(text, uuid) to anon, authenticated;
grant execute on function public.rp_list_comments(text, uuid, timestamptz) to anon, authenticated;
grant execute on function public.rp_add_comment(text, uuid, text, text, uuid) to anon, authenticated;
grant execute on function public.rp_edit_comment(text, uuid, text) to anon, authenticated;
grant execute on function public.rp_delete_comment(text, uuid) to anon, authenticated;
grant execute on function public.rp_set_status(text, uuid, text, text) to anon, authenticated;
grant execute on function public.rp_mark_seen(text, uuid) to anon, authenticated;
