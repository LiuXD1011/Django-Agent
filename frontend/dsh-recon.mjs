import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'

const BASE = 'http://127.0.0.1:3099/?token=MPNwGdknGR5QVKc0RwD2pbWCJdQo6zEme0YTABCpVts'
const OUT = '/tmp/dsh-analysis'
mkdirSync(OUT, { recursive: true })

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1720, height: 1000 } })
await page.goto(BASE)
await page.waitForLoadState('domcontentloaded')
await page.waitForTimeout(2500)
await page.getByRole('treeitem', { name: /这是什么项目/ }).click()
await page.waitForTimeout(2500)
await page.getByRole('tab', { name: 'Trajectory' }).click()
await page.waitForTimeout(1500)

// 1) 时间轴 hover tooltip
const timeline = page.getByRole('region', { name: 'Trajectory timeline' })
await timeline.hover({ position: { x: 700, y: 20 } })
await page.waitForTimeout(800)
await page.screenshot({ path: `${OUT}/12-timeline-hover.png` })

// 2) Session log
await page.getByRole('button', { name: 'Session log' }).click()
await page.waitForTimeout(2000)
await page.screenshot({ path: `${OUT}/13-session-log.png` })
const snap = await page.locator('body').ariaSnapshot()
console.log('=== SESSION LOG VIEW ===')
console.log(snap.slice(0, 3500))
await browser.close()
