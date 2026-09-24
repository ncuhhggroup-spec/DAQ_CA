# DEPLOYMENT_MANUAL.md

## System Architecture Overview

The **DAQ_CA** system is split into two separate components that run on distinct machines on the same LAN:

| Role | Host | Responsibilities |
|------|------|-------------------|
| **IOC Server (PC A)** | Runs `ca_server/ioc_server.py` – the EPICS Channel Access (CA) IOC server. It hosts the process variables (PVs) that control the sequence controller, stage, camera, and data manager. |
| **GUI Client (PC B)** | Runs `gui/main_gui.py` – a Qt‑based control panel that connects to the IOC server via EPICS CA. It provides user input, displays real‑time status, logs, and a camera preview. |

Both machines must be on the same subnet and be able to reach each other over UDP/TCP ports used by EPICS CA (default 5064 for UDP, 5065 for TCP).

## Step‑by‑Step Launch Guide

### 1. Server PC (IOC Host)
1. **Prerequisites**
   - Python 3.11+ installed.
   - Virtual environment activated (see `Py_venv.txt`).
   - Required packages installed: `caproto`, `numpy`, `h5py`, etc.
2. **Activate the environment**
   ```powershell
   cd C:\Users\USER\Documents\GitHub\DAQ_CA
   .\.venv\Scripts\activate
   ```
3. **Firewall / Network**
   - Allow inbound UDP/TCP ports **5064** and **5065** (EPICS CA).  On Windows you can run:
   ```powershell
   New-NetFirewallRule -DisplayName "EPICS CA" -Direction Inbound -Protocol UDP -LocalPort 5064 -Action Allow
   New-NetFirewallRule -DisplayName "EPICS CA TCP" -Direction Inbound -Protocol TCP -LocalPort 5065 -Action Allow
   ```
4. **Launch the IOC server**
   ```powershell
   python -m ca_server.ioc_server
   ```
   The server will start with the default PV prefix `EXP:Seq:` and print a connection banner.

### 2. Client PC (GUI Host)
1. **Prerequisites**
   - Same Python version and a virtual environment.
   - GUI dependencies installed: `PySide6`, `pyqtgraph`, `caproto`.
2. **Activate the environment**
   ```powershell
   cd C:\Users\USER\Documents\GitHub\DAQ_CA
   .\.venv\Scripts\activate
   ```
3. **Configure the target IOC IP address**
   - Set the environment variable `IOC_IP` (or directly set `EPICS_CA_ADDR_LIST`). Replace `192.168.1.10` with the actual IP of the Server PC.
   ```powershell
   $env:IOC_IP = "192.168.1.10"
   # Optional – verify the variable is exported to the process
   echo $env:IOC_IP
   ```
   - The GUI code reads `IOC_IP` at import time and populates `EPICS_CA_ADDR_LIST` automatically (see `gui/main_window.py`).
4. **Launch the GUI client**
   ```powershell
   python gui/main_gui.py
   ```
   The control panel should appear, automatically connecting to the IOC server.

## Verification Checklist
- **Server side**: In the server console you should see lines like `Listening on EPICS CA server on ...` and PVs being created.
- **Client side**:
  1. The **State** label shows **IDLE** (gray) on start‑up.
  2. In a terminal on either machine you can query a PV:
     ```powershell
     caproto-get EXP:Seq:State
     ```
     The result should be `IDLE`.
  3. Press **ARM / START** – the state label changes to **ARMED** (orange) and subsequently to **ACQUIRING**, **SAVING**, and back to **IDLE**. The console log in the GUI records each transition.
- If the GUI cannot connect, verify that `EPICS_CA_ADDR_LIST` contains the correct server IP and that firewall rules allow traffic on ports 5064/5065.

## Configuration Notes
- **`IOC_IP`** – a convenient placeholder that the GUI reads. It can be set system‑wide, per‑session, or via a `.env` file before launching the client.
- **Alternative** – set `EPICS_CA_ADDR_LIST` directly (e.g., `set EPICS_CA_ADDR_LIST=192.168.1.10`). The GUI respects this variable without modification.
- **PV Prefix** – currently hard‑coded as `EXP:Seq:` inside `gui/main_window.py`. To change it, edit the `EPICSWorker` constructor argument `prefix`.

---
*This manual is intended for a LAN‑based multi‑PC deployment of DAQ_CA. Adjust network settings as required for your specific environment.*
