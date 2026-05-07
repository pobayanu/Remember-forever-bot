-- Таблица карточек — v2 (фото + текст)
-- Вставь этот SQL в Supabase → SQL Editor → Run

create table cards (
  id                bigint generated always as identity primary key,
  user_id           bigint        not null,
  card_type         text          not null check (card_type in ('photo', 'text')),
  file_id           text,                     -- только для card_type = 'photo'
  text_content      text,                     -- только для card_type = 'text'
  caption           text          default '',
  added_at          timestamptz   default now(),
  next_review       date,
  repetition_count  int           default 0,
  completed         boolean       default false
);

create index idx_cards_user_review
  on cards (user_id, next_review)
  where completed = false;
