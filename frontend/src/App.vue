<script setup lang="ts">
// 根组件：路由 + Element Plus 中文语言包 + 暗色主题切换（持久化到 localStorage）
import { ref } from 'vue'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import { Moon, Sunny } from '@element-plus/icons-vue'

const dark = ref(localStorage.getItem('t2s-theme') === 'dark')
document.documentElement.classList.toggle('dark', dark.value)

function toggleTheme() {
  dark.value = !dark.value
  document.documentElement.classList.toggle('dark', dark.value)
  localStorage.setItem('t2s-theme', dark.value ? 'dark' : 'light')
}
</script>

<template>
  <el-config-provider :locale="zhCn">
    <router-view />
    <!-- 暗色/亮色切换：全局悬浮 -->
    <el-button class="theme-toggle" :icon="dark ? Sunny : Moon" circle
               :title="dark ? '切换亮色' : '切换暗色'" @click="toggleTheme" />
  </el-config-provider>
</template>

<style>
/* 全局基调：Element Plus 变量 + 基础排版（各视图 scoped 样式负责局部布局，暗色由 html.dark 变量自动生效） */
body {
  margin: 0;
  font-family: 'Helvetica Neue', Helvetica, 'PingFang SC', 'Hiragino Sans GB',
    'Microsoft YaHei', '微软雅黑', Arial, sans-serif;
  background: var(--el-bg-color-page, #f7f8fa);
  color: var(--el-text-color-primary, #303133);
  -webkit-font-smoothing: antialiased;
}
a { text-decoration: none; color: var(--el-color-primary, #4169e1); }
.theme-toggle { position: fixed; right: 1rem; bottom: 1rem; z-index: 99; }
</style>