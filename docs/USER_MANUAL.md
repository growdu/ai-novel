# novel-writer · 用户手册

> **v0.12** · 完整使用指南  
> **项目定位**：给定输入（题目 + 风格 + 字数 / TXT 源小说）→ 自动写完整本书。  
> **推荐入口**：`novel write`（统一覆盖需求驱动与模仿驱动两种工作流）。

## 目录

1. [快速开始](#1-快速开始)（5 分钟上手）
2. [安装与配置](#2-安装与配置)
3. [教程：5 种典型用法](#3-教程5种典型用法)
4. [命令详解](#4-命令详解)
5. [常见工作流](#5-常见工作流)
6. [故障排查](#6-故障排查)
7. [FAQ](#7-faq)
8. [附录：命令速查](#附录命令速查-47-个)

---

## 1. 快速开始

```bash
# 1. 装包
pip install -e .

# 2. 配置（交互式，密码隐藏输入）
novel setup

# 3. 一行写完整本书（v0.12 起推荐用 novel write）

# 入口 A：需求驱动（题目 + 风格 + 字数 → 自动写完整本）
novel write my_novel \
  --title "冬夜的灰" \
  --theme "1995 年东北小镇的命案与四个孩子" \
  --genre 悬疑 --style 冷峻 --words 60000 \
  --quality premium --serve

# 入口 B：模仿驱动（TXT 源小说 → 提骨架 → 自动写完整本）
novel write fanfic \
  --from-source 白夜行.txt \
  --direction 换壳 --genre 校园 --style 冷峻 \
  --words 60000 --title "夜行"

# 入口 C：网文专项（一键网文包 + 端到端）
novel webnovel-pack my_xuanhuan \
  --title "凡人仙途" --theme "凡人逆袭" \
  --idea "残破玉佩" --auto --words 500000
```

跑完之后：

```bash
cd my_novel
novel status                       # 看章节进度
novel doctor                       # 诊断（加 --fix 自动修复）
novel chat 3 "把结尾放慢一些"      # 自然语言协作修改
```

> **旧工作流（v0.11 及以前）**：仍是合法的 — 用 `novel init + novel chapter N` 手动逐步写，
> 或 `novel auto` 走 6 阶段流水线。`novel write` 是新的统一入口。

# 6. 看进度
# 浏览器：http://127.0.0.1:8765 （novel write --serve 或 novel auto --serve 启动后）
# 或终端：novel status --watch --auto
```

---

## 2. 安装与配置

### 2.1 系统要求

- Python 3.10+
- pip
- 任意 OpenAI Chat Completions 协议 API（默认 minimax）

### 2.2 安装

```bash
git clone <repo> ai-novel && cd ai-novel
pip install -e .             # 标准
pip install -e ".[dev]"      # 含 pytest + ruff（开发用）
```

### 2.3 配置 API（三选一）

| 方式 | 命令 / 文件 | 适合 |
|------|------------|------|
| **A. 向导**（交互） | `novel setup` | 首次（推荐） |
| **B. 复制 .env** | `cp .env.example .env` 后编辑 | 离线 / 已有 key |
| **C. 环境变量** | `export OPENAI_API_KEY=...` | CI / 脚本 |

**向导示例**：

```bash
$ novel setup
╭───────── novel setup ─────────╮
│ novel-writer 首次配置向导        │
│                                │
│ 下面会询问：API 地址、API key、  │
│ 模型、温度、DRY_RUN。           │
╰────────────────────────────────╯
API base URL: https://api.minimaxi.com/v1
API key: ************          ← 密码不回显
模型: minimax-Text-01
temperature（0.7 稳 / 0.95 放飞）: 0.9
目标章节字数: 3000
开启 DRY_RUN 模式? [否]y  # false 是 True
✓ 已写入: /path/to/.env
```

**.env** 关键字段：

```env
OPENAI_BASE_URL=https://api.minimaxi.com/v1
OPENAI_API_KEY=your-key
OPENAI_MODEL=minimax-Text-01    # 或 minimax-M3 / gpt-4o / deepseek-chat
TEMPERATURE=0.9
TARGET_CHAPTER_WORDS=3000
DRY_RUN=false
```

### 2.4 切换模型

```bash
# 临时：命令行
novel config --base-url https://api.openai.com/v1 --model gpt-4o

# 永久：写到 .env
novel config --api-key xxx --model gpt-4o

# 重置
novel setup --force
```

### 2.5 验证环境

```bash
novel doctor
```

应报告"未找到 .novel 项目目录"是预期行为——还没建项目。其他应该全绿。

---

## 3. 教程：5 种典型用法

### 教程 1：5 分钟跑通短篇

```bash
novel setup
novel init short \
  --title "窗台上的橘子" --theme "孤独老人与橘子" \
  --genre 现实 --style 诗意 --words 30000  # 10 章

cd short
novel outline
novel chapter 1    # ~3000 字
novel chapter 2
novel export       # → book.md
```

### 教程 2：长篇 1 周出 70%

```mermaid
graph TB
    A[init --words 200000] --> B[outline]
    B --> C[characters]
    C --> D[world]
    D --> E[volumes 5 卷]
    E --> F[chapter 1 - 70]
    F --> G[每章: state/foreshadow/arc/timeline]
    F --> H[每 5 章: rolling summary]
    F --> I[卷末: volume-report]
    I --> J[audit 检查]
    J --> K[export]
```

```bash
novel init long --title "百年孤影" --theme "东北四代人" \
  --genre 现实 --style 冷峻 --words 200000

cd long
novel outline; novel characters; novel world; novel volumes

# 写（手动单章）
novel chapter 1

# 推荐用 novel write 一行写完整本（v0.12 统一入口）
novel write demo --title X --theme Y --genre Z --style W --words N

# 自动维护：state / foreshadow / arc / timeline / title 每章都更新
# 滚动摘要每 5 章
# 卷末报告每卷

# 检查
novel check
novel audit
novel export
```

### 教程 3：100 万字玄幻仙侠（两阶段工作流）

```mermaid
graph LR
    A[阶段A: 生成章纲] --> B[阶段B: 调整章纲]
    B --> C[阶段C: 写正文]
```

```bash
# 阶段 A：生成大纲 + 所有章纲（30-60 分钟 API 调用）
novel webnovel-pack xiuxian \
  --title "凡人仙途" --theme "凡人逆袭" \
  --genre 修仙 --style 经典爽文 \
  --words 1000000 --idea "残破玉佩金手指"

cd xiuxian
# v0.12 推荐用法：用 novel write --plans-only 只生成章纲不写章节
novel write . --title "凡人仙途" --theme "凡人逆袭修仙" \
  --genre 修仙 --style 经典爽文 --words 1000000 \
  --idea "残破玉佩金手指" --plans-only

# 生成完章纲后人工审核（manual 命令保留）
ls .novel/chapter_plans | wc -l   # 应该看到大量章纲
nano .novel/chapter_plans/0005.md  # 手工调
# 重生成某章：删除文件后重跑 plans-only

# 阶段 C：自动写正文（8-15 小时）
novel write . -t "凡人仙途" --theme "..." \
  --genre 修仙 --style 经典爽文 \
  --words 1000000 --quality premium --budget 120 \
  --skip-plans --serve --serve-port 8765
# --skip-plans：跳过规划（已生成）
# --serve：后台启动 Web 仪表盘
# --budget 120：¥120 上限
```

打开 http://127.0.0.1:8765 看实时进度。

### 教程 4：网文冲量

```bash
# 一键建项目（黄金三章骨架）
novel webnovel-pack cultivation \
  --title "凡人修仙之xxx" --theme "凡人觉醒" \
  --genre 修仙 --style 经典爽文 \
  --idea "金手指：残破玉佩"

cd cultivation

# 黄金三章
novel chapter 1    # 困境
novel chapter 2    # 觉醒
novel chapter 3    # 打脸

# 升级流（v0.12 推荐用 novel write 一次写一段）
novel write demo --title "..." --genre 修仙 --words 50000

# 看半年成本
cat .novel/auto_state.json | python3 -m json.tool | grep -E "cumulative|budget"
```

### 教程 5：改编高热度小说

```bash
# 准备源小说信息
cat > source.txt << 'EOF'
《白夜行》东野圭吾
核心冲突：桐原亮司与雪穗共生 22 年。
EOF

# 一步改编
novel adapt -i source.txt \
  --direction 换名+换壳 --genre 校园 --style 冷峻 \
  --title "夜行"

# 改编方案存到 .novel/adapt.md
cat .novel/adapt.md

# 基于改编方案继续
novel outline
novel chapter 1
```

---

## 4. 命令详解

> 47 个命令，按 7 类组织。每条标注：用途 / 参数 / 示例。

### 4.1 基础（10 个）

| 命令 | 用途 | 关键参数 |
|---|---|---|
| `novel init <name>` | 建项目 | `--title --theme --genre --style --words` |
| `novel setup` | 配置向导 | `--force --no-input` |
| `novel config` | 改 config | `--base-url --model --api-key --dry-run/--no-dry-run` |
| `novel status` | 看项目 | `--watch --auto --interval` |
| `novel version` | 看版本 | `--no-output` 只输出版本号 |
| `novel doctor` | 诊断 | `--fix --json` |
| `novel list` | 列目录项目 | `--path --depth` |
| `novel info <name>` | 看单项目 | 无 |
| `novel whereami` | 当前项目 | 无 |
| `novel templates` | 推荐模板 | 无 |
| `novel serve` | Web 仪表盘 | `--port --host --open/--no-open` |

**`novel status --watch`**：终端版仪表盘
```bash
novel status --watch             # 完整项目状态
novel status --watch --auto      # 只看 auto 进度 / token / 成本
novel status --watch --interval 5  # 自定义刷新间隔
```

**`novel serve`**：浏览器版仪表盘
```bash
cd my_novel && novel serve         # 默认 http://127.0.0.1:8765
novel write ... --serve --serve-port 9000  # write 跑时同步启动
novel auto ... --serve --serve-port 9000   # 等价（同底层）
```

### 4.2 规划（6 个）

| 命令 | 用途 | 备注 |
|---|---|---|
| `novel outline` | 生成 / 重写全书大纲 | `--genre --words --extra --save/--print` |
| `novel characters` | 生成 / 扩展人物志 | `--extra` |
| `novel world` | 世界观 | 无 |
| `novel volumes` | 长篇分卷 | 无 |

> **v0.12 变更**：`plan` / `plan-all` / `plans` 已移除，被 `novel write` 的规划阶段覆盖。如需「只生成章纲不写章节」用 `novel write --plans-only`。

### 4.3 写作（10 个）

| 命令 | 用途 | 关键参数 |
|---|---|---|
| `novel chapter N` | 写第 N 章 | `--words --iters --no-polish --extra` |
| `novel continue N --with T` | 末尾接写 | `--words` |
| `novel chat N '指令'` | 自然语言改 | 无 |
| `novel expand-scene N` | 指定位置接场景 | `--after --words` |
| `novel auto ...` | **一键全自动** | 见 §4.10 |
| `novel webnovel-pack NAME` | 一键网文项目 | `--title --theme --idea` |
| `novel adapt ...` | 改编源小说 | `--source --direction --genre --style` |
| `novel fanfic ...` | 同人 / 后传 | `--source --char --era --as-chapter` |

### 4.4 润色（4 个）

| 命令 | 用途 |
|---|---|
| `novel polish N` | 润色第 N 章（基于 detect+review 反馈） |
| `novel detect N [--save]` | 检测 AI 味 |
| `novel radar N` | 6 维度风格雷达 |

> **v0.12 变更**：`batch` 已移除，被 `novel write` 的 POLISHING + CONSISTENCY 阶段自动覆盖。

### 4.5 一致性（10 个）

| 命令 | 自动 / 手动 | 触发时机 |
|---|---|---|
| `novel state` | 自动 + 手动 | 每章 |
| `novel rolling` | 自动 + 手动 | 每 5 章 |
| `novel foreshadow` | 自动 + 手动 | 每章 |
| `novel arc` | 自动 + 手动 | 每章 |
| `novel timeline` | 自动 + 手动 | 每章 |
| `novel title N` | 自动 + 手动 | 每章 |
| `novel check` | 手动 | 看漂移 |
| `novel volume-report` | 手动 | 卷末 |
| `novel gaps` | 手动 | 看伏笔状态 |
| `novel index` | 手动 | 全书索引 |

### 4.6 版本与导出（7 个）

| 命令 | 用途 | 关键参数 |
|---|---|---|
| `novel history` | 查看历史版本 | 无 |
| `novel diff N` | 对比两版 | `--from --to --stats` |
| `novel rollback N --to vN` | 回滚到历史版本 | `--yes` 跳过确认 |
| `novel fix N` | 检测 / 修复异常章节 | `--no-dry --yes` |
| `novel retry-stuck` | 自动重写残片 | `--threshold --iters` |
| `novel audit` | 综合审计表 | `--start --end` |
| `novel export` | 合并为书稿 | `--format md/txt --output` |

### 4.7 题材 / 文风查询（4 个）

| 命令 | 列出 |
|---|---|
| `novel genres` | 严肃向 10 个题材 |
| `novel styles` | 11 个文风 |
| `novel webnovel-genres` | 网文 8 个题材 |
| `novel webnovel-styles` | 9 个爽感文风 |

### 4.8 端到端写作（推荐入口 — v0.12 起）

#### `novel write <NAME>`（最常用）

两种工作流合一，**一行写完整本书**。

**参数**：

```bash
novel write [NAME] [OPTIONS]

模板快速开始：
  -T, --template NAME    套用推荐模板填充题材/文风/字数（`novel templates` 看列表）

需求驱动（与 --from-source 互不冲突，可同时给 --title 覆盖）：
  -t, --title TEXT       小说标题
  --theme TEXT           一句话主题
  -S, --from-source PATH 模仿驱动：源小说 TXT/MD 文件路径
  -d, --direction TEXT   模仿方向：换名/换壳/后传/反派视角/性别转换

共享：
  -g, --genre TEXT       题材（默认 "现实 / 严肃文学"）
  -s, --style TEXT       文风
  -w, --words INTEGER    目标总字数（默认 50000）
  --chapters INTEGER     显式章节数（0=按字数自动）
  --quality [draft|standard|premium]   质量档（默认 standard）
  --budget FLOAT         成本上限 CNY（0=不限）
  --wait-on-quota / --no-wait          撞 minimax 配额时是否等到恢复（v0.14+）；默认等
  --max-wait-seconds INT              撞配额单次最多等多少秒（默认 6h）

控制：
  --serve                启动后台 Web 仪表盘
  --serve-port INTEGER   仪表盘端口（默认 8765）
  --plans-only           只跑规划阶段，不进入写作
  --skip-plans           跳过规划阶段，直接进入写作
  --parallel / -P INT    并发章节 worker 数（0/1=串行，>=2=并发；v0.13+）
  --here                 就地初始化（跳过 NAME）
  --force                目标目录非空时仍执行
```

**示例**：

```bash
# 入口 A：需求驱动
novel write my_novel \
  --title "冬夜的灰" --theme "1995 东北命案" \
  --genre 悬疑 --style 冷峻 --words 60000 --quality premium

# 入口 B：模仿驱动（基于源小说自动提骨架 + 改编）
novel write fanfic --from-source 白夜行.txt \
  --direction 换壳 --genre 校园 --style 冷峻 --words 80000 \
  --title "夜行"

# 入口 C：模板快速开始（用 东北悬疑 模板填充，用户字段覆盖）
novel write quick --template 东北悬疑 --title '盘锦往事' --words 80000
```

**6 阶段流水线**：`novel write` 内部调用 `run_auto_novel()` 跑完：
1. PLANNING（大纲 / 人物 / 世界观 / 分卷 / 章纲）
2. WRITING（逐章生成 + 质量门控 + 重试）
3. POLISHING（自动润色未达标章节）
4. CONSISTENCY（人物名 / 时间 / 地点 / 设定漂移检测）
5. EXPORTING（合并为 `book.md`）
6. DONE（`state.phase = DONE`，`book.md` 存在）

**三档 quality 对比**：

| 档 | 章节迭代 | 字数容差 | AI 味阈值 | 雷达阈值 | 适合 |
|---|---|---|---|---|---|
| `draft` | 1 | ±30% | 跳过 | 跳过 | 网文冲量（速度优先）|
| `standard` | 2 | ±20% | < 50 | ≥ 60 | 一般场景（默认）|
| `premium` | 3 | ±10% | < 30 | ≥ 70 | 严肃向（质量优先）|

**撞到 minimax 配额怎么办（v0.14+ 默认行为）**：
- 默认 `--wait-on-quota`：**自动等 quota 重置再继续**，最多等 6 小时
- 等不情愿？加 `--no-wait` 立刻退出，下次 `novel write .` 自动续
- 周配额撞了调 `--max-wait-seconds 604800`（7 天）
- 详细：[§6.7a 撞到 minimax 配额限制](#67a-撞到-minimax-配额限制429--quota-exceeded)

**并发（加速）**：
- `--parallel 4` 开 4 个 worker 并发生成章节，比串行省 50%+ 时间
- 详情：见 [§4.11 并发生成](#411-并发生成)

#### `novel webnovel-pack <NAME> --auto`

网文专项（黄金三章骨架 + 爽感节奏）。`--auto` 一行写完整本网文：

```bash
novel webnovel-pack my_x --title "凡人仙途" --theme "凡人逆袭" \
  --idea "残破玉佩" --auto --words 500000 --quality premium
```

不加 `--auto` 只建项目骨架，行为与 v0.11 一致（向后兼容）。

`--auto` 模式同样支持 `--parallel` 与 `--wait-on-quota`。

### 4.11 并发生成（v0.13+）

`--parallel N`（或 `-P N`）让章节生成并发：

```bash
# 串行（默认）：逐章写
novel write demo --title X --words 60000

# 4 worker 并发：节省 50%+ 时间
novel write demo --title X --words 60000 --parallel 4

# 大项目：8 worker（接近理论上限）
novel write my_novel --title X --words 600000 --parallel 8
```

**并发原理**：`ThreadPoolExecutor` 并发 LLM 调用（I/O-bound）。
4 个并发安全问题已处理：
1. `state.json` 写竞争：`threading.Lock()` 串行化
2. `progress.update` 竞争：`threading.Lock()` 串行化
3. 跨 worker 章节顺序（`prev_tail`）：`prev_cache` dict 共享
4. 控制信号文件读取：OS 文件读写原子

**当并发撞到配额**：每个 worker 独立检测 429 → 等 quota → 重试。
多个 worker 共享 reset 时间，可能轮流 await 到 reset → 一起 retry。

**性能预期**：

| parallel | 6 章 | 30 章 | 60 章 |
|---|---|---|---|
| 1（默认） | 5-15 分钟 | 25-75 分钟 | 50-150 分钟 |
| 3 | 2-5 分钟（-60%）| 8-25 分钟 | 16-50 分钟 |
| 8 | 1-2 分钟（-80%）| 4-12 分钟 | 8-25 分钟 |

（实测待你跑完真 API 后补充）

### 4.12 FAQ

**Q：我跑 `novel write` 在第 30 章挂了，下次再跑会重写 1-29 章吗？**
A：不会。`auto_state.json` 记着已完成的章节号；下次 `novel write` 自动跳过。**首次或中断后无需任何参数**，照常跑就行。

**Q：5 万字的小说我应该选什么 quality？**
A：
- 长篇网文冲量：`draft`（最快）
- 严肃文学 / 商业小说：`premium`（最多 3 轮迭代）
- 默认 `standard` 对一般场景够用

**Q：`--parallel 4` 跟单 worker 写出来质量有区别吗？**
A：没有。每个 worker 调同一模型同一 prompt，输出确定性来自 temperature 而非并发。只差在 wall-clock。

**Q：我 Ctrl-C 退出了，下次跑会丢进度吗？**
A：不会。每章写完都 `state.save()`，下次 `novel write .` 自动从中断处继续。

**Q：我已经 init 过项目，能直接 `novel write` 而不重新 init 吗？**
A：能。`novel write .` 加 `--here` 就在当前目录写。状态自动从 `.novel/project.yaml` 恢复。

**Q：`novel auto` 和 `novel write` 啥区别？**
A：
- `novel write`：v0.12+ 推荐入口；自动 init + 跑 6 阶段；适合新项目
- `novel auto`：v0.11 旧入口；项目已 init 时用；底层和 `novel write` 共享 `run_auto_novel()`
- 完全等价：两条命令底层都调同一个 6 阶段流水线

**Q：`book.md` 在哪？**
A：`<project_dir>/book.md`。完整书稿（所有章节顺序合并）。

### 4.9 提示词管理

| 命令 | 用途 |
|---|---
| `novel prompt <name> --show` | 查看项目级提示词覆盖 |
| `novel prompt <name> --edit` | 用 `$EDITOR` 编辑 |
| `novel prompt <name> --reset` | 恢复默认（删项目副本）|

### 4.10 novel auto（底层入口，推荐用 novel write 替代）

**v0.12 起**：推荐用 §4.8 `novel write`，但 `novel auto` 仍然保留作为底层入口，行为与 v0.11 完全兼容。

```bash
novel auto [NAME] [OPTIONS]

一键全自动写小说：给定最小信息，跑完规划→写作→润色→一致性→导出。

必填：
  -t, --title TEXT       小说标题
  --theme TEXT           一句话主题

常用：
  -g, --genre TEXT       题材（默认 "现实 / 严肃文学"）
  -s, --style TEXT       文风（预设名或自由描述）
  -w, --words INTEGER    目标总字数（默认 30000）
  --chapters INTEGER     显式章节数（与 --words 二选一）
  --quality [draft|standard|premium]   质量档（默认 standard）
  --budget FLOAT         成本上限 CNY（0=不限）；超额自动降级
  --serve                启动后台 Web 仪表盘
  --serve-port INTEGER   仪表盘端口（默认 8765）

控制：
  --resume               强制续跑（默认自动检测 .novel/auto_state.json）
  --fresh                强制从头跑（覆盖旧进度）
  --dry-run              DRY_RUN 模式：不调 API

布局：
  --here                 就地初始化（跳过 NAME）
  --force                目标目录非空时仍执行

特殊：
  --plans-only           只跑规划阶段（生成 outline + 章纲），不进入写作
  --skip-plans           跳过规划阶段，直接进入写作（用现有 outline / chapter_plans）

示例：
  # 6 万字悬疑严肃向
  novel auto my_novel --title "冬夜的灰" --theme "..." \
    --genre 悬疑 --style 冷峻 --words 60000 --quality premium

  # 100 万字仙侠，预算 120
  novel auto xiuxian -t "凡人仙途" --theme "..." \
    --genre 修仙 -s 经典爽文 -w 1000000 \
    --quality premium --budget 120 --serve

  # 调试：只跑规划
  novel auto --title "..." --theme "..." --plans-only --dry-run

  # 续跑
  cd my_novel
  novel auto . -t "..." --theme "..." --words 60000
```

**质量档对比**：

| 档 | 章节迭代 | 字数容差 | AI 味阈值 | 雷达阈值 | 适合 |
|---|---|---|---|---|---|
| draft | 1 | ±30% | 跳过 | 跳过 | 网文冲量 |
| standard | 2 | ±20% | < 50 | ≥ 60 | 一般场景 |
| premium | 3 | ±10% | < 30 | ≥ 70 | 严肃向 |

**自动续跑**：每章写完即保存到 `.novel/auto_state.json`，Ctrl-C 后下次 `novel auto` 自动从中断处继续。

**失败兜底**：未达标的章节保留最后一次输出（占位草稿），可后续 `novel chapter N` 手动重写。

---

## 5. 常见工作流

### 5.1 短篇：30 分钟完成（v0.12+ 推荐）

```bash
# 一行就够：5 万字短篇
novel write short --title "我的短篇" --theme "一个夏天的故事" \
  --genre 现实 --style 朴素 --words 50000 \
  --quality premium --budget 10

# 想先看章纲再写？
novel write short --title X --genre 悬疑 --words 50000 --plans-only
# 看完 .novel/outline.md 觉得 OK 再跑：
novel write short --title X --genre 悬疑 --words 50000 --skip-plans --quality premium
```

旧版手动 `init + outline + chapter ×N` 在 v0.12+ 已不再推荐——除非你想手动覆盖某章。

### 5.2 长篇 1 周出 70%

**v0.12+ 推荐：一行跑长篇**

```bash
# 周一早上 9 点（开 4 worker + 启 Web 仪表盘后台监控）
novel write my_novel --title "百川归海" --theme "..." \
  --genre 都市 --style 冷峻 --words 600000 --chapters 120 \
  --quality standard --parallel 4 --serve --budget 80

# 撞 5h 配额时：自动等 + 心跳提示；Ctrl-C 安全退出；
# 下次再跑（ctrl-c 第二天）继续从第 N 章续写
```

**旧版手动 7 天工作流**（仍支持但不推荐）：

| 天 | 工作 | 命令（手动） |
|---|------|------|
| 周一 | 规划 | `outline / characters / world / volumes` |
| 周二-周四 | 写 1-25 章 | `novel chapter N` 循环 |
| 周五 | 检查 | `novel check / gaps / audit` |
| 周末 | 润色关键章 | `novel polish 1 --5 35 70` |

### 5.3 章节精修：与 LLM 来回协作

```bash
# 不满意第 5 章
novel chapter 5
novel chat 5 '对话太干瘪，加强心理戏'
novel chat 5 '加一段她在厨房洗碗的回忆'

# 末尾接场景
novel continue 5 --with '小红回到房间，发现一封信'

# 指定位置接场景
novel expand-scene 5 --after '她推开那扇门' --with '门后是陌生男人'
```

### 5.4 多本并行管理

```bash
# 同时管 3 本
novel list --path ~/novels
# ┏━━━━━━┳━━━━━━┳━━━━━━━━━━┓
# ┃ 标题 ┃ 题材 ┃ 字数目标 ┃
# ┡━━━━━━╇━━━━━━╇━━━━━━━━━━┡
# │ 灵瓶  │ 修仙 │ 200K     │
# │ 夜行  │ 悬疑 │ 100K     │
# │ 灰烬  │ 现实 │ 80K      │
# └──────┴──────┴──────────┘

# 快速进入某一本
cd $(novel info ~/novels/灵瓶 | grep 路径)
```

### 5.5 改编工作流（v0.12 推荐）

**端到端（一行）**：

```bash
novel write fanfic --from-source 白夜行.txt \
  --direction 换壳 --genre 校园 --style 冷峻 --words 80000 \
  --title "夜行"
```

走完流程：`extract_skeleton` → `adapt_novel` → 预填 `.novel/outline.md` → 6 阶段流水线 → `book.md`。

**逐步手动**（仅在你想看每步输出时）：

```bash
# 1. 提取骨架（dry-run 看效果）
novel adapt -i source.txt --direction 换名 --genre 校园 --style 冷峻 \
  --title 新名 --no-save --print > skeleton.md

# 2. 完整改编（保存到 .novel/adapt.md）
novel adapt -i source.txt --direction 换名 --genre 校园 --style 冷峻 \
  --title 新名

# 3. 用方案生成大纲
novel outline

# 4. 开始写
novel chapter 1
```

> 旧式 `novel adapt` 仅生成改编方案文档（不进入写作）。要端到端就用 `novel write --from-source`。

---

## 6. 故障排查

### 6.1 找不到项目目录

```
Error: 未找到 .novel 项目目录。
```

| 状况 | 解决 |
|------|------|
| 还没建项目 | `novel init <name>` |
| 已建项目 | `cd` 进入项目根目录（含 `.novel/` 的那层）|
| 想就地建 | `novel init . --here` |

### 6.2 API 调用失败

```
LLMError: api 401: ... invalid api key
```

```bash
novel config --api-key "your-real-key"
# 或
novel setup --force
```

### 6.3 章节空白 / think 截断

```
第 5 章字数 0 异常
```

```bash
# 自动检测 + 重写
novel retry-stuck --iters 2

# 手动重写
rm .novel/chapters/0005.md && novel chapter 5
```

### 6.4 think 残片污染

```
第 3 章包含未剥 think 标签
```

```bash
novel fix 3                # dry-run 检测
novel fix 3 --no-dry -y    # 一键删除并建议重写
```

### 6.5 跨章人物名漂移

```
novel check 发现：陈小军 vs 霍小军（0003 章用错名）
```

```bash
# 自动改
novel chat 3 '把"陈小军"全部改成"霍小军"'

# 或手工编辑冲突章节，统一用名
nano .novel/chapters/0003.md
```

### 6.6 长 prompt 超时

```
LLMError: chat failed after retries: timeout
```

```bash
REQUEST_TIMEOUT=300 novel chapter N   # 延长超时
TARGET_CHAPTER_WORDS=2000 novel chapter N  # 减小单章
```

### 6.7 novel write / auto 中途崩了

```bash
# 续跑：自动检测进度（state=None 会让 run_auto_novel 从 .novel/auto_state.json 加载）
cd my_novel
novel write . -t "..." --theme "..."  # 自动从中断处继续
# 或：
novel auto . -t "..." --theme "..."   # 等价（底层都调 run_auto_novel）
```

### 6.7a 撞到 minimax 配额限制（429 / "quota exceeded"）

v0.14+ 默认行为：**自动等到 quota 重置再继续**。

```bash
# 默认（推荐）：等 6 小时后自动续
novel write demo --title X --words 50000

# 不想等？加 --no-wait：撞配额立刻退出 + state 保存
novel write demo --title X --words 50000 --no-wait

# 等周配额？把上限调到 7 天
novel write demo --title X --words 50000 --max-wait-seconds 604800
```

如进程被 Ctrl-C 安全中断，state 已保存；下次 `novel write .` 自动从中断处继续（跳过已完成章节）。

### 6.8 仪表盘 / watch 看不到最新数据

仪表盘每 2 秒轮询，`status --watch` 同。手动：

```bash
cat .novel/auto_state.json | python3 -m json.tool
```

---

## 7. FAQ

### Q1：必须用 minimax 吗？

不是。任意 OpenAI Chat Completions 协议都行。改 `OPENAI_BASE_URL` + `OPENAI_MODEL`：

```bash
OPENAI_BASE_URL=https://api.openai.com/v1 OPENAI_MODEL=gpt-4o
OPENAI_BASE_URL=https://api.deepseek.com/v1 OPENAI_MODEL=deepseek-chat
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1 OPENAI_MODEL=qwen-long
```

### Q2：一章默认多少字？

3000 字（在 `.env` 中用 `TARGET_CHAPTER_WORDS` 配置）。模型会按目标字数的 75-95% 输出。

### Q3：怎么让小说更像某个作家？

```bash
# 方式 1：--style 致敬
novel init . --style "致敬汪曾祺《受戒》，短句、留白、淡墨"

# 方式 2：samples 目录放手写片段（推荐）
mkdir .novel/samples/
cat > .novel/samples/01.md << 'EOF'
（贴一段 200-1500 字的代表作品）
EOF
```

模型每章自动随机取 1-2 段作风格参考。

### Q4：怎么扩展 / 修改提示词？

1. **修改全局**：编辑 `prompts/<name>.md`，影响所有项目
2. **项目级覆盖**：`novel prompt <name> --edit`，写到 `.novel/prompts/<name>.md`，仅影响当前项目
3. **新增**：`prompts/<new>.md` + `novel/prompts.py` 加 `lru_cache` 加载函数

### Q5：项目数据能 git 追踪吗？

可以！但要加 `.gitignore`：

```gitignore
.env
.novel/chapters/   # 可选，体积大
.novel/history/    # 可选
.novel/auto_state.json  # 可选，含进度可重建
```

推荐追踪：`.novel/outline.md` / `.novel/characters.md` / `.novel/style.md` / `.novel/project.yaml` / `.novel/chapter_plans/`

### Q6：能写英文小说吗？

可以，但 `prompts/de_ai_flavour.md` 默认针对中文。改提示词 + 用英文模型（gpt-4o、claude-3-5-sonnet）。

### Q7：怎么减少 API 费用？

| 方法 | 节省 |
|---|---|
| `DRY_RUN=true` 调试 | 100%（不调 API） |
| 减小 `TARGET_CHAPTER_WORDS` 到 2000 | 33% |
| 用便宜模型（deepseek-chat） | 80%+ |
| `--quality draft` | 50%（单轮） |
| 跳过审稿 `--no-polish` | 33% |
| `--budget N` 限成本 | 超额自动降级 |

### Q8：能多人协作吗？

可以，git 协作：

- 把项目根目录推到 GitHub
- 每人本地一个 `.env`
- 章节是纯文本，可 diff / merge
- `save_chapter` 自动备份到 `history/` 防误覆盖

### Q9：能写剧本 / 漫画脚本吗？

可以，需改提示词：

1. 复制 `prompts/chapter.md` 为 `prompts/script.md`
2. 修改输出格式要求
3. 加 `novel script` 命令调用新的 `build_script_messages`

### Q10：auto 命令如何做到几小时两轮？

| 选项 | 答案 |
|---|---|
| 100 万字 | 8-15 小时 |
| 50 万字 | 4-7 小时 |
| 20 万字 | 1-3 小时 |
| 5 万字 | 10-30 分钟 |

成本：

| 档 | 100 万字 |
|---|---|
| draft | ¥5-15 |
| standard | ¥30-50 |
| premium | ¥80-150 |

---

## 附录：命令速查（47 个）

### 基础（11）
```
init          # 建项目
setup         # 首次配置向导
config        # 改 config
status        # 看项目状态（含 --watch / --auto）
version       # 看版本
doctor        # 诊断（含 --fix --json）
list          # 列目录下项目
info <name>   # 看单项目
whereami      # 当前所在项目
templates     # 推荐模板
serve         # Web 仪表盘
```

### 规划（7）
```
outline       # 全书大纲
characters    # 人物志
world         # 世界观
volumes       # 长篇分卷
plan N        # 细化第 N 章
plan-all      # 批量生成所有章纲
plans [N]     # 查看 / 列出章纲（--refresh 重生成）
```

### 写作（10）
```
chapter N     # 写第 N 章
write -s S -e E   # 连续写 S-E 章
sprint        # 从末尾自动写多章
continue N    # 末尾接写
chat N '...'  # 自然语言改
expand-scene N  # 指定位置接场景
auto ...      # 一键全自动（见 §4.9）
webnovel-pack NAME  # 一键网文项目
adapt         # 改编
fanfic        # 同人 / 后传
```

### 润色（4）
```
polish N      # 润色
detect N      # AI 味检测
radar N       # 风格雷达
batch <act>   # 批量处理
```

### 一致性（10）
```
state         # 故事状态（最近 3 章）
rolling       # 滚动摘要（每 5 章）
foreshadow    # 伏笔簿
arc           # 人物弧线
timeline      # 时间线
check         # 一致性检查
volume-report # 卷末报告
title N       # 章节标题
gaps          # 伏笔状态
index         # 全书索引
```

### 版本与导出（7）
```
history       # 历史版本
diff N        # 对比两版
rollback N    # 回滚
retry-stuck   # 重写残片
audit         # 综合审计
export        # 导出书稿
prompt        # 提示词管理（--show --edit --reset）
```

### 题材 / 文风（4）
```
genres            # 10 个严肃向题材
styles            # 11 个文风
webnovel-genres   # 8 个网文题材
webnovel-styles   # 9 个爽感文风
```

---

## 相关文档

- [REQUIREMENTS.md](REQUIREMENTS.md) · 需求规格
- [DESIGN.md](DESIGN.md) · 设计文档（含 30+ mermaid）
- [BEST_PRACTICES.md](BEST_PRACTICES.md) · 最佳实践（题材搭配、降 AI 味、成本配方）
- [PROGRESS.md](../PROGRESS.md) · 演进日志
- [CHANGELOG.md](../CHANGELOG.md) · 版本变更日志
- [CONTRIBUTING.md](../CONTRIBUTING.md) · 贡献指南
### 4.13 后台长跑：`novel daemon`（v0.15+）

单次 `novel write` 跑完只保证「能写出来」，未必满足你的所有要求。`novel daemon` 是**后台长跑循环**：每轮跑完 6 阶段，让 LLM 评一遍你写的硬指标，不达标就把问题反馈给下一轮再跑。

#### 写一份硬指标（`quality_criteria.md`）

```markdown
# 硬指标
- 第三章不能出现内心独白
- 全书 AI 味指数均值 < 40
- 5 个核心人物姓名不能有别名
- 每章 ≥ 2500 字
- 情节无前后矛盾
- 主角在最后一章必须明确选择
```

每行一条，支持 `- text` / `* text` / `1. text` 三种列表标记。空行 / 标题行 / 代码块内的行会被忽略。

#### 跑 daemon

```bash
# 标准用法：3 章 + 硬指标，最多 3 轮
novel daemon run my_novel --criteria ./quality_criteria.md

# 长跑大项目：开 Web 仪表盘后台监控
novel daemon run my_novel --criteria ./criteria.md \
  --max-iterations 5 --cost-budget 30 --serve

# 重置（从头开始，重新评估）
novel daemon run my_novel --criteria ./criteria.md --force
```

#### 终止条件（OR，任一满足即退）

- LLM 评估后所有 criteria 全 pass（达到要求）
- `iteration_count >= max_iterations`（默认 3）
- `cumulative_cost_cny >= cost_budget`（默认不限）
- `elapsed >= max_time_seconds`（默认不限）
- 用户写 `.novel/stop_daemon` 文件（`novel daemon stop` 一键写）
- SIGINT / SIGTERM（Ctrl-C / systemd stop）

#### 状态查看

```bash
# 终端看
novel daemon status

# 看具体某轮评估了什么
cat .novel/auto_state.json | python3 -m json.tool | grep last_criteria_report
```

#### 优雅停止

```bash
# 终端：写 .novel/stop_daemon，下一轮 check 时退出
novel daemon stop

# 立刻退出：Ctrl-C（state 已保存）
```

#### 部署为 systemd 服务（生产用法）

```bash
# 生成 unit file
novel daemon unit --user ubuntu --project /home/ubuntu/my_novel > novel.service

# root 权限安装
sudo cp novel.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now novel-my_novel.service
sudo journalctl -u novel-my_novel.service -f
```

#### 反馈注入机制

每轮跑完 6 阶段 → LLM 评估 `quality_criteria.md` → 拿 `top_priority_fixes`（如「修第 3 章、扩第 5 章」）→ 反馈格式化成文本，注入到下一轮每章的 prompt 的「## 作者额外要求」段 → LLM 看到问题后改进。

#### FAQ

**Q：daemon 跑完后我应该看哪里？**
A：`.novel/auto_state.json` 里 `iteration_count` / `last_iter_passed` / `last_criteria_report` 三个字段全 pass 即可。

**Q：`--max-iterations 3` 全 fail 怎么办？**
A：3 轮还没达标说明 criteria 描述可能太严或 LLM 短时间改不了。作者可调 criteria 后重跑（`--force`），或降低质量目标（用 `standard` 档替代 `premium`）。

**Q：怎么知道 daemon 在跑？**
A：`novel serve` + Web 仪表盘看 `state.iteration_count` 实时更新；或 `ps aux | grep daemon`。

**Q：daemon 和 `novel serve` 什么关系？**
A：`novel daemon run --serve` 会同时起 Web 仪表盘后台线程；`novel serve` 单独用则只跑仪表盘（不写小说）。
