/* Live channels and scan controls; authenticated native DVB bridge only. */
(() => {
  const root=document.getElementById("web-control-root");
  if(!root)return;
  root.innerHTML=[
   '<section class="panel"><h2>Real TV / Radio Channels · Favorites</h2>',
   '<p id="web-channel-origin">Connect to a real native DVB receiver.</p>',
   '<div class="actions"><select id="web-filter"><option value="all">All scanned</option><option value="included">Included</option><option value="favorite">Favorites</option><option value="new">New services</option><option value="tv">TV</option><option value="radio">Radio</option></select><button id="web-refresh">Refresh</button></div>',
   '<div id="web-channel-list" class="web-channel-list"><p>No receiver connected.</p></div><p id="web-channel-msg" role="status"></p></section>',
   '<section class="panel"><h2>Automatic DVB full scan · Live telemetry</h2>',
   '<p>Real RF sweep, frequency/service log and receiver C/N/UCB when available. An antenna and native DVB frontend are required.</p>',
   '<label>Country</label><select id="web-country"><option value="DE">Germany</option><option value="TR">Türkiye</option></select>',
   '<label>Delivery</label><select id="web-medium"><option value="t">Antenna DVB-T/T2</option><option value="c">Cable DVB-C</option><option value="s">Dish DVB-S/S2</option></select>',
   '<label>Satellite</label><select id="web-satellite"><option value="S42E0">Türksat 42°E</option><option value="S13E0">Hot Bird 13°E</option><option value="S19E2">Astra 19.2°E</option><option value="S7E0">Eutelsat 7°E</option></select>',
   '<div class="actions"><button id="web-scan-start">Start full scan</button><button id="web-scan-cancel">Cancel scan</button><button id="web-stop">Stop tuner</button></div>',
   '<p id="web-scan-state">Not scanning.</p><p id="web-signal">Signal metrics unavailable.</p><div class="web-channel-log" id="web-scan-log"></div></section>',
   '<section class="panel"><h2>Native subtitles and AI models</h2>',
   '<p id="web-model-info">The native model market is optional. Browser AI Studio has independent local models.</p>',
   '<div class="actions"><select id="web-caption-mode"><option value="off">Off</option><option value="teletext">Teletext subtitles</option><option value="page">Teletext page</option><option value="asr">Native Whisper ASR</option><option value="auto">Teletext → ASR fallback</option></select>',
   '<button id="web-caption-set">Set subtitle mode</button></div></section>'
  ].join("");
  const $=id=>document.getElementById(id);
  const conn=()=>window.tihuluTVWeb;
  const show=(id,value)=>{$(id).textContent=value};
  let channels=[],busy=false,advancedAvailable=true;
  const make=(tag,value,cls)=>{
    const n=document.createElement(tag);n.textContent=value||"";if(cls)n.className=cls;return n;
  };
  async function cmd(action,params){
    if(!conn()?.connected())throw Error("Connect or pair with native TV first");
    return conn().command(action,params||{});
  }
  async function refreshChannels(){
    if(!conn()?.connected()||busy||!advancedAvailable)return;
    busy=true;
    try{
      const data=await conn().get("/api/channels");
      channels=data.channels||[];
      show("web-channel-origin",(data.profile||"")+
        " · "+channels.length+" genuinely scanned services");
      $("web-country").value=data.country||"DE";
      $("web-medium").value=data.medium||"t";
      $("web-satellite").value=data.satellite||"S42E0";
      draw();
    }catch(e){
      if(/native.*bridge|native.*control|not available from.*sidecar|unavailable/i.test(e.message)){
        advancedAvailable=false;
        // Unlike the previous UI, do NOT render unusable scan/receiver
        // controls when paired only with the caption sidecar. The real
        // host playback/volume/tuning controls are shown above instead.
        root.replaceChildren();
        const panel=make("section","","panel");
        panel.append(make("h2","Advanced native DVB management"));
        panel.append(make("p",
          "This pairing is attached to the caption service. A native DVB control bridge "+
          "for full scan, channel favorites and receiver diagnostics is not available "+
          "in this session; use the main computer window. Host playback controls above "+
          "remain available through D-Bus."));
        root.append(panel);
      }else show("web-channel-msg","Channel lookup: "+e.message);
    }
    finally{busy=false;}
  }
  function draw(){
    const f=$("web-filter").value;
    const selected=channels.filter(c=>f==="all"||(f==="included"&&c.included)||
      (f==="favorite"&&c.favorite)||(f==="new"&&c.new)||f===c.kind);
    const list=$("web-channel-list");list.replaceChildren();
    if(!selected.length){list.append(make("p","No matching real DVB services."));return;}
    for(const c of selected){
      const item=make("div","","web-channel-item");
      item.append(make("div",(c.favorite?"★ ":"")+c.name+" · "+c.kind+
        (c.encrypted?" · encrypted":"")+(c.new?" · NEW":"")));
      const actions=make("div","","actions");
      for(const [text,operation] of [["▶ Watch","play"],[c.favorite?"★ Remove favorite":"☆ Favorite","favorite"],
                                     [c.included?"− Remove":"+ Include","included"],["↑","up"],["↓","down"]]){
        const button=make("button",text,"secondary");
        button.onclick=async()=>{
          button.disabled=true;
          try{
            if(operation==="play"){
              if(!c.included)throw Error("Include channel before tuning");
              await cmd("play",{key:c.key});
              show("web-channel-msg","Tuning requested: "+c.name);
            }else{
              await cmd("channel_update",{key:c.key,operation});
              await refreshChannels();
              show("web-channel-msg","Saved "+operation+": "+c.name);
            }
          }catch(e){show("web-channel-msg",e.message);}
          finally{button.disabled=false;}
        };
        actions.append(button);
      }
      item.append(actions);list.append(item);
    }
  }
  async function refreshScan(){
    if(!conn()?.connected()||!advancedAvailable)return;
    try{
      const data=await conn().get("/api/scan");
      show("web-scan-state",(data.running?"SCANNING · ":"Idle · ")+(data.status||""));
      show("web-signal",data.signal||"Frontend signal unavailable");
      const log=$("web-scan-log");log.replaceChildren();
      for(const e of (data.events||[]).slice(-45)){
        log.append(make("div","["+String(e.stage||"·")+"] "+(e.channel||e.text||e.kind||"")));
      }
    }catch(e){show("web-scan-state",e.message);}
  }
  async function refreshModels(){
    if(!conn()?.connected()||!advancedAvailable)return;
    try{
      const d=await conn().get("/api/models");
      show("web-model-info","Native ASR "+(d.asr_enabled?"ON":"OFF")+
        ", native translation "+(d.translation_enabled?"ON":"OFF")+
        ", backend "+d.backend+"; "+(d.models||[]).map(m=>m.name+
        (m.installed?" [installed]":" [not installed]")).join(", ")+
        ". Use desktop Settings to add/remove these packages.");
    }catch(e){show("web-model-info",e.message);}
  }
  $("web-filter").onchange=draw;
  $("web-refresh").onclick=refreshChannels;
  $("web-stop").onclick=async()=>{
    try{await cmd("stop");show("web-channel-msg","Stop requested; tuner released");}
    catch(e){show("web-channel-msg",e.message);}
  };
  $("web-scan-start").onclick=async()=>{
    const profile={country:$("web-country").value,medium:$("web-medium").value,
                   satellite:$("web-satellite").value};
    if(!confirm("Start a real full scan for "+profile.country+" / "+profile.medium+
                "? It requires exclusive native DVB access."))return;
    try{await cmd("scan_start",profile);show("web-scan-state","Scan requested");}
    catch(e){show("web-scan-state",e.message);}
  };
  $("web-scan-cancel").onclick=async()=>{
    try{await cmd("scan_cancel");show("web-scan-state","Cancel requested");}
    catch(e){show("web-scan-state",e.message);}
  };
  $("web-caption-set").onclick=async()=>{
    try{const r=await cmd("set_captions",{mode:$("web-caption-mode").value});
        show("web-model-info","Actual native subtitle mode: "+r.actual_mode);}
    catch(e){show("web-model-info",e.message);}
  };
  setInterval(()=>{if(conn()?.connected())refreshScan()},3000);
  setInterval(()=>{if(conn()?.connected()){refreshChannels();refreshModels()}},9000);
  document.addEventListener("tihulu-tv-connected",()=>{
    refreshChannels();refreshScan();refreshModels();
  });
})();
