"""CLI entrypoint (gem-dota 本地 .dem 为主)。

Usage:
  dota demo                 # 生成一份本地演示 .dem 并灌库（离线体验）
  dota ingest <replay.dem> --hero H --position P [--minutes N] [--interval M] [--result win|loss]
  dota coach --hero H --position P [--minutes N] [--interval M] [--gui]
  dota diff  <replay.dem> --hero H --position P [--minutes N] [--interval M] [--result win|loss]
  dota serve
  dota list
"""
from __future__ import annotations

import argparse
import sys

from dota_assistant import __version__


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="dota", description="dota:assistant (gem-dota 本地录像)")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    ing = sub.add_parser("ingest", help="灌入本地 .dem 录像行为到 SQLite")
    ing.add_argument("match", help=".dem 录像文件路径")
    ing.add_argument("--hero", required=True)
    ing.add_argument("--position", required=True)
    ing.add_argument("--minutes", type=int, default=10, help="前 N 分钟")
    ing.add_argument("--interval", type=int, default=30, help="间隔 M 秒")
    ing.add_argument("--result", choices=["win", "loss"], default=None)

    demo = sub.add_parser("demo", help="离线写入一份演示参考数据（无需 _dem / 联网）")

    co = sub.add_parser("coach", help="浮窗/终端实时给建议")
    co.add_argument("--hero")
    co.add_argument("--position")
    co.add_argument("--minutes", type=int, default=10)
    co.add_argument("--interval", type=int, default=30)
    co.add_argument("--gui", action="store_true", help="尝试 macOS 浮窗")

    df = sub.add_parser("diff", help="赛后对比行为 + 好坏判定")
    df.add_argument("match", help=".dem 录像文件路径")
    df.add_argument("--hero", required=True)
    df.add_argument("--position", required=True)
    df.add_argument("--minutes", type=int, default=10)
    df.add_argument("--interval", type=int, default=30)
    df.add_argument("--result", choices=["win", "loss"], default=None)

    sub.add_parser("serve", help="启动建议编辑 Web UI")
    sub.add_parser("list", help="列出数据库中的英雄/位置组合与条数")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        from dota_assistant.cli import commands
        fn = getattr(commands, "cmd_" + args.cmd)
        fn(args)
    except KeyboardInterrupt:
        print("\n已停止", file=sys.stderr)
    except Exception as e:  # noqa
        print(f"错误: {e}", file=sys.stderr)
        return 1
    return 0
