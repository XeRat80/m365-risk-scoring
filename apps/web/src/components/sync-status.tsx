import {Cloud, Database, RefreshCw} from "lucide-react";
import {Badge} from "@/components/ui/badge";
import {Button} from "@/components/ui/button";
import {Card, CardContent, CardDescription, CardHeader, CardTitle} from "@/components/ui/card";
import type {Connection, SyncJob} from "@/lib/api";

export function SyncStatus({jobs, connection, isAdmin, onConnect}: {jobs: SyncJob[]; connection?: Connection; isAdmin: boolean; onConnect: () => void}) {
  const connected = connection?.status === "connected";
  return <Card className="security-card" id="sync-jobs">
    <CardHeader className="border-b"><div className="flex items-start justify-between gap-3"><div><CardTitle className="flex items-center gap-2"><Cloud className="size-4 text-primary"/>Connector health</CardTitle><CardDescription className="mt-1">{connection?.provider ?? "Checking connector"} · content-free metadata</CardDescription></div><Badge variant="outline" className={connected ? "border-emerald-400/20 text-emerald-200" : "border-red-400/20 text-red-200"}><span className={`mr-1 size-1.5 rounded-full ${connected ? "bg-emerald-300" : "bg-red-300"}`}/>{connection?.status ?? "loading"}</Badge></div></CardHeader>
    <CardContent>
      {connection?.scopes.length ? <p className="mono-data mb-3 break-words text-[9px] leading-4 text-muted-foreground">{connection.scopes.join(" · ")}</p> : null}
      {!connected && isAdmin ? <Button variant="outline" className="mb-3 w-full" onClick={onConnect}>Start admin consent</Button> : null}
      <div className="grid gap-2">{jobs.slice(0, 4).map((job) => <div key={job.id} className="grid grid-cols-[auto_1fr_auto] items-center gap-2 rounded-lg border bg-black/10 px-3 py-2"><Database className="size-3.5 text-muted-foreground"/><div><p className="text-xs font-medium capitalize">{job.status}</p><p className="text-[10px] text-muted-foreground">Attempt {job.attempt}</p></div><time className="mono-data text-[10px] text-muted-foreground">{job.status === "retrying" ? `Retry ${new Date(job.next_attempt_at).toLocaleTimeString()}` : new Date(job.created_at).toLocaleTimeString()}</time></div>)}{!jobs.length && <p className="flex items-center gap-2 py-4 text-xs text-muted-foreground"><RefreshCw className="size-3.5 animate-spin"/>Waiting for the first sync job.</p>}</div>
    </CardContent>
  </Card>;
}
