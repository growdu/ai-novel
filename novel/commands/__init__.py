"""novel-writer 命令注册聚合（v0.13.x 模块化重构）。

把 novel_cli.py 的 50 个命令按功能切到 11 个子模块：
  _config.py    setup / config / version / prompt
  _presets.py   genres / styles / webnovel_genres / webnovel_styles / templates
  _init.py      init / write / webnovel_pack
  _run.py       auto / serve
  _planning.py  outline / characters / world / volumes
  _writing.py   chapter / continue / chat / expand_scene / title
  _qa.py        polish / detect / radar
  _state.py     timeline / volume_report / state / rolling / check / arc / foreshadow / gaps
  _project.py   list / info / whereami / status / audit / progress / history
  _diagnose.py  doctor / retry_stuck / rollback / fix / diff
  _output.py    export / index

novel_cli.py 只剩 ~30 行：thin entry。
"""
from __future__ import annotations

import typer

from . import (
    _adapt,
    _config,
    _diagnose,
    _init,
    _output,
    _planning,
    _presets,
    _project,
    _qa,
    _run,
    _state,
    _writing,
)


def register_all(app: typer.Typer) -> None:
    """把全部命令注册到给定 typer.Typer 实例。"""
    _config.register(app)
    _presets.register(app)
    _init.register(app)
    _run.register(app)
    _planning.register(app)
    _writing.register(app)
    _qa.register(app)
    _state.register(app)
    _project.register(app)
    _diagnose.register(app)
    _adapt.register(app)
    _output.register(app)


__all__ = ["register_all"]
