"use client";

import {ArrowDownAZ, ChevronRight, KeyRound, Search, ShieldCheck, ShieldOff, UserRoundCog, Users} from "lucide-react";
import {useQuery} from "@tanstack/react-query";
import Link from "next/link";
import {useMemo, useState} from "react";
import {Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip as RechartsTooltip, XAxis, YAxis} from "recharts";
import {PageHeader, RiskBadge, SectionHeading, StatCard, levelTone} from "@/components/risk-ui";
import {useRiskContext} from "@/components/risk-context";
import {Badge} from "@/components/ui/badge";
import {Button} from "@/components/ui/button";
import {Card, CardContent, CardHeader} from "@/components/ui/card";
import {Input} from "@/components/ui/input";
import {Select, SelectContent, SelectItem, SelectTrigger, SelectValue} from "@/components/ui/select";
import {Table, TableBody, TableCell, TableHead, TableHeader, TableRow} from "@/components/ui/table";
import {request, type CursorPage, type UserSummary} from "@/lib/api";

const TOOLTIP = {background: "#0b1714", border: "1px solid rgba(166,202,190,.18)", borderRadius: 10, fontSize: 12};

export function UsersView() {
  const {session, summary} = useRiskContext();
  const [search, setSearch] = useState("");
  const [level, setLevel] = useState("all");
  const [posture, setPosture] = useState("all");
  const [sort, setSort] = useState("risk-desc");
  const [page, setPage] = useState(1);
  const users = useQuery({
    queryKey: ["users", session.tenant],
    queryFn: () => request<CursorPage<UserSummary>>("/api/v1/users?limit=100", session.token),
    refetchInterval: 5_000,
  });

  const all = useMemo(() => users.data?.items ?? [], [users.data?.items]);
  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const result = all.filter((user) => {
      const matchesSearch = !needle || `${user.display_name} ${user.id}`.toLowerCase().includes(needle);
      const matchesLevel = level === "all" || user.level === level;
      const matchesPosture =
        posture === "all" ||
        (posture === "mfa-ready" && user.is_mfa_registered) ||
        (posture === "mfa-missing" && !user.is_mfa_registered) ||
        (posture === "admin" && user.is_admin) ||
        (posture === "entra-risk" && user.entra_risk_level !== "none");
      return matchesSearch && matchesLevel && matchesPosture;
    });
    return result.toSorted((left, right) => {
      if (sort === "risk-asc") return left.score - right.score;
      if (sort === "name") return left.display_name.localeCompare(right.display_name);
      return right.score - left.score;
    });
  }, [all, level, posture, search, sort]);

  const mfaReady = all.filter((user) => user.is_mfa_registered).length;
  const admins = all.filter((user) => user.is_admin).length;
  const identityRisk = all.filter((user) => user.entra_risk_level !== "none").length;
  const bands = ["critical", "high", "medium", "low"].map((band) => ({
    band: band[0].toUpperCase() + band.slice(1),
    users: all.filter((user) => user.level === band).length,
    fill: levelTone(band),
  }));
  const pageSize = 20;
  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize));
  const activePage = Math.min(page, pageCount);
  const visibleUsers = filtered.slice((activePage - 1) * pageSize, activePage * pageSize);

  return (
    <div className="grid gap-5">
      <PageHeader
        eyebrow="Investigations"
        title="User risk directory"
        description="Filter every protected identity, compare posture, and open a dedicated evidence timeline."
        actions={<Badge variant="outline" className="mono-data h-8">{filtered.length} of {all.length} identities</Badge>}
      />

      <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard label="Protected identities" value={summary?.users ?? all.length} detail="Visible to this verified tenant" icon={Users}/>
        <StatCard label="MFA coverage" value={`${all.length ? Math.round(mfaReady / all.length * 100) : 0}%`} detail={`${mfaReady} registered users`} icon={ShieldCheck}/>
        <StatCard label="Privileged users" value={admins} detail="Administrator identities" icon={UserRoundCog} tone="warning"/>
        <StatCard label="Entra risk signals" value={identityRisk} detail="Users above none" icon={KeyRound} tone="danger"/>
      </section>

      <section className="grid gap-4 xl:grid-cols-[.72fr_1.28fr]">
        <Card className="surface-panel">
          <CardHeader className="border-b"><SectionHeading title="Population by risk" description="Latest score band for every identity"/></CardHeader>
          <CardContent className="pt-4">
            <div className="h-64" role="img" aria-label="User count by risk band">
              <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{width: 720, height: 240}}>
                <BarChart data={bands} layout="vertical" margin={{top: 8, right: 22, left: 8, bottom: 0}}>
                  <CartesianGrid horizontal={false} stroke="rgba(166,202,190,.08)"/>
                  <XAxis type="number" hide/>
                  <YAxis type="category" dataKey="band" width={62} axisLine={false} tickLine={false} tick={{fontSize: 11, fill: "#91a59e"}}/>
                  <RechartsTooltip contentStyle={TOOLTIP}/>
                  <Bar dataKey="users" radius={[0, 6, 6, 0]} barSize={18}>
                    {bands.map((entry) => <Cell key={entry.band} fill={entry.fill}/>)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>

        <Card className="surface-panel">
          <CardHeader className="border-b"><SectionHeading title="Investigation filters" description="Refine the directory before opening an identity"/></CardHeader>
          <CardContent className="grid gap-3 pt-1">
            <label className="relative">
              <span className="sr-only">Search users</span>
              <Search className="pointer-events-none absolute top-1/2 left-3 size-3.5 -translate-y-1/2 text-muted-foreground"/>
              <Input value={search} onChange={(event) => {setSearch(event.target.value); setPage(1);}} className="h-10 bg-black/10 pl-9" placeholder="Search users"/>
            </label>
            <div className="grid gap-3 sm:grid-cols-3">
              <Select value={level} onValueChange={(value) => {setLevel(value); setPage(1);}}>
                <SelectTrigger aria-label="Risk level" className="h-10 w-full bg-black/10"><SelectValue/></SelectTrigger>
                <SelectContent><SelectItem value="all">All risk levels</SelectItem><SelectItem value="critical">Critical</SelectItem><SelectItem value="high">High</SelectItem><SelectItem value="medium">Medium</SelectItem><SelectItem value="low">Low</SelectItem></SelectContent>
              </Select>
              <Select value={posture} onValueChange={(value) => {setPosture(value); setPage(1);}}>
                <SelectTrigger aria-label="Identity posture" className="h-10 w-full bg-black/10"><SelectValue/></SelectTrigger>
                <SelectContent><SelectItem value="all">All posture</SelectItem><SelectItem value="mfa-ready">MFA ready</SelectItem><SelectItem value="mfa-missing">MFA missing</SelectItem><SelectItem value="admin">Privileged</SelectItem><SelectItem value="entra-risk">Entra risk</SelectItem></SelectContent>
              </Select>
              <Select value={sort} onValueChange={(value) => {setSort(value); setPage(1);}}>
                <SelectTrigger aria-label="Sort users" className="h-10 w-full bg-black/10"><ArrowDownAZ/><SelectValue/></SelectTrigger>
                <SelectContent><SelectItem value="risk-desc">Highest risk first</SelectItem><SelectItem value="risk-asc">Lowest risk first</SelectItem><SelectItem value="name">Name A–Z</SelectItem></SelectContent>
              </Select>
            </div>
            <div className="flex flex-wrap gap-2 pt-1">
              {["all", "critical", "high", "medium", "low"].map((band) => (
                <Button key={band} variant={level === band ? "default" : "outline"} size="sm" onClick={() => {setLevel(band); setPage(1);}} className="capitalize">
                  {band === "all" ? "All users" : band}
                </Button>
              ))}
            </div>
          </CardContent>
        </Card>
      </section>

      <Card className="surface-panel">
        <CardHeader className="border-b">
          <SectionHeading title="Investigation queue" description="Select an identity to inspect score history, contributing factors and related mail"/>
        </CardHeader>
        <CardContent className="px-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="pl-5">Identity</TableHead>
                <TableHead>Identity posture</TableHead>
                <TableHead>Entra risk</TableHead>
                <TableHead>Latest score</TableHead>
                <TableHead>Calculated</TableHead>
                <TableHead className="pr-5 text-right">Open</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visibleUsers.map((user) => (
                <TableRow key={user.id} className="group">
                  <TableCell className="pl-5">
                    <Link href={`/users/${user.id}`} className="font-medium transition-colors group-hover:text-primary">{user.display_name}</Link>
                    <span className="mono-data mt-1 block text-[10px] text-muted-foreground">{user.id}</span>
                  </TableCell>
                  <TableCell>
                    <span className="flex items-center gap-2 text-xs text-muted-foreground">
                      {user.is_mfa_registered ? <ShieldCheck className="size-3.5 text-primary"/> : <ShieldOff className="size-3.5 text-amber-200"/>}
                      {user.is_mfa_registered ? "MFA ready" : "MFA missing"}
                      {user.is_admin ? <Badge variant="outline" className="h-5 text-[9px]">admin</Badge> : null}
                    </span>
                  </TableCell>
                  <TableCell><span className="text-xs capitalize text-muted-foreground">{user.entra_risk_level}</span></TableCell>
                  <TableCell><span className="mono-data mr-2 text-xl font-semibold">{user.score}</span><RiskBadge level={user.level}/></TableCell>
                  <TableCell><span className="mono-data text-[10px] text-muted-foreground">{user.calculated_at ? new Date(user.calculated_at).toLocaleString() : "pending"}</span></TableCell>
                  <TableCell className="pr-5 text-right"><Button variant="ghost" size="icon-sm" asChild aria-label={`Open ${user.display_name}`}><Link href={`/users/${user.id}`}><ChevronRight/></Link></Button></TableCell>
                </TableRow>
              ))}
              {!filtered.length ? <TableRow><TableCell colSpan={6} className="h-48 text-center text-muted-foreground">{all.length ? "No identities match these filters." : "Waiting for the first synchronization."}</TableCell></TableRow> : null}
            </TableBody>
          </Table>
          {filtered.length ? (
            <div className="flex flex-col gap-3 border-t px-5 py-4 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
              <span>Showing {(activePage - 1) * pageSize + 1}–{Math.min(activePage * pageSize, filtered.length)} of {filtered.length}</span>
              <div className="flex items-center gap-2">
                <Button variant="outline" size="sm" disabled={activePage <= 1} onClick={() => setPage((current) => Math.max(1, current - 1))}>Previous</Button>
                <span className="mono-data px-2 text-[10px]">Page {activePage} / {pageCount}</span>
                <Button variant="outline" size="sm" disabled={activePage >= pageCount} onClick={() => setPage((current) => Math.min(pageCount, current + 1))}>Next</Button>
              </div>
            </div>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
