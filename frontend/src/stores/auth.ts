/** 全局登录态 store：让顶栏/登录页共享同一份响应式登录状态 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useAuthStore = defineStore('auth', () => {
  const loggedIn = ref(!!localStorage.getItem('token'))
  const phone = ref(localStorage.getItem('phone') || '')

  function setLogin(token: string, p: string) {
    localStorage.setItem('token', token)
    localStorage.setItem('phone', p)
    loggedIn.value = true
    phone.value = p
  }

  function clear() {
    localStorage.removeItem('token')
    localStorage.removeItem('phone')
    loggedIn.value = false
    phone.value = ''
  }

  return { loggedIn, phone, setLogin, clear }
})
