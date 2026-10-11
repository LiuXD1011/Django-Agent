import { randomUUID } from 'node:crypto';
import type { AuthService } from '../auth/index.js';
import type { AuthContext, Json, JsonObject } from '../contracts.js';
import type { WorkflowHook, WorkflowHookResult } from '../documents/pipeline.js';
import { enabled as booleanValue } from '../knowledge/config.js';
import type { ModelConfigurationService } from '../settings/model-configuration.js';
import type { CoreDatabase, Row } from '../storage/database.js';
import { array, check, chunks, completion, configuration, document, fail, hash, jsonPayload, kb, now, number, object, sourceFingerprint, sourceRefs, strings, text, warning } from './internal.js';
import { linkify, linkPattern, outgoing } from './links.js';
export { linkify } from './links.js';
export interface WikiList extends JsonObject {
    items: JsonObject[];
    data: JsonObject[];
    total: number;
    page: number;
    page_size: number;
}
export interface WikiGraph extends JsonObject {
    nodes: JsonObject[];
    edges: JsonObject[];
    meta: JsonObject;
}
export interface WikiIngestOptions {
    signal?: AbortSignal;
    publish?: <T>(work: () => T) => T;
    processConfig?: JsonObject;
    jobId?: string;
    attempt?: number;
}
interface Candidate {
    slug: string;
    title: string;
    page_type: string;
    aliases: string[];
    description: string;
}
const labels: Record<string, string> = { summary: '摘要', entity: '实体', concept: '概念', page: '页面', index: '目录' };
const referenceId = (ref: Json) => typeof ref === 'object' && ref !== null ? String(object(ref).knowledge_id ?? object(ref).id ?? object(ref).knowledgeId ?? '') : String(ref ?? '');
const slugify = (name: string) => name.trim().toLowerCase().replace(/[^\p{L}\p{N}\/_-]+/gu, '-').replace(/^-+|-+$/gu, '').slice(0, 160) || 'page';
const docRef = (d: Row): JsonObject => ({ knowledge_id: d.id!, title: d.title!, file_name: d.file_name!, source: d.source! });
/** All entry points consume an authoritative core AuthContext; no caller-controlled tenant field is accepted. */
export class WikiService {
    private closed = false;
    private readonly controllers = new Set<AbortController>();
    private readonly active = new Set<Promise<unknown>>();
    constructor(private readonly db: CoreDatabase, private readonly auth: AuthService, private readonly models: ModelConfigurationService) { }
    private scope(ctx: AuthContext, kbId: string, write = false): Row { return kb(this.db, this.auth, ctx, kbId, write ? 'wiki.write' : 'read'); }
    private pages(ctx: AuthContext, kbId: string, visible = false): Row[] {
        this.scope(ctx, kbId);
        return this.db.all(`SELECT id FROM wiki_pages WHERE tenant_id=? AND knowledge_base_id=? AND deleted_at IS NULL ${visible ? "AND slug<>'index' AND page_type<>'index'" : ''} ORDER BY title,slug,id`, ctx.tenantId, kbId).map(r => this.db.read('wiki_pages', String(r.id))!);
    }
    private page(ctx: AuthContext, kbId: string, slug: string, write = false): Row {
        this.scope(ctx, kbId, write);
        const row = this.db.get('SELECT id FROM wiki_pages WHERE tenant_id=? AND knowledge_base_id=? AND slug=? AND deleted_at IS NULL', ctx.tenantId, kbId, slug.replace(/^\/+/, ''));
        if (!row)
            fail(404, 'wiki_page_not_found', 'Wiki page not found');
        return this.db.read('wiki_pages', String(row.id))!;
    }
    private dto(page: Row): JsonObject { const { deleted_at: _deleted, ...data } = page; return { ...data, ...(page.page_metadata === undefined ? {} : { metadata: page.page_metadata }) }; }
    private pageList(rows: Row[], query: JsonObject = {}): WikiList {
        const requestedSize = query.page_size ?? query.limit;
        const unpaginated = requestedSize === undefined && query.page === undefined && query.offset === undefined;
        const pageSize = unpaginated ? Math.max(1, rows.length) : number(requestedSize, 50, 1, 200), offset = query.offset !== undefined && query.page === undefined ? number(query.offset, 0, 0, 10000000) : (number(query.page, 1, 1, 10000000) - 1) * pageSize;
        const items = rows.slice(offset, offset + pageSize).map(r => this.dto(r));
        return { items, data: items, total: rows.length, page: Math.floor(offset / pageSize) + 1, page_size: pageSize };
    }
    list(ctx: AuthContext, kbId: string, query: JsonObject = {}): WikiList { return this.pageList(this.pages(ctx, kbId, true), query); }
    get(ctx: AuthContext, kbId: string, slug: string): JsonObject { return this.dto(this.page(ctx, kbId, slug)); }
    private validate(data: JsonObject): void {
        if (!data || typeof data !== 'object' || Array.isArray(data) || Object.keys(data).some(k => !['slug', 'title', 'content', 'summary', 'folder_id', 'page_type', 'aliases', 'status', 'parent_slug', 'sort_order', 'version'].includes(k)))
            fail(400, 'invalid_wiki_input', 'Unsupported Wiki page field');
        if ('aliases' in data && (!Array.isArray(data.aliases) || data.aliases.length > 128 || data.aliases.some(v => typeof v !== 'string' || v.length > 512)))
            fail(400, 'invalid_wiki_input', 'Invalid page aliases');
    }
    private values(ctx: AuthContext, kbId: string, data: JsonObject, previous?: Row): Record<string, unknown> {
        this.validate(data);
        const title = text(data.title, 512, String(previous?.title ?? 'Untitled')), pageType = text(data.page_type, 32, String(previous?.page_type ?? 'page')) || 'page';
        const folderId = data.folder_id === undefined ? String(previous?.folder_id ?? '') : text(data.folder_id, 36);
        const folder = folderId ? this.folder(ctx, kbId, folderId) : this.defaultFolder(ctx, kbId, pageType);
        return { title, content: text(data.content, 2 * 1024 * 1024, String(previous?.content ?? '')), summary: text(data.summary, 65536, String(previous?.summary ?? '')),
            page_type: pageType, aliases: data.aliases === undefined ? previous?.aliases ?? [] : strings(data.aliases), status: text(data.status, 32, String(previous?.status ?? 'published')),
            folder_id: folder.id, parent_slug: text(data.parent_slug, 512, String(previous?.parent_slug ?? '')), category_path: String(folder.path).split('/'), wiki_path: `${folder.path}/${title}`, depth: Number(folder.depth) + 1,
            sort_order: number(data.sort_order, Number(previous?.sort_order ?? 0), -1000000, 1000000), updated_at: now() };
    }
    create(ctx: AuthContext, kbId: string, data: JsonObject): JsonObject {
        return this.db.transaction(() => {
            this.scope(ctx, kbId, true);
            this.validate(data);
            const title = text(data.title, 512, 'Untitled'), slug = text(data.slug, 512, slugify(title));
            if (!slug || /[\[\]|\n\r]/u.test(slug))
                fail(400, 'invalid_wiki_slug', 'Invalid Wiki page slug');
            if (this.db.get('SELECT id FROM wiki_pages WHERE knowledge_base_id=? AND slug=?', kbId, slug))
                fail(409, 'wiki_page_conflict', 'Wiki page already exists');
            const row = this.db.insert('wiki_pages', { tenant_id: ctx.tenantId, knowledge_base_id: kbId, slug, ...this.values(ctx, kbId, data), page_metadata: { manual: true } });
            this.refreshLinks(ctx, kbId);
            return this.get(ctx, kbId, String(row.slug));
        });
    }
    update(ctx: AuthContext, kbId: string, slug: string, data: JsonObject): JsonObject {
        return this.db.transaction(() => {
            const row = this.page(ctx, kbId, slug, true);
            this.validate(data);
            if (data.slug !== undefined && data.slug !== row.slug)
                fail(400, 'wiki_slug_immutable', 'Wiki page slug cannot be changed');
            if (data.version !== undefined && data.version !== row.version)
                fail(409, 'wiki_revision_conflict', 'Wiki page changed; refresh before editing');
            const metadata = { ...object(row.page_metadata), manual_edit: true, ...(data.content === undefined ? {} : { manual_content: data.content! }) };
            this.db.update('wiki_pages', String(row.id), { ...this.values(ctx, kbId, data, row), page_metadata: metadata, version: Number(row.version) + 1 });
            this.refreshLinks(ctx, kbId);
            return this.get(ctx, kbId, slug);
        });
    }
    delete(ctx: AuthContext, kbId: string, slug: string): JsonObject {
        return this.db.transaction(() => { const row = this.page(ctx, kbId, slug, true); this.db.update('wiki_pages', String(row.id), { deleted_at: now(), updated_at: now(), version: Number(row.version) + 1 }); this.refreshLinks(ctx, kbId, new Set([String(row.slug)])); return {}; });
    }
    private refreshLinks(ctx: AuthContext, kbId: string, removed = new Set<string>(), inject = false): void {
        const pages = this.pages(ctx, kbId), bySlug = new Map(pages.map(p => [String(p.slug), p]));
        const deleted = new Set(this.db.all('SELECT slug FROM wiki_pages WHERE tenant_id=? AND knowledge_base_id=? AND deleted_at IS NOT NULL', ctx.tenantId, kbId).map(r => String(r.slug)));
        for (const slug of removed)
            deleted.add(slug);
        const out = new Map<string, string[]>(), incoming = new Map<string, string[]>();
        for (const row of pages) {
            let content = String(row.content).replace(linkPattern, (whole, target: string, label?: string) => deleted.has(target.trim()) ? label ?? target : whole);
            if (inject && !object(row.page_metadata).manual && !object(row.page_metadata).manual_edit)
                content = linkify(content, pages, String(row.slug));
            const links = outgoing(content, String(row.slug)).filter(s => !deleted.has(s));
            out.set(String(row.slug), links);
            for (const target of links)
                if (bySlug.has(target))
                    incoming.set(target, [...incoming.get(target) ?? [], String(row.slug)]);
            if (content !== row.content)
                this.db.update('wiki_pages', String(row.id), { content, updated_at: now() });
        }
        for (const row of pages)
            this.db.update('wiki_pages', String(row.id), { out_links: out.get(String(row.slug)) ?? [], in_links: incoming.get(String(row.slug)) ?? [] });
    }
    private folder(ctx: AuthContext, kbId: string, id: string, write = false): Row {
        this.scope(ctx, kbId, write);
        const row = this.db.read('wiki_folders', id);
        if (!row || row.deleted_at !== null || String(row.tenant_id) !== ctx.tenantId || row.knowledge_base_id !== kbId)
            fail(404, 'wiki_folder_not_found', 'Wiki folder not found');
        return row;
    }
    getFolder(ctx: AuthContext, kbId: string, id: string): JsonObject { const { deleted_at: _deleted, ...data } = this.folder(ctx, kbId, id); return data; }
    folders(ctx: AuthContext, kbId: string, query: JsonObject = {}): WikiList {
        this.scope(ctx, kbId);
        const rows = this.db.all('SELECT id FROM wiki_folders WHERE tenant_id=? AND knowledge_base_id=? AND deleted_at IS NULL ORDER BY sort_order,name,id', ctx.tenantId, kbId).map(r => this.folder(ctx, kbId, String(r.id)));
        const result = this.pageList(rows, query);
        result.items = result.items.map(({ metadata: _meta, ...row }) => row);
        result.data = result.items;
        return result;
    }
    private defaultFolder(ctx: AuthContext, kbId: string, type: string): Row {
        const name = labels[type] ?? '页面', existing = this.db.get("SELECT id FROM wiki_folders WHERE tenant_id=? AND knowledge_base_id=? AND name=? AND parent_id='' AND deleted_at IS NULL ORDER BY id LIMIT 1", ctx.tenantId, kbId, name);
        return existing ? this.folder(ctx, kbId, String(existing.id)) : this.db.insert('wiki_folders', { tenant_id: ctx.tenantId, knowledge_base_id: kbId, name, path: name, sort_order: 4 });
    }
    private folderValues(ctx: AuthContext, kbId: string, data: JsonObject, previous?: Row): Record<string, unknown> {
        if (Object.keys(data).some(k => !['name', 'parent_id', 'path', 'depth', 'sort_order'].includes(k)))
            fail(400, 'invalid_wiki_folder', 'Unsupported Wiki folder field');
        const name = text(data.name, 255, String(previous?.name ?? 'Folder')), parentId = text(data.parent_id, 36, String(previous?.parent_id ?? ''));
        if (!name || name.includes('/'))
            fail(400, 'invalid_wiki_folder', 'Invalid folder name');
        const parent = parentId ? this.folder(ctx, kbId, parentId) : undefined;
        const seen = new Set<string>(previous ? [String(previous.id)] : []);
        let ancestor = parent;
        while (ancestor) {
            if (seen.has(String(ancestor.id)))
                fail(409, 'wiki_folder_cycle', 'Folder hierarchy cannot contain cycles');
            seen.add(String(ancestor.id));
            ancestor = ancestor.parent_id ? this.folder(ctx, kbId, String(ancestor.parent_id)) : undefined;
        }
        const previousPath = previous && data.name === undefined && data.parent_id === undefined ? String(previous.path) : parent ? `${parent.path}/${name}` : name;
        const previousDepth = previous && data.parent_id === undefined ? Number(previous.depth) : parent ? Number(parent.depth) + 1 : 0;
        return { name, parent_id: parentId, path: text(data.path, 2048, previousPath), depth: number(data.depth, previousDepth, 0, 10000), sort_order: number(data.sort_order, Number(previous?.sort_order ?? 0), -1000000, 1000000), updated_at: now() };
    }
    createFolder(ctx: AuthContext, kbId: string, data: JsonObject): JsonObject { return this.db.transaction(() => { this.scope(ctx, kbId, true); const row = this.db.insert('wiki_folders', { tenant_id: ctx.tenantId, knowledge_base_id: kbId, ...this.folderValues(ctx, kbId, data) }); return this.getFolder(ctx, kbId, String(row.id)); }); }
    private rebuildFolders(ctx: AuthContext, kbId: string, roots: string[], preserveRoots = false): void {
        const folders = this.db.all('SELECT id FROM wiki_folders WHERE tenant_id=? AND knowledge_base_id=? AND deleted_at IS NULL', ctx.tenantId, kbId).map(r => this.folder(ctx, kbId, String(r.id)));
        const pending = [...roots], visited = new Set<string>(), retained = new Set(preserveRoots ? roots : []);
        while (pending.length) {
            const id = pending.shift()!;
            if (visited.has(id))
                fail(409, 'wiki_folder_cycle', 'Folder hierarchy cannot contain cycles');
            visited.add(id);
            const row = this.folder(ctx, kbId, id);
            if (!retained.has(id))
                this.db.update('wiki_folders', id, this.folderValues(ctx, kbId, { name: row.name!, parent_id: row.parent_id! }, row));
            pending.push(...folders.filter(folder => folder.parent_id === id).map(folder => String(folder.id)));
        }
        for (const page of this.pages(ctx, kbId)) {
            const folder = page.folder_id ? this.folder(ctx, kbId, String(page.folder_id)) : undefined;
            this.db.update('wiki_pages', String(page.id), { category_path: folder ? String(folder.path).split('/') : [], wiki_path: folder ? `${folder.path}/${page.title}` : page.title, depth: folder ? Number(folder.depth) + 1 : 0 });
        }
    }
    updateFolder(ctx: AuthContext, kbId: string, id: string, data: JsonObject): JsonObject { return this.db.transaction(() => { const row = this.folder(ctx, kbId, id, true); this.db.update('wiki_folders', id, this.folderValues(ctx, kbId, data, row)); this.rebuildFolders(ctx, kbId, [id], true); return this.getFolder(ctx, kbId, id); }); }
    deleteFolder(ctx: AuthContext, kbId: string, id: string): JsonObject {
        return this.db.transaction(() => { const row = this.folder(ctx, kbId, id, true), children = this.db.all('SELECT id FROM wiki_folders WHERE tenant_id=? AND knowledge_base_id=? AND parent_id=? AND deleted_at IS NULL', ctx.tenantId, kbId, id).map(child => String(child.id)); this.db.run('UPDATE wiki_folders SET parent_id=? WHERE tenant_id=? AND knowledge_base_id=? AND parent_id=? AND deleted_at IS NULL', String(row.parent_id), ctx.tenantId, kbId, id); this.db.run('UPDATE wiki_pages SET folder_id=? WHERE tenant_id=? AND knowledge_base_id=? AND folder_id=? AND deleted_at IS NULL', String(row.parent_id), ctx.tenantId, kbId, id); this.db.update('wiki_folders', id, { deleted_at: now(), updated_at: now() }); this.rebuildFolders(ctx, kbId, children); return {}; });
    }
    index(ctx: AuthContext, kbId: string): JsonObject {
        const pages = this.pages(ctx, kbId, true).sort((a, b) => String(a.page_type).localeCompare(String(b.page_type)) || Number(a.sort_order) - Number(b.sort_order) || String(a.title).localeCompare(String(b.title)));
        return { groups: [...new Set(pages.map(p => String(p.page_type)))].map(type => ({ type, title: labels[type] ?? type, pages: pages.filter(p => p.page_type === type).map(p => this.dto(p)) })), items: pages.map(p => this.dto(p)) };
    }
    search(ctx: AuthContext, kbId: string, query: JsonObject = {}): WikiList & {
        pages: JsonObject[];
    } {
        const term = text(query.q ?? query.query, 4096).toLocaleLowerCase();
        const pages = this.pages(ctx, kbId, true).filter(p => [p.title, p.content].some(v => String(v).toLocaleLowerCase().includes(term)));
        const result = this.pageList(pages, { ...query, limit: number(query.limit, 50, 1, 200) });
        return { ...result, pages: result.items };
    }
    graph(ctx: AuthContext, kbId: string, query: JsonObject = {}): WikiGraph {
        const pages = this.pages(ctx, kbId, true), bySlug = new Map(pages.map(p => [String(p.slug), p])), adjacency = new Map<string, Set<string>>(), out = new Map<string, string[]>();
        for (const page of pages) {
            const refs = array(page.out_links).length ? array(page.out_links) : array(page.source_refs);
            const links = [...new Set(refs.map(r => typeof r === 'object' && r ? String(object(r).slug ?? object(r).target ?? object(r).page_slug ?? '') : String(r)).filter(s => bySlug.has(s) && s !== page.slug))];
            out.set(String(page.slug), links);
            for (const target of links) {
                const s = String(page.slug);
                adjacency.set(s, new Set([...adjacency.get(s) ?? [], target]));
                adjacency.set(target, new Set([...adjacency.get(target) ?? [], s]));
            }
        }
        const mode = text(query.mode, 16, 'overview'), center = text(query.center, 512), depth = number(query.depth, 1, 1, 3), limit = number(query.limit, 500, 1, 2000), offset = number(query.offset, 0, 0, 10000000), types = new Set(typeof query.types === 'string' ? query.types.split(',').map(s => s.trim()).filter(Boolean) : strings(query.types));
        if (!['overview', 'ego'].includes(mode))
            fail(400, 'invalid_graph_mode', 'Graph mode must be overview or ego');
        if (mode === 'ego' && !center)
            fail(400, 'graph_center_required', 'Graph center is required');
        const eligible = pages.filter(p => !types.size || types.has(String(p.page_type))), eligibleSlugs = new Set(eligible.map(p => String(p.slug)));
        let selected: string[];
        if (mode === 'ego') {
            const seen = new Set<string>(bySlug.has(center) ? [center] : []);
            let frontier = [...seen];
            for (let i = 0; i < depth; i++) {
                const next = [...new Set(frontier.flatMap(s => [...adjacency.get(s) ?? []]))].filter(s => eligibleSlugs.has(s) && !seen.has(s));
                for (const s of next)
                    seen.add(s);
                frontier = next;
            }
            selected = [...seen].sort((a, b) => a === center ? -1 : b === center ? 1 : a.localeCompare(b));
        }
        else
            selected = eligible.sort((a, b) => (adjacency.get(String(b.slug))?.size ?? 0) - (adjacency.get(String(a.slug))?.size ?? 0) || String(a.title).localeCompare(String(b.title)) || String(a.slug).localeCompare(String(b.slug))).map(p => String(p.slug));
        const total = selected.length;
        selected = selected.slice(offset, offset + limit);
        const chosen = new Set(selected);
        return { nodes: selected.map(slug => { const p = bySlug.get(slug)!; return { id: slug, slug, label: p.title!, title: p.title!, page_type: p.page_type!, link_count: adjacency.get(slug)?.size ?? 0 }; }), edges: selected.flatMap(source => (out.get(source) ?? []).filter(t => chosen.has(t)).map(target => ({ source, target }))), meta: { mode, center, depth, total, returned: selected.length, truncated: total > selected.length, offset, limit } };
    }
    stats(ctx: AuthContext, kbId: string): JsonObject {
        const pages = this.pages(ctx, kbId, true), slugs = new Set(pages.map(page => String(page.slug))), counts: JsonObject = {}, linked = new Set<string>();
        let totalLinks = 0;
        for (const page of pages) {
            const refs = array(page.out_links).length ? array(page.out_links) : array(page.source_refs);
            const targets = [...new Set(refs.map(ref => typeof ref === 'object' && ref ? String(object(ref).slug ?? object(ref).target ?? object(ref).page_slug ?? '') : String(ref)).filter(slug => slugs.has(slug) && slug !== page.slug))];
            totalLinks += targets.length;
            if (targets.length)
                linked.add(String(page.slug));
            for (const target of targets)
                linked.add(target);
        }
        for (const page of pages)
            counts[String(page.page_type)] = Number(counts[String(page.page_type)] ?? 0) + 1;
        return { pages: pages.length, total_pages: pages.length, folders: this.folders(ctx, kbId).total, total_links: totalLinks, pages_by_type: counts, orphan_count: pages.filter(p => !linked.has(String(p.slug))).length,
            recent_updates: [...pages].sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at))).slice(0, 5).map(p => this.dto(p)), pending_tasks: Number(this.db.get('SELECT count(*) AS n FROM wiki_pending_ops WHERE tenant_id=? AND scope_id=?', ctx.tenantId, kbId)?.n ?? 0), pending_issues: this.issues(ctx, kbId).items.length, is_active: true };
    }
    log(ctx: AuthContext, kbId: string, query: JsonObject = {}): WikiList { this.scope(ctx, kbId); return this.pageList(this.db.all('SELECT id FROM wiki_log_entries WHERE tenant_id=? AND knowledge_base_id=? ORDER BY created_at DESC,id DESC', ctx.tenantId, kbId).map(r => this.db.read('wiki_log_entries', String(r.id))!), { limit: 100, ...query }); }
    lint(ctx: AuthContext, kbId: string): {
        issues: JsonObject[];
    } {
        const pages = this.pages(ctx, kbId, true), slugs = new Set(pages.map(p => String(p.slug))), issues = pages.flatMap(p => outgoing(String(p.content), String(p.slug)).filter(s => !slugs.has(s)).map(target => ({ id: `wiki-issue:${hash([ctx.tenantId, kbId, p.slug, target])}`, knowledge_base_id: kbId, slug: p.slug!, target, kind: 'broken_link', status: 'open' })));
        return { issues };
    }
    issues(ctx: AuthContext, kbId: string, query: JsonObject = {}): {
        items: JsonObject[];
    } {
        const items = this.lint(ctx, kbId).issues.map(issue => { const row = this.db.read('generic_resources', String(issue.id)); return row && String(row.tenant_id) === ctx.tenantId && object(row.data).knowledge_base_id === kbId ? { ...issue, status: object(row.data).status ?? 'open' } : issue; }).filter(i => query.status === undefined || i.status === query.status);
        return { items };
    }
    updateIssueStatus(ctx: AuthContext, kbId: string, id: string, status: string): JsonObject {
        return this.db.transaction(() => { this.scope(ctx, kbId, true); if (!['open', 'resolved', 'ignored'].includes(status))
            fail(400, 'invalid_issue_status', 'Invalid Wiki issue status'); const issue = this.lint(ctx, kbId).issues.find(i => i.id === id); if (!issue)
            fail(404, 'wiki_issue_not_found', 'Wiki issue not found'); const existing = this.db.read('generic_resources', id); if (existing && (String(existing.tenant_id) !== ctx.tenantId || existing.resource_type !== 'wiki_issue' || object(existing.data).knowledge_base_id !== kbId))
            fail(409, 'wiki_issue_scope_mismatch', 'Wiki issue namespace is inconsistent'); const data = { ...issue, status }; if (existing)
            this.db.update('generic_resources', id, { data, updated_at: now() });
        else
            this.db.insert('generic_resources', { id, tenant_id: ctx.tenantId, resource_type: 'wiki_issue', name: id, data, status: 'active' }); return data; });
    }
    private enqueue(ctx: AuthContext, kbId: string, docId: string): void {
        this.scope(ctx, kbId, true);
        this.db.run('DELETE FROM wiki_pending_ops WHERE tenant_id=? AND scope_id=? AND dedup_key=?', ctx.tenantId, kbId, docId);
        this.db.insert('wiki_pending_ops', { tenant_id: ctx.tenantId, task_type: 'wiki:ingest', scope: 'knowledge_base', scope_id: kbId, op: 'ingest', dedup_key: docId, payload: { knowledge_id: docId } });
    }
    private contributions(ctx: AuthContext, kbId: string, page: Row): JsonObject {
        const values = object(object(page.page_metadata).contributions), valid: JsonObject = {}, live = chunks(this.db, ctx, kbId), allowed = new Map(live.map(c => [String(c.id), c]));
        for (const [id, value] of Object.entries(values)) {
            const d = this.db.read('knowledges', id);
            if (!d || String(d.tenant_id) !== ctx.tenantId || d.knowledge_base_id !== kbId || d.deleted_at !== null || d.enable_status !== 'enabled')
                continue;
            const c = object(value);
            valid[id] = { ...c, chunks: strings(c.chunks).filter(chunkId => allowed.get(chunkId)?.knowledge_id === id), doc_title: d.title! };
        }
        return valid;
    }
    private render(ctx: AuthContext, kbId: string, title: string, contributions: JsonObject): string {
        const parts = [`# ${title}`, '', '## 来源摘要', ''];
        const allowed = new Map(chunks(this.db, ctx, kbId).map(c => [String(c.id), c]));
        for (const [id, value] of Object.entries(contributions).sort(([, a], [, b]) => String(object(a).doc_title).localeCompare(String(object(b).doc_title)))) {
            const c = object(value);
            parts.push(`- 《${c.doc_title ?? id}》：${c.description ?? c.summary ?? ''}`);
            for (const chunkId of strings(c.chunks)) {
                const evidence = allowed.get(chunkId);
                if (evidence?.knowledge_id === id)
                    parts.push(`- [${chunkId}] ${Array.from(String(evidence.content)).slice(0, 300).join('')}`);
            }
        }
        return parts.join('\n').trim();
    }
    private retract(ctx: AuthContext, kbId: string, docId: string): string[] {
        const affected: string[] = [], removed = new Set<string>();
        for (const page of this.pages(ctx, kbId)) {
            const meta = object(page.page_metadata), original = object(meta.contributions);
            if (!(docId in original) && !array(page.source_refs).some(r => referenceId(r) === docId) && meta.source_knowledge_id !== docId)
                continue;
            affected.push(String(page.slug));
            const contributions = this.contributions(ctx, kbId, page);
            delete contributions[docId];
            const refs = array(page.source_refs).filter(r => referenceId(r) !== docId), chunkRefs = strings(Object.values(contributions).flatMap(v => strings(object(v).chunks)));
            if (!refs.length && !Object.keys(contributions).length && !meta.manual && !meta.manual_edit) {
                this.db.run('DELETE FROM wiki_pages WHERE id=? AND tenant_id=? AND knowledge_base_id=?', String(page.id), ctx.tenantId, kbId);
                removed.add(String(page.slug));
            }
            else
                this.db.update('wiki_pages', String(page.id), { content: meta.manual || meta.manual_edit ? page.content : this.render(ctx, kbId, String(page.title), contributions), summary: meta.manual || meta.manual_edit ? page.summary : '', source_refs: refs, chunk_refs: chunkRefs, page_metadata: { ...meta, contributions }, version: Number(page.version) + 1, updated_at: now() });
        }
        this.refreshLinks(ctx, kbId, removed);
        return affected;
    }
    removeDocument(ctx: AuthContext, kbId: string, docId: string): JsonObject {
        return this.db.transaction(() => { this.scope(ctx, kbId, true); const found = this.db.read('knowledges', docId); if (found && (String(found.tenant_id) !== ctx.tenantId || found.knowledge_base_id !== kbId))
            fail(404, 'knowledge_not_found', 'Document not found'); const affected = this.retract(ctx, kbId, docId); this.db.run('DELETE FROM wiki_pending_ops WHERE tenant_id=? AND scope_id=? AND dedup_key=?', ctx.tenantId, kbId, docId); this.rebuildIndex(ctx, kbId); this.db.insert('wiki_log_entries', { tenant_id: ctx.tenantId, knowledge_base_id: kbId, knowledge_id: docId, action: 'retract', pages_affected: affected, summary: `Retracted ${affected.length} Wiki contributions` }); return { pages: affected.length, status: 'completed' }; });
    }
    private rebuildIndex(ctx: AuthContext, kbId: string): void {
        const all = this.pages(ctx, kbId, true), existing = this.db.get('SELECT id,deleted_at FROM wiki_pages WHERE tenant_id=? AND knowledge_base_id=? AND slug=?', ctx.tenantId, kbId, 'index');
        if (existing?.deleted_at != null || !all.length && !existing)
            return;
        const folder = this.defaultFolder(ctx, kbId, 'index'), values = { title: 'Wiki 目录', content: `# Wiki 目录\n\n${all.map(p => `- [[${p.slug}|${p.title}]]`).join('\n')}`, summary: '自动生成的 Wiki 页面索引。', page_type: 'index', status: 'published', folder_id: folder.id, page_metadata: { generated: true }, updated_at: now() };
        if (existing)
            this.db.update('wiki_pages', String(existing.id), values);
        else
            this.db.insert('wiki_pages', { tenant_id: ctx.tenantId, knowledge_base_id: kbId, slug: 'index', ...values });
        this.refreshLinks(ctx, kbId, new Set(), true);
    }
    readonly workflowHook: WorkflowHook = context => this.ingest(context.auth, context.knowledgeBaseId, context.knowledgeId, { signal: context.signal, publish: context.publish, processConfig: context.processConfig, jobId: context.jobId, attempt: context.attempt });
    ingest(ctx: AuthContext, kbId: string, docId: string, options: WikiIngestOptions = {}): Promise<WorkflowHookResult> {
        if (this.closed)
            return Promise.reject(new Error('Wiki service is closed'));
        const controller = new AbortController();
        this.controllers.add(controller);
        const relay = () => controller.abort(options.signal?.reason);
        options.signal?.addEventListener('abort', relay, { once: true });
        if (options.signal?.aborted)
            relay();
        const claimId = randomUUID();
        const running = this.generate(ctx, kbId, docId, { ...options, signal: controller.signal }, claimId).catch(error => {
            // Task audit only: the specific invocation may finish its own claim after cancellation/revocation, never page content.
            const code = error && typeof error === 'object' && 'code' in error && /^[a-z][a-z0-9_.-]{0,63}$/u.test(String(error.code)) ? String(error.code) : 'wiki_generation_failed';
            const state = error && typeof error === 'object' && 'resultUnknown' in error && error.resultUnknown === true ? 'interrupted' : controller.signal.aborted ? 'cancelled' : 'failed';
            this.db.run("UPDATE wiki_pending_ops SET payload=json_set(payload,'$.execution_status',?),error_message=?,fail_count=fail_count+1 WHERE tenant_id=? AND scope_id=? AND dedup_key=? AND json_extract(payload,'$.claim_id')=?", state, code, ctx.tenantId, kbId, docId, claimId);
            throw error;
        }).finally(() => { options.signal?.removeEventListener('abort', relay); this.controllers.delete(controller); this.active.delete(running); });
        this.active.add(running);
        void running.catch(() => { });
        return running;
    }
    private async generate(ctx: AuthContext, kbId: string, docId: string, options: WikiIngestOptions, claimId: string): Promise<WorkflowHookResult> {
        check(options.signal);
        const base = this.scope(ctx, kbId, true), doc = document(this.db, this.auth, ctx, kbId, docId, 'wiki.write'), localChunks = chunks(this.db, ctx, kbId, docId);
        if (!booleanValue(options.processConfig?.wiki_enabled, booleanValue(object(base.indexing_strategy).wiki_enabled)) || doc.enable_status !== 'enabled' || !localChunks.length)
            return { status: 'pending', output: { reason: doc.enable_status !== 'enabled' ? 'source_disabled' : !localChunks.length ? 'no_chunks' : 'wiki_disabled' }, warnings: [warning('wiki_pending', 'wiki', 'Wiki generation requires an enabled source and chunks')] };
        const fingerprint = sourceFingerprint(this.db, ctx, kbId, doc), receiptKey = `wiki.receipt:${hash([ctx.tenantId, kbId, docId])}`, receipt = object(jsonPayload(this.db.get('SELECT value FROM desktop_meta WHERE key=?', receiptKey)?.value as string ?? '{}'));
        const cfg = configuration(this.models, ctx, String(object(base.wiki_config).model_id ?? base.summary_model_id ?? ''));
        const configHash = hash([base.wiki_config, base.summary_model_id, cfg]);
        if (cfg && receipt.fingerprint === fingerprint && receipt.configuration_signature === configHash && this.pages(ctx, kbId).some(p => array(p.source_refs).some(r => referenceId(r) === docId)))
            return { status: 'completed', output: { repeated: true, pages: Number(receipt.pages ?? 0) } };
        this.db.transaction(() => this.enqueue(ctx, kbId, docId));
        if (!cfg)
            return { status: 'needs_configuration', output: { pending: true, reason: 'wiki_model_not_configured' }, warnings: [warning('wiki_needs_configuration', 'wiki', 'Configure a Wiki extraction model to generate pages')] };
        this.db.transaction(() => {
            this.scope(ctx, kbId, true);
            check(options.signal);
            this.db.run("UPDATE wiki_pending_ops SET claimed_at=?,payload=json_set(payload,'$.claim_id',?,'$.execution_status','running','$.recovery_policy','manual') WHERE tenant_id=? AND scope_id=? AND dedup_key=?", now(), claimId, ctx.tenantId, kbId, docId);
        });
        const beforePages = this.pages(ctx, kbId), beforeHash = hash(beforePages), allChunks = chunks(this.db, ctx, kbId), lookup = new Map(allChunks.map(c => [String(c.id), c])), content = localChunks.map(c => String(c.content)).join('\n\n').slice(0, 32768);
        const callOptions = { ...options, knowledgeId: docId, knowledgeBaseId: kbId };
        const payload = object(jsonPayload(await completion(this.db, this.auth, this.models, ctx, cfg, `WIKI_CANDIDATES\nReturn strict JSON {"entities":[{"name":"...","aliases":[],"description":"..."}],"concepts":[]}. Preserve source language.\nTITLE: ${doc.title}\nSOURCE: ${content.slice(0, 12000)}`, 'wiki_candidate_slugs', callOptions)));
        const max = { focused: 6, standard: 10, exhaustive: 16 }[String(object(base.wiki_config).extraction_granularity) as 'focused'] ?? 10, candidates: Candidate[] = [];
        for (const [key, type] of [['entities', 'entity'], ['concepts', 'concept']])
            for (const value of array(payload[key!])) {
                const item = typeof value === 'string' ? { name: value } : object(value), title = text(item.name ?? item.title, 512).trim();
                if (!title)
                    continue;
                const slug = `${type}/${slugify(title)}`;
                if (!candidates.some(c => c.slug === slug) && candidates.length < max)
                    candidates.push({ slug, title, page_type: type!, aliases: strings(item.aliases, 6), description: text(item.description ?? item.summary, 8192) });
            }
        const pageInputs = candidates.map(c => { const page = beforePages.find(p => p.slug === c.slug), contributions = page ? this.contributions(ctx, kbId, page) : {}; delete contributions[docId]; return { ...c, existing_content: object(page?.page_metadata).manual_edit ? page?.content ?? '' : this.render(ctx, kbId, c.title, contributions), previous_contributions: contributions, evidence: localChunks.slice(0, 10).map(ch => ({ id: ch.id!, content: String(ch.content).slice(0, 600), provenance: object(ch.metadata).provenance ?? {} })) }; });
        const generated = new Map<string, JsonObject>();
        for (let start = 0; start < pageInputs.length; start += 5) {
            const parsed = object(jsonPayload(await completion(this.db, this.auth, this.models, ctx, cfg, `WIKI_PAGES\nGenerate or merge these pages using all current contributions. Return strict JSON {"pages":[{"slug":"...","summary":"...","content":"Markdown","referenced_chunks":[]}]}\nINPUT_JSON:\n${JSON.stringify(pageInputs.slice(start, start + 5))}`, 'wiki_page_generate', callOptions)));
            for (const item of array(parsed.pages)) {
                const page = object(item);
                if (candidates.some(c => c.slug === page.slug) && typeof page.content === 'string' && page.content.trim())
                    generated.set(String(page.slug), page);
            }
        }
        if (candidates.some(c => !generated.has(c.slug)))
            fail(502, 'wiki_generation_incomplete', 'Model did not generate all requested Wiki pages');
        const summary = await completion(this.db, this.auth, this.models, ctx, cfg, `WIKI_SUMMARY\nSummarize this source document in its original language. Return the summary text only.\nTITLE: ${doc.title}\nSOURCE: ${content.slice(0, 9000)}`, 'wiki_summary', callOptions);
        check(options.signal);
        return this.db.transaction(() => {
            let open = true, committed = false, finished = false;
            const commit = (): WorkflowHookResult => {
                if (!open || committed)
                    fail(409, 'wiki_publication_expired', 'Wiki publication is no longer active');
                committed = true;
                check(options.signal);
                const current = document(this.db, this.auth, ctx, kbId, docId, 'wiki.write'), currentBase = this.scope(ctx, kbId, true), currentCfg = configuration(this.models, ctx, String(object(currentBase.wiki_config).model_id ?? currentBase.summary_model_id ?? ''));
                if (sourceFingerprint(this.db, ctx, kbId, current) !== fingerprint || hash(this.pages(ctx, kbId)) !== beforeHash || hash([currentBase.wiki_config, currentBase.summary_model_id, currentCfg]) !== configHash)
                    fail(409, 'wiki_source_changed', 'Wiki source or pages changed during generation');
                const slugs = new Set(candidates.map(c => c.slug));
                slugs.add(`summary/${docId}`);
                for (const page of this.pages(ctx, kbId))
                    if (array(page.source_refs).some(r => referenceId(r) === docId) && !slugs.has(String(page.slug))) {
                        const contributions = this.contributions(ctx, kbId, page);
                        delete contributions[docId];
                        if (!Object.keys(contributions).length && !object(page.page_metadata).manual && !object(page.page_metadata).manual_edit)
                            this.db.run('DELETE FROM wiki_pages WHERE id=? AND tenant_id=? AND knowledge_base_id=?', String(page.id), ctx.tenantId, kbId);
                        else
                            this.db.update('wiki_pages', String(page.id), { content: object(page.page_metadata).manual_edit ? page.content : this.render(ctx, kbId, String(page.title), contributions), summary: '', source_refs: array(page.source_refs).filter(r => referenceId(r) !== docId), chunk_refs: strings(Object.values(contributions).flatMap(c => strings(object(c).chunks))), page_metadata: { ...object(page.page_metadata), contributions }, version: Number(page.version) + 1, updated_at: now() });
                    }
                const affected: string[] = [];
                const save = (slug: string, title: string, type: string, values: Record<string, unknown>) => {
                    const existing = this.db.get('SELECT id,deleted_at FROM wiki_pages WHERE knowledge_base_id=? AND slug=?', kbId, slug);
                    if (existing && existing.deleted_at !== null)
                        return;
                    if (existing && String(this.db.read('wiki_pages', String(existing.id))!.tenant_id) !== ctx.tenantId)
                        fail(409, 'wiki_page_scope_mismatch', 'Wiki page namespace is inconsistent');
                    const folder = this.defaultFolder(ctx, kbId, type), old = existing ? this.db.read('wiki_pages', String(existing.id)) : undefined, metadata = { ...object(old?.page_metadata), ...object(values.page_metadata), needs_rebuild: false, generated: true };
                    const patch = { title, page_type: type, status: 'published', folder_id: old?.folder_id || folder.id, category_path: [folder.name], wiki_path: `${folder.name}/${title}`, depth: 1, ...values, ...(object(old?.page_metadata).manual_edit ? { content: old!.content, summary: old!.summary } : {}), page_metadata: metadata, version: old ? Number(old.version) + 1 : 1, updated_at: now() };
                    if (existing)
                        this.db.update('wiki_pages', String(existing.id), patch);
                    else
                        this.db.insert('wiki_pages', { tenant_id: ctx.tenantId, knowledge_base_id: kbId, slug, ...patch });
                    affected.push(slug);
                };
                for (const candidate of candidates) {
                    const old = beforePages.find(p => p.slug === candidate.slug), contributions = old ? this.contributions(ctx, kbId, old) : {}, page = generated.get(candidate.slug)!;
                    const needles = [candidate.title, ...candidate.aliases], matched = localChunks.filter(c => needles.some(n => String(c.content).includes(n))).slice(0, 6), cited = strings(page.referenced_chunks).filter(id => lookup.get(id)?.knowledge_id === docId), chunkIds = cited.length ? cited : (matched.length ? matched : localChunks.slice(0, 1)).map(c => String(c.id));
                    // The merged page belongs to the whole topic, never to one contributor.
                    // Keep source-specific facts so removing a document cannot retain its prose in another contribution.
                    contributions[docId] = { doc_title: doc.title!, description: candidate.description, chunks: chunkIds, source_refs: chunkIds.flatMap(id => sourceRefs(lookup.get(id)!)) };
                    const refs = Object.keys(contributions).map(id => docRef(this.db.read('knowledges', id)!));
                    save(candidate.slug, candidate.title, candidate.page_type, { content: String(page.content), summary: text(page.summary, 65536), aliases: strings([...array(old?.aliases), ...candidate.aliases]), source_refs: refs, chunk_refs: strings(Object.values(contributions).flatMap(c => strings(object(c).chunks))), page_metadata: { contributions } });
                }
                save(`summary/${docId}`, String(doc.title), 'summary', { content: `# ${doc.title}\n\n${summary}\n\n## 相关页面\n\n${candidates.map(c => `- [[${c.slug}]]`).join('\n')}`, summary, source_refs: [docRef(doc)], chunk_refs: localChunks.slice(0, 8).map(c => String(c.id)), page_metadata: { source_knowledge_id: docId } });
                this.rebuildIndex(ctx, kbId);
                this.refreshLinks(ctx, kbId, new Set(), true);
                this.db.run('DELETE FROM wiki_pending_ops WHERE tenant_id=? AND scope_id=? AND dedup_key=?', ctx.tenantId, kbId, docId);
                this.db.run('INSERT INTO desktop_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', receiptKey, JSON.stringify({ fingerprint, configuration_signature: configHash, pages: affected.length }));
                this.db.insert('wiki_log_entries', { tenant_id: ctx.tenantId, knowledge_base_id: kbId, knowledge_id: docId, doc_title: doc.title, action: 'ingest', summary: `Generated ${affected.length} Wiki pages`, pages_affected: affected, details: { source_generation: object(doc.metadata).source_generation ?? null } });
                const result: WorkflowHookResult = { status: 'completed', output: { pages: affected.length, links: this.graph(ctx, kbId).edges.length, repeated: false }, warnings: [] };
                finished = true;
                return result;
            };
            try {
                const result = options.publish ? options.publish(commit) : commit();
                if (result && typeof (result as unknown as {
                    then?: unknown;
                }).then === 'function') {
                    void Promise.resolve(result).catch(() => { });
                    fail(409, 'wiki_publication_async', 'Wiki publication must be synchronous');
                }
                if (!finished)
                    fail(409, 'wiki_publication_missing', 'Wiki publication did not complete the write');
                return result;
            }
            finally {
                open = false;
            }
        });
    }
    async processPending(ctx: AuthContext, kbId: string, options: {
        signal?: AbortSignal;
        limit?: number;
    } = {}): Promise<JsonObject> {
        this.scope(ctx, kbId, true);
        const rows = this.db.all('SELECT id FROM wiki_pending_ops WHERE tenant_id=? AND scope_id=? AND task_type=? AND scope=? ORDER BY id LIMIT ?', ctx.tenantId, kbId, 'wiki:ingest', 'knowledge_base', options.limit ?? 5).map(r => this.db.read('wiki_pending_ops', String(r.id))!), results: JsonObject[] = [];
        const latest = new Map(rows.map(row => [String(row.dedup_key), row]));
        for (const row of latest.values()) {
            check(options.signal);
            const id = String(object(row.payload).knowledge_id ?? row.dedup_key);
            const doc = this.db.read('knowledges', id);
            if (row.op === 'retract' || !doc || doc.deleted_at !== null)
                results.push(this.removeDocument(ctx, kbId, id));
            else if (row.claimed_at !== null && object(row.payload).recovery_policy === 'manual')
                results.push({ status: 'manual_required', knowledge_id: id, reason: object(row.payload).execution_status ?? 'unknown' });
            else {
                const result = await this.ingest(ctx, kbId, id, { signal: options.signal });
                results.push({ status: result.status, ...(result.output ?? {}), warnings: result.warnings ?? [] });
            }
        }
        return { processed: results.length, results, pending: Number(this.db.get('SELECT count(*) AS n FROM wiki_pending_ops WHERE tenant_id=? AND scope_id=?', ctx.tenantId, kbId)?.n ?? 0) };
    }
    async close(): Promise<void> { this.closed = true; for (const controller of this.controllers)
        controller.abort(); await Promise.allSettled([...this.active]); }
}
