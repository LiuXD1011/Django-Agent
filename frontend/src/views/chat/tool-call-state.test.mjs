import assert from 'node:assert/strict'
import { appendToolCall, applyToolResult, findToolCallMessage } from './tool-call-state.mjs'

{
  const calls = []
  appendToolCall(calls, { tool_call_id: 'a', name: 'database_query', arguments: { query: 'first' }, iteration: 1 })
  appendToolCall(calls, { tool_call_id: 'b', name: 'database_query', arguments: { query: 'second' }, iteration: 2 })

  const applied = applyToolResult(calls, {
    tool_call_id: 'b',
    name: 'database_query',
    output: 'query failed',
    error: 'failed',
    duration_ms: 42,
  })

  assert.equal(applied, true)
  assert.equal(calls[0].status, 'running')
  assert.equal(calls[1].status, 'failed')
  assert.equal(calls[1].error, 'failed')
  assert.equal(calls[1].output, 'query failed')
  assert.equal(calls[1].duration_ms, 42)
}

{
  const calls = []
  appendToolCall(calls, { tool_call_id: 'a', name: 'database_query' })
  appendToolCall(calls, { tool_call_id: 'b', name: 'database_query' })

  const applied = applyToolResult(calls, { name: 'database_query', output: 'legacy result' })

  assert.equal(applied, true)
  assert.equal(calls[0].status, 'done')
  assert.equal(calls[0].output, 'legacy result')
  assert.equal(calls[1].status, 'running')
}

{
  const calls = []
  appendToolCall(calls, { tool_call_id: 'duplicate', name: 'database_query', arguments: { query: 'first' }, iteration: 1 })
  appendToolCall(calls, { tool_call_id: 'duplicate', name: 'database_query', arguments: { query: 'updated' }, iteration: 2 })

  assert.equal(calls.length, 1)
  assert.deepEqual(calls[0].arguments, { query: 'updated' })
  assert.equal(calls[0].iteration, 2)
  assert.equal(calls[0].status, 'running')

  applyToolResult(calls, { tool_call_id: 'duplicate', name: 'database_query', output: 'complete' })
  appendToolCall(calls, { tool_call_id: 'duplicate', name: 'database_query', arguments: { query: 'replayed' }, iteration: 3 })

  assert.equal(calls.length, 1)
  assert.equal(calls[0].status, 'done')
  assert.deepEqual(calls[0].arguments, { query: 'replayed' })
}

{
  const calls = []
  appendToolCall(calls, { tool_call_id: 'known', name: 'database_query' })
  const before = structuredClone(calls)

  const applied = applyToolResult(calls, { tool_call_id: 'unknown', name: 'database_query', output: 'wrong result' })

  assert.equal(applied, false)
  assert.deepEqual(calls, before)
}

{
  const messages = [
    { id: 'current', agent_tool_calls: [] },
    { id: 'other', agent_tool_calls: [] },
  ]
  const before = structuredClone(messages)

  const target = findToolCallMessage(messages, { assistant_message_id: 'missing' }, 'current')
  if (target) appendToolCall(target.agent_tool_calls, { tool_call_id: 'unexpected', name: 'database_query' })

  assert.equal(target, undefined)
  assert.deepEqual(messages, before)
}

console.log('tool-call-state tests passed')
