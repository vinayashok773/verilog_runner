# PulseLab Local

## Mac setup

1. Extract this ZIP to a folder on your Mac.
2. With Homebrew installed, run once: `brew install python icarus-verilog`.
3. Double-click `Start.command`. A local browser tab opens. Leave Terminal open while using it.
4. If Finder won't run the launcher, open Terminal, type `bash ` (with a space), drag `Start.command` onto Terminal, and press Enter.

No ChatGPT account, subscription, API key or internet is required after setup. The app uses real locally installed Icarus Verilog. No hosted simulator iframe is involved. Your source stays on your computer.

## Workflow

Paste or import sources, select the top module, and Analyze. Configure each input as constant, clock, reset, incrementing counter or timed sequence. Click Run. Select signals in the waveform panel; zoom, change radix, or download the VCD for GTKWave. Save project saves all source files, stimulus settings and testbench to JSON. Changes are not automatically saved: use Save project before closing.

Values are decimal unless prefixed: `0xFF`, `8'hFF`, `8'b1010`. Input sequence times are absolute ns, e.g. `0:0, 12:1, 22:0`. Reset starts at Initial and inverts at Release time; use Initial=0 for active-low resets. Each clock has an independent period. Avoid driving data/reset at the sampling edge unless deliberately testing a race.

Automatic mode rebuilds the testbench on every Run, stops at the requested duration and exposes the generated source. It does not check expected outputs or exhaustively verify your circuit. Use custom testbench mode for self-checking tests and protocol transactions. In custom mode your testbench controls termination; Duration does not override it. Include `$dumpfile("wave.vcd"); $dumpvars(0,tb);` with your actual testbench module name.

## Supported and bounded

- Multi-module / multi-file .v and .sv designs; include files and memory data files in the same flat directory.
- ANSI and non-ANSI scalar and packed-vector input/output ports, signed vectors, numeric parameters, common parameter expressions (including `$clog2`), multiple clocks.
- Custom testbenches for top-level inout, unpacked-array ports, complex types, advanced parameter declarations and compiler-supported SystemVerilog features.
- Icarus itself supports only part of SystemVerilog. Full UVM, every interface/class construct, encrypted vendor IP and FPGA implementation timing are not promised. Supply compatible simulation models for vendor primitives.
- Compiler errors are shown without inventing a waveform. Automatic parsing deliberately rejects unfamiliar port declarations instead of guessing. Parameter type/width information is simplified into localparams; use custom mode if typed or width-sensitive parameter semantics matter.
- Run bounds: 30-second compile, 15-second simulation, 20 MB waveform, 2 MB console, 5 MB request. Huge designs may exceed these limits. Export the project/testbench for external tools if needed.
- The browser waveform viewer displays scalar, vector, real and X/Z transitions. It is a basic viewer; use exported VCD in GTKWave for advanced inspection.

## Trust and verification

Run only trusted HDL. The server listens on loopback with a per-launch request token, but compiler/simulator execution is not an OS sandbox. HDL file operations run with your account's permissions. Temporary run directories are removed after each run, so export VCD and save your project when needed.

Run `python3 tests.py` for parser/generator and waveform tests. If Icarus is installed, it also runs actual compilation and behavioral checks; otherwise those are explicitly skipped.

The package was checked with Python/JavaScript syntax checks and regression tests. Actual Icarus execution could not be verified in the build environment because installing it was blocked. Browser UI interactions were not browser-tested there. Run the included tests on your Mac before relying on results.
