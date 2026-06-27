import { defineStore } from 'pinia'

/**
 * 聊天状态 store，用于跨路由传递首条消息。
 * 参考 WeKnora 的 menu store 中的 firstQuery 模式。
 */
export const useChatStore = defineStore('chat', {
  state: () => ({
    firstQuery: '' as string,
    firstPayload: null as any,
  }),
  actions: {
    setFirstQuery(query: string, payload: any) {
      this.firstQuery = query
      this.firstPayload = payload
    },
    clearFirstQuery() {
      this.firstQuery = ''
      this.firstPayload = null
    },
  },
})
