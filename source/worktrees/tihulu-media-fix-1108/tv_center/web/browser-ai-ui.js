/* Web AI controller. No model or microphone starts without a click. */
const el = id => document.getElementById(id);
let worker = null, nextId = 0, pending = new Map(), active = false;
let stream = null, audio = null, source = null, processor = null, sink = null;
let segments = [], samples = 0, processing = false, loaded = false;
const LANG = {de:"german",en:"english",tr:"turkish"};
const setStatus = t => {el("browser-ai-status").textContent=t};
function rpc(action, payload={}, transfers=[]) {
  if (!worker) throw Error("Browser AI worker is unloaded");
  const id=++nextId;
  return new Promise((resolve,reject)=>{
    pending.set(id,{resolve,reject});
    worker.postMessage({id,action,...payload},transfers);
  });
}
function ensureWorker() {
  if (worker) return;
  worker = new Worker(new URL("./browser-ai-worker.js",import.meta.url),{type:"module"});
  worker.onmessage = ({data})=>{
    if (data.type==="progress" || data.type==="ready") return setStatus(data.text);
    if (data.type!=="result") return;
    const job=pending.get(data.id);
    if (!job) return;
    pending.delete(data.id);
    if (data.error) job.reject(Error(data.error));
    else job.resolve(data);
  };
  worker.onerror = e => setStatus("AI worker failed: "+e.message+
      ". Check CDN, GPU and model compatibility.");
}
function resample(samples, sampleRate, targetRate=16000) {
  const length=Math.max(1,Math.floor(samples.length * targetRate / sampleRate));
  const out=new Float32Array(length);
  const ratio=sampleRate/targetRate;
  for (let i=0;i<length;i++) {
    const at=i*ratio, left=Math.floor(at), frac=at-left;
    out[i]=(samples[left]||0)*(1-frac)+(samples[left+1]||0)*frac;
  }
  return out;
}
async function processChunk(chunks,originalRate) {
  if (processing) return;
  processing=true;
  try {
    const len=chunks.reduce((acc,x)=>acc+x.length,0);
    const joined=new Float32Array(len);
    let at=0;
    for (const chunk of chunks) {joined.set(chunk,at);at+=chunk.length;}
    const pcm=resample(joined,originalRate);
    setStatus("Transcribing "+(joined.length/originalRate).toFixed(1)+" seconds locally...");
    const response=await rpc("speech",{pcm:pcm.buffer,language:LANG[el("browser-source-lang").value]},[pcm.buffer]);
    if (response.text) {
      el("browser-ai-original").textContent=response.text;
      el("browser-ai-caption").textContent="Whisper · "+el("browser-backend").value;
      if (el("browser-translation-toggle").checked) {
        const from=el("browser-source-lang").value,to=el("browser-target-lang").value;
        if (from===to) el("browser-ai-translated").textContent=response.text;
        else {
          try {
            const tr=await rpc("translate",{text:response.text,from,to});
            el("browser-ai-translated").textContent=tr.text;
          } catch(err) {
            el("browser-ai-translated").textContent="Translation unavailable: "+err.message;
          }
        }
      } else el("browser-ai-translated").textContent="";
    }
    setStatus("Listening; next chunk is recorded locally");
  } catch(err) {setStatus("Inference error: "+err.message);}
  finally {processing=false;}
}
function stop() {
  active=false;
  if (processor) {processor.disconnect();processor.onaudioprocess=null;processor=null;}
  if (source) {source.disconnect();source=null;}
  if (sink) {sink.disconnect();sink=null;}
  if (stream) {stream.getTracks().forEach(t=>t.stop());stream=null;}
  if (audio) {audio.close().catch(()=>{});audio=null;}
  segments=[];samples=0;
  el("browser-ai-stop").disabled=true;
  el("browser-ai-mic").disabled=!loaded;
  el("browser-ai-tab").disabled=!loaded;
  setStatus("Audio capture stopped; model remains cached/loaded");
}
async function capture(type) {
  if (!loaded) throw Error("Load model before starting audio capture");
  if (!navigator.mediaDevices) throw Error("Audio capture requires a secure browser context");
  stop();
  const raw=type==="mic" ?
    await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:false},video:false}) :
    await navigator.mediaDevices.getDisplayMedia({audio:true,video:true,systemAudio:"include"});
  if (!raw.getAudioTracks().length) {
    raw.getTracks().forEach(t=>t.stop());
    throw Error("The chosen tab/window did not provide an audio track");
  }
  stream=raw;
  for (const t of stream.getTracks()) t.onended=()=>{if(active)stop()};
  audio=new AudioContext();
  await audio.resume();
  source=audio.createMediaStreamSource(stream);
  processor=audio.createScriptProcessor(4096,1,1);
  sink=audio.createGain();sink.gain.value=0;
  source.connect(processor);processor.connect(sink);sink.connect(audio.destination);
  processor.onaudioprocess=event=>{
    if(!active) return;
    const pcm=Float32Array.from(event.inputBuffer.getChannelData(0));
    // Keep at most 12 seconds queued while the previous inference runs.
    if(processing && samples > audio.sampleRate * 12) {segments=[];samples=0;}
    segments.push(pcm);samples+=pcm.length;
    if(samples>=audio.sampleRate*10 && !processing) {
      const batch=segments;segments=[];samples=0;
      processChunk(batch,audio.sampleRate);
    }
  };
  active=true;
  el("browser-ai-stop").disabled=false;
  el("browser-ai-mic").disabled=true;
  el("browser-ai-tab").disabled=true;
  setStatus("Capturing "+type+" audio; 10-second Whisper windows. Raw sound stays in-browser.");
}
el("browser-ai-load").onclick=async()=>{
  el("browser-ai-load").disabled=true;
  try {
    ensureWorker();
    const backend=el("browser-backend").value==="auto"
      ? (navigator.gpu && await navigator.gpu.requestAdapter() ? "webgpu":"wasm")
      :el("browser-backend").value;
    await rpc("load",{model:el("browser-model").value,backend});
    loaded=true;
    el("browser-ai-mic").disabled=false;
    el("browser-ai-tab").disabled=false;
    setStatus("Model ready ("+backend+"). Choose mic or shared-tab audio.");
  }catch(err){setStatus("Model load failed: "+err.message);}
  finally{el("browser-ai-load").disabled=false;}
};
for (const [name,type] of [["browser-ai-mic","mic"],["browser-ai-tab","tab"]]) {
  el(name).onclick=()=>capture(type).catch(err=>setStatus("Audio capture unavailable: "+err.message));
}
el("browser-ai-stop").onclick=stop;
el("browser-ai-release").onclick=async()=>{
  stop();loaded=false;
  el("browser-ai-mic").disabled=true;el("browser-ai-tab").disabled=true;
  if(worker){worker.terminate();worker=null;}
  for(const job of pending.values())job.reject(Error("Model unloaded"));
  pending.clear();
  setStatus("Browser inference engine unloaded from memory. Cached model files remain.");
};
el("browser-ai-cache").onclick=async()=>{
  if(!confirm("Delete cached Transformers.js model assets for this site? This may affect other features served from the same GitHub Pages origin."))return;
  stop();
  if(worker){worker.terminate();worker=null;}
  pending.clear();loaded=false;
  let removed=0;
  if("caches" in window){
    const keys=await caches.keys();
    for(const name of keys.filter(x=>/transformers/i.test(x))){
      if(await caches.delete(name))removed++;
    }
  }
  setStatus("Removed "+removed+" Transformers.js caches. Other models may reside in browser site storage; clear site data if needed.");
};
window.addEventListener("pagehide",stop);
