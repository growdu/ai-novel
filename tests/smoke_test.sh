#!/usr/bin/env bash
# 冒烟测试：DRY_RUN 模式下完整跑一遍 CLI 验证
# 用法：在 ai_novel/ 目录下运行 ./tests/smoke_test.sh
set -e
cd "$(dirname "$0")/.."
ROOT=$(pwd)

echo "=== 1. 编译检查 ==="
python3 -c "
import py_compile
for f in ['novel_cli.py', 'novel/config.py', 'novel/llm.py', 'novel/storage.py', 'novel/prompts.py', 'novel/generator.py']:
    py_compile.compile(f, doraise=True)
print('  OK')
"

echo "=== 2. CLI 注册命令 ==="
python3 novel_cli.py --help 2>&1 | grep -E "│\\s+\\w" | wc -l | xargs -I {} echo "  注册命令数: {}"

echo "=== 3. 配置检查 ==="
if [ ! -f .env ]; then
    echo "  .env 缺失，复制 .env.example"
    cp .env.example .env
fi
python3 -c "from novel.config import load_global; cfg = load_global(); print('  base_url:', cfg.base_url, 'model:', cfg.model, 'temp:', cfg.temperature)"

echo "=== 4. DRY_RUN 完整流程 ==="
TESTDIR=/tmp/novel_smoke_$$
rm -rf $TESTDIR
DRY_RUN=true python3 novel_cli.py init $TESTDIR --title "测试" --theme "主题" --genre 现实 --words 50000 --style "测试"
cd $TESTDIR
DRY_RUN=true python3 $ROOT/novel_cli.py outline 2>&1 | tail -2
DRY_RUN=true python3 $ROOT/novel_cli.py characters 2>&1 | tail -2
DRY_RUN=true python3 $ROOT/novel_cli.py world 2>&1 | tail -2
DRY_RUN=true python3 $ROOT/novel_cli.py volumes 2>&1 | tail -2
DRY_RUN=true python3 $ROOT/novel_cli.py chapter 1 --iters 1 --no-polish 2>&1 | tail -2
DRY_RUN=true python3 $ROOT/novel_cli.py status 2>&1 | tail -3
DRY_RUN=true python3 $ROOT/novel_cli.py doctor 2>&1 | tail -3
cd $ROOT
rm -rf $TESTDIR

echo ""
echo "=== 冒烟测试完成 ==="
echo "如果你想实际跑一遍："
echo "  source .env  # 加载 minimax key"
echo "  novel init my_novel --title '...'"
echo "  cd my_novel && novel outline && novel characters && novel chapter 1"
