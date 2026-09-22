"""
DG645 Python Example Script
============================
Demonstrates how to:
1. Connect to SRS DG645 over RS-232 on COM5.
2. Query device identification (*IDN?).
3. Set trigger mode to Single-Shot with External Trigger (TSRC 3).
4. Set external trigger threshold level (e.g. 1.0 V).
5. Adjust delays for the 4 output channels (AB, CD, EF, GH) with 1 ms pulse width.
6. Arm/Trigger the single shot (*TRG).
"""

import time
from dg645 import DG645, DG645Error

# Serial port configuration
PORT = "COM5"       # Change if using another port
BAUDRATE = 9600     # DG645 factory default baud rate is 9600
PULSE_WIDTH = 0.001 # 1 ms pulse width (0.001 seconds)

def main():
    print(f"Connecting to DG645 on {PORT} at {BAUDRATE} baud...")

    try:
        # Using context manager ensures connection is cleanly closed even if an error occurs
        with DG645(port=PORT, baudrate=BAUDRATE, timeout=2.0) as dg:
            # 1. Identify device
            idn = dg.get_idn()
            print(f"Connected to: {idn}")

            # 2. Clear any prior errors/status
            dg.clear_status()

            # 3. Configure Trigger Mode:
            # Mode 3 = Single shot on external rising edges ('single_shot_ext_rising')
            # (Use mode 4 for falling edges, or mode 5 for purely manual single shot)
            print("\nConfiguring Trigger Mode...")
            dg.set_trigger_source("single_shot_ext_rising")
            dg.set_trigger_level(1.0) # 1.0 V external threshold
            print("Trigger mode set: Single-Shot External Rising Edge (TSRC 3), Threshold = 1.0 V")

            # 4. Configure delays for the 4 output channels with 1 ms pulse width:
            # - Channel 1 (AB): starts at 0.0 ms, ends at 1.0 ms
            # - Channel 2 (CD): starts at 10.0 ms, ends at 11.0 ms
            # - Channel 3 (EF): starts at 20.0 ms, ends at 21.0 ms
            # - Channel 4 (GH): starts at 30.0 ms, ends at 31.0 ms
            print(f"\nSetting 4 channels with {PULSE_WIDTH*1e3:.1f} ms pulse width:")
            channel_delays = {
                'AB': 0.000,      # 0.0 ms
                'CD': 0.010,      # 10.0 ms
                'EF': 0.020,      # 20.0 ms
                'GH': 0.030,      # 30.0 ms
            }

            for ch_name, delay_sec in channel_delays.items():
                dg.set_channel_pulse(
                    channel_index_or_name=ch_name,
                    delay_seconds=delay_sec,
                    pulse_width_seconds=PULSE_WIDTH
                )
                print(f"  Channel {ch_name}: Delay = {delay_sec*1e3:.3f} ms, Pulse Width = {PULSE_WIDTH*1e3:.1f} ms")

            # 5. Set outputs to standard TTL levels (0-4V)
            for bnc in ['AB', 'CD', 'EF', 'GH']:
                dg.set_ttl_output(bnc)
            print("\nAll 4 channel outputs configured to TTL levels.")

            # 6. Read back settings from instrument to verify
            print("\nVerifying channel settings from DG645:")
            readings = dg.get_all_delays()
            for ch, info in readings.items():
                print(f"  {ch}: Start Delay = {info['delay']:.9e} s, Width = {info['width']*1e3:.3f} ms")

            # 7. Single-Shot Trigger / Arm button demonstration:
            print("\n" + "="*50)
            print("Ready for Single Shot!")
            print("In Single-Shot External mode, sending *TRG arms the DG645.")
            print("The delay sequence will fire upon the next external trigger pulse.")
            print("="*50)

            # Interactive loop for triggering via command-line:
            while True:
                user_choice = input("\nPress [ENTER] to Arm/Trigger Single Shot (or type 'q' to quit): ").strip()
                if user_choice.lower() == 'q':
                    break

                dg.arm_single_shot()
                print(">>> *TRG sent! DG645 is armed / single shot initiated.")

    except serial.SerialException as e:
        print(f"\n[Serial Error] Could not open or communicate on {PORT}: {e}")
        print("Please check that the USB-to-RS232 adapter is plugged in and recognized as COM5.")
    except DG645Error as e:
        print(f"\n[DG645 Error]: {e}")
    except Exception as e:
        print(f"\n[Unexpected Error]: {e}")

if __name__ == "__main__":
    main()
