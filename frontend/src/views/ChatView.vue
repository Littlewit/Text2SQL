<script setup lang="ts">
// 主对话界面（UX-01）：左侧会话列表 + 右侧对话流；SSE 流式（FR-UI-05）—— Element Plus 版
// echarts 按需注册（体积优化：全量 ~1MB → 按需 ~400KB）
import * as echarts from 'echarts/core'
import { LineChart, BarChart, PieChart } from 'echarts/charts'
import {
  GridComponent, TooltipComponent, TitleComponent, LegendComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([
  LineChart, BarChart, PieChart,
  GridComponent, TooltipComponent, TitleComponent, LegendComponent,
  CanvasRenderer,
])
import { ElMessage } from 'element-plus'
import { nextTick, onMounted, ref } from 'vue'
import {
  auditPdfExport, createConversation, createFeedback, currentUser, getConversations, getDatasources,
  getFollowups, streamQuery, switchChart, type QueryEvent,
} from '../api'

interface ChatMessage {
  role: 'user' | 'assistant'
  question?: string
  text?: string
  sql?: string
  explain?: string
  assumptions?: string[]
  columns?: string[]
  rows?: unknown[][]
  chartType?: string
  chartOption?: unknown
  chartReason?: string
  clarify?: { question: string; options: string[] }
  error?: string
  errorCode?: number
  queryId?: number
  followups?: string[]
  feedbackSent?: boolean
  showCorrection?: boolean
  correctionSql?: string
  pdfDone?: boolean
}

const conversations = ref<{ id: number; title: string }[]>([])
const activeConv = ref<number>(0)
const datasourceId = ref<number>(0)
const datasources = ref<{ id: number; name: string }[]>([])
const messages = ref<ChatMessage[]>([])
const input = ref('')
const busy = ref(false)
const user = currentUser()
const chatBody = ref<HTMLElement>()

onMounted(async () => {
  datasources.value = await getDatasources()
  datasourceId.value = datasources.value[0]?.id ?? 0
  conversations.value = await getConversations()
  if (conversations.value.length) await selectConv(conversations.value[0].id)
})

async function newConv() {
  const conv = await createConversation('新会话')
  conversations.value.unshift(conv)
  await selectConv(conv.id)
}

async function selectConv(id: number) {
  activeConv.value = id
  const { getMessages } = await import('../api')
  const msgs = await getMessages(id)
  messages.value = msgs.map((m: { role: string; content: Record<string, unknown> }) =>
    m.role === 'user'
      ? { role: 'user' as const, question: String(m.content.question ?? m.content) }
      : { role: 'assistant' as const, ...m.content },
  )
  scrollBottom()
}

function scrollBottom() {
  nextTick(() => chatBody.value?.scrollTo({ top: chatBody.value.scrollHeight }))
}

async function send(question?: string) {
  const q = (question ?? input.value).trim()
  if (!q || busy.value || !activeConv.value || !datasourceId.value) return
  input.value = ''
  messages.value.push({ role: 'user', question: q })
  const msg: ChatMessage = { role: 'assistant', text: '思考中…' }
  messages.value.push(msg)
  busy.value = true
  scrollBottom()

  try {
    await streamQuery(
      { question: q, conversation_id: activeConv.value, datasource_id: datasourceId.value },
      (e: QueryEvent) => handleEvent(msg, e),
    )
  } catch (err) {
    msg.error = err instanceof Error ? err.message : '网络异常'
  } finally {
    busy.value = false
    getConversations().then((cs) => (conversations.value = cs))
    scrollBottom()
  }
}

function handleEvent(msg: ChatMessage, e: QueryEvent) {
  const { event, data } = e
  if (event === 'stage') {
    msg.text = String(data.message ?? '处理中…')
  } else if (event === 'sql') {
    msg.sql = String(data.sql)
    msg.explain = String(data.explanation ?? '')
    msg.assumptions = (data.assumptions as string[]) ?? []
  } else if (event === 'clarify') {
    msg.text = undefined
    msg.clarify = { question: String(data.question), options: (data.options as string[]) ?? [] }
  } else if (event === 'result') {
    msg.text = undefined
    msg.columns = data.columns as string[]
    msg.rows = data.rows as unknown[][]
    msg.queryId = Number(data.query_id ?? msg.queryId)
  } else if (event === 'chart') {
    msg.chartType = String(data.chart_type)
    msg.chartOption = data.chart_config
    msg.chartReason = String(data.reason)
  } else if (event === 'error') {
    msg.text = undefined
    msg.error = String(data.user_message)
    msg.errorCode = Number(data.code)
  } else if (event === 'done') {
    msg.queryId = Number(data.query_id)
    if (msg.queryId) {
      getFollowups(msg.queryId).then((fs) => { msg.followups = fs; scrollBottom() }).catch(() => {})
    }
  }
  scrollBottom()
}

function sendClarifyOption(option: string) {
  messages.value.push({ role: 'user', question: option })
  const lastClarifyIdx = [...messages.value].reverse().findIndex((m) => m.clarify)
  if (lastClarifyIdx >= 0) messages.value[messages.value.length - 1 - lastClarifyIdx].clarify = undefined
  send(option)
}

function retryLast(msg: ChatMessage) {
  const lastUser = [...messages.value].reverse().find((m) => m.role === 'user')
  messages.value = messages.value.filter((m) => m !== msg)
  send(lastUser?.question)
}

function renderChart(el: HTMLElement, msg: ChatMessage) {
  if (msg.chartType && msg.chartOption && msg.chartType !== 'empty' && msg.chartType !== 'table') {
    // 暗色主题下使用 echarts 内置 dark 主题（文字/背景自动适配）
    const isDark = document.documentElement.classList.contains('dark')
    const chart = echarts.init(el, isDark ? 'dark' : undefined)
    chart.setOption(msg.chartOption as echarts.EChartsCoreOption)
  }
}

// 图表一键切换（FR-VIS-03/04）：服务端基于缓存结果重建 option，零请求重查
async function switchChartType(msg: ChatMessage, chartType: string) {
  if (!msg.queryId) return
  try {
    const r = await switchChart(msg.queryId, chartType)
    msg.chartType = r.chart_type
    msg.chartOption = r.option
    msg.chartReason = r.reason
    await nextTick()
    scrollBottom()
  } catch { /* 切换失败保留当前图 */ }
}

// PDF 导出（FR-VIS-21）：先记录服务端审计，再触发浏览器打印
async function exportPdf(msg: ChatMessage) {
  if (!msg.queryId) return
  try {
    await auditPdfExport(msg.queryId)
    msg.pdfDone = true
    window.print()
  } catch { /* 审计失败不阻断打印 */ }
}

// 单位格式化（FR-VIS-05）：数值千分位，其余原样
function formatValue(v: unknown): string {
  if (typeof v === 'number') return v.toLocaleString('zh-CN')
  return v === null || v === undefined ? '-' : String(v)
}

async function sendFeedback(msg: ChatMessage, rating: 'up' | 'down') {
  if (!msg.queryId) return
  try {
    await createFeedback(msg.queryId, { rating, correction_sql: msg.correctionSql })
    msg.feedbackSent = true
    msg.showCorrection = false
    ElMessage.success('反馈已提交，感谢！管理员审核后可用于改进回答')
  } catch (e: unknown) {
    const resp = (e as { response?: { data?: { message?: string } } }).response
    ElMessage.error(resp?.data?.message ?? '反馈提交失败')
  }
}

function doLogout() {
  import('../api').then((m) => {
    m.logout()
    location.href = '/login'
  })
}
</script>
<template>
  <div class="chat-layout">
    <!-- 左侧会话列表（UX-01） -->
    <aside class="sidebar">
      <div class="user-bar">
        <span>{{ user?.username }}</span>
        <nav>
          <router-link to="/history">历史</router-link>
          <router-link to="/favorites">收藏</router-link>
          <router-link v-if="user?.roles.includes('R-DA') || user?.roles.includes('R-AD')" to="/admin">管理</router-link>
          <a href="#" @click.prevent="doLogout">退出</a>
        </nav>
      </div>
      <el-button class="new-conv" plain type="primary" @click="newConv">+ 新会话</el-button>
      <el-scrollbar class="conv-list">
        <div v-for="c in conversations" :key="c.id"
             :class="['conv-item', { active: c.id === activeConv }]" @click="selectConv(c.id)">
          {{ c.title || '会话 ' + c.id }}
        </div>
      </el-scrollbar>
      <div class="ds-picker" v-if="datasources.length">
        <span>数据源</span>
        <el-select v-model="datasourceId" size="small" placeholder="选择数据源">
          <el-option v-for="d in datasources" :key="d.id" :label="d.name" :value="d.id" />
        </el-select>
      </div>
    </aside>

    <!-- 右侧对话流 -->
    <main class="chat-main" ref="chatBody">
      <div v-if="!messages.length" class="empty-guide">
        <p>试试这样问：</p>
        <el-button plain @click="send('上个月哪个店铺GMV最高？')">上个月哪个店铺GMV最高？</el-button>
        <el-button plain @click="send('这个季度退货率超过10%的商品有哪些？')">这个季度退货率超过10%的商品有哪些？</el-button>
        <el-button plain @click="send('对比一下华东和华南的销售趋势')">对比一下华东和华南的销售趋势</el-button>
      </div>

      <div v-for="(m, i) in messages" :key="i" :class="['msg', m.role]">
        <div v-if="m.role === 'user'" class="user-bubble">{{ m.question }}</div>

        <div v-else class="assistant-card">
          <!-- 假设声明：视觉突出，不可折叠（UX-04） -->
          <el-alert v-if="m.assumptions?.length" type="warning" :closable="false" class="banner"
                    :title="`口径假设：${m.assumptions.join('；')}`" />

          <p v-if="m.text" class="stage-text">{{ m.text }}</p>

          <!-- 澄清卡片（FR-UI-07）：点选完成澄清 -->
          <div v-if="m.clarify" class="pill-group">
            <p>{{ m.clarify.question }}</p>
            <el-button v-for="opt in m.clarify.options" :key="opt" size="small" round @click="sendClarifyOption(opt)">
              {{ opt }}
            </el-button>
          </div>

          <!-- 错误态（FR-UI-10）：可行动建议 -->
          <el-alert v-if="m.error" type="error" :closable="false" class="banner" :title="m.error">
            <el-button size="small" type="danger" plain @click="retryLast(m)">重试</el-button>
          </el-alert>

          <!-- 四要素：结论 + 图表/表格 + SQL 解释（UX-02） -->
          <div v-if="m.chartType" class="result-area">
            <!-- 图表一键切换（FR-VIS-03/04）：复用缓存结果，零请求重查 -->
            <div v-if="m.queryId && m.chartType !== 'empty'" class="chart-switch">
              <el-radio-group v-model="m.chartType" size="small"
                              @change="(t: string | number | boolean | undefined) => switchChartType(m, String(t))">
                <el-radio-button value="line">折线</el-radio-button>
                <el-radio-button value="bar">柱状</el-radio-button>
                <el-radio-button value="pie">饼图</el-radio-button>
                <el-radio-button value="table">表格</el-radio-button>
              </el-radio-group>
              <el-button size="small" :disabled="m.pdfDone" @click="exportPdf(m)">打印/PDF</el-button>
              <el-tag v-if="m.pdfDone" type="success" size="small">已记录导出审计</el-tag>
            </div>
            <el-alert v-if="m.chartType === 'empty'" type="info" :closable="false" title="查询成功但无匹配数据" />
            <el-table v-else-if="m.chartType === 'table'" :data="m.rows" size="small" border max-height="360">
              <el-table-column v-for="(c, ci) in m.columns" :key="c" :label="c" min-width="100">
                <template #default="{ row }">{{ formatValue(row[ci]) }}</template>
              </el-table-column>
            </el-table>
            <div v-else class="chart-box" :ref="(el) => renderChart(el as HTMLElement, m)" />
            <p class="chart-reason">{{ m.chartReason }}</p>
          </div>

          <el-collapse v-if="m.sql" class="sql-collapse">
            <el-collapse-item title="查看 SQL 与解释" name="sql">
              <pre class="sql-pre">{{ m.sql }}</pre>
              <p>{{ m.explain }}</p>
            </el-collapse-item>
          </el-collapse>

          <!-- 建议追问（FR-UI-04） -->
          <div v-if="m.followups?.length" class="pill-group">
            <el-button v-for="f in m.followups" :key="f" size="small" round :disabled="busy" @click="send(f)">
              {{ f }}
            </el-button>
          </div>

          <!-- 反馈（FR-UI-08）：赞踩 + 纠错，进入样例库闭环 -->
          <div v-if="m.queryId && !m.feedbackSent" class="feedback-bar">
            <el-button size="small" circle @click="sendFeedback(m, 'up')">👍</el-button>
            <el-button size="small" round @click="m.showCorrection = !m.showCorrection">👎 纠错</el-button>
          </div>
          <div v-if="m.showCorrection && !m.feedbackSent" class="correction-box">
            <el-input v-model="m.correctionSql" type="textarea" :rows="3" placeholder="粘贴正确的 SQL…" />
            <el-button type="primary" @click="sendFeedback(m, 'down')">提交纠错</el-button>
          </div>
        </div>
      </div>
    </main>

    <!-- 输入区 -->
    <footer class="input-bar">
      <el-input v-model="input" :disabled="busy" size="large" clearable
                placeholder="用自然语言提问，例如：上个月哪个店铺GMV最高？" @keydown.enter="send()" />
      <el-button type="primary" size="large" :disabled="busy" @click="send()">发送</el-button>
    </footer>
  </div>
</template>

<style scoped>
.chat-layout { display: grid; grid-template-columns: 250px 1fr; grid-template-rows: 1fr auto; height: 100vh; }
.sidebar { grid-row: 1 / 3; border-right: 1px solid var(--el-border-color-lighter); padding: 1rem; display: flex; flex-direction: column; background: var(--el-fill-color-lighter); }
.user-bar { display: flex; justify-content: space-between; font-size: .8rem; margin-bottom: .8rem; }
.user-bar nav { display: flex; gap: .4rem; }
.new-conv { width: 100%; margin-bottom: .8rem; border-style: dashed; }
.conv-list { flex: 1; }
.conv-item { padding: .5rem .6rem; border-radius: 6px; cursor: pointer; font-size: .9rem;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.conv-item:hover { background: var(--el-fill-color); }
.conv-item.active { background: var(--el-color-primary-light-9); color: var(--el-color-primary); }
.ds-picker { font-size: .8rem; margin-top: 1rem; display: flex; flex-direction: column; gap: .3rem; }
.chat-main { overflow-y: auto; padding: 1.5rem; }
.empty-guide .el-button { margin: .4rem .4rem 0 0; }
.msg { margin-bottom: 1rem; }
.user-bubble { background: var(--el-color-primary); color: #fff; padding: .6rem 1rem;
  border-radius: 12px 12px 0 12px; max-width: 70%; margin-left: auto; width: fit-content; }
.assistant-card { background: #fff; border: 1px solid var(--el-border-color-lighter);
  border-radius: 12px; padding: 1rem; max-width: 90%; width: fit-content; min-width: 320px; }
.banner { margin-bottom: .8rem; }
.stage-text { color: #888; }
.pill-group { display: flex; flex-wrap: wrap; gap: .4rem; margin: .4rem 0; align-items: center; }
.pill-group p { width: 100%; margin: 0; }
.chart-box { height: 320px; width: 560px; }
.chart-switch { display: flex; gap: .5rem; margin-bottom: .5rem; align-items: center; }
.chart-reason { color: #999; font-size: .8rem; margin: .4rem 0 0; }
.feedback-bar { margin-top: .6rem; display: flex; gap: .4rem; align-items: center; }
.correction-box { margin-top: .6rem; display: flex; gap: .5rem; align-items: flex-end; }
.correction-box .el-input { flex: 1; }
.sql-collapse { margin-top: .5rem; }
.sql-pre { background: #f6f8fa; padding: .8rem; border-radius: 8px; overflow-x: auto; margin: 0; }
.input-bar { display: flex; gap: .6rem; padding: 1rem; border-top: 1px solid var(--el-border-color-lighter); }
.input-bar .el-input { flex: 1; }
</style>
