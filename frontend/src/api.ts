/** API 客户端：统一 baseURL、客户端标识、错误处理、登录态管理 */
import axios from 'axios'

function getClientId(): string {
  let cid = localStorage.getItem('client_id')
  if (!cid) {
    cid = crypto.randomUUID()
    localStorage.setItem('client_id', cid)
  }
  return cid
}

// 部署环境变量化：开发走 vite 代理（baseURL 为空），生产同源部署或设 VITE_API_BASE
export const api = axios.create({
  baseURL: (import.meta.env.VITE_API_BASE as string | undefined) || '',
  timeout: 300000,
})
api.interceptors.request.use((cfg) => {
  cfg.headers['X-Client-Id'] = getClientId()
  const token = localStorage.getItem('token')
  if (token) cfg.headers['Authorization'] = `Bearer ${token}`
  return cfg
})

// 401 拦截：token 过期/无效时清理本地登录态并引导重新登录
// （数据接口会静默降级为游客模式，这里只在明确收到 401 时提示）
api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('phone')
      // 用 location 而非 router 跳转，避免循环依赖；已在登录页则不跳
      if (!window.location.pathname.startsWith('/auth')) {
        window.location.href = '/auth'
      }
    }
    return Promise.reject(err)
  }
)

// ---------- 解析任务轮询（O-1） ----------
// POST /api/solve 立即返回 task_id，LLM 解析在后台执行；前端轮询至完成
export interface SolveTaskStatus {
  task_id: string
  status: 'pending' | 'running' | 'done' | 'failed'
  question_id?: string | null
  cached?: boolean
  error?: string | null
}

export async function pollSolveTask(
  taskId: string,
  onTick?: (elapsedMs: number) => void,
  intervalMs = 2000,
  timeoutMs = 600000, // OCR 密集大图可达 ~450s + LLM 解析，需与后端 _WORKER_TIMEOUT 对齐
): Promise<string> {
  const start = Date.now()
  for (;;) {
    if (Date.now() - start > timeoutMs) {
      throw new Error('解析超时，题目可能仍在后台处理，稍后可在搜题历史中查看')
    }
    const r = await api.get<SolveTaskStatus>(`/api/tasks/${taskId}`)
    const s = r.data
    if (s.status === 'done' && s.question_id) return s.question_id
    if (s.status === 'failed') throw new Error(s.error || '解析失败，请稍后再试')
    onTick?.(Date.now() - start)
    await new Promise((res) => setTimeout(res, intervalMs))
  }
}

// 按耗时给出阶段性进度话术（LLM 无法上报真实进度，用时间分段安抚等待）
export function phaseHint(elapsedMs: number): string {
  const s = elapsedMs / 1000
  if (s < 8) return 'AI 正在读题…'
  if (s < 20) return '正在推理分析…'
  if (s < 40) return '正在书写分步解析…'
  return '深度思考中，即将完成…'
}

export function errText(e: unknown): string {
  const err = e as {
    response?: { data?: { detail?: string }; status?: number }
    code?: string
  }
  if (err.response?.data?.detail) return err.response.data.detail
  if (err.response?.status === 429) return '今日次数已达上限，明天再来吧'
  if (err.code === 'ECONNABORTED') return '请求超时，请稍后重试'
  // pollSolveTask 抛出的普通 Error（任务失败原因/轮询超时提示）需原样透出，不能误报成网络异常
  if (err instanceof Error && err.message) return err.message
  return '网络异常，请稍后重试'
}
