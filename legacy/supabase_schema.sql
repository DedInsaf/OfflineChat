-- OfflineChat online backend. Run the whole file in Supabase SQL Editor.
-- Clients use only the RPC functions below; the base tables stay private.
create extension if not exists pgcrypto;

create table if not exists public.chat_profiles (
    name text primary key,
    display_name text not null default '', bio text not null default '',
    avatar_base64 text, owner_token_hash text,
    last_seen timestamptz not null default now(), updated_at timestamptz not null default now()
);
alter table public.chat_profiles add column if not exists display_name text not null default '';
alter table public.chat_profiles add column if not exists bio text not null default '';
alter table public.chat_profiles add column if not exists avatar_base64 text;
alter table public.chat_profiles add column if not exists owner_token_hash text;
alter table public.chat_profiles add column if not exists updated_at timestamptz not null default now();

create table if not exists public.chat_messages (
    id bigint generated always as identity primary key,
    client_id uuid, sender text not null, recipient text not null, body text not null,
    status text not null default 'sent', created_at timestamptz not null default now(),
    delivered_at timestamptz, read_at timestamptz, updated_at timestamptz not null default now()
);
alter table public.chat_messages add column if not exists client_id uuid;
alter table public.chat_messages add column if not exists status text not null default 'sent';
alter table public.chat_messages add column if not exists delivered_at timestamptz;
alter table public.chat_messages add column if not exists read_at timestamptz;
alter table public.chat_messages add column if not exists updated_at timestamptz not null default now();
update public.chat_messages set client_id = gen_random_uuid() where client_id is null;
alter table public.chat_messages alter column client_id set not null;
alter table public.chat_messages drop constraint if exists chat_messages_sender_fkey;
alter table public.chat_messages drop constraint if exists chat_messages_recipient_fkey;
alter table public.chat_messages add constraint chat_messages_sender_fkey foreign key (sender)
  references public.chat_profiles(name) on update cascade on delete cascade;
alter table public.chat_messages add constraint chat_messages_recipient_fkey foreign key (recipient)
  references public.chat_profiles(name) on update cascade on delete cascade;
create unique index if not exists chat_messages_sender_client_id_key on public.chat_messages(sender, client_id);
create index if not exists chat_messages_participants_idx on public.chat_messages(sender, recipient, id);

create table if not exists public.chat_events (
    id bigint generated always as identity primary key,
    message_id bigint not null references public.chat_messages(id) on delete cascade,
    kind text not null check (kind in ('message', 'delivered', 'read')),
    created_at timestamptz not null default now()
);
create index if not exists chat_events_message_idx on public.chat_events(message_id, id);
insert into public.chat_events(message_id,kind)
select m.id,'message' from public.chat_messages m
where m.body not like '::oc::%'
  and not exists(select 1 from public.chat_events e where e.message_id=m.id and e.kind='message');
create table if not exists public.chat_typing (
    sender text not null references public.chat_profiles(name) on update cascade on delete cascade,
    recipient text not null references public.chat_profiles(name) on update cascade on delete cascade,
    expires_at timestamptz not null, primary key (sender, recipient)
);

alter table public.chat_profiles enable row level security;
alter table public.chat_messages enable row level security;
alter table public.chat_events enable row level security;
alter table public.chat_typing enable row level security;
drop policy if exists "prototype profiles readable" on public.chat_profiles;
drop policy if exists "prototype profiles insertable" on public.chat_profiles;
drop policy if exists "prototype profiles updatable" on public.chat_profiles;
drop policy if exists "prototype messages readable" on public.chat_messages;
drop policy if exists "prototype messages insertable" on public.chat_messages;
revoke all on public.chat_profiles, public.chat_messages, public.chat_events, public.chat_typing from anon, authenticated;

create or replace function public.claim_chat_profile(p_name text, p_display_name text, p_owner_token text)
returns jsonb language plpgsql security definer set search_path = public, pg_temp as $$
declare
  v_hash text := encode(digest(p_owner_token, 'sha256'), 'hex');
  v_profile public.chat_profiles;
begin
  if p_name !~ '^[a-z][a-z0-9_]{2,19}$' then raise exception 'invalid username'; end if;
  if char_length(p_owner_token) < 32 then raise exception 'invalid owner token'; end if;
  insert into public.chat_profiles(name, display_name, owner_token_hash, last_seen, updated_at)
  values (p_name, left(coalesce(nullif(btrim(p_display_name), ''), p_name), 80), v_hash, now(), now())
  on conflict (name) do update set owner_token_hash=v_hash, last_seen=now(), updated_at=now()
    where chat_profiles.owner_token_hash is null or chat_profiles.owner_token_hash=v_hash
  returning * into v_profile;
  if v_profile.name is null then raise exception 'username is already taken'; end if;
  return jsonb_build_object('name',v_profile.name,'display_name',v_profile.display_name,'bio',v_profile.bio,
    'avatar_base64',v_profile.avatar_base64,'last_seen',v_profile.last_seen);
end $$;

create or replace function public.update_chat_profile(
  p_name text, p_new_name text, p_display_name text, p_bio text, p_avatar_base64 text, p_owner_token text
) returns jsonb language plpgsql security definer set search_path = public, pg_temp as $$
declare
  v_hash text := encode(digest(p_owner_token, 'sha256'), 'hex');
  v_profile public.chat_profiles;
begin
  if p_new_name !~ '^[a-z][a-z0-9_]{2,19}$' then raise exception 'invalid username'; end if;
  if char_length(coalesce(p_avatar_base64,'')) > 700000 then raise exception 'avatar is too large'; end if;
  if p_new_name<>p_name and exists(select 1 from public.chat_profiles where name=p_new_name) then
    raise exception 'username is already taken';
  end if;
  update public.chat_profiles set name=p_new_name, display_name=left(btrim(coalesce(p_display_name,'')),80),
    bio=left(btrim(coalesce(p_bio,'')),160), avatar_base64=nullif(p_avatar_base64,''), last_seen=now(), updated_at=now()
  where name=p_name and owner_token_hash=v_hash returning * into v_profile;
  if v_profile.name is null then raise exception 'invalid owner token'; end if;
  return jsonb_build_object('name',v_profile.name,'display_name',v_profile.display_name,'bio',v_profile.bio,
    'avatar_base64',v_profile.avatar_base64,'last_seen',v_profile.last_seen);
end $$;

create or replace function public.search_chat_profiles(p_query text)
returns jsonb language sql security definer stable set search_path = public, pg_temp as $$
  select coalesce(jsonb_agg(jsonb_build_object('name',p.name,'display_name',p.display_name,'bio',p.bio,
    'avatar_base64',p.avatar_base64,'last_seen',p.last_seen) order by (p.name=lower(btrim(p_query))) desc,p.name),'[]'::jsonb)
  from (select * from public.chat_profiles where name ilike '%'||lower(btrim(p_query))||'%'
    or display_name ilike '%'||btrim(p_query)||'%' limit 20) p;
$$;

create or replace function public.send_chat_message(
  p_sender text, p_recipient text, p_client_id uuid, p_body text, p_owner_token text
) returns jsonb language plpgsql security definer set search_path = public, pg_temp as $$
declare
  v_hash text := encode(digest(p_owner_token,'sha256'),'hex');
  v_message public.chat_messages; v_inserted boolean := false;
begin
  if not exists(select 1 from public.chat_profiles where name=p_sender and owner_token_hash=v_hash) then
    raise exception 'invalid owner token'; end if;
  if not exists(select 1 from public.chat_profiles where name=p_recipient) then raise exception 'recipient not found'; end if;
  if char_length(btrim(p_body)) not between 1 and 2000 then raise exception 'invalid message length'; end if;
  insert into public.chat_messages(client_id,sender,recipient,body) values(p_client_id,p_sender,p_recipient,btrim(p_body))
    on conflict(sender,client_id) do nothing returning * into v_message;
  v_inserted := found;
  if not v_inserted then select * into v_message from public.chat_messages where sender=p_sender and client_id=p_client_id;
  else insert into public.chat_events(message_id,kind) values(v_message.id,'message'); end if;
  return jsonb_build_object('id',v_message.id,'client_id',v_message.client_id,'sender',v_message.sender,
    'recipient',v_message.recipient,'body',v_message.body,'status',v_message.status,'created_at',v_message.created_at);
end $$;

create or replace function public.acknowledge_chat_messages(
  p_name text, p_owner_token text, p_message_ids bigint[], p_status text
) returns bigint[] language plpgsql security definer set search_path = public, pg_temp as $$
declare v_hash text:=encode(digest(p_owner_token,'sha256'),'hex'); v_ids bigint[];
begin
  if p_status not in ('delivered','read') then raise exception 'invalid acknowledgement'; end if;
  if not exists(select 1 from public.chat_profiles where name=p_name and owner_token_hash=v_hash) then
    raise exception 'invalid owner token'; end if;
  with changed as (
    update public.chat_messages set status=p_status, delivered_at=coalesce(delivered_at,now()),
      read_at=case when p_status='read' then coalesce(read_at,now()) else read_at end, updated_at=now()
    where id=any(p_message_ids) and recipient=p_name
      and (case status when 'sent' then 1 when 'delivered' then 2 else 3 end)<(case p_status when 'delivered' then 2 else 3 end)
    returning id
  ), events as (
    insert into public.chat_events(message_id,kind) select id,p_status from changed returning message_id
  ) select coalesce(array_agg(message_id),array[]::bigint[]) into v_ids from events;
  return v_ids;
end $$;

create or replace function public.set_chat_typing(p_name text,p_recipient text,p_owner_token text)
returns boolean language plpgsql security definer set search_path = public, pg_temp as $$
begin
  if not exists(select 1 from public.chat_profiles where name=p_name
    and owner_token_hash=encode(digest(p_owner_token,'sha256'),'hex')) then raise exception 'invalid owner token'; end if;
  insert into public.chat_typing(sender,recipient,expires_at) values(p_name,p_recipient,now()+interval '4 seconds')
    on conflict(sender,recipient) do update set expires_at=excluded.expires_at;
  return true;
end $$;

create or replace function public.sync_chat(p_name text,p_owner_token text,p_after_event bigint default 0)
returns jsonb language plpgsql security definer set search_path = public, pg_temp as $$
declare
  v_hash text:=encode(digest(p_owner_token,'sha256'),'hex');
  v_events jsonb; v_profiles jsonb; v_typing jsonb; v_cursor bigint;
begin
  if not exists(select 1 from public.chat_profiles where name=p_name and owner_token_hash=v_hash) then
    raise exception 'invalid owner token'; end if;
  update public.chat_profiles set last_seen=now() where name=p_name;
  with page as (
    select e.id event_id,e.kind,m.* from public.chat_events e join public.chat_messages m on m.id=e.message_id
    where (e.id>greatest(p_after_event,0) or (m.recipient=p_name and m.status='sent'))
      and (m.sender=p_name or m.recipient=p_name) order by e.id limit 500
  ) select coalesce(jsonb_agg(jsonb_build_object('event_id',event_id,'kind',kind,'message',jsonb_build_object(
      'id',id,'client_id',client_id,'sender',sender,'recipient',recipient,'body',body,'status',status,'created_at',created_at
    )) order by event_id),'[]'::jsonb),coalesce(max(event_id),p_after_event)
    into v_events,v_cursor from page;
  if jsonb_array_length(v_events)<500 then
    select greatest(v_cursor,coalesce(max(id),v_cursor)) into v_cursor from public.chat_events;
  end if;
  select coalesce(jsonb_agg(jsonb_build_object('name',p.name,'display_name',p.display_name,'bio',p.bio,
    'avatar_base64',p.avatar_base64,'last_seen',p.last_seen)),'[]'::jsonb) into v_profiles
  from public.chat_profiles p where p.name=p_name or p.name in (
    select case when sender=p_name then recipient else sender end from public.chat_messages where sender=p_name or recipient=p_name
  );
  select coalesce(jsonb_agg(sender),'[]'::jsonb) into v_typing from public.chat_typing
    where recipient=p_name and expires_at>now();
  return jsonb_build_object('cursor',coalesce(v_cursor,p_after_event),'events',v_events,'profiles',v_profiles,'typing',v_typing);
end $$;

revoke all on function public.claim_chat_profile(text,text,text) from public;
revoke all on function public.update_chat_profile(text,text,text,text,text,text) from public;
revoke all on function public.search_chat_profiles(text) from public;
revoke all on function public.send_chat_message(text,text,uuid,text,text) from public;
revoke all on function public.acknowledge_chat_messages(text,text,bigint[],text) from public;
revoke all on function public.set_chat_typing(text,text,text) from public;
revoke all on function public.sync_chat(text,text,bigint) from public;
grant execute on function public.claim_chat_profile(text,text,text) to anon,authenticated;
grant execute on function public.update_chat_profile(text,text,text,text,text,text) to anon,authenticated;
grant execute on function public.search_chat_profiles(text) to anon,authenticated;
grant execute on function public.send_chat_message(text,text,uuid,text,text) to anon,authenticated;
grant execute on function public.acknowledge_chat_messages(text,text,bigint[],text) to anon,authenticated;
grant execute on function public.set_chat_typing(text,text,text) to anon,authenticated;
grant execute on function public.sync_chat(text,text,bigint) to anon,authenticated;
