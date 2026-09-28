<script setup lang="ts">
/**
 * 首页/搜题页：图片上传 + 文字输入 + 最近搜题摘要
 * 图片 → /confirm 确认识别；文字 → 直接解析
 */
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api, errText, phaseHint, pollSolveTask } from '../api'

const router = useRouter()
const grade = ref(localStorage.getItem('grade') || '初中')
const grades = ['小学', '初中', '高中']
const text = ref('')
const solving = ref(false)
const progress = ref('')
const error = ref('')
const fileInput = ref<HTMLInputElement>()
const dragging = ref(false)
const privacyOk = ref(false)

// 学段选择持久化：图片流程跳转确认页后学段不丢失（P2-2）
watch(grade, (g) => localStorage.setItem('grade', g))

// 粘贴上传：监听 document 粘贴事件，剪贴板含图片文件时直接上传（P2-7）
function onPaste(e: ClipboardEvent) {
  const file = e.clipboardData?.files?.[0]
  if (file) {
    e.preventDefault()
    onFile(file)
  }
}
onMounted(() => document.addEventListener('paste', onPaste))
onUnmounted(() => document.removeEventListener('paste', onPaste))

async function onFile(file: File) {
  error.value = ''
  if (!['image/jpeg', 'image/png'].includes(file.type)) { error.value = '仅支持 JPG/PNG 图片'; return }
  if (file.size > 10 * 1024 * 1024) { error.value = '图片超过 10MB 限制'; return }
  const fd = new FormData()
  fd.append('file', file)
  try {
    const r = await api.post('/api/upload', fd)
    localStorage.setItem('pending_image', JSON.stringify(r.data))
    router.push('/confirm')
  } catch (e) { error.value = errText(e) }
}

function pick() { fileInput.value?.click() }
function onDrop(e: DragEvent) {
  dragging.value = false
  const f = e.dataTransfer?.files?.[0]
  if (f) onFile(f)
}

async function solveText() {
  if (!text.value.trim() || !privacyOk.value) return
  solving.value = true; error.value = ''
  progress.value = 'AI 正在读题…'
  try {
    const r = await api.post('/api/solve', { text: text.value.trim(), grade_level: grade.value })
    // 任务化（O-1）：缓存命中直接 done；否则轮询 task_id，期间显示阶段进度
    const qid = r.data.status === 'done' && r.data.question_id
      ? r.data.question_id
      : await pollSolveTask(r.data.task_id, (ms) => { progress.value = phaseHint(ms) })
    router.push(`/solution/${qid}`)
  } catch (e) { error.value = errText(e) } finally { solving.value = false }
}
</script>

<template>
  <div class="container" style="max-width: 640px">
    <!-- 学段选择 -->
    <div class="card" style="display:flex; align-items:center; gap:8px">
      <span class="muted">学段：</span>
      <button
        v-for="g in grades" :key="g" class="btn btn-sm"
        :class="g === grade ? '' : 'btn-ghost'"
        @click="grade = g"
      >{{ g }}</button>
    </div>

    <!-- 图片上传 -->
    <div
      class="card upload-zone" :class="{ drag: dragging }"
      @click="pick" @dragover.prevent="dragging = true" @dragleave="dragging = false" @drop.prevent="onDrop"
    >
      <div class="up-icon">📷</div>
      <div class="up-title">点击上传题目图片</div>
      <div class="muted">支持 JPG / PNG，单张 ≤ 10MB，也可拖拽或粘贴</div>
      <input ref="fileInput" type="file" accept="image/jpeg,image/png" hidden @change="onFile(($event.target as HTMLInputElement).files![0])" />
    </div>

    <div class="divider"><span>或</span></div>

    <!-- 文字输入 -->
    <div class="card">
      <textarea
        v-model="text" rows="4" class="input"
        placeholder="手动输入题目文字，例如：解方程 x^2 - 5x + 6 = 0（数学公式可用 $x^2$ 这种 LaTeX 写法）"
      ></textarea>
      <label class="muted" style="display:flex; gap:6px; align-items:center; margin-top:10px; cursor:pointer">
        <input v-model="privacyOk" type="checkbox" />
        我已知悉：上传内容可能包含个人信息，仅用于本次解题
      </label>
      <button class="btn" style="width:100%; margin-top:12px" :disabled="!text.trim() || !privacyOk || solving" @click="solveText">
        <span v-if="solving" class="spin"></span>
        {{ solving ? progress : '开始解析' }}
      </button>
    </div>

    <div v-if="error" class="error-box">{{ error }}</div>

    <!-- 快捷入口 -->
    <div style="display:flex; gap:12px">
      <router-link to="/mistakes" class="quick">📕 错题本</router-link>
      <router-link to="/history" class="quick">🕘 搜题历史</router-link>
    </div>
  </div>
</template>

<style scoped>
.upload-zone {
  text-align: center; padding: 44px 20px; cursor: pointer;
  border: 2px dashed var(--border); transition: 0.15s;
}
.upload-zone:hover, .upload-zone.drag { border-color: var(--primary); background: var(--primary-light); }
.up-icon { font-size: 40px; }
.up-title { font-size: 16px; font-weight: 600; margin: 8px 0 4px; }
.divider { text-align: center; color: var(--text-2); margin: 4px 0 12px; position: relative; }
.divider::before { content: ''; position: absolute; left: 0; right: 0; top: 50%; border-top: 1px solid var(--border); }
.divider span { position: relative; background: var(--bg); padding: 0 12px; }
.error-box {
  background: #fff1f0; border: 1px solid #ffa39e; color: #cf1322;
  border-radius: 8px; padding: 10px 14px; margin-bottom: 16px;
}
.quick {
  flex: 1; text-align: center; background: #fff; border: 1px solid var(--border);
  border-radius: 10px; padding: 12px; text-decoration: none; color: var(--text);
}
.quick:hover { border-color: var(--primary); color: var(--primary); }
</style>
