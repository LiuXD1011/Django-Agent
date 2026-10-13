"""Refresh graph connections when the persisted integration settings change."""
import threading

from .integration_config import neo4j_configuration


class ConfiguredNeo4jConnection:
    def __init__(self):
        self._driver = None
        self._driver_signature = None
        self._driver_lock = threading.Lock()

    @property
    def enabled(self):
        return bool(neo4j_configuration()["enabled"])

    @property
    def driver(self):
        config = neo4j_configuration()
        config["enabled"] = self.enabled
        signature = tuple(config[key] for key in ("enabled", "uri", "username", "password"))
        with self._driver_lock:
            if self._driver_signature != signature:
                if self._driver is not None:
                    # Drivers supplied by callers/tests before the first read stay usable.
                    if self._driver_signature is None and config["enabled"]:
                        self._driver_signature = signature
                        return self._driver
                    self._driver.close()
                self._driver = None
                self._driver_signature = signature
            if not config["enabled"]:
                return None
            if self._driver is None:
                try:
                    from neo4j import GraphDatabase

                    self._driver = GraphDatabase.driver(
                        config["uri"], auth=(config["username"], config["password"]),
                        connection_timeout=5, connection_acquisition_timeout=5,
                        max_transaction_retry_time=0,
                    )
                except (ImportError, ValueError):
                    return None
            return self._driver
