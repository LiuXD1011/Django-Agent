import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const settingsVue = readFileSync(resolve(import.meta.dirname, 'Settings.vue'), 'utf8')
const removedCopy = new RegExp([
  `空间${'/'}API`,
  `空间${'与'} API`,
  `当前${'空间'}`,
].join('|'))
const removedGeneralControls = new RegExp([
  `选择浅色、深色或跟随${'系统'}`,
  `调整界面文字${'大小'}`,
  `save${'UiPref'}`,
  `apply${'Theme'}`,
  `apply${'FontSize'}`,
  `ui${'Theme'}`,
  `ui${'FontSize'}`,
].join('|'))

assert.doesNotMatch(settingsVue, /key:\s*'tenant'/, 'settings navigation should not include the removed space/api section key')
assert.doesNotMatch(settingsVue, removedCopy, 'settings page should not render the removed space/api copy')
assert.doesNotMatch(settingsVue, /activeSection\s*===\s*'tenant'/, 'settings template should not keep the removed tenant section branch')
assert.doesNotMatch(settingsVue, removedGeneralControls, 'settings page should not keep non-functional theme/font controls or handlers')
