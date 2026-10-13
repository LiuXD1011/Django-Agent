import ast
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
MIGRATIONS_DIR = PROJECT_ROOT / "personal_knowledge_base" / "migrations"


def _migration_names() -> set[str]:
    return {
        path.stem
        for path in MIGRATIONS_DIR.glob("*.py")
        if path.name != "__init__.py"
    }


def _dependencies(path: Path) -> list[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Migration":
            for stmt in node.body:
                if isinstance(stmt, ast.Assign):
                    for target in stmt.targets:
                        if isinstance(target, ast.Name) and target.id == "dependencies":
                            return [
                                tuple(item.value for item in dep.elts)
                                for dep in stmt.value.elts
                                if isinstance(dep, ast.Tuple)
                                and len(dep.elts) == 2
                                and all(isinstance(item, ast.Constant) for item in dep.elts)
                            ]
    return []


class MigrationGraphIntegrityTest(unittest.TestCase):
    def test_personal_knowledge_base_dependencies_point_to_existing_files(self):
        names = _migration_names()
        missing = []
        for path in MIGRATIONS_DIR.glob("*.py"):
            if path.name == "__init__.py":
                continue
            for app, migration in _dependencies(path):
                if app == "personal_knowledge_base" and migration not in names:
                    missing.append(f"{path.name} -> {migration}")

        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
