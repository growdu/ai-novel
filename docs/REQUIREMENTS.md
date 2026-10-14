# 需求文档（Requirements）

novel-writer v0.11 的完整需求规格说明。

---

## 1. 项目目标

### 1.1 一句话定义

novel-writer 是一个 **AI 辅助长篇小说创作 CLI 工具**，通过结构化提示词工程和多轮审稿机制，让 LLM 写出的中文长篇最大程度地接近人类作家的水准。

### 1.2 核心目标

| 优先级 | 目标 | 衡量 |
|--------|------|------|
| P0 | 把作者从机械性写作中解放 | 1 本 20 万字长篇可在 1 周内出 70% 草稿 |
| P0 | 最大程度降低 AI 痕迹 | 风格雷达相似度 ≥ 90 |
| P0 | 跨章一致性 | 人物名 / 时间 / 地点零错误 |
| P1 | 兼容任意 OpenAI 协议 LLM | 支持 minimax / OpenAI / DeepSeek / 通义 |
| P1 | 长篇长期记忆 | 自动维护 state / foreshadow / arc |
| P2 | 改编 / 同人能力 | 适配高热度小说 |
| P2 | 网文专项 | 黄金三章 + 升级爽点节奏 |

### 1.3 非目标（明确不做）

| 不做 | 原因 |
|------|------|
| 替代作者 | 工具不替代作者，是放大作者能力 |
| 自动出版 | 出版涉及法律 / 编辑 / 校对，超出范围 |
| 多模态（配图） | 聚焦文字创作 |
| Web UI | v0.11 仍以 CLI 为核心（Web 服务见路线图） |

---

## 2. 用户画像

### 2.1 主要用户：长篇小说作者

```
人物：李雪，30 岁，自由撰稿人
工作流：
  - 周末有空写小说，平时做短视频脚本
  - 已有大纲、人物、世界观，但没时间逐章写
  - 用过大语言模型直接写，但 AI 味太重、自己改比写还累
痛点：
  - 写 5 章后人名开始漂移
  - 模型给的文字"顺但空"，缺乏血肉
  - 一次跑几千字后回头改要花 3 倍时间
  - 网文需要稳定的爽点节奏，自己写不来
目标：
  - 用工具出 70% 草稿，自己改 30%
  - 跨章一致性自动维持，省下检查时间
  - 致敬某个作家的文风（汪曾祺、双雪涛等）
```

### 2.2 次要用户：网文作者

```
人物：王大锤，28 岁，兼职网文作者
工作流：
  - 日更 4000 字，靠订阅吃饭
  - 多书矩阵：同时写 2-3 本
  - 网文有自己的"黄金三章"、"爽点流"、"升级流"等套路
痛点：
  - 一天写 4000 字手酸
  - 节奏容易拖，需要稳定的爽点
  - 同时多本，人物容易混
目标：
  - 一键生成黄金三章框架
  - 自动匹配网文题材 + 爽感文风预设
  - 多本同时管理不混
```

### 2.3 三级用户：剧本 / 同人 / 改编作者

```
人物：陈词，35 岁，编剧
工作流：
  - 想把一部高热度小说改编成另一个题材
  - 比如《白夜行》→ 校园 + 冷峻的《夜行》
  - 或者写个后传、番外
痛点：
  - 直接改编会被原作风味带着走
  - 提取骨架手动做太慢
目标：
  - 一键提取源小说骨架
  - 按方向（换名/换壳/后传/反派视角）生成改编方案
```

---

## 3. 功能性需求

### 3.1 项目管理

| 编号 | 需求 | 命令 |
|------|------|------|
| F-PM-1 | 初始化小说项目（标题/主题/题材/文风/字数） | `novel init` |
| F-PM-2 | 查看项目状态（章节/字数/元数据） | `novel status` |
| F-PM-3 | 自动诊断项目完整性 | `novel doctor [--fix --json]` |
| F-PM-4 | 浏览多个项目 | `novel list / info / whereami` |
| F-PM-5 | 一键网文项目初始化 | `novel webnovel-pack` |

### 3.2 写作流程

| 编号 | 需求 | 命令 |
|------|------|------|
| F-W-1 | 生成大纲 | `novel outline` |
| F-W-2 | 生成人物志 | `novel characters` |
| F-W-3 | 生成世界观 | `novel world` |
| F-W-4 | 长篇分卷 | `novel volumes` |
| F-W-5 | 写一章（多轮迭代） | `novel chapter N` |
| F-W-6 | 连续写多章 | `novel write / sprint` |
| F-W-7 | 章节末尾接写 | `novel continue` |
| F-W-8 | 自然语言协作修改 | `novel chat` |
| F-W-9 | 指定位置接场景 | `novel expand-scene` |
| F-W-10 | 细化单章大纲 | `novel plan` |

### 3.3 长篇一致性（关键）

| 编号 | 需求 | 命令 |
|------|------|------|
| F-LC-1 | 故事状态摘要（最近 3 章压缩） | `novel state`（自动） |
| F-LC-2 | 滚动摘要（每 5 章） | `novel rolling`（自动） |
| F-LC-3 | 伏笔簿（F1-Fn 编号） | `novel foreshadow`（自动） |
| F-LC-4 | 人物弧线 | `novel arc`（自动） |
| F-LC-5 | 时间线 | `novel timeline`（自动） |
| F-LC-6 | 跨章一致性检查 | `novel check` |
| F-LC-7 | 卷末报告 | `novel volume-report` |
| F-LC-8 | 章节标题 | `novel title` |
| F-LC-9 | 伏笔状态表 | `novel gaps` |

### 3.4 润色与质控

| 编号 | 需求 | 命令 |
|------|------|------|
| F-Q-1 | AI 味检测 | `novel detect [--save]` |
| F-Q-2 | 风格雷达（6 维度量化） | `novel radar` |
| F-Q-3 | 基于反馈润色 | `novel polish` |
| F-Q-4 | 批量处理 | `novel batch [polish/detect/radar/title]` |

### 3.5 版本与导出

| 编号 | 需求 | 命令 |
|------|------|------|
| F-V-1 | 自动版本备份 | `save_chapter` 内置 |
| F-V-2 | 查看历史版本 | `novel history` |
| F-V-3 | 对比任意两版 | `novel diff` |
| F-V-4 | 回滚到历史版本 | `novel rollback --to vN` |
| F-V-5 | 修复异常章节 | `novel fix` |
| F-V-6 | 自动重写残片章节 | `novel retry-stuck` |
| F-V-7 | 全项目审计 | `novel audit` |
| F-V-8 | 合并为书稿 | `novel export` |
| F-V-9 | 全书索引 | `novel index` |

### 3.6 改编 / 同人

| 编号 | 需求 | 命令 |
|------|------|------|
| F-A-1 | 基于源小说改编 | `novel adapt` |
| F-A-2 | 写后传 / 番外 / 同人 | `novel fanfic` |
| F-A-3 | 提取源小说骨架 | `extract_skeleton`（内部） |

### 3.7 配置与查询

| 编号 | 需求 | 命令 |
|------|------|------|
| F-C-1 | 全局配置 | `novel config` |
| F-C-2 | 首次配置向导 | `novel setup` |
| F-C-3 | 题材 / 文风查询 | `novel genres / styles / webnovel-genres / webnovel-styles` |
| F-C-4 | 模板推荐 | `novel templates` |
| F-C-5 | 提示词查看 / 编辑 | `novel prompt [--show --edit --reset]` |
| F-C-6 | 版本查询 | `novel --version / version` |

---

## 4. 非功能性需求

### 4.1 兼容性

| 项 | 要求 |
|---|---|
| Python | 3.10+ |
| LLM API | OpenAI Chat Completions 兼容协议 |
| 操作系统 | Linux / macOS / Windows |
| 安装 | `pip install -e ".[dev]"` |
| 字符编码 | UTF-8 全程 |

### 4.2 性能

| 项 | 要求 | 实测 |
|---|---|---|
| 单章生成 | 30 秒 - 5 分钟 | ~1-2 分钟 |
| 10 章 sprint | < 30 分钟 | ~15-25 分钟 |
| 工具命令（doctor / status / list） | < 2 秒 | < 1 秒 |
| DRY_RUN 模式 | 不调 API | < 0.5 秒 |

### 4.3 可靠性

| 项 | 要求 |
|---|---|
| API 失败自动重试 | 3 次指数退避 |
| 章节空内容自动重试 | 2 次 |
| think 标签残片 | 三层兜底剥离 |
| 文件损坏（0 字节） | `retry-stuck` 自动重写 |
| 损坏项目检测 | `doctor --fix` 自动恢复 |

### 4.4 可观测性

| 项 | 实现 |
|---|---|
| 写一章 token 用量 | 写入 .novel/.cache/usage.json |
| 错误日志 | rich console 红字 + traceback |
| 进度条 | rich progress（sprint / write） |

### 4.5 可移植性

| 项 | 要求 |
|---|---|
| 模型切换 | `OPENAI_BASE_URL` + `OPENAI_MODEL` 环境变量 |
| 数据迁移 | 项目目录纯文件，可 git 追踪 |
| 单文件备份 | `export` 输出 book.md/book.txt |

### 4.6 可维护性

| 项 | 实现 |
|---|---|
| 单测覆盖 | 关键模块 ≥ 80% |
| Lint | ruff (F-class 0 错) |
| CI | GitHub Actions 3 矩阵 |
| 提示词外置 | prompts/*.md 用户可改 |
| 版本备份 | `history/` 自动维护 |

### 4.7 可扩展性

| 项 | 实现 |
|---|---|
| 新增题材 / 文风 | prompts/genre_presets.md + style_presets.md |
| 新增命令 | novel_cli.py 加 @app.command() |
| 新增提示词 | prompts/<name>.md + prompts.py 加 lru_cache 加载 |
| 替换 LLM | 任意 OpenAI 协议 |

---

## 5. 约束

### 5.1 LLM 限制

| 约束 | 说明 |
|---|---|
| 上下文窗口 | 长 prompt 限制（实测 ~20K tokens） |
| 推理模型 think 标签 | 60-90% tokens 被 think 消耗 |
| max_tokens 限制 | 影响单章字数上限 |
| 联网需求 | 必须（除非 DRY_RUN） |
| 计费模型 | 用户自行承担 API 成本 |

### 5.2 文件约束

| 约束 | 说明 |
|---|---|
| 项目根 | 包含 `.novel/` 目录的路径 |
| 文件命名 | 章节 `0001.md`、历史 `chapter_<N>_v<M>.md` |
| 编码 | UTF-8 |
| 大小写 | 文件名小写，配置项小写 |

### 5.3 用户约束

| 约束 | 说明 |
|---|---|
| 命令行基础 | 用户应熟悉 bash / cd |
| Python 环境 | 用户应能安装 pip 包 |
| LLM 账号 | 用户需有 OpenAI / minimax 等账号 |

---

## 6. 验收标准

### 6.1 功能验收

- [ ] 46 个命令（含 `--help`）均可执行
- [ ] `novel init` 后生成完整的项目骨架
- [ ] `novel chapter N` 后自动维护 state / foreshadow / arc
- [ ] `novel doctor --fix` 可修复占位文件
- [ ] DRY_RUN 模式不调 API
- [ ] 切换 `OPENAI_BASE_URL` 可换不同 LLM

### 6.2 性能验收

- [ ] 单章生成 < 5 分钟（3000 字 / 中等网络）
- [ ] 工具命令 < 2 秒
- [ ] 启动时间 < 1 秒

### 6.3 质量验收

- [ ] 111 单测全过
- [ ] `ruff check` 无 F-class 错误
- [ ] CI 3 矩阵全绿
- [ ] `novel doctor` 在 my_novel 示例上诊断 0 issue

### 6.4 文档验收

- [ ] README 列出全部 46 命令
- [ ] USER_MANUAL 有快速开始 + 教程
- [ ] BEST_PRACTICES 有 5+ 个实战配方
- [ ] DESIGN 有架构图和数据流图
- [ ] CHANGELOG 记录 v0.1 - v0.11

---

## 7. 未来需求（路线图）

### 7.1 中期（v0.12 - v0.13）

| 需求 | 优先级 |
|---|---|
| OpenViking 集成（minimax 长期记忆库） | P1 |
| REPL 模式（作者+AI 多轮对话） | P1 |
| 多模型协作（强模型审稿、快模型润色） | P1 |
| FastAPI Web 服务（已有 [web] extra） | P1 |
| TUI 模式（terminal UI） | P2 |

### 7.2 长期（v1.0+）

| 需求 | 优先级 |
|---|---|
| 人物关系图（自动生成人物） | P2 |
| 时间线拖拽（自动写章节） | P3 |
| 多项目批量管理 | P2 |
| 出版级别长篇自动产出 | P3 |

详见 [PROGRESS.md §7](PROGRESS.md) 的未来路线图章节。