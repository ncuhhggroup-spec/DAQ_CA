// from 20190926
// final edited 202205
// 2023-10 Update: Implemented Directional PID, Hardware PWM, and Motion Profiling

#include <DueFlashStorage.h>
#include "variables.h"
DueFlashStorage dueFlashStorage;

void setup() {
  // --- NEW: Initialize Native USB for Monitoring ---
  SerialUSB.begin(115200); 

  // --- WAIT FOR CONNECTION ---
  // The board pauses here until Serial Monitor is opened
  while (!SerialUSB); 
  // ---------------------------
  
  SerialUSB.println("=== SYSTEM RESTART ===");
  
  // --- OLD: Keep RS232 exactly as it was ---
  Serial1.begin(19200);
  
  Respond[0] = 255; 

  name_due = dueFlashStorage.read(0); 

  pinMode(pinMotorMinus_ch1, OUTPUT); pinMode(pinMotorPlus_ch1, OUTPUT); pinMode(pinEncoderA_ch1, INPUT); pinMode(pinEncoderB_ch1, INPUT);
  pinMode(pinEn_ch1, OUTPUT);
  pinMode(pinMotorMinus_ch2, OUTPUT); pinMode(pinMotorPlus_ch2, OUTPUT); pinMode(pinEncoderA_ch2, INPUT); pinMode(pinEncoderB_ch2, INPUT); pinMode(pinEn_ch2, OUTPUT);
  pinMode(pinMotorMinus_ch3, OUTPUT); pinMode(pinMotorPlus_ch3, OUTPUT); pinMode(pinEncoderA_ch3, INPUT); pinMode(pinEncoderB_ch3, INPUT);
  pinMode(pinEn_ch3, OUTPUT);
  pinMode(pinMotorMinus_ch4, OUTPUT); pinMode(pinMotorPlus_ch4, OUTPUT); pinMode(pinEncoderA_ch4, INPUT); pinMode(pinEncoderB_ch4, INPUT); pinMode(pinEn_ch4, OUTPUT);
  pinMode(pinMotorMinus_ch5, OUTPUT); pinMode(pinMotorPlus_ch5, OUTPUT); pinMode(pinEncoderA_ch5, INPUT); pinMode(pinEncoderB_ch5, INPUT);
  pinMode(pinEn_ch5, OUTPUT);
  pinMode(pinMotorMinus_ch6, OUTPUT); pinMode(pinMotorPlus_ch6, OUTPUT); pinMode(pinEncoderA_ch6, INPUT); pinMode(pinEncoderB_ch6, INPUT); pinMode(pinEn_ch6, OUTPUT);

  // Initial Parameters to channel 1:
  encoderValue = &encoderValue_ch1;
  runningstatus = false;

  SelectMotorChannel(1);
  // Initialize PID & Ramp Parameters:
  float initialP = 10 * 0.001;
  Kp_Pos = initialP;
  Kp_Neg = initialP;
  Kd_Pos = 0.5;
  Kd_Neg = 0.5;
  
  // Ramp Speed: 5 steps per 5ms loop = 1000 steps/sec
  rampStep = 90;
  minPWM = 65;       
}

void loop() {
  // Check Serial1 (RS232) for machine commands
  if (Serial1.available() >= COMMANDLENGTH) {
    processSerialCommands(Serial1);
  }
  
  MotorRun(); 
}
