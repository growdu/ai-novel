# 贡献指南

感谢你对 novel-writer 感兴趣！本文档介绍如何在本地搭建开发环境、提 PR、修改提示词。

---

## 🛠 开发环境

### 1. 克隆 & 安装

```bash
git clone <repo> ai-novel
cd ai-novel
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

`[dev]` 包含 pytest + pytest-cov + ruff。

### 2. 配置（可选）

```bash
cp .env.example .env
# 编辑 .env 填入 API key
```

没有 API key 也能开发，所有 LLM 调用支持 DRY_RUN 模式：

```bash
DRY_RUN=true novel chapter 1 --no-polish
```

### 3. 验证环境

```bash
pytest tests/ -v                   # 跑单测（103 个用例，应全过）
ruff check novel/ novel_cli.py tests/   # lint 检查
ruff format --check novel/ novel_cli.py tests/  # 格式检查
bash tests/smoke_test.sh           # DRY_RUN 端到端冒烟测试
```

---

## 📁 代码结构

```
novel-writer/
├── novel_cli.py        # CLI 入口（typer 命令注册在这里）
├── novel/
│   ├── __init__.py     # __version__
│   ├── config.py       # GlobalConfig + .env 加载
│   ├── storage.py      # Project + 章节读写 + 版本备份
│   ├── llm.py          # LLMClient + think 标签剥离 + chat_with_continuation
│   ├── prompts.py      # 提示词加载 + 消息构建 + 题材/文风匹配
│   ├── generator.py    # 主流程：写章节、人物、世界观、伏笔、弧线、时间线
│   └── diff_utils.py   # 章节版本对比
├── prompts/            # 28 个独立 markdown 提示词
├── tests/              # pytest 单测
├── examples/           # 示例项目（my_novel）
└── .github/            # CI 配置
```

---

## 🔧 常见修改场景

### A. 修改 / 新增提示词

1. 编辑 `prompts/<name>.md`
2. 如果新增文件，在 `prompts.py` 加一个 `lru_cache(maxsize=1)` 加载函数
3. 在消息构建函数中拼接使用
4. 单测：`tests/test_prompts.py::TestPromptCaching::test_all_prompts_loadable`

### B. 新增 CLI 命令

1. 在 `novel_cli.py` 用 `@app.command()` 装饰器加新函数
2. 提供 docstring（会被 Typer 自动用作 `--help`）
3. 提示性参数用 `typer.Option(..., help="...")`
4. 写入 / 删除章节必须用 `S.save_chapter()`，会自动备份旧版本
5. 加载项目用 `S.load_project()`，找不到会抛 `ProjectNotFoundError`
6. 危险操作（rollback / fix --no-dry）必须显示 diff 摘要 + Confirm 确认
7. 加单测到 `tests/test_cli.py`，用 `typer.testing.CliRunner`

### C. 新增题材 / 文风预设

1. 编辑 `prompts/genre_presets.md`（严肃向）或 `prompts/webnovel_genres.md`（网文）
2. 编辑 `prompts/style_presets.md` 或 `prompts/webnovel_style.md`
3. 每个预设用 `# 标题` 格式作为一级标题
4. 配套写：硬规则、作家参考、容易翻车的写法
5. 单测：`tests/test_prompts.py::TestPresetListing` 会自动验证列表长度

### D. 修复 bug

1. 在 `tests/` 加一个失败的测试用例复现
2. 修复代码
3. 跑 `pytest tests/` 确认全过
4. PR 描述里附 issue 编号

---

## ✅ 提交规范

### Commit 消息格式

参考 [Conventional Commits](https://www.conventionalcommits.org/)：

```
feat: 新功能简述
fix: bug 简述
docs: 文档修改
test: 加测试
refactor: 重构（不改变行为）
chore: 杂项
```

### PR 流程

1. Fork → 创建分支 `feature/<name>` 或 `fix/<name>`
2. 修改后跑 `pytest tests/` + `ruff check`
3. 必要时更新 `PROGRESS.md` 的版本日志（加新版本段落）
4. 必要时更新 `pyproject.toml` 的版本号
5. 提交 PR，附 `.github/pull_request_template.md` 的清单

---

## 🧪 测试规范

### 必须覆盖

- **核心数据路径**：存储读写、版本备份、字数统计
- **关键逻辑**：think 标签剥离三层兜底、Chat continuation 续写、JSON 解析
- **CLI 入口**：version / setup / init / doctor / status / 错误处理
- **题材/文风**：列表、精确匹配、模糊匹配、空输入

### 命名

- 文件：`tests/test_<module>.py`
- 类：`Test<Feature>`
- 方法：`test_<scenario>_<expected>`

### Mock 外部依赖

- LLM：用 DRY_RUN 模式（不调 API）
- 文件：用 `tmp_path` fixture
- 环境变量：用 `monkeypatch.setenv()` / `delenv()`

---

## 🎯 设计原则（修改前请先读）

1. **提示词即产品**：所有生成质量源自 markdown 提示词文件，优先改 markdown 而不是 Python 代码
2. **减法优于加法**：AI 味来自过度正确；新功能先想"是否会让模型更装"
3. **多轮迭代**：每章生成 → 检测 → 审稿 → 润色，新功能尽量保持这个闭环
4. **长篇需要长期记忆**：跨章机制（state / foreshadow / arc）不可破坏
5. **兼容任意 OpenAI 协议**：不绑定特定供应商

完整设计哲学见 [PROGRESS.md](PROGRESS.md) 第 2 节。

---

## 🐛 报告 Bug

提 Issue 时附：

- `novel --version` 输出
- Python 版本（`python --version`）
- 使用的模型（`OPENAI_MODEL`）
- 复现步骤
- 完整错误输出

模板见 `.github/ISSUE_TEMPLATE/bug_report.md`。

---

## 💡 新功能建议

PR 前最好先提 Issue 讨论：
- 这个功能解决什么问题？
- 是否能用现有命令 + `--option` 实现？
- 是否会影响 prompt 的简洁性？
- 是否会增加 API 调用次数？

---

## 📜 许可证

MIT License。提交 PR 即表示你同意以 MIT 协议贡献你的代码。