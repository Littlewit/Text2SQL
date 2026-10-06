<script setup lang="ts">
// 登录页（FR-SEC-40）：Element Plus 表单
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { login } from '../api'

const router = useRouter()
const loading = ref(false)
const form = reactive({ username: '', password: '' })

async function doLogin() {
  if (!form.username || !form.password) {
    ElMessage.warning('请输入用户名与密码')
    return
  }
  loading.value = true
  try {
    await login(form.username, form.password)
    router.push('/')
  } catch (e: unknown) {
    const resp = (e as { response?: { data?: { message?: string } } }).response
    ElMessage.error(resp?.data?.message ?? '登录失败，请检查用户名密码')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-wrap">
    <el-card class="login-card" shadow="always">
      <h1>Text2SQL 智能数据分析平台</h1>
      <p class="subtitle">用自然语言查询数据库，即刻生成图表与结论</p>
      <el-form label-position="top" @submit.prevent="doLogin">
        <el-form-item label="用户名">
          <el-input v-model="form.username" placeholder="用户名" autocomplete="username" size="large" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" placeholder="密码" autocomplete="current-password"
                    size="large" show-password @keyup.enter="doLogin" />
        </el-form-item>
        <el-button type="primary" size="large" class="login-btn" :loading="loading" native-type="submit">
          {{ loading ? '登录中…' : '登 录' }}
        </el-button>
      </el-form>
    </el-card>
  </div>
</template>

<style scoped>
.login-wrap { min-height: 100vh; display: flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg, #edf0fe 0%, #f7f8fa 55%, #f3effe 100%); }
.login-card { width: 390px; border-radius: 16px; padding: .4rem .4rem .2rem; }
.login-card h1 { font-size: 1.2rem; text-align: center; margin: 0 0 .3rem; letter-spacing: .5px; }
.subtitle { text-align: center; color: var(--el-text-color-secondary); font-size: .8rem; margin: 0 0 1.2rem; }
.login-btn { width: 100%; margin-top: .4rem; --el-button-box-shadow: none; }
</style>