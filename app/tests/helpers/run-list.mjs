// UI phase 5 (docs/ui/2026-09-26-product-ux-redesign.md §5.2): a run is opened from the run list
// table on observe.html; inside a run, the header's compact "다른 실행" switch opens another one.
// Browser journeys use this instead of the select that used to be the page's only way to a run.

export async function openRunFromList(page, runId) {
  if (await page.locator('#run-empty').isVisible()) {
    await page.locator(`#run-table a[data-run-id="${runId}"]`).first().click();
  } else {
    await page.getByRole('combobox', { name: '다른 실행 열기' }).selectOption(runId);
  }
  await page.locator(`#run-panel[data-run-id="${runId}"]`).waitFor({ state: 'attached' });
}
