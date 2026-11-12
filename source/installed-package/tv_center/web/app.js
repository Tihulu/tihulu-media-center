"use strict";
(() => {
  const $ = id => document.getElementById(id);
  let token = "", timer = null, connected = false, busy = false;
  const BASE = "http://127.0.0.1:8768";
  const state = message => { $("state").textContent = message; };
  function reset() {
    if (timer) clearInterval(timer);
    timer = null; token = ""; connected = false; busy = false;
    $("connect").disabled = false; $("disconnect").disabled = true;
    $("open-page").disabled = true;
    state("DISCONNECTED");
  }
  async function api(path, method="GET", data=null) {
    const response = await fetch(BASE+path, {
      method, cache:"no-store",
      headers:{"Authorization":"Bearer "+token, "Content-Type":"application/json"},
      ...(data ? {body:JSON.stringify(data)} : {})
    });
    if (!response.ok) throw new Error("Local bridge HTTP "+response.status);
    return response.json();
  }
  async function refresh() {
    if (!connected || busy) return;
    busy = true;
    try {
      const data = await api("/api/status");
      $("channel").textContent = data.channel || "No tuned channel";
      $("source").textContent = data.source === "live_native_dvb" ?
        "Source: native Linux DVB receiver — current tuned channel" :
        "Receiver idle. No background tuner activity.";
      $("original").textContent = data.caption?.original || "No actual caption decoded yet";
      $("translated").textContent = data.caption?.translated || "";
      $("caption-source").textContent = data.caption?.source || "none";
      $("page").value = data.teletext_page || 150;
      state(data.source === "live_native_dvb" ? "LIVE LOCAL DVB" : "BRIDGE CONNECTED");
      $("connection-note").textContent = "Connected through an explicitly enabled loopback bridge.";
    } catch(e) {
      $("connection-note").textContent = "Disconnected: "+e.message+". Browsers may block local-network access from Pages.";
      reset();
    } finally { busy = false; }
  }
  $("connect").onclick = async () => {
    const next = $("token").value.trim();
    if (!next) return;
    token = next;
    connected = true;
    $("connect").disabled = true; $("disconnect").disabled = false;
    $("open-page").disabled = false;
    await refresh();
    if (connected) {
      timer = setInterval(refresh, 1500);
      document.dispatchEvent(new Event("tihulu-tv-connected"));
    }
  };
  $("disconnect").onclick = reset;
  $("open-page").onclick = async () => {
    if (!connected) return;
    const page = Number($("page").value);
    if (!Number.isInteger(page) || page < 100 || page > 899) {
      $("teletext-result").textContent = "Enter a three-digit page between 100 and 899.";
      return;
    }
    try {
      await api("/api/teletext", "POST", {page});
      $("teletext-result").textContent = "Page "+page+" requested. Decoding requires current live packets; data may be absent.";
    } catch(e) { $("teletext-result").textContent = e.message; }
  };
  for (const btn of document.querySelectorAll("[data-page]")) {
    btn.onclick = () => { $("page").value = btn.dataset.page; if (connected) $("open-page").click(); };
  }

  // WebUSB permission is optional and never used as evidence of TV reception.
  const usbStatus = message => { $("usb-status").textContent = message; };
  const matchesWinTV = device => device.vendorId === 0x2040 && device.productId === 0x8268;
  if (!("usb" in navigator)) {
    $("webusb-select").disabled = true;
    $("webusb-check").disabled = true;
    usbStatus("WebUSB unavailable in this browser. Use Chromium for device selection, or the optional native DVB bridge.");
  }
  $("webusb-select").onclick = async () => {
    if (!navigator.usb) return;
    try {
      const device = await navigator.usb.requestDevice({
        filters: [{vendorId: 0x2040, productId: 0x8268}]
      });
      if (!matchesWinTV(device)) {
        usbStatus("Selected USB device does not match the Hauppauge WinTV-soloHD profile.");
        return;
      }
      usbStatus("USB permission granted: " + (device.productName || "Hauppauge device") +
        " (2040:8268). Detection only — a DVB-T2 WebUSB tuner driver, firmware loader, transport decoder and browser video pipeline are NOT implemented. Continue with the native bridge for live TV.");
    } catch (e) {
      usbStatus(e.name === "NotFoundError" ? "No matching receiver chosen or permission dismissed." :
        "WebUSB permission failed: " + e.message);
    }
  };
  $("webusb-check").onclick = async () => {
    if (!navigator.usb) return;
    try {
      const devices = (await navigator.usb.getDevices()).filter(matchesWinTV);
      usbStatus(devices.length ?
        "Previously permitted WinTV-soloHD USB detected (" + devices.length +
        "). DVB-T2 decoding is not yet available in-browser." :
        "No previously permitted Hauppauge WinTV-soloHD USB receiver found.");
    } catch(e) { usbStatus("Unable to read permitted USB devices: " + e.message); }
  };
  $("check-compute").onclick = async () => {
    const availableWasm = typeof WebAssembly !== "undefined";
    let gpu = "unavailable";
    if (navigator.gpu) {
      try { gpu = (await navigator.gpu.requestAdapter()) ? "adapter available" : "no compatible adapter"; }
      catch(e) { gpu = "adapter check failed"; }
    }
    $("compute-status").textContent = "WebAssembly: " + (availableWasm ? "supported" : "unavailable") +
      " | WebGPU: " + gpu +
      ". No speech/translation model is installed or running in this page. Capability is not live ASR.";
  };
  window.tihuluTVWeb = {
    connected:()=>connected,
    get: path=>api(path),
    command:async(action,params)=>{
      const d=await api("/api/command","POST",{action,params});
      return d.result;
    }
  };
  window.addEventListener("pagehide", reset);
})();
