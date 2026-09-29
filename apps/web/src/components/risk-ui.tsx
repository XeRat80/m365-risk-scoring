import type {LucideIcon} from "lucide-react";
import {ArrowUpRight, CircleAlert, Inbox, RefreshCw} from "lucide-react";
import Link from "next/link";
import type {ReactNode} from "react";
import {Badge} from "@/components/ui/badge";
import {Button} from "@/components/ui/button";
import {Card, CardContent} from "@/components/ui/card";
import {cn} from "@/lib/utils";

export function RiskBadge({level, className}: {level: string; className?: string}) {
  const tone =
    level === "critical"
      ? "border-rose-400/25 bg-rose-400/10 text-rose-200"
      : level === "high"
        ? "border-orange-400/25 bg-orange-400/10 text-orange-200"
        : level === "medium"
          ? "border-amber-400/25 bg-amber-400/10 text-amber-100"
          : "border-emerald-400/20 bg-emerald-400/10 text-emerald-200";
  return <Badge variant="outline" className={cn("capitalize", tone, className)}>{level}</Badge>;
}

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow: string;
  title: string;
  description: string;
  actions?: ReactNode;
}) {
  return (
    <header className="page-header">
      <div className="min-w-0">
        <p className="page-eyebrow">{eyebrow}</p>
        <h1 className="page-title">{title}</h1>
        <p className="page-description">{description}</p>
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}

export function SectionHeading({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex items-end justify-between gap-4">
      <div>
        <h2 className="text-base font-semibold tracking-[-.025em]">{title}</h2>
        {description ? <p className="mt-1 text-xs leading-5 text-muted-foreground">{description}</p> : null}
      </div>
      {action}
    </div>
  );
}

export function StatCard({
  label,
  value,
  detail,
  icon: Icon,
  tone = "default",
  trend,
}: {
  label: string;
  value: string | number;
  detail: string;
  icon: LucideIcon;
  tone?: "default" | "danger" | "warning" | "info";
  trend?: string;
}) {
  const iconTone = {
    default: "bg-primary/10 text-primary ring-primary/15",
    danger: "bg-rose-400/10 text-rose-200 ring-rose-400/15",
    warning: "bg-amber-400/10 text-amber-100 ring-amber-400/15",
    info: "bg-sky-400/10 text-sky-200 ring-sky-400/15",
  }[tone];

  return (
    <Card className="surface-panel stat-card min-h-36 py-0">
      <CardContent className="flex h-full flex-col justify-between p-4 sm:p-5">
        <div className="flex items-start justify-between gap-3">
          <span className="text-xs font-medium text-muted-foreground">{label}</span>
          <span className={cn("grid size-8 place-items-center rounded-[10px] ring-1", iconTone)}>
            <Icon className="size-4" strokeWidth={1.7}/>
          </span>
        </div>
        <div className="mt-5">
          <div className="flex items-baseline justify-between gap-3">
            <span className="metric-number mono-data text-3xl font-semibold">{value}</span>
            {trend ? <span className="mono-data text-[10px] text-primary">{trend}</span> : null}
          </div>
          <p className="mt-1.5 text-[11px] leading-4 text-muted-foreground">{detail}</p>
        </div>
      </CardContent>
    </Card>
  );
}

export function ScoreRing({score, size = 132}: {score: number; size?: number}) {
  const normalized = Math.max(0, Math.min(100, score));
  const radius = 46;
  const circumference = 2 * Math.PI * radius;
  const tone = normalized >= 80 ? "#fb7185" : normalized >= 55 ? "#fb923c" : normalized >= 30 ? "#f5c451" : "#54e6ae";
  return (
    <div className="relative shrink-0" style={{width: size, height: size}} role="img" aria-label={`Risk score ${normalized} out of 100`}>
      <svg className="-rotate-90" viewBox="0 0 112 112" aria-hidden="true">
        <circle cx="56" cy="56" r={radius} fill="none" stroke="rgba(166,202,190,.11)" strokeWidth="9"/>
        <circle
          cx="56"
          cy="56"
          r={radius}
          fill="none"
          stroke={tone}
          strokeWidth="9"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - normalized / 100)}
        />
      </svg>
      <div className="absolute inset-0 grid place-items-center text-center">
        <div>
          <p className="mono-data text-3xl font-semibold tracking-[-.06em]">{normalized}</p>
          <p className="text-[9px] uppercase tracking-[.16em] text-muted-foreground">risk score</p>
        </div>
      </div>
    </div>
  );
}

export function EmptyState({
  title,
  description,
  icon: Icon = Inbox,
  action,
}: {
  title: string;
  description: string;
  icon?: LucideIcon;
  action?: ReactNode;
}) {
  return (
    <div className="grid min-h-52 place-items-center px-6 py-10 text-center">
      <div className="max-w-sm">
        <span className="mx-auto grid size-11 place-items-center rounded-xl bg-muted text-muted-foreground ring-1 ring-border">
          <Icon className="size-5" strokeWidth={1.6}/>
        </span>
        <h3 className="mt-4 text-sm font-semibold">{title}</h3>
        <p className="mt-2 text-xs leading-5 text-muted-foreground">{description}</p>
        {action ? <div className="mt-4">{action}</div> : null}
      </div>
    </div>
  );
}

export function ErrorState({message, onRetry}: {message: string; onRetry?: () => void}) {
  return (
    <div className="grid min-h-44 place-items-center px-6 py-8 text-center" role="alert">
      <div className="max-w-sm">
        <CircleAlert className="mx-auto size-6 text-rose-300"/>
        <p className="mt-3 text-sm font-medium">Data could not be loaded</p>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">{message}</p>
        {onRetry ? <Button variant="outline" size="sm" className="mt-4" onClick={onRetry}><RefreshCw/>Retry</Button> : null}
      </div>
    </div>
  );
}

export function ViewAllLink({href, children = "View all"}: {href: string; children?: ReactNode}) {
  return (
    <Button variant="ghost" size="sm" asChild className="text-muted-foreground">
      <Link href={href}>{children}<ArrowUpRight className="size-3.5"/></Link>
    </Button>
  );
}

export function formatRelativeTime(value: string | null | undefined) {
  if (!value) return "not yet";
  const delta = Date.now() - new Date(value).getTime();
  if (delta < 60_000) return `${Math.max(1, Math.round(delta / 1000))}s ago`;
  if (delta < 3_600_000) return `${Math.round(delta / 60_000)}m ago`;
  if (delta < 86_400_000) return `${Math.round(delta / 3_600_000)}h ago`;
  return new Date(value).toLocaleDateString();
}

export function levelTone(level: string) {
  return level === "critical" ? "#fb7185" : level === "high" ? "#fb923c" : level === "medium" ? "#f5c451" : "#54e6ae";
}
