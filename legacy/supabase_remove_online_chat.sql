-- Выполнить один раз в Supabase SQL Editor после переключения клиентов
-- на собственный сервер. Скрипт безвозвратно удаляет старый онлайн-чат.

begin;

drop function if exists public.sync_chat(text, text, bigint);
drop function if exists public.set_chat_typing(text, text, text);
drop function if exists public.acknowledge_chat_messages(text, text, bigint[], text);
drop function if exists public.send_chat_message(text, text, uuid, text, text);
drop function if exists public.search_chat_profiles(text);
drop function if exists public.update_chat_profile(text, text, text, text, text, text);
drop function if exists public.claim_chat_profile(text, text, text);

drop table if exists public.chat_typing cascade;
drop table if exists public.chat_events cascade;
drop table if exists public.chat_messages cascade;
drop table if exists public.chat_profiles cascade;

commit;
