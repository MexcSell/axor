import { Bell, Building2, Cog, Plug, ShieldCheck, UserCheck, Crown } from "lucide-react";
import { Panel, TabBody, Tabs } from "../ui/kit";
import { useQueryParam } from "../app/router";
import { useStore } from "../data/store";
import { AdminTab, ApprovalsTab, GeneralTab, IntegrationsTab, NotificationsTab, SecurityTab } from "./settings/tabs";

// Settings (§3.2): general, integrations, approvals, notifications, security and admin (self-renewal, AI roles, verification).
export default function Settings() {
  const [tab, setTab] = useQueryParam("tab", "general");
  const me = useStore((s) => s.me);
  const tabs = [
    { id: "general", label: "General", icon: Building2 }, { id: "integrations", label: "Integrations", icon: Plug }, { id: "approvals", label: "Approvals", icon: UserCheck },
    { id: "notifications", label: "Notifications", icon: Bell }, { id: "security", label: "Security", icon: ShieldCheck }, { id: "admin", label: "Admin", icon: Crown },
  ];
  return (
    <div className="ax-page">
      <Panel i={0} title="Settings" icon={Cog} sub="Integrations, approvals, workspace, notifications and security for your AXoR Company OS."
        help={{ body: "Workspace-wide settings. Appearance is separate (Appearance page). Items marked Sample data are not connected to real services in this build.", policy: me ? `Signed in as ${me.name} (${me.role}). Admin tab changes need the admin role.` : "Admin tab changes need the admin role." }}
        tabs={<Tabs tabs={tabs} value={tab} onChange={setTab} label="Settings sections" />}>
        <TabBody k={tab}>
          {tab === "general" && <GeneralTab />}{tab === "integrations" && <IntegrationsTab />}{tab === "approvals" && <ApprovalsTab />}
          {tab === "notifications" && <NotificationsTab />}{tab === "security" && <SecurityTab />}{tab === "admin" && <AdminTab />}
        </TabBody>
      </Panel>
    </div>
  );
}
