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
