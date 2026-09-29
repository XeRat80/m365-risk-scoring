"use client";

import {Archive, Box, CheckCircle2, FileJson, Fingerprint, Gauge, GitCompareArrows, LockKeyhole, ShieldAlert, XCircle} from "lucide-react";
import {Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip as RechartsTooltip, XAxis, YAxis} from "recharts";
import {PageHeader, SectionHeading, StatCard} from "@/components/risk-ui";
import {useRiskContext} from "@/components/risk-context";
import {Alert, AlertDescription, AlertTitle} from "@/components/ui/alert";
import {Badge} from "@/components/ui/badge";
import {Card, CardContent, CardHeader} from "@/components/ui/card";
import {cn} from "@/lib/utils";

type ModelMetric = {
  name: string;
  pr_auc: number;
  roc_auc: number;
  brier: number;
  ece: number;
  threshold: number;
  precision: number;
  recall: number;
};

type ModelMetrics = {
  split?: {strategy?: string; train_rows?: number; validation_rows?: number; test_rows?: number};
  email_models?: ModelMetric[];
  selected?: ModelMetric;
  user_risk?: {top_10_recall?: number; false_alerts_per_100?: number; median_detection_delay_days?: number};
  onnx_max_abs_difference?: number;
  selection_note?: string;
  hybrid_weight_selection?: {promoted?: boolean; reason?: string};
};

const TOOLTIP = {background: "#0b1714", border: "1px solid rgba(166,202,190,.18)", borderRadius: 10, fontSize: 12};
const WEIGHTS = [
  {name: "Email", value: 35, color: "#54e6ae"},
  {name: "Behaviour", value: 20, color: "#78a4ff"},
  {name: "Entra risk", value: 20, color: "#a997ff"},
  {name: "MFA posture", value: 15, color: "#f4b45f"},
  {name: "Privilege", value: 10, color: "#91a59e"},
];

function format(value: number | undefined, digits = 3) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "—";
}

export function ModelsView() {
  const {model} = useRiskContext();
  const metrics = (model?.metrics ?? {}) as ModelMetrics;
  const selected = metrics.selected;
  const userRisk = metrics.user_risk;
  const candidates = metrics.email_models ?? [];
  const comparison = candidates.map((candidate) => ({
    name: candidate.name === "hist_gradient_boosting" ? "gradient boost" : candidate.name,
    "PR-AUC": Number((candidate.pr_auc * 100).toFixed(1)),
    Precision: Number((candidate.precision * 100).toFixed(1)),
    Recall: Number((candidate.recall * 100).toFixed(1)),
  }));
  const gates = [
    {label: "PR-AUC", actual: selected?.pr_auc, gate: .9, direction: "min", detail: "Email ranking quality"},
    {label: "Precision", actual: selected?.precision, gate: .85, direction: "min", detail: "At the promoted threshold"},
    {label: "Recall", actual: selected?.recall, gate: .8, direction: "min", detail: "At the promoted threshold"},
    {label: "Brier", actual: selected?.brier, gate: .1, direction: "max", detail: "Probability calibration"},
    {label: "ECE", actual: selected?.ece, gate: .05, direction: "max", detail: "Expected calibration error"},
  ] as const;
  const passed = gates.filter((gate) => typeof gate.actual === "number" && (gate.direction === "min" ? gate.actual >= gate.gate : gate.actual <= gate.gate)).length;
  const parity = metrics.onnx_max_abs_difference;

  return (
    <div className="grid gap-5">
      <PageHeader
        eyebrow="Model governance"
        title="Promotion and inference evidence"
        description="Compare candidate models, inspect every quality gate, and verify the exact bundle serving user-risk explanations."
        actions={<Badge variant="outline" className={cn("h-8 gap-1.5", model?.approved ? "border-primary/20 text-primary" : "border-amber-400/20 text-amber-100")}><Fingerprint/>{model?.version ?? "loading"} · {model?.approved ? "approved" : "demo only"}</Badge>}
      />

      {!model?.approved ? (
        <Alert className="border-amber-400/20 bg-amber-400/[.06] text-amber-100">
          <LockKeyhole/>
          <AlertTitle>Production promotion is blocked</AlertTitle>
          <AlertDescription>Demo inference remains available locally, but the release pipeline refuses this model until every required gate passes.</AlertDescription>
        </Alert>
      ) : null}

      <section className="model-hero">
        <div>
          <p className="page-eyebrow">Current runtime</p>
          <h2 className="mt-2 text-3xl font-semibold tracking-[-.05em]">{selected?.name ?? "Model pending"}</h2>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">{metrics.selection_note ?? "The current model was selected from the versioned evaluation bundle."}</p>
          <div className="mt-5 flex flex-wrap gap-2">
            <Badge variant="outline">Feature schema · {model?.feature_version ?? "unknown"}</Badge>
            <Badge variant="outline">Split · grouped chronological</Badge>
            <Badge variant="outline">Python + ONNX</Badge>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 xl:w-[660px]">
          <div className="evidence-stat"><span>PR-AUC</span><strong>{format(selected?.pr_auc)}</strong></div>
          <div className="evidence-stat"><span>Recall</span><strong>{format(selected?.recall)}</strong></div>
          <div className="evidence-stat"><span>Brier</span><strong>{format(selected?.brier)}</strong></div>
          <div className="evidence-stat"><span>Parity</span><strong className="text-sm">{typeof parity === "number" ? parity.toExponential(2) : "—"}</strong></div>
        </div>
      </section>

      <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard label="Promotion gates" value={`${passed} / ${gates.length}`} detail="Email-model requirements passed" icon={model?.approved ? CheckCircle2 : XCircle} tone={model?.approved ? "default" : "danger"}/>
        <StatCard label="Top-10% recall" value={typeof userRisk?.top_10_recall === "number" ? `${Math.round(userRisk.top_10_recall * 100)}%` : "—"} detail="User-level compromise recall" icon={Gauge}/>
        <StatCard label="False alerts / 100" value={format(userRisk?.false_alerts_per_100, 1)} detail="Target is no more than five" icon={ShieldAlert} tone="warning"/>
        <StatCard label="Detection delay" value={typeof userRisk?.median_detection_delay_days === "number" ? `${format(userRisk.median_detection_delay_days, 1)}d` : "—"} detail="Median synthetic compromise delay" icon={GitCompareArrows} tone="info"/>
      </section>

      <section className="grid gap-4 xl:grid-cols-[1.2fr_.8fr]">
        <Card className="surface-panel">
          <CardHeader className="border-b"><SectionHeading title="Candidate comparison" description="Test-set quality across rules, logistic regression and gradient boosting"/></CardHeader>
          <CardContent className="pt-4">
            <div className="h-[330px]" role="img" aria-label="Candidate model quality comparison">
              <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{width: 720, height: 240}}>
                <BarChart data={comparison} margin={{top: 12, right: 8, left: -12, bottom: 0}}>
                  <CartesianGrid vertical={false} stroke="rgba(166,202,190,.07)"/>
                  <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{fontSize: 10, fill: "#91a59e"}}/>
                  <YAxis domain={[0, 100]} axisLine={false} tickLine={false} tick={{fontSize: 10, fill: "#91a59e"}}/>
                  <RechartsTooltip contentStyle={TOOLTIP}/>
                  <Bar dataKey="PR-AUC" fill="#54e6ae" radius={[4, 4, 0, 0]}/>
                  <Bar dataKey="Precision" fill="#78a4ff" radius={[4, 4, 0, 0]}/>
                  <Bar dataKey="Recall" fill="#a997ff" radius={[4, 4, 0, 0]}/>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="mt-2 flex flex-wrap justify-center gap-5 text-[10px] text-muted-foreground"><span className="flex items-center gap-1.5"><span className="size-2 rounded-sm bg-primary"/>PR-AUC</span><span className="flex items-center gap-1.5"><span className="size-2 rounded-sm bg-[#78a4ff]"/>Precision</span><span className="flex items-center gap-1.5"><span className="size-2 rounded-sm bg-[#a997ff]"/>Recall</span></div>
          </CardContent>
        </Card>

        <Card className="surface-panel">
          <CardHeader className="border-b"><SectionHeading title="Hybrid score composition" description="Retained baseline weights because tuning did not satisfy its promotion rule"/></CardHeader>
          <CardContent className="grid items-center gap-3 sm:grid-cols-[1fr_180px] xl:grid-cols-1 2xl:grid-cols-[1fr_170px]">
            <div className="relative h-64">
              <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{width: 720, height: 240}}>
                <PieChart>
                  <Pie data={WEIGHTS} dataKey="value" nameKey="name" innerRadius={58} outerRadius={86} paddingAngle={2} stroke="none">
                    {WEIGHTS.map((entry) => <Cell key={entry.name} fill={entry.color}/>)}
                  </Pie>
                  <RechartsTooltip contentStyle={TOOLTIP}/>
                </PieChart>
              </ResponsiveContainer>
              <div className="pointer-events-none absolute inset-0 grid place-items-center text-center"><div><p className="mono-data text-2xl font-semibold">100%</p><p className="text-[9px] text-muted-foreground">explainable</p></div></div>
            </div>
            <div className="grid gap-2">{WEIGHTS.map((weight) => <div key={weight.name} className="flex items-center justify-between rounded-lg bg-white/[.025] px-3 py-2 text-xs"><span className="flex items-center gap-2 text-muted-foreground"><span className="size-2 rounded-sm" style={{background: weight.color}}/>{weight.name}</span><strong className="mono-data">{weight.value}%</strong></div>)}</div>
          </CardContent>
        </Card>
      </section>

      <Card className="surface-panel">
        <CardHeader className="border-b"><SectionHeading title="Production promotion checklist" description="A production release requires every gate; one passing metric cannot offset another failure"/></CardHeader>
        <CardContent className="grid gap-3 pt-1 lg:grid-cols-5">
          {gates.map((gate) => {
            const pass = typeof gate.actual === "number" && (gate.direction === "min" ? gate.actual >= gate.gate : gate.actual <= gate.gate);
            return (
              <div key={gate.label} className={cn("promotion-gate", pass ? "promotion-gate-pass" : "promotion-gate-fail")}>
                <div className="flex items-center justify-between gap-2"><span className="text-xs font-semibold">{gate.label}</span>{pass ? <CheckCircle2 className="size-4 text-primary"/> : <XCircle className="size-4 text-rose-300"/>}</div>
                <p className="mono-data mt-5 text-2xl font-semibold">{format(gate.actual)}</p>
                <p className="mono-data mt-1 text-[10px] text-muted-foreground">gate {gate.direction === "min" ? "≥" : "≤"} {gate.gate.toFixed(2)}</p>
                <p className="mt-4 text-[10px] leading-4 text-muted-foreground">{gate.detail}</p>
              </div>
            );
          })}
        </CardContent>
      </Card>

      <section className="grid gap-4 xl:grid-cols-[.8fr_1.2fr]">
        <Card className="surface-panel">
          <CardHeader className="border-b"><SectionHeading title="Evaluation split" description="Training history remains isolated from validation and test"/></CardHeader>
          <CardContent className="grid grid-cols-3 gap-3">
            {[["Train", metrics.split?.train_rows], ["Validation", metrics.split?.validation_rows], ["Test", metrics.split?.test_rows]].map(([label, rows]) => <div key={String(label)} className="evidence-stat"><span>{label as string}</span><strong>{typeof rows === "number" ? rows.toLocaleString() : "—"}</strong></div>)}
          </CardContent>
        </Card>
        <Card className="surface-panel">
          <CardHeader className="border-b"><SectionHeading title="Immutable model bundle" description="Artifacts that move together through release and rollback"/></CardHeader>
          <CardContent className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {[
              [Box, "pipeline.joblib", "Authoritative Python inference"],
              [Archive, "model.onnx", "Portable runtime"],
              [FileJson, "manifest.json", "Version, hashes and status"],
              [FileJson, "metrics.json", "Evaluation and gate evidence"],
              [FileJson, "feature_schema.json", "Input contract"],
              [FileJson, "hybrid_weights.json", "Score composition"],
              [FileJson, "thresholds.json", "Decision thresholds"],
              [FileJson, "model_card.md", "Use and limitations"],
            ].map(([Icon, name, detail]) => {
              const IconComponent = Icon as typeof Box;
              return <div key={String(name)} className="rounded-xl bg-white/[.025] p-3 ring-1 ring-border"><IconComponent className="size-4 text-primary"/><p className="mono-data mt-3 text-[10px] font-semibold">{name as string}</p><p className="mt-1 text-[10px] leading-4 text-muted-foreground">{detail as string}</p></div>;
            })}
          </CardContent>
        </Card>
      </section>

      {metrics.hybrid_weight_selection?.reason ? <p className="rounded-xl border border-dashed p-4 text-xs leading-5 text-muted-foreground">{metrics.hybrid_weight_selection.reason}</p> : null}
    </div>
  );
}
