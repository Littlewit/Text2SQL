<script setup lang="ts">
// 查询历史（FR-HIS-01/02）
import { onMounted, ref } from 'vue'
import { getHistory } from '../api'

interface HistoryItem { id: number; question: string; intent: string; exec_status: string; row_count: number; duration_ms: number }
const items = ref<HistoryItem[]>([])
const total = ref(0)
const page = ref(1)

async function load() {
  const d = await getHistory(page.value)
  items.value = d.items
  total.value = d.total
}
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
    <h1>查询历史</h1>
    <table>
      <thead><tr><th>ID</th><th>问题</th><th>意图</th><th>状态</th><th>行数</th><th>耗时</th><th>操作</th></tr></thead>
      <tbody>
        <tr v-for="h in items" :key="h.id">
          <td>{{ h.id }}</td>
          <td>{{ h.question }}</td>
          <td>{{ h.intent }}</td>
          <td><span :class="h.exec_status">{{ h.exec_status }}</span></td>
          <td>{{ h.row_count }}</td>
          <td>{{ h.duration_ms }}ms</td>
          <td><button @click="exportExcel(h.id)">导出 Excel</button></td>
        </tr>
      </tbody>
    </table>
    <div class="pager">
      <button :disabled="page <= 1" @click="page--; load()">上一页</button>
      <span>{{ page }} / {{ Math.max(1, Math.ceil(total / 20)) }}</span>
      <button :disabled="page * 20 >= total" @click="page++; load()">下一页</button>
    </div>
  </div>
</template>

<style scoped>
.page { padding: 1.5rem; }
table { width: 100%; border-collapse: collapse; font-size: .85rem; }
th, td { border: 1px solid #eee; padding: .5rem .8rem; text-align: left; }
.success { color: #52c41a; } .failed { color: #d33; } .clarify, .refused { color: #fa8c16; }
button { padding: .25rem .7rem; cursor: pointer; }
.pager { margin-top: 1rem; display: flex; gap: 1rem; align-items: center; }
</style>
