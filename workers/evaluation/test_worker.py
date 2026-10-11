"""Standalone worker boundary tests; no Django and no business database access."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

WORKER = Path(__file__).with_name('worker.py')

class BoundaryTests(unittest.TestCase):
    def probe(self, body, prelude=''):
        script = prelude + "import importlib.util,sys\nspec=importlib.util.spec_from_file_location('evaluation_worker',%r)\nworker=importlib.util.module_from_spec(spec)\nspec.loader.exec_module(worker)\n" % str(WORKER)
        completed = subprocess.run([sys.executable, '-c', script + body], capture_output=True, text=True, timeout=15)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    def test_django_import_is_blocked(self):
        result = self.probe("try:\n import django\nexcept ImportError:\n print('{\"blocked\":true}')\nelse:\n print('{\"blocked\":false}')\n")
        self.assertTrue(result['blocked'])

    def test_sqlite_connection_is_blocked_before_file_creation(self):
        with tempfile.TemporaryDirectory(prefix='marlin-eval-boundary-') as root:
            path = Path(root) / 'forbidden.sqlite3'
            result = self.probe("import sqlite3\ntry:\n sqlite3.connect(%r)\nexcept PermissionError:\n print('{\"blocked\":true}')\nelse:\n print('{\"blocked\":false}')\n" % str(path))
            self.assertTrue(result['blocked'])
            self.assertFalse(path.exists())

    def test_database_file_open_is_blocked(self):
        with tempfile.TemporaryDirectory(prefix='marlin-eval-boundary-') as root:
            path = Path(root) / 'business.sqlite3'
            body = "try:\n open(%r,'wb')\nexcept PermissionError:\n print('{\"blocked\":true}')\nelse:\n print('{\"blocked\":false}')\n" % str(path)
            self.assertTrue(self.probe(body)['blocked'])
            self.assertFalse(path.exists())

    def test_direct_network_is_blocked(self):
        result = self.probe("import socket\ns=socket.socket()\ntry:\n s.connect(('127.0.0.1',9))\nexcept PermissionError:\n print('{\"blocked\":true}')\nelse:\n print('{\"blocked\":false}')\nfinally:\n s.close()\n")
        self.assertTrue(result['blocked'])

    def test_child_process_creation_is_blocked(self):
        result = self.probe("import subprocess\ntry:\n subprocess.Popen(['unreachable-program'])\nexcept PermissionError:\n print('{\"blocked\":true}')\nelse:\n print('{\"blocked\":false}')\n")
        self.assertTrue(result['blocked'])

    def test_protocol_input_is_bounded(self):
        result = self.probe("import io\nsys.stdin=io.TextIOWrapper(io.BytesIO(b'{'+b'x'*(worker.MAX_LINE+1)))\ntry:\n worker.read()\nexcept ValueError:\n print('{\"blocked\":true}')\nelse:\n print('{\"blocked\":false}')\n")
        self.assertTrue(result['blocked'])

    def test_trusted_async_bootstrap_supports_windows_socketpair_without_allowing_network(self):
        # Windows asyncio creates a loopback self-pipe; reproduce its fallback on POSIX.
        body = "import socket,asyncio\nasync def nothing():\n return 7\nvalue=getattr(worker,'run_async',asyncio.run)(nothing())\ns=socket.socket()\ntry:\n s.connect(('127.0.0.1',9))\nexcept PermissionError:\n blocked=True\nelse:\n blocked=False\nfinally:\n s.close()\nprint(json.dumps({'value':value,'blocked':blocked}))\n"
        fallback = "import socket,json\ndef fallback_pair(*args,**kwargs):\n listener=socket.socket()\n client=socket.socket()\n try:\n  listener.bind(('127.0.0.1',0))\n  listener.listen(1)\n  client.connect(listener.getsockname())\n  server,_=listener.accept()\n  return server,client\n finally:\n  listener.close()\nsocket.socketpair=fallback_pair\n"
        result = self.probe(body, fallback)
        self.assertEqual(result, {'value': 7, 'blocked': True})

if __name__ == '__main__':
    unittest.main()
