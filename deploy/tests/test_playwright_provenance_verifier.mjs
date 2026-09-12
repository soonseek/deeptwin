import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";

import {
  ProvenanceVerificationError,
  extractFulcioClaims,
  verifyPlaywrightProvenance,
} from "../locks/verify_playwright_provenance.mjs";

const expected = Object.freeze({
  certificate_identity:
    "https://github.com/microsoft/playwright/.github/workflows/publish_release.yml@refs/tags/v1.63.0",
  certificate_oidc_issuer: "https://token.actions.githubusercontent.com",
  subject_name: "pkg:npm/playwright-core@1.63.0",
  subject_sha512:
    "ad80ac045fcce478d4721e766dbb5538d1058efe97bbcb26f21ef674d951e5bcc81357ef0bf6f182ca7392349f53e3307843263ccf0a25e6c6ea79f2c68e660a",
  repository: "https://github.com/microsoft/playwright",
  workflow_path: ".github/workflows/publish_release.yml",
  source_ref: "refs/tags/v1.63.0",
  source_commit: "1b025d7e20a026371cd5f98ba0cdce48892737c8",
  event_name: "release",
  repository_id: "221981891",
  repository_owner_id: "6154722",
  builder_id: "https://github.com/actions/runner/github-hosted",
  invocation_id: "https://github.com/microsoft/playwright/actions/runs/33926504498/attempts/1",
});

const PUBLISH = "https://github.com/npm/attestation/tree/main/specs/publish/v0.1";
const SLSA = "https://slsa.dev/provenance/v1";

function digest(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

function derLength(length) {
  if (length < 128) return Buffer.from([length]);
  const values = [];
  for (let value = length; value > 0; value = Math.floor(value / 256)) values.unshift(value & 0xff);
  return Buffer.from([0x80 | values.length, ...values]);
}

function der(tag, content) {
  const value = Buffer.from(content);
  return Buffer.concat([Buffer.from([tag]), derLength(value.length), value]);
}

function derSequence(...children) {
  return der(0x30, Buffer.concat(children));
}

function encodeOid(value) {
  const parts = value.split(".").map(Number);
  const bytes = [parts[0] * 40 + parts[1]];
  for (const part of parts.slice(2)) {
    const encoded = [part & 0x7f];
    for (let value = Math.floor(part / 128); value > 0; value = Math.floor(value / 128)) {
      encoded.unshift(0x80 | (value & 0x7f));
    }
    bytes.push(...encoded);
  }
  return der(0x06, bytes);
}

function extension(oid, value, { wrapped = true, critical = false } = {}) {
  const payload = wrapped ? der(0x0c, Buffer.from(value)) : Buffer.from(value);
  return derSequence(
    encodeOid(oid),
    ...(critical ? [der(0x01, [0xff])] : []),
    der(0x04, payload),
  );
}

function certificate(overrides = {}, duplicateOid = null) {
  const claims = {
    identity: expected.certificate_identity,
    issuer: expected.certificate_oidc_issuer,
    event: expected.event_name,
    commit: expected.source_commit,
    slug: "microsoft/playwright",
    ref: expected.source_ref,
    runner: "github-hosted",
    repository: expected.repository,
    repositoryId: expected.repository_id,
    ownerId: expected.repository_owner_id,
    invocation: expected.invocation_id,
    ...overrides,
  };
  const san = derSequence(der(0x86, Buffer.from(claims.identity)));
  const extensions = [
    derSequence(encodeOid("2.5.29.17"), der(0x01, [0xff]), der(0x04, san)),
    extension("1.3.6.1.4.1.57264.1.1", claims.issuer, { wrapped: false }),
    extension("1.3.6.1.4.1.57264.1.2", claims.event, { wrapped: false }),
    extension("1.3.6.1.4.1.57264.1.3", claims.commit, { wrapped: false }),
    extension("1.3.6.1.4.1.57264.1.5", claims.slug, { wrapped: false }),
    extension("1.3.6.1.4.1.57264.1.6", claims.ref, { wrapped: false }),
    extension("1.3.6.1.4.1.57264.1.8", claims.issuer),
    extension("1.3.6.1.4.1.57264.1.9", claims.identity),
    extension("1.3.6.1.4.1.57264.1.11", claims.runner),
    extension("1.3.6.1.4.1.57264.1.12", claims.repository),
    extension("1.3.6.1.4.1.57264.1.13", claims.commit),
    extension("1.3.6.1.4.1.57264.1.14", claims.ref),
    extension("1.3.6.1.4.1.57264.1.15", claims.repositoryId),
    extension("1.3.6.1.4.1.57264.1.17", claims.ownerId),
    extension("1.3.6.1.4.1.57264.1.18", claims.identity),
    extension("1.3.6.1.4.1.57264.1.19", claims.commit),
    extension("1.3.6.1.4.1.57264.1.20", claims.event),
    extension("1.3.6.1.4.1.57264.1.21", claims.invocation),
  ];
  if (duplicateOid) extensions.push(extension(duplicateOid, "duplicate"));
  const tbsCertificate = derSequence(
    der(0xa0, der(0x02, [0x02])),
    der(0x02, [0x01]),
    derSequence(),
    derSequence(),
    derSequence(),
    derSequence(),
    derSequence(),
    der(0xa3, derSequence(...extensions)),
  );
  return derSequence(tbsCertificate, derSequence(), der(0x03, [0x00]));
}

function subject() {
  return [{ name: expected.subject_name, digest: { sha512: expected.subject_sha512 } }];
}

function publishStatement() {
  return {
    _type: "https://in-toto.io/Statement/v0.1",
    subject: subject(),
    predicateType: PUBLISH,
    predicate: {
      name: "playwright-core",
      version: "1.63.0",
      registry: "https://registry.npmjs.org",
    },
  };
}

function slsaStatement() {
  return {
    _type: "https://in-toto.io/Statement/v1",
    subject: subject(),
    predicateType: SLSA,
    predicate: {
      buildDefinition: {
        buildType: "https://slsa-framework.github.io/github-actions-buildtypes/workflow/v1",
        externalParameters: {
          workflow: {
            ref: expected.source_ref,
            repository: expected.repository,
            path: expected.workflow_path,
          },
        },
        internalParameters: {
          github: {
            event_name: expected.event_name,
            repository_id: expected.repository_id,
            repository_owner_id: expected.repository_owner_id,
          },
        },
        resolvedDependencies: [
          {
            uri: `git+${expected.repository}@${expected.source_ref}`,
            digest: { gitCommit: expected.source_commit },
          },
        ],
      },
      runDetails: {
        builder: { id: expected.builder_id },
        metadata: { invocationId: expected.invocation_id },
      },
    },
  };
}

function bundle(predicateType, statement, certificateDer = null) {
  const result = {
    predicateType,
    bundle: {
      mediaType:
        predicateType === SLSA
          ? "application/vnd.dev.sigstore.bundle.v0.3+json"
          : "application/vnd.dev.sigstore.bundle+json;version=0.2",
      verificationMaterial:
        predicateType === SLSA
          ? { certificate: { rawBytes: certificateDer.toString("base64") } }
          : { publicKey: { hint: "fixture" } },
      dsseEnvelope: {
        payload: Buffer.from(JSON.stringify(statement)).toString("base64"),
        payloadType: "application/vnd.in-toto+json",
        signatures: [{ sig: "fixture" }],
      },
    },
  };
  return result;
}

function fixture({ mutateSlsa, certificateOverrides, duplicateCertificateOid, mutateAudit } = {}) {
  const publish = publishStatement();
  const slsa = slsaStatement();
  mutateSlsa?.(slsa);
  const publishBytes = Buffer.from(JSON.stringify(publish));
  const slsaBytes = Buffer.from(JSON.stringify(slsa));
  const audit = {
    invalid: [],
    missing: [],
    verified: [
      {
        name: "playwright-core",
        version: "1.63.0",
        location: "node_modules/playwright-core",
        registry: "https://registry.npmjs.org/",
        attestations: {
          url: "https://registry.npmjs.org/-/npm/v1/attestations/playwright-core@1.63.0",
          provenance: { predicateType: SLSA },
        },
        attestationBundles: [
          bundle(PUBLISH, publish),
          bundle(SLSA, slsa, certificate(certificateOverrides, duplicateCertificateOid)),
        ],
      },
    ],
  };
  mutateAudit?.(audit);
  const auditBytes = Buffer.from(JSON.stringify(audit));
  const manifest = {
    playwright_core: {
      version: "1.63.0",
      npm_attestations: {
        url: "https://registry.npmjs.org/-/npm/v1/attestations/playwright-core@1.63.0",
        publish_statement_sha256: digest(publishBytes),
        slsa_statement_sha256: digest(slsaBytes),
        verified: true,
        cryptographic_verification: {
          exit_code: 0,
          invalid: [],
          missing: [],
          verified_package: "playwright-core@1.63.0",
          output_bytes: auditBytes.length,
          output_sha256: digest(auditBytes),
        },
        slsa_allowlist_postcheck: {
          required: true,
          expected: { ...expected },
        },
      },
    },
  };
  return { manifest, auditBytes };
}

function qualifiedNodeFixture() {
  const value = fixture();
  value.manifest.node = {
    version: "24.20.0",
    official_release_provenance: {
      signed_checksums: { openpgp_verified: true },
      platforms: [
        {
          os: "linux",
          architecture: "amd64",
          executable_sha256: "8".repeat(64),
          base_image_executable_sha256_match: true,
        },
        {
          os: "linux",
          architecture: "arm64",
          executable_sha256: "a".repeat(64),
          base_image_executable_sha256_match: true,
        },
      ],
    },
  };
  return value;
}

function expectFailure(build, code, locationPattern) {
  assert.throws(
    () => verifyPlaywrightProvenance(build()),
    (error) => {
      assert.ok(error instanceof ProvenanceVerificationError);
      assert.equal(error.code, code);
      assert.match(error.location, locationPattern);
      return true;
    },
  );
}

test("exact npm result passes policy but keeps Node runtime as a release blocker", () => {
  const result = verifyPlaywrightProvenance(fixture());
  assert.equal(result.policy_verified, true);
  assert.equal(result.release_ready, false);
  assert.deepEqual(result.release_blockers.map((item) => item.code), [
    "POSTCHECK_NODE_RUNTIME_UNQUALIFIED",
  ]);
});

test("exact signed Node runtime bytes promote a provenance policy pass", () => {
  const result = verifyPlaywrightProvenance({
    ...qualifiedNodeFixture(),
    observedNodeVersion: "24.20.0",
    observedNodePlatform: "linux",
    observedNodeArchitecture: "x64",
    observedNodeExecutableSha256: "8".repeat(64),
  });
  assert.equal(result.policy_verified, true);
  assert.equal(result.release_ready, true);
  assert.deepEqual(result.release_blockers, []);
});

test("a different Node executable cannot promote the policy result", () => {
  const result = verifyPlaywrightProvenance({
    ...qualifiedNodeFixture(),
    observedNodeVersion: "24.20.0",
    observedNodePlatform: "linux",
    observedNodeArchitecture: "arm64",
    observedNodeExecutableSha256: "b".repeat(64),
  });
  assert.equal(result.policy_verified, true);
  assert.equal(result.release_ready, false);
  assert.deepEqual(result.release_blockers.map((item) => item.code), [
    "POSTCHECK_NODE_RUNTIME_BYTES_MISMATCH",
  ]);
});

test("certificate DER extractor rejects duplicate security claims", () => {
  assert.throws(
    () => extractFulcioClaims(certificate({}, "1.3.6.1.4.1.57264.1.1")),
    (error) => error.code === "AMBIGUOUS_CERTIFICATE_CLAIM",
  );
});

test("raw npm output must retain its exact cryptographic-result hash", () => {
  const value = fixture();
  value.auditBytes = Buffer.concat([value.auditBytes, Buffer.from("\n")]);
  expectFailure(() => value, "ALLOWLIST_MISMATCH", /^audit\.bytes$/);
});

test("npm invalid signature state fails even when its new bytes are re-pinned", () => {
  expectFailure(
    () => fixture({ mutateAudit: (audit) => audit.invalid.push({ name: "playwright-core" }) }),
    "NPM_CRYPTOGRAPHIC_VERIFICATION_FAILED",
    /^audit$/,
  );
});

const slsaMutations = [
  ["subject", (value) => { value.subject[0].name = "pkg:npm/not-playwright@1.63.0"; }, /^slsa\.statement\.subject/],
  ["repository", (value) => { value.predicate.buildDefinition.externalParameters.workflow.repository = "https://github.com/attacker/playwright"; }, /^slsa\.workflow\.repository$/],
  ["workflow", (value) => { value.predicate.buildDefinition.externalParameters.workflow.path = ".github/workflows/untrusted.yml"; }, /^slsa\.workflow\.path$/],
  ["ref", (value) => { value.predicate.buildDefinition.externalParameters.workflow.ref = "refs/heads/main"; }, /^slsa\.workflow\.ref$/],
  ["commit", (value) => { value.predicate.buildDefinition.resolvedDependencies[0].digest.gitCommit = "0".repeat(40); }, /^slsa\.resolvedDependencies/],
  ["event", (value) => { value.predicate.buildDefinition.internalParameters.github.event_name = "workflow_dispatch"; }, /^slsa\.github\.event_name$/],
  ["repository id", (value) => { value.predicate.buildDefinition.internalParameters.github.repository_id = "1"; }, /^slsa\.github\.repository_id$/],
  ["owner id", (value) => { value.predicate.buildDefinition.internalParameters.github.repository_owner_id = "1"; }, /^slsa\.github\.repository_owner_id$/],
  ["builder", (value) => { value.predicate.runDetails.builder.id = "https://example.invalid/builder"; }, /^slsa\.runDetails\.builder\.id$/],
  ["invocation", (value) => { value.predicate.runDetails.metadata.invocationId = "https://example.invalid/run"; }, /^slsa\.runDetails\.metadata\.invocationId$/],
];

for (const [name, mutateSlsa, location] of slsaMutations) {
  test(`rejects re-hashed SLSA ${name} outside the allowlist`, () => {
    expectFailure(() => fixture({ mutateSlsa }), "ALLOWLIST_MISMATCH", location);
  });
}

test("rejects a re-pinned certificate identity outside the allowlist", () => {
  expectFailure(
    () => fixture({ certificateOverrides: { identity: "https://example.invalid/workflow@refs/tags/v1.63.0" } }),
    "ALLOWLIST_MISMATCH",
    /^certificate\.subjectAlternativeName$/,
  );
});

test("rejects a re-pinned certificate OIDC issuer outside the allowlist", () => {
  expectFailure(
    () => fixture({ certificateOverrides: { issuer: "https://issuer.example.invalid" } }),
    "ALLOWLIST_MISMATCH",
    /^certificate\.oidcIssuerLegacy$/,
  );
});

test("rejects duplicate SLSA bundles even if npm status fields claim success", () => {
  expectFailure(
    () => fixture({
      mutateAudit: (audit) => audit.verified[0].attestationBundles.push(
        structuredClone(audit.verified[0].attestationBundles[1]),
      ),
    }),
    "AMBIGUOUS_ATTESTATION_SET",
    /^audit\.verified\[0\]\.attestationBundles$/,
  );
});
