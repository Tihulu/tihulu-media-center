/* Opt-in browser ASR and translation. Inference remains on this device.
   Model assets load from Hugging Face only after explicit user action. */
let pipelineFn = null;
let speech = null;
let speechId = "";
let translatePipes = new Map();
const MODEL = {
  tiny: "onnx-community/whisper-tiny",
  small: "onnx-community/whisper-small",
};
const PAIRS = {
  "de-en": "Xenova/opus-mt-de-en",
  "en-de": "Xenova/opus-mt-en-de",
  "tr-en": "Xenova/opus-mt-tr-en",
  "en-tr": "R4kSo1997/opus-mt-en-tr-onnx-int8"
};
const emit = (type, data={}) => postMessage({type, ...data});
async function library() {
  if (!pipelineFn) {
    const lib = await import("https://cdn.jsdelivr.net/npm/@huggingface/transformers@3.8.1");
    pipelineFn = lib.pipeline;
    lib.env.useBrowserCache = true;
    lib.env.allowRemoteModels = true;
  }
  return pipelineFn;
}
async function loadSpeech(model, backend) {
  if (!MODEL[model]) throw Error("Unknown approved speech model");
  if (!["webgpu","wasm"].includes(backend)) throw Error("Unsupported inference backend");
  const id = MODEL[model] + ":" + backend;
  if (speech && speechId === id) return;
  const p = await library();
  if (speech?.dispose) await speech.dispose();
  speech = null;
  speechId = "";
  emit("progress", {text:"Downloading / loading " + MODEL[model] + " (" + backend + ")..."});
  speech = await p("automatic-speech-recognition", MODEL[model], {
    device:backend,
    dtype:"q8",
    progress_callback:x => {
      if (x.status === "progress") emit("progress", {
        text:x.file + ": " + Math.round(x.progress || 0) + "%"
      });
    }
  });
  speechId = id;
  emit("ready", {text:"Speech model ready: " + MODEL[model] + " · " + backend});
}
async function loadTranslator(from,to) {
  const k = from + "-" + to;
  if (!PAIRS[k]) throw Error("No verified browser model available for "+k+
                            "; use the host Argos engine instead");
  if (!translatePipes.has(k)) {
    const p = await library();
    emit("progress", {text:"Loading offline translation " + k + "..."});
    translatePipes.set(k, await p("translation", PAIRS[k], {
      device:"wasm", dtype:"q8",
      progress_callback:x => {
        if (x.status === "progress") emit("progress", {
          text:x.file + ": " + Math.round(x.progress||0) + "%"
        });
      }
    }));
  }
  return translatePipes.get(k);
}
async function translateText(text,from,to) {
  if (from === to) return text;
  const route = from !== "en" && to !== "en" ? [from,"en",to] : [from,to];
  let translated = text;
  for (let i=0;i<route.length-1;i++) {
    const pipe = await loadTranslator(route[i],route[i+1]);
    const result = await pipe(translated,{max_new_tokens:200});
    translated = result[0]?.translation_text || "";
    if (!translated) throw Error("Translation produced no output");
  }
  return translated;
}
onmessage = async ({data}) => {
  const {id,action} = data;
  try {
    if (action === "load") {
      await loadSpeech(data.model,data.backend);
      emit("result", {id, action,ok:true});
    } else if (action === "speech") {
      if (!speech) throw Error("Install/load a Whisper model first");
      const sound = new Float32Array(data.pcm);
      const result = await speech(sound,{
        language:data.language,task:"transcribe",
        chunk_length_s:20,return_timestamps:false
      });
      emit("result", {id,action,text:result.text?.trim()||""});
    } else if (action === "translate") {
      const text = await translateText(data.text,data.from,data.to);
      emit("result", {id,action,text});
    } else if (action === "unload") {
      if (speech?.dispose) await speech.dispose();
      for (const p of translatePipes.values()) if (p.dispose) await p.dispose();
      speech=null; speechId=""; translatePipes.clear();
      emit("result",{id,action,ok:true});
    } else {
      throw Error("Unknown browser AI operation");
    }
  } catch(err) {
    emit("result",{id,action,error:String(err.message||err).slice(0,400)});
  }
};
