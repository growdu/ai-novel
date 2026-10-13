# Novel Writer —— AI 写小说 CLI
基于大模型（默认 minimax-M3，兼容 OpenAI Chat Completions 协议）的小说自动创作工具。
核心目标：把大纲、主题、人物、字数、文风交给程序，让它自己出稿，并通过多轮审稿与润色，最大程度减少 AI 味。

## 能力速览（25 个命令）
| 类别 | 命令 |
|---|---|
| 基础 | init / status / config / progress / doctor |
| 规划 | outline / characters / world / volumes / plan |
| 写作 | chapter / write / sprint / continue / chat / expand-scene |
| 润色 | polish / detect / radar |
| 一致性 | check / timeline / state / rolling / foreshadow / arc / volume-report / title / history |

## 特性
- **真实长篇工作流**：20 万字长篇已实测（7 章 50K 字 + 自动维护 state / foreshadow / arc / timeline / title）
- **题材/文风系统**：10 个题材预设（玄幻/仙侠/科幻/悬疑/言情/历史/武侠/都市/校园/现实）
  + 11 个文风预设（搞笑/轻松/伤感/诗意/冷峻/热烈/朴素/华丽/紧张/黑色幽默/儿童）
  每个预设都自动注入硬规则和作家参考
- **minimax-M3 适配**：处理推理模型 think 标签，chat_with_continuation 自动续写避免截断
- **去 AI 味道**：6 维度风格雷达量化（与样本相似度 86+）
- **跨章一致性**：自动检测人物名 / 时间 / 地点 / 设定漂移
- **可移植**：兼容任意 OpenAI 协议（OpenAI / DeepSeek / 智谱 / 通义）
- **DRY_RUN 模式**：不调 API 完整打印提示词
# 特性
- 完整工作流：init / outline / characters / chapter / write / polish / detect / status
- 去 AI 味优先：核心提示词 de_ai_flavour.md 是项目灵魂，明确列出禁用表达、写作原则、作家风格参考
- 多轮迭代：每章默认跑"生成 检测 审稿 润色"循环
- 可控：所有提示词都是 markdown 文件，用户可自行改写
- 可移植：兼容 minimax / OpenAI / DeepSeek 等任意 OpenAI 协议 API
- DRY_RUN 模式：不调用 API，只打印提示词，方便本地调试
# 5 分钟上手
## 安装
```bash
cd /root/ai_novel
pip install -r requirements.txt
```
## 配置 API
复制 .env.example 为 .env 并填入：
```env
OPENAI_BASE_URL=https://api.minimaxi.com/v1
OPENAI_API_KEY=你的key
OPENAI_MODEL=minimax-Text-01
```
也可以用 novel config --api-key xxx --model xxx 临时设置，或者直接用环境变量。
## 写你的第一本书
```bash
novel init my_novel --title "冬夜的灰" --theme "1995 年东北小镇的命案与四个孩子" --genre 悬疑 --words 60000 --style "致敬双雪涛的北方叙事"
cd my_novel
novel outline
novel characters
novel chapter 1
novel write --start 1 --end 5
novel polish 1
novel detect 1 --save
novel status
```
## 命令一览
基础：
- novel init 创建新项目
- novel status 查看项目状态
- novel config 查看或修改全局配置
- DRY_RUN=true novel ... 不调用 API，只打印提示词

规划（建议顺序）：
- novel outline 生成或重写大纲
- novel characters 生成或扩展人物志
- novel world 生成世界观
- novel volumes 长篇分卷（5 卷结构 + 起止章节）
- novel plan N 细化第 N 章大纲（200-400 字场景规划）

写作：
- novel chapter N 写第 N 章（写完自动维护 state/foreshadow/arc/title）
- novel write -s 1 -e 5 连续写 1-5 章
- novel sprint --count 10 自动从最后一章后写 10 章
- novel continue N --with '意图' 在第 N 章末尾接写一段
- novel chat N '自然语言指令' 协作修改某章

协作润色：
- novel polish N 对第 N 章做去 AI 味润色（基于 detect+review 反馈）
- novel detect N 只检测第 N 章 AI 味
- novel expand-scene N --after '句子' --with '意图' 在指定位置接场景
- novel radar N 风格雷达：6 维度量化与 samples 的相似度

长篇一致性：
- novel timeline 维护故事内时间线（含冲突预警）
- novel state 维护故事状态摘要（最近 3 章压缩）
- novel rolling 全书滚动摘要（每 5 章自动更新）
- novel foreshadow 维护伏笔簿（F1-Fn 编号）
- novel arc 维护人物弧线
- novel check 跨章节一致性检查
- novel volume-report --volume N 第 N 卷卷末报告
- novel title N 为第 N 章生成标题

管理：
- novel history 查看所有章节的版本历史
- novel diff <chapter> 对比任意两版章节
- novel rollback <chapter> --to v1 把当前章节回滚到 v1
- novel fix <chapter> 检测异常章节（0 字节 / 残片）
- novel prompt <name> --show/--edit/--reset 查看编辑项目提示词
- novel batch <action> 批量执行 polish/detect/radar/title
# 去 AI 味的设计哲学
工具能做的只是把"好作家会规避的事情"显式写进提示词，再让模型自检。核心文件是 prompts/de_ai_flavour.md，主要做了这几件事：
1. 禁用表达清单：列了 20 多种典型 AI 句式作为强禁止。
2. 写作原则：场景先于心理、对话是人话、留白、不完美的角色、节奏紧凑。
3. 作家风格参考：老舍、双雪涛、汪曾祺、余华等具体作家，让模型有具体模仿对象而不是泛泛说"文笔流畅"。
4. 每章自检清单：模型写完后必须自检 AI 味。
5. 多轮迭代：detect 到 review 到 polish，每轮把"问题清单"作为下一轮 prompt 的一部分。
# 长篇小说工作流
项目初始化后推荐顺序：
1. novel outline 生成大纲（20 万字 → 约 60-70 章）
2. novel characters 生成人物志
3. novel world 生成世界观（地理、历史、社会、硬规则）
4. novel volumes 长篇分卷（每卷核心冲突、节奏、卷末状态）
5. novel chapter 5 6 7 ... 逐章写
6. novel write --start 10 --end 15 连续写
每章写完会自动维护 state、foreshadow、arc 等。
关键操作：
- novel timeline 维护时间线（自动检测冲突）
- novel check 跨章节一致性检查
- novel volume-report --volume N 第 N 卷卷末报告
- 把 samples/ 目录放上你喜欢的风格片段，模型会自动模仿
# 风格样本（few-shot）
项目下 .novel/samples/ 目录里放 1-3 个 .md 文件，每个文件 200-1500 字。
模型会在写每章时自动随机抽 1-2 段作为风格参考。
文件命名建议用数字（01.md、02.md），方便排序。

# 自定义提示词
所有提示词位于 prompts/ 目录：
- de_ai_flavour.md 去 AI 味的总规则，所有任务都会加载它
- outline.md 大纲生成
- character.md 人物志生成
- chapter.md 单章生成
- detect_ai.md AI 味检测
- polish.md 润色重写
- review.md 审稿
你可以直接修改这些 markdown。例如：
- 在 de_ai_flavour.md 第 4 节添加你喜欢的作家
- 在 polish.md 里加重你想要的润色策略
- 在 chapter.md 里调整开篇要求
# 项目目录结构
my_novel/.novel/project.yaml，
                outline.md，
                characters.md，
                style.md，
                chapters/0001.md 等，
                history/旧版本，
                reports/AI 味检测报告。
# 进阶：作为库使用
```python
from novel.config import GlobalConfig
from novel.llm import LLMClient
from novel import prompts as P
cfg = GlobalConfig()
client = LLMClient(cfg)
msgs = P.build_chapter_messages(...)
result = client.chat(msgs, temperature=0.95)
print(result.content)
```
# 常见问题
Q：必须用 minimax 吗？
A：不是。任意兼容 OpenAI Chat Completions 协议的 API 都能用。改 OPENAI_BASE_URL 和 OPENAI_MODEL 即可切换到 OpenAI / DeepSeek / 智谱 / 通义千问 等。
Q：DRY_RUN 模式是做什么的？
A：不真正调用 API，把将发送给模型的提示词完整打印到终端。用来调提示词或者学习怎么写提示词非常方便。
Q：怎么让小说更像某个作家？
A：在 init 时通过 --style 指定文风，或直接编辑 .novel/style.md。例如 --style "致敬汪曾祺的《受戒》，短句、留白、淡墨"。
Q：一章默认生成多少字？
A：默认 3000 字（在 .env 中通过 TARGET_CHAPTER_WORDS 配置）。模型会按目标字数的 75% 到 95% 输出，宁可少写不灌水。
Q：怎么扩展提示词？
A：在 prompts/ 目录添加新的 .md 文件，然后在 novel/prompts.py 里用 lru_cache 加载，或者修改现有提示词。
