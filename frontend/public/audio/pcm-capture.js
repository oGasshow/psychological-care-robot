/* global AudioWorkletProcessor, sampleRate, registerProcessor */
// Average consecutive input samples into mono PCM16 at 16 kHz. Fractional
// positions and partial 20 ms frames are retained across worklet callbacks.
class PcmCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.sum=0;this.weight=0;this.position=0;
    this.frame=new Int16Array(320);this.index=0;this.energy=0;
    this.ratio=sampleRate/16000;
  }
  process(inputs) {
    const channel=inputs[0]?.[0];
    if(!channel)return true;
    for(let i=0;i<channel.length;i++) {
      let rest=1;
      while(rest>1e-9) {
        const take=Math.min(rest,this.ratio-this.position);
        this.sum+=channel[i]*take;this.weight+=take;this.position+=take;rest-=take;
        if(this.position>=this.ratio-1e-9) {
          const value=Math.max(-1,Math.min(1,this.sum/this.weight));
          this.frame[this.index++]=Math.round(value*(value<0?32768:32767));
          this.energy+=value*value;this.sum=0;this.weight=0;this.position=0;
          if(this.index===320) {
            const pcm=this.frame.buffer;
            this.port.postMessage({pcm,level:Math.sqrt(this.energy/320)},[pcm]);
            this.frame=new Int16Array(320);this.index=0;this.energy=0;
          }
        }
      }
    }
    return true;
  }
}
registerProcessor('pcm-capture',PcmCapture);
