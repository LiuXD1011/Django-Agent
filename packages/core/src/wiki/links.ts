import type { JsonObject } from '../contracts.js';
import { strings } from './internal.js';
export const linkPattern = /\[\[([^\]|\n]+)(?:\|([^\]\n]+))?\]\]/gu;
export function outgoing(content: string, slug: string): string[] {
    return [...new Set(Array.from(content.matchAll(linkPattern)).map(m => m[1]!.trim()).filter(s => s && s !== slug))];
}
/** Replace prose mentions while preserving headings, fenced code and existing Markdown structures. */
export function linkify(content: string, pages: JsonObject[], currentSlug: string): string {
    const candidates = pages.filter(p => p.slug !== currentSlug && p.page_type !== 'index').flatMap(p => strings([p.title, ...strings(p.aliases)]).filter(n => Array.from(n).length >= 2).map(name => ({ name, slug: String(p.slug) })))
        .sort((a, b) => b.name.length - a.name.length || a.slug.localeCompare(b.slug));
    let fence = '';
    return content.split('\n').map(line => {
        const marker = line.trim().match(/^(`{3,}|~{3,})/u)?.[1];
        if (marker) {
            if (!fence)
                fence = marker[0]!;
            else if (fence === marker[0])
                fence = '';
            return line;
        }
        if (fence || /^\s*#/u.test(line))
            return line;
        let result = line;
        for (const { name, slug } of candidates.slice(0, 80)) {
            const protectedSpans = [...result.matchAll(/\[\[[^\n]*?\]\]|!?\[[^\]\n]*\]\([^\n]*?\)|`+[^`\n]*`+/gu)].map(m => [m.index, m.index + m[0].length]);
            const escaped = name.replace(/[.*+?^${}()|[\]\\]/gu, '\\$&');
            const match = [...result.matchAll(new RegExp(escaped, 'giu'))].find(m => !protectedSpans.some(([a, b]) => a! < m.index + m[0].length && m.index < b!));
            if (match)
                result = result.slice(0, match.index) + `[[${slug}|${match[0]}]]` + result.slice(match.index + match[0].length);
        }
        return result;
    }).join('\n');
}
