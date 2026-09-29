"use client";

import {ClipboardCheck, History, Lightbulb, Send} from "lucide-react";
import {useMutation, useQuery} from "@tanstack/react-query";
import {useState} from "react";
import {Line, LineChart, ResponsiveContainer, Tooltip as RechartsTooltip, XAxis, YAxis} from "recharts";
import {Badge} from "@/components/ui/badge";
import {Button} from "@/components/ui/button";
import {Card, CardContent, CardDescription, CardHeader} from "@/components/ui/card";
import {Textarea} from "@/components/ui/textarea";
import {request, type CursorPage, type Risk} from "@/lib/api";

interface RiskDetailProps {token: string; userId: string}
const VERDICTS = ["true_positive", "false_positive", "safe"] as const;
const TOOLTIP_STYLE = {background: "#0b1714", border: "1px solid rgba(166,202,190,.18)", borderRadius: 10, fontSize: 12};

export function RiskDetail({token, userId}: RiskDetailProps) {
  const [recorded, setRecorded] = useState("");
  const [comment, setComment] = useState("");
  const {data} = useQuery({queryKey: ["risk-history", userId], queryFn: () => request<CursorPage<Risk>>(`/api/v1/users/${userId}/risk-history?limit=100`, token), refetchInterval: 5000});
  const latest = data?.items[0];
  const feedback = useMutation({mutationFn: (verdict: string) => request<{status: string}>(`/api/v1/risks/${latest!.id}/feedback`, token, {method: "POST", body: JSON.stringify({verdict, comment: comment.trim() || null})}), onSuccess: (_, verdict) => {setRecorded(verdict.replaceAll("_", " ")); setComment("");}});
  if (!latest) return <Card className="security-card mt-4"><CardContent className="py-16 text-center text-sm text-muted-foreground">Risk history will appear after synchronization.</CardContent></Card>;
  const riskTone = latest.level === "critical" ? "border-red-400/25 bg-red-400/10 text-red-200" : latest.level === "high" ? "border-orange-400/25 bg-orange-400/10 text-orange-200" : latest.level === "medium" ? "border-amber-400/25 bg-amber-400/10 text-amber-100" : "border-emerald-400/20 bg-emerald-400/10 text-emerald-200";
  return <Card className="security-card mt-4">
    <CardHeader className="border-b"><div className="flex items-start justify-between gap-4"><div><h2 className="text-base leading-snug font-medium">{userId} · score {latest.score}</h2><CardDescription className="mt-1">Risk trajectory and evidence contributions</CardDescription></div><Badge variant="outline" className={`capitalize ${riskTone}`}>{latest.level}</Badge></div></CardHeader>
    <CardContent className="grid gap-5 pt-1 lg:grid-cols-[1.15fr_.85fr]">
      <div>
        <div className="mb-2 flex items-center gap-2 text-xs font-medium text-muted-foreground"><History className="size-3.5"/>90-day risk history</div>
        <div className="h-44" role="img" aria-label={`Risk score history for ${userId}`}><ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{width: 720, height: 240}}><LineChart data={[...(data?.items ?? [])].reverse()} margin={{top: 8, right: 4, bottom: 0, left: -24}}><XAxis dataKey="calculated_at" hide/><YAxis domain={[0,100]} stroke="#6f827b" tick={{fontSize: 10}} axisLine={false} tickLine={false}/><RechartsTooltip contentStyle={TOOLTIP_STYLE}/><Line type="monotone" dataKey="score" stroke="#54e6ae" strokeWidth={2.25} dot={false} activeDot={{r: 3, fill: "#54e6ae"}}/></LineChart></ResponsiveContainer></div>
        <div className="mt-3 grid gap-2">{latest.factors.map((factor) => <div key={factor.name} className="grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1"><span className="text-xs text-muted-foreground">{factor.name}</span><strong className="mono-data text-xs text-amber-200">+{factor.contribution.toFixed(1)}</strong><div className="col-span-2 h-1 overflow-hidden rounded-full bg-white/5"><div className="h-full rounded-full bg-amber-300/70" style={{width: `${Math.min(100, factor.contribution * 4)}%`}}/></div></div>)}</div>
      </div>
      <div className="border-t pt-5 lg:border-t-0 lg:border-l lg:pt-0 lg:pl-5">
        <div className="flex items-center gap-2 text-xs font-medium"><Lightbulb className="size-3.5 text-primary"/>Recommended actions</div>
        <ul className="mt-3 grid gap-2">{latest.recommended_actions.map((action) => <li key={action} className="flex gap-2 text-xs leading-5 text-muted-foreground"><span className="mt-2 size-1 shrink-0 rounded-full bg-primary"/>{action}</li>)}</ul>
        <div className="mt-5 border-t pt-4" aria-label="Analyst feedback"><label htmlFor="analyst-comment" className="flex items-center gap-2 text-xs font-medium"><ClipboardCheck className="size-3.5"/>Analyst note (optional)</label><Textarea id="analyst-comment" className="mt-2 min-h-20 resize-y bg-black/10 text-xs" value={comment} maxLength={2000} onChange={(event) => setComment(event.target.value)} placeholder="Record investigation context without copying message content."/><div className="mt-3 flex flex-wrap gap-1.5">{VERDICTS.map((verdict) => <Button key={verdict} size="xs" variant="outline" disabled={feedback.isPending} onClick={() => feedback.mutate(verdict)}>{verdict.replaceAll("_", " ")}</Button>)}</div></div>
        {feedback.isError && <p className="mt-3 text-xs text-red-300" role="alert">Feedback could not be recorded.</p>}
        {recorded && <p className="mt-3 flex items-center gap-1.5 text-xs text-emerald-300" role="status"><Send className="size-3"/>Recorded: {recorded}</p>}
      </div>
    </CardContent>
  </Card>;
}
