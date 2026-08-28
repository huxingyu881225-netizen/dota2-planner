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
    mr, inserted = ing.run(
        replay_path=args.match,
        hero=args.hero,
        position=position,
        minute_n=args.minutes,
        interval_m=args.interval,
        result=args.result,
        use_llm=getattr(args, "use_llm", None),
    )
    print(f"已入库: match_ref={mr}，写入样本 {inserted} 条 "
          f"({args.hero}/{position}, 前{args.minutes}分钟×每{args.interval}秒)")


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

    seeds = [
        (0, 2, "出门买补刀斧+治疗，尽量补到每一个正补，压制对线"),
        (2, 5, "囤野+拉双野，保持 CS 领先，注意兵线控制"),
        (5, 8, "带线推塔，利用大招带队打架，控制视野"),
        (8, 12, "跟团拿塔/推高地，注意切入时机"),
    ]
    for s, e, txt in seeds:
        repo.upsert_advice(Advice(hero=hero, position=position,
                                  t_start_min=s, t_end_min=e, advice=txt, source="demo"))
    print("演示数据已写入 SQLite（英雄 juggernaut / carry）：")
    print("  样本", len(samples), "条 + 建议", len(seeds), "条")
    print("现在可以跑: dota coach --hero juggernaut --position carry / dota serve")


def cmd_coach(args):
    from dota_assistant.overlay.coach import Coach, GameClock
    from dota_assistant.overlay.term import TermDisplay

    if not args.hero or not args.position:
        args.hero = input("英雄: ").strip()
        args.position = input("位置: ").strip()
        if args.minutes is None:
            args.minutes = int(input("前N分钟[10]: ") or 10)

    position = normalize_position(args.position)
    display = None
    if args.gui:
        try:
            from dota_assistant.overlay.mac_panel import MacOverlay
            display = MacOverlay()
        except Exception as e:
            print(f"浮窗不可用({e})，降级为终端模式。")
    if display is None:
        display = TermDisplay()

    conn = connect()
    init_schema(conn)
    coach = Coach(Repo(conn), display, GameClock())
    print(f"开始教练模式 {args.hero}/{position}，前{args.minutes}分钟，每{args.interval}秒。Ctrl+C 退出。")
    coach.run(args.hero, position, args.minutes, args.interval)
    if display is not None and hasattr(display, "close"):
        display.close()


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
    differ = Differ(Repo(conn), OutcomeJudger())
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
