"use client";

import dynamic from "next/dynamic";
import {LoginPanel} from "@/components/login-panel";
import {AppShell} from "@/components/app-shell";
import {RiskContextProvider} from "@/components/risk-context";
import {Skeleton} from "@/components/ui/skeleton";
import {useRiskSession} from "@/lib/session";

export type RiskView = "overview" | "users" | "user" | "mail" | "graph" | "operations" | "models";

function ViewSkeleton() {
  return (
    <div aria-label="Loading page" className="grid gap-5">
      <div className="space-y-3">
        <Skeleton className="h-3 w-28"/>
        <Skeleton className="h-10 w-[min(480px,80vw)]"/>
        <Skeleton className="h-4 w-[min(680px,90vw)]"/>
      </div>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {Array.from({length: 4}, (_, index) => <Skeleton key={index} className="h-36 rounded-xl"/>)}
      </div>
      <div className="grid gap-4 xl:grid-cols-[1.35fr_.65fr]">
        <Skeleton className="h-[420px] rounded-xl"/>
        <Skeleton className="h-[420px] rounded-xl"/>
      </div>
    </div>
  );
}

const OverviewView = dynamic(() => import("@/components/views/overview-view").then((module) => module.OverviewView), {loading: () => <ViewSkeleton/>});
const UsersView = dynamic(() => import("@/components/views/users-view").then((module) => module.UsersView), {loading: () => <ViewSkeleton/>});
const UserView = dynamic(() => import("@/components/views/user-view").then((module) => module.UserView), {loading: () => <ViewSkeleton/>});
const MailView = dynamic(() => import("@/components/views/mail-view").then((module) => module.MailView), {loading: () => <ViewSkeleton/>});
const GraphView = dynamic(() => import("@/components/views/graph-view").then((module) => module.GraphView), {loading: () => <ViewSkeleton/>});
const OperationsView = dynamic(() => import("@/components/views/operations-view").then((module) => module.OperationsView), {loading: () => <ViewSkeleton/>});
const ModelsView = dynamic(() => import("@/components/views/models-view").then((module) => module.ModelsView), {loading: () => <ViewSkeleton/>});

export function RiskCommand({view, userId}: {view: RiskView; userId?: string}) {
  const {session, login, logout} = useRiskSession();
  if (!session) return <LoginPanel onLogin={login}/>;

  return (
    <RiskContextProvider session={session}>
      <AppShell session={session} onLogout={logout}>
        {view === "overview" ? <OverviewView/> : null}
        {view === "users" ? <UsersView/> : null}
        {view === "user" ? <UserView userId={userId ?? ""}/> : null}
        {view === "mail" ? <MailView/> : null}
        {view === "graph" ? <GraphView/> : null}
        {view === "operations" ? <OperationsView/> : null}
        {view === "models" ? <ModelsView/> : null}
      </AppShell>
    </RiskContextProvider>
  );
}
