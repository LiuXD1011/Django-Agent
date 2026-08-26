import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const read = (path) => readFileSync(resolve(import.meta.dirname, path), 'utf8')
const settings = read('./Settings.vue')
const platform = read('./Platform.vue')
const router = read('../router/index.ts')

assert.equal(
  (settings.match(/router\.push\(['"]\/platform\/evaluation['"]\)/g) || []).length,
  1,
  'Settings should expose exactly one command to the evaluation workbench',
)

for (const legacySymbol of [
  'ragEvalLoading',
  'ragEvalResult',
  'ragEvalHistory',
  'runRagEval',
  'loadRagEvalHistory',
  'showEvalQuestionDialog',
  'evalQuestions',
  'loadEvalQuestions',
  'addEvalQuestion',
  'removeEvalQuestion',
  'generateEvalQuestions',
  'eval-question-manager',
]) {
  assert.doesNotMatch(settings, new RegExp(legacySymbol), `Settings should remove legacy evaluator symbol: ${legacySymbol}`)
}

assert.doesNotMatch(settings, /记忆与 RAG 评估|记忆开关、RAG 评估/, 'Settings captions should not describe a second evaluator')

for (const view of ['KnowledgeBases', 'KnowledgeDetail', 'Wiki', 'Chat', 'Settings', 'Evaluation']) {
  assert.match(
    router,
    new RegExp(`const ${view} = \\(\\) => import\\(['"]\\.\\.\\/views\\/${view}\\.vue['"]\\)`),
    `${view} should be loaded lazily`,
  )
  assert.doesNotMatch(
    router,
    new RegExp(`import ${view} from ['"]\\.\\.\\/views\\/${view}\\.vue['"]`),
    `${view} should not remain an eager import`,
  )
}

const recentLoader = platform.slice(
  platform.indexOf('async function loadRecentItems'),
  platform.indexOf('function goAccount'),
)
assert.match(
  recentLoader,
  /if \(route\.path\.startsWith\(['"]\/platform\/evaluation['"]\)\) \{[\s\S]*?recentItems\.value = \[\][\s\S]*?return/,
  'evaluation route should skip loading recent knowledge bases',
)

console.log('evaluation shell cleanup contract assertions passed')
