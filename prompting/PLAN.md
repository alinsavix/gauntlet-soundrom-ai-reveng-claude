# Gauntlet Sound ROM Analysis Plan

## Objective
Systematically analyze the 6502-based sound coprocessor ROM (`soundrom.bin`) from the Gauntlet arcade game using radare2 MCP tools to understand:
- Overall code structure (main loop, command dispatcher)
- Command dispatch flow and handler mapping
- Sound chip communication (POKEY, YM2151, TMS5220)
- Data table locations and formats
- Initialization sequences
- Hardware register interaction patterns

## Critical Context

**ROM Details:**
- File: `/tmp/gauntlet-soundrom-reveng/soundrom.bin` (48KB)
- **Format: Raw binary dump** (no headers, no metadata, just CPU code/data)
- **Hand-written assembly code** (not compiler output - expect irregular patterns)
- CPU address mapping: 0x4000-0xFFFF (must be manually configured in radare2)
  - File offset 0x0000 = CPU address 0x4000
  - File offset 0xBFFF = CPU address 0xFFFF
- Interrupt vectors at ROM end (CPU addresses):
  - Reset vector (stored at 0xFFFC): 0x5a25 (initialization entry point)
  - IRQ vector (stored at 0xFFFE): 0x4187
  - NMI vector (stored at 0xFFFA): 0x57b0
- 262+ JSR instructions (function calls), 259+ RTS instructions
- Code/data intermixed throughout ROM (no separate sections)

**Hardware Architecture:**
- RAM: 0x0000-0x0FFF
- Hardware: 0x1000 - 0x1fff (sparse address space)
- Command input: 0x1010 (from main CPU)
- Status output: 0x1000, 0x1030
- POKEY (SFX): 0x1800-0x180F (4 channels)
- YM2151 (music): 0x1810-0x1811 (register select + data)
- TMS5220 (speech): 0x1830
- 214 sound commands (0x00-0xD5) documented in soundcmds.csv

**Radare2 Limitation:**
6502 architecture lacks automatic function detection - must manually identify functions via JSR target analysis and define them before decompilation.

## State Management Between Phases

**CRITICAL: Save and restore radare2 state at phase boundaries**

Radare2 projects preserve all analysis work (functions, names, comments, xrefs) allowing you to pause and resume:

**Saving State (at end of each phase):**
```
run_command("Ps gauntlet_sound_phase_N")
```
- Saves all defined functions, renamed symbols, comments, and analysis data
- Project stored in radare2's project directory
- Replace N with phase number (1, 2, 3, etc.)

**Loading State (at start of each phase after Phase 1):**
1. Close current file: `close_file()`
2. Open ROM: `open_file("/tmp/gauntlet-soundrom-reveng/soundrom.bin")`
3. Load saved project: `run_command("Po gauntlet_sound_phase_N")`
   - Restores ROM mapping, function definitions, names, and all annotations
   - Replace N with previous phase number
4. Verify state loaded: `run_command("afl")` to list functions

**Phase Workflow:**
- **Phase 1**: Setup from scratch → Save as `gauntlet_sound_phase_1`
- **Phase 2**: Load `gauntlet_sound_phase_1` → Work → Save as `gauntlet_sound_phase_2`
- **Phase 3**: Load `gauntlet_sound_phase_2` → Work → Save as `gauntlet_sound_phase_3`
- And so on...

**If MCP server needs restart:**
- Simply reload the last saved phase project
- All work (functions, names, xrefs) will be restored
- No need to reconfigure ROM mapping or redefine functions

## Analysis Approach

### Phase 1: Setup & Initial Mapping
**Goal:** Configure radare2 and map code structure

**Raw ROM Setup (Critical):**
1. Open ROM with `mcp__radare2__open_file("/tmp/gauntlet-soundrom-reveng/soundrom.bin")`
2. Set architecture BEFORE mapping: `run_command("e asm.arch=6502")`
3. Set CPU: `run_command("e asm.cpu=6502")`
4. Enable virtual addressing: `run_command("e io.va=true")`
5. Map ROM to correct address space: `run_command("om `oq` 0x4000 0xc000 0x0 r-x")`
   - Maps 48KB ROM file to CPU address 0x4000-0xFFFF
6. Seek to ROM start: `run_command("s 0x4000")`
7. Verify mapping worked: `run_command("om")` should show map at 0x4000

**Vector Table Analysis:**
8. Read interrupt vectors (at end of ROM): `run_command("pxw 6 @ 0xFFFA")`
9. Extract addresses:
   - NMI vector at 0xFFFA
   - RESET vector at 0xFFFC (primary entry point)
   - IRQ vector at 0xFFFE

**Manual Function Discovery (Hand-written code requires careful analysis):**
10. Run conservative analysis: `analyze(level=1)` - avoid false positives from data
11. Find all JSR instructions: `run_command("/x 20 0x4000 0xFFFF")` - opcode 0x20
12. Parse JSR targets from search results
13. Verify targets are in code regions (not data tables)
14. **Manually define functions starting with vectors:**
    - `run_command("af @ <reset_vector>")` - entry point first
    - `run_command("af @ <irq_vector>")`
    - `run_command("af @ <nmi_vector>")`
15. Define next 20-30 most-called JSR targets
16. **Immediately rename vectors:**
    - `rename_function(address="<reset_vector>", name="RESET_HANDLER")`
    - Similar for IRQ_HANDLER, NMI_HANDLER

**Hand-written Assembly Considerations:**
- Expect interleaved code/data (tables within functions)
- Watch for inline data after JSR/RTS (function pointers, jump tables)
- Look for `JMP (addr,X)` indexed indirect jumps (computed dispatch)
- Don't assume regular function prologues/epilogues

**Outputs:**
- Confirmed ROM mapped to 0x4000-0xFFFF
- Interrupt vector addresses extracted and verified
- ~130 unique JSR target addresses identified
- Top 30 functions manually defined in radare2
- Three vector handlers renamed
- Update REPORT.md with findings and wait for approval

**Save State:**
```
run_command("Ps gauntlet_sound_phase_1")
```
All ROM mapping, function definitions, and renames preserved for Phase 2.

---

### Phase 2: Hardware Register Mapping
**Goal:** Find all code that interacts with sound hardware

**Load Previous State:**
1. `close_file()` - Close any open file
2. `open_file("/tmp/gauntlet-soundrom-reveng/soundrom.bin")` - Reopen ROM
3. `run_command("Po gauntlet_sound_phase_1")` - Load Phase 1 project
4. Verify: `run_command("afl")` - Should show ~30 defined functions

**POKEY (0x1800-0x180F):**
1. Search for writes to each register:
   - `run_command("/x 8d0018")` - STA 0x1800 (AUDF1 frequency)
   - `run_command("/x 8d0118")` - STA 0x1801 (AUDC1 control/volume)
   - Continue for 0x1802-0x1808 (channels 2-4 + AUDCTL)
2. Use `xrefs_to` for each address to identify accessing functions
3. Categorize functions that write to POKEY as SFX handlers

**YM2151 (0x1810-0x1811):**
1. Search for register writes:
   - `run_command("/x 8d1018")` - STA 0x1810 (register select)
   - `run_command("/x 8d1118")` - STA 0x1811 (data write)
2. Identify YM2151 write helper function
3. Find music-related functions via xrefs

**Command/Status Registers:**
1. Command reads: `run_command("/x ad1010")` - LDA 0x1010
2. Status writes: `run_command("/x 8d3010")` - STA 0x1030

**Outputs:**
- Map of all hardware register access locations
- Identified hardware interaction functions
- Function categorization (POKEY/YM2151/command handling)
- **IMMEDIATELY** rename hardware functions (POKEY_WRITE, YM2151_WRITE, etc.)
- Update REPORT.md with hardware mapping and wait for approval

**Save State:**
```
run_command("Ps gauntlet_sound_phase_2")
```

---

### Phase 3: Initialization Analysis
**Goal:** Understand system startup sequence

**Load Previous State:**
1. `close_file()`
2. `open_file("/tmp/gauntlet-soundrom-reveng/soundrom.bin")`
3. `run_command("Po gauntlet_sound_phase_2")`
4. Verify hardware function names present

1. Disassemble reset handler: `run_command("pd 100 @ <reset_vector>")`
2. **Before decompiling**, verify function boundary: `run_command("pdf @ <reset_vector>")`
3. If boundary looks wrong, manually adjust: `run_command("afu <reset_vector>")`
4. Decompile reset handler: `decompile_function("<reset_vector>")`
5. **Hand-written code analysis - look for:**
   - Stack pointer init (LDX #$FF, TXS) - may be non-standard location
   - Zero-page variable initialization (custom patterns, not compiler templates)
   - Hardware register init sequences (direct STA to I/O addresses)
   - Unusual optimization tricks (self-modifying code, shared cleanup routines)
6. Trace JSR calls from reset handler
7. Document initialization sequence:
   - Stack setup (TXS)
   - Interrupt configuration (SEI/CLI)
   - RAM clearing loops (may use clever countdown tricks)
   - POKEY initialization (register write sequences)
   - YM2151 initialization (with timing delays)
   - Interrupt vector setup (may be in RAM, not ROM)
8. Rename called functions as identified (e.g., INIT_POKEY, INIT_YM2151, CLEAR_RAM)

**Hand-written Assembly Patterns:**
- May reuse init code across chips (shared delay routines)
- Watch for unrolled loops (manual optimization)
- Init tables may be inline with code, not separate data sections

**Outputs:**
- Complete initialization flow documentation
- Hardware setup sequences for each sound chip
- Memory layout initialization
- Named initialization functions (already renamed in Phase 1)
- Update REPORT.md with initialization sequence and wait for approval

**Save State:**
```
run_command("Ps gauntlet_sound_phase_3")
```

---

### Phase 4: Command Dispatch System
**Goal:** Map command numbers to handler functions

**Load Previous State:**
1. `close_file()`
2. `open_file("/tmp/gauntlet-soundrom-reveng/soundrom.bin")`
3. `run_command("Po gauntlet_sound_phase_3")`
4. Verify initialization function names present

**Finding the Dispatcher (Hand-written patterns):**
1. Look for command input read: Search for `LDA $1010` - `run_command("/x ad1010")`
2. Trace xrefs to find main dispatcher function
3. Dispatcher likely uses one of these hand-coded patterns:
   - **Jump table**: `ASL A; TAX; LDA table,X; STA zp; LDA table+1,X; STA zp+1; JMP (zp)`
   - **Indexed indirect**: `JMP (table,X)` - requires addresses in zero-page
   - **Computed JSR**: `JSR indirect_jump; .word handler` - custom trampoline
   - **Range checking**: May have bounds check before dispatch (CMP #$D5)

**Analyzing Dispatcher:**
4. Disassemble dispatcher region: `run_command("pd 50 @ <dispatcher_addr>")`
5. Decompile dispatcher: `decompile_function("<dispatcher_address>")`
6. **Identify table address** - look for:
   - Base address loaded into zero-page (e.g., `LDA #<table; STA $80`)
   - Indexed access pattern with command value
   - May be split into high/low byte tables

**Extract Handler Table:**
7. Once table found, extract raw data: `run_command("px 428 @ <table_addr>")` (214 cmds × 2 bytes)
8. **Verify table format**:
   - Check if addresses are little-endian (LSB first, typical for 6502)
   - Verify addresses fall in ROM range (0x4000-0xFFFF)
   - Cross-check a few known handlers from previous exploration
9. Parse address pairs and create command→handler map

**Handler Analysis:**
10. Define functions at handler addresses: `run_command("af @ <handler_addr>")`
11. Cross-reference with soundcmds.csv to get handler names
12. **Immediately rename handlers** with command names: `rename_function(address="<addr>", name="CMD_FOOD_EATEN")`
13. Group handlers by category (SFX/Music/Speech) for systematic analysis

**Hand-written Assembly Notes:**
- Table may be split (256-byte high/low arrays for page alignment)
- Watch for special case handlers (e.g., cmd 0x00 may be NOP)
- Handlers may share common code via fall-through (no RTS, continues into next)

**Outputs:**
- Complete command-to-handler mapping table (0x00-0xD5)
- Identified command dispatcher logic and pattern
- All 214 handler functions defined in radare2
- Key handlers renamed with descriptive names
- Update REPORT.md with command mapping table and wait for approval

**Save State:**
```
run_command("Ps gauntlet_sound_phase_4")
```
All 214 command handlers defined and many renamed.

---

### Phase 5: POKEY Sound Effects Analysis
**Goal:** Understand SFX generation and data formats

**Load Previous State:**
1. `close_file()`
2. `open_file("/tmp/gauntlet-soundrom-reveng/soundrom.bin")`
3. `run_command("Po gauntlet_sound_phase_4")`
4. Verify command handler functions defined

1. Select simple SFX command (e.g., 0x0D "Food Eaten")
2. Decompile handler: `decompile_function("<handler_address>")`
3. Trace code flow to identify:
   - Data table reads (LDA table,X before hardware writes)
   - POKEY register write sequences
   - Multi-channel coordination
4. Extract SFX data tables: `run_command("px 64 @ <table_address>")`
5. Document table format:
   - Frequency values (AUDFx)
   - Volume/distortion (AUDCx bits)
   - Duration/timing
   - Channel assignments
6. Analyze multi-channel effects (e.g., heartbeat commands 0x18-0x1B)
7. Document common POKEY programming patterns

**Outputs:**
- SFX data table locations and formats
- POKEY register programming sequences
- Channel allocation strategies
- Sound effect generation algorithms
- Named POKEY-related functions
- Update REPORT.md with POKEY analysis and wait for approval

**Save State:**
```
run_command("Ps gauntlet_sound_phase_5")
```

---

### Phase 6: YM2151 Music Analysis
**Goal:** Understand FM synthesis and music playback

**Load Previous State:**
1. `close_file()`
2. `open_file("/tmp/gauntlet-soundrom-reveng/soundrom.bin")`
3. `run_command("Po gauntlet_sound_phase_5")`
4. Verify POKEY analysis data present

1. Find YM2151 write wrapper function via xrefs to 0x1810/0x1811
2. Decompile wrapper to understand write protocol (register select → delay → data write)
3. Analyze music test command (0x04): `decompile_function("<cmd_0x04_handler>")`
4. Analyze main music command (0x3B "Gauntlet Theme"): `decompile_function("<cmd_0x3B_handler>")`
5. Identify music data structures:
   - Instrument definitions (operator parameters)
   - Note sequences
   - Timing/duration data
   - Channel assignments
6. Extract instrument table: `run_command("px 512 @ <instrument_addr>")`
7. Document YM2151 register programming:
   - Operator setup (detune, multiply, levels)
   - Envelope parameters (ADSR)
   - Channel/algorithm configuration
8. Analyze music playback loop (likely in interrupt handler)

**Outputs:**
- YM2151 initialization sequence
- Instrument definitions and formats
- Music sequence data structures
- Note playback mechanisms
- Named YM2151-related functions
- Update REPORT.md with music analysis and wait for approval

**Save State:**
```
run_command("Ps gauntlet_sound_phase_6")
```

---

### Phase 7: Interrupt System Analysis
**Goal:** Understand real-time audio processing

**Load Previous State:**
1. `close_file()`
2. `open_file("/tmp/gauntlet-soundrom-reveng/soundrom.bin")`
3. `run_command("Po gauntlet_sound_phase_6")`
4. Verify YM2151 function names and analysis present

1. Read interrupt vectors: `run_command("pxw 6 @ 0xFFFA")`
2. Decompile NMI handler: `decompile_function("<nmi_vector>")`
3. Decompile IRQ handler: `decompile_function("<irq_vector>")`
4. Document interrupt flow:
   - Register preservation (PHA)
   - Interrupt source identification
   - Handler dispatch
   - Register restoration (PLA)
   - Return (RTI)
5. Identify audio update rate and timing
6. Find critical sections (SEI/CLI pairs)
7. Understand command buffer management in interrupt context

**Outputs:**
- Complete interrupt architecture documentation
- Audio update timing information
- Interrupt-driven command processing flow
- Named interrupt handlers
- Update REPORT.md with interrupt analysis and wait for approval

**Save State:**
```
run_command("Ps gauntlet_sound_phase_7")
```

---

### Phase 8: Data Table Extraction
**Goal:** Locate and document all major data tables

**Load Previous State:**
1. `close_file()`
2. `open_file("/tmp/gauntlet-soundrom-reveng/soundrom.bin")`
3. `run_command("Po gauntlet_sound_phase_7")`
4. Verify interrupt handler analysis complete

1. Identify code/data boundaries by finding RTS clusters
2. Extract string data: `list_strings(filter=".{4,}")`
3. Document table locations:
   - Command dispatch table (Phase 4)
   - POKEY SFX tables (Phase 5)
   - YM2151 instrument/sequence tables (Phase 6)
   - Speech data tables (0x1830 related)
4. For each table:
   - Record address and size
   - Extract hex dump
   - Document format specification
   - Add comments to accessing code
5. Create comprehensive table location map

**Outputs:**
- Complete table address reference
- Table format specifications
- Extracted table data
- Comments linking code to tables
- Update REPORT.md with table catalog and wait for approval

**Save State:**
```
run_command("Ps gauntlet_sound_phase_8")
```

---

### Phase 9: Comprehensive Documentation Review
**Goal:** Review all function naming and add final comments

**Load Previous State:**
1. `close_file()`
2. `open_file("/tmp/gauntlet-soundrom-reveng/soundrom.bin")`
3. `run_command("Po gauntlet_sound_phase_8")`
4. Verify all table extraction data present

1. Verify all major functions have descriptive names (should be done in earlier phases)
2. Add any remaining comments to key code sections:
   - Hardware register accesses
   - Command dispatch logic
   - Data table reads
   - Timing-critical sections
3. Generate function call hierarchy: `list_functions_tree()`
4. Document common subroutines and their usage patterns
5. Create cross-reference of hardware registers → functions
6. Finalize REPORT.md with complete analysis

**Outputs:**
- Fully annotated disassembly
- Function call graph
- Hardware interaction summary
- Comprehensive code documentation
- Final REPORT.md update and wait for approval

**Save State:**
```
run_command("Ps gauntlet_sound_phase_9")
```
Final comprehensive state with all analysis complete.

---

### Phase 10: Speech Synthesis (Optional)
**Goal:** Analyze TMS5220 speech commands

**Load Previous State:**
1. `close_file()`
2. `open_file("/tmp/gauntlet-soundrom-reveng/soundrom.bin")`
3. `run_command("Po gauntlet_sound_phase_9")`
4. Verify complete documentation review done

1. Find TMS5220 writes: `run_command("/x 8d3018")` - STA 0x1830
2. Analyze simple speech command (0x4A "ONE"): `decompile_function("<cmd_0x4A_handler>")`
3. Identify LPC speech data format
4. Map speech phrase data tables
5. Analyze speech status checking (bit 5 of 0x1030)
6. Document speech playback control flow

**Outputs:**
- Speech command handler mapping
- Speech data locations
- TMS5220 control protocol
- Named speech functions
- Update REPORT.md with speech analysis and wait for approval

**Save State:**
```
run_command("Ps gauntlet_sound_phase_10")
```
Complete analysis including optional speech synthesis.

---

## Critical Files to Modify

**None** - This is a read-only analysis task using radare2 MCP tools.

## Critical Files to Reference

- `/tmp/gauntlet-soundrom-reveng/soundrom.bin` - The ROM binary
- `/tmp/gauntlet-soundrom-reveng/operation.txt` - Hardware memory map
- `/tmp/gauntlet-soundrom-reveng/POKEY.md` - POKEY register reference
- `/tmp/gauntlet-soundrom-reveng/YM2151.md` - YM2151 register reference
- `/tmp/gauntlet-soundrom-reveng/soundcmds.csv` - Sound command reference

## Verification & Testing

**After each phase:**
1. Cross-reference findings with hardware documentation (POKEY.md, YM2151.md, operation.txt)
2. Check that identified functions have clear entry/exit points (JSR/RTS)
3. Ensure hardware register accesses align with documented memory map

**Final verification:**
1. All 214 sound commands (0x00-0xD5) mapped to handlers
2. All hardware registers (0x1000-0x1830 range) have xrefs documented
3. Reset vector flow traced from 0x4187 through initialization to main loop
4. Interrupt vectors (NMI/IRQ) handlers identified and documented
5. Major data tables located and formats specified
6. Function count matches ~130 unique JSR targets
7. Can trace complete flow: Reset → Init → Main Loop → Command Read → Dispatch → Handler → Hardware Write

**Success criteria:**
- Complete code structure map with named functions
- Command dispatch table fully documented
- All sound chip interaction patterns understood
- Data table catalog with formats
- Initialization sequence documented
- Ready to implement emulator or write detailed analysis report

## Execution Notes

**Raw ROM Dump Handling:**
- **CRITICAL**: Must manually map ROM to CPU address space (0x4000-0xFFFF) using `om` command
- File offset 0x0000 maps to CPU address 0x4000
- Interrupt vectors at physical ROM end (0xBFFA-0xBFFF) = CPU 0xFFFA-0xFFFF
- Always use CPU addresses in commands, not file offsets
- Verify mapping with `om` before any analysis

**Manual Function Definition Required:**
- 6502 architecture in radare2 has poor auto-analysis for hand-written code
- After finding JSR targets, must manually define with `af @ <address>`
- Start with interrupt vectors, then top 50 most-called functions
- Verify function boundaries with `pdf @ <address>` - look for RTS at end
- Use `afu <address>` to fix incorrect boundaries
- **Many false starts expected** - hand-written code has irregular structure

**Hand-written Assembly Challenges:**
- **Code/data interleaving**: Tables, strings, jump targets mixed with code
  - RTS may not mean end of function if followed by data
  - Use context (xrefs, surrounding code) to distinguish
- **Shared code paths**: Functions may jump into middle of other functions
  - Multiple entry points to same code block
  - Fall-through between functions (optimization)
- **Custom calling conventions**: May not follow standard 6502 patterns
  - Parameters in zero-page, not stack
  - Return values in registers or zero-page
  - May use self-modifying code for "variables"
- **Optimization tricks**:
  - Unrolled loops (manual repetition vs DEX/BNE)
  - Page-aligned tables for performance
  - Clever use of processor flags (BIT to test memory bits)
  - Branch target reuse (same label for multiple conditions)

**Efficient Analysis Strategy:**
1. **Name functions immediately** as identified - don't defer to later phases
2. **Start with simple, isolated functions** (e.g., hardware register writes)
3. Analyze one complete simple command handler (e.g., 0x0D) to understand patterns
4. Use that knowledge to rapidly analyze similar commands
5. Group commands by subsystem (SFX/Music/Speech) for focused analysis
6. **Document unusual patterns** when found (for future reference)
7. **Update REPORT.md at end of each phase** with findings and wait for approval

**Common 6502 Hand-written Patterns:**
- **Timing delays**: `DEX; BNE label` (empty countdown loops)
  - Often tuned to specific cycle counts for hardware
- **Zero-page scratch space**: Heavy reuse across functions
  - Same memory locations mean different things in different contexts
- **Indirect addressing**: `JMP (addr)` for computed jumps
  - Jump tables, command dispatch
- **Hardware register access**: `STA $1800` (absolute addressing to I/O)
  - Direct memory-mapped I/O, no abstraction
- **Self-modifying code**: `STA instruction+1` to change operands
  - Used as "variables" or function parameters
- **Page boundary tricks**: Using page crossing for timing or addressing
  - Tables at 0xnn00 boundaries for efficiency
- **Bit manipulation**: `BIT $addr` to test without affecting A register
  - Check hardware status bits

**Estimated Time:**
- Phases 1-4: 3-4 hours (critical foundation)
- Phases 5-7: 4-5 hours (core sound system analysis)
- Phases 8-9: 2-3 hours (documentation)
- Phase 10: 1-2 hours (optional speech analysis)
- **Total: 10-14 hours for complete analysis**
