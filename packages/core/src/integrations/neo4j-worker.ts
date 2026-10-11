import { parentPort, workerData } from 'node:worker_threads';
import neo4j from 'neo4j-driver';
import type { JsonObject } from '../contracts.js';

interface Request { uri: string; username: string; password: string; timeoutMs: number; statement?: string; parameters?: JsonObject; database?: string; write?: boolean }
const request = workerData as Request;
async function run(): Promise<JsonObject> {
  const driver = neo4j.driver(request.uri, neo4j.auth.basic(request.username, request.password), {
    connectionTimeout: request.timeoutMs, connectionAcquisitionTimeout: request.timeoutMs,
    maxTransactionRetryTime: 0, disableAutoCommitRetries: true, telemetryDisabled: true,
    logging: { level: 'error', logger: () => {} },
  });
  try {
    if (!request.statement) { await driver.verifyConnectivity(); return { state: 'connected', transport: 'bolt' }; }
    const session = driver.session({ defaultAccessMode: request.write ? neo4j.session.WRITE : neo4j.session.READ, database: request.database || 'neo4j', fetchSize: 100, disableAutoCommitRetries: true });
    try {
      const rows: JsonObject[] = []; let size = 0;
      for await (const record of session.run(request.statement, request.parameters, { timeout: request.timeoutMs })) {
        const row = JSON.parse(JSON.stringify(record.toObject(), (_name, value) => neo4j.isInt(value) ? value.inSafeRange() ? value.toNumber() : value.toString() : value)) as JsonObject;
        size += Buffer.byteLength(JSON.stringify(row));
        if (rows.length >= 1000 || size > 1024 * 1024) return { error: 'integration_response_too_large' };
        rows.push(row);
      }
      return { state: 'connected', records: rows };
    } finally { await session.close(); }
  } finally { await driver.close(); }
}
try { parentPort!.postMessage(await run()); }
catch { parentPort!.postMessage({ error: 'integration_connection_failed' }); }
finally { parentPort!.close(); }
