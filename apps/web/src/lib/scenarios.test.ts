import {describe, expect, it} from "vitest";
import {SCENARIOS, scenarioDefinition} from "./scenarios";

describe("scenario catalog", () => {
  it("keeps scenario ids unique and analyst guidance complete", () => {
    expect(new Set(SCENARIOS.map(({id}) => id)).size).toBe(SCENARIOS.length);
    expect(SCENARIOS.every(({signal, consequence, affected}) =>
      signal.length > 0 && consequence.length > 0 && affected.length > 0,
    )).toBe(true);
  });

  it("resolves a known scenario", () => {
    expect(scenarioDefinition("credential-phishing")?.family).toBe("mail");
    expect(scenarioDefinition("unknown")).toBeUndefined();
  });
});
