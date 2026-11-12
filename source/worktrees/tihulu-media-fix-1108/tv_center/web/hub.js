"use strict";
(() => {
const $=id=>document.getElementById(id);
let csrf="",paired=false,lastSerial=-1,source="none",lastImageSid="";
let currentKind="none",clockDelta=0,currentCue=null,cueSequence=-1,timer=null;
let webVtt=null, playerHls=null, lastCaption={original:"",translations:{}};
function error(e){$("status").textContent=e.message||String(e);}
async function api(path,payload=null){
  const began=Date.now();
  const response=await fetch(path,{method:payload===null?"GET":"POST",
    headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},
    body:payload===null?undefined:JSON.stringify(payload),
    cache:"no-store",credentials:"same-origin"});
  const type=response.headers.get("Content-Type")||"";
  if(!type.includes("json"))throw Error("Unexpected host response");
  const data=await response.json();
  if(!response.ok)throw Error(data.error||("HTTP "+response.status));
  if(path==="/api/status"&&Number.isFinite(data.server_epoch_ms)){
    clockDelta=data.server_epoch_ms-(began+Date.now())/2;
  }
  return data;
}
function setPaired(value){
  paired=value;$("login").hidden=value;$("hub-main").hidden=!value;
  $("connection").textContent=value?"PAIRED":"NOT PAIRED";
  $("logout").hidden=!value;
}
function setVideoSource(url){
  const player=$("player");
  if(playerHls){playerHls.destroy();playerHls=null;}
  player.pause();player.removeAttribute("src");player.load();
  if(player.canPlayType("application/vnd.apple.mpegurl")){
    player.src=url;player.load();
  }else if(window.Hls?.isSupported()){
    playerHls=new window.Hls({lowLatencyMode:false,maxBufferLength:24});
    playerHls.loadSource(url);playerHls.attachMedia(player);
    playerHls.on(window.Hls.Events.ERROR,(_,e)=>{
      if(e.fatal)$("playback-state").textContent="Browser HLS error: "+e.type;
    });
  }else{
    $("playback-state").textContent=
      "HLS needs Safari or hls.js-enabled browser. Try phone Safari.";
    return;
  }
  $("picture").hidden=true;player.hidden=false;
  player.play().catch(()=>{$("playback-state").textContent=
    "Tap Play on the phone to enable audio";});
}
function displayImage(url,alt){
  const img=$("picture");img.src=url;img.alt=alt;img.hidden=false;
  $("player").pause();$("player").hidden=true;
}
function drawSources(items,kind){
  const root=$("catalog");root.replaceChildren();
  const applicable=items.filter(x=>kind==="image"?(x.kind==="image"):
    kind==="file"?(x.kind!=="image"):true);
  if(!applicable.length){
    const p=document.createElement("p");
    p.textContent=kind==="dab"?"No verified live DAB services currently available.":
      "No explicitly shared "+kind+" sources available.";
    root.append(p);return;
  }
  for(const item of applicable){
    const row=document.createElement("div");row.className="web-channel-item";
    const name=document.createElement("strong");name.textContent=item.name;
    const button=document.createElement("button");
    button.textContent=kind==="image"?"View picture":"Play on "+$("target").selectedOptions[0].textContent;
    button.onclick=async()=>{
      try{
        if(kind==="image"){
          if($("target").value!=="phone")throw Error("Images are displayed on this paired phone; host image mirroring is unsupported");
          displayImage("/api/image?id="+encodeURIComponent(item.id),item.name);
          $("playback-state").textContent="Approved shared picture: "+item.name;
        }else{
          const result=await api("/api/start",{kind,id:kind==="dab"?item.sid:item.id,
                                              target:$("target").value});
          $("playback-state").textContent=result.status+" · "+(result.note||"");
          if($("target").value!=="host"){
            lastSerial=result.serial;
            setVideoSource("/hls/stream.m3u8?serial="+result.serial);
          }
          if(kind==="dab"){lastImageSid=item.sid;$("refresh-slide").disabled=false;}
          currentKind=kind;
        }
      }catch(e){error(e);}
    };
    row.append(name,button);root.append(row);
  }
}
async function refreshCatalog(){
  if(!paired)return;
  const kind=$("source-type").value;
  try{
    if(kind==="dab"){
      const data=await api("/api/dab");
      drawSources(data.items||[],"dab");
    }else{
      const data=await api("/api/catalog");
      drawSources(data.items||[],"file");
    }
  }catch(e){error(e);}
}
function showCaptions(caption){
  const type=$("subtitle-track").value;
  const original=(type==="translation"||type==="off")?"":String(caption.original||"");
  const translated=(type==="original"||type==="off")?"":Object.entries(caption.translations||{}).
    map(([lang,text])=>"["+lang.toUpperCase()+"] "+String(text)).join("\n");
  lastCaption=caption;
  $("original").textContent=original;
  $("translated").textContent=translated;
  $("overlay-original").textContent=original;
  $("overlay-translated").textContent=translated;
  $("fullscreen-captions").style.display=
    type==="off"||(!original&&!translated)?"none":"";
  if(webVtt)webVtt.mode=type==="off"?"disabled":"showing";
  $("fullscreen-captions").style.background="rgba(0,0,0,"+
    (Number($("caption-opacity").value)/100)+")";
}
function nativeTrack(caption){
  const video=$("player"),type=$("subtitle-track").value;
  if(type==="off")return;
  if(!webVtt){
    try{webVtt=video.addTextTrack("subtitles","TIHULU radio live","en");webVtt.mode="showing";}
    catch(_){return;}
  }
  if(typeof VTTCue==="undefined")return;
  const text=[(type!=="translation"?String(caption.original||""):""),
    (type!=="original"?Object.entries(caption.translations||{}).
      map(([k,v])=>"["+k.toUpperCase()+"] "+v).join("\n"):"")].
    filter(Boolean).join("\n");
  if(!text)return;
  try{
    const cue=new VTTCue(video.currentTime,video.currentTime+4.5,text);
    cue.position=50;cue.line=85;cue.align="middle";
    webVtt.addCue(cue);
    for(const old of Array.from(webVtt.cues||[])){
      if(old.endTime<video.currentTime-2)webVtt.removeCue(old);
    }
  }catch(_){}
}
function mobileLagMs(){
  const video=$("player");
  if(!video.buffered?.length||video.paused)return 0;
  const last=video.buffered.end(video.buffered.length-1);
  return Math.max(0,Math.min(30000,(last-video.currentTime)*1000))+8000;
}
function captionDue(data){
  const mode=$("sync-mode").value;
  const correction=Math.max(-20000,Math.min(20000,(Number($("offset").value)||0)*1000));
  const stamp=Number(data.source_capture_epoch_ms||data.timestamp*1000);
  if(!Number.isFinite(stamp))return Date.now();
  const hostCache=Number(data.host_audio_cache_ms)||0;
  const hostOffset=Number(data.host_caption_offset_ms)||0;
  let due=stamp+hostOffset;
  if(mode==="host")due+=hostCache;
  else if(mode==="mobile")due+=mobileLagMs();
  return due-clockDelta+correction;
}
async function refreshCaptions(){
  if(!paired)return;
  try{
    const data=await api("/api/captions");
    if(!data||!data.original)return;
    const sequence=Number(data.chunk_index);
    if(Number.isFinite(sequence)&&sequence===cueSequence)return;
    const due=captionDue(data),now=Date.now();
    if(due<now-25000)return;
    cueSequence=Number.isFinite(sequence)?sequence:cueSequence+1;
    const apply=()=>{
      if(!paired)return;
      showCaptions(data);
      nativeTrack(data);
      $("caption-source").textContent=(data.source_language||"und").toUpperCase()+
        " · "+(data.sync_note||"HLS A/V latency not calibrated");
    };
    if(timer)clearTimeout(timer);
    timer=setTimeout(apply,Math.max(0,Math.min(45000,due-now)));
  }catch(e){$("caption-source").textContent=e.message;}
}
async function statusCheck(){
  if(!paired)return;
  try{
    const state=await api("/api/status");
    $("status").textContent=state.state+" · "+state.source+
      " · "+(state.playlist_ready?"HLS ready":"awaiting selected stream");
    $("now-playing").textContent=state.source==="none"?
      "Choose a verified stream or approved file":state.source;
    $("capabilities").textContent=state.sync_note||
      "Only host-authorized media is available";
    $("source-info").textContent=
      "One HLS stream is shared by paired devices. Host-only playback does not replace it.";
  }catch(e){error(e);}
}
async function refreshSlide(){
  if(!lastImageSid)return;
  try{
    const query="/api/slide?sid="+encodeURIComponent(lastImageSid)+"&t="+Date.now();
    const response=await fetch(query,{credentials:"same-origin",cache:"no-store"});
    if(!response.ok)throw Error("No actual DAB slideshow image for this service");
    const blob=await response.blob();
    if(!blob.type.startsWith("image/"))throw Error("Invalid slideshow media");
    const url=URL.createObjectURL(blob);
    const image=$("picture");const previous=image.dataset.localUrl;
    image.src=url;image.dataset.localUrl=url;
    image.alt="Current native DAB service slideshow (real welle receiver)";
    // Show actual slideshow artwork while the separate DAB audio player
    // continues running (never pause or fake an image).
    image.classList.add("radio-cover");
    image.hidden=false;
    if(previous)URL.revokeObjectURL(previous);
  }catch(e){$("playback-state").textContent=e.message;}
}
$("logout").onclick=async()=>{
  try{if(paired)await api("/api/disconnect",{});}
  catch(e){error(e);}
  finally{
    csrf="";setPaired(false);
    const player=$("player");player.pause();player.removeAttribute("src");
    if(playerHls){playerHls.destroy();playerHls=null;}
    player.load();$("picture").hidden=true;
    lastImageSid="";lastSerial=-1;
    $("status").textContent="This device is unpaired.";
  }
};
$("pair").onclick=async()=>{
  try{
    const code=$("pin").value.trim();
    if(!/^\d{8}$/.test(code))throw Error("Enter the eight-digit Remote Hub PIN");
    const data=await api("/api/pair",{pin:code});
    csrf=data.csrf;$("pin").value="";
    setPaired(true);await refreshCatalog();await statusCheck();
    setInterval(statusCheck,4000);setInterval(refreshCaptions,1500);
    setInterval(()=>{if(lastImageSid && currentKind==="dab")refreshSlide()},9000);
  }catch(e){$("pair-status").textContent=e.message;}
};
$("source-type").onchange=refreshCatalog;
$("target").onchange=refreshCatalog;
$("catalog-refresh").onclick=refreshCatalog;
$("stop-stream").onclick=async()=>{
  try{await api("/api/stop",{});$("player").pause();
      $("player").removeAttribute("src");$("player").load();
      $("playback-state").textContent="Phone HLS encoder stopped on host.";}
  catch(e){error(e);}
};
for(const button of document.querySelectorAll("[data-cmd]")){
  button.onclick=async()=>{
    try{await api("/api/control",{action:button.dataset.cmd});
      $("command-state").textContent=button.dataset.cmd+" command accepted by host";}
    catch(e){$("command-state").textContent=e.message;}
  };
}
$("set-volume").onclick=async()=>{
  try{await api("/api/control",{action:"VolumeSet",value:Number($("volume").value)});
      $("command-state").textContent="Volume command sent to host";}catch(e){error(e);}
};
$("tune-tv").onclick=async()=>{
  try{await api("/api/control",{action:"TVChannel",channel:$("tvchannel").value.trim()});
      $("command-state").textContent="Native TV channel requested on host (no remote DVB video)";}
  catch(e){error(e);}
};
$("fullscreen").onclick=async()=>{
  try{
    if($("fullscreen-stage").requestFullscreen){
      await $("fullscreen-stage").requestFullscreen();
    }else if($("player").webkitEnterFullscreen){
      if(!webVtt)nativeTrack({original:"",translations:{}});
      $("player").webkitEnterFullscreen();
    }else throw Error("Fullscreen is unavailable");
  }catch(e){
    try{
      if($("player").webkitEnterFullscreen){
        if(!webVtt)nativeTrack({original:"",translations:{}});
        $("player").webkitEnterFullscreen();
      }else throw e;
    }catch(error){$("playback-state").textContent=error.message;}
  }
};
$("refresh-slide").onclick=refreshSlide;
$("subtitle-track").onchange=()=>showCaptions(lastCaption);
$("caption-opacity").oninput=()=>{$("fullscreen-captions").style.background=
  "rgba(0,0,0,"+Number($("caption-opacity").value)/100+")"};
$("offset").onchange=refreshCaptions;
$("sync-mode").onchange=refreshCaptions;
})();
