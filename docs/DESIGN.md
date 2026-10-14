# 设计文档（Design）

novel-writer v0.11 的架构设计说明，含架构图、数据流图、关键决策。

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
- [CONTRIBUTING.md](../CONTRIBUTING.md) - 贡献指南