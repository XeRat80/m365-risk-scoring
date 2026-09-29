import {mkdir} from "node:fs/promises";
import {resolve} from "node:path";
import {chromium} from "@playwright/test";

const output = resolve(process.cwd(), "../../output/playwright");
await mkdir(output, {recursive: true});
const browser = await chromium.launch({headless: true});
const page = await browser.newPage({viewport: {width: 1600, height: 1000}, deviceScaleFactor: 1});
page.setDefaultTimeout(30_000);

async function capture(name) {
  await page.evaluate(() => window.scrollTo({top: 0, behavior: "instant"}));
  await page.waitForTimeout(150);
  await page.screenshot({path: resolve(output, name), fullPage: true});
}

async function scenario(buttonName, banner, screenshot) {
  await page.getByRole("button", {name: buttonName, exact: true}).click();
  await page.getByText(banner, {exact: true}).waitFor();
  await page.waitForTimeout(2600);
  await capture(screenshot);
}

await page.goto("http://localhost:3000", {waitUntil: "networkidle"});
await capture("01-login.png");
await page.getByRole("button", {name: "Open risk command"}).click();
await page.getByRole("heading", {name: "User risk overview"}).waitFor();
await page.getByText("Incoming mail telemetry", {exact: true}).waitFor();
await page.getByRole("button", {name: "Reset", exact: true}).click();
await page.getByText("100", {exact: true}).first().waitFor({timeout: 45_000});
await page.locator(".mail-event").first().waitFor({timeout: 45_000});
await capture("02-normal-dashboard.png");

const firstEvent = page.locator(".mail-event").first();
const initialEvent = await firstEvent.innerText();
await page.waitForFunction((text) => document.querySelector(".mail-event")?.textContent !== text, initialEvent, {timeout: 20_000});
await capture("03-incoming-mail-stream.png");

await page.getByRole("button", {name: "Pause", exact: true}).click();
await page.locator(".sim-status").getByText("Paused", {exact: true}).waitFor();
await capture("04-paused-stream.png");

await scenario("credential phishing", "Credential phishing active", "05-credential-phishing.png");
await page.getByTestId("mail-event-feed").getByText(/high/).first().waitFor({timeout: 15_000});
await page.getByTestId("mail-event-feed").locator("span.text-red-300").filter({hasText: "spf"}).first().waitFor({timeout: 15_000});
await capture("05-credential-phishing.png");
await scenario("domain spoofing", "Domain spoofing active", "06-domain-spoofing.png");
await scenario("executive impersonation", "Executive impersonation active", "07-executive-impersonation.png");
await scenario("account takeover", "Account takeover active", "08-account-takeover.png");
await scenario("MFA removal", "MFA removal active", "09-mfa-removal.png");
await scenario("Entra escalation", "Entra risk escalation active", "10-entra-escalation.png");
await scenario("throttling", "Graph throttling active", "11-throttling.png");

await page.getByRole("button", {name: "recovery", exact: true}).click();
await page.getByText("Normal traffic baseline", {exact: true}).waitFor();
await page.waitForTimeout(2600);
await capture("12-recovery.png");

await page.getByPlaceholder("Search users").fill("user-001");
await page.getByRole("button", {name: "User 001"}).click();
await page.getByRole("heading", {name: /user-001 · score/}).waitFor();
await page.getByLabel("Analyst note (optional)").fill("Validated in the offline simulation.");
await page.getByRole("button", {name: "safe", exact: true}).click();
await page.getByText("Recorded: safe", {exact: true}).waitFor();
await capture("13-feedback-and-explanation.png");

await page.getByRole("button", {name: "Sign out"}).click();
await page.getByLabel("Tenant").click();
await page.getByRole("option", {name: "Contoso Operations"}).click();
await page.getByRole("button", {name: "Open risk command"}).click();
await page.getByText("Contoso Operations · admin", {exact: true}).waitFor();
await page.getByPlaceholder("Search users").fill("user-001");
await page.getByRole("button", {name: "User 001"}).click();
await page.getByRole("heading", {name: /user-001 · score/}).waitFor();
await capture("14-tenant-isolation.png");

await browser.close();
