"use client";

import {Activity, AlertTriangle, CircleDot, Database, GitBranch, Mail, Network, Shield, UserRound} from "lucide-react";
import {useQuery} from "@tanstack/react-query";
import {useMemo, useState} from "react";
import {PageHeader, SectionHeading} from "@/components/risk-ui";
import {useRiskContext} from "@/components/risk-context";
import {Badge} from "@/components/ui/badge";
import {Card, CardContent, CardHeader} from "@/components/ui/card";
import {Select, SelectContent, SelectItem, SelectTrigger, SelectValue} from "@/components/ui/select";
import {request, type CursorPage, type RiskGraphNode, type UserRiskGraph, type UserSummary} from "@/lib/api";
import {cn} from "@/lib/utils";

const PATHS = {
  all: {label: "All evidence paths", prefixes: []},
  mail: {label: "Mail → email threat", prefixes: ["mail:", "feature:email_", "component:email_"]},
  identity: {label: "Sign-in → identity", prefixes: ["signin:", "feature:identity_", "component:identity_"]},
  posture: {label: "MFA & privilege posture", prefixes: ["feature:mfa_", "feature:privilege_", "component:mfa_", "component:privilege_"]},
  endpoint: {label: "Alert → endpoint", prefixes: ["alert:", "feature:endpoint_", "component:endpoint_"]},
} as const;

function valueLabel(value: RiskGraphNode["value"]) {
  if (value === null) return "Unavailable";
  if (typeof value === "number") return `${Math.round(value * 100)}%`;
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return value;
}

function statusClass(status: RiskGraphNode["status"]) {
  if (status === "unavailable") return "border-slate-400/20 text-slate-300";
  if (status === "insufficient_history") return "border-amber-400/20 text-amber-100";
  return "border-primary/20 text-primary";
}

function nodeIcon(node: RiskGraphNode) {
  if (node.kind === "employee") return UserRound;
  if (node.kind === "feature") return GitBranch;
  if (node.kind === "component") return Shield;
  if (node.id.startsWith("mail:")) return Mail;
  if (node.id.startsWith("signin:")) return Activity;
  if (node.id.startsWith("alert:")) return AlertTriangle;
  return CircleDot;
}

export function GraphView() {
  const {session} = useRiskContext();
  const [chosenUser, setChosenUser] = useState("");
  const [path, setPath] = useState<keyof typeof PATHS>("all");
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const users = useQuery({
    queryKey: ["users", session.tenant],
    queryFn: () => request<CursorPage<UserSummary>>("/api/v1/users?limit=100", session.token),
  });
  const userId = chosenUser || users.data?.items[0]?.id || "";
  const graph = useQuery({
    queryKey: ["risk-graph", session.tenant, userId],
    queryFn: () => request<UserRiskGraph>(`/api/v1/users/${userId}/risk-graph`, session.token),
    enabled: Boolean(userId),
    refetchInterval: 5_000,
  });

  const visibleIds = useMemo(() => {
    if (!graph.data || path === "all") return new Set(graph.data?.nodes.map((node) => node.id) ?? []);
    const prefixes = PATHS[path].prefixes;
    return new Set(
      graph.data.nodes
        .filter((node) => node.kind === "employee" || prefixes.some((prefix) => node.id.startsWith(prefix)))
        .map((node) => node.id),
    );
  }, [graph.data, path]);
  const visibleNodes = graph.data?.nodes.filter((node) => visibleIds.has(node.id)) ?? [];
  const visibleEdges = graph.data?.edges.filter((edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target)) ?? [];
  const columns = {
    observation: visibleNodes.filter((node) => node.kind === "employee" || node.kind === "observation"),
    feature: visibleNodes.filter((node) => node.kind === "feature"),
    component: visibleNodes.filter((node) => node.kind === "component"),
  };
  const selected = visibleNodes.find((node) => node.id === selectedNodeId) ?? visibleNodes[0];
  const activeUser = users.data?.items.find((user) => user.id === userId);

  return (
    <div className="grid gap-5">
      <PageHeader
        eyebrow="V2 explainability"
        title="Field data graph"
        description="Follow privacy-safe observations through canonical features to the five final risk components. Features are properties in the scoring pipeline—not duplicated database entities."
        actions={<Badge variant="outline" className="h-8 gap-2 border-primary/20 text-primary"><Network className="size-3.5"/>Shadow mode V2</Badge>}
      />

      <Card className="surface-panel">
        <CardContent className="grid gap-3 pt-1 sm:grid-cols-2 xl:grid-cols-[1fr_1fr_auto] xl:items-end">
          <label className="grid gap-1.5 text-[10px] uppercase tracking-[.14em] text-muted-foreground">
            Employee
            <Select value={userId} onValueChange={(value) => {setChosenUser(value); setSelectedNodeId("");}}>
              <SelectTrigger aria-label="Select employee" className="h-10 w-full bg-black/10"><SelectValue placeholder="Select an employee"/></SelectTrigger>
              <SelectContent>{(users.data?.items ?? []).map((user) => <SelectItem key={user.id} value={user.id}>{user.display_name} · {user.id}</SelectItem>)}</SelectContent>
            </Select>
          </label>
          <label className="grid gap-1.5 text-[10px] uppercase tracking-[.14em] text-muted-foreground">
            Evidence path
            <Select value={path} onValueChange={(value) => {setPath(value as keyof typeof PATHS); setSelectedNodeId("");}}>
              <SelectTrigger aria-label="Filter evidence path" className="h-10 w-full bg-black/10"><SelectValue/></SelectTrigger>
              <SelectContent>{Object.entries(PATHS).map(([key, item]) => <SelectItem key={key} value={key}>{item.label}</SelectItem>)}</SelectContent>
            </Select>
          </label>
          <div className="flex h-10 items-center gap-3 rounded-lg border bg-black/10 px-3 text-xs">
            <span className="text-muted-foreground">V2 score</span>
            <span className="mono-data ml-auto text-lg font-semibold">{graph.data?.score ?? "—"}</span>
            <Badge variant="outline" className="capitalize">{graph.data?.level?.replaceAll("_", " ") ?? "pending"}</Badge>
          </div>
        </CardContent>
      </Card>

      {graph.isError ? (
        <Card className="border-amber-400/20 bg-amber-400/[.04]"><CardContent className="flex gap-3 p-5 text-sm text-amber-100"><AlertTriangle className="size-4 shrink-0"/>The V2 graph is not available yet. Run a synchronization to build the employee feature window.</CardContent></Card>
      ) : null}

      <section className="grid items-start gap-4 2xl:grid-cols-[minmax(0,1fr)_360px]">
        <Card className="surface-panel min-w-0">
          <CardHeader className="border-b">
            <SectionHeading title={activeUser ? `${activeUser.display_name} evidence flow` : "Evidence flow"} description={`${visibleNodes.length} nodes · ${visibleEdges.length} traceable relationships`}/>
            <div className="mt-3 flex flex-wrap gap-3 text-[10px] text-muted-foreground">
              <span className="flex items-center gap-1.5"><span className="size-2 rounded-full bg-sky-300"/>Observation</span>
              <span className="flex items-center gap-1.5"><span className="size-2 rounded-full bg-violet-300"/>Canonical feature</span>
              <span className="flex items-center gap-1.5"><span className="size-2 rounded-full bg-primary"/>Final component</span>
            </div>
          </CardHeader>
          <CardContent className="overflow-x-auto pt-4">
            <div className="grid min-w-[780px] grid-cols-[1fr_34px_1fr_34px_1fr] gap-2" role="group" aria-label="Risk evidence graph">
              {(["Observations", "Canonical features", "Final components"] as const).map((title, index) => (
                <div key={title} className={cn("mb-1 text-[10px] font-semibold uppercase tracking-[.16em] text-muted-foreground", index === 0 ? "col-start-1" : index === 1 ? "col-start-3" : "col-start-5")}>{title}</div>
              ))}
              {(["observation", "feature", "component"] as const).map((column, index) => (
                <div key={column} className={cn("grid content-start gap-2", index === 0 ? "col-start-1" : index === 1 ? "col-start-3" : "col-start-5")}>
                  {columns[column].map((node) => {
                    const Icon = nodeIcon(node);
                    return (
                      <button
                        key={node.id}
                        onClick={() => setSelectedNodeId(node.id)}
                        className={cn("rounded-lg border bg-black/10 p-3 text-left transition hover:border-primary/30 hover:bg-primary/[.035] focus-visible:ring-2 focus-visible:ring-ring", selected?.id === node.id && "border-primary/40 bg-primary/[.05]")}
                        aria-pressed={selected?.id === node.id}
                      >
                        <span className="flex items-start gap-2.5">
                          <span className={cn("grid size-7 shrink-0 place-items-center rounded-md border", node.kind === "observation" || node.kind === "employee" ? "border-sky-300/20 text-sky-200" : node.kind === "feature" ? "border-violet-300/20 text-violet-200" : "border-primary/20 text-primary")}><Icon className="size-3.5"/></span>
                          <span className="min-w-0 flex-1"><span className="block text-xs font-medium">{node.label}</span><span className="mono-data mt-1 block truncate text-[9px] text-muted-foreground">{node.id}</span></span>
                          <span className="mono-data text-[11px] font-semibold">{node.kind === "employee" ? "Entity" : valueLabel(node.value)}</span>
                        </span>
                        {node.status !== "available" ? <Badge variant="outline" className={cn("mt-2 h-5 text-[9px]", statusClass(node.status))}>{node.status.replaceAll("_", " ")}</Badge> : null}
                      </button>
                    );
                  })}
                  {!columns[column].length ? <div className="rounded-lg border border-dashed p-5 text-center text-xs text-muted-foreground">No nodes on this path</div> : null}
                </div>
              ))}
              <div className="col-start-2 row-start-2 grid place-items-center text-muted-foreground" aria-hidden="true">→</div>
              <div className="col-start-4 row-start-2 grid place-items-center text-muted-foreground" aria-hidden="true">→</div>
            </div>
          </CardContent>
        </Card>

        <div className="sticky top-20 grid gap-4">
          <Card className="surface-panel">
            <CardHeader className="border-b"><SectionHeading title="Node inspector" description="Selected node and provenance"/></CardHeader>
            <CardContent>
              {selected ? (
                <div className="grid gap-4">
                  <div><Badge variant="outline" className="capitalize">{selected.kind}</Badge><h3 className="mt-3 text-base font-semibold">{selected.label}</h3><p className="mono-data mt-1 break-all text-[9px] text-muted-foreground">{selected.id}</p></div>
                  <dl className="grid gap-2 text-xs">
                    <div className="flex justify-between gap-4 border-b pb-2"><dt className="text-muted-foreground">Value</dt><dd className="font-medium">{selected.kind === "employee" ? "Entity" : valueLabel(selected.value)}</dd></div>
                    <div className="flex justify-between gap-4 border-b pb-2"><dt className="text-muted-foreground">Coverage</dt><dd className="capitalize">{selected.status.replaceAll("_", " ")}</dd></div>
                    <div className="flex justify-between gap-4 border-b pb-2"><dt className="text-muted-foreground">Observed</dt><dd className="text-right">{selected.observed_at ? new Date(selected.observed_at).toLocaleString() : "Derived window"}</dd></div>
                  </dl>
                  {Object.keys(selected.metadata).length ? <div><p className="mb-2 text-[10px] uppercase tracking-[.15em] text-muted-foreground">Safe metadata</p><div className="rounded-lg border bg-black/10 p-3 font-mono text-[10px] leading-5 text-muted-foreground">{Object.entries(selected.metadata).map(([key, value]) => <p key={key}>{key}: {String(value)}</p>)}</div></div> : null}
                </div>
              ) : <p className="py-12 text-center text-xs text-muted-foreground">Select a graph node to inspect it.</p>}
            </CardContent>
          </Card>
          <Card className="privacy-panel"><CardContent className="flex gap-3 p-4"><Database className="mt-0.5 size-4 shrink-0 text-primary"/><div><p className="text-xs font-semibold">PostgreSQL-backed logical graph</p><p className="mt-1 text-[11px] leading-5 text-muted-foreground">Nodes are normalized observations and entities. Features stay versioned properties; raw IPs, mail bodies and subjects are not persisted.</p></div></CardContent></Card>
        </div>
      </section>
    </div>
  );
}
