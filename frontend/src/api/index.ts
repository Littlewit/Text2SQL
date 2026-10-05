import axios from 'axios'

// 统一 HTTP 客户端：响应包络 { code, message, data, trace_id }（§5.1）
export const http = axios.create({ baseURL: '/api/v1', timeout: 60_000 })

http.interceptors.request.use((cfg) => {
  const token = localStorage.getItem('t2s_token')
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  return cfg
})

http.interceptors.response.use(
  (resp) => resp,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('t2s_token')
      localStorage.removeItem('t2s_user')
      if (!location.pathname.startsWith('/login')) location.href = '/login'
    }
    return Promise.reject(err)
  },
)

export interface UserInfo { id: number; username: string; roles: string[]; must_change_password: boolean }

export async function login(username: string, password: string): Promise<UserInfo> {
  const { data } = await http.post('/auth/login', { username, password })
  localStorage.setItem('t2s_token', data.data.token)
  localStorage.setItem('t2s_user', JSON.stringify(data.data.user))
  return data.data.user
}

export function logout() {
  http.post('/auth/logout').catch(() => {})
  localStorage.removeItem('t2s_token')
  localStorage.removeItem('t2s_user')
}

export function currentUser(): UserInfo | null {
  const raw = localStorage.getItem('t2s_user')
  return raw ? JSON.parse(raw) : null
}

// ---------- 查询 ----------
export interface QueryResult {
  query_id: number
  exec_status: string
  result: { columns: string[]; rows: unknown[][]; row_count: number; truncated: boolean } | null
  chart: { chart_type: string; reason: string; option: unknown } | null
}

export interface QueryEvent { event: string; data: Record<string, unknown> }

/**
 * SSE 流式查询（FR-UI-05）：POST 不能用 EventSource，用 fetch 读流并解析 SSE 帧。
 * onEvent 回调按到达顺序收 stage/clarify/sql/result/chart/error/done。
 */
export async function streamQuery(
  body: { question: string; conversation_id: number; datasource_id: number },
  onEvent: (e: QueryEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const token = localStorage.getItem('t2s_token')
  const resp = await fetch('/api/v1/query/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
    signal,
  })
  if (!resp.ok || !resp.body) {
    const err = await resp.json().catch(() => ({ message: '请求失败' }))
    throw new Error(err.message || `HTTP ${resp.status}`)
  }
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const frames = buffer.split('\n\n')
    buffer = frames.pop() ?? ''
    for (const frame of frames) parseFrame(frame, onEvent)
  }
}

function parseFrame(frame: string, onEvent: (e: QueryEvent) => void) {
  let event = 'message'
  let data = ''
  for (const line of frame.split('\n')) {
    if (line.startsWith('event: ')) event = line.slice(7).trim()
    else if (line.startsWith('data: ')) data += line.slice(6)
  }
  if (!data) return
  try { onEvent({ event, data: JSON.parse(data) }) } catch { /* 忽略非 JSON 心跳帧 */ }
}

// ---------- 常规 REST ----------
export const getConversations = () => http.get('/conversations').then((r) => r.data.data)
export const createConversation = (title?: string) => http.post('/conversations', { title }).then((r) => r.data.data)
export const getMessages = (id: number) => http.get(`/conversations/${id}/messages`).then((r) => r.data.data)
export const getHistory = (page = 1) => http.get('/history', { params: { page } }).then((r) => r.data.data)
export const getFavorites = () => http.get('/favorites').then((r) => r.data.data)
export const createFavorite = (body: Record<string, unknown>) => http.post('/favorites', body).then((r) => r.data.data)
export const deleteFavorite = (id: number) => http.delete(`/favorites/${id}`).then((r) => r.data)
export const runFavorite = (id: number) => http.post(`/favorites/${id}/run`).then((r) => r.data.data)
export const getFollowups = (queryId: number) =>
  http.get('/suggest/followups', { params: { query_id: queryId } }).then((r) => r.data.data.suggestions as string[])
export const exportQuery = (queryId: number) =>
  http.post(`/query/${queryId}/export`, null, { responseType: 'blob' }).then((r) => r.data as Blob)
export const createShare = (body: Record<string, unknown>) => http.post('/shares', body).then((r) => r.data.data)
// M2-T1：反馈与样例库
export const createFeedback = (queryId: number, body: Record<string, unknown>) =>
  http.post(`/query/${queryId}/feedback`, body).then((r) => r.data.data)
export const getPendingFeedbacks = () => http.get('/admin/feedbacks').then((r) => r.data.data)
export const reviewFeedback = (id: number, approve: boolean) =>
  http.post(`/admin/feedbacks/${id}/review?approve=${approve}`).then((r) => r.data.data)
export const getFewShots = (status?: number) =>
  http.get('/admin/few-shots', { params: status !== undefined ? { status } : {} }).then((r) => r.data.data)
export const createFewShot = (body: Record<string, unknown>) => http.post('/admin/few-shots', body).then((r) => r.data.data)
export const reviewFewShot = (id: number, approve: boolean) =>
  http.post(`/admin/few-shots/${id}/review?approve=${approve}`).then((r) => r.data.data)
export const deleteFewShot = (id: number) => http.delete(`/admin/few-shots/${id}`).then((r) => r.data)
export const getUncaptured = () => http.get('/admin/uncaptured').then((r) => r.data.data)
// M2-T4：图表切换 / 历史详情 / PDF / 分享管理
export const switchChart = (queryId: number, chartType: string) =>
  http.post(`/query/${queryId}/chart`, { chart_type: chartType }).then((r) => r.data.data)
export const getHistoryDetail = (queryId: number) =>
  http.get(`/history/${queryId}`).then((r) => r.data.data)
export const auditPdfExport = (queryId: number) =>
  http.post(`/query/${queryId}/export/pdf`).then((r) => r.data)
export const getMyShares = () => http.get('/my-shares').then((r) => r.data.data)
export const revokeShare = (id: number) => http.delete(`/shares/${id}`).then((r) => r.data)
// M2-T5：运营看板与清理
export const getOpsDashboard = (days: number) =>
  http.get('/admin/ops/dashboard', { params: { days } }).then((r) => r.data.data)
export const runOpsCleanup = (dryRun: boolean) =>
  http.post('/admin/ops/cleanup', { dry_run: dryRun }).then((r) => r.data.data)
// M2-T6：评测管理
export const runEval = (mode: 'offline' | 'full') =>
  http.post('/admin/ops/eval/run', { mode }).then((r) => r.data.data)
export const getEvalReports = () =>
  http.get('/admin/ops/eval/reports').then((r) => r.data.data)
export const getEvalCompare = (a: number, b: number) =>
  http.get('/admin/ops/eval/compare', { params: { a, b } }).then((r) => r.data.data)
// M2-T3：行级权限策略
export const getRowPolicies = (dsId?: number) =>
  http.get('/admin/row-policies', { params: dsId ? { datasource_id: dsId } : {} }).then((r) => r.data.data)
export const createRowPolicy = (body: Record<string, unknown>) => http.post('/admin/row-policies', body).then((r) => r.data.data)
export const deleteRowPolicy = (id: number) => http.delete(`/admin/row-policies/${id}`).then((r) => r.data)

// ---------- 管理台 ----------
export const getDatasources = () => http.get('/admin/datasources').then((r) => r.data.data)
export const createDatasource = (body: Record<string, unknown>) => http.post('/admin/datasources', body).then((r) => r.data.data)
export const testDatasource = (id: number) => http.post(`/admin/datasources/${id}/test`).then((r) => r.data.data)
export const scanDatasource = (id: number) => http.post(`/admin/schema/datasources/${id}/scan`).then((r) => r.data.data)
export const getTables = (dsId: number) => http.get('/admin/schema/tables', { params: { datasource_id: dsId } }).then((r) => r.data.data)
export const getColumns = (tableId: number) => http.get(`/admin/schema/tables/${tableId}/columns`).then((r) => r.data.data)
export const annotateTable = (id: number, body: Record<string, unknown>) => http.patch(`/admin/schema/tables/${id}`, body).then((r) => r.data.data)
export const getMetrics = () => http.get('/admin/metrics').then((r) => r.data.data)
export const createMetricApi = (body: Record<string, unknown>) => http.post('/admin/metrics', body).then((r) => r.data.data)
export const getConfigs = () => http.get('/admin/configs').then((r) => r.data.data)
export const patchConfig = (key: string, value: unknown) => http.patch(`/admin/configs/${key}`, { value }).then((r) => r.data.data)
export const schemaSearch = (query: string, datasourceId?: number) =>
  http.post('/admin/schema/search', { query, datasource_id: datasourceId }).then((r) => r.data.data)
