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