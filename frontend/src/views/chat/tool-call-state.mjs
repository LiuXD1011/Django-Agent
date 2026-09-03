function hasValue(value) {
  return value !== undefined && value !== null && value !== ''
}

export function appendToolCall(calls, event) {
  const existing = hasValue(event.tool_call_id)
    ? calls.find((item) => item.tool_call_id === event.tool_call_id)
    : undefined

  if (existing) {
    existing.name = event.name
    existing.arguments = event.arguments
    existing.iteration = event.iteration
    return existing
  }

  const call = {
    tool_call_id: event.tool_call_id,
    name: event.name,
    arguments: event.arguments,
    iteration: event.iteration,
    status: 'running',
  }
  calls.push(call)
  return call
}

export function applyToolResult(calls, event) {
  const hasToolCallId = hasValue(event.tool_call_id)
  const call = hasToolCallId
    ? calls.find((item) => item.tool_call_id === event.tool_call_id)
    : calls.find((item) => item.name === event.name && item.status === 'running')

  if (!call) return false

  call.output = event.output
  call.error = event.error
  call.duration_ms = event.duration_ms
  call.status = event.error ? 'failed' : 'done'
  return true
}

// 用户手动停止后，把仍在 running 的工具调用收敛为 failed，避免 UI 永远转圈
export function markToolCallsStopped(calls, note = '已手动停止') {
  let changed = false
  for (const item of calls || []) {
    if (item.status === 'running') {
      item.status = 'failed'
      item.error = note
      changed = true
    }
  }
  return changed
}

// 同上，作用于子 Agent 轨迹（ActorTrace）
export function markActorTracesStopped(traces, note = '已手动停止') {
  let changed = false
  for (const trace of traces || []) {
    if (['running', 'pending'].includes(String(trace.status || '').toLowerCase())) {
      trace.status = 'failure'
      trace.last_outcome = note
      changed = true
    }
  }
  return changed
}

export function findToolCallMessage(messages, event, currentAssistantId) {
  const targetId = hasValue(event.assistant_message_id)
    ? event.assistant_message_id
    : currentAssistantId
  return messages.find((message) => message.id === targetId)
}
