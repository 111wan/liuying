import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import { mkdir, stat } from 'node:fs/promises';
import path from 'node:path';

const output = path.resolve('../test-results');
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome' });
const context = await browser.newContext({ viewport: { width: 1440, height: 1080 }, acceptDownloads: true });
const page = await context.newPage();
const errors = [];
page.on('pageerror', error => errors.push(error.message));
page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });

try {
  await page.goto('http://127.0.0.1:8000');
  await page.getByRole('button', { name: '解析链接', exact: true }).waitFor();
  await page.waitForFunction(() => !document.querySelector('button.primary')?.disabled);
  await page.screenshot({ path: path.join(output, 'desktop-home.png'), fullPage: true });
  await page.getByRole('button', { name: '解析链接', exact: true }).click();
  assert.match(await page.getByRole('alert').innerText(), /请先粘贴/);
  await page.getByRole('button', { name: '试用公开样片' }).click();
  await page.getByRole('heading', { name: 'Sintel · 官方公开预告片' }).waitFor({ timeout: 75000 });
  assert.match(await page.locator('.watermark').innerText(), /水印情况未知/);
  await page.screenshot({ path: path.join(output, 'desktop-result.png'), fullPage: true });
  await page.getByRole('button', { name: '准备下载', exact: true }).click();
  await page.getByRole('button', { name: '保存到设备', exact: true }).waitFor({ timeout: 120000 });
  const pendingDownload = page.waitForEvent('download');
  await page.getByRole('button', { name: '保存到设备', exact: true }).click();
  const download = await pendingDownload;
  await download.saveAs(path.join(output, download.suggestedFilename()));
  const saved = await stat(path.join(output, download.suggestedFilename()));
  assert.ok(saved.size > 1_000_000);
  await page.getByRole('button', { name: /^任务/ }).click();
  await page.getByRole('button', { name: '保存', exact: true }).waitFor();
  await page.screenshot({ path: path.join(output, 'desktop-tasks.png'), fullPage: true });
  await page.reload();
  await page.getByRole('button', { name: '保存', exact: true }).waitFor();
  await page.getByRole('button', { name: '支持平台', exact: true }).click();
  await page.getByRole('heading', { name: '视频直链', exact: true }).waitFor();
  assert.equal(await page.locator('.platform-state.experimental').count(), 8);
  await page.screenshot({ path: path.join(output, 'desktop-platforms.png'), fullPage: true });
  await page.getByRole('button', { name: '下载', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('nav button.current')?.textContent === '下载');
  for (const width of [390, 320, 768]) {
    await page.setViewportSize({ width, height: 844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `Horizontal overflow at ${width}`);
    await page.screenshot({ path: path.join(output, `responsive-${width}.png`), fullPage: true });
  }
  await page.getByRole('button', { name: /^任务/ }).click();
  await page.getByRole('button', { name: '查看', exact: true }).first().click();
  await page.getByRole('heading', { name: 'Sintel · 官方公开预告片' }).waitFor();
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.screenshot({ path: path.join(output, `mobile-result-${width}.png`), fullPage: true });
  }
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ pass: true, savedFile: download.suggestedFilename(), bytes: saved.size, widths: [1440, 768, 390, 320], consoleErrors: errors.length }, null, 2));
} finally {
  await browser.close();
}
