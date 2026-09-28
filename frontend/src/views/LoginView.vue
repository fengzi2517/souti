<script setup lang="ts">
/** 登录页：手机号 + 验证码（开发模式验证码直接回显） */
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, errText } from '../api'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const auth = useAuthStore()
const phone = ref('')
const code = ref('')
const sent = ref(false)
const devCode = ref('')
const sending = ref(false)
const logging = ref(false)
const msg = ref('')
const error = ref('')

async function sendCode() {
  if (!/^1\d{10}$/.test(phone.value)) { error.value = '请输入正确的 11 位手机号'; return }
  sending.value = true; error.value = ''
  try {
    const r = await api.post('/api/auth/send_code', { phone: phone.value })
    if (r.data.ok) {
      sent.value = true
      devCode.value = r.data.dev_code || ''
      msg.value = devCode.value ? `开发模式验证码：${devCode.value}` : r.data.message
    } else { error.value = r.data.message }
  } catch (e) { error.value = errText(e) } finally { sending.value = false }
}

async function login() {
  if (!code.value) return
  logging.value = true; error.value = ''
  try {
    const clientId = localStorage.getItem('client_id') || ''
    const r = await api.post('/api/auth/login', {
      phone: phone.value, code: code.value, client_id: clientId,
    })
    if (r.data.ok) {
      auth.setLogin(r.data.token, r.data.phone)
      router.push('/')
    } else { error.value = r.data.message }
  } catch (e) { error.value = errText(e) } finally { logging.value = false }
}

function logout() {
  auth.clear()
  router.push('/')
}
</script>

<template>
  <div class="container" style="max-width: 440px">
    <!-- 已登录 -->
    <div v-if="auth.loggedIn" class="card" style="text-align:center; padding:36px">
      <div style="font-size:40px">👤</div>
      <div style="font-size:17px; font-weight:600; margin:10px 0 4px">{{ auth.phone }}</div>
      <div class="muted" style="margin-bottom:18px">已登录 · 历史/错题云端同步</div>
      <button class="btn btn-ghost" @click="logout">退出登录</button>
    </div>

    <!-- 未登录 -->
    <template v-else>
      <div class="card">
        <h3 style="margin-bottom:14px">📱 登录后云端同步学习数据</h3>
        <div class="muted" style="margin-bottom:14px">
          登录后本次游客模式下的搜题历史、错题本会自动迁移到你的账号
        </div>
        <div style="display:flex; gap:8px">
          <input v-model="phone" class="input" style="flex:1" maxlength="11" placeholder="手机号" />
          <button class="btn btn-ghost btn-sm" :disabled="sending" @click="sendCode" style="white-space:nowrap">
            {{ sending ? '发送中…' : sent ? '重新发送' : '发送验证码' }}
          </button>
        </div>
        <input v-if="sent" v-model="code" class="input" style="margin-top:10px" maxlength="6" placeholder="6 位验证码" />
        <button
          v-if="sent" class="btn" style="width:100%; margin-top:12px"
          :disabled="!code || logging" @click="login"
        >
          <span v-if="logging" class="spin"></span>
          {{ logging ? '登录中…' : '登录' }}
        </button>
      </div>
      <div v-if="msg" class="card" style="background:var(--warn-bg); border-color:var(--warn-border)">{{ msg }}</div>
      <div v-if="error" class="card" style="color:#cf1322">{{ error }}</div>
    </template>
  </div>
</template>
