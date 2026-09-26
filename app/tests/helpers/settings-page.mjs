// Opening one panel of the settings page in a real browser (2026-09-26 UI phase 2: the
// operations sections moved there from the records page, one panel shown at a time by the
// address's fragment). A fragment-only change is a same-document navigation that reads
// nothing again, so when the page is already open it is reloaded: every open reads the
// server's state afresh, as opening the records page used to.

export async function openSettings(page, url, panel) {
  const target = `${url}settings.html#${panel}`;
  const already = page.url().split('#', 1)[0] === `${url}settings.html`;
  await page.goto(target);
  if (already) await page.reload();
  await page.locator(`#${panel}`).waitFor();
}
