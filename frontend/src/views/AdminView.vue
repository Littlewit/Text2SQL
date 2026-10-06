<script setup lang="ts">
// 管理后台（FR-ADM-02/03/05 精简版）：数据源接入与扫描、表标注、指标、系统配置
import { onMounted, ref, watch } from 'vue'
import {
  annotateTable, createDatasource, createFewShot as createFewShotApi, deleteFewShot as deleteFewShotApi,
  getColumns, getConfigs, getDatasources, getEvalCompare, getEvalReports, getFewShots, getMetrics,
  getOpsDashboard, getPendingFeedbacks, getTables, getUncaptured, patchConfig,
  reviewFeedback as reviewFeedbackApi, runEval, runOpsCleanup, scanDatasource, testDatasource,
} from '../api'

type Tab = 'datasource' | 'schema' | 'metric' | 'config' | 'fewshot' | 'uncaptured' | 'rowpolicy' | 'ops' | 'eval'
const tab = ref<Tab>('datasource')
const msg = ref('')

// el-tabs 切换时触发懒加载（原按钮 click 逻辑迁移至此）
watch(tab, (t) => {
  if (t === 'fewshot' || t === 'rowpolicy') loadFewShots()
  if (t === 'ops') loadDashboard()
  if (t === 'eval') loadEvalReports()
})

// 运营看板（FR-ADM-06，M2-T5）
interface Dash {
  summary: { total: number; success_rate: number; avg_duration_ms: number; retry_rate: number; clarify: number; refused: number; llm_tokens: number }
  duration_buckets: Record<string, number>
  top_questions: [string, number][]
  top_failures: [string, number][]
}
const dash = ref<Dash | null>(null)
const dashboardDays = ref(7)
const cleanupMsg = ref('')

async function loadDashboard() {
  try {
    dash.value = await getOpsDashboard(dashboardDays.value)
    cleanupMsg.value = ''
  } catch { /* 无权限或网络错误时静默 */ }
}

async function runCleanup() {
  try {
    const dry = await runOpsCleanup(true)
    if (!confirm(`预检：审计 ${dry.audit_to_delete} 条、历史 ${dry.history_to_delete} 条将被清理，确认执行？`)) return
    const real = await runOpsCleanup(false)
    cleanupMsg.value = `已清理审计 ${real.audit_to_delete} 条、历史 ${real.history_to_delete} 条`
  } catch { cleanupMsg.value = '清理失败（仅管理员）' }
}

// 评测管理（FR-ADM-07，M2-T6）
interface EvalRun { id: number; mode: string; status: string; total: number; passed: number; failed: number; skipped: number; pass_rate: number; model_version: string | null; created_at: string }
interface CmpResult {
  a: { id: number; pass_rate: number; created_at: string }
  b: { id: number; pass_rate: number; created_at: string }
  overall_diff: number
  by_tag: Record<string, { a: number; b: number; diff: number }>
}
const evalReports = ref<EvalRun[]>([])
const evalMsg = ref('')
const cmpB = ref(0)
const cmpResult = ref<CmpResult | null>(null)
const detailTags = ref<Record<string, { total: number; passed: number }> | null>(null)
const detailId = ref(0)

async function loadEvalReports() {
  try {
    evalReports.value = await getEvalReports()
  } catch { /* 无权限静默 */ }
}

async function triggerEval(mode: 'offline' | 'full') {
  try {
    if (!confirm(mode === 'full' ? '全量评测将调用真实 LLM（产生费用、耗时数分钟），继续？' : '触发离线评测？')) return
    const { run_id } = await runEval(mode)
    evalMsg.value = `评测 #${run_id} 已启动，列表将自动刷新…`
    // 轮询刷新列表直到该任务完成
    const timer = setInterval(async () => {
      await loadEvalReports()
      const run = evalReports.value.find((r) => r.id === run_id)
      if (run && run.status !== 'running') {
        clearInterval(timer)
        evalMsg.value = `评测 #${run_id} ${run.status === 'done' ? '完成' : '失败'}：通过率 ${(run.pass_rate * 100).toFixed(1)}%`
      }
    }, 3000)
  } catch (e: unknown) {
    evalMsg.value = `触发失败：${(e as Error).message}`
  }
}

function sign(v: number): string {
  return (v >= 0 ? '+' : '') + (v * 100).toFixed(1) + '%'
}

async function doCompare(a: number) {
  try {
    cmpResult.value = await getEvalCompare(a, cmpB.value)
  } catch { evalMsg.value = '对比失败' }
}

async function evalDetail(id: number) {
  const d = await import('../api').then((m) => m.http.get(`/admin/ops/eval/reports/${id}`).then((r) => r.data.data))
  detailId.value = id
  detailTags.value = d.by_tag ?? {}
}

// 数据源
const dss = ref<{ id: number; name: string; host: string; db_name: string; status: number }[]>([])
const dsForm = ref({ name: '', host: 'localhost', port: 5433, db_name: '', readonly_user: 't2s', password: '' })

// Schema 标注
const selectedDs = ref(0)
const scanning = ref(false)
const tables = ref<{ id: number; table_name: string; cn_name: string | null; included: boolean; annotation_score: number }[]>([])
const selectedTable = ref(0)
const columns = ref<{ id: number; column_name: string; cn_name: string | null; description: string | null }[]>([])

// 指标
const metrics = ref<{ id: number; name: string; code: string; description: string | null; unit: string | null }[]>([])
const metricForm = ref({ name: '', code: '', description: '', unit: '' })

// 配置
const configs = ref<{ key: string; value: unknown; description: string | null }[]>([])

// M2-T1：待审核反馈 / 样例库 / 未覆盖问题
const feedbacks = ref<{ id: number; rating: string; correction_sql: string | null; comment: string | null }[]>([])
const fewShots = ref<{ id: number; question: string; sql_text: string; status: number; hit_count: number }[]>([])
const fewShotForm = ref({ question: '', sql_text: '', explanation: '' })
const uncaptured = ref<{ items: { question: string; count: number; statuses: string[] }[]; total_uncovered: number }>()

// M2-T3：行级权限策略
const rowPolicies = ref<{ id: number; table_meta_id: number; filter_template: string; apply_to_role_ids: string[]; combine_mode: string; enabled: boolean }[]>([])
const policyForm = ref({ table_meta_id: 0, filter_template: '', apply_to_role_ids: 'R-BIZ', combine_mode: 'union' })

async function loadAll() {
  dss.value = await getDatasources()
  if (dss.value.length && !selectedDs.value) selectedDs.value = dss.value[0].id
  metrics.value = await getMetrics()
  configs.value = await getConfigs()
}

async function loadFewShots() {
  const [{ getFewShots, getPendingFeedbacks, getUncaptured, getRowPolicies }] = await Promise.all([import('../api')])
  fewShots.value = await getFewShots()
  feedbacks.value = await getPendingFeedbacks()
  uncaptured.value = await getUncaptured()
  rowPolicies.value = await getRowPolicies()
}

async function addRowPolicy() {
  const { createRowPolicy } = await import('../api')
  await createRowPolicy({
    datasource_id: selectedDs.value, table_meta_id: policyForm.value.table_meta_id,
    filter_template: policyForm.value.filter_template,
    apply_to_role_ids: policyForm.value.apply_to_role_ids.split(',').map((s) => s.trim()),
    combine_mode: policyForm.value.combine_mode,
  })
  msg.value = '策略已创建，对新查询立即生效（FR-SEC-13）'
  await loadFewShots()
}

async function delRowPolicy(id: number) {
  const { deleteRowPolicy } = await import('../api')
  await deleteRowPolicy(id)
  await loadFewShots()
}

async function reviewFeedback(id: number, approve: boolean) {
  await reviewFeedbackApi(id, approve)
  msg.value = '已审核，采纳的纠错将自动转为样例'
  await loadFewShots()
}

async function addFewShot() {
  await createFewShotApi({ ...fewShotForm.value, datasource_id: selectedDs.value || null })
  msg.value = '样例已录入（待审核），审核启用后参与召回'
  fewShotForm.value = { question: '', sql_text: '', explanation: '' }
  await loadFewShots()
}

async function delFewShot(id: number) {
  await deleteFewShotApi(id)
  await loadFewShots()
}

async function addDatasource() {
  msg.value = ''
  try {
    const ds = await createDatasource(dsForm.value)
    const test = await testDatasource(ds.id)
    ElMessage.success(`接入成功，连通性测试：${test.ok}（${test.latency_ms}ms）`)
    await loadAll()
  } catch (e: unknown) {
    ElMessage.error((e as { response?: { data?: { message?: string } } }).response?.data?.message ?? '接入失败')
  }
}

async function scan() {
  scanning.value = true
  try {
    const stats = await scanDatasource(selectedDs.value)
    ElMessage.success(`扫描完成：${stats.tables} 表 / ${stats.columns} 字段（新增 ${stats.new_tables}/${stats.new_columns}）`)
    await loadTables()
  } catch (e: unknown) {
    ElMessage.error((e as { response?: { data?: { message?: string } } }).response?.data?.message ?? '扫描失败')
  } finally {
    scanning.value = false
  }
}

async function loadTables() {
  tables.value = await getTables(selectedDs.value)
}

async function pickTable(id: number) {
  selectedTable.value = id
  columns.value = await getColumns(id)
}

async function saveAnnotation(t: { id: number; cn_name: string | null; table_name?: string }) {
  await annotateTable(t.id, { cn_name: t.cn_name, included: true })
  ElMessage.success(`已保存并重新向量化：${t.table_name ?? t.id}`)
  await loadTables()
}

async function saveMetric() {
  await getMetrics // 引用避免未用告警
  const { createMetricApi } = await import('../api')
  await createMetricApi(metricForm.value)
  metrics.value = await getMetrics()
  ElMessage.success('指标已创建并向量化')
}

async function saveConfig(c: { key: string; value: unknown }) {
  await patchConfig(c.key, c.value)
  ElMessage.success(`配置 ${c.key} 已更新（留痕审计）`)
}

// el-table 作用域槽的 row 为 DefaultRow，包一层避免模板内类型断言
function saveConfigRow(row: Record<string, unknown>) {
  return saveConfig(row as unknown as { key: string; value: unknown })
}
</script>

<template>
  <div class="page">
    <div class="topbar">
      <h1 style="font-size: 1.2rem; margin: 0">管理后台</h1>
      <router-link to="/" class="back">
        <el-button size="small" text type="primary">← 返回对话</el-button>
      </router-link>
    </div>
    <el-tabs :model-value="tab" @tab-change="(name: string | number) => tab = name as Tab">
      <el-tab-pane label="数据源" name="datasource" />
      <el-tab-pane label="表标注" name="schema" />
      <el-tab-pane label="指标" name="metric" />
      <el-tab-pane label="系统配置" name="config" />
      <el-tab-pane label="样例库与反馈" name="fewshot" />
      <el-tab-pane label="行级权限" name="rowpolicy" />
      <el-tab-pane label="运营看板" name="ops" />
      <el-tab-pane label="评测" name="eval" />
    </el-tabs>
    <p v-if="msg" class="msg">{{ msg }}</p>

    <!-- 运营看板（FR-ADM-06，M2-T5） -->
    <section v-if="tab === 'ops'">
      <h2>运营看板（近 {{ dashboardDays }} 天）</h2>
      <div class="ops-tools">
        <el-select v-model="dashboardDays" style="width: 110px" @change="loadDashboard()">
          <el-option :value="1" label="近 1 天" />
          <el-option :value="7" label="近 7 天" />
          <el-option :value="30" label="近 30 天" />
        </el-select>
        <el-button type="warning" plain @click="runCleanup">清理超期审计/历史（先预检）</el-button>
        <span v-if="cleanupMsg" class="cleanup-msg">{{ cleanupMsg }}</span>
      </div>
      <div v-if="dash" class="cards">
        <div class="card"><b>{{ dash.summary.total }}</b><span>查询总量</span></div>
        <div class="card"><b>{{ (dash.summary.success_rate * 100).toFixed(1) }}%</b><span>成功率</span></div>
        <div class="card"><b>{{ dash.summary.avg_duration_ms }}ms</b><span>平均耗时</span></div>
        <div class="card"><b>{{ (dash.summary.retry_rate * 100).toFixed(1) }}%</b><span>自愈重试率</span></div>
        <div class="card"><b>{{ dash.summary.clarify }}</b><span>澄清次数</span></div>
        <div class="card"><b>{{ dash.summary.refused }}</b><span>拒答次数</span></div>
        <div class="card"><b>{{ dash.summary.llm_tokens.toLocaleString() }}</b><span>Token 用量</span></div>
      </div>
      <div v-if="dash" class="cols">
        <div>
          <h3>耗时分布</h3>
          <ul class="kv">
            <li v-for="(v, k) in dash.duration_buckets" :key="k">{{ k }}：<b>{{ v }}</b></li>
          </ul>
          <h3>Top 失败原因（错误码）</h3>
          <ul class="kv">
            <li v-for="f in dash.top_failures" :key="f[0]">错误码 {{ f[0] }}：<b>{{ f[1] }}</b> 次</li>
            <li v-if="!dash.top_failures.length">无失败记录</li>
          </ul>
        </div>
        <div>
          <h3>高频问题 Top 10</h3>
          <ol class="kv">
            <li v-for="q in dash.top_questions" :key="q[0]">{{ q[0] }}（{{ q[1] }} 次）</li>
            <li v-if="!dash.top_questions.length">暂无查询</li>
          </ol>
        </div>
      </div>
    </section>

    <!-- 评测管理（FR-ADM-07，M2-T6） -->
    <section v-if="tab === 'eval'">
      <h2>评测管理</h2>
      <div class="ops-tools">
        <el-button type="primary" plain @click="triggerEval('offline')">跑离线评测（安全/时间解析，秒级）</el-button>
        <el-button type="primary" @click="triggerEval('full')">跑全量评测（含真实 LLM，数分钟）</el-button>
        <el-select v-model="cmpB" style="width: 200px" placeholder="对比基线…">
          <el-option v-for="r in evalReports.filter((x) => x.status === 'done')" :key="r.id"
                     :value="r.id" :label="`#${r.id} (${(r.pass_rate * 100).toFixed(1)}%)`" />
        </el-select>
      </div>
      <p v-if="evalMsg" class="cleanup-msg">{{ evalMsg }}</p>
      <el-table :data="evalReports" size="small" stripe>
        <el-table-column label="ID" width="70">
          <template #default="{ row }">#{{ row.id }}</template>
        </el-table-column>
        <el-table-column prop="mode" label="模式" width="80" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.status === 'done' ? 'success' : row.status === 'failed' ? 'danger' : 'warning'" size="small">
              {{ row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="total" label="总数" width="70" />
        <el-table-column prop="passed" label="通过" width="70" />
        <el-table-column prop="failed" label="失败" width="70" />
        <el-table-column prop="skipped" label="跳过" width="70" />
        <el-table-column label="通过率" width="90">
          <template #default="{ row }"><b>{{ (row.pass_rate * 100).toFixed(1) }}%</b></template>
        </el-table-column>
        <el-table-column label="模型" width="120">
          <template #default="{ row }">{{ row.model_version || '-' }}</template>
        </el-table-column>
        <el-table-column label="时间" width="160">
          <template #default="{ row }">{{ row.created_at?.slice(0, 19) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="170">
          <template #default="{ row }">
            <el-button v-if="cmpB && cmpB !== row.id" size="small" @click="doCompare(row.id)">与 #{{ cmpB }} 对比</el-button>
            <el-button size="small" plain @click="evalDetail(row.id)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!evalReports.length" description="暂无评测记录，点击上方按钮触发" :image-size="60" />
      <!-- 分维度对比结果（EV-05） -->
      <div v-if="cmpResult" class="shares">
        <h3>对比：#{{ cmpResult.b.id }} vs #{{ cmpResult.a.id }}（整体 {{ sign(cmpResult.overall_diff) }}）</h3>
        <el-table :data="Object.entries(cmpResult.by_tag)" size="small" stripe>
          <el-table-column label="维度" min-width="160">
            <template #default="{ row }">{{ row[0] }}</template>
          </el-table-column>
          <el-table-column label="基准通过率" width="120">
            <template #default="{ row }">{{ (row[1].a * 100).toFixed(1) }}%</template>
          </el-table-column>
          <el-table-column label="对比通过率" width="120">
            <template #default="{ row }">{{ (row[1].b * 100).toFixed(1) }}%</template>
          </el-table-column>
          <el-table-column label="变化" width="100">
            <template #default="{ row }">
              <el-tag :type="row[1].diff >= 0 ? 'success' : 'danger'" size="small">{{ sign(row[1].diff) }}</el-tag>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <!-- 分维度详情 -->
      <div v-if="detailTags" class="shares">
        <h3>报告 #{{ detailId }} 分维度明细</h3>
        <ul class="kv">
          <li v-for="(v, tag) in detailTags" :key="tag">{{ tag }}：{{ v.passed }}/{{ v.total }}（{{ ((v.passed / v.total) * 100).toFixed(1) }}%）</li>
        </ul>
      </div>
    </section>
    <section v-if="tab === 'datasource'">
      <h2>数据源接入</h2>
      <el-form class="ds-form" :model="dsForm" inline @submit.prevent="addDatasource">
        <el-form-item required><el-input v-model="dsForm.name" placeholder="名称" style="width: 130px" /></el-form-item>
        <el-form-item required><el-input v-model="dsForm.host" placeholder="主机" style="width: 140px" /></el-form-item>
        <el-form-item><el-input-number v-model="dsForm.port" placeholder="端口" :min="1" :max="65535" style="width: 130px" /></el-form-item>
        <el-form-item required><el-input v-model="dsForm.db_name" placeholder="库名" style="width: 150px" /></el-form-item>
        <el-form-item required><el-input v-model="dsForm.readonly_user" placeholder="只读账号" style="width: 130px" /></el-form-item>
        <el-form-item required><el-input v-model="dsForm.password" type="password" placeholder="密码" show-password style="width: 150px" /></el-form-item>
        <el-form-item>
          <el-button type="primary" native-type="submit" :loading="scanning">接入并测试</el-button>
        </el-form-item>
      </el-form>
      <el-table :data="dss" size="small" stripe>
        <el-table-column prop="name" label="名称" width="160" />
        <el-table-column prop="host" label="主机" min-width="140" />
        <el-table-column prop="db_name" label="库名" min-width="140" />
        <el-table-column label="操作" width="140">
          <template #default="{ row }">
            <el-button size="small" type="primary" plain
                       @click="selectedDs = row.id; scan(); tab = 'schema'">扫描表结构</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <!-- 表标注 -->
    <section v-if="tab === 'schema'">
      <h2>表标注（FR-SCH-10：标注内容将注入 Prompt）</h2>
      <div class="row">
        <select v-model.number="selectedDs" @change="loadTables">
          <option v-for="d in dss" :key="d.id" :value="d.id">{{ d.name }}</option>
        </select>
        <button @click="scan">重新扫描</button>
      </div>
      <table>
        <thead><tr><th>表</th><th>中文名（业务标注）</th><th>完整度</th><th>纳入候选池</th></tr></thead>
        <tbody>
          <tr v-for="t in tables" :key="t.id">
            <td>{{ t.table_name }}</td>
            <td><el-input v-model="t.cn_name" size="small" placeholder="中文名" /></td>
            <td>{{ t.annotation_score }}%</td>
            <td>
              <el-switch :model-value="t.included" @change="saveAnnotation(t)" />
              <el-button size="small" @click="pickTable(t.id)">字段</el-button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-if="selectedTable">
        <h3>字段列表</h3>
        <ul>
          <li v-for="c in columns" :key="c.id">{{ c.column_name }} — {{ c.cn_name ?? '未标注' }} {{ c.description ?? '' }}</li>
        </ul>
      </div>
    </section>

    <!-- 指标 -->
    <section v-if="tab === 'metric'">
      <h2>指标定义（FR-SCH-12：口径由元数据定义，LLM 不得自造）</h2>
      <el-form class="row" inline @submit.prevent="saveMetric">
        <el-form-item><el-input v-model="metricForm.name" placeholder="指标名（如 GMV）" style="width: 150px" /></el-form-item>
        <el-form-item><el-input v-model="metricForm.code" placeholder="编码（如 gmv）" style="width: 130px" /></el-form-item>
        <el-form-item><el-input v-model="metricForm.description" placeholder="业务口径说明" style="width: 200px" /></el-form-item>
        <el-form-item><el-input v-model="metricForm.unit" placeholder="单位" style="width: 90px" /></el-form-item>
        <el-form-item><el-button type="primary" native-type="submit">创建</el-button></el-form-item>
      </el-form>
      <ul><li v-for="m in metrics" :key="m.id">{{ m.name }}（{{ m.code }}）{{ m.description ?? '' }}</li></ul>
    </section>

    <!-- 系统配置 -->
    <section v-if="tab === 'config'">
      <h2>系统参数（FR-ADM-05：变更留痕）</h2>
      <el-table :data="configs" size="small" stripe>
        <el-table-column prop="key" label="键" width="260" />
        <el-table-column label="值" min-width="180">
          <template #default="{ row }">
            <el-input v-model="row.value" size="small" />
          </template>
        </el-table-column>
        <el-table-column prop="description" label="说明" min-width="220" show-overflow-tooltip />
        <el-table-column label="操作" width="90">
          <template #default="{ row }">
            <el-button size="small" type="primary" plain @click="saveConfigRow(row)">保存</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <!-- 样例库与反馈（M2-T1：FR-ADM-04、FR-UI-08、FR-ADM-08） -->
    <section v-if="tab === 'fewshot'">
      <h2>待审核纠错反馈</h2>
      <el-table v-if="feedbacks.length" :data="feedbacks" size="small" stripe>
        <el-table-column prop="rating" label="评分" width="80" />
        <el-table-column label="正确 SQL" min-width="220" show-overflow-tooltip>
          <template #default="{ row }"><code>{{ row.correction_sql }}</code></template>
        </el-table-column>
        <el-table-column prop="comment" label="说明" min-width="160" show-overflow-tooltip />
        <el-table-column label="操作" width="180">
          <template #default="{ row }">
            <el-button size="small" type="primary" plain @click="reviewFeedback(row.id, true)">采纳（转样例）</el-button>
            <el-button size="small" type="danger" plain @click="reviewFeedback(row.id, false)">驳回</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-else description="暂无待审核反馈" :image-size="60" />

      <h2>Few-shot 样例库</h2>
      <el-form class="row" inline @submit.prevent="addFewShot">
        <el-form-item><el-input v-model="fewShotForm.question" placeholder="问题" style="width: 200px" /></el-form-item>
        <el-form-item><el-input v-model="fewShotForm.sql_text" placeholder="标准 SQL" style="width: 280px" /></el-form-item>
        <el-form-item><el-input v-model="fewShotForm.explanation" placeholder="说明" style="width: 160px" /></el-form-item>
        <el-form-item><el-button type="primary" native-type="submit">录入（待审核）</el-button></el-form-item>
      </el-form>
      <el-table :data="fewShots" size="small" stripe>
        <el-table-column prop="question" label="问题" min-width="200" show-overflow-tooltip />
        <el-table-column label="SQL" min-width="220" show-overflow-tooltip>
          <template #default="{ row }"><code>{{ row.sql_text.slice(0, 60) }}…</code></template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.status === 1 ? 'success' : row.status === 2 ? 'warning' : 'info'" size="small">
              {{ row.status === 2 ? '待审核' : row.status === 1 ? '启用' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="hit_count" label="命中" width="70" />
        <el-table-column label="操作" width="90">
          <template #default="{ row }">
            <el-button size="small" type="danger" plain @click="delFewShot(row.id)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <h2>未覆盖问题（FR-ADM-08）</h2>
      <p>累计未覆盖查询：{{ uncaptured?.total_uncovered ?? 0 }} 次，去重后 {{ uncaptured?.items.length ?? 0 }} 个问题</p>
      <el-table v-if="uncaptured?.items.length" :data="uncaptured.items" size="small" stripe>
        <el-table-column prop="question" label="问题" min-width="240" show-overflow-tooltip />
        <el-table-column prop="count" label="次数" width="80" />
        <el-table-column label="状态" min-width="160">
          <template #default="{ row }">{{ row.statuses.join(' / ') }}</template>
        </el-table-column>
      </el-table>
    </section>

    <!-- 行级权限策略（M2-T3：FR-SEC-10/12） -->
    <section v-if="tab === 'rowpolicy'">
      <h2>行级权限策略（注入执行 SQL，对新查询立即生效）</h2>
      <el-form class="row" inline @submit.prevent="addRowPolicy">
        <el-form-item>
          <el-select v-model="policyForm.table_meta_id" placeholder="目标表" style="width: 150px">
            <el-option v-for="t in tables" :key="t.id" :value="t.id" :label="t.table_name" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-input v-model="policyForm.filter_template" placeholder="过滤片段，如 region = '华东'" style="width: 220px" />
        </el-form-item>
        <el-form-item>
          <el-input v-model="policyForm.apply_to_role_ids" placeholder="角色，逗号分隔（R-BIZ）" style="width: 180px" />
        </el-form-item>
        <el-form-item>
          <el-select v-model="policyForm.combine_mode" style="width: 120px">
            <el-option value="union" label="并集 (OR)" />
            <el-option value="intersect" label="交集 (AND)" />
          </el-select>
        </el-form-item>
        <el-form-item><el-button type="primary" native-type="submit">创建</el-button></el-form-item>
      </el-form>
      <p class="hint">先在「数据源」或「表标注」页选定数据源并扫描，再选择目标表</p>
      <el-table :data="rowPolicies" size="small" stripe>
        <el-table-column prop="table_meta_id" label="表 ID" width="80" />
        <el-table-column label="过滤条件" min-width="180" show-overflow-tooltip>
          <template #default="{ row }"><code>{{ row.filter_template }}</code></template>
        </el-table-column>
        <el-table-column label="适用角色" min-width="140">
          <template #default="{ row }">{{ row.apply_to_role_ids.join(', ') }}</template>
        </el-table-column>
        <el-table-column prop="combine_mode" label="叠加" width="90" />
        <el-table-column label="启用" width="70">
          <template #default="{ row }">{{ row.enabled ? '是' : '否' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="90">
          <template #default="{ row }">
            <el-button size="small" type="danger" plain @click="delRowPolicy(row.id)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>

<style scoped>
.topbar { display: flex; justify-content: space-between; align-items: center; }
.ops-tools { display: flex; gap: .6rem; align-items: center; margin-bottom: .8rem; }
.cleanup-msg { color: #52c41a; font-size: .85rem; }
.cards { display: flex; gap: .6rem; flex-wrap: wrap; margin-bottom: 1rem; }
.card { background: #fafbfc; border: 1px solid #eee; border-radius: 10px; padding: .7rem 1.1rem; text-align: center; }
.card b { display: block; font-size: 1.3rem; }
.card span { color: #888; font-size: .75rem; }
.cols { display: flex; gap: 2rem; }
.cols > div { flex: 1; }
.kv { font-size: .85rem; line-height: 1.7; }
.page { padding: 1.5rem; max-width: 960px; margin: 0 auto; }
.tabs { display: flex; gap: .5rem; margin-bottom: 1rem; align-items: center; }
.tabs button, .tabs .back { padding: .4rem 1rem; border: 1px solid #ddd; background: #fff; border-radius: 8px; cursor: pointer; }
.tabs .on { background: #4169e1; color: #fff; border-color: #4169e1; }
.row { display: flex; gap: .5rem; flex-wrap: wrap; margin-bottom: 1rem; }
.row input, .row select { padding: .45rem .6rem; border: 1px solid #ddd; border-radius: 6px; }
.row button { padding: .45rem 1rem; background: #4169e1; color: #fff; border: 0; border-radius: 6px; cursor: pointer; }
table { width: 100%; border-collapse: collapse; font-size: .85rem; margin-top: .8rem; }
th, td { border: 1px solid #eee; padding: .45rem .7rem; text-align: left; }
button { padding: .3rem .8rem; cursor: pointer; border: 1px solid #ddd; background: #fff; border-radius: 6px; }
.danger { color: #d33; }
.msg { padding: .6rem 1rem; background: #e6f7ff; border: 1px solid #91d5ff; border-radius: 8px; }
</style>
