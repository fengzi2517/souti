<script setup lang="ts">
/** 做题页：逐题作答（解析隐藏）→ 全部完成后提交批改 */
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, errText } from '../api'
import { renderMathHtml } from '../latex'

const route = useRoute()
const router = useRouter()
const setId = route.params.setId as string
const loading = ref(true)
const error = ref('')
const cur = ref(0)
const items = ref<any[]>([])
const answers = ref<Record<string, string>>({})
const submitting = ref(false)

onMounted(async () => {
  // 从缓存取刚生成的题目；刷新场景尝试回源（已提交过则直接看结果）
  const raw = sessionStorage.getItem(`practice_${setId}`)
  if (raw) {
    items.value = JSON.parse(raw).items
    loading.value = false
    return
  }
  try {
    await api.get(`/api/practice/${setId}/result`)
    // 能回源说明已提交过批改：直接展示结果页
    router.replace(`/practice/${setId}/result`)
    return
  } catch {
    // 未提交过（409）或不存在（404）：作答无法恢复，需重新生成
  }
  error.value = '练习数据已丢失（刷新页面会导致作答丢失），请返回解析页重新生成变式题'
  loading.value = false
})

const mh = renderMathHtml
const diffColor: Record<string, string> = { 基础: 'tag-ok', 进阶: 'tag', 挑战: 'tag-bad' }

function next() { if (cur.value < items.value.length - 1) cur.value++ }

async function submit() {
  submitting.value = true; error.value = ''
  try {
    const payload = {
      set_id: setId,
      answers: items.value.map((it) => ({ item_id: it.item_id, user_answer: answers.value[it.item_id] || '' })),
    }
    const r = await api.post('/api/practice/submit', payload)
    sessionStorage.setItem(`result_${setId}`, JSON.stringify(r.data))
    router.push(`/practice/${setId}/result`)
  } catch (e) { error.value = errText(e) } finally { submitting.value = false }
}

const allAnswered = () => items.value.every((it) => (answers.value[it.item_id] || '').trim())
</script>

<template>
  <div class="container" style="max-width: 680px">
    <div v-if="loading" class="card" style="text-align:center; padding:60px"><span class="loading-dots">加载中</span></div>
    <div v-else-if="error" class="card" style="color:#cf1322">
      {{ error }}
      <div style="margin-top:10px"><router-link class="btn btn-ghost btn-sm" to="/">返回首页</router-link></div>
    </div>

    <template v-else>
      <div class="card" style="display:flex; align-items:center; justify-content:space-between">
        <b>🎯 举一反三训练</b>
        <span class="muted">第 {{ cur + 1 }} / {{ items.length }} 题 · 已答 {{ items.filter(it => (answers[it.item_id]||'').trim()).length }} 题</span>
      </div>

      <!-- 题号导航 -->
      <div class="card" style="display:flex; gap:8px; padding:12px 20px">
        <button
          v-for="(it, i) in items" :key="it.item_id"
          class="nav-no" :class="{ active: i === cur, done: (answers[it.item_id]||'').trim() }"
          @click="cur = i"
        >{{ i + 1 }}</button>
      </div>

      <!-- 当前题 -->
      <div class="card">
        <span class="tag" :class="diffColor[items[cur].difficulty]">{{ items[cur].difficulty }}</span>
        <div class="q-text" v-html="mh(items[cur].question)"></div>
        <textarea
          v-model="answers[items[cur].item_id]" rows="3" class="input"
          placeholder="写下你的解答过程和最终答案…"
        ></textarea>
      </div>

      <div style="display:flex; gap:10px">
        <button v-if="cur > 0" class="btn btn-ghost" style="flex:1" @click="cur--">上一题</button>
        <button v-if="cur < items.length - 1" class="btn" style="flex:1" @click="next">下一题</button>
        <button v-else class="btn" style="flex:2" :disabled="!allAnswered() || submitting" @click="submit">
          <span v-if="submitting" class="spin"></span>
          {{ submitting ? 'AI 批改中，约需 20~40 秒' : '全部提交，AI 批改' }}
        </button>
      </div>
      <div v-if="error" class="card" style="color:#cf1322; margin-top:12px">{{ error }}</div>
    </template>
  </div>
</template>

<style scoped>
.q-text { font-size: 15px; line-height: 1.8; margin: 10px 0 14px; }
.nav-no {
  width: 30px; height: 30px; border-radius: 8px; border: 1px solid var(--border);
  background: #fff; cursor: pointer; color: var(--text-2);
}
.nav-no.active { border-color: var(--primary); color: var(--primary); font-weight: 700; }
.nav-no.done { background: var(--primary-light); color: var(--primary); }
</style>
