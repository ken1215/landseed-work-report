-- 報告分享連結（2026-10-09 使用者選定）：每期報告一把隨機 share key，網址 #s=<key> 直接開、不用登入。
-- 開啟後選名字（限該期有授權的讀者＋作者），token 組成 's:<key>:<name>'，沿用既有 rp_* 全部權限檢查，
-- 並以交易內設定 lwr.scope 把可見範圍鎖在該期（看不到其他期別）。
-- 風險（使用者已知悉並接受）：持有連結者可選任何名單內的名字留言。

alter table public.reports add column if not exists share_key_sha256 text unique;

create or replace function public._rp_auth(p_token text)
returns public.readers
language plpgsql stable security definer
set search_path = public, extensions
as $$
declare
  me public.readers;
  rep public.reports;
  k text;
  nm text;
begin
  perform set_config('lwr.scope', '', true);
  if p_token is null or p_token = '' then
    raise exception 'invalid token';
  end if;
  if p_token like 's:%' then
    k := split_part(p_token, ':', 2);
    nm := substr(p_token, length(k) + 4);
    if k = '' or nm = '' then
      raise exception 'invalid token';
    end if;
    select * into rep from public.reports
     where share_key_sha256 = encode(digest(k, 'sha256'), 'hex');
    if not found then
      raise exception 'invalid token';
    end if;
    select r.* into me from public.readers r
     where r.name = nm and r.active
       and (r.role = 'author' or exists (select 1 from public.report_access a
                                          where a.report_id = rep.id and a.reader_id = r.id))
     order by r.created_at limit 1;
    if not found then
      raise exception 'invalid token';
    end if;
    perform set_config('lwr.scope', rep.id::text, true);
    return me;
  end if;
  select * into me from public.readers
   where token_sha256 = encode(digest(p_token, 'sha256'), 'hex') and active;
  if not found then
    raise exception 'invalid token';
  end if;
  return me;
end
$$;
revoke all on function public._rp_auth(text) from public, anon, authenticated;

create or replace function public._rp_scope()
returns uuid
language sql stable
as $$ select nullif(current_setting('lwr.scope', true), '')::uuid $$;
revoke all on function public._rp_scope() from public, anon, authenticated;

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
  if public._rp_scope() is not null and rep.id <> public._rp_scope() then
    raise exception 'forbidden';
  end if;
  if p_me.role <> 'author' and not exists (
       select 1 from public.report_access a
        where a.report_id = rep.id and a.reader_id = p_me.id) then
    raise exception 'forbidden';
  end if;
  return rep;
end
$$;
revoke all on function public._rp_require_report(public.readers, uuid) from public, anon, authenticated;

-- 分享連結開啟時的第一支呼叫：不需 token，只回報告期別與可選名字
create or replace function public.rs_share_info(p_key text)
returns jsonb
language plpgsql stable security definer
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
  return jsonb_build_object(
    'period', rep.period, 'title', rep.title,
    'names', (select coalesce(jsonb_agg(jsonb_build_object('name', r.name, 'role', r.role)
                                        order by (r.role = 'reader') desc, r.created_at), '[]'::jsonb)
                from public.readers r
               where r.active
                 and (r.role = 'author' or exists (select 1 from public.report_access a
                                                    where a.report_id = rep.id and a.reader_id = r.id))));
end
$$;
revoke all on function public.rs_share_info(text) from public;
grant execute on function public.rs_share_info(text) to anon, authenticated;

-- 期別清單也受分享連結的範圍限制（其餘 rp_* 皆經 _rp_require_report）
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
    where (me.role = 'author'
           or exists (select 1 from public.report_access a
                       where a.report_id = rep.id and a.reader_id = me.id))
      and (public._rp_scope() is null or rep.id = public._rp_scope())
  ) x;
  return result;
end
$$;
