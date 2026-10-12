import type { PrivateBinding } from '../application.js';
import type { CoreRequest, CoreResponse } from '../contracts.js';
import type { OwnerBootstrap, OwnerFailure } from './owner-contracts.js';
import type { CancelTarget } from './document-cancel-preflight.js';

/** Private access credentials only; no refresh token, uploads, SQL or AuthContext. */
export type QueryBinding = Pick<PrivateBinding, 'transport' | 'access' | 'bearer' | 'apiKey' | 'selectedTenant'>;
export type QueryBootstrap = Pick<OwnerBootstrap, 'databasePath' | 'dataRoot' | 'generation' | 'parserEnabled'>;
export interface QueryWorkerData { bootstrap: QueryBootstrap; authority: SharedArrayBuffer }
export type QueryInput =
  | { protocol: 1; type: 'query'; id: string; generation: string; epoch: string; deadline: number; request: CoreRequest; binding: QueryBinding; operation?: 'cancel-preflight' }
  | { protocol: 1; type: 'close' };
export type QueryOutput =
  | { protocol: 1; type: 'ready'; generation: string }
  | { protocol: 1; type: 'result'; id: string; generation: string; epoch: string; response: CoreResponse; target?: CancelTarget }
  | { protocol: 1; type: 'startup-error'; error: OwnerFailure }
  | { protocol: 1; type: 'closed' };
