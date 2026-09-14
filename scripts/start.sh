#!/bin/bash
# 定位脚本所在仓库，允许从任意目录启动；直接使用项目虚拟环境，无须手动 activate。
set -euo pipefail
# 脚本位于 scripts 目录，其上一级才是项目根目录。
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ ! -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
  echo "缺少项目虚拟环境 .venv，请先自行创建并安装后端依赖。" >&2
  exit 1
fi
exec "$PROJECT_ROOT/.venv/bin/python" "$PROJECT_ROOT/scripts/dev.py" "$@"
