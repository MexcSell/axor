import { useMemo } from "react";
import { Bot, CheckCircle2, GitBranch, Network, RefreshCw, Star, Users, FlaskConical, Database, UserPlus, Play, Sparkles, AlertTriangle, XCircle, TrendingUp, } from "lucide-react";
import { IconBtn, Kpi, Panel, TabBody, Tabs, useToast } from "../ui/kit";
import { go, useQueryParam } from "../app/router";
import { useStore } from "../data/store";
import { healthOf, skillScore, loadOf } from "./agents/data";
import { AgentDetail, AgentTable, EvolutionPanel, InstancesPanel, MentoringPanel, SkillRadar, VerifierPanel } from "./agents/Directory";
import { BranchMerge } from "./agents/BranchMerge";
import { AgentGraphTab } from "./agents/Graph";
import { ProfileView } from "./agents/Profile";
import { useSelected } from "./agents/util";

// Agents (spec 4.10 + 5-6). Reference 30-4: left table, right detail + branch/merge, bottom panels. Tabs: Directory · Agent Graph · Profile.
export default function Agents() {
  const [tab, setTab] = useQueryParam("tab", "directory"); const toast = useToast();
  const agents = useStore((s) => s.agents), instances = useStore((s) => s.instances), missions = useStore((s) => s.missions);
  const { id, open } = useSelected();
  const a = agents.find((x) => x.id === id) ?? agents[0];
  const stat = useMemo(() => {
    const healthy = agents.filter((x) => healthOf(x) === "healthy").length, degraded = agents.filter((x) => healthOf(x) === "degraded").length, risk = agents.filter((x) => healthOf(x) === "at_risk").length;
    return { healthy, degraded, risk, active: instances.filter((i) => i.status !== "done").length, load: Math.round(agents.reduce((s, x) => s + loadOf(x), 0) / agents.length), skill: +(agents.reduce((s, x) => s + skillScore(x), 0) / agents.length).toFixed(1) };
  }, [agents, instances]);
  const pageTabs = <Tabs label="Agents views" value={tab} onChange={setTab} tabs={[{ id: "directory", label: "Directory", icon: Bot }, { id: "graph", label: "Agent Graph", icon: Network }, { id: "profile", label: "Profile", icon: Users }]} />;
  const openProfile = (x: string, pt?: string) => open(x, pt);
  const total = agents.length;
  return (
    <div className="ax-page" style={{ gridTemplateRows: tab === "directory" ? "13fr 44fr 30fr" : "15fr 85fr" }}>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 245px", gap: "var(--ax-gap)", minHeight: 0 }}>
        <Panel i={0} title="Agents" icon={Bot} sub="Manage, monitor, evolve, and orchestrate your AI agents." actions={pageTabs}
          help={{ body: "All agents of the company. Each agent is a stable identity; missions use isolated instances of it. Switch between the directory, the hierarchy graph and one agent's full profile.", source: "Agent registry and instances (sample data)." }}>
          <div className="ax-kpis" style={{ gridTemplateColumns: "repeat(7, 1fr)", height: 72 }}>
            <style>{".ax-compact td{padding:3px 8px}.ax-compact th{padding:4px 8px}"}</style>
            <Kpi i={0} icon={Bot} c="#3b8cff" value={total} label="Total Agents" onClick={() => setTab("directory")} />
            <Kpi i={1} icon={CheckCircle2} c="#2fd27a" value={stat.healthy} label="Healthy" delta={`${(total ? (stat.healthy / total) * 100 : 0).toFixed(1)}% of agents`} />
            <Kpi i={2} icon={AlertTriangle} c="#f2b53a" value={stat.degraded} label="Degraded" delta="success < 90%" />
            <Kpi i={3} icon={XCircle} c="#ef4444" value={stat.risk} label="At Risk" delta="offline or error" />
            <Kpi i={4} icon={Database} c="#a77bff" value={stat.active} label="Instances" delta={`in ${missions.filter((m) => !m.archived).length} missions`} onClick={() => open(a.id, "instances")} />
            <Kpi i={5} icon={TrendingUp} c="#22d3ee" value={stat.load} suffix="%" label="Avg. Load" />
            <Kpi i={6} icon={Star} c="#f2b53a" value={stat.skill} decimals={1} label="Avg. Skill Score" />
          </div>
        </Panel>
        <Panel i={1} title="Quick Actions" icon={Sparkles} help="Shortcuts. Actions that would change the company only show a confirmation in this sample build.">
          <div className="ax-flex" style={{ gap: 6, flexWrap: "wrap" }}>
            <IconBtn icon={UserPlus} label="Request a new agent" onClick={() => toast("Sample: the GM would draft an org-change proposal for a new agent", "info")} />
            <IconBtn icon={Play} label={`Mobilize ${a.id} for a mission`} onClick={() => toast(`Sample: ${a.id} would get a new isolated instance`, "info")} />
            <IconBtn icon={RefreshCw} label="Refresh health" onClick={() => toast("Sample data refreshed")} />
            <IconBtn icon={Network} label="Open Organization" onClick={() => go("organization")} />
            <IconBtn icon={FlaskConical} label="Open Evolution Lab" onClick={() => go("evolution")} />
            <IconBtn icon={GitBranch} label={`Branch and merge of ${a.id}`} onClick={() => open(a.id, "instances")} />
          </div>
        </Panel>
      </div>
      {tab === "directory" ? (
        <TabBody k="directory" style={{ display: "contents" }}>
          <div style={{ display: "grid", gridTemplateColumns: "minmax(0,45fr) minmax(0,28fr) minmax(0,27fr)", gap: "var(--ax-gap)", minHeight: 0 }}>
            <AgentTable i={2} onOpen={openProfile} />
            <AgentDetail id={a.id} i={3} onOpen={openProfile} />
            <Panel i={4} title={`Multi-Mission Branch & Merge — ${a.id}`} icon={GitBranch} help={{ body: "One agent can be mobilized for several missions that run separately. When a mission completes, the agent combines its verified experience back into the original, like branching from the stem and merging back.", policy: "Merge only after independent verification; promotion only if verified better." }}>
              <BranchMerge agentId={a.id} compact max={3} />
            </Panel>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1.05fr 1fr 1fr .95fr 1fr", gap: "var(--ax-gap)", minHeight: 0 }}>
            <SkillRadar a={a} i={5} />
            <InstancesPanel a={a} i={6} onOpen={(p) => openProfile(a.id, p)} />
            <EvolutionPanel a={a} i={7} onOpen={(p) => openProfile(a.id, p)} />
            <VerifierPanel a={a} i={8} />
            <MentoringPanel a={a} i={9} />
          </div>
        </TabBody>
      ) : (
        <TabBody k={tab}>
          {tab === "graph" && <AgentGraphTab onOpen={(x) => openProfile(x)} />}
          {tab === "profile" && <ProfileView a={a} />}
        </TabBody>
      )}
    </div>
  );
}
