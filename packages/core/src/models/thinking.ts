import type { JsonObject } from '../contracts.js';

export interface ThinkingCapability {
  profile: 'unknown' | 'deepseek-v4-chat' | 'glm-5.3-required-thinking';
  modes: string[];
  efforts: string[];
  note: string;
}
export interface ThinkingPolicy { mode: 'default' | 'on' | 'off'; effort: string | null; }

/** Match the previously verified endpoint/model pairs; never guess from a model substring. */
export function capability(base: string, model: string): ThinkingCapability {
  let host = '';
  try { host = new URL(base).hostname; } catch { /* An absent endpoint has no verified profile. */ }
  if (host === 'api.deepseek.com' && ['deepseek-v4-flash', 'deepseek-v4-pro', 'deepseek-flash'].includes(model)) {
    return { profile: 'deepseek-v4-chat', modes: ['default', 'off', 'on'], efforts: ['low', 'high', 'max'],
      note: '旧版 V4 接口可能将 low 映射为 high；不会修改模型名称。' };
  }
  if (['open.bigmodel.cn', 'api.z.ai'].includes(host) && model === 'glm-5.3-flash') {
    return { profile: 'glm-5.3-required-thinking', modes: ['default', 'on'], efforts: ['low', 'high', 'max'],
      note: '该模型始终启用思考；辅助任务使用 low，不能关闭思考。' };
  }
  return { profile: 'unknown', modes: ['default'], efforts: [],
    note: '该端点与模型尚无已验证的思考参数适配，保持供应商默认。' };
}

export function normalizeThinking(value: JsonObject, cap: ThinkingCapability): ThinkingPolicy {
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).some(k => !['mode', 'effort'].includes(k))) {
    throw new Error('Thinking policy must contain only mode and effort');
  }
  const mode = value.mode === undefined ? 'default' : value.mode;
  const effort = value.effort ?? null;
  if (typeof mode !== 'string' || !cap.modes.includes(mode) || (mode !== 'on' && effort !== null)) {
    throw new Error('The model does not support the requested thinking mode');
  }
  if (effort !== null && (typeof effort !== 'string' || !cap.efforts.includes(effort))) {
    throw new Error('The model does not support the requested thinking effort');
  }
  return { mode: mode as ThinkingPolicy['mode'], effort: effort as string | null };
}

/** Legacy enable_thinking=False for short summary/Wiki tasks, without mutating Chat policy. */
export function auxiliaryThinking(base: string, model: string): JsonObject | undefined {
  const profile = capability(base, model).profile;
  if (profile === 'glm-5.3-required-thinking') return { mode: 'on', effort: 'low' };
  if (profile === 'deepseek-v4-chat') return { mode: 'off', effort: null };
  return undefined;
}

/** The same adapter is used for chat, vision, summary, memory and other auxiliary completions. */
export function thinkingWireOptions(base: string, model: string, value: JsonObject = { mode: 'default' }): JsonObject {
  const cap = capability(base, model);
  const policy = normalizeThinking(value, cap);
  if (policy.mode === 'default') {
    return cap.profile === 'glm-5.3-required-thinking' ? { thinking: { type: 'enabled' } } : {};
  }
  const body: JsonObject = { thinking: { type: policy.mode === 'on' ? 'enabled' : 'disabled' } };
  if (policy.mode === 'on' && policy.effort) body.reasoning_effort = policy.effort;
  return body;
}
