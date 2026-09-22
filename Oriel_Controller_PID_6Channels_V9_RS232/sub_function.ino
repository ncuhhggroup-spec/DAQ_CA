// ================================================================
// ENCODER FUNCTIONS
// ================================================================

void InitialEncoderState()
{
  stateEncoderA_running = digitalRead(pinEncoderA_running);
  stateEncoderB_running = digitalRead(pinEncoderB_running);
  if (stateEncoderA_running == LOW){
    if (stateEncoderB_running == LOW)
      valueEncoder_previous = 1; //0 0
    else
      valueEncoder_previous = 4; // 0 1
  }
  else{
    if (stateEncoderB_running == LOW)
      valueEncoder_previous = 2; //1 0
    else
      valueEncoder_previous = 3; //1 1
  }
}

void ReadEncoderState()
{
  stateEncoderA_running = digitalRead(pinEncoderA_running);
  stateEncoderB_running = digitalRead(pinEncoderB_running);
  
  if (stateEncoderA_running == LOW){
    if (stateEncoderB_running == LOW)
      valueEncoder_present = 1; //0 0
    else
      valueEncoder_present = 4; // 0 1
  }
  else{
    if (stateEncoderB_running == LOW)
      valueEncoder_present = 2; //1 0
    else
      valueEncoder_present = 3; //1 1
  }

  if (valueEncoder_present > valueEncoder_previous){
    diffEncoder = valueEncoder_present - valueEncoder_previous; 
    if (diffEncoder == 1)
      ++*encoderValue;  //+1
    else if (diffEncoder == 3)
      --*encoderValue;  //+3
  }
  if (valueEncoder_present < valueEncoder_previous){
    diffEncoder = valueEncoder_previous - valueEncoder_present; 
    if (diffEncoder == 1)
      --*encoderValue;  //-1
    else if (diffEncoder == 3)
      ++*encoderValue;  //-3
  }

  valueEncoder_previous = valueEncoder_present; 
}



// ================================================================
// REVISED MOTOR CONTROL LOOP (With Direction Change Dead-Time)
// ================================================================
unsigned long lastMonitorTime = 0; 
int lastDirection = 0;                // To track direction changes
unsigned long dirChangeTimer = 0;     // To track the pause time
const int DEAD_TIME_MS = 50;          // 50ms pause when changing direction

void MotorRun() {
  // 1. Safety & Idle Check
  if (!runningstatus) {
    analogWrite(HbridgeHigh, 0);
    analogWrite(HbridgeLow, 0);    
    digitalWrite(pinEn_running, LOW); 
    // Reset state when stopped
    lastDirection = 0;
    return; 
  }

  // 2. Sample Rate Control (5ms loop)
  if (millis() - lastPIDTime < loopTimeMS) {
    return;
  }
  lastPIDTime = millis();

  // --- RAMP GENERATOR ---
  long distToFinal = finalTarget - tempTarget;
  if (distToFinal != 0) {
    if (abs(distToFinal) > rampStep) {
      if (distToFinal > 0) tempTarget += rampStep;
      else                 tempTarget -= rampStep;
    } else {
      tempTarget = finalTarget;
    }
  }
  
  // --- BACKLASH HANDLING & COMPLETION ---
  long currentPos = *encoderValue;
  if (tempTarget == finalTarget && abs(currentPos - tempTarget) <= thresholdValue) {
      if (finalTarget != targetValue) {
          finalTarget = targetValue;
      } 
      else {
          runningstatus = false;
          analogWrite(HbridgeHigh, 0);
          digitalWrite(pinEn_running, LOW);
          
          SerialUSB.print("Target Reached. Final Pos: ");
          SerialUSB.println(currentPos);
          return;
      }
  }

  // --- PID CONTROL ---
  long currentError = tempTarget - currentPos;
  
  // Determine Desired Direction
  int currentDir = 0;
  if (currentError > 0) currentDir = 1;
  else if (currentError < 0) currentDir = -1;

  // --- NEW: DETECT DIRECTION CHANGE ---
  if (currentDir != lastDirection && lastDirection != 0) {
     // If direction just changed, start the timer
     dirChangeTimer = millis();
  }
  lastDirection = currentDir;

  // --- NEW: APPLY DEAD TIME ---
  // If we are within the Dead Time window, force STOP
  if (millis() - dirChangeTimer < DEAD_TIME_MS) {
     analogWrite(HbridgeHigh, 0);
     digitalWrite(HbridgeLow, LOW);
     digitalWrite(pinEn_running, HIGH); // Keep enabled to allow magnetic braking
     return; // Skip the rest of the loop (Do not move)
  }

  // If we passed the Dead Time, proceed with Normal Movement
  float currentKp, currentKd;
  int signedPowerMultiplier = 1; 

  if (currentDir == 1) {
    HbridgeHigh = pinMotorMinus_running;
    HbridgeLow = pinMotorPlus_running; 
    currentKp = Kp_Pos;
    currentKd = Kd_Pos;
    signedPowerMultiplier = 1; 
  } else {
    HbridgeHigh = pinMotorPlus_running;
    HbridgeLow = pinMotorMinus_running;
    currentKp = Kp_Neg;
    currentKd = Kd_Neg;
    signedPowerMultiplier = -1; 
  }

  // PID Math
  long errorDelta = currentError - prevError;
  float pidTerm = (currentKp * abs(currentError)) - (currentKd * abs(errorDelta));

  // Ensure pidTerm doesn't go negative (optional, but good for stability if not using reverse-braking)
  if (pidTerm < 0) pidTerm = 0;
  
  int outputPWM = (int)(pidTerm + minPWM);
  outputPWM = constrain(outputPWM, 0, pwmSpeedMax);

  // Drive
  digitalWrite(pinEn_running, HIGH);
  digitalWrite(HbridgeLow, LOW);
  analogWrite(HbridgeHigh, outputPWM);

  prevError = currentError;

  // ============================================================
  // TELEMETRY OUTPUT
  // ============================================================
  if (millis() - lastMonitorTime > 50) { 
    lastMonitorTime = millis();
    SerialUSB.print("Pos:");
    SerialUSB.print(currentPos);
    SerialUSB.print(" Pwr:");
    SerialUSB.println(outputPWM * signedPowerMultiplier); 
  }
}

// ================================================================
// COMMAND PROCESSOR
// ================================================================
void processSerialCommands(Stream& serialPort) {
  if (serialPort.available() < COMMANDLENGTH) return;
  
  // Read Data
  for (int i = 0; i < COMMANDLENGTH; i++) {
    Command[i] = serialPort.read();
  }

  // --- NEW: Echo Received Command to Native USB ---
  // Only echo if the command came from Serial1 (External)
  if (&serialPort == &Serial1) {
    SerialUSB.print("RX[Hex]: ");
    for (int i = 0; i < COMMANDLENGTH; i++) {
       if(Command[i] < 0x10) SerialUSB.print("0"); // Leading zero for clean format
       SerialUSB.print(Command[i], HEX);
       SerialUSB.print(" ");
    }
    SerialUSB.println(); 
  }

  // Normal Command Processing
  if (Command[0] != 0xFF) return;
  if (Command[1] != 0x00 && Command[1] != name_due) return;
  
  switch (Command[2]) {
    
    case 0x00: { // Manual Move
      int manualPWM = Command[3];
      int dir = Command[4];
      int duration = Command[5]; 

      if (dir == 1) {
        HbridgeHigh = pinMotorMinus_running;
        HbridgeLow = pinMotorPlus_running;
      } else {
        HbridgeHigh = pinMotorPlus_running;
        HbridgeLow = pinMotorMinus_running;
      }
      
      digitalWrite(pinEn_running, HIGH);
      digitalWrite(HbridgeLow, LOW);
      analogWrite(HbridgeHigh, manualPWM);
      
      // Echo Manual move status to USB
      SerialUSB.print("Manual Move. PWM: ");
      SerialUSB.println(manualPWM);

      if (duration > 0) {
        delay(duration);
        analogWrite(HbridgeHigh, 0);
        digitalWrite(pinEn_running, LOW);
      }
      break;
    }

    // 0x01: Report Status
    case 0x01: {
      Respond[1] = channel_num;
      Respond[2] = runningstatus;
      Respond[3] = (*encoderValue >= 0) ? 1 : 0; 
      U32toU8(abs(*encoderValue));
      Respond[4] = U8_a; Respond[5] = U8_b;
      Respond[6] = U8_c; Respond[7] = U8_d;
      
      // NOTE: writing back to 'serialPort' ensures Serial1 replies to Serial1. 
      // This preserves existing functionality.
      for (int i = 0; i < 8; i++) serialPort.write(Respond[i]);
      break;
    }

    // 0x02: Go To Target 
    case 0x02: {
      long rawTarget = U8toU32(Command[3], Command[4], Command[5], Command[6]);
      if (Command[7] == 0) rawTarget *= -1; 
      
      targetValue = rawTarget;
      // Initialize the Ramp
      tempTarget = *encoderValue; 
      finalTarget = targetValue - BACKLASH_OVERSHOOT_STEPS; 
      
      runningstatus = true;
      SerialUSB.print("Auto Move. Target: "); 
      SerialUSB.println(targetValue);
      break;
    }
    
    case 0x03: {
      float newP = Command[3] * 0.001;
      Kp_Pos = newP;
      Kp_Neg = newP;
      Speed_lowest = Command[4]; 
      break;
    }
    case 0x04: {
      SelectMotorChannel(Command[3]);
      SerialUSB.print("Ch Changed to: "); SerialUSB.println(Command[3]); 
      break;
    }
    case 0x05: {
      long newVal = U8toU32(Command[3], Command[4], Command[5], Command[6]);
      if (Command[7] == 0) newVal *= -1;
      *encoderValue = newVal;
      SerialUSB.print("Pos Set to: "); SerialUSB.println(newVal); 
      break;
    }
    case 0x06: {
      runningstatus = false;
      analogWrite(HbridgeHigh, 0); 
      digitalWrite(pinEn_running, LOW);
      SerialUSB.println("E-STOP"); 
      break;
    }
    case 0x07: {
      name_due = Command[3];
      dueFlashStorage.write(0, name_due);
      break;
    }
  }
}
// [Rest of file: SelectMotorChannel, U8toU16, etc. remain unchanged]

void SelectMotorChannel(int ch) {
  detachInterrupt(digitalPinToInterrupt(pinEncoderA_ch1)); detachInterrupt(digitalPinToInterrupt(pinEncoderB_ch1));
  detachInterrupt(digitalPinToInterrupt(pinEncoderA_ch2)); detachInterrupt(digitalPinToInterrupt(pinEncoderB_ch2));
  detachInterrupt(digitalPinToInterrupt(pinEncoderA_ch3)); detachInterrupt(digitalPinToInterrupt(pinEncoderB_ch3));
  detachInterrupt(digitalPinToInterrupt(pinEncoderA_ch4)); detachInterrupt(digitalPinToInterrupt(pinEncoderB_ch4));
  detachInterrupt(digitalPinToInterrupt(pinEncoderA_ch5)); detachInterrupt(digitalPinToInterrupt(pinEncoderB_ch5));
  detachInterrupt(digitalPinToInterrupt(pinEncoderA_ch6)); detachInterrupt(digitalPinToInterrupt(pinEncoderB_ch6));

  channel_num = ch;
  switch (ch) {
    case 1: pinEncoderA_running = pinEncoderA_ch1; pinEncoderB_running = pinEncoderB_ch1; pinMotorMinus_running = pinMotorMinus_ch1; pinMotorPlus_running = pinMotorPlus_ch1; pinEn_running = pinEn_ch1; encoderValue = &encoderValue_ch1; break;
    case 2: pinEncoderA_running = pinEncoderA_ch2; pinEncoderB_running = pinEncoderB_ch2; pinMotorMinus_running = pinMotorMinus_ch2; pinMotorPlus_running = pinMotorPlus_ch2; pinEn_running = pinEn_ch2; encoderValue = &encoderValue_ch2; break;
    case 3: pinEncoderA_running = pinEncoderA_ch3; pinEncoderB_running = pinEncoderB_ch3; pinMotorMinus_running = pinMotorMinus_ch3; pinMotorPlus_running = pinMotorPlus_ch3; pinEn_running = pinEn_ch3; encoderValue = &encoderValue_ch3; break;
    case 4: pinEncoderA_running = pinEncoderA_ch4; pinEncoderB_running = pinEncoderB_ch4; pinMotorMinus_running = pinMotorMinus_ch4; pinMotorPlus_running = pinMotorPlus_ch4; pinEn_running = pinEn_ch4; encoderValue = &encoderValue_ch4; break;
    case 5: pinEncoderA_running = pinEncoderA_ch5; pinEncoderB_running = pinEncoderB_ch5; pinMotorMinus_running = pinMotorMinus_ch5; pinMotorPlus_running = pinMotorPlus_ch5; pinEn_running = pinEn_ch5; encoderValue = &encoderValue_ch5; break;
    case 6: pinEncoderA_running = pinEncoderA_ch6; pinEncoderB_running = pinEncoderB_ch6; pinMotorMinus_running = pinMotorMinus_ch6; pinMotorPlus_running = pinMotorPlus_ch6; pinEn_running = pinEn_ch6; encoderValue = &encoderValue_ch6; break;
  }

  InitialEncoderState();
  attachInterrupt(digitalPinToInterrupt(pinEncoderA_running), ReadEncoderState, CHANGE);
  attachInterrupt(digitalPinToInterrupt(pinEncoderB_running), ReadEncoderState, CHANGE);
}

unsigned long U8toU16(int v1, int v2) {
  unsigned long y1, y2, result;
  y1 = (unsigned long)(v1) << 8; y2 = (unsigned long)(v2);
  result = y1 + y2;
  return result;
}

unsigned long U8toU32(int v1, int v2, int v3, int v4) {
  unsigned long y1, y2, y3, y4, y5;
  y1 = (unsigned long)(v1) << 24; y2 = (unsigned long)(v2) << 16;
  y3 = (unsigned long)(v3) << 8;  y4 = (unsigned long)(v4);
  y5 = y1 + y2 + y3 + y4;
  return y5;
}

void U32toU8(unsigned long value){
  U8_a = value >> 24; U8_b = value >> 16; U8_c = value >> 8; U8_d = value;  
}
