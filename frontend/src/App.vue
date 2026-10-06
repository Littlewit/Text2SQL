<script setup lang="ts">
// 根组件：仅承载路由（布局在各视图内实现）
</script>

<template>
  <router-view />
</template>

<style>
/* 全局基调：Element Plus 变量 + 基础排版（各视图 scoped 样式负责局部布局） */
body {
  margin: 0;
  font-family: 'Helvetica Neue', Helvetica, 'PingFang SC', 'Hiragino Sans GB',
    'Microsoft YaHei', '微软雅黑', Arial, sans-serif;
  background: #f7f8fa;
  color: var(--el-text-color-primary, #303133);
  -webkit-font-smoothing: antialiased;
}
a { text-decoration: none; color: var(--el-color-primary, #4169e1); }
</style>