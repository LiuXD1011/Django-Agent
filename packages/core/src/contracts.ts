export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export type JsonObject = { [key: string]: Json };
export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

export interface CoreRequest {
  protocol: 1;
  id: string;
  method: HttpMethod;
  path: string;
  body?: Json;
}

export interface CoreResponse {
  protocol: 1;
  id: string;
  status: number;
  body: Json;
}

export interface CoreEvent {
  protocol: 1;
  topic: string;
  request_id: string;
  seq: number;
  type: string;
  data: Json;
}

/** Trusted core-only delegated visitor; never an ordinary account/device credential. */
export interface ChannelPrincipal extends JsonObject {
  id: string;
  grantId: string;
  guestId: string;
  version: string;
  origin: string;
  expiresAt: number;
  knowledgeBaseIds: string[];
}

export interface AuthContext {
  userId: string;
  tenantId: string;
  role: string;
  deviceId: string;
  isSystemAdmin: boolean;
  channel?: ChannelPrincipal;
}

export interface ParseRequest {
  protocol: 1;
  id: string;
  operation: 'capabilities' | 'parse';
  input?: { path: string; name: string; sha256: string; size_bytes: number };
  artifact_dir?: string;
  options?: JsonObject;
  limits?: { max_input_bytes?: number; max_artifact_bytes?: number; max_pages?: number; max_images?: number };
}

export interface ParsedTextBlock {
  id: string;
  kind: 'text';
  block_index: number;
  block_type: string;
  text: string;
  canonical_range: { start: number; end: number };
  provenance: JsonObject;
  metadata: JsonObject;
}

export interface ParsedImageBlock {
  id: string;
  kind: 'image';
  block_index: number;
  artifact_path: string;
  sha256: string;
  original_mime_type: string;
  mime_type: string;
  width: number;
  height: number;
  provenance: JsonObject;
  metadata: JsonObject;
}

export interface ParsedDocument {
  document: {
    name: string;
    input_sha256: string;
    parser_version: string;
    canonicalization_version: 'blocks-double-newline-v1';
    offset_unit: 'unicode_code_point';
    canonical_text: string;
    canonical_sha256: string;
  };
  blocks: Array<ParsedTextBlock | ParsedImageBlock>;
  warnings: Array<{ code: string; message: string; block_index?: number }>;
  diagnostics: JsonObject;
}

export type ParserMessage =
  | { protocol: 1; id: string; type: 'progress'; stage: string; progress: number }
  | { protocol: 1; id: string; type: 'result'; operation: 'parse'; result: ParsedDocument }
  | { protocol: 1; id: string; type: 'result'; operation: 'capabilities'; result: JsonObject }
  | { protocol: 1; id: string; type: 'error'; error: { code: string; message: string; retryable: boolean } };

export interface ModelConfiguration {
  id: string;
  name: string;
  type: string;
  source: string;
  parameters: JsonObject;
  context_window?: number | null;
}

export interface ChatMessage {
  role: 'system' | 'user' | 'assistant' | 'tool';
  content: string | JsonObject[];
  tool_call_id?: string;
  tool_calls?: JsonObject[];
}

export interface ModelUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cached_tokens: number;
  reasoning_tokens: number;
}

export type ModelDelta =
  | { type: 'content'; content: string }
  | { type: 'reasoning'; content: string }
  | { type: 'tool_calls'; tool_calls: JsonObject[] }
  | { type: 'usage'; usage: ModelUsage }
  | { type: 'done'; finish_reason: string };

export interface ModelCallOptions {
  signal?: AbortSignal;
  timeoutMs?: number;
  thinking?: JsonObject;
  tools?: JsonObject[];
  temperature?: number;
  maxTokens?: number;
}
