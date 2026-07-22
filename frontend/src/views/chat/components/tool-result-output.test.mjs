import assert from 'node:assert/strict'
import { shouldRenderToolOutput } from './tool-result-output.mjs'

assert.equal(shouldRenderToolOutput('  request failed\n', 'request   failed'), false)
assert.equal(shouldRenderToolOutput(' ERROR: Request Failed ', 'request failed'), false)
assert.equal(shouldRenderToolOutput('query diagnostics', 'request failed'), true)
assert.equal(shouldRenderToolOutput('Error: a different failure', 'request failed'), true)

console.log('tool-result-output tests passed')
