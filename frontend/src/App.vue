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
/* ===== Design tokens: brand palette overrides Element Plus defaults ===== */
:root {
  --t2s-primary: #4c6ef5;
  --t2s-primary-dark: #3c58c4;
  --t2s-grad: linear-gradient(135deg, #4c6ef5 0%, #6d5ce8 100%);
  --t2s-radius: 10px;
  --el-color-primary: #4c6ef5;
  --el-color-primary-light-3: #8299f8;
  --el-color-primary-light-5: #a6b6fa;
  --el-color-primary-light-7: #c9d3fc;
  --el-color-primary-light-8: #dbe2fd;
  --el-color-primary-light-9: #edf0fe;
  --el-color-primary-dark-2: #3c58c4;
  --el-border-radius-base: 8px;
  --el-font-family: 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Helvetica Neue', Arial, sans-serif;
}

/* ===== Component polish (rounded, soft shadows, gentle transitions) ===== */
.el-button { border-radius: 8px; transition: all .18s ease; }
.el-button--primary:not(.is-plain):not(.is-text) { box-shadow: 0 2px 8px rgb(76 110 245 / 28%); }
.el-button--primary:not(.is-plain):not(.is-text):hover { box-shadow: 0 4px 14px rgb(76 110 245 / 38%); transform: translateY(-1px); }
.el-card { border-radius: 12px; border: none; box-shadow: 0 1px 3px rgb(16 24 40 / 6%), 0 1px 2px rgb(16 24 40 / 4%); }
.el-table { border-radius: 10px; --el-table-header-bg-color: var(--el-fill-color-light); }
.el-table th.el-table__cell { font-weight: 600; }
.el-dialog { border-radius: 14px; }
.el-tabs__item { font-size: .95rem; }
.el-input__wrapper, .el-select__wrapper, .el-textarea__inner { border-radius: 8px; }

/* ===== Global typography ===== */
body {
  margin: 0;
  font-family: 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Helvetica Neue', Arial, sans-serif;
  background: var(--el-bg-color-page, #f7f8fa);
  color: var(--el-text-color-primary, #303133);
  -webkit-font-smoothing: antialiased;
}
a { text-decoration: none; color: var(--el-color-primary); }
.theme-toggle { position: fixed; right: 1rem; bottom: 1rem; z-index: 99; }

/* ===== Shared page header pattern (history / favorites / admin) ===== */
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.2rem; }
.page-header h1 { font-size: 1.25rem; margin: 0; letter-spacing: .5px; }
</style>