import {render, screen} from "@testing-library/react";
import {describe, expect, it} from "vitest";
import {RiskBadge, ScoreRing} from "./risk-ui";

describe("risk presentation", () => {
  it("exposes a readable score and clamps impossible values", () => {
    const {rerender} = render(<ScoreRing score={82}/>);
    expect(screen.getByRole("img", {name: "Risk score 82 out of 100"})).toBeInTheDocument();

    rerender(<ScoreRing score={140}/>);
    expect(screen.getByRole("img", {name: "Risk score 100 out of 100"})).toBeInTheDocument();
  });

  it("renders the semantic risk level", () => {
    render(<RiskBadge level="critical"/>);
    expect(screen.getByText("critical")).toBeInTheDocument();
  });
});
