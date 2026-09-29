"use client";

import {
  ArrowLeft,
  Check,
  ClipboardCheck,
  Clock3,
  KeyRound,
  Mail,
  Paperclip,
  Route,
  Send,
  ShieldCheck,
  ShieldOff,
  UserRoundCog,
} from "lucide-react";
import {useMutation, useQuery} from "@tanstack/react-query";
import Link from "next/link";
import {useMemo, useState} from "react";
import {Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip as RechartsTooltip, XAxis, YAxis} from "recharts";
import {ErrorState, PageHeader, RiskBadge, ScoreRing, SectionHeading, formatRelativeTime} from "@/components/risk-ui";
import {useRiskContext} from "@/components/risk-context";
import {Badge} from "@/components/ui/badge";
import {Button} from "@/components/ui/button";
import {Card, CardContent, CardHeader} from "@/components/ui/card";
import {Textarea} from "@/components/ui/textarea";
import {request, type CursorPage, type MailEvent, type Risk, type UserSummary} from "@/lib/api";

const VERDICTS = ["true_positive", "false_positive", "safe"] as const;
const TOOLTIP = {background: "#0b1714", border: "1px solid rgba(166,202,190,.18)", borderRadius: 10, fontSize: 12};

export function UserView({userId}: {userId: string}) {
  const {session} = useRiskContext();
  const [comment, setComment] = useState("");
  const [recorded, setRecorded] = useState("");
  const users = useQuery({
    queryKey: ["users", session.tenant],
    queryFn: () => request<CursorPage<UserSummary>>("/api/v1/users?limit=100", session.token),
    refetchInterval: 5_000,
  });
  const history = useQuery({
    queryKey: ["risk-history", session.tenant, userId],
    queryFn: () => request<CursorPage<Risk>>(`/api/v1/users/${userId}/risk-history?limit=180`, session.token),
    enabled: Boolean(userId),
    refetchInterval: 5_000,
  });
  const mail = useQuery({
    queryKey: ["mail-events", session.tenant],
    queryFn: () => request<{items: MailEvent[]}>("/api/v1/mail/events?limit=50", session.token),
    refetchInterval: 2_000,
  });
  const latest = history.data?.items[0];
  const user = users.data?.items.find((item) => item.id === userId);
  const relatedMail = useMemo(() => (mail.data?.items ?? []).filter((event) => event.user_id === userId).slice(0, 8), [mail.data?.items, userId]);

  const feedback = useMutation({
    mutationFn: (verdict: string) =>
      request<{status: string}>(`/api/v1/risks/${latest!.id}/feedback`, session.token, {
        method: "POST",
        body: JSON.stringify({verdict, comment: comment.trim() || null}),
      }),
    onSuccess: (_, verdict) => {
      setRecorded(verdict.replaceAll("_", " "));
      setComment("");
    },
  });

  if (history.isError) return <ErrorState message="The risk history could not be retrieved for this tenant identity." onRetry={() => void history.refetch()}/>;

  const chart = [...(history.data?.items ?? [])].reverse().map((risk) => ({
    date: new Date(risk.calculated_at).toLocaleDateString(undefined, {month: "short", day: "numeric"}),
    score: risk.score,
    level: risk.level,
  }));
  const previous = history.data?.items[1];
  const delta = latest && previous ? latest.score - previous.score : 0;

  return (
    <div className="grid gap-5">
      <Button variant="ghost" size="sm" asChild className="-ml-2 w-fit text-muted-foreground"><Link href="/users"><ArrowLeft/>Back to investigation queue</Link></Button>
      <PageHeader
        eyebrow={`Identity investigation · ${userId}`}
        title={user?.display_name ?? userId}
        description="A dedicated record of risk movement, evidence contributions, posture and analyst disposition."
        actions={
          <>
            {latest ? <RiskBadge level={latest.level} className="h-8 px-3"/> : null}
            <Button variant="outline" asChild><Link href="/mail">Open related telemetry<Mail/></Link></Button>
          </>
        }
      />

      <section className="identity-hero">
        <div className="flex flex-col items-start gap-6 sm:flex-row sm:items-center">
          <ScoreRing score={latest?.score ?? user?.score ?? 0}/>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-2xl font-semibold tracking-[-.04em]">Current assessment</h2>
              {delta ? <Badge variant="outline" className={delta > 0 ? "border-rose-400/25 text-rose-200" : "border-primary/20 text-primary"}>{delta > 0 ? "+" : ""}{delta} since prior score</Badge> : null}
            </div>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
              Calculated {formatRelativeTime(latest?.calculated_at)} with model <span className="mono-data text-foreground">{latest?.model_version ?? "pending"}</span>.
            </p>
            <div className="mt-5 flex flex-wrap gap-2">
              <Badge variant="outline" className={user?.is_mfa_registered ? "border-primary/20 text-primary" : "border-amber-400/20 text-amber-100"}>
                {user?.is_mfa_registered ? <ShieldCheck/> : <ShieldOff/>}{user?.is_mfa_registered ? "MFA registered" : "MFA missing"}
              </Badge>
              <Badge variant="outline"><KeyRound/>Entra risk: {user?.entra_risk_level ?? "unknown"}</Badge>
              {user?.is_admin ? <Badge variant="outline" className="border-violet-400/20 text-violet-200"><UserRoundCog/>Privileged identity</Badge> : null}
            </div>
          </div>
        </div>
        <div className="grid gap-3 sm:grid-cols-3 xl:w-[540px]">
          <div className="evidence-stat"><span>Risk records</span><strong>{history.data?.items.length ?? 0}</strong></div>
          <div className="evidence-stat"><span>Active factors</span><strong>{latest?.factors.length ?? 0}</strong></div>
          <div className="evidence-stat"><span>Recent mail</span><strong>{relatedMail.length}</strong></div>
        </div>
      </section>

      <section className="grid gap-4 xl:grid-cols-[1.28fr_.72fr]">
        <Card className="surface-panel">
          <CardHeader className="border-b"><SectionHeading title="90-day risk trajectory" description="Every recalculation for this identity"/></CardHeader>
          <CardContent className="pt-4">
            <div className="h-80" role="img" aria-label={`Risk score history for ${userId}`}>
              <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{width: 720, height: 240}}>
                <AreaChart data={chart} margin={{top: 10, right: 10, bottom: 0, left: -20}}>
                  <defs><linearGradient id="userRiskArea" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#54e6ae" stopOpacity={.26}/><stop offset="100%" stopColor="#54e6ae" stopOpacity={0}/></linearGradient></defs>
                  <CartesianGrid vertical={false} stroke="rgba(166,202,190,.07)"/>
                  <XAxis dataKey="date" axisLine={false} tickLine={false} tick={{fontSize: 10, fill: "#91a59e"}} interval="preserveStartEnd"/>
                  <YAxis domain={[0, 100]} axisLine={false} tickLine={false} tick={{fontSize: 10, fill: "#91a59e"}}/>
                  <RechartsTooltip contentStyle={TOOLTIP}/>
                  <Area type="monotone" dataKey="score" stroke="#54e6ae" strokeWidth={2.4} fill="url(#userRiskArea)" dot={false} activeDot={{r: 4, fill: "#54e6ae"}}/>
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>

        <Card className="surface-panel">
          <CardHeader className="border-b"><SectionHeading title="Current contributions" description="Stored explanation for the latest score"/></CardHeader>
          <CardContent className="grid gap-4 pt-2">
            {(latest?.factors ?? []).map((factor) => (
              <div key={factor.name}>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-xs text-muted-foreground">{factor.name}</span>
                  <strong className="mono-data text-xs text-amber-100">+{factor.contribution.toFixed(1)}</strong>
                </div>
                <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/[.05]">
                  <div className="h-full rounded-full bg-gradient-to-r from-amber-300/50 to-amber-300" style={{width: `${Math.min(100, factor.contribution * 3.2)}%`}}/>
                </div>
              </div>
            ))}
            {!latest?.factors.length ? <p className="py-12 text-center text-xs text-muted-foreground">No active factors for the latest score.</p> : null}
          </CardContent>
        </Card>
      </section>

      <section className="grid items-start gap-4 xl:grid-cols-[1fr_.78fr]">
        <Card className="surface-panel">
          <CardHeader className="border-b"><SectionHeading title="Related mail evidence" description="Privacy-safe metadata addressed to this identity"/></CardHeader>
          <CardContent className="grid gap-2 pt-1">
            {relatedMail.map((event) => (
              <div key={event.id} className="grid gap-3 rounded-xl bg-white/[.025] p-3 ring-1 ring-border sm:grid-cols-[1fr_auto]">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="mono-data text-xs font-medium">domain:{event.sender_domain_hash.slice(0, 12)}</span>
                    <Badge variant="outline" className={event.risk_probability >= .7 ? "border-rose-400/20 text-rose-200" : "border-primary/20 text-primary"}>{Math.round(event.risk_probability * 100)}%</Badge>
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-3 text-[10px] text-muted-foreground">
                    <span className="flex items-center gap-1"><Clock3 className="size-3"/>{new Date(event.received_at).toLocaleString()}</span>
                    <span className="flex items-center gap-1"><Route className="size-3"/>{event.received_hops} hops</span>
                    {event.has_attachments ? <span className="flex items-center gap-1"><Paperclip className="size-3"/>attachment metadata</span> : null}
                  </div>
                </div>
                <div className="flex items-center gap-1.5">
                  {["spf", "dkim", "dmarc"].map((key) => {
                    const pass = ["pass", "none"].includes(event.authentication_results[key] ?? "");
                    return <Badge key={key} variant="outline" className={pass ? "border-primary/15 text-primary" : "border-rose-400/20 text-rose-200"}>{pass ? <Check/> : <ShieldOff/>}{key}</Badge>;
                  })}
                </div>
              </div>
            ))}
            {!relatedMail.length ? <p className="py-14 text-center text-xs text-muted-foreground">No recent mail metadata for this identity.</p> : null}
          </CardContent>
        </Card>

        <div className="grid gap-4">
          <Card className="surface-panel">
            <CardHeader className="border-b"><SectionHeading title="Recommended actions" description="Generated from the latest evidence"/></CardHeader>
            <CardContent>
              <ul className="grid gap-3">
                {(latest?.recommended_actions ?? []).map((action, index) => (
                  <li key={action} className="flex gap-3 text-xs leading-5 text-muted-foreground">
                    <span className="mono-data grid size-6 shrink-0 place-items-center rounded-lg bg-primary/10 text-[9px] text-primary">{String(index + 1).padStart(2, "0")}</span>
                    {action}
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>

          <Card className="surface-panel">
            <CardHeader className="border-b"><SectionHeading title="Analyst disposition" description="Record a privacy-safe outcome for model improvement"/></CardHeader>
            <CardContent>
              <label htmlFor="user-analyst-comment" className="flex items-center gap-2 text-xs font-medium"><ClipboardCheck className="size-3.5"/>Investigation note (optional)</label>
              <Textarea id="user-analyst-comment" className="mt-2 min-h-24 resize-y bg-black/10 text-xs" value={comment} maxLength={2000} onChange={(event) => setComment(event.target.value)} placeholder="Record decision context without copying message content."/>
              <div className="mt-3 flex flex-wrap gap-2">
                {VERDICTS.map((verdict) => <Button key={verdict} size="sm" variant="outline" disabled={!latest || feedback.isPending} onClick={() => feedback.mutate(verdict)}>{verdict.replaceAll("_", " ")}</Button>)}
              </div>
              {feedback.isError ? <p className="mt-3 text-xs text-rose-300" role="alert">Feedback could not be recorded.</p> : null}
              {recorded ? <p className="mt-3 flex items-center gap-1.5 text-xs text-primary" role="status"><Send className="size-3"/>Recorded: {recorded}</p> : null}
            </CardContent>
          </Card>
        </div>
      </section>

      <Card className="surface-panel">
        <CardHeader className="border-b"><SectionHeading title="Score history" description="Latest records with model version and evidence count"/></CardHeader>
        <CardContent className="px-0">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b text-muted-foreground"><tr><th className="px-5 py-3 font-medium">Calculated</th><th className="px-3 py-3 font-medium">Score</th><th className="px-3 py-3 font-medium">Level</th><th className="px-3 py-3 font-medium">Factors</th><th className="px-5 py-3 text-right font-medium">Model</th></tr></thead>
              <tbody>
                {(history.data?.items ?? []).slice(0, 20).map((risk) => (
                  <tr key={risk.id} className="border-b last:border-0 hover:bg-white/[.02]">
                    <td className="mono-data px-5 py-3 text-[10px] text-muted-foreground">{new Date(risk.calculated_at).toLocaleString()}</td>
                    <td className="mono-data px-3 py-3 text-base font-semibold">{risk.score}</td>
                    <td className="px-3 py-3"><RiskBadge level={risk.level}/></td>
                    <td className="px-3 py-3 text-muted-foreground">{risk.factors.length}</td>
                    <td className="mono-data px-5 py-3 text-right text-[10px] text-muted-foreground">{risk.model_version}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
