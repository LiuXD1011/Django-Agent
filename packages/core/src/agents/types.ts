import type { AuthContext, Json, JsonObject } from '../contracts.js';
import type { IntegrationService } from '../integrations/index.js';
export interface ToolResult { output: string; data?: Json; error?: string; duration_ms?: number; references?: Json[]; error_type?: string; retryable?: boolean; failed_fields?: string[]; }
export interface AgentHooks {
  integrations?: Pick<IntegrationService, 'listMcpTools' | 'callMcpTool' | 'search'>;
  graph?: (context: AuthContext, knowledgeBaseIds: string[], query: string, options: { signal: AbortSignal }) => Promise<ToolResult>;
  webFetch?: (context: AuthContext, url: string, options: { signal: AbortSignal; maxChars: number }) => Promise<ToolResult>;
  readSkill?: (context: AuthContext, name: string) => Promise<ToolResult>;
}
export interface ToolDefinition { name: string; description: string; parameters: JsonObject }
export const validation = (message: string, fields: string[] = []): ToolResult => ({ output: '', error: message, error_type: 'INVALID_ARGUMENT', retryable: false, failed_fields: fields });
export const unavailable = (message: string): ToolResult => ({ output: '', error: message, error_type: 'NOT_CONFIGURED', retryable: false });
