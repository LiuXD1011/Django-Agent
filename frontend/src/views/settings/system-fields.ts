export interface ConfigField {
  key: string
  label: string
  kind?: 'boolean' | 'number' | 'secret' | 'list' | 'choice'
  min?: number
  max?: number
  step?: number
  choices?: string[]
}
export const configSections: Record<string, { title: string, description: string, fields: ConfigField[] }> = {
  application: { title: '应用配置', description: '系统管理员配置，全局生效；保存后更新项目名称。', fields: [
    { key: 'name', label: '项目名称' },
  ] },
  neo4j: { title: 'Neo4j 图数据库', description: '用于知识图谱和跨会话记忆。凭据加密保存，留空保留；保存后连接按新配置重建。', fields: [
    { key: 'enabled', label: '启用 Neo4j', kind: 'boolean' },
    { key: 'uri', label: '连接地址' }, { key: 'username', label: '用户名' },
    { key: 'password', label: '连接密码', kind: 'secret' },
  ] },
  langfuse: { title: '追踪选项', description: '保存后生效；默认仅上报元数据。API 地址和密钥在上方配置。', fields: [
    { key: 'ui_base_url', label: '浏览器 UI 地址（空白跟随 API 地址）' },
    { key: 'ui_project_id', label: '项目 ID' },
    { key: 'trace_links_enabled', label: '管理员可查看追踪链接', kind: 'boolean' },
    { key: 'sample_rate', label: '采样率', kind: 'number', min: 0, max: 1, step: 0.1 },
    { key: 'log_content', label: '上传提示词与内容（经过脱敏）', kind: 'boolean' },
    { key: 'upload_eval_datasets', label: '上传评估数据集', kind: 'boolean' },
    { key: 'tracing_environment', label: '环境标签' },
    { key: 'orphan_mode', label: '无业务上下文时', kind: 'choice', choices: ['skip', 'standalone'] },
  ] },
  local_services: { title: '本地 Langfuse 服务', description: '自动启动在下次开发入口启动时生效；桌面入口不自动启动 Docker。自动登录仅用于同主机本地服务。', fields: [
    { key: 'autostart', label: '自动启动本地 Docker 服务', kind: 'boolean' },
    { key: 'startup_timeout_seconds', label: '启动超时（秒）', kind: 'number', min: 1, max: 120 },
    { key: 'auto_login', label: '开启本地自动登录', kind: 'boolean' },
    { key: 'login_email', label: 'Langfuse 登录邮箱' },
    { key: 'password', label: 'Langfuse 登录密码', kind: 'secret' },
    { key: 'local_login_user_id', label: '额外授权本地用户 ID（空白仅系统管理员）' },
  ] },
  startup: { title: '启动配置', description: '由后端写入数据目录的 .settings/startup.json，不依赖数据库启动。保存后需重启；部署环境变量优先，密钥不在此文件中。', fields: [
    { key: 'debug', label: '开发调试模式', kind: 'boolean' },
    { key: 'allowed_hosts', label: '允许的主机（逗号分隔）', kind: 'list' },
    { key: 'cors_origins', label: '允许的前端来源（逗号分隔）', kind: 'list' },
    { key: 'task_workers', label: '后台任务线程数', kind: 'number', min: 2, max: 32 },
    { key: 'sqlite_timeout', label: 'SQLite 锁等待（秒）', kind: 'number', min: 1, max: 300 },
    { key: 'model_timeout', label: '模型请求超时（秒）', kind: 'number', min: 1, max: 600 },
    { key: 'model_retries', label: '模型请求重试次数', kind: 'number', min: 0, max: 10 },
    { key: 'log_level', label: '日志级别', kind: 'choice', choices: ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] },
    { key: 'no_proxy', label: '不走代理的主机' },
    { key: 'proxy_url', label: '模型请求代理（HTTP(S)，不含凭据；留空直连）' },
  ] },
}

export function configPayload(fields: ConfigField[], form: Record<string, any>) {
  return Object.fromEntries(fields.filter(field => field.kind !== 'secret' || form[field.key]).map(field => {
    const value = form[field.key]
    return [field.key, field.kind === 'list' ? String(value ?? '').split(',').map(item => item.trim()).filter(Boolean) : value]
  }))
}
