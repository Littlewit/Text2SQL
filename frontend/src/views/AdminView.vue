<script setup lang="ts">
// 管理后台（FR-ADM-02/03/05 精简版）：数据源接入与扫描、表标注、指标、系统配置
import { onMounted, ref } from 'vue'
import {
  annotateTable, createDatasource, createFewShot as createFewShotApi, deleteFewShot as deleteFewShotApi,
  getColumns, getConfigs, getDatasources, getFewShots, getMetrics, getPendingFeedbacks, getTables,
  getUncaptured, patchConfig, reviewFeedback as reviewFeedbackApi, scanDatasource, testDatasource,
} from '../api'

type Tab = 'datasource' | 'schema' | 'metric' | 'config' | 'fewshot' | 'uncaptured' | 'rowpolicy'
const tab = ref<Tab>('datasource')
const msg = ref('')

// 数据源
const dss = ref<{ id: number; name: string; host: string; db_name: string; status: number }[]>([])
const dsForm = ref({ name: '', host: 'localhost', port: 5433, db_name: '', readonly_user: 't2s', password: '' })

// Schema 标注
const selectedDs = ref(0)
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
    msg.value = `接入成功，连通性测试：${test.ok}（${test.latency_ms}ms）`
    await loadAll()
  } catch (e: unknown) {
    msg.value = (e as { response?: { data?: { message?: string } } }).response?.data?.message ?? '接入失败'
  }
}

async function scan() {
  const stats = await scanDatasource(selectedDs.value)
  msg.value = `扫描完成：${stats.tables} 表 / ${stats.columns} 字段（新增 ${stats.new_tables}/${stats.new_columns}）`
  await loadTables()
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
  msg.value = `已保存并重新向量化：${t.table_name ?? t.id}`
  await loadTables()
}

async function saveMetric() {
  await getMetrics // 引用避免未用告警
  const { createMetricApi } = await import('../api')
  await createMetricApi(metricForm.value)
  metrics.value = await getMetrics()
  msg.value = '指标已创建并向量化'
}

async function saveConfig(c: { key: string; value: unknown }) {
  await patchConfig(c.key, c.value)
  msg.value = `配置 ${c.key} 已更新（留痕审计）`
}
</script>

<template>
  <div class="page">
    <nav class="tabs">
      <button :class="{ on: tab === 'datasource' }" @click="tab = 'datasource'">数据源</button>
      <button :class="{ on: tab === 'schema' }" @click="tab = 'schema'">表标注</button>
      <button :class="{ on: tab === 'metric' }" @click="tab = 'metric'">指标</button>
      <button :class="{ on: tab === 'config' }" @click="tab = 'config'">系统配置</button>
      <button :class="{ on: tab === 'fewshot' }" @click="tab = 'fewshot'; loadFewShots()">样例库与反馈</button>
      <button :class="{ on: tab === 'rowpolicy' }" @click="tab = 'rowpolicy'; loadFewShots()">行级权限</button>
      <router-link to="/" class="back">返回对话</router-link>
    </nav>
    <p v-if="msg" class="msg">{{ msg }}</p>

    <!-- 数据源 -->
    <section v-if="tab === 'datasource'">
      <h2>数据源接入</h2>
      <form class="row" @submit.prevent="addDatasource">
        <input v-model="dsForm.name" placeholder="名称" required />
        <input v-model="dsForm.host" placeholder="主机" required />
        <input v-model.number="dsForm.port" type="number" placeholder="端口" />
        <input v-model="dsForm.db_name" placeholder="库名" required />
        <input v-model="dsForm.readonly_user" placeholder="只读账号" required />
        <input v-model="dsForm.password" type="password" placeholder="密码" required />
        <button type="submit">接入并测试</button>
      </form>
      <ul>
        <li v-for="d in dss" :key="d.id">
          {{ d.name }}（{{ d.host }}/{{ d.db_name }}）
          <button @click="selectedDs = d.id; scan(); tab = 'schema'">扫描表结构</button>
        </li>
      </ul>
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
            <td><input v-model="t.cn_name" /></td>
            <td>{{ t.annotation_score }}%</td>
            <td>
              <input type="checkbox" :checked="t.included" @change="saveAnnotation(t)" />
              <button @click="pickTable(t.id)">字段</button>
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
      <form class="row" @submit.prevent="saveMetric">
        <input v-model="metricForm.name" placeholder="指标名（如 GMV）" required />
        <input v-model="metricForm.code" placeholder="编码（如 gmv）" required />
        <input v-model="metricForm.description" placeholder="业务口径说明" />
        <input v-model="metricForm.unit" placeholder="单位" />
        <button type="submit">创建</button>
      </form>
      <ul><li v-for="m in metrics" :key="m.id">{{ m.name }}（{{ m.code }}）{{ m.description ?? '' }}</li></ul>
    </section>

    <!-- 系统配置 -->
    <section v-if="tab === 'config'">
      <h2>系统参数（FR-ADM-05：变更留痕）</h2>
      <table>
        <thead><tr><th>键</th><th>值</th><th>说明</th><th></th></tr></thead>
        <tbody>
          <tr v-for="c in configs" :key="c.key">
            <td>{{ c.key }}</td>
            <td><input v-model="c.value" /></td>
            <td>{{ c.description }}</td>
            <td><button @click="saveConfig(c)">保存</button></td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- 样例库与反馈（M2-T1：FR-ADM-04、FR-UI-08、FR-ADM-08） -->
    <section v-if="tab === 'fewshot'">
      <h2>待审核纠错反馈</h2>
      <table v-if="feedbacks.length">
        <thead><tr><th>评分</th><th>正确 SQL</th><th>说明</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="f in feedbacks" :key="f.id">
            <td>{{ f.rating }}</td>
            <td><code>{{ f.correction_sql }}</code></td>
            <td>{{ f.comment }}</td>
            <td>
              <button @click="reviewFeedback(f.id, true)">采纳（转样例）</button>
              <button class="danger" @click="reviewFeedback(f.id, false)">驳回</button>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else>暂无待审核反馈</p>

      <h2>Few-shot 样例库</h2>
      <form class="row" @submit.prevent="addFewShot">
        <input v-model="fewShotForm.question" placeholder="问题" required />
        <input v-model="fewShotForm.sql_text" placeholder="标准 SQL" required />
        <input v-model="fewShotForm.explanation" placeholder="说明" />
        <button type="submit">录入（待审核）</button>
      </form>
      <table>
        <thead><tr><th>问题</th><th>SQL</th><th>状态</th><th>命中</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="s in fewShots" :key="s.id">
            <td>{{ s.question }}</td>
            <td><code>{{ s.sql_text.slice(0, 60) }}…</code></td>
            <td>{{ s.status === 2 ? '待审核' : s.status === 1 ? '启用' : '停用' }}</td>
            <td>{{ s.hit_count }}</td>
            <td><button class="danger" @click="delFewShot(s.id)">删除</button></td>
          </tr>
        </tbody>
      </table>

      <h2>未覆盖问题（FR-ADM-08）</h2>
      <p>累计未覆盖查询：{{ uncaptured?.total_uncovered ?? 0 }} 次，去重后 {{ uncaptured?.items.length ?? 0 }} 个问题</p>
      <table v-if="uncaptured?.items.length">
        <thead><tr><th>问题</th><th>次数</th><th>状态</th></tr></thead>
        <tbody>
          <tr v-for="(u, i) in uncaptured.items" :key="i">
            <td>{{ u.question }}</td>
            <td>{{ u.count }}</td>
            <td>{{ u.statuses.join(' / ') }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- 行级权限策略（M2-T3：FR-SEC-10/12） -->
    <section v-if="tab === 'rowpolicy'">
      <h2>行级权限策略（注入执行 SQL，对新查询立即生效）</h2>
      <form class="row" @submit.prevent="addRowPolicy">
        <select v-model.number="policyForm.table_meta_id">
          <option v-for="t in tables" :key="t.id" :value="t.id">{{ t.table_name }}</option>
        </select>
        <input v-model="policyForm.filter_template" placeholder="过滤片段，如 region = '华东'" required />
        <input v-model="policyForm.apply_to_role_ids" placeholder="角色，逗号分隔（R-BIZ）" required />
        <select v-model="policyForm.combine_mode">
          <option value="union">并集 (OR)</option>
          <option value="intersect">交集 (AND)</option>
        </select>
        <button type="submit">创建</button>
      </form>
      <p class="hint">先在「数据源」或「表标注」页选定数据源并扫描，再选择目标表</p>
      <table>
        <thead><tr><th>表 ID</th><th>过滤条件</th><th>适用角色</th><th>叠加</th><th>启用</th><th></th></tr></thead>
        <tbody>
          <tr v-for="p in rowPolicies" :key="p.id">
            <td>{{ p.table_meta_id }}</td>
            <td><code>{{ p.filter_template }}</code></td>
            <td>{{ p.apply_to_role_ids.join(', ') }}</td>
            <td>{{ p.combine_mode }}</td>
            <td>{{ p.enabled ? '是' : '否' }}</td>
            <td><button class="danger" @click="delRowPolicy(p.id)">删除</button></td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>

<style scoped>
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
