"use client";

import {Activity, DatabaseZap, LockKeyhole, ShieldCheck} from "lucide-react";
import {useState} from "react";
import {Button} from "@/components/ui/button";
import {Card, CardContent, CardDescription, CardHeader, CardTitle} from "@/components/ui/card";
import {Label} from "@/components/ui/label";
import {Select, SelectContent, SelectItem, SelectTrigger, SelectValue} from "@/components/ui/select";
import {API_URL} from "@/lib/api";

interface LoginPanelProps {onLogin: (token: string, tenant: string, role: string) => void}
const tenants = [{id: "00000000-0000-4000-8000-000000000001", name: "Northwind Research"}, {id: "00000000-0000-4000-8000-000000000002", name: "Contoso Operations"}];

export function LoginPanel({onLogin}: LoginPanelProps) {
  const [tenant, setTenant] = useState(tenants[0].id);
  const [role, setRole] = useState("admin");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  async function login() {
    setLoading(true); setError("");
    try {
      const response = await fetch(`${API_URL}/api/v1/auth/mock-token`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({tenant_id: tenant, role})});
      if (!response.ok) throw new Error("Start the Docker demo before signing in.");
      const payload = await response.json() as {access_token: string};
      onLogin(payload.access_token, tenants.find((item) => item.id === tenant)?.name ?? tenant, role);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Login failed"); }
    finally { setLoading(false); }
  }
  return <main className="grid min-h-screen place-items-center p-4 sm:p-8">
    <div className="grid w-full max-w-5xl overflow-hidden rounded-2xl border bg-[#081310]/95 shadow-2xl shadow-black/50 lg:grid-cols-[1.15fr_.85fr]">
      <section className="relative flex min-h-[560px] flex-col justify-between overflow-hidden border-b p-8 lg:border-r lg:border-b-0 lg:p-12">
        <div className="absolute -top-32 -left-24 size-96 rounded-full bg-emerald-400/10 blur-3xl"/>
        <div className="relative">
          <div className="mb-16 flex items-center gap-3 text-sm font-semibold"><span className="grid size-9 place-items-center rounded-xl border border-emerald-300/20 bg-emerald-300/10 text-primary"><Activity className="size-4"/></span>M365 Risk Command</div>
          <p className="mono-data text-[11px] uppercase tracking-[.2em] text-primary">Offline security operations</p>
          <h1 className="mt-5 max-w-xl text-4xl leading-[1.05] font-semibold tracking-[-.05em] sm:text-6xl">See user risk before it becomes an incident.</h1>
          <p className="mt-6 max-w-lg text-sm leading-6 text-muted-foreground sm:text-base">Correlate mail integrity, communication anomalies, identity posture and privilege without storing message content.</p>
        </div>
        <div className="relative grid gap-3 sm:grid-cols-3">
          {[{icon: ShieldCheck, label: "Forced RLS"}, {icon: LockKeyhole, label: "Signed OIDC"}, {icon: DatabaseZap, label: "Offline Graph"}].map(({icon: Icon, label}) => <div key={label} className="flex items-center gap-2 rounded-lg border bg-black/10 px-3 py-2.5 text-xs text-muted-foreground"><Icon className="size-3.5 text-primary"/>{label}</div>)}
        </div>
      </section>
      <section className="flex items-center p-6 sm:p-10">
        <Card className="security-card w-full border-0 bg-transparent ring-0">
          <CardHeader className="px-0"><CardTitle className="text-2xl tracking-tight">Enter the simulation</CardTitle><CardDescription>Use a locally signed tenant identity. No company access is required.</CardDescription></CardHeader>
          <CardContent className="grid gap-5 px-0">
            <div className="grid gap-2"><Label htmlFor="tenant-select">Tenant</Label><Select value={tenant} onValueChange={setTenant}><SelectTrigger id="tenant-select" aria-label="Tenant" className="h-10 w-full bg-black/15"><SelectValue/></SelectTrigger><SelectContent>{tenants.map((item) => <SelectItem key={item.id} value={item.id}>{item.name}</SelectItem>)}</SelectContent></Select></div>
            <div className="grid gap-2"><Label htmlFor="role-select">Role</Label><Select value={role} onValueChange={setRole}><SelectTrigger id="role-select" aria-label="Role" className="h-10 w-full bg-black/15"><SelectValue/></SelectTrigger><SelectContent><SelectItem value="admin">Administrator</SelectItem><SelectItem value="analyst">Analyst</SelectItem></SelectContent></Select></div>
            {error && <p className="rounded-lg border border-red-400/20 bg-red-400/8 p-3 text-xs text-red-200" role="alert">{error}</p>}
            <Button size="lg" className="mt-1 h-11 w-full" onClick={login} disabled={loading}>{loading ? "Signing in..." : "Open risk command"}</Button>
            <p className="flex items-center justify-center gap-2 text-center text-[11px] text-muted-foreground"><ShieldCheck className="size-3.5 text-primary"/>Headers and metadata only · tenant-isolated by design</p>
          </CardContent>
        </Card>
      </section>
    </div>
  </main>;
}
