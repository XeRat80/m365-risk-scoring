"use client";

import {ArrowRight, Gauge, MailWarning, ShieldAlert, Users} from "lucide-react";
import {useQuery} from "@tanstack/react-query";
import Link from "next/link";
import {useMemo, useState} from "react";
import {
  Area,
  AreaChart,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from "recharts";
import {MailTelemetry} from "@/components/mail-telemetry";
import {RiskDetail} from "@/components/risk-detail";
import {RiskTable} from "@/components/risk-table";
import {SyncStatus} from "@/components/sync-status";
import {PageHeader, SectionHeading, StatCard, ViewAllLink, formatRelativeTime, levelTone} from "@/components/risk-ui";
import {useRiskContext} from "@/components/risk-context";
import {Alert, AlertDescription, AlertTitle} from "@/components/ui/alert";
import {Badge} from "@/components/ui/badge";
import {Button} from "@/components/ui/button";
import {Card, CardContent, CardHeader} from "@/components/ui/card";
import {
  request,
  type CursorPage,
  type MailEvent,
  type Risk,
  type SyncJob,
  type UserSummary,
} from "@/lib/api";

const TOOLTIP = {
  background: "#0b1714",
  border: "1px solid rgba(166,202,190,.18)",
  borderRadius: 10,
  fontSize: 12,
};

function trendData(risks: Risk[]) {
  const sorted = [...risks].sort((a, b) => new Date(a.calculated_at).getTime() - new Date(b.calculated_at).getTime());
  const buckets = new Map<string, {sum: number; count: number; urgent: number}>();
  for (const risk of sorted) {
    const key = new Date(risk.calculated_at).toLocaleDateString(undefined, {month: "short", day: "numeric"});
    const bucket = buckets.get(key) ?? {sum: 0, count: 0, urgent: 0};
    bucket.sum += risk.score;
    bucket.count += 1;
    bucket.urgent += risk.score >= 55 ? 1 : 0;
    buckets.set(key, bucket);
  }
  return [...buckets.entries()].slice(-18).map(([date, value]) => ({
    date,
    score: Number((value.sum / value.count).toFixed(1)),
    urgent: value.urgent,
  }));
}

export function OverviewView() {
  const {
    session,
    summary,
    connection,
    stale,
    commonError,
    startOnboarding,
  } = useRiskContext();
  const [selected, setSelected] = useState("user-001");

  const users = useQuery({
    queryKey: ["users", session.tenant],
    queryFn: () => request<CursorPage<UserSummary>>("/api/v1/users?limit=100", session.token),
    refetchInterval: 5_000,
  });
  const risks = useQuery({
    queryKey: ["risks", session.tenant],
    queryFn: () => request<CursorPage<Risk>>("/api/v1/risks?limit=100", session.token),
    refetchInterval: 5_000,
  });
  const mail = useQuery({
    queryKey: ["mail-events", session.tenant],
    queryFn: () => request<{items: MailEvent[]}>("/api/v1/mail/events?limit=24", session.token),
    refetchInterval: 2_000,
  });
  const syncs = useQuery({
    queryKey: ["sync-jobs", session.tenant],
    queryFn: () => request<CursorPage<SyncJob>>("/api/v1/sync/jobs?limit=50", session.token),
    refetchInterval: 5_000,
  });

  const data = summary ?? {users: 0, critical: 0, high: 0, medium: 0, low: 0, average_score: 0, last_sync_at: null};
  const urgentMail = (mail.data?.items ?? []).filter((event) => event.risk_probability >= .7).length;
  const trend = useMemo(() => trendData(risks.data?.items ?? []), [risks.data?.items]);
  const distribution = [
    {name: "Critical", value: data.critical, color: levelTone("critical")},
    {name: "High", value: data.high, color: levelTone("high")},
    {name: "Medium", value: data.medium, color: levelTone("medium")},
    {name: "Low", value: data.low, color: levelTone("low")},
  ];

  return (
    <div className="grid gap-5">
      <PageHeader
        eyebrow={`${session.tenant} · ${session.role}`}
        title="User risk overview"
        description="A live operating picture across mail integrity, communication behavior and identity posture."
        actions={
          <>
            <Badge variant="outline" className="h-8 gap-1.5 border-primary/20 bg-primary/[.05] text-primary">
              <span className="status-pulse size-1.5 rounded-full bg-primary"/>System live
            </Badge>
            <Button variant="outline" asChild><Link href="/users">Open investigation queue<ArrowRight/></Link></Button>
          </>
        }
      />

      {stale ? (
        <Alert className="border-amber-400/20 bg-amber-400/[.06] text-amber-100">
          <ShieldAlert/>
          <AlertTitle>Freshness warning</AlertTitle>
          <AlertDescription>Data is stale or synchronization is still completing.</AlertDescription>
        </Alert>
      ) : null}
      {commonError || users.isError || mail.isError || risks.isError ? (
        <Alert variant="destructive">
          <ShieldAlert/>
          <AlertTitle>Refresh failed</AlertTitle>
          <AlertDescription>Risk data could not be refreshed. Verify API and connector health.</AlertDescription>
        </Alert>
      ) : null}
      <section className="grid grid-cols-2 gap-3 lg:grid-cols-4" aria-label="Risk metrics">
        <StatCard label="Protected users" value={data.users} detail={`${data.low} currently low risk`} icon={Users} trend="tenant scope"/>
        <StatCard
          label="Urgent queue"
          value={data.critical + data.high}
          detail="Critical and high-risk identities"
          icon={ShieldAlert}
          tone="danger"
          trend={data.critical ? `${data.critical} critical` : `${data.high} high`}
        />
        <StatCard label="Average score" value={data.average_score.toFixed(1)} detail="Across the latest user scores" icon={Gauge} tone="warning" trend="/ 100"/>
        <StatCard label="High-risk mail" value={urgentMail} detail="Among the latest 24 metadata events" icon={MailWarning} tone="info" trend="live"/>
      </section>

      <section className="grid gap-4 xl:grid-cols-[.72fr_1.28fr]">
        <Card className="surface-panel">
          <CardHeader className="border-b">
            <SectionHeading title="Risk distribution" description="Latest tenant posture by risk band" action={<ViewAllLink href="/users">All users</ViewAllLink>}/>
          </CardHeader>
          <CardContent className="grid items-center gap-2 pt-1 sm:grid-cols-[1fr_160px] xl:grid-cols-1 2xl:grid-cols-[1fr_150px]">
            <div className="relative h-56">
              <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{width: 720, height: 240}}>
                <PieChart>
                  <Pie data={distribution} dataKey="value" nameKey="name" innerRadius={60} outerRadius={88} paddingAngle={2} stroke="none">
                    {distribution.map((entry) => <Cell key={entry.name} fill={entry.color}/>)}
                  </Pie>
                  <RechartsTooltip contentStyle={TOOLTIP}/>
                </PieChart>
              </ResponsiveContainer>
              <div className="pointer-events-none absolute inset-0 grid place-items-center text-center">
                <div>
                  <p className="mono-data text-3xl font-semibold">{data.users}</p>
                  <p className="text-[9px] uppercase tracking-[.14em] text-muted-foreground">identities</p>
                </div>
              </div>
            </div>
            <div className="grid gap-2">
              {distribution.map((item) => (
                <div key={item.name} className="flex items-center justify-between gap-4 rounded-lg bg-white/[.025] px-3 py-2">
                  <span className="flex items-center gap-2 text-xs text-muted-foreground"><span className="size-2 rounded-sm" style={{background: item.color}}/>{item.name}</span>
                  <strong className="mono-data text-xs">{item.value}</strong>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card className="surface-panel">
          <CardHeader className="border-b">
            <SectionHeading title="Tenant risk movement" description="Average score across the latest scoring activity" action={<span className="mono-data text-[10px] text-muted-foreground">updated {formatRelativeTime(data.last_sync_at)}</span>}/>
          </CardHeader>
          <CardContent className="pt-3">
            <div className="h-[286px]" role="img" aria-label="Average tenant risk score trend">
              <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{width: 720, height: 240}}>
                <AreaChart data={trend} margin={{top: 12, right: 8, bottom: 0, left: -24}}>
                  <defs>
                    <linearGradient id="riskArea" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#54e6ae" stopOpacity={.24}/>
                      <stop offset="100%" stopColor="#54e6ae" stopOpacity={0}/>
                    </linearGradient>
                  </defs>
                  <XAxis dataKey="date" stroke="#6f827b" tick={{fontSize: 10}} axisLine={false} tickLine={false} interval="preserveStartEnd"/>
                  <YAxis domain={[0, 100]} stroke="#6f827b" tick={{fontSize: 10}} axisLine={false} tickLine={false}/>
                  <RechartsTooltip contentStyle={TOOLTIP}/>
                  <Area type="monotone" dataKey="score" stroke="#54e6ae" strokeWidth={2.2} fill="url(#riskArea)" dot={false} activeDot={{r: 3, fill: "#54e6ae"}}/>
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
      </section>

      <section className="grid items-start gap-4 2xl:grid-cols-[minmax(0,1.55fr)_minmax(390px,.75fr)]">
        <div className="min-w-0">
          <RiskTable users={users.data?.items ?? []} selected={selected} onSelect={setSelected}/>
          <RiskDetail token={session.token} userId={selected}/>
        </div>
        <MailTelemetry events={mail.data?.items ?? []} loading={mail.isLoading} onSelect={setSelected}/>
      </section>

      <section className="grid items-start gap-4 lg:grid-cols-2">
        <SyncStatus
          jobs={syncs.data?.items ?? []}
          connection={connection}
          isAdmin={session.role === "admin"}
          onConnect={startOnboarding}
        />
        <Card className="surface-panel">
          <CardHeader className="border-b"><SectionHeading title="Operational handoff" description="Where to continue from the overview"/></CardHeader>
          <CardContent className="grid gap-2">
            {[
              ["/users", "Investigate identities", "Filter the complete user population and open a dedicated evidence page."],
              ["/mail", "Inspect header telemetry", "Analyze authentication outcomes, probability bands and metadata."],
              ["/models", "Review model promotion", "Compare candidates and inspect every production gate."],
            ].map(([href, label, description]) => (
              <Link key={href} href={href} className="group rounded-xl bg-white/[.025] p-3 ring-1 ring-border transition hover:-translate-y-0.5 hover:bg-white/[.045]">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-xs font-semibold group-hover:text-primary">{label}</p>
                  <ArrowRight className="size-3.5 text-muted-foreground group-hover:text-primary"/>
                </div>
                <p className="mt-1.5 text-[11px] leading-4 text-muted-foreground">{description}</p>
              </Link>
            ))}
          </CardContent>
        </Card>
      </section>
    </div>
  );
}
