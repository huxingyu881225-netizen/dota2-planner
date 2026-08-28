import pytest

from dota_assistant.db.database import connect, init_schema
from dota_assistant.db.repo import Repo
from dota_assistant.ingest.extractor import extract
from dota_assistant.core.models import MatchMeta, Advice
from dota_assistant.analysis.differ import Differ, OutcomeJudger
from dota_assistant.core.positions import normalize_position

# gem-dota is installed; use its real ParsedPlayer dataclass to build fixtures.
from gem.results import models as M

TICK = 30  # ticks per second


def make_player(cs_per_min, kills=2, deaths=0, assists=1):
    """Build a real gem ParsedPlayer with sampled (~1/sec) series."""
    seconds = 12 * 60
    times = [i * TICK for i in range(seconds + 1)]
    lh, gold, earned, nw, xp, dn = [], [], [], [], [], []
    for i in range(seconds + 1):
        m = i / 60
        target = cs_per_min[int(min(m, len(cs_per_min) - 1))]
        lh.append(float(target))
        gold.append(600 + m * 40)
        earned.append(500 + m * 22 * 60)
        nw.append(1500 + m * 950)
        xp.append(600 + m * 140 * 60)
        dn.append(float(target // 2))
    return M.ParsedPlayer(
        player_id=0,
        hero_name="npc_dota_hero_juggernaut",
        times=times, lh_t=lh, dn_t=dn, gold_t=gold,
        total_earned_gold_t=earned, net_worth_t=nw, xp_t=xp,
        kills=kills, deaths=deaths, assists=0,
        position_log=[(i * TICK, 100.0, 200.0) for i in range(0, seconds + 1, 60)],
    )


def data_for(player):
    return {"match": None, "players": [player], "player": player}


@pytest.fixture
def repo(tmp_path):
    conn = connect(tmp_path / "t.db")
    init_schema(conn)
    return Repo(conn)


def test_positions():
    assert normalize_position("off") == "offline"
    assert normalize_position("pos5") == "safelane_support"
    with pytest.raises(ValueError):
        normalize_position("wat")


def test_extract_and_repo(repo):
    p = make_player([8, 16, 24, 32, 40, 48, 56, 64, 72, 80, 88, 96])
    samples = extract(data_for(p), "juggernaut", "carry", 10, 30)
    assert len(samples) == 10 * 60 // 30 + 1
    # series present
    assert samples[0].cs is not None and samples[0].networth is not None
    mr = repo.insert_match(MatchMeta("1", "test", "juggernaut", "carry", 10, 30, "win"))
    repo.insert_samples(mr, samples)
    assert repo.stats()["samples"] == len(samples)

    repo.upsert_advice(Advice("juggernaut", "carry", 0, 2, "对线压制", "seed"))
    hits = repo.lookup_advice_at("juggernaut", "carry", 1.5)
    assert hits and "对线压制" in hits[0]["advice"]


def test_diff_skips_unknown(repo):
    report = Differ(repo, OutcomeJudger()).compare([], "zeta", "mid")
    assert report.skipped


def test_diff_flags_low_cs(repo):
    good_p = make_player([8, 16, 24, 32, 40, 48, 56, 64, 72, 80, 88, 96])
    mr = repo.insert_match(MatchMeta("1", "test", "juggernaut", "carry", 10, 30, "win"))
    repo.insert_samples(mr, extract(data_for(good_p), "juggernaut", "carry", 10, 30))

    bad_p = make_player([4, 7, 9, 11, 12, 13, 14, 15, 16, 16, 17, 17], kills=0, deaths=4)
    bad = extract(data_for(bad_p), "juggernaut", "carry", 10, 60)
    report = Differ(repo, OutcomeJudger()).compare(bad, "juggernaut", "carry", "loss")
    assert not report.skipped
    assert report.bad_count > 0
