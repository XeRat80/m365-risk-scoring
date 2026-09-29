import {
  CircleStop,
  CloudAlert,
  KeyRound,
  MailWarning,
  RefreshCw,
  ShieldMinus,
  UserRoundX,
  type LucideIcon,
} from "lucide-react";

export type ScenarioDefinition = {
  id: string;
  label: string;
  family: "mail" | "identity" | "operations";
  description: string;
  signal: string;
  consequence: string;
  affected: string[];
  icon: LucideIcon;
  tone: "danger" | "warning" | "recovery";
};

export const SCENARIOS: ScenarioDefinition[] = [
  {
    id: "credential-phishing",
    label: "Credential phishing",
    family: "mail",
    description: "Inject high-intent credential capture signals into external mail.",
    signal: "Failed SPF, DKIM and DMARC; reply-to mismatch; novel domains.",
    consequence: "Mail risk rises and affected users move up the analyst queue.",
    affected: ["Email threat", "Communication behavior"],
    icon: KeyRound,
    tone: "danger",
  },
  {
    id: "domain-spoofing",
    label: "Domain spoofing",
    family: "mail",
    description: "Simulate sender and routing alignment failures.",
    signal: "From/sender mismatch, failed DMARC and suspicious routing hops.",
    consequence: "Header integrity weakens and high-risk events become visible.",
    affected: ["Email threat"],
    icon: MailWarning,
    tone: "danger",
  },
  {
    id: "executive-impersonation",
    label: "Executive impersonation",
    family: "mail",
    description: "Target privileged users with high-importance external mail.",
    signal: "Role-based targeting, urgency and unusual sender relationships.",
    consequence: "Privileged identities receive higher investigation priority.",
    affected: ["Email threat", "Privilege"],
    icon: UserRoundX,
    tone: "warning",
  },
  {
    id: "account-takeover",
    label: "Account takeover",
    family: "identity",
    description: "Combine mailbox anomalies with identity-risk escalation.",
    signal: "Behavior shift, risky-user evidence and unusual communications.",
    consequence: "The target user trajectory jumps from baseline to high risk.",
    affected: ["Behavior", "Entra risk", "Email threat"],
    icon: CloudAlert,
    tone: "danger",
  },
  {
    id: "mfa-removal",
    label: "MFA removal",
    family: "identity",
    description: "Degrade registration posture for a selected identity.",
    signal: "MFA registration disappears while other evidence remains active.",
    consequence: "Posture contribution increases and the user can become critical.",
    affected: ["MFA posture", "Entra risk"],
    icon: ShieldMinus,
    tone: "warning",
  },
  {
    id: "entra-escalation",
    label: "Entra escalation",
    family: "identity",
    description: "Raise the Microsoft Entra risky-user signal.",
    signal: "High identity-protection risk is correlated with mailbox behavior.",
    consequence: "Identity contribution lifts the explainable hybrid score.",
    affected: ["Entra risk"],
    icon: CloudAlert,
    tone: "warning",
  },
  {
    id: "throttling",
    label: "Graph throttling",
    family: "operations",
    description: "Exercise bounded backoff and Retry-After handling.",
    signal: "Graph-compatible endpoints return HTTP 429 responses.",
    consequence: "Freshness warnings appear while resumable sync jobs retry.",
    affected: ["Connector", "Freshness"],
    icon: CircleStop,
    tone: "warning",
  },
  {
    id: "recovery",
    label: "Recovery",
    family: "operations",
    description: "Restore healthy traffic and identity posture.",
    signal: "Connector faults clear and the normal deterministic stream resumes.",
    consequence: "Delta synchronization catches up while audit evidence remains.",
    affected: ["Connector", "Sync queue"],
    icon: RefreshCw,
    tone: "recovery",
  },
];

export function scenarioDefinition(id: string | undefined) {
  return SCENARIOS.find((scenario) => scenario.id === id);
}
