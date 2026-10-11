/** Original ENTITY labels are derived exclusively from verified SQLite identities. */
export function legacyLabels(knowledgeBaseId: string, knowledgeId: string): string[] {
  return [knowledgeBaseId, knowledgeId].map(id => `ENTITY${id.replace(/[^A-Za-z0-9_]/g, '_')}`);
}
export function legacyReadTemplate(labels: readonly string[], phase: 'node' | 'relation'): string {
  if (labels.length !== 2 || labels.some(label => !/^ENTITY[A-Za-z0-9_]+$/.test(label))) throw new Error('Invalid verified legacy labels');
  const expression = labels.map(label => `:${label}`).join('');
  return phase === 'node' ? `// MARLIN_LEGACY_READ_NODES
MATCH (n${expression}) WHERE n.kg=$knowledge_id AND elementId(n)>$cursor
RETURN {kind:'node',key:elementId(n),labels:labels(n),properties:properties(n)} AS record
ORDER BY elementId(n) LIMIT $limit` : `// MARLIN_LEGACY_READ_RELATIONS
MATCH (s${expression})-[r]->(t${expression})
WHERE s.kg=$knowledge_id AND t.kg=$knowledge_id AND elementId(r)>$cursor
RETURN {kind:'relation',key:elementId(r),source:elementId(s),target:elementId(t),relation_type:type(r),properties:properties(r)} AS record
ORDER BY elementId(r) LIMIT $limit`;
}
