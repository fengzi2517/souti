<script setup lang="ts">
/** 解析详情页：答案 + 分步解析 + 三 Tab（解析/复盘/归纳）+ 举一反三入口 */
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, errText } from '../api'
import { renderMathHtml } from '../latex'

const route = useRoute()
const router = useRouter()
const tab = ref<'solve' | 'review' | 'summary'>('solve')
const loading = ref(true)
const error = ref('')
const generating = ref(false)
const data = ref<any>(null)

const tabs = [
  { key: 'solve', label: '📖 答案解析' },
  { key: 'review', label: '🔍 复盘' },
  { key: 'summary', label: '📌 归纳' },
]

onMounted(load)
watch(() => route.params.id, load)

async function load() {
  loading.value = true; error.value = ''
  try {
    const r = await api.get(`/api/questions/${route.params.id}`)
    data.value = r.data
  } catch (e) { error.value = errText(e) } finally { loading.value = false }
}

async function generatePractice() {
  generating.value = true; error.value = ''
  try {
    const r = await api.post('/api/practice/generate', { question_id: route.params.id })
    sessionStorage.setItem(`practice_${r.data.set_id}`, JSON.stringify(r.data))
    router.push(`/practice/${r.data.set_id}`)
  } catch (e) { error.value = errText(e) } finally { generating.value = false }
}

const mh = renderMathHtml
</script>

<template>
  <div class="container">
    <div v-if="loading" class="card" style="text-align:center; padding:60px">
      <span class="loading-dots">加载中</span>
    </div>
    <div v-else-if="error" class="card" style="color:#cf1322">{{ error }}</div>

    <template v-else-if="data">
      <!-- 题干 -->
      <div class="card">
        <div style="margin-bottom:8px">
          <span class="tag">{{ data.solution.grade_level }}</span>
          <span class="tag">{{ data.solution.subject }}</span>
        </div>
        <div class="question" v-html="mh(data.content_text)"></div>
      </div>

      <!-- Tab -->
      <div class="tabbar">
        <button v-for="t in tabs" :key="t.key" class="tab" :class="{ active: tab === t.key }" @click="tab = t.key as any">
          {{ t.label }}
        </button>
      </div>

      <!-- 解析 -->
      <template v-if="tab === 'solve'">
        <div class="card answer-card">
          <div class="sec-title">✅ 最终答案</div>
          <div class="answer" v-html="mh(data.solution.answer)"></div>
        </div>
        <div class="card">
          <div class="sec-title">📝 分步解析</div>
          <div v-for="(s, i) in data.solution.steps" :key="i" class="step">
            <div class="step-head">
              <span class="step-no">{{ i + 1 }}</span>
              <b>{{ s.title }}</b>
            </div>
            <div class="step-body" v-html="mh(s.content)"></div>
          </div>
        </div>
      </template>

      <!-- 复盘 -->
      <template v-else-if="tab === 'review'">
        <div class="card">
          <div class="sec-title">🎯 本题考点</div>
          <div><span v-for="p in data.solution.key_points" :key="p" class="tag">{{ p }}</span></div>
        </div>
        <div class="card">
          <div class="sec-title">⚠️ 易错点提醒</div>
          <ul class="plain-list">
            <li v-for="(m, i) in data.solution.common_mistakes" :key="i" v-html="mh('• ' + m)"></li>
          </ul>
        </div>
        <div class="card">
          <div class="sec-title">🩹 易错点自查</div>
          <p class="muted" style="margin-bottom:8px">如果你做错了这道题，对照以下易错点自查：</p>
          <div v-for="(m, i) in data.solution.common_mistakes" :key="i" class="cause-item">
            <span class="cause-tag cause-generic">易错</span>
            <span v-html="mh(m)"></span>
          </div>
          <div class="advice">
            💡 <b>建议动作：</b>重做一遍本题 → 完成下方"举一反三"训练 → 答错的题会自动进入错题本，3 天后重做。
          </div>
        </div>
      </template>

      <!-- 归纳 -->
      <template v-else>
        <div v-for="(k, i) in data.solution.knowledge_points" :key="i" class="card">
          <div class="sec-title">📌 {{ k.name }}</div>
          <div class="kp-row"><span class="kp-label">定义</span><span v-html="mh(k.definition)"></span></div>
          <div class="kp-row" v-if="k.formula"><span class="kp-label">公式</span><span v-html="mh(k.formula)"></span></div>
          <div class="kp-row" v-if="k.tip"><span class="kp-label">记忆点</span><span v-html="mh('💡 ' + k.tip)"></span></div>
        </div>
      </template>

      <!-- 举一反三入口 -->
      <div class="card" style="text-align:center; background:var(--primary-light); border-color:#adc6ff">
        <div style="font-size:16px; font-weight:600; margin-bottom:6px">🎯 学会了吗？来 4 道变式题检验一下</div>
        <div class="muted" style="margin-bottom:14px">同考点出题 · 基础 / 进阶 / 挑战难度梯度 · AI 批改讲评</div>
        <button class="btn" :disabled="generating" @click="generatePractice">
          <span v-if="generating" class="spin"></span>
          {{ generating ? 'AI 正在出题，约需 20~40 秒' : '开始举一反三' }}
        </button>
        <div class="muted" style="margin-top:8px; font-size:12px">第一次生成后同一道题再次进入会秒开</div>
      </div>
      <div v-if="error" class="card" style="color:#cf1322">{{ error }}</div>
    </template>
  </div>
</template>

<style scoped>
.question { font-size: 16px; line-height: 1.8; }
.tabbar { display: flex; gap: 4px; margin-bottom: 12px; }
.tab {
  flex: 1; padding: 10px; background: #fff; border: 1px solid var(--border);
  border-radius: 8px; cursor: pointer; font-size: 14px; color: var(--text-2);
}
.tab.active { border-color: var(--primary); color: var(--primary); font-weight: 600; background: var(--primary-light); }
.sec-title { font-weight: 600; margin-bottom: 10px; font-size: 15px; }
.answer-card { background: #f6ffed; border-color: #b7eb8f; }
.answer { font-size: 16px; font-weight: 600; }
.step { padding: 10px 0; border-bottom: 1px dashed var(--border); }
.step:last-child { border-bottom: none; }
.step-head { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.step-no {
  width: 20px; height: 20px; border-radius: 50%; background: var(--primary);
  color: #fff; font-size: 12px; display: inline-flex; align-items: center; justify-content: center;
}
.plain-list { list-style: none; }
.plain-list li { padding: 4px 0; }
.cause-item { display: flex; gap: 8px; align-items: baseline; padding: 6px 0; }
.cause-tag { padding: 1px 8px; border-radius: 8px; font-size: 12px; white-space: nowrap; }
.cause-generic { background: #fff7e6; color: #d46b08; }
.advice { background: var(--warn-bg); border: 1px solid var(--warn-border); border-radius: 8px; padding: 10px 12px; margin-top: 10px; }
.kp-row { display: flex; gap: 10px; padding: 5px 0; }
.kp-label { color: var(--primary); font-weight: 600; white-space: nowrap; }
</style>
