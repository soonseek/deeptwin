import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";


const ROOT = fileURLToPath(new URL("../..", import.meta.url));
const HTML_PATH = `${ROOT}/deploy/bootstrap/index.html`;
const VECTOR_PATH = `${ROOT}/schemas/v1/test-vectors/bootstrap-origin-profile-v1.json`;

const html = await readFile(HTML_PATH, "utf8");
const vectors = JSON.parse(await readFile(VECTOR_PATH, "utf8"));
const scriptMatch = html.match(
  /<script type="module" data-deeptwin-bootstrap-helper>([\s\S]*?)<\/script>/,
);
assert.ok(scriptMatch, "bootstrap helper must expose one inspectable inline module");
await import(
  `data:text/javascript;base64,${Buffer.from(scriptMatch[1]).toString("base64")}`
);
const helper = globalThis.DeepTwinBootstrap;


test("shared capability vectors match WebCrypto-compatible helper", async () => {
  for (const item of vectors.capability_vectors) {
    assert.deepEqual(
      [...helper.strictDecodeB64u32(item.raw_capability_b64u)],
      [...Buffer.from(item.raw_capability_hex, "hex")],
    );
    assert.equal(
      await helper.deriveCapabilityVerifier(item.raw_capability_b64u),
      item.verifier_b64u,
    );
    assert.equal(
      await helper.verifyBootstrapCapability(
        item.raw_capability_b64u,
        item.verifier_b64u,
      ),
      true,
    );
    const changed = `${item.raw_capability_b64u[0] === "A" ? "B" : "A"}${item.raw_capability_b64u.slice(1)}`;
    assert.equal(
      await helper.verifyBootstrapCapability(changed, item.verifier_b64u),
      false,
    );
  }
  for (const value of vectors.invalid_capability_b64u) {
    assert.throws(() => helper.strictDecodeB64u32(value), /invalid bootstrap input/);
  }
});


test("shared local and portable vectors have exact canonical profiles", async () => {
  for (const item of vectors.origin_profile_vectors) {
    const profile = item.constructor === "local"
      ? await helper.createLocalOriginProfile(item.input)
      : await helper.createPortableOriginProfile(item.input);
    assert.deepEqual(profile, item.profile, item.name);
    const preimage = helper.canonicalJson(
      Object.fromEntries(Object.entries(profile).filter(([key]) => key !== "digest")),
    );
    assert.equal(preimage, item.canonical_preimage_utf8);
    assert.equal(
      createHash("sha256").update(preimage).digest("hex"),
      profile.digest,
    );
  }
});


test("the pinned IDNA validity table is enforced by the canonical-host path", async () => {
  assert.deepEqual(helper.idnaProfile, vectors.idna_profile);
  const table = helper.idnaPvalidTableBytes();
  assert.equal(
    createHash("sha256").update(table).digest("hex"),
    vectors.idna_profile.pvalid_table_sha256,
  );
  assert.equal(helper.isPvalidCodePoint("a".codePointAt(0)), true);
  assert.equal(helper.isPvalidCodePoint("딥".codePointAt(0)), true);
  assert.equal(helper.isPvalidCodePoint("ᄰ".codePointAt(0)), false);

  let offset = 0;
  let previousEnd = 0;
  let rangeCount = 0;
  const readLeb128 = () => {
    let value = 0;
    let scale = 1;
    for (;;) {
      const byte = table[offset];
      offset += 1;
      value += (byte & 127) * scale;
      if ((byte & 128) === 0) return value;
      scale *= 128;
    }
  };
  while (offset < table.length) {
    const start = previousEnd + readLeb128();
    const end = start + readLeb128();
    assert.equal(helper.isPvalidCodePoint(start), true);
    assert.equal(helper.isPvalidCodePoint(end - 1), true);
    if (start > previousEnd) {
      assert.equal(helper.isPvalidCodePoint(start - 1), false);
    }
    previousEnd = end;
    rangeCount += 1;
  }
  assert.equal(rangeCount, vectors.idna_profile.pvalid_range_count);
  const bidiTable = helper.idnaBidiTableBytes();
  assert.equal(
    createHash("sha256").update(bidiTable).digest("hex"),
    vectors.idna_profile.bidi_table_sha256,
  );
  assert.equal(helper.bidiClassForCodePoint("a".codePointAt(0)), "L");
  assert.equal(helper.bidiClassForCodePoint(0x0870), "AL");
  assert.equal(helper.bidiClassForCodePoint(0xa7cb), "");
  let bidiOffset = 0;
  let previousBidiEnd = 0;
  let bidiRangeCount = 0;
  const readBidiLeb128 = () => {
    let value = 0;
    let scale = 1;
    for (;;) {
      const byte = bidiTable[bidiOffset];
      bidiOffset += 1;
      value += (byte & 127) * scale;
      if ((byte & 128) === 0) return value;
      scale *= 128;
    }
  };
  while (bidiOffset < bidiTable.length) {
    const start = previousBidiEnd + readBidiLeb128();
    const end = start + readBidiLeb128();
    const bidiClass = vectors.idna_profile.bidi_classes[bidiTable[bidiOffset]];
    bidiOffset += 1;
    assert.equal(helper.bidiClassForCodePoint(start), bidiClass);
    assert.equal(helper.bidiClassForCodePoint(end - 1), bidiClass);
    if (start > previousBidiEnd) {
      assert.equal(helper.bidiClassForCodePoint(start - 1), "");
    }
    previousBidiEnd = end;
    bidiRangeCount += 1;
  }
  assert.equal(bidiRangeCount, vectors.idna_profile.bidi_range_count);

  const invalidNames = new Set([
    "crafted-a-label-leading-hyphen",
    "crafted-a-label-trailing-hyphen",
    "contexto-misuse",
    "disallowed-jamo",
    "disallowed-combiner",
    "mixed-bidi-label",
  ]);
  for (const item of vectors.invalid_portable_urls.filter(({ name }) => invalidNames.has(name))) {
    await assert.rejects(
      helper.createPortableOriginProfile({
        instance_id: vectors.portable_instance_id,
        url: item.url,
      }),
      /invalid bootstrap input/,
    );
  }
});


test("ambiguous URLs, IDs, ports, and cross-profile mappings fail closed", async () => {
  for (const item of vectors.invalid_local_inputs) {
    await assert.rejects(
      helper.createLocalOriginProfile(item.input),
      /invalid bootstrap input/,
    );
  }
  for (const item of vectors.invalid_portable_urls) {
    await assert.rejects(
      helper.createPortableOriginProfile({
        instance_id: vectors.portable_instance_id,
        url: item.url,
      }),
      /invalid bootstrap input/,
    );
  }
  const local = vectors.origin_profile_vectors[0].profile;
  await assert.rejects(
    helper.validateOriginProfile({ ...local, mode: "portable_https" }),
    /invalid bootstrap input/,
  );
  await assert.rejects(
    helper.validateOriginProfile({ ...local, raw_capability_b64u: "A".repeat(43) }),
    /invalid bootstrap input/,
  );
  for (const profile of vectors.invalid_origin_profiles) {
    await assert.rejects(
      helper.validateOriginProfile(profile),
      /invalid bootstrap input/,
    );
  }
});


test("configuration never contains the one-time raw capability", async () => {
  const capability = vectors.capability_vectors[0];
  const profile = vectors.origin_profile_vectors[0].profile;
  const config = await helper.buildBootstrapConfiguration({
    profile,
    verifier_b64u: capability.verifier_b64u,
    recovery_epoch: 1,
  });
  assert.deepEqual(Object.keys(config).sort(), [
    "origin_profile",
    "recovery_epoch",
    "verifier_b64u",
  ]);
  assert.equal(JSON.stringify(config).includes(capability.raw_capability_b64u), false);
  assert.equal(JSON.stringify(config).includes("raw_capability"), false);
  await assert.rejects(
    helper.buildBootstrapConfiguration({
      profile,
      verifier_b64u: capability.verifier_b64u,
      recovery_epoch: 2,
    }),
    /invalid bootstrap input/,
  );
});


test("live generator uses fresh 128-bit IDs and a 32-byte capability", async () => {
  const first = await helper.generateBootstrapBundle({ mode: "local_loopback", port: 4183 });
  const second = await helper.generateBootstrapBundle({ mode: "local_loopback", port: 4183 });
  assert.match(first.rawCapabilityB64u, /^[A-Za-z0-9_-]{43}$/);
  assert.equal(helper.strictDecodeB64u32(first.rawCapabilityB64u).length, 32);
  assert.notEqual(first.rawCapabilityB64u, second.rawCapabilityB64u);
  assert.notEqual(first.configuration.origin_profile.instance_id, second.configuration.origin_profile.instance_id);
  assert.match(first.configuration.origin_profile.base_path, /^\/[0-9a-f]{32}\/$/);
  assert.equal(JSON.stringify(first.configuration).includes(first.rawCapabilityB64u), false);
});


test("static helper is offline, secret-minimal, and keyboard-readable", () => {
  assert.equal(
    createHash("sha256").update(html).digest("hex"),
    vectors.bootstrap_helper_sha256,
  );
  for (const forbidden of [
    /<script[^>]+src=/i,
    /<link[^>]+href=/i,
    /\bfetch\s*\(/,
    /\bXMLHttpRequest\b/,
    /\bWebSocket\b/,
    /\bEventSource\b/,
    /\bsendBeacon\b/,
    /\blocalStorage\b/,
    /\bsessionStorage\b/,
    /\bindexedDB\b/,
    /\bcaches\b/,
    /serviceWorker/,
    /\bconsole\s*\./,
    /document\.cookie/,
    /location\s*[.=]/,
    /<form\b/i,
  ]) {
    assert.equal(forbidden.test(html), false, String(forbidden));
  }
  assert.match(html, /<html lang="ko">/);
  assert.match(html, /<meta http-equiv="Content-Security-Policy"/);
  assert.match(html, /connect-src 'none'/);
  assert.match(html, /crypto\.getRandomValues\s*\(/);
  assert.match(html, /crypto\.subtle\.digest\s*\(/);
  assert.doesNotMatch(html, /Math\.random\s*\(/);
  assert.match(html, /<main\b/);
  assert.match(html, /<h1\b/);
  assert.match(html, /<fieldset\b/);
  assert.match(html, /<legend\b/);
  assert.match(html, /<label[^>]+for="deployment-mode"/);
  assert.match(html, /<label[^>]+for="local-port"/);
  assert.match(html, /<label[^>]+for="portable-url"/);
  assert.match(html, /role="status"[^>]+aria-live="polite"/);
  assert.match(html, /id="raw-capability"[^>]+tabindex="0"/);
  assert.match(html, /id="configuration"[^>]+tabindex="0"/);
  assert.match(html, /한 번만/);
});


test("editing deployment inputs invalidates pending and completed secret output", async () => {
  class FakeElement {
    constructor(value = "") {
      this.value = value;
      this.disabled = false;
      this.hidden = false;
      this.textContent = "";
      this.listeners = new Map();
    }

    addEventListener(type, listener) {
      const listeners = this.listeners.get(type) ?? [];
      listeners.push(listener);
      this.listeners.set(type, listeners);
    }

    emit(type) {
      return Promise.all(
        (this.listeners.get(type) ?? []).map((listener) => listener({ type, target: this })),
      );
    }

    focus() {}
  }

  const elements = {
    "deployment-mode": new FakeElement("local_loopback"),
    "local-fields": new FakeElement(),
    "portable-fields": new FakeElement(),
    "local-port": new FakeElement("4183"),
    "portable-url": new FakeElement(""),
    generate: new FakeElement(),
    status: new FakeElement(),
    results: new FakeElement(),
    "raw-capability": new FakeElement(),
    configuration: new FakeElement(),
  };
  const originalDocument = Object.getOwnPropertyDescriptor(globalThis, "document");
  const originalCrypto = Object.getOwnPropertyDescriptor(globalThis, "crypto");
  const originalHelper = globalThis.DeepTwinBootstrap;
  const nativeCrypto = globalThis.crypto;
  let releaseFirstDigest;
  let delayFirstDigest = true;
  const delayedCrypto = {
    getRandomValues: nativeCrypto.getRandomValues.bind(nativeCrypto),
    subtle: {
      digest(...args) {
        if (!delayFirstDigest) return nativeCrypto.subtle.digest(...args);
        delayFirstDigest = false;
        return new Promise((resolve, reject) => {
          releaseFirstDigest = () => nativeCrypto.subtle.digest(...args).then(resolve, reject);
        });
      },
    },
  };

  try {
    Object.defineProperty(globalThis, "document", {
      configurable: true,
      value: { getElementById: (id) => elements[id] },
    });
    Object.defineProperty(globalThis, "crypto", {
      configurable: true,
      value: delayedCrypto,
    });
    const domScript = `${scriptMatch[1]}\n// isolated DOM race harness`;
    await import(`data:text/javascript;base64,${Buffer.from(domScript).toString("base64")}`);

    const pending = elements.generate.emit("click");
    assert.equal(elements["deployment-mode"].disabled, true);
    assert.equal(elements["local-port"].disabled, true);
    assert.equal(elements.generate.disabled, true);

    elements["local-port"].value = "5000";
    await elements["local-port"].emit("input");
    releaseFirstDigest();
    await pending;
    assert.equal(elements.results.hidden, true);
    assert.equal(elements["raw-capability"].textContent, "");
    assert.equal(elements.configuration.textContent, "");

    await elements.generate.emit("click");
    assert.equal(elements.results.hidden, false);
    assert.equal(
      JSON.parse(elements.configuration.textContent).origin_profile.port,
      5000,
    );
    assert.match(elements["raw-capability"].textContent, /^[A-Za-z0-9_-]{43}$/);

    elements["local-port"].value = "5001";
    await elements["local-port"].emit("input");
    assert.equal(elements.results.hidden, true);
    assert.equal(elements["raw-capability"].textContent, "");
    assert.equal(elements.configuration.textContent, "");
  } finally {
    if (originalDocument) Object.defineProperty(globalThis, "document", originalDocument);
    else delete globalThis.document;
    Object.defineProperty(globalThis, "crypto", originalCrypto);
    globalThis.DeepTwinBootstrap = originalHelper;
  }
});
