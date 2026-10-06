<script setup lang="ts">
// 收藏管理（FR-HIS-04/05）：列表 + 重执行（动态时间参数）+ 删除 —— Element Plus 版
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'
import { deleteFavorite, getFavorites, runFavorite } from '../api'

interface Fav { id: number; name: string; question: string; datasource_id: number; params: Record<string, unknown> | null }
const router = useRouter()
const items = ref<Fav[]>([])
const running = ref(0)

async function load() { items.value = await getFavorites() }

async function run(f: Fav) {
  running.value = f.id
  try {
    const r = await runFavorite(f.id)
    if (r.exec_status === 'success') {
      ElMessage.success(`执行成功，返回 ${r.result?.row_count ?? 0} 行（时间条件已按当前日期重算，AC-10）`)
      router.push('/')
    } else {
      ElMessage.warning(`执行状态：${r.exec_status}`)
    }
  } catch (e: unknown) {
    const resp = (e as { response?: { data?: { message?: string } } }).response
    ElMessage.error(resp?.data?.message ?? '执行失败')
  } finally {
    running.value = 0
  }
}

async function remove(f: Fav) {
  try {
    await ElMessageBox.confirm(`删除收藏「${f.name}」？`, '删除收藏', { type: 'warning' })
  } catch { return }
  await deleteFavorite(f.id)
  await load()
  ElMessage.success('已删除')
}

onMounted(load)
</script>

<template>
  <div class="page">
    <div class="header">
      <h1>我的收藏</h1>
      <router-link to="/">返回对话</router-link>
    </div>
    <el-card shadow="never">
      <el-table :data="items" size="small" stripe>
        <el-table-column prop="name" label="名称" width="180" show-overflow-tooltip />
        <el-table-column prop="question" label="问题" min-width="240" show-overflow-tooltip />
        <el-table-column label="动态时间" width="120">
          <template #default="{ row }">
            <el-tag :type="row.params?.dynamic_time ? 'success' : 'info'" size="small">
              {{ row.params?.dynamic_time ? '每次执行重算' : '固定' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150">
          <template #default="{ row }">
            <el-button size="small" type="primary" plain :loading="running === row.id" @click="run(row)">
              {{ running === row.id ? '执行中…' : '执行' }}
            </el-button>
            <el-button size="small" type="danger" plain @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!items.length" description="暂无收藏，在对话结果中点击收藏即可添加" :image-size="60" />
    </el-card>
  </div>
</template>

<style scoped>
.page { padding: 1.5rem; max-width: 1100px; margin: 0 auto; }
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; }
</style>