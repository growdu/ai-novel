# 演进日志（PROGRESS.md）

这份文档记录了 novel-writer 项目的设计决策、迭代过程与未来方向。
适合作者、贡献者、回溯项目历史的人阅读。

# 目录
1. 项目定位
2. 核心设计哲学
3. minimax-M3 适配实战经验
4. 长篇 vs 短篇的架构差异
5. 迭代历程
6. 已知问题与限制
7. 未来路线图

# 1. 项目定位

novel-writer 是一个 AI 辅助长篇小说创作 CLI 工具。它做三件事：
1. 把作者零散的想法（主题、人物、大纲、文风）组织成可执行的任务
2. 调用大模型（默认 minimax-M3）生成小说章节、元数据
3. 通过多轮审稿、润色、检测来减少 AI 味道

它不替代作者，而是把作者从机械性写作中解放出来。

# 2. 核心设计哲学

## 2.1 提示词即产品
所有生成质量都来自提示词。提示词以独立 markdown 文件存在 prompts/ 目录，
作者可以直接修改、版本化、对比。

## 2.2 减法优于加法
AI 小说最致命的味道是过度正确：太顺、太圆、太会总结。
我们用 121 行的 de_ai_flavour.md 列出 20 多条禁用表达，加上作家风格参考，
让模型有具体模仿对象。

## 2.3 多轮迭代
每章写作流程：生成 检测 审稿 润色 重写。
审稿报告和检测报告作为下一轮 prompt 的输入。

## 2.4 长篇需要长期记忆
模型上下文窗口有限。长篇写作必须解决：
跨章人物名漂移、时间线漂移、设定漂移、伏笔追踪、人物弧线追踪、节奏管理。

# 3. minimax-M3 适配实战经验

minimax-M3 是带 internal thinking 的推理模型。
60 到 90 百分比的 token 被 think 消耗，留给正文的不多。
实战中遇到三个主要问题：

## 3.1 think 标签污染
模型输出经常带 think 块。当块被截断（max_tokens 不够）时，残片会进入正文。

修复：llm.py 的 _strip_think_tags 三层兜底：
1. 闭合 think 块：_THINK_TAG_RE
2. 未闭合但跟标题相邻：_PARTIAL_THINK_RE
3. 任何含 <think> 关键字的：从 <think> 开始截断

## 3.2 think 残片含英文/拼音
有时模型先英文思考再输出，比如 OK so I should not have 然后 标题 1. 视角人物...
这些英文 think 残片难以用正则匹配。

修复：检测开头 15 行内出现 ## 标题 + 标题前是英文 think 残片时，从首个标题开始截断。

## 3.3 chat_with_continuation 的阈值
looks_substantial = len(content) > 800 太死板。短任务（细化大纲 400 字）会被判定为不完整。

修复：动态阈值 min_chars = max(200, target_words * 0.6)。

# 4. 长篇 vs 短篇的架构差异

短篇（小于 5 万字）写完即忘，所有信息塞进 prompt 即可。
长篇（大于 10 万字）必须有以下能力：

## 4.1 状态摘要（state）
每章写完自动压缩最近 3 章为 500-800 字状态摘要，作为下一章 prompt 的一部分。

## 4.2 滚动摘要（rolling summary）
每 5 章压缩一次全书 800-1500 字总摘要，让模型随时拿全局视角。

## 4.3 伏笔簿（foreshadow）
独立的 F1 到 Fn 编号系统。每条伏笔带预计回收章节。

## 4.4 人物弧线（arc）
每个核心人物的 起点到中段到当前状态到下一卷预计走向 追踪。

## 4.5 跨章一致性（check）
自动扫描人物名漂移、时间漂移、地点漂移、设定冲突、物品漂移。

## 4.6 卷末报告（volume-report）
每卷结束时生成 伏笔埋收清单 + 人物弧进度 + 与下一卷衔接点。

## 4.7 风格雷达（radar）
每章与 samples 比较，6 维度评分（句子长度、标点、视角、比喻、词汇、节奏）。

# 5. 迭代历程

## 5.1 v0.1 短篇工具（commit 0c0c902）
最早版本：init / outline / characters / chapter / polish / detect。
4 个提示词 + 一个简单 LLM 包装。
问题：长篇写 10 章后人名就漂了。

## 5.2 v0.2 长篇工作流（commit 045c97f）
重大重构：
- llm.py 处理 minimax-M3 推理模型
- storage.py 新增长篇元数据文件
- 14 个新命令
- 自动维护 state / foreshadow / arc / timeline

## 5.3 v0.3 长篇提示词专精（commit e1f6b3b）
6 个长篇专项提示词：consistency / volume_report / rolling_summary / style_radar / chapter_title / samples。
每个提示词独立 markdown，用户可改。

## 5.4 v0.4 示例项目 + 真实长篇（commit 2e574df）
生成《冬夜的灰》真实长篇：4 章 11K 字。
实测了完整工作流：outline / characters / world / volumes / chapter / state / foreshadow / arc / check / volume-report。
发现 1 处真实时间线问题：0003 章霍小军不是在沈阳？ 与 0002 矛盾。

## 5.5 v0.5 交互式能力（commits c98c592, 078b045, a5e79eb, fabe5cc, 1d79fe4, e4f6dda）
6 个新功能：
- expand-scene：作者指定位置接场景
- plan：粗大纲细化为 200-400 字场景规划
- progress：长篇写作进度统计
- continue：章节末尾接写
- sprint：自动从最后一章后写多章
- chat：自然语言协作修改

## 5.6 v0.6 工具化（commits 25f0624, dcf6514, f252517）
doctor：自动诊断项目
smoke_test.sh：端到端冒烟测试
README 全面重写

## 5.7 v0.7 写作流增强（commits 1bfda0a, b58349a, 9924adc, c988348）
PROGRESS.md：完整的设计决策与演进日志
diff：对比任意两版章节的差异
prompt：每项目独立的提示词管理
batch：批量执行 polish / detect / radar / title

## 5.8 v0.8 实用工具集（commits c988348, 51c0825, a454219）
rollback：章节回滚到任意历史版本（回滚前自动备份）
fix：检测异常章节（0 字节、含 think 残片）
audit：全项目综合审计表

## 5.9 v0.9 输出与追踪（commits a483b2c, 31a32c7, b7f0538, d9a629d, cac6ca2）
export：合并所有章节为单一书稿（book.md / book.txt）
retry-stuck：自动检测并重写 0 字节/残片章节
index：全书索引表（章节、标题、字数、状态）
gaps：伏笔状态表（未回收/待回收/已到章节）
auto-retry：章节空内容自动重试 2 次（解决 5 截断问题）

## 5.10 v0.10 题材/文风系统（commits 602e42, 13ec09b）
之前：genre 是字符串、style 是自由文本，prompt 完全不用。
现在：
- prompts/genre_presets.md：10 个题材（玄幻/仙侠/科幻/悬疑/言情/历史/武侠/都市/校园/现实）
  每个含硬规则、常见设定、容易翻车、作家参考
- prompts/style_presets.md：11 个文风（搞笑/轻松/伤感/诗意/冷峻/热烈/朴素/华丽/紧张/黑色幽默/儿童）
  每个含语言特征、写作时注意、作家参考
- novel/prompts.py：list_genres/list_styles + 智能匹配（精确 -> 包含 -> 前缀）
- novel_cli.py init：完整 --genre/--style 选项
- 自动注入：build_chapter_messages / build_outline_messages 把 genre 硬规则加入 system prompt
- 自动存档：.novel/genre_preset.md 保存选中的题材硬规则
- novel genres / novel styles 命令：查询所有支持预设

## 5.12 v0.11 易用性增强 + 工程化（commit a3c447c + 本次改动）
### 5.12.1 易用性提升
- novel --version / -V 全局标志
- novel version 命令（含环境信息）
- novel setup 交互式首次配置向导（密码隐藏 + 确认；支持 --no-input）
- novel doctor --fix 自动修复占位文件
- novel doctor --json 机器可读报告
- novel rollback / novel fix 默认显示 diff 摘要 + Confirm 确认；--yes 跳过
- ProjectNotFoundError 携带友好解决路径（cd / init / --here）
- shell 自动补全：add_completion=True + typer --install-completion

### 5.12.2 多项目管理
- novel list [--path / --depth]：列目录下所有 .novel 项目（跳级深度、隐藏目录过滤）
- novel info <name>：不cd查看项目元信息
- novel whereami：当前在哪项目里（不在项目里也给建议）
- novel webnovel-pack 已有：一键网文项目

### 5.12.3 工程化
- pyproject.toml: 0.1.0 → 0.11.0
- novel/__init__.py: __version__ = "0.11.0"
- pyproject.toml 加入 [tool.ruff] + [tool.pytest.ini_options]
- dev extras: pip install -e ".[dev]"
- 测试覆盖：103 个 → 111 个用例，5 个文件
  - test_llm.py: _strip_think_tags 三层兜底
  - test_storage.py: 项目 CRUD + 版本备份 + 字数统计
  - test_prompts.py: 题材/文风预设匹配 + 消息构建
  - test_diff_and_config.py: diff + config env helpers
  - test_cli.py: version / setup / init / doctor / list / info / whereami
- CI: .github/workflows/ci.yml
  - 3 矩阵 Python 3.10/3.11/3.12
  - lint + 单测 + DRY_RUN smoke test
  - Issue template + PR template

### 5.12.4 Bug 修复
- novel_cli.py:270-272 polish() 重复 save_chapter + print
- novel_cli.py:831 retry-stuck() ctx dict 重复 genre 键
- novel_cli.py:636 progress() vol_pattern.pattern 永远 truthy 死代码
- novel_cli.py:556 list() 命名冲突覆盖 Python builtin，导致 doctor 报错
- novel/generator.py:250 update_rolling_summary() 缺 Message 导入

### 5.12.5 文档
- README.md 全面重写：46 命令完整列表（含 v0.10 题材/文风、v0.11 改编/网文）
- CONTRIBUTING.md：开发流程、修改规范、PR 流程
- CHANGELOG.md：v0.1 - v0.11 完整版本日志

实战：
- 白夜行 -> 校园/冷峻《夜行》：35 章 4 卷完整改编，22 年时间跨度
  中国学段切分（2003-2025）+ 时代背景锚点（非典/奥运/移动互联网/疫情/大模型）
- 白夜行 -> 桐原亮司后传 30 秒灵魂视角：214 行世界级文学水准

## 5.13 v0.11.x 项目模板系统（commit pending）
在 v0.10 题材/文风原子预设之上，预置 10 个常用组合（一键套用）：

### 5.13.1 设计动机
v0.10 让用户选择题材 + 文风 + 字数，但作者面对空白 init 选项仍然要在 10×11 矩阵里挑组合。
本特性把高频组合收敛为 `模板名`，写作时不再需要从零组合。

### 5.13.2 模板结构（novel/templates.py）
- 新增 `Template` dataclass：name / description / genre / style / default_words
  / sample_title / sample_theme / sample_characters / sample_idea / tags
- 10 个预设：
  1. 东北悬疑（悬疑+冷峻，80K）→ 双雪涛/班宇
  2. 硬科幻（科幻+朴素，60K）→ 刘慈欣/阿西莫夫
  3. 古典言情（言情+诗意，50K）→ 张爱玲/王安忆
  4. 武侠经典（武侠+朴素，120K）→ 金庸/古龙
  5. 轻松校园（校园+轻松，30K）→ 日系轻小说
  6. 诗意现实（现实+诗意，40K）→ 汪曾祺/沈从文
  7. 黑色幽默（都市+黑色幽默，50K）→ 余华/王小波
  8. 网文经典（修仙+经典爽文，2M）→ 长篇网文
  9. 虐心言情（言情+伤感，40K）→ 重逢/遗憾感
  10. 紧张悬疑（悬疑+紧张，60K）→ 暴风雪山庄

### 5.13.3 匹配策略（get_template）
四级 fallback：精确 name → 包含关系 → tag 命中 → description 包含。
例：`东北悬疑` / `东北` / `双雪涛` / `金庸` 都能找到目标。

### 5.13.4 init --template 集成
- `novel init demo --template 东北悬疑` 一行创建完整项目
- 用户参数优先：`--title '盘锦往事' --words 100000` 会覆盖模板默认值
- 未指定参数回退模板值（genre/style/words 任何子集可挑）
- 实现要点：`apply_template()` 过滤掉 None override，只在缺失时回退模板默认
  （之前 bug：dict.get(key, default) 在 key 存在但值为 None 时仍返回 None）

### 5.13.5 测试
- tests/test_templates.py：16 个用例
  - 模板 CRUD：list / get(精确/部分/tag/描述/未知/空)
  - apply_template：默认值 / overrides / None 兜底
  - 模板完整性：name/genre/style/default_words/description 非空校验
  - CLI 集成：init --help 含 --template、unknown 模板报错、部分匹配、words 覆盖

## 5.14 v0.12 输入驱动的端到端定位（commit pending）
**项目定位修订**：从「辅助创作工具」转向「给定输入自动写完整本书」。
为此把两条工作流收敛为统一的 `novel write` 顶层入口，并删除被
auto 流水线完全替代的命令。

### 5.14.1 novel write 统一入口
新增顶层命令 `novel write`，两种工作流（互不冲突）：

**需求驱动**（--title）：
```bash
novel write demo --title '冬夜的灰' --theme '东北命案' \\
  --genre 悬疑 --style 冷峻 --words 60000
```

**模仿驱动**（--from-source）：
```bash
novel write fanfic --from-source 白夜行.txt \\
  --direction 换壳 --genre 校园 --style 冷峻 --words 80000 \\
  --title '冬夜的灰'
```

两种分支都最终调用 `run_auto_novel(spec, project_dir)` 走完整 6 阶段流水线
（PLANNING→WRITING→POLISHING→CONSISTENCY→EXPORTING→DONE）。
模仿分支先做 `extract_skeleton` + `adapt_novel`，把改编结果预填到
`.novel/outline.md`，让 auto 的 PLANNING 阶段跳过大纲生成；
章节规划 + 写作都基于改编内容继续。

### 5.14.2 spec_from_project helper
新增 `novel.auto.spec_from_project(project_dir, quality)`，
从 `.novel/project.yaml` 恢复 `AutoSpec`（title/theme/genre/style/target_words）。
作用：当用户已 init 过项目（手动或带 --template），再用 `novel auto` 时
无需再次输入所有字段。

### 5.14.3 webnovel-pack --auto
网文专项项目（黄金三章骨架等）支持 `--auto` 一行写完整本：
```bash
novel webnovel-pack my_book --title '凡人仙途' --theme '凡人逆袭' \\
  --idea '残破玉佩' --auto --words 500000 --quality premium
```
预填 `webnovel_plan.md` 到 outline.md，自动继承网文节奏。

### 5.14.4 删除被 auto 完全替代的命令
| 命令 | 行号 | 替代物 |
|---|---|---|
| `plan N` | novel_cli.py:677 | `_planning_phase` 自动批量生成（auto 阶段 1） |
| `plan-all` | novel_cli.py:686 | 同上 + `auto --plans-only` |
| `plans [N]` | novel_cli.py:757 | `status` / `audit` 已含章纲列表 |
| `sprint` | novel_cli.py:494 | `auto` 续跑（auto_state 跳过已完成） |
| `batch {polish,detect,radar,title}` | novel_cli.py:1502 | auto 的 POLISHING + CONSISTENCY 阶段 |
| `write --start --end` | novel_cli.py:527 | 与 `auto` + `--chapters` 重叠；让位给 `novel write` 顶层 |

每个被删命令都有对应的 manual 命令保留：`chapter N`（单章）、`polish N`（单章）、
`detect N`（单章）、`radar N`（单章）、`chat N`（交互协作）、`expand-scene N`（场景插入）、
`rollback N`/`diff N`（调试）、`retry-stuck`/`fix N`（修复）。这些保留主名不做
nested 子命令，但 README 把它们标在「高级手动」分类下。

删除 `tests/test_plan_all.py`（8 个失效用例）。

### 5.14.5 顺手修复的 bug
`novel_cli.py` 调用 `run_auto_novel(... resume=effective_resume ...)`，
但 `run_auto_novel` 的真实签名是 `state=`，不是 `resume=`。
当前没人触发（位置参数旁路），但 `auto --resume` 在特定路径会抛 TypeError。
改为传 `state=None`，让 `run_auto_novel` 内部从 `.novel/auto_state.json` 加载。

### 5.14.6 测试
- tests/test_write.py：6 个用例（需求驱动 + 模仿驱动 + 互斥校验 + 错误源 + 帮助）
- 全套 215 用例全过（删除 8 + 新增 6 = 净 -2）

## 5.15 v0.13 并发章节生成（commit pending）
兑现 §11.1 提到的「单章 LLM 调用 ~30 秒 → 多章并发（TODO）」承诺。

### 5.15.1 设计
AutoSpec.parallel 从 `bool = False` 改为 `int = 0`：
- `0` 或 `1`：走原串行 `_writing_phase`（v0.12 行为完全不变）
- `>= 2`：调 `_writing_phase_parallel` 用 `ThreadPoolExecutor(max_workers=parallel)`

CLI 层：novel write / novel auto / novel webnovel-pack --auto 都加 `--parallel N / -P N` flag。
默认 `0 = 串行`（向后兼容；用户不显式加 flag 行为不变）。

### 5.15.2 并发安全的 4 个问题
1. **state.json 写竞争** → `threading.Lock()` 串行化
2. **progress.update 竞争** → `threading.Lock()` 串行化
3. **跨 worker 章节顺序（prev_tail）** → `prev_cache` dict（chapter_no → content）跨 worker 共享
4. **`_check_control_signal` 单文件读取** → OS 文件读写原子性保证

### 5.15.3 实现要点
- `_writing_phase_parallel(spec, project, client, state)`
- 每个 worker 流程：检查 → 构 ctx（含 prev_cache 覆盖）→ 写 → state.save → 缓存
- prev_cache 在 worker 内获取锁读；在写完章后获取锁写
- `as_completed` 收集 futures；任一 worker 异常只打印不断其他
- `_write_one_chapter_locked` = 原 `_write_one_chapter` 的并发安全变体（progress 调用走 safe_progress 加锁包装）

### 5.15.4 性能预期
按 LLM I/O-bound 特性，parallel=3 应对应节省 50-65% wall-clock；parallel=8 接近 80%。
DRY_RUN 模式（LLM 直接返回占位）下并发几乎瞬间完成；不测 wall-clock 以避免 flaky。

### 5.15.5 测试
新增 `tests/test_auto_parallel.py`（11 个用例）：
- AutoSpec 字段语义（默认 0、合法 int、负数归零）
- parallel=4 / parallel=8 端到端：state 完整、book.md 存在
- parallel=1 回落到串行
- CLI `--parallel` 透传（write/auto/webnovel-pack 三个入口）
- state.json 写竞争安全（能 parse + cumulative_tokens 不为负）
- 每个 chapter 都进 chapter_results（无写丢）

# 6. 已知问题与限制

## 6.1 think 截断
即使有 chat_with_continuation，模型偶尔仍会返回空内容（think 占满 max_tokens）。
实际表现：约 5 百分比的章节需要手动重跑。

## 6.2 长 prompt 超时
长篇写作 prompt tokens 可达 20K（state + foreshadow + samples + chapter_plan + outline + ...）。
在 sandbox 网络下，单次响应可能超时。

## 6.3 风格雷达与作者期望可能不一致
作者手写片段的风格和模型认为的风格可能有偏差。
雷达评分只是参考，不是绝对标准。

## 6.4 伏笔簿的准确性取决于模型
F1 到 Fn 编号、回收时间都是模型自填的，可能漏掉或填错。

# 7. 未来路线图

## 7.1 短期
- diff 命令：对比两版章节差异
- prompt 命令：显示或编辑当前提示词
- batch 命令：批量 polish / detect

## 7.2 中期
- OpenViking 集成：minimax 长期记忆库，跨项目复用人物/伏笔
- REPL 模式：每章写作时进入作者+AI 多轮对话
- 多模型协作：强模型审稿、快模型润色
- TUI 模式：终端图形界面

## 7.3 长期
- 让作者可以直接画人物关系图（自动生成人物）
- 让作者拖动时间线节点（自动写章节）
- 多项目批量管理
- 出版级别的长篇自动产出

## 5.16 v0.13.x novel_cli.py 模块化重构（commit pending）

### 背景
v0.12 时 `novel_cli.py` 2038 行装 50 命令 + helpers：
- 添加新命令要在 2000 行里找位置
- 命令名全局冲突（如 `write` 撞过）
- 一处改动影响整文件（hot reload 不友好）

### 实现
把 `novel_cli.py` 拆成 11 个按功能切的命令模块：

| 模块 | 命令数 | 责任 |
|---|---|---|
| `commands/_config.py` | 4 | setup / config / version / prompt |
| `commands/_presets.py` | 5 | genres / styles / webnovel_genres / webnovel_styles / templates |
| `commands/_init.py` | 3 | init / write / webnovel_pack + `_run_auto_via_spec` |
| `commands/_run.py` | 2 | auto / serve |
| `commands/_planning.py` | 4 | outline / characters / world / volumes |
| `commands/_writing.py` | 5 | chapter / continue / chat / expand_scene / title |
| `commands/_qa.py` | 3 | polish / detect / radar |
| `commands/_state.py` | 8 | timeline / state / rolling / check / arc / foreshadow / volume_report / gaps |
| `commands/_project.py` | 7 | list / info / whereami / status / audit / progress / history + `_print_auto_status` + `_watch_status` |
| `commands/_diagnose.py` | 5 | doctor / retry-stuck / rollback / fix / diff |
| `commands/_adapt.py` | 2 | adapt / fanfic |
| `commands/_output.py` | 2 | export / index |

`novel_cli.py` 现在只剩 45 行：app 定义 + 全局 callback + `register_all(app)` + `if __name__`。

### 设计要点
- 每个模块自建 `console = Console()` + 自管 imports
- 命令函数不直接 `@app.command()`，而是裸函数 + 模块底部 `register(app)`
- `__init__.py` 的 `register_all(app)` 顺序遍历所有模块
- 全局 callback（`--version` / `--verbose`）保留在 `novel_cli.py`（callback 必须绑定到 main app）
- 类型层 `invoke_without_command=True` 必须保留（否则 `--version` 单独执行会失败）

### 测试
**回归通过**：`tests/` 全套 228 用例零改动通过；模块切分对外行为完全透明。
（这是模块化的关键指标：refactor 不应改变外部行为。）

### 文档
- DEVELOPER_GUIDE §1.1 文件树：加 `novel/commands/*` 11 个模块
- DEVELOPER_GUIDE §1.3 模块大小表：把 `novel_cli.py` 行数 2038→45；新增 11 命令模块明细
- 模块大小对比表格：v0.12 vs v0.13

## 5.17 v0.14 minimax 配额限制自动等待（commit pending）

### 背景
minimax 模型有 **5 小时**窗口配额 + **周**配额双上限。一本 30 万字小说通常要 30+ 章连续 LLM 调用，实测会撞 5 小时配额 1-2 次。

旧行为（v0.13）：撞 429 直接抛异常 → 用户必须手动 `novel auto` 续跑（state 自动加载）。

新行为（v0.14）：
- 默认**自动等到 quota 重置**再继续
- 单次最多等 `--max-wait-seconds`（默认 6 小时）
- 超时 / Ctrl-C 干净退出 + state 已保存 → 下次 `novel auto` 自动续

### 5.17.1 实现

**两层架构**：

1. **检测层（`novel/llm.py`）**：
   - 新增 `RateLimitError(LLMError)` —— 携带 `reset_at` / `retry_after_seconds` / `raw_status` 元数据
   - `_is_rate_limit_response(status, text, headers)` 检测 9 种触发条件：
     - 429（hard signal）
     - 403 + quota/billing 关键词
     - 文本匹配 9 种正则：insufficient_quota / rate limit / RPM / TPM / 配额 / 余额不足 / 5小时限额 / 周用量限额 / 请求过快
   - 命中 → 抛 `RateLimitError`（不是 generic LLMError）

2. **等待层（`novel/auto.py`）**：
   - `_call_with_quota_retry(fn, max_wait_seconds, chapter_no, on_rate_limit=None)` —— 装饰任意 fn 调用
   - 撞 `RateLimitError` → 调用 `_wait_for_quota(err, max_wait_seconds, chapter_no)`
   - `_wait_for_quota`：算等待秒数（`retry_after` + 30s 缓冲，cap 到 max_wait_seconds）→ 60s 一段睡眠（每段醒一次检查控制信号）→ 返回 True/False
   - Ctrl-C 在任意段安全中断 → 返回 False → outer 把 chapter 标 failed
   - 返回 True → retry fn → 成功继续

**调用点**（v0.14 后 `_write_one_chapter` 内 3 个 LLM 调用都包了 wrapper）：
- `G.write_chapter_extended(...)` — 写主章节
- `run_all_gates(...)` — 跑质量门控
- `_regenerate_chapter(...)` — 失败重试

### 5.17.2 CLI + AutoSpec 字段

```bash
novel write / novel auto / novel webnovel-pack --auto:

# 新增：
  --wait-on-quota / --no-wait          # 默认 --wait-on-quota；--no-wait 直接退出 + state 留底
  --max-wait-seconds INT              # 默认 21600（6h）；调到更长可等周配额
```

### 5.17.3 状态保留下次续
撞配额 + 退出的那一刻，`auto_state.json` 已保存：
- 已完成的章节：`chapters_done` 里
- 未完成的章节：还没 mark done → 下次 `novel auto` 自动重跑（无需 --resume）

### 5.17.4 测试
- `tests/test_rate_limit.py`：26 用例
  - 检测层：9 种配额正则全部命中；403 / 500 等不被误判
  - retry 层：撞 → 等（mock time.sleep） → 重试 → 成功；max_wait=0 立即抛；Ctrl-C 干净中断
  - kwarg 路由：`wait_on_quota=False` → `_PASS_THROUGH` 哨兵
  - CLI：`--wait-on-quota/--no-wait/--max-wait-seconds` 都出现在 help
- 全套 254 用例全过
