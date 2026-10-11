import { AsyncLocalStorage } from 'node:async_hooks';
import type { AuthContext } from '../contracts.js';
import type { ObservationContext } from './types.js';

const observations = new AsyncLocalStorage<ObservationContext>();
export function withObservation<T>(context: ObservationContext, work: () => Promise<T>): Promise<T> { return observations.run(context, work); }
export function currentObservation(context?: AuthContext): ObservationContext | undefined {
  const current = observations.getStore();
  return current && (!context || current.context.userId === context.userId && current.context.tenantId === context.tenantId && current.context.deviceId === context.deviceId) ? current : undefined;
}
