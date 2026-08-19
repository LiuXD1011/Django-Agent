import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


class FakeRecord:
    def __getitem__(self, key):
        raise KeyError(key)


class FakeTx:
    def __init__(self):
        self.query = ""
        self.params = {}

    def run(self, query, **params):
        self.query = query
        self.params = params
        return []


class FakeSession:
    def __init__(self):
        self.tx = FakeTx()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute_read(self, fn):
        return fn(self.tx)


class FakeDriver:
    def __init__(self):
        self.session_obj = FakeSession()

    def session(self):
        return self.session_obj


class MemoryNeo4jQueryTest(unittest.TestCase):
    def test_find_related_episodes_uses_single_limit_clause(self):
        from personal_knowledge_base.memory import MemoryRepository

        class TestMemoryRepository(MemoryRepository):
            @property
            def enabled(self):
                return True

        repo = TestMemoryRepository()
        driver = FakeDriver()
        repo._driver = driver

        repo.find_related_episodes("user-1", ["订单"], limit=5)

        query = driver.session_obj.tx.query
        self.assertEqual(query.count("LIMIT $limit"), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
