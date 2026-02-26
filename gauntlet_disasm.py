#!/usr/bin/env python3
"""Gauntlet Sound ROM Sequence Disassembler

Decodes the bytecode sequences in the Gauntlet sound ROM (48KB, 6502-based
sound coprocessor). Resolves any of the 219 sound commands to their
underlying sequence data and produces human-readable disassembly.

Includes TMS5220 LPC speech synthesis (ported from MAME's tms5220.cpp),
POKEY chip emulation (ported from MAME's pokey.cpp), and YM2151 FM synthesis
for decoding and exporting speech, sound effects, and music as WAV files.

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
    python gauntlet_disasm.py soundrom.bin --sfx-wav 0x0D
    python gauntlet_disasm.py soundrom.bin --sfx-all
    python gauntlet_disasm.py soundrom.bin --music-wav 0x3B
    python gauntlet_disasm.py soundrom.bin --music-all
    python gauntlet_disasm.py soundrom.bin --render-wav 0x0D
    python gauntlet_disasm.py soundrom.bin --render-all
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


# ── POKEY Chip Emulator ──────────────────────────────────────────────────────
#
# Ported from MAME's pokey.cpp (v4.9). Generates audio by clocking 4 channels
# at 1.789790 MHz with polynomial counter-based distortion, then downsampling.

class POKEYEmulator:
    """POKEY audio chip emulator (4 channels, polynomial distortion)."""

    FREQ_17_EXACT = 1789790  # 1.79 MHz NTSC clock

    # AUDCx bit masks
    NOTPOLY5    = 0x80
    POLY4       = 0x40
    PURE        = 0x20
    VOLUME_ONLY = 0x10
    VOLUME_MASK = 0x0F

    # AUDCTL bit masks
    POLY9       = 0x80
    CH1_HICLK   = 0x40
    CH3_HICLK   = 0x20
    CH12_JOINED = 0x10
    CH34_JOINED = 0x08
    CH1_FILTER  = 0x04
    CH2_FILTER  = 0x02
    CLK_15KHZ   = 0x01

    DIV_64  = 28   # prescaler for 63.9 kHz
    DIV_15  = 114  # prescaler for 15.7 kHz
    CLK_1   = 0
    CLK_28  = 1
    CLK_114 = 2

    # POKEY_DEFAULT_GAIN = 32767/11/4 ~ 744
    DEFAULT_GAIN = 32767 // 11 // 4

    def __init__(self):
        self.poly4 = self._init_poly4_5(4)
        self.poly5 = self._init_poly4_5(5)
        self.poly9 = self._init_poly9_17(9)
        self.poly17 = None  # lazy init (512KB)
        self.reset()

    def reset(self):
        """Zero all channel state and counters."""
        # Per-channel state: [AUDF, AUDC, counter, borrow_cnt, output, filter_sample]
        self.ch_AUDF = [0, 0, 0, 0]
        self.ch_AUDC = [0xB0, 0xB0, 0xB0, 0xB0]
        self.ch_counter = [0, 0, 0, 0]
        self.ch_borrow_cnt = [0, 0, 0, 0]
        self.ch_output = [0, 0, 0, 0]
        self.ch_filter_sample = [1, 1, 0, 0]

        self.AUDCTL = 0
        self.SKCTL = 0x03  # not in reset state

        self.p4 = 0
        self.p5 = 0
        self.p9 = 0
        self.p17 = 0
        self.clock_cnt = [0, 0, 0]

        self.out_raw = 0
        self.old_raw_inval = True

    @staticmethod
    def _init_poly4_5(size):
        """Generate poly4 (15 entries) or poly5 (31 entries) table."""
        mask = (1 << size) - 1
        poly = []
        lfsr = 0
        xorbit = size - 1
        for _ in range(mask):
            lfsr = ((lfsr << 1) | (~((lfsr >> 2) ^ (lfsr >> xorbit)) & 1)) & mask
            poly.append(lfsr)
        return poly

    @staticmethod
    def _init_poly9_17(size):
        """Generate poly9 (511 entries) or poly17 (131071 entries) table."""
        mask = (1 << size) - 1
        poly = []
        lfsr = mask
        if size == 17:
            for _ in range(mask):
                in8 = ((lfsr >> 8) ^ (lfsr >> 13)) & 1
                in_bit = lfsr & 1
                lfsr = lfsr >> 1
                lfsr = (lfsr & 0xFF7F) | (in8 << 7)
                lfsr = (in_bit << 16) | lfsr
                poly.append(lfsr)
        else:  # size == 9
            for _ in range(mask):
                in_bit = ((lfsr >> 0) ^ (lfsr >> 5)) & 1
                lfsr = (lfsr >> 1) | (in_bit << 8)
                poly.append(lfsr)
        return poly

    def _ensure_poly17(self):
        """Lazy-init poly17 table (131071 entries)."""
        if self.poly17 is None:
            self.poly17 = self._init_poly9_17(17)

    def write(self, addr, data):
        """Write to POKEY register (address 0x00-0x0F)."""
        reg = addr & 0x0F
        if reg == 0x00:    # AUDF1
            self.ch_AUDF[0] = data
        elif reg == 0x01:  # AUDC1
            self.ch_AUDC[0] = data
            self.old_raw_inval = True
        elif reg == 0x02:  # AUDF2
            self.ch_AUDF[1] = data
        elif reg == 0x03:  # AUDC2
            self.ch_AUDC[1] = data
            self.old_raw_inval = True
        elif reg == 0x04:  # AUDF3
            self.ch_AUDF[2] = data
        elif reg == 0x05:  # AUDC3
            self.ch_AUDC[2] = data
            self.old_raw_inval = True
        elif reg == 0x06:  # AUDF4
            self.ch_AUDF[3] = data
        elif reg == 0x07:  # AUDC4
            self.ch_AUDC[3] = data
            self.old_raw_inval = True
        elif reg == 0x08:  # AUDCTL
            if data != self.AUDCTL:
                self.AUDCTL = data
                self.old_raw_inval = True
        elif reg == 0x09:  # STIMER - reset all counters
            for i in range(4):
                self.ch_counter[i] = self.ch_AUDF[i] ^ 0xFF
                self.ch_borrow_cnt[i] = 0
                self.ch_output[i] = 0
                self.ch_filter_sample[i] = 1 if i < 2 else 0
            self.old_raw_inval = True
        elif reg == 0x0F:  # SKCTL
            self.SKCTL = data

    def _reset_channel(self, ch):
        """Reset a channel's counter from its AUDF value."""
        self.ch_counter[ch] = self.ch_AUDF[ch] ^ 0xFF
        self.ch_borrow_cnt[ch] = 0

    def _inc_chan(self, ch, borrow_cycles):
        """Increment channel counter; start borrow countdown on overflow."""
        self.ch_counter[ch] = (self.ch_counter[ch] + 1) & 0xFF
        if self.ch_counter[ch] == 0 and self.ch_borrow_cnt[ch] == 0:
            self.ch_borrow_cnt[ch] = borrow_cycles

    def _check_borrow(self, ch):
        """Check if borrow countdown completed this clock."""
        if self.ch_borrow_cnt[ch] > 0:
            self.ch_borrow_cnt[ch] -= 1
            return self.ch_borrow_cnt[ch] == 0
        return False

    def _process_channel(self, ch):
        """Generate output bit based on distortion mode."""
        audc = self.ch_AUDC[ch]
        if (audc & self.NOTPOLY5) or (self.poly5[self.p5] & 1):
            if audc & self.PURE:
                self.ch_output[ch] ^= 1
            elif audc & self.POLY4:
                self.ch_output[ch] = self.poly4[self.p4] & 1
            elif self.AUDCTL & self.POLY9:
                self.ch_output[ch] = self.poly9[self.p9] & 1
            else:
                self._ensure_poly17()
                self.ch_output[ch] = self.poly17[self.p17] & 1
            self.old_raw_inval = True

    def _step_one_clock(self):
        """Advance the chip by one 1.79 MHz clock cycle."""
        if not (self.SKCTL & 0x03):
            return  # in reset state

        # Advance polynomial counters
        self.p4 = (self.p4 + 1) % 15
        self.p5 = (self.p5 + 1) % 31
        self.p9 = (self.p9 + 1) % 511
        self.p17 = (self.p17 + 1) % 131071

        # Prescaler clocks
        clock_triggered = [1, 0, 0]  # CLK_1 always fires
        self.clock_cnt[self.CLK_28] += 1
        if self.clock_cnt[self.CLK_28] >= self.DIV_64:
            self.clock_cnt[self.CLK_28] = 0
            clock_triggered[self.CLK_28] = 1
        self.clock_cnt[self.CLK_114] += 1
        if self.clock_cnt[self.CLK_114] >= self.DIV_15:
            self.clock_cnt[self.CLK_114] = 0
            clock_triggered[self.CLK_114] = 1

        base_clock = self.CLK_114 if (self.AUDCTL & self.CLK_15KHZ) else self.CLK_28

        # Channel 1 clocking
        if (self.AUDCTL & self.CH1_HICLK) and clock_triggered[self.CLK_1]:
            if self.AUDCTL & self.CH12_JOINED:
                self._inc_chan(0, 7)
            else:
                self._inc_chan(0, 4)
        if not (self.AUDCTL & self.CH1_HICLK) and clock_triggered[base_clock]:
            self._inc_chan(0, 1)

        # Channel 3 clocking
        if (self.AUDCTL & self.CH3_HICLK) and clock_triggered[self.CLK_1]:
            if self.AUDCTL & self.CH34_JOINED:
                self._inc_chan(2, 7)
            else:
                self._inc_chan(2, 4)
        if not (self.AUDCTL & self.CH3_HICLK) and clock_triggered[base_clock]:
            self._inc_chan(2, 1)

        # Channels 2 and 4 at base clock (when not joined)
        if clock_triggered[base_clock]:
            if not (self.AUDCTL & self.CH12_JOINED):
                self._inc_chan(1, 1)
            if not (self.AUDCTL & self.CH34_JOINED):
                self._inc_chan(3, 1)

        # Check borrows - Channel 3
        if self._check_borrow(2):
            if self.AUDCTL & self.CH34_JOINED:
                if self.ch_counter[3] == 0xFF:
                    pass  # serial handling omitted
                self._inc_chan(3, 1)
            else:
                self._reset_channel(2)
            self._process_channel(2)
            if self.AUDCTL & self.CH1_FILTER:
                self.ch_filter_sample[0] = self.ch_output[0]
            else:
                self.ch_filter_sample[0] = 1
            self.old_raw_inval = True

        # Check borrows - Channel 4
        if self._check_borrow(3):
            if self.AUDCTL & self.CH34_JOINED:
                self._reset_channel(2)
            self._reset_channel(3)
            self._process_channel(3)
            if self.AUDCTL & self.CH2_FILTER:
                self.ch_filter_sample[1] = self.ch_output[1]
            else:
                self.ch_filter_sample[1] = 1
            self.old_raw_inval = True

        # Check borrows - Channel 1
        if self._check_borrow(0):
            if self.AUDCTL & self.CH12_JOINED:
                self._inc_chan(1, 1)
            else:
                self._reset_channel(0)
            self._process_channel(0)

        # Check borrows - Channel 2
        if self._check_borrow(1):
            if self.AUDCTL & self.CH12_JOINED:
                self._reset_channel(0)
            self._reset_channel(1)
            self._process_channel(1)

        # Update raw output
        if self.old_raw_inval:
            raw = 0
            for ch in range(4):
                audible = ((self.ch_output[ch] ^ self.ch_filter_sample[ch]) or
                           (self.ch_AUDC[ch] & self.VOLUME_ONLY))
                if audible:
                    raw |= (self.ch_AUDC[ch] & self.VOLUME_MASK) << (ch * 4)
            self.out_raw = raw
            self.old_raw_inval = False

    def _get_sample(self):
        """Get current output as a signed 16-bit sample."""
        total = 0
        for ch in range(4):
            total += (self.out_raw >> (ch * 4)) & 0x0F
        out = total * self.DEFAULT_GAIN
        return max(-32768, min(32767, out))

    def render(self, num_samples, sample_rate=44100):
        """Generate num_samples PCM samples at given sample rate.

        Internally runs at 1.789790 MHz and downsamples by averaging.
        Returns list of int16 values.
        """
        self._ensure_poly17()
        samples = []
        clocks_per_sample = self.FREQ_17_EXACT / sample_rate
        clock_accum = 0.0

        for _ in range(num_samples):
            clock_accum += clocks_per_sample
            clocks_this = int(clock_accum)
            clock_accum -= clocks_this

            # Accumulate for averaging
            total = 0
            for _ in range(clocks_this):
                self._step_one_clock()
                total += self._get_sample()

            if clocks_this > 0:
                samples.append(max(-32768, min(32767, total // clocks_this)))
            else:
                samples.append(self._get_sample())

        return samples


# ── YM2151 FM Synthesis Emulator ─────────────────────────────────────────────
#
# 8-channel, 4-operator FM synthesizer. Implements all 8 connection algorithms,
# ADSR envelopes, LFO, detune, and key scaling from YM2151 documentation.

class YM2151Emulator:
    """YM2151 OPM FM synthesis emulator."""

    CLOCK = 3579545       # master clock
    RATE = CLOCK // 64    # ~55930 Hz native sample rate

    # Sine table (1024 entries, linear amplitude)
    _sin_table = None
    # Envelope rate tables
    _eg_rate_table = None
    _eg_shift_table = None
    # DT1 detune table
    _dt1_table = None

    @classmethod
    def _init_tables(cls):
        """One-time init of shared lookup tables."""
        if cls._sin_table is not None:
            return
        import math
        # Linear sine table (0..1.0 range, 1024 entries)
        cls._sin_table = [math.sin(2.0 * math.pi * i / 1024.0)
                          for i in range(1024)]
        # Envelope rate table: maps (rate, counter_step) to increment
        # Simplified from OPM documentation
        cls._eg_rate_table = []
        for r in range(64):
            if r < 2:
                cls._eg_rate_table.append(0)
            elif r < 60:
                cls._eg_rate_table.append(r)
            else:
                cls._eg_rate_table.append(63)
        # EG shift table for timing
        cls._eg_shift_table = []
        for r in range(64):
            if r < 2:
                cls._eg_shift_table.append(11)
            elif r >= 60:
                cls._eg_shift_table.append(0)
            else:
                cls._eg_shift_table.append(max(0, 11 - (r >> 2)))
        # DT1 detune table (4 levels x 32 key codes)
        cls._dt1_table = [[0]*32 for _ in range(4)]
        dt1_values = [
            [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
            [0,0,0,0,1,1,1,1,1,1,1,1,2,2,2,2,2,3,3,3,4,4,4,5,5,6,6,7,8,8,8,8],
            [1,1,1,1,2,2,2,2,2,3,3,3,4,4,4,5,5,6,6,7,8,8,9,10,11,12,13,14,16,16,16,16],
            [2,2,2,2,2,3,3,3,4,4,4,5,5,6,6,7,8,8,9,10,11,12,13,14,16,17,19,20,22,22,22,22],
        ]
        for d in range(4):
            for k in range(32):
                cls._dt1_table[d][k] = dt1_values[d][k]

    # Note frequency table: KC (key code) to phase increment
    # KC = (octave << 4) | note, note 0-15 (but only 0,1,2,4,5,6,8,9,10,12,13,14 valid)
    # Base frequencies for octave 0, notes C# through C (YM2151 note order)
    _NOTE_FREQ = [
        16.35, 17.32, 18.35, 18.35,  # C#, D, D#, (D# dup)
        19.45, 20.60, 21.83, 21.83,  # E, F, F#, (F# dup)
        23.12, 24.50, 25.96, 25.96,  # G, G#, A, (A dup)
        27.50, 29.14, 30.87, 30.87,  # A#, B, C, (C dup)
    ]

    def __init__(self):
        self._init_tables()
        self.reset()

    def reset(self):
        """Initialize all state."""
        # Per-operator state (32 ops = 8 channels * 4 ops)
        self.op_tl = [0] * 32      # Total Level (0-127)
        self.op_ar = [0] * 32      # Attack Rate
        self.op_d1r = [0] * 32     # Decay 1 Rate
        self.op_d2r = [0] * 32     # Decay 2 Rate
        self.op_rr = [0] * 32      # Release Rate
        self.op_d1l = [0] * 32     # Decay 1 Level
        self.op_ks = [0] * 32      # Key Scale
        self.op_mul = [0] * 32     # Multiply
        self.op_dt1 = [0] * 32     # Detune 1
        self.op_dt2 = [0] * 32     # Detune 2
        self.op_ams_en = [0] * 32  # AMS enable

        # Envelope state
        self.op_eg_phase = [3] * 32     # 0=atk,1=dec1,2=dec2,3=rel
        self.op_eg_level = [1023] * 32  # 10-bit (0=max vol, 1023=silent)
        self.op_eg_counter = [0] * 32

        # Phase accumulators
        self.op_phase = [0] * 32

        # Per-channel state
        self.ch_kc = [0] * 8       # Key Code (octave + note)
        self.ch_kf = [0] * 8       # Key Fraction
        self.ch_fb = [0] * 8       # Feedback level (0-7)
        self.ch_con = [0] * 8      # Connection algorithm (0-7)
        self.ch_lr = [3] * 8       # L/R enable (bits: D7=R, D6=L -> stored as 0-3)
        self.ch_pms = [0] * 8      # PMS
        self.ch_ams = [0] * 8      # AMS

        # Feedback memory (2 previous outputs per channel)
        self.ch_fb_out = [[0, 0] for _ in range(8)]

        # Key-on state per operator
        self.op_key_on = [False] * 32

        # LFO state
        self.lfo_freq = 0
        self.lfo_wave = 0  # 0=saw, 1=square, 2=tri, 3=noise
        self.lfo_amd = 0
        self.lfo_pmd = 0
        self.lfo_phase = 0
        self.lfo_counter = 0

        # Noise
        self.noise_enable = False
        self.noise_freq = 0
        self.noise_lfsr = 1
        self.noise_counter = 0

        # EG global counter
        self.eg_timer = 0
        self.eg_cnt = 0

    def write(self, addr, data):
        """Write to YM2151 register."""
        addr &= 0xFF
        data &= 0xFF

        if addr == 0x01:  # Test register
            return
        elif addr == 0x08:  # Key on/off
            ch = data & 0x07
            for s in range(4):
                op_idx = ch + s * 8
                was_on = self.op_key_on[op_idx]
                now_on = bool(data & (1 << (s + 3)))
                if now_on and not was_on:
                    # Key ON - start attack
                    self.op_eg_phase[op_idx] = 0
                    self.op_eg_level[op_idx] = 1023
                    self.op_eg_counter[op_idx] = 0
                    self.op_phase[op_idx] = 0
                elif not now_on and was_on:
                    # Key OFF - start release
                    self.op_eg_phase[op_idx] = 3
                self.op_key_on[op_idx] = now_on
        elif addr == 0x0F:  # Noise
            self.noise_enable = bool(data & 0x80)
            self.noise_freq = data & 0x1F
        elif addr == 0x18:  # LFO frequency
            self.lfo_freq = data
        elif addr == 0x19:  # PMD/AMD
            if data & 0x80:
                self.lfo_pmd = data & 0x7F
            else:
                self.lfo_amd = data & 0x7F
        elif addr == 0x1B:  # LFO waveform
            self.lfo_wave = data & 0x03
        elif 0x20 <= addr <= 0x27:  # RL / FB / CON
            ch = addr & 0x07
            self.ch_con[ch] = data & 0x07
            self.ch_fb[ch] = (data >> 3) & 0x07
            self.ch_lr[ch] = (data >> 6) & 0x03
        elif 0x28 <= addr <= 0x2F:  # KC (key code)
            ch = addr & 0x07
            self.ch_kc[ch] = data & 0x7F
        elif 0x30 <= addr <= 0x37:  # KF (key fraction)
            ch = addr & 0x07
            self.ch_kf[ch] = (data >> 2) & 0x3F
        elif 0x38 <= addr <= 0x3F:  # PMS / AMS
            ch = addr & 0x07
            self.ch_ams[ch] = data & 0x03
            self.ch_pms[ch] = (data >> 4) & 0x07
        elif 0x40 <= addr <= 0x5F:  # DT1 / MUL
            op_idx = self._slot_map(addr)
            self.op_dt1[op_idx] = (data >> 4) & 0x07
            self.op_mul[op_idx] = data & 0x0F
        elif 0x60 <= addr <= 0x7F:  # TL
            op_idx = self._slot_map(addr)
            self.op_tl[op_idx] = data & 0x7F
        elif 0x80 <= addr <= 0x9F:  # KS / AR
            op_idx = self._slot_map(addr)
            self.op_ar[op_idx] = data & 0x1F
            self.op_ks[op_idx] = (data >> 6) & 0x03
        elif 0xA0 <= addr <= 0xBF:  # AMS-EN / D1R
            op_idx = self._slot_map(addr)
            self.op_d1r[op_idx] = data & 0x1F
            self.op_ams_en[op_idx] = (data >> 7) & 1
        elif 0xC0 <= addr <= 0xDF:  # DT2 / D2R
            op_idx = self._slot_map(addr)
            self.op_d2r[op_idx] = data & 0x1F
            self.op_dt2[op_idx] = (data >> 6) & 0x03
        elif 0xE0 <= addr <= 0xFF:  # D1L / RR
            op_idx = self._slot_map(addr)
            self.op_rr[op_idx] = data & 0x0F
            self.op_d1l[op_idx] = (data >> 4) & 0x0F

    def _slot_map(self, addr):
        """Map register address to operator index.

        YM2151 slot order: 0x40-0x47 = OP1 (M1), 0x48-0x4F = OP3 (C1),
        0x50-0x57 = OP2 (M2), 0x58-0x5F = OP4 (C2).
        We store as: ops 0-7 = M1, 8-15 = M2, 16-23 = C1, 24-31 = C2.
        """
        ch = addr & 0x07
        slot_group = ((addr >> 3) & 0x03)
        # slot_group: 0=M1(OP1), 1=C1(OP3), 2=M2(OP2), 3=C2(OP4)
        # remap to: 0=M1, 1=M2, 2=C1, 3=C2
        remap = [0, 2, 1, 3]
        return ch + remap[slot_group] * 8

    def _calc_phase_inc(self, ch, op_idx):
        """Calculate phase increment for an operator."""
        import math
        kc = self.ch_kc[ch]
        kf = self.ch_kf[ch]
        octave = (kc >> 4) & 0x07
        note = kc & 0x0F

        # Base frequency from note table
        if note < 16:
            base_freq = self._NOTE_FREQ[note]
        else:
            base_freq = self._NOTE_FREQ[0]

        freq = base_freq * (1 << octave)

        # Key fraction (6 bits = 64 steps per semitone)
        freq *= 2.0 ** (kf / (64.0 * 12.0))

        # Multiply
        mul = self.op_mul[op_idx]
        if mul == 0:
            freq *= 0.5
        else:
            freq *= mul

        # DT1 detune
        dt1 = self.op_dt1[op_idx]
        dt1_sign = 1 if dt1 < 4 else -1
        dt1_idx = dt1 & 3
        kc_idx = min(31, kc >> 1)
        if dt1_idx > 0:
            freq += dt1_sign * self._dt1_table[dt1_idx][kc_idx] * freq / 1024.0

        # DT2 coarse detune
        dt2 = self.op_dt2[op_idx]
        dt2_cents = [0, 600, 781, 950][dt2]  # in cents
        if dt2_cents:
            freq *= 2.0 ** (dt2_cents / 1200.0)

        # Phase increment: freq / native_rate * 1024 (table size)
        return freq / self.RATE * 1024.0

    def _advance_eg(self, op_idx):
        """Advance envelope generator for one operator.

        Uses an exponential attack curve and linear decay/release.
        The EG counter is divided by a rate-dependent period to control speed.
        """
        phase = self.op_eg_phase[op_idx]
        level = self.op_eg_level[op_idx]
        counter = self.op_eg_counter[op_idx]

        if phase == 0:  # Attack (exponential: fast at high level, slow near 0)
            rate = self.op_ar[op_idx]
            if rate == 0:
                return
            eff_rate = min(63, rate * 2 + (self.ch_kc[op_idx % 8] >> (3 - self.op_ks[op_idx])) if self.op_ks[op_idx] else rate * 2)
            eff_rate = min(63, eff_rate)
            # Period between EG steps: lower eff_rate = longer period
            if eff_rate >= 62:
                # Instant attack
                level = 0
                self.op_eg_phase[op_idx] = 1
            else:
                period = max(1, 1 << max(0, 8 - (eff_rate >> 2)))
                counter += 1
                if counter >= period:
                    counter = 0
                    # Exponential attack: step proportional to remaining level
                    step = max(1, level >> max(0, 3 - (eff_rate & 3)))
                    level -= step
                    if level <= 0:
                        level = 0
                        self.op_eg_phase[op_idx] = 1
        elif phase == 1:  # Decay 1 (linear toward D1L)
            rate = self.op_d1r[op_idx]
            if rate == 0:
                self.op_eg_level[op_idx] = level
                self.op_eg_counter[op_idx] = counter
                return
            eff_rate = min(63, rate * 2 + (self.op_ks[op_idx] >> 1))
            period = max(1, 1 << max(0, 8 - (eff_rate >> 2)))
            counter += 1
            if counter >= period:
                counter = 0
                step = 1 + (eff_rate & 3)
                level += step
                d1l = self.op_d1l[op_idx]
                target = d1l << 5 if d1l < 15 else 1023
                if level >= target:
                    level = target
                    self.op_eg_phase[op_idx] = 2
        elif phase == 2:  # Decay 2 / Sustain (linear toward silence)
            rate = self.op_d2r[op_idx]
            if rate == 0:
                self.op_eg_level[op_idx] = level
                self.op_eg_counter[op_idx] = counter
                return
            eff_rate = min(63, rate * 2 + (self.op_ks[op_idx] >> 1))
            period = max(1, 1 << max(0, 8 - (eff_rate >> 2)))
            counter += 1
            if counter >= period:
                counter = 0
                level = min(1023, level + 1 + (eff_rate & 3))
        elif phase == 3:  # Release (linear, faster)
            rate = self.op_rr[op_idx]
            eff_rate = min(63, rate * 4 + 2 + (self.op_ks[op_idx] >> 1))
            period = max(1, 1 << max(0, 6 - (eff_rate >> 2)))
            counter += 1
            if counter >= period:
                counter = 0
                level = min(1023, level + 2 + (eff_rate & 3))

        self.op_eg_level[op_idx] = level
        self.op_eg_counter[op_idx] = counter

    def _calc_op(self, op_idx, phase_inc, modulation):
        """Calculate one operator output sample."""
        # Advance phase
        self.op_phase[op_idx] = (self.op_phase[op_idx] + phase_inc) % 1024.0

        # Phase with modulation
        phase = (self.op_phase[op_idx] + modulation) % 1024.0
        idx = int(phase) & 1023

        # Sine lookup
        out = self._sin_table[idx]

        # Apply envelope (TL + EG level)
        # TL is 0-127 (0=max), EG is 0-1023 (0=max)
        tl = self.op_tl[op_idx]
        eg = self.op_eg_level[op_idx]
        # Convert to attenuation: each TL unit = 0.75dB, each EG unit ~0.09375dB
        atten_db = tl * 0.75 + eg * (48.0 / 1024.0)
        if atten_db > 96:
            return 0.0
        import math
        atten = math.pow(10.0, -atten_db / 20.0)
        return out * atten

    def _calc_channel(self, ch):
        """Calculate one channel output using the connection algorithm."""
        con = self.ch_con[ch]
        fb = self.ch_fb[ch]

        # Operator indices: M1, M2, C1, C2
        m1 = ch + 0 * 8
        m2 = ch + 1 * 8
        c1 = ch + 2 * 8
        c2 = ch + 3 * 8

        # Phase increments
        m1_inc = self._calc_phase_inc(ch, m1)
        m2_inc = self._calc_phase_inc(ch, m2)
        c1_inc = self._calc_phase_inc(ch, c1)
        c2_inc = self._calc_phase_inc(ch, c2)

        # Feedback for M1
        if fb > 0:
            fb_mod = (self.ch_fb_out[ch][0] + self.ch_fb_out[ch][1]) / 2.0
            fb_mod *= (1 << (fb - 1)) / 4.0  # scale feedback
        else:
            fb_mod = 0.0

        m1_out = self._calc_op(m1, m1_inc, fb_mod)
        self.ch_fb_out[ch][1] = self.ch_fb_out[ch][0]
        self.ch_fb_out[ch][0] = m1_out * 512.0  # scale for feedback

        # Connection algorithms (from YM2151 documentation)
        # Phase modulation is scaled by 512
        if con == 0:
            # M1->C1->M2->C2
            c1_out = self._calc_op(c1, c1_inc, m1_out * 512)
            m2_out = self._calc_op(m2, m2_inc, c1_out * 512)
            c2_out = self._calc_op(c2, c2_inc, m2_out * 512)
            out = c2_out
        elif con == 1:
            # (M1+C1)->M2->C2
            c1_out = self._calc_op(c1, c1_inc, 0)
            m2_out = self._calc_op(m2, m2_inc, (m1_out + c1_out) * 256)
            c2_out = self._calc_op(c2, c2_inc, m2_out * 512)
            out = c2_out
        elif con == 2:
            # (M1+(C1->M2))->C2
            c1_out = self._calc_op(c1, c1_inc, 0)
            m2_out = self._calc_op(m2, m2_inc, c1_out * 512)
            c2_out = self._calc_op(c2, c2_inc, (m1_out + m2_out) * 256)
            out = c2_out
        elif con == 3:
            # ((M1->C1)+M2)->C2
            c1_out = self._calc_op(c1, c1_inc, m1_out * 512)
            m2_out = self._calc_op(m2, m2_inc, 0)
            c2_out = self._calc_op(c2, c2_inc, (c1_out + m2_out) * 256)
            out = c2_out
        elif con == 4:
            # (M1->C1)+(M2->C2)
            c1_out = self._calc_op(c1, c1_inc, m1_out * 512)
            m2_out = self._calc_op(m2, m2_inc, 0)
            c2_out = self._calc_op(c2, c2_inc, m2_out * 512)
            out = c1_out + c2_out
        elif con == 5:
            # M1->(C1+M2+C2)
            c1_out = self._calc_op(c1, c1_inc, m1_out * 512)
            m2_out = self._calc_op(m2, m2_inc, m1_out * 512)
            c2_out = self._calc_op(c2, c2_inc, m1_out * 512)
            out = c1_out + m2_out + c2_out
        elif con == 6:
            # M1->C1, M2, C2 (1 modulator + 3 carriers)
            c1_out = self._calc_op(c1, c1_inc, m1_out * 512)
            m2_out = self._calc_op(m2, m2_inc, 0)
            c2_out = self._calc_op(c2, c2_inc, 0)
            out = c1_out + m2_out + c2_out
        else:  # con == 7
            # M1+C1+M2+C2 (4 carriers, no modulation)
            c1_out = self._calc_op(c1, c1_inc, 0)
            m2_out = self._calc_op(m2, m2_inc, 0)
            c2_out = self._calc_op(c2, c2_inc, 0)
            out = m1_out + c1_out + m2_out + c2_out

        return out

    def render(self, num_samples, sample_rate=44100):
        """Generate num_samples of stereo PCM at given rate.

        Returns list of (left, right) int16 tuples.
        """
        import math
        output = []
        ratio = self.RATE / sample_rate
        native_pos = 0.0
        native_left = 0.0
        native_right = 0.0
        native_count = 0

        total_native = int(num_samples * ratio) + 2
        for _ in range(total_native):
            # Advance envelopes
            self.eg_cnt += 1
            for op in range(32):
                self._advance_eg(op)

            # Advance LFO
            self.lfo_counter += 1

            # Mix all 8 channels
            left = 0.0
            right = 0.0
            for ch in range(8):
                sample = self._calc_channel(ch)
                lr = self.ch_lr[ch]
                if lr & 2:  # left
                    left += sample
                if lr & 1:  # right
                    right += sample

            # Accumulate for resampling
            native_left += left
            native_right += right
            native_count += 1
            native_pos += 1.0

            if native_pos >= ratio and native_count > 0:
                avg_l = native_left / native_count
                avg_r = native_right / native_count
                # Scale to int16 range
                sl = max(-32768, min(32767, int(avg_l * 24000)))
                sr = max(-32768, min(32767, int(avg_r * 24000)))
                output.append((sl, sr))
                native_left = 0.0
                native_right = 0.0
                native_count = 0
                native_pos -= ratio

                if len(output) >= num_samples:
                    break

        # Pad if needed
        while len(output) < num_samples:
            output.append((0, 0))

        return output


# ── Sequence Interpreter (Bytecode Executor) ─────────────────────────────────
#
# Executes the bytecode sequences that drive POKEY and YM2151, producing
# timed register writes that can be rendered to audio.

class SequenceInterpreter:
    """Executes Gauntlet sound ROM bytecode sequences against chip emulators."""

    # Frequency table: 128 entries at ROM 0x5A35, 16-bit LE
    FREQ_TABLE_ADDR = 0x5A35

    def __init__(self, rom, pokey=None, ym2151=None):
        self.rom = rom
        self.pokey = pokey
        self.ym2151 = ym2151

    def execute_to_audio(self, start_addr, channel_id, max_seconds=30.0,
                         sample_rate=44100):
        """Execute a sequence and return rendered PCM samples.

        For POKEY channels (channel_id >= 0x08): returns list of int16 (mono).
        For YM2151 channels (channel_id <= 0x07): returns list of (L,R) int16.

        Args:
            start_addr: ROM address of sequence start
            channel_id: Hardware channel assignment
            max_seconds: Safety limit on output duration
            sample_rate: Output sample rate
        """
        is_ym = channel_id <= 0x07
        hw_mode = "YM2151" if is_ym else "POKEY"

        # Collect timed events: list of (time_in_seconds, event_type, data)
        events = self._interpret_sequence(start_addr, channel_id, hw_mode,
                                          max_seconds)

        if is_ym and self.ym2151:
            return self._render_ym_events(events, max_seconds, sample_rate)
        elif not is_ym and self.pokey:
            return self._render_pokey_events(events, max_seconds, sample_rate)
        else:
            return []

    def _interpret_sequence(self, start_addr, channel_id, hw_mode,
                            max_seconds):
        """Walk bytecode and produce timed register-write events.

        Returns list of (time_secs, event_type, data) where event_type is
        'reg_write', 'note_on', 'note_off', 'end'.
        """
        events = []
        pc = start_addr
        return_stack = []     # for PUSH_SEQ (0x8D) call/return
        loop_stack = []       # for PUSH_SEQ_EXT (0x8E) repeat loops
                              # each entry: [loop_start_addr, remaining_count]

        tempo = 0
        volume = 0
        transpose = 0
        freq_offset = 0
        distortion = 0xA0     # default pure tone
        ctrl_bits = 0
        repeat_count = 0
        freq_env_ptr = 0
        vol_env_ptr = 0
        variables = [0] * 8
        var_reg = 0

        cumulative_frames = 0.0
        max_frames = max_seconds * 120.0
        max_instructions = 50000

        pokey_ch_idx = max(0, (channel_id - 8)) if channel_id >= 8 else 0

        for _ in range(max_instructions):
            if cumulative_frames > max_frames:
                break
            if pc < ROM_BASE or pc > ROM_END:
                break

            byte0 = self.rom.read_byte(pc)

            # End marker
            if byte0 >= 0xBB:
                events.append((cumulative_frames / 120.0, 'end', None))
                break

            # Note/Rest/Chain
            if byte0 <= 0x7F:
                byte1 = self.rom.read_byte(pc + 1)
                if byte1 == 0x00:
                    # CHAIN
                    if return_stack:
                        pc = return_stack.pop()
                        continue
                    else:
                        events.append((cumulative_frames / 120.0, 'end', None))
                        break

                # Parse duration
                dur_idx = byte1 & 0x0F
                dotted = bool(byte1 & 0x40)
                sustain = bool(byte1 & 0x80)

                if dur_idx == 0:
                    base_dur = 0
                else:
                    base_dur = self.rom.read_word(DURATION_TABLE_ADDR +
                                                  dur_idx * 2)
                dur_value = base_dur * 1.5 if dotted else float(base_dur)
                if tempo > 0 and dur_value > 0:
                    dur_frames = dur_value / tempo
                else:
                    dur_frames = 0.0

                time_secs = cumulative_frames / 120.0
                dur_secs = dur_frames / 120.0

                if byte0 != 0:  # Not a rest
                    note = byte0
                    # Apply transpose
                    effective_note = (note + transpose) & 0x7F
                    if effective_note == 0:
                        effective_note = 1

                    if hw_mode == "POKEY" and self.pokey:
                        # Read frequency from ROM table
                        freq_word = self.rom.read_word(
                            self.FREQ_TABLE_ADDR + effective_note * 2)
                        freq_word = (freq_word + freq_offset) & 0xFFFF

                        # Compute AUDF divider
                        if freq_word > 0:
                            audf = freq_word & 0xFF
                        else:
                            audf = 0

                        audc = (volume & 0x0F) | (distortion & 0xF0)
                        events.append((time_secs, 'pokey_note_on',
                                       (pokey_ch_idx, audf, audc)))
                        events.append((time_secs + dur_secs, 'pokey_note_off',
                                       (pokey_ch_idx,)))

                    elif hw_mode == "YM2151" and self.ym2151:
                        # Convert note to YM2151 key code
                        midi = effective_note - 1
                        octave = max(0, min(7, (midi // 12)))
                        semitone = midi % 12
                        # YM2151 note mapping
                        ym_notes = [0,1,2,4,5,6,8,9,10,12,13,14]
                        ym_note = ym_notes[semitone] if semitone < 12 else 0
                        kc = (octave << 4) | ym_note

                        events.append((time_secs, 'ym_note_on',
                                       (channel_id, kc, volume)))
                        if not sustain:
                            events.append((time_secs + dur_secs,
                                           'ym_note_off', (channel_id,)))
                        else:
                            events.append((time_secs + dur_secs,
                                           'ym_note_off', (channel_id,)))
                else:
                    # Rest - just silence
                    if hw_mode == "POKEY" and self.pokey:
                        events.append((time_secs, 'pokey_note_off',
                                       (pokey_ch_idx,)))

                cumulative_frames += dur_frames
                pc += 2
                continue

            # Opcodes 0x80-0xBA
            if byte0 not in OPCODES:
                pc += 2
                continue

            name, arg_bytes, desc, arg_fmt = OPCODES[byte0]
            args = []
            for i in range(arg_bytes):
                try:
                    args.append(self.rom.read_byte(pc + 1 + i))
                except ValueError:
                    break

            # Dispatch opcodes
            if byte0 == 0x80 and args:       # SET_TEMPO
                tempo = args[0] >> 2
            elif byte0 == 0x81 and args:     # ADD_TEMPO
                tempo = (tempo + args[0]) & 0xFF
            elif byte0 == 0x82 and args:     # SET_VOLUME
                volume = args[0]
            elif byte0 == 0x83 and args:     # SET_VOLUME_CHK
                volume = args[0]
            elif byte0 == 0x84 and args:     # ADD_TRANSPOSE
                val = args[0]
                if val >= 128:
                    val -= 256
                transpose = (transpose + val) & 0x7F
            elif byte0 == 0x86 and len(args) >= 2:  # SET_FREQ_ENV
                freq_env_ptr = args[0] | (args[1] << 8)
            elif byte0 == 0x87 and len(args) >= 2:  # SET_VOL_ENV
                vol_env_ptr = args[0] | (args[1] << 8)
            elif byte0 == 0x89 and args:     # SET_REPEAT
                repeat_count = args[0]
            elif byte0 == 0x8A and args:     # SET_DISTORTION
                distortion = args[0]
            elif byte0 == 0x8B and args:     # SET_CTRL_BITS
                ctrl_bits |= args[0]
            elif byte0 == 0x8C and args:     # CLR_CTRL_BITS
                ctrl_bits &= ~args[0]
            elif byte0 == 0x8D and len(args) >= 2:  # PUSH_SEQ
                target = args[0] | (args[1] << 8)
                ret = pc + 3
                if ROM_BASE <= target <= ROM_END:
                    return_stack.append(ret)
                    pc = target
                    continue
                else:
                    pc = ret
                    continue
            elif byte0 == 0x8E and args:     # PUSH_SEQ_EXT (repeat loop)
                loop_count = args[0]
                loop_start = pc + 2  # addr after this instruction
                if loop_count > 1:
                    loop_stack.append([loop_start, loop_count])
                # Execution continues linearly (no jump)
            elif byte0 == 0x8F:              # POP_SEQ
                if loop_stack:
                    loop_stack[-1][1] -= 1
                    if loop_stack[-1][1] > 0:
                        pc = loop_stack[-1][0]  # loop back
                        continue
                    else:
                        loop_stack.pop()  # done looping
                # No loop active or loop done: continue linearly (no-op)
            elif byte0 == 0x90:              # SWITCH_POKEY
                hw_mode = "POKEY"
            elif byte0 == 0x91:              # SWITCH_YM2151
                hw_mode = "YM2151"
            elif byte0 == 0x97:              # RESET_ENVELOPE
                freq_env_ptr = 0
                vol_env_ptr = 0
            elif byte0 == 0x99 and len(args) >= 2:  # SET_SEQ_PTR (jump)
                target = args[0] | (args[1] << 8)
                if ROM_BASE <= target <= ROM_END:
                    pc = target
                    continue
                else:
                    break
            elif byte0 == 0x9C:              # FORCE_POKEY
                hw_mode = "POKEY"
            elif byte0 == 0x9D and len(args) >= 2:  # SET_VOICE (YM2151)
                if hw_mode == "YM2151":
                    voice_ptr = args[0] | (args[1] << 8)
                    time_secs = cumulative_frames / 120.0
                    for reg, val in self._load_ym_voice(channel_id,
                                                        voice_ptr):
                        events.append((time_secs, 'ym_reg_write',
                                       (reg, val)))
            elif byte0 == 0x9E and len(args) >= 2:  # YM_LOAD_ENV
                pass  # envelope table load
            elif byte0 == 0x9F and len(args) >= 2:  # YM_LOAD_REG
                if hw_mode == "YM2151":
                    time_secs = cumulative_frames / 120.0
                    events.append((time_secs, 'ym_reg_write',
                                   (args[0], args[1])))
            elif byte0 == 0xA0 and args:     # FREQ_OFFSET
                val = args[0]
                if val >= 128:
                    val -= 256
                freq_offset = val
            elif byte0 == 0xA7 and args:     # FREQ_ADD
                val = args[0]
                if val >= 128:
                    val -= 256
                freq_offset = (freq_offset + val) & 0xFFFF
            elif byte0 == 0xA4 and len(args) >= 2:  # VAR_LOAD
                var_reg = args[0]
                if var_reg < len(variables):
                    variables[var_reg] = args[1]
            elif byte0 == 0xA9 and args:     # VAR_ADD
                if var_reg < len(variables):
                    variables[var_reg] = (variables[var_reg] + args[0]) & 0xFF
            elif byte0 == 0xAA and args:     # VAR_SUB
                if var_reg < len(variables):
                    variables[var_reg] = (variables[var_reg] - args[0]) & 0xFF
            elif byte0 == 0xAE and len(args) >= 2:  # COND_JUMP
                target = args[0] | (args[1] << 8)
                if var_reg < len(variables) and variables[var_reg] == 0:
                    if ROM_BASE <= target <= ROM_END:
                        pc = target
                        continue
            elif byte0 == 0xAF and len(args) >= 2:  # COND_JUMP_INC
                target = args[0] | (args[1] << 8)
                if var_reg < len(variables):
                    variables[var_reg] = (variables[var_reg] + 1) & 0xFF
                    if variables[var_reg] == 0:
                        if ROM_BASE <= target <= ROM_END:
                            pc = target
                            continue
            elif byte0 == 0xB5 and len(args) >= 3:  # COND_JUMP_EQ
                idx = args[0]
                target = args[1] | (args[2] << 8)
                if idx < len(variables) and variables[idx] == 0:
                    if ROM_BASE <= target <= ROM_END:
                        pc = target
                        continue
            elif byte0 == 0xB6 and len(args) >= 3:  # COND_JUMP_NE
                idx = args[0]
                target = args[1] | (args[2] << 8)
                if idx < len(variables) and variables[idx] != 0:
                    if ROM_BASE <= target <= ROM_END:
                        pc = target
                        continue
            elif byte0 == 0xB7 and len(args) >= 3:  # COND_JUMP_PL
                idx = args[0]
                target = args[1] | (args[2] << 8)
                if idx < len(variables):
                    val = variables[idx]
                    if val < 128:  # positive (unsigned < 0x80)
                        if ROM_BASE <= target <= ROM_END:
                            pc = target
                            continue
            elif byte0 == 0xB8 and len(args) >= 3:  # COND_JUMP_MI
                idx = args[0]
                target = args[1] | (args[2] << 8)
                if idx < len(variables):
                    val = variables[idx]
                    if val >= 128:  # negative (unsigned >= 0x80)
                        if ROM_BASE <= target <= ROM_END:
                            pc = target
                            continue

            pc += 1 + arg_bytes

        return events

    def _load_ym_voice(self, channel, voice_ptr):
        """Build register writes for a YM2151 voice definition from ROM.

        Returns list of (register, value) tuples.
        """
        writes = []
        try:
            ch = channel & 0x07
            fb_con = self.rom.read_byte(voice_ptr)
            writes.append((0x20 + ch, fb_con | 0xC0))  # L+R enabled
            ptr = voice_ptr + 1

            for slot_base in [
                    (0x40, 0x60, 0x80, 0xA0, 0xC0, 0xE0),   # M1
                    (0x50, 0x70, 0x90, 0xB0, 0xD0, 0xF0),   # M2
                    (0x48, 0x68, 0x88, 0xA8, 0xC8, 0xE8),   # C1
                    (0x58, 0x78, 0x98, 0xB8, 0xD8, 0xF8)]:  # C2
                for reg_base in slot_base:
                    val = self.rom.read_byte(ptr)
                    writes.append((reg_base + ch, val))
                    ptr += 1
        except (ValueError, IndexError):
            pass
        return writes

    def _render_pokey_events(self, events, max_seconds, sample_rate):
        """Render POKEY events to mono PCM samples."""
        if not self.pokey or not events:
            return []

        events.sort(key=lambda e: e[0])
        total_samples = int(max_seconds * sample_rate)

        # Find actual duration from events
        end_time = 0
        for t, etype, data in events:
            if etype == 'end' and t > 0:
                end_time = max(end_time, t)
            elif t > end_time:
                end_time = t
        end_time = min(end_time + 0.1, max_seconds)  # small tail

        if end_time <= 0:
            return []

        total_samples = int(end_time * sample_rate)
        if total_samples <= 0:
            return []

        # Process events in time order, rendering between them
        self.pokey.reset()
        self.pokey.SKCTL = 0x03  # ensure not in reset

        samples = []
        current_sample = 0
        event_idx = 0

        while current_sample < total_samples and event_idx <= len(events):
            # Find next event time
            if event_idx < len(events):
                next_time = events[event_idx][0]
                next_sample = min(int(next_time * sample_rate), total_samples)
            else:
                next_sample = total_samples

            # Render up to next event
            render_count = next_sample - current_sample
            if render_count > 0:
                chunk = self.pokey.render(render_count, sample_rate)
                samples.extend(chunk)
                current_sample += render_count

            # Apply events at this time
            while (event_idx < len(events) and
                   int(events[event_idx][0] * sample_rate) <= current_sample):
                t, etype, data = events[event_idx]
                if etype == 'pokey_note_on':
                    ch_idx, audf, audc = data
                    ch_idx = ch_idx % 4
                    self.pokey.write(ch_idx * 2, audf)      # AUDFn
                    self.pokey.write(ch_idx * 2 + 1, audc)  # AUDCn
                elif etype == 'pokey_note_off':
                    ch_idx = data[0] % 4
                    self.pokey.write(ch_idx * 2 + 1, 0)     # silence
                event_idx += 1

            if event_idx >= len(events):
                # Render remaining
                remain = total_samples - current_sample
                if remain > 0:
                    chunk = self.pokey.render(remain, sample_rate)
                    samples.extend(chunk)
                    current_sample += remain
                break

        return samples[:total_samples]

    def _render_ym_events(self, events, max_seconds, sample_rate):
        """Render YM2151 events to stereo PCM samples."""
        if not self.ym2151 or not events:
            return []

        events.sort(key=lambda e: e[0])

        end_time = 0
        for t, etype, data in events:
            if etype == 'end' and t > 0:
                end_time = max(end_time, t)
            elif t > end_time:
                end_time = t
        end_time = min(end_time + 0.5, max_seconds)

        if end_time <= 0:
            return []

        total_samples = int(end_time * sample_rate)
        if total_samples <= 0:
            return []

        self.ym2151.reset()
        samples = []
        current_sample = 0
        event_idx = 0

        while current_sample < total_samples and event_idx <= len(events):
            if event_idx < len(events):
                next_time = events[event_idx][0]
                next_sample = min(int(next_time * sample_rate), total_samples)
            else:
                next_sample = total_samples

            render_count = next_sample - current_sample
            if render_count > 0:
                chunk = self.ym2151.render(render_count, sample_rate)
                samples.extend(chunk)
                current_sample += render_count

            while (event_idx < len(events) and
                   int(events[event_idx][0] * sample_rate) <= current_sample):
                t, etype, data = events[event_idx]
                if etype == 'ym_reg_write':
                    reg, val = data
                    self.ym2151.write(reg, val)
                elif etype == 'ym_note_on':
                    ch, kc, vol = data
                    ch = ch & 0x07
                    self.ym2151.write(0x28 + ch, kc)
                    # Key on all 4 slots
                    self.ym2151.write(0x08, 0x78 | ch)
                elif etype == 'ym_note_off':
                    ch = data[0] & 0x07
                    self.ym2151.write(0x08, ch)  # all slots off
                event_idx += 1

            if event_idx >= len(events):
                remain = total_samples - current_sample
                if remain > 0:
                    chunk = self.ym2151.render(remain, sample_rate)
                    samples.extend(chunk)
                    current_sample += remain
                break

        return samples[:total_samples]


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


# ── Audio Normalization ─────────────────────────────────────────────────────

def _normalize_mono(samples, target_peak=0.9):
    """Normalize mono int16 samples to target peak level (0.0-1.0)."""
    if not samples:
        return samples
    peak = max(abs(s) for s in samples)
    if peak == 0:
        return samples
    target = int(32767 * target_peak)
    scale = target / peak
    return [max(-32768, min(32767, int(s * scale))) for s in samples]


def _normalize_stereo(samples, target_peak=0.9):
    """Normalize stereo (L,R) int16 samples to target peak level."""
    if not samples:
        return samples
    peak = max(max(abs(s[0]), abs(s[1])) for s in samples)
    if peak == 0:
        return samples
    target = int(32767 * target_peak)
    scale = target / peak
    return [(max(-32768, min(32767, int(l * scale))),
             max(-32768, min(32767, int(r * scale))))
            for l, r in samples]


# ── POKEY SFX WAV Export ────────────────────────────────────────────────────

def sfx_to_wav(rom, cmd, names, out_path, sample_rate=44100):
    """Render a POKEY SFX command to a WAV file."""
    info = resolve_command(rom, cmd)
    if info is None:
        print(f"Invalid command number: 0x{cmd:02X}", file=sys.stderr)
        return

    if info.handler_type != 7:
        print(f"Command 0x{cmd:02X}: not a type 7 SFX command "
              f"(type {info.handler_type}: {info.type_name})")
        return

    channels = info.channels or []
    if not channels:
        print(f"Command 0x{cmd:02X}: no channel data")
        return

    # Filter to POKEY channels (channel_id >= 0x08)
    pokey_channels = [ch for ch in channels if ch.channel >= 0x08]
    ym_channels = [ch for ch in channels if ch.channel < 0x08]

    all_samples = []
    hw_desc = []

    # Render POKEY channels
    for ch in pokey_channels:
        pokey = POKEYEmulator()
        interp = SequenceInterpreter(rom, pokey=pokey)
        print(f"  Rendering POKEY channel 0x{ch.channel:02X} "
              f"(seq @ ${ch.seq_ptr:04X})...", flush=True)
        samples = interp.execute_to_audio(ch.seq_ptr, ch.channel,
                                          sample_rate=sample_rate)
        if samples:
            all_samples.append(('mono', samples))
            hw_desc.append(f"POKEY ch0x{ch.channel:02X}")

    # Render YM2151 channels
    if ym_channels:
        ym = YM2151Emulator()
        for ch in ym_channels:
            interp = SequenceInterpreter(rom, ym2151=ym)
            print(f"  Rendering YM2151 channel 0x{ch.channel:02X} "
                  f"(seq @ ${ch.seq_ptr:04X})...", flush=True)
            samples = interp.execute_to_audio(ch.seq_ptr, ch.channel,
                                              sample_rate=sample_rate)
            if samples:
                all_samples.append(('stereo', samples))
                hw_desc.append(f"YM2151 ch0x{ch.channel:02X}")

    if not all_samples:
        print(f"Command 0x{cmd:02X}: rendering produced no audio")
        return

    # Mix all channels using float accumulation to avoid clipping.
    # Scale each chip group (POKEY vs YM2151) to contribute equally,
    # then normalize the final mix.
    has_stereo = any(t == 'stereo' for t, _ in all_samples)
    max_len = max(len(s) for _, s in all_samples)

    # Accumulate in float — separate POKEY and YM groups
    pokey_l = [0.0] * max_len
    pokey_r = [0.0] * max_len
    ym_l = [0.0] * max_len
    ym_r = [0.0] * max_len
    n_pokey = 0
    n_ym = 0

    for stype, sdata in all_samples:
        if stype == 'stereo':
            n_ym += 1
            for i in range(len(sdata)):
                ym_l[i] += sdata[i][0]
                ym_r[i] += sdata[i][1]
        else:
            n_pokey += 1
            for i in range(len(sdata)):
                pokey_l[i] += sdata[i]
                pokey_r[i] += sdata[i]

    # Find peak of each group
    pokey_peak = max(max(abs(pokey_l[i]), abs(pokey_r[i]))
                     for i in range(max_len)) if n_pokey else 0
    ym_peak = max(max(abs(ym_l[i]), abs(ym_r[i]))
                  for i in range(max_len)) if n_ym else 0

    # Scale each group so its peak fits in roughly half of int16 range.
    # This ensures neither chip dominates the other in the mix.
    # When only one chip is present, it gets the full range.
    if n_pokey > 0 and n_ym > 0:
        # Both present: give each half the headroom
        target = 16000.0
        pk_scale = (target / pokey_peak) if pokey_peak > 0 else 0.0
        ym_scale = (target / ym_peak) if ym_peak > 0 else 0.0
    elif n_pokey > 0:
        pk_scale = (29000.0 / pokey_peak) if pokey_peak > 0 else 0.0
        ym_scale = 0.0
    else:
        pk_scale = 0.0
        ym_scale = (29000.0 / ym_peak) if ym_peak > 0 else 0.0

    # Final mix
    if has_stereo:
        mixed = []
        for i in range(max_len):
            l = pokey_l[i] * pk_scale + ym_l[i] * ym_scale
            r = pokey_r[i] * pk_scale + ym_r[i] * ym_scale
            mixed.append((max(-32768, min(32767, int(l))),
                          max(-32768, min(32767, int(r)))))

        with wave.open(out_path, 'w') as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            pcm = b''
            for l, r in mixed:
                pcm += struct.pack('<hh', l, r)
            wf.writeframes(pcm)
        n_samples = len(mixed)
    else:
        mixed = []
        for i in range(max_len):
            s = pokey_l[i] * pk_scale + ym_l[i] * ym_scale
            mixed.append(max(-32768, min(32767, int(s))))

        with wave.open(out_path, 'w') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            pcm = struct.pack(f'<{len(mixed)}h', *mixed)
            wf.writeframes(pcm)
        n_samples = len(mixed)

    duration = n_samples / sample_rate
    name_info = names.get(cmd)
    label = f'"{name_info[1]}"' if name_info else f"0x{cmd:02X}"
    print(f"SFX command 0x{cmd:02X} {label}:")
    print(f"  Channels: {', '.join(hw_desc)}")
    print(f"  Samples: {n_samples} ({duration:.2f}s @ {sample_rate} Hz)")
    print(f"  Output: {out_path}")


def sfx_all_to_wav(rom, names, out_dir, sample_rate=44100):
    """Render all POKEY SFX commands to WAV files in a directory."""
    os.makedirs(out_dir, exist_ok=True)

    count = 0
    for cmd in range(MAX_COMMANDS):
        info = resolve_command(rom, cmd)
        if info is None or info.handler_type != 7:
            continue
        channels = info.channels or []
        if not channels:
            continue
        # Check if any channel is POKEY
        has_pokey = any(ch.channel >= 0x08 for ch in channels)
        if not has_pokey:
            continue

        name_info = names.get(cmd)
        if name_info:
            safe = name_info[1].replace(' ', '_').replace('"', '').replace("'", '')
            safe = ''.join(c for c in safe if c.isalnum() or c in '_-')
            safe = safe.strip('_-')
            fname = f"0x{cmd:02X}_{safe}.wav"
        else:
            fname = f"0x{cmd:02X}.wav"

        out_path = os.path.join(out_dir, fname)
        print(f"\n--- Command 0x{cmd:02X} ---")
        try:
            sfx_to_wav(rom, cmd, names, out_path, sample_rate)
            count += 1
        except Exception as e:
            print(f"  Error: {e}", file=sys.stderr)

    print(f"\nExported {count} SFX commands to {out_dir}/")


# ── Music WAV Export ────────────────────────────────────────────────────────

def music_to_wav(rom, cmd, names, out_path, sample_rate=44100):
    """Render a music command (YM2151 channels) to a WAV file."""
    info = resolve_command(rom, cmd)
    if info is None:
        print(f"Invalid command number: 0x{cmd:02X}", file=sys.stderr)
        return

    if info.handler_type != 7:
        print(f"Command 0x{cmd:02X}: not a type 7 command "
              f"(type {info.handler_type}: {info.type_name})")
        return

    channels = info.channels or []
    if not channels:
        print(f"Command 0x{cmd:02X}: no channel data")
        return

    ym_channels = [ch for ch in channels if ch.channel < 0x08]
    if not ym_channels:
        print(f"Command 0x{cmd:02X}: no YM2151 channels (POKEY SFX only)")
        return

    # Shared YM2151 for all channels
    ym = YM2151Emulator()
    all_events = []

    for ch in ym_channels:
        interp = SequenceInterpreter(rom, ym2151=ym)
        print(f"  Interpreting YM2151 channel 0x{ch.channel:02X} "
              f"(seq @ ${ch.seq_ptr:04X})...", flush=True)
        events = interp._interpret_sequence(ch.seq_ptr, ch.channel,
                                            "YM2151", max_seconds=300.0)
        all_events.extend(events)

    if not all_events:
        print(f"Command 0x{cmd:02X}: no events generated")
        return

    # Sort all events by time and render
    all_events.sort(key=lambda e: e[0])

    end_time = 0
    for t, etype, data in all_events:
        if t > end_time:
            end_time = t
    end_time = min(end_time + 1.0, 300.0)

    total_samples = int(end_time * sample_rate)
    if total_samples <= 0:
        print(f"Command 0x{cmd:02X}: zero duration")
        return

    print(f"  Rendering {end_time:.1f}s of audio ({total_samples} samples)...",
          flush=True)

    ym.reset()
    samples = []
    current_sample = 0
    event_idx = 0

    while current_sample < total_samples:
        # Find next event
        if event_idx < len(all_events):
            next_time = all_events[event_idx][0]
            next_sample = min(int(next_time * sample_rate), total_samples)
        else:
            next_sample = total_samples

        render_count = next_sample - current_sample
        if render_count > 0:
            chunk = ym.render(render_count, sample_rate)
            samples.extend(chunk)
            current_sample += render_count

        # Apply events
        while (event_idx < len(all_events) and
               int(all_events[event_idx][0] * sample_rate) <= current_sample):
            t, etype, data = all_events[event_idx]
            if etype == 'ym_reg_write':
                reg, val = data
                ym.write(reg, val)
            elif etype == 'ym_note_on':
                ch_id, kc, vol = data
                ch_id = ch_id & 0x07
                ym.write(0x28 + ch_id, kc)
                ym.write(0x08, 0x78 | ch_id)
            elif etype == 'ym_note_off':
                ch_id = data[0] & 0x07
                ym.write(0x08, ch_id)
            event_idx += 1

        if event_idx >= len(all_events):
            remain = total_samples - current_sample
            if remain > 0:
                chunk = ym.render(remain, sample_rate)
                samples.extend(chunk)
                current_sample += remain
            break

    # Normalize and write stereo WAV
    samples = _normalize_stereo(samples)
    with wave.open(out_path, 'w') as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        pcm = b''
        for l, r in samples:
            pcm += struct.pack('<hh', l, r)
        wf.writeframes(pcm)

    duration = len(samples) / sample_rate
    name_info = names.get(cmd)
    label = f'"{name_info[1]}"' if name_info else f"0x{cmd:02X}"
    print(f"Music command 0x{cmd:02X} {label}:")
    print(f"  YM2151 channels: {len(ym_channels)}")
    print(f"  Samples: {len(samples)} ({duration:.2f}s @ {sample_rate} Hz)")
    print(f"  Output: {out_path}")


def music_all_to_wav(rom, names, out_dir, sample_rate=44100):
    """Render all music commands to WAV files."""
    os.makedirs(out_dir, exist_ok=True)

    count = 0
    for cmd in range(MAX_COMMANDS):
        info = resolve_command(rom, cmd)
        if info is None or info.handler_type != 7:
            continue
        channels = info.channels or []
        if not channels:
            continue
        has_ym = any(ch.channel < 0x08 for ch in channels)
        if not has_ym:
            continue

        name_info = names.get(cmd)
        if name_info:
            safe = name_info[1].replace(' ', '_').replace('"', '').replace("'", '')
            safe = ''.join(c for c in safe if c.isalnum() or c in '_-')
            safe = safe.strip('_-')
            fname = f"0x{cmd:02X}_{safe}.wav"
        else:
            fname = f"0x{cmd:02X}.wav"

        out_path = os.path.join(out_dir, fname)
        print(f"\n{'='*60}")
        print(f"Command 0x{cmd:02X}")
        try:
            music_to_wav(rom, cmd, names, out_path, sample_rate)
            count += 1
        except Exception as e:
            print(f"  Error: {e}", file=sys.stderr)

    print(f"\nExported {count} music commands to {out_dir}/")


def render_wav(rom, cmd, names, out_path, sample_rate=44100):
    """Render any type 7 command to WAV (auto-detects POKEY vs YM2151)."""
    info = resolve_command(rom, cmd)
    if info is None:
        print(f"Invalid command number: 0x{cmd:02X}", file=sys.stderr)
        return

    if info.handler_type == 11 and info.is_speech:
        speech_to_wav(rom, cmd, names, out_path)
        return

    if info.handler_type != 7:
        print(f"Command 0x{cmd:02X}: not renderable "
              f"(type {info.handler_type}: {info.type_name})")
        return

    channels = info.channels or []
    has_ym = any(ch.channel < 0x08 for ch in channels)
    has_pokey = any(ch.channel >= 0x08 for ch in channels)

    if has_ym and not has_pokey:
        music_to_wav(rom, cmd, names, out_path, sample_rate)
    elif has_pokey:
        sfx_to_wav(rom, cmd, names, out_path, sample_rate)
    else:
        print(f"Command 0x{cmd:02X}: no renderable channels")


def render_all_to_wav(rom, names, out_dir, sample_rate=44100):
    """Render all renderable commands (SFX + music + speech) to WAV."""
    os.makedirs(out_dir, exist_ok=True)

    count = 0
    for cmd in range(MAX_COMMANDS):
        info = resolve_command(rom, cmd)
        if info is None:
            continue

        if info.handler_type == 7 and info.channels:
            name_info = names.get(cmd)
            if name_info:
                safe = name_info[1].replace(' ', '_').replace('"', '').replace("'", '')
                safe = ''.join(c for c in safe if c.isalnum() or c in '_-')
                safe = safe.strip('_-')
                fname = f"0x{cmd:02X}_{safe}.wav"
            else:
                fname = f"0x{cmd:02X}.wav"

            out_path = os.path.join(out_dir, fname)
            print(f"\n{'='*60}")
            try:
                render_wav(rom, cmd, names, out_path, sample_rate)
                count += 1
            except Exception as e:
                print(f"  Error rendering 0x{cmd:02X}: {e}", file=sys.stderr)

    print(f"\nExported {count} audio commands to {out_dir}/")


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
  %(prog)s soundrom.bin --sfx-wav 0x0D    # Render POKEY SFX to WAV
  %(prog)s soundrom.bin --sfx-all         # Render all POKEY SFX to WAV
  %(prog)s soundrom.bin --music-wav 0x3B  # Render YM2151 music to WAV
  %(prog)s soundrom.bin --music-all       # Render all music to WAV
  %(prog)s soundrom.bin --render-wav 0x0D # Auto-detect and render to WAV
  %(prog)s soundrom.bin --render-all      # Render all commands to WAV
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
    parser.add_argument("--sfx-wav", type=parse_int, metavar="N",
                        help="Render POKEY SFX command N to WAV file")
    parser.add_argument("--sfx-all", action="store_true",
                        help="Render all POKEY SFX commands to WAV files")
    parser.add_argument("--music-wav", type=parse_int, metavar="N",
                        help="Render YM2151 music command N to WAV file")
    parser.add_argument("--music-all", action="store_true",
                        help="Render all YM2151 music commands to WAV files")
    parser.add_argument("--render-wav", type=parse_int, metavar="N",
                        help="Render any command N to WAV (auto-detects type)")
    parser.add_argument("--render-all", action="store_true",
                        help="Render all renderable commands to WAV files")
    parser.add_argument("--out", metavar="FILE",
                        help="Output path for WAV file (default: auto-generated)")
    parser.add_argument("--out-dir", metavar="DIR",
                        help="Output directory for batch exports (default: varies)")
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

    if args.sfx_wav is not None:
        out = args.out or f"sfx_0x{args.sfx_wav:02X}.wav"
        sfx_to_wav(rom, args.sfx_wav, names, out)

    elif args.sfx_all:
        out_dir = args.out_dir or "sfx"
        sfx_all_to_wav(rom, names, out_dir)

    elif args.music_wav is not None:
        out = args.out or f"music_0x{args.music_wav:02X}.wav"
        music_to_wav(rom, args.music_wav, names, out)

    elif args.music_all:
        out_dir = args.out_dir or "music"
        music_all_to_wav(rom, names, out_dir)

    elif args.render_wav is not None:
        out = args.out or f"render_0x{args.render_wav:02X}.wav"
        render_wav(rom, args.render_wav, names, out)

    elif args.render_all:
        out_dir = args.out_dir or "rendered"
        render_all_to_wav(rom, names, out_dir)

    elif args.speech_wav is not None:
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
