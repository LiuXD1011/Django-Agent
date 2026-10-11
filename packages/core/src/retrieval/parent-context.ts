import type { JsonObject } from '../contracts.js';
import { type ChunkRecord, bounded } from './internal.js';
import type { SearchHit, MatchedRange } from './types.js';

type Segment = { start: number; end: number; sourceStart: number; sourceEnd: number; child?: string };
const points = (text: string) => Array.from(text);
function valid(child: ChunkRecord, parent: ChunkRecord): boolean {
  const end = parent.end_at > parent.start_at ? parent.end_at : parent.start_at + points(parent.content).length;
  return child.start_at >= parent.start_at && child.end_at > child.start_at && child.end_at <= end && child.end_at - parent.start_at <= points(parent.content).length;
}
function window(total: number, cap: number, spans: Array<[number,number]>): [number,number] {
  if (total <= cap) return [0,total];
  if (cap === 0) return [0,0];
  const useful = spans.filter(([start,end]) => end > start);
  if (!useful.length) return [0,cap];
  const low = Math.min(...useful.map(span => span[0])), high = Math.max(...useful.map(span => span[1]));
  const [first,last] = high - low <= cap ? [low,high] : useful[0]!;
  const start = Math.min(Math.max(0, first - Math.floor(Math.max(0,cap-(last-first))/2)), total-cap);
  return [start,start+cap];
}
function render(parent: ChunkRecord, siblings: ChunkRecord[]): { text: string; segments: Segment[]; applied: string[] } {
  const raw = points(parent.content); const edits = siblings.filter(child => valid(child,parent) && raw.slice(child.start_at-parent.start_at,child.end_at-parent.start_at).join('') !== child.content);
  edits.sort((a,b) => b.updated_at.localeCompare(a.updated_at) || a.chunk_index-b.chunk_index || a.start_at-b.start_at || a.end_at-b.end_at || a.id.localeCompare(b.id));
  const accepted: ChunkRecord[] = [];
  for (const edit of edits) if (!accepted.some(other => edit.start_at < other.end_at && other.start_at < edit.end_at)) accepted.push(edit);
  accepted.sort((a,b) => a.start_at-b.start_at || a.end_at-b.end_at || a.chunk_index-b.chunk_index || a.id.localeCompare(b.id));
  const parts: string[] = [], segments: Segment[] = []; let sourceCursor = 0, renderedCursor = 0;
  const append = (text: string, sourceStart: number, sourceEnd: number, child?: string) => {
    if (!text) return; const length = points(text).length; parts.push(text);
    segments.push({ start: renderedCursor, end: renderedCursor+length, sourceStart: sourceStart+parent.start_at, sourceEnd: sourceEnd+parent.start_at, child }); renderedCursor += length;
  };
  for (const edit of accepted) {
    const start = edit.start_at-parent.start_at,end = edit.end_at-parent.start_at;
    if (start > sourceCursor) append(raw.slice(sourceCursor,start).join(''),sourceCursor,start);
    append(edit.content,start,end,edit.id); sourceCursor = end;
  }
  if (sourceCursor < raw.length) append(raw.slice(sourceCursor).join(''),sourceCursor,raw.length);
  return { text: parts.join(''), segments, applied: accepted.map(edit => edit.id) };
}
function span(child: ChunkRecord, segments: Segment[]): [number,number] {
  const direct = segments.filter(segment => segment.child === child.id);
  const ranges: Array<[number,number]> = direct.length ? direct.map(segment => [segment.start,segment.end]) : segments.flatMap(segment => {
    const start = Math.max(segment.sourceStart,child.start_at),end = Math.min(segment.sourceEnd,child.end_at);
    if (end <= start) return [];
    return [segment.child === undefined ? [segment.start+start-segment.sourceStart,segment.start+end-segment.sourceStart] as [number,number] : [segment.start,segment.end] as [number,number]];
  });
  return ranges.length ? [Math.min(...ranges.map(range=>range[0])),Math.max(...ranges.map(range=>range[1]))] : [0,0];
}
function matched(child: ChunkRecord, [start,end]: [number,number], low: number, high: number): MatchedRange {
  const visibleStart = Math.max(start,low),visibleEnd = Math.min(end,high),visible = visibleEnd > visibleStart;
  return { child_id: child.id, start_at: child.start_at, end_at: child.end_at, rendered_start_at: start, rendered_end_at: end,
    context_start_at: visible ? visibleStart-low : null, context_end_at: visible ? visibleEnd-low : null, visible,
    clipped: !visible || visibleStart > start || visibleEnd < end };
}
function capped(item: SearchHit, child: ChunkRecord, cap: number, reason?: string): SearchHit {
  const content = points(item.content); const low = 0,high = Math.min(cap,content.length);
  const exactSourceLength = child.end_at-child.start_at===content.length;
  const row: SearchHit = { ...item, content: content.slice(low,high).join(''), context_window: {
    parent_start_at: child.start_at, parent_end_at: child.end_at, source_start_at: child.start_at+(exactSourceLength?low:0),
    source_end_at: exactSourceLength?child.start_at+high:child.end_at, rendered_start_at: low, rendered_end_at: high, max_context_chars: cap,
    clipped: high < content.length, clip_reason: high < content.length ? 'max_context_chars' : '' } };
  if (reason) { row.context_fallback = reason; row.matched_child_ids = [child.id]; row.matched_ranges = [matched(child,[0,content.length],low,high)]; delete row.parent_chunk_id; }
  return row;
}
function recap(item: SearchHit, cap: number): SearchHit {
  const chars=points(item.content), spans:Array<[number,number]>=(item.matched_ranges??[])
    .filter(range=>range.context_start_at!==null && range.context_end_at!==null)
    .map(range=>[range.context_start_at!,range.context_end_at!]);
  const [low,high]=window(chars.length,cap,spans),old=item.context_window??{};
  const base=Number(old.rendered_start_at??0),previousEnd=Number(old.rendered_end_at??base);
  const clipped=Boolean(old.clipped)||low>0||high<chars.length;
  const contextWindow:JsonObject={...old,rendered_start_at:base+low,rendered_end_at:base+high,max_context_chars:cap,
    clipped,clip_reason:clipped?'max_context_chars':''};
  if(typeof old.source_start_at==='number' && typeof old.source_end_at==='number' && old.source_end_at-old.source_start_at===previousEnd-base) {
    contextWindow.source_start_at=old.source_start_at+low;contextWindow.source_end_at=old.source_start_at+high;
  }
  return {...item,content:chars.slice(low,high).join(''),context_window:contextWindow,matched_ranges:item.matched_ranges?.map(range=>{
    if(range.context_start_at===null || range.context_end_at===null) return {...range};
    const start=Math.max(range.context_start_at,low),end=Math.min(range.context_end_at,high),visible=end>start;
    return {...range,context_start_at:visible?start-low:null,context_end_at:visible?end-low:null,visible,
      clipped:range.clipped||!visible||start>range.context_start_at||end<range.context_end_at};
  })};
}
/** Text parents are intentionally disabled. Children and all overlays remain active and in the exact document scope. */
export function resolveParentContext(children: ChunkRecord[], all: ChunkRecord[], hits: SearchHit[], cap: number): SearchHit[] {
  bounded(cap,4096,0,1000000);
  const childMap = new Map(children.map(row=>[row.id,row])), parentMap = new Map(all.map(row=>[row.id,row]));
  const ordered = hits.map((item,index)=>({item,index})).sort((a,b)=>(a.item.final_rank??a.index+1)-(b.item.final_rank??b.index+1) || a.index-b.index);
  const groups = new Map<string,Array<{item:SearchHit;child:ChunkRecord;index:number}>>();
  const standalone: Array<{row:SearchHit;index:number}> = []; const seen = new Set<string>();
  for (const {item,index} of ordered) {
    const child = childMap.get(item.chunk_id);
    if (!child || seen.has(child.id) || item.knowledge_id !== child.knowledge_id || item.knowledge_base_id !== child.knowledge_base_id || item.chunk_type !== child.chunk_type) continue;
    seen.add(child.id);
    if (child.chunk_type !== 'text' || !child.context_parent_id) { standalone.push({row:capped(item,child,cap),index}); continue; }
    const parent = parentMap.get(child.context_parent_id);
    const reason = !parent ? 'missing_parent' : parent.chunk_type !== 'parent_text' ? 'invalid_parent_type'
      : parent.knowledge_id !== child.knowledge_id || parent.knowledge_base_id !== child.knowledge_base_id ? 'parent_scope_mismatch'
      : !valid(child,parent) ? 'invalid_source_range' : '';
    if (reason || !parent) { standalone.push({row:capped(item,child,cap,reason),index}); continue; }
    if(item.parent_chunk_id===parent.id && item.matched_child_ids?.length && item.matched_child_ids.every(id=>{
      const matchedChild=childMap.get(id);return matchedChild?.chunk_type==='text' && matchedChild.context_parent_id===parent.id &&
        matchedChild.knowledge_id===parent.knowledge_id && matchedChild.knowledge_base_id===parent.knowledge_base_id && valid(matchedChild,parent);
    })) {
      for(const id of item.matched_child_ids) seen.add(id);
      standalone.push({row:recap(item,cap),index});continue;
    }
    const group = groups.get(parent.id)??[]; group.push({item,child,index}); groups.set(parent.id,group);
  }
  for (const [parentId,group] of groups) {
    const parent = parentMap.get(parentId)!, representative = group[0]!;
    const siblings = children.filter(row=>row.chunk_type==='text' && row.context_parent_id===parentId && row.knowledge_id===parent.knowledge_id && row.knowledge_base_id===parent.knowledge_base_id);
    const rendered = render(parent,siblings),spans = group.map(record=>span(record.child,rendered.segments));
    const chars = points(rendered.text),[low,high] = window(chars.length,cap,spans);
    const visibleSegments = rendered.segments.filter(segment=>segment.start<high && segment.end>low);
    const sourceRanges = visibleSegments.map(segment=>segment.child===undefined
      ? [segment.sourceStart+Math.max(low,segment.start)-segment.start,segment.sourceStart+Math.min(high,segment.end)-segment.start]
      : [segment.sourceStart,segment.sourceEnd]);
    const row: SearchHit = { ...representative.item, content: chars.slice(low,high).join(''), parent_chunk_id: parent.id,
      matched_child_ids: group.map(record=>record.child.id), matched_ranges: group.map((record,index)=>matched(record.child,spans[index]!,low,high)),
      applied_edit_child_ids: rendered.applied, selected_strategy: String(representative.child.metadata.selected_strategy??parent.metadata.selected_strategy??
        (representative.child.knowledge_metadata.chunking_diagnostics as JsonObject|undefined)?.selected_strategy??''),
      matched_child_provenance: group.map(record=>({child_id:record.child.id,chunk_id:record.child.id,id:record.child.id,input_rank:record.index+1,
        final_rank:record.item.final_rank??null,score:record.item.score,rrf_score:record.item.rrf_score,rerank_score:record.item.rerank_score,
        keyword_rank:record.item.keyword_rank,vector_rank:record.item.vector_rank,match_sources:record.item.match_sources})),
      context_window: { parent_start_at: parent.start_at,parent_end_at:parent.end_at,source_start_at:sourceRanges.length?Math.min(...sourceRanges.map(range=>range[0]!)):parent.start_at,
        source_end_at:sourceRanges.length?Math.max(...sourceRanges.map(range=>range[1]!)):parent.start_at,rendered_start_at:low,rendered_end_at:high,
        max_context_chars:cap,clipped:low>0||high<chars.length,clip_reason:low>0||high<chars.length?'max_context_chars':'' } };
    standalone.push({row,index:representative.index});
  }
  return standalone.sort((a,b)=>(a.row.final_rank??a.index+1)-(b.row.final_rank??b.index+1)||a.index-b.index).map(record=>record.row);
}
