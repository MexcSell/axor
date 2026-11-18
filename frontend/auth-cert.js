// "Your account is approved" window (#f-cert): "Download Certificate" + how to install AXoR's root certificate.
// Same file as System → Cluster → Domain → "Download AXoR's root certificate" (public GET /api/platform/ca.crt,
// 404 until the platform has made its certificate authority). auth.js calls AuthCert.load() when an admin approves
// a sign-up: false (no CA yet) → it skips the window.
const AuthCert = (() => {
  const PATH = "/api/platform/ca.crt";
  const $ = s => document.querySelector(s);
  const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function guessOS() {
    const ua = navigator.userAgent || "";
    if (/iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1)) return "ios";
    if (/Android/.test(ua)) return "android";
    if (/Windows/.test(ua)) return "windows";
    if (/Macintosh|Mac OS X/.test(ua)) return "mac";
    return "linux";
  }

  async function fingerprint(pem) {
    if (!window.crypto?.subtle) return "";  // only in a secure context (HTTPS or localhost)
    const b64 = pem.replace(/-----[^-]+-----/g, "").replace(/\s+/g, "");
    const der = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
    const h = new Uint8Array(await crypto.subtle.digest("SHA-256", der));
    return [...h].map(b => b.toString(16).padStart(2, "0").toUpperCase()).join(":");  // same format as openssl -fingerprint
  }

  function cmd(label, text) {
    return `<div class="acert-cmd"><div class="acert-cmd-h"><span>${label}</span><button type="button" class="link" data-acert-copy>Copy</button></div><code>${esc(text)}</code></div>`;
  }

  function guides(url) {
    return {
      windows: {
        label: "Windows",
        steps: [
          "Click <b>Download Certificate</b> and open <code>axor-ca.crt</code>.",
          "Choose <b>Install Certificate…</b> → <b>Current User</b> → Next.",
          "Pick <b>Place all certificates in the following store</b> → Browse → <b>Trusted Root Certification Authorities</b>.",
          "Next → Finish, then <b>Yes</b> on the security warning.",
          "Restart your browser. Chrome and Edge use this store; Firefox 120+ does too.",
        ],
        fast: [cmd("PowerShell, no admin needed (answer Yes on the prompt)",
          `curl.exe -kfsSLo "$env:TEMP\\axor-ca.crt" ${url}; certutil -user -addstore Root "$env:TEMP\\axor-ca.crt"`)],
      },
      mac: {
        label: "macOS",
        steps: [
          "Click <b>Download Certificate</b> and double-click <code>axor-ca.crt</code>: Keychain Access adds it.",
          "In Keychain Access, open the new AXoR certificate and expand <b>Trust</b>.",
          "Set <b>When using this certificate</b> to <b>Always Trust</b>, close the window and enter your password.",
          "Restart your browser. Safari and Chrome use the keychain; Firefox 120+ does too.",
        ],
        fast: [cmd("Terminal (asks for your password)",
          `curl -kfsSLo /tmp/axor-ca.crt ${url} && sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain /tmp/axor-ca.crt`)],
      },
      ios: {
        label: "iPhone / iPad",
        steps: [
          "Open this page in <b>Safari</b> and tap <b>Download Certificate</b>, then <b>Allow</b>. If it lands in the Files app instead, open it there: that starts the same install.",
          "Open <b>Settings</b> → <b>Profile Downloaded</b> → <b>Install</b> (enter your passcode).",
          "Go to <b>Settings → General → About → Certificate Trust Settings</b>.",
          "Turn on full trust for the AXoR certificate. Without this step Safari still shows warnings.",
        ],
        fast: [],
      },
      android: {
        label: "Android",
        steps: [
          "Tap <b>Download Certificate</b> (it goes to Downloads).",
          "Open <b>Settings → Security &amp; privacy → More security settings → Encryption &amp; credentials</b>. Search Settings for “certificate” if your phone names it differently.",
          "Tap <b>Install a certificate → CA certificate → Install anyway</b> and choose <code>axor-ca.crt</code>.",
          "Chrome trusts it right away. Some other apps ignore certificates you add yourself.",
        ],
        fast: [],
      },
      linux: {
        label: "Linux",
        steps: [
          "Run the command for your distribution below. It saves the certificate and adds it to the system's trusted list.",
          "Chrome and Chromium keep their own list (NSS): run the third command too. You need the <code>libnss3-tools</code> package.",
          "Firefox: Settings → Privacy &amp; Security → Certificates → <b>View Certificates</b> → Authorities → <b>Import</b>, then tick <b>Trust this CA to identify websites</b>.",
        ],
        fast: [
          cmd("Debian / Ubuntu", `sudo curl -kfsSLo /usr/local/share/ca-certificates/axor-ca.crt ${url} && sudo update-ca-certificates`),
          cmd("Fedora / RHEL", `sudo curl -kfsSLo /etc/pki/ca-trust/source/anchors/axor-ca.crt ${url} && sudo update-ca-trust`),
          cmd("Chrome / Chromium", `curl -kfsSLo /tmp/axor-ca.crt ${url} && certutil -d sql:$HOME/.pki/nssdb -A -t "C,," -n "AXoR root" -i /tmp/axor-ca.crt`),
        ],
      },
    };
  }

  function render(url, fp) {
    const G = guides(url), body = $("#acert-body");
    let os = guessOS();
    const verify = fp ? `<div class="acert-fp"><span>SHA-256 fingerprint</span><code>${fp}</code>
        <small>Before you trust the file, check that it matches the fingerprint your administrator gave you.</small>
        ${cmd("Show a downloaded file's fingerprint (macOS / Linux)", "openssl x509 -noout -fingerprint -sha256 -in axor-ca.crt")}</div>` : "";
    const draw = () => {
      const g = G[os];
      body.innerHTML = `
        <p class="acert-why">Install it once on each device you use. It only vouches for AXoR's own addresses.</p>
        <div class="seg full acert-os" role="tablist">${Object.entries(G).map(([k, v]) =>
          `<button type="button" role="tab" data-acert-os="${k}" aria-pressed="${k === os}" aria-selected="${k === os}">${v.label}</button>`).join("")}</div>
        <ol class="acert-steps">${g.steps.map(s => `<li>${s}</li>`).join("")}</ol>
        <div class="acert-fast"><b>${icon("terminal")}Faster: install from the link</b>
          ${g.fast.length ? g.fast.join("") : `<p>Send this link to the phone and open it there (in Safari on an iPhone). That replaces the download step.</p>`}
          <div class="acert-link"><code>${esc(url)}</code><button type="button" class="btn sm" data-acert-copy="${esc(url)}">${icon("copy")}Copy link</button></div>
          ${g.fast.length ? `<small>The commands use <code>-k</code> because your device can't check the connection until the certificate is installed.${fp ? " Check the fingerprint below to make sure you got the real file." : ""}</small>` : ""}
        </div>${verify}`;
    };
    draw();
    if (body.dataset.wired) return;  // load() may run again (reload, second approval in one tab)
    body.dataset.wired = "1";
    body.addEventListener("click", e => {
      const t = e.target.closest("[data-acert-os]");
      if (t) { os = t.dataset.acertOs; return draw(); }
      const c = e.target.closest("[data-acert-copy]");
      if (!c) return;
      const text = c.dataset.acertCopy || c.closest(".acert-cmd")?.querySelector("code")?.textContent || "";
      const done = () => { const old = c.innerHTML; c.textContent = "Copied"; setTimeout(() => { c.innerHTML = old; }, 1400); };
      if (navigator.clipboard?.writeText) navigator.clipboard.writeText(text).then(done, () => {});
    });
  }

  // Fills #f-cert. Resolves true when there is a certificate to offer, false otherwise (never throws).
  async function load() {
    const box = $("#acert"); if (!box) return false;
    let pem;
    try {
      const r = await fetch(PATH, { credentials: "same-origin", cache: "no-store" });
      if (!r.ok) return false;  // no certificate authority yet: nothing to offer
      pem = await r.text();
      if (!pem.includes("BEGIN CERTIFICATE")) return false;
    } catch { return false; }
    const url = location.origin + PATH;
    let fp = ""; try { fp = await fingerprint(pem); } catch {}
    render(url, fp);
    if (typeof hydrateIcons === "function") hydrateIcons(box);
    return true;
  }
  return { load };
})();
