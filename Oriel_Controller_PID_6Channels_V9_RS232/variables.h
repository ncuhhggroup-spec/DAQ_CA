#define COMMANDLENGTH 15
#define RESPONDLENGTH 10

// serial port parameters------------------------------------------------------------------------------------
unsigned char Command[COMMANDLENGTH];       // The Current Command For The Arduino To Process
byte Respond[8] = {0, 0, 0, 0, 0, 0, 0, 0}; // The Current Respond For The Arduino To Process

//-----------------------------------------------------------------------------------------------------------

// DueFlashStorage parameters------------------------------------------------------------------------------------
// name of the controller
unsigned char name_due = 0x01;
//-----------------------------------------------------------------------------------------------------------

// motor control parameters-------------------------------------------------------------------------------------------------
byte U8_a, U8_b, U8_c, U8_d;
byte position_direction = 0;
byte channel_num = 1;

int thresholdValue = 10; // Threshold for "Target Reached"
byte fullpowercount = 0;

// --- MOTOR POWER LIMIT ---
// Max PWM value (0-255). 
// 100 = ~39% Duty Cycle (Current Limit)
byte pwmSpeedMax = 100;              

byte pwmSpeedValue = 1;
// Speed_lowest is no longer used for clamping, but kept for compatibility
byte Speed_lowest = 100; 
int slowarea_num = 500;

// --- NEW PID & CONTROL PARAMETERS ---
// Directional P Gains (Proportional)
float Kp_Pos = 0.020;  // Gain when moving Positive
float Kp_Neg = 0.020;  // Gain when moving Negative

// Directional D Gains (Derivative)
float Kd_Pos = 0.0;
float Kd_Neg = 0.0;

// Minimum PWM to overcome static friction (Stiction)
// Crucial for low-speed movement near target
int minPWM = 60; 

// Loop timing (Non-blocking)
unsigned long lastPIDTime = 0;
int loopTimeMS = 5; // Run PID loop every 5ms (200Hz)

// Backlash Compensation & Motion Profiling
const int BACKLASH_OVERSHOOT_STEPS = 0; // Steps to overshoot before returning
long finalTarget = 0;      // The ultimate destination
long tempTarget = 0;       // The "rabbit" the PID chases (Ramp Generator)
long rampStep = 5;         // Max steps to change tempTarget per loop (Velocity Limit)
long prevError = 0;        // For Derivative calculation

// Using pointer to send encoder signal to each channels
int *encoderValue;
int stateEncoderB_running = 0;
int stateEncoderA_running = 0;
int valueEncoder_present = 2; 
int valueEncoder_previous = 1; 
int diffEncoder = 1; 
bool runningstatus         = false;
bool motorlimit            = false;

// Function Prototypes
void count(void);
void MotorRun(void);
void processSerialCommands(Stream& serialPort);
void SelectMotorChannel(int ch);
void InitialEncoderState(void);
void ReadEncoderState(void);
unsigned long U8toU16(int v1, int v2, int v3, int v4);
void U32toU8(unsigned long value);

int encoderValue_ch1 = 0;
int encoderValue_ch2 = 0;
int encoderValue_ch3 = 0;
int encoderValue_ch4 = 0;
int encoderValue_ch5 = 0;
int encoderValue_ch6 = 0;

//-----------------------------------------------------------------------------------------------------------

//Pin Number-------------------------------------------------------------------------------------------------
byte pinEncoderA_running = 30;
byte pinEncoderB_running = 31;
byte pinMotorMinus_running = 2;
byte pinMotorPlus_running = 3;
byte pinEn_running = 42;
long targetValue = 0; // Changed to long for safety

byte pinEncoderA_ch1 = 30;
byte pinEncoderB_ch1 = 31;
byte pinMotorMinus_ch1 = 2;
byte pinMotorPlus_ch1 = 3;
byte pinEn_ch1 = 42;

byte pinEncoderA_ch2 = 32;
byte pinEncoderB_ch2 = 33;
byte pinMotorMinus_ch2 = 4;
byte pinMotorPlus_ch2 = 5;
byte pinEn_ch2 = 43;

byte pinEncoderA_ch3 = 34;
byte pinEncoderB_ch3 = 35;
byte pinMotorMinus_ch3 = 6;
byte pinMotorPlus_ch3 = 7;
byte pinEn_ch3 = 44;

byte pinEncoderA_ch4 = 36;
byte pinEncoderB_ch4 = 37;
byte pinMotorMinus_ch4 = 8;
byte pinMotorPlus_ch4 = 9;
byte pinEn_ch4 = 45;

byte pinEncoderA_ch5 = 38;
byte pinEncoderB_ch5 = 39;
byte pinMotorMinus_ch5 = 10;
byte pinMotorPlus_ch5 = 11;
byte pinEn_ch5 = 46;

byte pinEncoderA_ch6 = 40;
byte pinEncoderB_ch6 = 41;
byte pinMotorMinus_ch6 = 12;
byte pinMotorPlus_ch6 = 13;
byte pinEn_ch6 = 47;

byte HbridgeHigh = pinMotorMinus_running;
byte HbridgeLow = pinMotorPlus_running;
