<script setup lang="ts">
// 查询历史（FR-HIS-01/02）+ 详情回看（M2-T4）+ 我的分享管理（FR-HIS-06/07 前端）
import { onMounted, ref } from 'vue'
import { getHistory, getHistoryDetail, getMyShares, revokeShare } from '../api'

interface HistoryItem { id: number; question: string; intent: string; exec_status: string; row_count: number; duration_ms: number }
interface HistoryDetail {
  id: number; question: string; exec_status: string
  generated_sql: string | null; explain_text: string | null
  assumptions: { list?: string[] } | null; recalled_schema: unknown; retry_count: number; duration_ms: number | null
}
interface ShareItem { id: number; question: string; token: string; expire_at: string; revoked: boolean }

const items = ref<HistoryItem[]>([])
const total = ref(0)
const page = ref(1)
const detail = ref<HistoryDetail | null>(null)
const shares = ref<ShareItem[]>([])
const showShares = ref(false)

async function load() {
  const d = await getHistory(page.value)
  items.value = d.items
  total.value = d.total
}

// 详情回看（FR-HIS-01 增强）：SQL/解释/假设/召回明细
async function openDetail(id: number) {
  detail.value = await getHistoryDetail(id)
}

function closeDetail() {
  detail.value = null
}

// 我的分享管理（FR-HIS-06/07 前端）：列表 + 撤销
async function toggleShares() {
  showShares.value = !showShares.value
  if (showShares.value) shares.value = await getMyShares()
}

async function removeShare(id: number) {
  await revokeShare(id)
  shares.value = await getMyShares()
}

// PDF 导出（FR-VIS-21）：审计由 ChatView 打印通道记录；此处仅 Excel 导出
async function exportExcel(id: number) {
  const blob = await import('../api').then((m) => m.exportQuery(id))
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `query_${id}.xlsx`
  a.click()
  URL.revokeObjectURL(url)
}

onMounted(load)
</script>

<template>
  <div class="page">
    <div class="header">
      <h1>查询历史</h1>
      <nav>
        <router-link to="/">返回对话</router-link>
        <button @click="toggleShares">{{ showShares ? '收起分享' : '我的分享' }}</button>
      </nav>
    </div>

    <!-- 我的分享管理（FR-HIS-06/07 前端） -->
    <section v-if="showShares" class="shares">
      <h2>我的分享（可撤销，撤销后失效）</h2>
      <table v-if="shares.length">
        <thead><tr><th>问题</th><th>有效期至</th><th>状态</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="s in shares" :key="s.id">
            <td>{{ s.question }}</td>
            <td>{{ s.expire_at.slice(0, 10) }}</td>
            <td>{{ s.revoked ? '已撤销' : '有效' }}</td>
            <td><button v-if="!s.revoked" class="danger" @click="removeShare(s.id)">撤销</button></td>
          </tr>
        </tbody>
      </table>
      <p v-else>暂无分享记录</p>
    </section>

    <table>
      <thead><tr><th>ID</th><th>问题</th><th>意图</th><th>状态</th><th>行数</th><th>耗时</th><th>操作</th></tr></thead>
      <tbody>
        <tr v-for="h in items" :key="h.id">
          <td>{{ h.id }}</td>
          <td class="q" @click="openDetail(h.id)">{{ h.question }}</td>
          <td>{{ h.intent }}</td>
          <td><span :class="h.exec_status">{{ h.exec_status }}</span></td>
          <td>{{ h.row_count }}</td>
          <td>{{ h.duration_ms }}ms</td>
          <td>
            <button @click="openDetail(h.id)">详情</button>
            <button @click="exportExcel(h.id)">导出</button>
          </td>
        </tr>
      </tbody>
    </table>
    <div class="pager">
      <button :disabled="page <= 1" @click="page--; load()">上一页</button>
      <span>{{ page }} / {{ Math.max(1, Math.ceil(total / 20)) }}</span>
      <button :disabled="page * 20 >= total" @click="page++; load()">下一页</button>
    </div>

    <!-- 详情弹层（FR-HIS-01 增强） -->
    <div v-if="detail" class="detail-mask" @click.self="closeDetail">
      <div class="detail-card">
        <div class="detail-head">
          <h2>{{ detail.question }}</h2>
          <button @click="closeDetail">关闭</button>
        </div>
        <p class="meta">状态 {{ detail.exec_status }} · 耗时 {{ detail.duration_ms }}ms · 自愈重试 {{ detail.retry_count }} 次</p>
        <h3>口径假设</h3>
        <ul><li v-for="a in detail.assumptions?.list ?? []" :key="a">{{ a }}</li></ul>
        <h3>生成 SQL</h3>
        <pre>{{ detail.generated_sql }}</pre>
        <h3>SQL 解释</h3>
        <p>{{ detail.explain_text }}</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page { padding: 1.5rem; }
.header { display: flex; justify-content: space-between; align-items: center; }
.header nav { display: flex; gap: .6rem; }
table { width: 100%; border-collapse: collapse; font-size: .85rem; }
th, td { border: 1px solid #eee; padding: .5rem .8rem; text-align: left; }
.q { cursor: pointer; color: #4169e1; }
.success { color: #52c41a; } .failed { color: #d33; } .clarify, .refused { color: #fa8c16; }
button { padding: .25rem .7rem; cursor: pointer; }
.danger { color: #d33; }
.pager { margin-top: 1rem; display: flex; gap: 1rem; align-items: center; }
.shares { background: #fafbfc; border: 1px solid #eee; border-radius: 8px; padding: 1rem; margin-bottom: 1rem; }
.detail-mask { position: fixed; inset: 0; background: rgb(0 0 0 / 40%); display: flex; align-items: center; justify-content: center; z-index: 10; }
.detail-card { background: #fff; border-radius: 12px; padding: 1.5rem; width: min(720px, 90vw); max-height: 80vh; overflow-y: auto; }
.detail-head { display: flex; justify-content: space-between; align-items: center; }
.detail-card .meta { color: #888; font-size: .8rem; }
.detail-card pre { background: #f6f8fa; padding: .8rem; border-radius: 8px; overflow-x: auto; white-space: pre-wrap; }
</style>
