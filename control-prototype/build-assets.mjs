import { mkdir, lstat, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createHash } from 'node:crypto';
import { ARTIFACTS } from './fixtures.mjs';

const prototypeRoot = path.dirname(fileURLToPath(import.meta.url));
const extensions = { text: 'md', csv: 'csv', svg: 'svg', pdf: 'pdf' };
export const ASSET_FILES = Object.freeze([...Object.values(ARTIFACTS)
  .flatMap(artifact => [artifact.path, ...(artifact.preview ? [artifact.preview] : [])]), 'assets/manifest.json']);
const xml = value => String(value).replace(/[<>&"']/g, character => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;', "'": '&apos;' }[character]));
export function validateAssetPath(relative) {
  if (typeof relative !== 'string' || !/^assets\/[a-z0-9][a-z0-9-]*\.(?:md|csv|svg|pdf|json)$/.test(relative)) {
    throw new Error(`Invalid asset path: ${String(relative)}`);
  }
  return relative;
}
function checkLines(lines) {
  if (!Array.isArray(lines) || !lines.length || lines.length > 45 || lines.some(line => line.length > 76)) {
    throw new Error('PDF page capacity exceeded: at most 45 lines of 76 characters');
  }
  if (lines.some(line => /[^\x20-\x7e]/.test(line))) throw new Error('PDF source must use printable ASCII page lines');
}
export function pdfBytes(lines) {
  checkLines(lines);
  const literal = text => text.replace(/([\\()])/g, '\\$1');
  const stream = `BT\n/F1 11 Tf\n14 TL\n54 736 Td\n${lines.map((line, index) => `${index ? 'T*\n' : ''}(${literal(line)}) Tj`).join('\n')}\nET\n`;
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>',
    `<< /Length ${Buffer.byteLength(stream, 'ascii')} >>\nstream\n${stream}endstream`,
  ];
  let source = '%PDF-1.4\n';
  const offsets = [0];
  for (const [index, object] of objects.entries()) {
    offsets.push(Buffer.byteLength(source, 'ascii'));
    source += `${index + 1} 0 obj\n${object}\nendobj\n`;
  }
  const startxref = Buffer.byteLength(source, 'ascii');
  source += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  source += offsets.slice(1).map(offset => `${String(offset).padStart(10, '0')} 00000 n \n`).join('');
  source += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${startxref}\n%%EOF\n`;
  return Buffer.from(source, 'ascii');
}
export function pagePreview(lines) {
  checkLines(lines);
  return `<svg xmlns="http://www.w3.org/2000/svg" width="612" height="822" viewBox="0 0 612 822" role="img"><title>Derivative preview of a synthetic PDF page</title><rect width="612" height="822" fill="#edf4f3"/><text x="20" y="19" font-family="Arial,sans-serif" font-size="10" fill="#486064">DERIVATIVE PREVIEW - OPEN THE PDF FOR THE ORIGINAL FORMAT</text><g transform="translate(0 30)"><rect width="612" height="792" fill="white" stroke="#bccdca"/>${lines.map((line, index) => `<text x="54" y="${56 + index * 14}" font-family="Courier,monospace" font-size="11" fill="#162b2d" xml:space="preserve">${xml(line)}</text>`).join('')}</g></svg>`;
}
export function renderAssets(artifacts = ARTIFACTS) {
  const files = new Map();
  const entries = [];
  const put = (relative, bytes, sourceArtifact, derivativeOf = null) => {
    validateAssetPath(relative);
    if (files.has(relative)) throw new Error(`Duplicate generated asset: ${relative}`);
    files.set(relative, bytes);
    entries.push({ path: relative, sourceArtifact, derivativeOf, bytes: bytes.length,
      sha256: createHash('sha256').update(bytes).digest('hex') });
  };
  for (const artifact of Object.values(artifacts)) {
    validateAssetPath(artifact.path);
    const extension = extensions[artifact.type];
    if (!extension || path.extname(artifact.path) !== `.${extension}`) throw new Error(`Artifact extension mismatch: ${artifact.id}`);
    if (typeof artifact.body !== 'string') throw new Error(`Artifact body is not text source: ${artifact.id}`);
    if (artifact.type === 'pdf') {
      const lines = artifact.body.split('\n');
      if (!artifact.preview || path.extname(artifact.preview) !== '.svg') throw new Error(`Missing derivative SVG path: ${artifact.id}`);
      put(artifact.path, pdfBytes(lines), artifact.id);
      put(artifact.preview, Buffer.from(pagePreview(lines), 'utf8'), artifact.id, artifact.path);
    } else {
      if (artifact.type === 'svg' && (/<(?:script|foreignObject|iframe|image|use)\b/i.test(artifact.body)
        || /\bon[a-z]+\s*=|\b(?:href|src)\s*=|url\s*\(/i.test(artifact.body))) {
        throw new Error(`Active SVG is forbidden in synthetic fixtures: ${artifact.id}`);
      }
      put(artifact.path, Buffer.from(artifact.body, 'utf8'), artifact.id);
    }
  }
  files.set('assets/manifest.json', Buffer.from(`${JSON.stringify({ synthetic: true,
    description: 'Deterministic UI fixture assets; not actual work, lens or evaluation evidence.', entries }, null, 2)}\n`, 'utf8'));
  return { files, entries };
}
async function statOrNull(target) {
  try { return await lstat(target); }
  catch (error) { if (error.code === 'ENOENT') return null; throw error; }
}
export async function buildAssets() {
  const directory = path.join(prototypeRoot, 'assets');
  const existingDirectory = await statOrNull(directory);
  if (existingDirectory && (!existingDirectory.isDirectory() || existingDirectory.isSymbolicLink())) {
    throw new Error('Refusing a non-directory or symbolic-link assets destination');
  }
  await mkdir(directory, { recursive: false }).catch(error => { if (error.code !== 'EEXIST') throw error; });
  const createdDirectory = await lstat(directory);
  if (!createdDirectory.isDirectory() || createdDirectory.isSymbolicLink()) throw new Error('Refusing changed assets destination');
  const { files } = renderAssets();
  let created = 0;
  let unchanged = 0;
  for (const [relative, bytes] of files) {
    const target = path.join(prototypeRoot, validateAssetPath(relative));
    const existing = await statOrNull(target);
    if (existing) {
      if (!existing.isFile() || existing.isSymbolicLink()) throw new Error(`Refusing non-regular asset: ${relative}`);
      if (!(await readFile(target)).equals(bytes)) throw new Error(`Asset differs; preserve and review before replacing: ${relative}`);
      unchanged += 1;
    } else {
      await writeFile(target, bytes, { flag: 'wx' });
      created += 1;
    }
  }
  return { created, unchanged, total: files.size };
}
if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  buildAssets().then(result => process.stdout.write(`${JSON.stringify(result)}\n`)).catch(error => {
    process.stderr.write(`${error.message}\n`);
    process.exitCode = 1;
  });
}
