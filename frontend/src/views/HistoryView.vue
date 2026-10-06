<script setup lang="ts">
// 查询历史（FR-HIS-01/02）+ 详情回看（M2-T4）+ 我的分享管理（FR-HIS-06/07 前端）——Element Plus 版
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
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
const detailVisible = ref(false)
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
  detailVisible.value = true
}

// 我的分享管理（FR-HIS-06/07 前端）：列表 + 撤销
async function toggleShares() {
  showShares.value = !showShares.value
  if (showShares.value) shares.value = await getMyShares()
}

async function removeShare(id: number) {
  try {
    await ElMessageBox.confirm('撤销后接收方将无法访问该分享，确认撤销？', '撤销分享', {
      type: 'warning', confirmButtonText: '确认撤销', cancelButtonText: '取消',
    })
  } catch { return }
  await revokeShare(id)
  shares.value = await getMyShares()
  ElMessage.success('已撤销')
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
  ElMessage.success('导出成功')
}

onMounted(load)
</script>

<template>
  <div class="page">
    <div class="header">
      <h1>查询历史</h1>
      <nav>
        <router-link to="/">返回对话</router-link>
        <el-button size="small" @click="toggleShares">{{ showShares ? '收起分享' : '我的分享' }}</el-button>
      </nav>
    </div>

    <!-- 我的分享管理（FR-HIS-06/07 前端） -->
    <el-card v-if="showShares" class="block-card" shadow="never">
      <template #header><b>我的分享（可撤销，撤销后失效）</b></template>
      <el-table v-if="shares.length" :data="shares" size="small" stripe>
        <el-table-column prop="question" label="问题" min-width="240" show-overflow-tooltip />
        <el-table-column label="有效期至" width="120">
          <template #default="{ row }">{{ row.expire_at.slice(0, 10) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.revoked ? 'info' : 'success'" size="small">{{ row.revoked ? '已撤销' : '有效' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90">
          <template #default="{ row }">
            <el-button v-if="!row.revoked" size="small" type="danger" plain @click="removeShare(row.id)">撤销</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-else description="暂无分享记录" :image-size="60" />
    </el-card>

    <el-card shadow="never">
      <el-table :data="items" size="small" stripe @row-click="(row: HistoryItem) => openDetail(row.id)">
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="question" label="问题" min-width="240" show-overflow-tooltip>
          <template #default="{ row }"><span class="q">{{ row.question }}</span></template>
        </el-table-column>
        <el-table-column prop="intent" label="意图" width="90" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.exec_status === 'success' ? 'success' : row.exec_status === 'failed' ? 'danger' : 'warning'"
                    size="small">{{ row.exec_status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="row_count" label="行数" width="80" />
        <el-table-column label="耗时" width="90">
          <template #default="{ row }">{{ row.duration_ms }}ms</template>
        </el-table-column>
        <el-table-column label="操作" width="150">
          <template #default="{ row }">
            <el-button size="small" @click.stop="openDetail(row.id)">详情</el-button>
            <el-button size="small" type="primary" plain @click.stop="exportExcel(row.id)">导出</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination class="pager" layout="prev, pager, next" :total="total" :page-size="20"
                     :current-page="page" @current-change="(p: number) => { page = p; load() }" />
    </el-card>

    <!-- 详情弹层（FR-HIS-01 增强） -->
    <el-dialog v-model="detailVisible" :title="detail?.question" width="720px" top="6vh">
      <template v-if="detail">
        <p class="meta">状态 {{ detail.exec_status }} · 耗时 {{ detail.duration_ms }}ms · 自愈重试 {{ detail.retry_count }} 次</p>
        <h4>口径假设</h4>
        <el-tag v-for="a in detail.assumptions?.list ?? []" :key="a" class="as-tag" type="warning" effect="plain">{{ a }}</el-tag>
        <p v-if="!detail.assumptions?.list?.length" class="meta">无</p>
        <h4>生成 SQL</h4>
        <pre class="sql-pre">{{ detail.generated_sql }}</pre>
        <h4>SQL 解释</h4>
        <p>{{ detail.explain_text }}</p>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page { padding: 1.5rem; max-width: 1100px; margin: 0 auto; }
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; }
.header nav { display: flex; gap: .6rem; align-items: center; }
.q { cursor: pointer; color: #4169e1; }
.block-card { margin-bottom: 1rem; }
.pager { margin-top: 1rem; justify-content: flex-end; }
.meta { color: #888; font-size: .8rem; }
.as-tag { margin-right: .4rem; }
.sql-pre { background: #f6f8fa; padding: .8rem; border-radius: 8px; overflow-x: auto; white-space: pre-wrap; }
</style>