// 浏览器能力是可选增强，认证和业务请求仍走同源核心 API。
export async function registerStaticWorker({ navigator, location, onWaiting, onError = () => {} }) {
  if (!('serviceWorker' in navigator) || !['https:', 'http:'].includes(location.protocol)) return null
  try {
    const registration = await navigator.serviceWorker.register('/sw.js', { scope: '/', updateViaCache: 'none' })
    const notify = () => { if (registration.waiting) onWaiting(registration) }
    notify()
    registration.addEventListener('updatefound', () => {
      const worker = registration.installing
      worker?.addEventListener('statechange', () => {
        if (worker.state === 'installed' && navigator.serviceWorker.controller) notify()
      })
    })
    // 不 skipWaiting、不自动 reload；现有输入和在途上传不因下载新壳而丢失。
    return registration
  } catch (error) {
    onError(error)
    return null
  }
}

export function installMobileViewport(target = window) {
  const root = target.document.documentElement
  const viewport = target.visualViewport
  const update = () => {
    // 缩放不是软键盘，避免 pinch zoom 改变整个应用布局。
    const height = viewport && viewport.scale === 1 ? viewport.height : target.innerHeight
    root.style.setProperty('--app-viewport-height', `${height}px`)
    const active = target.document.activeElement
    const editing = active?.matches('input:not([type="checkbox"]):not([type="radio"]), textarea, [contenteditable="true"]')
    root.classList.toggle('mobile-keyboard-open', !!editing && target.innerHeight - height > 120)
  }
  viewport?.addEventListener('resize', update)
  target.addEventListener('resize', update)
  target.document.addEventListener('focusin', update)
  target.document.addEventListener('focusout', update)
  update()
  return () => {
    viewport?.removeEventListener('resize', update)
    target.removeEventListener('resize', update)
    target.document.removeEventListener('focusin', update)
    target.document.removeEventListener('focusout', update)
  }
}
