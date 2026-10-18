# Ostrich for Static Hermes

All 12 standard JavaScript benchmarks from
[`Sable/Ostrich`](https://github.com/Sable/Ostrich/tree/dd06ca4340ecdbc0a795274d826cb5c034a2b9fe),
pinned at `dd06ca4340ecdbc0a795274d826cb5c034a2b9fe`.
Each file is a standalone program: no browser, Node.js, npm packages, filesystem
reads, or runtime downloads are needed. The original TypedArrays and numerical
kernels are retained.

## Running

Use the existing `bench.py` for performance measurements. From the repository
root, for example, compare HBC and Static Hermes across all 12 entries:

```sh
python3 benchmarks/speculative/bench.py \
  --only ostrich \
  --variant hbc hbc /path/to/hermes \
  --variant sh sh /path/to/shermes \
  --schedule anchor-pairs --anchor hbc --cycles 5 \
  --json /tmp/ostrich-hbc-sh.json
```

Use `--only ostrich/nqueens` to select one entry. Other engine variants and
schedules work as usual. The annotation A/B mode (`-a VERSION`) additionally
requires matching files under `annotations/VERSION/ostrich/`; annotations are
not included in this migration.

Each `.js` is also independently compilable:

```sh
CC=clang /path/to/shermes -O -fstatic-builtins \
  benchmarks/speculative/suites/ostrich/nqueens.js -o /tmp/ostrich-nqueens
/tmp/ostrich-nqueens
```

Each entry prints exactly one `Time: <milliseconds>` line consumed by
`bench.py`. This is the upstream kernel timer converted from seconds to
milliseconds; input generation and compilation are excluded. LavaMD retains
the upstream force-check time within its timer. Other diagnostic output is
retained; the SRAD diagnostic uses `Kernel time:` so it cannot be mistaken for
the final `Time:` line.

## Optional migration checks

`run_ostrich.py` is a separate execution checker used to validate this import.
It is not required by the benchmark files or by `bench.py`, and does not perform
the repeated, interleaved performance measurements of `bench.py`.

For example, check the execution budget or run smaller smoke inputs:

```sh
python3 benchmarks/speculative/run_ostrich.py --max-seconds 2
python3 benchmarks/speculative/run_ostrich.py --smoke --json /tmp/ostrich-smoke.json
```

Use `--only bfs` to select one entry, `--build-dir /tmp/ostrich-build` to retain
binaries and logs, or `--timeout 1200` for a slower machine. Without `--shermes`,
the runner uses `shermes` on PATH, then the sibling `static-build-release` build.
Default inputs are sized for execution below two seconds per entry on the local
SH release build, including input generation and result checks. Compilation is
excluded. The runner records both kernel time and execution wall time; use
`--max-seconds 2` to check that execution budget on your machine.

To reproduce the original, much larger upstream workloads:

```sh
python3 benchmarks/speculative/run_ostrich.py --shermes /path/to/shermes --upstream
```

## Workloads

The upstream makefiles' **js** target arguments are retained as
`upstream_arguments` in the manifest and selected with `--upstream`. The
experimental `lud_typed.js` is not selected by that target and is not imported.

| Entry | Default arguments | Smoke arguments |
| --- | --- | --- |
| backprop | 131,072 input elements | 4,096 |
| bfs | 100,000 nodes | 10,000 |
| crc | 128 pages, 65,536 bytes/page, 6 repeats | same data, 1 repeat |
| fft | exponent 8 (256 × 256) | exponent 5 (32 × 32) |
| hmm | vary states: 64, 1,000 observations | 32 states, 1,000 observations |
| lavamd | 3 boxes per dimension | 2 |
| lud | dimension 256, with full reconstruction check | 32, with full reconstruction check |
| nqueens | 13 queens | 12 |
| nw | dimension 1,024, penalty 1 | 64, penalty 1 |
| pagerank | 1,024 pages, 10 iterations, threshold 1e-8, divisor 100,000 | 128 pages; other arguments unchanged |
| spmv | dimension 4,096, density 2,000 ppm, stddev 0.01, 100 repeats | dimension 512, 2 repeats; other arguments unchanged |
| srad | 10 iterations, lambda 1, original 502 × 458 image | 1 iteration, same image |

Files contain fixed `OSTRICH_ARGS` constants. `--smoke` and `--upstream` rewrite
these in temporary compiler inputs; benchmark files have no runtime
configuration or host shims.

## Adaptations and checks

- Browser `console.log` calls use `print()`. A local timer uses
  `performance.now()` where available, and `Date.now()` in HBC shells. It does
  not install or modify any globals.
- The seeded upstream PRNG is bundled under local names. Backprop calls it
  directly instead of assigning to `Math.random`, keeping builtins immutable
  for `-fstatic-builtins`.
- Unused Array constructor overrides for the `js-nota` variant are removed.
  SpMV retains its zero-initialized Ziggurat tables through a local helper.
- SRAD bundles the exact upstream image as hex bytes, decoded before the timer.
  This avoids a large array literal and any external data loader.
- Existing upstream-size checks remain enabled. PageRank's reference loop now
  uses the array's `.length`; SRAD and LavaMD mismatches throw errors instead
  of only logging them.
- Smaller inputs also have result checks. Backprop, BFS, LavaMD, SRAD and
  Needleman-Wunsch use references from the unmodified upstream JavaScript;
  LUD uses the original full matrix reconstruction check. PageRank validates
  ordinary and weighted sums at the smaller sizes.
- N-Queens checks total and unique counts for sizes 12, 13 and 16. FFT checks its
  DC component and Parseval's energy identity. HMM checks the known likelihood
  of the uniform model. SpMV checks ordinary and weighted output sums against
  the unmodified upstream JS under Node.js, with relative tolerance 1e-6.
- A missing result, failure status, or invalid elapsed time fails the program.

## Validation

On the local AMD EPYC 7601 with `static-build-release/bin/shermes`, Clang and
`-O -fstatic-builtins`, all 12 default workloads passed
`run_ostrich.py --max-seconds 2`. Execution wall times were 0.144–1.471 seconds,
including input generation and result checks, excluding compilation.
All 12 smoke workloads also passed. Default and smoke result snapshots match
the unmodified upstream JavaScript exactly when both are executed under
Node.js. Injected incorrect results or reference values were rejected by all
12 checks under Node.js. `--upstream --only nw` also passed, exercising original
input selection and the full upstream reference sequence checks.

## Re-importing and licenses

```sh
git clone https://github.com/Sable/Ostrich.git /tmp/ostrich-upstream
git -C /tmp/ostrich-upstream checkout dd06ca4340ecdbc0a795274d826cb5c034a2b9fe
python3 benchmarks/speculative/import_ostrich.py /tmp/ostrich-upstream
```

The importer is deterministic and requires the pinned commit. It regenerates
the 12 JavaScript files, [LICENSE](LICENSE), and
[ostrich-manifest.json](../../ostrich-manifest.json), which records source paths,
arguments, and SHA-256 hashes of upstream inputs. This README is maintained
separately. Original MIT notices, the PRNG's BSD notice, and the upstream
Ziggurat attribution are retained.
