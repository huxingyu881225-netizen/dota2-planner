# dota:assistant（dota-planner 实现）

本地 Dota 2 规划/教练助手：用 **gem-dota** 解析本地 `.dem` 录像（职业/高质量），把行为沉淀进本地 SQLite；开黑时用浮窗持续给出该英雄/位置的参考行为建议；赛后自动对比「你打得和参考哪里不一致 + 结果好坏」；还提供界面手动修正建议。

灵感来自 `dota-ai-coach`（macOS/Windows 浮窗 + 实时建议）和 `dota2-coach-plugin`（录像行为抽取）。完整设计见 [docs/DESIGN.md](docs/DESIGN.md)。

## 数据源：gem-dota（本地）

- 主数据源 = **本地 `.dem` 录像文件**，用 [gem-dota](https://pypi.org/project/gem-dota/) 解析，**秒级**时间序列（补刀/经济/经验/净财富/插眼/击杀/购买/坐标）。
- 职业比赛录像由你自行下载（作为“好的例子”灌库）；OpenDota 仅保留为可选预留后端，CLI 默认不再使用。

## 功能（对应需求）

| 需求 | 命令 | 说明 |
|------|------|------|
| 1 灌录相行为入库 | `dota ingest pro.dem --hero H --position P [--minutes N --interval M]` | 本地解析 .dem，把该英雄前 N 分钟、每 M 秒的主要行为写入 SQLite |
| 2 浮窗实时给建议 | `dota coach --hero H --position P --minutes N --interval M [--gui]` | 每 M 秒查 DB 对应时间段建议；macOS NSPanel 浮窗或终端显示 |
| 3 赛后对比+好坏判定 | `dota diff my.dem --hero H --position P [--result win\|loss]` | 对比本局行为与 DB 参考，指出偏差并判好坏；DB 无该英雄/位置则跳过 |
| 4 编辑建议界面 | `dota serve` | 浏览器打开 `http://localhost:17373` 修改某英雄/位置/时间段的建议 |

辅助：`dota list` 查看库内数据；`dota demo` 离线造一份演示数据（无需 .dem）。

## 环境要求

- macOS（浮窗用 pyobjc；无 GUI 自动降级终端）
- Python 3.11+（推荐 [uv](https://docs.astral.sh/uv/)）
- 无需联网（本地分析；下载职业 .dem 时需要网络）

## 在另一台电脑上部署（clone 后运行）

```bash
# 拉取代码（二选一）
git clone git@github.com:huxingyu881225-netizen/dota2-planner.git
# 或 HTTPS：git clone https://github.com/huxingyu881225-netizen/dota2-planner.git

cd dota2-planner
uv sync                          # 安装依赖（含 gem-dota、fastapi、pyobjc）
dota demo                        # 离线造一份演示数据（无需 .dem / 联网）
dota list                        # 确认数据已写入
dota coach --hero juggernaut --position carry --minutes 10 --interval 30   # 终端/浮窗给建议
dota serve                       # 打开建议编辑界面 http://localhost:17373
```

> 说明：仓库不含 `.venv`（已 gitignore），clone 后必须在本机执行 `uv sync` 重建环境；
> `pyobjc` 只在 macOS 上安装（浮窗用），无 GUI 时 coach 自动降级为终端模式。

## 快速开始

```bash
cd dota2-planner
uv sync                        # 安装依赖（含 gem-dota）

# 离线体验（无需 .dem/联网）
dota demo
dota coach --hero juggernaut --position carry --minutes 10 --interval 30
dota serve                     # 浏览器打开建议编辑器

# 正式使用：灌一盘职业录像 -> 参考库
dota ingest ./pro_match.dem --hero juggernaut --position carry --minutes 10 --interval 30

# 赛后对比：你自己的一盘
dota diff ./my_match.dem --hero juggernaut --position carry --result loss
```

## 位置枚举

`carry / mid / offline / offlane_support / safelane_support`（接受别名 `off`、`pos4`、`pos5` 等）。

## 项目结构

```
src/dota_assistant/
├── core/        positions 枚举、领域模型、行为叙述生成
├── db/          建表 + 仓储（samples / advice / matches）
├── ingest/      gem-dota 解析（主）+ extractor 秒级取样；opendota.py 可选预留
├── analysis/    赛后 diff + 好坏判定
├── overlay/     教练循环 + macOS 浮窗 + 终端降级
├── ui/          FastAPI 编辑界面（REST + 静态页）
└── cli/         命令行入口
docs/DESIGN.md   完整设计方案
```

## 测试

```bash
PYTHONPATH=src uv run pytest -q
```

## 常见问题

- **`dota/uv` 命令找不到**：先 `uv sync`；若 `uv` 未装，用 `pip install uv` 或直接用
  `python -m dota_assistant ...` 替代 `dota ...`。
- **coach 没显示建议**：先用 `dota demo` 写入演示数据，或 `dota ingest <xxx.dem>` 灌入参考库；
  若 DB 里某英雄/位置没数据，coach/diff 会提示自动跳过。
- **浮窗没出来**：`--gui` 需要 macOS + pyobjc；否则会提示降级为终端。

## 已知边界

- 行为“好坏判定”默认是启发式规则，可替换 `OutcomeJudger` 升级为 LLM 版（未来）。
- 浮窗默认“会话计时”，后续可接 Dota 2 GSI 自动对齐真实游戏时间（同 dota-ai-coach）。
