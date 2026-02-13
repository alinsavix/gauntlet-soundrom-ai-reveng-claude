# Gauntlet Sound ROM Reverse Engineering via Claude Code

## What

I (Alinsa) have been slowly reverse engineering parts of the Gauntlet II arcade game for... uhhh... a long time. I've got a pretty large chunk of the game's ROMs reverse engineered and understood at this point, but I've never been able to make much progress on the ROM for the sound coprocessor -- the code is abstract and obtuse enough that there's never been enough for me to grab onto for actually making progress.

So, as an experiment, I provided Claude Code with a copy of the Gauntlet II sound ROM, a breakdown of what I knew about its operation, a radare2 MCP for doing disassembly, and put it to work.

The results were, to put it lightly, impressive, and complete to a depth that I don't think I ever could have reached on my own. The results are also, best I can tell, actually _correct_. Correct enough that it was able to write a python command for me that was able to (among other things) create a MIDI file of the music present in the ROM!

Also, the Gauntlet II sound ROM implements a kind of non-trivial bytecode for making sounds happen! That's not that surprising, but still an impressive amount of sophistication

## Results

My original prompt is in [PROMPT.md](prompting/PROMPT.md). I provided the prompt, and the operational documentation present in the [docs](docs) directory (typed up by me, derived from my own knowledge, the schematics, and the datasheets for the various chips).

That prompt generated [PLAN.md](prompting/PLAN.md), which I used largely unchanged. There were a few minor things that needed correcting -- mostly involved with how to use `r2mcp` -- but what is provided here is largely intact.

Claude still had a few issues successfully using r2mcp, like not being able to correctly save the state, but it worked around them, using the report file to take note of all the function naming and such it created, rather than saving the r2mcp state as a way to do that. It did recover from that on its own, though!

The main work output of Claude Code is [REPORT.md](REPORT.md), which has, effectively, a running log of what it discovered for each phase of its disassembly work. This is a bit long-winded, but lets you see the process that it went through to reverse engineer things.

There were a few places where I had to correct the AI on things (or at least, point out problems), but these were surprisingly few, and required surprisingly small nudges to get it back on track. Off the top of my head, there were two real corrections I had to make:

  * I had noticed that it was flagging a couple of addresses in the I/O (hardware) memory area as being JSR destinations. Turns out it had found interesting things to disassemble by looking for a byte sequence of <JSR> <VALID ADDRESS>, and was disassembling one section of the code offset by one byte because of something that that matched the pattern, but was actually data for an instruction.
  * When it originally reverse engineered the tables for the music (the theme song in specific), and wrote the python command to be able to dump them, the results were obviously wrong (to a human that knew the song) -- 3 seconds long and just a few notes. Pointing this out made it look again, at which point it discovered that it had misunderstood how the music data chained together, and how channel management for music was done -- it thought there were 2 channels for music, when there were actually 8!

Other corrections were extremely minor, things like the way IRQs were generated (which required consulting the schematic) and other things that were fairly inconsequential (like knowing one of the memory locations it was reading was a coin counter).

After the reverse engineering work was largely complete, I had the AI summarize it in a more digestible form in [REPORT_SUMMARY.md](REPORT_SUMMARY.md), which includes the final versions of all the various information, along with flow-of-control diagrams and other information useful for understanding what is going on. Further editing could probably be done on this document to make it a bit more streamlined, but if one wanted a single document to explain the majority of the sound ROM, that would be the one to look at.

I also had Claude generate [MEMMAP.md](MEMMAP.md), just as a compact document show the short version of where everything was and what it was.

And finally, Claude generated (actually _offered_ to generate!) a python script that can dump all of the data associated with each different sound. It seems to work pretty well, and I had it add a couple of bonus feature (the `--score` flag, and the ability to generate MIDI files for the music tracks). That was created as [gauntlet_disasm.py](gauntlet_disasm.py), and has no dependencies.

## Finally

What really impressed me about this project is *just* how little hand-holding Claude Code actually took to be able to produce extremely high-quality results. Even when it got something wrong, I could give it very little information ("hey, this song should be longer") and it would do an impressive job of figuring out the specifics, even when the problem wasn't simple -- in this example case, the problem was a misunderstanding of certain fields in the data structures for the music, which required it to go back and re-analyze its work, figure out where some additional data might be stored, and then figure out how to connect the two to improve its understanding of the data structures. That's, uhh, impressive.

The only real downside? This repository represents about $50 of Claude Code API usage. That's amazingly cheap for the result (especially given how many dozens of hours I'd spent trying to accomplish the same thing, far less productively, in the past), but the number did still go up pretty quickly, and I can definitely see how it would be possible to go through hundreds of dollars of compute really quickly!

Pretty cool overall, though. I'm definitely impressed.

--A


## Appendix: ROMs

The actual sound ROMs from Gauntlet II are not included in this repository, for copyright reasons. If you want to make your own matching ROM to match with the information here, you will need:

| Part Number | Board Location | Size | sha1sum |
|-------------|----------------|------|---------|
| 136043-1120 | 16R | 16kB | 045ad571db34ef870b1bf003e77eea403204f55b |
| 136043-1119 | 16S | 32kB | 6d0d8493609974bd5a63be858b045fe4db35d8df |


\
These need to be combined together (in the order above) to create:

| File | Size | sha1sum |
|------|------|---------|
| soundrom.bin | 48kB | a9795393899fd20ce23ef98811195b9406485ed0 |
