import {fireEvent, render, screen} from "@testing-library/react";
import {describe, expect, it, vi} from "vitest";

vi.mock("@/components/risk-context", () => ({
  useRiskContext: () => ({session: {tenant: "tenant-a", token: "token", role: "analyst"}}),
}));

vi.mock("@tanstack/react-query", () => ({
  useQuery: ({queryKey}: {queryKey: string[]}) => queryKey[0] === "users"
    ? {data: {items: [{id: "user-001", display_name: "Demo User", score: 50, level: "high"}]}}
    : {
        data: {
          user_id: "user-001",
          feature_version: "UserFeatureWindowV2",
          model_version: "shadow-rules-v2",
          calculated_at: "2026-09-17T12:00:00Z",
          score: null,
          level: "insufficient_data",
          components: {email_threat: null},
          coverage: {email_threat: "unavailable"},
          nodes: [
            {id: "employee:user-001", kind: "employee", label: "Demo User", status: "available", value: null, observed_at: null, metadata: {user_id: "user-001"}},
            {id: "feature:email_top3", kind: "feature", label: "Email Top3", status: "unavailable", value: null, observed_at: null, metadata: {}},
            {id: "component:email_threat", kind: "component", label: "Email Threat", status: "unavailable", value: null, observed_at: null, metadata: {}},
          ],
          edges: [{source: "feature:email_top3", target: "component:email_threat", relation: "CONTRIBUTES_TO"}],
        },
        isError: false,
      },
}));

import {GraphView} from "./graph-view";

describe("field data graph", () => {
  it("exposes labelled controls and preserves unavailable evidence", () => {
    render(<GraphView/>);
    expect(screen.getByRole("heading", {name: "Field data graph"})).toBeInTheDocument();
    expect(screen.getByRole("combobox", {name: "Select employee"})).toBeInTheDocument();
    expect(screen.getByRole("combobox", {name: "Filter evidence path"})).toBeInTheDocument();
    expect(screen.getAllByText("unavailable").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", {name: /Email Threat/i}));
    expect(screen.getAllByText("component:email_threat")).toHaveLength(2);
  });
});
