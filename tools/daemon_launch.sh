#!/usr/bin/env bash
# nohup 后台启动《第七界域》全量重写 daemon。
#
# 用法：
#   bash tools/daemon_launch.sh              # 启动
#   bash tools/daemon_launch.sh --stop       # 优雅停止（写 stop 文件）
#   bash tools/daemon_launch.sh --status     # 看状态
#   tail -f /tmp/novel-daemon.log            # 跟日志
set -uo pipefail

REPO=/home/ubuntu/ai-novel
PROJ="text/yuzhou_chuanshuo/第一部_第三秩序"
CRIT="$PROJ/.novel/criteria.md"
LOG=/tmp/novel-daemon.log
PIDF=/tmp/novel-daemon.pid

cd "$REPO" || exit 1

case "${1:-start}" in
  --stop)
    python3 novel_cli.py daemon stop "$PROJ"
    ;;
  --status)
    python3 novel_cli.py daemon status "$PROJ"
    ;;
  start)
    if [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; then
      echo "已在运行（PID $(cat "$PIDF")）。要重启请先 --stop。"
      exit 1
    fi
    nohup python3 novel_cli.py daemon run "$PROJ" \
      --criteria "$CRIT" \
      --max-iterations 3 \
      --cost-budget 30 \
      --max-time 172800 \
      --parallel 3 \
      --eval-batch-size 12 \
      --eval-overlap 4 \
      >>"$LOG" 2>&1 &
    echo $! >"$PIDF"
    echo "已启动 PID $(cat "$PIDF")"
    echo "日志: $LOG"
    echo "状态: bash tools/daemon_launch.sh --status"
    echo "停止: bash tools/daemon_launch.sh --stop"
    ;;
  *)
    echo "用法: $0 [start|--stop|--status]" >&2
    exit 2
    ;;
esac