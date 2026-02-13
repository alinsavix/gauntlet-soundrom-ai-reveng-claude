# Gauntlet Sound ROM - Memory Map

**ROM File**: `soundrom.bin` (48KB, 0xC000 bytes)
**Architecture**: 6502 CPU
**CPU Address Range**: 0x4000-0xFFFF

---

## 1. RAM (0x0000-0x0FFF)

### 1.1 Zero Page (0x0000-0x00FF)

| Address | Name | Purpose |
|---------|------|---------|
| 0x00 | irq_frame_counter | IRQ frame counter, incremented each IRQ; bit 0 selects POKEY (odd) vs YM2151 (even) |
| 0x01 | init_complete_flag | Initialization complete flag (0=not ready, nonzero=ready) |
| 0x02 | error_flags | Error flags: bit 0=RAM error, bit 1=YM2151 timeout, bit 2=general error |
| 0x03 | cmd_param_temp | Temporary storage for command parameter |
| 0x04-0x05 | nmi_buffer_ptr | NMI buffer pointer (16-bit) |
| 0x06-0x07 | seq_data_ptr | Sequence data base pointer (used by `LDA ($06),Y`) |
| 0x08-0x09 | hw_indirect_ptr | Hardware indirect pointer (POKEY/YM2151 base address for `STA ($08),Y`) |
| 0x0D | ym2151_timeout_flag | YM2151 timeout bypass flag (bit 7: skip delay) |
| 0x0E-0x0F | utility_ptr | Utility pointer / checksum address pointer |
| 0x10 | checksum_page_count | Checksum page counter |
| 0x11 | checksum_expected | Expected checksum / channel index save |
| 0x13 | music_filter_threshold | Music filter comparison threshold |
| 0x14 | linked_list_head | Linked list head pointer for channel management |
| 0x15-0x16 | channel_state_ptr | Computed channel state record pointer (16-bit) |
| 0x17 | chain_present_flag | Chain-present flag (0xFF=chained, 0x00=not chained) |
| 0x18-0x27 | seq_var_workspace | Sequence variable workspace (accessible by variable classifier indices 6-21) |
| 0x28 | master_speech_vol | Master speech volume (high 3 bits of mixer) |
| 0x29 | master_eff_music_vol | Master effects+music volume (low 5 bits of mixer) |
| 0x2A | timer_countdown | Timer countdown (decremented in IRQ; on expiry, writes $29 to 0x1020) |
| 0x2B-0x2C | music_seq_ptr | Music/speech sequence data pointer (16-bit) |
| 0x2D-0x2E | music_seq_length | Music/speech sequence length (16-bit) |
| 0x2F | music_active_flag | Music/speech active flag (0x00=idle, 0x80=playing, 0xFF=ending) |
| 0x30 | music_state_a | Music state variable A (initialized to 0xFF) |
| 0x31-0x32 | music_index_calc | Music index calculation workspace (16-bit) |
| 0x34 | music_status_bits | Music status bits (bit 7 = special mode; written to 0x1033) |
| 0x35 | music_tempo | Music tempo value |
| 0x36-0x39 | coin_led_accum | Coin counter LED pulse accumulators (4 channels, used by `control_register_update` second path) |
| 0x3E-0x41 | coin_led_envelope | Coin counter LED envelope states (attack/decay values, AND'd with 0x1F) |
| 0x42 | coin_led_frame_ctr | Coin counter LED frame counter (incremented each call; LSB selects normalization pass) |
| 0x44 | coin_led_output | Coin counter/LED combined output byte (bit-mapped to 4 channels via masks at 0x83A4) |

### 1.2 Stack (0x0100-0x01FF)

Standard 6502 stack. Initialized to 0x01FF on reset.

### 1.3 Command Buffer (0x0200-0x0226)

| Address | Name | Purpose |
|---------|------|---------|
| 0x0200-0x020F | cmd_circular_buf | Circular command queue (16 entries, 1 byte each) |
| 0x0210 | cmd_read_ptr | Command buffer read pointer |
| 0x0211 | cmd_write_ptr | Command buffer write pointer |
| 0x0212 | nmi_buf_state | NMI buffer state counter |
| 0x0213 | nmi_mode_flag | NMI mode flag (0=normal, nonzero=alternate path) |
| 0x0214-0x0223 | output_buf | Output buffer to main CPU (16 entries) |
| 0x0224 | output_read_ptr | Output buffer read pointer |
| 0x0225 | output_write_ptr | Output buffer write pointer |
| 0x0226 | output_overflow_flag | Output buffer overflow flag (0x80=overflow) |
| 0x0227 | sfx_data_offset_save | Saved SFX data offset during channel allocation |

### 1.4 Sound Channel State (0x0228-0x0809)

30 logical channels, each with 48 state arrays. Arrays are indexed by channel number X (0-29).

| Array Base | Name | Purpose |
|-----------|------|---------|
| 0x0228+X | chan_active_cmd | Active command ID (0xFF=dead, 0xFE=special marker) |
| 0x0246+X | chan_seq_ptr_lo | Sequence pointer low byte |
| 0x0264+X | chan_seq_ptr_hi | Sequence pointer high byte |
| 0x0282+X | chan_base_freq_lo | Base frequency low byte |
| 0x02A0+X | chan_base_freq_hi | Base frequency high byte (YM2151 only) |
| 0x02BE+X | chan_pri_timer_lo | Primary timer low (note duration countdown) |
| 0x02DC+X | chan_pri_timer_hi | Primary timer high |
| 0x02FA+X | chan_sec_timer_lo | Secondary timer low (envelope trigger countdown) |
| 0x0318+X | chan_sec_timer_hi | Secondary timer high |
| 0x0336+X | chan_current_note | Current note data (raw byte 1 from sequence) |
| 0x0390+X | chan_status | Channel status (0=inactive; bit 0=type; priority encoded) |
| 0x03AE+X | chan_dist_shape | Distortion shape index (into table at 0x5C8F) |
| 0x03CC+X | chan_ctrl_mask | Control AND mask (AUDCTL) |
| 0x03EA+X | chan_ctrl_bits | Control OR bits (AUDCTL) |
| 0x0408+X | chan_base_volume | Base volume (0x00-0x0F) |
| 0x0426+X | chan_vol_env_ptr_lo | Volume envelope pointer low byte |
| 0x0444+X | chan_vol_env_ptr_hi | Volume envelope pointer high byte |
| 0x0462+X | chan_freq_env_ptr_lo | Frequency envelope pointer low byte |
| 0x0480+X | chan_freq_env_ptr_hi | Frequency envelope pointer high byte |
| 0x049E+X | chan_vol_env_pos | Volume envelope position |
| 0x04BC+X | chan_vol_env_frame | Volume envelope frame counter |
| 0x04DA+X | chan_vol_env_mod | Volume envelope modulation accumulator |
| 0x04F8+X | chan_vol_env_loop | Volume envelope loop counter |
| 0x0516+X | chan_freq_env_pos | Frequency envelope position |
| 0x0534+X | chan_freq_env_frame | Frequency envelope frame counter |
| 0x0552+X | chan_freq_accum_lo | Frequency accumulator low (24-bit pitch) |
| 0x0570+X | chan_freq_accum_mid | Frequency accumulator mid |
| 0x058E+X | chan_freq_accum_hi | Frequency accumulator high |
| 0x05AC+X | chan_freq_env_loop | Frequency envelope loop counter |
| 0x05CA+X | chan_tempo | Tempo/speed (higher = faster; subtracted from duration each frame) |
| 0x05E8+X | chan_transpose | Transpose offset (added to note values) |
| 0x0606+X | chan_repeat_state | Repeat state |
| 0x0624+X | chan_repeat_counter | Repeat counter |
| 0x0642+X | chan_dist_mask | Distortion mask (OR'd with volume output) |
| 0x0660+X | chan_vibrato_depth | Vibrato depth |
| 0x067E+X | chan_porta_delta_lo | Portamento delta low byte |
| 0x069C+X | chan_porta_delta_hi | Portamento delta high byte |
| 0x06BA+X | chan_seg_chain_a | Segment chain A (linked list for multi-segment sequences) |
| 0x06D8+X | chan_seg_chain_b | Segment chain B |
| 0x06F6+X | chan_ext_chain_ctr | Extended chain counter |
| 0x0714+X | chan_env_counter_lo | Envelope counter low |
| 0x0732+X | chan_env_counter_hi | Envelope counter high |
| 0x0750+X | chan_env_rate_lo | Envelope rate low |
| 0x076E+X | chan_env_rate_hi | Envelope rate high |
| 0x078C+X | chan_env_frac | Envelope fractional accumulator |
| 0x07AA+X | chan_gp_register | General-purpose register (used by opcodes) |
| 0x07C8+X | chan_reg_shadow | Register shadow |
| 0x07E6+X | chan_linked_next | Linked list next pointer (0=end of list) |

### 1.5 Work Area (0x0810-0x083B)

| Address | Name | Purpose |
|---------|------|---------|
| 0x0810 | work_channel_index | Current channel index save |
| 0x0811-0x0813 | work_misc | Miscellaneous work bytes; 0x0813 = channel type (0=POKEY, 1=YM2151) |
| 0x0814-0x0815 | work_sel_status | Selected channel status (after mix) |
| 0x0816 | work_sel_freq_alt | Selected alternate frequency |
| 0x0817 | work_volume | Volume/control byte output (POKEY AUDCx or YM2151 TL) |
| 0x0818 | work_volume_2 | Volume second value |
| 0x0819 | work_freq_lo | Frequency low byte output |
| 0x081A | work_freq_hi | Frequency high byte output (YM2151) |
| 0x081B | work_porta_lo | Portamento low (frequency fine adjust) |
| 0x081C | work_saved_chan_x | Saved current channel index during chaining |
| 0x081D | work_channel_type | Channel hardware type (0=POKEY, 2=YM2151) |
| 0x081E-0x0821 | work_extra_params | Additional params (POKEY distortion / YM2151 DT/MUL) |
| 0x0822-0x0825 | work_audctl_bits | AUDCTL mask bits |
| 0x0826 | work_vol_env_copy | Volume envelope position copy |
| 0x082F | work_update_flag | "Update needed" flag (1=write to hardware) |
| 0x0830-0x0831 | work_match_val | Match value for channel search / dispatch parameter |
| 0x0832 | speech_queue_read | Speech queue read pointer |
| 0x0833 | speech_queue_write | Speech queue write pointer |
| 0x0834-0x083B | speech_queue_buf | Speech command queue (8 entries, circular) |

### 1.6 YM2151 Operator Shadow Area (0x083C-0x089F)

| Address | Name | Purpose |
|---------|------|---------|
| 0x083C | ym_channel_num | Current YM2151 channel number (0-7) |
| 0x083D+0x08 | ym_shadow_key_on | Key On register shadow |
| 0x083D+0x20 | ym_shadow_dt2_conn | DT2/connection per channel (reg 0x20+ch) |
| 0x083D+0x28 | ym_shadow_noise | Noise/LFO per channel (reg 0x28+ch) |
| 0x083D+0x30 | ym_shadow_dt1_mul | DT1/MUL per channel (reg 0x30+ch) |
| 0x083D+0x38 | ym_shadow_tl | Total Level per channel (reg 0x38+ch) |
| 0x083D+0x40-0x78 | ym_shadow_ops | Operator parameters (4 ops x 8 regs each) |

### 1.7 Channel State Records (0x093D+)

Computed by `channel_state_ptr_calc`: `address = 0x093D + (channel - 1) * 4`

| Offset | Purpose |
|--------|---------|
| +0 | Next-channel link (linked list traversal) |
| +1-2 | Saved sequence pointer (16-bit) |
| +3 | Repeat/loop counter |

---

## 2. Hardware I/O (0x1000-0x1FFF)

### 2.1 Main CPU Interface

| Address | R/W | Name | Purpose |
|---------|-----|------|---------|
| 0x1000 | W | data_output | Data output to main CPU. Write triggers IRQ to main CPU + latches data byte. |
| 0x1002 | W | data_output_alias_1 | Alias of 0x1000 (low 4 address bits not decoded) |
| 0x1003 | W | data_output_alias_2 | Alias of 0x1000 |
| 0x100B | W | data_output_alias_3 | Alias of 0x1000 |
| 0x100C | W | data_output_alias_4 | Alias of 0x1000 |
| 0x1010 | R | cmd_input | Command input from main CPU. Hardware-latched simultaneously with NMI trigger. |
| 0x1020 | W | volume_mixer | Volume mixer. Bits 7-5: speech (TMS5220, 8 levels). Bits 4-3: effects (POKEY, 4 levels). Bits 2-0: music (YM2151, 8 levels). |

### 2.2 Status/Control Register (0x1030)

| Address | R/W | Name | Bit Map |
|---------|-----|------|---------|
| 0x1030 | R | status_read | Bit 0-3: coin slots 1-4. Bit 4: self-test enable. Bit 5: TMS5220 ready. Bit 6: sound buffer full. Bit 7: main CPU (68010) output buffer full. |
| 0x1030 | W | ym2151_reset | Write triggers YM2151 reset (value is don't-care). Also used for boot handshake sequence. |

### 2.3 Coin Counter / LED Outputs

| Address | R/W | Name | Purpose |
|---------|-----|------|---------|
| 0x1034 | W | coin_led_out_hi | Coin counter LED output, channels 2-3 combined (`$38 OR $39`). Written by `control_register_update`. |
| 0x1035 | W | coin_led_out_lo | Coin counter LED output, channels 0-1 combined (`$36 OR $37`). Written by `control_register_update`. |

### 2.4 TMS5220 Control

| Address | R/W | Name | Purpose |
|---------|-----|------|---------|
| 0x1032 | W | tms5220_reset | TMS5220 chip reset (value is don't-care) |
| 0x1033 | W | speech_squeak | Changes TMS5220 oscillator frequency (voice pitch effect) |

### 2.5 POKEY (0x1800-0x180F)

Accessed via indirect addressing through zero-page pointer (0x08-0x09 = 0x1800).

| Address | Name | Purpose |
|---------|------|---------|
| 0x1800 | AUDF1 | Channel 1 frequency |
| 0x1801 | AUDC1 | Channel 1 control (bits 7-4: volume, bits 3-0: distortion) |
| 0x1802 | AUDF2 | Channel 2 frequency |
| 0x1803 | AUDC2 | Channel 2 control |
| 0x1804 | AUDF3 | Channel 3 frequency |
| 0x1805 | AUDC3 | Channel 3 control |
| 0x1806 | AUDF4 | Channel 4 frequency |
| 0x1807 | AUDC4 | Channel 4 control |
| 0x1808 | AUDCTL | Audio control register (clock dividers, high-pass filters) |

### 2.6 YM2151 (0x1810-0x1811)

| Address | R/W | Name | Purpose |
|---------|-----|------|---------|
| 0x1810 | W | ym2151_reg_sel | Register select (written via `STY $1810`) |
| 0x1811 | W | ym2151_data | Data write (written via `STA $1811`) |
| 0x1811 | R | ym2151_status | Status read (bit 7: busy flag; polled by `ym2151_wait_ready`) |

### 2.7 TMS5220 (0x1820)

| Address | R/W | Name | Purpose |
|---------|-----|------|---------|
| 0x1820 | W | tms5220_data | Speech data input. LPC bytes streamed by `sound_status_update`. |

### 2.8 IRQ Acknowledge (0x1830)

| Address | R/W | Name | Purpose |
|---------|-----|------|---------|
| 0x1830 | W | irq_ack | IRQ acknowledge. Write resets 6502 IRQ line (value is don't-care). |

---

## 3. ROM (0x4000-0xFFFF)

### 3.1 ROM Region Overview

| Range | Size | Contents |
|-------|------|----------|
| 0x4000-0x5CFF | ~7.5 KB | Code (functions, handlers, state machine) |
| 0x5D00-0x6FFF | ~5 KB | Data tables (command dispatch, SFX metadata) |
| 0x7000-0x86FF | ~6 KB | POKEY SFX sequence data |
| 0x8700-0xACFF | ~10 KB | YM2151 music sequence data |
| 0xAD00-0xFECD | ~21 KB | TMS5220 speech LPC data |
| 0xFECE-0xFFF5 | 296 B | Unused (zero-padded) |
| 0xFFF6-0xFFF9 | 4 B | Mystery bytes (`8C FF 00 00`), unreferenced |
| 0xFFFA-0xFFFF | 6 B | 6502 interrupt vectors |

### 3.2 Functions in ROM

#### System & Boot

| Address | Name | Purpose |
|---------|------|---------|
| 0x4002 | init_main | Main initialization: stack setup, RAM test, hardware init, enable IRQ |
| 0x4142 | ram_error_handler | Handle RAM test failures |
| 0x415F | checksum_ram | Verify memory integrity via multi-page checksum |
| 0x41E6 | clear_sound_buffers | Zero all sound channel buffers and build free-channel list |
| 0x5833 | init_sound_state | Initialize sound system state variables and pointers |
| 0x5A0B | init_hardware_regs | Initialize hardware control registers (0x1000-0x100C) |
| 0x5A25 | reset_handler | Reset vector entry point; waits for main CPU ready signal on 0x1030 |

#### Main Loop & Dispatch

| Address | Name | Purpose |
|---------|------|---------|
| 0x40C8 | main_loop | Main execution loop; polls command buffer and dispatches |
| 0x432E | command_dispatcher | Two-level command dispatch (219 commands -> 15 handler types) |

#### Interrupt Handlers

| Address | Name | Purpose |
|---------|------|---------|
| 0x4183 | irq_ack_write | Simple wrapper: `STA $1830; RTS` (IRQ acknowledge) |
| 0x4187 | irq_handler | Real-time audio processing at ~240Hz |
| 0x41C8 | irq_audio_update | Audio update subroutine called from IRQ: 3x status + alternating channel + 1x status |
| 0x57B0 | nmi_handler | Command input from main CPU (event-driven) |
| 0x57F0 | nmi_command_input | Validate and buffer commands from NMI |

#### Command Handlers (Type 0-14)

| Address | Name | Handler Type | Purpose |
|---------|------|-------------|---------|
| 0x4347 | handler_type_0 | 0 | Parameter shift (ASL A x2); commands 0x01-0x02 |
| 0x434C | handler_type_1 | 1 | Set variable from data table (reserved, never dispatched) |
| 0x4359 | handler_type_2 | 2 | Add to variable from data table (reserved, never dispatched) |
| 0x4369 | handler_type_3 | 3 | Jump table dispatch for special commands; command 0x00 |
| 0x4374 | handler_kill_by_status | 4 | Kill channels by status pattern match (reserved, never dispatched) |
| 0x438D | handler_stop_sound | 5 | Stop specific named sound; commands 0x21, 0x2F, 0x39 |
| 0x43AF | handler_stop_chain | 6 | Stop channel chain by group (reserved, never dispatched) |
| 0x43D4 | handler_fadeout_sound | 9 | Fade out specific sound; command 0x3C ("Theme Fade Out") |
| 0x440B | handler_fadeout_by_status | 10 | Fade out by status match; command 0x41 ("Treasure Fade Out") |
| 0x4439 | handler_type_11 | 11 | YM2151 music/speech entry; ~112 commands (0x08, 0x4A-0xD5) |
| 0x4445 | handler_type_8 | 8 | Queue commands to main CPU output buffer; command 0xDA |
| 0x4461 | handler_channel_control | 12 | Complex channel manipulation (reserved, never dispatched) |
| 0x44DE | handler_type_7 | 7 | Main POKEY SFX handler with priority system; ~90 commands |
| 0x4618 | handler_type_14 | 14 | Null handler (single RTS; reserved, never dispatched) |
| 0x4619 | handler_type_13 | 13 | Update volume mixer register 0x1020; commands 0xD6-0xD9 |

#### Channel Management

| Address | Name | Size | Purpose |
|---------|------|------|---------|
| 0x4295 | channel_list_init | 49B | Build free-channel linked list (1->2->...->N->0) |
| 0x42C6 | channel_list_follow | 17B | Follow linked-list pointer to next channel |
| 0x42D7 | channel_state_ptr_calc | 34B | Compute ZP pointer to channel's 4-byte state record |
| 0x42F9 | channel_list_unlink | 53B | Remove channel from active linked lists |
| 0x500D | channel_dispatcher | ~40B | Route to POKEY/YM2151/RAM based on channel index (X=0->POKEY, X=1->YM2151) |
| 0x5059 | channel_find_active_cmd | 22B | Search for channel playing specific command |
| 0x506F | channel_dispatch_by_type | 12B | Dispatch handler by type from opcode table |

#### Core State Machine

| Address | Name | Size | Purpose |
|---------|------|------|---------|
| 0x4651 | channel_state_machine | ~1300B | Core engine: sequence interpreter, envelope processing, frame-by-frame playback for all channel types |

#### Sequence Engine

| Address | Name | Size | Purpose |
|---------|------|------|---------|
| 0x5029 | seq_opcode_dispatch | 30B | Bytecode interpreter: dispatch 59 opcodes (0x80-0xBA) via jump table at 0x507B |
| 0x5047 | seq_advance_read | 18B | Advance 16-bit sequence pointer and read next byte (19 callers, most-called function) |
| 0x5181 | channel_apply_volume | 22B | Apply volume adjustment to channel output |
| 0x5444 | seq_var_classifier | 109B | Map variable index to channel state array for read/write |

#### POKEY Pipeline

| Address | Name | Size | Purpose |
|---------|------|------|---------|
| 0x4B6B | envelope_process_freq | 171B | Frequency envelope: 24-bit pitch modulation via envelope shape tables |
| 0x4D02 | pokey_channel_mix | 250B | Mix two channel groups, select highest-priority output per physical channel |
| 0x4DFC | pokey_update_registers | 77B | Orchestrate POKEY channel processing (2 pairs x mix + write) |
| 0x4E1B | pokey_write_registers | 77B | Write computed values to physical POKEY AUDFx/AUDCx/AUDCTL registers |

#### YM2151 Pipeline

| Address | Name | Size | Purpose |
|---------|------|------|---------|
| 0x4C16 | ym2151_update_channel_state | 236B | Copy channel state to operator shadow area + vibrato processing |
| 0x4E68 | ym2151_write_operator | ~140B | Write 3-5 YM2151 registers per channel (operator config, key on, noise) |
| 0x4FD6 | ym2151_channel_update | ~26B | Loop over 8 YM2151 channels, calling write_operator for each |
| 0x4FF0 | ym2151_wait_ready | ~30B | Busy-wait for YM2151 ready (polls bit 7 of 0x1811; timeout after 255 checks) |
| 0x558F | ym2151_load_voice | 132B | Load complete FM voice/instrument definition (patch) to all 4 operators |
| 0x5614 | seq_op_ym_write_regs | 65B | Sequence opcode: write YM2151 register block from sequence data |
| 0x5656 | seq_op_ym_write_single | 28B | Sequence opcode: write single YM2151 register |
| 0x5676 | ym2151_write_reg_indirect | 20B | Generic YM2151 register write with shadow storage |
| 0x568A | seq_op_ym_set_algorithm | 37B | Sequence opcode: set YM2151 algorithm/feedback |
| 0x56AF | ym2151_sub_detune | 45B | Subtract from YM2151 detune value |
| 0x5715 | ym2151_apply_detune | ~64B | Apply pitch/detune adjustment to all 4 operators |
| 0x5755 | ym2151_reload_vol_env | 59B | Reload volume envelope base from voice definition |

#### Music/Speech

| Address | Name | Purpose |
|---------|------|---------|
| 0x5932 | music_speech_handler | Main music/speech playback: load sequence, calculate volume, start playback |

#### Status & Control

| Address | Name | Purpose |
|---------|------|---------|
| 0x5894 | sound_status_update | Stream speech data to TMS5220 (0x1820), manage speech queue at 0x0832-0x083B |
| 0x59E2 | speech_queue_enqueue | Priority-based circular queue enqueue for speech/sound commands. Uses $0832/$0833 read/write indices, $0834-$083B buffer, $35 priority. Called via JMP from `music_speech_handler`. |
| 0x8381 | control_register_update | Coin counter LED controller (190 bytes, 0x8381-0x843E). Two paths: (1) When bit 4 of $1030 is clear: maps coin inputs to LED state via $44 using inline masks. (2) When bit 4 is set: 4-channel attack/decay envelope processor using $36-$39 accumulators, $3E-$41 envelope states, $42 frame counter. Writes combined outputs to $1034 and $1035. Inline data table at 0x83A4-0x83AB. |

### 3.3 Data Tables in ROM

#### Command Dispatch Tables

| Address | Name | Size | Format | Purpose |
|---------|------|------|--------|---------|
| 0x4633 | handler_addr_table | 32B | 16-bit LE addr-1 pairs (15 entries + sentinel) | Handler type -> function address (RTS dispatch trick: stored value = target - 1) |
| 0x5D0F | nmi_validation_table | 219B | 1 byte/cmd | NMI command validation (0xFF=store in buffer, 0x00-0x02=immediate NMI dispatch) |
| 0x5DEA | cmd_type_map | 219B | 1 byte/cmd | Command number -> handler type (0x00-0x0E valid, 0xFF=no handler) |
| 0x5EC5 | cmd_param_table | 219B | 1 byte/cmd | Command parameter loaded into A before handler call |
| 0x5FA2 | nmi_dispatch_table | 6B | 3 x 16-bit LE addr-1 | NMI immediate dispatch handlers for validation types 0-2 |

#### POKEY SFX Metadata Tables

| Address | Name | Size | Format | Purpose |
|---------|------|------|--------|---------|
| 0x5FA8 | sfx_data_offset | ~62B | 1 byte/sound | SFX command parameter -> index into data pointer and metadata tables |
| 0x5FE6 | sfx_flags | ~62B | 1 byte/sound | Behavior flags (0xFF=immediate play/no dup check, 0x00=check for duplicates) |
| 0x6024 | sfx_priority | ~62B | 1 byte/sound | Interrupt priority (0x00=lowest, 0x0F=highest/uninterruptible) |
| 0x60DA | sfx_channel_map | ~62B | 1 byte/sound | Physical POKEY channel assignment (0x04-0x0B) |
| 0x6190 | sfx_data_ptrs_a | ~200B | 16-bit LE pairs | Primary sound sequence data pointers |
| 0x6290 | sfx_data_ptrs_b | ~200B | 16-bit LE pairs | Alternate sound sequence data pointers |
| 0x62FC | sfx_chain_offsets | ~180B | 1 byte/entry | Multi-channel chaining table (0x00=end, nonzero=next offset for additional channels) |

#### YM2151 Music/Speech Metadata Tables

| Address | Name | Size | Format | Purpose |
|---------|------|------|--------|---------|
| 0x63B2 | music_seq_index | 219B | 1 byte/cmd | Command -> sequence index (0x00-0x5B) into pointer tables |
| 0x643F | music_flags | 219B | 1 byte/cmd | Bit 7: special mode (updates 0x1033); bits 0-3: volume calculation params |
| 0x64CC | music_tempo | 219B | 1 byte/cmd | Tempo value (mostly 0x00 = default) |
| 0x8449 | music_seq_ptrs | ~184B | 16-bit LE pairs (~92 entries) | Pointers to music/speech note sequence data |
| 0x85C3 | music_seq_lengths | ~184B | 16-bit LE pairs (~92 entries) | Sequence length/loop parameters |

#### Sequence Engine Tables

| Address | Name | Size | Format | Purpose |
|---------|------|------|--------|---------|
| 0x507B | opcode_jump_table | 118B | 59 x 16-bit LE addr-1 | Sequence opcode handlers (0x80-0xBA); stored as target-1 for RTS dispatch |
| 0x5A35 | ym2151_freq_table | 256B | 128 x 16-bit LE | Note number -> YM2151 frequency parameter. Note 0=rest; note 0x46 (70)=A4 (440Hz). MIDI note = ROM note - 1. |
| 0x5C5F | duration_table | 32B | 16 x 16-bit LE | Musical note durations in fixed-point (index 0-15; see format below) |
| 0x5C7F | freq_env_shape_table | ~16B | 1 byte/entry | Frequency envelope shape multipliers (0xFF=envelope finished) |
| 0x5C8F | vol_env_shape_table | ~16B | 1 byte/entry | Volume envelope distortion shapes (RAM-initialized at boot) |

**Duration Table (0x5C5F) values**:

| Index | Value | Musical Duration |
|-------|-------|-----------------|
| 0x0 | 0x0000 | Immediate/rest |
| 0x1 | 0x1E00 | Whole note |
| 0x2 | 0x0F00 | Half note |
| 0x3 | 0x0780 | Quarter note |
| 0x4 | 0x03C0 | Eighth note |
| 0x5 | 0x0A00 | Dotted half |
| 0x6 | 0x0500 | Dotted quarter |
| 0x7 | 0x0280 | Dotted eighth |
| 0x8 | 0x0600 | Triplet half |
| 0x9 | 0x01E0 | Sixteenth note |
| 0xA | 0x00F0 | Thirty-second note |
| 0xB | 0x0078 | Sixty-fourth note |
| 0xC | 0x003C | 128th note |
| 0xD | 0x0140 | Dotted sixteenth |
| 0xE | 0x00A0 | Dotted thirty-second |
| 0xF | 0x0300 | Triplet quarter |

#### Hardware Configuration Tables

| Address | Name | Size | Format | Purpose |
|---------|------|------|--------|---------|
| 0x57A8 | hw_ptr_table | 8B | Interleaved low bytes | Channel index -> hardware base address low bytes (0=0x00, 1=0x10, 2=0x18, 3=0x18) |
| 0x57AA | hw_ptr_table_hi | 8B | Interleaved high bytes | Channel index -> hardware base address high bytes (0=0x18, 1=0x18, 2=0x00, 3=0x02) |
| 0x57AC | hw_channel_types | 8B | 1 byte/channel | Hardware chip type (0x00=POKEY, 0x03=YM2151) |
| 0x57AE | hw_channel_config | 8B | 1 byte/channel | Additional channel parameters (register base offsets) |

**Hardware pointer resolution**:

| Index | Pointer | Target |
|-------|---------|--------|
| 0 | 0x1800 | POKEY base |
| 1 | 0x1810 | YM2151 base |
| 2 | 0x0018 | RAM workspace |
| 3 | 0x0218 | RAM buffer |

#### YM2151 Operator Tables

| Address | Name | Size | Format | Purpose |
|---------|------|------|--------|---------|
| 0x5AF9 | ym_operator_params | ~64B | 1 byte/entry | Noise/LFO settings per operator configuration |
| 0x57A0 | ym_algo_op_mask | ~8B | 1 byte/algo | Operator mask per algorithm (for detune application) |

#### Control Register Inline Data

| Address | Name | Size | Format | Purpose |
|---------|------|------|--------|---------|
| 0x83A4-0x83A7 | coin_led_on_masks | 4B | 1 byte/channel | Bit masks for LED "on" states: `40 10 04 01` (channels 0-3) |
| 0x83A8-0x83AB | coin_led_field_masks | 4B | 1 byte/channel | Bit masks for field isolation: `C0 30 0C 03` (channels 0-3) |

#### Initialization Data

| Address | Name | Size | Format | Purpose |
|---------|------|------|--------|---------|
| 0x5F20 | init_data_table | ~100B | Sequential bytes | Initialization values (0x12-0x75) used during boot |
| 0x655C | handler_match_table | ~var | 1 byte/entry | Match values for handler_stop_sound / handler_fadeout operations |

#### NMI Dispatch Targets

| Index | Address | Purpose |
|-------|---------|---------|
| 0 | 0x843F | NMI dispatch handler 0 |
| 1 | 0x44B8 | NMI dispatch handler 1 |
| 2 | 0x44A8 | NMI dispatch handler 2 |

### 3.4 Sound Data Regions

| Range | Size | Contents |
|-------|------|----------|
| 0x6800-0x7FFF | ~6 KB | POKEY SFX sequence data (2-byte frames: freq/opcode + duration/envelope) |
| 0x8700-0xACFF | ~10 KB | YM2151 music sequence data (same 2-byte frame format, shared bytecode engine) |
| 0xAD00-0xFFF9 | ~21 KB | TMS5220 speech LPC data (bit-packed Linear Predictive Coding frames) |

### 3.5 Interrupt Vectors

| Address | Name | Target |
|---------|------|--------|
| 0xFFFA | NMI vector | 0x57B0 (nmi_handler) |
| 0xFFFC | RESET vector | 0x5A25 (reset_handler) |
| 0xFFFE | IRQ vector | 0x4187 (irq_handler) |

### 3.6 Unused ROM Space (~366 bytes total)

| Address | Size | Fill Pattern | Context |
|---------|------|-------------|---------|
| 0x5874-0x5893 | 32 B | 0xFF (erased EPROM) | Between `init_sound_state` (RTS at 0x5873) and `sound_status_update` (0x5894) |
| 0x6000-0x6023 | 36 B | 0xFF (erased EPROM) | Before `sfx_priority` table (0x6024). Unreferenced by any code. |
| 0x8447-0x8448 | 2 B | `94 FF` | Between NMI handler 0 (ends 0x8446) and `music_seq_ptrs` table (starts 0x8449). Unreferenced. |
| 0xFECE-0xFFF5 | 296 B | 0x00 (zero-padded) | Between end of speech LPC data and interrupt vectors. ROM build tool padding. |
| 0xFFF6-0xFFF9 | 4 B | `8C FF 00 00` | Between zero padding and interrupt vectors. Not standard 6502 vectors. Unreferenced. |

**Note**: Several regions that appear to contain 0xFF or 0x00 runs are actually legitimate data:
- 0x5D17-0x5DE9: 0xFF bytes in `nmi_validation_table` (value means "store in buffer")
- 0x5FE6-0x5FFE: 0xFF bytes in `sfx_flags` table (value means "immediate play")
- 0x5C8F: 32 zero bytes in `vol_env_shape_table` (legitimate zero envelope values)

---

## 4. Sequence Data Format

All sound channels (POKEY SFX, YM2151 music, TMS5220 speech) use the same 2-byte frame format, interpreted by `channel_state_machine` (0x4651).

### Frame Format

```
Byte 0 (Frequency/Opcode):
  0x00-0x7F: Note/frequency value (bit 7 clear)
  0x80-0xBA: Sequence opcode (bit 7 set; dispatched via jump table at 0x507B)
  0xBB-0xFF: End-of-sequence marker (channel stops)

Byte 1 (Duration/Envelope) -- present only when Byte 0 is a note (0x00-0x7F):
  Bits 0-3: Duration index (into table at 0x5C5F, 16 entries)
  Bits 4-5: Division control (affects secondary envelope timer rate)
  Bit 6:    Dotted note flag (x1.5 duration multiplier)
  Bit 7:    Sustain flag (sets secondary timer = 0x7F; note rings until next note)

  Value 0x00: Channel chain -- load next segment from linked list
```

### Sequence Opcodes (59 opcodes, 0x80-0xBA)

| Opcode | Handler | Name | Args | Description |
|--------|---------|------|------|-------------|
| 0x80 | 0x5173 | SET_TEMPO | 1 | arg>>2 -> tempo |
| 0x81 | 0x516A | ADD_TEMPO | 1 | Add to tempo (8-bit wrapping) |
| 0x82 | 0x5192 | SET_VOLUME | 1 | Set base volume / YM2151 detune |
| 0x83 | 0x517A | SET_VOLUME_CHK | 1 | Set volume (with 0xFE marker check) |
| 0x84 | 0x51AE | ADD_TRANSPOSE | 1 | Add to transpose offset |
| 0x85 | 0x51AA | NOP_FE_CHECK | 1 | No-op if channel ended (0xFE) |
| 0x86 | 0x515F | SET_FREQ_ENV | 2 | Set frequency envelope pointer (16-bit) |
| 0x87 | 0x5154 | SET_VOL_ENV | 2 | Set volume envelope pointer (16-bit) |
| 0x88 | 0x50F1 | RESET_TIMER | 1 | Reset timers and counters |
| 0x89 | 0x514B | SET_REPEAT | 1 | Set repeat counter |
| 0x8A | 0x51B3 | SET_DISTORTION | 1 | Set distortion mask |
| 0x8B | 0x51B7 | SET_CTRL_BITS | 1 | Set control bits (OR) |
| 0x8C | 0x51CB | CLR_CTRL_BITS | 1 | Clear control bits (AND/OR masks) |
| 0x8D | 0x51E2 | SET_VIBRATO | 1 | Set vibrato depth |
| 0x8E | 0x51E6 | PUSH_SEQ | 2 | Push current pointer, load new segment (16-bit) |
| 0x8F | 0x5214 | PUSH_SEQ_EXT | 1 | Push to extended chain |
| 0x90 | 0x54CC | SWITCH_POKEY | 1 | Switch channel to POKEY mode |
| 0x91 | 0x54E5 | SWITCH_YM2151 | 1 | Switch channel to YM2151 mode |
| 0x92-0x95 | 0x4719 | NOP | 0 | No-op (reserved) |
| 0x96 | 0x54F4 | QUEUE_OUTPUT | 1 | Queue byte to main CPU output buffer |
| 0x97 | 0x54F9 | RESET_ENVELOPE | 0 | Reset envelope to defaults, set 0xFE marker |
| 0x98 | 0x4719 | NOP | 0 | No-op |
| 0x99 | 0x5515 | SET_SEQ_PTR | 2 | Unconditional jump (set sequence pointer, 16-bit) |
| 0x9A | 0x5524 | PLAY_MUSIC_CMD | 1 | Trigger music command from within sequence |
| 0x9B | 0x51CB | SET_VAR_NAMED | 1 | Set named variable via classifier |
| 0x9C | 0x54B1 | FORCE_POKEY | 1 | Force POKEY mode + clear YM status |
| 0x9D | 0x5535 | SET_VOICE | 2+ | Load YM2151 voice/instrument definition (FM patch) |
| 0x9E | 0x5271 | SET_ENV_PARAMS | 2 | Set envelope rate/shape parameters |
| 0x9F | various | YM_LOAD_REG | 2 | Load YM2151 register block (pointer+0x29) |
| 0xA0-0xA3 | various | REG_OPS | 1 | Register operations (freq offset, detune neg, OR, XOR) |
| 0xA4 | 0x5271 | VAR_LOAD | 2 | Load pair to sequence variables |
| 0xA5-0xA6 | various | SHIFT_OPS | 1 | NOP / shift left |
| 0xA7 | 0x56DC | FREQ_ADD | 1 | Signed frequency detune |
| 0xA8 | 0x5711 | SET_RELEASE | 1 | Set release rate |
| 0xA9-0xAD | various | VAR_OPS | 1 | Variable add/sub/AND/OR/XOR |
| 0xAE | 0x5320 | COND_JUMP | 2* | Conditional jump (if var=0: jump; variable-length) |
| 0xAF | 0x5347 | COND_JUMP_INC | 2* | Conditional jump + increment variable |
| 0xB0-0xB2 | various | VAR_ACCESS | 1 | var_to_reg, var_apply, var_classify |
| 0xB3-0xB4 | various | SHIFT_VAR | 1 | Shift variable right/left |
| 0xB5-0xB8 | various | COND_BRANCH | 3 | Classify + conditional jump (EQ/NE/PL/MI, 2-byte address) |
| 0xB9-0xBA | various | VAR_SUB | 1 | Variable classify-subtract / sub-store |

### Timing Formula

```
seconds = (duration_table[byte1 & 0x0F] * (1.5 if bit 6 set else 1.0)) / tempo / 120
```

SET_TEMPO stores `arg >> 2` as tempo. Each frame (120Hz), tempo is subtracted from the note's duration timer.

### Note-to-Pitch Mapping

- MIDI note = ROM note value - 1
- Note 0x46 (70 decimal) = MIDI 69 = A4 (440Hz)
- Note 0 = rest/silence
- Chromatic scale with ratio 2^(1/12) between consecutive entries

---

## 5. Command Map Summary

219 commands (0x00-0xDA) dispatched through the two-level table system.

| Range | Handler Type | Category | Count |
|-------|-------------|----------|-------|
| 0x00 | 3 (jump dispatch) | System: stop all | 1 |
| 0x01-0x02 | 0 (param shift) | System: silent/noisy mode | 2 |
| 0x03, 0x06-0x07 | 0xFF (none) | Invalid/unused (silently ignored) | 3 |
| 0x04-0x05 | 7 (POKEY SFX) | Self-test: music chip, effects chip | 2 |
| 0x08 | 11 (music/speech) | Self-test: speech chip | 1 |
| 0x09-0x20 | 7 (POKEY SFX) | Sound effects | ~24 |
| 0x21 | 5 (stop sound) | Stop specific sound | 1 |
| 0x22-0x2E | 7 (POKEY SFX) | Sound effects | ~13 |
| 0x2F | 5 (stop sound) | Stop specific sound | 1 |
| 0x30-0x38 | 7 (POKEY SFX) | Sound effects | ~9 |
| 0x39 | 5 (stop sound) | Stop specific sound | 1 |
| 0x3A-0x3B | 7 (POKEY SFX) | Sound effects (including Theme Song) | 2 |
| 0x3C | 9 (fadeout) | Theme fade out | 1 |
| 0x3D-0x40 | 7 (POKEY SFX) | Sound effects (treasure rooms) | 4 |
| 0x41 | 10 (fadeout by status) | Treasure fade out | 1 |
| 0x42-0x49 | 7 (POKEY SFX) | Sound effects | ~8 |
| 0x4A-0xD5 | 11 (music/speech) | Music tracks and speech phrases | 112 |
| 0xD6-0xD9 | 13 (control reg) | Volume mixer control | 4 |
| 0xDA | 8 (output queue) | Queue data to main CPU | 1 |

Reserved handler types (code exists but no commands route to them): 1, 2, 4, 6, 12, 14.
