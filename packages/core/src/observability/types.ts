import type { AuthContext, Json, JsonObject, ModelUsage } from '../contracts.js';
import type { ChatExecution } from '../chat/types.js';

export interface ModelObservation {
  invocationId: string; scenario: string; startedAt: number; endedAt: number; success: boolean;
  usage: ModelUsage; metadata: JsonObject;
}
export interface ObservationContext {
  context: AuthContext;
  model(event: ModelObservation): void;
  journal(type: string, data: JsonObject): void;
}
/** Trusted core observer. Renderer input cannot supply observers or trace destinations. */
export interface ChatObserver {
  run<T>(execution: ChatExecution, work: () => Promise<T>, kind?: 'chat.turn' | 'agent.run' | 'chat.maintenance'): Promise<T>;
  projectTrajectory(context: AuthContext, sessionId: string, trajectory: JsonObject): JsonObject;
}
export type TracePreview = Json;
