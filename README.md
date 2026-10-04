# Text2SQL 智能数据分析平台

用自然语言查询数据库并生成图表的智能数据分析平台。

- 需求文档：`.codebuddy/docs/Text2SQL 智能数据分析平台 - 详细需求文档.md`
- 系统设计：`.codebuddy/docs/Text2SQL 智能数据分析平台 - 系统设计.md`
- 任务计划：`.codebuddy/plans/下一步任务计划.md`

## 技术栈

后端 Python + FastAPI + SQLAlchemy 2.0（async）+ Celery；AI：LangChain + DeepSeek；
向量检索 pgvector；数据库全环境统一 PostgreSQL（不使用 SQLite）；前端 Vue3 + TS + Pinia + ECharts；部署 Docker Compose。

## 快速开始（开发环境）

前置条件：Docker Desktop（数据库必须走 Docker，ENV-01）、Python 3.10+、Node 18+。

```powershell
# 1. 启动基础设施 + 后端（首次会自动构建镜像）
docker compose -f docker-compose.dev.yml up -d

# 2. 健康检查
curl http://localhost:8000/api/v1/healthz

# 3. 执行数据库迁移（启用 pgvector 扩展等）
cd backend
pip install -e ".[dev]"
alembic upgrade head

# 4. 启动前端开发服务器（另开终端）
cd ../frontend
npm install
npm run dev   # http://localhost:5173
```

## 后端本地运行（不进容器）

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
copy .env.example .env   # 按需修改
python run.py            # 统一入口（处理 Windows 事件循环兼容性）
```

## 测试

```powershell
cd backend
pytest -m "not integration" -v   # 单元测试，无外部依赖
ruff check .                      # 代码检查
```

## 目录结构

```text
backend/    后端（FastAPI），分层见系统设计 §2.3
frontend/   前端（Vue3 + Vite）
.codebuddy/ 需求/设计/计划文档（不纳入版本管理）
```

## 文档接口

开发模式（DEBUG=true）下访问 `http://localhost:8000/docs`；生产环境关闭（DEP-08）。
