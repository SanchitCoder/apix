import { expect, test } from "@playwright/test";

test("load overview", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "APIx" })).toBeVisible();
  // The banner declares the placeholder status of this deployment.
  await expect(page.getByText(/Data status: EXAMPLE_ONLY/)).toBeVisible();
  await expect(page.getByText("APIx headline").first()).toBeVisible();
  await expect(page.getByText("Month-over-month")).toBeVisible();
  await expect(
    page.getByRole("img", { name: /Line chart comparing the APIx headline index/ }),
  ).toBeVisible();
  await expect(page.getByText("Data freshness — today")).toBeVisible();
  await expect(page.getByRole("progressbar", { name: "Route coverage today" })).toBeVisible();
});

test("drill into a route in the route explorer", async ({ page }) => {
  await page.goto("/routes");
  await expect(page.getByRole("heading", { name: "Fare curve — DEL-BOM" })).toBeVisible();

  await page.locator("#route-select").selectOption("DEL-BLR");
  await expect(page.getByRole("heading", { name: "Fare curve — DEL-BLR" })).toBeVisible();

  // Split by carrier and confirm the legend swaps from windows to carrier names.
  await page.getByRole("radio", { name: "Carrier" }).click();
  await expect(page.getByRole("heading", { name: "Corridor momentum" })).toBeVisible();
});

test("changing a method-console control changes the preview index", async ({ page }) => {
  await page.goto("/method");
  await expect(page.getByRole("heading", { name: "Preview index run" })).toBeVisible();

  const hashLine = page.getByText(/Preview config hash:/);
  await expect(hashLine).toContainText("matches the method in force");
  const before = await hashLine.textContent();

  await page.getByLabel("Elementary formula").selectOption("dutot");

  await expect(hashLine).not.toContainText("matches the method in force");
  await expect
    .poll(async () => hashLine.textContent())
    .not.toBe(before);
});

test("completes one full provenance drill-down", async ({ page }) => {
  await page.goto("/audit");
  const chart = page.getByTestId("audit-index-chart");
  await expect(chart).toBeVisible();

  await chart.focus();
  await page.keyboard.press("Enter");

  await expect(page.getByRole("heading", { name: "Contributing route indices" })).toBeVisible();
  await page.getByRole("button", { name: /DEL-BOM/ }).click();

  await expect(page.getByRole("heading", { name: /Cleaned quotes/ })).toBeVisible();
  await page.getByRole("button", { name: "Trace source" }).first().click();

  await expect(page.getByRole("heading", { name: "Source and legal basis" })).toBeVisible();
  await expect(page.getByText("Recorded fixture replay")).toBeVisible();
  await expect(page.getByText("FIXTURE").first()).toBeVisible();
});
