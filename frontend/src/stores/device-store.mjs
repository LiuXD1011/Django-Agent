const PREFIX = 'personal_kb_device:'

/** Only explicitly saved drafts and cursors belong here, never authentication or model credentials. */
export class DeviceStore {
  constructor(storage = globalThis.localStorage) {
    this.storage = storage
    this.identity = null
  }

  bind(serviceId, userId, spaceId) {
    if (![serviceId, userId, spaceId].every((value) => value !== null && value !== undefined && String(value))) {
      throw new Error('设备缓存需要完整的服务、账号和空间标识')
    }
    this.identity = [String(serviceId), String(userId), String(spaceId)]
  }

  key(kind, resource) {
    if (!this.identity) throw new Error('设备缓存尚未绑定账号')
    if (!['draft', 'cursor'].includes(kind)) throw new Error('不支持的设备缓存类型')
    return PREFIX + JSON.stringify([...this.identity, kind, String(resource)])
  }

  read(kind, resource) {
    const key = this.key(kind, resource)
    try { return JSON.parse(this.storage.getItem(key) || 'null') }
    catch { this.storage.removeItem(key); return null }
  }

  write(kind, resource, value) {
    this.storage.setItem(this.key(kind, resource), JSON.stringify(value))
  }

  remove(kind, resource) { this.storage.removeItem(this.key(kind, resource)) }

  clearCurrent() {
    if (!this.identity) return
    const prefix = PREFIX + JSON.stringify(this.identity).slice(0, -1) + ','
    const keys = []
    for (let index = 0; index < this.storage.length; index += 1) {
      const key = this.storage.key(index)
      if (key?.startsWith(prefix)) keys.push(key)
    }
    keys.forEach((key) => this.storage.removeItem(key))
  }

  unbind({ clear = false } = {}) {
    if (clear) this.clearCurrent()
    this.identity = null
  }
}

export const deviceStore = new DeviceStore()
