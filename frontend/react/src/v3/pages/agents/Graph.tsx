import { memo, useMemo } from "react";
import { Background, Controls, Handle, MarkerType, MiniMap, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { motion } from "framer-motion";
import { Network, ExternalLink } from "lucide-react";
import { Avatar, ROLES, type Role } from "../../ui/Avatar";
import { Legend, Panel, Pill } from "../../ui/kit";
import { useStore } from "../../data/store";
import { useTheme } from "../../theme/ThemeContext";
import { HEALTH_C, deptName, healthOf } from "./data";
import { useSelected } from "./util";
import type { AgentIdentity } from "../../domain/types";

type D = { a: AgentIdentity; big: boolean; sel: boolean };
const N = memo(({ data }: NodeProps<Node<D>>) => {
  const { a, big, sel } = data;
  return (
    <motion.div initial={{ scale: .6, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} whileHover={{ scale: 1.07 }} aria-label={`${a.id} ${a.name}, ${a.status}`}
      style={{ display: "flex", alignItems: "center", gap: 6, padding: big ? "6px 10px" : "3px 8px 3px 4px", borderRadius: 11, width: big ? 150 : 124, background: "var(--ax-panel2)", cursor: "pointer",
        border: `1.5px solid ${sel ? "var(--ax-accent)" : ROLES[a.role].c}`, boxShadow: sel ? "0 0 16px var(--ax-glow)" : "none" }}>
      <Handle type="target" position={Position.Top} style={{ opacity: 0 }} /><Avatar role={a.role} size={big ? 34 : 24} name={a.id} status={a.status} />
      <span style={{ minWidth: 0, lineHeight: 1.15 }}><b style={{ fontSize: big ? 12 : 10.5 }}>{a.id}</b><span style={{ display: "block", fontSize: 9, color: "var(--ax-muted)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{a.baseline} · {Math.round(a.successRate)}%</span></span>
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
    </motion.div>);
});
const nodeTypes = { agent: N };

export function AgentGraphTab({ onOpen }: { onOpen: (id: string) => void }) {
  const agents = useStore((s) => s.agents), departments = useStore((s) => s.departments); const { mode } = useTheme(); const { id: sel } = useSelected();
  const { nodes, edges } = useMemo(() => {
    // Hierarchy from the data (works for the sample company and for live AXoR agents): root = reports to nobody,
    // heads = report to the root, specialists = report to a head; anything unattached goes in a last row.
    const ns: Node<D>[] = [], es: Edge[] = []; const W = 150, kids = (id: string) => agents.filter((x) => x.reportsTo === id);
    const root = agents.find((x) => !x.reportsTo) ?? agents[0];
    if (!root) return { nodes: ns, edges: es };
    const heads = kids(root.id).map((x) => x.id);
    ns.push({ id: root.id, type: "agent", position: { x: ((Math.max(heads.length, 1) - 1) * W) / 2, y: 0 }, data: { a: root, big: true, sel: sel === root.id } });
    const placed = new Set([root.id]);
    heads.forEach((h, c) => {
      const a = agents.find((x) => x.id === h); if (!a) return; placed.add(h);
      ns.push({ id: h, type: "agent", position: { x: c * W, y: 120 }, data: { a, big: true, sel: sel === h } });
      es.push({ id: `e-${root.id}-${h}`, source: root.id, target: h, type: "smoothstep", style: { stroke: "var(--ax-accent)", strokeWidth: 1.5 }, markerEnd: { type: MarkerType.ArrowClosed, color: "var(--ax-accent)" } });
      kids(h).forEach((k, r) => {
        placed.add(k.id);
        ns.push({ id: k.id, type: "agent", position: { x: c * W + 12, y: 210 + r * 44 }, data: { a: k, big: false, sel: sel === k.id } });
        es.push({ id: `e-${h}-${k.id}`, source: h, target: k.id, type: "smoothstep", style: { stroke: "var(--ax-border)", strokeWidth: 1.1 }, animated: k.status === "busy" });
      });
    });
    const rest = agents.filter((x) => !placed.has(x.id)); const maxRows = Math.max(1, ...heads.map((h) => kids(h).length));
    rest.forEach((k, i) => ns.push({ id: k.id, type: "agent", position: { x: (i % Math.max(heads.length, 6)) * W, y: 260 + maxRows * 44 + Math.floor(i / Math.max(heads.length, 6)) * 60 }, data: { a: k, big: false, sel: sel === k.id } }));
    return { nodes: ns, edges: es };
  }, [agents, departments, sel]);
  const cnt = (f: (a: AgentIdentity) => boolean) => agents.filter(f).length;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 270px", gap: "var(--ax-gap)", height: "100%", minHeight: 0 }}>
      <Panel i={1} title={`Agent Graph (${agents.length} agents)`} icon={Network} flush help={{ body: "The company hierarchy: GM at the top, department heads below, specialists under each head. Click an agent to open its profile.", source: "Agent registry: reportsTo links (sample data)." }}>
        <div className="ax-react-flow" style={{ width: "100%", height: "100%" }} role="figure" aria-label={`Company hierarchy of ${agents.length} agents`}>
          <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: .06 }} minZoom={.3} maxZoom={1.6} nodesDraggable={false} nodesConnectable={false} proOptions={{ hideAttribution: true }} onNodeClick={(_, n) => onOpen(n.id)} colorMode={mode}>
            <Background color="var(--ax-border)" gap={22} size={1} /><Controls showInteractive={false} position="bottom-right" /><MiniMap pannable zoomable style={{ background: "var(--ax-panel2)" }} />
          </ReactFlow>
          <ul className="sr-only">{agents.map((a) => <li key={a.id}><button type="button" onClick={() => onOpen(a.id)}>{a.id}: {a.name}, reports to {a.reportsTo ?? "nobody"}</button></li>)}</ul>
        </div>
      </Panel>
      <div style={{ display: "grid", gridTemplateRows: "auto auto minmax(0,1fr)", gap: "var(--ax-gap)", minHeight: 0 }}>
        <Panel i={2} title="Legend" icon={Network} help="Border colour is the agent's role; the ring on the avatar shows its live status. Lines are reporting relations.">
          <Legend items={[{ label: "Reporting line (GM to heads)", c: "var(--ax-accent)" }, { label: "Reports to department head", c: "var(--ax-border)" }, { label: `Healthy ${cnt((a) => healthOf(a) === "healthy")}`, c: HEALTH_C.healthy }, { label: `Degraded ${cnt((a) => healthOf(a) === "degraded")}`, c: HEALTH_C.degraded }, { label: `At risk ${cnt((a) => healthOf(a) === "at_risk")}`, c: HEALTH_C.at_risk }]} />
        </Panel>
        <Panel i={3} title="Selected" icon={ExternalLink} help="The agent highlighted in the graph. Click any node to open its profile.">
          {(() => { const a = agents.find((x) => x.id === sel); return a ? <div className="ax-flex" style={{ gap: 8 }}><Avatar role={a.role} size={36} name={a.id} /><span><b>{a.id}</b><span className="ax-xs ax-muted" style={{ display: "block" }}>{a.name}</span></span></div> : null; })()}
        </Panel>
        <Panel i={4} title="Departments" icon={Network} help="Head count per department.">
          {[{ id: "executive", name: "Executive", role: "gm" as Role }, ...departments].map((d) => <div key={d.id} className="ax-flex ax-small" style={{ gap: 6, padding: "3px 0" }}><Avatar role={d.role} size={20} name={d.name} /><span style={{ flex: 1 }}>{d.name}</span><Pill c="var(--ax-info)">{agents.filter((a) => a.dept === d.id).length}</Pill></div>)}
          <span className="ax-xs ax-muted">{deptName({ departments } as never, "executive")} holds GM and the Architect.</span>
        </Panel>
      </div>
    </div>
  );
}
