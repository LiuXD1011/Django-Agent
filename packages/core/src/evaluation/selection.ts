// MT19937 compatibility for historical CPython integer-seed shuffle/sample.
// Original generator: Copyright (C) 1997-2002 Makoto Matsumoto and Takuji Nishimura.
// See LICENSE-MT19937.txt. CPython reference: Modules/_randommodule.c and Lib/random.py.
import { fail } from './common.js';
class IntegerRandom {
  private readonly state = new Uint32Array(624);
  private offset = 624;
  constructor(seed: number) {
    if (!Number.isSafeInteger(seed)) return fail(400, 'invalid_evaluation_input', 'Selection seed must be a safe integer');
    let value = BigInt(seed); if (value < 0n) value = -value;
    const key: number[] = []; do { key.push(Number(value & 0xffffffffn)); value >>= 32n; } while (value);
    const state = this.state; state[0] = 19650218;
    for (let index = 1; index < 624; index++) state[index] = (Math.imul(1812433253, state[index - 1]! ^ (state[index - 1]! >>> 30)) + index) >>> 0;
    let index = 1, keyIndex = 0;
    for (let count = Math.max(624, key.length); count > 0; count--) {
      state[index] = ((state[index]! ^ Math.imul(state[index - 1]! ^ (state[index - 1]! >>> 30), 1664525)) + key[keyIndex]! + keyIndex) >>> 0;
      if (++index >= 624) { state[0] = state[623]!; index = 1; } if (++keyIndex >= key.length) keyIndex = 0;
    }
    for (let count = 623; count > 0; count--) {
      state[index] = ((state[index]! ^ Math.imul(state[index - 1]! ^ (state[index - 1]! >>> 30), 1566083941)) - index) >>> 0;
      if (++index >= 624) { state[0] = state[623]!; index = 1; }
    }
    state[0] = 0x80000000;
  }
  private word(): number {
    const state = this.state;
    if (this.offset >= 624) {
      for (let index = 0; index < 624; index++) { const mixed = (state[index]! & 0x80000000) | (state[(index + 1) % 624]! & 0x7fffffff); state[index] = (state[(index + 397) % 624]! ^ (mixed >>> 1) ^ (mixed & 1 ? 0x9908b0df : 0)) >>> 0; }
      this.offset = 0;
    }
    let value = state[this.offset++]!; value ^= value >>> 11; value ^= (value << 7) & 0x9d2c5680; value ^= (value << 15) & 0xefc60000; value ^= value >>> 18; return value >>> 0;
  }
  below(limit: number): number { const bits = 32 - Math.clz32(limit); let value: number; do { value = this.word() >>> (32 - bits); } while (value >= limit); return value; }
}
export function shuffled<T>(values: readonly T[], seed: number): T[] { const result = [...values], random = new IntegerRandom(seed); for (let index = result.length - 1; index > 0; index--) { const selected = random.below(index + 1); [result[index], result[selected]] = [result[selected]!, result[index]!]; } return result; }
export function sampledIndices(length: number, size: number, seed = 20260819): number[] {
  if (!Number.isSafeInteger(length) || !Number.isSafeInteger(size) || length < 0 || length > 100000 || size < 0 || size > length) return fail(400, 'invalid_evaluation_input', 'Invalid review sample size');
  const random = new IntegerRandom(seed), output: number[] = []; let threshold = 21; if (size > 5) threshold += 4 ** Math.ceil(Math.log(size * 3) / Math.log(4));
  if (length <= threshold) { const pool = Array.from({ length }, (_, index) => index); for (let index = 0; index < size; index++) { const selected = random.below(length - index); output.push(pool[selected]!); pool[selected] = pool[length - index - 1]!; } }
  else { const selected = new Set<number>(); for (let index = 0; index < size; index++) { let value: number; do { value = random.below(length); } while (selected.has(value)); selected.add(value); output.push(value); } }
  return output;
}
