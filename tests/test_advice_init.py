"""验证：samples 初始化 advice（30秒粒度）+ 浮窗边界匹配逻辑。"""
import types

from dota_assistant.db.database import connect, init_schema
from dota_assistant.db.repo import Repo
from dota_assistant.ingest.extractor import extract
from dota_assistant.core.models import MatchMeta


def make_player(cs_per_min, kills=2, deaths=0):
    secs = 6 * 60
    return types.SimpleNamespace(
        player_id=0, hero_name="npc_dota_hero_juggernaut",
        times=[i * 30 for i in range(secs + 1)],
        lh_t=[float(cs_per_min[int(min(i / 60, len(cs_per_min) - 1))]) for i in range(secs + 1)],
        dn_t=[0.0] * (secs + 1),
        gold_t=[600 + (i / 60) * 40 for i in range(secs + 1)],
        total_earned_gold_t=[500 + (i / 60) * 22 * 60 for i in range(secs + 1)],
        net_worth_t=[1500 + (i / 60) * 950 for i in range(secs + 1)],
        xp_t=[600 + (i / 60) * 140 * 60 for i in range(secs + 1)],
        kills=kills, deaths=deaths, assists=1,
        kills_log=[], obs_log=[], sen_log=[], purchase_log=[], position_log=[])


def test_init_advice_from_samples_30s(tmp_path):
    conn = connect(tmp_path / "t.db")
    init_schema(conn)
    repo = Repo(conn)

    player = make_player([8, 16, 24, 32, 40, 48, 56])
    data = {"player": player, "match": None, "players": None}
    samples = extract(data, "juggernaut", "carry", 5, 30)
    mr = repo.insert_match(MatchMeta("m1", "test", "juggernaut", "carry", 5, 30, "win"))
    repo.insert_samples(mr, samples)

    n = repo.init_advice_from_samples("juggernaut", "carry", source="m1.dem", interval_m=30)
    assert n == len(samples) == 11  # 0..300s 每30s

    rows = repo.list_advice("juggernaut", "carry")
    assert len(rows) == 11
    # 30 秒粒度窗口
    assert rows[0]["t_start_min"] == 0.0
    assert rows[0]["t_end_min"] == 0.5
    assert rows[1]["t_start_min"] == 0.5
    # 文本来自 sample.behavior
    assert rows[0]["advice"] == samples[0].behavior

    # 边界匹配：左闭右开
    assert [(r["t_start_min"], r["t_end_min"]) for r in repo.lookup_advice_at("juggernaut", "carry", 1.0)] == [(1.0, 1.5)]
    assert [(r["t_start_min"], r["t_end_min"]) for r in repo.lookup_advice_at("juggernaut", "carry", 1.7)] == [(1.5, 2.0)]


def test_advice_editable_upsert(tmp_path):
    from dota_assistant.core.models import Advice
    conn = connect(tmp_path / "t.db")
    init_schema(conn)
    repo = Repo(conn)
    repo.upsert_advice(Advice("juggernaut", "carry", 0.0, 0.5, "旧策略", "ingest"))
    repo.upsert_advice(Advice("juggernaut", "carry", 0.0, 0.5, "人工修改后的策略", "user"))
    rows = repo.list_advice("juggernaut", "carry")
    assert len(rows) == 1
    assert rows[0]["advice"] == "人工修改后的策略"
    assert rows[0]["source"] == "user"
