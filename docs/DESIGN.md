# dota:assistant（dota-planner）设计方案

> 灵感来源：`dota-ai-coach`（macOS/Windows 浮窗 + 实时建议）与 `dota2-coach-plugin`（录像/职业比赛行为抽取）。
> 目标：把「职业/高质量录像的行为」沉淀成本地 SQLite 数据库，在玩家自己开黑时以浮窗持续给出该英雄/位置的「参考行为」建议，并能在赛后对比「你自己打得和参考哪里不一致 + 结果好坏」，同时提供界面手动修正建议。

---

## 1. 背景与核心思路

需求拆成四件事：

| # | 需求 | 本质 | 落点 |
|---|------|------|------|
| 1 | 喂一盘本地 .dem 录像 + 英雄 + 位置 + 前 N 分钟 + 间隔 M 秒 → 抽取该英雄每 M 秒的主要行为入库 | **数据灌入（ETL）** | SQLite `samples` |
| 2 | 浮窗：输入英雄+位置 → 每 M 秒给 DB 里的建议行为，直到第 N 分钟 | **实时教练（读库）** | 浮窗 + `advice` |
| 3 | 喂录像+英雄+位置 → 对比前 N 分钟行为与 DB 参考，指出不一致并判断好坏；DB 无该英雄/位置则跳过 | **赛后对比（diff）** | `analysis` 引擎 |
| 4 | 界面：修改某英雄某位置某时间段的建议行为 | **编辑管理（CRUD）** | Web UI → `advice` |

**一句话架构**：*Ingest（写）→ SQLite（存）→ Coach / Diff / Edit（读与管理）*。

设计原则：
- **数据与逻辑分离**：入库的 `samples`（客观观测）与可编辑的 `advice`（参考建议）分开，避免被手动编辑污染原始样本。
- **以 gem-dota 为主数据源**（本地解析 .dem，秒级、离线、职业录像自备）；OpenDota 仅作可选预留。
- **本地优先**：全部落在本地 SQLite，浮窗/UI 均为本地服务，分析全程离线。

---

## 2. 技术选型

- **语言**：Python 3.11+（与 dota2-coach-plugin 同生态；astral/uv 管理依赖）。
- **LLM（可选）**：核心策略文本由 LLM 生成（OpenRouter 等 OpenAI 兼容接口），
  环境变量 `DOTA_LLM_API_KEY` 配置后启用；未配置自动回退本地模板，完全离线。
- **数据库**：SQLite（`sqlite3` 标准库），`data/dota_planner.db`。
- **数据获取**：**gem-dota 为主数据源**（读取本地 `.dem`，职业比赛录像由用户自行下载）。gem 提供秒级并行时间序列
  （`times/gold_t/total_earned_gold_t/net_worth_t/lh_t/dn_t/xp_t`）与事件日志（击杀/购买/插眼/位置），时间粒度比第三方在线数据更细。
  - OpenDota 已降级为可选/预留后端（`ingest/opendota.py` 保留），CLI 默认不再暴露。
- **浮窗**：macOS 原生 `NSPanel`（配合 `pyobjc`），无边框、置顶、不抢焦点——与 dota-ai-coach 浮窗形式一致；同时提供终端降级模式（无 GUI 也能跑）。
- **编辑/管理 UI**：本地 Web（FastAPI + 静态 HTML/JS），端口 `17373`。
- **包管理**：`uv` + `pyproject.toml`。

---

## 3. 目录结构

```
dota2-assistant/
├── pyproject.toml
├── README.md
├── docs/DESIGN.md
├── data/                       # 本地 SQLite + 缓存(不入库)
├── src/dota_assistant/
│   ├── __init__.py
│   ├── core/
│   │   ├── models.py           # 领域模型：Position, Sample, MatchMeta, Advice, DiffReport
│   │   ├── positions.py        # 位置枚举(carry/mid/offline/offlane_support/safelane_support)
│   │   └── behavior.py         # 行为生成器：metrics+events -> 行为文本
│   ├── db/
│   │   ├── schema.sql          # 建表语句
│   │   ├── database.py         # 连接/初始化
│   │   └── repo.py             # 仓储：Sample/Advice/Match CRUD 与查询
│   ├── llm/
│   │   └── strategy.py         # LLM 核心策略生成(OpenRouter/OpenAI兼容, 无key回退模板)
│   ├── ingest/
│   │   ├── source.py           # 数据源抽象
│   │   ├── opendota.py         # OpenDota 源（可选/预留）
│   │   ├── gem.py              # gem-dota 本地 .dem 源（可选）
│   │   └── extractor.py        # 核心抽取：按 M 秒对齐取样 -> Sample 列表
│   ├── analysis/
│   │   └── differ.py           # 需求3：行为对比 + 好坏判定
│   ├── overlay/
│   │   ├── coach.py            # 教练循环：按 M 秒查 advice 并显示
│   │   ├── mac_panel.py        # macOS NSPanel 浮窗
│   │   └── term.py             # 终端降级输出
│   └── ui/
│       ├── server.py           # FastAPI：REST + 静态页
│       └── static/             # 编辑界面 HTML/JS
│   └── cli/
│       ├── main.py             # argparse 入口
│       └── commands.py         # ingest / coach / diff / serve / edit
├── tests/                      # 单测（repo/extractor/differ）
```

---

## 4. 数据库设计（SQLite）

三个核心表。`samples` 是**原始观测**，`advice` 是**参考建议**（对应需求 4 的可编辑项），`matches` 记录来源。

```sql
-- 来源录像元信息
CREATE TABLE IF NOT EXISTS matches (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  match_id    TEXT NOT NULL,
  source      TEXT NOT NULL,            -- 'opendota' | 'gem' | 'manual'
  hero        TEXT NOT NULL,
  position    TEXT NOT NULL,
  minute_n    INTEGER NOT NULL,         -- 前 N 分钟
  interval_m  INTEGER NOT NULL,         -- 间隔 M 秒
  result      TEXT,                     -- 'win'|'loss'（用于好坏参照）
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 每 M 秒的行为样本（客观观测）
CREATE TABLE IF NOT EXISTS samples (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  match_ref   INTEGER NOT NULL REFERENCES matches(id),
  hero        TEXT NOT NULL,
  position    TEXT NOT NULL,
  t_sec       INTEGER NOT NULL,         -- 录像内时刻(秒)
  t_min       REAL NOT NULL,            -- 分钟(浮点)
  behavior    TEXT NOT NULL,            -- 生成的“主要行为”叙述
  cs          INTEGER,                  -- 补刀数
  gpm         INTEGER,                  -- 每分钟金钱
  xpm         INTEGER,
  networth    INTEGER,
  kills       INTEGER,
  deaths      INTEGER,
  pos_x       REAL, pos_y REAL,         -- 地图坐标（如有）
  extra       TEXT                      -- JSON 扩展（物品/眼/野怪等）
);

-- 参考建议（需求 4 的可编辑数据；需求 2 的读库对象）
CREATE TABLE IF NOT EXISTS advice (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  hero        TEXT NOT NULL,
  position    TEXT NOT NULL,
  t_start_min REAL NOT NULL,            -- 时间窗口起点(分钟)
  t_end_min   REAL NOT NULL,            -- 时间窗口终点(分钟)
  advice      TEXT NOT NULL,            -- 建议行为文本
  source      TEXT,                     -- 来源(自动生成/人工)
  updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(hero, position, t_start_min, t_end_min)
);

CREATE INDEX IF NOT EXISTS idx_samples_hero_pos ON samples(hero, position, t_sec);
CREATE INDEX IF NOT EXISTS idx_advice_hero_pos   ON advice(hero, position);
```

**关于“时间段”**：
- `samples` 用绝对时刻 `t_sec` 表达「前 N 分钟里每 M 秒」。
- `advice` 用 `[t_start_min, t_end_min]` 表达「某时间段」，因为建议通常是分阶段的（如 0-2 分钟对线、3-5 分钟囤野），而不是秒级。教练浮窗根据当前游戏分钟落在哪个窗口来显示对应建议。

---

## 5. 位置枚举（position）

参照需求原文，定义为 5 个：

| 枚举值 | 说明 | OpenDota lane_role 映射（参考） |
|--------|------|-------------------------------|
| `carry` | 一号位/核心 | safelane core (1) |
| `mid` | 二号位/中路 | mid (2) |
| `offline` | 三号位/劣单 | offlane (3) |
| `offlane_support` | 四号位/劣单辅助 | 4 |
| `safelane_support` | 五号位/优势路辅助 | 5 |

位置在校验与会话层做归一化（允许别名：`offlane`, `off`, `pos4`, `safelane`→`carry` 等按需软映射，默认严格枚举）。

---

## 6. 模块设计

### 6.1 Ingest（需求 1）——`ingest/`

`ingester.run(replay_path, hero, position, minute_n, interval_m) -> (match_ref, inserted)`

处理流程（主路径：gem-dota 本地 .dem）：
1. `GemSource.fetch(replay_path, hero, position, ...)`：
   - `gem.parse(path)` 解析出 `ParsedMatch`（含 `players`）。
   - `gem.find_player(match, hero)` 按英雄定位目标玩家（支持显示名/`npc_dota_hero_*`/裸后缀）。
   - 产出统一数据字典 `{match, players, player, hero, ...}`。
2. `extractor.extract(...)` 只对目标玩家工作：
   - 用 gem 秒级序列 `times/lh_t/gold_t/total_earned_gold_t/net_worth_t/xp_t/dn_t` 对齐到取样网格
     `0, M, 2M, …, N*60` 秒（tick=30 刻/秒，gem 约 1 次/秒采样）。
   - 每取样点计算：CS、GPM（累计赚金币）、净财富、XP、补刀差、窗口新增金钱、击杀（`kills_log`）、
     插眼（`obs_log/sen_log`）、本窗口新买装备（`purchase_log.value_name`）、坐标（`position_log`）。
   - 用 `behavior.build()` 生成“主要行为”叙述。
3. 写库：`matches` + `samples`。

> 因为 gem 是秒级采样，`M` 秒间隔（如 30/60）都能得到平滑数据；若想用整数分钟刻度，可直接取 gem 的
> `*_min` 序列（`lh_t_min` 等，与 OpenDota 对齐）。

### 6.2 Coach 浮窗（需求 2）——`overlay/`

`coach.run(hero, position, minute_n, interval_m)`：

1. 用户输入 `英雄 + 位置`（浮窗表单或 CLI 参数）。
2. 每 `interval_m` 秒做一次：
   - 读当前“游戏分钟”（浮窗模式下用户手动输入/或与 GSI 联动；MVP 用会话计时器从 0 开始累加，也可读真实 Dota GSI 的 `map.game_time`）。
   - `repo.lookup_advice(hero, position, current_minute)` 查命中窗口的 `advice`。
   - 若无该英雄/位置或该分钟，显示“暂无参考建议，请先灌入/编辑”。
   - 持续到 `current_minute >= minute_n` 停止。
3. 展示载体：
   - **macOS NSPanel**（`mac_panel.py`）：无边框、置顶、不抢焦点，仿 dota-ai-coach 浮窗。若 `pyobjc` 不可用则自动降级到终端。
   - **终端**（`term.py`）：打印一行建议。

与 dota-ai-coach 的衔接：后续可通过 GSI 配置把真实游戏时间喂给 coach，做到“完全免手输分钟”的实时贴合（已预留 `GameClockProvider` 接口）。

### 6.3 Diff 引擎（需求 3）——`analysis/differ.py`

`diff(sample_set_a, db_reference, hero, position) -> DiffReport`

流程：
1. 取新录像的 `samples`（前 N 分钟，每 M 秒）。
2. 从 DB 取**同一英雄+同一位置**的参考 `samples`（可能多盘 → 逐分钟聚合出“参考区间”，如均值/常见值）。
3. 若 DB 中该英雄+位置没有样本 → 直接返回 `skipped=True`（需求 3 要求“没有就跳过”）。
4. 对每个时间桶，对比 `行为类型 + 关键指标`：
   - 偏差项（deviation）：如“CS 比参考低 12”“本该 2 分钟打野却还在线上”“没有在第 5 分钟买眼”。
   - 对每个偏差，结合该盘最终 `result`（win/loss）判断“偏离 → 好结果 or 坏结果”：
     - 简单的相关性启发式：偏差方向 + 该盘相对参考的胜负/经济差。
     - 设计上把“好坏判定”做成**可替换策略**（`OutcomeJudger`），默认用规则；配置 `DOTA_LLM_API_KEY` 时，
       `llm/judger.py` 会把偏差列表发给 LLM，逐条覆盖 outcome 并补一句人话解释（解析失败自动保留规则结果）。
       核心策略生成同样走 LLM（见 6.1），未配置 key 时两者都自动回退本地实现，完全离线可用。
   - 输出结构化 `DiffReport`（偏差列表 + 每条好/坏 + 汇总建议），并可选写入一个 `reports` 表（设计里先落 JSON 文件 `data/reports/`）。

### 6.4 编辑界面（需求 4）——`ui/`

- `ui/server.py`：FastAPI 提供 REST：
  - `GET /advice?hero=&position=` 查询建议；
  - `POST /advice` 新增/更新某时间段建议（upsert）；
  - `DELETE /advice/{id}` 删除；
  - `GET/POST /samples` 查看/回灌样本；
  - `GET /` 静态编辑页。
- `ui/static/`：极简单页：英雄下拉 + 位置下拉 → 时间线表格（时间段、建议文本、来源、更新），就地编辑保存。
- 启动：`dota run serve`，浏览器打开 `http://localhost:17373`。

---

## 7. CLI（入口）——`cli/main.py`

统一命令（主数据源 = 本地 .dem）：

```
dota ingest  <replay.dem> --hero <h> --position <p> [--minutes N --interval M] [--result win|loss]
dota coach                             # 交互式：输入英雄+位置(+M+N)，浮窗/终端给建议
dota coach --hero <h> --position <p> --minutes N --interval M [--gui]
dota diff   <replay.dem> --hero <h> --position <p> [--minutes N --interval M] [--result win|loss]
dota demo                             # 离线造一份演示数据（无需 .dem / 联网）
dota serve                            # 启动建议编辑 Web UI
dota list                             # 列出库里已有的 英雄/位置/条数
```

> 玩家自备职业比赛 `.dem`，即可当“好的参考例子”灌库。真正入口：
> `python -m dota_assistant.cli.main ...` 或 `dota ...`（console_script）。

---

## 8. 运行数据流小结

- 准备职业录像 `.dem`（如职业赛事录像）→ 灌库。
- 首次使用：`dota ingest pro_match.dem --hero juggernaut --position carry --minutes 10 --interval 30` → 写入参考样本。
- 想更丰富：灌多盘同一英雄/位置的职业 `.dem`，DB 聚合出“参考行为”。
- 对局中（需求 2）：`dota coach --hero juggernaut --position carry --minutes 10 --interval 30` → 浮窗每 30s 显示建议。
- 赛后（需求 3）：`dota diff your_match.dem --hero juggernaut --position carry --result loss` → 输出与参考不一致 + 好坏结论。
- 改建议（需求 4）：`dota serve` → 浏览器里编辑 `advice`。

---

## 9. 扩展点 / 后续

- **GSI 实时对齐**（借鉴 dota-ai-coach）：接入 Dota 2 Game State Integration，自动感知当前英雄/位置/游戏时间。
- **LLM 好坏判定**：核心策略生成与 diff 好坏判定均已用 LLM（可选，无 key 回退规则/模板）。
- **行为结构化**：将叙述升级为带 `action_type` 的结构（对线/游走/打野/控图/团战/买眼）。
- **批量灌库**：批量灌同英雄/位置的职业 `.dem`，聚合出参考库。

---

## 10. 安全 / 合规 / 边界

- 全程本地分析 `.dem`，无云端依赖；职业录像需自行下载（遵循其版权/使用条款）。
- 数据全部本地，不采集个人对局上传。
- 浮窗不抢焦点、可关闭，避免影响游戏操作。
