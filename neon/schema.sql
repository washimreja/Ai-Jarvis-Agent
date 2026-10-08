-- Run this migration in the Neon SQL Editor.
create table if not exists public.chat_messages (
    id uuid primary key default gen_random_uuid(),
    conversation_id text not null,
    sender_id text not null,
    sender_name text not null,
    message_content text not null check (char_length(trim(message_content)) > 0),
    sent_at timestamptz not null default now()
);

create index if not exists chat_messages_sent_at_idx
    on public.chat_messages (sent_at desc);

create index if not exists chat_messages_conversation_id_idx
    on public.chat_messages (conversation_id, sent_at);
