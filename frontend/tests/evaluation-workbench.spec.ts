import { expect, test } from '@playwright/test'

function response(route: any, data: any, status = 200) {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify({ success: true, data }) })
}

async function authenticate(page: any) {
  await page.addInitScript(() => {
    localStorage.setItem('personal_kb_token', 'playwright-token')
    localStorage.setItem('personal_kb_selected_tenant_id', 'tenant-1')
    localStorage.setItem('personal_kb_user', JSON.stringify({ username: 'researcher' }))
    sessionStorage.setItem('rag-eval-open-run', JSON.stringify({ run_id: 'stale-tab-run' }))
  })
}

const publicDatasets = [
  { id: 'open_rag_benchmark_180', version: 'arxiv-v1', label: 'Open RAG Benchmark 180', count: 180, documents: 1000, ready: true, status: 'ready', progress: 1 },
  { id: 'open_rag_benchmark_full', version: 'arxiv-v1', label: 'Open RAG Benchmark Full', count: 3045, documents: 1000, ready: true, status: 'ready', progress: 1 },
]

const models = [
  { id: 'answer-1', display_name: 'Answer Chat', model_type: 'KnowledgeQA' },
  { id: 'judge-1', display_name: 'Judge Chat', roles: ['judge', 'chat'] },
  { id: 'embedding-1', display_name: 'Default Embedding', type: 'embedding', is_default: true },
  { id: 'rerank-1', display_name: 'Default Rerank', role: 'rerank', is_default: true },
  { id: 'vlm-1', display_name: 'Default VLM', model_type: 'VLLM', is_default: true },
]

test('runs the fixed public subset through the unified workbench contract', async ({ page }) => {
  const requests: Array<{ method: string; path: string; body: any }> = []
  await authenticate(page)
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    requests.push({ method: request.method(), path, body: request.postDataJSON() })
    if (path === '/api/v1/knowledge-bases') return response(route, { items: [{ id: 'kb-1', name: '产品资料库' }] })
    if (path === '/api/v1/models') return response(route, { items: models })
    if (path === '/api/v1/rag-eval/open-datasets') return response(route, { datasets: publicDatasets })
    if (path === '/api/v1/rag-eval/history') return response(route, { history: [] })
    if (path === '/api/v1/rag-eval/runs' && request.method() === 'GET') return response(route, { active_run: null })
    if (path === '/api/v1/rag-eval/runs' && request.method() === 'POST') return response(route, { run_id: 'run-public', status: 'queued', total_questions: 100 }, 202)
    if (path === '/api/v1/rag-eval/runs/run-public' && request.method() === 'GET') return response(route, {
      run_id: 'run-public', status: 'completed', stage: 'complete', progress: 1,
      completed_questions: 100, total_questions: 100, failed_count: 2, valid_coverage: 0.98,
      elapsed_seconds: 120, eta_seconds: 0, verified: true, completed_at: '2026-08-21T08:02:00Z',
      metrics: {
        rag: { verified: true, faithfulness: 0.91, answer_relevancy: 0.82, context_precision: null },
        retrieval: { verified: true, hit_at_10: 0.8, mrr_at_10: null, recall_at_20: 0.9 },
        chunking: { verified: true, strategies: { auto_parent_child: { questions: 100, mrr_at_10: 0.7, context_precision: 0.76 } } },
      },
      report_url: '/api/v1/rag-eval/reports/run-public',
    })
    if (path === '/api/v1/rag-eval/reports/run-public') return response(route, { run_id: 'run-public' })
    return response(route, {})
  })

  await page.goto('/platform/evaluation')
  await expect(page.getByLabel('数据集')).toHaveValue('public:open_rag_benchmark_180@arxiv-v1')
  await expect(page.getByLabel('数据集')).toContainText('180 题')
  await expect(page.getByLabel('数据集')).toContainText('3045 题')
  await expect(page.getByText('问题类型')).toHaveCount(0)
  await expect(page.getByLabel('审核模式')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '生成评估集' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '发布评估集' })).toHaveCount(0)

  await expect(page.getByLabel('Answer 模型')).not.toContainText('Embedding')
  await expect(page.getByLabel('Answer 模型')).not.toContainText('Rerank')
  await expect(page.getByLabel('Answer 模型')).not.toContainText('VLM')
  await expect(page.getByLabel('Judge 模型')).not.toContainText('Embedding')
  await page.getByLabel('Answer 模型').selectOption('answer-1')
  await page.getByLabel('Judge 模型').selectOption('judge-1')

  await expect(page.getByLabel('自适应父子块')).toBeChecked()
  await expect(page.getByLabel('语义父子块')).not.toBeChecked()
  await expect(page.getByLabel('启用 Rerank')).toBeChecked()

  await page.getByRole('button', { name: '运行评测' }).click()
  await expect(page.getByText('已完成题目：100 / 100')).toBeVisible()
  await expect(page.getByText('失败题目：2')).toBeVisible()
  await expect(page.getByText('有效覆盖率：98.0%')).toBeVisible()
  await expect(page.getByText('耗时：2 分 0 秒')).toBeVisible()
  await expect(page.getByText('预计剩余：0 秒')).toBeVisible()
  await expect(page.getByText('91.0%', { exact: true })).toBeVisible()
  await expect(page.locator('.metric-card').filter({ hasText: 'MRR@10' }).locator('strong')).toHaveText('--')
  await expect(page.locator('.metric-card').filter({ hasText: 'Context Precision' }).locator('strong')).toHaveText('--')

  const create = requests.find((item) => item.method === 'POST' && item.path === '/api/v1/rag-eval/runs')
  expect(create?.body).toEqual({
    source: { type: 'open_dataset', dataset_id: 'open_rag_benchmark_180', dataset_version: 'arxiv-v1' },
    retrieval_strategy: 'hybrid', rerank_enabled: true, chunking_strategies: ['auto_parent_child'],
    answer_model_id: 'answer-1', judge_model_id: 'judge-1',
  })
  expect(requests.some((item) => item.path.includes('open-runs'))).toBe(false)
  expect(requests.some((item) => item.path.includes('stale-tab-run'))).toBe(false)
})

test('keeps chunking comparison controls interactive and responsive', async ({ page }) => {
  await authenticate(page)
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/v1/knowledge-bases') return response(route, { items: [] })
    if (path === '/api/v1/models') return response(route, { items: models })
    if (path === '/api/v1/rag-eval/open-datasets') return response(route, { datasets: publicDatasets })
    if (path === '/api/v1/rag-eval/history') return response(route, { history: [] })
    if (path === '/api/v1/rag-eval/runs') return response(route, { active_run: null })
    return response(route, {})
  })

  await page.goto('/platform/evaluation')
  await page.getByLabel('comparison-recursive').check()
  await expect(page.getByLabel('comparison-recursive')).toBeChecked()
  await page.getByLabel('递归分块（父子）').check()
  await expect(page.getByLabel('递归分块（父子）')).toBeChecked()
  await expect(page.getByLabel('comparison-recursive')).toHaveCount(0)
  await expect(page.getByLabel('comparison-auto_parent_child')).not.toBeChecked()

  const dimensions = await page.locator('.evaluation-page').evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
  }))
  expect(dimensions.scrollWidth).toBe(dimensions.clientWidth)
  const selectHeight = await page.getByLabel('数据集').evaluate((element) => element.getBoundingClientRect().height)
  expect(selectHeight).toBeLessThanOrEqual(44)
})

test('restores and resumes the server-side active run with the same id', async ({ page }) => {
  const requests: Array<{ method: string; path: string }> = []
  await authenticate(page)
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    requests.push({ method: request.method(), path })
    if (path === '/api/v1/knowledge-bases') return response(route, { items: [] })
    if (path === '/api/v1/models') return response(route, { items: models })
    if (path === '/api/v1/rag-eval/open-datasets') return response(route, { datasets: publicDatasets })
    if (path === '/api/v1/rag-eval/history') return response(route, { history: [] })
    if (path === '/api/v1/rag-eval/runs' && request.method() === 'GET') return response(route, { active_run: {
      run_id: 'server-run', status: 'failed', stage: 'ragas', completed_questions: 80, total_questions: 100,
      failed_count: 3, valid_coverage: 0.77, elapsed_seconds: 600, eta_seconds: 180, error: 'judge_rate_limited',
    } })
    if (path === '/api/v1/rag-eval/runs/server-run/resume') return response(route, { run_id: 'server-run', status: 'queued' }, 202)
    if (path === '/api/v1/rag-eval/runs/server-run') return response(route, { run_id: 'server-run', status: 'queued', total_questions: 100 })
    return response(route, {})
  })

  await page.goto('/platform/evaluation')
  await expect(page.getByText('judge_rate_limited')).toBeVisible()
  await page.getByRole('button', { name: '继续评测' }).click()
  await expect.poll(() => requests.filter((item) => item.path.endsWith('/server-run/resume')).length).toBe(1)
  expect(requests.some((item) => item.method === 'POST' && item.path === '/api/v1/rag-eval/runs')).toBe(false)
})

test('submits tenant datasets to the same background endpoint', async ({ page }) => {
  const posts: Array<{ path: string; body: any }> = []
  await authenticate(page)
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (request.method() === 'POST') posts.push({ path, body: request.postDataJSON() })
    if (path === '/api/v1/knowledge-bases') return response(route, { items: [{ id: 'kb-1', name: '产品资料库' }] })
    if (path === '/api/v1/models') return response(route, { items: models })
    if (path === '/api/v1/rag-eval/open-datasets') return response(route, { datasets: publicDatasets })
    if (path === '/api/v1/rag-eval/history') return response(route, { history: [] })
    if (path === '/api/v1/rag-eval/runs' && request.method() === 'GET') return response(route, { active_run: null })
    if (path === '/api/v1/rag-eval/testsets') return response(route, { id: 'tenant-dataset-1', generated: 1, entries: [{ id: 'q-1', question: '什么是 RAG？', ground_truth: '检索增强生成', status: 'approved' }] })
    if (path === '/api/v1/rag-eval/runs' && request.method() === 'POST') return response(route, { run_id: 'tenant-run', status: 'queued', total_questions: 1 }, 202)
    if (path === '/api/v1/rag-eval/runs/tenant-run') return response(route, { run_id: 'tenant-run', status: 'completed', metrics: {}, completed_questions: 1, total_questions: 1 })
    return response(route, {})
  })

  await page.goto('/platform/evaluation')
  await page.getByLabel('数据集').selectOption('kb:kb-1')
  await expect(page.getByText('问题类型')).toBeVisible()
  await expect(page.getByLabel('审核模式')).toBeVisible()
  const dimensions = await page.locator('.evaluation-page').evaluate((element) => ({ clientWidth: element.clientWidth, scrollWidth: element.scrollWidth }))
  expect(dimensions.scrollWidth).toBe(dimensions.clientWidth)
  await page.getByRole('button', { name: '生成评估集' }).click()
  await page.getByRole('button', { name: '发布评估集' }).click()
  await page.getByRole('button', { name: '运行评测' }).click()

  expect(posts.find((item) => item.path === '/api/v1/rag-eval/runs')?.body).toMatchObject({
    source: { type: 'tenant_dataset', dataset_id: 'tenant-dataset-1', knowledge_base_id: 'kb-1' },
    retrieval_strategy: 'hybrid', rerank_enabled: true, chunking_strategies: ['auto_parent_child'],
  })
  expect(posts.some((item) => ['/api/v1/rag-eval/run', '/api/v1/rag-eval/retrieval', '/api/v1/rag-eval/chunking'].includes(item.path))).toBe(false)
})

test('estimates and confirms the exact full dataset size before starting', async ({ page }) => {
  let confirmText = ''
  const posts: Array<{ path: string; body: any }> = []
  await authenticate(page)
  page.on('dialog', async (dialog) => {
    confirmText = dialog.message()
    await dialog.accept()
  })
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (request.method() === 'POST') posts.push({ path, body: request.postDataJSON() })
    if (path === '/api/v1/knowledge-bases') return response(route, { items: [] })
    if (path === '/api/v1/models') return response(route, { items: models })
    if (path === '/api/v1/rag-eval/open-datasets') return response(route, { datasets: publicDatasets })
    if (path === '/api/v1/rag-eval/history') return response(route, { history: [] })
    if (path === '/api/v1/rag-eval/runs' && request.method() === 'GET') return response(route, { active_run: null })
    if (path === '/api/v1/rag-eval/runs/estimate') return response(route, { estimated_seconds: 18000, estimated_model_calls: 12180 })
    if (path === '/api/v1/rag-eval/runs' && request.method() === 'POST') return response(route, { run_id: 'full-run', status: 'queued', total_questions: 3045 }, 202)
    if (path === '/api/v1/rag-eval/runs/full-run') return response(route, { run_id: 'full-run', status: 'queued', total_questions: 3045 })
    return response(route, {})
  })

  await page.goto('/platform/evaluation')
  await page.getByLabel('数据集').selectOption('public:open_rag_benchmark_full@arxiv-v1')
  await page.getByRole('button', { name: '运行评测' }).click()
  await expect.poll(() => confirmText).toContain('3045')
  expect(confirmText).toContain('5 小时')
  expect(confirmText).toContain('12180')
  expect(posts.find((item) => item.path === '/api/v1/rag-eval/runs/estimate')?.body.source.dataset_id).toBe('open_rag_benchmark_full')
  expect(posts.find((item) => item.path === '/api/v1/rag-eval/runs')?.body.source.dataset_id).toBe('open_rag_benchmark_full')
})
