import {expect, test} from "@playwright/test";

test("signs into the offline tenant and shows the dashboard", async ({page}) => {
  test.setTimeout(150_000);
  await page.goto("/");
  await expect(page.getByRole("heading", {name: /See user risk/})).toBeVisible();
  await page.getByRole("button", {name: "Open risk command"}).click();
  await expect(page.getByRole("heading", {name: "User risk overview"})).toBeVisible({timeout: 20_000});
  await expect(page.getByText("Scenario control")).toBeVisible();
  await expect(page.getByText("Connector health")).toBeVisible();
  await expect(page.getByText("Incoming mail telemetry")).toBeVisible();
  const liveStatus = page.locator(".sim-status strong");
  const session = await page.evaluate(() => JSON.parse(localStorage.getItem("m365-risk-session") ?? "{}") as {token: string});
  const latestSync = async () => {
    const response = await page.request.get("http://localhost:8000/api/v1/sync/jobs?limit=1", {
      headers: {Authorization: `Bearer ${session.token}`},
    });
    expect(response.ok()).toBeTruthy();
    return ((await response.json()) as {items: Array<{id: string; status: string}>}).items[0];
  };
  const latestMail = async () => {
    const response = await page.request.get("http://localhost:8000/api/v1/mail/events?limit=24", {
      headers: {Authorization: `Bearer ${session.token}`},
    });
    expect(response.ok()).toBeTruthy();
    const payload = await response.json() as {items: Array<Record<string, unknown>>};
    for (const event of payload.items) {
      expect(event).not.toHaveProperty("subject");
      expect(event).not.toHaveProperty("body");
      expect(event).not.toHaveProperty("preview");
    }
    return payload.items;
  };
  const priorSyncId = (await latestSync())?.id;
  await page.getByRole("button", {name: "Reset"}).click();
  await expect(liveStatus).toContainText("normal", {timeout: 10_000});
  await expect.poll(async () => {
    const latest = await latestSync();
    return latest?.id !== priorSyncId ? latest?.status : "unchanged";
  }, {timeout: 45_000, intervals: [250]}).toBe("completed");
  await page.getByPlaceholder("Search users").fill("user-001");
  await expect(page.getByRole("button", {name: "User 001"})).toBeVisible({timeout: 20_000});
  await page.getByRole("button", {name: "User 001"}).click();
  const scoreHeading = page.getByRole("heading", {name: /user-001 · score/});
  await expect(scoreHeading).toBeVisible();
  const readScore = async () => Number((await scoreHeading.textContent())?.match(/score (\d+)/)?.[1] ?? 0);
  await expect.poll(readScore, {timeout: 20_000, intervals: [500]}).toBeLessThan(50);
  await expect(page.getByText("Data is stale or synchronization is still completing.")).toBeHidden({timeout: 20_000});
  const initialMailId = String((await latestMail())[0]?.id ?? "");
  await expect.poll(async () => String((await latestMail())[0]?.id ?? ""), {timeout: 20_000, intervals: [1000]}).not.toBe(initialMailId);
  const initialRisk = await readScore();
  await expect(page.getByText("Recommended actions")).toBeVisible();
  await page.getByLabel("Analyst note (optional)").fill("Validated in the offline simulation.");
  await page.getByRole("button", {name: "safe", exact: true}).click();
  await expect(page.getByText("Recorded: safe")).toBeVisible();

  const initialStatus = await liveStatus.textContent();
  await expect.poll(async () => liveStatus.textContent(), {timeout: 8_000}).not.toBe(initialStatus);
  const preScenarioSyncId = (await latestSync())?.id;
  await page.getByRole("button", {name: "credential phishing"}).click();
  await expect(liveStatus).toContainText("credential-phishing", {timeout: 10_000});
  await expect(page.getByText("Credential phishing active")).toBeVisible();
  await expect.poll(async () => {
    const latest = await latestSync();
    return latest?.id !== preScenarioSyncId ? latest?.status : "unchanged";
  }, {timeout: 10_000, intervals: [250]}).toBe("completed");
  await expect.poll(readScore, {timeout: 10_000, intervals: [500]}).toBeGreaterThan(initialRisk);
  await expect.poll(async () => (await latestMail()).some((event) => Number(event.risk_probability) >= .7 && Object.values(event.authentication_results as Record<string, string>).includes("fail")), {timeout: 10_000, intervals: [500]}).toBe(true);
  await expect(page.getByTestId("mail-event-feed").getByText(/high/).first()).toBeVisible();
  const compromisedRisk = await readScore();
  await expect(page.getByText("High-risk email headers")).toBeVisible();
  await page.getByRole("button", {name: "recovery"}).click();
  await expect(liveStatus).toContainText("normal", {timeout: 10_000});
  await page.getByRole("button", {name: "Reset"}).click();
  await expect(liveStatus).toContainText("normal", {timeout: 10_000});

  await page.getByRole("button", {name: "Sign out"}).click();
  await page.getByLabel("Tenant").click();
  await page.getByRole("option", {name: "Contoso Operations"}).click();
  await page.getByRole("button", {name: "Open risk command"}).click();
  await expect(page.getByText("Contoso Operations · admin")).toBeVisible();
  await page.getByPlaceholder("Search users").fill("user-001");
  await page.getByRole("button", {name: "User 001"}).click();
  const tenantTwoScore = await readScore();
  expect(tenantTwoScore).toBeLessThan(compromisedRisk);
});
