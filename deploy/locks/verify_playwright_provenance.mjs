#!/usr/bin/env node

/**
 * Fail-closed Playwright npm provenance policy postcheck.
 *
 * This program intentionally does not replace npm's Sigstore verification. The
 * input audit JSON MUST be the byte-for-byte output of the pinned command
 * recorded in browser-worker.json:
 *
 *   npm audit signatures --json --include-attestations
 *
 * npm establishes the cryptographic validity of the included bundles. This
 * postcheck binds that output to the manifest and enforces DeepTwin's exact
 * certificate and SLSA allowlist. Exit status 0 additionally means the running
 * Node executable matches the separately authenticated platform release bytes;
 * status 3 means package policy passed but that runtime qualification did not.
 * Exit status 1 is a policy failure; 64 is bad usage.
 */

import { createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import { readFile } from "node:fs/promises";
import process from "node:process";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const IN_TOTO_V01 = "https://in-toto.io/Statement/v0.1";
const IN_TOTO_V1 = "https://in-toto.io/Statement/v1";
const PAYLOAD_TYPE = "application/vnd.in-toto+json";
const PUBLISH_PREDICATE =
  "https://github.com/npm/attestation/tree/main/specs/publish/v0.1";
const SLSA_PREDICATE = "https://slsa.dev/provenance/v1";
const GITHUB_ACTIONS_BUILD_TYPE =
  "https://slsa-framework.github.io/github-actions-buildtypes/workflow/v1";
const SIGSTORE_BUNDLE_V02 = "application/vnd.dev.sigstore.bundle+json;version=0.2";
const SIGSTORE_BUNDLE_V03 = "application/vnd.dev.sigstore.bundle.v0.3+json";

const CERTIFICATE_OIDS = Object.freeze({
  subjectAlternativeName: "2.5.29.17",
  oidcIssuerLegacy: "1.3.6.1.4.1.57264.1.1",
  githubEventLegacy: "1.3.6.1.4.1.57264.1.2",
  sourceCommitLegacy: "1.3.6.1.4.1.57264.1.3",
  repositorySlugLegacy: "1.3.6.1.4.1.57264.1.5",
  sourceRefLegacy: "1.3.6.1.4.1.57264.1.6",
  oidcIssuer: "1.3.6.1.4.1.57264.1.8",
  workflowIdentity: "1.3.6.1.4.1.57264.1.9",
  runnerEnvironment: "1.3.6.1.4.1.57264.1.11",
  repository: "1.3.6.1.4.1.57264.1.12",
  sourceCommit: "1.3.6.1.4.1.57264.1.13",
  sourceRef: "1.3.6.1.4.1.57264.1.14",
  repositoryId: "1.3.6.1.4.1.57264.1.15",
  repositoryOwnerId: "1.3.6.1.4.1.57264.1.17",
  buildConfigUri: "1.3.6.1.4.1.57264.1.18",
  sourceDigest: "1.3.6.1.4.1.57264.1.19",
  buildTrigger: "1.3.6.1.4.1.57264.1.20",
  runInvocationUri: "1.3.6.1.4.1.57264.1.21",
});

const REQUIRED_ALLOWLIST_FIELDS = Object.freeze([
  "certificate_identity",
  "certificate_oidc_issuer",
  "subject_name",
  "subject_sha512",
  "repository",
  "workflow_path",
  "source_ref",
  "source_commit",
  "event_name",
  "repository_id",
  "repository_owner_id",
  "builder_id",
  "invocation_id",
]);

export class ProvenanceVerificationError extends Error {
  constructor(code, location, message) {
    super(`${location}: ${message}`);
    this.name = "ProvenanceVerificationError";
    this.code = code;
    this.location = location;
  }
}

function fail(code, location, message) {
  throw new ProvenanceVerificationError(code, location, message);
}

function requireObject(value, location) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    fail("INVALID_STRUCTURE", location, "expected an object");
  }
  return value;
}

function requireArray(value, location) {
  if (!Array.isArray(value)) {
    fail("INVALID_STRUCTURE", location, "expected an array");
  }
  return value;
}

function requireString(value, location) {
  if (typeof value !== "string" || value.length === 0) {
    fail("INVALID_STRUCTURE", location, "expected a non-empty string");
  }
  return value;
}

function requireInteger(value, location) {
  if (!Number.isSafeInteger(value) || value < 0) {
    fail("INVALID_STRUCTURE", location, "expected a non-negative safe integer");
  }
  return value;
}

function requireEqual(actual, expected, location) {
  if (actual !== expected) {
    fail(
      "ALLOWLIST_MISMATCH",
      location,
      `expected ${JSON.stringify(expected)}, observed ${JSON.stringify(actual)}`,
    );
  }
}

function requireExactKeys(value, expectedKeys, location) {
  const actual = Object.keys(requireObject(value, location)).sort();
  const expected = [...expectedKeys].sort();
  if (
    actual.length !== expected.length ||
    actual.some((item, index) => item !== expected[index])
  ) {
    fail(
      "AMBIGUOUS_STRUCTURE",
      location,
      `expected keys ${JSON.stringify(expected)}, observed ${JSON.stringify(actual)}`,
    );
  }
}

function requireSingle(value, location) {
  const values = requireArray(value, location);
  if (values.length !== 1) {
    fail("AMBIGUOUS_STRUCTURE", location, `expected exactly one item, observed ${values.length}`);
  }
  return values[0];
}

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function sha256File(path) {
  return new Promise((resolveHash, rejectHash) => {
    const digest = createHash("sha256");
    const stream = createReadStream(path);
    stream.on("error", rejectHash);
    stream.on("data", (chunk) => digest.update(chunk));
    stream.on("end", () => resolveHash(digest.digest("hex")));
  });
}

function parseJson(bytes, location) {
  try {
    return JSON.parse(bytes.toString("utf8"));
  } catch (error) {
    fail("INVALID_JSON", location, error.message);
  }
}

function decodeBase64(value, location) {
  requireString(value, location);
  if (!/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value)) {
    fail("INVALID_BASE64", location, "expected canonical padded base64");
  }
  const decoded = Buffer.from(value, "base64");
  if (decoded.toString("base64") !== value) {
    fail("INVALID_BASE64", location, "base64 is not canonical");
  }
  return decoded;
}

function readDerElement(buffer, offset, location) {
  if (offset >= buffer.length) {
    fail("INVALID_CERTIFICATE_DER", location, "unexpected end of DER");
  }
  const start = offset;
  const tag = buffer[offset++];
  if ((tag & 0x1f) === 0x1f) {
    fail("INVALID_CERTIFICATE_DER", location, "high-tag-number DER is unsupported");
  }
  if (offset >= buffer.length) {
    fail("INVALID_CERTIFICATE_DER", location, "missing DER length");
  }
  const firstLength = buffer[offset++];
  let length;
  if ((firstLength & 0x80) === 0) {
    length = firstLength;
  } else {
    const lengthBytes = firstLength & 0x7f;
    if (lengthBytes === 0 || lengthBytes > 4 || offset + lengthBytes > buffer.length) {
      fail("INVALID_CERTIFICATE_DER", location, "invalid DER long-form length");
    }
    if (buffer[offset] === 0) {
      fail("INVALID_CERTIFICATE_DER", location, "non-minimal DER length");
    }
    length = 0;
    for (let index = 0; index < lengthBytes; index += 1) {
      length = length * 256 + buffer[offset++];
    }
    if (length < 128) {
      fail("INVALID_CERTIFICATE_DER", location, "non-minimal DER long-form length");
    }
  }
  const contentStart = offset;
  const end = contentStart + length;
  if (end > buffer.length) {
    fail("INVALID_CERTIFICATE_DER", location, "DER element exceeds input length");
  }
  return { tag, start, contentStart, end, content: buffer.subarray(contentStart, end) };
}

function parseDerChildren(element, location) {
  if ((element.tag & 0x20) === 0) {
    fail("INVALID_CERTIFICATE_DER", location, "expected constructed DER element");
  }
  const children = [];
  let offset = element.contentStart;
  while (offset < element.end) {
    const child = readDerElement(element.buffer, offset, `${location}[${children.length}]`);
    child.buffer = element.buffer;
    children.push(child);
    offset = child.end;
  }
  if (offset !== element.end) {
    fail("INVALID_CERTIFICATE_DER", location, "constructed DER length mismatch");
  }
  return children;
}

function decodeOid(bytes, location) {
  if (bytes.length === 0) {
    fail("INVALID_CERTIFICATE_DER", location, "empty object identifier");
  }
  const first = bytes[0];
  const components = [Math.min(2, Math.floor(first / 40)), first >= 80 ? first - 80 : first % 40];
  let value = 0;
  let active = false;
  for (const byte of bytes.subarray(1)) {
    active = true;
    value = value * 128 + (byte & 0x7f);
    if (!Number.isSafeInteger(value)) {
      fail("INVALID_CERTIFICATE_DER", location, "object identifier component is too large");
    }
    if ((byte & 0x80) === 0) {
      components.push(value);
      value = 0;
      active = false;
    }
  }
  if (active) {
    fail("INVALID_CERTIFICATE_DER", location, "truncated object identifier");
  }
  return components.join(".");
}

function utf8(bytes, location) {
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch (error) {
    fail("INVALID_CERTIFICATE_DER", location, `invalid UTF-8: ${error.message}`);
  }
}

function decodeExtensionText(bytes, location) {
  if (bytes.length > 0 && bytes[0] === 0x0c) {
    const wrapped = readDerElement(bytes, 0, location);
    if (wrapped.end !== bytes.length || wrapped.tag !== 0x0c) {
      fail("INVALID_CERTIFICATE_DER", location, "invalid UTF8String wrapper");
    }
    return utf8(wrapped.content, location);
  }
  return utf8(bytes, location);
}

function collectExtensions(extensionSequence, wantedOids) {
  const found = new Map();
  const extensionElements = parseDerChildren(extensionSequence, "certificate.tbsCertificate.extensions");
  extensionElements.forEach((extensionElement, index) => {
    const location = `certificate.tbsCertificate.extensions[${index}]`;
    if (extensionElement.tag !== 0x30) {
      fail("INVALID_CERTIFICATE_DER", location, "expected an Extension sequence");
    }
    const children = parseDerChildren(extensionElement, location);
    if (
      (children.length !== 2 && children.length !== 3) ||
      children[0].tag !== 0x06 ||
      children.at(-1).tag !== 0x04 ||
      (children.length === 3 && children[1].tag !== 0x01)
    ) {
      fail("INVALID_CERTIFICATE_DER", location, "malformed Extension structure");
    }
    const oid = decodeOid(children[0].content, `${location}.oid`);
    if (!wantedOids.has(oid)) return;
    if (found.has(oid)) {
      fail("AMBIGUOUS_CERTIFICATE_CLAIM", location, `duplicate extension ${oid}`);
    }
    found.set(oid, Buffer.from(children.at(-1).content));
  });
  return found;
}

function decodeSingleSanUri(bytes) {
  const root = readDerElement(bytes, 0, "certificate.subjectAlternativeName");
  root.buffer = bytes;
  if (root.tag !== 0x30 || root.end !== bytes.length) {
    fail("INVALID_CERTIFICATE_DER", "certificate.subjectAlternativeName", "expected one DER sequence");
  }
  const names = parseDerChildren(root, "certificate.subjectAlternativeName");
  if (names.length !== 1 || names[0].tag !== 0x86) {
    fail(
      "AMBIGUOUS_CERTIFICATE_CLAIM",
      "certificate.subjectAlternativeName",
      "expected exactly one URI general name",
    );
  }
  return utf8(names[0].content, "certificate.subjectAlternativeName.uri");
}

export function extractFulcioClaims(certificateDer) {
  if (!Buffer.isBuffer(certificateDer) || certificateDer.length === 0) {
    fail("INVALID_CERTIFICATE_DER", "certificate", "expected non-empty DER bytes");
  }
  const root = readDerElement(certificateDer, 0, "certificate");
  root.buffer = certificateDer;
  if (root.tag !== 0x30 || root.end !== certificateDer.length) {
    fail("INVALID_CERTIFICATE_DER", "certificate", "expected one DER certificate sequence");
  }
  const certificateChildren = parseDerChildren(root, "certificate");
  if (certificateChildren.length !== 3 || certificateChildren[0].tag !== 0x30) {
    fail("INVALID_CERTIFICATE_DER", "certificate", "expected an X.509 Certificate sequence");
  }
  const tbsChildren = parseDerChildren(certificateChildren[0], "certificate.tbsCertificate");
  const extensionWrappers = tbsChildren.filter((element) => element.tag === 0xa3);
  if (extensionWrappers.length !== 1) {
    fail(
      "AMBIGUOUS_CERTIFICATE_CLAIM",
      "certificate.tbsCertificate.extensions",
      `expected exactly one [3] extensions wrapper, observed ${extensionWrappers.length}`,
    );
  }
  const wrapperChildren = parseDerChildren(
    extensionWrappers[0],
    "certificate.tbsCertificate.extensionsWrapper",
  );
  if (wrapperChildren.length !== 1 || wrapperChildren[0].tag !== 0x30) {
    fail(
      "INVALID_CERTIFICATE_DER",
      "certificate.tbsCertificate.extensionsWrapper",
      "expected one Extensions sequence",
    );
  }
  const wanted = new Set(Object.values(CERTIFICATE_OIDS));
  const extensions = collectExtensions(wrapperChildren[0], wanted);
  for (const [name, oid] of Object.entries(CERTIFICATE_OIDS)) {
    if (!extensions.has(oid)) {
      fail("MISSING_CERTIFICATE_CLAIM", `certificate.${name}`, `missing extension ${oid}`);
    }
  }
  const claims = {};
  for (const [name, oid] of Object.entries(CERTIFICATE_OIDS)) {
    claims[name] =
      name === "subjectAlternativeName"
        ? decodeSingleSanUri(extensions.get(oid))
        : decodeExtensionText(extensions.get(oid), `certificate.${name}`);
  }
  return Object.freeze(claims);
}

function verifySubject(statement, expected, location) {
  const subject = requireObject(requireSingle(statement.subject, `${location}.subject`), `${location}.subject[0]`);
  requireExactKeys(subject, ["name", "digest"], `${location}.subject[0]`);
  requireEqual(subject.name, expected.subject_name, `${location}.subject[0].name`);
  requireExactKeys(subject.digest, ["sha512"], `${location}.subject[0].digest`);
  requireEqual(subject.digest.sha512, expected.subject_sha512, `${location}.subject[0].digest.sha512`);
}

function decodeStatement(bundleRecord, expectedHash, location) {
  const record = requireObject(bundleRecord, location);
  const bundle = requireObject(record.bundle, `${location}.bundle`);
  const envelope = requireObject(bundle.dsseEnvelope, `${location}.bundle.dsseEnvelope`);
  requireEqual(envelope.payloadType, PAYLOAD_TYPE, `${location}.bundle.dsseEnvelope.payloadType`);
  const signatures = requireArray(envelope.signatures, `${location}.bundle.dsseEnvelope.signatures`);
  if (signatures.length === 0) {
    fail("MISSING_CRYPTOGRAPHIC_EVIDENCE", `${location}.bundle.dsseEnvelope.signatures`, "no signature");
  }
  const payload = decodeBase64(envelope.payload, `${location}.bundle.dsseEnvelope.payload`);
  requireEqual(sha256(payload), expectedHash, `${location}.statement_sha256`);
  const statement = requireObject(parseJson(payload, `${location}.statement`), `${location}.statement`);
  requireEqual(record.predicateType, statement.predicateType, `${location}.predicateType`);
  return { bundle, statement };
}

function verifyPublishStatement(statement, expected, packageVersion) {
  requireEqual(statement._type, IN_TOTO_V01, "publish.statement._type");
  requireEqual(statement.predicateType, PUBLISH_PREDICATE, "publish.statement.predicateType");
  verifySubject(statement, expected, "publish.statement");
  const predicate = requireObject(statement.predicate, "publish.statement.predicate");
  requireExactKeys(predicate, ["name", "version", "registry"], "publish.statement.predicate");
  const expectedName = expected.subject_name.slice("pkg:npm/".length).split("@")[0];
  requireEqual(predicate.name, expectedName, "publish.statement.predicate.name");
  requireEqual(predicate.version, packageVersion, "publish.statement.predicate.version");
  requireEqual(predicate.registry, "https://registry.npmjs.org", "publish.statement.predicate.registry");
}

function verifySlsaStatement(statement, expected) {
  requireEqual(statement._type, IN_TOTO_V1, "slsa.statement._type");
  requireEqual(statement.predicateType, SLSA_PREDICATE, "slsa.statement.predicateType");
  verifySubject(statement, expected, "slsa.statement");

  const predicate = requireObject(statement.predicate, "slsa.statement.predicate");
  const buildDefinition = requireObject(predicate.buildDefinition, "slsa.statement.predicate.buildDefinition");
  requireEqual(buildDefinition.buildType, GITHUB_ACTIONS_BUILD_TYPE, "slsa.buildDefinition.buildType");

  const workflow = requireObject(
    buildDefinition.externalParameters?.workflow,
    "slsa.buildDefinition.externalParameters.workflow",
  );
  requireExactKeys(workflow, ["ref", "repository", "path"], "slsa.buildDefinition.externalParameters.workflow");
  requireEqual(workflow.repository, expected.repository, "slsa.workflow.repository");
  requireEqual(workflow.path, expected.workflow_path, "slsa.workflow.path");
  requireEqual(workflow.ref, expected.source_ref, "slsa.workflow.ref");

  const github = requireObject(
    buildDefinition.internalParameters?.github,
    "slsa.buildDefinition.internalParameters.github",
  );
  requireExactKeys(
    github,
    ["event_name", "repository_id", "repository_owner_id"],
    "slsa.buildDefinition.internalParameters.github",
  );
  requireEqual(github.event_name, expected.event_name, "slsa.github.event_name");
  requireEqual(github.repository_id, expected.repository_id, "slsa.github.repository_id");
  requireEqual(github.repository_owner_id, expected.repository_owner_id, "slsa.github.repository_owner_id");

  const dependency = requireObject(
    requireSingle(buildDefinition.resolvedDependencies, "slsa.buildDefinition.resolvedDependencies"),
    "slsa.buildDefinition.resolvedDependencies[0]",
  );
  requireExactKeys(dependency, ["uri", "digest"], "slsa.buildDefinition.resolvedDependencies[0]");
  requireEqual(
    dependency.uri,
    `git+${expected.repository}@${expected.source_ref}`,
    "slsa.resolvedDependencies[0].uri",
  );
  requireExactKeys(dependency.digest, ["gitCommit"], "slsa.resolvedDependencies[0].digest");
  requireEqual(dependency.digest.gitCommit, expected.source_commit, "slsa.resolvedDependencies[0].digest.gitCommit");

  requireEqual(predicate.runDetails?.builder?.id, expected.builder_id, "slsa.runDetails.builder.id");
  requireEqual(
    predicate.runDetails?.metadata?.invocationId,
    expected.invocation_id,
    "slsa.runDetails.metadata.invocationId",
  );
}

function verifyCertificateClaims(claims, expected) {
  const repositorySlug = expected.repository.replace(/^https:\/\/github\.com\//, "");
  const runnerClass = expected.builder_id.split("/").at(-1);
  const equalityChecks = [
    ["subjectAlternativeName", "certificate_identity"],
    ["oidcIssuerLegacy", "certificate_oidc_issuer"],
    ["githubEventLegacy", "event_name"],
    ["sourceCommitLegacy", "source_commit"],
    ["repositorySlugLegacy", null, repositorySlug],
    ["sourceRefLegacy", "source_ref"],
    ["oidcIssuer", "certificate_oidc_issuer"],
    ["workflowIdentity", "certificate_identity"],
    ["runnerEnvironment", null, runnerClass],
    ["repository", "repository"],
    ["sourceCommit", "source_commit"],
    ["sourceRef", "source_ref"],
    ["repositoryId", "repository_id"],
    ["repositoryOwnerId", "repository_owner_id"],
    ["buildConfigUri", "certificate_identity"],
    ["sourceDigest", "source_commit"],
    ["buildTrigger", "event_name"],
    ["runInvocationUri", "invocation_id"],
  ];
  for (const [claim, expectedField, literal] of equalityChecks) {
    requireEqual(claims[claim], literal ?? expected[expectedField], `certificate.${claim}`);
  }
}

function verifyAuditEnvelope(audit, attestations, expected, packageVersion) {
  const invalid = requireArray(audit.invalid, "audit.invalid");
  const missing = requireArray(audit.missing, "audit.missing");
  if (invalid.length !== 0 || missing.length !== 0) {
    fail(
      "NPM_CRYPTOGRAPHIC_VERIFICATION_FAILED",
      "audit",
      `npm reported ${invalid.length} invalid and ${missing.length} missing signatures`,
    );
  }
  const verified = requireObject(requireSingle(audit.verified, "audit.verified"), "audit.verified[0]");
  const packageName = expected.subject_name.slice("pkg:npm/".length).split("@")[0];
  requireEqual(verified.name, packageName, "audit.verified[0].name");
  requireEqual(verified.version, packageVersion, "audit.verified[0].version");
  requireEqual(verified.location, `node_modules/${packageName}`, "audit.verified[0].location");
  requireEqual(verified.registry, "https://registry.npmjs.org/", "audit.verified[0].registry");
  requireEqual(verified.attestations?.url, attestations.url, "audit.verified[0].attestations.url");
  requireEqual(
    verified.attestations?.provenance?.predicateType,
    SLSA_PREDICATE,
    "audit.verified[0].attestations.provenance.predicateType",
  );

  const records = requireArray(verified.attestationBundles, "audit.verified[0].attestationBundles");
  if (records.length !== 2) {
    fail(
      "AMBIGUOUS_ATTESTATION_SET",
      "audit.verified[0].attestationBundles",
      `expected exactly two bundles, observed ${records.length}`,
    );
  }
  const byPredicate = new Map();
  records.forEach((record, index) => {
    const predicateType = requireString(record?.predicateType, `audit.attestationBundles[${index}].predicateType`);
    if (byPredicate.has(predicateType)) {
      fail("AMBIGUOUS_ATTESTATION_SET", "audit.attestationBundles", `duplicate ${predicateType}`);
    }
    byPredicate.set(predicateType, record);
  });
  if (
    byPredicate.size !== 2 ||
    !byPredicate.has(PUBLISH_PREDICATE) ||
    !byPredicate.has(SLSA_PREDICATE)
  ) {
    fail("MISSING_ATTESTATION", "audit.attestationBundles", "publish and SLSA bundles are both required");
  }
  return byPredicate;
}

function nodeRuntimeBlockers(
  root,
  {
    observedNodeVersion,
    observedNodePlatform,
    observedNodeArchitecture,
    observedNodeExecutableSha256,
  },
) {
  const unqualified = (code, detail) => [{ code, detail }];
  if (root.node === undefined || observedNodeExecutableSha256 === null) {
    return unqualified(
      "POSTCHECK_NODE_RUNTIME_UNQUALIFIED",
      "the postcheck was not given a manifest-bound hash for its own Node executable",
    );
  }
  const node = requireObject(root.node, "manifest.node");
  const provenance = requireObject(
    node.official_release_provenance,
    "manifest.node.official_release_provenance",
  );
  if (observedNodeVersion !== node.version) {
    return unqualified(
      "POSTCHECK_NODE_RUNTIME_VERSION_MISMATCH",
      `expected Node ${node.version}, observed ${observedNodeVersion}`,
    );
  }
  const architecture = { x64: "amd64", arm64: "arm64" }[observedNodeArchitecture];
  if (observedNodePlatform !== "linux" || architecture === undefined) {
    return unqualified(
      "POSTCHECK_NODE_RUNTIME_PLATFORM_UNQUALIFIED",
      `expected linux/amd64 or linux/arm64, observed ${observedNodePlatform}/${observedNodeArchitecture}`,
    );
  }
  const candidates = requireArray(
    provenance.platforms,
    "manifest.node.official_release_provenance.platforms",
  ).filter(
    (item) => item?.os === observedNodePlatform && item?.architecture === architecture,
  );
  if (candidates.length !== 1) {
    fail(
      "AMBIGUOUS_STRUCTURE",
      "manifest.node.official_release_provenance.platforms",
      `expected one ${observedNodePlatform}/${architecture} runtime`,
    );
  }
  const candidate = requireObject(candidates[0], "manifest.node.official_release_provenance.platform");
  requireEqual(
    provenance.signed_checksums?.openpgp_verified,
    true,
    "manifest.node.official_release_provenance.signed_checksums.openpgp_verified",
  );
  requireEqual(
    candidate.base_image_executable_sha256_match,
    true,
    "manifest.node.official_release_provenance.platform.base_image_executable_sha256_match",
  );
  if (!/^[0-9a-f]{64}$/.test(observedNodeExecutableSha256)) {
    return unqualified(
      "POSTCHECK_NODE_RUNTIME_HASH_INVALID",
      "the observed Node executable hash is absent, abbreviated or malformed",
    );
  }
  if (observedNodeExecutableSha256 !== candidate.executable_sha256) {
    return unqualified(
      "POSTCHECK_NODE_RUNTIME_BYTES_MISMATCH",
      `the running Node executable does not match the signed ${observedNodePlatform}/${architecture} release bytes`,
    );
  }
  return [];
}

/** Verify npm cryptographic output, exact SLSA policy and the verifier runtime. */
export function verifyPlaywrightProvenance({
  manifest,
  auditBytes,
  observedNodeVersion = process.versions.node,
  observedNodePlatform = process.platform,
  observedNodeArchitecture = process.arch,
  observedNodeExecutableSha256 = null,
}) {
  const root = requireObject(manifest, "manifest");
  const playwright = requireObject(root.playwright_core, "manifest.playwright_core");
  const attestations = requireObject(playwright.npm_attestations, "manifest.playwright_core.npm_attestations");
  const cryptoVerification = requireObject(
    attestations.cryptographic_verification,
    "manifest.playwright_core.npm_attestations.cryptographic_verification",
  );
  const postcheck = requireObject(attestations.slsa_allowlist_postcheck, "manifest.playwright_core.npm_attestations.slsa_allowlist_postcheck");
  const expected = requireObject(postcheck.expected, "manifest.playwright_core.npm_attestations.slsa_allowlist_postcheck.expected");

  for (const field of REQUIRED_ALLOWLIST_FIELDS) {
    requireString(expected[field], `manifest.slsa_allowlist_postcheck.expected.${field}`);
  }
  requireEqual(postcheck.required, true, "manifest.slsa_allowlist_postcheck.required");
  requireEqual(attestations.verified, true, "manifest.npm_attestations.verified");
  requireEqual(cryptoVerification.exit_code, 0, "manifest.cryptographic_verification.exit_code");
  if (
    requireArray(cryptoVerification.invalid, "manifest.cryptographic_verification.invalid").length !== 0 ||
    requireArray(cryptoVerification.missing, "manifest.cryptographic_verification.missing").length !== 0
  ) {
    fail("NPM_CRYPTOGRAPHIC_VERIFICATION_FAILED", "manifest.cryptographic_verification", "manifest records invalid or missing signatures");
  }
  requireEqual(
    cryptoVerification.verified_package,
    `playwright-core@${playwright.version}`,
    "manifest.cryptographic_verification.verified_package",
  );

  if (!Buffer.isBuffer(auditBytes)) {
    fail("INVALID_STRUCTURE", "auditBytes", "expected a Buffer");
  }
  requireEqual(auditBytes.length, requireInteger(cryptoVerification.output_bytes, "manifest.cryptographic_verification.output_bytes"), "audit.bytes");
  requireEqual(sha256(auditBytes), cryptoVerification.output_sha256, "audit.sha256");
  const audit = requireObject(parseJson(auditBytes, "audit"), "audit");
  const bundles = verifyAuditEnvelope(audit, attestations, expected, playwright.version);

  const publish = decodeStatement(
    bundles.get(PUBLISH_PREDICATE),
    attestations.publish_statement_sha256,
    "publish",
  );
  requireEqual(publish.bundle.mediaType, SIGSTORE_BUNDLE_V02, "publish.bundle.mediaType");
  verifyPublishStatement(publish.statement, expected, playwright.version);

  const slsa = decodeStatement(
    bundles.get(SLSA_PREDICATE),
    attestations.slsa_statement_sha256,
    "slsa",
  );
  requireEqual(slsa.bundle.mediaType, SIGSTORE_BUNDLE_V03, "slsa.bundle.mediaType");
  verifySlsaStatement(slsa.statement, expected);

  const certificate = decodeBase64(
    slsa.bundle.verificationMaterial?.certificate?.rawBytes,
    "slsa.bundle.verificationMaterial.certificate.rawBytes",
  );
  const certificateClaims = extractFulcioClaims(certificate);
  verifyCertificateClaims(certificateClaims, expected);

  const releaseBlockers = nodeRuntimeBlockers(root, {
    observedNodeVersion,
    observedNodePlatform,
    observedNodeArchitecture,
    observedNodeExecutableSha256,
  });

  return Object.freeze({
    schema_version: "deeptwin-playwright-provenance-result-v1",
    policy_verified: true,
    release_ready: releaseBlockers.length === 0,
    package: `playwright-core@${playwright.version}`,
    subject: expected.subject_name,
    subject_sha512: expected.subject_sha512,
    source_commit: expected.source_commit,
    npm_cryptographic_output_sha256: cryptoVerification.output_sha256,
    slsa_statement_sha256: attestations.slsa_statement_sha256,
    observed_postcheck_node_version: observedNodeVersion,
    observed_postcheck_node_platform: observedNodePlatform,
    observed_postcheck_node_architecture: observedNodeArchitecture,
    observed_postcheck_node_executable_sha256: observedNodeExecutableSha256,
    release_blockers: releaseBlockers,
  });
}

export async function main(argv = process.argv.slice(2)) {
  if (argv.length !== 2) {
    process.stderr.write(
      "usage: verify_playwright_provenance.mjs BROWSER_WORKER_MANIFEST NPM_AUDIT_SIGNATURES_JSON\n",
    );
    return 64;
  }
  try {
    // The release wrapper runs with a read-only root filesystem and launches this exact path.
    // Reading process.execPath avoids QEMU's EINVAL on /proc/self/exe while still checking the
    // executable bytes selected by the wrapper.
    const runtimeExecutable = process.execPath;
    const [manifestBytes, auditBytes, observedNodeExecutableSha256] = await Promise.all([
      readFile(argv[0]),
      readFile(argv[1]),
      sha256File(runtimeExecutable),
    ]);
    const manifest = parseJson(manifestBytes, "manifest");
    const result = verifyPlaywrightProvenance({
      manifest,
      auditBytes,
      observedNodeExecutableSha256,
    });
    process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
    return result.release_ready ? 0 : 3;
  } catch (error) {
    const result = {
      schema_version: "deeptwin-playwright-provenance-result-v1",
      policy_verified: false,
      release_ready: false,
      error: {
        code: error instanceof ProvenanceVerificationError ? error.code : "UNEXPECTED_ERROR",
        message: error.message,
      },
    };
    process.stderr.write(`${JSON.stringify(result, null, 2)}\n`);
    return 1;
  }
}

const invokedPath = process.argv[1] ? resolve(process.argv[1]) : "";
if (invokedPath && resolve(fileURLToPath(import.meta.url)) === invokedPath) {
  process.exitCode = await main();
}
