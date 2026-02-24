#!/usr/bin/env python3
"""Gauntlet Sound ROM Sequence Disassembler

Decodes the bytecode sequences in the Gauntlet sound ROM (48KB, 6502-based
sound coprocessor). Resolves any of the 219 sound commands to their
underlying sequence data and produces human-readable disassembly.

Includes TMS5220 LPC speech synthesis (ported from MAME's tms5220.cpp) for
decoding and exporting the ~140 speech phrases as WAV files.

Usage:
    python gauntlet_disasm.py soundrom.bin --cmd 0x0D
    python gauntlet_disasm.py soundrom.bin --list
    python gauntlet_disasm.py soundrom.bin --all
    python gauntlet_disasm.py soundrom.bin --addr 0x7234
    python gauntlet_disasm.py soundrom.bin --range 0x09-0x0C
    python gauntlet_disasm.py soundrom.bin --score 0x3B
    python gauntlet_disasm.py soundrom.bin --midi 0x3B
    python gauntlet_disasm.py soundrom.bin --midi 0x3B --midi-out theme.mid
    python gauntlet_disasm.py soundrom.bin --speech-wav 0x5A
    python gauntlet_disasm.py soundrom.bin --speech-wav 0x5A --out needs_food.wav
    python gauntlet_disasm.py soundrom.bin --speech-all
    python gauntlet_disasm.py soundrom.bin --speech-all --out-dir my_speech/
"""

import argparse
import csv
import os
import struct
import sys
import wave

# ── ROM Layout ────────────────────────────────────────────────────────────────

ROM_BASE = 0x4000
ROM_END  = 0xFFFF
ROM_SIZE = 0xC000   # 48KB

# ── Dispatch Tables ───────────────────────────────────────────────────────────

DISPATCH_TYPE_TABLE  = 0x5DEA   # 219 bytes: cmd -> handler type
DISPATCH_PARAM_TABLE = 0x5EC5   # 219 bytes: cmd -> parameter

# ── Type 7 (POKEY SFX) Tables ────────────────────────────────────────────────

SFX_OFFSET_TABLE   = 0x5FA8    # param -> data offset
SFX_FLAGS_TABLE    = 0x5FE6    # param -> flags (0xFF = immediate)
SFX_PRIORITY_TABLE = 0x6024    # offset -> priority
SFX_CHANNEL_TABLE  = 0x60DA    # offset -> channel
SFX_SEQ_PTR_TABLE  = 0x6190    # offset*2 -> 16-bit seq pointer (primary+alt)
SFX_NEXT_TABLE     = 0x62FC    # offset -> next offset (0 = end of chain)

# ── Type 11 (Music/Speech) Tables ────────────────────────────────────────────

MUSIC_INDEX_TABLE   = 0x63B2   # param -> sequence index
MUSIC_SEQ_PTR_TABLE = 0x8449   # index*2 -> 16-bit seq pointer
MUSIC_SEQ_LEN_TABLE = 0x85C3   # index*2 -> 16-bit length parameter

# ── Duration Table ────────────────────────────────────────────────────────────

DURATION_TABLE_ADDR = 0x5C5F   # 16 entries, 16-bit LE each

# ── Limits ────────────────────────────────────────────────────────────────────

MAX_COMMANDS  = 219    # 0x00 - 0xDA
MAX_SEQ_BYTES = 512

# ── Handler Type Descriptions ─────────────────────────────────────────────────

HANDLER_TYPES = {
    0:    "Parameter Shift",
    1:    "Set Variable",
    2:    "Add to Variable",
    3:    "Jump Table Dispatch",
    4:    "Kill by Status",
    5:    "Stop Sound",
    6:    "Stop Chain",
    7:    "POKEY SFX",
    8:    "Output Buffer Queue",
    9:    "Fade Out Sound",
    10:   "Fade Out by Status",
    11:   "YM2151 Music/Speech",
    12:   "Channel Control",
    13:   "Control Register",
    14:   "Null Handler",
    0xFF: "Invalid/Unused",
}

# ── Duration Names (index 0-15) ──────────────────────────────────────────────

DURATION_NAMES = [
    "rest",             # 0
    "whole",            # 1
    "half",             # 2
    "quarter",          # 3
    "eighth",           # 4
    "dotted-half",      # 5
    "dotted-quarter",   # 6
    "dotted-eighth",    # 7
    "triplet",          # 8
    "sixteenth",        # 9
    "32nd",             # A
    "64th",             # B
    "128th",            # C
    "dotted-16th",      # D
    "dotted-32nd",      # E
    "triplet-quarter",  # F
]

# ── Duration Abbreviations (for --score display) ──────────────────────────────

DURATION_ABBREVS = {
    "rest":             "rest",
    "whole":            "W",
    "half":             "H",
    "quarter":          "Q",
    "eighth":           "8th",
    "dotted-half":      "H.",
    "dotted-quarter":   "Q.",
    "dotted-eighth":    "8.",
    "triplet":          "trip",
    "sixteenth":        "16th",
    "32nd":             "32nd",
    "64th":             "64th",
    "128th":            "128",
    "dotted-16th":      "16.",
    "dotted-32nd":      "32.",
    "triplet-quarter":  "Qtr",
}

# ── TMS5220 Speech Synthesis Tables ──────────────────────────────────────────
#
# From MAME's tms5110r.hxx: tms5220_coeff struct (TI_028X_LATER_ENERGY,
# TI_5220_PITCH, TI_5110_5220_LPC, TI_LATER_CHIRP, TI_INTERP).

TMS5220_ENERGY_TABLE = [0, 1, 2, 3, 4, 6, 8, 11, 16, 23, 33, 47, 63, 85, 114, 0]

TMS5220_PITCH_TABLE = [
    0,  15,  16,  17,  18,  19,  20,  21,  22,  23,  24,  25,  26,  27,  28,  29,
   30,  31,  32,  33,  34,  35,  36,  37,  38,  39,  40,  41,  42,  44,  46,  48,
   50,  52,  53,  56,  58,  60,  62,  65,  68,  70,  72,  76,  78,  80,  84,  86,
   91,  94,  98, 101, 105, 109, 114, 118, 122, 127, 132, 137, 142, 148, 153, 159,
]

TMS5220_K1_TABLE = [
    -501, -498, -497, -495, -493, -491, -488, -482,
    -478, -474, -469, -464, -459, -452, -445, -437,
    -412, -380, -339, -288, -227, -158,  -81,   -1,
      80,  157,  226,  287,  337,  379,  411,  436,
]
TMS5220_K2_TABLE = [
    -328, -303, -274, -244, -211, -175, -138,  -99,
     -59,  -18,   24,   64,  105,  143,  180,  215,
     248,  278,  306,  331,  354,  374,  392,  408,
     422,  435,  445,  455,  463,  470,  476,  506,
]
TMS5220_K3_TABLE = [
    -441, -387, -333, -279, -225, -171, -117, -63,
      -9,   45,   98,  152,  206,  260,  314, 368,
]
TMS5220_K4_TABLE = [
    -328, -273, -217, -161, -106,  -50,    5,  61,
     116,  172,  228,  283,  339,  394,  450, 506,
]
TMS5220_K5_TABLE = [
    -328, -282, -235, -189, -142,  -96,  -50,  -3,
      43,   90,  136,  182,  229,  275,  322, 368,
]
TMS5220_K6_TABLE = [
    -256, -212, -168, -123,  -79,  -35,   10,  54,
      98,  143,  187,  232,  276,  320,  365, 409,
]
TMS5220_K7_TABLE = [
    -308, -260, -212, -164, -117,  -69,  -21,  27,
      75,  122,  170,  218,  266,  314,  361, 409,
]
TMS5220_K8_TABLE = [-256, -161, -66, 29, 124, 219, 314, 409]
TMS5220_K9_TABLE = [-256, -176, -96, -15, 65, 146, 226, 307]
TMS5220_K10_TABLE = [-205, -132, -59, 14, 87, 160, 234, 307]

TMS5220_K_TABLES = [
    TMS5220_K1_TABLE, TMS5220_K2_TABLE, TMS5220_K3_TABLE, TMS5220_K4_TABLE,
    TMS5220_K5_TABLE, TMS5220_K6_TABLE, TMS5220_K7_TABLE, TMS5220_K8_TABLE,
    TMS5220_K9_TABLE, TMS5220_K10_TABLE,
]

# Chirp excitation table (TI_LATER_CHIRP) — 52 entries, treated as signed int8
TMS5220_CHIRP_TABLE = [
    0x00, 0x03, 0x0F, 0x28, 0x4C, 0x6C, 0x71, 0x50,
    0x25, 0x26, 0x4C, 0x44, 0x1A, 0x32, 0x3B, 0x13,
    0x37, 0x1A, 0x25, 0x1F, 0x1D, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00,
]

TMS5220_INTERP_COEFF = [0, 3, 3, 3, 2, 2, 1, 1]
TMS5220_KBITS = [5, 5, 4, 4, 4, 4, 4, 3, 3, 3]
TMS5220_SAMPLE_RATE = 8000


# ── TMS5220 Speech Emulator ─────────────────────────────────────────────────

class TMS5220Emulator:
    """TMS5220 LPC speech synthesizer emulation.

    Ported from MAME's tms5220.cpp. Implements Speak External mode:
    raw LPC bitstream data in, signed 16-bit PCM samples out.
    """

    def __init__(self):
        self._reset()

    def _reset(self):
        """Reset all internal state."""
        # Filter state
        self.u = [0] * 11
        self.x = [0] * 10

        # Current interpolated parameters
        self.current_energy = 0
        self.current_pitch = 0
        self.current_k = [0] * 10
        self.previous_energy = 0

        # New frame target indices
        self.new_frame_energy_idx = 0
        self.new_frame_pitch_idx = 0
        self.new_frame_k_idx = [0] * 10

        # Control flags
        self.OLDE = True
        self.OLDP = True
        self.zpar = True
        self.uv_zpar = True
        self.inhibit = False
        self.pitch_zero = False

        # Counters (subc_reload=1 for TMS5220 normal speech rate;
        # produces 200 samples/frame.  subc_reload=0 is SPKSLOW.)
        self.subc_reload = 1
        self.IP = 0
        self.PC = 0
        self.subcycle = self.subc_reload
        self.pitch_count = 0

        # LFSR (13-bit, init 0x1FFF)
        self.RNG = 0x1FFF

        self.excitation_data = 0

        # Talk state
        self.SPEN = False
        self.TALK = False
        self.TALKD = False

        # Bitstream state
        self.data = b''
        self.byte_pos = 0
        self.bit_pos = 0

    def _read_bits(self, count):
        """Read N bits from data buffer (LSB-first per byte, MSB-first into result)."""
        val = 0
        for _ in range(count):
            if self.byte_pos < len(self.data):
                bit = (self.data[self.byte_pos] >> self.bit_pos) & 1
            else:
                bit = 0
            val = (val << 1) | bit
            self.bit_pos += 1
            if self.bit_pos >= 8:
                self.byte_pos += 1
                self.bit_pos = 0
        return val

    def _parse_frame(self):
        """Parse one LPC frame from the bitstream."""
        self.uv_zpar = 0
        self.zpar = 0

        self.new_frame_energy_idx = self._read_bits(4)
        if self.new_frame_energy_idx == 0 or self.new_frame_energy_idx == 15:
            return

        rep_flag = self._read_bits(1)
        self.new_frame_pitch_idx = self._read_bits(6)
        self.uv_zpar = int(self.new_frame_pitch_idx == 0)

        if rep_flag:
            return

        for i in range(4):
            self.new_frame_k_idx[i] = self._read_bits(TMS5220_KBITS[i])

        if self.new_frame_pitch_idx == 0:
            return

        for i in range(4, 10):
            self.new_frame_k_idx[i] = self._read_bits(TMS5220_KBITS[i])

    @staticmethod
    def _matrix_multiply(a, b):
        """10-bit x 14-bit fixed-point multiply with >>9 shift."""
        a = ((a + 512) % 1024) - 512
        b = ((b + 16384) % 32768) - 16384
        return (a * b) >> 9

    def _lattice_filter(self):
        """10-stage lattice filter (direct port from MAME lines 1308-1373)."""
        mm = self._matrix_multiply
        self.u[10] = mm(self.previous_energy, self.excitation_data << 6)
        self.u[9] = self.u[10] - mm(self.current_k[9], self.x[9])
        self.u[8] = self.u[9] - mm(self.current_k[8], self.x[8])
        self.u[7] = self.u[8] - mm(self.current_k[7], self.x[7])
        self.u[6] = self.u[7] - mm(self.current_k[6], self.x[6])
        self.u[5] = self.u[6] - mm(self.current_k[5], self.x[5])
        self.u[4] = self.u[5] - mm(self.current_k[4], self.x[4])
        self.u[3] = self.u[4] - mm(self.current_k[3], self.x[3])
        self.u[2] = self.u[3] - mm(self.current_k[2], self.x[2])
        self.u[1] = self.u[2] - mm(self.current_k[1], self.x[1])
        self.u[0] = self.u[1] - mm(self.current_k[0], self.x[0])
        # Backward path (x updates in reverse)
        self.x[9] = self.x[8] + mm(self.current_k[8], self.u[8])
        self.x[8] = self.x[7] + mm(self.current_k[7], self.u[7])
        self.x[7] = self.x[6] + mm(self.current_k[6], self.u[6])
        self.x[6] = self.x[5] + mm(self.current_k[5], self.u[5])
        self.x[5] = self.x[4] + mm(self.current_k[4], self.u[4])
        self.x[4] = self.x[3] + mm(self.current_k[3], self.u[3])
        self.x[3] = self.x[2] + mm(self.current_k[2], self.u[2])
        self.x[2] = self.x[1] + mm(self.current_k[1], self.u[1])
        self.x[1] = self.x[0] + mm(self.current_k[0], self.u[0])
        self.x[0] = self.u[0]
        self.previous_energy = self.current_energy
        return self.u[0]

    @staticmethod
    def _clip_analog(sample):
        """Clamp to 12-bit range and upshift to 16-bit (MAME lines 1243-1274)."""
        sample = ((sample + 16384) % 32768) - 16384
        if sample > 2047:
            sample = 2047
        elif sample < -2048:
            sample = -2048
        sample &= ~0xF
        u16 = sample & 0xFFFF
        result = ((u16 << 4) & 0xFFFF) | ((u16 & 0x7F0) >> 3) | ((u16 & 0x400) >> 10)
        if result >= 32768:
            result -= 65536
        return result

    def synthesize(self, data_bytes):
        """Feed raw LPC bitstream bytes, return list of int16 PCM samples."""
        self._reset()
        self.data = data_bytes
        if not data_bytes:
            return []

        # Speak External: set up for immediate speech
        self.SPEN = True
        self.TALK = True
        self.TALKD = True
        self.zpar = 1
        self.uv_zpar = 1
        self.OLDE = True
        self.OLDP = True

        # Initialize frame indices (matches MAME speak external init)
        for i in range(4):
            self.new_frame_k_idx[i] = 0
        for i in range(4, 7):
            self.new_frame_k_idx[i] = 0xF
        for i in range(7, 10):
            self.new_frame_k_idx[i] = 0x7

        samples = []
        max_samples = len(data_bytes) * 8 * 50  # generous upper bound

        while len(samples) < max_samples:
            if self.TALKD:
                # ── New frame? (IP=0, PC=12, subcycle=1) ─────────────
                if self.IP == 0 and self.PC == 12 and self.subcycle == 1:
                    self.IP = 0  # reload_table[0]
                    self._parse_frame()

                    if self.new_frame_energy_idx == 0xF:
                        self.TALK = False
                        self.SPEN = False

                    old_uv = self.OLDP
                    old_si = self.OLDE
                    new_uv = (self.new_frame_pitch_idx == 0)
                    new_si = (self.new_frame_energy_idx == 0)

                    if ((not old_uv and new_uv) or
                            (old_uv and not new_uv) or
                            (old_si and not new_si) or
                            (old_uv and new_si)):
                        self.inhibit = True
                    else:
                        self.inhibit = False

                else:
                    # ── Interpolation at subcycle 2 (B cycle) ────────
                    inhibit_state = int(self.inhibit and (self.IP != 0))

                    if self.subcycle == 2:
                        shift = TMS5220_INTERP_COEFF[self.IP]
                        if self.PC == 0:
                            if self.IP == 0:
                                self.pitch_zero = False
                            tgt = TMS5220_ENERGY_TABLE[self.new_frame_energy_idx]
                            self.current_energy = (
                                self.current_energy +
                                (((tgt - self.current_energy) *
                                  (1 - inhibit_state)) >> shift)
                            ) * (1 - self.zpar)
                        elif self.PC == 1:
                            tgt = TMS5220_PITCH_TABLE[self.new_frame_pitch_idx]
                            self.current_pitch = (
                                self.current_pitch +
                                (((tgt - self.current_pitch) *
                                  (1 - inhibit_state)) >> shift)
                            ) * (1 - self.zpar)
                        elif 2 <= self.PC <= 11:
                            ki = self.PC - 2
                            tgt = TMS5220_K_TABLES[ki][self.new_frame_k_idx[ki]]
                            zp = self.zpar if ki < 4 else self.uv_zpar
                            self.current_k[ki] = (
                                self.current_k[ki] +
                                (((tgt - self.current_k[ki]) *
                                  (1 - inhibit_state)) >> shift)
                            ) * (1 - int(zp))

                # ── Excitation ───────────────────────────────────────
                if self.OLDP:  # old frame unvoiced
                    self.excitation_data = -64 if (self.RNG & 1) else 64
                else:  # voiced
                    idx = min(self.pitch_count, 51)
                    v = TMS5220_CHIRP_TABLE[idx]
                    self.excitation_data = v - 256 if v > 127 else v

                # ── LFSR (20 ticks per sample) ───────────────────────
                for _ in range(20):
                    bitout = (((self.RNG >> 12) ^ (self.RNG >> 3) ^
                               (self.RNG >> 2) ^ self.RNG) & 1)
                    self.RNG = ((self.RNG << 1) | bitout) & 0x1FFF

                # ── Lattice filter + clip ────────────────────────────
                raw = self._lattice_filter()
                samples.append(self._clip_analog(raw))

                # ── Update counters ──────────────────────────────────
                self.subcycle += 1
                if self.subcycle == 2 and self.PC == 12:
                    if self.IP == 7 and self.inhibit:
                        self.pitch_zero = True
                    if self.IP == 7:
                        self.OLDE = (self.new_frame_energy_idx == 0)
                        self.OLDP = (self.new_frame_pitch_idx == 0)
                        self.TALKD = self.TALK
                        if not self.TALK and self.SPEN:
                            self.TALK = True
                    self.subcycle = self.subc_reload
                    self.PC = 0
                    self.IP = (self.IP + 1) & 0x7
                elif self.subcycle == 3:
                    self.subcycle = self.subc_reload
                    self.PC += 1

                self.pitch_count += 1
                if self.pitch_count >= self.current_pitch or self.pitch_zero:
                    self.pitch_count = 0
                self.pitch_count &= 0x1FF

            else:
                # Not talking — run counters, wait for TALKD
                self.subcycle += 1
                if self.subcycle == 2 and self.PC == 12:
                    if self.IP == 7:
                        self.TALKD = self.TALK
                        if not self.TALK and self.SPEN:
                            self.TALK = True
                    self.subcycle = self.subc_reload
                    self.PC = 0
                    self.IP = (self.IP + 1) & 0x7
                elif self.subcycle == 3:
                    self.subcycle = self.subc_reload
                    self.PC += 1

                if not self.TALK and not self.SPEN and not self.TALKD:
                    break

        return samples


class TimedEvent:
    """A note or rest with absolute timing for score display."""
    __slots__ = ('time', 'duration', 'pitch', 'dur_abbrev', 'is_rest',
                 'midi_note', 'sustain')

    def __init__(self, time, duration, pitch, dur_abbrev, is_rest,
                 midi_note=None, sustain=False):
        self.time = time          # start time in seconds
        self.duration = duration  # duration in seconds
        self.pitch = pitch        # "A4", "C#3", or None for rests
        self.dur_abbrev = dur_abbrev  # "Q", "8th", "H.", etc.
        self.is_rest = is_rest
        self.midi_note = midi_note  # MIDI note number (0-127) or None
        self.sustain = sustain      # True if sustain bit (0x80) set


# ── Opcode Definitions (0x80-0xBA) ───────────────────────────────────────────
#
# Every opcode consumes at least 1 argument byte (the 6502 dispatch always
# reads byte1 into A, and the main loop always advances the sequence pointer
# by 2). Multi-arg opcodes call seq_advance_read for additional bytes.
#
# Format: opcode -> (name, total_arg_bytes, description, arg_format)
#   arg_format:  "b"  = 1 byte
#                "w"  = 16-bit LE pointer (2 bytes treated as address)
#                "bb" = 2 independent bytes
#                "bw" = 1 byte + 16-bit LE pointer

# ── Musical Note Names ──────────────────────────────────────────────────────
#
# The frequency table at $5A35 is a chromatic scale (128 entries × 16-bit LE).
# Note 0 = rest, notes 1-127 are chromatic.  Mapping: MIDI note = note_value - 1.
# This makes note $46 (70) = MIDI 69 = A4 (440 Hz).

NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


def note_name(note_value):
    """Convert a ROM note value (1-127) to a musical note name like 'A4'."""
    if note_value == 0:
        return None  # rest
    midi = note_value - 1
    name = NOTE_NAMES[midi % 12]
    octave = (midi // 12) - 1
    return f"{name}{octave}"


OPCODES = {
    0x80: ("SET_TEMPO",       1, "Set tempo (A>>2)",               "b"),
    0x81: ("ADD_TEMPO",       1, "Add to tempo",                   "b"),
    0x82: ("SET_VOLUME",      1, "Set base volume",                "b"),
    0x83: ("SET_VOLUME_CHK",  1, "Set volume (w/ $FE check)",      "b"),
    0x84: ("ADD_TRANSPOSE",   1, "Add to transpose offset",        "b"),
    0x85: ("NOP_FE_CHECK",    1, "No-op ($FE check)",              "b"),
    0x86: ("SET_FREQ_ENV",    2, "Set freq envelope ptr",          "w"),
    0x87: ("SET_VOL_ENV",     2, "Set vol envelope ptr",           "w"),
    0x88: ("RESET_TIMER",     1, "Reset timers/counters",          "b"),
    0x89: ("SET_REPEAT",      1, "Set repeat counter",             "b"),
    0x8A: ("SET_DISTORTION",  1, "Set distortion mask",            "b"),
    0x8B: ("SET_CTRL_BITS",   1, "Set control bits",               "b"),
    0x8C: ("CLR_CTRL_BITS",   1, "Clear control bits",             "b"),
    0x8D: ("PUSH_SEQ",        2, "Push & load segment ptr",        "w"),
    0x8E: ("PUSH_SEQ_EXT",    1, "Push extended chain state",      "b"),
    0x8F: ("POP_SEQ",         1, "Pop sequence from chain",        "b"),
    0x90: ("SWITCH_POKEY",    1, "Switch to POKEY mode",           "b"),
    0x91: ("SWITCH_YM2151",   1, "Switch to YM2151 mode",          "b"),
    0x92: ("NOP_92",          1, "No-op (consumed)",               "b"),
    0x93: ("NOP_93",          1, "No-op (consumed)",               "b"),
    0x94: ("NOP_94",          1, "No-op (consumed)",               "b"),
    0x95: ("NOP_95",          1, "No-op (consumed)",               "b"),
    0x96: ("QUEUE_OUTPUT",    1, "Queue byte to main CPU",         "b"),
    0x97: ("RESET_ENVELOPE",  1, "Reset envelope to defaults",     "b"),
    0x98: ("NOP_98",          1, "No-op (consumed)",               "b"),
    0x99: ("SET_SEQ_PTR",     2, "Set sequence pointer (jump)",    "w"),
    0x9A: ("PLAY_MUSIC_CMD",  1, "Trigger music command",          "b"),
    0x9B: ("SET_VAR_NAMED",   1, "Set named variable",             "b"),
    0x9C: ("FORCE_POKEY",     1, "Force POKEY mode",               "b"),
    0x9D: ("SET_VOICE",       2, "Load YM2151 voice definition",   "w"),
    0x9E: ("YM_LOAD_ENV",     2, "Load YM envelope table",         "bb"),
    0x9F: ("YM_LOAD_REG",     2, "Load YM register block",         "bb"),
    0xA0: ("FREQ_OFFSET",     1, "Add signed frequency offset",    "b"),
    0xA1: ("YM_DETUNE_NEG",   1, "Negate + apply YM detune",       "b"),
    0xA2: ("REG_OR",          1, "OR register",                    "b"),
    0xA3: ("REG_XOR",         1, "XOR register",                   "b"),
    0xA4: ("VAR_LOAD",        2, "Load pair to seq variables",     "bb"),
    0xA5: ("NOP_A5",          1, "No-op (consumed)",               "b"),
    0xA6: ("SHIFT_LEFT",      1, "Shift register left N",          "b"),
    0xA7: ("FREQ_ADD",        1, "Add signed value to frequency",  "b"),
    0xA8: ("SET_RELEASE",     1, "Set release rate",               "b"),
    0xA9: ("VAR_ADD",         1, "Add to sequence variable",       "b"),
    0xAA: ("VAR_SUB",         1, "Subtract from variable",         "b"),
    0xAB: ("VAR_AND",         1, "AND mask variable",              "b"),
    0xAC: ("VAR_OR",          1, "OR mask variable",               "b"),
    0xAD: ("VAR_XOR",         1, "XOR mask variable",              "b"),
    0xAE: ("COND_JUMP",       2, "Conditional jump (if var=0)",    "w"),
    0xAF: ("COND_JUMP_INC",   2, "Cond jump + inc var",            "w"),
    0xB0: ("VAR_TO_REG",      1, "Store var to selected register", "b"),
    0xB1: ("VAR_APPLY",       1, "Apply var to subsystem",         "b"),
    0xB2: ("VAR_CLASSIFY",    1, "Classify var + jump to shared",  "b"),
    0xB3: ("SHIFT_VAR_RIGHT", 1, "Shift variable right by N",     "b"),
    0xB4: ("SHIFT_VAR_LEFT",  1, "Shift variable left by N",      "b"),
    0xB5: ("COND_JUMP_EQ",    3, "Jump if var == 0",               "bw"),
    0xB6: ("COND_JUMP_NE",    3, "Jump if var != 0",               "bw"),
    0xB7: ("COND_JUMP_PL",    3, "Jump if var >= 0",               "bw"),
    0xB8: ("COND_JUMP_MI",    3, "Jump if var < 0",                "bw"),
    0xB9: ("VAR_CLASSIFY_SUB",1, "Classify var + subtract",        "b"),
    0xBA: ("VAR_SUB_STORE",   1, "Subtract from var + store",      "b"),
}


# ── ROM Access Layer ──────────────────────────────────────────────────────────

class GauntletROM:
    """Provides CPU-address-based access to the 48KB Gauntlet sound ROM."""

    def __init__(self, filepath):
        with open(filepath, 'rb') as f:
            self.data = f.read()
        if len(self.data) != ROM_SIZE:
            print(f"Warning: ROM is {len(self.data)} bytes, expected {ROM_SIZE}",
                  file=sys.stderr)

    def _offset(self, addr):
        """Convert CPU address to file offset."""
        if addr < ROM_BASE or addr > ROM_END:
            raise ValueError(f"Address ${addr:04X} outside ROM range "
                             f"(${ROM_BASE:04X}-${ROM_END:04X})")
        off = addr - ROM_BASE
        if off >= len(self.data):
            raise ValueError(f"Address ${addr:04X} beyond end of ROM data")
        return off

    def read_byte(self, addr):
        """Read single byte at CPU address."""
        return self.data[self._offset(addr)]

    def read_word(self, addr):
        """Read 16-bit little-endian word at CPU address."""
        off = self._offset(addr)
        if off + 1 >= len(self.data):
            raise ValueError(f"Word read at ${addr:04X} extends beyond ROM")
        return self.data[off] | (self.data[off + 1] << 8)

    def read_bytes(self, addr, n):
        """Read N bytes starting at CPU address."""
        off = self._offset(addr)
        end = min(off + n, len(self.data))
        return bytes(self.data[off:end])


# ── Sound Name Loader ─────────────────────────────────────────────────────────

def load_sound_names(csv_path):
    """Parse soundcmds.csv → {cmd_number: (subsystem, description)}."""
    names = {}
    if not csv_path:
        return names
    try:
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            next(reader, None)  # skip header
            for row in reader:
                if len(row) < 3:
                    continue
                sid = row[0].strip().strip('"').strip()
                if not sid:
                    continue
                try:
                    cmd = int(sid, 0)
                except ValueError:
                    continue
                subsystem = row[1].strip()
                desc = row[2].strip().strip('"').strip()
                if 0 <= cmd <= 0xDA:
                    names[cmd] = (subsystem, desc)
    except FileNotFoundError:
        pass
    return names


# ── Command Resolution ────────────────────────────────────────────────────────

class ChannelInfo:
    """Per-channel data for a multi-channel SFX command."""
    __slots__ = ('offset', 'priority', 'channel', 'seq_ptr')

    def __init__(self, offset, priority, channel, seq_ptr):
        self.offset = offset
        self.priority = priority
        self.channel = channel
        self.seq_ptr = seq_ptr


class CommandInfo:
    __slots__ = ('cmd', 'handler_type', 'param', 'type_name',
                 'seq_ptr', 'seq_len', 'priority', 'channel', 'offset',
                 'has_sequence', 'is_speech', 'channels')

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))


def resolve_command(rom, cmd):
    """Resolve command number → handler info and sequence pointer."""
    if cmd < 0 or cmd > 0xDA:
        return None

    handler_type = rom.read_byte(DISPATCH_TYPE_TABLE + cmd)
    param = rom.read_byte(DISPATCH_PARAM_TABLE + cmd)
    type_name = HANDLER_TYPES.get(handler_type, f"Unknown({handler_type})")

    info = CommandInfo(
        cmd=cmd, handler_type=handler_type, param=param,
        type_name=type_name, seq_ptr=None, seq_len=None,
        priority=None, channel=None, offset=None,
        has_sequence=False, is_speech=False, channels=None,
    )

    if handler_type == 7:
        # POKEY SFX path — follow the next-offset chain at $62FC
        # to collect ALL channels for multi-channel commands.
        offset = rom.read_byte(SFX_OFFSET_TABLE + param)
        channels = []
        cur = offset
        seen = set()
        while cur != 0 and cur not in seen and len(channels) < 30:
            seen.add(cur)
            ch = ChannelInfo(
                offset=cur,
                priority=rom.read_byte(SFX_PRIORITY_TABLE + cur),
                channel=rom.read_byte(SFX_CHANNEL_TABLE + cur),
                seq_ptr=rom.read_word(SFX_SEQ_PTR_TABLE + cur * 2),
            )
            channels.append(ch)
            cur = rom.read_byte(SFX_NEXT_TABLE + cur)

        info.channels = channels
        # Primary channel info (backwards compat for single-channel display)
        info.offset = offset
        info.priority = channels[0].priority if channels else None
        info.channel = channels[0].channel if channels else None
        info.seq_ptr = channels[0].seq_ptr if channels else None
        info.has_sequence = True

    elif handler_type == 11:
        # Music/Speech path — in this ROM, ALL type 11 commands are
        # speech or speech-related (LPC data, not sequence bytecode).
        # Music commands route through type 7 instead.
        index = rom.read_byte(MUSIC_INDEX_TABLE + param)
        info.offset = index
        info.seq_ptr = rom.read_word(MUSIC_SEQ_PTR_TABLE + index * 2)
        info.seq_len = rom.read_word(MUSIC_SEQ_LEN_TABLE + index * 2)
        info.has_sequence = True
        info.is_speech = True

    return info


# ── Sequence Disassembler ─────────────────────────────────────────────────────

class Instruction:
    __slots__ = ('addr', 'raw', 'mnemonic', 'operands', 'comment',
                 'is_marker')

    def __init__(self, addr, raw, mnemonic, operands='', comment='',
                 is_marker=False):
        self.addr = addr
        self.raw = raw
        self.mnemonic = mnemonic
        self.operands = operands
        self.comment = comment
        self.is_marker = is_marker


def _marker(addr, text):
    """Create a segment-boundary marker pseudo-instruction."""
    return Instruction(addr, [], text, is_marker=True)


def _format_note(addr, byte0, byte1):
    """Format a note/rest instruction from byte0 (freq) and byte1 (dur)."""
    raw = [byte0, byte1]
    dur_idx  = byte1 & 0x0F
    div_ctrl = (byte1 >> 4) & 0x03
    dotted   = bool(byte1 & 0x40)
    sustain  = bool(byte1 & 0x80)

    dur_name = (DURATION_NAMES[dur_idx]
                if dur_idx < len(DURATION_NAMES) else f"?{dur_idx}")

    flags = []
    if dotted:
        flags.append("dotted")
    if sustain:
        flags.append("sustain")
    if div_ctrl:
        flags.append(f"div={div_ctrl}")
    flag_str = " [" + ", ".join(flags) + "]" if flags else ""

    mnemonic = "REST" if byte0 == 0x00 else "NOTE"
    pitch = note_name(byte0)
    if pitch:
        operands = f"{pitch} (${byte0:02X}), {dur_name}"
    else:
        operands = f"${byte0:02X}, {dur_name}"
    return Instruction(addr, raw, mnemonic, operands, flag_str.strip())


def _format_opcode(addr, byte0, args, arg_fmt):
    """Format an opcode instruction with its arguments."""
    name = OPCODES[byte0][0]
    raw = [byte0] + list(args)
    operands = ''
    comment = ''

    if arg_fmt == 'b' and len(args) >= 1:
        operands = f"${args[0]:02X}"

    elif arg_fmt == 'w' and len(args) >= 2:
        word = args[0] | (args[1] << 8)
        operands = f"${word:04X}"
        if byte0 == 0x99:       # SET_SEQ_PTR
            if word <= addr:
                comment = f"LOOP -> ${word:04X}"
            else:
                comment = f"jump -> ${word:04X}"
        elif byte0 == 0x8D:     # PUSH_SEQ
            comment = f"call -> ${word:04X}"
        elif byte0 in (0x86, 0x87, 0x9D):  # pointer args
            comment = f"-> ${word:04X}"
        elif byte0 in (0xAE, 0xAF):  # conditional jumps
            comment = ("back" if word <= addr else "fwd") + f" -> ${word:04X}"

    elif arg_fmt == 'bb' and len(args) >= 2:
        operands = f"${args[0]:02X}, ${args[1]:02X}"

    elif arg_fmt == 'bw' and len(args) >= 3:
        word = args[1] | (args[2] << 8)
        operands = f"${args[0]:02X}, ${word:04X}"
        comment = ("back" if word <= addr else "fwd") + f" -> ${word:04X}"

    return Instruction(addr, raw, name, operands, comment)


def disassemble_sequence(rom, start_addr, max_bytes=MAX_SEQ_BYTES):
    """Disassemble bytecode sequence, following PUSH_SEQ chains.

    PUSH_SEQ (0x8D) pushes the return address and jumps to a sub-segment.
    CHAIN (byte1=0x00) pops the return address and continues there.
    SET_SEQ_PTR (0x99) is an unconditional jump.

    Disassembly stops at END markers, when the return stack is empty on
    CHAIN, or when a segment is encountered a second time.

    Returns a list of Instruction objects (including marker pseudo-
    instructions for segment boundaries).
    """
    instructions = []
    return_stack = []               # pushed return addresses from PUSH_SEQ
    visited_segments = {start_addr} # segment entry points we've decoded
    visited_addrs = set()           # individual addresses (loop guard)
    addr = start_addr
    total = 0
    max_total = 1024                # safety limit on total instructions

    while total < max_total:
        # ── Safety checks ────────────────────────────────────────────
        if addr < ROM_BASE or addr > ROM_END:
            instructions.append(_marker(addr, "--- OUT OF ROM RANGE ---"))
            break

        if addr in visited_addrs:
            instructions.append(_marker(addr,
                f"--- LOOP to ${addr:04X} (already disassembled) ---"))
            break
        visited_addrs.add(addr)

        try:
            byte0 = rom.read_byte(addr)
        except ValueError:
            instructions.append(_marker(addr, "--- READ ERROR ---"))
            break

        total += 1

        # ── End-of-sequence marker (0xBB-0xFF) ──────────────────────
        if byte0 >= 0xBB:
            instructions.append(Instruction(
                addr, [byte0], "END", f"${byte0:02X}"))
            break

        # ── Note / Rest / Chain (0x00-0x7F) ─────────────────────────
        if byte0 <= 0x7F:
            try:
                byte1 = rom.read_byte(addr + 1)
            except ValueError:
                instructions.append(Instruction(
                    addr, [byte0], "NOTE?", f"${byte0:02X}", "truncated"))
                break

            if byte1 == 0x00:
                # CHAIN: pop return stack or end
                if return_stack:
                    ret_addr = return_stack.pop()
                    instructions.append(Instruction(
                        addr, [byte0, byte1], "CHAIN", "",
                        f"return to ${ret_addr:04X}"))
                    instructions.append(_marker(ret_addr,
                        f"--- Returning to ${ret_addr:04X} ---"))
                    addr = ret_addr
                    continue
                else:
                    instructions.append(Instruction(
                        addr, [byte0, byte1], "CHAIN", "",
                        "end of sequence"))
                    break
            else:
                instructions.append(_format_note(addr, byte0, byte1))
                addr += 2
                continue

        # ── Opcode (0x80-0xBA) ──────────────────────────────────────
        if byte0 not in OPCODES:
            instructions.append(Instruction(
                addr, [byte0], f"??? ${byte0:02X}", "", "unknown opcode"))
            addr += 2
            continue

        name, arg_bytes, desc, arg_fmt = OPCODES[byte0]

        # Read argument bytes
        args = []
        for i in range(arg_bytes):
            try:
                args.append(rom.read_byte(addr + 1 + i))
            except ValueError:
                break

        # Emit the instruction
        instructions.append(_format_opcode(addr, byte0, args, arg_fmt))

        # ── PUSH_SEQ: call sub-segment ──────────────────────────────
        if byte0 == 0x8D and len(args) >= 2:
            target = args[0] | (args[1] << 8)
            ret_addr = addr + 3  # instruction after PUSH_SEQ

            if target < ROM_BASE or target > ROM_END:
                instructions.append(_marker(target,
                    f"--- Segment @ ${target:04X} "
                    f"(in RAM, not in ROM) ---"))
                addr = ret_addr
            elif target in visited_segments:
                instructions.append(_marker(target,
                    f"--- Segment @ ${target:04X} "
                    f"(already shown above) ---"))
                addr = ret_addr
            else:
                visited_segments.add(target)
                return_stack.append(ret_addr)
                instructions.append(_marker(target,
                    f"--- Entering segment @ ${target:04X} ---"))
                addr = target
            continue

        # ── SET_SEQ_PTR: unconditional jump ─────────────────────────
        if byte0 == 0x99 and len(args) >= 2:
            target = args[0] | (args[1] << 8)
            if target < ROM_BASE or target > ROM_END:
                instructions.append(_marker(target,
                    f"--- Jump to ${target:04X} "
                    f"(outside ROM) ---"))
                break
            if target in visited_segments:
                instructions.append(_marker(target,
                    f"--- Jump to ${target:04X} "
                    f"(already shown above) ---"))
                break
            visited_segments.add(target)
            addr = target
            continue

        # ── All other opcodes: advance past instruction ─────────────
        addr += 1 + arg_bytes

    return instructions


# ── Music Stats ──────────────────────────────────────────────────────────────

def compute_channel_stats(rom, instructions):
    """Compute note count and estimated play time for one channel.

    Tracks SET_TEMPO / ADD_TEMPO through the instruction stream and sums
    the duration of every NOTE and REST.

    Returns (note_count, total_seconds).
    """
    tempo = 0
    total_frames = 0.0
    note_count = 0

    for inst in instructions:
        if inst.is_marker:
            continue

        opcode = inst.raw[0] if inst.raw else None

        # SET_TEMPO: stored value = arg >> 2
        if inst.mnemonic == "SET_TEMPO" and len(inst.raw) >= 2:
            tempo = inst.raw[1] >> 2

        # ADD_TEMPO: raw 8-bit unsigned addition to tempo
        elif inst.mnemonic == "ADD_TEMPO" and len(inst.raw) >= 2:
            tempo = (tempo + inst.raw[1]) & 0xFF

        elif inst.mnemonic in ("NOTE", "REST") and len(inst.raw) >= 2:
            byte1 = inst.raw[1]
            if byte1 == 0:      # CHAIN marker, not a timed event
                continue
            dur_idx = byte1 & 0x0F
            dotted = bool(byte1 & 0x40)

            # Read base duration from ROM table
            if dur_idx == 0:
                base_value = 0
            else:
                base_value = rom.read_word(DURATION_TABLE_ADDR + dur_idx * 2)

            dur_value = base_value * 1.5 if dotted else float(base_value)

            if tempo > 0 and dur_value > 0:
                total_frames += dur_value / tempo

            if inst.mnemonic == "NOTE":
                note_count += 1

    total_seconds = total_frames / 120.0
    return note_count, total_seconds


# ── Score Mode (Timeline) ────────────────────────────────────────────────────

def build_channel_timeline(rom, instructions):
    """Walk an instruction list and build a list of TimedEvents.

    Tracks SET_TEMPO / ADD_TEMPO identically to compute_channel_stats(),
    then for each NOTE/REST computes absolute start time and duration in
    seconds.

    Returns a list of TimedEvent sorted by time.
    """
    tempo = 0
    cumulative_frames = 0.0
    events = []

    for inst in instructions:
        if inst.is_marker:
            continue

        if inst.mnemonic == "SET_TEMPO" and len(inst.raw) >= 2:
            tempo = inst.raw[1] >> 2
        elif inst.mnemonic == "ADD_TEMPO" and len(inst.raw) >= 2:
            tempo = (tempo + inst.raw[1]) & 0xFF
        elif inst.mnemonic in ("NOTE", "REST") and len(inst.raw) >= 2:
            byte0 = inst.raw[0]
            byte1 = inst.raw[1]
            if byte1 == 0:  # CHAIN marker, not a timed event
                continue

            dur_idx = byte1 & 0x0F
            dotted = bool(byte1 & 0x40)
            sustain = bool(byte1 & 0x80)

            # Duration name and abbreviation
            dur_name = (DURATION_NAMES[dur_idx]
                        if dur_idx < len(DURATION_NAMES) else f"?{dur_idx}")
            abbrev = DURATION_ABBREVS.get(dur_name, dur_name[:4])
            if sustain:
                abbrev += "sus"

            # Compute duration in frames, then seconds
            if dur_idx == 0:
                base_value = 0
            else:
                base_value = rom.read_word(DURATION_TABLE_ADDR + dur_idx * 2)

            dur_value = base_value * 1.5 if dotted else float(base_value)

            if tempo > 0 and dur_value > 0:
                dur_frames = dur_value / tempo
            else:
                dur_frames = 0.0

            time_secs = cumulative_frames / 120.0
            dur_secs = dur_frames / 120.0

            pitch = note_name(byte0)
            is_rest = (byte0 == 0)
            midi_note = byte0 - 1 if byte0 > 0 else None

            events.append(TimedEvent(
                time=time_secs,
                duration=dur_secs,
                pitch=pitch,
                dur_abbrev=abbrev,
                is_rest=is_rest,
                midi_note=midi_note,
                sustain=sustain,
            ))

            cumulative_frames += dur_frames

    return events


def _effective_end_times(timelines):
    """Compute effective end time for each event in each timeline.

    For sustained notes, the audible end extends to the start of the
    next non-rest note in the same channel.  If no subsequent note
    exists, the note rings until the end of the longest channel.
    """
    # Find the overall song end (latest event end across all channels)
    song_end = 0.0
    for tl in timelines:
        for ev in tl:
            end = ev.time + ev.duration
            if end > song_end:
                song_end = end

    result = []   # list of lists, parallel to timelines
    for tl in timelines:
        note_events = [ev for ev in tl if not ev.is_rest
                       and ev.midi_note is not None]
        # Map event id → effective end
        end_map = {}
        for i, ev in enumerate(note_events):
            if ev.sustain:
                if i + 1 < len(note_events):
                    end_map[id(ev)] = note_events[i + 1].time
                else:
                    end_map[id(ev)] = song_end
        result.append(end_map)
    return result


def merge_channel_timelines(timelines):
    """Merge per-channel TimedEvent lists into aligned rows.

    Collects all unique event start times, then for each time point
    determines what each channel is doing:
      ("new", event)     — note/rest starts at this time
      ("sustain", event) — note started earlier, still sounding
      ("silent", None)   — no active event

    Sustained notes (bit 7 set) extend their audible window to the
    next note in the channel, so the score shows "|" instead of ".".

    Returns list of (time, [cell, ...]) rows.
    """
    # Pre-compute effective end times for sustained notes
    end_maps = _effective_end_times(timelines)

    # Collect all unique start times
    all_times = set()
    for tl in timelines:
        for ev in tl:
            all_times.add(round(ev.time, 4))
    all_times = sorted(all_times)

    if not all_times:
        return []

    rows = []
    for t in all_times:
        row_cells = []
        for tl, end_map in zip(timelines, end_maps):
            cell = ("silent", None)
            for ev in tl:
                ev_start = round(ev.time, 4)
                eff_end = end_map.get(id(ev), ev.time + ev.duration)
                ev_end = round(eff_end, 4)
                if ev_start == t:
                    cell = ("new", ev)
                    break
                elif ev_start < t < ev_end:
                    cell = ("sustain", ev)
                    break
            row_cells.append(cell)
        rows.append((t, row_cells))

    return rows


def format_score(rows, num_channels, channel_labels=None):
    """Render merged timeline rows as a fixed-width columnar display.

    Each channel column is 12 chars wide:
      New note:  "A4  Q      " (pitch + dur_abbrev)
      New rest:  "--- 8th    "
      Sustain:   "  |        "
      Silent:    "  .        "
    """
    COL_W = 12

    if channel_labels is None:
        channel_labels = [f"Ch{i+1}" for i in range(num_channels)]

    # Header
    lines = []
    hdr = f"{'Time':>8s} |"
    sep = "---------+"
    for lbl in channel_labels:
        hdr += f" {lbl:<{COL_W}s}|"
        sep += "-" * (COL_W + 1) + "+"
    lines.append(hdr)
    lines.append(sep)

    # Rows
    for t, cells in rows:
        line = f"{t:7.2f}s |"
        for kind, ev in cells:
            if kind == "new":
                if ev.is_rest:
                    cell_str = f"--- {ev.dur_abbrev}"
                else:
                    cell_str = f"{ev.pitch:<4s}{ev.dur_abbrev}"
                cell_str = f" {cell_str:<{COL_W}s}"
            elif kind == "sustain":
                cell_str = f" {'  |':<{COL_W}s}"
            else:  # silent
                cell_str = f" {'  .':<{COL_W}s}"
            line += cell_str + "|"
        lines.append(line)

    return "\n".join(lines)


# ── MIDI Export ──────────────────────────────────────────────────────────────

def _midi_varlen(value):
    """Encode an integer as a MIDI variable-length quantity (1-4 bytes)."""
    if value < 0:
        value = 0
    buf = [value & 0x7F]
    value >>= 7
    while value:
        buf.append((value & 0x7F) | 0x80)
        value >>= 7
    buf.reverse()
    return bytes(buf)


def _midi_track(events):
    """Build one MTrk chunk from a list of (abs_tick, event_bytes) tuples.

    Converts absolute ticks to delta-times, appends End of Track meta event.
    """
    events.sort(key=lambda e: e[0])
    data = bytearray()
    prev_tick = 0
    for tick, evt_bytes in events:
        delta = max(0, tick - prev_tick)
        data += _midi_varlen(delta)
        data += evt_bytes
        prev_tick = tick
    # End of Track meta event
    data += _midi_varlen(0) + b'\xFF\x2F\x00'
    return b'MTrk' + struct.pack('>I', len(data)) + bytes(data)


def write_midi(timelines, filepath, ticks_per_beat=480):
    """Write a Type 1 Standard MIDI File from channel timelines.

    Track 0 = tempo track (120 BPM).
    Tracks 1-N = one per channel with Note On/Off events.

    Sustained notes (sustain bit set in bytecode) extend their Note Off
    to the start of the next non-rest note in the same channel.  If the
    sustained note is the last in its channel, it extends to the end of
    the longest channel (i.e. the end of the piece).
    """
    # Find the end-of-song time (latest event end across all channels)
    song_end = 0.0
    for tl in timelines:
        for ev in tl:
            end = ev.time + ev.duration
            if end > song_end:
                song_end = end

    num_tracks = len(timelines) + 1  # +1 for tempo track

    # MThd header: chunk_len=6, format=1, num_tracks, ticks_per_beat
    header = b'MThd' + struct.pack('>IHHH', 6, 1, num_tracks, ticks_per_beat)

    # Track 0: tempo meta event (120 BPM = 500000 us/beat)
    tempo_us = 500000
    tempo_bytes = tempo_us.to_bytes(3, 'big')
    tempo_event = (0, b'\xFF\x51\x03' + tempo_bytes)
    track0 = _midi_track([tempo_event])

    tracks = [track0]

    for ch_idx, timeline in enumerate(timelines):
        # MIDI channels 0-8, skip 9 (drums), then 10-15
        if ch_idx < 9:
            midi_ch = ch_idx
        elif ch_idx < 15:
            midi_ch = ch_idx + 1  # skip channel 9
        else:
            midi_ch = 15  # clamp to max

        # Collect non-rest note events for sustain extension
        note_events = [ev for ev in timeline if not ev.is_rest
                       and ev.midi_note is not None]

        events = []
        for i, ev in enumerate(note_events):
            note = max(0, min(127, ev.midi_note))
            start_tick = int(ev.time * ticks_per_beat * 2)  # 120 BPM = 2 beats/sec

            if ev.sustain:
                # Extend to start of next note, or end of song
                if i + 1 < len(note_events):
                    end_secs = note_events[i + 1].time
                else:
                    end_secs = song_end
                dur_ticks = max(1, int((end_secs - ev.time) * ticks_per_beat * 2))
            else:
                dur_ticks = max(1, int(ev.duration * ticks_per_beat * 2))

            end_tick = start_tick + dur_ticks

            # Note On (velocity 100)
            events.append((start_tick, bytes([0x90 | midi_ch, note, 100])))
            # Note Off (velocity 0)
            events.append((end_tick, bytes([0x80 | midi_ch, note, 0])))

        tracks.append(_midi_track(events))

    with open(filepath, 'wb') as f:
        f.write(header)
        for trk in tracks:
            f.write(trk)


def midi_command(rom, cmd, names, output_path):
    """Export a sound command as a Standard MIDI File.

    Same channel resolution as score_command, writes Type 1 MIDI.
    """
    info = resolve_command(rom, cmd)
    if info is None:
        print(f"Invalid command number: 0x{cmd:02X}", file=sys.stderr)
        return

    if not info.has_sequence:
        print(f"Command 0x{cmd:02X}: no sequence data for handler "
              f"type {info.handler_type} ({info.type_name})")
        return

    if info.is_speech:
        print(f"Command 0x{cmd:02X}: speech command — MIDI export "
              f"not applicable.")
        print("  Use --cmd for speech data display.")
        return

    # Disassemble all channels
    channels = info.channels or []
    all_instructions = []

    if not channels:
        if info.seq_ptr is not None:
            insts = disassemble_sequence(rom, info.seq_ptr)
            all_instructions.append(insts)
    else:
        for ch in channels:
            try:
                insts = disassemble_sequence(rom, ch.seq_ptr)
                all_instructions.append(insts)
            except ValueError:
                all_instructions.append([])

    if not all_instructions:
        print(f"Command 0x{cmd:02X}: no channels to export.")
        return

    # Build timelines and compute stats
    timelines = []
    total_notes = 0
    max_seconds = 0.0
    for insts in all_instructions:
        tl = build_channel_timeline(rom, insts)
        timelines.append(tl)
        notes, secs = compute_channel_stats(rom, insts)
        total_notes += notes
        if secs > max_seconds:
            max_seconds = secs

    write_midi(timelines, output_path)

    # Summary
    name_info = names.get(cmd)
    label = f'"{name_info[1]}"' if name_info else f"0x{cmd:02X}"
    secs_rounded = round(max_seconds)
    m, s = divmod(secs_rounded, 60)
    print(f"Exported command {label} as MIDI:")
    print(f"  Channels: {len(timelines)} | Notes: {total_notes} | "
          f"Est. play time: {max_seconds:.1f}s ({m}:{s:02d})")
    print(f"  Output: {output_path}")


# ── Speech WAV Export ────────────────────────────────────────────────────────

def speech_to_wav(rom, cmd, names, out_path):
    """Synthesize a speech command to a WAV file."""
    info = resolve_command(rom, cmd)
    if info is None:
        print(f"Invalid command number: 0x{cmd:02X}", file=sys.stderr)
        return

    if not info.is_speech:
        print(f"Command 0x{cmd:02X}: not a speech command "
              f"(type {info.handler_type}: {info.type_name})")
        return

    data = rom.read_bytes(info.seq_ptr, info.seq_len)
    emu = TMS5220Emulator()
    samples = emu.synthesize(data)

    if not samples:
        print(f"Command 0x{cmd:02X}: synthesis produced no samples")
        return

    # Write 16-bit mono WAV
    with wave.open(out_path, 'w') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(TMS5220_SAMPLE_RATE)
        pcm = struct.pack(f'<{len(samples)}h', *samples)
        wf.writeframes(pcm)

    duration = len(samples) / TMS5220_SAMPLE_RATE
    name_info = names.get(cmd)
    label = f'"{name_info[1]}"' if name_info else f"0x{cmd:02X}"
    print(f"Speech command 0x{cmd:02X} {label}:")
    print(f"  LPC data: ${info.seq_ptr:04X} ({info.seq_len} bytes)")
    print(f"  Samples: {len(samples)} ({duration:.2f}s @ {TMS5220_SAMPLE_RATE} Hz)")
    print(f"  Output: {out_path}")


def speech_all_to_wav(rom, names, out_dir):
    """Synthesize all speech commands to WAV files in a directory."""
    os.makedirs(out_dir, exist_ok=True)

    count = 0
    for cmd in range(MAX_COMMANDS):
        info = resolve_command(rom, cmd)
        if info is None or not info.is_speech:
            continue

        name_info = names.get(cmd)
        if name_info:
            # Sanitize description for filename
            safe = name_info[1].replace(' ', '_').replace('"', '').replace("'", '')
            safe = ''.join(c for c in safe if c.isalnum() or c in '_-')
            safe = safe.strip('_-')
            fname = f"0x{cmd:02X}_{safe}.wav"
        else:
            fname = f"0x{cmd:02X}.wav"

        out_path = os.path.join(out_dir, fname)
        data = rom.read_bytes(info.seq_ptr, info.seq_len)
        emu = TMS5220Emulator()
        samples = emu.synthesize(data)

        if not samples:
            print(f"  0x{cmd:02X}: no samples (skipped)")
            continue

        with wave.open(out_path, 'w') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(TMS5220_SAMPLE_RATE)
            pcm = struct.pack(f'<{len(samples)}h', *samples)
            wf.writeframes(pcm)

        duration = len(samples) / TMS5220_SAMPLE_RATE
        label = f'"{name_info[1]}"' if name_info else ""
        print(f"  0x{cmd:02X}: {info.seq_len:4d} bytes -> "
              f"{len(samples):6d} samples ({duration:.2f}s)  {label}  -> {fname}")
        count += 1

    print(f"\nExported {count} speech commands to {out_dir}/")


def score_command(rom, cmd, names):
    """Top-level function for --score mode.

    Resolves command, disassembles all channels, builds timelines,
    merges them, and prints the score view.
    """
    info = resolve_command(rom, cmd)
    if info is None:
        return f"Invalid command number: 0x{cmd:02X}"

    lines = [format_command_header(info, names)]

    if not info.has_sequence:
        lines.append("  (no sequence data for this handler type)")
        return "\n".join(lines)

    if info.is_speech:
        lines.append("  Score view not applicable for speech commands.")
        lines.append("  Use --cmd for speech data display.")
        return "\n".join(lines)

    # Disassemble all channels
    channels = info.channels or []
    all_instructions = []   # list of instruction lists, one per channel
    channel_labels = []
    errors = []

    if not channels:
        if info.seq_ptr is not None:
            try:
                insts = disassemble_sequence(rom, info.seq_ptr)
                all_instructions.append(insts)
                channel_labels.append("Ch1")
            except ValueError as e:
                errors.append(str(e))
    else:
        for i, ch in enumerate(channels):
            try:
                insts = disassemble_sequence(rom, ch.seq_ptr)
                all_instructions.append(insts)
                # Label: YM for channels 0x00-0x07, PK for POKEY channels
                if ch.channel <= 0x07:
                    hw = "YM"
                else:
                    hw = "PK"
                channel_labels.append(f"Ch{i+1} ({hw})")
            except ValueError as e:
                all_instructions.append([])
                channel_labels.append(f"Ch{i+1} (ERR)")
                errors.append(f"Ch{i+1}: {e}")

    if not all_instructions:
        lines.append("  No channels to display.")
        if errors:
            for e in errors:
                lines.append(f"  Error: {e}")
        return "\n".join(lines)

    # Compute stats
    total_notes = 0
    max_seconds = 0.0
    for insts in all_instructions:
        notes, secs = compute_channel_stats(rom, insts)
        total_notes += notes
        if secs > max_seconds:
            max_seconds = secs

    if total_notes > 0:
        secs_rounded = round(max_seconds)
        m, s = divmod(secs_rounded, 60)
        lines.append(f"Notes: {total_notes} | "
                     f"Est. play time: {max_seconds:.1f}s ({m}:{s:02d}) | "
                     f"Channels: {len(all_instructions)}")

    # Build timelines
    timelines = []
    for insts in all_instructions:
        tl = build_channel_timeline(rom, insts)
        timelines.append(tl)

    # Merge and format
    rows = merge_channel_timelines(timelines)
    if rows:
        lines.append("")
        lines.append(format_score(rows, len(timelines), channel_labels))
    else:
        lines.append("  (no timed events found)")

    # For single-channel, also show the regular disassembly
    if len(all_instructions) == 1:
        lines.append("")
        lines.append("(Single channel — full disassembly below)")
        lines.append(format_instructions(all_instructions[0]))

    return "\n".join(lines)


# ── Output Formatting ─────────────────────────────────────────────────────────

def format_command_header(info, names):
    """Format the command header block."""
    lines = []

    name_info = names.get(info.cmd)
    if name_info:
        subsys, desc = name_info
        lines.append(f'=== Command 0x{info.cmd:02X}: "{desc}" ({subsys}) ===')
    else:
        lines.append(f'=== Command 0x{info.cmd:02X} ===')

    parts = [f"Handler: Type {info.handler_type} ({info.type_name})"]
    parts.append(f"Param: 0x{info.param:02X}")

    if info.priority is not None:
        parts.append(f"Priority: {info.priority}")
    if info.channel is not None:
        parts.append(f"Channel: 0x{info.channel:02X}")
    if info.offset is not None:
        parts.append(f"Offset: 0x{info.offset:02X}")
    if info.seq_len is not None:
        parts.append(f"SeqLen: {info.seq_len}")
    if info.channels and len(info.channels) > 1:
        parts.append(f"Channels: {len(info.channels)}")

    lines.append(" | ".join(parts))
    return "\n".join(lines)


def format_instructions(instructions):
    """Format disassembled instructions as text lines."""
    lines = []
    for inst in instructions:
        if inst.is_marker:
            # Segment boundary / annotation line
            lines.append(f"\n  {inst.mnemonic}")
            continue

        hex_bytes = " ".join(f"{b:02X}" for b in inst.raw)
        hex_col = f"{hex_bytes:<14s}"

        if inst.operands:
            asm = f"{inst.mnemonic} {inst.operands}"
        else:
            asm = inst.mnemonic

        if inst.comment:
            asm += f"  ; {inst.comment}"

        lines.append(f"  ${inst.addr:04X}:  {hex_col} {asm}")
    return "\n".join(lines)


def format_hex_dump(rom, addr, length, cols=16):
    """Format a hex dump for raw data (e.g. speech)."""
    lines = []
    for off in range(0, length, cols):
        chunk_addr = addr + off
        remaining = min(cols, length - off)
        try:
            data = rom.read_bytes(chunk_addr, remaining)
        except ValueError:
            break
        hex_part = " ".join(f"{b:02X}" for b in data)
        ascii_part = "".join(chr(b) if 0x20 <= b < 0x7F else '.' for b in data)
        lines.append(f"  ${chunk_addr:04X}:  {hex_part:<{cols*3}s} {ascii_part}")
    return "\n".join(lines)


def disassemble_command(rom, cmd, names):
    """Full disassembly of a single command."""
    info = resolve_command(rom, cmd)
    if info is None:
        return f"Invalid command number: 0x{cmd:02X}"

    lines = [format_command_header(info, names)]

    if not info.has_sequence:
        lines.append("  (no sequence data for this handler type)")
        return "\n".join(lines)

    if info.is_speech:
        display_len = min(info.seq_len or 64, 128)
        lines.append(f"\nSpeech/LPC data @ ${info.seq_ptr:04X} "
                     f"({info.seq_len} bytes):")
        lines.append(format_hex_dump(rom, info.seq_ptr, display_len))
        if info.seq_len and info.seq_len > display_len:
            lines.append(f"  ... ({info.seq_len - display_len} more bytes)")
        return "\n".join(lines)

    # Disassemble all channels first (to compute stats before output)
    channels = info.channels or []
    all_channel_results = []  # [(instructions, channel_info, error), ...]

    if not channels:
        if info.seq_ptr is not None:
            try:
                instructions = disassemble_sequence(rom, info.seq_ptr)
                all_channel_results.append((instructions, None, None))
            except ValueError as e:
                all_channel_results.append((None, None, e))
    else:
        for ch in channels:
            try:
                instructions = disassemble_sequence(rom, ch.seq_ptr)
                all_channel_results.append((instructions, ch, None))
            except ValueError as e:
                all_channel_results.append((None, ch, e))

    # Compute music stats
    total_notes = 0
    max_seconds = 0.0
    for insts, _, err in all_channel_results:
        if insts is None:
            continue
        notes, secs = compute_channel_stats(rom, insts)
        total_notes += notes
        if secs > max_seconds:
            max_seconds = secs

    # Show stats in header area
    if total_notes > 0:
        secs_rounded = round(max_seconds)
        m, s = divmod(secs_rounded, 60)
        lines.append(f"Notes: {total_notes} | "
                     f"Est. play time: {max_seconds:.1f}s ({m}:{s:02d})")

    # Now emit the disassembly
    if not channels:
        if info.seq_ptr is not None:
            insts, _, err = all_channel_results[0]
            lines.append(f"\nSequence @ ${info.seq_ptr:04X}:")
            if insts:
                lines.append(format_instructions(insts))
            else:
                lines.append(f"  Error: {err}")
        else:
            lines.append("  (no sequence pointer)")
    elif len(channels) == 1:
        insts, ch, err = all_channel_results[0]
        lines.append(f"\nSequence @ ${ch.seq_ptr:04X}:")
        if insts:
            lines.append(format_instructions(insts))
        else:
            lines.append(f"  Error: {err}")
    else:
        for i, (insts, ch, err) in enumerate(all_channel_results):
            lines.append(
                f"\n--- Channel {i+1}/{len(channels)}: "
                f"hw=0x{ch.channel:02X}, priority={ch.priority}, "
                f"offset=0x{ch.offset:02X} ---")
            lines.append(f"Sequence @ ${ch.seq_ptr:04X}:")
            if insts:
                lines.append(format_instructions(insts))
            else:
                lines.append(f"  Error: {err}")

    return "\n".join(lines)


def list_commands(rom, names):
    """List all 219 commands with summary info."""
    lines = []
    hdr = (f"{'Cmd':>5s}  {'Type':>4s}  {'Handler':<24s}  "
           f"{'Param':>5s}  {'SeqPtr':>7s}  {'Ch':>3s}  {'Sub':>6s}  Description")
    lines.append(hdr)
    lines.append("-" * 105)

    for cmd in range(MAX_COMMANDS):
        info = resolve_command(rom, cmd)
        if info is None:
            continue

        name_info = names.get(cmd)
        desc = name_info[1] if name_info else ""
        subsys = name_info[0] if name_info else ""

        ptr_str = f"${info.seq_ptr:04X}" if info.seq_ptr is not None else "   -  "
        type_str = f"Type {info.handler_type:2d} ({info.type_name})"
        n_ch = len(info.channels) if info.channels else 0
        ch_str = f"{n_ch:3d}" if n_ch > 1 else "  1" if n_ch == 1 else "  -"

        lines.append(
            f"0x{cmd:02X}   {info.handler_type:4d}  {type_str:<24s}  "
            f"0x{info.param:02X}  {ptr_str:>7s}  {ch_str}  {subsys:>6s}  {desc}")

    return "\n".join(lines)


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_int(s):
    """Parse integer from hex (0x...) or decimal string."""
    s = s.strip()
    try:
        return int(s, 0)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid number: {s}")


def find_csv(rom_path):
    """Auto-detect soundcmds.csv near the ROM file."""
    rom_dir = os.path.dirname(os.path.abspath(rom_path))
    cwd = os.getcwd()
    candidates = [
        os.path.join(rom_dir, "soundcmds.csv"),
        os.path.join(cwd, "soundcmds.csv"),
        os.path.join(rom_dir, "docs", "soundcmds.csv"),
        os.path.join(cwd, "docs", "soundcmds.csv"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Gauntlet Sound ROM Sequence Disassembler",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  %(prog)s soundrom.bin --cmd 0x0D        # Disassemble "Food Eaten"
  %(prog)s soundrom.bin --cmd 13          # Same command (decimal)
  %(prog)s soundrom.bin --addr 0x7983     # Raw address disassembly
  %(prog)s soundrom.bin --list            # All 219 commands summary
  %(prog)s soundrom.bin --all             # Disassemble everything
  %(prog)s soundrom.bin --range 0x09-0x0C # Range of commands
  %(prog)s soundrom.bin --score 0x3B     # Score/tracker view
  %(prog)s soundrom.bin --midi 0x3B      # Export as MIDI file
  %(prog)s soundrom.bin --midi 0x3B --midi-out theme.mid
  %(prog)s soundrom.bin --speech-wav 0x5A # Synthesize speech to WAV
  %(prog)s soundrom.bin --speech-all      # Export all speech as WAVs
""")

    parser.add_argument("rom", help="Path to soundrom.bin (48KB)")
    parser.add_argument("--cmd", type=parse_int, metavar="N",
                        help="Disassemble command N (hex or decimal)")
    parser.add_argument("--addr", type=parse_int, metavar="ADDR",
                        help="Disassemble raw sequence at address")
    parser.add_argument("--list", action="store_true",
                        help="List all 219 commands with summary")
    parser.add_argument("--all", action="store_true",
                        help="Disassemble all commands with sequence data")
    parser.add_argument("--range", metavar="START-END",
                        help="Disassemble range of commands (e.g., 0x09-0x0C)")
    parser.add_argument("--score", type=parse_int, metavar="N",
                        help="Score/tracker view of command N (all channels)")
    parser.add_argument("--midi", type=parse_int, metavar="N",
                        help="Export command N as Standard MIDI File")
    parser.add_argument("--midi-out", metavar="FILE",
                        help="Output path for MIDI file "
                             "(default: command_0xNN.mid)")
    parser.add_argument("--speech-wav", type=parse_int, metavar="N",
                        help="Synthesize speech command N to WAV file")
    parser.add_argument("--speech-all", action="store_true",
                        help="Synthesize all speech commands to WAV files")
    parser.add_argument("--out", metavar="FILE",
                        help="Output path for WAV file (default: auto-generated)")
    parser.add_argument("--out-dir", metavar="DIR",
                        help="Output directory for --speech-all (default: speech/)")
    parser.add_argument("--csv", metavar="FILE",
                        help="Path to soundcmds.csv (auto-detected if omitted)")

    args = parser.parse_args()

    # Load ROM
    if not os.path.exists(args.rom):
        print(f"Error: ROM file not found: {args.rom}", file=sys.stderr)
        sys.exit(1)
    rom = GauntletROM(args.rom)

    # Load sound names
    csv_path = args.csv if args.csv else find_csv(args.rom)
    names = load_sound_names(csv_path)

    # ── Execute action ────────────────────────────────────────────────────

    if args.speech_wav is not None:
        out = args.out or f"speech_0x{args.speech_wav:02X}.wav"
        speech_to_wav(rom, args.speech_wav, names, out)

    elif args.speech_all:
        out_dir = args.out_dir or "speech"
        speech_all_to_wav(rom, names, out_dir)

    elif args.midi is not None:
        midi_out = args.midi_out or f"command_0x{args.midi:02X}.mid"
        midi_command(rom, args.midi, names, midi_out)

    elif args.score is not None:
        print(score_command(rom, args.score, names))

    elif args.list:
        print(list_commands(rom, names))

    elif args.cmd is not None:
        print(disassemble_command(rom, args.cmd, names))

    elif args.addr is not None:
        print(f"Sequence @ ${args.addr:04X}:\n")
        try:
            instructions = disassemble_sequence(rom, args.addr)
            print(format_instructions(instructions))
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    elif args.all:
        first = True
        for cmd in range(MAX_COMMANDS):
            info = resolve_command(rom, cmd)
            if info and info.has_sequence:
                if not first:
                    print("\n" + "=" * 70 + "\n")
                print(disassemble_command(rom, cmd, names))
                first = False

    elif args.range:
        parts = args.range.split("-", 1)
        if len(parts) != 2:
            print("Error: --range format is START-END (e.g., 0x09-0x0C)",
                  file=sys.stderr)
            sys.exit(1)
        try:
            start = int(parts[0].strip(), 0)
            end = int(parts[1].strip(), 0)
        except ValueError:
            print("Error: invalid range values", file=sys.stderr)
            sys.exit(1)

        first = True
        for cmd in range(start, min(end + 1, MAX_COMMANDS)):
            if not first:
                print("\n" + "=" * 70 + "\n")
            print(disassemble_command(rom, cmd, names))
            first = False

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
