import { memo, useMemo } from "react";
import { Background, Controls, Handle, MarkerType, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { motion } from "framer-motion";
import { Avatar } from "../../ui/Avatar";
import { StatusPill } from "../../ui/kit";
import { useStore } from "../../data/store";
import { useTheme } from "../../theme/ThemeContext";
import type { AgentInstance } from "../../domain/types";

// Mission agent hierarchy (readme §3, CTRL-001, UI-AT-03): GM → department heads → specialists.
// Solid gold arrows = commands (down), dashed cyan arrows = reports (up), purple curves = peer conversations.
// Moving dashes mean traffic in the last hour. Real command/report links only; no decorative lines.
type NData = { inst: AgentInstance; role: import("../../ui/Avatar").Role; name: string; selected: boolean; compact: boolean; lr: boolean };

const AgentNode = memo(({ data }: NodeProps<Node<NData>>) => {
  const { inst, role, selected, compact } = data;
  return (
    <motion.div initial={{ scale: .6, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} whileHover={{ scale: 1.06 }}
      style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 2, padding: compact ? "4px 6px" : "6px 8px", borderRadius: 12, minWidth: compact ? 74 : 96,
        background: "var(--ax-panel2)", border: `1.5px solid ${selected ? "var(--ax-accent)" : "var(--ax-border)"}`, boxShadow: selected ? "0 0 16px var(--ax-glow)" : "0 0 calc(8px * var(--ax-glow-k)) color-mix(in srgb, var(--ax-accent2) 25%, transparent)", cursor: "pointer" }}
      aria-label={`${inst.agentId}, ${data.name}, ${inst.status}`}>
      <Handle type="target" position={data.lr ? Position.Left : Position.Top} style={{ opacity: 0 }} />
      <Avatar role={role} size={compact ? 30 : 38} name={inst.agentId} status={inst.status === "running" ? "busy" : inst.status === "blocked" ? "error" : inst.status === "done" ? "active" : "idle"} />
      <b style={{ fontSize: compact ? 10.5 : 12 }}>{inst.agentId}</b>
      {!compact && <span style={{ fontSize: 9.5, color: "var(--ax-muted)", maxWidth: 110, textAlign: "center", lineHeight: 1.1 }}>{data.name}</span>}
      <StatusPill s={inst.status} small />
      <Handle type="source" position={data.lr ? Position.Right : Position.Bottom} style={{ opacity: 0 }} />
      <Handle id="l" type="source" position={data.lr ? Position.Top : Position.Left} style={{ opacity: 0 }} />
      <Handle id="r" type="target" position={data.lr ? Position.Bottom : Position.Right} style={{ opacity: 0 }} />
    </motion.div>
  );
});
const nodeTypes = { agent: AgentNode };

export function AgentGraph({ missionId, selected, onSelect, compact, showPeers = true }: { missionId: string; selected?: string | null; onSelect: (agentId: string) => void; compact?: boolean; showPeers?: boolean }) {
  const { mode } = useTheme();
  const instances = useStore((s) => s.instances), agents = useStore((s) => s.agents), threads = useStore((s) => s.threads), messages = useStore((s) => s.messages);
  const { nodes, edges } = useMemo(() => {
    const mine = instances.filter((i) => i.missionId === missionId);
    const byAgent = new Map(mine.map((i) => [i.agentId, i]));
    const agentOf = (id: string) => agents.find((a) => a.id === id);
    // parent: department head if present in this mission, else GM
    const parent = (id: string): string | null => {
      if (id === "GM") return null; const a = agentOf(id); if (!a) return "GM";
      if (a.reportsTo && a.reportsTo !== "GM" && byAgent.has(a.reportsTo)) return a.reportsTo;
      return byAgent.has("GM") ? "GM" : null;
    };
    const level = (id: string): number => { let l = 0, p = parent(id); while (p) { l++; p = parent(p); } return l; };
    const levels = new Map<number, string[]>();
    for (const i of mine) { const l = level(i.agentId); levels.set(l, [...(levels.get(l) ?? []), i.agentId]); }
    const lr = !!compact; // narrow panels: left-to-right tree (GM → heads → specialists)
    const W = compact ? 120 : 136, H = compact ? 92 : 150;
    const ns: Node<NData>[] = [];
    for (const [l, ids] of levels) ids.sort().forEach((id, k) => {
      const a = agentOf(id); const inst = byAgent.get(id)!;
      const along = (k - (ids.length - 1) / 2);
      ns.push({ id, type: "agent", position: lr ? { x: l * W * 1.25, y: along * H } : { x: along * W, y: l * H }, data: { inst, role: a?.role ?? "developer", name: a?.name ?? id, selected: selected === id, compact: !!compact, lr } });
    });
    const recent = (a: string, b: string) => messages.some((m) => m.missionId === missionId && ((m.from === a && m.to === b) || (m.from === b && m.to === a)) && Date.now() - +new Date(m.at) < 3600e3 * 3);
    const es: Edge[] = [];
    for (const i of mine) {
      const p = parent(i.agentId); if (!p) continue;
      const live = recent(p, i.agentId) || i.status === "running";
      es.push({ id: `c-${p}-${i.agentId}`, source: p, target: i.agentId, type: "smoothstep", animated: live, label: compact ? undefined : "command",
        style: { stroke: "var(--ax-accent)", strokeWidth: 1.6 }, markerEnd: { type: MarkerType.ArrowClosed, color: "var(--ax-accent)" }, labelStyle: { fill: "var(--ax-muted)", fontSize: 9 }, labelBgStyle: { fill: "transparent" } });
      if (recent(p, i.agentId)) es.push({ id: `r-${i.agentId}-${p}`, source: i.agentId, target: p, sourceHandle: "l", targetHandle: "r", type: "smoothstep", animated: true,
        style: { stroke: "var(--ax-accent2)", strokeWidth: 1.2, strokeDasharray: "5 4" }, markerEnd: { type: MarkerType.ArrowClosed, color: "var(--ax-accent2)" }, label: compact ? undefined : "report", labelStyle: { fill: "var(--ax-accent2)", fontSize: 9 }, labelBgStyle: { fill: "transparent" } });
    }
    if (showPeers) for (const t of threads.filter((t) => t.missionId === missionId && t.kind === "peer")) {
      if (!byAgent.has(t.a) || !byAgent.has(t.b)) continue;
      es.push({ id: `p-${t.id}`, source: t.a, target: t.b, sourceHandle: "l", targetHandle: "r", type: "default", animated: true,
        style: { stroke: "var(--ax-blocked)", strokeWidth: 1.2, strokeDasharray: "3 3" }, markerEnd: { type: MarkerType.Arrow, color: "var(--ax-blocked)" } });
    }
    return { nodes: ns, edges: es };
  }, [instances, agents, threads, messages, missionId, selected, compact, showPeers]);

  if (!nodes.length) return <p className="ax-muted ax-small">No agents assigned yet; the GM staffs the mission after planning.</p>;
  return (
    <div className="ax-react-flow" style={{ width: "100%", height: "100%", minHeight: 200 }} role="figure" aria-label={`Agent hierarchy for mission ${missionId}: ${nodes.length} agents`}>
      <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: .15 }} minZoom={.3} maxZoom={1.6}
        nodesDraggable={false} nodesConnectable={false} proOptions={{ hideAttribution: true }} onNodeClick={(_, n) => onSelect(n.id)} colorMode={mode}>
        <Background color="var(--ax-border)" gap={22} size={1} />
        <Controls showInteractive={false} position="bottom-right" />
      </ReactFlow>
      {/* accessible list alternative (NFR-006) */}
      <ul className="sr-only">{nodes.map((n) => <li key={n.id}><button type="button" onClick={() => onSelect(n.id)}>{n.id}: {n.data.name}, {n.data.inst.status}</button></li>)}</ul>
    </div>
  );
}
export function GraphLegend() {
  const item = (c: string, dash: string, label: string) => <span className="ax-flex ax-xs" style={{ gap: 4 }}><svg width="22" height="6" aria-hidden><line x1="0" y1="3" x2="22" y2="3" stroke={c} strokeWidth="2" strokeDasharray={dash} /></svg>{label}</span>;
  return <span className="ax-flex" style={{ gap: 10, flexWrap: "wrap" }}>{item("var(--ax-accent)", "", "command")}{item("var(--ax-accent2)", "5 4", "report")}{item("var(--ax-blocked)", "3 3", "peer")}</span>;
}
