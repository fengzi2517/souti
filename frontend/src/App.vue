<script setup lang="ts">
import { onMounted } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { api } from './api'
import { useAuthStore } from './stores/auth'

const route = useRoute()
const auth = useAuthStore()
const navs = [
  { path: '/', label: '搜题' },
  { path: '/mistakes', label: '错题本' },
  { path: '/history', label: '历史' },
]

// 会话校验：本地 token 可能已过期（后端会静默降级为游客），挂载时校验一次，
// 过期则清理本地登录态（不跳转，游客模式合法），让顶栏状态与实际一致。
onMounted(async () => {
  if (!auth.loggedIn) return
  try {
    const res = await api.get('/api/auth/me')
    if (!res.data?.ok) auth.clear()
  } catch {
    // 网络异常不清理，保持现状
  }
})
</script>

<template>
  <header class="topbar">
    <div class="topbar-inner">
      <RouterLink to="/" class="logo">🧮 AI 解题助手</RouterLink>
      <nav>
        <RouterLink
          v-for="n in navs" :key="n.path" :to="n.path"
          class="nav-item" :class="{ active: route.path === n.path }"
        >{{ n.label }}</RouterLink>
      </nav>
      <RouterLink v-if="auth.loggedIn" to="/auth" class="tag" style="text-decoration:none">👤 {{ auth.phone }}</RouterLink>
      <RouterLink v-else to="/auth" class="tag" style="text-decoration:none; cursor:pointer">登录</RouterLink>
    </div>
  </header>
  <RouterView />
</template>

<style scoped>
.topbar {
  background: #fff; border-bottom: 1px solid var(--border);
  position: sticky; top: 0; z-index: 10;
}
.topbar-inner {
  max-width: 860px; margin: 0 auto; padding: 0 16px;
  height: 52px; display: flex; align-items: center; gap: 28px;
}
.logo { font-weight: 700; font-size: 16px; color: var(--primary); text-decoration: none; }
nav { display: flex; gap: 4px; flex: 1; }
.nav-item {
  padding: 6px 14px; border-radius: 6px; text-decoration: none;
  color: var(--text-2);
}
.nav-item:hover { background: var(--bg); }
.nav-item.active { color: var(--primary); font-weight: 600; background: var(--primary-light); }
</style>
