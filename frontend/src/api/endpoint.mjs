/** Browser/PWA endpoints remain same-origin. Native service switching is a separate adapter. */
export class EndpointResolver {
  constructor(origin) {
    this.origin = new URL(origin).origin
    this.service = null
  }

  resolve(path) {
    const url = new URL(path, this.origin)
    if (url.origin !== this.origin || url.username || url.password || url.hash
      || !url.pathname.startsWith('/api/v1/')) throw new Error('API 地址必须与当前站点同源')
    return url.href
  }

  bind(capabilities) {
    if (!capabilities || typeof capabilities.service_id !== 'string' || !capabilities.service_id.trim()
      || capabilities.client_protocol !== 1 || !Array.isArray(capabilities.auth_modes) || !capabilities.auth_modes.includes('cookie')) {
      throw new Error('服务未提供受支持的客户端能力')
    }
    this.service = { ...capabilities }
    return this.service
  }
}

export const endpoint = new EndpointResolver(globalThis.location?.origin || 'http://localhost')
