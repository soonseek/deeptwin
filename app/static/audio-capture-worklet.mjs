// A continuous area-average resampler keeps native device rates out of the API.
// Only 20ms PCM frames leave this worklet; microphone audio is never played back.
class PCM16Capture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / 16000;
    this.weight = 0;
    this.sum = 0;
    this.offset = 0;
    this.energy = 0;
    this.frame = new ArrayBuffer(640);
    this.view = new DataView(this.frame);
  }

  process(inputs, outputs) {
    for (const output of outputs) for (const channel of output) channel.fill(0);
    const channels = inputs[0];
    if (!channels?.length) return true;
    for (let index = 0; index < channels[0].length; index++) {
      let value = 0;
      for (const channel of channels) value += channel[index] || 0;
      value /= channels.length;
      let remaining = 1;
      while (remaining > 1e-10) {
        const take = Math.min(remaining, this.ratio - this.weight);
        this.sum += value * take;
        this.weight += take;
        remaining -= take;
        if (this.weight >= this.ratio - 1e-9) {
          const sample = Math.max(-1, Math.min(1, this.sum / this.ratio));
          this.view.setInt16(this.offset * 2, Math.round(sample * (sample < 0 ? 32768 : 32767)), true);
          this.energy += sample * sample;
          this.offset++;
          this.weight = 0; this.sum = 0;
          if (this.offset === 320) {
            this.port.postMessage({ pcm: this.frame, rms: Math.sqrt(this.energy / 320) }, [this.frame]);
            this.frame = new ArrayBuffer(640);
            this.view = new DataView(this.frame);
            this.offset = 0; this.energy = 0;
          }
        }
      }
    }
    return true;
  }
}

registerProcessor('deeptwin-pcm16-capture', PCM16Capture);
