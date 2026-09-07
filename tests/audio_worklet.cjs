const vm = require('node:vm');
const fs = require('node:fs');
const assert = require('node:assert/strict');
for (const rate of [16000, 44100, 48000]) {
  let Processor;
  const frames = [];
  const context = {
    sampleRate: rate,
    AudioWorkletProcessor: class {
      constructor() { this.port = {postMessage(data) { frames.push(new Int16Array(data)); }}; }
    },
    registerProcessor(name, p) { Processor = p; }, Int16Array, Math
  };
  vm.runInNewContext(fs.readFileSync('web/pcm-worklet.js', 'utf8'), context);
  const processor = new Processor();
  for (let offset = 0; offset < rate * 2; offset += 128) {
    const input = new Float32Array(Math.min(128, rate * 2 - offset));
    input.fill(.25);
    processor.process([[input]]);
  }
  assert.equal(frames.length, 2);
  assert.equal(frames[0].length, 16000);
  assert.ok(Math.abs(frames[1][15999] - 8192) <= 1);
  console.log(`AudioWorklet ${rate} -> 16000: PASS`);
}
