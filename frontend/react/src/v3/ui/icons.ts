import {
  AlertTriangle, BarChart3, BookOpen, Box, Check, Coins, Dna, FileText, FlaskConical, GitBranch, GitCommit, Infinity as InfinityIcon, Layers, ListChecks,
  MessageSquare, Monitor, Palette, Pause, Play, RefreshCw, Rocket, Route, Rss, Server, Settings, Shield, Smartphone, Sparkles, Star, Users, Workflow, X,
  type LucideIcon,
} from "lucide-react";

// Mission / event icon keys used by the data layer → lucide icons with a clear meaning.
export const ICON: Record<string, LucideIcon> = {
  star: Star, box: Box, book: BookOpen, chart: BarChart3, infinity: InfinityIcon, phone: Smartphone, pipe: Workflow, layers: Layers, palette: Palette,
  shield: Shield, server: Server, rocket: Rocket, sparkles: Sparkles, check: Check, flask: FlaskConical, x: X, users: Users, route: Route, file: FileText,
  monitor: Monitor, alert: AlertTriangle, message: MessageSquare, git: GitCommit, coins: Coins, play: Play, pause: Pause, retry: RefreshCw, resume: Play,
  cancel: X, rss: Rss, dna: Dna, settings: Settings, branch: GitBranch, list: ListChecks,
};
export const iconFor = (k?: string): LucideIcon => (k && ICON[k]) || Sparkles;
