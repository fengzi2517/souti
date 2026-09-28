<script setup lang="ts">
/** 搜题历史：时间线列表，点击回看解析 */
import { onMounted, ref } from 'vue'
import { api, errText } from '../api'

const items = ref<any[]>([])
const loading = ref(true)
const loadingMore = ref(false)
const error = ref('')
const total = ref(0)

const PAGE_SIZE = 50

function fmt(iso: string) {
  const d = new Date(iso)
  return `${d.getMonth() + 1}月${d.getDate()}日 ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

onMounted(async () => {
  try {
    const r = await api.get('/api/history', { params: { offset: 0, limit: PAGE_SIZE } })
    items.value = r.data.items
    total.value = r.data.total
  } catch (e) { error.value = errText(e) } finally { loading.value = false }
})

async function loadMore() {
  loadingMore.value = true
  try {
    const r = await api.get('/api/history', { params: { offset: items.value.length, limit: PAGE_SIZE } })
    items.value.push(...r.data.items)
    total.value = r.data.total
  } catch (e) { error.value = errText(e) } finally { loadingMore.value = false }
}
</script>

<template>
  <div class="container" style="max-width: 680px">
    <div class="card" style="display:flex; gap:10px; align-items:center">
      <b>🕘 搜题历史</b>
      <span class="tag tag-gray" style="margin-left:auto">{{ total }} 条</span>
    </div>

    <div v-if="loading" class="card" style="text-align:center; padding:60px"><span class="loading-dots">加载中</span></div>
    <div v-else-if="error" class="card" style="color:#cf1322">{{ error }}</div>
    <div v-else-if="!items.length" class="card" style="text-align:center; padding:50px">
      <div style="font-size:36px">🔍</div>
      <div class="muted" style="margin-top:8px">还没有搜题记录</div>
    </div>

    <router-link
      v-for="h in items" :key="h.question_id + h.created_at"
      :to="`/solution/${h.question_id}`" class="card h-item"
    >
      <div class="h-text">{{ h.content_text.slice(0, 80) }}{{ h.content_text.length > 80 ? '…' : '' }}</div>
      <div class="h-meta">
        <span class="tag" v-if="h.grade_level">{{ h.grade_level }}</span>
        <span class="tag tag-gray" v-if="h.subject">{{ h.subject }}</span>
        <span class="muted">{{ fmt(h.created_at) }}</span>
      </div>
    </router-link>

    <button
      v-if="items.length < total" class="btn btn-ghost"
      style="width:100%" :disabled="loadingMore" @click="loadMore"
    >
      <span v-if="loadingMore" class="spin"></span>
      {{ loadingMore ? '加载中' : `加载更多（已显示 ${items.length} / ${total} 条）` }}
    </button>
  </div>
</template>

<style scoped>
.h-item { text-decoration: none; color: var(--text); display: block; }
.h-item:hover { border-color: var(--primary); }
.h-text { margin-bottom: 8px; line-height: 1.7; }
.h-meta { display: flex; align-items: center; gap: 8px; }
</style>
