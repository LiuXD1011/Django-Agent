export function safeParseStorage(raw, key, storage = globalThis.localStorage) {
  if (!raw) return null
  try {
    return JSON.parse(raw)
  } catch {
    storage.removeItem(key)
    return null
  }
}
