"""CLI 子命令实现（gem-dota 本地 .dem 为主）。"""
from __future__ import annotations

import json
from pathlib import Path

from dota_assistant.core.models import Advice, MatchMeta, Sample
from dota_assistant.core.positions import normalize_position
from dota_assistant.db.database import connect, init_schema
from dota_assistant.db.repo import Repo

PROJECT_ROOT = Path(__file__).resolve().parents[3]
REPORT_DIR = PROJECT_ROOT / "data" / "reports"


def cmd_ingest(args):
    from dota_assistant.ingest.ingester import Ingester

    position = normalize_position(args.position)
    ing = Ingester()
    mr, inserted, advice_n = ing.run(
        replay_path=args.match,
        hero=args.hero,
        position=position,
        minute_n=args.minutes,
        interval_m=args.interval,
        result=args.result,
        use_llm=getattr(args, "use_llm", None),
    )
    print(f"已入库: match_ref={mr}，写入样本 {inserted} 条 "
          f"({args.hero}/{position}, 前{args.minutes}分钟×每{args.interval}秒)，"
          f"并初始化建议 {advice_n} 条")


def cmd_demo(args):
    """离线演示：直接造一份“职业参考样本 + 建议”入 SQLite（无需 .dem / 联网）。"""
    hero, position = "juggernaut", "carry"
    conn = connect()
    init_schema(conn)
    repo = Repo(conn)

    # 造一组看起来像职业盘高水平的样本（前 12 分钟，每 30 秒）
    mr = repo.insert_match(MatchMeta(
        match_id="demo_pro_1", source="demo", hero=hero, position=position,
        minute_n=12, interval_m=30, result="win",
    ))
    samples = []
    for t in range(0, 12 * 60 + 1, 30):
        m = t / 60
        cs = int(8 + m * 9)                      # 每分钟稳步 +9 补刀
        gpm = int(500 + m * 22)
        nw = int(1500 + m * 950)
        samples.append(Sample(
            hero=hero, position=position, t_sec=t, t_min=round(m, 2),
            behavior=f"{t//60:02d}:{t%60:02d} 对线/发育；CS {cs}；GPM {gpm}；净财富 {nw}",
            cs=cs, gpm=gpm, xpm=int(600 + m * 140), networth=nw, kills=3, deaths=0,
        ))
    repo.insert_samples(mr, samples)
    advice_n = repo.init_advice_from_samples(hero, position, source="demo", interval_m=30)
    print("演示数据已写入 SQLite（英雄 juggernaut / carry）：")
    print("  样本", len(samples), "条 + 建议", advice_n, "条（30秒粒度）")
    print("现在可以跑: dota coach --hero juggernaut --position carry / dota serve")


def cmd_coach(args):
    from dota_assistant.overlay.coach import Coach, SessionClock
    from dota_assistant.overlay.gsi import GsiServer, GsiState, GsiGameClock
    from dota_assistant.overlay.term import TermDisplay
    import time as _time

    # ---- GSI：游戏开始自动计时 ----
    gsi_state = GsiState()
    gsi_server = None
    if not getattr(args, "no_gsi", False):
        gsi_server = GsiServer(port=getattr(args, "gsi_port", 6000), state=gsi_state)
        if gsi_server.start():
            print(f"GSI 已启动，监听 {gsi_server.host}:{gsi_server.port}（把 gamestate_integration_*.cfg 放进 Dota2 cfg 目录）。")
        else:
            print(f"[提示] 无法监听 GSI 端口 {gsi_server.port}（可能被占用），回退会话计时。")
            gsi_server = None

    # ---- 英雄/位置：优先 GSI 自动识别，其次用户输入 ----
    position = None
    if args.hero and args.position:
        hero, position = args.hero, normalize_position(args.position)
    else:
        # 等 GSI 报出英雄（最多等 30s），否则让用户输入
        if gsi_server is not None:
            auto = None
            for _ in range(30):
                n = gsi_state.hero_name.replace("npc_dota_hero_", "")
                if n:
                    auto = n
                    break
                _time.sleep(1)
            if auto and not args.hero:
                args.hero = auto
                print(f"已从 GSI 自动识别英雄: {auto}")
        if not args.hero:
            args.hero = input("英雄: ").strip()
        if position is None:
            position = normalize_position(args.position or input("位置: ").strip())
        if args.minutes is None:
            args.minutes = int(input("前N分钟[10]: ") or 10)

    # ---- 显示载体 ----
    use_gui = bool(getattr(args, "gui", False))
    display = None
    if use_gui:
        try:
            from dota_assistant.overlay.mac_panel import MacOverlay
            display = MacOverlay()
            # 打开面板，等待用户在浮窗输入英雄/位置并点「开始」
            display.open(hero=args.hero or "", position=args.position or "")
            print("浮窗已打开，请在浮窗输入英雄/位置后点「开始输出建议」…")
            display.wait_for_start()
            s = display.get_selection()
            if s[0]:
                args.hero = s[0]
            if s[1]:
                args.position = s[1]
        except Exception as e:
            print(f"浮窗不可用({e})，降级为终端模式。")
            display = None
    if display is None:
        display = TermDisplay()

    # 兜底：若仍未确定英雄/位置（如非 GUI 且无参数），则交互输入
    if not args.hero:
        args.hero = input("英雄: ").strip()
    if not args.position:
        args.position = input("位置: ").strip()
    if args.minutes is None:
        args.minutes = int(input("前N分钟[10]: ") or 10)

    conn = connect()
    init_schema(conn)

    position = normalize_position(args.position)
    # ---- 时钟：GSI 优先，否则会话计时 ----
    clock = GsiGameClock(gsi_state) if gsi_server is not None else SessionClock()
    coach = Coach(Repo(conn), display, clock=clock, gsi_state=gsi_state)
    print(f"开始教练模式 {args.hero}/{position}，前{args.minutes}分钟，每{args.interval}秒。Ctrl+C 退出。")
    try:
        coach.run(args.hero, position, args.minutes, args.interval)
    finally:
        if display is not None and hasattr(display, "close"):
            display.close()
        if gsi_server is not None:
            gsi_server.stop()


def cmd_diff(args):
    from dota_assistant.analysis.differ import Differ, OutcomeJudger
    from dota_assistant.ingest.gem import GemSource
    from dota_assistant.ingest.extractor import extract

    position = normalize_position(args.position)
    src = GemSource()
    data = src.fetch(args.match, args.hero, position, args.minutes, args.interval)
    if data.get("player") is None:
        print(f"录像中未找到英雄 {args.hero} 的玩家。")
        return
    samples = extract(data, args.hero, position, args.minutes, args.interval)

    conn = connect()
    init_schema(conn)
    differ = Differ(Repo(conn), OutcomeJudger(), use_llm=getattr(args, "use_llm", True))
    report = differ.compare(samples, args.hero, position, match_result=args.result)

    if report.skipped:
        print(f"跳过：{report.skip_reason}")
        return

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / f"{args.hero}_{position}_{Path(args.match).name}.json"
    out.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"== {args.hero}/{position} 对比报告 ==")
    print(report.summary)
    for d in report.deviations:
        icon = "✅好" if d.outcome == "good" else "❌坏" if d.outcome == "bad" else "➖"
        print(f"  T{d.t_min:6.1f}min  {d.field}: 实际={d.actual} vs 参考={d.reference} [{icon}] {d.note}")
    print(f"报告已写入 {out}")


def cmd_serve(args):
    import uvicorn
    print("启动编辑界面: http://localhost:17373  (Ctrl+C 退出)")
    uvicorn.run("dota_assistant.ui.server:app", host="127.0.0.1", port=17373, log_level="warning")


def cmd_list(args):
    conn = connect()
    init_schema(conn)
    repo = Repo(conn)
    stats = repo.stats()
    print(f"matches={stats['matches']}  samples={stats['samples']}  建议={stats['advice']}")
    print("（英雄/位置）:")
    for hero, pos in repo.hero_position_pairs():
        print(f"  {hero:>16} / {pos}")
