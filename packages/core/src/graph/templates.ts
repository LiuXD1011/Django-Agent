/** Trusted core templates only. Graph names, IDs, relation kinds and namespaces are always parameters. */
export const writeGeneration = `// MARLIN_WRITE_GENERATION
CALL {
  UNWIND $nodes AS node
  MERGE (n:MarlinEntity {namespace:$namespace, tenant_id:$tenant_id, knowledge_base_id:$knowledge_base_id,
    knowledge_id:$knowledge_id, generation:$generation, id:node.id})
  SET n.name=node.name, n.node_type=node.node_type, n.attributes=node.attributes, n.chunks=node.chunks
  RETURN count(*) AS nodes
}
CALL {
  UNWIND $relations AS edge
  MATCH (s:MarlinEntity {namespace:$namespace, tenant_id:$tenant_id, knowledge_base_id:$knowledge_base_id,
    knowledge_id:$knowledge_id, generation:$generation, id:edge.source})
  MATCH (t:MarlinEntity {namespace:$namespace, tenant_id:$tenant_id, knowledge_base_id:$knowledge_base_id,
    knowledge_id:$knowledge_id, generation:$generation, id:edge.target})
  MERGE (s)-[r:MARLIN_REL {namespace:$namespace, tenant_id:$tenant_id, knowledge_base_id:$knowledge_base_id,
    knowledge_id:$knowledge_id, generation:$generation, id:edge.id}]->(t)
  SET r.source=edge.source, r.target=edge.target, r.relation_type=edge.relation_type,
    r.strength=edge.strength, r.weight=edge.weight, r.combined_degree=edge.combined_degree, r.chunks=edge.chunks
  RETURN count(*) AS relations
}
RETURN nodes, relations`;
export const readGenerations = `// MARLIN_READ_GENERATIONS
CALL {
  MATCH (n:MarlinEntity {namespace:$namespace, tenant_id:$tenant_id, knowledge_base_id:$knowledge_base_id})
  WHERE any(a IN $active WHERE n.knowledge_id=a.knowledge_id AND n.generation=a.generation)
  RETURN properties(n) AS node, null AS relation, 'node' AS kind, n.id AS key, n.generation AS generation
  UNION ALL
  MATCH (s:MarlinEntity {namespace:$namespace, tenant_id:$tenant_id, knowledge_base_id:$knowledge_base_id})
    -[r:MARLIN_REL {namespace:$namespace, tenant_id:$tenant_id, knowledge_base_id:$knowledge_base_id}]->
    (t:MarlinEntity {namespace:$namespace, tenant_id:$tenant_id, knowledge_base_id:$knowledge_base_id})
  WHERE any(a IN $active WHERE r.knowledge_id=a.knowledge_id AND r.generation=a.generation)
    AND s.knowledge_id=r.knowledge_id AND t.knowledge_id=r.knowledge_id
    AND s.generation=r.generation AND t.generation=r.generation
  RETURN null AS node, properties(r) AS relation, 'relation' AS kind, r.id AS key, r.generation AS generation
}
RETURN node, relation ORDER BY kind,key,generation SKIP $offset LIMIT $limit`;
export const deleteDocument = `// MARLIN_DELETE_DOCUMENT
MATCH (n:MarlinEntity {namespace:$namespace, tenant_id:$tenant_id, knowledge_base_id:$knowledge_base_id, knowledge_id:$knowledge_id})
WHERE $generation='' OR n.generation=$generation
DETACH DELETE n RETURN count(*) AS deleted`;
/** Only a persisted deletion ticket for an already tombstoned KB may invoke this. */
export const deleteKnowledgeBase = `// MARLIN_DELETE_KNOWLEDGE_BASE
MATCH (n:MarlinEntity {namespace:$namespace, tenant_id:$tenant_id, knowledge_base_id:$knowledge_base_id})
DETACH DELETE n RETURN count(*) AS deleted`;
