import { expect, test } from '@playwright/test'

function response(route: any, data: any) {
  return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data }) })
}

test('reviews an evaluation set and renders only returned metrics', async ({ page }) => {
  const requests: Array<{ path: string; body: any }> = []
  await page.addInitScript(() => {
    localStorage.setItem('personal_kb_token', 'playwright-token')
    localStorage.setItem('personal_kb_selected_tenant_id', 'tenant-1')
    localStorage.setItem('personal_kb_user', JSON.stringify({ username: 'researcher' }))
  })
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (request.method() === 'POST') requests.push({ path, body: request.postDataJSON() })
    if (path === '/api/v1/rag-eval/questions') return response(route, { questions: [
      { id: 'q-1', question: '什么是检索增强生成？', ground_truth: '结合检索上下文生成答案', question_type: 'simple' },
      { id: 'q-2', question: '如何验证检索结果？', ground_truth: '使用可追溯证据集', question_type: 'reasoning' },
    ] })
    if (path === '/api/v1/knowledge-bases') return response(route, { items: [{ id: 'kb-1', name: '产品资料库' }] })
    if (path === '/api/v1/models') return response(route, { items: [{ id: 'judge-1', name: 'judge-model', display_name: 'Judge Model', role: 'chat' }] })
    if (path === '/api/v1/rag-eval/history') return response(route, { history: [{ run_id: 'report-1', evaluation_type: 'rag', evaluator: 'ragas', verified: true, dataset: { entries: 2 }, provenance: { created_at: '2026-08-19T08:00:00Z' } }] })
    if (path === '/api/v1/rag-eval/run') return response(route, { verified: true, faithfulness: 0.91, answer_relevancy: 0.82, context_precision: 0.76, run_id: 'rag-run' })
    if (path === '/api/v1/rag-eval/retrieval') return response(route, { verified: true, hit_at_10_new: 0.8, mrr_new: 0.7, recall_new: 0.9, run_id: 'retrieval-run' })
    if (path === '/api/v1/rag-eval/chunking') return response(route, { verified: true, strategies: { auto_parent_child: { questions: 2, mrr_at_10: 0.7, recall_at_20: 0.9, context_precision: 0.76 } }, run_id: 'chunking-run' })
    return response(route, {})
  })

  await page.goto('/platform/evaluation')
  await expect(page.locator('.evaluation-header h2')).toHaveText('评测工作台')
  await expect(page.getByLabel('审核列表')).toContainText('什么是检索增强生成？')
  await page.getByLabel('自动审核').check()
  await expect(page.getByLabel('审核列表')).toHaveCount(0)
  await page.getByLabel('抽样审核').check()
  await expect(page.getByLabel('审核列表')).toBeVisible()

  await page.getByRole('button', { name: '发布评估集' }).click()
  await page.getByRole('button', { name: '运行评测' }).click()
  await expect(page.getByText('91.0%', { exact: true })).toBeVisible()
  await expect(page.getByText('verified', { exact: true }).first()).toBeVisible()
  await expect(page.getByRole('button', { name: '下载报告' })).toBeVisible()
  expect(requests.find((item) => item.path === '/api/v1/rag-eval/run')?.body.questions).toEqual([
    { question: '什么是检索增强生成？', ground_truth: '结合检索上下文生成答案' },
    { question: '如何验证检索结果？', ground_truth: '使用可追溯证据集' },
  ])
})
