#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { basename, join } from "node:path";


function fail(message) {
  throw new Error(message);
}

function sha256File(path) {
  const hash = createHash("sha256");
  hash.update(readFileSync(path));
  return hash.digest("hex");
}

function architecture() {
  if (process.arch === "x64") return "amd64";
  if (process.arch === "arm64") return "arm64";
  fail(`unsupported runtime architecture: ${process.arch}`);
}

function installedPackages() {
  const output = execFileSync(
    "dpkg-query",
    ["-W", "-f=${Package}\t${Version}\n"],
    { encoding: "utf8" },
  );
  const packages = new Map();
  for (const line of output.trim().split("\n")) {
    if (!line) continue;
    const [name, version] = line.split("\t");
    if (!name || !version || packages.has(name)) fail(`invalid dpkg row: ${line}`);
    packages.set(name, version);
  }
  return packages;
}

function verifyDescriptor(path, descriptor, label) {
  const size = statSync(path).size;
  if (size !== descriptor.bytes) fail(`${label}: byte count ${size} != ${descriptor.bytes}`);
  const digest = sha256File(path);
  if (digest !== descriptor.sha256) fail(`${label}: SHA-256 mismatch`);
}

function verifyBase(manifest, platform, packages) {
  const inventory = platform.base_dpkg_inventory;
  const statusPath = "/var/lib/dpkg/status";
  if (sha256File(statusPath) !== inventory.status_sha256) {
    fail("base dpkg status does not match the pinned OCI-layer inventory");
  }
  if (packages.size !== inventory.installed_count) {
    fail(`base installed count ${packages.size} != ${inventory.installed_count}`);
  }
  for (const item of inventory.closure_packages_satisfied) {
    if (packages.get(item.name) !== item.base_version || item.base_version !== item.version) {
      fail(`base package mismatch: ${item.name}`);
    }
  }
}

function findBundleFile(root, member) {
  const direct = join(root, member);
  try {
    if (statSync(direct).isFile()) return direct;
  } catch {
    // A release build may strip the upstream top directory while preserving file names.
  }
  const wanted = basename(member);
  const matches = [];
  const queue = [root];
  while (queue.length) {
    const directory = queue.pop();
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const path = join(directory, entry.name);
      if (entry.isDirectory()) queue.push(path);
      else if (entry.isFile() && entry.name === wanted) matches.push(path);
    }
  }
  if (matches.length !== 1) fail(`${member}: expected one bundle member, found ${matches.length}`);
  return matches[0];
}

function verifyInstalled(manifest, platform, packages, browserRoot) {
  const addedPackages = platform.install_delta.packages.filter(
    (item) => item.action === "add",
  );
  const replacedPackages = platform.install_delta.packages.filter(
    (item) => item.action === "upgrade_or_replace",
  );
  if (addedPackages.length + replacedPackages.length !== platform.install_delta.package_count) {
    fail("install delta contains an unsupported or uncounted action");
  }
  const expectedFinalCount = platform.base_dpkg_inventory.installed_count + addedPackages.length;
  if (packages.size !== expectedFinalCount) {
    fail(`final installed count ${packages.size} != ${expectedFinalCount}`);
  }
  for (const item of manifest.closure.packages) {
    if (packages.get(item.name) !== item.version) {
      fail(`final package mismatch: ${item.name}=${packages.get(item.name) ?? "missing"}`);
    }
  }
  const audit = execFileSync("dpkg", ["--audit"], { encoding: "utf8" });
  if (audit.trim()) fail(`dpkg audit reported: ${audit.trim()}`);

  execFileSync("fc-cache", ["-f"], { stdio: "pipe" });
  const koreanFonts = execFileSync("fc-list", [":lang=ko", "family"], {
    encoding: "utf8",
  })
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  if (!koreanFonts.length) fail("fontconfig found no Korean-capable font");

  if (!browserRoot) {
    return {
      finalPackageCount: packages.size,
      koreanFontFamilies: koreanFonts.length,
    };
  }
  for (const file of platform.elf_needed_audit.files) {
    const path = findBundleFile(browserRoot, file.member);
    verifyDescriptor(path, file, file.member);
    const ldd = execFileSync("ldd", [path], { encoding: "utf8" });
    if (/\bnot found\b/.test(ldd)) fail(`${file.member}: unresolved ldd dependency`);
  }
  const executable = findBundleFile(
    browserRoot,
    platform.elf_needed_audit.files[0].member,
  );
  const version = execFileSync(executable, ["--version"], { encoding: "utf8" }).trim();
  if (version !== "Google Chrome for Testing 153.0.8010.12") {
    fail(`unexpected browser version: ${version}`);
  }
  return {
    browserVersion: version,
    finalPackageCount: packages.size,
    koreanFontFamilies: koreanFonts.length,
  };
}

function main() {
  const [manifestPath, phase, browserRoot] = process.argv.slice(2);
  if (!manifestPath || !["base", "installed"].includes(phase)) {
    fail("usage: verify_browser_runtime.mjs MANIFEST (base|installed) [BROWSER_ROOT]");
  }
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  if (manifest.schema_version !== "deeptwin-browser-debian-bookworm-lock-v1") {
    fail("unsupported browser Debian manifest");
  }
  const arch = architecture();
  const platform = manifest.platforms[arch];
  if (!platform) fail(`manifest does not include ${arch}`);
  const packages = installedPackages();
  if (phase === "base") {
    verifyBase(manifest, platform, packages);
    console.log(JSON.stringify({ status: "pass", phase, arch, packages: packages.size }));
    return;
  }
  const result = verifyInstalled(manifest, platform, packages, browserRoot);
  console.log(JSON.stringify({ status: "pass", phase, arch, ...result }));
}


try {
  main();
} catch (error) {
  console.error(`browser runtime verification failed: ${error.message}`);
  process.exitCode = 1;
}
