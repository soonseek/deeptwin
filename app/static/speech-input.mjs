// Capture stays in browser memory. Only bounded PCM windows go to the instance-owned speech endpoint.
export function createSpeechInput({ api, getWork, saveWork, canStart, appendText }) {
  const panel = document.querySelector('#speech-input');
  const toggle = document.querySelector('#speech-toggle');
  const cancelButton = document.querySelector('#speech-cancel');
  const status = document.querySelector('#speech-status');
  const provisional = document.querySelector('#speech-provisional');
  let ready = false;
  let run = null;
  let state = 'idle';
  let flushing = false;
  let generation = 0;
  let recovery = Promise.resolve(true);
  const closeWarning = '마이크는 꺼졌습니다. 서버의 음성 입력 종료는 확인하지 못했습니다.';

  function display(next, message) {
    state = next;
    panel.dataset.state = next;
    status.textContent = message;
    updateControls();
  }

  function updateControls() {
    panel.dataset.ready = String(ready);
    toggle.textContent = state === 'recording' ? '음성 입력 중지' : state === 'finishing' ? '마지막 말을 정리하는 중…' : '말로 입력';
    toggle.disabled = state === 'starting' || state === 'finishing' || (state !== 'recording' && (!ready || !canStart()));
    toggle.setAttribute('aria-pressed', String(state === 'recording'));
    cancelButton.hidden = !run;
  }

  function live(r) { return run === r && !r.cancelled && getWork()?.id === r.workId; }
  function stopCapture(r) {
    r.capturing = false;
    if (r.processor) r.processor.port.onmessage = null;
    for (const track of r.stream?.getTracks() || []) { track.onended = null; track.stop(); }
    r.source?.disconnect(); r.processor?.disconnect();
    if (r.context && r.context.state !== 'closed') void r.context.close().catch(() => {});
  }
  async function closeSession(r) {
    if (!r.session) return true;
    if (!r.closePromise) r.closePromise = api(`/api/speech/sessions/${encodeURIComponent(r.session.id)}/close`, { method: 'POST', body: {} }).then(() => true, () => false);
    return r.closePromise;
  }

  function cancel(message = '음성 입력을 취소했습니다. 이미 넣은 글은 그대로 남아 있습니다.') {
    const r = run;
    if (!r) return;
    r.cancelled = true;
    stopCapture(r);
    r.frames = []; r.pre = []; r.finals = []; r.interim = null; r.texts = [];
    provisional.textContent = '';
    run = null;
    display('idle', message);
    recovery = closeSession(r);
    void recovery.then(closed => { if (!closed && generation === r.generation && !run) status.textContent = closeWarning; });
  }

  function fail(r, error) {
    if (run !== r) return;
    stopCapture(r);
    r.cancelled = true;
    r.frames = []; r.pre = []; r.finals = []; r.interim = null;
    // Keep any confirmed-but-not-inserted text visible for manual recovery.
    provisional.textContent = r.texts.map(item => item.text).join('\n');
    run = null;
    const message = error?.name === 'NotAllowedError' ? '마이크 권한을 허용하지 않았습니다. 입력한 글은 그대로 남아 있습니다.'
      : error?.message || '음성 입력을 마치지 못했습니다. 입력한 글은 그대로 남아 있습니다.';
    display('error', message);
    recovery = closeSession(r);
  }

  function showPending(r) {
    if (!live(r)) return;
    provisional.textContent = r.texts.length ? r.texts.map(item => item.text).join('\n') : r.preview;
  }
  function flushPending() {
    const r = run;
    if (!r || !live(r) || flushing) return;
    flushing = true;
    try {
      while (r.texts.length && appendText(r.texts[0].text, r.workId)) r.texts.shift();
    } finally { flushing = false; }
    showPending(r);
    if (r.texts.length) status.textContent = '입력을 마치면 음성으로 쓴 글을 넣습니다. 길이가 넘치면 아래 글을 따로 옮겨 주세요.';
    void finishIfDrained(r);
  }

  async function finishIfDrained(r) {
    if (!live(r) || state !== 'finishing' || r.capturing || r.inFlight || r.finals.length || r.texts.length || r.finishing) return;
    r.finishing = true;
    const closed = await closeSession(r);
    if (!live(r)) return;
    run = null;
    provisional.textContent = '';
    display('idle', closed ? '음성 입력을 마쳤습니다. 잘못 들은 글은 업무 설명에서 고쳐 주세요.' : closeWarning);
  }

  function pcm(frames) {
    // Short voiced tails are padded to the endpoint's 250ms minimum.
    const bytes = new Uint8Array(Math.max(8000, frames.length * 640));
    frames.forEach((frame, index) => bytes.set(new Uint8Array(frame), index * 640));
    return bytes.buffer;
  }

  function finalize(r) {
    if (!r.frames.length) return;
    if (r.voiced >= 8) r.finals.push({ utterance: r.utterance, final: true, body: pcm(r.frames) });
    r.frames = []; r.pre = []; r.voiced = 0; r.silence = 0; r.interim = null; r.preview = '';
    r.utterance++;
    showPending(r);
    // At most two final windows can wait behind the one active request.
    if (r.finals.length >= 2 || r.texts.length >= 2) {
      stopCapture(r);
      display('finishing', '음성을 정리하는 데 시간이 걸려 마이크를 잠시 껐습니다. 마지막 말을 정리하고 있습니다.');
    }
    void drain(r);
  }

  function frame(r, data) {
    if (!live(r) || !r.capturing || !(data.pcm instanceof ArrayBuffer) || data.pcm.byteLength !== 640) return;
    const voiced = Number.isFinite(data.rms) && data.rms >= .015;
    if (!r.frames.length) {
      if (!voiced) { r.pre.push(data.pcm); if (r.pre.length > 10) r.pre.shift(); return; }
      r.frames = r.pre.splice(0);
    }
    r.frames.push(data.pcm);
    if (voiced) { r.voiced++; r.silence = 0; } else r.silence++;
    if (r.silence >= 35 || r.frames.length >= 300) finalize(r);
    else if (r.frames.length % 100 === 0 && r.voiced >= 8) {
      r.interim = { utterance: r.utterance, final: false, body: pcm(r.frames) };
      void drain(r);
    }
  }

  async function drain(r) {
    if (!live(r) || r.inFlight) return;
    const job = r.finals.shift() || r.interim;
    if (!job) { void finishIfDrained(r); return; }
    if (!job.final) r.interim = null;
    r.inFlight = true;
    const sequence = ++r.sequence;
    try {
      const path = `/api/speech/sessions/${encodeURIComponent(r.session.id)}/chunks?sequence=${sequence}&utterance=${job.utterance}&final=${job.final}`;
      let result;
      try { result = await api(path, { method: 'POST', raw: true, contentType: 'audio/pcm', body: job.body }); }
      catch (error) {
        // A lost response retries the identical sequence and bytes once; HTTP rejection does not.
        if (error.status || !live(r)) throw error;
        result = await api(path, { method: 'POST', raw: true, contentType: 'audio/pcm', body: job.body });
      }
      if (!live(r)) return;
      const keys = ['elapsed_ms', 'engine', 'final', 'language', 'model', 'sequence', 'session_id', 'text', 'utterance', 'work_id'];
      if (!result || typeof result !== 'object' || Array.isArray(result)
        || Object.keys(result).sort().join('\0') !== keys.join('\0')
        || result.session_id !== r.session.id || result.work_id !== r.workId || result.sequence !== sequence
        || result.utterance !== job.utterance || result.final !== job.final || typeof result.text !== 'string'
        || result.text.length > 20000 || result.engine !== 'whisper.cpp' || result.model !== 'base'
        || result.language !== 'ko' || !Number.isInteger(result.elapsed_ms) || result.elapsed_ms < 0) throw new Error('음성 입력 응답을 확인하지 못했습니다. 기존 입력은 유지했습니다.');
      if (job.final && !r.committed.has(job.utterance)) {
        r.committed.add(job.utterance);
        if (result.text.trim()) r.texts.push({ text: result.text });
        flushPending();
      } else if (!job.final && job.utterance === r.utterance && r.capturing) {
        r.preview = result.text; showPending(r);
      }
      if (sequence >= 120 && r.capturing) stop();
    } catch (error) { if (live(r)) fail(r, error); }
    finally { r.inFlight = false; if (live(r)) void drain(r); }
  }

  function stop() {
    const r = run;
    if (!r || !live(r) || !r.capturing) return;
    stopCapture(r); // Track shutdown must precede all network completion waits.
    display('finishing', '마이크를 껐습니다. 마지막 말을 정리하고 있습니다.');
    r.interim = null;
    finalize(r);
    void drain(r);
  }

  async function start() {
    if (run || !ready || !canStart() || document.hidden) return;
    const r = { generation: ++generation, cancelled: false, capturing: false, frames: [], pre: [], voiced: 0, silence: 0,
      finals: [], interim: null, inFlight: false, texts: [], preview: '', utterance: 1, sequence: 0, committed: new Set() };
    run = r;
    provisional.textContent = '';
    display('starting', '마이크를 준비하고 있습니다…');
    try {
      if (!await recovery) throw new Error(closeWarning);
      if (run !== r || r.cancelled) return;
      if (!navigator.mediaDevices?.getUserMedia || !window.AudioContext || !window.AudioWorkletNode) throw new Error('이 브라우저에서는 음성 입력을 사용할 수 없습니다. 글로 입력해 주세요.');
      r.stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true }, video: false });
      if (run !== r || r.cancelled) { stopCapture(r); return; }
      const work = await saveWork();
      if (run !== r || r.cancelled) { stopCapture(r); return; }
      if (!work) throw new Error('업무를 저장하지 못해 음성 입력을 시작하지 않았습니다.');
      r.workId = work.id;
      r.session = await api('/api/speech/sessions', { method: 'POST', body: { work_id: work.id, revision: work.revision } });
      if (!r.session || typeof r.session !== 'object' || Array.isArray(r.session)
        || Object.keys(r.session).sort().join('\0') !== ['id', 'revision', 'status', 'work_id'].join('\0')
        || typeof r.session.id !== 'string' || !r.session.id || r.session.work_id !== work.id
        || r.session.revision !== work.revision || r.session.status !== 'active') throw new Error('음성 입력 세션 응답을 확인하지 못했습니다. 기존 입력은 유지했습니다.');
      if (!live(r)) { stopCapture(r); void closeSession(r); return; }
      r.context = new AudioContext();
      await r.context.audioWorklet.addModule('/audio-capture-worklet.mjs');
      if (!live(r)) return;
      r.source = r.context.createMediaStreamSource(r.stream);
      r.processor = new AudioWorkletNode(r.context, 'deeptwin-pcm16-capture');
      r.processor.port.onmessage = event => frame(r, event.data);
      r.source.connect(r.processor); r.processor.connect(r.context.destination);
      await r.context.resume();
      if (!live(r)) { stopCapture(r); return; }
      r.capturing = true;
      for (const track of r.stream.getTracks()) track.onended = stop;
      display('recording', '듣고 있습니다 · 잠시 멈추면 글로 넣습니다.');
    } catch (error) { if (run === r) fail(r, error); }
  }

  async function load() {
    try {
      const info = await api('/api/speech');
      ready = info?.ready === true && info.engine === 'whisper.cpp' && info.model === 'base' && info.language === 'ko';
      const message = info?.ready === true && !ready
        ? 'DeepTwin 인스턴스의 음성 입력 정보를 확인하지 못했습니다. 마이크 음성은 보내지 않습니다.'
        : info?.message || '음성 입력을 준비 중입니다.';
      if (!run) display('idle', ready ? '브라우저가 마이크 음성을 받고, DeepTwin 인스턴스가 글로 바꿉니다.' : message);
    } catch { ready = false; display('error', '음성 입력 상태를 확인하지 못했습니다. 글로 입력할 수 있습니다.'); }
    updateControls();
  }
  toggle.addEventListener('click', () => { if (state === 'recording') stop(); else void start(); });
  cancelButton.addEventListener('click', () => cancel());
  return { load, cancel, updateControls, flushPending };
}
