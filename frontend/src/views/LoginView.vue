<script setup lang="ts">
// 登录页（FR-SEC-40）
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { login } from '../api'

const router = useRouter()
const username = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)

async function doLogin() {
  error.value = ''
  loading.value = true
  try {
    await login(username.value, password.value)
    router.push('/')
  } catch (e: unknown) {
    const resp = (e as { response?: { data?: { message?: string } } }).response
    error.value = resp?.data?.message ?? '登录失败，请检查用户名密码'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-wrap">
    <form class="login-card" @submit.prevent="doLogin">
      <h1>Text2SQL 智能数据分析平台</h1>
      <input v-model="username" placeholder="用户名" autocomplete="username" />
      <input v-model="password" type="password" placeholder="密码" autocomplete="current-password" />
      <button type="submit" :disabled="loading">{{ loading ? '登录中…' : '登录' }}</button>
      <p v-if="error" class="error">{{ error }}</p>
    </form>
  </div>
</template>

<style scoped>
.login-wrap { min-height: 100vh; display: flex; align-items: center; justify-content: center; background: #f5f6fa; }
.login-card { width: 340px; padding: 2rem; background: #fff; border-radius: 12px; display: flex; flex-direction: column; gap: .8rem; box-shadow: 0 2px 12px rgb(0 0 0 / 8%); }
.login-card h1 { font-size: 1.1rem; text-align: center; }
input { padding: .6rem .8rem; border: 1px solid #ddd; border-radius: 8px; }
button { padding: .6rem; background: #4169e1; color: #fff; border: 0; border-radius: 8px; cursor: pointer; }
.error { color: #d33; font-size: .85rem; }
</style>
