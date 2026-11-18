import { Landmark } from "lucide-react";
import { Panel, TabBody, Tabs } from "../ui/kit";
import { useQueryParam } from "../app/router";
import { AuditTab, PermissionsTab, PoliciesTab } from "./governance/tabs";
import { GovDashboard, GovKpis } from "./governance/dash";
import { ModelLoaderTab } from "./governance/loader";
import { SelfRenewalTab } from "./governance/renewal";

const TABS = [{ id: "autonomy", label: "Autonomy" }, { id: "permissions", label: "Permissions" }, { id: "routing", label: "Model Routing" }, { id: "renewal", label: "Self-Renewal" }, { id: "policies", label: "Policies" }, { id: "audit", label: "Audit" }];

export default function Governance() {
  const [tab, setTab] = useQueryParam("tab", "autonomy");
  return (
    <div className="ax-page" style={{ gridTemplateRows: tab === "autonomy" ? "minmax(0,19fr) minmax(0,37fr) minmax(0,44fr)" : "auto 1fr" }}>
      <Panel i={0} title="Governance" icon={Landmark} sub="Autonomy, permissions, model routing, self-renewal and policies for the autonomous AI company. Sample data."
        help={{ body: "How much the agents may do on their own, who approves what, which model each role uses (the Model Loader), and the stop controls. Money is on the Finance page.", policy: "The owner retains authority. No agent can grant itself permissions." }}
        tabs={<Tabs label="Governance tabs" value={tab} onChange={setTab} tabs={TABS} />}>
        {tab === "autonomy" && <GovKpis />}
      </Panel>
      {tab === "autonomy" ? <GovDashboard go={setTab} /> : <div style={{ minHeight: 0 }}>
        <TabBody k={tab}>
          {tab === "permissions" && <PermissionsTab />}{tab === "routing" && <ModelLoaderTab />}
          {tab === "renewal" && <SelfRenewalTab />}{tab === "policies" && <PoliciesTab />}{tab === "audit" && <AuditTab />}
        </TabBody>
      </div>}
    </div>
  );
}
