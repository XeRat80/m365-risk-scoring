"use client";

import {useInfiniteQuery, useMutation, useQueryClient} from "@tanstack/react-query";
import {Bell, Check, ExternalLink, ShieldAlert} from "lucide-react";
import Link from "next/link";
import {useState} from "react";
import {PageHeader, SectionHeading} from "@/components/risk-ui";
import {useRiskContext} from "@/components/risk-context";
import {Badge} from "@/components/ui/badge";
import {Button} from "@/components/ui/button";
import {Card, CardContent, CardHeader} from "@/components/ui/card";
import {request, type CursorPage, type SecurityAlert} from "@/lib/api";

type CloseReason = "resolved" | "false_positive" | "accepted_risk";

export function AlertsView() {
  const {session} = useRiskContext();
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<"open" | "closed" | "all">("open");
  const [reasons, setReasons] = useState<Record<string, CloseReason>>({});
  const alerts = useInfiniteQuery({
    queryKey: ["security-alerts", session.tenant, filter],
    initialPageParam: "",
    queryFn: ({pageParam}) => request<CursorPage<SecurityAlert>>(
      `/api/v1/alerts?limit=100${filter === "all" ? "" : `&soc_status=${filter}`}${pageParam ? `&cursor=${encodeURIComponent(pageParam)}` : ""}`,
      session.token,
    ),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    refetchInterval: 5_000,
  });
  const close = useMutation({
    mutationFn: ({id, selectedReason}: {id: string; selectedReason: CloseReason}) =>
      request<SecurityAlert>(`/api/v1/alerts/${encodeURIComponent(id)}/close`, session.token, {
        method: "POST", body: JSON.stringify({reason: selectedReason}),
      }),
    onSuccess: () => void queryClient.invalidateQueries({queryKey: ["security-alerts", session.tenant]}),
  });
  const all = alerts.data?.pages.flatMap((page) => page.items) ?? [];

  return (
    <div className="grid gap-5">
      <PageHeader eyebrow="SOC queue" title="Microsoft security alerts" description="Provider alerts collected during recurring scans. Analysts can close a local SOC case after review."/>
      <Card className="surface-panel">
        <CardHeader className="border-b">
          <SectionHeading title="Collected alerts" description="Provider status and SOC decision are tracked separately"/>
          <div className="flex flex-wrap gap-2" role="group" aria-label="Filter alerts">
            {(["open", "closed", "all"] as const).map((value) => (
              <Button key={value} size="sm" variant={filter === value ? "default" : "outline"} onClick={() => setFilter(value)} className="capitalize">{value}</Button>
            ))}
          </div>
        </CardHeader>
        <CardContent className="grid gap-3 pt-4">
          {alerts.isError ? <p role="alert" className="text-sm text-rose-200">Alerts could not be loaded. Check the API connection and retry.</p> : null}
          {close.isError ? <p role="alert" className="text-sm text-rose-200">The alert could not be closed. Retry after checking your access.</p> : null}
          {alerts.isLoading ? <p className="text-sm text-muted-foreground">Loading alerts…</p> : null}
          {!alerts.isLoading && !alerts.isError && !all.length ? (
            <p className="text-sm text-muted-foreground">No {filter === "all" ? "collected" : filter} alerts.</p>
          ) : null}
          {all.map((alert) => (
            <article key={alert.id} className="rounded-xl border border-border bg-white/[.025] p-4">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-0 space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    {alert.soc_status === "open" ? <ShieldAlert className="size-4 text-amber-300"/> : <Check className="size-4 text-primary"/>}
                    <span className="text-sm font-semibold">{alert.user_id ? "User-linked alert" : "Tenant alert"}</span>
                    <Badge variant="outline" className="capitalize">{alert.severity}</Badge>
                    <Badge variant="outline" className="capitalize">SOC: {alert.soc_status}</Badge>
                  </div>
                  <p className="mono-data break-all text-[10px] text-muted-foreground">{alert.id}</p>
                  <p className="text-xs text-muted-foreground">Microsoft status: {alert.provider_status} · {new Date(alert.created_at).toLocaleString()}</p>
                  {alert.user_id ? <Link href={`/users/${encodeURIComponent(alert.user_id)}`} className="inline-flex items-center gap-1 text-xs text-primary hover:underline">Investigate {alert.user_id}<ExternalLink className="size-3"/></Link> : null}
                  {alert.closure ? <p className="text-xs text-muted-foreground">Closed by {alert.closure.actor ?? "analyst"} · {alert.closure.reason?.replaceAll("_", " ") ?? "resolved"} · {alert.closure.closed_at ? new Date(alert.closure.closed_at).toLocaleString() : ""}</p> : null}
                </div>
                {alert.soc_status === "open" ? (
                  <div className="flex flex-wrap items-center gap-2">
                    <label className="text-xs text-muted-foreground" htmlFor={`reason-${alert.id}`}>Close reason</label>
                    <select id={`reason-${alert.id}`} value={reasons[alert.id] ?? "resolved"} onChange={(event) => setReasons((current) => ({...current, [alert.id]: event.target.value as CloseReason}))} className="h-9 rounded-lg border border-border bg-background px-2 text-xs">
                      <option value="resolved">Resolved</option>
                      <option value="false_positive">False positive</option>
                      <option value="accepted_risk">Accepted risk</option>
                    </select>
                    <Button size="sm" disabled={close.isPending} onClick={() => close.mutate({id: alert.id, selectedReason: reasons[alert.id] ?? "resolved"})}>Close alert</Button>
                  </div>
                ) : null}
              </div>
            </article>
          ))}
          {alerts.hasNextPage ? <Button variant="outline" disabled={alerts.isFetchingNextPage} onClick={() => void alerts.fetchNextPage()}>{alerts.isFetchingNextPage ? "Loading…" : "Load more alerts"}</Button> : null}
        </CardContent>
      </Card>
      <p className="flex items-center gap-2 text-xs text-muted-foreground"><Bell className="size-3.5"/>Closing an alert records a local SOC decision; it does not resolve it in Microsoft or change the user risk score.</p>
    </div>
  );
}
