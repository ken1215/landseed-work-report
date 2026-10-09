-- 0001_schema.sql — 表、索引、RLS deny-all
-- ⚠ SQL 未實測：撰寫時 Supabase 帳號未開、本機無 psql/docker，只做過靜態自檢（tests/test_sql_static.py）。
-- 原則：每張表 enable RLS 且不建任何 policy（deny-all）；anon/authenticated 的表權限一併 revoke。
--       所有讀寫只經 0002 的 security definer RPC。不使用 force RLS（RPC 以表擁有者身分執行）。
-- 遷移順序判定：本檔為「新增」型，可先於前端上線。

create extension if not exists pgcrypto with schema extensions;

create table if not exists public.readers (
  id            uuid primary key default gen_random_uuid(),
  name          text not null check (char_length(btrim(name)) between 1 and 100),
  role          text not null check (role in ('author','reader')),
  token_sha256  text not null unique check (token_sha256 ~ '^[0-9a-f]{64}$'),
  active        boolean not null default true,
  created_at    timestamptz not null default now()
);

create table if not exists public.reports (
  id              uuid primary key default gen_random_uuid(),
  period          text not null unique,
  title           text not null,
  content         jsonb not null,
  status_anchors  text[] not null default '{}',
  anchor_index    jsonb not null default '[]',
  version         int not null default 1,
  published_at    timestamptz not null default now()
);

create table if not exists public.report_access (
  report_id  uuid not null references public.reports(id) on delete cascade,
  reader_id  uuid not null references public.readers(id) on delete cascade,
  primary key (report_id, reader_id)
);

create table if not exists public.comments (
  id          uuid primary key default gen_random_uuid(),
  report_id   uuid not null references public.reports(id) on delete cascade,
  anchor      text not null check (char_length(anchor) between 1 and 200),
  reader_id   uuid not null references public.readers(id),
  parent_id   uuid null references public.comments(id) on delete cascade,
  body        text not null,
  created_at  timestamptz not null default now(),
  edited_at   timestamptz null,
  deleted     boolean not null default false,
  orphaned    boolean not null default false,
  -- 軟刪除會把 body 清成 ''，所以長度檢查只套在未刪除列
  check (deleted or char_length(body) between 1 and 2000),
  check (char_length(body) <= 2000)
);
create index if not exists comments_report_created_idx on public.comments (report_id, created_at);
create index if not exists comments_parent_idx on public.comments (parent_id);
create index if not exists comments_reader_idx on public.comments (reader_id);

create table if not exists public.reads (
  report_id  uuid not null references public.reports(id) on delete cascade,
  reader_id  uuid not null references public.readers(id) on delete cascade,
  first_at   timestamptz not null default now(),
  last_at    timestamptz not null default now(),
  primary key (report_id, reader_id)
);

create table if not exists public.statuses (
  report_id   uuid not null references public.reports(id) on delete cascade,
  anchor      text not null,
  reader_id   uuid not null references public.readers(id) on delete cascade,
  status      text not null check (status in ('同意','再議','請補資料')),
  updated_at  timestamptz not null default now(),
  primary key (report_id, anchor, reader_id)
);
create index if not exists statuses_report_updated_idx on public.statuses (report_id, updated_at);

create table if not exists public.seen (
  reader_id             uuid not null references public.readers(id) on delete cascade,
  report_id             uuid not null references public.reports(id) on delete cascade,
  last_seen_comment_at  timestamptz not null,
  primary key (reader_id, report_id)
);

alter table public.readers       enable row level security;
alter table public.reports       enable row level security;
alter table public.report_access enable row level security;
alter table public.comments      enable row level security;
alter table public.reads         enable row level security;
alter table public.statuses      enable row level security;
alter table public.seen          enable row level security;

revoke all on table public.readers, public.reports, public.report_access, public.comments,
                    public.reads, public.statuses, public.seen
  from anon, authenticated;

-- 照片 bucket（private）；publish.py 以 service_role 上傳並產簽章 URL
insert into storage.buckets (id, name, public)
values ('report-photos', 'report-photos', false)
on conflict (id) do nothing;
