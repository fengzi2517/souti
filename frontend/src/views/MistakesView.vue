<script setup lang="ts">
/** 错题本：筛选（科目/错因）+ 展开 + 移除 + 重做入口 */
import { onMounted, ref } from 'vue'
import { api, errText } from '../api'
import { renderMathHtml } from '../latex'

const mh = renderMathHtml

const items = ref<any[]>([])
const loading = ref(true)
const loadingMore = ref(false)
const error = ref('')
const expanded = ref<number | null>(null)
const filterSubject = ref('')
const filterCause = ref('')
const total = ref(0)

const causes = ['概念不清', '审题偏差', '计算失误', '方法缺失']
const PAGE_SIZE = 50

async function load() {
  loading.value = true; error.value = ''
  try {
    const params: any = { offset: 0, limit: PAGE_SIZE }
    if (filterSubject.value) params.subject = filterSubject.value
    if (filterCause.value) params.error_cause = filterCause.value
    const r = await api.get('/api/mistakes', { params })
    items.value = r.data.items
    total.value = r.data.total
  } catch (e) { error.value = errText(e) } finally { loading.value = false }
}

async function loadMore() {
  loadingMore.value = true
  try {
    const params: any = { offset: items.value.length, limit: PAGE_SIZE }
    if (filterSubject.value) params.subject = filterSubject.value
    if (filterCause.value) params.error_cause = filterCause.value
    const r = await api.get('/api/mistakes', { params })
    items.value.push(...r.data.items)
    total.value = r.data.total
  } catch (e) { error.value = errText(e) } finally { loadingMore.value = false }
}

async function remove(id: number) {
  await api.delete(`/api/mistakes/${id}`)
  await load()
}

onMounted(load)
</script>

<template>
  <div class="container" style="max-width: 680px">
    <div class="card" style="display:flex; gap:10px; align-items:center; flex-wrap:wrap">
      <b>📕 错题本</b>
      <span class="tag tag-gray" style="margin-left:auto">{{ total }} 道</span>
    </div>

    <div class="card" style="display:flex; gap:8px; align-items:center; padding:12px 20px; flex-wrap:wrap">
      <span class="muted">错因：</span>
      <button class="btn btn-sm" :class="!filterCause ? '' : 'btn-ghost'" @click="filterCause = ''; load()">全部</button>
      <button
        v-for="c in causes" :key="c" class="btn btn-sm"
        :class="filterCause === c ? '' : 'btn-ghost'" @click="filterCause = c; load()"
      >{{ c }}</button>
    </div>

    <div v-if="loading" class="card" style="text-align:center; padding:60px"><span class="loading-dots">加载中</span></div>
    <div v-else-if="error" class="card" style="color:#cf1322">{{ error }}</div>
    <div v-else-if="!items.length" class="card" style="text-align:center; padding:50px">
      <div style="font-size:36px">🎉</div>
      <div class="muted" style="margin-top:8px">错题本是空的，去做几道题试试</div>
    </div>

    <div v-for="m in items" :key="m.id" class="card mistake">
      <div class="m-head" @click="expanded = expanded === m.id ? null : m.id">
        <span class="tag" v-if="m.error_cause" style="background:#fff1f0; color:#cf1322">{{ m.error_cause }}</span>
        <span class="tag tag-gray" v-if="m.subject">{{ m.subject }}</span>
        <span class="m-title" v-html="mh(m.title)"></span>
      </div>
      <div v-if="expanded === m.id" class="m-body">
        <div class="m-sec"><b>题目：</b><span v-html="mh(m.content)"></span></div>
        <div class="m-sec" v-if="m.answer"><b>答案：</b><span class="ans" v-html="mh(m.answer)"></span></div>
        <div style="display:flex; gap:8px; margin-top:10px">
          <button class="btn btn-sm" @click="expanded = null">收起</button>
          <button class="btn btn-ghost btn-sm" @click="remove(m.id)">移出错题本</button>
        </div>
      </div>
    </div>

    <button
      v-if="items.length < total" class="btn btn-ghost"
      style="width:100%; margin-bottom:16px" :disabled="loadingMore" @click="loadMore"
    >
      <span v-if="loadingMore" class="spin"></span>
      {{ loadingMore ? '加载中' : `加载更多（已显示 ${items.length} / ${total} 道）` }}
    </button>
  </div>
</template>

<style scoped>
.m-head { display: flex; align-items: center; gap: 8px; cursor: pointer; }
.m-title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.m-body { border-top: 1px dashed var(--border); margin-top: 10px; padding-top: 10px; }
.m-sec { padding: 4px 0; line-height: 1.8; }
.ans { color: var(--success); }
</style>
