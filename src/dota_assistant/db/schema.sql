PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS matches (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  match_id    TEXT NOT NULL,
  source      TEXT NOT NULL,
  hero        TEXT NOT NULL,
  position    TEXT NOT NULL,
  minute_n    INTEGER NOT NULL,
  interval_m  INTEGER NOT NULL,
  result      TEXT,
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS samples (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  match_ref   INTEGER NOT NULL REFERENCES matches(id),
  hero        TEXT NOT NULL,
  position    TEXT NOT NULL,
  t_sec       INTEGER NOT NULL,
  t_min       REAL NOT NULL,
  behavior    TEXT NOT NULL,
  cs          INTEGER,
  gpm         INTEGER,
  xpm         INTEGER,
  networth    INTEGER,
  kills       INTEGER,
  deaths      INTEGER,
  pos_x       REAL,
  pos_y       REAL,
  extra       TEXT
);

CREATE TABLE IF NOT EXISTS advice (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  hero        TEXT NOT NULL,
  position    TEXT NOT NULL,
  t_start_min REAL NOT NULL,
  t_end_min   REAL NOT NULL,
  advice      TEXT NOT NULL,
  source      TEXT,
  updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(hero, position, t_start_min, t_end_min)
);

CREATE INDEX IF NOT EXISTS idx_samples_hero_pos ON samples(hero, position, t_sec);
CREATE INDEX IF NOT EXISTS idx_advice_hero_pos   ON advice(hero, position);
