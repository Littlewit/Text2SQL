# 后端服务镜像（DEP-01）
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai

WORKDIR /app

# 先装依赖再拷贝代码，利用 Docker 层缓存
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

COPY . .

EXPOSE 8000

# 开发模式默认热重载；生产由 compose 覆盖 command 并关闭 --reload（DEP-08）
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
