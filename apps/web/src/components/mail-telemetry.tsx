"use client";

import {AlertTriangle, ArrowDown, Check, CircleDashed, Mail, Paperclip, Route, ShieldX} from "lucide-react";
import {Badge} from "@/components/ui/badge";
import {Card, CardContent, CardDescription, CardHeader, CardTitle} from "@/components/ui/card";
import {ScrollArea} from "@/components/ui/scroll-area";
import {Separator} from "@/components/ui/separator";
import {Tooltip, TooltipContent, TooltipTrigger} from "@/components/ui/tooltip";
import type {MailEvent} from "@/lib/api";

const authKeys = ["spf", "dkim", "dmarc"];

function probabilityTone(value: number) {
  if (value >= .7) return {label: "high", color: "#ff747a", className: "border-red-400/20 bg-red-400/10 text-red-200"};
  if (value >= .35) return {label: "watch", color: "#f4b45f", className: "border-amber-400/20 bg-amber-400/10 text-amber-100"};
  return {label: "clean", color: "#54e6ae", className: "border-emerald-400/20 bg-emerald-400/10 text-emerald-100"};
}

function AuthResult({name, value}: {name: string; value: string}) {
  const passed = value === "pass" || value === "none";
  return <Tooltip><TooltipTrigger asChild><span className={`inline-flex items-center gap-1 font-mono text-[10px] uppercase ${passed ? "text-emerald-300" : "text-red-300"}`}>{passed ? <Check className="size-3"/> : <ShieldX className="size-3"/>}{name}</span></TooltipTrigger><TooltipContent>{name.toUpperCase()} result: {value || "unknown"}</TooltipContent></Tooltip>;
}

export function MailTelemetry({events, loading, onSelect}: {events: MailEvent[]; loading: boolean; onSelect: (userId: string) => void}) {
  const newestTimestamp = events[0] ? new Date(events[0].received_at).getTime() : 0;
  const lastMinute = events.filter((event) => newestTimestamp - new Date(event.received_at).getTime() < 60_000).length;
  const highRisk = events.filter((event) => event.risk_probability >= .7).length;
  return <Card className="security-card h-full min-h-[580px]" id="mail-telemetry">
    <CardHeader className="border-b">
      <div className="flex items-start justify-between gap-4">
        <div>
          <CardTitle className="flex items-center gap-2"><Mail className="size-4 text-primary"/>Incoming mail telemetry</CardTitle>
          <CardDescription className="mt-1">Privacy-safe headers and model signals, newest first</CardDescription>
        </div>
        <Badge variant="outline" className="gap-1.5 border-emerald-400/20 bg-emerald-400/8 text-emerald-200"><span className="status-pulse size-1.5 rounded-full bg-emerald-300"/>Live</Badge>
      </div>
      <div className="mt-3 grid grid-cols-3 divide-x divide-border rounded-lg border bg-black/10 py-2">
        <div className="px-3"><p className="mono-data text-lg font-semibold">{events.length}</p><p className="text-[10px] uppercase tracking-wider text-muted-foreground">In view</p></div>
        <div className="px-3"><p className="mono-data text-lg font-semibold">{lastMinute}</p><p className="text-[10px] uppercase tracking-wider text-muted-foreground">Last min</p></div>
        <div className="px-3"><p className="mono-data text-lg font-semibold text-red-300">{highRisk}</p><p className="text-[10px] uppercase tracking-wider text-muted-foreground">High risk</p></div>
      </div>
    </CardHeader>
    <CardContent className="px-0">
      <ScrollArea className="h-[490px]" data-testid="mail-event-feed">
        {events.map((event, index) => {
          const tone = probabilityTone(event.risk_probability);
          return <button key={event.id} onClick={() => onSelect(event.user_id)} className="mail-event risk-glow block w-full px-4 py-3 text-left transition-colors hover:bg-white/[.025] focus-visible:bg-white/[.04]" style={{"--event-color": tone.color} as React.CSSProperties} aria-label={`Inspect ${event.user_id} mail event`}>
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="mono-data truncate text-xs font-medium text-foreground">domain:{event.sender_domain_hash.slice(0, 10)}</span>
                  {index === 0 && <ArrowDown className="size-3 animate-bounce text-primary" aria-hidden="true"/>}
                </div>
                <p className="mt-1 text-[11px] text-muted-foreground">to {event.user_id} · {new Date(event.received_at).toLocaleTimeString()}</p>
              </div>
              <Badge variant="outline" className={`mono-data shrink-0 ${tone.className}`}>{Math.round(event.risk_probability * 100)}% {tone.label}</Badge>
            </div>
            <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1.5">
              {authKeys.map((key) => <AuthResult key={key} name={key} value={event.authentication_results[key] ?? "unknown"}/>)}
              <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground"><Route className="size-3"/>{event.received_hops} hops</span>
              {event.has_attachments && <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground"><Paperclip className="size-3"/>attachment</span>}
              {(event.reply_to_domain_mismatch || event.from_sender_mismatch) && <span className="inline-flex items-center gap-1 text-[10px] text-amber-200"><AlertTriangle className="size-3"/>domain mismatch</span>}
            </div>
            <Separator className="mt-3 opacity-60"/>
          </button>;
        })}
        {!events.length && <div className="grid min-h-72 place-items-center px-8 text-center"><div><CircleDashed className={`mx-auto mb-3 size-7 text-muted-foreground ${loading ? "animate-spin" : ""}`}/><p className="text-sm font-medium">Waiting for synchronized mail</p><p className="mt-1 text-xs leading-5 text-muted-foreground">New privacy-safe Microsoft 365 metadata will appear after synchronization.</p></div></div>}
      </ScrollArea>
    </CardContent>
  </Card>;
}
