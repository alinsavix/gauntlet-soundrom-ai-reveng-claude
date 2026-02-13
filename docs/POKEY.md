# POKEY
"POKEY", an acronym for "Pot Keyboard Integrated Circuit", is a digital I/O chip designed by Doug Neubauer at Atari. POKEY combines functions for reading paddle controllers (potentiometers) and keyboards, as well as sound generation and a source for Pseudorandom number generator|pseudorandom numbers. It produces four voices of distinctive square wave audio, either as clear tones or modified with distortion settings.

POKEY chips are used for audio in many arcade video games of the 1980s including Gauntlet.. Some Atari arcade systems use multi-core versions with 2 or 4 POKEYs in a single package for more audio channels.

The version of the POKEY used in Gauntlet is the 137324-1221, which is a quad-core POKEY, though it is unknown if all four cores are used.

## Features
* Audio
** 4 semi-independent audio channels
** Channels may be configured as one of: Four 8-bit channels, two 16-bit channels, or one 16-bit channel and two 8-bit channels.
** Per-channel loudness, frequency, and waveform (square wave with variable duty cycle, or pseudorandom noise)
** 15&kHz or 64kHz frequency divider.
** Two channels may be driven at the CPU clock frequency.
** [[High-pass filter]]
* High Resolution Timers (audio channels 1, 2, and 4 can be configured to cause timer interrupts when they cross zero)
* Random number generator (8 bits of a 17-bit polynomial counter can be read)
* Serial I/O port
* Eight [[Interrupt request|IRQ]] interrupts


## Registers
The Gauntlet arcade game maps POKEY to the 0x1800 - 0x180f memory range.

POKEY provides 29 Read/Write registers controlling Sound, Paddle input, keyboard input, serial input/output, and interrupts. Many POKEY register addresses have dual purposes performing different functions as a Read vs a Write register. Therefore, no code should read Hardware registers expecting to retrieve the previously written value.

The registers are as follows (in CSV form):

Register,Description,Direction,Address
AUDF1,Audio,Channel,1,Frequency,Write,0x1800
POT0,Potentiometer,(Paddle),0,Read,0x1800
AUDC1,Audio,Channel,1,Control,Write,0x1801
POT1,Potentiometer,(Paddle),1,Read,0x1801
AUDF2,Audio,Channel,2,Frequency,Write,0x1802
POT2,Potentiometer,(Paddle),2,Read,0x1802
AUDC2,Audio,Channel,2,Control,Write,0x1803
POT3,Potentiometer,(Paddle),3,Read,0x1803
AUDF3,Audio,Channel,3,Frequency,Write,0x1804
POT4,Potentiometer,(Paddle),4,Read,0x1804
AUDC3,Audio,Channel,3,Control,Write,0x1805
POT5,Potentiometer,(Paddle),5,Read,0x1805
AUDF4,Audio,Channel,4,Frequency,Write,0x1806
POT6,Potentiometer,(Paddle),6,Read,0x1806
AUDC4,Audio,Channel,4,Control,Write,0x1807
POT7,Potentiometer,(Paddle),7,Read,0x1807
AUDCTL,Audio,Control,Write,0x1808
ALLPOT,Read,8,Line,POT,Port,State,Read,0x1808
STIMER,Start,Timers,Write,0x1809
KBCODE,Keyboard,Code,Read,0x1809
SKREST,Reset,Serial,Status,(SKSTAT),Write,0x180A
RANDOM,Random,Number,Generator,Read,0x180A
POTGO,Start,POT,Scan,Sequence,Write,0x180B
SEROUT,Serial,Port,Data,Output,Write,0x180D
SERIN,Serial,Port,Data,Input,Read,0x180D
IRQEN,Interrupt,Request,Enable,Write,0x180E
IRQST,IRQ,Status,Read,0x180E
SKCTL,Serial,Port,Control,Write,0x180F
SKSTAT,Serial,Port,Status,Read,0x180F

### Register Explanations
0 - Bit must be 0
1 - Bit must be 1
? - Bit may be either 0 or 1, and is used for a purpose.
- - Bit is unused, or should not be expected to be a certain value
label - Refer to a later explanation for the purpose of the bit.

## Audio
POKEY contains four audio channels with separate frequency, noise and voice level controls.

Each channel has an 8-bit frequency divider and an 8-bit register to select noise and volume.
*AUDF1 to AUDF4 – frequency register (AUDio Frequency)
*AUDC1 to AUDC4 – volume and noise register (AUDio Control)
*AUDCTL – general register, which controls generators (AUDio ConTroL)

POKEY's sound is distinctive: when the four channels are used independently, there is noticeable detuning of parts of the 12-tone equal temperament scale, due to lack of pitch accuracy. Channels may be paired for higher accuracy; in addition, multiple forms of distortion are available, allowing a thicker sound. The distortion is primarily used in music for bass parts.


### Audio Channel Frequency

The AUDF* registers control the frequency or pitch of the corresponding sound channels. The AUDF* values also control the POKEY hardware timers useful for code that must run in precise intervals more frequent than the vertical blank.

Each AUDF* register is an 8-bit value providing a countdown timer or divisor for the pulses from the POKEY clock. So, smaller values permit more frequent output of pulses from POKEY, and larger values, less frequent. The values 0x00 to 0xFF are incremented by POKEY to range from 0x01 to 0x100.  The actual audible sound pitch is dependent on the POKEY clock frequency and distortion values chosen. See Audio Channel Control and AUDCTL.


#### AUDF1 0x1800 Write
Audio Channel 1 Frequency

#### AUDF2 0x1802 Write
Audio Channel 2 Frequency

#### AUDF3 0x1804 Write
Audio Channel 3 Frequency

#### AUDF4 0x1806 Write
Audio Channel 4 Frequency


! Bit 7 !! Bit 6 !! Bit 5 !! Bit 4 !! Bit 3 !! Bit 2 !! Bit 1 !! Bit 0
| ? || ? || ? || ? || ? || ? || ? || ?


### Audio Channel Control

The Audio Channel control registers provide volume and distortion control over individual sound channels.  Audio may also be generated independently of the POKEY clock by direct volume manipulation of a sound channel which is useful for playing back digital samples.

#### AUDC1 0x1801 Write
Audio Channel 1 Control

#### AUDC2 0x1803 Write
Audio Channel 2 Control

#### AUDC3 0x1805 Write
Audio Channel 3 Control

#### AUDC4 0x1807 Write
Audio Channel 4 Control

! Bit 7 !! Bit 6 !! Bit 5 !! Bit 4 !! Bit 3 !! Bit 2 !! Bit 1 !! Bit 0
| Noise 2 || Noise 1 || Noise 0 || Force Volume || Volume 3 || Volume 2 || Volume 1 || Volume 0


Bit 0-3: Control over volume level, from 0 to F.

Bit 4: Forced volume-only output. When this bit is set the channel ignores the AUDF timer, noise/distortion controls, and high-pass filter.  Sound is produced only by setting volume bits 0:3 . This feature was used to create digital audio via pulse-code modulation.

Bit 5-7: Shift register settings for noises/distortion.  Bit values described below:

! Noise Value !! Bits Value !! Description
| 0 0 0 ||  $00 || 5-bit then 17-bit polynomials
| 0 0 1 ||  $20 || 5-bit poly only
| 0 1 0 ||  $40 || 5-bit then 4-bit polys
| 0 1 1 ||  $60 || 5-bit poly only
| 1 0 0 ||  $80 || 17-bit poly only
| 1 0 1 ||  $A0 || no poly (pure tone)
| 1 1 0 ||  $C0 || 4-bit poly only
| 1 1 1 ||  $E0 || no poly (pure tone)

Generating random noises is served by reading 8 bits from top of 17-bit shift register.  That registers are driven by frequency 1.79MHz for NTSC or 1.77MHz for PAL. Its outputs can by used independently by each audio channels' divider rate.

### AUDCTL 0x1808 Write

Audio Control allows the choice of clock input used for the audio channels, control over the high-pass filter feature, merging two channels together allowing 16-bit frequency accuracy, selecting a high frequency clock for specific channels, and control over the "randomness" of the polynomial input.

! Bit 7 !! Bit 6 !! Bit 5 !! Bit 4 !! Bit 3 !! Bit 2 !! Bit 1 !! Bit 0
| 17 vs 9 Poly || CH1 1.79 || CH3 1.79 || CH2 + 1 || CH4 + 3 || FI1 + 3 || FI2 + 4 || 64 vs 15kHz

"1" means "on", if not described:

Bit 0: $01: (15kHz), choice of frequency divider rate "0" - 64kHz, "1" - 15kHz
Bit 1: $02: (FI2 + 4), high-pass filter for channel 2 rated by frequency of channel 4
Bit 2: $04: (FI1 + 3), high-pass filter for channel 1 rated by frequency of channel 3
Bit 3: $08: (CH4 + 3), connection of dividers 4+3 to obtain 16-bit accuracy
Bit 4: $10: (CH2 + 1), connection of dividers 2+1 to obtain 16-bit accuracy
Bit 5: $20: (CH3 1.79), set channel 3 frequency "0" is 64kHz. "1" is 1.79MHz NTSC or 1.77MHz PAL
Bit 6: $40: (CH1 1.79),  set channel 1 frequency "0" is 64kHz. "1" is 1.79MHz NTSC or 1.77MHz PAL
Bit 7: $80: (POLY 9), switch shift register "0" - 17-bit, "1" – 9-bit

All frequency dividers (AUDF) can be driven at the same time by 64kHz or 15kHz rate.

Frequency dividers 1 and 3 can be alternately driven by CPU clock (1.79MHz NTSC, 1.77MHz PAL).
Frequency dividers 2 and 4 can be alternately driven by output of dividers 1 and 3.
In this way, POKEY makes possible connecting of 8-bit channels to create sound with 16-bit accuracy.

Possible channel configurations:
* four 8-bit channels
* two 8-bit channels and one 16-bit channel
* two 16-bit channels

==Potentiometers==
POKEY has eight analog to digital converter ports most commonly used for potentiometers, also known as Paddle Controllers.  The analog inputs are also used for the Touch Tablet controller, and the 12-button, video game Keyboard Controllers. Each input has a drop transistor, which can be set on or off from software.

### POT0 0x1800 Read
SHADOW: PADDL0 $0270

Paddle Controller 0 Input

### POT1 0x1801 Read

Paddle Controller 1 Input

### POT2 0x1802 Read

Paddle Controller 2 Input

### POT3 0x1803 Read

Paddle Controller 3 Input

### POT4 0x1804 Read

Paddle Controller 4 Input

### POT5 0x1805 Read

Paddle Controller 5 Input

### POT6 0x1806 Read

Paddle Controller 6 Input

### POT7 0x1807 Read

Paddle Controller 7 Input

! Bit 7 !! Bit 6 !! Bit 5 !! Bit 4 !! Bit 3 !! Bit 2 !! Bit 1 !! Bit 0
| ? || ? || ? || ? || ? || ? || ? || ?


Each input has 8-bit timer, counting time when each TV line is being displayed. This had the added advantage of allowing the value read out to be fed directly into screen coordinates of objects being driven by the paddles.  The Atari Paddle values range from 0 to 228, though the maximum possible is 244.  The Paddle controller reads 0 when turned to its maximum clockwise position, and returns increasing values as it is turned counter-clockwise ending at its maximum value.

The Paddle reading process begins by writing to POTGO, which resets the POT* values to 0, the ALLPOT value to $FF, and discharges the potentiometer read capacitors.  The POT* values increment as they are being scanned until reaching the resistance value of the potentiometer.  When the Paddle reading is complete the corresponding bit in ALLPOT is reset to 0.

The Paddle scanning process can take the majority of a video frame to complete.  The Atari Operating System takes care of Paddle reading automatically. The Paddles are read and paddle scanning initiated during the stage 2 vertical blank.  Paddle values are copied to shadow registers.  (Note that Paddle triggers are actually joystick direction input read from PIA.)

A faster mode of scanning the Paddles is possible by setting a bit in SKCTL.  The reading sequence completes in only a couple scan lines, but the value is less accurate.

### ALLPOT 0x1808 Read
Potentiometer Scanning Status

! Bit 7 !! Bit 6 !! Bit 5 !! Bit 4 !! Bit 3 !! Bit 2 !! Bit 1 !! Bit 0
| Paddle 7 || Paddle 6 || Paddle 5 || Paddle 4 || Paddle 3 || Paddle 2 || Paddle 1 || Paddle 0

Each bit corresponds to one potentiometer input (the POT* registers).  When paddle scanning is started by writing to POTGO, each paddle's bit in ALLPOT is set to 1.  When a paddle's scan is complete the corresponding bit in ALLPOT is reset to 0 indicating the value in the associated POT* register is now valid to read.

### POTGO 0x180B Write
Start Potentiometer Scan

! Bit 7 !! Bit 6 !! Bit 5 !! Bit 4 !! Bit 3 !! Bit 2 !! Bit 1 !! Bit 0
| - || - || - || - || - || - || - || -

Writing to POTGO initiates the potentiometer (Paddle) scanning process.  This resets the POT* values to 0, the ALLPOT value to $FF, and discharges the potentiometer read capacitors.  As each potentiometer scan completes the bit corresponding to the potentiometer in ALLPOT is cleared indicating the value of the associated POT* register is valid for reading.

## Serial input output port
Contains:
* serial input line
* serial output line
* serial clock output line
* two-way serial clock data line
* registers SKREST, SEROUT, SERIN, SKCTL, SKSTAT

POKEY is a sort of UART. Usually one of the doubled audio channels is used as baud rate generator. The standard baud rate is 19.2 kbit/s, the maximum possible baud rate is 127 kbit/s. A byte put into the SEROUT register is automatically sent over the serial bus. The data frame contains 10 bits: 1 start bit, 8 data bits, 1 stop bit. The voltage levels are 0V (logical 0) and +4V (logical 1). It is possible to connect the Atari serial port with an RS-232 port by means of a simple voltage converter.

Each I/O operation causes POKEY's internal shift registers to change value, so when programming for POKEY, it is necessary to re-initialise some values after each operation is carried out.

### SKREST 0x180A Write
Reset Serial Port Status (SKSTAT).

! Bit 7 !! Bit 6 !! Bit 5 !! Bit 4 !! Bit 3 !! Bit 2 !! Bit 1 !! Bit 0
| - || - || - || - || - || - || - || -


A write to this register will reset bits 5 through 7 of SKSTAT which are latches to 1.  The latches flag keyboard overrun, Serial data input overrun, and Serial data input frame error.

### SEROUT 0x180D Write
Serial port data output byte.

! Bit 7 !! Bit 6 !! Bit 5 !! Bit 4 !! Bit 3 !! Bit 2 !! Bit 1 !! Bit 0
| - || - || - || - || - || - || - || -

This is a parallel "holding" register for the eight bit (one byte) value that will be transferred to the serial shift register for output one bit at a time. When the port is ready to accept data for output a Serial Data Out interrupt informs the Operating System that it can write a byte to this output register.

### SERIN 0x180D Read
Serial port data input byte.

! Bit 7 !! Bit 6 !! Bit 5 !! Bit 4 !! Bit 3 !! Bit 2 !! Bit 1 !! Bit 0
| - || - || - || - || - || - || - || -

Like SEROUT, also a parallel "holding" register.  This holds the eight bit (one byte) value assembled by the serial shift register reading the data input one bit at a time.  When a full byte is read a Serial Data In interrupt occurs informing the Operating System that it can read the byte from this register.

### SKCTL 0x180F Write
Serial Port Control

! Bit 7 !! Bit 6 !! Bit 5 !! Bit 4 !! Bit 3 !! Bit 2 !! Bit 1 !! Bit 0
| Serial Break || Serial Mode2 || Serial Mode1 || Serial Mode0 || Serial Two-Tone || Fast Pot Scan || Enable KB Scan || KB debounce

Bit 0: Enable "debounce" scanning which is intended to eliminate noise or jitter from mechanical switches.  A value of 1 enables POKEY to use an internal comparison register while scanning keys.  A key must be detected in two simultaneous scans before it is identified as pressed, and it must be seen released for two consecutive scans to be considered released.  This should be enabled to maintain normal keyboard handling with the Operating System.

Bit 1: Set to 1 to enable keyboard scanning.  This should be enabled to maintain normal keyboard handling with the Operating System.

Bit 2: Set to 1 to enable fast, though less accurate Potentiometer scanning.  Fast Pot scanning increments the counter on every cycle and returns a usable result within two scan lines.  The Operating System uses the slow Pot Scanning which increments the counter once every 114 cycles (scan line) taking a frame (1/60th second) to produce a result.  The OS reads the Pot values during its Vertical Blank Interrupt (VBI) and copies the result to the potentiometer Shadow registers in RAM.  It then resets POTGO for the next read during the next VBI.

Bit 3: Enable Serial port two-tone mode.  When enabled, 1 and 0 bits output to the SIO bus are replaced by tones set by timers 1 and 2.  This is ordinarily used for writing analog tones representing digital data to cassette tape.

Bit 4-6: Clock Timing Control for serial port operation. Bit values described below:

! Port Control [6:4] !! Bits Value !! Input Clock !! Output Clock !! Bidirectional Clock
| 0 0 0 ||  $00 || External || External || Input
| 0 0 1 ||  $10 || Channels 3+4 (async) || External || Input
| 0 1 0 ||  $20 || Channel 4 || Channel 4 || Output Channel 4
| 0 1 1 ||  $30 || Channel 3+4 (async) || Channel 4 (async) || Input
| 1 0 0 ||  $40 || External || Channel 4 || Input
| 1 0 1 ||  $50 || Channel 3+4 (async) || Channel 4 (async) || Input
| 1 1 0 ||  $60 || Channel 4 || Channel 2 || Output Channel 4
| 1 1 1 ||  $70 || Channel 3+4 (async) || Channel 2 || Input

Bit 7: Forces a known 0 output, so that timer 2 can reset timer 1 in two-tone serial output mode.

### SKSTAT 0x180F Read
Serial Port Status

! Bit 7 !! Bit 6 !! Bit 5 !! Bit 4 !! Bit 3 !! Bit 2 !! Bit 1 !! Bit 0
| Serial in frame error || Serial in overrun || KB overrun || Read Data ready || Shift Key || Last Key Still Pressed || Serial Input Busy || -

### KBCODE 0x1809 Read

Keyboard Code

## Eight IRQ interrupts
BREAK: Break (BREAK key interrupt)
K: Keyboard (keyboard interrupt)
SIR: if Serial Input Ready (read interrupt from serial rail)
ODN: if Output Data Needed (write interrupt from serial rail)
XD: if eXmitend Data (serial transmission end interrupt)
T1: Timer 1, timer 1 interrupt
T2: Timer 2, timer 2 interrupt
T4: Timer 4, timer 4 interrupt

Interrupts can be set on or off from software by register IRQEN.
IRQSTAT register contains interrupts status.

## Keyboard

Six key register of actually pushed keys (K0 K5), which contains values from 00 to 3F. Contains 2 control values. One of them acts as decoder of all 6 values. Second control values is used to decode special key values&nbsp;— CTRL, SHIFT and BREAK.
