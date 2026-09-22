"""
DG645 GUI Controller
====================
Graphical User Interface for Stanford Research Systems DG645 Digital Delay Generator.
Supports:
- RS-232 serial connection over COM5 (or any available port)
- Configuring Single-Shot with External Trigger mode (TSRC 3 / TSRC 4)
- Setting delays for 4 output pulse channels (AB, CD, EF, GH) with 1 ms pulse width
- Dedicated Single-Shot Trigger / Arm button
- Live serial communication log
"""

import sys
import time
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import serial.tools.list_ports

from dg645 import DG645, DG645Error, TRIGGER_SOURCES, OUTPUT_PULSE_CHANNELS


class DG645App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SRS DG645 Digital Delay Generator Controller")
        self.geometry("860x780")
        self.minsize(780, 700)

        # Style configuration
        self.style = ttk.Style(self)
        try:
            self.style.theme_use("clam")
        except Exception:
            pass

        self.dg: DG645 = None

        # Build UI layout
        self._create_widgets()
        self._refresh_com_ports()

    def _create_widgets(self):
        # Master container with padding
        main_frame = ttk.Frame(self, padding="12")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # ---------------------------------------------------------------------
        # 1. Connection Panel
        # ---------------------------------------------------------------------
        conn_frame = ttk.LabelFrame(main_frame, text=" Serial Connection ", padding="10")
        conn_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(conn_frame, text="Port:").grid(row=0, column=0, padx=(0, 4), sticky=tk.W)
        self.port_var = tk.StringVar(value="COM5")
        self.port_combo = ttk.Combobox(conn_frame, textvariable=self.port_var, width=12)
        self.port_combo.grid(row=0, column=1, padx=(0, 10), sticky=tk.W)

        btn_refresh = ttk.Button(conn_frame, text="↻ Refresh Ports", command=self._refresh_com_ports, width=13)
        btn_refresh.grid(row=0, column=2, padx=(0, 15), sticky=tk.W)

        ttk.Label(conn_frame, text="Baud Rate:").grid(row=0, column=3, padx=(0, 4), sticky=tk.W)
        self.baud_var = tk.StringVar(value="9600")
        baud_combo = ttk.Combobox(
            conn_frame,
            textvariable=self.baud_var,
            values=["4800", "9600", "19200", "38400", "57600", "115200"],
            width=8,
            state="readonly"
        )
        baud_combo.grid(row=0, column=4, padx=(0, 15), sticky=tk.W)

        self.btn_connect = tk.Button(
            conn_frame,
            text="Connect",
            command=self._toggle_connection,
            bg="#2e7d32",
            fg="white",
            font=("Segoe UI", 9, "bold"),
            padx=12,
            pady=2,
            relief=tk.RAISED
        )
        self.btn_connect.grid(row=0, column=5, padx=(0, 15), sticky=tk.W)

        self.status_var = tk.StringVar(value="Disconnected")
        self.status_label = ttk.Label(conn_frame, textvariable=self.status_var, font=("Segoe UI", 9, "italic"))
        self.status_label.grid(row=0, column=6, sticky=tk.W)

        # ---------------------------------------------------------------------
        # 2. Trigger Configuration Panel
        # ---------------------------------------------------------------------
        trig_frame = ttk.LabelFrame(main_frame, text=" Trigger Mode Settings ", padding="10")
        trig_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(trig_frame, text="Trigger Mode:").grid(row=0, column=0, padx=(0, 6), sticky=tk.W)
        self.trig_mode_var = tk.StringVar(value="Single Shot Ext Rising (TSRC 3)")
        self.trig_combo = ttk.Combobox(
            trig_frame,
            textvariable=self.trig_mode_var,
            values=[
                "Single Shot Ext Rising (TSRC 3)",
                "Single Shot Ext Falling (TSRC 4)",
                "Single Shot Software (TSRC 5)",
                "Continuous Ext Rising (TSRC 1)",
                "Internal Oscillator (TSRC 0)",
            ],
            width=32,
            state="readonly"
        )
        self.trig_combo.grid(row=0, column=1, padx=(0, 15), sticky=tk.W)

        ttk.Label(trig_frame, text="External Trigger Level (V):").grid(row=0, column=2, padx=(0, 6), sticky=tk.W)
        self.trig_level_var = tk.StringVar(value="1.000")
        self.trig_level_entry = ttk.Entry(trig_frame, textvariable=self.trig_level_var, width=8)
        self.trig_level_entry.grid(row=0, column=3, padx=(0, 15), sticky=tk.W)

        self.btn_apply_trig = ttk.Button(
            trig_frame,
            text="Apply Trigger Mode",
            command=self._apply_trigger_settings
        )
        self.btn_apply_trig.grid(row=0, column=4, sticky=tk.W)

        # ---------------------------------------------------------------------
        # 3. 4-Channel Delays & Pulse Widths Panel
        # ---------------------------------------------------------------------
        ch_frame = ttk.LabelFrame(main_frame, text=" 4-Channel Delays (Pulse Width = 1.0 ms) ", padding="10")
        ch_frame.pack(fill=tk.X, pady=(0, 10))

        headers = ["Channel (BNC)", "Edge Linkage", "Start Delay", "Unit", "Pulse Width (Trailing Edge)"]
        for c_idx, h in enumerate(headers):
            lbl = ttk.Label(ch_frame, text=h, font=("Segoe UI", 9, "bold"))
            lbl.grid(row=0, column=c_idx, padx=6, pady=(0, 6), sticky=tk.W)

        self.ch_entries = {}
        channel_configs = [
            (1, "Ch 1 (AB)", "A = T0 + Delay", "0.0", "ms", "B = A + 1.0 ms"),
            (2, "Ch 2 (CD)", "C = T0 + Delay", "10.0", "ms", "D = C + 1.0 ms"),
            (3, "Ch 3 (EF)", "E = T0 + Delay", "20.0", "ms", "F = E + 1.0 ms"),
            (4, "Ch 4 (GH)", "G = T0 + Delay", "30.0", "ms", "H = G + 1.0 ms"),
        ]

        for idx, (ch_num, name, link_info, def_val, def_unit, trail_info) in enumerate(channel_configs, start=1):
            ttk.Label(ch_frame, text=name).grid(row=idx, column=0, padx=6, pady=4, sticky=tk.W)
            ttk.Label(ch_frame, text=link_info, foreground="#555").grid(row=idx, column=1, padx=6, pady=4, sticky=tk.W)

            val_var = tk.StringVar(value=def_val)
            val_entry = ttk.Entry(ch_frame, textvariable=val_var, width=12)
            val_entry.grid(row=idx, column=2, padx=6, pady=4, sticky=tk.W)

            unit_var = tk.StringVar(value=def_unit)
            unit_combo = ttk.Combobox(ch_frame, textvariable=unit_var, values=["s", "ms", "us", "ns"], width=5, state="readonly")
            unit_combo.grid(row=idx, column=3, padx=6, pady=4, sticky=tk.W)

            ttk.Label(ch_frame, text=trail_info, foreground="#1976d2", font=("Segoe UI", 9, "bold")).grid(row=idx, column=4, padx=6, pady=4, sticky=tk.W)

            self.ch_entries[ch_num] = {
                'val': val_var,
                'unit': unit_var,
            }

        # Buttons row under channel table
        btn_ch_box = ttk.Frame(ch_frame)
        btn_ch_box.grid(row=5, column=0, columnspan=5, pady=(10, 0), sticky=tk.W)

        btn_apply_delays = ttk.Button(
            btn_ch_box,
            text="Apply All Delays (1 ms Width)",
            command=self._apply_all_delays
        )
        btn_apply_delays.pack(side=tk.LEFT, padx=(0, 10))

        btn_read_delays = ttk.Button(
            btn_ch_box,
            text="Read Delays From DG645",
            command=self._read_current_delays
        )
        btn_read_delays.pack(side=tk.LEFT, padx=(0, 10))

        btn_set_ttl = ttk.Button(
            btn_ch_box,
            text="Set Outputs to TTL (0-4V)",
            command=self._set_ttl_levels
        )
        btn_set_ttl.pack(side=tk.LEFT)

        # ---------------------------------------------------------------------
        # 4. Prominent Single-Shot Trigger Button
        # ---------------------------------------------------------------------
        trig_btn_frame = ttk.LabelFrame(main_frame, text=" Trigger Control ", padding="12")
        trig_btn_frame.pack(fill=tk.X, pady=(0, 10))

        # Single Shot Trigger Button
        self.btn_single_shot = tk.Button(
            trig_btn_frame,
            text="⚡ SINGLE SHOT TRIGGER / ARM (*TRG) ⚡",
            command=self._send_single_shot_trigger,
            bg="#d32f2f",
            fg="white",
            activebackground="#b71c1c",
            activeforeground="white",
            font=("Segoe UI", 12, "bold"),
            relief=tk.RAISED,
            bd=3,
            pady=10,
            cursor="hand2"
        )
        self.btn_single_shot.pack(fill=tk.X)

        self.trig_hint_label = ttk.Label(
            trig_btn_frame,
            text="In Single Shot External Trigger mode, clicking this arms the DG645 to trigger on the next incoming external pulse.",
            foreground="#555",
            font=("Segoe UI", 8, "italic")
        )
        self.trig_hint_label.pack(pady=(4, 0))

        # ---------------------------------------------------------------------
        # 5. Activity Log
        # ---------------------------------------------------------------------
        log_frame = ttk.LabelFrame(main_frame, text=" Serial Activity Log ", padding="8")
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            height=10,
            bg="#1e1e1e",
            fg="#dcdcdc",
            font=("Consolas", 9),
            wrap=tk.WORD
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)

        btn_clear_log = ttk.Button(log_frame, text="Clear Log", command=self._clear_log)
        btn_clear_log.pack(side=tk.RIGHT, pady=(4, 0))

    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------

    def log(self, message: str, level: str = "INFO"):
        """Append a message to the activity log."""
        timestamp = time.strftime("%H:%M:%S")
        prefix = f"[{timestamp}] [{level}]"
        self.log_text.insert(tk.END, f"{prefix} {message}\n")
        self.log_text.see(tk.END)

    def _clear_log(self):
        self.log_text.delete("1.0", tk.END)

    def _refresh_com_ports(self):
        """Scan system for available COM ports."""
        ports = [p.device for p in serial.tools.list_ports.comports()]
        if not ports:
            ports = ["COM5"]
        self.port_combo["values"] = ports
        if "COM5" in ports:
            self.port_var.set("COM5")
        elif ports:
            self.port_var.set(ports[0])
        self.log(f"Available serial ports: {', '.join(ports)}")

    def _unit_to_seconds(self, val_str: str, unit: str) -> float:
        """Convert a numerical string and unit into seconds."""
        val = float(val_str.strip())
        factors = {
            "s": 1.0,
            "ms": 1e-3,
            "us": 1e-6,
            "ns": 1e-9,
        }
        return val * factors.get(unit.lower(), 1.0)

    # -------------------------------------------------------------------------
    # Connection Handlers
    # -------------------------------------------------------------------------

    def _toggle_connection(self):
        if self.dg and self.dg.is_connected():
            # Disconnect
            try:
                self.dg.disconnect()
            except Exception as e:
                self.log(f"Error while disconnecting: {e}", "ERROR")
            self.dg = None
            self.btn_connect.config(text="Connect", bg="#2e7d32")
            self.status_var.set("Disconnected")
            self.status_label.config(foreground="black")
            self.log("Disconnected from serial port.")
        else:
            # Connect
            port = self.port_var.get().strip()
            baud = int(self.baud_var.get())
            try:
                self.log(f"Connecting to DG645 on {port} at {baud} baud...")
                self.dg = DG645(port=port, baudrate=baud, timeout=2.0)
                idn = self.dg.connect()
                self.log(f"Connected successfully! IDN: {idn}")
                self.btn_connect.config(text="Disconnect", bg="#c62828")
                self.status_var.set(f"Connected ({port})")
                self.status_label.config(foreground="#2e7d32")

                # Auto-query current mode
                self._read_current_delays()
            except Exception as e:
                self.dg = None
                self.log(f"Failed to connect: {e}", "ERROR")
                messagebox.showerror("Connection Error", f"Could not connect to {port}:\n{e}")

    # -------------------------------------------------------------------------
    # Instrument Operations
    # -------------------------------------------------------------------------

    def _apply_trigger_settings(self):
        if not self.dg or not self.dg.is_connected():
            messagebox.showwarning("Not Connected", "Please connect to the DG645 first.")
            return

        mode_str = self.trig_mode_var.get()
        # Extract code:
        if "TSRC 3" in mode_str:
            code = 3
        elif "TSRC 4" in mode_str:
            code = 4
        elif "TSRC 5" in mode_str:
            code = 5
        elif "TSRC 1" in mode_str:
            code = 1
        else:
            code = 0

        try:
            level_v = float(self.trig_level_var.get())
            self.dg.set_trigger_source(code)
            self.log(f"Set Trigger Source: {mode_str} (code {code})")
            
            self.dg.set_trigger_level(level_v)
            self.log(f"Set External Trigger Threshold: {level_v:.3f} V")
            messagebox.showinfo("Success", f"Trigger settings applied successfully!\nMode: {mode_str}\nThreshold: {level_v} V")
        except Exception as e:
            self.log(f"Error applying trigger settings: {e}", "ERROR")
            messagebox.showerror("Error", f"Failed to set trigger mode: {e}")

    def _apply_all_delays(self):
        if not self.dg or not self.dg.is_connected():
            messagebox.showwarning("Not Connected", "Please connect to the DG645 first.")
            return

        pulse_width_sec = 0.001  # Exactly 1.0 ms as requested

        try:
            for ch_num in [1, 2, 3, 4]:
                raw_val = self.ch_entries[ch_num]['val'].get()
                unit = self.ch_entries[ch_num]['unit'].get()
                delay_sec = self._unit_to_seconds(raw_val, unit)

                self.dg.set_channel_pulse(
                    channel_index_or_name=ch_num,
                    delay_seconds=delay_sec,
                    pulse_width_seconds=pulse_width_sec
                )
                ch_name = ["AB", "CD", "EF", "GH"][ch_num - 1]
                self.log(f"Configured Channel {ch_num} ({ch_name}): Delay = {delay_sec:.9e} s, Width = {pulse_width_sec*1e3:.1f} ms")

            messagebox.showinfo("Success", "All 4 channels updated successfully!\nPulse widths locked to 1.0 ms.")
        except Exception as e:
            self.log(f"Error applying delays: {e}", "ERROR")
            messagebox.showerror("Error", f"Failed to apply delays: {e}")

    def _read_current_delays(self):
        if not self.dg or not self.dg.is_connected():
            return

        try:
            # Query trigger source
            tsrc = self.dg.get_trigger_source()
            for opt in self.trig_combo["values"]:
                if f"TSRC {tsrc}" in opt:
                    self.trig_mode_var.set(opt)
                    break
            self.log(f"Current Trigger Source: TSRC {tsrc}")

            # Query trigger level
            tlvl = self.dg.get_trigger_level()
            self.trig_level_var.set(f"{tlvl:.3f}")

            # Query channel delays
            delays = self.dg.get_all_delays()
            names = ["AB", "CD", "EF", "GH"]
            for idx, name in enumerate(names, start=1):
                d_sec = delays[name]['delay']
                # Pick sensible unit display
                if d_sec >= 1.0 or d_sec == 0.0:
                    self.ch_entries[idx]['val'].set(f"{d_sec:.6f}")
                    self.ch_entries[idx]['unit'].set("s")
                elif d_sec >= 1e-3:
                    self.ch_entries[idx]['val'].set(f"{d_sec * 1e3:.6f}")
                    self.ch_entries[idx]['unit'].set("ms")
                elif d_sec >= 1e-6:
                    self.ch_entries[idx]['val'].set(f"{d_sec * 1e6:.6f}")
                    self.ch_entries[idx]['unit'].set("us")
                else:
                    self.ch_entries[idx]['val'].set(f"{d_sec * 1e9:.3f}")
                    self.ch_entries[idx]['unit'].set("ns")

                self.log(f"Channel {name}: Delay={d_sec:.9e} s, Pulse Width={delays[name]['width']*1e3:.4f} ms")

        except Exception as e:
            self.log(f"Could not read settings from instrument: {e}", "WARNING")

    def _set_ttl_levels(self):
        if not self.dg or not self.dg.is_connected():
            messagebox.showwarning("Not Connected", "Please connect to the DG645 first.")
            return

        try:
            for bnc in [1, 2, 3, 4]:
                self.dg.set_ttl_output(bnc)
            self.log("Configured channels AB, CD, EF, GH to standard TTL levels (0-4V).")
            messagebox.showinfo("TTL Levels Set", "Outputs AB, CD, EF, GH configured to standard TTL levels (0 to 4V).")
        except Exception as e:
            self.log(f"Error setting TTL levels: {e}", "ERROR")

    def _send_single_shot_trigger(self):
        """Button action for single shot trigger."""
        if not self.dg or not self.dg.is_connected():
            messagebox.showwarning("Not Connected", "Please connect to the DG645 first.")
            return

        try:
            # Animate button momentarily
            orig_bg = self.btn_single_shot.cget("bg")
            self.btn_single_shot.config(bg="#ff9800", text="⚡ TRIGGER / ARM SENT ⚡")
            self.update_idletasks()

            self.dg.arm_single_shot()
            self.log("Sent *TRG command: Single-shot triggered / armed!")

            self.after(350, lambda: self.btn_single_shot.config(bg=orig_bg, text="⚡ SINGLE SHOT TRIGGER / ARM (*TRG) ⚡"))
        except Exception as e:
            self.log(f"Error sending trigger: {e}", "ERROR")
            messagebox.showerror("Trigger Error", f"Failed to send trigger command:\n{e}")


def main():
    app = DG645App()
    app.mainloop()


if __name__ == "__main__":
    main()
