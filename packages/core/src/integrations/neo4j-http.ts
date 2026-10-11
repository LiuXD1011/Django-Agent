import type { JsonObject } from '../contracts.js';
import { type CallScope, endpoint, fail, responseJSON, restrictedFetch } from './network.js';
import { externalProjection } from './projection.js';

/** Explicit low-level Query API adapter. The normal saved Neo4j configuration uses Bolt. */
export async function queryNeo4jHttp(scope: CallScope, configuration: JsonObject, statement: string, parameters: JsonObject, database = 'neo4j'): Promise<JsonObject> {
  if (!/^[a-zA-Z0-9_.-]{1,63}$/.test(database) || typeof statement !== 'string' || !statement.trim() || statement.length > 16384 || !parameters || typeof parameters !== 'object' || Array.isArray(parameters)) return fail(400, 'integration_invalid_query', 'Invalid graph query');
  const base = endpoint(configuration.url), url = new URL(base.toString().replace(/\/$/, '') + `/db/${encodeURIComponent(database)}/query/v2`);
  const response = await restrictedFetch(scope, base.origin)(url, { method: 'POST', headers: { authorization: `Basic ${Buffer.from(`${configuration.username}:${configuration.password}`).toString('base64')}`, accept: 'application/json', 'content-type': 'application/json' }, body: JSON.stringify({ statement, parameters }) });
  const result = await responseJSON(response) as any;
  if (Array.isArray(result?.errors) && result.errors.length) return fail(502, 'integration_query_failed', 'Neo4j rejected the query');
  if (!Array.isArray(result?.data?.fields) || !result.data.fields.every((field: unknown) => typeof field === 'string') || !Array.isArray(result?.data?.values) || result.data.values.some((row: unknown) => !Array.isArray(row) || row.length !== result.data.fields.length)) return fail(502, 'integration_invalid_response', 'Invalid Neo4j Query API response');
  if (result.data.values.length > 1000) return fail(502, 'integration_response_too_large', 'Graph query exceeded the result limit');
  const records = result.data.values.map((row: unknown[]) => Object.fromEntries(row.map((value, index) => [result.data.fields[index], value])));
  return externalProjection({ state: 'connected', transport: 'query_api_http', records }, configuration);
}
