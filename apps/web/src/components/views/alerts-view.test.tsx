import {QueryClient, QueryClientProvider} from "@tanstack/react-query";
import {fireEvent, render, screen, waitFor} from "@testing-library/react";
import {describe, expect, it, vi} from "vitest";

const mockRequest = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({request: mockRequest}));
vi.mock("@/components/risk-context", () => ({
  useRiskContext: () => ({session: {tenant: "tenant-a", token: "analyst-token", role: "analyst"}}),
}));

import {AlertsView} from "./alerts-view";

describe("security alert queue", () => {
  it("closes the selected tenant alert with its own reason", async () => {
    let closed = false;
    const rows = [
      {id: "user-alert", user_id: "user-001", severity: "high", provider_status: "new", soc_status: "open", created_at: "2026-01-02T00:00:00Z", closure: null},
      {id: "tenant-alert", user_id: null, severity: "medium", provider_status: "new", soc_status: "open", created_at: "2026-01-01T00:00:00Z", closure: null},
    ];
    mockRequest.mockImplementation(async (path: string, _token: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        closed = true;
        return {...rows[1], soc_status: "closed"};
      }
      if (path.includes("soc_status=open")) {
        return {items: closed ? [rows[0]] : rows, next_cursor: null};
      }
      return {items: rows, next_cursor: null};
    });
    const client = new QueryClient({defaultOptions: {queries: {retry: false}}});
    render(<QueryClientProvider client={client}><AlertsView/></QueryClientProvider>);

    expect(await screen.findByText("Tenant alert")).toBeInTheDocument();
    const selectors = screen.getAllByRole("combobox", {name: "Close reason"}) as HTMLSelectElement[];
    fireEvent.change(selectors[1], {target: {value: "false_positive"}});
    expect(selectors[0].value).toBe("resolved");
    expect(selectors[1].value).toBe("false_positive");
    fireEvent.click(screen.getAllByRole("button", {name: "Close alert"})[1]);
    await waitFor(() => expect(mockRequest).toHaveBeenCalledWith(
      "/api/v1/alerts/tenant-alert/close", "analyst-token",
      {method: "POST", body: JSON.stringify({reason: "false_positive"})},
    ));
    await waitFor(() => expect(screen.queryByText("Tenant alert")).not.toBeInTheDocument());
    expect(screen.getByText("User-linked alert")).toBeInTheDocument();
  });
});
