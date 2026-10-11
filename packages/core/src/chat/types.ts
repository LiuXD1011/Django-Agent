import type { AuthContext, ChatMessage, Json, JsonObject, ModelCallOptions } from '../contracts.js';
import type { ModelCompletion } from '../models/runtime.js';
import type { JobContext } from '../jobs/queue.js';
import type { SearchHit, SearchOptions, SearchResult, SearchScope } from '../retrieval/types.js';
import type { ModelCaller } from './calls.js';
import type { ChatObserver } from '../observability/types.js';

export interface ChatSearchHit extends Omit<SearchHit, 'retrieval_path'> {
  retrieval_path: 'document' | 'graph';
  match_type?: 'graph';
  relation_type?: 'entity' | 'direct' | 'indirect';
  graph_provenance?: JsonObject[];
  expanded_chunk_ids?: string[];
  expanded_source_refs?: JsonObject[];
}
export interface ChatSearchResult extends Omit<SearchResult, 'results'> { results: ChatSearchHit[] }
export interface ChatStart extends JsonObject { session_id: string; request_id: string; assistant_message_id: string; job_id: string; message: JsonObject; idempotent: boolean }
export interface ChatFrame { event: string; data: JsonObject }
export interface ChatOutcome { content: string; refs: Json[]; steps: Json[]; durationMs: number; stoppedReason?: string }
export interface ChatForkInput { actorRowId: string; actorId: string; query: string; config?: JsonObject; timeoutMs?: number; sourceMessageIds?: string[] }
export interface ChatForkHandle { jobId: string; settled: Promise<Json>; cancel(): Promise<void> }
/** Trusted core hooks receive an authenticated, fenced execution; never register these as renderer RPCs. */
export interface ChatExecution {
  context: AuthContext; sessionId: string; messageId: string; requestId: string; query: string;
  input: JsonObject; config: JsonObject; history: ChatMessage[]; scope: SearchScope;
  job: JobContext; signal: AbortSignal; calls: ModelCaller;
  assert(): void;
  publish<T>(work: () => T): T;
  emit(type: string, data: JsonObject): void;
  journal(type: string, data: JsonObject): void;
  search(query: string, options?: SearchOptions): Promise<ChatSearchResult>;
  /** Core-only callback: a manual job with its own claim and lifetime, never renderer input. */
  fork?(input: ChatForkInput, work: (execution: ChatExecution) => Promise<Json>): ChatForkHandle;
}
export interface ChatHooks {
  observability?: ChatObserver;
  agent?: (execution: ChatExecution) => Promise<ChatOutcome>;
  memory?: (execution: ChatExecution) => Promise<{ context: string; warnings?: Json[] }>;
  maintenance?: (execution: ChatExecution, result: ChatOutcome) => Promise<void>;
  deleteMemory?: (context: AuthContext, sessionId: string) => Promise<{ warnings?: Json[] } | void>;
  attachments?: (execution: ChatExecution, attachments: Json[]) => Promise<{ text: string; attachments?: Json[]; warnings?: Json[] }>;
  images?: (execution: ChatExecution, images: Json[]) => Promise<{ images: Json[]; warnings?: Json[] }>;
  branchUploads?: (context: AuthContext, sourceSessionId: string, targetSessionId: string) => void;
  cleanupUploads?: (context: AuthContext, sessionId: string) => Promise<{ warnings?: Json[] }>;
  /** Graph results supply identifiers, never authoritative citation text or permissions. */
  graphRetrieval?: (execution: ChatExecution, query: string, options: { limit: number; seenChunkIds: string[] }) => Promise<JsonObject>;
  retrievalOptions?: (context: AuthContext, scope: SearchScope) => SearchOptions;
}
export type CompletionCall = (messages: ChatMessage[], options?: ModelCallOptions) => Promise<ModelCompletion>;
