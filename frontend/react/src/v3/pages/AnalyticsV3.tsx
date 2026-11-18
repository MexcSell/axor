import { useState } from "react";
import { Bot, BarChart3, Coins, Gem, LineChart, Target, TrendingUp, Timer, CheckCircle2 } from "lucide-react";
import { Kpi, Panel, TabBody, Tabs } from "../ui/kit";
import { Dropdown } from "../ui/widgets";
import { useStore } from "../data/store";
import { PERF_SERIES } from "../data/sample";
import { useQueryParam } from "../app/router";
import { Execution, Fleet, HealthEvo, Predictive, Resources, Trends, ValueRoi, useRoi } from "./analytics/overview";
import { AgentsTab, CostTab, MissionsTab, PredictionsTab } from "./analytics/tabs";
import { RANGES, avg, tail, type Range } from "./analytics/data";

// Analytics & Performance (40-13). Agents, missions and tasks come from the store; success/spend series, finance totals and the
// forecast are SAMPLE data and are labelled as such on the panels.
export default function AnalyticsV3() {
  const [tab, setTab] = useQueryParam("tab", "overview");
  const [range, setRange] = useState<Range>("30");
  const agents = useStore((s) => s.agents), missions = useStore((s) => s.missions);
  const { value, cost, roi } = useRoi();
  const live = agents.filter((a) => a.status !== "offline");
  const success = avg(agents.map((a) => a.successRate));
  const p = tail(PERF_SERIES, range), dSucc = p.length > 1 ? p[p.length - 1].success - p[0].success : 0;
  const exec = avg(agents.map((a) => a.latencyS));
  const tabs = [{ id: "overview", label: "Overview", icon: BarChart3 }, { id: "agents", label: "Agents", icon: Bot, count: agents.length }, { id: "missions", label: "Missions", icon: Target, count: missions.length },
    { id: "cost", label: "Cost & ROI", icon: Coins }, { id: "predictions", label: "Predictions", icon: TrendingUp }];
  return (
    <div className="ax-page" style={{ gridTemplateRows: tab === "overview" ? "auto auto 1fr" : "auto 1fr" }}>
      <Panel i={0} title="Analytics & Performance" icon={BarChart3} sub="Real-time insights, agent performance, mission outcomes, and predictive intelligence."
        help={{ body: "How the company performs: Overview is the dashboard, Agents ranks the fleet, Missions shows outcomes and budget burn, Cost & ROI shows spend and return, Predictions looks 7 to 14 days ahead.", source: "Agents, missions and tasks come from the company store; trend, spend and forecast series are sample data and say so." }}
        actions={<Dropdown label="Period" value={range} options={RANGES} onChange={(v) => setRange(v as Range)} />}
        tabs={<Tabs tabs={tabs} value={tab} onChange={setTab} label="Analytics sections" />} />
      {tab === "overview" && (
        <div className="ax-kpis" style={{ gridTemplateColumns: "repeat(7, 1fr)", position: "relative", zIndex: 1, height: 78 }}>
          <Kpi i={0} icon={Target} c="#3b8cff" value={missions.length} label="Missions" delta={`${missions.filter((m) => m.status === "done").length} completed`} />
          <Kpi i={1} icon={Bot} c="#22d3ee" value={live.length} label="Active Agents" delta={`of ${agents.length} registered`} />
          <Kpi i={2} icon={CheckCircle2} c="#2fd27a" value={success} decimals={1} suffix="%" label="Success Rate" delta={`${dSucc >= 0 ? "↑ +" : "↓ "}${dSucc.toFixed(1)} pp (sample trend)`} />
          <Kpi i={3} icon={Timer} c="#f2b53a" value={exec} decimals={1} suffix=" s" label="Execution Time" delta="avg per task" />
          <Kpi i={4} icon={Coins} c="#a77bff" value={cost} prefix="$" label="Cost (Compute)" delta="sample finance" />
          <Kpi i={5} icon={LineChart} c="#2fd27a" value={value} prefix="$" label="Value Generated" delta="sample finance" />
          <Kpi i={6} icon={Gem} c="#c084fc" value={roi} decimals={1} suffix="x" label="ROI" delta="value / cost" />
        </div>)}
      {tab === "overview" ? (
        <TabBody k="overview" style={{ display: "grid", gap: "var(--ax-gap)", gridTemplateRows: "30fr 20fr 21fr", gridTemplateColumns: "1fr", minHeight: 0, height: "100%" }}>
          <div style={{ display: "grid", gridTemplateColumns: "1.1fr 1fr", gap: "var(--ax-gap)", minHeight: 0 }}><Fleet i={2} /><Trends range={range} i={3} /></div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--ax-gap)", minHeight: 0 }}><Execution range={range} i={4} /><Predictive onRecs={() => setTab("predictions")} i={5} /></div>
          <div style={{ display: "grid", gridTemplateColumns: "1.15fr 1fr 1.05fr", gap: "var(--ax-gap)", minHeight: 0 }}><Resources range={range} i={6} /><ValueRoi range={range} i={7} /><HealthEvo i={8} /></div>
        </TabBody>
      ) : (
        <TabBody k={tab} style={{ minHeight: 0, height: "100%" }}>
          {tab === "agents" && <AgentsTab range={range} />}
          {tab === "missions" && <MissionsTab />}
          {tab === "cost" && <CostTab range={range} />}
          {tab === "predictions" && <PredictionsTab />}
        </TabBody>)}
    </div>
  );
}
