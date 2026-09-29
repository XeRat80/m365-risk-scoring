import {render, screen} from "@testing-library/react";
import {Users} from "lucide-react";
import {describe, expect, it} from "vitest";
import {MetricCard} from "./metric-card";

describe("MetricCard", () => {it("renders the value and label", () => {render(<MetricCard label="Protected users" value={200} detail="All tenants" icon={Users}/>); expect(screen.getByText("Protected users")).toBeInTheDocument(); expect(screen.getByText("200")).toBeInTheDocument();});});
