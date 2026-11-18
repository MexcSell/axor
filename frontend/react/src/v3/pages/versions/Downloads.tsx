import { useState } from "react";
import { motion } from "framer-motion";
import { Download, FileArchive, Fingerprint, PackageCheck } from "lucide-react";
import { CopyBtn, IconBtn, Panel, Pill } from "../../ui/kit";
import type { Release } from "../../domain/types";
import { provenance } from "./data";
import { useDownload } from "./Releases";

export function DownloadsTab({ releases, sel }: { releases: Release[]; sel: string }) {
  const dl = useDownload();
  const [v, setV] = useState(sel); const r = releases.find((x) => x.version === v) ?? releases[0]; const pv = provenance(r);
  const rows = releases.flatMap((x) => x.artifacts.map((a) => ({ x, a })));
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1.7fr 1fr", gap: "var(--ax-gap)", height: "100%", minHeight: 0 }}>
      <Panel i={0} title="Downloads" icon={FileArchive} sub={`${rows.length} artifacts`} help="All stored artifacts of all editions with their sha256 checksum. Download generates a JSON manifest in your browser (the sample binaries do not exist in this prototype). Verify with the checksum.">
        <table className="ax-table"><thead><tr><th>Edition</th><th>Artifact</th><th>Size</th><th>sha256</th><th aria-label="Actions" /></tr></thead>
          <tbody>{rows.map(({ x, a }, i) => (
            <motion.tr key={x.version + a.name} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: Math.min(i, 12) * .03 }} onClick={() => setV(x.version)} style={{ cursor: "pointer", background: x.version === r.version ? "color-mix(in srgb, var(--ax-accent) 8%, transparent)" : undefined }}>
              <td><b>{x.version}</b></td><td className="ax-small">{a.name}</td><td className="ax-small">{a.size}</td><td className="ax-mono ax-xs" title={a.sha256}>{a.sha256.slice(0, 24)}…</td>
              <td><span className="ax-flex" style={{ gap: 2 }}><CopyBtn text={a.sha256} label="Copy sha256" /><IconBtn icon={Download} size="sm" label={`Download ${a.name} manifest`} onClick={(e) => { e.stopPropagation(); dl(x, a.name); }} /></span></td></motion.tr>))}</tbody></table>
      </Panel>
      <Panel i={1} title={`Provenance · ${r.version}`} icon={Fingerprint} help="Where the artifacts of this edition came from: commit, branch, the pipeline run and whether it is signed. Sample data: nothing here is attested.">
        <div className="ax-col" style={{ gap: 8 }}>
          <div className="ax-kv">
            <span className="ax-muted">Builder</span><span>{pv.builder}</span><span className="ax-muted">Built by</span><span>{pv.builtBy}</span>
            <span className="ax-muted">Commit</span><span className="ax-mono">{pv.commit}</span><span className="ax-muted">Branch</span><span className="ax-mono">{pv.branch}</span>
            <span className="ax-muted">Workflow</span><span className="ax-mono ax-small">{pv.workflow}</span><span className="ax-muted">Pipeline run</span><span className="ax-mono">{pv.run}</span>
            <span className="ax-muted">SLSA level</span><span>{pv.slsa}</span><span className="ax-muted">Signature</span><Pill c="var(--ax-warn)">unsigned (sample)</Pill>
          </div>
          <div className="ax-tile ax-small"><b className="ax-flex"><PackageCheck size={14} className="ax-ok" aria-hidden />How to verify</b><span className="ax-mono ax-xs">sha256sum axor-web-{r.version}.tar.gz</span><br />Compare the output with the sha256 in the table.</div>
        </div>
      </Panel>
    </div>
  );
}
