# Satellite dish / Raspberry Pi 5 connection guide

## What works, and what does not

A normal Turkish home satellite dish is **DVB-S or DVB-S2** via an LNB and an
F-type coaxial cable, normally aimed at **Türksat 42°E**. The existing
**Hauppauge WinTV-soloHD (USB 2040:8268)** receives DVB-T/T2/C, **not DVB-S2**.
No antenna or firmware setting can turn that tuner into a satellite receiver.

**Never connect the satellite coax directly to Raspberry Pi 5 GPIO, USB,
Ethernet, HDMI, camera/display ribbon ports, or the 40-pin header.**
GPIO signals use 3.3 V logic and cannot handle satellite LNB supply or
demodulate 950–2150 MHz intermediate-frequency RF. Typical satellite tuners
supply 13/18 V and a 22 kHz tone to the LNB. A safe design requires a **real
DVB-S2 tuner with built-in LNB power control**, and electrically appropriate
RF connectors and drivers. Neither a passive pin converter nor a software
GPIO mapping can provide that capability.

## Recommended connection: USB DVB-S2 receiver

1. Use a **Linux-supported USB DVB-S2/S2X receiver** with its own coax F socket
   and appropriate LNB power supply. Confirm the exact chipset, Linux kernel
   driver, USB power requirements and firmware before purchasing.
2. Attach the dish's coax to the tuner F socket (with equipment powered off).
   If there is a multiswitch, Unicable/SCR, or DiSEqC switching system,
   identify its configuration; do not assume a direct Universal LNB.
3. Connect the USB tuner to the Raspberry Pi 5 or Debian/Pop!_OS PC. Use a
   **powered USB hub or dedicated tuner power adapter** if the tuner requires it.
4. Check receiver enumeration with:
   
   ```bash
   ls -l /dev/dvb/
   dmesg | grep -Ei 'dvb|frontend|firmware|lnb'
   ```
5. Open **TV Center → Satellite dish DVB-S/S2**, choose the tuner adapter,
   **Türksat 42°E**, a standard **Universal LNB** and the correct DiSEqC
   switch port, if present. Run **Automatic full channel scan**.
6. Review all actually detected services before adding, ordering or favoriting.
   The signal monitor shows real C/N and UCB when the driver exposes them.
   Unavailable signal readings are reported as unavailable, not invented.

If both WinTV-soloHD and DVB-S2 adapters are plugged in, **do not assume**
adapter0 is the satellite tuner. Select the correct adapter in the UI.

## Raspberry Pi 5 HAT/PCIe route

A genuine DVB-S2 add-on HAT or PCIe tuner board may be supported **only if**
its manufacturer explicitly supports the Pi 5, Linux DVB drivers, suitable
power and LNB supply. The GPIO, SPI or I2C pins can carry *control signals
for a properly designed receiver board*, but cannot be used as an RF
coaxial input themselves. Raspberry Pi 5's PCIe FFC needs an appropriately
engineered adapter and compatible board; there is no safe universal
GPIO-to-satellite wiring guide. For most users, **USB DVB-S2** is simpler.

A **SAT>IP** network satellite tuner is another option, but the current
native application does not yet implement a generic SAT>IP client.
Do not claim satellite reception based on simply seeing an IP address.

## DVB-S/S2 scan specifics

`w_scan_cpp -f s -s S42E0` chooses satellite, not the terrestrial country
frequency table. `-l UNIVERSAL` selects a common universal LNB preset,
and optional DiSEqC settings choose the intended switch input.
Use them only when compatible with the actual installation. The code
never triggers rotor movement or guesses Unicable user-band parameters.

Other optional profiles: Hot Bird 13°E, Astra 19.2°E and Eutelsat 7°E.
The dish must actually point at the selected satellite. Program availability
depends on the true transponders, encryption, tuner driver and antenna lock.

## Optional AI engines and storage

Under **Settings → Model Market**, keep both **Speech transcription** and
**Translation** OFF by default. Install only desired GGML multilingual Whisper
models or Argos language packs. DE/EN/TR output requires a matching
Argos language pair; model files alone do not install the required runtime.
Choose CPU, GPU or NPU explicitly. A detected GPU/NPU is not enough: its
runtime and compatible model must pass a readiness check before use.
Model storage can be moved to a mounted external SSD; the application
never silently downloads an engine or model during TV reception.

## Safety and test status

Physical installation, lightning protection, grounding, dish positioning
and LNB wiring should follow the antenna equipment manufacturer's guidance
and local electrical rules. Neither Pi 5 DVB-S2 nor actual Türksat reception
has been acceptance-tested in this development preview.

Sources: Linux DVB tools `dvbv5-scan` and `w_scan_cpp` manuals.
