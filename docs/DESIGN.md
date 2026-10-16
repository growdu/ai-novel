# 设计文档（Design）

novel-writer v0.12 的架构设计说明，含架构图、数据流图、关键决策。

> **v0.12 定位修订**：从「AI 辅助创作工具」转向「**给定输入自动写完整本书**」。  
> 两种工作流（需求驱动 / 模仿驱动）收敛为统一 `novel write` 顶层入口；删除了 5 个被 auto 流水线完全替代的命令。详见 [§13. v0.12 输入驱动架构](#13-v012-输入驱动架构)。

---

## 1. 总体架构

### 1.1 分层视图

```mermaid
graph TB
    subgraph User["用户层"]
        U[作者]
    end

    subgraph CLI["CLI 层 (Typer)"]
        CMD[novel 命令]
        SETUP[setup 向导]
        DOC[doctor 诊断]
    end

    subgraph Domain["业务逻辑层"]
        GEN[generator.py]
        STO[storage.py]
        PRO[prompts.py]
    end

    subgraph Infra["基础设施层"]
        LLM[llm.py]
        CFG[config.py]
        DIFF[diff_utils.py]
    end

    subgraph Ext["外部依赖"]
        API[LLM API<br/>minimax / OpenAI / ...]
        FS[本地文件系统]
    end

    U --> CMD
    U --> SETUP
    CMD --> GEN
    CMD --> STO
    CMD --> PRO
    DOC --> STO
    GEN --> LLM
    GEN --> STO
    GEN --> PRO
    PRO --> LLM
    LLM --> API
    STO --> FS
    CFG --> FS
```

### 1.2 模块依赖矩阵

```mermaid
graph LR
    novel_cli[novel_cli.py] -->|imports| config
    novel_cli -->|imports| storage
    novel_cli -->|imports| generator
    novel_cli -->|imports| prompts
    novel_cli -->|imports| llm
    generator -->|imports| storage
    generator -->|imports| prompts
    generator -->|imports| llm
    generator -->|imports| config
    prompts -->|imports| llm
    storage -->|imports| config
    config -.独立.-> config
    llm -.独立.-> llm
    diff_utils -.独立.-> diff_utils
```

**关键约束**：依赖单向、不形成环。`config` 和 `llm` 是叶子模块。

---

## 2. 数据模型

### 2.1 项目结构

```mermaid
graph TB
    Root[my_novel/] --> NOVEL[.novel/]
    Root --> ENV[.env<br/>项目级配置]
    NOVEL --> Yaml[project.yaml]
    NOVEL --> Outline[outline.md]
    NOVEL --> Char[characters.md]
    NOVEL --> Style[style.md]
    NOVEL --> Genre[genre_preset.md]
    NOVEL --> World[world.md]
    NOVEL --> Vol[volumes.md]
    NOVEL --> TL[timeline.md]
    NOVEL --> State[state.md]
    NOVEL --> Roll[rolling_summary.md]
    NOVEL --> FS[foreshadowing.md]
    NOVEL --> Arcs[arcs/]
    Arcs --> ArcOverview[_overview.md]
    NOVEL --> Chapters[chapters/]
    Chapters --> C1[0001.md]
    Chapters --> C2[0002.md]
    Chapters --> CN[NNNN.md]
    NOVEL --> History[history/]
    History --> HV1[chapter_0001_v1.md]
    NOVEL --> Reports[reports/]
    Reports --> DET[detect_0001.md]
    Reports --> RAD[style_radar_0001.md]
    NOVEL --> Plans[chapter_plans/]
    NOVEL --> Prompts[prompts/<br/>项目级覆盖]
    NOVEL --> Samples[samples/<br/>风格样本]
```

### 2.2 元数据流（每章写完）

```mermaid
sequenceDiagram
    participant Author
    participant CLI as novel_cli
    participant Gen as generator
    participant LLM
    participant Store as storage

    Author->>CLI: novel chapter 5
    CLI->>Gen: write_chapter_extended(req, ctx)
    Gen->>Store: load 上下文 (outlines/characters/世界...)
    Store-->>Gen: 上下文 dict

    loop 迭代次数
        Gen->>LLM: chat(messages, temperature=0.95)
        LLM-->>Gen: chapter content
        Gen->>LLM: detect(content)
        LLM-->>Gen: detect report
        Gen->>LLM: review(content)
        LLM-->>Gen: review report
        Gen->>LLM: polish(content, feedback)
        LLM-->>Gen: polished content
    end

    Gen->>Store: save_chapter(5, content)
    Store->>Store: backup -> history/chapter_0005_v1.md
    Store-->>Gen: saved path

    Gen->>LLM: update_state(5)
    Gen->>LLM: update_foreshadow(5)
    Gen->>LLM: update_arc(5)
    Gen->>LLM: update_timeline(5)
    Gen->>LLM: generate_chapter_title(5)
    Gen->>Store: save 各元数据

    Gen-->>CLI: result(content, word_count, iterations)
    CLI-->>Author: 显示报告
```

---

## 3. 长篇一致性机制

### 3.1 五种"长期记忆"

```mermaid
graph TB
    subgraph 长期记忆
        State[state.md<br/>最近 3 章压缩<br/>~500-800 字]
        Roll[rolling_summary.md<br/>全书每 5 章刷新<br/>~800-1500 字]
        FS[foreshadowing.md<br/>F1-Fn 编号 + 回收章节]
        TL[timeline.md<br/>故事内时间线]
        Arc[arcs/_overview.md<br/>每人 起点→中段→当前→下一卷]
    end

    subgraph 来源
        Outline[outline.md]
        Char[characters.md]
        Vol[volumes.md]
        Chapters[chapters/*.md]
    end

    Outline --> State
    Char --> State
    Chapters --> State
    Outline --> Roll
    Chapters --> Roll
    Chapters --> FS
    Chapters --> TL
    Outline --> TL
    Char --> Arc
    Vol --> Arc
    Chapters --> Arc

    style State fill:#e1f5e1
    style Roll fill:#e1f5e1
    style FS fill:#fff4e1
    style TL fill:#fff4e1
    style Arc fill:#fff4e1
```

### 3.2 记忆的传递

每章 prompt 注入的"上下文"由七部分组成：

```mermaid
graph LR
    Chapter[写第 N 章] --> Ctx[ChapterContext]
    Ctx --> A[outline]
    Ctx --> B[characters]
    Ctx --> C[style]
    Ctx --> D[chapter_plan]
    Ctx --> E[prev_chapter_tail]
    Ctx --> F[state<br/>最近 3 章]
    Ctx --> G[foreshadow]
    Ctx --> H[world]
    Ctx --> I[timeline]
    Ctx --> J[volumes]
    Ctx --> K[arc]
    Ctx --> L[rolling_summary]
    Ctx --> N[genre 硬规则]
    Ctx --> M[style_samples 风格样本]
    A & B & C & D & E & F & G & H & I & J & K & L & M & N --> Build[build_chapter_messages]
    Build --> LLM[LLM.chat]
```

---

## 4. LLM 适配层

### 4.1 think 标签剥离（三层兜底）

```mermaid
flowchart TB
    Start[LLM 返回 content] --> L1{第 1 层<br/>完整闭合<br/>think 块?}
    L1 -->|是| R1[sub 闭合 think 块]
    L1 -->|否| L2{第 2 层<br/>未闭合 think<br/>后跟 #标题<br/>或 \\n\\Z?}
    L2 -->|是| R2[sub 到边界]
    L2 -->|否| L3{第 3 层<br/>仍含 think 关键字?}
    L3 -->|是| R3[从首个 think 截断]
    L3 -->|否| L4{15 行内<br/>有标题 +<br/>英文 think 残片?}
    L4 -->|是| R4[从首个标题截断]
    L4 -->|否| Done[原文返回]
    R1 --> Done2[strip+返回]
    R2 --> Done2
    R3 --> Done2
    R4 --> Done2

    style Done fill:#e1f5e1
    style Done2 fill:#e1f5e1
```

**为什么需要 4 层？**
- 第 1 层：处理标准的 `<think>...</think>`
- 第 2 层：处理被 max_tokens 截断的 think 块（带 `\n\n##` 边界）
- 第 3 层：兜底任何残余 `<think>` 关键字
- 第 4 层：处理英文 think 残片（"OK so let me..."）

### 4.2 chat_with_continuation 自动续写

```mermaid
sequenceDiagram
    participant CLI
    participant CC as chat_with_continuation
    participant LLM
    participant Merge

    CLI->>CC: chat_with_continuation(msgs, target_words)

    loop 迭代 ≤ 4
        CC->>LLM: chat(msgs, max_tokens=剩余)
        LLM-->>CC: result(content, finish_reason)

        alt finish_reason=stop AND len ≥ min_chars
            Note over CC: 完整 → break
        else len 不足 或 finish_reason=length
            Note over CC: 添加 "接着写" prompt
            CC->>LLM: chat(msgs + "接着写")
            LLM-->>CC: result2
        end
    end

    CC->>Merge: 拼接所有 chunks
    Merge-->>CLI: 完整内容
```

**关键参数**：
- `min_chars = max(200, target_words * 0.6)`：动态阈值（替代固定 800）
- `max_total_tokens=30000`：4 次迭代的上限
- 每次 `max_tokens = min(剩余预算, 16000)`

---

## 5. 提示词系统

### 5.1 三层提示词

```mermaid
graph TB
    subgraph L1[第 1 层 - 全局规则]
        DAI[de_ai_flavour.md<br/>6.4K 字节<br/>20+ 禁用表达<br/>作家参考<br/>每章自检]
    end

    subgraph L2[第 2 层 - 任务模板]
        T1[outline.md]
        T2[chapter.md]
        T3[polish.md]
        T4[detect_ai.md]
        T5[review.md]
        T6[state.md]
        T7[foreshadow.md]
        T8[arc.md]
        T9[timeline.md]
        T10[volume_report.md]
        T11[style_radar.md]
        T12[其他 17 个]
    end

    subgraph L3[第 3 层 - 用户上下文]
        C1[题材硬规则<br/>genre_presets.md]
        C2[文风预设<br/>style_presets.md]
        C3[本项目大纲]
        C4[本项目人物]
        C5[本项目风格样本]
        C6[本项目长期记忆]
    end

    DAI --> Build[build_xxx_messages]
    T1 & T2 & T3 & T4 & T5 & T6 & T7 & T8 & T9 & T10 & T11 & T12 --> Build
    C1 & C2 & C3 & C4 & C5 & C6 --> Build
    Build --> Send[发送给 LLM]
```

### 5.2 题材 / 文风匹配流程

```mermaid
flowchart TB
    Input[--genre '悬疑'] --> A{精确匹配<br/>titles?}
    A -->|命中| Use[使用完整标题]
    A -->|未中| C{包含 / 前缀匹配?}
    C -->|命中| Use
    C -->|未中| D{公共前缀<br/>≥ 2 字?}
    D -->|命中| Use
    D -->|未中| Empty[返回空<br/>= 不注入硬规则]
    Use --> Block[提取 markdown 块]
    Block --> Inject[注入 system prompt]
```

---

## 6. 命令路由

```mermaid
graph LR
    A[novel xxx] --> B{xxx 是}

    B -->|init| C1[init_project]
    B -->|outline| C2[LLM with outline prompt]
    B -->|chapter N| C3[write_chapter_extended]
    B -->|sprint| C4[write × N]
    B -->|polish N| C5[detect+polish+save]
    B -->|state| C6[update_state]
    B -->|...| C99[其他命令]

    C1 --> S1[storage]
    C2 --> S1
    C3 --> S1
    C3 --> S2[generator]
    C3 --> S3[llm]
    C3 --> S4[prompts]
    C4 --> S1
    C4 --> S2
    C5 --> S1
    C5 --> S2
    C6 --> S1
    C6 --> S2

    style S1 fill:#ffe1e1
    style S2 fill:#e1e1ff
    style S3 fill:#e1ffe1
    style S4 fill:#fff4e1
```

---

## 7. 改编工作流

### 7.1 adapt 命令的两步流程

```mermaid
sequenceDiagram
    participant User
    participant Adapt as novel adapt
    participant Skel as extract_skeleton
    participant AdaptG as adapt_novel
    participant LLM

    User->>Adapt: --source novel.txt --direction 换名<br/>--genre 悬疑 --style 冷峻

    alt --with-skeleton (default)
        Adapt->>Skel: extract_skeleton(source)
        Skel->>LLM: chat(target_words=600, temp=0.4)
        LLM-->>Skel: 骨架（人物、冲突、节奏）
        Skel-->>Adapt: skeleton_text
    end

    Adapt->>AdaptG: adapt_novel(source, direction, genre, style)
    adapt_g->>LLM: chat(target_words=2000, temp=0.7)
    LLM-->>AdaptG: 改编方案
    AdaptG-->>Adapt: adapt_text

    Adapt->>User: 保存到 .novel/adapt.md
    Note over User: 下一步：<br/>novel outline 用方案生成新大纲
```

### 7.3 webnovel-pack 一键流程

```mermaid
flowchart TB
    A[novel webnovel-pack name<br/>--title --theme<br/>--genre --style --idea] --> B[创建项目目录]
    B --> C[加载网文题材 hard规则]
    C --> D[加载爽感文风]
    D --> E[写入 style.md<br/>=genre_block + 金手指]
    E --> F[写入 genre_preset.md]
    F --> G[写入 webnovel_plan.md<br/>黄金三章 + 节奏建议]
    G --> H[init_project .yaml]
    H --> I[显示下一步<br/>outline → chapter 1-3]
```

---

## 8. 状态管理

### 8.1 自动维护触发

```mermaid
graph LR
    A[novel chapter N 写完] --> B[state.md]
    A --> C[foreshadowing.md]
    A --> D[arcs/_overview.md]
    A --> E[timeline.md]
    A --> F[titles.json]

    A --> G{N mod 5 == 0?}
    G -->|是| H[rolling_summary.md]
    G -->|否| Skip[跳过]

    A --> I{N == 卷末?}
    I -->|是| J[reports/volume_<V>_report.md]
    I -->|否| Skip2[跳过]
```

### 8.2 伏笔簿（F1-Fn 编号）

```mermaid
graph TB
    A[小说情节] --> B[埋下伏笔<br/>标记 F1]
    B --> C[foreshadowing.md 记录<br/>F1: 主角偷看日记<br/>回收: 第 15 章]
    C --> D{到第 15 章?}
    D -->|是| E[review / arc 检测是否回收]
    D -->|否| F[gaps: 待回收]
    E -->|已回收| G[fulfilled]
    E -->|未回收| H[overdue 警告]
    F --> I[upcoming]

    style G fill:#e1f5e1
    style H fill:#ffe1e1
    style I fill:#fff4e1
```

---

## 9. 异常处理

### 9.1 API 失败重试

```mermaid
sequenceDiagram
    participant Caller
    participant Chat as chat
    participant API

    Caller->>Chat: chat(messages, retry=3)

    loop attempt 0..retry
        Chat->>API: POST /chat/completions

        alt 5xx 错误
            API-->>Chat: 5xx
            Note over Chat: sleep min(2**attempt, 8)
        else 4xx 错误
            API-->>Chat: 4xx
            Chat-->>Caller: LLMError(立即)
        else 网络异常
            API-->>Chat: ConnectionError
            Note over Chat: sleep min(2**attempt, 8)
        else 成功
            API-->>Chat: 200 + content
            Chat->>Chat: _strip_think_tags
            Chat-->>Caller: LLMResult
        end
    end

    Chat-->>Caller: LLMError("chat failed after retries")
```

### 9.2 章节残片兜底

```mermaid
flowchart TB
    A[chapter] --> B{章节字数<br/>< 100?}
    B -->|是| Fail[标记为异常]
    B -->|否| C{含 think 残片?}
    C -->|是| Fail
    C -->|否| OK[正常]

    Fail --> D[novel retry-stuck]
    D --> E{自动重写?}
    E -->|是| F[删除文件 + 重跑 chapter]
    E -->|否| G[仅列出]
```

---

## 10. 关键设计决策

### 10.1 提示词即产品

| 决策 | 原因 |
|------|------|
| 提示词外置到 `prompts/*.md` | 作者可改、可版本化、可对比 |
| `@lru_cache` 加载 | 避免重复读盘 |
| 不用 f-string 模板 | 减少 LLM 端的不确定性 |

### 10.2 减法优于加法

| 决策 | 原因 |
|------|------|
| `de_ai_flavour.md` 列出 20+ 禁用表达 | 比"教怎么写"更有效 |
| 6 维度雷达量化 | 把"AI 味"从主观变成可测量 |
| 多轮审稿迭代 | 让模型能自我修正 |

### 10.3 长篇需要长期记忆

| 决策 | 原因 |
|------|------|
| state（最近 3 章）+ rolling（每 5 章）| 双层记忆，平衡细节与全局 |
| foreshadow 编号 F1-Fn | 模型可主动埋设和回收 |
| arc（人物弧线）| 长期人物变化 |
| 自动维护而非手动 | 作者不写元数据 |

### 10.4 兼容任意 OpenAI 协议

| 决策 | 原因 |
|------|------|
| 不绑定特定供应商 | minimax / OpenAI / DeepSeek / 通义 都可用 |
| DRY_RUN 模式 | 调试提示词不需要 API |
| 项目级 `.env` | 覆盖全局配置 |

---

## 11. 性能与可扩展性

### 11.1 性能瓶颈与对策

| 瓶颈 | 对策 |
|---|---|
| 单章 LLM 调用 ~30 秒 | 多章并发（TODO） |
| 长 prompt 20K tokens | 拆分摘要、自动剪枝 |
| max_tokens 截断 | chat_with_continuation 续写 |
| think 残片 | 三层兜底 |

### 11.2 可扩展点

| 扩展 | 实现 |
|---|---|
| 新增题材 | `prompts/genre_presets.md` 加 `# 标题` 段落 |
| 新增文风 | `prompts/style_presets.md` 加 `# 标题` 段落 |
| 新增提示词 | `prompts/<name>.md` + `prompts.py` 加 `lru_cache` |
| 新增命令 | `novel_cli.py` 加 `@app.command()` |
| 新增 LLM | 修改 `OPENAI_BASE_URL` 即可 |
| 新增风格雷达维度 | `style_radar.md` 加评估项 |

---

## 12. 安全与隐私

| 风险 | 对策 |
|---|---|
| API key 明文 | `.env` 在 `.gitignore` |
| API key 打印 | `masked()` 隐藏前 4 + 后 3 |
| 提示词泄露 | prompts/ 是公开 markdown |
| 数据丢失 | `save_chapter` 自动备份 |
| 误删章节 | `novel rollback --to vN` |

---

## 附录 A：相关文档

- [REQUIREMENTS.md](REQUIREMENTS.md) - 需求规格
- [USER_MANUAL.md](USER_MANUAL.md) - 用户手册
- [BEST_PRACTICES.md](BEST_PRACTICES.md) - 最佳实践
- [PROGRESS.md](../PROGRESS.md) - 演进日志
- [CHANGELOG.md](../CHANGELOG.md) - 版本日志

---

## 13. v0.12 输入驱动架构

### 13.1 定位变化

| | v0.11（之前） | v0.12（现在） |
|---|---|---|
| 项目定位 | AI 辅助创作工具 | 给定输入自动写完整本书 |
| 主入口 | `novel auto`（需求）/ `novel init + chapter N`（手动） | `novel write`（需求 + 模仿 + 网文 三个语义合一） |
| 手动介入 | 单章写、续写、改写频繁 | 仅在 auto 流水线结果上做局部微调 |
| 命令数 | 50 | 45（删 6 加 1） |

v0.11 把「规划 / 写作 / 润色 / 一致性 / 导出」拆成大量子命令留给用户逐步调用；
v0.12 把这些步骤收敛为 `run_auto_novel()` 的 6 阶段流水线，对外只暴露两个语义入口。

### 13.2 novel write 双分支数据流

```
┌────────────────────────────────────────────────────────────┐
│                       novel write                          │
│  (typer command, novel_cli.py:236)                         │
└────────────────────────┬───────────────────────────────────┘
                         │
              ┌──────────┴──────────┐
              │                     │
     --title 走需求驱动      --from-source 走模仿驱动
              │                     │
              ▼                     ▼
    init_project()         extract_skeleton(source)
    填 title/theme/genre   ─→ adapt_novel(source, direction,
    /style/words → spec              target_genre, target_style)
              │                     │
              │                     ├─→ 保存 .novel/adapt.md
              │                     ├─→ 预填 .novel/outline.md
              │                     └─→ init_project() + spec
              │                     │
              └──────────┬──────────┘
                         │
                         ▼
              run_auto_novel(spec, project_dir)
              ┌──────────────────────────────────────┐
              │ 阶段 1: PLANNING                    │
              │   outline / characters / world /     │
              │   volumes / chapter_plans            │
              │ 阶段 2: WRITING                     │
              │   _write_one_chapter ×N              │
              │ 阶段 3: POLISHING                   │
              │   batch polish + detect              │
              │ 阶段 4: CONSISTENCY                 │
              │   timeline / state / arcs            │
              │ 阶段 5: EXPORTING                   │
              │   book.md                           │
              └──────────────────────────────────────┘
```

### 13.3 模仿驱动的桥接

**问题**：`run_auto_novel()` 默认是「从零生成」的 6 阶段流水线。模仿驱动有现成的
「改编方案」文本，能否在 auto 里被消费？

**方案**：让 `_planning_phase()` 的产物文件存在性 + 大小检查（≥200 字节）天然跳过：

```python
# novel/auto.py:106
if not project.outline_path.exists() or project.outline_path.stat().st_size < 200:
    # regenerate
    ...
project.outline_path.write_text("# 大纲\n\n" + res.content + "\n", encoding="utf-8")
```

模仿驱动先调用 `extract_skeleton` + `adapt_novel` 拿到改编方案，再把
adapt_text 作为 `outline.md`（>200 字节）写出：

```python
# novel_cli.py:354-356
(proj.novel_dir / "adapt.md").write_text(...)
proj.outline_path.write_text("# 大纲（基于模仿改编）\n\n" + adapt_text + "\n", ...)
```

`_planning_phase` 看到 outline.md 已存在 → 跳过大纲生成，**进入下一步**：

- characters.md：auto 自动基于 outline 生成（有具体人物名）
- world.md：auto 自动基于 outline 生成（如果是网文/玄幻等非现实题材）
- chapter_plans/*.md：auto 自动基于 outline + characters + world 逐章生成

**结果**：改编方案的「核心冲突 / 人物骨架 / 主题」沿用，但具体人物名 / 章纲由 auto
重新规划以匹配目标题材。这一设计避免了在 auto 的 prompt 里塞入 adapt 内容的耦合。

### 13.4 spec_from_project helper

**问题**：`run_auto_novel(spec, project_dir)` 要求传入完整 `AutoSpec`；
但用户已经手动 `init` 过一个项目（写好 .novel/project.yaml），再跑 auto 时
期望「复用项目元数据」。

**方案**：

```python
# novel/auto.py:534-560
def spec_from_project(project_dir: Path, quality: QualityPreset = ...) -> _AutoSpec:
    proj = S.load_project(project_dir)
    meta = proj.meta or {}
    return _AutoSpec(
        title=proj.title,
        theme=meta.get("theme", ""),
        genre=meta.get("genre", "现实 / 严肃文学"),
        style=meta.get("style_preset", ""),
        target_words=int(meta.get("target_words") or 100000),
        target_chapters=0,  # 由 __post_init__ 自动算
        quality=quality,
    )
```

现在用户可以「`novel init --template 东北悬疑` → `novel write . --quality premium`」
两步走，前者只填元数据，后者只跑流水线。

### 13.5 删除的命令：定位 vs 实现

| 命令 | 定位 | 实现 | v0.12 后定位 |
|---|---|---|---|
| `plan` | 单章细化 | `G.generate_chapter_plan(proj, n)` | 由 `_planning_phase` 批量化（auto 阶段 1） |
| `plan-all` | 批量细化 | 循环 `generate_chapter_plan` | 由 `--plans-only` + `_planning_phase` 取代 |
| `plans` | 章纲列表 | `proj.novel_dir / "chapter_plans"` glob | 由 `status` / `audit` 取代 |
| `sprint` | 从末章冲 N 章 | 调用 `write(start, end)` | 由 `auto` 续跑（auto_state 跳过已完成）取代 |
| `batch` | 批量 polish/detect | 4 个 if-else 分支调用 LLM | 由 `auto` 的 POLISHING + CONSISTENCY 阶段取代 |
| `write -s --end` | 手动连续写 | 循环 `write_chapter_extended` | **顶级化**为 `novel write`（统一入口） |

**保留为高级手动**（局部微调，不违反「输入 → 自动」定位）：
- `chapter N`：覆盖单章
- `continue N`：接写单章
- `chat N`：自然语言协作
- `expand-scene N`：场景插入
- `polish N` / `detect N` / `radar N`：单章检测（统计与报告）

### 13.6 隐藏 bug 的修复

**问题**：`novel_cli.py:1968` 调用 `run_auto_novel(... resume=effective_resume ...)`，
但 `run_auto_novel` 的真实签名是 `state=`，不是 `resume=`。当前没人触发是因为
位置参数旁路；但 `auto --resume` 显式续跑 + 控制信号路径会 TypeError。

**修复**：

```python
# 之前（潜在 TypeError）
out = run_auto_novel(
    spec, proj.root, cfg=cfg,
    resume=effective_resume,    # ← 错（同名状态对象，不是 bool）
    ...
)

# 现在
out = run_auto_novel(
    spec, proj.root, cfg=cfg,
    budget_cny=budget,
    plans_only=plans_only,
    skip_plans=skip_plans,
)
# 让 run_auto_novel 内部 if state is None: state = AutoState.load(...) 自动加载
```

### 13.7 与 v0.13+ 的衔接点

`novel write` 提供的统一入口对未来的特性友好：

- **多语言**：`--lang en` 让 spec 加 language 字段，传给 `_build_chapter_ctx` 的 prompts
- **不同 POV**：`--pov first-person` 让 spec 加 pov 字段，写入每章 prompt
- **不同输出格式**：`--format epub/pdf`：复用 `_exporting_phase` 的 last 步骤

这些都不需要 `novel write` 重构，只需要在 `AutoSpec` 加字段 + 6 阶段的对应步骤
读取即可。内核的「简化设计 = 可扩展」的体现。

---

## 14. v0.13.x 模块化设计

### 14.1 动机
v0.12 时 `novel_cli.py` 2038 行装 50 个 @app.command() + 若干 helpers：
- 加新命令要在 2000 行里找位置
- 命令名全局冲突（如 `write` 被旧命令占用，新写的 `novel write` 顶层入口要换名字）
- 一处改动影响整文件，对 hot reload / 静态分析都不友好
- 阅读时认知负担太重（一个文件无法只关心「写小说的代码」而不被无关命令分心）

### 14.2 切分原则
**按功能而不是按类型切**。原本可以按「类/函数/全局」类型切，但更合理的是按用户意图切：
- config 层（setup / config / version / prompt）
- presets 层（genres / styles / templates）
- init 层（init / write / webnovel_pack — 顶层入口）
- run 层（auto / serve）
- planning 层（outline / characters / world / volumes）
- writing 层（chapter / continue / chat / expand_scene / title）
- qa 层（polish / detect / radar）
- state 层（timeline / state / rolling / check / arc / foreshadow / gaps）
- project 层（list / info / whereami / status / audit / progress / history）
- diagnose 层（doctor / retry-stuck / rollback / fix / diff）
- adapt 层（adapt / fanfic）
- output 层（export / index）

### 14.3 模块接口
每个 `novel/commands/_xxx.py`：
- 自带 imports（只 import 自己用的）
- 自建 `console = Console()`（不共享全局）
- 暴露 N 个**裸函数**（不直接 @app.command()）
- 暴露 `register(app: typer.Typer)` 函数，循环注册

```python
# novel/commands/_init.py
def init(...): ...  # 裸函数
def write(...): ...  # 裸函数

def register(app):
    app.command()(init)
    app.command(name="write")(write)
```

`novel/commands/__init__.py` 的 `register_all(app)` 顺序遍历各模块。

### 14.4 全局 callback 必须留在 entry
`@app.callback()` 用于定义 `--version / --quiet` 这种全局 flag。这种 callback 必须装饰到 main `app`，而不能跨模块注册。所以：
- `novel_cli.py` 保留 `_main` callback + `app = typer.Typer(...)` + `register_all(app)`
- 各模块**不能**用 `@app.callback()`

### 14.5 设计权衡
| 决策 | 选择 | 理由 |
|---|---|---|
| 子模块用 `_xxx` 前缀 | ✅ | 让 import 语句按字母排序时 commands 在最前 |
| `console` 每个模块独立 | ✅ | 避免模块间隐式耦合 |
| `register(app)` 在每个模块底部 | ✅ | 模块自描述，refactor 时整个文件移走也能用 |
| `register_all` 在 `__init__.py` | ✅ | 单一注册入口，便于调试（「到底注册了哪些命令」）|
| 模块内命令用裸函数 | ✅ | 测试时可以单独 import 函数测，无需构造 typer app |

### 14.6 收益
- `novel_cli.py`: 2038 → 45 行
- 单文件最大: 389 行（`_project.py`）
- 加新命令成本: 新建 ~150 行 + 1 行 register
- 命名冲突: 消除（每模块独立命名空间）
- 测试隔离: 可单独 import `from novel.commands._init import write` 测

---

## 15. v0.14 配额限制自动等待

### 15.1 问题
minimax / OpenAI 等 LLM 服务有 quota 限制：
- **minimax**：5 小时窗口 + 周用量双上限
- **OpenAI**：RPM / TPM 限制
- 一本 30 万字小说 30+ 章 × 每次 ~10 LLM 调用 ≈ 300+ 次；实战必撞 5 小时上限

旧行为（v0.13 及之前）：撞 429 / "quota exceeded" → 抛 LLMError → 用户必须手动 `novel auto` 续跑。

新行为（v0.14）：**自动等到 quota 重置再继续**；超时 / 用户中断也安全保留 state。

### 15.2 两层架构

```
┌─────────────────────────────────────────────────────────────────┐
│  Layer 1: 检测（novel/llm.py）                                    │
│  ─ 检测 9 种配额 trigger（429 / 403+quota / insufficient_quota /  │
│    RPM/TPM / 配额 / 余额不足 / 5小时限额 / 周用量限额 / 请求过快） │
│  ─ 抛 RateLimitError（含 reset_at + retry_after_seconds）          │
└─────────────────────────────────────────────────────────────────┘
                                ↓ RateLimitError
┌─────────────────────────────────────────────────────────────────┐
│  Layer 2: 等待与重试（novel/auto.py）                            │
│  ─ _call_with_quota_retry(fn, max_wait_seconds, chapter_no)        │
│  ─ 撞 RateLimitError → _wait_for_quota() 等到 reset + 30s 缓冲     │
│  ─ 60s 分段可中断睡眠（Ctrl-C 安全）                              │
│  ─ max_wait_seconds cap（默认 6h，覆盖 5h 配额窗口）            │
│  ─ 超时 / 中断 → 抛原 RateLimitError → chapter 标 failed / 整体停   │
└─────────────────────────────────────────────────────────────────┘
```

### 15.3 关键决策

| 决策 | 选择 | 理由 |
|---|---|---|
| 默认 wait / 不 wait | **默认 wait**，加 `--no-wait` 显式退出 | 长任务场景下用户最关心「自动恢复」；短任务可显式关闭 |
| cap 默认 6h 还是更长 | 默认 **6h**（21600s） | 5h 配额典型场景能自动等；更长场景用户自行加 flag |
| sleep 分段粒度 | **60s** | 兼顾：能快速响应 Ctrl-C；又不会频繁调度 |
| 等待期间是否继续写其他章节 | **否**（单章 writer 阻塞等）| 一章绪写等 5h 是常态；并发 writer 在另一章也会立刻撞同样配额，等于徒增复杂度 |
| state 保存粒度 | **每章存档**（已有）+ **撞配额时自动落盘**（新）| 撞配额到下次重启期间任何中断都安全 |
| `--no-wait` 退出语义 | 直接抛 RateLimitError → chapter 标 failed | 用户明确表达「现在不要等」 |

### 15.4 与 v0.13 并发的协作

并发章节生成（`_writing_phase_parallel`）会让多个 worker 同时调用 LLM：
- 撞配额是同时撞的（几个 worker 都拿 429）
- 每个 worker 独立 `_call_with_quota_retry`：
  - 在第一个 429 时记下 `reset_at`
  - 后续 worker 拿到 error 看到 `reset_at` 知道何时可用
  - 但每个 worker 会独立 sleep → 可能多个 worker 同时 sleep 到 reset_at，然后一起 retry → 撞到 429 死循环风险

**v0.14 简化**：并发模式撞到配额后，**所有 worker 共享一个等待时间**（通过临时协调），但实现复杂度高，目前实际行为是「第一个 worker sleep 后 retry，第二个 worker 看到 reset 仍未到继续 sleep」。这本质上是顺序 retry，但每个 worker 独立倒计时。最坏情况 = 不必要的串行化。

**未来优化**（不在 v0.14 范围）：把 `_call_with_quota_retry` 改为读取进程级 shared event，到 reset_at 后触发所有 worker 重试。

### 15.5 可观测性
- 用户能看到：撞配额时控制台打印 HTTP 状态 / reset 估计 / 等待时长
- 心跳：每 5 分钟打印「⏳ 还在等 quota（剩 X 分钟）」
- 退出信息：明确说明「下次 novel auto 自动续」+ 状态位置
- 状态文件：`.novel/auto_state.json` 已落盘，无丢失风险

### 15.6 与续跑的接续
用户即便 Ctrl-C 或 `--no-wait` 退出，下次 `novel auto` 自动接续：
1. 读 `.novel/auto_state.json`，找 `chapters_done` set
2. spec 仍可重建（来自 project.yaml）
3. `_write_one_chapter(n)` 写入时，n 不在 `chapters_done` → 重写
4. 撞配额又自动等

整个机制是**幂等的**：重复跑同一段命令，不会破坏现有章节。

---

## 16. v0.15+ 演进方向

详见 PROGRESS §7。这些都不属当前定位「输入 → 自动写完整本书」的硬要求：

- **OpenViking 集成**：minimax 长期记忆库，跨项目复用人物/伏笔
- **REPL 模式**：与 AI 进行多轮对话式协作
- **多模型协作**：强模型审稿、快模型润色
- **TUI 终端图形界面**

按「内核精简」原则，这些将作为「附加模块」而非核心功能。

---

## 附录 A：相关文档
- [CONTRIBUTING.md](../CONTRIBUTING.md) - 贡献指南