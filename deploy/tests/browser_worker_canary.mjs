#!/usr/bin/env node

import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  chmod,
  mkdir,
  readFile,
  readdir,
  realpath,
  stat,
  writeFile,
} from "node:fs/promises";
import {
  networkInterfaces,
  platform as operatingSystem,
} from "node:os";
import { basename, dirname, isAbsolute, join } from "node:path";
import { pathToFileURL } from "node:url";
import { inflateRawSync } from "node:zlib";

const EXPECTED_PLAYWRIGHT_VERSION = "1.63.0";
const EXPECTED_BROWSER_VERSION = "153.0.8010.12";
const EXPECTED_BROWSER = {
  x64: {
    architecture: "amd64",
    bytes: 197422408,
    sha256: "ded93a9c9a53a1ae040f08124badcca95c938e9d5015ff340c3b5538c41bf39e",
  },
  arm64: {
    architecture: "arm64",
    bytes: 189402512,
    sha256: "f5d89353cc9ef8dc1541268bbee1f05ee40a31ce3d9799b3a274e5147f6a8cdb",
  },
};
const FORBIDDEN_BROWSER_ARGUMENTS = [
  "--disable-gpu-sandbox",
  "--disable-namespace-sandbox",
  "--disable-seccomp-filter-sandbox",
  "--disable-setuid-sandbox",
  "--disable-sandbox",
  "--no-sandbox",
  "--single-process",
];
const HTTP_PROBE_URL = "https://192.0.2.1/deeptwin-egress-canary";
const WEBSOCKET_PROBE_URL = "wss://198.51.100.1/deeptwin-egress-canary";
const PNG_SIGNATURE = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);

function fail(message) {
  throw new Error(message);
}

function usage() {
  return [
    "usage:",
    "  node deploy/tests/browser_worker_canary.mjs \\",
    "    --playwright /absolute/path/to/playwright-core/index.mjs \\",
    "    --browser /absolute/path/to/chrome-headless-shell \\",
    "    --output /absolute/path/to/new-output-directory",
    "",
    "The output directory must not exist. Run inside a Linux container with",
    "--network none, a non-root user, and no proxy environment variables.",
  ].join("\n");
}

function parseArguments(argv) {
  if (argv.includes("--help") || argv.includes("-h")) {
    console.log(usage());
    process.exit(0);
  }
  const result = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!value || !["--playwright", "--browser", "--output"].includes(key)) {
      fail(usage());
    }
    if (result[key]) fail(`duplicate argument: ${key}`);
    result[key] = value;
  }
  for (const key of ["--playwright", "--browser", "--output"]) {
    if (!result[key]) fail(usage());
    if (!isAbsolute(result[key])) fail(`${key} must be an absolute path`);
  }
  return {
    browserPath: result["--browser"],
    outputDirectory: result["--output"],
    playwrightPath: result["--playwright"],
  };
}

async function sha256File(path) {
  const hash = createHash("sha256");
  const file = await import("node:fs").then(({ createReadStream }) => createReadStream(path));
  for await (const chunk of file) hash.update(chunk);
  return hash.digest("hex");
}

function sha256Buffer(buffer) {
  return createHash("sha256").update(buffer).digest("hex");
}

function assertLinuxNonRoot() {
  if (operatingSystem() !== "linux") fail("canary must run on Linux");
  if (typeof process.getuid !== "function" || typeof process.getgid !== "function") {
    fail("runtime does not expose POSIX identity");
  }
  const uid = process.getuid();
  const gid = process.getgid();
  if (uid === 0) fail("browser worker canary refuses to run as root");
  return { uid, gid };
}

async function assertNoExternalNetworkNamespace() {
  const unexpectedInterfaces = [];
  for (const [name, addresses] of Object.entries(networkInterfaces())) {
    for (const address of addresses ?? []) {
      if (!address.internal && name !== "lo") {
        unexpectedInterfaces.push(`${name}:${address.address}`);
      }
    }
  }
  if (unexpectedInterfaces.length) {
    fail(`non-loopback network interfaces present: ${unexpectedInterfaces.join(", ")}`);
  }

  const proxyVariables = Object.entries(process.env)
    .filter(([key, value]) => value && /^(all|http|https)_proxy$/i.test(key))
    .map(([key]) => key)
    .sort();
  if (proxyVariables.length) {
    fail(`proxy environment variables are forbidden: ${proxyVariables.join(", ")}`);
  }

  const routeFiles = ["/proc/net/route", "/proc/net/ipv6_route"];
  const observedRoutes = [];
  for (const path of routeFiles) {
    let content;
    try {
      content = await readFile(path, "utf8");
    } catch (error) {
      fail(`cannot inspect ${path}: ${error.message}`);
    }
    for (const line of content.trim().split("\n").slice(path.endsWith("/route") ? 1 : 0)) {
      const fields = line.trim().split(/\s+/);
      if (!fields[0]) continue;
      const interfaceName = path.endsWith("ipv6_route") ? fields.at(-1) : fields[0];
      observedRoutes.push(`${basename(path)}:${interfaceName}`);
      if (interfaceName !== "lo") fail(`non-loopback kernel route present in ${path}: ${line}`);
    }
  }
  return { observedRoutes, unexpectedInterfaces, proxyVariables };
}

async function verifyPinnedInputs(playwrightPath, browserPath) {
  const expected = EXPECTED_BROWSER[process.arch];
  if (!expected) fail(`unsupported runtime architecture: ${process.arch}`);
  const canonicalPlaywrightPath = await realpath(playwrightPath);
  const canonicalBrowserPath = await realpath(browserPath);
  const browserStat = await stat(canonicalBrowserPath);
  if (!browserStat.isFile()) fail("browser executable is not a regular file");
  if ((browserStat.mode & 0o111) === 0) fail("browser executable has no execute bit");
  assert.equal(browserStat.size, expected.bytes, "browser executable byte count");
  assert.equal(await sha256File(canonicalBrowserPath), expected.sha256, "browser executable SHA-256");

  const packagePath = join(dirname(canonicalPlaywrightPath), "package.json");
  const packageDocument = JSON.parse(await readFile(packagePath, "utf8"));
  assert.equal(packageDocument.name, "playwright-core", "Playwright package name");
  assert.equal(packageDocument.version, EXPECTED_PLAYWRIGHT_VERSION, "Playwright package version");
  return {
    architecture: expected.architecture,
    browser: {
      bytes: browserStat.size,
      path: canonicalBrowserPath,
      sha256: expected.sha256,
      version: EXPECTED_BROWSER_VERSION,
    },
    playwright: {
      entrypointPath: canonicalPlaywrightPath,
      entrypointSha256: await sha256File(canonicalPlaywrightPath),
      version: packageDocument.version,
    },
  };
}

function readProcessStatus(content) {
  const fields = new Map();
  for (const line of content.split("\n")) {
    const separator = line.indexOf(":");
    if (separator !== -1) fields.set(line.slice(0, separator), line.slice(separator + 1).trim());
  }
  return fields;
}

async function chromiumProcessEvidence(browserPath, uid, cdpProcessInfo) {
  const expectedExecutable = await realpath(browserPath);
  const cdpEntries = cdpProcessInfo.map((entry) => ({
    id: Number(entry.id),
    type: entry.type,
  }));
  const evidence = [];
  const processDirectories = (await readdir("/proc", { withFileTypes: true }))
    .filter((entry) => entry.isDirectory() && /^\d+$/.test(entry.name))
    .map((entry) => Number(entry.name))
    .sort((left, right) => left - right);
  for (const pid of processDirectories) {
    let commandLine;
    let executable;
    let status;
    try {
      commandLine = (await readFile(`/proc/${pid}/cmdline`))
        .toString("utf8")
        .split("\0")
        .filter(Boolean);
      executable = await realpath(`/proc/${pid}/exe`);
      status = readProcessStatus(await readFile(`/proc/${pid}/status`, "utf8"));
    } catch {
      continue;
    }
    if (executable !== expectedExecutable) continue;
    const namespacePids = (status.get("NSpid") ?? String(pid))
      .split(/\s+/)
      .map(Number)
      .filter((value) => Number.isInteger(value) && value > 0);
    const cdpMatches = cdpEntries.filter((entry) => namespacePids.includes(entry.id));
    for (const argument of commandLine) {
      const forbidden = FORBIDDEN_BROWSER_ARGUMENTS.find(
        (value) => argument === value || argument.startsWith(`${value}=`),
      );
      if (forbidden) fail(`Chromium process ${pid} contains forbidden argument ${forbidden}`);
    }
    const realUid = Number(status.get("Uid")?.split(/\s+/)[0]);
    if (realUid !== uid) fail(`Chromium process ${pid} runs as uid ${realUid}, expected ${uid}`);
    evidence.push({
      cdpMatches,
      commandType: commandLine.find((value) => value.startsWith("--type="))?.slice(7) ?? null,
      noNewPrivileges: Number(status.get("NoNewPrivs")),
      namespacePids,
      pid,
      seccomp: Number(status.get("Seccomp")),
      uid: realUid,
    });
  }
  const diagnostics = { cdpEntries, pinnedExecutableProcesses: evidence };
  if (!evidence.length) {
    fail(`no /proc process resolved to the pinned Chromium executable: ${JSON.stringify(diagnostics)}`);
  }
  const renderer = evidence.find((entry) => entry.cdpMatches.some((match) => match.type === "renderer"));
  if (!renderer) fail(`CDP/NSpid inventory contains no pinned renderer: ${JSON.stringify(diagnostics)}`);
  if (renderer.commandType !== null && renderer.commandType !== "renderer") {
    fail(`renderer cmdline contradicts CDP/NSpid type: ${JSON.stringify(diagnostics)}`);
  }
  if (renderer.noNewPrivileges !== 1 || renderer.seccomp !== 2) {
    fail(`renderer sandbox state is insufficient: NoNewPrivs=${renderer.noNewPrivileges}, Seccomp=${renderer.seccomp}`);
  }
  const matchedCdpIds = new Set(evidence.flatMap((entry) => entry.cdpMatches.map((match) => match.id)));
  return {
    cdpEntries,
    processes: evidence,
    unmatchedCdpEntries: cdpEntries.filter((entry) => !matchedCdpIds.has(entry.id)),
  };
}

function validatePng(buffer) {
  if (buffer.length < 5000) fail(`PNG is unexpectedly small: ${buffer.length} bytes`);
  if (!buffer.subarray(0, 8).equals(PNG_SIGNATURE)) fail("PNG signature mismatch");
  if (buffer.subarray(12, 16).toString("ascii") !== "IHDR") fail("PNG has no IHDR chunk");
  if (buffer.subarray(-8, -4).toString("ascii") !== "IEND") fail("PNG has no terminal IEND chunk");
  const width = buffer.readUInt32BE(16);
  const height = buffer.readUInt32BE(20);
  if (width !== 1280 || height < 900) fail(`unexpected PNG dimensions: ${width}x${height}`);
  return { height, width };
}

function validatePdf(buffer) {
  if (buffer.length < 10000) fail(`PDF is unexpectedly small: ${buffer.length} bytes`);
  if (!buffer.subarray(0, 5).equals(Buffer.from("%PDF-"))) fail("PDF header mismatch");
  const tail = buffer.subarray(Math.max(0, buffer.length - 2048)).toString("latin1");
  if (!tail.includes("startxref") || !/%%EOF\s*$/.test(tail)) fail("PDF trailer is incomplete");
  const text = buffer.toString("latin1");
  if (!text.includes("/Type /Catalog")) fail("PDF catalog is missing");
  return { version: buffer.subarray(5, 8).toString("ascii") };
}

function zipCentralDirectory(buffer) {
  const lowerBound = Math.max(0, buffer.length - 65557);
  let end = -1;
  for (let offset = buffer.length - 22; offset >= lowerBound; offset -= 1) {
    if (buffer.readUInt32LE(offset) === 0x06054b50) {
      end = offset;
      break;
    }
  }
  if (end === -1) fail("trace ZIP end-of-central-directory record is missing");
  const count = buffer.readUInt16LE(end + 10);
  const centralBytes = buffer.readUInt32LE(end + 12);
  const centralOffset = buffer.readUInt32LE(end + 16);
  if (count === 0xffff || centralBytes === 0xffffffff || centralOffset === 0xffffffff) {
    fail("unexpected ZIP64 trace archive");
  }
  const entries = [];
  let cursor = centralOffset;
  for (let index = 0; index < count; index += 1) {
    if (buffer.readUInt32LE(cursor) !== 0x02014b50) fail("invalid trace ZIP central-directory entry");
    const nameBytes = buffer.readUInt16LE(cursor + 28);
    const extraBytes = buffer.readUInt16LE(cursor + 30);
    const commentBytes = buffer.readUInt16LE(cursor + 32);
    const name = buffer.subarray(cursor + 46, cursor + 46 + nameBytes).toString("utf8");
    entries.push({
      compressedBytes: buffer.readUInt32LE(cursor + 20),
      compression: buffer.readUInt16LE(cursor + 10),
      localOffset: buffer.readUInt32LE(cursor + 42),
      name,
      uncompressedBytes: buffer.readUInt32LE(cursor + 24),
    });
    cursor += 46 + nameBytes + extraBytes + commentBytes;
  }
  if (cursor !== centralOffset + centralBytes) fail("trace ZIP central-directory size mismatch");
  return entries;
}

function extractZipEntry(buffer, entry) {
  const offset = entry.localOffset;
  if (buffer.readUInt32LE(offset) !== 0x04034b50) fail(`invalid local ZIP entry: ${entry.name}`);
  const nameBytes = buffer.readUInt16LE(offset + 26);
  const extraBytes = buffer.readUInt16LE(offset + 28);
  const start = offset + 30 + nameBytes + extraBytes;
  const compressed = buffer.subarray(start, start + entry.compressedBytes);
  let value;
  if (entry.compression === 0) value = compressed;
  else if (entry.compression === 8) value = inflateRawSync(compressed);
  else fail(`unsupported trace ZIP compression ${entry.compression}: ${entry.name}`);
  if (value.length !== entry.uncompressedBytes) fail(`trace ZIP length mismatch: ${entry.name}`);
  return value;
}

function validateTrace(buffer) {
  if (buffer.length < 1000 || buffer.readUInt32LE(0) !== 0x04034b50) {
    fail("trace is not a non-trivial ZIP archive");
  }
  const entries = zipCentralDirectory(buffer);
  const entryNames = entries.map((entry) => entry.name);
  const traceEntry = entries.find((entry) => entry.name === "trace.trace");
  const networkEntry = entries.find((entry) => entry.name === "trace.network");
  if (!traceEntry || !networkEntry) {
    fail(`trace archive lacks trace.trace or trace.network: ${JSON.stringify(entryNames)}`);
  }
  const traceLines = extractZipEntry(buffer, traceEntry)
    .toString("utf8")
    .split("\n")
    .filter(Boolean);
  if (traceLines.length < 3) fail("trace.trace has too few events");
  const traceEvents = [];
  for (const [index, line] of traceLines.entries()) {
    try {
      traceEvents.push(JSON.parse(line));
    } catch {
      fail(`trace.trace event ${index + 1} is not JSON`);
    }
  }
  const networkLines = extractZipEntry(buffer, networkEntry)
    .toString("utf8")
    .split("\n")
    .filter(Boolean);
  for (const [index, line] of networkLines.entries()) {
    try {
      JSON.parse(line);
    } catch {
      fail(`trace.network event ${index + 1} is not JSON`);
    }
  }

  const beforeEvents = traceEvents.filter((event) => event.type === "before");
  const afterCallIds = new Set(
    traceEvents
      .filter((event) => event.type === "after" && typeof event.callId === "string")
      .map((event) => event.callId),
  );
  const observedActions = beforeEvents.map((event) => ({
    apiName: event.apiName ?? null,
    callId: event.callId ?? null,
    class: event.class ?? null,
    method: event.method ?? null,
  }));
  for (const requiredMethod of ["setContent", "screenshot", "pdf"]) {
    const action = beforeEvents.find((event) =>
      event.method === requiredMethod || event.apiName === `page.${requiredMethod}`,
    );
    if (!action || (action.callId && !afterCallIds.has(action.callId))) {
      fail(
        `trace lacks a completed ${requiredMethod} action; entries=${JSON.stringify(entryNames)} `
        + `actions=${JSON.stringify(observedActions)}`,
      );
    }
  }
  const screenshotEvidence = traceEvents.some((event) =>
    event.type === "screencast-frame"
    || event.method === "screenshot"
    || event.apiName === "page.screenshot"
    || (Array.isArray(event.attachments) && event.attachments.some((item) => /screenshot|png/i.test(item.name ?? item.contentType ?? ""))),
  );
  if (!screenshotEvidence) fail(`trace has no screenshot evidence: ${JSON.stringify(observedActions)}`);
  return {
    actions: observedActions.length,
    entries: entries.length,
    entryNames,
    networkEvents: networkLines.length,
    resourceEntries: entryNames.filter((name) => name.startsWith("resources/")).length,
    traceEvents: traceLines.length,
  };
}

async function describeArtifact(path, validator) {
  const buffer = await readFile(path);
  const validation = validator(buffer);
  await chmod(path, 0o600);
  return {
    bytes: buffer.length,
    path,
    sha256: sha256Buffer(buffer),
    ...validation,
  };
}

const fixture = `<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <title>DeepTwin browser worker canary</title>
  <style>
    @page { size: A4; margin: 14mm; }
    * { box-sizing: border-box; }
    html { color-scheme: dark; background: #071117; }
    body { margin: 0; min-height: 960px; padding: 54px; color: #eef7f5; background: radial-gradient(circle at 82% 10%, #153f46, #071117 42%); font-family: "Noto Sans CJK KR", "Unifont", sans-serif; }
    main { width: 100%; min-height: 850px; padding: 40px; border: 1px solid #2a6971; border-radius: 24px; background: rgba(9, 27, 34, .94); }
    h1 { margin: 0 0 8px; font-size: 38px; letter-spacing: -.04em; }
    .lead { color: #9ee7dd; font-size: 19px; }
    .graph { display: grid; grid-template-columns: repeat(3, 1fr); align-items: center; gap: 38px; margin: 52px 0 36px; }
    .node { position: relative; min-height: 130px; padding: 24px; border: 1px solid #3d7f87; border-radius: 18px; background: #10262e; }
    .node:not(:last-child)::after { content: "→"; position: absolute; right: -31px; top: 44px; color: #62d7cb; font-size: 28px; }
    .tag { display: inline-block; margin-bottom: 12px; padding: 5px 9px; border-radius: 999px; color: #051517; background: #65dfd0; font-weight: 700; }
    .artifact { display: grid; grid-template-columns: 1.2fr .8fr; gap: 22px; padding: 24px; border-radius: 18px; background: #0b1b22; }
    canvas { width: 100%; height: 150px; border-radius: 12px; background: #f7fbfa; }
    table { width: 100%; border-collapse: collapse; }
    th, td { padding: 10px 12px; border-bottom: 1px solid #284750; text-align: left; }
    @media print { html, body { background: white; color: #11282d; } main { border-color: #8eb7b5; background: white; } .node, .artifact { background: #eef7f5; } }
  </style>
</head>
<body>
  <main id="fixture" aria-label="딥트윈 멀티에이전트 실행 그래프">
    <h1>업무가 흐르고, 차이가 학습됩니다</h1>
    <p class="lead">원본 산출물과 사용자의 대안 산출물을 같은 실행 계보에서 비교합니다.</p>
    <section class="graph" aria-label="에이전트 산출물 전달 그래프">
      <article class="node"><span class="tag">수집 에이전트</span><strong>소재 후보 묶음</strong><p>근거 링크와 범용성 신호</p></article>
      <article class="node"><span class="tag">검증 에이전트</span><strong>팩트 검증표</strong><p>주장·출처·불확실성</p></article>
      <article class="node"><span class="tag">구성 에이전트</span><strong>영상 뼈대</strong><p>썸네일 약속과 첫 30초</p></article>
    </section>
    <section class="artifact">
      <canvas id="korean-canvas" width="760" height="150" aria-label="한국어 캔버스 렌더링"></canvas>
      <table aria-label="산출물 상태"><tbody><tr><th>원본</th><td>보존됨</td></tr><tr><th>대안</th><td>비교 가능</td></tr><tr><th>승격</th><td>사람 승인 필요</td></tr></tbody></table>
    </section>
  </main>
</body>
</html>`;

async function main() {
  process.umask(0o077);
  const options = parseArguments(process.argv.slice(2));
  const identity = assertLinuxNonRoot();
  const network = await assertNoExternalNetworkNamespace();
  const inputs = await verifyPinnedInputs(options.playwrightPath, options.browserPath);
  await mkdir(options.outputDirectory, { mode: 0o700 });

  const screenshotPath = join(options.outputDirectory, "korean-render.png");
  const pdfPath = join(options.outputDirectory, "korean-render.pdf");
  const tracePath = join(options.outputDirectory, "render-trace.zip");
  const receiptPath = join(options.outputDirectory, "receipt.json");
  const { chromium } = await import(pathToFileURL(inputs.playwright.entrypointPath).href);
  if (!chromium) fail("playwright-core entrypoint does not export chromium");

  let browser;
  let context;
  let tracing = false;
  try {
    browser = await chromium.launch({
      args: [
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-default-apps",
        "--disable-domain-reliability",
        "--disable-sync",
        "--host-resolver-rules=MAP * ~NOTFOUND",
        "--metrics-recording-only",
        "--no-first-run",
        "--no-proxy-server",
        "--safebrowsing-disable-auto-update",
      ],
      chromiumSandbox: true,
      executablePath: inputs.browser.path,
      headless: true,
      timeout: 20000,
    });
    const observedVersion = browser.version();
    if (observedVersion !== EXPECTED_BROWSER_VERSION && !observedVersion.endsWith(`/${EXPECTED_BROWSER_VERSION}`)) {
      fail(`unexpected Playwright browser version: ${observedVersion}`);
    }

    context = await browser.newContext({
      acceptDownloads: false,
      deviceScaleFactor: 1,
      javaScriptEnabled: true,
      locale: "ko-KR",
      serviceWorkers: "block",
      timezoneId: "Asia/Seoul",
      viewport: { width: 1280, height: 960 },
    });
    context.setDefaultTimeout(10000);
    const blockedHttp = [];
    const blockedWebSockets = [];
    await context.route("**/*", async (route) => {
      const url = route.request().url();
      const protocol = new URL(url).protocol;
      if (["about:", "blob:", "chrome:", "data:"].includes(protocol)) {
        await route.continue();
        return;
      }
      blockedHttp.push(url);
      await route.abort("blockedbyclient");
    });
    await context.routeWebSocket(/.*/, async (socket) => {
      blockedWebSockets.push(socket.url());
      await socket.close({ code: 1008, reason: "DeepTwin egress denied" });
    });

    const sandboxPage = await context.newPage();
    let sandboxStatus;
    try {
      await sandboxPage.goto("chrome://sandbox", { waitUntil: "domcontentloaded" });
      const text = (await sandboxPage.locator("body").innerText()).replace(/\s+/g, " ").trim();
      if (!/sandbox status/i.test(text)) fail("chrome://sandbox did not expose Sandbox Status");
      if (/no usable sandbox|you are not sandboxed/i.test(text)) {
        fail(`Chromium reported an unusable sandbox: ${text}`);
      }
      if (!/(namespace|seccomp[^ ]*) sandbox\s+yes/i.test(text)) {
        fail(`Chromium reported no positive namespace/seccomp sandbox signal: ${text}`);
      }
      sandboxStatus = { available: true, text };
    } catch (error) {
      const message = String(error?.message ?? error);
      if (!message.includes("net::ERR_INVALID_URL") || !message.includes("chrome://sandbox")) throw error;
      sandboxStatus = {
        available: false,
        error: "net::ERR_INVALID_URL",
        reason: "chrome://sandbox is not exposed by the pinned chrome-headless-shell binary",
      };
    } finally {
      await sandboxPage.close();
    }

    const probePage = await context.newPage();
    const httpProbe = await probePage.evaluate(async (url) => {
      try {
        await fetch(url, { cache: "no-store", credentials: "omit" });
        return "unexpected-success";
      } catch {
        return "blocked";
      }
    }, HTTP_PROBE_URL);
    assert.equal(httpProbe, "blocked", "HTTP interception probe escaped");
    assert.deepEqual(blockedHttp, [HTTP_PROBE_URL], "unexpected HTTP request set");

    const webSocketProbe = await probePage.evaluate((url) => new Promise((resolve) => {
      const socket = new WebSocket(url);
      const timer = setTimeout(() => resolve("timeout"), 3000);
      socket.addEventListener("open", () => socket.close());
      socket.addEventListener("close", () => {
        clearTimeout(timer);
        resolve("blocked");
      });
      socket.addEventListener("error", () => {
        clearTimeout(timer);
        resolve("blocked");
      });
    }), WEBSOCKET_PROBE_URL);
    assert.equal(webSocketProbe, "blocked", "WebSocket interception probe escaped");
    assert.deepEqual(blockedWebSockets, [WEBSOCKET_PROBE_URL], "unexpected WebSocket request set");
    await probePage.close();

    await context.tracing.start({
      name: "deeptwin-browser-worker-canary",
      screenshots: true,
      snapshots: true,
      sources: false,
      title: "DeepTwin browser worker canary",
    });
    tracing = true;
    const page = await context.newPage();
    const pageErrors = [];
    const consoleErrors = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    await page.setContent(fixture, { waitUntil: "load" });
    const rendering = await page.evaluate(async () => {
      await document.fonts.ready;
      const korean = "딥트윈 산출물 비교와 사람 승인";
      const canvas = document.querySelector("#korean-canvas");
      const context2d = canvas.getContext("2d");
      context2d.fillStyle = "#f7fbfa";
      context2d.fillRect(0, 0, canvas.width, canvas.height);
      context2d.fillStyle = "#0a3438";
      context2d.font = '700 30px "Noto Sans CJK KR", "Unifont", sans-serif';
      context2d.fillText(korean, 30, 86);
      const pixels = context2d.getImageData(0, 0, canvas.width, canvas.height).data;
      let nonBackgroundPixels = 0;
      for (let index = 0; index < pixels.length; index += 4) {
        if (pixels[index] < 235 || pixels[index + 1] < 235 || pixels[index + 2] < 235) nonBackgroundPixels += 1;
      }
      const heading = document.querySelector("h1");
      const rectangle = heading.getBoundingClientRect();
      return {
        canvasNonBackgroundPixels: nonBackgroundPixels,
        fontCheck: document.fonts.check('700 30px "Noto Sans CJK KR", "Unifont", sans-serif', korean),
        headingHeight: rectangle.height,
        headingText: heading.textContent,
        htmlLanguage: document.documentElement.lang,
        title: document.title,
      };
    });
    assert.equal(rendering.htmlLanguage, "ko");
    assert.equal(rendering.title, "DeepTwin browser worker canary");
    assert.equal(rendering.headingText, "업무가 흐르고, 차이가 학습됩니다");
    assert.equal(rendering.fontCheck, true, "browser font subsystem cannot resolve Korean text");
    if (rendering.headingHeight < 30 || rendering.canvasNonBackgroundPixels < 500) {
      fail(`Korean rendering probe is empty: ${JSON.stringify(rendering)}`);
    }

    await page.emulateMedia({ media: "screen" });
    await page.screenshot({ animations: "disabled", caret: "hide", fullPage: true, path: screenshotPath });
    await page.emulateMedia({ media: "print" });
    await page.pdf({ format: "A4", margin: { bottom: "12mm", left: "12mm", right: "12mm", top: "12mm" }, path: pdfPath, preferCSSPageSize: true, printBackground: true });
    const cdp = await browser.newBrowserCDPSession();
    const browserMetadata = await cdp.send("Browser.getVersion");
    const processInfo = await cdp.send("SystemInfo.getProcessInfo");
    await cdp.detach();
    const processEvidence = await chromiumProcessEvidence(inputs.browser.path, identity.uid, processInfo.processInfo);
    assert.deepEqual(pageErrors, [], "page errors");
    assert.deepEqual(consoleErrors, [], "console errors");
    await page.close();
    await context.tracing.stop({ path: tracePath });
    tracing = false;

    const artifacts = {
      pdf: await describeArtifact(pdfPath, validatePdf),
      png: await describeArtifact(screenshotPath, validatePng),
      trace: await describeArtifact(tracePath, validateTrace),
    };
    const receipt = {
      schema_version: "deeptwin-browser-worker-canary-v1",
      status: "pass",
      inputs,
      runtime: {
        browserVersion: observedVersion,
        browserMetadata,
        cdpProcessInfo: processEvidence.cdpEntries,
        chromiumSandboxRequested: true,
        forbiddenArgumentsObserved: [],
        identity,
        network,
        processes: processEvidence.processes,
        sandboxStatus,
        unmatchedCdpProcessInfo: processEvidence.unmatchedCdpEntries,
      },
      rendering,
      egress: {
        httpProbe: { outcome: httpProbe, url: HTTP_PROBE_URL },
        webSocketProbe: { outcome: webSocketProbe, url: WEBSOCKET_PROBE_URL },
      },
      artifacts,
    };
    await writeFile(receiptPath, `${JSON.stringify(receipt, null, 2)}\n`, { encoding: "utf8", flag: "wx", mode: 0o600 });
    console.log(JSON.stringify({ ...receipt, receiptPath }));
  } finally {
    if (tracing) await context?.tracing.stop().catch(() => {});
    await context?.close().catch(() => {});
    await browser?.close().catch(() => {});
  }
}

main().catch((error) => {
  console.error(`browser worker canary failed: ${error.stack ?? error.message}`);
  process.exitCode = 1;
});
