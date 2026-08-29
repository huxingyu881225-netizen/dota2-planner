"""验证：gem 返回的绝对 tick 需用 match.game_start_tick 归零，才能在前 N 分钟取到数据。"""
import types

from dota_assistant.ingest.extractor import extract, extract_windows, _to_sec


def make_player(cs_per_min, base_tick=0, kills=2, deaths=0):
    secs = 6 * 60
    # tick 从 base_tick 开始（绝对 tick）
    times = [base_tick + i * 30 for i in range(secs + 1)]
    return types.SimpleNamespace(
        player_id=0, hero_name="npc_dota_hero_juggernaut",
        times=times,
        lh_t=[float(cs_per_min[int(min(i / 60, len(cs_per_min) - 1))]) for i in range(secs + 1)],
        dn_t=[0.0] * (secs + 1),
        gold_t=[600 + (i / 60) * 40 for i in range(secs + 1)],
        total_earned_gold_t=[500 + (i / 60) * 22 * 60 for i in range(secs + 1)],
        net_worth_t=[1500 + (i / 60) * 950 for i in range(secs + 1)],
        xp_t=[600 + (i / 60) * 140 * 60 for i in range(secs + 1)],
        kills=kills, deaths=deaths, assists=1,
        # 绝对 tick 的购买/插眼/击杀/位置
        purchase_log=[types.SimpleNamespace(tick=base_tick + 100 * 30, value_name="item_blink")],
        obs_log=[types.SimpleNamespace(tick=base_tick + 150 * 30)],
        sen_log=[],
        kills_log=[types.SimpleNamespace(tick=base_tick + 80 * 30)],
        position_log=[(base_tick + i * 60 * 1, 100.0 + i, 200.0 + i) for i in range(0, secs + 1, 60)],
    )


def test_to_sec_with_base():
    assert _to_sec(1000, 100) == 30          # (1000-100)/30
    assert _to_sec(1000, 0) == 33            # 无 base 时行为


def test_windows_get_data_with_game_start_tick():
    base = 10_000  # 模拟 replay 绝对 tick 基准
    player = make_player([8, 16, 24, 32, 40], base_tick=base)
    match = types.SimpleNamespace(game_start_tick=base)
    data = {"player": player, "match": match, "players": None}

    wins = extract_windows(data, 5, 30)
    # 关键：前 10 分钟窗口应能取到 cs/networth 等
    assert len(wins) == 5 * 60 // 30 + 1
    # 0 秒窗口
    assert wins[0]["cs"] is not None and wins[0]["cs"] >= 0
    assert wins[0]["networth"] is not None
    # 某个窗口应统计到购买的 blink（100s=100*30 tick，即 1.5min 窗口内）
    # blink 在 100s → 属于窗口 [90,120)s；kills 在 80s → [60,90)s
    # 检查相对窗口的杀/购买事件
    for w in wins:
        if w["t_sec"] == 90:
            assert w["kills_in_window"] >= 1, "90s 窗口应含 80s 的击杀"
        if w["t_sec"] == 120:
            assert "blink" in " ".join(w.get("items_bought", [])), "120s 窗口应含 100s 的购买"
    # 位置在 100s 应可取到某坐标
    assert wins[2]["pos_x"] is not None  # 90s 窗口


def test_no_base_tick_still_works():
    """没配 game_start_tick（None）时退化为原行为，不报错。"""
    player = make_player([8, 16, 24], base_tick=0)
    match = types.SimpleNamespace(game_start_tick=None)
    data = {"player": player, "match": match, "players": None}
    wins = extract_windows(data, 3, 30)
    assert len(wins) > 0
    assert wins[0]["cs"] is not None
