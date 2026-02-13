# Gauntlet Sound ROM - Complete Analysis Summary

**ROM File**: `soundrom.bin` (48KB)
**Architecture**: 6502 CPU, hand-written assembly
**CPU Address Range**: 0x4000-0xFFFF
**Analysis Date**: 2026-02-05 through 2026-02-10
**Analysis Tool**: radare2 via MCP

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Memory Map](#memory-map)
3. [Function Reference](#function-reference)
4. [Major Subsystems](#major-subsystems)
5. [Data Tables](#data-tables)
6. [Interrupt System](#interrupt-system)
7. [Unknown/Unexplored Areas](#unknown-areas)
8. [Sequence Data Format](#sequence-data-format-phase-13)
9. [Implementation Notes](#implementation-notes)

---

## Architecture Overview

### System Components

The Gauntlet sound ROM implements a sophisticated multi-chip audio coprocessor:

- **6502 CPU** @ ~2MHz
- **POKEY** (0x1800-0x180F): 4-channel programmable sound generator (SFX)
- **YM2151** (0x1810-0x1811): 8-channel FM synthesizer (Music)
- **TMS5220** (0x1820): Speech synthesizer with LPC (Voice)
- **IRQ Acknowledge** (0x1830): Write to reset 6502 IRQ line
- **Main CPU Interface**: Commands via 0x1010, Status via 0x1000/0x1030

### Key Design Principles

1. **Interrupt-Driven Audio**: 240Hz IRQ drives all sound generation
2. **Alternating Updates**: POKEY and YM2151 alternate to reduce CPU load
3. **Table-Driven Dispatch**: 219 commands via 15 handlers (two-level lookup)
4. **Priority System**: 30 logical sound channels with preemption
5. **Unified Playback**: Music and speech share infrastructure
6. **Robust Buffering**: Circular buffers prevent glitches

### Overall System Flow

```
RESET → Initialize → Main Loop ──┐
                                  │
                    ┌─────────────┴─────────────┐
                    │                           │
              Main Loop (poll)             Interrupts
                    │                           │
                    ↓                           ↓
          ┌──────────────────┐      ┌──────────────────┐
          │ Read Cmd Buffer  │      │  IRQ (240Hz)     │
          │ cmd_dispatch     │      │   - POKEY (120Hz)│
          │  → Handlers      │      │   - YM2151(120Hz)│
          │    - POKEY SFX   │      │   - TMS5220(240) │
          │    - YM2151 Mus  │      │                  │
          │    - TMS5220 Spc │      │  NMI (events)    │
          │    - Control     │      │   - Read 0x1010  │
          └──────────────────┘      │   - Queue cmds   │
                                    └──────────────────┘
```

---

## Memory Map

### Complete Address Space

```
0x0000 - 0x0FFF    RAM (4KB)
  0x0000 - 0x00FF    Zero-page (fast access)
    0x00: IRQ frame counter
    0x01: Initialization complete flag
    0x02: Error flags
    0x04-0x05: NMI buffer pointer
    0x08-0x09: Hardware indirect pointer (POKEY/YM2151 base)
    0x0E-0x0F: Utility pointer
    0x10-0x13: Checksum/utility variables
    0x28-0x29: Volume/control registers
    0x2A: Timer countdown
    0x2B-0x2C: Music/speech sequence pointer
    0x2D-0x2E: Sequence length
    0x2F: Music/speech active flag
    0x30-0x35: Music state variables
    0x36-0x39: Coin counter LED pulse accumulators (4 channels)
    0x3E-0x41: Coin counter LED envelope states (attack/decay)
    0x42: Coin counter LED frame counter
    0x44: Coin counter/LED combined output byte

  0x0100 - 0x01FF    Stack (6502 standard)

  0x0200 - 0x021F    Command Buffer
    0x0200-0x020F: Circular command queue (16 entries)
    0x0210: Read pointer
    0x0211: Write pointer
    0x0212-0x0213: NMI buffer state
    0x0214-0x0223: Output buffer to main CPU
    0x0224-0x0226: Output buffer pointers

  0x0228 - 0x083F    Sound Channel State (30 channels)
    0x0228-0x0245: Active command IDs
    0x0246-0x0281: Data pointers (per channel)
    0x0282-0x0839: Multiple state arrays
    0x07E6-0x0809: Channel linked lists
    0x0810-0x083B: Work area
    0x0832-0x0833: Speech queue pointers
    0x0834-0x083B: Speech command queue (8 entries)

  0x0840 - 0x0FFF    Extended State
    0x083C-0x089F: YM2151 operator data
    0x0390-0x03AD: Channel priority/status

0x1000 - 0x1FFF    Hardware I/O (Sparse)
  0x1000: Status output to main CPU (write triggers IRQ to main CPU + data latch)
  0x1002-0x1003: Aliases of 0x1000 (low 4 address bits not decoded)
  0x100B-0x100C: Aliases of 0x1000 (low 4 address bits not decoded)
  0x1010: Command input from main CPU (latched on NMI)
  0x1020: Volume mixer (bits 7-5: speech, 4-3: effects, 2-0: music)
  0x1030: Status/control register (read: coin/status bits; write: YM2151 reset)
  0x1032: TMS5220 reset (write, data is don't-care)
  0x1033: Speech squeak (write, changes TMS5220 oscillator frequency)
  0x1034: Coin counter LED output, channels 2-3 (write, from control_register_update)
  0x1035: Coin counter LED output, channels 0-1 (write, from control_register_update)

  0x1800-0x180F: POKEY Registers
    0x1800: AUDF1 (channel 1 frequency)
    0x1801: AUDC1 (channel 1 control/volume)
    0x1802: AUDF2 (channel 2 frequency)
    0x1803: AUDC2 (channel 2 control/volume)
    0x1804: AUDF3 (channel 3 frequency)
    0x1805: AUDC3 (channel 3 control/volume)
    0x1806: AUDF4 (channel 4 frequency)
    0x1807: AUDC4 (channel 4 control/volume)
    0x1808: AUDCTL (audio control register)

  0x1810: YM2151 Register Select
  0x1811: YM2151 Data Write

  0x1820: TMS5220 Data Write (speech synthesis)
  0x1830: IRQ Acknowledge (write resets 6502 IRQ line)

0x1030 READ Bit Map (per schematic):
  Bit 0-3: Coin inserted (slots 1-4)
  Bit 4:   Self-test enable
  Bit 5:   TMS5220 speech chip ready
  Bit 6:   Sound buffer full
  Bit 7:   Main CPU (68010) output buffer full

0x1020 Volume Mixer (per schematic):
  Bits 7-5: Speech volume (TMS5220)
  Bits 4-3: Effects volume (POKEY)
  Bits 2-0: Music volume (YM2151)

0x4000 - 0xFFFF    ROM (48KB)
  0x4000-0x5CFF: Code (functions, handlers)
  0x5D00-0x6FFF: Data tables (command/SFX tables)
  0x7000-0x9FFF: Sound sequence data (SFX waveforms)
  0xA000-0xFECD: Music & speech data (LPC frames)
  0xFECE-0xFFF5: Unused (zero-padded, 296 bytes)
  0xFFF6-0xFFF9: Mystery bytes (8C FF 00 00, unreferenced)
  0xFFFA-0xFFFF: Interrupt vectors
```

---

## Function Reference

### Complete Function List (51+ Verified Functions)

#### System & Boot Functions

| Address | Name | Size | Purpose |
|---------|------|------|---------|
| 0x5A25 | **reset_handler** | 46 | Reset vector - waits for main CPU ready signal |
| 0x4002 | **init_main** | Large | Main initialization: stack, RAM test, hardware init |
| 0x5A0B | **init_hardware_regs** | Small | Initialize hardware control registers (0x1000-0x100C) |
| 0x5833 | **init_sound_state** | Medium | Initialize sound system state variables |
| 0x41E6 | **clear_sound_buffers** | Medium | Zero all sound channel buffers (30 channels) |
| 0x415F | **checksum_ram** | Medium | Verify memory integrity via checksum |
| 0x4142 | **ram_error_handler** | Small | Handle RAM test failures |

#### Main Loop & Dispatch

| Address | Name | Size | Purpose |
|---------|------|------|---------|
| 0x40C8 | **main_loop** | Medium | Main execution loop - polls command buffer |
| 0x432E | **command_dispatcher** | Small | Two-level command dispatch (219 commands → 15 handlers) |

#### Interrupt Handlers

| Address | Name | Size | Purpose |
|---------|------|------|---------|
| 0x4187 | **irq_handler** | Medium | Real-time audio processing @ 240Hz |
| 0x57B0 | **nmi_handler** | Medium | Command input from main CPU (event-driven) |
| 0x57F0 | **nmi_command_input** | Medium | Validate & buffer commands in NMI |

#### Command Handler Functions (Type 0-14)

| Address | Name | Purpose |
|---------|------|---------|
| 0x4347 | **handler_type_0** | Parameter shift (ASL A × 2) |
| 0x434C | **handler_type_1** | Set variable from data table (never dispatched) |
| 0x4359 | **handler_type_2** | Add to variable from data table (never dispatched) |
| 0x4369 | **handler_type_3** | Jump table dispatch for special commands |
| 0x4374 | **handler_kill_by_status** | Kill channels by status pattern match (never dispatched) |
| 0x438D | **handler_stop_sound** | Stop specific named sound (0x21, 0x2F, 0x39) |
| 0x43AF | **handler_stop_chain** | Stop channel chain by group (never dispatched) |
| 0x44DE | **handler_type_7** | **Main POKEY SFX** (~90 commands, priority system) |
| 0x4445 | **handler_type_8** | Queue commands to main CPU output buffer |
| 0x43D4 | **handler_fadeout_sound** | Fade out specific sound (0x3C "Theme Fade Out") |
| 0x440B | **handler_fadeout_by_status** | Fade out by status match (0x41 "Treasure Fade Out") |
| 0x4439 | **handler_type_11** | **YM2151 Music/Speech entry** (~112 commands) |
| 0x4461 | **handler_channel_control** | Complex channel manipulation (never dispatched) |
| 0x4619 | **handler_type_13** | Update hardware control register 0x1020 |
| 0x4618 | **handler_type_14** | Null handler (single RTS, never dispatched) |

#### Channel Management Functions (Phase 12)

| Address | Name | Size | Purpose |
|---------|------|------|---------|
| 0x4295 | **channel_list_init** | 49B | Build free-channel linked list (1→2→...→N→0) |
| 0x42C6 | **channel_list_follow** | 17B | Follow linked-list pointer to next channel |
| 0x42D7 | **channel_state_ptr_calc** | 34B | Compute ZP pointer to channel's 4-byte state record |
| 0x42F9 | **channel_list_unlink** | 53B | Remove channel from active linked lists |
| 0x5059 | **channel_find_active_cmd** | 22B | Search for channel playing specific command |
| 0x506F | **channel_dispatch_by_type** | 12B | Dispatch handler by type from table |

#### Core State Machine (Phase 13)

| Address | Name | Size | Purpose |
|---------|------|------|---------|
| 0x4651 | **channel_state_machine** | ~1300B | **Core engine**: sequence interpreter, envelope processing, frame-by-frame playback |

#### Sequence Engine Functions (Phases 12-13)

| Address | Name | Size | Purpose |
|---------|------|------|---------|
| 0x5029 | **seq_opcode_dispatch** | 30B | Bytecode interpreter: dispatch 59 opcodes via jump table |
| 0x5047 | **seq_advance_read** | 18B | Advance 16-bit sequence pointer + read next byte (19 callers!) |
| 0x5181 | **channel_apply_volume** | 22B | Apply volume adjustment to channel output |
| 0x5444 | **seq_var_classifier** | 109B | Map variable index to channel state array |

#### POKEY Pipeline Functions (Phase 14)

| Address | Name | Size | Purpose |
|---------|------|------|---------|
| 0x4B6B | **envelope_process_freq** | 171B | Frequency envelope: 24-bit pitch modulation |
| 0x4D02 | **pokey_channel_mix** | 250B | Mix two channel groups, select highest-priority output |
| 0x4DFC | **pokey_update_registers** | 77B | Write POKEY AUDFx/AUDCx registers via indirect addressing |
| 0x4E1B | **pokey_write_registers** | 77B | Write computed values to physical POKEY registers |
| 0x500D | **channel_dispatcher** | Medium | Route to POKEY/YM2151/RAM based on channel index |

#### YM2151 Pipeline Functions (Phases 14-15)

| Address | Name | Size | Purpose |
|---------|------|------|---------|
| 0x4C16 | **ym2151_update_channel_state** | 236B | Copy channel state to shadow area + vibrato processing |
| 0x4FD6 | **ym2151_channel_update** | Medium | Write 8 YM2151 registers sequentially |
| 0x4E68 | **ym2151_write_operator** | Medium | Write 3-5 registers for FM operator config |
| 0x4FF0 | **ym2151_wait_ready** | Small | Busy-wait for YM2151 (checks bit 7 of 0x1811) |
| 0x558F | **ym2151_load_voice** | 132B | Load complete voice/instrument definition (FM patch) |
| 0x5676 | **ym2151_write_reg_indirect** | 20B | Generic register write with shadow storage |
| 0x5715 | **ym2151_apply_detune** | ~64B | Apply pitch/detune to all 4 operators |
| 0x5755 | **ym2151_reload_vol_env** | 59B | Reload volume envelope base from voice definition |

#### YM2151 Sequence Opcodes (Phase 15)

| Address | Name | Size | Purpose |
|---------|------|------|---------|
| 0x5614 | **seq_op_ym_write_regs** | 65B | Write YM2151 register block from sequence |
| 0x5656 | **seq_op_ym_write_single** | 28B | Write single YM2151 register |
| 0x568A | **seq_op_ym_set_algorithm** | 37B | Set YM2151 algorithm/feedback |
| 0x56AF | **ym2151_sub_detune** | 45B | Subtract from YM2151 detune |

#### Music/Speech Functions

| Address | Name | Purpose |
|---------|------|---------|
| 0x5932 | **music_speech_handler** | **Main music/speech playback** (shared engine!) |

#### TMS5220 Functions

| Address | Name | Purpose |
|---------|------|---------|
| 0x4183 | **irq_ack_write** | Simple wrapper: STA 0x1830 (IRQ acknowledge); RTS |
| 0x5894 | **sound_status_update** | Stream speech data to TMS5220 (0x1820), manage speech queue |

#### Status & Control Functions

| Address | Name | Purpose |
|---------|------|---------|
| 0x59E2 | **speech_queue_enqueue** | Priority-based circular queue enqueue for speech/sound commands (uses $0832-$083B, $35 priority) |
| 0x8381 | **control_register_update** | Coin counter LED controller (190B). Two paths: (1) bit 4 of $1030 clear: map coin inputs to LED state via $44. (2) bit 4 set: 4-channel attack/decay envelope processor writing to $1034/$1035. Inline data at 0x83A4-0x83AB. |

---

## Major Subsystems

### 1. Boot & Initialization System

**Flow**:
```
POWER ON
  ↓
RESET Vector (0xFFFC) → 0x5A25
  ↓
┌─────────────────────────────────────┐
│ reset_handler (0x5A25)              │
│ - Wait for bit pattern in 0x1030   │
│ - Infinite loop until ready         │
└─────────────────────────────────────┘
  ↓
┌─────────────────────────────────────┐
│ init_main (0x4002)                  │
│                                     │
│ 1. CPU Setup:                       │
│    - SEI (disable interrupts)       │
│    - CLD (binary mode)              │
│    - TXS (stack = 0x01FF)           │
│                                     │
│ 2. Status Handshake (0x1030):      │
│    - Write 0xFF → 0x00 → 0xFF       │
│                                     │
│ 3. RAM Test (conditional):         │
│    - Check bit 4 of 0x1030          │
│    - If set: Simple clear           │
│    - If clear: Walking-bit test     │
│                                     │
│ 4. Checksum (3 passes):            │
│    - checksum_ram × 3               │
│    - Verify ROM/RAM integrity       │
│                                     │
│ 5. Hardware Init:                   │
│    - init_hardware_regs             │
│    - irq_ack_write (STA 0x1830)     │
│                                     │
│ 6. Enable Interrupts:               │
│    - CLI                            │
│    - Wait for IRQ to set 0x00       │
│                                     │
│ 7. Enter Main Loop                  │
└─────────────────────────────────────┘
  ↓
┌─────────────────────────────────────┐
│ main_loop (0x40C8)                  │
│                                     │
│ - init_sound_state                  │
│ - init_sound_state (0x5833)         │
│ - clear_sound_buffers               │
│                                     │
│ [Infinite loop]:                    │
│   ↓                                 │
│   Read command buffer (0x0200,X)    │
│   ↓                                 │
│   command_dispatcher (Y=cmd)        │
│   ↓                                 │
│   Loop back                         │
└─────────────────────────────────────┘
```

**Boot Time**: 1-125ms (depending on RAM test path)

---

### 2. Command Dispatch System

**Architecture**: Two-level table lookup (elegant space optimization!)

```
Command Input (0x00-0xDA, 219 commands)
    ↓
┌──────────────────────────────────────┐
│ command_dispatcher (0x432E)          │
│                                      │
│ 1. Validate: CPY #0xDB               │
│    If >= 219: return                 │
│                                      │
│ 2. Table 1 Lookup:                   │
│    LDA 0x5DEA,Y  → Handler Type      │
│    CMP #0x0F                         │
│    If >= 15: return                  │
│                                      │
│ 3. Table 2 Lookup:                   │
│    ASL A (type × 2)                  │
│    TAX                               │
│    LDA 0x4634,X → High byte          │
│    PHA                               │
│    LDA 0x4633,X → Low byte           │
│    PHA                               │
│                                      │
│ 4. Load Parameter:                   │
│    LDA 0x5EC5,Y → Parameter to A     │
│                                      │
│ 5. Jump via RTS:                     │
│    RTS (pops address+1, jumps)       │
└──────────────────────────────────────┘
    ↓
Handler Function (15 handlers)
    ↓
Process sound/music/speech
    ↓
Return to main_loop
```

**Handler Type Distribution** (from complete Phase 16 analysis):

| Type | Handler | Count | Command Ranges |
|------|---------|-------|---------------|
| 0 | handler_type_0 (param shift) | 2 | 0x01-0x02 |
| 3 | handler_type_3 (jump dispatch) | 1 | 0x00 |
| 5 | handler_stop_sound | 3 | 0x21, 0x2F, 0x39 |
| 7 | handler_type_7 (POKEY SFX) | 90 | 0x04-0x05, 0x09-0x20, 0x22-0x2E, 0x30-0x3B, 0x3D-0x40, 0x42-0x49 |
| 8 | handler_type_8 (output queue) | 1 | 0xDA |
| 9 | handler_fadeout_sound | 1 | 0x3C |
| 10 | handler_fadeout_by_status | 1 | 0x41 |
| 11 | handler_type_11 (music/speech) | 112 | 0x08, 0x4A-0xD5 |
| 13 | handler_type_13 (control reg) | 4 | 0xD6-0xD9 |
| FF | Invalid (no handler) | 4 | 0x03, 0x06-0x07 |
| **Total** | | **219** | 0x00-0xDA |

**Types never dispatched**: 1, 2, 4, 6, 12, 14 (exist in address table but no commands route to them — reserved for expansion).

---

### 3. POKEY Sound Effects System

**Architecture**: 30 logical channels → 4 physical POKEY channels

```
POKEY SFX Command (e.g., 0x0D "Food Eaten")
    ↓
┌──────────────────────────────────────────┐
│ handler_type_7 (0x44DE)               │
│                                          │
│ 1. Load SFX Data:                        │
│    X = 0x5FA8[cmd]  (data offset)        │
│    A = 0x5FE6[cmd]  (flags)              │
│                                          │
│ 2. Check Duplicates (if flags=0):        │
│    Scan 0x0228 array (active cmds)       │
│    If same sound playing: EXIT           │
│                                          │
│ 3. Find Free Channel:                    │
│    Scan 0x0390 array (status)            │
│    Find channel with status=0            │
│                                          │
│ 4. Priority Preemption (if all busy):    │
│    Priority = 0x6024[X]                  │
│    Compare with active sounds            │
│    Interrupt lower priority if needed    │
│    Use linked list (0x07E6) to track     │
│                                          │
│ 5. Initialize Channel (~50 stores):      │
│    Clear 30+ state variables             │
│    Set initial: priority, volume, etc.   │
│                                          │
│ 6. Load Sound Data:                      │
│    Channel = 0x60DA[X]                   │
│    Pointer = 0x6190[X*2] or 0x6290[X*2]  │
│    Store in 0x0246,Y                     │
│                                          │
│ 7. Link Into Active List:                │
│    Insert into 0x07E6 linked list        │
│    Maintain priority order               │
└──────────────────────────────────────────┘
    ↓
[IRQ processes channel @ 120Hz]
    ↓
┌──────────────────────────────────────────┐
│ IRQ: channel_dispatcher (X=0)            │
│ ↓                                        │
│ Sets pointer 0x08 = 0x1800 (POKEY base)  │
│ ↓                                        │
│ pokey_update_registers (0x4DFC)          │
│ ↓                                        │
│ Read channel state:                      │
│   Frequency from 0x081A                  │
│   Control from 0x081B, 0x0817, 0x0818    │
│ ↓                                        │
│ Write via indirect:                      │
│   LDY #0x04-0x08                         │
│   STA (0x08),Y  → POKEY 0x1804-0x1808    │
└──────────────────────────────────────────┘
```

**Priority System**:
- Values 0x00-0x0F (higher = more important)
- 0x0F = Cannot be interrupted (e.g., heartbeat)
- 0x08 = Medium priority (most SFX)
- Linked lists track preemptable sounds

**Channel Allocation**:
- 30 logical channels managed
- Dynamically mapped to 4 POKEY channels
- Table 0x60DA assigns physical channel
- Multiple logical → same physical possible

**Update Rate**: 120Hz (every other IRQ)

---

### 4. YM2151 FM Music System

**Architecture**: Shared music/speech playback engine

```
Music Command (e.g., 0x3B "Gauntlet Theme")
    ↓
┌──────────────────────────────────────────┐
│ handler_type_11 (0x4439)         │
│ - Quick filter check                     │
│ - Jump to music_speech_handler           │
└──────────────────────────────────────────┘
    ↓
┌──────────────────────────────────────────┐
│ music_speech_handler (0x5932)            │
│                                          │
│ 1. Check Active Flag (0x2F):             │
│    If playing: jump to update (0x59E2)   │
│    If idle: start new                    │
│                                          │
│ 2. Load Music Metadata:                  │
│    Flags = 0x643F[cmd]                   │
│    Tempo = 0x64CC[cmd]                   │
│    Index = 0x63B2[cmd]                   │
│                                          │
│ 3. Update Status Register:               │
│    STA 0x1033 (music flags)              │
│                                          │
│ 4. Calculate Sequence Pointers:          │
│    Addr = 0x8449 + (index × 2)           │
│    Read 16-bit pointer → 0x2B-0x2C       │
│    Addr = 0x85C3 + (index × 2)           │
│    Read 16-bit length → 0x2D-0x2E        │
│                                          │
│ 5. Set Active Flag:                      │
│    STA 0x2F ← 0x80                       │
│                                          │
│ 6. Calculate Volume:                     │
│    Complex bit manipulation              │
│    Write to 0x1020 (control reg)         │
│                                          │
│ 7. Write Volume/Control:                 │
│    ORA $28; STA $1020 (control reg)      │
└──────────────────────────────────────────┘
    ↓
[IRQ processes music @ 120Hz]
    ↓
┌──────────────────────────────────────────┐
│ IRQ: channel_dispatcher (X=1)            │
│ ↓                                        │
│ Sets pointer 0x08 = 0x1810 (YM2151 base) │
│ ↓                                        │
│ ym2151_channel_update (0x4FD6)           │
│ ↓                                        │
│ Loop 8 times:                            │
│   Register = 0x57AE[X] + offset         │
│   JSR ym2151_write_operator              │
│   DEC counter                            │
└──────────────────────────────────────────┘
    ↓
┌──────────────────────────────────────────┐
│ ym2151_write_operator (0x4E68)           │
│                                          │
│ For each note, write 3-5 registers:      │
│                                          │
│ 1. JSR ym2151_wait_ready                 │
│    STY 0x1810 (reg select)               │
│    STA 0x1811 (data write)               │
│                                          │
│ 2. JSR ym2151_wait_ready                 │
│    LDY reg+0x30                          │
│    STY 0x1810                            │
│    STA 0x1811 (operator params)          │
│                                          │
│ 3. JSR ym2151_wait_ready                 │
│    LDY reg+0x38                          │
│    STY 0x1810                            │
│    STA 0x1811 (operator params 2)        │
│                                          │
│ 4. JSR ym2151_wait_ready                 │
│    LDY #0x08 (Key On/Off)                │
│    STY 0x1810                            │
│    STA 0x1811 (channel number)           │
│                                          │
│ 5. [Conditional] JSR ym2151_wait_ready   │
│    LDY reg+0x28                          │
│    STY 0x1810                            │
│    STA 0x1811 (noise/LFO)                │
└──────────────────────────────────────────┘
```

**Delay Function** (ym2151_wait_ready at 0x4FF0):
```assembly
wait_loop:
  BIT 0x1811            ; Read YM2151 status
  BPL ready             ; Bit 7 clear = ready
  ; Increment timeout counter
  BNE wait_loop
  ; Set timeout error flag
ready:
  RTS
```

**Critical**: Must wait between every YM2151 register write!

**Update Rate**: 120Hz (odd IRQs only)

---

### 5. TMS5220 Speech System

**Architecture**: Shares music playback infrastructure!

```
Speech Command (e.g., 0x5A "NEEDS FOOD, BADLY")
    ↓
┌──────────────────────────────────────────┐
│ handler_type_11 (0x4439)         │
│ (Same entry as music!)                   │
└──────────────────────────────────────────┘
    ↓
Command queued in speech buffer (0x0834-0x083B)
    ↓
┌──────────────────────────────────────────┐
│ IRQ: sound_status_update × 4             │
│ (Called 960Hz - 4× per IRQ)              │
│                                          │
│ 1. Check Speech Queue:                   │
│    Read ptr (0x0832) vs Write (0x0833)   │
│    If not empty: dequeue command         │
│                                          │
│ 2. Check TMS5220 Status:                 │
│    LDA 0x1030 & 0x20 (bit 5)             │
│    Bit 5 = ready/busy flag               │
│                                          │
│ 3. Dispatch Speech:                      │
│    LDA 0x0834,Y (queued command)         │
│    JMP music_speech_handler (0x5939)     │
└──────────────────────────────────────────┘
    ↓
┌──────────────────────────────────────────┐
│ music_speech_handler (0x5932)            │
│ - Load LPC sequence pointer (0xBEE9)    │
│ - Load length (299 bytes for 0x5A)      │
│ - Set active flag (0x2F = 0x80)          │
└──────────────────────────────────────────┘
    ↓
[Playback Loop - streams LPC data]
    ↓
┌──────────────────────────────────────────┐
│ sound_status_update (0x5894):            │
│ (Called 4× per IRQ = 960Hz)              │
│                                          │
│   Check TMS5220 ready (bit 5 of 0x1030) │
│   If ready and speech active:            │
│     Read byte from (0x2B),Y              │
│     Increment pointer                    │
│     Decrement length                     │
│     STA 0x1820  → TMS5220!              │
└──────────────────────────────────────────┘
```

**Data Rate**: 240 bytes/sec = 2400 bits/sec (standard TMS5220 rate)

**Speech Data**: LPC frames (Linear Predictive Coding)
- 10-bit energy, pitch, K1-K10 coefficients
- Bit-packed (not byte-aligned)
- Located at 0xAD00-0xFFFF (~20KB)

**Queue Prevents Overlap**:
- Only one speech plays at a time
- New speech waits in queue
- Smooth transitions

---

### 6. Interrupt System (Real-Time Audio Engine)

**Dual Interrupt Architecture**:

```
┌─────────────────────────────────────────────┐
│              HARDWARE                       │
│                                             │
│  IRQ Generator → ~240Hz (video-derived,      │
│                   every 64 scanlines)        │
│  NMI Generator → Event-driven (main CPU      │
│                   address decode + data latch)│
└────────┬──────────────────────┬─────────────┘
         │                      │
         ↓                      ↓
┌────────────────────┐  ┌─────────────────┐
│  IRQ (0x4187)      │  │  NMI (0x57B0)   │
│  240Hz periodic    │  │  Event-driven   │
└────────────────────┘  └─────────────────┘
         │                      │
         │                      │
    ┌────┴─────┐               │
    │          │               │
    ↓          ↓               ↓
  ODD       EVEN         COMMAND INPUT
  IRQs      IRQs              │
    │         │               │
    ↓         ↓               ↓
 POKEY    YM2151      Buffer @ 0x0200
 120Hz     120Hz            │
    │         │             │
    └────┬────┘             │
         ↓                  ↓
  TMS5220 (via       IRQ Ack
  status_update)     (0x1830)
                          │
                     Main Loop
                       Processes
```

#### IRQ Handler Flow (0x4187) - 240Hz

```
IRQ_HANDLER:
  1. Save registers (A, X)
  2. CLD (ensure binary mode)
  3. STA 0x1830 (IRQ acknowledge - resets IRQ line, value is don't-care)
  4. Clear error flag (0x02 &= ~0x04)

  5. Check initialized (0x01):
     If not: INC 0x00; exit

  6. Check for BRK:
     If BRK detected: reset stack, JMP main_loop

  7. Save Y, increment counter (0x00)

  8. Timer countdown (0x2A):
     If expired: LDA 0x29; STA 0x1020 (inline write, not a subroutine call)

  9. Call audio functions:
     - JSR 0x41C8 (audio update subroutine):
       - sound_status_update × 3
       - Alternating channel update (see below)
       - JMP sound_status_update (4th call)
     - control_register_update (0x8381)

  10. Alternating channel update:
      If 0x00 is ODD (bit 0 set):
        channel_dispatcher(X=0) → POKEY
      If 0x00 is EVEN (bit 0 clear):
        channel_dispatcher(X=1) → YM2151

  11. Restore registers (Y, X, A)
  12. RTI
```

**Key Optimization**: POKEY and YM2151 alternate IRQs (reduces peak load 50%!)

#### NMI Handler Flow (0x57B0) - Event Driven

```
NMI_HANDLER:
  1. Save A register

  2. Buffer full check:
     wait: BIT 0x1030; BVS wait
     (Wait for bit 6 clear = sound buffer not full)

  3. Save Y register

  4. Check mode flag (0x0213)

  5. Command buffer management:
     - Update circular buffer pointer (0x0212)
     - Handle pointer wraparound

  6. Read command:
     LDA 0x1010 (hardware command input)

  7. Validate command:
     Check table 0x5D0F[cmd]
     If FF: invalid, skip
     If 00-02: dispatch immediately via 0x5FA2 table
     Otherwise: store in buffer

  8. Buffer storage:
     nmi_command_input (0x57F0):
       - Store in 0x0200,Y
       - Update write pointer (0x0211)
       - Check for buffer full

  9. Restore registers (Y, A)
  10. RTI
```

**Buffer Full Wait**: Ensures sound buffer has space before accepting new command

**Data Latch**: NMI fires simultaneously with hardware latch capturing the main CPU's data bus, guaranteeing atomicity — the sound CPU can take as long as needed to service the NMI without the value at 0x1010 changing

**Circular Buffer**: 16 commands (0x0200-0x020F), prevents overflow

---

### 7. Channel Dispatcher (0x500D)

**Purpose**: Route updates to correct hardware chip

```
channel_dispatcher (X = channel set):
  ↓
  Load hardware pointer from 0x57A8 table
  ↓
  ┌─────────────────────────────┐
  │ X=0: Pointer = 0x1800       │
  │      Type = 0x00            │
  │      → POKEY channels       │
  ├─────────────────────────────┤
  │ X=1: Pointer = 0x1810       │
  │      Type = 0x03            │
  │      → YM2151 channels      │
  ├─────────────────────────────┤
  │ X=2: Pointer = 0x0018       │
  │      Type = varies          │
  │      → RAM (work area)      │
  └─────────────────────────────┘
  ↓
  Branch on Type:
    Type 0x00: JMP pokey_update_registers
    Type 0x03: JMP ym2151_channel_update
    Other: RTS
```

**Pointer Table** (0x57A8-0x57B7):
```
Offset 0,2:  00 18 → 0x1800 POKEY
Offset 1,3:  10 18 → 0x1810 YM2151
Offset 2,4:  18 00 → 0x0018 RAM
Offset 3,5:  18 02 → 0x0218 RAM buffer
```

---

## Data Tables

### Command Dispatch Tables

| Address | Name | Size | Format | Purpose |
|---------|------|------|--------|---------|
| **0x5DEA** | Command Type Map | 219 B | 1B/cmd | Command → Handler Type (0-14, FF=invalid) |
| **0x4633** | Handler Address Table | 32 B | 16-bit LE | Handler Type → Address (15 handlers) |
| **0x5EC5** | Command Parameters | 219 B | 1B/cmd | Optional parameter loaded to A register |
| **0x5D0F** | NMI Validation Table | 219 B | 1B/cmd | Command validation (FF=invalid, 0-2=dispatch) |
| **0x5FA2** | NMI Dispatch Table | 6 B | 16-bit LE | NMI immediate dispatch (3 handlers) |

### POKEY SFX Tables

| Address | Name | Size | Format | Purpose |
|---------|------|------|--------|---------|
| **0x5FA8** | SFX Data Offset | ~200 B | 1B/sound | Index into data pointer tables |
| **0x5FE6** | SFX Flags | ~200 B | 1B/sound | Behavior flags (FF=immediate, 00=dup check) |
| **0x6024** | SFX Priority | ~200 B | 1B/sound | Interrupt priority (00=low, 0F=high) |
| **0x60DA** | SFX Channel Map | ~200 B | 1B/sound | POKEY channel assignment (04-0B) |
| **0x6190** | SFX Data Pointers A | ~400 B | 16-bit LE | Primary sound sequence pointers |
| **0x6290** | SFX Data Pointers B | ~400 B | 16-bit LE | Alternate sound sequences |
| **0x62FC** | SFX Next-Offset Chain | ~180 B | 1B/offset | Multi-channel chaining (0=end) |

**SFX Sequence Data**: Located at 0x6800-0x7FFF (~6KB)
- 2-byte frames: [frequency/opcode] [duration/envelope]
- Frequency: 0x00-0x7F = note value, 0x80-0xBA = opcode, 0xBB+ = end
- Duration: bits 0-3 = index into 0x5C5F table, bits 4-7 = flags
- Interpreted by channel_state_machine (0x4651) with 59 opcodes

**Multi-Channel SFX** (Phase 17): The type 7 handler chains through offsets via the table at $62FC. After setting up one channel, it reads `$62FC[offset]` to get the next offset; zero terminates. This allows a single command to allocate multiple simultaneous channels:
- Most simple SFX: 2 channels (stereo pairs)
- Music and complex effects: up to 8 channels (e.g., Theme Song, Treasure Room)
- Single-channel SFX: `$62FC[offset] = 0x00`

### YM2151 Music Tables

| Address | Name | Size | Format | Purpose |
|---------|------|------|--------|---------|
| **0x643F** | Music Flags | 219 B | 1B/cmd | Bit 7=special mode, bits 0-3=volume calc |
| **0x64CC** | Music Tempo | 219 B | 1B/cmd | Tempo values (mostly 0x00=default) |
| **0x63B2** | Music Sequence Index | 219 B | 1B/cmd | Index into sequence pointer tables (00-5B) |
| **0x8449** | Music Seq Pointers | ~184 B | 16-bit LE | Pointers to note sequence data |
| **0x85C3** | Music Seq Lengths | ~184 B | 16-bit LE | Sequence length/loop parameters |
| **0x5AF9** | YM2151 Operator Params | ~64 B | 1B/entry | Noise/LFO settings for operators |

**Music Sequence Data**: Located at 0x8700-0xAD00 (~10KB)
- Same 2-byte frame format as POKEY SFX (shared bytecode engine!)
- Uses same 59-opcode instruction set
- Additional YM2151-specific opcodes: SET_VOICE (0x9D), YM_WRITE_REGS (0xB4), YM_SET_ALGO (0xB6)
- FM operator configs, note frequencies via 128-entry table at 0x5A35

### TMS5220 Speech Tables

**Speech uses same tables as music** (0x643F, 0x64CC, 0x63B2, 0x8449, 0x85C3):
- Commands 0x4A-0xD5 (100+ phrases)
- Sequence indices 0x6A and above
- Pointers to LPC data regions

**Speech Data**: Located at 0xAD00-0xFFFF (~21KB)
- TMS5220 LPC frames (bit-packed)
- Energy + pitch + 10 K coefficients per frame
- Example: "NEEDS FOOD, BADLY" at 0xBEE9 (299 bytes)

### Sequence Engine Tables (Phases 12-13)

| Address | Name | Size | Format | Purpose |
|---------|------|------|--------|---------|
| **0x507B** | Opcode Jump Table | 118 B | 16-bit LE (addr-1) | 59 sequence opcode handlers (0x80-0xBA) |
| **0x5C5F** | Duration Table | 32 B | 16-bit LE × 16 | Musical note durations (whole, half, quarter, etc.) |
| **0x5C7F** | Envelope Shape Table | ~16 B | 1B/entry | Frequency envelope shape multipliers |
| **0x5C8F** | Volume Shape Table | ~16 B | 1B/entry | Volume envelope distortion shapes (RAM-initialized) |
| **0x5A35** | YM2151 Frequency Table | 256 B | 16-bit LE × 128 | Note number → frequency (chromatic, A4=note $46) |

**Duration Table** (0x5C5F) — Musical note durations in 16-bit fixed-point:

| Index | Value | Musical Duration | Frames @120Hz |
|-------|-------|-----------------|---------------|
| 0 | 0x0000 | Immediate/rest | 0 |
| 1 | 0x1E00 | Whole note | 64 |
| 2 | 0x0F00 | Half note | 32 |
| 3 | 0x0780 | Quarter note | 16 |
| 4 | 0x03C0 | Eighth note | 8 |
| 5 | 0x0A00 | Dotted half | ~43 |
| 6 | 0x0500 | Dotted quarter | ~21 |
| 7 | 0x0280 | Dotted eighth | ~11 |
| 8 | 0x0600 | Triplet | ~13 |
| 9 | 0x01E0 | Sixteenth | 4 |
| A | 0x00F0 | Thirty-second | 2 |
| B | 0x0078 | Sixty-fourth | 1 |
| C | 0x003C | 128th | <1 |
| D | 0x0140 | Dotted sixteenth | ~3 |
| E | 0x00A0 | Dotted thirty-second | ~1.3 |
| F | 0x0300 | Triplet quarter | ~6 |

**Note-to-Pitch Mapping** (Phase 17): MIDI_note = ROM_note_value - 1. Note $46 (70) = MIDI 69 = A4 (440Hz). Note 0 = rest. Chromatic scale with ratio 2^(1/12) between consecutive entries.

**Timing Formula** (Phase 17): SET_TEMPO stores `arg >> 2` as tempo. ADD_TEMPO adds raw arg (8-bit wrapping). Each frame (120Hz), tempo is subtracted from the note's duration timer. Dotted flag (bit 6) multiplies duration by 1.5. Division control (bits 4-5) affects only the envelope secondary timer.
```
seconds = (duration_table[byte1 & 0x0F] × (1.5 if dotted else 1.0)) / tempo / 120
```

**Sustain flag** (bit 7): Sets the secondary timer to $7F (maximum), preventing the volume envelope from decaying. While this does not change the sequence timing advance (the primary note duration timer still expires normally), the sustained note continues to produce audible sound until the next note overwrites the channel. For the last note in a channel, a sustained note rings until the entire command stops. This is musically critical — e.g., the Theme Song (0x3B) harmony channels end with sustained whole notes that hold the final chord for ~7 extra seconds under the continuing melody.

### Hardware Configuration Tables

| Address | Name | Size | Format | Purpose |
|---------|------|------|--------|---------|
| **0x57A8** | Hardware Pointers | 16 B | Pairs | Maps channel index → hardware base address |
| **0x57AC** | Channel Types | 8 B | 1B/ch | Hardware chip type (00=POKEY, 03=YM2151) |
| **0x57AE** | Channel Config | 8 B | 1B/ch | Additional channel parameters |

### Initialization Data

| Address | Name | Size | Format | Purpose |
|---------|------|------|--------|---------|
| **0x5F20** | Init Data Table | ~100 B | Sequential | Values 0x12-0x75 (18-117 decimal) |

---

## Interrupt System

### IRQ Handler Detail (0x4187) - Real-Time Audio @ 240Hz

**Timing**: ~240Hz, video-derived (triggers every 64 scanlines when bit 5 of scanline counter transitions 0→1, first at scanline 32; NTSC: ~262 lines/frame × 60fps ÷ 64 ≈ 245Hz)

**Function Calls per IRQ**:
1. `STA $1830` (IRQ acknowledge - resets IRQ line, value is don't-care) - 1×
2. Timer check: if 0x2A expired, inline `LDA $29; STA $1020` (not a subroutine call)
3. `JSR $41C8` (audio update subroutine) - 1×:
   - `sound_status_update` (0x5894) × 3
   - `channel_dispatcher` (0x500D) × 1 (alternating, see below)
   - `JMP sound_status_update` (0x5894) × 1
   - Total: sound_status_update 4× per IRQ (960Hz total!)
4. `control_register_update` (0x8381) - 1×
5. Channel alternation within $41C8:
   - X=0 (odd IRQs): `pokey_update_registers` - 120Hz
   - X=1 (even IRQs): `ym2151_channel_update` → `ym2151_write_operator` - 120Hz

**CPU Cycles per IRQ** (estimated @ 2MHz):
- Available: ~8,333 cycles
- IRQ overhead: ~100 cycles
- IRQ acknowledge: ~20 cycles
- Status updates: ~400 cycles (4× calls)
- Channel update: ~2,000-3,000 cycles (alternating)
- Control updates: ~200 cycles
- **Total**: ~3,000-4,000 cycles (~40-50% CPU utilization)

**Remaining cycles**: Available for main loop command processing

### NMI Handler Detail (0x57B0) - Command Input

**Timing**: Event-driven (triggered by main CPU address decode; same signal latches data bus to 0x1010)

**Typical Rate**: 10-100 commands/second (gameplay dependent)

**Function Calls**:
1. Buffer full wait (bit 6 of 0x1030)
2. `nmi_command_input` (0x57F0) - buffer management
3. Conditional dispatch via 0x5FA2 table (commands 0-2 only)

**Buffer**: 16-entry circular buffer (0x0200-0x020F)

---

## Unknown / Unexplored Areas

### Resolved Phantom Addresses

The previous analysis listed two functions at addresses in I/O space. These have been confirmed as **disassembly alignment artifacts**:

1. ~~**func_2010** (0x2010)~~ — **RESOLVED**: The bytes `20 10` at 0x41BA are the operand of `STA $1020` (opcode `8D 20 10`) at 0x41B9. If disassembly starts 1 byte into this instruction, `20` is the JSR opcode and `10 XX` form a phantom target address. The actual instruction is an inline write of `$29 → $1020` (volume/control register), not a subroutine call.

2. ~~**music_processor** (0x2810)~~ — **RESOLVED**: Same pattern. The bytes at 0x59DD are `STA $1020` (`8D 20 10`). Misaligned disassembly reads `20 10 28` as `JSR $2810`. The actual instruction writes the calculated volume to control register 0x1020 at the end of `music_speech_handler`.

### Previously Unexamined Code Targets — ALL RESOLVED (Phases 12-16)

All 16 previously unexamined code targets have been fully analyzed and named:

| Address | Name | Size | Phase |
|---------|------|------|-------|
| 0x4295 | channel_list_init | 49B | 12 |
| 0x42C6 | channel_list_follow | 17B | 12 |
| 0x42D7 | channel_state_ptr_calc | 34B | 12 |
| 0x42F9 | channel_list_unlink | 53B | 12 |
| 0x4651 | channel_state_machine | ~1300B | 13 |
| 0x4B6B | envelope_process_freq | 171B | 14 |
| 0x4C16 | ym2151_update_channel_state | 236B | 14 |
| 0x4D02 | pokey_channel_mix | 250B | 14 |
| 0x5029 | seq_opcode_dispatch | 30B | 12 |
| 0x5047 | seq_advance_read | 18B | 12 |
| 0x5181 | channel_apply_volume | 22B | 13 |
| 0x5444 | seq_var_classifier | 109B | 14 |
| 0x558F | ym2151_load_voice | 132B | 15 |
| 0x5676 | ym2151_write_reg_indirect | 20B | 15 |
| 0x5715 | ym2151_apply_detune | ~64B | 15 |
| 0x5755 | ym2151_reload_vol_env | 59B | 15 |

### Hardware Address Corrections (Per Schematic)

Per schematic analysis:
- **0x1820** = TMS5220 Data Write. `STA $1820` at 0x5926 in `sound_status_update` streams speech data to the TMS5220.
- **0x1830** = IRQ Acknowledge. `STA $1830` at 0x418B in the IRQ handler resets the 6502 IRQ line so it can fire again. The value written is irrelevant (at that point A holds the old X register value from the interrupted code).

### Handler Types — ALL RESOLVED (Phase 16)

All 15 handler types fully documented:

| Type | Address | Name | Commands | Status |
|------|---------|------|----------|--------|
| 0 | 0x4347 | handler_type_0 | 0x01-0x02 | Active |
| 1 | 0x434C | handler_type_1 | None | Reserved |
| 2 | 0x4359 | handler_type_2 | None | Reserved |
| 3 | 0x4369 | handler_type_3 | 0x00 | Active |
| 4 | 0x4374 | handler_kill_by_status | None | Reserved |
| 5 | 0x438D | handler_stop_sound | 0x21, 0x2F, 0x39 | Active |
| 6 | 0x43AF | handler_stop_chain | None | Reserved |
| 7 | 0x44DE | handler_type_7 | ~90 POKEY SFX | Active |
| 8 | 0x4445 | handler_type_8 | 0xDA | Active |
| 9 | 0x43D4 | handler_fadeout_sound | 0x3C | Active |
| 10 | 0x440B | handler_fadeout_by_status | 0x41 | Active |
| 11 | 0x4439 | handler_type_11 | ~112 music/speech | Active |
| 12 | 0x4461 | handler_channel_control | None | Reserved |
| 13 | 0x4619 | handler_type_13 | 0xD6-0xD9 | Active |
| 14 | 0x4618 | handler_type_14 (null RTS) | None | Reserved |

### Unused ROM Space (Phase 21)

Total: ~366 bytes of genuinely unused ROM space across 5 regions:

| Address | Size | Fill | Context |
|---------|------|------|---------|
| 0x5874-0x5893 | 32 B | 0xFF (erased EPROM) | Padding between `init_sound_state` (RTS at 0x5873) and `sound_status_update` (0x5894) |
| 0x6000-0x6023 | 36 B | 0xFF (erased EPROM) | Gap before `sfx_priority` table (0x6024). Unreferenced. |
| 0x8447-0x8448 | 2 B | `94 FF` | Gap between NMI handler 0 (ends 0x8446) and `music_seq_ptrs` table (starts 0x8449, confirmed via code at 0x5969). Unreferenced. |
| 0xFECE-0xFFF5 | 296 B | 0x00 (zero-padded) | Gap between end of speech LPC data and interrupt vectors. ROM build tool padding. |
| 0xFFF6-0xFFF9 | 4 B | `8C FF 00 00` | Mystery bytes before interrupt vectors. Not standard 6502 vectors. Unreferenced. |

**Not unused** (confirmed as legitimate data):
- 0x5D17-0x5DE9: 0xFF values in `nmi_validation_table` (meaning "store in buffer")
- 0x5FE6-0x5FFE: 0xFF values in `sfx_flags` table (meaning "immediate play")
- 0x5C8F: 32 zero bytes in `vol_env_shape_table` (legitimate zero envelope values)

### Remaining Unexplored Data Regions

1. **Sound Sequence Data** (0x6800-0x7FFF, ~6KB):
   - POKEY waveform sequences — **format now fully understood** (2-byte frames: freq/opcode + duration/envelope)
   - Individual sound data not decoded
   - **Action**: Extract and decode specific SFX waveforms

2. **Music Sequence Data** (0x8700-0xAD00, ~10KB):
   - YM2151 FM synthesis sequences — **format now fully understood** (same bytecode engine with 59 opcodes)
   - Individual compositions not decoded
   - **Action**: Decode actual music note-by-note

3. **Speech LPC Data** (0xAD00-0xFFFF, ~21KB):
   - TMS5220 LPC frames
   - Format: Known (10-bit frames, bit-packed)
   - **Action**: Extract and decode specific phrases

### Resolved Hardware Questions (Per Schematic)

1. **0x1002, 0x1003, 0x100B, 0x100C**: Aliases of 0x1000 — the bottom 4 address bits are not wired to anything. Boot writes to these addresses are simply repeated writes to the main CPU status latch.

2. **0x1020 Volume Mixer**: Bits 7-5 = speech volume (TMS5220), bits 4-3 = effects volume (POKEY), bits 2-0 = music volume (YM2151).

3. **0x1030 READ**: Bits 0-3 = coin slots 1-4, bit 4 = self-test enable, bit 5 = TMS5220 ready, bit 6 = sound buffer full (NOT VBlank), bit 7 = main CPU output buffer full.

4. **0x1030 WRITE**: Triggers YM2151 reset (value is don't-care).

5. **0x1032 WRITE**: Resets the TMS5220 speech chip (value is don't-care).

6. **0x1033 WRITE**: "Speech squeak" — changes the oscillator frequency input to the TMS5220 chip.

7. **IRQ Source**: Video-derived, triggers every 64 scanlines (when bit 5 of scanline counter transitions 0→1, first at scanline 32). NTSC: ~245Hz.

8. **NMI Source**: Triggered by main CPU address decode. The same signal simultaneously latches the data bus, making the command byte available at 0x1010. This guarantees atomicity.

9. **Output to Main CPU**: Writes to 0x1000 trigger an IRQ to the main CPU AND latch the data byte for the main CPU to read. The output buffer at 0x0214 stages data in RAM before writing each byte to 0x1000.

### Remaining Incomplete Understanding

1. **Commands 0x03, 0x06, 0x07**: Map to handler type 0xFF (no handler, silently ignored). Whether these are reserved placeholders, development artifacts, or intercepted by the main CPU before reaching the sound board is unknown. Requires main CPU ROM analysis.

2. **Reserved Handler Types (1, 2, 4, 6, 12, 14)**: Code exists but no commands route to them. Whether these were used in development builds, reserved for Gauntlet II, or dead code is unknown.

---

## Sequence Data Format (Phase 13)

The core discovery: every sound/music channel reads a stream of 2-byte frames interpreted by the channel state machine (0x4651).

### Frame Format

```
Byte 0 (Frequency/Opcode):
  0x00-0x7F: Note/frequency value (bit 7 clear)
  0x80-0xBA: Sequence opcode (bit 7 set, dispatched via jump table at 0x507B)
  0xBB-0xFF: End-of-sequence marker (channel stops)

Byte 1 (Duration/Envelope) — only when byte 0 is a note:
  Bits 0-3: Duration index (into table at 0x5C5F, 16 entries)
  Bits 4-5: Division control (affects secondary timer)
  Bit 6:    Dotted note flag (×1.5 duration multiplier)
  Bit 7:    Sustain mode (sets secondary timer = $7F; note rings until next note)

  Value 0x00: Channel chain — load next segment from linked list
```

### Sequence Opcode Summary (59 opcodes, 0x80-0xBA) — Corrected Phase 18

| Range | Args | Category | Description |
|-------|------|----------|-------------|
| 0x80-0x81 | 1 | Tempo | SET_TEMPO (arg>>2), ADD_TEMPO |
| 0x82-0x83 | 1 | Volume | SET_VOLUME (two variants) |
| 0x84-0x85 | 1 | Transpose | ADD_TRANSPOSE, NOP_FE_CHECK |
| 0x86-0x87 | 2 | Envelopes | SET_FREQ_ENV, SET_VOL_ENV (pointers) |
| 0x88-0x89 | 1 | Timing | RESET_TIMER, SET_REPEAT |
| 0x8A-0x8C | 1 | Control | SET_DISTORTION, SET_CTRL_BITS, CLR_CTRL_BITS |
| 0x8D | 2 | Linking | PUSH_SEQ (push & load segment pointer) |
| 0x8E | 1 | Linking | PUSH_SEQ_EXT (push extended chain state) |
| 0x8F | 1 | Linking | POP_SEQ (pop from chain) |
| 0x90-0x91 | 1 | Mode | SWITCH_POKEY, SWITCH_YM2151 |
| 0x96 | 1 | Output | QUEUE_OUTPUT to main CPU |
| 0x97 | 1 | Reset | RESET_ENVELOPE to defaults |
| 0x99 | 2 | Jump | SET_SEQ_PTR (unconditional jump, pointer) |
| 0x9A | 1 | Music | PLAY_MUSIC_CMD (trigger from sequence) |
| 0x9C | 1 | Mode | FORCE_POKEY mode |
| 0x9D | 2 | Voice | SET_VOICE (YM2151 instrument, pointer) |
| 0x9E | 2 | YM2151 | YM_LOAD_ENV (load envelope table, pointer+$24) |
| 0x9F | 2 | YM2151 | YM_LOAD_REG (load register block, pointer+$29) |
| 0xA0-0xA3 | 1 | Register | FREQ_OFFSET, YM_DETUNE_NEG, REG_OR, REG_XOR |
| 0xA4 | 2 | Variable | VAR_LOAD (load pair to seq variables) |
| 0xA5-0xA6 | 1 | ALU | NOP_A5, SHIFT_LEFT |
| 0xA7 | 1 | Frequency | FREQ_ADD (signed frequency detune) |
| 0xA8 | 1 | Release | SET_RELEASE rate |
| 0xA9-0xAD | 1 | Variable | VAR_ADD/SUB/AND/OR/XOR (state variable ops) |
| 0xAE | 2* | Jump | COND_JUMP (if var=0, jump; *variable-length) |
| 0xAF | 2* | Jump | COND_JUMP_INC (cond jump + increment var) |
| 0xB0-0xB2 | 1 | Variable | VAR_TO_REG, VAR_APPLY, VAR_CLASSIFY |
| 0xB3-0xB4 | 1 | Variable | SHIFT_VAR_RIGHT, SHIFT_VAR_LEFT |
| 0xB5-0xB8 | 3 | Branch | COND_JUMP_EQ/NE/PL/MI (classify + 2-byte addr) |
| 0xB9-0xBA | 1 | Variable | VAR_CLASSIFY_SUB, VAR_SUB_STORE |

*0xAE/0xAF consume 2 args when state var=0 (unconditional jump), but 2+2N args when var=N>0 (skip N frames then jump). 0xAF also increments the variable for progressive multi-pass behavior.

### Channel State Array Map (48 arrays × 30 entries = 1440 bytes)

| Array Base | Purpose |
|-----------|---------|
| $0228+X | Active command ID ($FF=dead, $FE=special) |
| $0246+X | Sequence pointer low |
| $0264+X | Sequence pointer high |
| $0282+X | Base frequency low |
| $02A0+X | Base frequency high (YM2151) |
| $02BE+X | Primary timer low (note duration) |
| $02DC+X | Primary timer high |
| $02FA+X | Secondary timer low (envelope) |
| $0318+X | Secondary timer high |
| $0336+X | Current note data |
| $0390+X | Channel status (bit 0: type) |
| $03AE+X | Distortion shape index |
| $03CC+X | Control mask (AND) |
| $03EA+X | Control bits (OR) |
| $0408+X | Base volume (0-15) |
| $0426+X | Vol envelope ptr low |
| $0444+X | Vol envelope ptr high |
| $0462+X | Freq envelope ptr low |
| $0480+X | Freq envelope ptr high |
| $049E+X | Vol env position |
| $04BC+X | Vol env frame counter |
| $04DA+X | Vol env modulation |
| $04F8+X | Vol env loop counter |
| $0516+X | Freq env position |
| $0534+X | Freq env frame counter |
| $0552+X | Freq accumulator low (24-bit) |
| $0570+X | Freq accumulator mid |
| $058E+X | Freq accumulator high |
| $05AC+X | Freq env loop counter |
| $05CA+X | Tempo/speed |
| $05E8+X | Transpose offset |
| $0606+X | Repeat state |
| $0624+X | Repeat counter |
| $0642+X | Distortion mask |
| $0660+X | Vibrato depth |
| $067E+X | Portamento delta low |
| $069C+X | Portamento delta high |
| $06BA+X | Segment chain A |
| $06D8+X | Segment chain B |
| $06F6+X | Extended chain counter |
| $0714+X | Envelope counter low |
| $0732+X | Envelope counter high |
| $0750+X | Envelope rate low |
| $076E+X | Envelope rate high |
| $078C+X | Envelope fractional |
| $07AA+X | General-purpose register |
| $07C8+X | Register shadow |
| $07E6+X | Linked list next |

---

## Implementation Notes

### For Emulator Developers

#### Critical Timing Requirements

1. **IRQ must fire at 240Hz** (4.16ms intervals)
   - Use system timer or audio callback
   - Alternating POKEY/YM2151 updates crucial

2. **YM2151 busy flag** (bit 7 of 0x1811):
   - Must simulate chip delay (~84µs per write @ 3.58MHz)
   - Timeout detection after 255 checks

3. **TMS5220 streaming** (via 0x1820):
   - Speech bytes written by `sound_status_update`, not the IRQ entry point
   - Decode LPC frames internally
   - Set bit 5 of 0x1030 when ready

4. **IRQ Acknowledge** (0x1830):
   - Must be written each IRQ to reset the interrupt line
   - Value written is don't-care

#### Hardware Register Simulation

**Read Registers**:
- 0x1010 (R): Command input from main CPU (hardware-latched on NMI)
- 0x1030 (R): Status bits (0-3: coin slots, 4: self-test, 5: TMS5220 ready, 6: sound buffer full, 7: main CPU output buffer full)
- 0x1811 (R): YM2151 status (bit 7 = busy)

**Write Registers**:
- 0x1000 (W): Data output to main CPU (triggers IRQ to main CPU + latches data)
- 0x1002/0x1003/0x100B/0x100C (W): Aliases of 0x1000 (low 4 address bits not decoded)
- 0x1020 (W): Volume mixer (bits 7-5: speech, 4-3: effects, 2-0: music)
- 0x1030 (W): YM2151 reset (value is don't-care)
- 0x1032 (W): TMS5220 reset (value is don't-care)
- 0x1033 (W): Speech squeak — changes TMS5220 oscillator frequency
- 0x1034 (W): Coin counter LED output, channels 2-3 (from control_register_update)
- 0x1035 (W): Coin counter LED output, channels 0-1 (from control_register_update)
- 0x1800-0x1808: POKEY sound registers
- 0x1810: YM2151 register select
- 0x1811: YM2151 data write
- 0x1820: TMS5220 data input (speech synthesis)
- 0x1830: IRQ acknowledge (resets IRQ line, value is don't-care)

#### RAM Requirements

- **Minimum**: 4KB (0x0000-0x0FFF)
- **Critical regions**:
  - Zero-page: Heavily used (0x00-0x3F)
  - Stack: Standard 6502 (0x0100-0x01FF)
  - Buffers: Command queue, output queue
  - Sound state: 30 channels × 60+ bytes

#### ROM Access Patterns

- **Code execution**: 0x4000-0x5FFF
- **Table lookups**: Heavy random access to all regions
- **Sequential reads**: Music/speech data streaming

### For Music/Sound Designers

#### Command Structure

**219 Total Commands**:
- **0x00-0x03**: System (stop, silent, noisy)
- **0x04-0x2F**: POKEY SFX (44 effects)
- **0x30-0x42**: YM2151 Music (19 tracks)
- **0x43-0x49**: More SFX (7 effects)
- **0x4A-0xD5**: TMS5220 Speech (140 phrases)

**To Add New Sound**:
1. Create sequence data (POKEY/YM2151/LPC format)
2. Add pointer to appropriate table (0x6190, 0x8449, etc.)
3. Set priority (0x6024) and channel (0x60DA)
4. Update dispatch table (0x5DEA) with handler type
5. Add parameter (0x5EC5) if needed

#### Sound Design Guidelines

**POKEY SFX**:
- 4 channels available
- 8-bit frequency + 4-bit volume + distortion
- Priority 0x00-0x0F (higher = less interruptible)
- Duration controlled by sequence length
- Multi-channel effects via $62FC chain table (e.g., heartbeat=2ch, theme song=8ch)

**YM2151 Music**:
- 8 channels FM synthesis
- 4 operators per channel (complex timbres)
- Sequences can be complex compositions
- Volume integrated with global control (0x1020)

**TMS5220 Speech**:
- One phrase at a time (queued)
- LPC format (use TI tools to encode)
- 240 bytes/sec streaming rate
- Average phrase: 100-400 bytes (0.5-2 seconds)

#### Disassembler Tool (`gauntlet_disasm.py`)

The disassembler can decode any of the 219 sound commands:
- `--cmd N`: Full disassembly with bytecode, opcodes, note names, and timing
- `--score N`: Tracker-style columnar view of all channels with aligned timing
- `--midi N`: Export as Standard MIDI File (Type 1) for playback in any DAW/player
- `--midi N --midi-out FILE`: Custom output filename (default: `command_0xNN.mid`)
- `--list`: Summary of all 219 commands
- `--all`: Disassemble everything with sequence data

MIDI export correctly handles sustained notes (bit 7): Note Off is delayed to the start of the next note in the channel, or to the end of the piece for the last note. This preserves the held-chord behavior of the original hardware.

### For Arcade Cabinet Operators

#### Self-Test Commands

- **0x04**: Music chip test (YM2151)
- **0x05**: Effects chip test (POKEY)
- **0x08**: Speech chip test (TMS5220)

#### Diagnostic Checks

**Boot Status** (0x1030):
- Pattern: Main CPU should see 0xFF, 0x00, 0xFF during boot
- If stuck: Sound CPU not booting properly

**Error Flags** (0x02):
- Bit 0: RAM error
- Bit 1: YM2151 timeout
- Bit 2: General error
- Check via status output (0x1000)

---

## Sound Chip Programming Details

### POKEY (0x1800-0x180F)

**Access Method**: Indirect via zero-page pointer (0x08)

```assembly
; Setup (done in channel_dispatcher)
LDA #0x00 / STA 0x08      ; Pointer low
LDA #0x18 / STA 0x09      ; Pointer high = 0x1800

; Write (in pokey_update_registers)
LDY #0x04                 ; Register offset
LDA frequency
STA (0x08),Y              ; → 0x1804 (AUDF3)

INY
INY
LDA control
STA (0x08),Y              ; → 0x1806 (AUDF4)
```

**Register Programming**:
- AUDFx: 8-bit frequency (lower = higher pitch)
- AUDCx: Upper 4 bits = volume, lower 4 bits = distortion
- AUDCTL (0x1808): Clock dividers, high-pass filters

**Update Rate**: 120Hz (every other IRQ)

### YM2151 (0x1810-0x1811)

**Access Method**: Direct register/data pair

```assembly
; Write operator parameter
JSR ym2151_wait_ready     ; Wait for bit 7 of 0x1811 clear
STY 0x1810                ; Register select (e.g., 0x20)
LDA operator_data
STA 0x1811                ; Data write
; Chip now busy - must wait before next write!
```

**Typical Write Sequence**:
1. Register base (0x20-0x3F range)
2. Register+0x30 (detune/multiply)
3. Register+0x38 (total level/volume)
4. Register 0x08 (key on/off)
5. Register+0x28 (noise enable - conditional)

**Delay Required**: 84µs between writes (enforced by ym2151_wait_ready)

**Update Rate**: 120Hz (odd IRQs only)

### TMS5220 (0x1820)

**Access Method**: Write-only data stream via `sound_status_update`

```assembly
; In sound_status_update (called 4× per IRQ, 960Hz)
; When TMS5220 is ready and speech data available:
  LDA (0x2B),Y            ; Read next LPC byte from sequence
  STA 0x1820              ; Stream to TMS5220
```

**No Delays Required**: TMS5220 has internal FIFO buffer

**Status Check**: Bit 5 of 0x1030 (TMS5220 ready flag)

**Reset**: Write to 0x1032 (value is don't-care) resets the TMS5220

**Speech Squeak**: Write to 0x1033 changes TMS5220 oscillator frequency (used for voice pitch effects)

**Data Format**: LPC frames (10-bit energy, pitch, K1-K10 coefficients)

**Streaming Rate**: ~240 bytes/sec = ~2400 bits/sec (driven by TMS5220 data request rate)

### Volume Mixer (0x1020)

**Purpose**: Controls output volume for all three sound chips

**Bit Map** (per schematic):
```
Bit 7-5: Speech volume (TMS5220)  — 8 levels (0-7)
Bit 4-3: Effects volume (POKEY)   — 4 levels (0-3)
Bit 2-0: Music volume (YM2151)    — 8 levels (0-7)
```

**Written by**:
- `music_speech_handler` (0x5932): Calculates volume from music flags, ORs with master volume ($28), writes to 0x1020
- `irq_handler` (0x4187): On timer expiry, restores $29 → 0x1020 (fadeout recovery)
- `handler_type_13` (0x4619): Direct control register updates

### IRQ Acknowledge (0x1830)

**Purpose**: Reset the 6502 IRQ line so it can fire again

```assembly
; First thing in IRQ handler after saving registers:
  STA 0x1830              ; Acknowledge IRQ (value doesn't matter)
```

**Note**: The value written is whatever happened to be in A (old X register). Only the write itself matters — it resets the hardware IRQ latch.

---

## Reverse Engineering Notes

### Hand-Written Assembly Characteristics

1. **Optimization Techniques**:
   - PHA/PHA/RTS dispatch (saves code space)
   - Alternating IRQ updates (reduces peak load)
   - Zero-page heavy (fast memory access)
   - Inline expansion where speed matters
   - Table-driven architecture

2. **Code Patterns**:
   - Irregular function boundaries
   - Code/data interleaving
   - Shared code paths (fall-through optimization)
   - Custom calling conventions (zero-page parameters)
   - Self-documenting via consistent patterns

3. **No Debug Symbols**:
   - Production ROM (no strings, no debug info)
   - All analysis via pattern recognition
   - Function identification via JSR target analysis
   - Data table discovery via access pattern tracing

### Analysis Challenges Overcome

1. **6502 Limited Auto-Analysis**:
   - Manual function definition required
   - 51+ functions identified via JSR analysis
   - Function boundaries verified manually

2. **Code/Data Intermixing**:
   - Tables within code regions
   - Data after RTS instructions
   - Required context-based interpretation

3. **Indirect Addressing**:
   - POKEY accessed via zero-page pointers
   - Required pointer table analysis
   - Multi-level indirection traced

4. **Two-Level Dispatch**:
   - Initially confusing command routing
   - Elegant once understood
   - Enables massive command set with minimal code

### Radare2 Project Notes

**Project save attempted but failed** - radare2 MCP may not support project persistence

**Workaround**: All findings documented in REPORT.md and SUMMARY.md

**For Future Analysis**:
- Reopen ROM with: `open_file("/path/to/soundrom.bin")`
- Remap: `om \`oq\` 0x4000 0xc000 0x0 r-x`
- Redefine key functions using this SUMMARY

---

## Quick Reference

### Most Important Functions

1. **reset_handler** (0x5A25) - System entry point
2. **irq_handler** (0x4187) - Audio processing @ 240Hz
3. **nmi_handler** (0x57B0) - Command input
4. **main_loop** (0x40C8) - Main execution
5. **command_dispatcher** (0x432E) - Command routing
6. **channel_state_machine** (0x4651) - Core engine (~1300B, sequence interpreter + envelopes)
7. **handler_type_7** (0x44DE) - SFX with priority
8. **music_speech_handler** (0x5932) - Music & voice playback
9. **seq_advance_read** (0x5047) - Most-called function (19 callers)
10. **seq_opcode_dispatch** (0x5029) - Bytecode interpreter for 59 opcodes

### Most Important Tables

1. **0x5DEA** - Command → Handler Type (219 bytes)
2. **0x4633** - Handler Type → Address (32 bytes)
3. **0x507B** - Sequence Opcode Jump Table (59 entries × 2 bytes)
4. **0x5C5F** - Duration Table (16 musical note durations)
5. **0x5A35** - YM2151 Frequency Table (128 entries)
6. **0x6024** - SFX Priority (critical for sound mixing)
7. **0x8449** - Music/Speech Sequence Pointers
8. **0x57A8** - Hardware Base Addresses

### Key Hardware Registers

- **0x1000**: Data output → Main CPU (write triggers main CPU IRQ + data latch)
- **0x1010**: Command input ← Main CPU (hardware-latched on NMI)
- **0x1020**: Volume mixer (bits 7-5: speech, 4-3: effects, 2-0: music)
- **0x1030 R**: Status (bits 0-3: coins, 4: self-test, 5: TMS5220 ready, 6: buffer full, 7: main CPU buffer full)
- **0x1030 W**: YM2151 reset (value is don't-care)
- **0x1032 W**: TMS5220 reset (value is don't-care)
- **0x1033 W**: Speech squeak (changes TMS5220 oscillator frequency)
- **0x1034 W**: Coin counter LED output, channels 2-3 combined (from `control_register_update`)
- **0x1035 W**: Coin counter LED output, channels 0-1 combined (from `control_register_update`)
- **0x1800**: POKEY base (indirect access)
- **0x1810-0x1811**: YM2151 register/data pair
- **0x1820**: TMS5220 data write (speech synthesis)
- **0x1830**: IRQ acknowledge (resets IRQ line)

---

## Architectural Insights

### Why This Design is Brilliant

1. **Alternating Updates Reduce Peak Load**:
   - Instead of updating all chips every IRQ (heavy load)
   - Alternate POKEY/YM2151 (smooth load distribution)
   - Still maintains adequate 120Hz update rate for both

2. **Two-Level Dispatch Saves ROM**:
   - Could have 219 separate handlers (huge!)
   - Instead: 219 → 15 handlers (14× smaller!)
   - Parameter table adds flexibility

3. **Shared Music/Speech Engine**:
   - Both are sequential data playback
   - Code reuse reduces ROM usage
   - Different data formats, same infrastructure

4. **Priority System Enables Rich Soundscapes**:
   - 30 logical channels (7.5× hardware channels!)
   - Important sounds don't get interrupted
   - Automatic mixing via priority preemption

5. **Robust Real-Time Operation**:
   - Circular buffers prevent overflow
   - Error detection and recovery
   - Timeout handling
   - Buffer flow control (NMI waits for space)

### Lessons for Modern Development

1. **Resource Constraints Drive Innovation**:
   - Limited ROM/RAM forced efficient design
   - Table-driven architecture still relevant
   - Interrupt-driven real-time processing model

2. **Separation of Concerns**:
   - IRQ = continuous audio
   - NMI = event input
   - Main loop = command processing
   - Clean boundaries enable understanding

3. **Multi-Rate Processing**:
   - Different subsystems at different rates
   - 120Hz-960Hz range optimized per need
   - Applicable to modern embedded systems

4. **Hand-Optimization Still Has Value**:
   - Carefully crafted assembly
   - Understanding of hardware timing
   - Trade-offs made consciously

---

## Conclusion

The Gauntlet sound ROM is a masterpiece of 1980s arcade engineering:

- **51+ verified functions** implementing complete audio coprocessor (all targets resolved)
- **59 sequence opcodes** decoded (complete bytecode instruction set)
- **219 commands** mapped to 9 active handler types (6 reserved)
- **48 per-channel state arrays** (1440 bytes) fully documented
- **25+ data tables** enabling rich sound programming
- **3 sound chips** coordinated seamlessly via unified bytecode engine
- **240Hz interrupt-driven** real-time processing
- **Sophisticated priority system** for sound mixing (30 logical → 4/8 physical channels)
- **Shared infrastructure** (music/speech/SFX all use same state machine)
- **Hand-optimized assembly** throughout

**Analysis Status**: Phases 1-17 + Phase 21 (ROM gap analysis) complete
- All 52+ functions identified, named, and documented
- Complete sequence data format specified byte-by-byte
- Both POKEY and YM2151 pipelines traced end-to-end
- All 15 handler types fully documented
- Two phantom addresses (func_2010, music_processor) resolved as disassembly artifacts
- IRQ alternation direction corrected (ODD→POKEY, EVEN→YM2151)
- 0x1820 = TMS5220, 0x1830 = IRQ acknowledge (per schematic)
- Core channel state machine (~1300 bytes) fully reverse-engineered

**Remaining Work** (data, not code):
- Individual SFX waveform data (0x6800-0x7FFF): multi-channel structure now understood via $62FC chain table; per-note decoding available via `gauntlet_disasm.py`
- Individual music compositions (0x8700-0xAD00): timing formula and note mapping now known; per-note decoding available via `gauntlet_disasm.py`; MIDI export via `--midi` flag
- Speech LPC data (0xAD00-0xFFFF) not decoded phrase-by-phrase
- Commands 0x03, 0x06, 0x07 purpose unknown (main CPU side question)
- Reserved handler types 1, 2, 4, 6, 12, 14 never dispatched (development artifacts?)

**Hardware**: Fully resolved per schematic — all registers (including coin counter LED outputs at $1034/$1035), IRQ/NMI sources, and communication protocol documented

**ROM Space**: ~366 bytes unused across 5 regions (0.7% of 48KB ROM). Largest gap: 296 bytes zero-padded before interrupt vectors.

**Total Analysis Effort**: 17 phases + Phase 21 (ROM gap analysis), comprehensive reverse engineering

**Files Generated**:
- `REPORT.md`: Detailed phase-by-phase analysis (~5000 lines)
- `REPORT_SUMMARY.md`: This comprehensive reference (you are here!)
- `gauntlet_disasm.py`: Sequence disassembler tool with multi-channel, note names, timing, score view, and MIDI export

---

*Analysis performed using radare2 MCP tools*
*Gauntlet © 1985 Atari Games*
