"use client";

import {Activity, CheckCircle2, Cloud, Play, RefreshCw, Server, ShieldCheck, TimerReset, TriangleAlert} from "lucide-react";
import {useMutation, useQuery, useQueryClient} from "@tanstack/react-query";
import {useMemo} from "react";
import {Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip as RechartsTooltip, XAxis, YAxis} from "recharts";
import {PageHeader, SectionHeading, StatCard, formatRelativeTime} from "@/components/risk-ui";
import {useRiskContext} from "@/components/risk-context";
import {Alert, AlertDescription, AlertTitle} from "@/components/ui/alert";
import {Badge} from "@/components/ui/badge";
import {Button} from "@/components/ui/button";
import {Card, CardContent, CardHeader} from "@/components/ui/card";
import {request, type CursorPage, type SyncJob} from "@/lib/api";
import {cn} from "@/lib/utils";

const TOOLTIP = {background: "#0b1714", border: "1px solid rgba(166,202,190,.18)", borderRadius: 10, fontSize: 12};

export function OperationsView() {
  const {session, connection, model, summary, stale, startOnboarding, onboardingBusy} = useRiskContext();
  const queryClient = useQueryClient();
  const syncs = useQuery({
    queryKey: ["sync-jobs", session.tenant],
    queryFn: () => request<CursorPage<SyncJob>>("/api/v1/sync/jobs?limit=100", session.token),
    refetchInterval: 3_000,
  });
  const health = useQuery({
    queryKey: ["health-ready"],
    queryFn: () => request<{status: string; connector: string}>("/health/ready", session.token),
    refetchInterval: 10_000,
    retry: 1,
  });
  const startSync = useMutation({
    mutationFn: () => request<SyncJob>("/api/v1/sync", session.token, {method: "POST", headers: {"Idempotency-Key": crypto.randomUUID()}}),
    onSuccess: () => void queryClient.invalidateQueries({queryKey: ["sync-jobs", session.tenant]}),
  });

  const jobs = useMemo(() => syncs.data?.items ?? [], [syncs.data?.items]);
  const completed = jobs.filter((job) => job.status === "completed").length;
  const retrying = jobs.filter((job) => job.status === "retrying").length;
  const failed = jobs.filter((job) => job.status === "failed" || Boolean(job.error)).length;
  const successRate = jobs.length ? Math.round(completed / jobs.length * 100) : 0;
  const durationValues = jobs
    .filter((job) => job.completed_at)
    .map((job) => new Date(job.completed_at!).getTime() - new Date(job.created_at).getTime())
    .filter((value) => value >= 0);
  const medianDuration = durationValues.length ? durationValues.toSorted((a, b) => a - b)[Math.floor(durationValues.length / 2)] : 0;
  const statusChart = useMemo(() => [
    {status: "Completed", count: completed, color: "#54e6ae"},
    {status: "Running", count: jobs.filter((job) => job.status === "running").length, color: "#78a4ff"},
    {status: "Queued", count: jobs.filter((job) => job.status === "queued").length, color: "#a997ff"},
    {status: "Retrying", count: retrying, color: "#f4b45f"},
    {status: "Failed", count: failed, color: "#fb7185"},
  ], [completed, failed, jobs, retrying]);

  const readiness = [
    {label: "API process", value: health.data?.status === "ready" ? "ready" : health.isError ? "unavailable" : "checking", healthy: health.data?.status === "ready"},
    {label: "PostgreSQL", value: health.data?.status === "ready" ? "reachable" : "checking", healthy: health.data?.status === "ready"},
    {label: "Connector", value: connection?.status ?? "checking", healthy: connection?.status === "connected"},
    {label: "Model bundle", value: model ? `${model.version} loaded` : "checking", healthy: Boolean(model)},
    {label: "Data freshness", value: stale ? "stale" : "current", healthy: !stale},
  ];

  return (
    <div className="grid gap-5">
      <PageHeader
        eyebrow="System operations"
        title="Connector and synchronization health"
        description="Operate the durable PostgreSQL queue, inspect retries and verify every dependency behind the analyst experience."
        actions={
          <>
            <Badge variant="outline" className={cn("h-8 gap-1.5", health.data?.status === "ready" ? "border-primary/20 text-primary" : "border-rose-400/20 text-rose-200")}><span className={cn("size-1.5 rounded-full", health.data?.status === "ready" ? "status-pulse bg-primary" : "bg-rose-400")}/>{health.data?.status ?? "checking"}</Badge>
            <Button variant="outline" disabled={startSync.isPending || session.role !== "admin"} onClick={() => startSync.mutate()}><Play/>Run delta sync</Button>
          </>
        }
      />

      {startSync.isError ? <Alert variant="destructive"><TriangleAlert/><AlertTitle>Synchronization could not be queued</AlertTitle><AlertDescription>Confirm administrator access and inspect the API request log.</AlertDescription></Alert> : null}

      <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard label="Queue success" value={`${successRate}%`} detail={`${completed} of ${jobs.length} recent jobs completed`} icon={CheckCircle2}/>
        <StatCard label="Median duration" value={medianDuration ? `${(medianDuration / 1000).toFixed(1)}s` : "—"} detail="Create-to-complete duration" icon={TimerReset} tone="info"/>
        <StatCard label="Retrying jobs" value={retrying} detail="Bounded exponential backoff" icon={RefreshCw} tone="warning"/>
        <StatCard label="Failed jobs" value={failed} detail="Require operator review" icon={TriangleAlert} tone="danger"/>
      </section>

      <section className="grid items-start gap-4 xl:grid-cols-[.78fr_1.22fr]">
        <div className="grid gap-4">
          <Card className="surface-panel">
            <CardHeader className="border-b"><SectionHeading title="Connector" description="Tenant-scoped Microsoft Graph adapter"/></CardHeader>
            <CardContent className="grid gap-5">
              <div className="flex items-start justify-between gap-4">
                <div className="flex items-center gap-3">
                  <span className="grid size-10 place-items-center rounded-xl bg-primary/10 text-primary ring-1 ring-primary/15"><Cloud className="size-5"/></span>
                  <div><p className="text-sm font-semibold">{connection?.provider ?? "Checking provider"}</p><p className="mt-1 text-[10px] capitalize text-muted-foreground">{connection?.mode ?? "unknown"} mode · {connection?.status ?? "checking"}</p></div>
                </div>
                <Badge variant="outline" className={connection?.status === "connected" ? "border-primary/20 text-primary" : "border-rose-400/20 text-rose-200"}>{connection?.status ?? "checking"}</Badge>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-[.15em] text-muted-foreground">Granted scopes</p>
                <div className="mt-3 flex flex-wrap gap-1.5">{(connection?.scopes ?? []).map((scope) => <Badge key={scope} variant="outline" className="mono-data h-6 text-[9px]">{scope}</Badge>)}</div>
              </div>
              {connection?.status !== "connected" && session.role === "admin" ? <Button variant="outline" disabled={onboardingBusy} onClick={startOnboarding}>Start admin consent</Button> : null}
            </CardContent>
          </Card>

          <Card className="surface-panel">
            <CardHeader className="border-b"><SectionHeading title="Dependency readiness" description="Independent checks behind /health/ready"/></CardHeader>
            <CardContent className="grid gap-1 pt-1">
              {readiness.map((item) => (
                <div key={item.label} className="flex items-center justify-between gap-4 border-b py-3 last:border-0">
                  <span className="flex items-center gap-2 text-xs"><span className={cn("size-1.5 rounded-full", item.healthy ? "bg-primary" : "bg-amber-300")}/>{item.label}</span>
                  <span className="mono-data text-[10px] capitalize text-muted-foreground">{item.value}</span>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>

        <Card className="surface-panel">
          <CardHeader className="border-b"><SectionHeading title="Queue outcomes" description="Status mix across the latest 100 durable jobs"/></CardHeader>
          <CardContent className="pt-4">
            <div className="h-[356px]" role="img" aria-label="Synchronization jobs by status">
              <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{width: 720, height: 240}}>
                <BarChart data={statusChart} margin={{top: 12, right: 10, left: -18, bottom: 0}}>
                  <CartesianGrid vertical={false} stroke="rgba(166,202,190,.07)"/>
                  <XAxis dataKey="status" axisLine={false} tickLine={false} tick={{fontSize: 10, fill: "#91a59e"}}/>
                  <YAxis allowDecimals={false} axisLine={false} tickLine={false} tick={{fontSize: 10, fill: "#91a59e"}}/>
                  <RechartsTooltip contentStyle={TOOLTIP}/>
                  <Bar dataKey="count" radius={[6, 6, 0, 0]} barSize={42}>{statusChart.map((entry) => <Cell key={entry.status} fill={entry.color}/>)}</Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="mt-3 grid gap-2 sm:grid-cols-3">
              <div className="evidence-stat"><span>Latest completed</span><strong className="text-sm">{formatRelativeTime(jobs.find((job) => job.completed_at)?.completed_at)}</strong></div>
              <div className="evidence-stat"><span>Last tenant sync</span><strong className="text-sm">{formatRelativeTime(summary?.last_sync_at)}</strong></div>
              <div className="evidence-stat"><span>Queue engine</span><strong className="text-sm">PostgreSQL</strong></div>
            </div>
          </CardContent>
        </Card>
      </section>

      <Card className="surface-panel">
        <CardHeader className="border-b"><SectionHeading title="Synchronization jobs" description="Durable queue state, attempts, retries and operator-visible errors"/></CardHeader>
        <CardContent className="px-0">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b text-muted-foreground"><tr><th className="px-5 py-3 font-medium">Job</th><th className="px-3 py-3 font-medium">Created</th><th className="px-3 py-3 font-medium">Status</th><th className="px-3 py-3 font-medium">Attempt</th><th className="px-3 py-3 font-medium">Next action</th><th className="px-5 py-3 text-right font-medium">Error</th></tr></thead>
              <tbody>
                {jobs.map((job) => (
                  <tr key={job.id} className="border-b last:border-0 hover:bg-white/[.02]">
                    <td className="mono-data px-5 py-3 text-[10px]">{job.id.slice(0, 12)}</td>
                    <td className="mono-data px-3 py-3 text-[10px] text-muted-foreground">{new Date(job.created_at).toLocaleString()}</td>
                    <td className="px-3 py-3"><Badge variant="outline" className={cn("capitalize", job.status === "completed" ? "border-primary/20 text-primary" : job.status === "retrying" ? "border-amber-400/20 text-amber-100" : job.error ? "border-rose-400/20 text-rose-200" : "")}>{job.status}</Badge></td>
                    <td className="mono-data px-3 py-3">{job.attempt}</td>
                    <td className="mono-data px-3 py-3 text-[10px] text-muted-foreground">{job.completed_at ? `completed ${formatRelativeTime(job.completed_at)}` : `retry ${new Date(job.next_attempt_at).toLocaleTimeString()}`}</td>
                    <td className="max-w-64 truncate px-5 py-3 text-right text-rose-200">{job.error ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      <section className="grid gap-3 md:grid-cols-3">
        {[
          [Server, "Read API SLO", "< 300 ms p95", "Measured separately by the acceptance benchmark."],
          [Activity, "Processing SLO", "≥ 1,000 events/min", "Worker queue remains resumable across restarts."],
          [ShieldCheck, "Dashboard freshness", "≤ 10 seconds", "Scenario starts enqueue synchronization immediately."],
        ].map(([Icon, title, target, description]) => {
          const IconComponent = Icon as typeof Server;
          return <Card key={String(title)} className="surface-panel"><CardContent className="flex gap-3 p-4"><IconComponent className="mt-0.5 size-4 shrink-0 text-primary"/><div><p className="text-xs font-semibold">{title as string}</p><p className="mono-data mt-1 text-lg">{target as string}</p><p className="mt-1 text-[10px] leading-4 text-muted-foreground">{description as string}</p></div></CardContent></Card>;
        })}
      </section>
    </div>
  );
}
