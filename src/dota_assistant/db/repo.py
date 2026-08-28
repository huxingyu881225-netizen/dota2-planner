"""Repository: persist/query matches, samples, advice."""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Optional

from dota_assistant.core.models import Advice, MatchMeta, Sample
from dota_assistant.db.database import connect, init_schema


class Repo:
    def __init__(self, conn: Optional[sqlite3.Connection] = None):
        self.conn = conn
        self._owns = conn is None

    def __enter__(self):
        if self._owns:
            self.conn = connect()
            init_schema(self.conn)
        return self

    def __exit__(self, *exc):
        if self._owns and self.conn:
            self.conn.close()

    # ---- matches ----
    def insert_match(self, meta: MatchMeta) -> int:
        cur = self.conn.execute(
            """INSERT INTO matches(match_id, source, hero, position, minute_n, interval_m, result)
               VALUES(?,?,?,?,?,?,?)""",
            meta.row(),
        )
        self.conn.commit()
        return cur.lastrowid

    # ---- samples ----
    def insert_samples(self, match_ref: int, samples: list[Any]) -> int:
        cur = self.conn.executemany(
            """INSERT INTO samples(match_ref, hero, position, t_sec, t_min, behavior,
                                   cs, gpm, xpm, networth, kills, deaths, pos_x, pos_y, extra)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [s.to_row(match_ref) for s in samples],
        )
        self.conn.commit()
        return cur.rowcount

    def samples_by_hero_position(self, hero: str, position: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM samples WHERE hero=? AND position=? ORDER BY t_sec", (hero, position)
        ).fetchall()

    def latest_sample_minutes(self, hero: str, position: str) -> Optional[float]:
        row = self.conn.execute(
            "SELECT MAX(t_min) AS m FROM samples WHERE hero=? AND position=?",
            (hero, position),
        ).fetchone()
        return row["m"] if row and row["m"] is not None else None

    # ---- advice ----
    def upsert_advice(self, a: Advice) -> int:
        self.conn.execute(
            """INSERT INTO advice(hero, position, t_start_min, t_end_min, advice, source, updated_at)
               VALUES(?,?,?,?,?,?,datetime('now'))
               ON CONFLICT(hero, position, t_start_min, t_end_min)
               DO UPDATE SET advice=excluded.advice, source=excluded.source,
                             updated_at=datetime('now')""",
            (a.hero, a.position, a.t_start_min, a.t_end_min, a.advice, a.source),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT id FROM advice WHERE hero=? AND position=? AND t_start_min=? AND t_end_min=?",
            (a.hero, a.position, a.t_start_min, a.t_end_min),
        ).fetchone()
        return row["id"] if row else -1

    def delete_advice(self, advice_id: int) -> bool:
        cur = self.conn.execute("DELETE FROM advice WHERE id=?", (advice_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def list_advice(self, hero: Optional[str] = None, position: Optional[str] = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM advice"
        where, args = [], []
        if hero:
            where.append("hero=?")
            args.append(hero)
        if position:
            where.append("position=?")
            args.append(position)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY hero, position, t_start_min"
        return self.conn.execute(sql, args).fetchall()

    def lookup_advice_at(self, hero: str, position: str, minute: float) -> list[sqlite3.Row]:
        """Advice windows whose [t_start,t_end] contains `minute`."""
        return self.conn.execute(
            """SELECT * FROM advice
               WHERE hero=? AND position=? AND t_start_min<=? AND t_end_min>=?
               ORDER BY t_start_min""",
            (hero, position, minute, minute),
        ).fetchall()

    # ---- misc ----
    def stats(self) -> dict[str, Any]:
        def n(tbl: str) -> int:
            return self.conn.execute(f"SELECT COUNT(*) c FROM {tbl}").fetchone()["c"]

        def distinct_hp(tbl: str) -> int:
            return self.conn.execute(
                f"SELECT COUNT(*) c FROM (SELECT DISTINCT hero, position FROM {tbl})"
            ).fetchone()["c"]

        return {
            "matches": n("matches"),
            "samples": n("samples"),
            "hero_position_combos": distinct_hp("samples"),
            "advice": n("advice"),
            "advice_hero_position_combos": distinct_hp("advice"),
        }

    def hero_position_pairs(self, table: str = "samples") -> list[tuple[str, str]]:
        return [
            (r["hero"], r["position"])
            for r in self.conn.execute(f"SELECT DISTINCT hero, position FROM {table}")
        ]

    def sample_json(self, s: sqlite3.Row) -> dict:
        d = dict(s)
        try:
            d["extra"] = json.loads(d["extra"]) if d.get("extra") else {}
        except Exception:
            d["extra"] = {}
        return d
