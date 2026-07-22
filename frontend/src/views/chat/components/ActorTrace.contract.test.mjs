import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import assert from 'node:assert/strict'

const __dirname = dirname(fileURLToPath(import.meta.url))
const assistantMessage = readFileSync(resolve(__dirname, './AssistantMessage.vue'), 'utf8')
const actorTrace = readFileSync(resolve(__dirname, './ActorTrace.vue'), 'utf8')
const chatView = readFileSync(resolve(__dirname, '../../Chat.vue'), 'utf8')
const appCss = readFileSync(resolve(__dirname, '../../../styles/app.css'), 'utf8')

assert.match(
  assistantMessage,
  /import\s+ActorTrace\s+from\s+['"]\.\/ActorTrace\.vue['"]/,
  'AssistantMessage should import ActorTrace'
)
assert.match(
  assistantMessage,
  /<ActorTrace\s+:actors="actorTraces"\s*\/>/,
  'AssistantMessage should render ActorTrace for actor traces'
)
assert.doesNotMatch(
  assistantMessage,
  /v-for="actor in actorTraces"/,
  'AssistantMessage should not retain the inline actor trace loop'
)

assert.match(actorTrace, /aria-expanded/, 'ActorTrace toggles should expose expanded state')
assert.match(
  actorTrace,
  /import\s+\{\s*renderMarkdownLite\s*\}\s+from\s+['"]\.\.\/\.\.\/\.\.\/utils\/markdown-lite\.mjs['"]/,
  'ActorTrace should use the shared Markdown renderer'
)
for (const icon of ['ChevronRightIcon', 'ChevronDownIcon', 'CheckCircleIcon', 'ErrorCircleIcon', 'LoadingIcon', 'TimeIcon']) {
  assert.match(actorTrace, new RegExp(`\\b${icon}\\b`), `ActorTrace should use ${icon}`)
}
assert.match(actorTrace, /expandedById\s*=\s*ref/, 'ActorTrace should retain expansion state per actor')
assert.match(actorTrace, /manuallyTouchedActorIds\s*=\s*new Set/, 'manual Actor choices should persist')
assert.match(actorTrace, /['"]pending['"]/, 'pending actors should default expanded')
assert.match(actorTrace, /['"]running['"]/, 'running actors should default expanded')
assert.match(actorTrace, /['"]success['"]/, 'terminal actors should default collapsed')
assert.match(actorTrace, /renderMarkdownLite\(actor\.output/, 'Actor output should render safe Markdown')
assert.match(actorTrace, /\{\{\s*actor\.error\s*\}\}/, 'Actor errors should render as text only')
assert.match(actorTrace, /function\s+effectiveStatus\(/, 'ActorTrace should derive visual status from terminal outcomes')
assert.match(actorTrace, /status\s*===\s*['"]idle['"]\s*&&\s*lastOutcome\s*===\s*['"]success['"]\)\s*return\s*['"]success['"]/, 'idle success should resolve to a successful visual status')
assert.match(actorTrace, /status\s*===\s*['"]idle['"]\s*&&\s*lastOutcome\s*===\s*['"]failure['"]\)\s*return\s*['"]failed['"]/, 'idle failure should resolve to a failed visual status')
assert.match(actorTrace, /function\s+statusIcon\(actor:\s*any\)\s*\{[\s\S]*?effectiveStatus\(actor\)/, 'icon selection should use effective status')
assert.match(actorTrace, /successfulStatuses\.has\(status\)\)\s*return\s*CheckCircleIcon/, 'successful effective status should use CheckCircleIcon')
assert.match(actorTrace, /return\s+ErrorCircleIcon/, 'failed effective status should use ErrorCircleIcon')
assert.match(actorTrace, /:class="effectiveStatus\(actor\)"/, 'Actor item styling should use effective status')
assert.match(actorTrace, /<div\s+v-show="isExpanded\(actor, index\)"\s+:id=/, 'collapsed details should remain mounted for aria-controls')
assert.doesNotMatch(actorTrace, /<div\s+v-if="isExpanded\(actor, index\)"\s+:id=/, 'details should not be removed when collapsed')
assert.match(appCss, /\.actor-item\.failed\s+\.actor-status-icon/, 'failed terminal outcomes should receive failed styling')
assert.match(chatView, /metadata:\s*data\.metadata\s*\|\|\s*trace\.metadata\s*\|\|\s*\{\}/, 'live actor events should retain metadata including duration_ms')
assert.match(
  chatView,
  /if\s*\(\s*!Array\.isArray\(trace\.events\)\s*\)\s*trace\.events\s*=\s*\[\]/,
  'persisted actor traces without events should be initialized before appending live events'
)
assert.match(
  chatView,
  /trace\.events\.push\(\{\s*type:\s*data\.response_type/,
  'all actor events, including tool events, should remain in the event history'
)
assert.doesNotMatch(
  chatView,
  /Object\.assign\(trace,\s*\{[\s\S]*?output:\s*data\.output\s*\?\?[\s\S]*?error:\s*data\.error\s*\?\?\s*trace\.error[\s\S]*?\}\)/,
  'non-terminal tool events must not overwrite Actor-level output or error'
)
assert.match(
  chatView,
  /data\.response_type\s*===\s*['"]actor_completed['"][\s\S]*?trace\.output\s*=\s*data\.output\s*\?\?\s*trace\.output[\s\S]*?trace\.error\s*=\s*['"]/,
  'actor completion should update Actor output and clear stale Actor errors'
)
assert.match(
  chatView,
  /data\.response_type\s*===\s*['"]actor_failed['"][\s\S]*?trace\.error\s*=\s*data\.error\s*\?\?\s*trace\.error/,
  'actor failure should update the Actor-level error'
)
