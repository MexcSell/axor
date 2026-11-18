/* QR: a small QR code encoder for the wallet's Receive sheet. Byte mode, error correction level L, versions 1 to 5
   (up to 106 bytes: an SS58 address is 48), the mask with the lowest penalty. QR.svg(text) returns an SVG. */
const QR = (() => {
  const DATA = [0, 19, 34, 55, 80, 108], EC = [0, 7, 10, 15, 20, 26];  // codewords per version at level L (one block each)
  // GF(256) arithmetic for the Reed-Solomon error correction
  const EXP = new Array(512), LOG = new Array(256);
  for (let i = 0, x = 1; i < 255; i++) { EXP[i] = x; LOG[x] = i; x = (x << 1) ^ (x & 128 ? 0x11d : 0); }
  for (let i = 255; i < 512; i++) EXP[i] = EXP[i - 255];
  const mul = (a, b) => a && b ? EXP[LOG[a] + LOG[b]] : 0;
  function ecc(data, n) {
    let gen = [1];
    for (let i = 0; i < n; i++) { const next = new Array(gen.length + 1).fill(0); gen.forEach((g, j) => { next[j] ^= g; next[j + 1] ^= mul(g, EXP[i]); }); gen = next; }
    const out = [...data, ...new Array(n).fill(0)];
    for (let i = 0; i < data.length; i++) { const f = out[i]; if (f) for (let j = 1; j < gen.length; j++) out[i + j] ^= mul(gen[j], f); }
    return out.slice(data.length);
  }
  function codewords(bytes, v) {
    const bits = [], push = (val, len) => { for (let i = len - 1; i >= 0; i--) bits.push((val >> i) & 1); };
    push(4, 4); push(bytes.length, 8); bytes.forEach(b => push(b, 8));
    const cap = DATA[v] * 8;
    push(0, Math.min(4, cap - bits.length));
    while (bits.length % 8) bits.push(0);
    const data = []; for (let i = 0; i < bits.length; i += 8) data.push(parseInt(bits.slice(i, i + 8).join(""), 2));
    for (let p = 0; data.length < DATA[v]; p ^= 1) data.push(p ? 0x11 : 0xec);
    return [...data, ...ecc(data, EC[v])];
  }
  function matrix(text, forceMask) {
    const bytes = [...new TextEncoder().encode(text)];
    const v = [1, 2, 3, 4, 5].find(x => bytes.length + 2 <= DATA[x]);
    if (!v) throw new Error("Too long for a QR code here");
    const n = 17 + 4 * v, m = Array.from({ length: n }, () => new Array(n).fill(null)), fn = Array.from({ length: n }, () => new Array(n).fill(false));
    const set = (r, c, val) => { m[r][c] = val; fn[r][c] = true; };
    const finder = (r0, c0) => { for (let r = -1; r <= 7; r++) for (let c = -1; c <= 7; c++) { const rr = r0 + r, cc = c0 + c; if (rr < 0 || cc < 0 || rr >= n || cc >= n) continue;
      set(rr, cc, r >= 0 && r <= 6 && c >= 0 && c <= 6 && (r === 0 || r === 6 || c === 0 || c === 6 || (r >= 2 && r <= 4 && c >= 2 && c <= 4))); } };
    finder(0, 0); finder(0, n - 7); finder(n - 7, 0);
    for (let i = 8; i < n - 8; i++) { set(6, i, i % 2 === 0); set(i, 6, i % 2 === 0); }
    if (v >= 2) { const a = n - 7; for (let r = -2; r <= 2; r++) for (let c = -2; c <= 2; c++) set(a + r, a + c, Math.max(Math.abs(r), Math.abs(c)) !== 1); }
    set(n - 8, 8, true);  // the dark module
    for (let i = 0; i < 9; i++) { if (!fn[8][i]) set(8, i, false); if (!fn[i][8]) set(i, 8, false); }
    for (let i = 0; i < 8; i++) { if (!fn[8][n - 1 - i]) set(8, n - 1 - i, false); if (!fn[n - 1 - i][8]) set(n - 1 - i, 8, false); }
    // data, in the zigzag order, skipping the vertical timing column
    const bits = codewords(bytes, v).flatMap(b => [7, 6, 5, 4, 3, 2, 1, 0].map(i => (b >> i) & 1));
    let k = 0;
    for (let right = n - 1, up = true; right > 0; right -= 2, up = !up) {
      if (right === 6) right = 5;
      for (let i = 0; i < n; i++) { const r = up ? n - 1 - i : i; for (const c of [right, right - 1]) if (!fn[r][c]) m[r][c] = !!bits[k++]; }
    }
    const MASKS = [(r, c) => (r + c) % 2 === 0, r => r % 2 === 0, (r, c) => c % 3 === 0, (r, c) => (r + c) % 3 === 0,
      (r, c) => (Math.floor(r / 2) + Math.floor(c / 3)) % 2 === 0, (r, c) => (r * c) % 2 + (r * c) % 3 === 0,
      (r, c) => ((r * c) % 2 + (r * c) % 3) % 2 === 0, (r, c) => ((r + c) % 2 + (r * c) % 3) % 2 === 0];
    const withMask = mk => {
      const g = m.map((row, r) => row.map((val, c) => fn[r][c] ? val : val !== MASKS[mk](r, c)));
      let f = (1 << 3) | mk, rem = f;  // level L = 01
      for (let i = 0; i < 10; i++) rem = (rem << 1) ^ (rem >> 9 ? 0x537 : 0);
      const bitsF = ((f << 10) | rem) ^ 0x5412, bit = i => ((bitsF >> i) & 1) === 1;
      for (let i = 0; i <= 5; i++) g[i][8] = bit(i);  // g[row][column]
      g[7][8] = bit(6); g[8][8] = bit(7); g[8][7] = bit(8);
      for (let i = 9; i < 15; i++) g[8][14 - i] = bit(i);
      for (let i = 0; i < 8; i++) g[8][n - 1 - i] = bit(i);
      for (let i = 8; i < 15; i++) g[n - 15 + i][8] = bit(i);
      return g;
    };
    const penalty = g => {
      let p = 0;
      for (const line of [...g, ...g[0].map((_, c) => g.map(row => row[c]))]) {
        for (let i = 0, run = 1; i < n; i++) { if (i && line[i] === line[i - 1]) { run++; if (run === 5) p += 3; else if (run > 5) p++; } else run = 1; }
        const s = line.map(x => x ? 1 : 0).join("");
        for (const pat of ["10111010000", "00001011101"]) for (let i = s.indexOf(pat); i >= 0; i = s.indexOf(pat, i + 1)) p += 40;
      }
      for (let r = 0; r < n - 1; r++) for (let c = 0; c < n - 1; c++) { const x = g[r][c]; if (x === g[r][c + 1] && x === g[r + 1][c] && x === g[r + 1][c + 1]) p += 3; }
      const dark = g.flat().filter(Boolean).length;
      return p + Math.floor(Math.abs(dark * 20 - n * n * 10) / (n * n)) * 10;
    };
    if (forceMask != null) return withMask(forceMask);
    let best = null, bestP = Infinity;
    for (let mk = 0; mk < 8; mk++) { const g = withMask(mk), p = penalty(g); if (p < bestP) { best = g; bestP = p; } }
    return best;
  }
  function svg(text) {
    const g = matrix(text), n = g.length, q = 2;
    let d = "";
    g.forEach((row, r) => row.forEach((on, c) => { if (on) d += `M${c + q} ${r + q}h1v1h-1z`; }));
    return `<svg viewBox="0 0 ${n + 2 * q} ${n + 2 * q}" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges"><path fill="#111" d="${d}"/></svg>`;
  }
  return { svg, matrix };
})();
