import type { CoreFrame, PrivateBinding, PrivateDispatch } from '../application.js';
import type { CoreRequest, CoreResponse, JsonObject } from '../contracts.js';
import type { IpcOptions, IpcResponse, NativeLangfuseResponse } from '../adapters/ipc.js';
import type { DocumentParserOptions } from '../documents/parser.js';
import type { EvaluationOptions } from '../evaluation/index.js';
import type { AuthIssue } from '../auth/index.js';
import type { DocumentAttemptIdentity, DocumentQueuedIdentity } from '../jobs/attempt-control.js';

export interface CoreOwnerConfig {
  dataRoot: string;
  allowAutoSetup?: boolean;
  parser?: DocumentParserOptions;
  evaluation?: Omit<EvaluationOptions, 'answer'>;
}
/** Private Node bootstrap; none of these fields is a renderer configuration. */
export interface OwnerWorkerData { config: CoreOwnerConfig; authority: SharedArrayBuffer; generation: string }
export interface OwnerBootstrap {
  databasePath: string;
  dataRoot: string;
  generation: string;
  parserEnabled: boolean;
  startupActive: JsonObject;
  environmentOverrides: string[];
  session: OwnerSessionState;
}
export interface OwnerSessionState { epoch: string; access?: string }
export interface CoreHttpTransport {
  readonly serviceId: string;
  readonly isAlive: boolean;
  readonly csrfKey: string;
  dispatch(request: CoreRequest, binding: PrivateBinding, signal?: AbortSignal): Promise<PrivateDispatch>;
  preflightUpload(binding: PrivateBinding, kind: 'document' | 'chat', resourceId: string, signal?: AbortSignal): Promise<void>;
}
export type OwnerCall =
  | { operation: 'dispatch'; request: CoreRequest; binding: PrivateBinding }
  | { operation: 'invoke' | 'stream'; input: unknown; options: IpcOptions }
  | { operation: 'langfuse'; input: unknown }
  | { operation: 'http' }
  | { operation: 'discard-issue'; issue: AuthIssue }
  | { operation: 'settle-ipc'; commit: string; accept: boolean }
  | { operation: 'upload-preflight'; binding: PrivateBinding; kind: 'document' | 'chat'; resourceId: string }
  | { operation: 'log'; level: string; event: string };
export type OwnerInput =
  | { protocol: 1; type: 'attempt-registration-result'; id: string; generation: string; error?: OwnerFailure }
  | { protocol: 1; type: 'cancel-attempt'; id: string; requestId: string; identity: DocumentAttemptIdentity | DocumentQueuedIdentity }
  | { protocol: 1; type: 'call'; id: string; call: OwnerCall; epoch: string }
  | { protocol: 1; type: 'abort'; id: string }
  | { protocol: 1; type: 'ack'; id: string; sequence: number }
  | { protocol: 1; type: 'close' };
export type OwnerValue = Omit<PrivateDispatch, 'stream'> | IpcResponse | NativeLangfuseResponse | { response: CoreResponse } | { csrfKey: string } | null;
export interface OwnerFailure { status: number; code: string; message: string }
export type OwnerOutput =
  | { protocol: 1; type: 'attempt-register'; id: string; generation: string; identity: DocumentAttemptIdentity; shared: SharedArrayBuffer }
  | { protocol: 1; type: 'attempt-unregister'; generation: string; identity: DocumentAttemptIdentity }
  | { protocol: 1; type: 'cancel-response'; id: string; response: CoreResponse }
  | { protocol: 1; type: 'ready'; serviceId: string; bootstrap: OwnerBootstrap }
  | { protocol: 1; type: 'startup-error'; error: OwnerFailure }
  | { protocol: 1; type: 'response'; id: string; value: OwnerValue; streaming: boolean; session: OwnerSessionState; ipcCommit?: string }
  | { protocol: 1; type: 'error'; id: string; error: OwnerFailure; session: OwnerSessionState }
  | { protocol: 1; type: 'frame'; id: string; sequence: number; frame: CoreFrame }
  | { protocol: 1; type: 'end'; id: string }
  | { protocol: 1; type: 'closed'; error?: OwnerFailure };
