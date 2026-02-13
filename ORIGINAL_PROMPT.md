You have access to the radare2 MCP server.

Your job is to use radare2 to analyze the provided 6502 arcade ROM file, which runs the sound coprocessor for the "Gauntlet" arcade game. The ROM is a 48kB binary file, "/tmp/gauntlet-soundrom-reveng/soundrom.bin", which should be mapped contiguously at 0x4000 - 0xFFFF in the 6502's address space.

We are interested in knowing:
* The overall structure of the code: where the main loop is, where it dispatches commands, and how it communicates with each individual sound chip
* The code flow for how commands are actually dispatched
* The locations of the data tables for the various sound chip functions
* The format of the data tables, and how they are used to actually drive each sound chip
* How the sound chips are actually manipulated by the code
* How the sound CPU initializes itself and the sound chips on startup
* Any other information that seems useful for gaining a thorough understanding how the sound coprosessor works.

INPUTS (local files):
The following local files are available with information about the ROM and hardware:

* ROM (raw): /tmp/gauntlet-soundrom-reveng/soundrom.bin
  * Size: 48KB (0xC000)
  * Mapped into CPU address space starting at 0x4000 (so spans 0x4000–0xFFFF)
* operation.txt: includes the hardware memory map and known operation summary
* POKEY.md: POKEY chip behavior / registers
* YM2151.md: YM2151 chip behavior / registers
* soundcmds.csv: list of available sound commands


IMPORTANT 6502 FACTS YOU MUST USE:
* Interrupt vectors are stored at:
  * NMI vector at 0xFFFA–0xFFFB
  * RESET vector at 0xFFFC–0xFFFD
  * IRQ/BRK vector at 0xFFFE–0xFFFF
* Each vector is a LITTLE-ENDIAN 16-bit address. (Low byte first, then high byte.)


TOOLING RULES (r2mcp):
* Prefer r2mcp structured tools: open_file, analyze, disassemble, disassemble_function, xrefs_to,
list_functions, list_functions_tree, show_function_details, rename_function, set_comment,
list_sections, show_headers, search_string, search_bytes, hexdump.
* Use run_command only when the structured tools do not expose what you need (e.g., asm.arch/base address).
* Do NOT use shell pipes, redirection, subshells, backticks, or “!” in run_command. Assume r2mcp sanitizes or truncates those patterns.


OUTPUT DELIVERABLES:

Produce a file-like output named REPORT.md (Markdown content in your final response) containing:
A) Overview + memory map summary
B) Entry points from vectors (NMI/RESET/IRQ) with addresses
C) Reset/init sequence, with key routines and I/O writes
D) IRQ/NMI responsibilities (timers, queue service, chip update cadence)
E) Main loop / scheduler behavior
F) Sound command interface:
  * where commands arrive (addresses)
  * command format (ID + args if visible)
  * dispatch method (compare chain vs jump table)
  * mapping: soundcmds.csv command IDs → handler addresses → chip effects
G) POKEY driver behavior: init, register write API, timing
H) YM2151 driver behavior: init, register write API, polling/IRQ coupling
I) Tables/data: envelopes, instrument tables, jump tables, command tables (addresses + interpretation)
J) Appendix: function inventory (address, name, 1–2 sentence description). Name the functions in an intuitive way based on their behavior.
K) Next leads: 5–10 concrete follow-ups with addresses and what to inspect
