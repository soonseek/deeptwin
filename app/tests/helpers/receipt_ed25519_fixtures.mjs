#!/usr/bin/env node
/* Developer-test-only ephemeral Ed25519 receipt fixture generator/verifier. */

import {
  createHash,
  createPublicKey,
  generateKeyPairSync,
  randomUUID,
  sign,
  verify,
} from "node:crypto";
import { readFileSync } from "node:fs";

const FRAME_LIMIT = 131072;
const REQUEST_LIMIT = 65536;
const CASE_LIMIT = 64;
const STATIC_CASES = new Set([
  "valid_succeeded_present",
  "valid_failed_absent",
  "valid_failed_unknown",
  "valid_unknown_unknown",
  "invalid_cross_request",
  "invalid_profile",
  "invalid_tuple",
  "invalid_key_adapter",
  "invalid_time",
  "invalid_expiry",
  "invalid_fact",
]);
const CASES = new Set([...STATIC_CASES, "invalid_service_identity"]);
const SPKI_PREFIX = Buffer.from("302a300506032b6570032100", "hex");

function fail() {
  process.stderr.write("receipt_fixture_invalid\n");
  process.exit(1);
}

function exactKeys(value, names) {
  return (
    value !== null &&
    !Array.isArray(value) &&
    typeof value === "object" &&
    Object.keys(value).sort().join("\0") === [...names].sort().join("\0")
  );
}

function canonical(value) {
  if (value === null || typeof value === "boolean" || typeof value === "string") {
    return JSON.stringify(value);
  }
  if (typeof value === "number" && Number.isSafeInteger(value)) {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map(canonical).join(",")}]`;
  }
  if (value !== null && typeof value === "object") {
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`)
      .join(",")}}`;
  }
  throw new Error("invalid JSON value");
}

function canonicalBytes(value) {
  return Buffer.from(canonical(value), "utf8");
}

function sha256(value) {
  return createHash("sha256").update(value).digest();
}

function b64(value) {
  return Buffer.from(value).toString("base64url");
}

function decodeB64(value, limit) {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value.includes("=") ||
    !/^[A-Za-z0-9_-]+$/.test(value)
  ) {
    fail();
  }
  const decoded = Buffer.from(value, "base64url");
  if (decoded.length > limit || b64(decoded) !== value) fail();
  return decoded;
}

function rawPublicKey(publicKey) {
  const der = publicKey.export({ format: "der", type: "spki" });
  if (der.length !== SPKI_PREFIX.length + 32 || !der.subarray(0, SPKI_PREFIX.length).equals(SPKI_PREFIX)) {
    fail();
  }
  return der.subarray(SPKI_PREFIX.length);
}

function publicKeyFromRaw(raw) {
  if (!Buffer.isBuffer(raw) || raw.length !== 32) fail();
  return createPublicKey({
    key: Buffer.concat([SPKI_PREFIX, raw]),
    format: "der",
    type: "spki",
  });
}

function validateProfile(profile) {
  const fields = [
    "deployment_profile_id",
    "instance_id",
    "mode",
    "scheme",
    "host",
    "port",
    "base_path",
    "origin_base",
    "digest",
  ];
  if (!exactKeys(profile, fields) || !/^[0-9a-f]{32}$/.test(profile.instance_id)) fail();
  if (!Number.isInteger(profile.port) || profile.port < 1 || profile.port > 65535) fail();
  const preimage = {};
  for (const name of fields.slice(0, -1)) preimage[name] = profile[name];
  if (sha256(canonicalBytes(preimage)).toString("hex") !== profile.digest) fail();
  if (profile.deployment_profile_id === "local-no-terminal-v1") {
    const suffix = profile.port === 80 ? "" : `:${profile.port}`;
    if (
      profile.mode !== "local_loopback" ||
      profile.scheme !== "http" ||
      profile.host !== `${profile.instance_id}.localhost` ||
      !/^\/[0-9a-f]{32}\/$/.test(profile.base_path) ||
      profile.origin_base !== `http://${profile.host}${suffix}${profile.base_path}`
    ) fail();
  } else if (profile.deployment_profile_id === "portable-compose-v1") {
    const suffix = profile.port === 443 ? "" : `:${profile.port}`;
    if (
      profile.mode !== "portable_https" ||
      profile.scheme !== "https" ||
      !/^[a-z0-9.-]+$/.test(profile.host) ||
      profile.base_path !== "/" ||
      profile.origin_base !== `https://${profile.host}${suffix}/`
    ) fail();
  } else fail();
  return profile;
}

function makeProfile(portable) {
  const instance = portable ? "3".repeat(32) : "1".repeat(32);
  const fields = portable
    ? {
        deployment_profile_id: "portable-compose-v1",
        instance_id: instance,
        mode: "portable_https",
        scheme: "https",
        host: "example.org",
        port: 443,
        base_path: "/",
        origin_base: "https://example.org/",
      }
    : {
        deployment_profile_id: "local-no-terminal-v1",
        instance_id: instance,
        mode: "local_loopback",
        scheme: "http",
        host: `${instance}.localhost`,
        port: 8080,
        base_path: `/${"2".repeat(32)}/`,
        origin_base: `http://${instance}.localhost:8080/${"2".repeat(32)}/`,
      };
  return { ...fields, digest: sha256(canonicalBytes(fields)).toString("hex") };
}

function makeStage(instance) {
  const service = `ext-${instance}-01`;
  return {
    schema_id: "deeptwin.extension-stage-request.v1",
    extension_id: "synthetic-tool",
    manifest_digest: "1".repeat(64),
    service_descriptor_digest: "2".repeat(64),
    selected_platform_entry: {
      platform: "linux/amd64",
      index_digest: `sha256:${"a".repeat(64)}`,
      manifest_digest: `sha256:${"4".repeat(64)}`,
      config_digest: `sha256:${"b".repeat(64)}`,
      ordered_layer_digests: [`sha256:${"c".repeat(64)}`],
    },
    new_service_effect: {
      service_identity: service,
      socket_mounts: [
        {
          mount_id: "xs01",
          purpose: "broker_pair",
          volume_name: `dt-${instance}-ipc-xs01`,
          container_path: "/run/deeptwin/ipc/xs01",
          read_only: false,
        },
      ],
      named_volume_mounts: [],
      network_policy_ref: {
        document_kind: "network_declaration",
        sha256: "5".repeat(64),
        size_bytes: 75,
      },
      resource_profile_ref: {
        document_kind: "resource_declaration",
        sha256: "6".repeat(64),
        size_bytes: 136,
      },
    },
    expected_installation_head: { state: "absent" },
    expected_next_installation_revision: 1,
  };
}

function makeRequest(profile, ordinal) {
  const request = {
    schema: "deployment-request-v1",
    domain: "deeptwin-deployment-request-v1",
    request_id: ordinal === 1
      ? "12345678-1234-4234-8234-123456789abc"
      : "22345678-1234-4234-8234-123456789abc",
    kind: "extension_stage",
    request_nonce: b64(Buffer.alloc(32, ordinal)),
    instance_id: profile.instance_id,
    origin_profile_digest: b64(Buffer.from(profile.digest, "hex")),
    effect_payload: makeStage(profile.instance_id),
    preconditions: {},
    created_by: {
      kind: "actor",
      id: "87654321-4321-4321-8321-cba987654321",
      version: 1,
      sha256: "7".repeat(64),
    },
    created_at: "2023-11-14T22:13:20.000Z",
    expires_at: "2023-11-14T22:14:20.000Z",
  };
  request.request_digest = b64(sha256(canonicalBytes(request)));
  return request;
}

function validUuid(value) {
  return typeof value === "string" &&
    /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(value) &&
    value !== "00000000-0000-0000-0000-000000000000";
}

function validHex(value, size = 64) {
  return typeof value === "string" && new RegExp(`^[0-9a-f]{${size}}$`).test(value);
}

function validId(value, maximum = 128) {
  return typeof value === "string" && value.length <= maximum &&
    /^[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?$/.test(value);
}

function validBroker(value) {
  return typeof value === "string" && value.length <= 64 &&
    /^[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)*$/.test(value);
}

function validTimestamp(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(value)) {
    return false;
  }
  const instant = new Date(value);
  return Number.isFinite(instant.valueOf()) && instant.toISOString() === value;
}

function validMeta(value, kind) {
  return exactKeys(value, ["document_kind", "sha256", "size_bytes"]) &&
    value.document_kind === kind && validHex(value.sha256) &&
    Number.isInteger(value.size_bytes) && value.size_bytes > 0 && value.size_bytes <= 65536;
}

function validateStage(stage) {
  if (!exactKeys(stage, [
    "schema_id", "extension_id", "manifest_digest", "service_descriptor_digest",
    "selected_platform_entry", "new_service_effect", "expected_installation_head",
    "expected_next_installation_revision",
  ]) || stage.schema_id !== "deeptwin.extension-stage-request.v1" ||
      !validId(stage.extension_id) || !validHex(stage.manifest_digest) ||
      !validHex(stage.service_descriptor_digest) ||
      !exactKeys(stage.expected_installation_head, ["state"]) ||
      stage.expected_installation_head.state !== "absent" ||
      stage.expected_next_installation_revision !== 1) fail();
  const selected = stage.selected_platform_entry;
  const oci = (value) => typeof value === "string" && /^sha256:[0-9a-f]{64}$/.test(value);
  if (!exactKeys(selected, [
    "platform", "index_digest", "manifest_digest", "config_digest", "ordered_layer_digests",
  ]) || !["linux/amd64", "linux/arm64"].includes(selected.platform) ||
      !oci(selected.index_digest) || !oci(selected.manifest_digest) || !oci(selected.config_digest) ||
      !Array.isArray(selected.ordered_layer_digests) || selected.ordered_layer_digests.length < 1 ||
      selected.ordered_layer_digests.length > 128 || !selected.ordered_layer_digests.every(oci)) fail();
  const effect = stage.new_service_effect;
  if (!exactKeys(effect, [
    "service_identity", "socket_mounts", "named_volume_mounts", "network_policy_ref",
    "resource_profile_ref",
  ]) || !validBroker(effect.service_identity) || !Array.isArray(effect.socket_mounts) ||
      effect.socket_mounts.length !== 1 || !Array.isArray(effect.named_volume_mounts) ||
      effect.named_volume_mounts.length !== 0 ||
      !validMeta(effect.network_policy_ref, "network_declaration") ||
      !validMeta(effect.resource_profile_ref, "resource_declaration")) fail();
  const mount = effect.socket_mounts[0];
  if (!exactKeys(mount, ["mount_id", "purpose", "volume_name", "container_path", "read_only"]) ||
      !validId(mount.mount_id) || mount.purpose !== "broker_pair" || !validId(mount.volume_name) ||
      typeof mount.container_path !== "string" || mount.container_path.length > 256 ||
      !mount.container_path.startsWith("/") || typeof mount.read_only !== "boolean") fail();
}

function parseRequest(raw, profile) {
  if (!Buffer.isBuffer(raw) || raw.length === 0 || raw.length > REQUEST_LIMIT) fail();
  let request;
  try {
    const text = raw.toString("utf8");
    if (!Buffer.from(text, "utf8").equals(raw)) fail();
    request = JSON.parse(text);
    if (!canonicalBytes(request).equals(raw)) fail();
  } catch {
    fail();
  }
  const fields = [
    "schema", "domain", "request_id", "request_digest", "request_nonce", "kind",
    "instance_id", "origin_profile_digest", "effect_payload", "preconditions", "created_by",
    "created_at", "expires_at",
  ];
  if (
    !exactKeys(request, fields) ||
    request.schema !== "deployment-request-v1" ||
    request.domain !== "deeptwin-deployment-request-v1" ||
    request.kind !== "extension_stage" ||
    !validUuid(request.request_id) ||
    decodeB64(request.request_digest, 32).length !== 32 ||
    decodeB64(request.request_nonce, 32).length !== 32 ||
    !validHex(request.instance_id, 32) ||
    decodeB64(request.origin_profile_digest, 32).length !== 32 ||
    request.instance_id !== profile.instance_id ||
    request.origin_profile_digest !== b64(Buffer.from(profile.digest, "hex")) ||
    !exactKeys(request.preconditions, []) ||
    !exactKeys(request.created_by, ["kind", "id", "version", "sha256"]) ||
    request.created_by.kind !== "actor" || !validUuid(request.created_by.id) ||
    !Number.isSafeInteger(request.created_by.version) || request.created_by.version < 1 ||
    !validHex(request.created_by.sha256) || !validTimestamp(request.created_at) ||
    !validTimestamp(request.expires_at)
  ) fail();
  const duration = new Date(request.expires_at) - new Date(request.created_at);
  if (duration < 60000 || duration > 86400000 || duration % 1000 !== 0) fail();
  validateStage(request.effect_payload);
  const copy = { ...request };
  delete copy.request_digest;
  if (request.request_digest !== b64(sha256(canonicalBytes(copy)))) fail();
  return request;
}

function makeTrust(profile, keyId, publicRaw) {
  return {
    schema: "deployment-public-trust-set-v1",
    domain: "deeptwin-deployment-public-trust-set-v1",
    version: 1,
    instance_id: profile.instance_id,
    origin_profile_digest: b64(Buffer.from(profile.digest, "hex")),
    keys: [
      {
        key_id: keyId,
        algorithm: "ed25519",
        public_key: b64(publicRaw),
        trust_class: "instance_operator",
        adapter_ids: ["deeptwin-stage-operator-v1"],
      },
    ],
    adapters: [
      {
        operator_adapter: "deeptwin-stage-operator-v1",
        operator_version: "1.0.0",
        deployment_profile_id: profile.deployment_profile_id,
      },
    ],
  };
}

function shifted(timestamp, milliseconds) {
  const instant = new Date(timestamp);
  if (!Number.isFinite(instant.valueOf())) fail();
  return new Date(instant.valueOf() + milliseconds).toISOString();
}

function makeService(request, presence, observedAt, failureClass) {
  const stage = request.effect_payload;
  const selectedDigest = sha256(canonicalBytes(stage.selected_platform_entry)).toString("hex");
  if (presence === "absent") return { presence: "absent" };
  if (presence === "present") {
    return {
      presence: "present",
      service_identity: stage.new_service_effect.service_identity,
      manifest_digest: stage.manifest_digest,
      service_descriptor_digest: stage.service_descriptor_digest,
      selected_platform_entry_digest: selectedDigest,
      image_manifest_digest: stage.selected_platform_entry.manifest_digest,
      reachable_after_effect: true,
      observed_at: observedAt,
    };
  }
  return {
    presence: "unknown",
    expected_service_identity: stage.new_service_effect.service_identity,
    expected_manifest_digest: stage.manifest_digest,
    expected_service_descriptor_digest: stage.service_descriptor_digest,
    expected_selected_platform_entry_digest: selectedDigest,
    expected_image_manifest_digest: stage.selected_platform_entry.manifest_digest,
    failure_class: failureClass,
    observed_at: observedAt,
  };
}

function buildCase({ request, profile, trustBytes, keyId, privateKey, caseName }) {
  if (!CASES.has(caseName)) fail();
  let outcome = "succeeded";
  let failureClass = null;
  let presence = "present";
  if (caseName === "valid_failed_absent") {
    outcome = "failed";
    failureClass = "effect_failed";
    presence = "absent";
  } else if (caseName === "valid_failed_unknown") {
    outcome = "failed";
    failureClass = "effect_failed";
    presence = "unknown";
  } else if (caseName === "valid_unknown_unknown") {
    outcome = "unknown";
    failureClass = "observation_unavailable";
    presence = "unknown";
  }
  let startedAt = shifted(request.created_at, 1000);
  let observedAt = shifted(request.created_at, 1500);
  let completedAt = shifted(request.created_at, 2000);
  if (caseName === "invalid_time") {
    startedAt = shifted(request.created_at, -2000);
    observedAt = shifted(request.created_at, -1500);
    completedAt = shifted(request.created_at, -1000);
  } else if (caseName === "invalid_expiry") {
    completedAt = request.expires_at;
  }
  const observationFailure = outcome === "unknown" ? failureClass : "observation_unavailable";
  const receipt = {
    schema: "deployment-receipt-v1",
    domain: "deeptwin-deployment-receipt-v1",
    request_id: request.request_id,
    request_digest: request.request_digest,
    request_nonce: request.request_nonce,
    kind: request.kind,
    instance_id: request.instance_id,
    origin_profile_digest: request.origin_profile_digest,
    deployment_profile_id: profile.deployment_profile_id,
    operator_adapter: "deeptwin-stage-operator-v1",
    operator_version: "1.0.0",
    effect_result: {
      schema_id: "deeptwin.extension-stage-result.v1",
      extension_id: request.effect_payload.extension_id,
      expected_installation_head: { state: "absent" },
      expected_next_installation_revision: 1,
      old_service: { presence: "absent" },
      new_service: makeService(request, presence, observedAt, observationFailure),
    },
    started_at: startedAt,
    completed_at: completedAt,
    outcome,
    failure_class: failureClass,
    claimed_facts: ["request_binding"],
    verified_facts: ["service_presence"],
    unverified_facts: ["service_reachability"],
    key_id: keyId,
    trust_set_digest: b64(sha256(trustBytes)),
    trust_class: "instance_operator",
  };
  if (caseName === "invalid_cross_request") {
    const invalidNonce = decodeB64(request.request_nonce, 32);
    invalidNonce[0] ^= 1;
    receipt.request_nonce = b64(invalidNonce);
  }
  if (caseName === "invalid_profile") {
    receipt.deployment_profile_id = profile.deployment_profile_id === "local-no-terminal-v1"
      ? "portable-compose-v1"
      : "local-no-terminal-v1";
  }
  if (caseName === "invalid_tuple") {
    const manifest = request.effect_payload.manifest_digest;
    receipt.effect_result.new_service.manifest_digest =
      (manifest[0] === "0" ? "1" : "0") + manifest.slice(1);
  }
  if (caseName === "invalid_service_identity") {
    receipt.effect_result.new_service.service_identity = `1${"a".repeat(64)}`;
  }
  if (caseName === "invalid_key_adapter") receipt.operator_version = "1.0.1";
  if (caseName === "invalid_fact") receipt.claimed_facts = ["request_binding", "request_binding"];
  const preimage = canonicalBytes(receipt);
  receipt.signature = b64(sign(null, preimage, privateKey));
  return { receiptBytes: canonicalBytes(receipt), preimage };
}

function expectedValidity(caseName) {
  if (caseName.startsWith("valid_")) return "valid";
  if (caseName === "invalid_cross_request" || caseName === "invalid_tuple" ||
      caseName === "invalid_service_identity") {
    return "request_mismatch";
  }
  if (caseName === "invalid_time" || caseName === "invalid_expiry") return "request_time_invalid";
  if (caseName === "invalid_profile") return "trust_profile_invalid";
  return "intrinsic_invalid";
}

function generateStatic() {
  const { publicKey, privateKey } = generateKeyPairSync("ed25519");
  const publicRaw = rawPublicKey(publicKey);
  const keyId = randomUUID();
  const profiles = [makeProfile(false), makeProfile(true)];
  const names = [...STATIC_CASES];
  const cases = names.map((caseName, index) => {
    const profile = profiles[index % profiles.length];
    const request = makeRequest(profile, (index % 2) + 1);
    const requestBytes = canonicalBytes(request);
    const trustBytes = canonicalBytes(makeTrust(profile, keyId, publicRaw));
    const built = buildCase({ request, profile, trustBytes, keyId, privateKey, caseName });
    return {
      name: caseName,
      expected_validity: expectedValidity(caseName),
      profile,
      public_key: b64(publicRaw),
      request_utf8: requestBytes.toString("utf8"),
      trust_utf8: trustBytes.toString("utf8"),
      trust_sha256: sha256(trustBytes).toString("hex"),
      receipt_utf8: built.receiptBytes.toString("utf8"),
      unsigned_preimage_utf8: built.preimage.toString("utf8"),
    };
  });
  process.stdout.write(`${JSON.stringify({
    schema: "deployment-receipt-ed25519-fixture-v1",
    algorithm: "Ed25519",
    cases,
  }, null, 2)}\n`);
}

function verifyStatic() {
  const raw = readFileSync(0);
  if (raw.length === 0 || raw.length > 262144) fail();
  let fixture;
  try {
    fixture = JSON.parse(raw.toString("utf8"));
  } catch {
    fail();
  }
  if (!exactKeys(fixture, ["schema", "algorithm", "cases"]) ||
      fixture.schema !== "deployment-receipt-ed25519-fixture-v1" ||
      fixture.algorithm !== "Ed25519" || !Array.isArray(fixture.cases)) fail();
  const seen = new Set();
  for (const entry of fixture.cases) {
    if (!exactKeys(entry, [
      "name", "expected_validity", "profile", "public_key", "request_utf8", "trust_utf8",
      "trust_sha256", "receipt_utf8", "unsigned_preimage_utf8",
    ]) || !STATIC_CASES.has(entry.name) || seen.has(entry.name) ||
        entry.expected_validity !== expectedValidity(entry.name)) fail();
    seen.add(entry.name);
    validateProfile(entry.profile);
    const receiptBytes = Buffer.from(entry.receipt_utf8, "utf8");
    const preimage = Buffer.from(entry.unsigned_preimage_utf8, "utf8");
    let receipt, trust;
    try {
      receipt = JSON.parse(entry.receipt_utf8);
      trust = JSON.parse(entry.trust_utf8);
    } catch {
      fail();
    }
    const unsigned = { ...receipt };
    const signature = decodeB64(unsigned.signature, 64);
    delete unsigned.signature;
    if (!canonicalBytes(unsigned).equals(preimage)) fail();
    if (!canonicalBytes(receipt).equals(receiptBytes) ||
        sha256(Buffer.from(entry.trust_utf8, "utf8")).toString("hex") !== entry.trust_sha256 ||
        !Array.isArray(trust.keys) || trust.keys.length !== 1 ||
        trust.keys[0].public_key !== entry.public_key ||
        receipt.trust_set_digest !== b64(sha256(Buffer.from(entry.trust_utf8, "utf8")))) fail();
    const key = publicKeyFromRaw(decodeB64(entry.public_key, 32));
    if (!verify(null, preimage, key, signature)) fail();
  }
  if (seen.size !== STATIC_CASES.size) fail();
}

function runSession() {
  let state = null;
  let count = 0;
  let buffered = Buffer.alloc(0);

  function handle(frame) {
    if (frame.length === 0 || frame.length > FRAME_LIMIT) fail();
    let command;
    try {
      const text = frame.toString("utf8");
      if (!Buffer.from(text, "utf8").equals(frame)) fail();
      command = JSON.parse(text);
    } catch {
      fail();
    }
    if (state === null) {
      if (!exactKeys(command, ["op", "profile"]) || command.op !== "init") fail();
      const profile = validateProfile(command.profile);
      const pair = generateKeyPairSync("ed25519");
      const publicRaw = rawPublicKey(pair.publicKey);
      const keyId = randomUUID();
      const trustBytes = canonicalBytes(makeTrust(profile, keyId, publicRaw));
      state = { profile, privateKey: pair.privateKey, keyId, trustBytes };
      process.stdout.write(`${JSON.stringify({ trust_b64: b64(trustBytes) })}\n`);
      return;
    }
    if (!exactKeys(command, ["op", "request_b64", "case"]) ||
        command.op !== "case" || !CASES.has(command.case) || count >= CASE_LIMIT) fail();
    count += 1;
    const requestBytes = decodeB64(command.request_b64, REQUEST_LIMIT);
    const request = parseRequest(requestBytes, state.profile);
    const built = buildCase({
      request,
      profile: state.profile,
      trustBytes: state.trustBytes,
      keyId: state.keyId,
      privateKey: state.privateKey,
      caseName: command.case,
    });
    process.stdout.write(`${JSON.stringify({
      receipt_b64: b64(built.receiptBytes),
      unsigned_preimage_b64: b64(built.preimage),
    })}\n`);
  }

  process.stdin.on("data", (chunk) => {
    let offset = 0;
    while (offset < chunk.length) {
      const newline = chunk.indexOf(10, offset);
      const end = newline === -1 ? chunk.length : newline;
      const piece = chunk.subarray(offset, end);
      if (buffered.length + piece.length > FRAME_LIMIT) fail();
      buffered = Buffer.concat([buffered, piece]);
      if (newline === -1) return;
      handle(buffered);
      buffered = Buffer.alloc(0);
      offset = newline + 1;
    }
  });
  process.stdin.on("end", () => {
    if (buffered.length !== 0) fail();
  });
  process.stdin.on("error", fail);
}

try {
  if (process.argv.length === 2) generateStatic();
  else if (process.argv.length === 3 && process.argv[2] === "--verify") verifyStatic();
  else if (process.argv.length === 3 && process.argv[2] === "--session") runSession();
  else fail();
} catch {
  fail();
}
