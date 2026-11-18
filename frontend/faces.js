/* Agent portraits: a person's face drawn as SVG, the same face every time for the same name. Skin tone, face shape,
   hair, eyes, brows, nose, mouth, facial hair, glasses and clothes all come from a seeded random sequence, with soft
   shading so it reads as a portrait rather than an icon. Self-contained: no photos, no external requests.
   agentAvatar(a, size) draws the agent's face on its colour (its icon becomes a small role badge on large sizes);
   anything without a name (placeholders, skills) keeps the plain icon tile. */
const Face = (() => {
  const SKIN = [["#f9dcc4", "#e9b896"], ["#f3cfb0", "#dca37c"], ["#eac09a", "#cf9469"], ["#d9a57a", "#b97c52"],
                ["#c68a5e", "#a1683f"], ["#a86f47", "#83502e"], ["#8a5634", "#673b20"], ["#64391f", "#4a2814"]];
  const HAIR = ["#1c1714", "#2e211a", "#4a3324", "#6b4a31", "#8f5a33", "#b0703c", "#d3a35f", "#e3c28a", "#8c8c8c", "#cfcfcf", "#a33b1f"];
  const EYES = ["#3b2a1e", "#5b3b23", "#2f5d7c", "#4f7a4a", "#6b6f78", "#7a5a2e"];
  const SHIRT = ["#1f2a44", "#2d3748", "#f4f4f2", "#4b5d3a", "#6b2737", "#1f6f78", "#c8952c", "#3c5a8a", "#55385f", "#2f2f2f"];
  const LIPS = ["#c9706a", "#b45f5a", "#a8564f", "#8f4a44", "#d27c7c"];

  function hash(s) { let h = 2166136261; for (const c of String(s)) { h ^= c.codePointAt(0); h = Math.imul(h, 16777619); } return h >>> 0; }
  function rng(seed) { let a = seed; return () => { a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
  const shade = (hex, f) => { const n = parseInt(hex.slice(1), 16), c = [n >> 16, (n >> 8) & 255, n & 255].map(v => Math.max(0, Math.min(255, Math.round(f < 0 ? v * (1 + f) : v + (255 - v) * f)))); return "#" + c.map(v => v.toString(16).padStart(2, "0")).join(""); };

  const HEADS = {
    oval: "M32 12.5C42 12.5 44 20.5 44 28c0 9-5 16-12 16s-12-7-12-16c0-7.5 2-15.5 12-15.5z",
    round: "M32 13c10.5 0 13 7.5 13 15 0 8.5-5.5 15.5-13 15.5S19 36.5 19 28c0-7.5 2.5-15 13-15z",
    square: "M32 12.5c10 0 12.5 8 12.5 15.5 0 7-2.5 12-6.5 14.5-2.5 1.5-4 2-6 2s-3.5-.5-6-2c-4-2.5-6.5-7.5-6.5-14.5 0-7.5 2.5-15.5 12.5-15.5z",
    narrow: "M32 12c9 0 11 8 11 16 0 9.5-4.5 17-11 17s-11-7.5-11-17c0-8 2-16 11-16z",
  };
  // hair: [behind the head, over the forehead]
  const HAIRS = {
    crop: ["", "M19.6 27C19 16 25 11 32 11s13 5 12.4 16c-1.4-6-4.4-8.6-9.4-9-5-.4-10 1-13 4-1 1.5-1.8 3-2.4 5z"],
    part: ["", "M19.5 28C18.5 15 26 10.5 33 10.8 41 11 46 17 44.5 28c-.5-6-2.5-9-6.5-10.5-5 2-12 3-16.5 4-1 2-1.6 4-2 6.5z"],
    buzz: ["", "M20.6 25c0-9 5.4-12.5 11.4-12.5S43.4 16 43.4 25c-3.4-6-19.4-6-22.8 0z"],
    long: ["M18 28C17 14 25 9 32 9s15 5 14 19l1.2 22c-5 2-9 0-10-3H27c-1 3-5 5-10 3z", "M19.5 28C19 15 25 10.5 32 10.5S45 15 44.5 28c-1.5-8-5.5-11.5-11.5-12-5 2-9 5-12 10z"],
    wavy: ["M18 28C16.5 14 25 9 32 9s15.5 5 14 19c1 4 2.5 8 1 12 1.5 4 0 8-2 10-4 1-7-1-8-3H27c-1 2-4 4-8 3-2-2-3.5-6-2-10-1.5-4 0-8 1-11z", "M19.5 28C19 15 25 10.5 32 10.5S45 15 44.5 28c-2-7-4-10-8-11.5-2 2.5-6 3.5-9 3.5-3 0-5.5 2-8 7.5z"],
    bob: ["M18.5 28C17.5 14 25 9.5 32 9.5S46.5 14 45.5 28v10c-3.5 1.5-5.5 0-6-2h-15c-.5 2-2.5 3.5-6 2z", "M20 25c0-10.5 6-14.5 12-14.5S44 14.5 44 25v-2.5c-6-2-18-2-24 0z"],
    bun: ["M32 3.5a5.6 5.6 0 1 1 0 11.2 5.6 5.6 0 0 1 0-11.2z", "M20 25.5c0-9.5 5.5-13.5 12-13.5s12 4 12 13.5c-2.5-5-6.5-7.5-12-7.5s-9.5 2.5-12 7.5z"],
    tail: ["M42 16c6 2 8 9 7 17-.5 5-2 10-4 14-1-6-2.5-11-4-15z", "M20 25.5c0-9.5 5.5-13.5 12-13.5s12 4 12 13.5c-2.5-5-6.5-7.5-12-7.5s-9.5 2.5-12 7.5z"],
    curly: ["curls", "curls-front"],
    bald: ["", "M19.8 30c-.2-3 .4-5.5 1.6-7.5l1.6 1c-.8 1.8-1.2 3.8-1 6.5zM44.2 30c.2-3-.4-5.5-1.6-7.5l-1.6 1c.8 1.8 1.2 3.8 1 6.5z"],
  };
  const STYLE_KEYS = Object.keys(HAIRS);
  const cache = new Map();

  function svg(seed, bg) {
    const key = seed + "|" + bg;
    if (cache.has(key)) return cache.get(key);
    const h = hash(seed), r = rng(h), pick = xs => xs[Math.floor(r() * xs.length)], id = "fc" + hash(key).toString(36);
    const [skin, skinD] = pick(SKIN), hair = pick(HAIR.slice(0, 8).concat(r() < .25 ? HAIR.slice(8) : [])), eye = pick(EYES);
    const head = pick(Object.keys(HEADS)), style = pick(STYLE_KEYS), shirt = pick(SHIRT), lip = pick(LIPS);
    const beard = r() < .28 ? pick(["stubble", "stubble", "beard", "mustache", "goatee"]) : null;
    const glasses = r() < .24 ? pick(["round", "rect"]) : null, earring = r() < .18, collar = pick(["crew", "vneck", "collar", "hoodie"]);
    const brow = pick(["arch", "flat", "soft"]), mouth = pick(["smile", "smile", "grin", "calm"]);
    const hairD = shade(hair, -.35), lidY = 27.2 + r() * .4, eyeGap = 4.7 + r() * .6, browT = .9 + r() * .5;
    const ex = [32 - eyeGap, 32 + eyeGap];

    let back = "", front = "";
    if (style === "curly") {
      const c = []; for (let i = 0; i < 15; i++) { const a = Math.PI * (1.02 + i * .068), R = 13.5 + (i % 2) * 1.2; c.push(`<circle cx="${(32 + Math.cos(a) * R).toFixed(1)}" cy="${(25 + Math.sin(a) * R * .95).toFixed(1)}" r="${(4.6 + (i % 3) * .5).toFixed(1)}"/>`); }
      back = `<g fill="url(#${id}h)">${c.join("")}<circle cx="32" cy="15" r="9"/></g>`;
      front = `<g fill="url(#${id}h)">${[22.5, 26.5, 31, 35.5, 40].map((x, i) => `<circle cx="${x}" cy="${17.6 + (i % 2) * 1.2}" r="3.3"/>`).join("")}</g>`;
    } else {
      const [b, f] = HAIRS[style];
      if (b) back = `<path d="${b}" fill="url(#${id}h)"/>`;
      if (f) front = `<path d="${f}" fill="url(#${id}h)"/>`;
    }
    const collars = {
      crew: `<path d="M26 49.6c2 3.2 10 3.2 12 0" fill="none" stroke="${shade(shirt, -.3)}" stroke-width="1.2"/>`,
      vneck: `<path d="M27 49 32 56.5 37 49z" fill="${skinD}"/><path d="M27 49 32 56.5 37 49" fill="none" stroke="${shade(shirt, -.3)}" stroke-width="1"/>`,
      collar: `<path d="M26.5 48.5 32 54l-3.5 3-4-6.5zM37.5 48.5 32 54l3.5 3 4-6.5z" fill="${shade(shirt, shirt === "#f4f4f2" ? -.08 : .55)}"/>`,
      hoodie: `<path d="M21 52c1-5 4-7.5 6-8l5 7 5-7c2 .5 5 3 6 8-3 3.5-7 5-11 5s-8-1.5-11-5z" fill="${shade(shirt, .12)}"/><path d="M30 55v5M34 55v5" stroke="${shade(shirt, .55)}" stroke-width=".8" stroke-linecap="round"/>`,
    };
    const brows = { arch: (x, s) => `M${x - 2.8 * s} ${24.9}q${2.6 * s} -2 ${5.2 * s} -.3`, flat: (x, s) => `M${x - 2.7 * s} ${24.6}l${5.1 * s} -.4`, soft: (x, s) => `M${x - 2.8 * s} ${24.9}q${2.8 * s} -1.2 ${5.4 * s} .1` };
    const mouths = {
      smile: `<path d="M28.4 37.4c2 2.3 5.2 2.3 7.2 0" fill="none" stroke="${lip}" stroke-width="1.15" stroke-linecap="round"/><path d="M29.8 38.9c1.4.7 3 .7 4.4 0" fill="none" stroke="${shade(lip, .25)}" stroke-width=".6" stroke-linecap="round" opacity=".7"/>`,
      grin: `<path d="M28.2 37.1c1.7 3.4 5.9 3.4 7.6 0z" fill="${shade(lip, -.45)}"/><path d="M28.8 37.3h6.4c-.3.9-.7 1.4-1.2 1.6h-4c-.5-.2-.9-.7-1.2-1.6z" fill="#fff"/><path d="M28.2 37.1c1.7 3.4 5.9 3.4 7.6 0" fill="none" stroke="${lip}" stroke-width=".9" stroke-linecap="round"/>`,
      calm: `<path d="M29 38.2c2 .7 4 .7 6 0" fill="none" stroke="${lip}" stroke-width="1.15" stroke-linecap="round"/>`,
    };
    const beards = {
      stubble: `<path d="M21.2 31c.3 8 4.8 13.5 10.8 13.5S42.5 39 42.8 31c-1.3 5.5-4.8 8.8-10.8 8.8S22.5 36.5 21.2 31z" fill="${hairD}" opacity=".28"/>`,
      beard: `<path d="M20.8 29.5c0 9.5 4.8 16.5 11.2 16.5s11.2-7 11.2-16.5c-1.3 5.5-4.2 8.2-7.2 8.6-1.6-1.6-6.4-1.6-8 0-3-.4-5.9-3.1-7.2-8.6z" fill="url(#${id}h)"/>`,
      mustache: `<path d="M27.6 36.3c1.8-1.6 6.2-1.6 8.8 0-1.4 1-3 .9-4.4.3-1.4.6-3 .7-4.4-.3z" fill="url(#${id}h)"/>`,
      goatee: `<path d="M27.8 36.3c1.8-1.6 6.6-1.6 8.4 0-1.4.9-3 .8-4.2.3-1.2.5-2.8.6-4.2-.3zM29.5 40.2c1.4.9 3.6.9 5 0 .2 2.2-1 4-2.5 4s-2.7-1.8-2.5-4z" fill="url(#${id}h)"/>`,
    };
    const eyeG = x => `<g><ellipse cx="${x}" cy="${lidY + .6}" rx="2.55" ry="1.65" fill="#fbfaf8"/><circle cx="${x + .15}" cy="${lidY + .65}" r="1.35" fill="${eye}"/><circle cx="${x + .15}" cy="${lidY + .65}" r=".68" fill="#111"/><circle cx="${x + .6}" cy="${lidY + .2}" r=".38" fill="#fff"/>
      <path d="M${x - 2.7} ${lidY + .7}q2.7-2.6 5.4 0" fill="none" stroke="${shade(skinD, -.45)}" stroke-width=".75" stroke-linecap="round"/></g>`;
    const glassesG = glasses === "round"
      ? `<g fill="rgb(255 255 255 / .12)" stroke="#2b2b2b" stroke-width=".8"><circle cx="${ex[0]}" cy="${lidY + .6}" r="3.6"/><circle cx="${ex[1]}" cy="${lidY + .6}" r="3.6"/></g><path d="M${ex[0] + 3.6} ${lidY + .2}q${eyeGap - 3.6} -1 ${2 * (eyeGap - 3.6)} 0" fill="none" stroke="#2b2b2b" stroke-width=".8"/>`
      : glasses === "rect" ? `<g fill="rgb(255 255 255 / .12)" stroke="#2b2b2b" stroke-width=".85"><rect x="${ex[0] - 3.8}" y="${lidY - 2}" width="7.6" height="5.2" rx="1.4"/><rect x="${ex[1] - 3.8}" y="${lidY - 2}" width="7.6" height="5.2" rx="1.4"/></g><path d="M${ex[0] + 3.8} ${lidY}h${2 * eyeGap - 7.6}" stroke="#2b2b2b" stroke-width=".85"/>` : "";

    const out = `<svg class="face" viewBox="9.5 5 45 45" aria-hidden="true" focusable="false"><defs>
      <radialGradient id="${id}s" cx="42%" cy="35%" r="70%"><stop offset="0" stop-color="${shade(skin, .12)}"/><stop offset=".65" stop-color="${skin}"/><stop offset="1" stop-color="${skinD}"/></radialGradient>
      <linearGradient id="${id}h" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${shade(hair, .18)}"/><stop offset="1" stop-color="${hairD}"/></linearGradient>
      <linearGradient id="${id}c" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${shade(shirt, .1)}"/><stop offset="1" stop-color="${shade(shirt, -.25)}"/></linearGradient></defs>
      ${back}
      <path d="M8 64c1-10 10-14.5 19-15.3h10c9 .8 18 5.3 19 15.3z" fill="url(#${id}c)"/>
      <path d="M27 38h10v11.5c-2 2.5-8 2.5-10 0z" fill="${skinD}"/><path d="M27 44c3 2 7 2 10 0v-3H27z" fill="${shade(skinD, -.18)}" opacity=".6"/>
      ${collars[collar]}
      <ellipse cx="20.2" cy="29.5" rx="2.5" ry="3.7" fill="${skinD}"/><ellipse cx="43.8" cy="29.5" rx="2.5" ry="3.7" fill="${skinD}"/>
      ${earring ? `<circle cx="20.4" cy="33.6" r=".9" fill="#e7c26b"/><circle cx="43.6" cy="33.6" r=".9" fill="#e7c26b"/>` : ""}
      <path d="${HEADS[head]}" fill="url(#${id}s)"/>
      <circle cx="25.2" cy="33.2" r="2.7" fill="#e8807a" opacity=".16"/><circle cx="38.8" cy="33.2" r="2.7" fill="#e8807a" opacity=".16"/>
      ${beard === "stubble" || beard === "beard" ? beards[beard] : ""}
      ${front}
      <path d="${brows[brow](ex[0] + .2, 1)}" fill="none" stroke="${hairD}" stroke-width="${browT}" stroke-linecap="round"/>
      <path d="${brows[brow](ex[1] - .2, -1)}" fill="none" stroke="${hairD}" stroke-width="${browT}" stroke-linecap="round"/>
      ${eyeG(ex[0])}${eyeG(ex[1])}
      <path d="M32.2 29.6c-.5 2.4-1.3 3.7-.9 4.4.5.6 1.6.7 2.2.2" fill="none" stroke="${shade(skinD, -.3)}" stroke-width=".75" stroke-linecap="round" opacity=".7"/>
      ${beard === "mustache" || beard === "goatee" ? beards[beard] : ""}
      ${mouths[mouth]}
      ${glassesG}
    </svg>`;
    cache.set(key, out);
    return out;
  }
  // fresh seeds for the editor's face picker
  const seeds = n => Array.from(crypto.getRandomValues(new Uint32Array(n)), x => x.toString(36));
  return { svg, seeds };
})();

// the agent's face on its colour (the face it was given in the editor, else one drawn from its name);
// things without a name keep the icon tile
function agentAvatar(a, cls = "") {
  if (!a?.name) return `<span class="av c-${esc(a?.color || "blue")} ${cls}" aria-hidden="true">${icon(a?.icon || "bot")}</span>`;
  return `<span class="av face-av c-${esc(a.color || "blue")} ${cls}" aria-hidden="true">${Face.svg(a.face ? "pick:" + a.face : a.name.trim().toLowerCase(), a.color || "blue")}${a.icon && /\b(lg|xl)\b/.test(cls) ? `<span class="av-badge">${icon(a.icon)}</span>` : ""}</span>`;
}
