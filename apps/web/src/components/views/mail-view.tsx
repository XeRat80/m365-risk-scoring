"use client";

import {AlertTriangle, Check, Filter, Fingerprint, Mail, Paperclip, Route, Search, ShieldCheck, ShieldOff} from "lucide-react";
import {useQuery} from "@tanstack/react-query";
import Link from "next/link";
import {useMemo, useState} from "react";
import {Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip as RechartsTooltip, XAxis, YAxis} from "recharts";
import {PageHeader, SectionHeading, StatCard} from "@/components/risk-ui";
import {useRiskContext} from "@/components/risk-context";
import {Badge} from "@/components/ui/badge";
import {Button} from "@/components/ui/button";
import {Card, CardContent, CardHeader} from "@/components/ui/card";
import {Input} from "@/components/ui/input";
import {Select, SelectContent, SelectItem, SelectTrigger, SelectValue} from "@/components/ui/select";
import {request, type MailEvent} from "@/lib/api";

const TOOLTIP = {background: "#0b1714", border: "1px solid rgba(166,202,190,.18)", borderRadius: 10, fontSize: 12};
const BANDS = [
  {label: "0–24", min: 0, max: .25, color: "#54e6ae"},
  {label: "25–49", min: .25, max: .5, color: "#78a4ff"},
  {label: "50–69", min: .5, max: .7, color: "#f4b45f"},
  {label: "70–84", min: .7, max: .85, color: "#fb923c"},
  {label: "85–100", min: .85, max: 1.01, color: "#fb7185"},
];

function authPassed(value: string | undefined) {
  return value === "pass" || value === "none";
}

export function MailView() {
  const {session} = useRiskContext();
  const [selectedId, setSelectedId] = useState("");
  const [riskBand, setRiskBand] = useState("all");
  const [auth, setAuth] = useState("all");
  const [search, setSearch] = useState("");
  const mail = useQuery({
    queryKey: ["mail-events", session.tenant],
    queryFn: () => request<{items: MailEvent[]}>("/api/v1/mail/events?limit=50", session.token),
    refetchInterval: 2_000,
  });

  const events = useMemo(() => mail.data?.items ?? [], [mail.data?.items]);
  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return events.filter((event) => {
      const high = event.risk_probability >= .7;
      const watch = event.risk_probability >= .35 && event.risk_probability < .7;
      const failed = ["spf", "dkim", "dmarc"].some((key) => !authPassed(event.authentication_results[key]));
      return (
        (!needle || `${event.user_id} ${event.sender_domain_hash}`.toLowerCase().includes(needle)) &&
        (riskBand === "all" || (riskBand === "high" && high) || (riskBand === "watch" && watch) || (riskBand === "clean" && !high && !watch)) &&
        (auth === "all" || (auth === "failed" && failed) || (auth === "passed" && !failed))
      );
    });
  }, [auth, events, riskBand, search]);

  const selected = events.find((event) => event.id === selectedId) ?? filtered[0] ?? events[0];
  const high = events.filter((event) => event.risk_probability >= .7).length;
  const failedAuth = events.filter((event) => ["spf", "dkim", "dmarc"].some((key) => !authPassed(event.authentication_results[key]))).length;
  const mismatched = events.filter((event) => event.reply_to_domain_mismatch || event.from_sender_mismatch).length;
  const histogram = BANDS.map((band) => ({
    label: band.label,
    events: events.filter((event) => event.risk_probability >= band.min && event.risk_probability < band.max).length,
    color: band.color,
  }));
  const authChart = ["spf", "dkim", "dmarc"].map((key) => ({
    protocol: key.toUpperCase(),
    passed: events.filter((event) => authPassed(event.authentication_results[key])).length,
    failed: events.filter((event) => !authPassed(event.authentication_results[key])).length,
  }));

  return (
    <div className="grid gap-5">
      <PageHeader
        eyebrow="Mail intelligence"
        title="Privacy-safe header telemetry"
        description="Inspect authentication, routing and probability signals without exposing message subject, body, preview or attachment content."
        actions={<Badge variant="outline" className="h-8 gap-1.5 border-primary/20 text-primary"><span className="status-pulse size-1.5 rounded-full bg-primary"/>Live monitoring</Badge>}
      />

      <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard label="Recent events" value={events.length} detail="Latest synchronized metadata" icon={Mail}/>
        <StatCard label="High probability" value={high} detail="Risk probability at or above 70%" icon={AlertTriangle} tone="danger"/>
        <StatCard label="Auth failures" value={failedAuth} detail="SPF, DKIM or DMARC failed" icon={ShieldOff} tone="warning"/>
        <StatCard label="Domain mismatch" value={mismatched} detail="Reply-to or from/sender mismatch" icon={Fingerprint} tone="info"/>
      </section>

      <section className="grid gap-4 xl:grid-cols-2">
        <Card className="surface-panel">
          <CardHeader className="border-b"><SectionHeading title="Probability distribution" description="Latest events by model risk band"/></CardHeader>
          <CardContent className="pt-4">
            <div className="h-64" role="img" aria-label="Mail risk probability distribution">
              <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{width: 720, height: 240}}>
                <BarChart data={histogram} margin={{top: 10, right: 10, left: -20, bottom: 0}}>
                  <CartesianGrid vertical={false} stroke="rgba(166,202,190,.07)"/>
                  <XAxis dataKey="label" axisLine={false} tickLine={false} tick={{fontSize: 10, fill: "#91a59e"}}/>
                  <YAxis allowDecimals={false} axisLine={false} tickLine={false} tick={{fontSize: 10, fill: "#91a59e"}}/>
                  <RechartsTooltip contentStyle={TOOLTIP}/>
                  <Bar dataKey="events" radius={[6, 6, 0, 0]} barSize={34}>
                    {histogram.map((entry) => <Cell key={entry.label} fill={entry.color}/>)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
        <Card className="surface-panel">
          <CardHeader className="border-b"><SectionHeading title="Authentication outcomes" description="Protocol results in the latest synchronized set"/></CardHeader>
          <CardContent className="pt-4">
            <div className="h-64" role="img" aria-label="Authentication pass and fail counts">
              <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{width: 720, height: 240}}>
                <BarChart data={authChart} margin={{top: 10, right: 10, left: -20, bottom: 0}}>
                  <CartesianGrid vertical={false} stroke="rgba(166,202,190,.07)"/>
                  <XAxis dataKey="protocol" axisLine={false} tickLine={false} tick={{fontSize: 10, fill: "#91a59e"}}/>
                  <YAxis allowDecimals={false} axisLine={false} tickLine={false} tick={{fontSize: 10, fill: "#91a59e"}}/>
                  <RechartsTooltip contentStyle={TOOLTIP}/>
                  <Bar dataKey="passed" stackId="auth" fill="#54e6ae" radius={[0, 0, 5, 5]}/>
                  <Bar dataKey="failed" stackId="auth" fill="#fb7185" radius={[5, 5, 0, 0]}/>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="mt-1 flex justify-center gap-5 text-[10px] text-muted-foreground"><span className="flex items-center gap-1.5"><span className="size-2 rounded-sm bg-primary"/>Passed</span><span className="flex items-center gap-1.5"><span className="size-2 rounded-sm bg-rose-400"/>Failed / unknown</span></div>
          </CardContent>
        </Card>
      </section>

      <section className="grid items-start gap-4 xl:grid-cols-[minmax(0,1.45fr)_minmax(360px,.75fr)]">
        <Card className="surface-panel min-w-0">
          <CardHeader className="border-b">
            <SectionHeading title="Incoming mail stream" description="Newest content-free events first"/>
            <div className="mt-3 grid gap-2 md:grid-cols-[1fr_150px_160px]">
              <label className="relative">
                <span className="sr-only">Search mail telemetry</span>
                <Search className="pointer-events-none absolute top-1/2 left-3 size-3.5 -translate-y-1/2 text-muted-foreground"/>
                <Input value={search} onChange={(event) => setSearch(event.target.value)} className="bg-black/10 pl-9" placeholder="Search user or domain hash"/>
              </label>
              <Select value={riskBand} onValueChange={setRiskBand}>
                <SelectTrigger aria-label="Mail risk band" className="w-full bg-black/10"><Filter/><SelectValue/></SelectTrigger>
                <SelectContent><SelectItem value="all">All risk bands</SelectItem><SelectItem value="high">High ≥ 70%</SelectItem><SelectItem value="watch">Watch 35–69%</SelectItem><SelectItem value="clean">Clean &lt; 35%</SelectItem></SelectContent>
              </Select>
              <Select value={auth} onValueChange={setAuth}>
                <SelectTrigger aria-label="Authentication outcome" className="w-full bg-black/10"><SelectValue/></SelectTrigger>
                <SelectContent><SelectItem value="all">All authentication</SelectItem><SelectItem value="failed">Any failure</SelectItem><SelectItem value="passed">All passed</SelectItem></SelectContent>
              </Select>
            </div>
          </CardHeader>
          <CardContent className="px-0">
            <div className="max-h-[660px] overflow-y-auto" data-testid="mail-event-feed">
              {filtered.map((event, index) => {
                const risk = Math.round(event.risk_probability * 100);
                const active = selected?.id === event.id;
                return (
                  <button
                    key={event.id}
                    onClick={() => setSelectedId(event.id)}
                    className={`mail-event grid w-full gap-3 border-b px-4 py-4 text-left transition-colors last:border-0 hover:bg-white/[.03] sm:grid-cols-[minmax(0,1fr)_auto] ${active ? "bg-primary/[.045]" : ""}`}
                    aria-label={`Inspect mail event for ${event.user_id}`}
                  >
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        {index === 0 ? <span className="status-pulse size-1.5 rounded-full bg-primary"/> : null}
                        <span className="mono-data truncate text-xs font-medium">domain:{event.sender_domain_hash.slice(0, 14)}</span>
                        <Badge variant="outline" className={risk >= 70 ? "border-rose-400/20 text-rose-200" : risk >= 35 ? "border-amber-400/20 text-amber-100" : "border-primary/20 text-primary"}>{risk}%</Badge>
                        {event.importance === "high" ? <Badge variant="outline" className="border-orange-400/20 text-orange-200">high importance</Badge> : null}
                      </div>
                      <p className="mt-1.5 text-[11px] text-muted-foreground">to {event.user_id} · {new Date(event.received_at).toLocaleString()}</p>
                      <div className="mt-2.5 flex flex-wrap items-center gap-3">
                        {["spf", "dkim", "dmarc"].map((key) => {
                          const pass = authPassed(event.authentication_results[key]);
                          return <span key={key} className={`inline-flex items-center gap-1 font-mono text-[10px] uppercase ${pass ? "text-primary" : "text-rose-300"}`}>{pass ? <Check className="size-3"/> : <ShieldOff className="size-3"/>}{key}</span>;
                        })}
                        <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground"><Route className="size-3"/>{event.received_hops} hops</span>
                        {event.has_attachments ? <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground"><Paperclip className="size-3"/>attachment</span> : null}
                        {event.reply_to_domain_mismatch || event.from_sender_mismatch ? <span className="inline-flex items-center gap-1 text-[10px] text-amber-100"><AlertTriangle className="size-3"/>domain mismatch</span> : null}
                      </div>
                    </div>
                    <span className="mono-data text-[10px] text-muted-foreground">{event.id.slice(0, 10)}</span>
                  </button>
                );
              })}
              {!filtered.length ? <p className="px-6 py-20 text-center text-xs text-muted-foreground">{events.length ? "No events match these filters." : "Waiting for synchronized mail metadata."}</p> : null}
            </div>
          </CardContent>
        </Card>

        <div className="grid min-w-0 gap-4 xl:sticky xl:top-20">
          <Card className="surface-panel min-w-0">
            <CardHeader className="border-b"><SectionHeading title="Header inspector" description="Selected event evidence"/></CardHeader>
            <CardContent className="min-w-0">
              {selected ? (
                <div className="grid gap-5">
                  <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-start gap-4">
                    <div className="min-w-0">
                      <p className="mono-data break-all text-sm font-semibold">domain:{selected.sender_domain_hash.slice(0, 14)}</p>
                      <p className="mono-data mt-1 break-all text-[10px] leading-4 text-muted-foreground">Event {selected.id}</p>
                    </div>
                    <div className="shrink-0 text-right">
                      <span className="mono-data block text-3xl leading-none font-semibold">{Math.round(selected.risk_probability * 100)}<span className="text-xs text-muted-foreground">%</span></span>
                      <span className="mt-1 block text-[9px] uppercase tracking-[.12em] text-muted-foreground">Mail probability</span>
                    </div>
                  </div>
                  <dl className="grid gap-3 text-xs">
                    {[
                      ["Recipient", selected.user_id],
                      ["Received", new Date(selected.received_at).toLocaleString()],
                      ["External sender", selected.external_sender ? "yes" : "no"],
                      ["Recipients", String(selected.recipient_count)],
                      ["Importance", selected.importance],
                      ["Routing hops", String(selected.received_hops)],
                      ["Attachment metadata", selected.has_attachments ? "present" : "none"],
                      ["Reply-to mismatch", selected.reply_to_domain_mismatch ? "detected" : "none"],
                      ["From/sender mismatch", selected.from_sender_mismatch ? "detected" : "none"],
                    ].map(([label, value]) => (
                      <div key={label} className="grid min-w-0 grid-cols-[minmax(0,.9fr)_minmax(0,1.1fr)] items-start gap-4 border-b pb-2 last:border-0 last:pb-0">
                        <dt className="min-w-0 text-muted-foreground">{label}</dt>
                        <dd className="min-w-0 break-words text-right leading-5 capitalize">{value}</dd>
                      </div>
                    ))}
                  </dl>
                  <div>
                    <p className="mb-2 text-[10px] uppercase tracking-[.15em] text-muted-foreground">Authentication</p>
                    <div className="grid grid-cols-3 gap-2">
                      {["spf", "dkim", "dmarc"].map((key) => {
                        const value = selected.authentication_results[key] ?? "unknown";
                        const pass = authPassed(value);
                        return <div key={key} className={`rounded-lg p-2 text-center ring-1 ${pass ? "bg-primary/[.05] text-primary ring-primary/15" : "bg-rose-400/[.06] text-rose-200 ring-rose-400/15"}`}><p className="font-mono text-[10px] uppercase">{key}</p><p className="mt-1 text-[10px] capitalize">{value}</p></div>;
                      })}
                    </div>
                  </div>
                  <Button variant="outline" asChild><Link href={`/users/${selected.user_id}`}>Open recipient investigation</Link></Button>
                </div>
              ) : <p className="py-16 text-center text-xs text-muted-foreground">Select an event to inspect its headers.</p>}
            </CardContent>
          </Card>
          <Card className="privacy-panel">
            <CardContent className="flex gap-3 p-4">
              <ShieldCheck className="mt-0.5 size-4 shrink-0 text-primary"/>
              <div><p className="text-xs font-semibold">Content boundary enforced</p><p className="mt-1 text-[11px] leading-5 text-muted-foreground">Subject, body, preview, unique body and attachment bytes never enter this view or persistent storage.</p></div>
            </CardContent>
          </Card>
        </div>
      </section>
    </div>
  );
}
