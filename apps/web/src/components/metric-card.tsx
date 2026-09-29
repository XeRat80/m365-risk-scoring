import type {LucideIcon} from "lucide-react";
import {Card, CardContent} from "@/components/ui/card";

interface MetricCardProps {label: string; value: string | number; detail: string; icon: LucideIcon; tone?: "default" | "danger" | "warning"}

export function MetricCard({label, value, detail, icon: Icon, tone = "default"}: MetricCardProps) {
  const toneClass = tone === "danger" ? "text-red-300 bg-red-400/10 ring-red-400/15" : tone === "warning" ? "text-amber-200 bg-amber-400/10 ring-amber-400/15" : "text-emerald-200 bg-emerald-400/10 ring-emerald-400/15";
  return <Card className="security-card min-h-32 py-0">
    <CardContent className="flex h-full flex-col justify-between p-4">
      <div className="flex items-center justify-between gap-3"><span className="text-xs font-medium text-muted-foreground">{label}</span><span className={`grid size-8 place-items-center rounded-lg ring-1 ${toneClass}`}><Icon className="size-4"/></span></div>
      <div className="mt-5"><div className="metric-number mono-data text-3xl font-semibold">{value}</div><p className="mt-1.5 text-[11px] text-muted-foreground">{detail}</p></div>
    </CardContent>
  </Card>;
}
