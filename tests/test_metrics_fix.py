"""验证 3 项修法：GPM/XPM 计算、window_gain 用累计收入、deaths 用分钟累计序列。"""
import types

from dota_assistant.ingest.extractor import extract_windows


def make_player(base_tick=0, total_gold_fn=lambda i: i * 10, gold_fn=lambda i: i * 10,
                xp_fn=lambda i: i * 100, deaths_min=None):
    secs = 5 * 60
    deaths_min = deaths_min if deaths_min is not None else [0, 1, 1, 2, 2, 2]
    return types.SimpleNamespace(
        player_id=0, hero_name="npc_dota_hero_juggernaut",
        times=[base_tick + i * 30 for i in range(secs + 1)],
        lh_t=[float(min(i, 100)) for i in range(secs + 1)],
        dn_t=[0.0] * (secs + 1),
        gold_t=[gold_fn(i) for i in range(secs + 1)],
        total_earned_gold_t=[total_gold_fn(i) for i in range(secs + 1)],
        total_earned_gold_t_min=[total_gold_fn(i * 60) for i in range(6)],
        net_worth_t=[1500.0 + i for i in range(secs + 1)],
        xp_t=[xp_fn(i) for i in range(secs + 1)],
        xp_t_min=[xp_fn(i * 60) for i in range(6)],
        total_deaths_t_min=deaths_min,
        kills=9, deaths=9, assists=1,   # 最终整局值（不应混入前期窗口）
        kills_log=[], obs_log=[], sen_log=[], purchase_log=[], position_log=[],
    )


def test_gpm_xpm_calc():
    # earned(t) = t*10；gpm = earned*60/t = 600；xpm = xp/(t/60), xp=t*100 -> 6000
    p = make_player(total_gold_fn=lambda i: i * 10, xp_fn=lambda i: i * 100)
    wins = extract_windows({"player": p, "match": types.SimpleNamespace(game_start_tick=0), "players": None}, 3, 30)
    for w in wins:
        if w["t_sec"] > 0:
            assert w["gpm"] == 600, f"t={w['t_sec']} gpm={w['gpm']}"
            assert w["xpm"] == 6000
        else:
            assert w["gpm"] == 0 and w["xpm"] == 0
    assert wins[0]["gpm"] == 0  # t=0 -> 0


def test_window_gain_uses_earned_not_gold():
    # 让 gold 在某窗口骤降（模拟买装备），累计收入仍涨：window_gain 应取累计收入差值
    def gold_drops(i):
        # 110s 起突然扣掉 1500 金（模拟买大件），使 120s 时身上金低于 90s
        return i * 10 - (1500 if i >= 110 else 0)
    p = make_player(total_gold_fn=lambda i: i * 10, gold_fn=gold_drops)
    wins = extract_windows({"player": p, "match": types.SimpleNamespace(game_start_tick=0), "players": None}, 3, 30)
    # 窗口 [90,120)：earned 90->900, 120->1200 => diff=300
    w120 = next(w for w in wins if w["t_sec"] == 120)
    w90 = next(w for w in wins if w["t_sec"] == 90)
    # window_gain 应为累计收入差 300，不受 gold 骤降影响
    assert w120["window_gain"] == 300, w120["window_gain"]
    # 身上金因买装备下降（gold 差为负），但累计收入窗口差仍为正
    assert (w120.get("gold", 0) - w90.get("gold", 0)) < 0
    assert w120["window_gain"] > 0


def test_deaths_uses_minute_series():
    deaths_min = [0, 1, 1, 2, 2, 2]  # 第0分钟0死, 第1分钟1死, 第3分钟2死
    p = make_player(deaths_min=deaths_min)
    wins = extract_windows({"player": p, "match": types.SimpleNamespace(game_start_tick=0), "players": None}, 3, 30)
    d0 = next(w for w in wins if w["t_sec"] == 0)
    assert d0["deaths"] == 0  # 第0分钟，未死
    # 第 2 分钟 (t=120) -> deaths_min[2]=1
    d2 = next(w for w in wins if w["t_sec"] == 120)
    assert d2["deaths"] == 1
    # 不应是整局最终死亡 9
    assert d2["deaths"] != 9 and d0["deaths"] != 9


def test_metrics_has_xpm_key():
    """metrics 字典包含 xpm 键（= XPM 而非累计 XP）。"""
    p = make_player(total_gold_fn=lambda i: i * 10, xp_fn=lambda i: i * 100)
    wins = extract_windows({"player": p, "match": types.SimpleNamespace(game_start_tick=0), "players": None}, 3, 30)
    for w in wins:
        assert "xpm" in w, f"缺 xpm 键: {w}"
        assert "xp" in w
        # xpm = xp/(t/60)，t=120 -> xp=12000, xpm=6000
        if w["t_sec"] > 0:
            assert w["xpm"] == 6000
            assert w["xp"] == w["t_sec"] * 100  # xp 仍是累计值
