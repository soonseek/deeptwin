import assert from 'node:assert/strict';

export async function openModelSettings(page) {
  await page.locator('#model-settings[data-ready="true"]').waitFor();
  if (!await page.locator('#model-settings').evaluate(el => el.open)) await page.locator('#model-settings > summary').click();
}

export async function saveModelSelection(page, model = 'gpt-fixture', effort = 'medium') {
  await openModelSettings(page);
  await page.locator('#model-connection').selectOption('codex:subscription');
  await page.locator('#refresh-model-catalog').click();
  await page.locator('#model-settings[data-catalog-status="ready"]').waitFor();
  await page.locator('#model-choice').selectOption(model);
  await page.locator('#model-effort').selectOption(effort);
  await page.locator('#save-model-selection').click();
  await page.locator('#model-selection-status[data-state="saved"]').waitFor();
  assert.equal(await page.locator('#model-choice').inputValue(), model);
}

export async function ensureModelSelection(page) {
  await page.locator('#model-settings[data-ready="true"]').waitFor();
  if (await page.locator('#model-selection-status').getAttribute('data-state') !== 'saved') await saveModelSelection(page);
}
