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

export function findToolCallMessage(messages, event, currentAssistantId) {
  const targetId = hasValue(event.assistant_message_id)
    ? event.assistant_message_id
    : currentAssistantId
  return messages.find((message) => message.id === targetId)
}
