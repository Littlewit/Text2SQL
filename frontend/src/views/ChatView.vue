<script setup lang="ts">
// 主对话界面（UX-01）：左侧会话列表 + 右侧对话流；SSE 流式（FR-UI-05）
import * as echarts from 'echarts'
import { nextTick, onMounted, ref } from 'vue'
import {
  createConversation, createFeedback, currentUser, getConversations, getDatasources,
  getFollowups, streamQuery, type QueryEvent,
} from '../api'

interface ChatMessage {
  role: 'user' | 'assistant'
  question?: string
  text?: string           // 结论文本 / 系统提示
  sql?: string
  explain?: string
  assumptions?: string[]  // 口径假设（UX-04 视觉突出）
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
    // 刷新会话列表（新会话由后端创建时）
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
    // 查询完成后拉取建议追问（FR-UI-04）
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
    const chart = echarts.init(el)
    chart.setOption(msg.chartOption as echarts.EChartsOption)
  }
}

async function sendFeedback(msg: ChatMessage, rating: 'up' | 'down') {
  if (!msg.queryId) return
  try {
    await createFeedback(msg.queryId, { rating, correction_sql: msg.correctionSql })
    msg.feedbackSent = true
    msg.showCorrection = false
  } catch (e: unknown) {
    const resp = (e as { response?: { data?: { message?: string } } }).response
    alert(resp?.data?.message ?? '反馈提交失败')
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
      <button class="new-conv" @click="newConv">+ 新会话</button>
      <ul>
        <li v-for="c in conversations" :key="c.id" :class="{ active: c.id === activeConv }" @click="selectConv(c.id)">
          {{ c.title || '会话 ' + c.id }}
        </li>
      </ul>
      <div class="ds-picker" v-if="datasources.length">
        数据源：
        <select v-model.number="datasourceId">
          <option v-for="d in datasources" :key="d.id" :value="d.id">{{ d.name }}</option>
        </select>
      </div>
    </aside>

    <!-- 右侧对话流 -->
    <main class="chat-main" ref="chatBody">
      <div v-if="!messages.length" class="empty-guide">
        <p>试试这样问：</p>
        <button @click="send('上个月哪个店铺GMV最高？')">上个月哪个店铺GMV最高？</button>
        <button @click="send('这个季度退货率超过10%的商品有哪些？')">这个季度退货率超过10%的商品有哪些？</button>
        <button @click="send('对比一下华东和华南的销售趋势')">对比一下华东和华南的销售趋势</button>
      </div>

      <div v-for="(m, i) in messages" :key="i" :class="['msg', m.role]">
        <div v-if="m.role === 'user'" class="user-bubble">{{ m.question }}</div>

        <div v-else class="assistant-card">
          <!-- 假设声明：视觉突出，不可折叠（UX-04） -->
          <div v-if="m.assumptions?.length" class="assumption-banner">
            ⚠ 口径假设：{{ m.assumptions.join('；') }}
          </div>

          <p v-if="m.text" class="stage-text">{{ m.text }}</p>

          <!-- 澄清卡片（FR-UI-07）：点选完成澄清 -->
          <div v-if="m.clarify" class="clarify">
            <p>{{ m.clarify.question }}</p>
            <button v-for="opt in m.clarify.options" :key="opt" @click="sendClarifyOption(opt)">{{ opt }}</button>
          </div>

          <!-- 错误态（FR-UI-10）：可行动建议 -->
          <div v-if="m.error" class="error-box">
            <p>{{ m.error }}</p>
            <button @click="retryLast(m)">重试</button>
          </div>

          <!-- 四要素：结论 + 图表/表格 + SQL 解释（UX-02） -->
          <div v-if="m.chartType" class="result-area">
            <div v-if="m.chartType === 'empty'" class="empty-card">查询成功但无匹配数据</div>
            <div v-else-if="m.chartType === 'table'" class="table-box">
              <table>
                <thead><tr><th v-for="c in m.columns" :key="c">{{ c }}</th></tr></thead>
                <tbody><tr v-for="(r, ri) in m.rows" :key="ri"><td v-for="(v, vi) in r" :key="vi">{{ v ?? '-' }}</td></tr></tbody>
              </table>
            </div>
            <div v-else class="chart-box" :ref="(el) => renderChart(el as HTMLElement, m)" />
            <p class="chart-reason">{{ m.chartReason }}</p>
          </div>

          <details v-if="m.sql" class="sql-details">
            <summary>查看 SQL 与解释</summary>
            <pre>{{ m.sql }}</pre>
            <p>{{ m.explain }}</p>
          </details>

          <!-- 建议追问（FR-UI-04） -->
          <div v-if="m.followups?.length" class="followups">
            <button v-for="f in m.followups" :key="f" :disabled="busy" @click="send(f)">{{ f }}</button>
          </div>

          <!-- 反馈（FR-UI-08）：赞踩 + 纠错，进入样例库闭环 -->
          <div v-if="m.queryId && !m.feedbackSent" class="feedback-bar">
            <button @click="sendFeedback(m, 'up')">👍</button>
            <button @click="m.showCorrection = !m.showCorrection">👎 纠错</button>
            <span v-if="m.feedbackSent" class="fb-ok">反馈已提交，感谢！管理员审核后可用于改进回答。</span>
          </div>
          <div v-if="m.showCorrection && !m.feedbackSent" class="correction-box">
            <textarea v-model="m.correctionSql" rows="3" placeholder="粘贴正确的 SQL…" />
            <button @click="sendFeedback(m, 'down')">提交纠错</button>
          </div>
        </div>
      </div>
    </main>

    <!-- 输入区 -->
    <footer class="input-bar">
      <input
        v-model="input" :disabled="busy" placeholder="用自然语言提问，例如：上个月哪个店铺GMV最高？"
        @keydown.enter="send()"
      />
      <button :disabled="busy" @click="send()">发送</button>
    </footer>
  </div>
</template>

<style scoped>
.chat-layout { display: grid; grid-template-columns: 240px 1fr; grid-template-rows: 1fr auto; height: 100vh; }
.sidebar { grid-row: 1 / 3; border-right: 1px solid #e5e6eb; padding: 1rem; overflow-y: auto; background: #fafbfc; }
.user-bar { display: flex; justify-content: space-between; font-size: .8rem; margin-bottom: .8rem; }
.user-bar nav { display: flex; gap: .4rem; }
.new-conv { width: 100%; padding: .5rem; margin-bottom: .8rem; border: 1px dashed #4169e1; color: #4169e1; background: none; border-radius: 8px; cursor: pointer; }
.sidebar ul { list-style: none; padding: 0; }
.sidebar li { padding: .5rem; border-radius: 6px; cursor: pointer; font-size: .9rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sidebar li.active { background: #eef2ff; }
.ds-picker { font-size: .8rem; margin-top: 1rem; }
.ds-picker select { width: 100%; margin-top: .3rem; }
.chat-main { overflow-y: auto; padding: 1.5rem; }
.empty-guide button { display: block; margin: .5rem 0; padding: .6rem 1rem; border: 1px solid #ddd; background: #fff; border-radius: 8px; cursor: pointer; }
.msg { margin-bottom: 1rem; }
.user-bubble { background: #4169e1; color: #fff; padding: .6rem 1rem; border-radius: 12px 12px 0 12px; max-width: 70%; margin-left: auto; }
.assistant-card { background: #fff; border: 1px solid #e5e6eb; border-radius: 12px; padding: 1rem; max-width: 90%; }
.assumption-banner { background: #fff7e6; border: 1px solid #ffd591; padding: .5rem .8rem; border-radius: 8px; margin-bottom: .8rem; color: #ad6800; }
.stage-text { color: #888; }
.clarify button, .followups button { margin: .2rem .4rem .2rem 0; padding: .35rem .8rem; border: 1px solid #4169e1; color: #4169e1; background: none; border-radius: 16px; cursor: pointer; }
.error-box { background: #fff1f0; border: 1px solid #ffa39e; padding: .8rem; border-radius: 8px; }
.error-box button { margin-top: .5rem; padding: .3rem .8rem; border: 1px solid #d33; color: #d33; background: none; border-radius: 6px; cursor: pointer; }
.chart-box { height: 320px; }
.table-box { overflow-x: auto; }
.table-box table { border-collapse: collapse; font-size: .85rem; }
.table-box th, .table-box td { border: 1px solid #eee; padding: .4rem .8rem; }
.chart-reason { color: #999; font-size: .8rem; }
.feedback-bar { margin-top: .6rem; display: flex; gap: .4rem; align-items: center; }
.feedback-bar button { border: 1px solid #ddd; background: #fff; border-radius: 6px; padding: .2rem .6rem; cursor: pointer; }
.fb-ok { color: #52c41a; font-size: .8rem; }
.correction-box { margin-top: .6rem; display: flex; gap: .5rem; }
.correction-box textarea { flex: 1; font-family: monospace; border: 1px solid #ddd; border-radius: 6px; }
.correction-box button { align-self: flex-end; padding: .4rem .8rem; background: #4169e1; color: #fff; border: 0; border-radius: 6px; cursor: pointer; }
.sql-details pre { background: #f6f8fa; padding: .8rem; border-radius: 8px; overflow-x: auto; }
.input-bar { display: flex; gap: .6rem; padding: 1rem; border-top: 1px solid #e5e6eb; }
.input-bar input { flex: 1; padding: .7rem 1rem; border: 1px solid #ddd; border-radius: 10px; }
.input-bar button { padding: .7rem 1.6rem; background: #4169e1; color: #fff; border: 0; border-radius: 10px; cursor: pointer; }
</style>
