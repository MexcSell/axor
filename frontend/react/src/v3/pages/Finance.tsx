import type { CSSProperties } from "react";
import { Coins } from "lucide-react";
import { Panel, TabBody, Tabs } from "../ui/kit";
import { useQueryParam } from "../app/router";
import { AgentAllocPanel, AlertsPanel, BudgetPanel, CategoryPanel, DeptPanel, FinKpis, MissionSpendPanel, OptimPanel, SustainPanel, TrendPanel } from "./finance/parts";
import { AlertsTab, BudgetsTab, ForecastTab, MissionCostTab, UsageTab } from "./finance/tabs";

const TABS = [{ id: "overview", label: "Overview" }, { id: "budgets", label: "Budgets" }, { id: "usage", label: "Usage" }, { id: "mission", label: "Cost by Mission" }, { id: "alerts", label: "Alerts" }, { id: "forecast", label: "Forecast" }];
const row = (c: string): CSSProperties => ({ display: "grid", gridTemplateColumns: c.split(" ").map((x) => `minmax(0,${x})`).join(" "), gridTemplateRows: "minmax(0, 1fr)", gap: "var(--ax-gap)", minHeight: 0 });

export default function Finance() {
  const [tab, setTab] = useQueryParam("tab", "overview");
  const ov = tab === "overview";
  return (
    <div className="ax-page" style={{ gridTemplateRows: ov ? "minmax(0,19fr) minmax(0,26fr) minmax(0,30fr) minmax(0,25fr)" : "auto 1fr" }}>
      <style>{".fin-compact td{padding:3px 8px}"}</style>
      <Panel i={0} title="Finance" icon={Coins} sub="Manage budgets, spending, cost optimization, and forecasts for the autonomous AI company. Sample data, in US dollars."
        help={{ body: "Where the money goes: budgets, usage by model, agent and mission, alerts, and a forecast with its assumptions. Governance (autonomy, model routing, policies) is on its own page.", source: "Finance store (sample data; no billing integration is connected)" }}
        tabs={<Tabs label="Finance tabs" value={tab} onChange={setTab} tabs={TABS} />}>
        {ov && <FinKpis />}
      </Panel>
      {ov ? (<>
        <div style={row("1fr 1.15fr 1.1fr")}><BudgetPanel i={1} /><CategoryPanel i={2} /><TrendPanel i={3} /></div>
        <div style={row("1.1fr 1.1fr 1fr .85fr")}><MissionSpendPanel i={4} /><DeptPanel i={5} /><AlertsPanel i={6} /><OptimPanel i={7} /></div>
        <div style={row("2.2fr 1fr")}><AgentAllocPanel i={8} /><SustainPanel i={9} /></div>
      </>) : (
        <div style={{ minHeight: 0 }}>
          <TabBody k={tab}>
            {tab === "budgets" && <BudgetsTab />}{tab === "usage" && <UsageTab />}{tab === "mission" && <MissionCostTab />}{tab === "alerts" && <AlertsTab />}{tab === "forecast" && <ForecastTab />}
          </TabBody>
        </div>
      )}
    </div>
  );
}
