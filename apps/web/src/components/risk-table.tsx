"use client";

import {Search, ShieldCheck, ShieldOff, UserRoundCog} from "lucide-react";
import {useMemo, useState} from "react";
import {Badge} from "@/components/ui/badge";
import {Card, CardContent, CardDescription, CardHeader, CardTitle} from "@/components/ui/card";
import {Input} from "@/components/ui/input";
import {Select, SelectContent, SelectItem, SelectTrigger, SelectValue} from "@/components/ui/select";
import {Table, TableBody, TableCell, TableHead, TableHeader, TableRow} from "@/components/ui/table";
import type {UserSummary} from "@/lib/api";

interface RiskTableProps {users: UserSummary[]; selected: string; onSelect: (id: string) => void}

function RiskBadge({level}: {level: string}) {
  const style = level === "critical" ? "border-red-400/25 bg-red-400/10 text-red-200" : level === "high" ? "border-orange-400/25 bg-orange-400/10 text-orange-200" : level === "medium" ? "border-amber-400/25 bg-amber-400/10 text-amber-100" : "border-emerald-400/20 bg-emerald-400/10 text-emerald-200";
  return <Badge variant="outline" className={`capitalize ${style}`}>{level}</Badge>;
}

export function RiskTable({users, selected, onSelect}: RiskTableProps) {
  const [search, setSearch] = useState("");
  const [level, setLevel] = useState("all");
  const sorted = useMemo(() => users.filter((user) => `${user.display_name} ${user.id}`.toLowerCase().includes(search.toLowerCase())).filter((user) => level === "all" || user.level === level).sort((left, right) => right.score - left.score).slice(0, 12), [users, search, level]);
  return <Card className="security-card" id="users">
    <CardHeader className="border-b">
      <div className="flex flex-wrap items-start justify-between gap-4"><div><CardTitle>Highest user risk</CardTitle><CardDescription className="mt-1">Latest score by identity, ordered for analyst triage</CardDescription></div><Badge variant="outline" className="gap-1.5 border-emerald-400/20 text-emerald-200"><span className="status-pulse size-1.5 rounded-full bg-emerald-300"/>Live ranking</Badge></div>
      <div className="mt-3 flex gap-2">
        <label className="relative min-w-0 flex-1"><span className="sr-only">Search users</span><Search className="pointer-events-none absolute top-2.5 left-2.5 size-3.5 text-muted-foreground"/><Input className="bg-black/10 pl-8" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search users"/></label>
        <Select value={level} onValueChange={setLevel}><SelectTrigger aria-label="Risk level" className="w-32 bg-black/10"><SelectValue/></SelectTrigger><SelectContent><SelectItem value="all">All levels</SelectItem><SelectItem value="critical">Critical</SelectItem><SelectItem value="high">High</SelectItem><SelectItem value="medium">Medium</SelectItem><SelectItem value="low">Low</SelectItem></SelectContent></Select>
      </div>
    </CardHeader>
    <CardContent className="px-0">
      <Table>
        <TableHeader><TableRow><TableHead className="pl-4">Identity</TableHead><TableHead>Posture</TableHead><TableHead>Score</TableHead><TableHead className="pr-4 text-right">Level</TableHead></TableRow></TableHeader>
        <TableBody>
          {sorted.map((user) => <TableRow key={user.id} data-state={selected === user.id ? "selected" : undefined} className="group">
            <TableCell className="pl-4"><button className="text-left font-medium transition-colors group-hover:text-primary" onClick={() => onSelect(user.id)}>{user.display_name}</button><div className="mono-data mt-1 text-[10px] text-muted-foreground">{user.id}</div></TableCell>
            <TableCell><span className="flex items-center gap-1.5 text-xs text-muted-foreground">{!user.is_mfa_capable ? <ShieldOff className="size-3.5 text-red-300"/> : user.is_mfa_registered ? <ShieldCheck className="size-3.5 text-emerald-300"/> : <ShieldOff className="size-3.5 text-amber-200"/>}{!user.is_mfa_capable ? "MFA incapable" : user.is_mfa_registered ? "MFA ready" : "MFA missing"}{user.is_admin && <UserRoundCog className="ml-1 size-3.5 text-violet-300"/>}</span></TableCell>
            <TableCell><span className="mono-data text-lg font-semibold">{user.score}</span><span className="text-[10px] text-muted-foreground"> / 100</span></TableCell>
            <TableCell className="pr-4 text-right"><RiskBadge level={user.level}/></TableCell>
          </TableRow>)}
          {!sorted.length && <TableRow><TableCell colSpan={4} className="h-32 text-center text-muted-foreground">{users.length ? "No users match these filters." : "Waiting for the first synchronization..."}</TableCell></TableRow>}
        </TableBody>
      </Table>
    </CardContent>
  </Card>;
}
