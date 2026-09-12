"""Bounded, local text extraction. Uploaded documents are data, not commands."""

from io import BytesIO
from pathlib import Path, PurePosixPath
import os
import selectors
import shutil
import subprocess
import tempfile
import time
from zipfile import ZipFile

from docx import Document

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TEXT = 20_000
MEDIA_TYPES = {
    'txt': 'text/plain', 'md': 'text/markdown', 'csv': 'text/csv',
    'json': 'application/json',
    'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'pdf': 'application/pdf', 'png': 'image/png', 'jpg': 'image/jpeg',
    'jpeg': 'image/jpeg', 'svg': 'image/svg+xml', 'html': 'text/html',
}


def _result(status, text, note, media_type):
    if len(text) > MAX_TEXT:
        status = 'partial'
        text = text[:MAX_TEXT]
        note += ' 텍스트는 앞 20,000자까지만 읽었습니다.'
    return dict(read_status=status, text=text, read_note=note, media_type=media_type)


def _docx(data, media_type):
    try:
        with ZipFile(BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > 1000 or sum(entry.file_size for entry in entries) > 20 * 1024 * 1024:
                raise ValueError('ZIP size limit')
            for entry in entries:
                path = PurePosixPath(entry.filename)
                if (path.is_absolute() or '..' in path.parts or '\\' in entry.filename
                        or entry.flag_bits & 1
                        or entry.file_size > max(1, entry.compress_size) * 200):
                    raise ValueError('Unsafe ZIP member')
        document = Document(BytesIO(data))
        chunks = []
        for block in document.iter_inner_content():
            if hasattr(block, 'rows'):
                chunks.extend('\t'.join(cell.text for cell in row.cells) for row in block.rows)
            else:
                chunks.append(block.text)
        return _result('partial', '\n'.join(chunks),
                       'DOCX 본문 문단과 표만 읽었습니다. 그림·도형·머리말 등은 해석하지 않았습니다.', media_type)
    except Exception:
        # Parser failures are not evidence that a document was read. Do not
        # expose parser paths or uploaded XML in the user-facing note.
        return _result('unreadable', '', 'DOCX를 안전하게 읽지 못했습니다. 원본은 보관합니다.', media_type)


def _pdf(data, media_type):
    executable = shutil.which('pdftotext')
    if executable is None:
        return _result('unsupported', '', '로컬 pdftotext 도구가 없어 PDF 텍스트를 읽지 않았습니다. OCR도 수행하지 않았습니다.', media_type)
    if not data.startswith(b'%PDF-'):
        return _result('unreadable', '', 'PDF 형식을 확인하지 못했습니다.', media_type)
    try:
        with tempfile.TemporaryDirectory(prefix='deeptwin-pdf-') as folder:
            # A bounded page range and subprocess timeout limit work. The
            # source filename is never used as a filesystem path or argument.
            source = Path(folder) / 'source.pdf'
            source.write_bytes(data)
            with subprocess.Popen(
                [executable, '-f', '1', '-l', '50', '-enc', 'UTF-8', str(source), '-'],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            ) as process:
                output = bytearray()
                deadline = time.monotonic() + 10
                try:
                    with selectors.DefaultSelector() as selector:
                        selector.register(process.stdout, selectors.EVENT_READ)
                        while len(output) < (MAX_TEXT + 1) * 4:
                            remaining = deadline - time.monotonic()
                            if remaining <= 0 or not selector.select(remaining):
                                raise ValueError('PDF extraction timed out')
                            chunk = os.read(process.stdout.fileno(), min(8192, (MAX_TEXT + 1) * 4 - len(output)))
                            if not chunk:
                                if process.wait(timeout=max(0.01, deadline - time.monotonic())):
                                    raise ValueError('PDF extraction failed')
                                break
                            output.extend(chunk)
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.wait()
                # A byte cap may split the final UTF-8 character. Only this
                # deliberately truncated suffix is omitted, never invented.
                text = output.decode('utf-8', errors='ignore')
        if not text.strip():
            return _result('unreadable', '', '추출 가능한 PDF 텍스트가 없습니다. 이미지 OCR은 수행하지 않았습니다.', media_type)
        return _result('partial', text, 'PDF 앞 50쪽의 추출 가능한 텍스트만 읽었습니다. 조판·그림·OCR은 해석하지 않았습니다.', media_type)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return _result('unreadable', '', 'PDF 텍스트를 안전하게 읽지 못했습니다. 원본은 보관합니다.', media_type)


def extract(name, data):
    """Return a truthful, bounded reading result; never execute uploaded content."""
    if not isinstance(name, str) or not isinstance(data, bytes) or len(data) > MAX_FILE_BYTES:
        raise ValueError('Invalid file or file size')
    extension = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
    if extension not in MEDIA_TYPES:
        raise ValueError('Unsupported file extension')
    media_type = MEDIA_TYPES[extension]
    if extension in {'txt', 'md', 'csv', 'json'}:
        try:
            body = data.decode('utf-8')
        except UnicodeDecodeError:
            return _result('unreadable', '', 'UTF-8 텍스트로 읽지 못했습니다. 원본은 보관합니다.', media_type)
        return _result('read', body, 'UTF-8 원문을 읽었습니다. 명령 실행이나 의미 분석은 하지 않았습니다.', media_type)
    if extension == 'docx':
        return _docx(data, media_type)
    if extension == 'pdf':
        return _pdf(data, media_type)
    return _result('unsupported', '', '원본만 보관합니다. 이미지 OCR·HTML/SVG 실행이나 내용 해석은 하지 않았습니다.', media_type)
