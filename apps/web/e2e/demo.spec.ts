import {expect, test} from "@playwright/test";

const API = "http://localhost:8000";

type Session = {token: string};
type Run = {
  id: string;
  scenario: string;
  target_user_id: string;
  status: "queued" | "syncing" | "evaluating" | "detected" | "missed" | "reset";
  detected: boolean;
  measurements: {mail_observations?: number};
};

test("keeps scenarios in the validation lab and detects their evidence in the SOC", async ({page}) => {
  test.setTimeout(150_000);

  await page.goto("/");
  await expect(page.getByRole("heading", {name: /See user risk/})).toBeVisible();
  await page.getByRole("button", {name: "Open risk command"}).click();
  await expect(page.getByRole("heading", {name: "User risk overview"})).toBeVisible({timeout: 20_000});
  await expect(page.getByText("Connector health")).toBeVisible();
  await expect(page.getByText("Incoming mail telemetry")).toBeVisible();
  await expect(page.getByText("Scenario control")).toHaveCount(0);

  const {token} = await page.evaluate(() => JSON.parse(localStorage.getItem("m365-risk-session") ?? "{}") as Session);
  expect(token).toBeTruthy();
  const headers = {Authorization: `Bearer ${token}`};
  const usersResponse = await page.request.get(`${API}/api/v1/users?limit=100`, {headers});
  expect(usersResponse.ok()).toBeTruthy();
  const users = await usersResponse.json() as {items: Array<{id: string}>};
  expect(users.items).toHaveLength(100);
  expect(users.items.some((user) => user.id === "user-001")).toBe(true);

  const lab = await page.context().newPage();
  await lab.goto("http://localhost:3002");
  await expect(lab.getByRole("heading", {name: "Scenario launcher"})).toBeVisible();
  await expect(lab.locator('#target option[value="user-001"]')).toBeAttached({timeout: 20_000});
  await lab.locator("#target").selectOption("user-001");
  await lab.getByRole("button", {name: "Run targeted validation"}).click();
  await expect(lab.locator("#runId")).toContainText("Run ", {timeout: 20_000});
  await expect(lab.getByRole("heading", {name: "Live data flow"})).toBeVisible();

  let runId = "";
  await expect.poll(async () => {
    const response = await page.request.get(`${API}/api/v1/simulation-runs?limit=1`, {headers});
    expect(response.ok()).toBeTruthy();
    const payload = await response.json() as {items: Run[]};
    const run = payload.items[0];
    if (run?.scenario === "credential-phishing" && run.target_user_id === "user-001") runId = run.id;
    return runId;
  }, {timeout: 20_000}).not.toBe("");

  const currentRun = async () => {
    const response = await page.request.get(`${API}/api/v1/simulation-runs/${runId}`, {headers});
    expect(response.ok()).toBeTruthy();
    return await response.json() as Run;
  };
  await expect.poll(async () => (await currentRun()).status, {timeout: 90_000, intervals: [1000]}).toBe("detected");
  const completed = await currentRun();
  expect(completed.detected).toBe(true);
  expect(completed.measurements.mail_observations).toBeGreaterThan(0);
  await expect(lab.locator("#status")).toHaveText("detected", {timeout: 15_000});

  const mailResponse = await page.request.get(`${API}/api/v1/mail/events?limit=50`, {headers});
  expect(mailResponse.ok()).toBeTruthy();
  const mail = await mailResponse.json() as {items: Array<Record<string, unknown>>};
  expect(mail.items.some((event) => event.user_id === "user-001" && Number(event.risk_probability) >= 0.7)).toBe(true);
  for (const event of mail.items) {
    expect(event).not.toHaveProperty("subject");
    expect(event).not.toHaveProperty("body");
    expect(event).not.toHaveProperty("preview");
  }

  await page.goto("/users/user-001");
  await expect(page.getByRole("heading", {name: "User 001"})).toBeVisible({timeout: 20_000});
  await expect(page.getByRole("heading", {name: "Current assessment"})).toBeVisible();
  await page.goto("/mail");
  await expect(page.getByRole("heading", {name: "Privacy-safe header telemetry"})).toBeVisible();

  await page.getByRole("button", {name: "Sign out"}).click();
  await page.getByLabel("Tenant").click();
  await page.getByRole("option", {name: "Contoso Operations"}).click();
  await page.getByRole("button", {name: "Open risk command"}).click();
  await expect(page.getByRole("heading", {name: "User risk overview"})).toBeVisible({timeout: 20_000});
  const secondSession = await page.evaluate(() => JSON.parse(localStorage.getItem("m365-risk-session") ?? "{}") as Session);
  const crossTenant = await page.request.get(`${API}/api/v1/simulation-runs/${runId}`, {
    headers: {Authorization: `Bearer ${secondSession.token}`},
  });
  expect(crossTenant.status()).toBe(404);
});
