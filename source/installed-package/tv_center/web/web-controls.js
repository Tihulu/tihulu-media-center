/* PIN-paired native DVB receiver management, without simulated RF readings.
   The standalone Kaffeine caption sidecar cannot scan; never display a
   functional-looking scan button unless the native Qt WebCommandQueue answers. */
"use strict";
(() => {
  const root=document.getElementById("web-control-root");
  if(!root)return;
  const html=[
    '<section class="panel" id="web-service-panel">',
    '<div class="web-panel-heading"><h2>Scanned TV / radio channels</h2>',
    '<button id="web-refresh" class="secondary">Refresh</button></div>',
    '<p id="web-channel-origin" class="muted">Pair with a native DVB receiver to load real services.</p>',
    '<label for="web-filter">Channel filter</label>',
    '<select id="web-filter"><option value="all">All scanned</option>',
    '<option value="included">Included</option><option value="favorite">★ Favorites</option>',
    '<option value="new">New services</option><option value="tv">Television</option>',
    '<option value="radio">Radio</option></select>',
    '<div id="web-channel-list" class="web-channel-list" aria-live="polite"></div>',
    '<p id="web-channel-msg" role="status"></p></section>',
    '<section class="panel" id="web-scan-panel">',
    '<div class="web-panel-heading"><h2>Automatic DVB channel scan</h2>',
    '<span id="web-receiver-badge" class="web-inline-status">Not connected</span></div>',
    '<p class="muted">A real Linux DVB frontend is required. Scanning temporarily owns the',
    ' selected receiver; saved channels and favorites remain untouched if a scan fails.</p>',
    '<div class="web-scan-grid">',
    '<label class="web-scan-field" id="web-country-field">Country',
    '<select id="web-country"><option value="DE">Germany</option><option value="TR">Türkiye</option></select></label>',
    '<label class="web-scan-field">Receiver type',
    '<select id="web-medium"><option value="t">Antenna · DVB-T/T2</option>',
    '<option value="c">Cable · DVB-C</option>',
    '<option value="s">Satellite dish · DVB-S/S2</option></select></label>',
    '<label class="web-scan-field" id="web-satellite-field" hidden>Satellite position',
    '<select id="web-satellite"><option value="S42E0">Türksat 42°E</option>',
    '<option value="S13E0">Hot Bird 13°E</option>',
    '<option value="S19E2">Astra 19.2°E</option>',
    '<option value="S7E0">Eutelsat 7°E</option></select></label>',
    '<label class="web-scan-field" id="web-diseqc-field" hidden>LNB / DiSEqC input',
    '<select id="web-diseqc"><option value="direct">Direct LNB (no switch)</option>',
    '<option value="0">Port 1</option><option value="1">Port 2</option>',
    '<option value="2">Port 3</option><option value="3">Port 4</option></select></label>',
    '</div>',
    '<p id="web-profile-note" class="muted"></p>',
    '<div id="web-hardware" class="web-receiver-summary" role="status">Checking actual frontend…</div>',
    '<div class="actions wrap">',
    '<button id="web-scan-start" disabled>Start real scan</button>',
    '<button id="web-scan-cancel" class="secondary" disabled>Cancel scan</button>',
    '<button id="web-measure" class="secondary" disabled>Measure signal</button>',
    '<button id="web-stop" class="secondary" disabled>Stop playback / release tuner</button>',
    '</div>',
    '<div class="web-scan-progress">',
    '<progress id="web-scan-progress" hidden aria-label="Indeterminate real RF scan progress"></progress>',
    '<p id="web-scan-state" role="status">No scan requested.</p>',
    '<p id="web-scan-detail" class="muted">No frequency measured yet.</p>',
    '<p id="web-signal" class="muted">No active signal measurement.</p></div>',
    '<details id="web-scan-events" open><summary>Live scan log (<span id="web-scan-log-count">0</span>)</summary>',
    '<div class="web-channel-log" id="web-scan-log" aria-live="off"></div></details>',
    '</section>',
    '<section class="panel" id="web-native-ai">',
    '<h2>Host subtitles and model status</h2>',
    '<p id="web-model-info" class="muted">Waiting for native model status.</p>',
    '<div class="control-inline"><label>Caption mode',
    '<select id="web-caption-mode"><option value="off">Off</option>',
    '<option value="teletext">Broadcast Teletext</option>',
    '<option value="page">Teletext page</option>',
    '<option value="asr">Native offline Whisper</option>',
    '<option value="auto">Teletext → Whisper fallback</option></select></label>',
    '<button id="web-caption-set" disabled>Apply on host</button></div></section>'
  ].join("");
  root.innerHTML=html;
  const $=id=>document.getElementById(id);
  const api=()=>window.tihuluTVWeb;
  const show=(id,value)=>{const node=$(id);if(node)node.textContent=String(value??"");};
  const make=(tag,text,cls)=>{
    const e=document.createElement(tag);e.textContent=String(text??"");
    if(cls)e.className=cls;return e;
  };
  let advancedAvailable=false,connected=false,busyChannels=false;
  let channels=[],scanData=null,editProfile=false,requestInFlight=false;
  let currentProfile="",lastEventSignature="";
  const cleanError=error=>String(error?.message||error||"Unknown failure");
  async function command(action,params={}){
    if(!api()?.connected())throw Error("Pair with a live native DVB host first");
    return api().command(action,params);
  }
  function useNativeBridge(value,reason=""){
    advancedAvailable=value;
    $("web-scan-panel").hidden=!value;
    $("web-service-panel").hidden=!value;
    $("web-native-ai").hidden=!value;
    let notice=$("web-native-unavailable");
    if(!notice){
      notice=make("section","","panel");
      notice.id="web-native-unavailable";
      const title=make("h2","Native receiver connection");
      const body=make("p",
        "Full RF scanning and signal telemetry require the legacy Qt TV Center "+
        "native bridge (tihulu-tv-center legacy-player), not the Kaffeine "+
        "subtitle sidecar or a static GitHub Pages preview. "+
        "Pair with the right running host to enable actual controls.");
      const detail=make("p","","muted");detail.id="web-native-reason";
      notice.append(title,body,detail);
      root.prepend(notice);
    }
    notice.hidden=value;
    show("web-native-reason",reason||"Waiting for an authenticated native DVB connection.");
  }
  function deliveryUi(){
    const medium=$("web-medium").value, sat=medium==="s";
    $("web-satellite-field").hidden=!sat;
    $("web-diseqc-field").hidden=!sat;
    $("web-country-field").hidden=false;
    show("web-profile-note",sat?
      "Satellite scan uses the chosen orbital position and real DVB-S/S2 tuner; "+
      "country only organizes the saved channel profile. Select your actual LNB input.":
      medium==="c"?
      "Cable scan uses the country's DVB-C frequency plan. Satellite/LNB settings do not apply.":
      "Terrestrial DVB-T/T2 scan uses the selected country's frequency plan. "+
      "Satellite/LNB settings do not apply.");
  }
  function syncProfile(data){
    if(editProfile)return;
    for(const [name,key] of [["web-country","country"],["web-medium","medium"],
      ["web-satellite","satellite"]]){
      const node=$(name),value=data[key];
      if(!node||document.activeElement===node)continue;
      if([...node.options].some(o=>o.value===String(value)))node.value=String(value);
    }
    if(data.diseqc_port===null||Number.isInteger(data.diseqc_port))
      $("web-diseqc").value=data.diseqc_port===null?"direct":String(data.diseqc_port);
    deliveryUi();
  }
  function displayReceiver(data){
    const present=data.frontend_present===true;
    const adapters=Array.isArray(data.adapters)?data.adapters:[];
    const dep=data.scanning_dependencies||{};
    const missing=Object.entries(dep).filter(([name,installed])=>!installed)
                                .map(([name])=>name);
    const busy=data.busy===true,running=data.running===true;
    const ready=present&&!busy&&!running&&missing.length===0;
    show("web-receiver-badge",running?"Scanning":
      present?(busy?"In use":"Receiver detected"):"No DVB frontend");
    show("web-hardware","Active adapter: "+(Number.isInteger(data.selected_adapter)?
         data.selected_adapter:"not reported")+" · "+
         (present?("Kernel frontend: "+data.frontend):
          "No /dev/dvb/.../frontend0 for this adapter")+
         " · Detected adapters: "+(adapters.length?adapters.join(", "):"none")+
         (missing.length?" · Missing: "+missing.join(", "):"")+
         (busy?" · Tuner busy playing TV":""));
    $("web-scan-start").disabled=!ready||requestInFlight;
    $("web-scan-cancel").disabled=!running||requestInFlight;
    $("web-stop").disabled=!busy||running||requestInFlight;
    $("web-measure").disabled=!busy||running||requestInFlight;
    const reason=!present?"Plug in a supported DVB receiver and verify Linux firmware/driver.":
      missing.length?"Install missing host utilities: "+missing.join(", "):
      busy?"Stop host TV playback before full scan; signal can be measured on tuned channel.":
      running?"Scan owns the frontend. A second signal monitor cannot read it reliably.":
      "Receiver ready for a real frequency sweep.";
    show("web-scan-detail",reason);
  }
  function drawChannels(){
    const filter=$("web-filter").value;
    const chosen=channels.filter(c=>filter==="all"||
      (filter==="included"&&c.included)||(filter==="favorite"&&c.favorite)||
      (filter==="new"&&c.new)||c.kind===filter);
    const list=$("web-channel-list");list.replaceChildren();
    if(!chosen.length){
      list.append(make("p","No real scanned channels match the current filter."));
      return;
    }
    for(const c of chosen){
      const item=make("div","","web-channel-item");
      item.append(make("div",(c.favorite?"★ ":"")+c.name+" · "+c.kind+
        (c.encrypted?" · encrypted":"")+(c.new?" · NEW":"")));
      const buttons=make("div","","actions");
      for(const [label,operation] of [
        ["▶ Watch","play"],[c.favorite?"★ Unfavorite":"☆ Favorite","favorite"],
        [c.included?"− Remove from list":"+ Include","included"],
        ["Move up","up"],["Move down","down"]]){
        const btn=make("button",label,"secondary");
        btn.onclick=async()=>{
          btn.disabled=true;
          try{
            if(operation==="play"){
              if(!c.included)throw Error("Include the channel before tuning");
              await command("play",{key:c.key});
              show("web-channel-msg","Native tuning requested: "+c.name);
            }else{
              await command("channel_update",{key:c.key,operation});
              await refreshChannels();
              show("web-channel-msg","Saved: "+c.name);
            }
          }catch(error){show("web-channel-msg",cleanError(error));}
          finally{btn.disabled=false;}
        };
        buttons.append(btn);
      }
      item.append(buttons);list.append(item);
    }
  }
  async function refreshChannels(){
    if(!connected||!advancedAvailable||busyChannels)return;
    busyChannels=true;
    try{
      const data=await api().get("/api/channels");
      if(data.backend!=="native_tv_center"){
        useNativeBridge(false,"No native channel controller is attached to this pairing.");
        return;
      }
      channels=Array.isArray(data.channels)?data.channels:[];
      currentProfile=data.profile||"";
      show("web-channel-origin",currentProfile+" · "+channels.length+
        " saved services (not evidence of current RF lock)");
      syncProfile(data);drawChannels();
    }catch(error){
      show("web-channel-msg","Channel list: "+cleanError(error));
    }finally{busyChannels=false;}
  }
  function summarizeEvent(event){
    if(!event||typeof event!=="object")return null;
    const type=String(event.kind||"status");
    const stage=event.stage===undefined?"":("Step "+String(event.stage)+" · ");
    if(type==="frequency")return stage+"Tuning "+String(event.frequency||"frequency unknown");
    if(type==="found")return stage+"Service "+String(event.channel||"unknown")+
      " · "+String(event.frequency||"")+ " · count "+String(event.count||"");
    if(type==="signal"){
      const m=event.metrics||{};
      return "Signal monitor: "+(m.available?"reported by driver":
        String(m.reason||"unavailable while scanner owns the tuner"));
    }
    if(type==="failed")return "Scan failed: "+String(event.text||"");
    if(type==="complete")return "Scan finished: "+String(event.text||event.count||"");
    return stage+String(event.text||event.channel||event.kind||"");
  }
  function drawScanEvents(events){
    const source=(Array.isArray(events)?events:[]).slice(-80);
    const signature=JSON.stringify(source);
    if(signature===lastEventSignature)return;
    lastEventSignature=signature;
    const panel=$("web-scan-log");panel.replaceChildren();
    for(const item of source){
      const summary=summarizeEvent(item);
      if(summary)panel.append(make("div",summary));
    }
    show("web-scan-log-count",panel.children.length);
    panel.scrollTop=panel.scrollHeight;
  }
  async function refreshScan(){
    if(!connected||!advancedAvailable)return;
    try{
      const data=await api().get("/api/scan");
      if(data.backend!=="native_tv_center"){
        useNativeBridge(false,"No native DVB scan backend responded.");
        return;
      }
      scanData=data;
      syncProfile(data);
      displayReceiver(data);
      $("web-scan-progress").hidden=!data.running;
      const events=data.events||[];
      const latest=events.length?events[events.length-1]:null;
      const headline=(data.running?"SCANNING · ":"Idle · ")+
        (latest?.kind==="failed"?"Scan failed · ":"")+
        (data.status||"");
      show("web-scan-state",headline);
      const detail=data.last_event||latest;
      if(detail?.kind==="frequency")show("web-scan-detail",
        "Real frequency: "+detail.frequency+" · services "+(data.discovered_services||0));
      else if(detail?.kind==="found")show("web-scan-detail",
        "Found "+(data.discovered_services||0)+" services · latest "+(detail.channel||""));
      show("web-signal",data.running?
        "C/N/UCB: not measured during scanning — scanner exclusively owns the frontend.":
        (data.signal||"Tune a service, then request an actual signal measurement."));
      drawScanEvents(events);
    }catch(error){
      show("web-scan-state","Scan status unavailable: "+cleanError(error));
    }
  }
  async function refreshModels(){
    if(!connected||!advancedAvailable)return;
    try{
      const data=await api().get("/api/models");
      show("web-model-info","Host ASR "+(data.asr_enabled?"ON":"OFF")+
        " · translation "+(data.translation_enabled?"ON":"OFF")+
        " · "+(data.backend||"unknown backend")+
        " · installed "+(Array.isArray(data.models)?data.models.length:0)+
        " model(s). Add/remove packages in desktop Settings.");
      $("web-caption-set").disabled=false;
    }catch(error){show("web-model-info",cleanError(error));}
  }
  async function action(commandName,params={},target="web-scan-state"){
    try{
      requestInFlight=true;
      if(scanData)displayReceiver(scanData);
      const response=await command(commandName,params);
      show(target,response?.note||JSON.stringify(response));
      await refreshScan();
      if(commandName==="scan_start"||commandName==="stop")await refreshChannels();
      return response;
    }catch(error){
      show(target,cleanError(error));return null;
    }finally{
      requestInFlight=false;
      if(scanData)displayReceiver(scanData);
    }
  }
  for(const id of ["web-medium","web-country","web-satellite","web-diseqc"]){
    $(id).onchange=()=>{editProfile=true;deliveryUi();};
  }
  deliveryUi();
  // Do not show a deceptive RF scan form on unpaired static/GitHub Pages.
  // The panel becomes visible only after a real native Qt bridge answers.
  useNativeBridge(false,"No native DVB scan bridge has been verified yet.");
  $("web-filter").onchange=drawChannels;
  $("web-refresh").onclick=refreshChannels;
  $("web-stop").onclick=async()=>{
    if(!window.confirm("Stop native TV and release its tuner?"))return;
    await action("stop",{},"web-channel-msg");
  };
  $("web-scan-start").onclick=async()=>{
    const medium=$("web-medium").value;
    const params={country:$("web-country").value,medium};
    if(medium==="s"){
      params.satellite=$("web-satellite").value;
      params.diseqc_port=$("web-diseqc").value==="direct"?null:Number($("web-diseqc").value);
    }
    if(!window.confirm("Start REAL "+(medium==="s"?"satellite":medium==="c"?"cable":"terrestrial")+
       " DVB scan on host? It needs exclusive access. Existing channels are preserved if no services are found."))return;
    editProfile=false;
    await action("scan_start",params);
  };
  $("web-scan-cancel").onclick=()=>action("scan_cancel",{});
  $("web-measure").onclick=()=>action("measure_signal",{},"web-signal");
  $("web-caption-set").onclick=()=>action(
    "set_captions",{mode:$("web-caption-mode").value},"web-model-info");
  async function activate(){
    if(!api()?.connected())return;
    if(connected&&advancedAvailable)return;
    connected=true;
    try{
      const data=await api().get("/api/channels");
      if(data.backend!=="native_tv_center"){
        useNativeBridge(false,"The current pairing does not expose live native scans.");
        return;
      }
      useNativeBridge(true);
      channels=Array.isArray(data.channels)?data.channels:[];
      currentProfile=data.profile||"";
      syncProfile(data);drawChannels();
      await Promise.all([refreshScan(),refreshModels()]);
    }catch(error){
      useNativeBridge(false,cleanError(error));
    }
  }
  setInterval(()=>{
    if(connected&&advancedAvailable)refreshScan();
  },2500);
  setInterval(()=>{
    if(connected&&advancedAvailable){refreshChannels();refreshModels();}
  },9000);
  document.addEventListener("tihulu-tv-connected",activate);
  if(api()?.connected())activate();
})();
