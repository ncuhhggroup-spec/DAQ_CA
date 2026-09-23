# Cross-PC EPICS IOC Testing Manual & Operation Guide

This manual explains how to test the **DAQ EPICS Channel Access (CA) IOC Server** across two different computers on the same Local Area Network (LAN):
- **PC A (Server PC)**: Connected to hardware (or running mock drivers), hosts the EPICS IOC.
- **PC B (Client PC)**: Remote operator computer sending setpoints and trigger commands via Channel Access.

---

## 1. Network & Firewall Prerequisites

EPICS Channel Access uses standard ports:
- **Port 5064 (TCP & UDP)**: CA Search and Connection
- **Port 5065 (UDP)**: CA Beacon

### On PC A (Server PC)
```powershell
### On PC A (Server PC)
1. Find PC A's LAN IP address:
   ```powershell
   ipconfig
   # Look for IPv4 Address, e.g. 192.168.1.32

```

2. Configure Windows Defender Firewall rules for EPICS CA and Ping (ICMPv4):
```powershell
# Run in PowerShell (Admin) on PC A:

# Allow EPICS Channel Access (TCP 5064, UDP 5064-5065)
netsh advfirewall firewall add rule name="EPICS CA 5064" dir=in action=allow protocol=TCP localport=5064
netsh advfirewall firewall add rule name="EPICS CA UDP" dir=in action=allow protocol=UDP localport=5064,5065

# Allow ICMPv4 (Ping requests)
netsh advfirewall firewall add rule name="Allow ICMPv4-In" protocol=icmpv4:8,any dir=in action=allow


### Check Connectivity
From **PC B (Client PC)**, verify you can ping PC A:
```powershell
ping 192.168.1.100
```

---

## 2. Setting Up the Environment

### On PC A (Server PC)
Make sure the dependencies are installed:
```powershell
cd DAQ_CA
.\.venv\Scripts\Activate.ps1
pip install -r Requirements.txt
```

### On PC B (Client PC)
PC B only needs a minimal Python environment with `caproto` (it does **not** need any hardware drivers or large dependencies):
```powershell
pip install caproto
```

---

## 3. Step-by-Step Test Procedure

### Step 3.1: Start the IOC on PC A (Server PC)
In PowerShell on PC A:
```powershell
cd DAQ_CA
.\.venv\Scripts\python.exe -m ca_server.ioc_server
```

You will see:
```text
=================================================================
       STARTING CAPROTO EPICS CHANNEL ACCESS IOC SERVER          
=================================================================
PVs exposed under prefix 'EXP:Seq:':
  - EXP:Seq:ShotTarget (int, R/W)
  - EXP:Seq:Arm        (int, R/W)
  - EXP:Seq:State      (str, RO)
  - EXP:Seq:FileName   (str, R/W)
  - EXP:Seq:Note       (str, R/W)
-----------------------------------------------------------------
```
Leave this window running.

---

### Step 3.2: Run the Automated Test Client from PC B (Client PC)

Copy `ca_client_test.py` to PC B (or clone the repository on PC B), then execute:

```powershell
# Replace 192.168.1.100 with the actual IP address of PC A
python ca_client_test.py --server-ip 192.168.1.32
```

#### Expected Test Output on PC B:
```text
[Config] Set EPICS_CA_ADDR_LIST = 192.168.1.100 (AUTO_ADDR_LIST=NO)

========================================================
  CONNECTING TO DAQ IOC SERVER (Prefix: EXP:Seq:)
========================================================

[1/4] Reading initial PV values...
  - EXP:Seq:ShotTarget   = 1
  - EXP:Seq:Arm          = 0
  - EXP:Seq:State        = IDLE
  - EXP:Seq:FileName     = exp_run
  - EXP:Seq:Note         = 

>>> Connection verified successfully!

[2/4] Writing test configuration parameters...
  - Setting FileName   -> 'remote_test_1234'
  - Setting Note       -> 'Remote PC DAQ test'
  - Setting ShotTarget -> 3

[3/4] Triggering Acquisition (Arm = 1)...

[4/4] Monitoring State progression...
  [State Update] -> ARMED
  [State Update] -> IDLE

========================================================
  REMOTE DAQ SEQUENCE TEST PASSED (100% OK)!
========================================================
```

---

## 4. Alternative: Manual Testing via Command-Line / Caproto CLI

You can also interact with the PVs individually using standard EPICS command-line tools or `caproto-get` / `caproto-put` directly on PC B.

Set the destination server IP in PowerShell on PC B:
```powershell
$env:EPICS_CA_ADDR_LIST = "192.168.1.100"
$env:EPICS_CA_AUTO_ADDR_LIST = "NO"
```

### 1. Read Current State:
```powershell
python -m caproto.sync.client read EXP:Seq:State
# Returns: IDLE
```

### 2. Set Parameters:
```powershell
# Set 5 shots
python -m caproto.sync.client write EXP:Seq:ShotTarget 5

# Set file name prefix
python -m caproto.sync.client write EXP:Seq:FileName my_beam_scan

# Set user note
python -m caproto.sync.client write EXP:Seq:Note "Shot from Remote PC"
```

### 3. Fire the Sequence:
```powershell
python -m caproto.sync.client write EXP:Seq:Arm 1
```

### 4. Check Server Output on PC A:
On PC A, you will see the logs showing:
- RAM buffer pre-allocation for 5 frames
- Mock camera frame acquisition
- HDF5 file (`data/my_beam_scan_<timestamp>.h5`) and TIFF file saved to local SSD
- `experiment_log.xlsx` updated with a new row.

---

## 5. Troubleshooting & FAQ

| Problem | Cause | Solution |
| :--- | :--- | :--- |
| **Timeout / PV not found** | PC B cannot reach PC A on port 5064 | 1. Check IP address with `ipconfig`.<br>2. Run `ping <server-ip>` from PC B.<br>3. Allow ports 5064 and 5065 in Windows Firewall on PC A. |
| **State stays `ERROR`** | Stage interlock triggered (stage is in motion) | Check stage status on PC A. The controller requires `stage.is_moving() == False` before arming. |
| **Different Subnets** | Subnet broadcast blocked across VLANs | Explicitly set `EPICS_CA_ADDR_LIST="192.168.X.Y"` and `EPICS_CA_AUTO_ADDR_LIST="NO"` on the client PC. |
