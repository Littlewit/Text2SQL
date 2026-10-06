# Text2SQL Frontend

Vue 3 + TypeScript 单页应用：对话式数据查询（SSE 流式）、结果可视化、
查询历史/收藏/分享，以及管理后台与运营看板。

## 技术栈

- **Vue 3**（Composition API + `<script setup>`）+ **TypeScript**
- **Vue Router**（路由守卫：未登录跳转登录页）
- **Pinia**（用户状态）
- **Axios**（统一响应包络拦截器：业务码非 0 统一抛错、401 自动跳登录）
- **ECharts 5**（折线/柱状/饼图，按需初始化）
- **Vite** 构建（`vue-tsc` 类型检查）

## 页面

| 路由 | 视图 | 说明 |
|---|---|---|
| `/login` | LoginView | 登录（JWT） |
| `/` | ChatView | 对话查询：流式阶段反馈、四要素结果、图表一键切换（折线/柱状/饼/表格，零请求）、SQL 手工修正、口径反馈、建议追问、Excel 导出、打印/PDF |
| `/history` | HistoryView | 查询历史：详情回看（SQL/解释/假设/重试次数）、我的分享管理（撤销）、Excel 导出 |
| `/favorites` | FavoritesView | 收藏查询 |
| `/admin` | AdminView | 管理后台（R-DA/R-AD）：数据源接入与扫描、表/字段标注、指标/同义词/枚举/JOIN 路径、系统配置、样例库与反馈、行级权限、**运营看板**、**评测管理**（触发/报告/分维度对比） |

## 启动

```bash
npm install
npm run dev       # 开发服务器 http://localhost:5173（代理后端 8000，见 vite.config.ts）
npm run build     # vue-tsc 类型检查 + 产物构建
npm run preview   # 预览构建产物
```

后端地址默认 `http://localhost:8000`（见 `src/api/http.ts`）。

## 约定

- **响应包络**：所有接口返回 `{code, message, data}`，拦截器统一处理（见 `src/api/http.ts`）；
- **SSE 查询**：`POST /query` 以事件流返回 `stage/sql/result/chart/clarify/error/done`，
  逐事件更新对话气泡（见 `streamQuery`）；
- **图表切换**：切换类型调用 `POST /query/{id}/chart`，服务端基于缓存结果重建 option，零请求重查；
- **导出**：Excel 走 blob 下载；PDF 为服务端审计 + 浏览器打印通道。