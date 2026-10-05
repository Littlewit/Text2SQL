#!/bin/sh
# 后端容器入口（DEP-07）：先执行数据库迁移（幂等），再启动服务
set -e
echo "[entrypoint] running migrations..."
python -m alembic upgrade head
echo "[entrypoint] starting app..."
exec python run.py
