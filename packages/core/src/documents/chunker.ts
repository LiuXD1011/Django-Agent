import { createHash } from 'node:crypto';
import type { JsonObject, ParsedDocument, ParsedTextBlock } from '../contracts.js';
import { chunking, projectedChunking } from '../knowledge/config.js';
export interface ChunkDraft {
    content: string;
    context_header: string;
    start_at: number;
    end_at: number;
    chunk_type: string;
    context_parent_index: number | null;
    metadata: JsonObject;
}
export interface ChunkingResult {
    parents: ChunkDraft[];
    children: ChunkDraft[];
    diagnostics: JsonObject;
}
export interface ChunkerOptions {
    title: string;
    signal?: AbortSignal;
    tokenCounter?: (text: string) => number;
    semanticEmbed?: (texts: string[]) => Promise<number[][]>;
    semanticDimension?: number;
    semanticSignature?: string;
    semanticCache?: Map<string, {
        inputs: string[];
        vectors: number[][];
    }>;
}
interface Unit {
    start: number;
    end: number;
    type: string;
    index: number;
    metadata: JsonObject;
    protected: boolean;
    boundary: boolean;
}
type Range = [
    number,
    number
];
const chars = (s: string) => Array.from(s);
const count = (s: string) => chars(s).length;
const obj = (x: unknown): JsonObject => x && typeof x === 'object' && !Array.isArray(x) ? x as JsonObject : {};
const floor = (size: number) => Math.max(8, Math.min(64, Math.floor(size / 4)));
const protectedTypes = new Set(['table', 'code', 'formula', 'link', 'image_reference']);
const check = (options: ChunkerOptions) => options.signal?.throwIfAborted();
function protectedRanges(text: string, offset = 0): Range[] {
    const ranges: Range[] = [];
    for (const pattern of [/^\s*(```|~~~)[\s\S]*?^\s*\1[^\n]*$/gm, /\$\$[\s\S]*?\$\$/g, /(?<!\$)\$[^\n$]+\$(?!\$)/g, /!?\[[^\]\n]*\]\([^\n)]*\)/g]) {
        for (const m of text.matchAll(pattern))
            ranges.push([offset + count(text.slice(0, m.index)), offset + count(text.slice(0, m.index! + m[0].length))]);
    }
    return merge(ranges);
}
function merge(ranges: Range[]): Range[] {
    const result: Range[] = [];
    for (const r of ranges.sort((a, b) => a[0] - b[0])) {
        const last = result.at(-1);
        if (last && r[0] <= last[1])
            last[1] = Math.max(last[1], r[1]);
        else
            result.push([...r]);
    }
    return result;
}
function units(parsed: ParsedDocument): Unit[] {
    const result: Unit[] = [];
    let previous: ParsedTextBlock | undefined;
    const images = parsed.blocks.filter(b => b.kind === 'image').map(b => b.block_index);
    for (const block of parsed.blocks.filter((b): b is ParsedTextBlock => b.kind === 'text')) {
        const metadata: JsonObject = { ...block.metadata, ...block.provenance, provenance: block.provenance, block_id: block.id };
        const page = metadata.page_index, oldPage = previous && { ...previous.metadata, ...previous.provenance }.page_index;
        const boundary = !!previous && (images.some(i => previous!.block_index < i && i < block.block_index) || page != null && oldPage != null && page !== oldPage);
        const base = block.canonical_range.start;
        const add = (start: number, end: number, type: string, extra: JsonObject = {}) => {
            if (start >= end)
                return;
            const value = chars(block.text).slice(start, end).join(''), ranges = protectedRanges(value);
            result.push({ start: base + start, end: base + end, type, index: block.block_index, metadata: { ...metadata, ...extra }, protected: protectedTypes.has(type) || ranges.some(r => r[0] === 0 && r[1] === count(value)), boundary: false });
        };
        const first = result.length;
        const matches = block.block_type === 'heading' ? [] : [...block.text.matchAll(/^(#{1,6})[ \t]+(.+?)[ \t]*$/gm)].filter(m => !protectedRanges(block.text).some(([s, e]) => s <= count(block.text.slice(0, m.index)) && e > count(block.text.slice(0, m.index))));
        let cursor = 0;
        for (const m of matches) {
            const start = count(block.text.slice(0, m.index)), end = start + count(m[0]);
            add(cursor, start, 'paragraph');
            add(start, end, 'heading', { heading_level: m[1]!.length });
            cursor = end;
        }
        add(cursor, count(block.text), block.block_type);
        if (result[first])
            result[first]!.boundary = boundary;
        previous = block;
    }
    return result;
}
function auto(items: Unit[]): string {
    if (items.some(u => u.type === 'heading'))
        return 'heading';
    if (items.some(u => u.type === 'record'))
        return 'record';
    if (items.some(u => ['paragraph', 'text_box'].includes(u.type) || ['slide_number', 'paragraph_index', 'page_number', 'page_index'].some(k => u.metadata[k] != null)))
        return 'layout';
    return 'recursive';
}
function metadata(items: Unit[], start: number, end: number, strategy: string): JsonObject {
    const covered = items.filter(u => u.start < end && u.end > start);
    return { strategy, block_indices: [...new Set(covered.map(u => u.index))], source_refs: covered.map(u => ({ ...u.metadata, block_index: u.index, block_type: u.type, canonical_start: u.start, canonical_end: u.end })) };
}
function draft(source: string[], items: Unit[], start: number, end: number, header: string, strategy: string): ChunkDraft {
    return { content: source.slice(start, end).join(''), context_header: header, start_at: start, end_at: end, chunk_type: 'text', context_parent_index: null, metadata: metadata(items, start, end, strategy) };
}
function ranges(items: Unit[], source: string[]): Range[] {
    return merge(items.flatMap(u => u.protected ? [[u.start, u.end] as Range] : protectedRanges(source.slice(u.start, u.end).join(''), u.start)));
}
function split(source: string[], items: Unit[], start: number, end: number, size: number, overlap: number, header: string, strategy: string, counter: (s: string) => number, limit: number): ChunkDraft[] {
    const output: ChunkDraft[] = [], protectedSpans = ranges(items, source);
    const inside = (n: number) => protectedSpans.find(([s, e]) => s < n && n < e);
    const boundary = (cursor: number, desired: number) => {
        const text = source.slice(cursor, desired).join('');
        for (const re of [/\n\s*\n/g, /\n/g, /[。！？.!?；;]\s*/g, /\s+/g]) {
            const positions = [...text.matchAll(re)].map(m => cursor + count(text.slice(0, m.index! + m[0].length))).filter(n => n >= cursor + Math.floor(size / 2) && !inside(n));
            if (positions.length)
                return positions.at(-1)!;
        }
        return desired;
    };
    let cursor = start;
    while (cursor < end) {
        let last = Math.min(end, cursor + size), p = inside(last);
        if (p)
            last = Math.min(end, p[1]);
        else if (last < end)
            last = boundary(cursor, last);
        if (limit) {
            while (counter(source.slice(cursor, last).join('')) > limit) {
                const earlier = protectedSpans.find(([s, e]) => s < last && cursor < e);
                if (earlier && earlier[0] <= cursor)
                    throw new Error('token_limit_exceeded:unsplittable_protected_range');
                last = earlier ? earlier[0] : last - 1;
                if (last <= cursor)
                    throw new Error('token_limit_exceeded:unsplittable_range');
            }
        }
        if (source.slice(cursor, last).join('').trim())
            output.push(draft(source, items, cursor, last, header, strategy));
        if (last >= end)
            break;
        cursor = Math.max(cursor + 1, last - overlap);
        p = inside(cursor);
        if (p)
            cursor = p[1];
    }
    return output;
}
function groups(items: Unit[], strategy: string, title: string, source: string[], boundaries: Set<number>): Array<{
    header: string;
    items: Unit[];
}> {
    const output: Array<{
        header: string;
        items: Unit[];
    }> = [];
    let headings: string[] = [], key = '', header = title;
    for (let i = 0; i < items.length; i++) {
        const u = items[i]!;
        let nextKey = key;
        if (strategy === 'heading' && u.type === 'heading') {
            const level = Number(u.metadata.heading_level ?? 1);
            headings = headings.slice(0, Math.max(0, level - 1));
            headings.push(source.slice(u.start, u.end).join('').replace(/^#{1,6}\s*/, '').trim());
            header = [title, ...headings].filter(Boolean).join(' > ');
            nextKey = `heading:${i}`;
        }
        else if (strategy === 'layout') {
            const page = u.metadata.slide_number ?? u.metadata.page_number ?? (u.metadata.page_index == null ? null : Number(u.metadata.page_index) + 1);
            nextKey = JSON.stringify([u.metadata.slide_number == null ? 'Page' : 'Slide', page]);
            header = [title, page == null ? '' : `${u.metadata.slide_number == null ? 'Page' : 'Slide'} ${page}`].filter(Boolean).join(' > ');
        }
        else if (strategy === 'record') {
            const sheet = u.metadata.sheet_name ?? u.metadata.record_group ?? 'Records', columns = Array.isArray(u.metadata.headers) ? u.metadata.headers.map(String) : [];
            nextKey = JSON.stringify([sheet, columns]);
            header = [title, String(sheet), columns.join(' | ')].filter(Boolean).join(' > ');
        }
        if (!output.length || nextKey !== key || u.boundary || boundaries.has(i))
            output.push({ header, items: [] });
        output.at(-1)!.items.push(u);
        key = nextKey;
    }
    return output;
}
function pack(source: string[], all: Unit[], strategy: string, title: string, size: number, overlap: number, counter: (s: string) => number, limit: number, boundaries: Set<number>): ChunkDraft[] {
    const output: ChunkDraft[] = [];
    for (const group of groups(all, strategy, title, source, boundaries)) {
        if (strategy === 'recursive') {
            output.push(...split(source, all, group.items[0]!.start, group.items.at(-1)!.end, size, overlap, group.header, strategy, counter, limit));
            continue;
        }
        let pending: Unit[] = [];
        const flush = () => { if (pending.length)
            output.push(draft(source, all, pending[0]!.start, pending.at(-1)!.end, group.header, strategy)); pending = []; };
        for (const u of group.items) {
            if (u.end - u.start > size && !u.protected) {
                flush();
                output.push(...split(source, all, u.start, u.end, size, overlap, group.header, strategy, counter, limit));
                continue;
            }
            const candidate = source.slice(pending[0]?.start ?? u.start, u.end).join('');
            if (pending.length && (count(candidate) > size || limit && counter(candidate) > limit))
                flush();
            pending.push(u);
        }
        flush();
    }
    return coalesce(output, source, all, size, counter, limit, strategy);
}
function coalesce(drafts: ChunkDraft[], source: string[], items: Unit[], size: number, counter: (s: string) => number, limit: number, strategy: string): ChunkDraft[] {
    const output: ChunkDraft[] = [];
    const same = (a: ChunkDraft, b: ChunkDraft) => !items.some(u => u.boundary && a.start_at < u.start && u.start <= b.start_at);
    const combine = (a: ChunkDraft, b: ChunkDraft, header: string) => draft(source, items, a.start_at, b.end_at, header, strategy);
    const fits = (c: ChunkDraft) => count(c.content) <= size && (!limit || counter(c.content) <= limit);
    for (let i = 0; i < drafts.length; i++) {
        let d = drafts[i]!;
        while (count(d.content.trim()) < floor(size)) {
            const next = drafts[i + 1], prev = output.at(-1);
            if (next && d.end_at <= next.start_at && !source.slice(d.end_at, next.start_at).join('').trim() && same(d, next) && fits(combine(d, next, next.context_header))) {
                d = combine(d, next, next.context_header);
                i++;
                continue;
            }
            if (prev && prev.end_at <= d.start_at && !source.slice(prev.end_at, d.start_at).join('').trim() && same(prev, d) && fits(combine(prev, d, prev.context_header))) {
                output.pop();
                d = combine(prev, d, prev.context_header);
            }
            break;
        }
        output.push(d);
    }
    return output;
}
async function semantic(items: Unit[], source: string[], config: JsonObject, options: ChunkerOptions): Promise<Set<number>> {
    if (!options.semanticEmbed)
        throw new Error('missing_embedding_callable');
    const dimension = options.semanticDimension;
    if (!Number.isSafeInteger(dimension) || dimension! <= 0)
        throw new Error('invalid_embedding_dimension');
    const inputs: string[] = [], segments: number[] = [];
    let segment = 0;
    for (let i = 0; i < items.length; i++) {
        if (items[i]!.boundary)
            segment = i;
        let end = i + 1;
        while (end < items.length && !items[end]!.boundary && end < i + Number(config.semantic_window_size))
            end++;
        inputs.push(items.slice(i, end).map(u => source.slice(u.start, u.end).join('')).join('\n'));
        segments.push(segment);
    }
    const key = createHash('sha256').update(JSON.stringify([options.semanticSignature ?? '', dimension, config.semantic_window_size, config.semantic_breakpoint_percentile, inputs, segments])).digest('hex');
    const cached = options.semanticCache?.get(key);
    const vectors = cached?.vectors ?? await options.semanticEmbed(inputs);
    check(options);
    if (vectors.length !== inputs.length || vectors.some(v => v.length !== dimension || v.some(n => !Number.isFinite(n)) || !Math.hypot(...v)))
        throw new Error('invalid_embedding_vectors');
    options.semanticCache?.set(key, { inputs, vectors });
    const distances: Array<[
        number,
        number
    ]> = [];
    for (let i = 1; i < vectors.length; i++)
        if (segments[i] === segments[i - 1]) {
            const a = vectors[i - 1]!, b = vectors[i]!, cos = a.reduce((n, x, j) => n + x * b[j]!, 0) / (Math.hypot(...a) * Math.hypot(...b));
            distances.push([i, 1 - Math.max(-1, Math.min(1, cos))]);
        }
    const values = distances.map(([, n]) => n).sort((a, b) => a - b), position = (values.length - 1) * Number(config.semantic_breakpoint_percentile) / 100, lo = Math.floor(position), hi = Math.ceil(position), threshold = values.length ? values[lo]! + (values[hi]! - values[lo]!) * (position - lo) : Infinity;
    const boundaries = new Set<number>();
    let start = 0;
    const minimum = floor(Number(config.enable_parent_child ? config.parent_chunk_size : config.chunk_size));
    for (let i = 1; i < items.length; i++)
        if (items[i]!.boundary) {
            boundaries.add(i);
            start = i;
        }
        else if (distances.some(([j, d]) => j === i && d >= threshold) && items.slice(start, i).reduce((n, u) => n + u.end - u.start, 0) >= minimum && items.slice(i).reduce((n, u) => n + u.end - u.start, 0) >= minimum) {
            boundaries.add(i);
            start = i;
        }
    return boundaries;
}
function validate(drafts: ChunkDraft[], source: string[], size: number, counter: (s: string) => number, limit: number): string[] {
    const issues: string[] = [];
    let cursor = 0, previous = -1;
    for (const d of drafts) {
        if (d.start_at < previous || d.start_at < 0 || d.end_at > d.start_at + source.length || source.slice(d.start_at, d.end_at).join('') !== d.content)
            issues.push('source_range_mismatch');
        if (limit && counter(d.content) > limit)
            issues.push('token_limit_exceeded');
        if (d.start_at > cursor && source.slice(cursor, d.start_at).join('').trim())
            issues.push('incomplete_source_coverage');
        cursor = Math.max(cursor, d.end_at);
        previous = d.start_at;
    }
    if (source.slice(cursor).join('').trim())
        issues.push('incomplete_source_coverage');
    const tiny = drafts.filter(d => count(d.content.trim()) < floor(size)).length;
    if (drafts.length > 2 && tiny > 2 && tiny / drafts.length > 0.25)
        issues.push('excessive_tiny_chunks');
    return [...new Set(issues)];
}
function statistics(drafts: ChunkDraft[], counter: (s: string) => number): JsonObject {
    const sizes = drafts.map(d => count(d.content)), tokens = drafts.map(d => counter(d.content));
    const avg = (a: number[]) => a.length ? a.reduce((n, x) => n + x, 0) / a.length : 0;
    return { count: drafts.length, total: sizes.reduce((n, x) => n + x, 0), min: sizes.length ? Math.min(...sizes) : 0, max: sizes.length ? Math.max(...sizes) : 0, average: avg(sizes), min_chars: sizes.length ? Math.min(...sizes) : 0, max_chars: sizes.length ? Math.max(...sizes) : 0, average_chars: avg(sizes), min_tokens: tokens.length ? Math.min(...tokens) : 0, max_tokens: tokens.length ? Math.max(...tokens) : 0, average_tokens: avg(tokens) };
}
/** All offsets and budgets use Unicode code points, matching the parser protocol and original Python slicing. */
export async function splitDocument(parsed: ParsedDocument, raw: unknown, options: ChunkerOptions): Promise<ChunkingResult> {
    const started = Date.now(), config = chunking({ ...projectedChunking({}).config, ...obj(raw) }), source = chars(parsed.document.canonical_text), items = units(parsed), requested = String(config.strategy), fallback: JsonObject[] = [];
    const counter = options.tokenCounter ?? ((s: string) => Math.ceil(count(s) / 4));
    check(options);
    let candidates = [requested === 'auto' ? auto(items) : requested], boundaries = new Set<number>();
    if (requested === 'semantic')
        try {
            boundaries = await semantic(items, source, config, options);
            candidates = ['semantic', auto(items)];
        }
        catch (error) {
            if (options.signal?.aborted || obj(error).resultUnknown === true || error instanceof Error && 'resultUnknown' in error && error.resultUnknown === true)
                throw error;
            fallback.push({ strategy: 'semantic', reason: error instanceof Error ? error.message : 'embedding_error' });
            candidates = [auto(items)];
        }
    if (!candidates.includes('recursive'))
        candidates.push('recursive');
    let last = 'empty_output';
    for (const strategy of [...new Set(candidates)]) {
        check(options);
        try {
            let parents: ChunkDraft[] = [], children: ChunkDraft[] = [];
            if (source.join('').trim()) {
                if (config.enable_parent_child) {
                    parents = pack(source, items, strategy, options.title, Number(config.parent_chunk_size), 0, counter, Number(config.token_limit), boundaries);
                    parents.forEach((p, i) => { p.chunk_type = 'parent_text'; const cs = split(source, items, p.start_at, p.end_at, Number(config.child_chunk_size), Number(config.child_chunk_overlap), p.context_header, strategy, counter, Number(config.token_limit)); for (const c of cs)
                        c.context_parent_index = i; children.push(...cs); });
                }
                else
                    children = pack(source, items, strategy, options.title, Number(config.chunk_size), Number(config.chunk_overlap), counter, Number(config.token_limit), boundaries);
            }
            const issues = validate(children, source, Number(config.enable_parent_child ? config.child_chunk_size : config.chunk_size), counter, Number(config.token_limit));
            if (parents.length)
                issues.push(...validate(parents, source, Number(config.parent_chunk_size), counter, Number(config.token_limit)));
            if (issues.length)
                throw new Error([...new Set(issues)].join(';'));
            return { parents, children, diagnostics: { requested_strategy: requested, selected_strategy: strategy, fallback_chain: fallback, size_statistics: { parents: statistics(parents, counter), children: statistics(children, counter) }, duration: (Date.now() - started) / 1000, duration_ms: Date.now() - started, token_counter_source: options.tokenCounter ? 'custom' : 'character_estimate' } };
        }
        catch (error) {
            last = error instanceof Error ? error.message : 'chunking_failed';
            fallback.push({ strategy, reason: last });
        }
    }
    throw new Error(`Chunk validation failed: ${last}`);
}
