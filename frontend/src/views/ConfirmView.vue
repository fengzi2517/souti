<script setup lang="ts">
/** 图片确认页：展示 OCR 识别结果，用户可编辑修正后提交解析 */
import { onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api, errText, phaseHint, pollSolveTask } from '../api'

const router = useRouter()
const ocrText = ref('')
const imageUrl = ref('')
const grade = ref(localStorage.getItem('grade') || '初中')
// 学段选择持久化（P2-2）：此处修改同步写回，下次进入任何页面保持一致
watch(grade, (g) => localStorage.setItem('grade', g))
const loading = ref(true)
const solving = ref(false)
const visionSolving = ref(false)
const progress = ref('')
const error = ref('')

let imageId = ''
onMounted(async () => {
  const raw = localStorage.getItem('pending_image')
  if (!raw) { router.replace('/'); return }
  const img = JSON.parse(raw)
  imageUrl.value = img.image_url
  imageId = img.image_id
  try {
    // 密集大图 OCR 可达数分钟，单独放宽本请求超时（全局仍为 300s）
  const r = await api.post('/api/ocr', { image_id: img.image_id }, { timeout: 600000 })
    ocrText.value = r.data.text
    if (!ocrText.value) error.value = '未识别出文字，可手动编辑补充，或返回改用文字输入'
  } catch (e) { error.value = errText(e) } finally { loading.value = false }
})

async function solve() {
  if (!ocrText.value.trim()) return
  solving.value = true; error.value = ''
  progress.value = 'AI 正在读题…'
  try {
    const r = await api.post('/api/solve', { text: ocrText.value.trim(), grade_level: grade.value })
    // 任务化（O-1）：缓存命中直接 done；否则轮询并显示阶段进度
    const qid = r.data.status === 'done' && r.data.question_id
      ? r.data.question_id
      : await pollSolveTask(r.data.task_id, (ms) => { progress.value = phaseHint(ms) })
    localStorage.removeItem('pending_image')
    router.push(`/solution/${qid}`)
  } catch (e) { error.value = errText(e) } finally { solving.value = false }
}

async function solveVision() {
  if (!imageId) return
  visionSolving.value = true; error.value = ''
  progress.value = 'AI 正在读图…'
  try {
    const r = await api.post('/api/solve', {
      image_id: imageId, grade_level: grade.value, direct_image: true,
    })
    const qid = r.data.status === 'done' && r.data.question_id
      ? r.data.question_id
      : await pollSolveTask(r.data.task_id, (ms) => { progress.value = phaseHint(ms) })
    localStorage.removeItem('pending_image')
    router.push(`/solution/${qid}`)
  } catch (e) { error.value = errText(e) } finally { visionSolving.value = false }
}
</script>

<template>
  <div class="container" style="max-width: 640px">
    <div class="card">
      <h3 style="margin-bottom:12px">📷 确认识别结果</h3>
      <img v-if="imageUrl" :src="imageUrl" style="max-width:100%; max-height:220px; border-radius:8px; border:1px solid var(--border)" />
    </div>

    <div class="card">
      <div style="display:flex; align-items:center; gap:8px; margin-bottom:10px">
        <span class="muted">识别结果（可编辑修正）：</span>
        <span v-if="loading" class="loading-dots">识别中</span>
      </div>
      <textarea v-model="ocrText" rows="6" class="input" placeholder="识别出的题目文字会显示在这里，可手动修正" :disabled="loading"></textarea>
      <div style="display:flex; gap:8px; align-items:center; margin-top:12px">
        <span class="muted">学段：</span>
        <button v-for="g in ['小学','初中','高中']" :key="g" class="btn btn-sm" :class="g===grade?'':'btn-ghost'" @click="grade=g">{{ g }}</button>
      </div>
      <button class="btn" style="width:100%; margin-top:12px" :disabled="!ocrText.trim() || solving" @click="solve">
        <span v-if="solving" class="spin"></span>
        {{ solving ? progress : '确认无误，开始解析' }}
      </button>
      <div class="divider"><span>或</span></div>
      <button class="btn btn-ghost" style="width:100%" :disabled="visionSolving" @click="solveVision">
        <span v-if="visionSolving" class="spin"></span>
        {{ visionSolving ? progress : '🧠 公式复杂？跳过识别，图片直传 AI 解析' }}
      </button>
      <div class="muted" style="margin-top:6px; text-align:center">分式、根号等复杂数学排版识别易错，推荐直传原图保公式完整</div>
    </div>

    <div v-if="error" class="error-box">{{ error }}</div>
    <router-link to="/" class="muted">← 返回重新上传</router-link>
  </div>
</template>

<style scoped>
.error-box {
  background: #fff1f0; border: 1px solid #ffa39e; color: #cf1322;
  border-radius: 8px; padding: 10px 14px; margin-bottom: 16px;
}
.divider { text-align: center; color: var(--text-2); margin: 12px 0; position: relative; }
.divider::before { content: ''; position: absolute; left: 0; right: 0; top: 50%; border-top: 1px solid var(--border); }
.divider span { position: relative; background: #fff; padding: 0 12px; }
</style>
