from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase

from .models import KnowledgeBase, Tenant, WikiPage
from .wiki_ingest import inject_cross_links as link_pages
from .wiki_page_generator import inject_cross_links


class WikiLinkTextTests(SimpleTestCase):
    def setUp(self):
        self.pages = [
            SimpleNamespace(title="orca-audit.md", slug="summary/doc", aliases=[]),
            SimpleNamespace(title="Orca", slug="entity/orca", aliases=[]),
        ]

    def test_overlapping_names_do_not_create_nested_links_and_repeated_passes_are_stable(self):
        content = "Source: orca-audit.md. Orca supports Django."
        linked = inject_cross_links(content, self.pages, "entity/django")
        self.assertEqual(linked, "Source: [[summary/doc|orca-audit.md]]. [[entity/orca|Orca]] supports Django.")
        self.assertEqual(inject_cross_links(linked, self.pages, "entity/django"), linked)

    def test_links_inline_code_and_fenced_code_remain_unchanged(self):
        protected = "# Orca\n[[summary/doc|orca-audit.md]] [Orca](https://example.com) `Orca`\n```text\nOrca\n```"
        linked = inject_cross_links(protected + "\nOrca is available.", self.pages, "page/fixture")
        self.assertEqual(linked, protected + "\n[[entity/orca|Orca]] is available.")


class WikiLinkPersistenceTests(TestCase):
    def test_ingest_keeps_global_longest_name_priority_across_page_aliases(self):
        tenant = Tenant.objects.create(name="alias priority", api_key="alias-priority")
        kb = KnowledgeBase.objects.create(tenant=tenant, name="fixture")
        source = WikiPage.objects.create(tenant=tenant, knowledge_base=kb, title="Source", slug="source", content="Artificial intelligence uses AI models.")
        WikiPage.objects.create(tenant=tenant, knowledge_base=kb, title="Artificial intelligence", slug="concept/ai", aliases=["AI"])
        WikiPage.objects.create(tenant=tenant, knowledge_base=kb, title="AI models", slug="concept/models")
        link_pages(kb, [source])
        source.refresh_from_db()
        self.assertEqual(source.content, "[[concept/ai|Artificial intelligence]] uses [[concept/models|AI models]].")

    def test_ingest_does_not_expand_single_character_aliases(self):
        tenant = Tenant.objects.create(name="short aliases", api_key="short-aliases")
        kb = KnowledgeBase.objects.create(tenant=tenant, name="fixture")
        source = WikiPage.objects.create(tenant=tenant, knowledge_base=kb, title="Source", slug="source", content="AI can analyze data.")
        WikiPage.objects.create(tenant=tenant, knowledge_base=kb, title="AI", slug="concept/ai", aliases=["a"])
        link_pages(kb, [source])
        source.refresh_from_db()
        self.assertEqual(source.content, "[[concept/ai|AI]] can analyze data.")

    def test_ingest_link_pass_preserves_existing_target_and_label(self):
        tenant = Tenant.objects.create(name="wiki links", api_key="wiki-link-fixture")
        kb = KnowledgeBase.objects.create(tenant=tenant, name="fixture")
        source = WikiPage.objects.create(tenant=tenant, knowledge_base=kb, title="Django", slug="entity/django", content="[[summary/doc|orca-audit.md]] and Orca.")
        WikiPage.objects.create(tenant=tenant, knowledge_base=kb, title="orca-audit.md", slug="summary/doc")
        WikiPage.objects.create(tenant=tenant, knowledge_base=kb, title="Orca", slug="entity/orca")
        link_pages(kb, [source])
        source.refresh_from_db()
        self.assertEqual(source.content, "[[summary/doc|orca-audit.md]] and [[entity/orca|Orca]].")
        self.assertEqual(set(source.out_links), {"summary/doc", "entity/orca"})
