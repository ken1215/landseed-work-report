-- supabase/tests/share.sql — 分享連結（0004_share.sql）存取測試。單一交易、最後 rollback，不留資料。
-- 執行：private/.venv/bin/python tools/run_sql.py supabase/tests/share.sql
begin;

insert into public.readers (id, name, role, token_sha256, active) values
  ('00000000-0000-0000-0000-0000000000a1', '測試作者',   'author', encode(extensions.digest('tok-author',  'sha256'), 'hex'), true),
  ('00000000-0000-0000-0000-0000000000a2', '測試讀者一', 'reader', encode(extensions.digest('tok-r1',      'sha256'), 'hex'), true),
  ('00000000-0000-0000-0000-0000000000a3', '測試讀者二', 'reader', encode(extensions.digest('tok-r2',      'sha256'), 'hex'), true),
  ('00000000-0000-0000-0000-0000000000a4', '已撤銷讀者', 'reader', encode(extensions.digest('tok-revoked', 'sha256'), 'hex'), false);

insert into public.reports (id, period, title, content, status_anchors, share_key_sha256) values
  ('00000000-0000-0000-0000-0000000000b1', '990101-0103', '測試期A', '{"blocks":[]}', array['s4/li/aaaaaaaaaa'],
   encode(extensions.digest('shareKeyA-0123456789abcdef', 'sha256'), 'hex')),
  ('00000000-0000-0000-0000-0000000000b2', '990104-0106', '測試期B', '{"blocks":[]}', '{}', null);

-- 讀者一授權 A、B；讀者二只授權 B；撤銷讀者授權 A
insert into public.report_access (report_id, reader_id) values
  ('00000000-0000-0000-0000-0000000000b1', '00000000-0000-0000-0000-0000000000a2'),
  ('00000000-0000-0000-0000-0000000000b2', '00000000-0000-0000-0000-0000000000a2'),
  ('00000000-0000-0000-0000-0000000000b2', '00000000-0000-0000-0000-0000000000a3'),
  ('00000000-0000-0000-0000-0000000000b1', '00000000-0000-0000-0000-0000000000a4');

create function pg_temp.expect_error(p_sql text, p_msg text) returns void
language plpgsql as $$
begin
  begin
    execute p_sql;
  exception when others then
    if sqlerrm = p_msg then
      return;
    end if;
    raise exception 'expected "%" but got "%" from: %', p_msg, sqlerrm, p_sql;
  end;
  raise exception 'expected "%" but no error from: %', p_msg, p_sql;
end
$$;

do $$ declare j jsonb; names text; begin
  j := public.rs_share_info('shareKeyA-0123456789abcdef');
  select string_agg(x->>'name', ',') into names from jsonb_array_elements(j->'names') x;
  -- 真資料庫可能已有真實作者，只驗測試名單的進出
  if j->>'period' <> '990101-0103' or names not like '測試讀者一,%' or position('測試作者' in names) = 0
     or position('測試讀者二' in names) > 0 or position('已撤銷讀者' in names) > 0 then
    raise exception 'SHARE 1 FAILED info=% names=%', j, names;
  end if;
  perform pg_temp.expect_error($q$select public.rs_share_info('wrong-key-0123456789')$q$, 'invalid token');
  perform pg_temp.expect_error($q$select public.rs_share_info('short')$q$, 'invalid token');
  raise notice 'SHARE 1 OK share_info 回期別＋可選名字（只含授權讀者＋作者，不含撤銷／未授權者）；錯 key → invalid token';
end $$;

do $$ begin
  perform pg_temp.expect_error($q$select public.rp_whoami('s:shareKeyA-0123456789abcdef:測試讀者二')$q$, 'invalid token');
  perform pg_temp.expect_error($q$select public.rp_whoami('s:shareKeyA-0123456789abcdef:已撤銷讀者')$q$, 'invalid token');
  perform pg_temp.expect_error($q$select public.rp_whoami('s:wrong-key-0123456789:測試讀者一')$q$, 'invalid token');
  perform pg_temp.expect_error($q$select public.rp_whoami('s:shareKeyA-0123456789abcdef:')$q$, 'invalid token');
  raise notice 'SHARE 2 OK 名單外名字／撤銷者／錯 key／空名字 → invalid token';
end $$;

do $$ declare j jsonb; begin
  j := public.rp_list_reports('s:shareKeyA-0123456789abcdef:測試讀者一');
  if jsonb_array_length(j) <> 1 or j->0->>'period' <> '990101-0103' then
    raise exception 'SHARE 3 FAILED list=%', j;
  end if;
  perform pg_temp.expect_error($q$select public.rp_get_report('s:shareKeyA-0123456789abcdef:測試讀者一', '990104-0106')$q$, 'forbidden');
  j := public.rp_list_reports('s:shareKeyA-0123456789abcdef:測試作者');
  if jsonb_array_length(j) <> 1 then
    raise exception 'SHARE 3 FAILED author list=%', j;
  end if;
  perform pg_temp.expect_error($q$select public.rp_get_report('s:shareKeyA-0123456789abcdef:測試作者', '990104-0106')$q$, 'forbidden');
  raise notice 'SHARE 3 OK 分享連結只看得到該期（讀者一本有 B 期權限、作者本可看全部，仍被鎖在 A 期）';
end $$;

do $$ declare j jsonb; c jsonb; s jsonb; begin
  j := public.rp_get_report('s:shareKeyA-0123456789abcdef:測試讀者一', '990101-0103');
  c := public.rp_add_comment('s:shareKeyA-0123456789abcdef:測試讀者一', '00000000-0000-0000-0000-0000000000b1', 's1/blk/0000000000', '分享連結留言', null);
  if c->>'reader_name' <> '測試讀者一' then
    raise exception 'SHARE 4 FAILED comment=%', c;
  end if;
  s := public.rp_set_status('s:shareKeyA-0123456789abcdef:測試讀者一', '00000000-0000-0000-0000-0000000000b1', 's4/li/aaaaaaaaaa', '同意');
  perform pg_temp.expect_error(format($q$select public.rp_set_status('s:shareKeyA-0123456789abcdef:測試作者', %L, 's4/li/aaaaaaaaaa', '同意')$q$, '00000000-0000-0000-0000-0000000000b1'), 'forbidden');
  c := public.rp_add_comment('s:shareKeyA-0123456789abcdef:測試作者', '00000000-0000-0000-0000-0000000000b1', 'x', '作者回覆', (c->>'id')::uuid);
  if c->>'role' <> 'author' then
    raise exception 'SHARE 4 FAILED reply=%', c;
  end if;
  raise notice 'SHARE 4 OK 分享連結可讀報告、留言、讀者設狀態、作者回覆；作者不可設狀態';
end $$;

do $$ declare j jsonb; begin
  -- 同一交易內，分享 token 之後改用一般 token：範圍必須被重設，不可沿用上一支的 lwr.scope
  perform public.rp_whoami('s:shareKeyA-0123456789abcdef:測試讀者一');
  j := public.rp_list_reports('tok-author');
  if (select count(*) from jsonb_array_elements(j) x where x->>'period' in ('990101-0103', '990104-0106')) <> 2 then
    raise exception 'SHARE 5 FAILED scope 外洩 list=%', j;
  end if;
  raise notice 'SHARE 5 OK 一般 token 不受前一次分享範圍影響（scope 每次重設）';
end $$;

do $$ declare j jsonb; n int; begin
  select count(*) into n from public.share_opens where report_id = '00000000-0000-0000-0000-0000000000b1';
  j := public.rs_get_shared('shareKeyA-0123456789abcdef');
  if j->>'period' <> '990101-0103' or j->'content' is null then
    raise exception 'SHARE 6 FAILED %', j;
  end if;
  if (select count(*) from public.share_opens where report_id = '00000000-0000-0000-0000-0000000000b1') <> n + 1 then
    raise exception 'SHARE 6 FAILED 開啟未記錄';
  end if;
  perform pg_temp.expect_error($q$select public.rs_get_shared('wrong-key-0123456789')$q$, 'invalid token');
  perform pg_temp.expect_error($q$select public.rs_get_shared(null)$q$, 'invalid token');
  set local role anon;
  j := public.rs_get_shared('shareKeyA-0123456789abcdef');
  perform pg_temp.expect_error($q$select count(*) from public.share_opens$q$, 'permission denied for table share_opens');
  reset role;
  raise notice 'SHARE 6 OK 單向分享：正確 key 回該期內容並記錄開啟；錯 key／null → invalid token；anon 可呼叫但讀不到開啟紀錄表';
end $$;

rollback;
