import { Accessibility, Bell, Bot, Eye, FileJson, LayoutGrid, Palette, Plug, Settings as Cog, ShieldCheck, Sparkles, Type, Layers } from "lucide-react";
import { Panel, TabBody, Tabs } from "../ui/kit";
import { useQueryParam } from "../app/router";
import { Card, grid } from "./settings/parts";
import { LivePreview } from "./appearance/Preview";
import { ThemeTab } from "./appearance/ThemeTab";
import { AccessibilityTab, ColorsTab, IconsTab, LayoutTab, PresetsTab, ThemesTab, TypographyTab } from "./appearance/tabs";
import { IntegrationsTab, NotificationsTab, SecurityTab } from "./settings/tabs";

// Appearance & Settings (30-10, §4.14, THEME-001..003): the Theme dashboard plus detail tabs. Tabs that need a preview show the
// same representative states (THEME-003) on the right; the Theme tab has its own mini-dashboard carousel.
const WIDE = ["theme", "integrations", "notifications", "security"];
export default function Appearance() {
  const [tab, setTab] = useQueryParam("tab", "theme");
  const tabs = [
    { id: "theme", label: "Theme", icon: Palette }, { id: "layout", label: "Layout", icon: LayoutGrid }, { id: "avatar", label: "Agent Avatar", icon: Bot },
    { id: "integrations", label: "Integrations", icon: Plug }, { id: "notifications", label: "Notifications", icon: Bell }, { id: "security", label: "Security", icon: ShieldCheck },
    { id: "colors", label: "Colors", icon: Sparkles }, { id: "typography", label: "Typography", icon: Type }, { id: "a11y", label: "Accessibility", icon: Accessibility },
    { id: "gallery", label: "Gallery", icon: Layers }, { id: "presets", label: "Presets", icon: FileJson },
  ];
  const body = (
    <>
      {tab === "theme" && <ThemeTab />}{tab === "layout" && <LayoutTab />}{tab === "avatar" && <IconsTab />}{tab === "integrations" && <IntegrationsTab />}
      {tab === "notifications" && <NotificationsTab />}{tab === "security" && <SecurityTab />}{tab === "colors" && <ColorsTab />}{tab === "typography" && <TypographyTab />}
      {tab === "a11y" && <AccessibilityTab />}{tab === "gallery" && <ThemesTab />}{tab === "presets" && <PresetsTab />}
    </>
  );
  return (
    <div className="ax-page">
      <Panel i={0} title="Appearance & Settings" icon={Cog} sub="Customize the look, behavior, integrations, and security of your AXoR Company OS."
        help={{ body: "Change colours, style, icons, avatars, density and more; changes apply instantly, are saved to your account and can be undone (Gallery tab). Hover a Gallery tile to preview a look first.", source: "Per-user preferences (THEME-001); local and server." }}
        tabs={<Tabs tabs={tabs} value={tab} onChange={setTab} label="Appearance and settings sections" wrap />}>
        {WIDE.includes(tab) ? <TabBody k={tab}>{body}</TabBody> : (
          <div style={grid("1.5fr 1fr", { height: "100%" })}>
            <TabBody k={tab}>{body}</TabBody>
            <Card title="Live Preview" icon={Eye} help={{ body: "The same representative parts (toolbar, card, form, chat bubble, status badges, selected tab, alert, graph node, disabled controls) in every look.", source: "THEME-003" }}><LivePreview /></Card>
          </div>)}
      </Panel>
    </div>
  );
}
