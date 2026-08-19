"""
Diagnose Neo4j memory failures seen while asking questions in the chat page.

Run:
    python tests/test_neo4j_memory_root_cause.py

This is a local diagnostic test. It does not require Django to be fully
initialized or Neo4j to be installed. It verifies the root-cause chain shown in
the server log: Neo4j is enabled, the configured Bolt port is unreachable, and
the current availability check can still report memory as available because the
Neo4j driver connects lazily.
"""

import os
import socket
import unittest
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"


def _load_dotenv(path):
    values = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _env_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _neo4j_target(uri):
    parsed = urlparse(uri)
    return parsed.hostname or "localhost", parsed.port or 7687


class Neo4jMemoryRootCauseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = {**_load_dotenv(ENV_PATH), **os.environ}
        cls.neo4j_enabled = _env_bool(cls.env.get("NEO4J_ENABLE"), False)
        cls.neo4j_uri = cls.env.get("NEO4J_URI", "bolt://localhost:7687")
        cls.host, cls.port = _neo4j_target(cls.neo4j_uri)

    def test_project_configuration_enables_neo4j_memory(self):
        self.assertTrue(
            self.neo4j_enabled,
            f"NEO4J_ENABLE is not true in {ENV_PATH}; the pasted log must be from a different environment.",
        )
        self.assertEqual(self.neo4j_uri, "bolt://localhost:7687")

    def test_configured_neo4j_bolt_port_is_not_accepting_connections(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1)
            result = sock.connect_ex((self.host, self.port))

        self.assertNotEqual(
            result,
            0,
            f"Neo4j is accepting connections at {self.host}:{self.port}; the pasted connection-refused log is stale.",
        )

    def test_current_memory_availability_check_can_be_true_without_live_neo4j_connection(self):
        try:
            from neo4j import GraphDatabase
        except ImportError as exc:
            raise unittest.SkipTest(f"neo4j package is not installed: {exc}")

        driver = GraphDatabase.driver(
            self.neo4j_uri,
            auth=(self.env.get("NEO4J_USERNAME", "neo4j"), self.env.get("NEO4J_PASSWORD", "password")),
        )
        try:
            # Mirrors personal_knowledge_base.memory.MemoryRepository.available:
            # enabled and driver object exists. Neo4j does not open the socket
            # until verify_connectivity/session transaction time.
            current_available_result = self.neo4j_enabled and driver is not None
            self.assertTrue(current_available_result)

            with self.assertRaises(Exception) as cm:
                driver.verify_connectivity()
            self.assertIn("Couldn't connect", str(cm.exception))
        finally:
            driver.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
