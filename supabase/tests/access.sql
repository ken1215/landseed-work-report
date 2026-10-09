-- supabase/tests/access.sql — 存取控制測試（PLAN §5，≧ 8 條；實際 18 條）
-- ⚠ SQL 未實測：帳號開好、db push 完成後，在 Supabase SQL Editor（postgres 身分）整份貼上執行。
-- 全部包在單一交易並於最後 rollback，不留任何測試資料。
-- 判讀：每條成功印 NOTICE「TEST n OK …」；任何一條失敗會 raise「TEST n FAILED …」並中止整份（之後的不會跑）。
-- 測試 token 為明文字串 tok-*，只存在本交易內。

begin;

-- ── 夾具 ───────────────────────────────────────────────────────────────
insert into public.readers (id, name, role, token_sha256, active) values
  ('00000000-0000-0000-0000-0000000000a1', '測試作者',   'author', encode(extensions.digest('tok-author',  'sha256'), 'hex'), true),
  ('00000000-0000-0000-0000-0000000000a2', '測試讀者一', 'reader', encode(extensions.digest('tok-r1',      'sha256'), 'hex'), true),
  ('00000000-0000-0000-0000-0000000000a3', '測試讀者二', 'reader', encode(extensions.digest('tok-r2',      'sha256'), 'hex'), true),
  ('00000000-0000-0000-0000-0000000000a4', '已撤銷讀者', 'reader', encode(extensions.digest('tok-revoked', 'sha256'), 'hex'), false);

insert into public.reports (id, period, title, content, status_anchors) values
  ('00000000-0000-0000-0000-0000000000b1', '990101-0103', '測試期A', '{"blocks":[]}', array['s4/li/aaaaaaaaaa', 's4/row/bbbbbbbbbb']),
  ('00000000-0000-0000-0000-0000000000b2', '990104-0106', '測試期B', '{"blocks":[]}', '{}');

-- 讀者一、二只授權 A 期；撤銷讀者也授權 A 期（驗證撤銷優先於授權）
insert into public.report_access (report_id, reader_id) values
  ('00000000-0000-0000-0000-0000000000b1', '00000000-0000-0000-0000-0000000000a2'),
  ('00000000-0000-0000-0000-0000000000b1', '00000000-0000-0000-0000-0000000000a3'),
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

-- ── token ──────────────────────────────────────────────────────────────
do $$ begin
  perform pg_temp.expect_error($q$select public.rp_whoami('no-such-token')$q$, 'invalid token');
  raise notice 'TEST 1 OK 無效 token → invalid token';
end $$;

do $$ begin
  perform pg_temp.expect_error($q$select public.rp_whoami('tok-revoked')$q$, 'invalid token');
  perform pg_temp.expect_error($q$select public.rp_get_report('tok-revoked', '990101-0103')$q$, 'invalid token');
  raise notice 'TEST 2 OK 撤銷 token（active=false，即使有 report_access）→ invalid token';
end $$;

do $$ begin
  perform pg_temp.expect_error($q$select public.rp_whoami('')$q$, 'invalid token');
  perform pg_temp.expect_error($q$select public.rp_whoami(null)$q$, 'invalid token');
  raise notice 'TEST 3 OK 空字串／null token → invalid token';
end $$;

do $$ declare j jsonb; begin
  j := public.rp_whoami('tok-author');
  if j->>'role' <> 'author' or j->>'name' <> '測試作者' then
    raise exception 'TEST 4 FAILED whoami=%', j;
  end if;
  raise notice 'TEST 4 OK 正確 token 以 sha256 hex 比對成功（陽性對照）';
end $$;

-- ── 期別授權 ────────────────────────────────────────────────────────────
do $$ begin
  perform pg_temp.expect_error($q$select public.rp_get_report('tok-r1', '990104-0106')$q$, 'forbidden');
  perform pg_temp.expect_error($q$select public.rp_mark_read('tok-r1', '00000000-0000-0000-0000-0000000000b2')$q$, 'forbidden');
  perform pg_temp.expect_error($q$select public.rp_list_comments('tok-r1', '00000000-0000-0000-0000-0000000000b2', null)$q$, 'forbidden');
  raise notice 'TEST 5 OK 讀者讀未授權期別 → forbidden';
end $$;

do $$ declare j jsonb; begin
  j := public.rp_list_reports('tok-r1');
  if jsonb_array_length(j) <> 1 or j->0->>'period' <> '990101-0103' or j->0->'readers' <> '[]'::jsonb then
    raise exception 'TEST 6 FAILED list_reports(r1)=%', j;
  end if;
  perform pg_temp.expect_error($q$select public.rp_get_report('tok-r1', '000000-0000')$q$, 'not found');
  raise notice 'TEST 6 OK 讀者清單只含授權期別、readers=[]；不存在期別 → not found';
end $$;

do $$ declare j jsonb; begin
  -- 正式庫可能已有真實期別，只看測試期別（9901 開頭）
  select jsonb_agg(e order by ord) into j
    from jsonb_array_elements(public.rp_list_reports('tok-author')) with ordinality as t(e, ord)
   where e->>'period' like '9901%';
  if jsonb_array_length(j) <> 2 or j->0->>'period' <> '990104-0106' then
    raise exception 'TEST 7 FAILED list_reports(author)=%', j;
  end if;
  -- A 期 readers 只列 role=reader 且有 report_access 者（含已撤銷者，共 3）
  if jsonb_array_length(j->1->'readers') <> 3 then
    raise exception 'TEST 7 FAILED readers=%', j->1->'readers';
  end if;
  perform public.rp_get_report('tok-author', '990104-0106');
  raise notice 'TEST 7 OK author 讀全部期別（period 降冪）且看得到讀者清單';
end $$;

-- ── 留言 ───────────────────────────────────────────────────────────────
do $$ declare c jsonb; begin
  c := public.rp_add_comment('tok-r2', '00000000-0000-0000-0000-0000000000b1', 's1/blk/0000000000', '讀者二的留言', null);
  perform pg_temp.expect_error(format($q$select public.rp_edit_comment('tok-r1', %L, '竄改')$q$, c->>'id'), 'forbidden');
  perform pg_temp.expect_error(format($q$select public.rp_delete_comment('tok-r1', %L)$q$, c->>'id'), 'forbidden');
  perform pg_temp.expect_error(format($q$select public.rp_edit_comment('tok-author', %L, '竄改')$q$, c->>'id'), 'forbidden');
  if (select body from public.comments where id = (c->>'id')::uuid) <> '讀者二的留言' then
    raise exception 'TEST 8 FAILED body 被改';
  end if;
  raise notice 'TEST 8 OK 改／刪他人留言 → forbidden（含 author）';
end $$;

do $$ declare c jsonb; d jsonb; begin
  c := public.rp_add_comment('tok-r1', '00000000-0000-0000-0000-0000000000b1', 's1/blk/0000000000', '  自己的留言  ', null);
  if c->>'body' <> '自己的留言' then
    raise exception 'TEST 9 FAILED trim body=%', c->>'body';
  end if;
  d := public.rp_delete_comment('tok-r1', (c->>'id')::uuid);
  if not (d->>'deleted')::boolean then
    raise exception 'TEST 9 FAILED delete=%', d;
  end if;
  perform pg_temp.expect_error(format($q$select public.rp_edit_comment('tok-r1', %L, '再改')$q$, c->>'id'), 'forbidden');
  if (select body from public.comments where id = (c->>'id')::uuid) <> '' then
    raise exception 'TEST 9 FAILED 軟刪 body 未清空';
  end if;
  raise notice 'TEST 9 OK 本人可刪（軟刪、body 清空）；已刪不可再改';
end $$;

do $$ begin
  perform pg_temp.expect_error(format($q$select public.rp_add_comment('tok-r1', '00000000-0000-0000-0000-0000000000b1', 's1/blk/0000000000', %L, null)$q$, repeat('字', 2001)), 'body too long');
  perform pg_temp.expect_error($q$select public.rp_add_comment('tok-r1', '00000000-0000-0000-0000-0000000000b1', 's1/blk/0000000000', E'  \n ', null)$q$, 'body empty');
  perform public.rp_add_comment('tok-r1', '00000000-0000-0000-0000-0000000000b1', 's1/blk/0000000000', repeat('字', 2000), null);
  raise notice 'TEST 10 OK body 2001 字 → body too long；空白 → body empty；2000 字可寫入';
end $$;

do $$ declare p jsonb; r jsonb; begin
  p := public.rp_add_comment('tok-r1', '00000000-0000-0000-0000-0000000000b1', 's4/li/aaaaaaaaaa', '請補資料', null);
  r := public.rp_add_comment('tok-author', '00000000-0000-0000-0000-0000000000b1', 's4/li/aaaaaaaaaa', '已補', (p->>'id')::uuid);
  perform pg_temp.expect_error(format($q$select public.rp_add_comment('tok-r1', '00000000-0000-0000-0000-0000000000b1', 's4/li/aaaaaaaaaa', '再回', %L)$q$, r->>'id'), 'reply depth');
  perform pg_temp.expect_error($q$select public.rp_add_comment('tok-r1', '00000000-0000-0000-0000-0000000000b1', 's4/li/aaaaaaaaaa', '回覆', '00000000-0000-0000-0000-00000000ffff')$q$, 'not found');
  raise notice 'TEST 11 OK 回覆只允許一層 → reply depth；parent 不存在 → not found';
end $$;

-- ── 狀態指示 ────────────────────────────────────────────────────────────
do $$ begin
  perform pg_temp.expect_error($q$select public.rp_set_status('tok-r1', '00000000-0000-0000-0000-0000000000b1', 's1/blk/0000000000', '同意')$q$, 'anchor not statusable');
  raise notice 'TEST 12 OK 狀態寫到不可指示錨點 → anchor not statusable';
end $$;

do $$ declare s jsonb; begin
  perform pg_temp.expect_error($q$select public.rp_set_status('tok-r1', '00000000-0000-0000-0000-0000000000b1', 's4/li/aaaaaaaaaa', '不同意')$q$, 'invalid status');
  perform pg_temp.expect_error($q$select public.rp_set_status('tok-author', '00000000-0000-0000-0000-0000000000b1', 's4/li/aaaaaaaaaa', '同意')$q$, 'forbidden');
  s := public.rp_set_status('tok-r1', '00000000-0000-0000-0000-0000000000b1', 's4/li/aaaaaaaaaa', '同意');
  s := public.rp_set_status('tok-r1', '00000000-0000-0000-0000-0000000000b1', 's4/li/aaaaaaaaaa', '再議');
  if s->>'status' <> '再議' or (select count(*) from public.statuses where reader_id = '00000000-0000-0000-0000-0000000000a2') <> 1 then
    raise exception 'TEST 13 FAILED status=%', s;
  end if;
  -- 先呼叫再檢查：同一個 if 裡無關聯的 exists 會被當 InitPlan 先算，看不到函式內的刪除
  s := public.rp_set_status('tok-r1', '00000000-0000-0000-0000-0000000000b1', 's4/li/aaaaaaaaaa', null);
  if s is not null
     or exists (select 1 from public.statuses where reader_id = '00000000-0000-0000-0000-0000000000a2') then
    raise exception 'TEST 13 FAILED null 未刪列';
  end if;
  raise notice 'TEST 13 OK 非三選一 → invalid status；author 設狀態 → forbidden；每人每錨點一列；null 清除';
end $$;

-- ── 已閱／未讀／通知 ─────────────────────────────────────────────────────
do $$ declare a jsonb; b jsonb; begin
  a := public.rp_mark_read('tok-r1', '00000000-0000-0000-0000-0000000000b1');
  b := public.rp_mark_read('tok-r1', '00000000-0000-0000-0000-0000000000b1');
  if a->>'first_at' is null or a->>'first_at' <> b->>'first_at' then
    raise exception 'TEST 14 FAILED a=% b=%', a, b;
  end if;
  -- 同一交易內 now() 固定，此條只證明可重複呼叫不撞 pk；first_at 跨次不變需實機分兩次呼叫確認
  raise notice 'TEST 14 OK mark_read 可重複呼叫（upsert）且回傳 first_at';
end $$;

do $$ declare j jsonb; begin
  -- 讀者一：作者在 TEST 11 回覆了他的留言 → unread_replies ≧ 1
  j := public.rp_list_reports('tok-r1');
  if (j->0->>'unread_replies')::int < 1 then
    raise exception 'TEST 15 FAILED r1=%', j;
  end if;
  -- 作者：有讀者留言 → unread_count ≧ 1；mark_seen 後歸零
  select e into j from jsonb_array_elements(public.rp_list_reports('tok-author')) e where e->>'period' = '990101-0103';
  if (j->>'unread_count')::int < 1 then
    raise exception 'TEST 15 FAILED author=%', j;
  end if;
  perform public.rp_mark_seen('tok-author', '00000000-0000-0000-0000-0000000000b1');
  select e into j from jsonb_array_elements(public.rp_list_reports('tok-author')) e where e->>'period' = '990101-0103';
  if (j->>'unread_count')::int <> 0 then
    raise exception 'TEST 15 FAILED after seen=%', j;
  end if;
  raise notice 'TEST 15 OK 未讀數／新回覆數；mark_seen 後 unread=0';
end $$;

do $$ begin
  if not exists (select 1 from public.notifications
                  where reader_id = '00000000-0000-0000-0000-0000000000a2' and kind = 'reply') then
    raise exception 'TEST 16 FAILED 缺 reply 通知';
  end if;
  if not exists (select 1 from public.notifications
                  where reader_id = '00000000-0000-0000-0000-0000000000a1' and kind = 'new_comment') then
    raise exception 'TEST 16 FAILED 缺 new_comment 通知';
  end if;
  raise notice 'TEST 16 OK notifications trigger：作者回覆→讀者 reply；讀者留言→作者 new_comment';
end $$;

-- ── anon 直接碰表／helper ─────────────────────────────────────────────────
set local role anon;

do $$ declare n int; begin
  begin
    select count(*) into n from public.comments;
    if n <> 0 then
      raise exception 'TEST 17 FAILED anon 讀到 comments % 列', n;
    end if;
  exception when insufficient_privilege then
    null;
  end;
  begin
    select count(*) into n from public.readers;
    if n <> 0 then
      raise exception 'TEST 17 FAILED anon 讀到 readers % 列', n;
    end if;
  exception when insufficient_privilege then
    null;
  end;
  begin
    insert into public.comments (report_id, anchor, reader_id, body)
    values ('00000000-0000-0000-0000-0000000000b1', 'x', '00000000-0000-0000-0000-0000000000a2', 'anon 直寫');
    raise exception 'TEST 17 FAILED anon 可直接 insert comments';
  exception when insufficient_privilege then
    null;
  end;
  raise notice 'TEST 17 OK anon 直接 select/insert 表被擋（permission denied 或 0 列）';
end $$;

do $$ declare j jsonb; begin
  begin
    perform public._rp_auth('tok-author');
    raise exception 'TEST 18 FAILED anon 可呼叫 helper _rp_auth';
  exception when insufficient_privilege then
    null;
  end;
  j := public.rp_whoami('tok-r1');
  if j->>'role' <> 'reader' then
    raise exception 'TEST 18 FAILED anon 呼叫 rp_whoami=%', j;
  end if;
  raise notice 'TEST 18 OK anon 不可呼叫內部 helper；可呼叫 rp_*（陽性對照）';
end $$;

reset role;

rollback;
