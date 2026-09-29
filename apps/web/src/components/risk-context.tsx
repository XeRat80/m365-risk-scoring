"use client";

import {useMutation, useQuery, useQueryClient} from "@tanstack/react-query";
import {createContext, useContext, type ReactNode} from "react";
import {
  request,
  type Connection,
  type DashboardSummary,
  type ModelInfo,
  type Onboarding,
} from "@/lib/api";
import type {Session} from "@/lib/session";

type RiskContextValue = {
  session: Session;
  summary?: DashboardSummary;
  connection?: Connection;
  model?: ModelInfo;
  loading: boolean;
  stale: boolean;
  commonError: boolean;
  startOnboarding: () => void;
  onboardingBusy: boolean;
};

const RiskContext = createContext<RiskContextValue | null>(null);

export function RiskContextProvider({session, children}: {session: Session; children: ReactNode}) {
  const queryClient = useQueryClient();
  const summary = useQuery({
    queryKey: ["summary", session.tenant],
    queryFn: () => request<DashboardSummary>("/api/v1/dashboard/summary", session.token),
    refetchInterval: 5_000,
  });
  const connection = useQuery({
    queryKey: ["connection", session.tenant],
    queryFn: () => request<Connection>("/api/v1/tenants/connection", session.token),
    refetchInterval: 10_000,
  });
  const model = useQuery({
    queryKey: ["model", session.tenant],
    queryFn: () => request<ModelInfo>("/api/v1/models/current", session.token),
    staleTime: 60_000,
  });
  const onboarding = useMutation({
    mutationFn: () => request<Onboarding>("/api/v1/tenants/onboarding/start", session.token, {method: "POST"}),
    onSuccess: (result) => {
      if (result.url) window.location.assign(result.url);
      else void queryClient.invalidateQueries({queryKey: ["connection", session.tenant]});
    },
  });

  const data = summary.data;
  const stale = !data?.last_sync_at || (
    summary.dataUpdatedAt > 0 &&
    summary.dataUpdatedAt - new Date(data.last_sync_at).getTime() > 30_000
  );

  return (
    <RiskContext.Provider
      value={{
        session,
        summary: summary.data,
        connection: connection.data,
        model: model.data,
        loading: summary.isLoading || connection.isLoading || model.isLoading,
        stale,
        commonError: summary.isError || connection.isError || model.isError,
        startOnboarding: () => onboarding.mutate(),
        onboardingBusy: onboarding.isPending,
      }}
    >
      {children}
    </RiskContext.Provider>
  );
}

export function useRiskContext() {
  const context = useContext(RiskContext);
  if (!context) throw new Error("useRiskContext must be used inside RiskContextProvider");
  return context;
}
