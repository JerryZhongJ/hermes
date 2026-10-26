# Ostrich for Static Hermes

This directory contains the 12 retained old benchmarks from the former
`ostrich-old/` directory, plus the imported `srad.js` benchmark. The 12 old files
are preserved byte-for-byte, including their implementations, parameters,
logging, and source locations. The duplicate `ostrich-old/` source directory
has been removed. Original copyright notices are retained.

| Retained filenames | Origin |
| --- | --- |
| `backprop`, `bfs`, `crc`, `fft`, `lavamd`, `lud`, `nqueens`, `pagerank`, `spmv` | Same-named old files |
| `bwa_hmm`, `needle` | Old filenames restored; imported `hmm` and `nw` duplicates removed |
| `lud_typed` | Old experimental LUD implementation restored |
| `srad` | Additional imported benchmark with the old harness |

The imported inputs originate from `Sable/Ostrich` commit
`dd06ca4340ecdbc0a795274d826cb5c034a2b9fe`.
[ostrich-manifest.json](../../ostrich-manifest.json) records current filenames,
entry points, fixed parameters, and validation profiles. Existing upstream
input hashes describe the original import inputs, not current source hashes.

## Harness

All 13 programs use a top-level harness without an outer IIFE:

```js
// Static Hermes benchmark runner: fixed params, timed with performance.now
var __performance = globalThis.performance ?? (globalThis.performance = {});
__performance.now ??= Date.now;
var __start = __performance.now();
runSRAD( 10, 1 );
var __end = __performance.now();
print( "Time: " + Math.round( __end - __start ) );
```

The final `Time:` measures the entire entry-point call, including input
allocation/generation, result checks, and logging inside that call. Earlier
file initialization and the final timing print are excluded. Each program
prints one final `Time: <integer milliseconds>` line.

SRAD retains its numerical kernel, embedded 502 × 458 image, fixed parameters,
and result checks. Its image is decoded during file initialization, before the
outer timer. Its `Kernel time:` diagnostic still reports the narrower internal
region. The imported `result.time` output and outer wrapper have been replaced
by the old harness; SRAD payload syntax trees and decoded input values were
checked during conversion.

The retained old files also retain their original global adaptations,
including `Math` PRNG assignments and the `Array` overrides in `needle` and
`spmv`. The former imported versions used local helpers instead. Their timings
also covered different regions, so previous kernel timings do not describe
this restored suite.

## Fixed workloads

| Benchmark | Entry-point arguments |
| --- | --- |
| backprop | `300000` |
| bfs | `200000` |
| bwa_hmm | `"n", 128` |
| crc | `128, 65536, 5` |
| fft | `9` (512 × 512) |
| lavamd | `3` |
| lud | `384` |
| lud_typed | `384` |
| needle | `2048, 1, {}` |
| nqueens | `14` |
| pagerank | `1500, 10, 1e-8, 100000` |
| spmv | `10000, 2000, 0.01, 5` |
| srad | `10, 1` |

The old implementations retain their original checks and limitations; the
extra small-input checks from the former imported versions are not present
in these restored files. SRAD retains its imported checksum.

## Running

From the repository root:

```sh
python3 benchmarks/speculative/run_ostrich.py --shermes /path/to/shermes
python3 benchmarks/speculative/run_ostrich.py --shermes /path/to/shermes \
  --smoke --json /tmp/ostrich-smoke.json
```

`--only bwa_hmm` or `--only ostrich/needle` selects one entry. `--build-dir`
retains compiler inputs, binaries, and logs. `--smoke` rewrites only the direct
entry-point call in a temporary copy using the manifest's smoke parameters.
SpMV's smoke profile uses 100 repeats to avoid rounding its time to zero.
`--upstream` selects the larger reference workloads; `lud_typed` uses the
standard LUD reference dimension because it was not a separate standard JS
target. `--max-seconds` checks an optional process execution budget. No runtime
budget is claimed for the restored default workloads.

Individual files compile directly with Static Hermes. `bench.py` also accepts
the final `Time:` lines; for example:

```sh
python3 benchmarks/speculative/bench.py --only ostrich \
  --variant hbc hbc /path/to/hermes \
  --variant sh sh /path/to/shermes \
  --schedule anchor-pairs --anchor hbc --cycles 5
```

## Annotations

Historical annotation subdirectories were renamed from `ostrich-old/` to
`ostrich/`, with JSON contents unchanged:

- `annotations/jelly-old/ostrich/`: 12 files, matching the retained old sources.
- `annotations/coverage-guided-old/ostrich/`: 11 historical candidate files;
  `bwa_hmm` has no annotation in that set.

These paths are relative to `benchmarks/speculative/`. Annotations for the
former imported versions of those benchmarks were removed from
`annotations/jelly/ostrich/` and `annotations/coverage-guided/ostrich/`.

`annotations/jelly/ostrich/srad.json` is retained separately. Its source ranges
were relocated for the top-level source, and five guards targeting removed
harness expressions were removed. All algorithm annotations and static shapes
were retained. No new annotations were fabricated for missing entries.

## Validation

The restored 13-entry suite passed compilation and execution with the sibling
Static Hermes release build (`-O -fstatic-builtins`) for both default and smoke
profiles. SRAD also compiled and ran with its relocated jelly annotation.
Its existing duplicate/unmatched guard warnings remain; comparison against the
original source and annotation found no added warning categories or counts.
Successful execution does not imply every historical guard was applied.

## Historical importer and licenses

`import_ostrich.py` retains the former 12-entry import procedure. Running it
again overwrites restored sources, recreates the imported `hmm`/`nw` names,
and restores the IIFE and kernel-timed harnesses. It does not reproduce this
legacy restoration. Formatting restored sources also changes source locations
and requires corresponding annotation updates.

Original MIT notices, PRNG BSD notices, and Ziggurat attribution remain in the
source files. The upstream MIT license is included in [LICENSE](LICENSE).
