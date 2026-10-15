# novel-writer · AI 写小说 CLI

> 基于大模型（默认 `minimax-Text-01` / `minimax-M3`，兼容 OpenAI Chat Completions 协议）的小说自动创作工具。
> 核心目标：把大纲、主题、人物、字数、文风交给程序，让它自己出稿，并通过多轮审稿与润色，最大程度减少 AI 味。

[![CI](https://img.shields.io/badge/CI-passing-brightgreen)](.github/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)
[![Version](https://img.shields.io/badge/version-0.11.0-orange)](pyproject.toml)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-111%20passed-brightgreen)](tests/)

## 📚 文档

| 文档 | 读者 | 内容 |
|------|------|------|
| [📘 REQUIREMENTS.md](docs/REQUIREMENTS.md) | PM / 架构师 | 需求规格（46 功能 / 6 非功能 / 7 验收标准） |
| [📐 DESIGN.md](docs/DESIGN.md) | 开发者 | 架构图 / 数据流图 / 关键模块设计（**30+ mermaid**） |
| [📗 USER_MANUAL.md](docs/USER_MANUAL.md) | 作者 | 安装 / 教程 / 命令详解 / 故障排查 |
| [📙 BEST_PRACTICES.md](docs/BEST_PRACTICES.md) | 作者 | 题材搭配 / 降 AI 味 / 实战配方 / 避坑清单 |
| [📕 文档索引](docs/README.md) | 所有人 | 按角色分类的文档地图 |

**新作者**：先读 [USER_MANUAL.md](docs/USER_MANUAL.md) § 1-3（5 分钟上手 + 4 个教程）。

**贡献者**：先读 [CONTRIBUTING.md](CONTRIBUTING.md) + [DESIGN.md](docs/DESIGN.md) § 1-2。

## ✨ 特性速览

| 特性 | 说明 |
|------|------|
| **47 个命令** | 覆盖 init / 写作 / 一致性 / 润色 / 改编 / 网文 + 一键全自动 + Web 仪表盘 |
| **真实长篇工作流** | 已实测 50K 字长篇（7 章自动维护 state/foreadow/arc/timeline/title） |
| **题材/文风预设** | 严肃向 10 题材 + 11 文风；网文专项 8 题材 + 9 爽感文风 |
| **minimax 适配** | 处理 `<think>` 标签三层兜底 + chat_with_continuation 自动续写 |
| **去 AI 味道** | 6 维度风格雷达（与 samples 相似度 86+） |
| **跨章一致性** | 自动检测人物名 / 时间 / 地点 / 设定漂移 |
| **改编 / 同人** | `novel adapt` / `novel fanfic` —— 基于源小说换名 / 换壳 / 后传 / 反派视角 |
| **可移植** | 兼容 OpenAI / minimax / 智谱 / DeepSeek / 通义千问 |
| **DRY_RUN 模式** | 不调 API 完整打印提示词，方便调试提示词 |

---

## 📦 5 分钟上手

### 1. 安装

```bash
git clone <repo> ai-novel && cd ai-novel
pip install -e .
```

或直接：

```bash
pip install -r requirements.txt
```

### 2. 配置 API（交互式）

```bash
novel setup
```

按提示输入：
- API base URL（默认 `https://api.minimaxi.com/v1`）
- API key
- 模型名（默认 `minimax-Text-01`，推荐 `minimax-M3` 推理模型）
- temperature（默认 `0.9`，0.7 稳 / 0.95 放飞）
- 目标章节字数（默认 3000）
- 是否开启 DRY_RUN

完成后会在当前目录生成 `.env`。非交互模式：`novel setup --no-input`。

跳过向导，手动复制 `.env.example` 为 `.env` 也可。

### 3. 写你的第一本书

```bash
novel init my_novel \
  --title "冬夜的灰" \
  --theme "1995 年东北小镇的命案与四个孩子" \
  --genre 悬疑 \
  --style 冷峻 \
  --words 60000

cd my_novel

# 规划阶段
novel outline
novel characters
novel world
novel volumes

# 写作阶段
novel chapter 1
novel write --start 2 --end 5
novel sprint --count 10         # 自动从最后一章后写 10 章

# 润色 / 检查
novel polish 1
novel detect 1 --save
novel doctor                    # 诊断项目状态（可加 --fix 自动修复）
novel status
```

---

## 📚 命令一览（47 个）

### 🚀 一键（1 个）

| 命令 | 说明 |
|---|---|
| `novel auto -t TITLE --theme T` | 一键全自动：最小信息 → 规划→逐章→润色→一致性→导出 |

### 🛠 基础（5 个）

| 命令 | 说明 |
|------|------|
| `novel setup` | 首次配置向导，交互式生成 `.env`（`--no-input` 非交互；`--force` 覆盖） |
| `novel config` | 查看或修改全局配置（API key / base_url / model / DRY_RUN） |
| `novel init <name>` | 初始化新项目（`--title --theme --genre --style --words --template`） |
| `novel status` | 查看当前项目状态（路径 / 字数 / 元数据 / 章节列表） |
| `novel version` | 显示版本号与运行环境（`--short` 只输出版本号；亦可 `--version` / `-V`） |
| `novel doctor` | 自动诊断项目（`--fix` 自动修复；`--json` 机器可读） |

### 📝 规划（5 个）

| 命令 | 说明 |
|------|------|
| `novel outline` | 生成或重写全书大纲（`--genre --words --extra --save/--print`） |
| `novel characters` | 基于大纲生成或扩展人物志（`--extra`） |
| `novel world` | 生成世界观（地理 / 历史 / 硬规则） |
| `novel volumes` | 长篇分卷（5 卷结构 + 起止章节） |
| `novel plan <N>` | 细化第 N 章大纲（200-400 字场景规划） |

### ✍️ 写作（8 个）

| 命令 | 说明 |
|------|------|
| `novel chapter <N>` | 写第 N 章（写完自动维护 state/foreadow/arc/title） |
| `novel write -s 1 -e 5` | 连续写 1-5 章 |
| `novel sprint --count 10` | 自动从最后一章后写 10 章 |
| `novel continue <N> --with '意图'` | 在第 N 章末尾接写一段 |
| `novel chat <N> '指令'` | 自然语言协作修改某章 |
| `novel expand-scene <N>` | 在指定句子后接一段场景 |
| `novel webnovel-pack <name>` | 一键建网文项目（建项目 + 选题材 + 选爽文 + 黄金三章骨架） |
| `novel adapt` | 改编源小说（`--source --direction --genre --style --with-skeleton`） |
| `novel fanfic` | 写后传 / 番外 / 同人（`--char --era --as-chapter`） |

> **说明**：写作类共 9 个（含 adapt / fanfic / webnovel-pack 这三个 v1 工作流入口）。

### 🎨 润色 / 质控（4 个）

| 命令 | 说明 |
|------|------|
| `novel polish <N>` | 去 AI 味润色（基于 detect+review 反馈） |
| `novel detect <N>` | 检测 AI 味（`--save` 存报告） |
| `novel radar <N>` | 风格雷达：6 维度量化与 samples 相似度 |
| `novel batch <action>` | 批量执行 polish / detect / radar / title（`--start --end --skip-empty`） |

### 🔍 一致性 / 长篇机制（14 个）

| 命令 | 说明 |
|------|------|
| `novel timeline` | 维护故事内时间线（含冲突预警） |
| `novel state` | 维护故事状态摘要（最近 3 章压缩） |
| `novel rolling` | 手动刷新全书滚动摘要（每 5 章自动） |
| `novel foreshadow` | 维护伏笔簿（F1-Fn 编号） |
| `novel arc` | 维护人物弧线（`--char NAME --only`） |
| `novel check` | 跨章节一致性检查（`--lookback N`） |
| `novel volume-report -v N` | 第 N 卷卷末报告 |
| `novel title <N>` | 为第 N 章生成标题（`--force` 重生成） |
| `novel history` | 查看所有章节版本历史 |
| `novel diff <N>` | 对比任意两版章节（`--from --to --stats --context`） |
| `novel rollback <N> --to v1` | 回滚章节到历史版本（`--list --yes`，回滚前会显示 diff 摘要） |
| `novel fix <N>` | 检测异常章节（`--dry/--no-dry --yes`） |
| `novel retry-stuck` | 自动重写 0 字节 / 残片章节（`--threshold --dry --iters`） |
| `novel audit` | 全项目综合审计（章节 / 字数 / AI 味 / 雷达） |

### 📊 查询 / 工具（5 个）

| 命令 | 说明 |
|------|------|
| `novel status` | 项目状态（章节 + 字数 + 元数据） |
| `novel progress` | 长篇写作进度（章节 / 字数 / 当前卷 / 预计剩余时间） |
| `novel index` | 全书索引表（章节 / 标题 / 字数 / 状态） |
| `novel gaps` | 伏笔状态表（未回收 / 待回收 / 已到章节） |
| `novel export` | 合并所有章节为单一书稿（`--format md/txt --output`） |

### 🎭 题材 / 文风查询（5 个）

| 命令 | 说明 |
|------|------|
| `novel genres` | 列出严肃向 10 个题材 |
| `novel styles` | 列出 11 个文风 |
| `novel templates` | 列出 10 个推荐模板（题材+文风+字数一键组合，`novel init --template` 调用） |
| `novel webnovel-genres` | 列出网文专项 8 个题材 |
| `novel webnovel-styles` | 列出网文爽感 9 个文风 |
| `novel prompt <name>` | 查看 / 编辑 / 恢复项目级提示词（`--show --edit --reset`） |

---

## 🎯 核心设计哲学

### 1. 提示词即产品

所有生成质量都来自提示词。提示词以独立 markdown 文件存在 `prompts/` 目录（共 28 个），
作者可以直接修改、版本化、对比。

### 2. 减法优于加法

AI 小说最致命的味道是过度正确：太顺、太圆、太会总结。
我们用 6.4K 的 `de_ai_flavour.md` 列出 20+ 条禁用表达，加上作家风格参考，
让模型有具体模仿对象（老舍 / 双雪涛 / 汪曾祺 / 余华等）。

### 3. 多轮迭代

每章写作流程：**生成 → 检测 → 审稿 → 润色 → 重写**。
审稿报告和检测报告作为下一轮 prompt 的输入。

### 4. 长篇需要长期记忆

模型上下文窗口有限。长篇写作必须解决：
跨章人物名漂移、时间线漂移、设定漂移、伏笔追踪、人物弧线追踪、节奏管理。

---

## 🛡 长篇小说工作流

项目初始化后推荐顺序：

```bash
novel outline         # 1. 大纲（20 万字 → 约 60-70 章）
novel characters      # 2. 人物志
novel world           # 3. 世界观（地理 / 历史 / 硬规则）
novel volumes         # 4. 长篇分卷（每卷核心冲突、节奏、卷末状态）
novel chapter 5 6 7   # 5. 逐章写（每章自动维护元数据）
novel write -s 10 -e 15  # 6. 连续写
```

每章写完会自动维护 `state.md` / `foreshadowing.md` / `arcs/_overview.md` / `titles.json` / `timeline.md` / `volumes.md`。

关键操作：

```bash
novel timeline        # 维护时间线（自动检测冲突）
novel check          # 跨章节一致性检查
novel volume-report --volume 2  # 第 2 卷卷末报告
novel doctor --fix   # 一键体检 + 自动修复占位文件
```

---

## 🎨 题材 / 文风系统

### 严肃向（10 + 11）

| 题材（10） | 文风（11） |
|----------|----------|
| 玄幻 / 仙侠 / 科幻 / 悬疑 / 言情 / 历史 / 武侠 / 都市 / 校园 / 现实 | 搞笑 / 轻松 / 伤感 / 诗意 / 冷峻 / 热烈 / 朴素 / 华丽 / 紧张 / 黑色幽默 / 儿童 |

### 网文专项（8 + 9）

| 网文题材（8） | 爽感文风（9） |
|------------|------------|
| 修仙 / 玄幻 / 都市 / 异能 / 科幻 / 军事 / 悬疑 / 校园 / 历史 | 经典爽文 / 反转爽文 / 黑化爽文 / 轻松搞笑 / 热血燃 / 虐恋 / 系统流 / 无限流 / 签到流 |

每个预设都自动注入：
- **硬规则**：题材 / 文风的语言特征、写作时注意
- **作家参考**：建议模仿的具体作家和作品
- **踩坑预警**：容易翻车的写法

使用示例：

```bash
# 严肃文学
novel init my_book --genre 悬疑 --style 冷峻

# 推荐模板（一键套用预设题材 + 文风 + 字数）
novel templates                          # 看 10 个模板列表
novel init demo --template 东北悬疑 --title '盘锦往事'  # 默认 80K 冷峻
novel init demo --template 网文经典 --words 1000000     # 部分覆盖模板字数

# 网文项目（推荐）
novel webnovel-pack cultivation_novel \
  --title "凡人修仙传之xxx" \
  --theme "凡人逆袭成仙" \
  --genre 修仙 --style 经典爽文 \
  --idea "金手指：残破玉佩"

# 模糊匹配
novel init x --style "冷"      # 自动匹配"冷峻"
```

---

## 🌐 模型适配

兼容任意 OpenAI Chat Completions 协议 API：

| 模型 | 推荐场景 | 说明 |
|------|---------|------|
| `minimax-Text-01` | 通用 | 默认 |
| `minimax-M3` | 长推理 + 创作 | 处理 `<think>` 标签 |
| `gpt-4` / `gpt-4o` | 英文质量高 | OpenAI |
| `deepseek-chat` | 性价比 | DeepSeek |
| `glm-4` / `qwen-long` | 中文支持 | 智谱 / 通义 |

切换模型：

```bash
novel config --base-url https://api.openai.com/v1 --model gpt-4o --api-key sk-xxx
```

或在 `.env` 中修改：

```env
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o
OPENAI_API_KEY=sk-xxx
```

---

## 🔧 DRY_RUN 模式

DRY_RUN 模式不真调用 API，把将发送给模型的提示词完整打印到终端。
用来调提示词或者学习怎么写提示词非常方便。

```bash
DRY_RUN=true novel outline
DRY_RUN=true novel chapter 1 --iters 1 --no-polish
```

或 `novel setup` 启动向导中选择 DRY_RUN。

---

## 📁 项目目录结构

```
my_novel/
├── .env                  # 项目级环境变量（可选，覆盖全局）
├── .novel/
│   ├── project.yaml      # 元数据（title / theme / genre / style_preset）
│   ├── outline.md        # 全书大纲
│   ├── characters.md     # 人物志
│   ├── style.md          # 文风（含 genre/style preset 自动注入）
│   ├── genre_preset.md   # 当前题材硬规则
│   ├── world.md          # 世界观
│   ├── volumes.md        # 分卷
│   ├── timeline.md       # 故事内时间线
│   ├── state.md          # 状态摘要（最近 3 章压缩）
│   ├── rolling_summary.md  # 全书滚动摘要
│   ├── foreshadowing.md  # 伏笔簿
│   ├── arcs/
│   │   └── _overview.md  # 人物弧线总览
│   ├── chapters/
│   │   ├── 0001.md
│   │   ├── 0002.md
│   │   └── ...
│   ├── history/          # 旧版本（save_chapter 自动备份）
│   ├── reports/          # AI 味检测、风格雷达报告
│   ├── chapter_plans/    # 细化大纲
│   ├── prompts/          # 项目级提示词覆盖（novel prompt --edit）
│   └── samples/          # 作者手写风格样本（few-shot）
└── book.md               # novel export 输出
```

---

## 📂 风格样本（few-shot）

`.novel/samples/` 目录里放 1-3 个 `.md` 文件，每个文件 200-1500 字。
模型会在写每章时自动随机抽 1-2 段作为风格参考。

文件命名建议用数字（`01.md`、`02.md`），方便排序。

---

## 🔌 进阶：作为库使用

```python
from novel import __version__
from novel.config import GlobalConfig
from novel.llm import LLMClient, Message
from novel import prompts as P

cfg = GlobalConfig()  # 读 .env
client = LLMClient(cfg)

ctx = P.ChapterContext(
    title="我的小说",
    outline="...",
    characters="...",
    style="...",
    chapter_plan="第 1 章 困境",
    prev_chapter_tail="",
    target_words=3000,
)
msgs = P.build_chapter_messages(ctx)
result = client.chat(msgs, temperature=0.95)
print(result.content)
```

---

## 🧪 进阶：作为 Web 服务

安装 web 扩展：

```bash
pip install -e ".[web]"
```

`[web]` 依赖：fastapi + uvicorn。（FastAPI 路由尚未实现，见路线图）

---

## ❓ 常见问题

**Q：必须用 minimax 吗？**
不是。任意兼容 OpenAI Chat Completions 协议的 API 都能用。改 `OPENAI_BASE_URL` 和 `OPENAI_MODEL` 即可。

**Q：怎么让小说更像某个作家？**
`novel init --style "致敬汪曾祺的《受戒》"`，或编辑 `.novel/style.md`。

**Q：一章默认生成多少字？**
默认 3000 字（在 `.env` 中通过 `TARGET_CHAPTER_WORDS` 配置）。
模型会按目标字数的 75% 到 95% 输出，宁可少写不灌水。

**Q：怎么扩展提示词？**
在 `prompts/` 目录添加新的 `.md` 文件，然后在 `novel/prompts.py` 里加一个 `lru_cache` 加载函数。

**Q：怎么诊断项目状态？**
`novel doctor`（可加 `--fix` 自动修复占位文件、`--json` 机器可读）。

**Q：如何参与开发？**
参见 [CONTRIBUTING.md](CONTRIBUTING.md)；提交 PR 前跑 `pytest tests/` 和 `ruff check`。

---

## 🗺 路线图

### 已完成（v0.1 - v0.11）
- v0.1 短篇工具 → v0.2 长篇工作流 → v0.3 提示词专精
- v0.4 示例项目 → v0.5 交互式能力 → v0.6 工具化
- v0.7 写作流增强 → v0.8 实用工具集 → v0.9 输出与追踪
- v0.10 题材/文风系统 → v0.11 改编工作流（adapt / fanfic / webnovel-pack）

### 中期
- OpenViking 集成：minimax 长期记忆库，跨项目复用人物/伏笔
- REPL 模式：每章写作时进入作者+AI 多轮对话
- 多模型协作：强模型审稿、快模型润色
- FastAPI Web 服务
- TUI 模式：终端图形界面

### 长期
- 人物关系图（自动生成人物）
- 时间线拖拽（自动写章节）
- 多项目批量管理
- 出版级别长篇自动产出

详见 [PROGRESS.md](PROGRESS.md) 的完整决策日志。

---

## 🤝 贡献

欢迎 PR 与反馈。提 PR 前请：

```bash
pytest tests/              # 全过
ruff check novel/ novel_cli.py tests/  # 无 lint 错误
```

详细规范见 [CONTRIBUTING.md](CONTRIBUTING.md)（待补充）。

## 📄 许可证

MIT