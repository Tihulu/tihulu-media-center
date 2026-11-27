"use strict";
// TIHULU paired native DVB remote: no simulated channel, clock or recording.
(() => {
  const $ = id => document.getElementById(id);
  let connected = false, loading = false, ticker = null, playerHls = null;
  let selectedSource = "dvb", serverClockDelta = 0;
  let seen = new Set(), pending = [], active = null;
  let nativeTrack = null, lastCaptionText = "";
  let currentlyPlayingHls = false;
  const allowedSource = new Set(["dvb", "captions"]);
  const get = async path => {
    const start = Date.now();
    const response = await fetch(path,{credentials:"same-origin",cache:"no-store"});
    const data = await response.json();
    if(!response.ok) throw Error(data.error || "HTTP " + response.status);
    if(path === "/api/status" && typeof data.server_epoch_ms === "number") {
      serverClockDelta = data.server_epoch_ms - (start + Date.now()) / 2;
    }
    return data;
  };
  const send = async (url, obj) => {
    const response = await fetch(url,{method:"POST",credentials:"same-origin",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify(obj),cache:"no-store"});
    const data = await response.json();
    if(!response.ok) throw Error(data.error || "HTTP "+response.status);
    return data;
  };
  const setEnabled = (enabled) => {
    for(const id of ["leave","start-video","stop-video","fullscreen",
        "open-page","apply-target","apply-source","enable-host-stream","disable-host-stream","host-play","host-pause",
        "host-stop","host-prev","host-next","set-host-volume","mute-host","tune-tv",
        "desktop-apply-mode","desktop-apply-offset","desktop-apply-buffer",
        "desktop-captions-start","desktop-captions-stop"]){
      if($(id)) $(id).disabled = !enabled;
    }
    $("pair").disabled=enabled;
    $("start-video").disabled = true; $("stop-video").disabled = !enabled || !currentlyPlayingHls;
    $("fullscreen").disabled = !enabled;
  };
  function resetTimeline(){
    pending=[];seen.clear();active=null;
    updateOverlay();
    if(connected)refresh();
  }
  const stopClient = () => {
    if(playerHls){playerHls.destroy();playerHls=null;}
    const video=$("tv");video.pause();video.removeAttribute("src");video.load();
    const wasPlaying=currentlyPlayingHls;
    currentlyPlayingHls=false;
    $("stop-video").disabled=true;
    if(wasPlaying)resetTimeline();
  };
  function disconnect(){
    connected=false;
    if(ticker){clearInterval(ticker);ticker=null;}
    stopClient();setEnabled(false);
    seen.clear();pending=[];active=null;
    $("state").textContent="NOT PAIRED";
    $("caption-status").textContent="";
    $("fullscreen-captions").style.display="none";
    $("video-status").textContent="Pairing required";
  }
  const showError = (error) => {
    $("host-feedback").textContent = String(error?.message || error);
  };
  function initTextTrack(){
    const video=$("tv");
    if(nativeTrack)return nativeTrack;
    try {
      nativeTrack=video.addTextTrack("subtitles","TIHULU live captions","en");
      nativeTrack.mode="showing";
    } catch(error) {
      $("latency-state").textContent="Native phone video text track unavailable: "+
        error.message + ". Keep the video container in fullscreen.";
    }
    return nativeTrack;
  }
  function composedCaption(caption){
    const choice=$("subtitle-display").value;
    if(choice==="off")return "";
    const original=choice==="translation"?"":String(caption.original||"");
    const translated=choice==="original"?"":String(caption.translated||"");
    return [original,translated].filter(Boolean).join("\n");
  }
  function clearExpiredTrack(){
    if(!nativeTrack || !nativeTrack.cues)return;
    const video=$("tv");
    for(const cue of Array.from(nativeTrack.cues)){
      if(cue.endTime < video.currentTime-2){
        try{nativeTrack.removeCue(cue)}catch(_){}
      }
    }
  }
  function addNativeCue(item,seconds){
    if(!currentlyPlayingHls || !item?.caption)return;
    const track=initTextTrack();
    if(!track || typeof VTTCue==="undefined")return;
    const content=composedCaption(item.caption);
    if(!content)return;
    const video=$("tv");
    const start=Math.max(0,video.currentTime+Math.max(0,seconds));
    const end=start+Math.min(8,Math.max(2.4,item.duration||4));
    try{
      const cue=new VTTCue(start,end,content);
      cue.line=88;cue.position=50;cue.align="middle";
      track.addCue(cue);
      clearExpiredTrack();
    }catch(_){}
  }
  function hlsLagEstimateMs(){
    const video=$("tv");
    if(!currentlyPlayingHls)return 0;
    if(!video.buffered || !video.buffered.length)return 6500;
    const last=video.buffered.end(video.buffered.length-1);
    if(!Number.isFinite(last)||!Number.isFinite(video.currentTime))return 0;
    // The buffered tail is behind the encoder's live edge. Include two
    // nominal HLS segments: approximate, NOT verified broadcast PTS.
    return Math.max(0,Math.min(30000,(last-video.currentTime)*1000))+4000;
  }
  function cueTime(item){
    const t=item.timing||{}, mode=$("sync-mode").value;
    const manual=Math.max(-20000,Math.min(20000,
      (Number($("phone-offset").value)||0)*1000));
    let due=t.host_caption_due_epoch_ms;
    if(typeof due!=="number")return null;
    if(mode==="manual"){
      due=(t.capture_end_epoch_ms??due)+500;
    }else if(mode==="mobile" && currentlyPlayingHls){
      // Important: mobile HLS receives TS BEFORE desktop's libVLC delay.
      // Do not add 15 seconds again. Prefer the actually confirmed delay.
      if(t.host_buffer_verified && Number.isFinite(t.host_effective_buffer_ms))
        due-=t.host_effective_buffer_ms;
      else if(Number.isFinite(t.capture_end_epoch_ms))
        due=t.capture_end_epoch_ms+500+(t.host_caption_offset_ms||0);
      due+=hlsLagEstimateMs();
    }
    return due-serverClockDelta+manual;
  }
  function scheduleEvents(data){
    const now=Date.now();
    for(const event of data.caption_events||[]){
      if(!event || !Number.isInteger(event.sequence) || seen.has(event.sequence))continue;
      seen.add(event.sequence);
      const due=cueTime(event);
      if(due===null)continue;
      if(due<now-16000)continue; // Never surface stale caption after resuming.
      const t=event.timing||{};
      const duration=(Number(t.cue_expiry_epoch_ms)-Number(t.host_caption_due_epoch_ms))/1000;
      pending.push({...event,due,
        duration: Number.isFinite(duration)?Math.max(2,Math.min(8,duration)):4});
    }
    if(seen.size>250)seen=new Set([...seen].slice(-90));
    pending.sort((a,b)=>a.due-b.due);
    pending=pending.slice(-48);
  }
  function displayEvent(event){
    active={...event,until:Date.now()+Math.max(2400,event.duration*1000)};
    const c=event.caption||{};
    $("original").textContent=c.original||"";
    $("translated").textContent=c.translated||"";
    $("caption-source").textContent=(c.source_language||"und").toUpperCase()+
      " · "+(c.source||"Whisper/Teletext");
    updateOverlay();
  }
  function updateOverlay(){
    const source=active?.caption||{},choice=$("subtitle-display").value;
    $("overlay-original").textContent=choice==="translation"||choice==="off"?
      "":(source.original||"");
    $("overlay-translated").textContent=choice==="original"||choice==="off"?
      "":(source.translated||"");
    $("fullscreen-captions").style.display=
      choice==="off"||(!$("overlay-original").textContent &&
                       !$("overlay-translated").textContent)?"none":"";
    if(nativeTrack)nativeTrack.mode=choice==="off"?"disabled":"showing";
    $("fullscreen-captions").style.background="rgba(0,0,0,"+
       (Number($("caption-opacity").value)/100)+")";
  }
  function tickCaptions(){
    const now=Date.now();
    while(pending.length && pending[0].due<=now){
      const next=pending.shift();
      if(next.due<now-12000)continue;
      displayEvent(next);
      addNativeCue(next,0);
    }
    if(active && now>active.until){
      active=null;
      $("original").textContent="Listening for the next phrase…";
      $("translated").textContent="";
      updateOverlay();
    }
  }
  async function refresh(){
    if(!connected||loading)return;
    loading=true;
    try{
      const state=await get("/api/status");
      $("channel").textContent=state.channel||"No TV channel tuned";
      $("source").textContent=state.source==="live_native_dvb"?
        "Current tuned native DVB service; receiver remains on the host.":
        "No active DVB transport stream from host";
      $("state").textContent=state.mobile_video?"MOBILE STREAM":"PAIRED";
      if(document.activeElement!==$("play-target"))
        $("play-target").value=state.playback_target||"phone";
      const services=state.mobile_sources||[];
      const selector=$("media-source");
      const signature=JSON.stringify(services.map(x=>[x.id,x.label,x.available]));
      if(selector.dataset.signature!==signature){
        const previous=selectedSource;
        selector.replaceChildren();
        for(const source of services){
          if(!allowedSource.has(source.id))continue;
          const option=document.createElement("option");
          option.value=source.id;
          option.textContent=source.label+(source.available?"":" · offline");
          option.disabled=!source.available;
          selector.append(option);
        }
        selectedSource=allowedSource.has(previous)?previous:"dvb";
        if(![...selector.options].some(o=>o.value===selectedSource&&!o.disabled))
          selectedSource="captions";
        selector.value=selectedSource;
        selector.dataset.signature=signature;
      }
      if(document.activeElement===selector)selectedSource=selector.value;
      const actual=services.find(s=>s.id===selectedSource);
      $("source-capabilities").textContent=actual?.reason||
        "Host tuning remains local. Phone HLS and caption-only are separate modes.";
      $("start-video").disabled=!state.mobile_video || selectedSource!=="dvb";
      $("enable-host-stream").disabled=state.mobile_video || state.source!=="live_native_dvb";
      $("disable-host-stream").disabled=!state.mobile_video;
      $("stop-video").disabled=!currentlyPlayingHls;
      const desktop=state.desktop_caption_settings||{};
      if(desktop.mode && document.activeElement!==$("desktop-caption-mode"))
        $("desktop-caption-mode").value=desktop.mode;
      if(document.activeElement!==$("desktop-offset"))
        $("desktop-offset").value=((desktop.offset_ms||0)/1000).toFixed(2);
      if(document.activeElement!==$("desktop-buffer"))
        $("desktop-buffer").value=((desktop.requested_buffer_ms||0)/1000).toFixed(1);
      const t=state.caption_timing||{};
      const host=t.host_effective_buffer_ms;
      $("host-latency").textContent=t.host_buffer_verified?
        "Computer: "+(host/1000).toFixed(1)+" s verified MPEG-TS buffer; "
          +(Number(t.host_caption_offset_ms)/1000).toFixed(2)+" s caption offset.":
        "Computer requested "+((t.host_requested_buffer_ms||0)/1000).toFixed(1)+
          " s buffer; native applied delay not yet verified.";
      $("video-status").textContent=state.mobile_video?
        "Host HLS ready; tap Watch live TV. Fullscreen captions available.":
        "Phone HLS is OFF or no valid DVB source is active. Host must enable streaming.";
      scheduleEvents(state);
      $("latency-state").textContent=$("sync-mode").value==="mobile"?
        "Phone HLS estimated playback lag: "+(hlsLagEstimateMs()/1000).toFixed(1)+
        " s · not PTS-calibrated; use fine-tune when needed.":
        $("sync-mode").value==="host"?
        "Using verified desktop caption schedule, independent of phone media buffer.":
        "Manual mode uses audio capture end and your phone-only delay.";
      $("caption-status").textContent=state.stream_disclaimer||"";
    }catch(e){
      $("pair-note").textContent=e.message;
      if(/401|expired|pair/i.test(e.message))disconnect();
    }finally{loading=false;}
  }
  async function invoke(action,params={},label=""){
    try{
      const result=(await send("/api/command",{action,params})).result;
      $("host-feedback").textContent=(label||action)+" · "+
        (result?.note||"Command accepted");
      await refresh();
      return result;
    }catch(e){showError(e);throw e;}
  }
  $("pair").onclick=async()=>{
    try{
      await send("/api/pair",{pin:$("pin").value.trim()});
      $("pin").value="";connected=true;setEnabled(true);
      await refresh();
      ticker=setInterval(refresh,1200);
      document.dispatchEvent(new Event("tihulu-tv-connected"));
    }catch(e){$("pair-note").textContent=e.message;}
  };
  $("leave").onclick=async()=>{
    try{if(connected)await send("/api/disconnect",{});}
    catch(e){$("pair-note").textContent="Could not revoke session: "+e.message;}
    finally{disconnect();}
  };
  function watchVideo(){
    const video=$("tv"),url="/hls/index.m3u8";
    if(playerHls){playerHls.destroy();playerHls=null;}
    if(video.canPlayType("application/vnd.apple.mpegurl")){
      video.src=url;video.load();
    }else if(window.Hls?.isSupported()){
      playerHls=new window.Hls({lowLatencyMode:false,maxBufferLength:24});
      playerHls.loadSource(url);
      playerHls.attachMedia(video);
      playerHls.on(window.Hls.Events.ERROR,(_,err)=>{
        if(err.fatal)$("video-status").textContent=
          "HLS playback error: "+err.type+" (check source, codec and signal)";
      });
    }else{
      $("video-status").textContent=
        "This browser cannot play the host's HLS stream; try Safari or a browser with hls.js.";
      return;
    }
    currentlyPlayingHls=true;
    initTextTrack();
    // Rebase queued host-timed captions against the phone's own HLS clock,
    // rather than carrying over 15-second desktop deadlines.
    resetTimeline();
    $("stop-video").disabled=false;
    $("video-status").textContent="Playing host stream with phone caption sync";
    video.play().catch(()=>{$("video-status").textContent=
      "Tap the video Play button to enable audio on this phone.";});
  }
  $("enable-host-stream").onclick=async()=>{
    try{
      await invoke("video",{enabled:true},"Host phone-stream encoder");
      await refresh();
    }catch(_){}
  };
  $("disable-host-stream").onclick=async()=>{
    try{
      stopClient();
      await invoke("video",{enabled:false},"Host phone-stream encoder");
      await refresh();
    }catch(_){}
  };
  $("start-video").onclick=watchVideo;
  $("stop-video").onclick=stopClient;
  $("fullscreen").onclick=async()=>{
    const stage=$("fullscreen-stage"),video=$("tv");
    try{
      if(stage.requestFullscreen)await stage.requestFullscreen();
      else if(video.webkitEnterFullscreen){
        initTextTrack();video.webkitEnterFullscreen();
      }else throw Error("Fullscreen not supported in this browser");
    }catch(e){
      // Some iPhone Safari versions expose requestFullscreen but reject
      // non-video elements. Keep real subtitles as a native WebVTT track.
      try{
        if(video.webkitEnterFullscreen){initTextTrack();video.webkitEnterFullscreen();}
        else throw e;
      }catch(error){$("video-status").textContent="Fullscreen: "+error.message;}
    }
  };
  $("subtitle-display").onchange=updateOverlay;
  $("caption-opacity").oninput=updateOverlay;
  $("sync-mode").onchange=()=>{pending=[];seen.clear();active=null;refresh();};
  $("phone-offset").onchange=()=>{pending=[];seen.clear();active=null;refresh();};
  $("desktop-apply-mode").onclick=()=>invoke(
    "set_desktop_caption_mode",{mode:$("desktop-caption-mode").value},
    "Native subtitle mode").catch(()=>{});
  $("desktop-apply-offset").onclick=()=>{
    const n=Math.round(Number($("desktop-offset").value)*1000);
    if(!Number.isInteger(n)||n<-10000||n>10000)return;
    invoke("set_desktop_caption_offset",{offset_ms:n},
      "Native caption offset").catch(()=>{});
  };
  $("desktop-apply-buffer").onclick=()=>{
    const n=Math.round(Number($("desktop-buffer").value)*1000);
    if(!Number.isInteger(n)||n<0||n>20000)return;
    invoke("set_desktop_tv_buffer",{buffer_ms:n},
      "Native TV buffer (pending acknowledgement)").catch(()=>{});
  };
  $("desktop-captions-start").onclick=()=>invoke(
    "desktop_subtitles_running",{running:true},"Desktop captions").catch(()=>{});
  $("desktop-captions-stop").onclick=()=>invoke(
    "desktop_subtitles_running",{running:false},"Desktop captions").catch(()=>{});
  $("apply-target").onclick=async()=>{
    try{
      const target=$("play-target").value;
      await invoke("player_target",{target},"Playback target");
      if(target==="host"){stopClient();}
      else if(selectedSource==="dvb" && !$("start-video").disabled)watchVideo();
    }catch(_){}
  };
  $("media-source").onchange=()=>{selectedSource=$("media-source").value;};
  $("apply-source").onclick=()=>{
    selectedSource=$("media-source").value;
    if(selectedSource==="captions")stopClient();
    $("caption-only-stage").hidden=selectedSource!=="captions";
    $("tv").hidden=selectedSource==="captions";
    refresh();
  };
  for(const [id,action] of [["host-play","play"],["host-pause","pause"],
     ["host-stop","stop"],["host-next","next"],["host-prev","previous"]]){
    $(id).onclick=()=>invoke(action,{},action).catch(()=>{});
  }
  $("set-host-volume").onclick=()=>invoke(
    "volume",{value:Number($("host-volume").value)},"Volume").catch(()=>{});
  $("mute-host").onclick=async()=>{
    try{
      await invoke("volume",{value:0},"Host audio muted");
      $("host-volume").value=0;
      $("host-feedback").textContent=
        "Computer audio muted. The native tuner must remain running to "+
        "feed phone TV; restore volume with the slider if desired.";
    }catch(_){}
  };
  $("tune-tv").onclick=()=>invoke(
    "tv_channel",{channel:$("tv-channel").value.trim()},"Tune TV").catch(()=>{});
  $("open-page").onclick=async()=>{
    const page=Number($("page").value);
    if(!Number.isInteger(page)||page<100||page>899)return;
    try{await send("/api/teletext",{page});
      $("teletext-result").textContent="Requested native Teletext page "+page;}
    catch(e){$("teletext-result").textContent=e.message;}
  };
  document.querySelectorAll("[data-page]").forEach(btn=>btn.onclick=()=>{
    $("page").value=btn.dataset.page;
    if(connected)$("open-page").click();
  });
  window.tihuluTVWeb={
    connected:()=>connected,
    get,
    command:async(action,params)=>{
      return (await send("/api/command",{action,params})).result;
    }
  };
  setInterval(tickCaptions,180);
  // A valid HttpOnly cookie may survive browser refresh; only host validates.
  connected=true;
  refresh().then(()=>{
    if(connected){
      setEnabled(true);
      ticker=setInterval(refresh,1200);
      document.dispatchEvent(new Event("tihulu-tv-connected"));
    }else disconnect();
  });
})();
