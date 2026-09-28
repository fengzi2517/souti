<script setup lang="ts">
/** 批改结果页：得分总览 + 逐题讲评 + 错题入本提示；刷新后自动从服务端回源 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, errText } from '../api'
import { renderMathHtml } from '../latex'

const route = useRoute()
const router = useRouter()
const setId = route.params.setId as string
const results = ref<any[]>([])
const practiceItems = ref<any[]>([])
const questionId = ref('')
const cur = ref(0)
const loading = ref(true)
const error = ref('')
const regenerating = ref(false)

onMounted(async () => {
  const r = sessionStorage.getItem(`result_${setId}`)
  const p = sessionStorage.getItem(`practice_${setId}`)
  if (r) results.value = JSON.parse(r).results
  if (p) {
    const parsed = JSON.parse(p)
    practiceItems.value = parsed.items
    questionId.value = parsed.question_id || ''
  }
  // 刷新后 sessionStorage 丢失：回源接口从数据库恢复（P2-5）
  if (!results.value.length || !practiceItems.value.length) {
    try {
      const res = await api.get(`/api/practice/${setId}/result`)
      results.value = res.data.results
      practiceItems.value = res.data.items
      questionId.value = res.data.question_id || ''
    } catch (e) {
      error.value = errText(e)
    }
  }
  loading.value = false
})

// 换一套（O-3）：refresh 绕过变式题缓存重新生成
async function regenerate() {
  if (!questionId.value || regenerating.value) return
  regenerating.value = true; error.value = ''
  try {
    const r = await api.post('/api/practice/generate', {
      question_id: questionId.value, refresh: true,
    })
    sessionStorage.setItem(`practice_${r.data.set_id}`, JSON.stringify(r.data))
    router.push(`/practice/${r.data.set_id}`)
  } catch (e) { error.value = errText(e) } finally { regenerating.value = false }
}

const correctCount = computed(() => results.value.filter((r) => r.is_correct).length)
const curResult = computed(() => results.value[cur.value])
const curItem = computed(() => practiceItems.value[cur.value])
const mh = renderMathHtml

function itemById(id: string) { return practiceItems.value.find((p) => p.item_id === id) }
</script>

<template>
  <div class="container" style="max-width: 680px">
    <div v-if="loading" class="card" style="text-align:center; padding:60px"><span class="loading-dots">加载中</span></div>
    <div v-else-if="error" class="card" style="color:#cf1322">
      {{ error }}
      <div style="margin-top:10px"><router-link class="btn btn-ghost btn-sm" to="/">返回首页</router-link></div>
    </div>

    <template v-else>
    <!-- 总览 -->
    <div class="card score-card">
      <div class="score-num" :class="correctCount === results.length ? 'good' : ''">
        {{ correctCount }} / {{ results.length }}
      </div>
      <div class="muted" style="margin-bottom:10px">
        {{ correctCount === results.length ? '全部正确，太棒了！🎉' : `答对 ${correctCount} 题，错题已自动收录到错题本` }}
      </div>
      <div style="display:flex; gap:8px; justify-content:center">
        <button
          v-for="(r, i) in results" :key="r.item_id"
          class="nav-no" :class="{ ok: r.is_correct, bad: !r.is_correct, active: i === cur }"
          @click="cur = i"
        >{{ i + 1 }}</button>
      </div>
    </div>

    <!-- 逐题讲评 -->
    <template v-if="curResult">
      <div class="card">
        <div style="margin-bottom:8px">
          <span class="tag" :class="curResult.is_correct ? 'tag-ok' : 'tag-bad'">
            {{ curResult.is_correct ? '✓ 回答正确' : '✗ 回答错误' }}
          </span>
          <span v-if="curResult.error_cause" class="tag" style="background:#fff1f0; color:#cf1322">错因：{{ curResult.error_cause }}</span>
        </div>
        <div class="q-text" v-html="mh(itemById(curResult.item_id)?.question || '')"></div>
        <div class="block">
          <div class="blk-label">你的作答</div>
          <div v-html="mh(curResult.user_answer || '（未填写）')"></div>
        </div>
        <div class="block good-block">
          <div class="blk-label">✅ 标准答案</div>
          <div v-html="mh(curResult.standard_answer)"></div>
        </div>
        <div class="block fb-block">
          <div class="blk-label">👨‍🏫 AI 讲评</div>
          <div v-html="mh(curResult.feedback)"></div>
        </div>
      </div>
      <div style="display:flex; gap:10px">
        <button v-if="cur > 0" class="btn btn-ghost" style="flex:1" @click="cur--">上一题</button>
        <button v-if="cur < results.length - 1" class="btn" style="flex:1" @click="cur++">下一题</button>
      </div>
      <div style="display:flex; gap:10px; margin-top:12px">
        <router-link to="/mistakes" class="btn btn-ghost" style="flex:1">查看错题本</router-link>
        <button v-if="questionId" class="btn btn-ghost" style="flex:1" :disabled="regenerating" @click="regenerate">
          <span v-if="regenerating" class="spin"></span>
          {{ regenerating ? 'AI 出题中…' : '换一套再练' }}
        </button>
        <router-link to="/" class="btn" style="flex:1">再搜一题</router-link>
      </div>
    </template>
    </template>
  </div>
</template>

<style scoped>
.score-card { text-align: center; padding: 26px; }
.score-num { font-size: 40px; font-weight: 700; }
.score-num.good { color: var(--success); }
.nav-no {
  width: 30px; height: 30px; border-radius: 8px; border: 1px solid var(--border);
  background: #fff; cursor: pointer;
}
.nav-no.ok { color: var(--success); }
.nav-no.bad { color: var(--danger); }
.nav-no.active { border-width: 2px; font-weight: 700; }
.q-text { font-size: 15px; line-height: 1.8; margin-bottom: 12px; }
.block { border-radius: 8px; padding: 10px 12px; margin-top: 10px; background: var(--bg); }
.good-block { background: #f6ffed; }
.fb-block { background: var(--primary-light); }
.blk-label { font-weight: 600; margin-bottom: 4px; font-size: 13px; }
</style>
