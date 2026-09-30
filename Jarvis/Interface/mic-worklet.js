// Processeur audio : regroupe le signal du micro en blocs et les transmet à la page.

const BLOCK = 1024;

class MicCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.block = new Float32Array(BLOCK);
    this.offset = 0;
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel) return true;

    let read = 0;
    while (read < channel.length) {
      const count = Math.min(channel.length - read, BLOCK - this.offset);
      this.block.set(channel.subarray(read, read + count), this.offset);
      this.offset += count;
      read += count;
      if (this.offset === BLOCK) {
        this.port.postMessage(this.block.slice(0));
        this.offset = 0;
      }
    }
    return true;
  }
}

registerProcessor('mic-capture', MicCapture);
