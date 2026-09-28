/** LaTeX 公式渲染：把文本中的 $...$ / $$...$$ 片段渲染为 KaTeX HTML，失败降级原文 */
import katex from 'katex'

export function renderMathHtml(text: string): string {
  if (!text) return ''
  const esc = (s: string) =>
    s
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      // LLM 常输出 markdown 粗体，转为 <b>
      .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
      .replace(/`([^`]+)`/g, '<code>$1</code>')

  // 先按 $$...$$ 分块（display），再在块内处理 $...$（inline）
  const parts = text.split(/\$\$([\s\S]*?)\$\$/g)
  let html = ''
  for (let i = 0; i < parts.length; i++) {
    if (i % 2 === 1) {
      html += renderOne(parts[i], true)
    } else {
      // 处理行内 $...$
      const segs = parts[i].split(/\$([^$]+)\$/g)
      for (let j = 0; j < segs.length; j++) {
        html += j % 2 === 1 ? renderOne(segs[j], false) : esc(segs[j]).replace(/\n/g, '<br/>')
      }
    }
  }
  return html
}

function renderOne(tex: string, display: boolean): string {
  try {
    return katex.renderToString(tex, { throwOnError: false, displayMode: display })
  } catch {
    // 降级展示原文：必须转义 HTML，否则恶意构造（如 $<img src=x onerror=...>$）
    // 会经 v-html 注入页面（内容源是 LLM 输出，间接含用户输入）
    const escHtml = (s: string) =>
      s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
    return `<code>$${escHtml(tex)}$</code>`
  }
}
