/** FTS5 trigram terms: Chinese questions share codepoint windows with answer text. */
export function keywordTerms(query: string): string[] {
  return (query.match(/[\p{L}\p{N}_]+/gu) ?? []).flatMap(word => {
    const points = Array.from(word);
    if (points.length < 3) return [];
    if (!/\p{Script=Han}/u.test(word)) return [word];
    return [...new Set(points.slice(0, -2).map((_, index) => points.slice(index, index + 3).join('')))];
  });
}
