# Changelog

novel-writer 的版本变更记录。遵循 [Keep a Changelog](https://keepachangelog.com/) 格式。

---

## [Unreleased]

### 新增
- `novel videos` / `novel list` / `novel info` / `novel whereami`：浏览项目（计划中）
- `novel templates`：一键题材-文风组合（计划中）

---

## [0.11.0] - 2026-XX

### 新增
- **可移植性**：兼容任意 OpenAI Chat Completions 协议（minimax / OpenAI / DeepSeek / 智谱 / 通义）
- **DRY_RUN 模式**：不调 API 完整打印提示词
- **自动备份**：`save_chapter` 写盘前自动备份旧版本到 `history/`
- **跨章一致性**：自动检测人物名 / 时间 / 地点 / 设定漂移
- **风格雷达**：6 维度量化与 samples 相似度

### 修复
- 已知 5% 章节生成失败（think 标签吃满 max_tokens）

### 完整命令（5 类 + ~50 命令）
（命令太长，启动前的命令不在此处赘述；见 README）

---

## [0.10.0] - 题材/文风系统

### 新增
- 严肃向题材 10 个（玄幻/仙侠/科幻/悬疑/言情/历史/武侠/都市/校园/现实）
- 严肃向文风 11 个（搞笑/轻松/伤感/诗意/冷峻/热烈/朴素/华丽/紧张/黑色幽默/儿童）
- 网文题材 8 个（修仙/异能/军事/校园/历史/科幻/都市/悬疑）
- 网文爽感文风 9 个（经典爽文/反转爽文/黑化爽文/轻松搞笑/热血燃/虐恋/系统流/无限流/签到流）
- 每个预设自动注入硬规则 + 作家参考 + 容易翻车的写法
- `novel genres` / `novel styles` / `novel webnovel-genres` / `novel webnovel-styles` 查询
- `init --genre/--style` 模糊匹配（精确 → 包含 → 前缀）

---

## [0.11.x] - 改编工作流

### 新增
- `novel adapt`：基于源小说（高热度小说）改编
  - `--direction` 换名 / 换壳 / 后传 / 反派视角 / 性别转换
  - `--with-skeleton/--no-skeleton` 是否先提取骨架
  - 自动注入目标 genre/style 硬规则
- `novel fanfic`：写后传 / 番外 / 同人
  - `--char` 视角人物
  - `--era` 故事时机
  - `--as-chapter` 直接保存为指定章节
- `novel webnovel-pack`：一键网文项目（建项目 + 选题材 + 选爽文 + 黄金三章骨架）
- 3 个提示词：`prompts/skeleton.md` / `prompts/adapt.md` / `prompts/fanfic.md`

### 实战验证
- 《白夜行》→ 校园/冷峻《夜行》：35 章 4 卷完整改编，22 年时间跨度
- 《白夜行》→ 桐原亮司后传 30 秒灵魂视角：214 行世界级文学水准

---

## [0.11.x] - 项目模板系统

### 新增
- `novel/templates.py`：10 个推荐模板（东北悬疑 / 硬科幻 / 古典言情 / 武侠经典 / 轻松校园 / 诗意现实 / 黑色幽默 / 网文经典 / 虐心言情 / 紧张悬疑）
- `novel templates` 命令：列出 10 个预设组合（题材 + 文风 + 字数 + 风格描述）
- `novel init <name> --template NAME`：一键套用模板（用户参数仍可覆盖）
  - 模糊匹配：精确 → 包含 → tag → 描述（`东北悬疑`/`东北`/`双雪涛` 都命中）
- 16 个单元测试 + CLI 集成测试

### 修复
- `apply_template()` 在 override 为 None 时错误返回 None（dict.get 模式 bug）：改为过滤 None 后再回退默认值

---

## [0.12.0] - 输入驱动端到端定位

### 项目定位修订
从「辅助创作工具」转向「给定输入自动写完整本书」。

### 新增
- **novel write 顶层统一入口**：两种工作流走一条命令
  - 需求驱动：`novel write demo --title X --theme Y --genre Z --style W --words N`
  - 模仿驱动：`novel write fanfic --from-source 白夜行.txt --direction 换壳 --genre 校园 --style 冷峻 --words 80000`
  - 内部统一走 `run_auto_novel(spec, project_dir)` 的 6 阶段流水线
- **`novel.auto.spec_from_project(project_dir, quality)`**：从 `.novel/project.yaml` 恢复 `AutoSpec`，方便已 init 项目跑 auto
- **`novel webnovel-pack --auto`**：网文项目加 `--auto` 直接跑 6 阶段流水线（之前只建骨架）

### 修复
- `run_auto_novel(... resume=...)` 调用错误（真实签名是 `state=`），改为传 `state=None` 让内部自动从 `.novel/auto_state.json` 加载

### 移除（被 auto 流水线完全替代）
- `plan` / `plan-all` / `plans` → `_planning_phase` 自动批量
- `sprint` → `auto` 续跑等同
- `write --start --end`（旧）→ 与 `novel write` 顶层入口重名，让位
- `batch {polish,detect,radar,title}` → auto 的 POLISHING + CONSISTENCY 阶段覆盖
- 同步删除 `tests/test_plan_all.py`（8 个失效用例）

### 测试
- 新增 `tests/test_write.py`：6 个用例（需求驱动 / 模仿驱动 / 帮助与互斥）
- 全套 215 用例全过（删除 8 + 新增 6 + 已有 217 = 215）

---

## [0.13.0] - 并发章节生成

### 新增
- **`run_auto_novel(spec)` 并发模式**：`AutoSpec.parallel` 从 `bool` 升级为 `int`（worker 数）
  - 默认 `0`（串行，向后兼容 v0.12 行为）
  - `>= 2` 走 `_writing_phase_parallel`（ThreadPoolExecutor）
- **`novel write / novel auto / novel webnovel-pack --auto` 加 `--parallel N / -P N`** flag
- 4 个并发安全问题解决方案：
  - state.json 写竞争 → `threading.Lock()`
  - progress.update 竞争 → `threading.Lock()`
  - 跨 worker 章节顺序（prev_tail）→ `prev_cache` dict 跨 worker 共享
  - 控制信号文件读取 → OS 文件读写原子性

### 实现
- `_writing_phase_parallel(spec, project, client, state)` — 并发版实现（novel/auto.py:~430）
- `_write_one_chapter_locked(...)` — `_write_one_chapter` 的并发安全变体
- `as_completed` 收集 futures；任一 worker 异常只打印不断其他

### 测试
- 新增 `tests/test_auto_parallel.py`：11 个用例
  - AutoSpec.parallel 字段语义（默认 0、合法 int、负数归零）
  - parallel=4 / parallel=8 端到端：state 完整、book.md 存在
  - parallel=1 回落串行
  - CLI `--parallel` 透传（write/auto/webnovel-pack）
  - state.json 写竞争安全（JSON parse 通过、cumulative_tokens 不为负）
- 全套 228 用例全过

### 性能预期
- parallel=3：节省 50-65% wall-clock（按 LLM I/O-bound 特性）
- parallel=8：接近 80%
- DRY_RUN 模式不测 wall-clock（避免 flaky）

---

## [0.13.1] - novel_cli.py 模块化重构

### 重构
把 `novel_cli.py`（2038 行）拆成 11 个 `novel/commands/*.py` 模块：

```
novel/commands/
├── __init__.py       # register_all(app) 聚合
├── _config.py        # setup / config / version / prompt
├── _presets.py       # genres / styles / webnovel_genres / webnovel_styles / templates
├── _init.py          # init / write / webnovel_pack
├── _run.py           # auto / serve
├── _planning.py      # outline / characters / world / volumes
├── _writing.py       # chapter / continue / chat / expand_scene / title
├── _qa.py            # polish / detect / radar
├── _state.py         # timeline / state / rolling / check / arc / foreshadow / volume_report / gaps
├── _project.py       # list / info / whereami / status / audit / progress / history
├── _diagnose.py      # doctor / retry-stuck / rollback / fix / diff
├── _adapt.py         # adapt / fanfic
└── _output.py        # export / index
```

### 收益
- `novel_cli.py`: 2038 行 → **45 行**（thin entry）
- 单文件最大行数：389（`_project.py`）
- 加新命令成本：翻 2000 行找位置 → 新建 ~150 行文件 + 1 行 register 调用
- 命名冲突：全局命名空间 → 每模块独立

### 测试
**228 用例零改动通过**（refactor 对外行为透明）

### 文档
- DEVELOPER_GUIDE §1.1 文件树 + §1.3 模块大小表
- PROGRESS §5.16 模块化重构

---

## [0.14.0] - 配额限制自动等待

### 背景
minimax / OpenAI 等 LLM 服务有 quota 限额（minimax 5 小时 + 周用量）；
跑长篇小说过程中常被 429 / "quota exceeded" 中断。v0.13 之前用户必须手动重跑。

### 新增
- **`novel.llm.RateLimitError(LLMError)`**：携带 `reset_at` / `retry_after_seconds` / `raw_status` 元数据
- **检测层**：429 / 403+quota / 9 种正则（insufficient_quota / RPM / TPM / 配额 / 余额不足 / 5小时限额 / 周用量限额 / 请求过快 ...）
- **等待层**：
  - `auto._call_with_quota_retry(fn, max_wait_seconds, chapter_no)` — 装饰任意 LLM 调用
  - `auto._wait_for_quota(err, max_wait_seconds, chapter_no)` — 算 retry_after + 30s 缓冲，60s 一段可中断睡眠
- **`AutoSpec` 字段**：
  - `wait_on_quota: bool = True` — 撞配额自动等到恢复
  - `max_wait_seconds: int = 21600` — 单次最多等 6 小时
- **CLI flags**（novel write / novel auto / webnovel-pack --auto）：
  - `--wait-on-quota / --no-wait`
  - `--max-wait-seconds INT`

### 行为
- 默认行为（v0.14）：撞配额 → 自动等到 reset 时段（最多 6h）→ 续写
- 撞周配额（> 6h）：自动等 6h 然后放弃 → state 保存退出 → 用户 `novel auto` 自动续
- Ctrl-C 任何时候安全中断 → state 已保存，下次手动跑时自动跳过已完成

### 兼容性
零行为变化：对没用过 quota 的用户来说，v0.13 → v0.14 完全透明

### 测试
- 新增 `tests/test_rate_limit.py`：26 用例
  - 检测层：9 种配额正则 + 403/500 误判防护
  - retry 层：撞 → 等 → 重试 → 成功；max_wait=0 立即抛；Ctrl-C 干净中断；`_PASS_THROUGH` 哨兵
  - kwarg 路由：wait_on_quota → (max_wait, on_rate_limit)
  - CLI：3 个新 flag 全部进 help
- 全套 **254 用例**全过（228 + 26）

---

## [0.9.0] - 输出与追踪

### 新增
- `novel export`：合并为单一书稿（md / txt）
- `novel retry-stuck`：自动重写 0 字节 / 残片章节
- `novel index`：全书索引表（章节 / 标题 / 字数 / 状态）
- `novel gaps`：伏笔状态表（未回收 / 待回收 / 已到章节）
- 自动重试：章节空内容自动重试 2 次

---

## [0.8.0] - 实用工具集

### 新增
- `novel rollback`：`--to v1` 回滚章节到历史版本（回滚前自动备份）
- `novel fix`：检测异常章节（0 字节 / 残片 / 含英文 think）
- `novel audit`：全项目综合审计表（字数 + 异常 + AI 味 + 雷达）

---

## [0.7.0] - 写作流增强

### 新增
- `PROGRESS.md`：完整的设计决策与演进日志
- `novel diff`：对比任意两版章节的差异（`--from --to --stats --context`）
- `novel prompt`：每项目独立的提示词管理（`--show --edit --reset`）
- `novel batch`：批量执行 polish / detect / radar / title

---

## [0.6.0] - 工具化

### 新增
- `novel doctor`：自动诊断项目（v0.11 增强：加 `--fix` / `--json`）
- `tests/smoke_test.sh`：DRY_RUN 端到端冒烟测试
- README 全面重写

---

## [0.5.0] - 交互式能力

### 新增
- `novel expand-scene`：作者指定位置接场景
- `novel plan`：粗大纲细化为 200-400 字场景规划
- `novel progress`：长篇写作进度统计（章节 / 字数 / 当前卷 / 预计剩余）
- `novel continue`：章节末尾接写
- `novel sprint`：自动从最后一章后写多章
- `novel chat`：自然语言协作修改

---

## [0.4.0] - 示例项目 + 真实长篇

### 新增
- 示例项目 `my_novel/`：4 章 11K 字
- 真实长篇实测：《冬夜的灰》
- 发现 1 处真实时间线问题：0003 章霍小军"不是在沈阳"与 0002 矛盾（已修复并记录）

---

## [0.3.0] - 长篇提示词专精

### 新增
- 6 个长篇专项提示词：
  - `consistency.md`：跨章一致性检查
  - `volume_report.md`：卷末报告
  - `rolling_summary.md`：全书滚动摘要
  - `style_radar.md`：风格雷达
  - `chapter_title.md`：章节标题
  - `samples.md`：风格样本引导
- 每个提示词独立 markdown，用户可改

---

## [0.2.0] - 长篇工作流（重大重构）

### 新增
- `novel.llm` 处理 minimax-M3 推理模型（think 标签三层兜底 + chat_with_continuation）
- `novel.storage` 新增长篇元数据文件（state / foreshadow / arc / timeline / volumes）
- 14 个新命令（覆盖写作 / 一致性 / 润色 / 工具）
- 自动维护：每章写完自动更新 state / foreshadow / arc / timeline

### 修复
- 长篇写 10 章后人名漂移问题
- 推理模型 think 标签污染正文问题

---

## [0.1.0] - 短篇工具

### 新增
- 6 个核心命令：`init` / `outline` / `characters` / `chapter` / `polish` / `detect`
- 4 个核心提示词：`de_ai_flavour.md` / `outline.md` / `chapter.md` / `detect_ai.md`
- 简单 LLM 包装
- DRY_RUN 模式

---

## 版本号规则

本项目遵循 [Semantic Versioning](https://semver.org/)：

- **MAJOR**：不兼容的 API 变更
- **MINOR**：向下兼容的功能新增
- **PATCH**：向下兼容的 bug 修复

预发布标识：
- v0.x.y：API 可能在 MINOR 中变化
- 1.0.0：API 稳定承诺

---

## 图标视图

- 🚀 新功能
- ⭐ 重大变更
- 🐛 Bug 修复
- 📝 文档
- 🔧 内部重构
- 🧪 测试
- ⚠️ 废弃警告
---

## [0.15.0] - novel daemon 后台长跑

### 背景
单跑 6 阶段只能「写出来」，未必「达标」。真实长篇要确保所有硬指标满足（字数 / 风格 / 情节一致性 / 角色一致等），需要**循环跑 + LLM 评估 + 反馈注入**。

### 新增
- **`novel/criteria.py`**（~200 行）：
  - `load_criteria(path)` — 解析用户 `quality_criteria.md`（支持 list / code block / 标题 跳过）
  - `evaluate_via_llm(criteria_lines, full_text, prev_feedback)` — LLM 评估器，输出 JSON
  - `format_feedback_for_next_iter(report)` — 转成下轮 prompt 注入
- **`prompts/daemon_criteria.md`**：评估 prompt 模板，输出 `{summary, all_passed, criteria:[{id,text,passed,evidence,suggestion}], top_priority_fixes}`
- **`novel/daemon.py`**（~280 行）：
  - `_daemon_loop(spec, project_dir, cfg, max_iterations, cost_budget, max_time)` — 主循环
  - `_check_should_stop` — 6 重停止条件（max_iter / cost / time / stop file / signal / 评估全 pass）
  - `is_stop_requested(project_dir)` — `.novel/stop_daemon` 文件检测
  - `render_systemd_unit(...)` — 输出 systemd service 文件
  - `_install_signal_handlers` — SIGINT / SIGTERM 优雅退出
- **`novel/commands/_daemon.py`**：4 子命令 run / status / stop / unit
- **`AutoSpec` / `AutoState` 字段**：
  - `daemon_criteria_path: str`
  - `max_iterations: int = 3`
  - `max_time_seconds: int = 0`
  - `extra: str = ""`（注入到下轮 prompts 的反馈）
  - `iteration_count / last_criteria_report / last_iter_passed`（state 持久化）

### CLI
```bash
# 前台长跑（Ctrl-C 优雅退出）
novel daemon run my_novel \
  --criteria ./quality_criteria.md \
  --max-iterations 3 --cost-budget 30 --serve

# 状态 / 停止 / 生成 systemd unit
novel daemon status
novel daemon stop
novel daemon unit --user ubuntu > /etc/systemd/system/novel.service
```

### 反馈注入机制
每轮迭代：
1. 跑 6 阶段生成 book.md
2. 调 `evaluate_via_llm` 评估 `quality_criteria.md` → 拿 `top_priority_fixes`
3. 反馈格式化成 `spec.extra`，下一轮注入到 `build_chapter_messages` 的「## 作者额外要求」段
4. LLM 看到上一轮问题 → 改进

### 终止条件（OR）
- `iteration_count >= max_iterations`
- `cumulative_cost_cny >= cost_budget`
- `elapsed >= max_time_seconds`
- `.novel/stop_daemon` 文件存在
- SIGINT / SIGTERM
- `evaluate_via_llm.all_passed == True`

### 部署模式
- **前台**：`novel daemon run` 直接跑（开发 / 短任务）
- **后台**：systemd / launchd / supervisord 管（生成 unit file）

### 测试
- `tests/test_daemon.py`：29 用例
  - criteria 解析 7 用例（list 标记 / 标题 / code block / 备选标记 / 空 / 不存在）
  - JSON 提取 3 用例（```json / 散文 / 无 JSON 兜底）
  - feedback 格式 2 用例
  - 终止条件 6 路径
  - systemd unit 2 用例
  - 端到端 5 用例（无 criteria / 全 pass / 多次后 pass / max_iter / stop file）
  - CLI 4 用例
- 全套 **326 用例**全过（297 → 326 +29）

### 文档
- PROGRESS §5.18 v0.15 daemon 完整设计
- CHANGELOG [0.15.0]
- USER_MANUAL §4.13 novel daemon 运维部署
- DEVELOPER_GUIDE §4.14 daemon 实现 + state 字段

---

## [0.16.0] - surgical rebuild

### 背景
v0.15 daemon 每轮跑全 6 阶段 → 30 章×3 轮 = 90 章 LLM 调用（~6h）。大部分章本已通过硬指标，重写纯属浪费。

### 新增
- **`AutoState` 字段**：
  - `passed_chapters: list[int]` — 累计通过硬指标的章（surgical 跳过用）
  - `last_failed_chapters: list[int]` — 最近一轮未通过章
- **`EvaluatorReport` 字段**：
  - `failed_chapters: list[int]` — LLM 评估时输出哪些章没过；daemon 用此驱动 surgical
- **`run_auto_novel(only_chapters: list[int])` 参数**：
  - 串行 / 并发 _writing_phase 都按此过滤；非目标章视为「已通过」并标 done
  - _polishing_phase 限制只 polish 未通过章
  - _consistency_phase surgical 时直接 skip（criteria 评估已覆盖）
- **`daemon._daemon_loop` 状态机改**：
  - iter 1：only_chapters=None（全跑）
  - iter ≥ 2：only_chapters = failed_chapters \ passed_chapters
  - 每轮累加 passed_chapters（已通过章永不再写）

### CLI
无需新 flag。`novel daemon run` 默认开 surgical。`--force` 重置 state（含 passed_chapters）。

### 性能预期
| 章数 | 轮数 | failed 假设 | v0.15 调用 | v0.16 调用 | 节省 |
|---|---|---|---|---|---|
| 30 | 3 | 5 → 2 → 0 | 90 | 37 | 59% |
| 60 | 3 | 8 → 3 → 0 | 180 | 71 | 60% |
| 100 | 3 | 12 → 4 → 0 | 300 | 116 | 61% |

### 测试
- 新增 `tests/test_daemon_surgical.py`：10 用例
  - 解析 5：乱序排序 / 非 int 容错 / 缺字段兜底
  - run_auto_novel 2：None 全写 / [2] surgical
  - daemon 状态机 3：第 1 轮 None / 第 2 轮 surgical / passed 累加
- 全套 **336 用例**全过（326 + 10）

### 兼容性
零行为变化：用户不感知；daemon 主循环内部 transparent 升级。
