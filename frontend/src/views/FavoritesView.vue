<script setup lang="ts">
// 收藏管理（FR-HIS-04/05）：列表 + 重执行（动态时间参数）+ 删除
import { onMounted, ref } from 'vue'
import { deleteFavorite, getFavorites, runFavorite } from '../api'

interface Fav { id: number; name: string; question: string; datasource_id: number; params: Record<string, unknown> | null }
const items = ref<Fav[]>([])
const running = ref<number>(0)
const runResult = ref<string>('')

async function load() { items.value = await getFavorites() }

async function run(f: Fav) {
  running.value = f.id
  runResult.value = ''
  try {
    const r = await runFavorite(f.id)
    runResult.value = r.exec_status === 'success'
      ? `执行成功，返回 ${r.result?.row_count ?? 0} 行（时间条件已按当前日期重算，AC-10）`
      : `执行状态：${r.exec_status}`
  } catch (e: unknown) {
    const resp = (e as { response?: { data?: { message?: string } } }).response
    runResult.value = resp?.data?.message ?? '执行失败'
  } finally {
    running.value = 0
  }
}

async function remove(f: Fav) {
  await deleteFavorite(f.id)
  await load()
}
onMounted(load)
</script>

<template>
  <div class="page">
    <h1>我的收藏</h1>
    <p v-if="runResult" class="result">{{ runResult }}</p>
    <table>
      <thead><tr><th>名称</th><th>问题</th><th>动态时间</th><th>操作</th></tr></thead>
      <tbody>
        <tr v-for="f in items" :key="f.id">
          <td>{{ f.name }}</td>
          <td>{{ f.question }}</td>
          <td>{{ f.params?.dynamic_time ? '每次执行重算' : '固定' }}</td>
          <td>
            <button :disabled="running === f.id" @click="run(f)">{{ running === f.id ? '执行中…' : '执行' }}</button>
            <button class="danger" @click="remove(f)">删除</button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.page { padding: 1.5rem; }
table { width: 100%; border-collapse: collapse; font-size: .85rem; }
th, td { border: 1px solid #eee; padding: .5rem .8rem; text-align: left; }
button { padding: .25rem .7rem; margin-right: .4rem; cursor: pointer; }
.danger { color: #d33; }
.result { padding: .6rem 1rem; background: #f6ffed; border: 1px solid #b7eb8f; border-radius: 8px; }
</style>
