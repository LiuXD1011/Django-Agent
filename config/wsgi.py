import os

from pathlib import Path
from django.core.wsgi import get_wsgi_application

from personal_knowledge_base.startup import mirror_legacy_migration_records


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
mirror_legacy_migration_records(Path(__file__).resolve().parent.parent / "db.sqlite3")

application = get_wsgi_application()
