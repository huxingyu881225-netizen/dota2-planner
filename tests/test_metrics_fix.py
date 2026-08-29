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


def test_starting_items_up_to_12():
    """starting_items 最多取 12 件（覆盖开局岗哨守卫等）。"""
    base = 5000
    secs = 3 * 60
    # 开局 2 秒内连买 9 件（含岗哨守卫）+ 后续
    purchases = []
    for i in range(9):
        purchases.append(types.SimpleNamespace(tick=base + (1 + i) * 30, value_name=f"item_ward_{i}"))
    purchases.append(types.SimpleNamespace(tick=base + 10 * 30, value_name="item_ward_sentry"))
    purchases.append(types.SimpleNamespace(tick=base + 12 * 30, value_name="item_tango"))
    purchases.append(types.SimpleNamespace(tick=base + 13 * 30, value_name="item_clarity"))
    purchases.append(types.SimpleNamespace(tick=base + 60 * 30, value_name="item_boots"))
    p = types.SimpleNamespace(
        player_id=0, hero_name="npc_dota_hero_juggernaut",
        times=[base + i * 30 for i in range(secs + 1)],
        lh_t=[0.0] * (secs + 1), dn_t=[0.0] * (secs + 1),
        gold_t=[600.0] * (secs + 1), total_earned_gold_t=[500.0] * (secs + 1),
        net_worth_t=[1500.0] * (secs + 1), xp_t=[600.0] * (secs + 1),
        total_deaths_t_min=[0] * 4, kills=0, deaths=0, assists=5,
        kills_log=[], obs_log=[], sen_log=[], purchase_log=purchases, position_log=[],
    )
    wins = extract_windows({"player": p, "match": types.SimpleNamespace(game_start_tick=base), "players": None}, 2, 30)
    # 前15秒：9件ward + sentry + tango + clarity = 12件（boots 在60s 不算）
    start = wins[0]["starting_items"]
    assert len(start) <= 12
    assert "ward sentry" in start or any("sentry" in s for s in start), start
    assert "boots" not in start
    # 数量超过6（老实现会截断到6）
    assert len(start) >= 9


def test_no_final_assists_in_metrics():
    """前期窗口 metrics 不含整局最终 assists，避免 LLM 误判。"""
    base = 0
    secs = 3 * 60
    p = types.SimpleNamespace(
        player_id=0, hero_name="npc_dota_hero_juggernaut",
        times=[i * 30 for i in range(secs + 1)],
        lh_t=[0.0] * (secs + 1), dn_t=[0.0] * (secs + 1),
        gold_t=[600.0] * (secs + 1), total_earned_gold_t=[500.0] * (secs + 1),
        net_worth_t=[1500.0] * (secs + 1), xp_t=[600.0] * (secs + 1),
        total_deaths_t_min=[0] * 4, kills=9, deaths=9, assists=7,
        kills_log=[], obs_log=[], sen_log=[], purchase_log=[], position_log=[],
    )
    wins = extract_windows({"player": p, "match": types.SimpleNamespace(game_start_tick=0), "players": None}, 2, 30)
    for w in wins:
        assert "assists" not in w, f"t={w['t_sec']} 不应有整局 assists: {w}"
        assert "assists_in_window" not in w


def test_behavior_fallback_includes_starting_items():
    """fallback(behavior.build) 要输出起始装/窗口新增/累计已购。"""
    from dota_assistant.core.behavior import build
    text = build({
        "t_sec": 30,
        "starting_items": ["tango", "magic stick"],
        "items_bought_in_window": ["boots"],
        "items_bought_so_far": ["tango", "magic stick", "boots"],
        "cs": 10, "gpm": 500,
    }, "carry")
    assert "起始装:tango,magic stick" in text
    assert "本窗口新增购买:boots" in text
    assert "已购:tango,magic stick,boots" in text
