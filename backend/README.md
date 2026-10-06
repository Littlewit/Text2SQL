# Text2SQL Backend

FastAPI 异步后端：自然语言 → 安全 SQL → 脱敏结果 → 图表配置的完整链路，
以及认证、权限、运营看板与评测管理。

## 技术栈

| 层 | 选型 |
|---|---|
| Web 框架 | FastAPI（异步，SSE 流式） |
| ORM / 迁移 | SQLAlchemy 2.0 (async) + Alembic |
| 数据库 | PostgreSQL 16 + pgvector（元数据库与向量检索同库） |
| 缓存 / 计数 | Redis（限流、每日配额；不可用自动降级内存后端） |
| LLM | DeepSeek Flash（OpenAI 兼容协议，`app/llm/` 适配层可替换） |
| SQL 校验 | sqlglot AST 白名单（`app/services/sql_guard/`） |
| 评测 | 自研 eval 框架（231 条用例，`eval/`） |
| 观测 | Prometheus `/metrics`、trace_id 中间件、结构化日志 |

## 目录结构

```text
app/
├── api/v1/          # 路由：auth、query(SSE)、extras(分享/收藏/导出)、admin/*(用户/数据源/配置/审计/标注/语义层/运营)
├── core/            # config(Pydantic Settings)、security(JWT/argon2)、credential(AES-GCM)、
│                    # rate_limit(QPS/并发)、quota(每日配额)、result_cache、deps、obs、errors
├── services/        # nlu(意图/时间解析)、schema_retrieval(混合检索)、prompt、sql_gen、
│                    # sql_guard、permission(行级改写)、masking、executor、visualization、
│                    # dashboard、cleanup、eval_service、audit
├── infra/           # ORM 模型（11 张业务表）与异步引擎
├── llm/             # LLM 客户端（熔断）与 Embedding（Hash/真模型）
└── workers/         # Celery 任务骨架（向量化）
eval/                # 评测框架：cases_v1.json(231 条)、runner、ex_utils、baseline.json
alembic/             # 迁移 0001~0010
scripts/             # demo_business.sql（示例库）、seed_eval_meta.py、seed_few_shots.py
tests/               # 单元（无外部依赖）+ 集成（真实 PG）
```

## 环境变量

完整清单见 `.env.example`，关键字段：

| 变量 | 说明 |
|---|---|
| `DEEPSEEK_API_KEY` | LLM 密钥（优先），兼容 `LLM_API_KEY`；未配置时走 FakeLLM 替身 |
| `METADATA_DB_URL` | 元数据库连接串（默认 `localhost:5433/text2sql_meta`） |
| `SECRET_KEY` | JWT 签名密钥，生产必须覆盖 |
| `EMBEDDING_MODEL` / `EMBEDDING_DIM` | Embedding 模型与维度（默认 1024） |

## 进入环境

```bash
cd backend

# Windows（PowerShell）
python -m venv .venv
.venv\Scripts\activate          # 激活后命令行前缀出现 (.venv)

# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate
```

- 激活后 `python` / `pip` 即指向虚拟环境，无需再写 `.venv\Scripts\python`；
- 退出虚拟环境：`deactivate`；
- 依赖安装与所有命令（alembic / pytest / eval 等）均在**激活状态**下执行；
- IDE（VS Code / PyCharm）选择解释器为 `backend/.venv` 即可自动激活。

> 不激活也可以用完整路径调用：`.venv\Scripts\python -m pytest ...`（Windows）或
> `.venv/bin/python -m pytest ...`（Linux），效果等价。

## 启动

```bash
# （进入虚拟环境后）
pip install -e ".[dev]"
alembic upgrade head      # 迁移（首次自动启用 pgvector）
python run.py             # 统一入口（Windows 事件循环兼容处理）
```

- API 前缀 `/api/v1`，交互式文档 `/docs`（`DEBUG=false` 时关闭）
- 健康探针：`/api/v1/healthz`（存活）、`/api/v1/readyz`（依赖 DB 可达）
- Prometheus 指标：`/metrics`

## 测试与质量门禁

```bash
pytest -m "not integration"                    # 单元测试（80 条，无外部依赖）
pytest -m integration                          # 集成测试（57 条，需 Docker 真实 PG）
pytest -m "not integration" --cov=app --cov-append
pytest -m integration --cov=app --cov-append --cov-fail-under=70   # 覆盖率门禁（实测 75.7%）
ruff check .
```

## 评测

```bash
python -m eval.run --offline              # 离线安全类别（CI 红线 100%）
python -m eval.run                        # 全量 231 条（真实 LLM，与 baseline.json 对比）
python -m eval.run --kinds sql_exec,recall
python -m eval.run --gate                 # 全量跑通后写入新基线
```

当前基线 **97.4%**（安全/召回/拒答/时间解析 100%，EX 95%+，意图 88%）。

## 关键设计约定

- **零信任 LLM**：生成 SQL 必过 AST 白名单 → 行级权限改写 → 复验 → 只读执行 → 服务端统一脱敏；
- **CMP-02 红线**：Prompt 只含 Schema 元数据/指标口径/样例 SQL/问题文本，禁止真实数据行；
- **响应包络**：统一 `{code, message, data}`，业务错误码见 `app/core/errors.py`；
- **种子脚本幂等**：重复执行不产生重复数据；数据源须先在管理后台接入并扫描。