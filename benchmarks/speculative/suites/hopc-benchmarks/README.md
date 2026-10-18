# Hop compiler benchmarks

Imported from [`manuel-serrano/jsbench`](https://github.com/manuel-serrano/jsbench)
at commit `7c8fc4e58d2a5c7980c207d302b1d1cb18308a5c`.
[hopc-manifest.json](../../hopc-manifest.json) records each entry's upstream path.

The migration contains all 11 `bglstone/*.js` entries in the adjacent
`bglstone/` directory. This directory merges all 16 `other/*.js` entries and
the `realworld/js-beautify` application into 17 standalone entries:

| Upstream | Entries |
| --- | --- |
| `other/` | `basic`, `box2d`, `jpeg`, `js-of-ocaml`, `marked`, `minimatch`, `minimist`, `moment`, `moment-full`, `navier-stokes`, `qrcode`, `rho`, `rho-simple`, `uuid`, `uuid-tarray`, `z80` |
| `realworld/js-beautify/` | `js-beautify` |

## Running

From `benchmarks/speculative/`, run every entry without annotations:

```sh
python3 run_hopc.py --shermes /path/to/shermes
```

Run shorter workloads with Static Hermes:

```sh
python3 run_hopc.py --shermes /path/to/shermes --smoke \
  --json /tmp/hopc-smoke.json
```

Use `--only bglstone` or `--only hopc-benchmarks/minimatch` to select entries.
`--build-dir /tmp/hopc-build` retains binaries and compiler inputs for
inspection. The runner uses `-O -fstatic-builtins` and fixes
`TZ=UTC` and `LC_ALL=C` for date tests. This is an execution check, not a
statistical performance comparison.

Individual entries also compile directly:

```sh
shermes -O -fstatic-builtins suites/hopc-benchmarks/minimatch.js -o /tmp/minimatch
TZ=UTC /tmp/minimatch
```

Each program prints exactly one `Time: <milliseconds>` line on completion,
compatible with `bench.py`'s timing parser. Default loop counts are calibrated
for runs below two seconds on the validation machine, usually around one
second. `bench.py` additionally requires corresponding
annotation files for its A/B discovery; this migration does not fabricate
annotations.

Each program contains a fixed `const N`; `import_hopc.py` records the calibrated
counts in `DEFAULT_ITERATIONS` and `hopc-manifest.json` records them per entry.
`--smoke` rewrites that constant in temporary compiler inputs, using the reduced
counts in `hopc-manifest.json`; the benchmark files have no runtime workload
switch or argument validation. The reduced Navier–Stokes workload retains 15
frames to exercise its checksum. The default workloads preserve the same
algorithms, inputs, and checks while changing only the outer loop count.

## Adaptations

- Entries target Static Hermes directly, using `print()` and
  `performance.now()`. The shared harness only records the start/end time and
  prints `Time:`. There are no simulated
  `process`, `global`, or `console` objects, output normalization, or runtime
  detection/fallbacks in the harness.
- Upstream command-line workload expressions use calibrated fixed loop counts.
  Logging calls use `print`; aborts throw errors. Moment debug flags
  are disabled directly. Only Maze buffers partial lines to preserve its output.
- js_of_ocaml uses `globalThis`, its existing in-memory filesystem, and direct
  `print` calls. Its unused Node filesystem backend is removed. No runtime npm
  installation or external resources are required.
- Box2D directly calls setup, the physics loop, and teardown. The unused Octane
  registration interfaces are removed.
- Navier–Stokes initializes once before its frame loop and tears down afterward.
  The upstream driver initialized on every frame, breaking the existing
  frame-15 checksum. The checksum remains enabled.
- UUID's typed-array variant checks `Uint8Array` instead of the unavailable
  Node `Buffer` class. Minimatch mismatches throw instead of only printing a
  message. Other upstream checks are retained, including their original limits.
- js-beautify bundles its standalone 1.8.9 library and the original `test.js`
  input as a string. It formats that same input using the original options;
  filesystem loading and the callback wrapper are replaced by a synchronous
  loop. The bundled formatter is accessed directly, without AMD/CommonJS/browser
  export detection. The input is data, so its Hop-specific syntax is not executed.
- Non-UTF-8 upstream files are decoded as Latin-1 and stored as UTF-8.

The timer covers JavaScript initialization, workload execution, and workload
output. It excludes compilation and the final timing print.

## Validation

Timing measurements for the calibrated default workloads are recorded in
[`hopc-timings.json`](../../hopc-timings.json), including loop counts and source
hashes. They use Static Hermes `-O -fstatic-builtins` and exclude compilation.
Execution time varies by CPU and system load; two seconds is the calibration
target, not a portable timeout guarantee. Navier–Stokes still executes its
frame-15 checksum. The existing `bench.py` timing parser is compatible with the
`Time:` output.

## Default runtime measurements

Measured on an AMD EPYC 7601 with `-O -fstatic-builtins`, `TZ=UTC`, and
`LC_ALL=C`. Each entry ran three times after its initial compile/run check.
Times below are seconds; compilation is excluded. The maximum column includes
the initial check and three repeated program timings.

| Benchmark | Fixed N | Median (s) | Maximum (s) |
| --- | ---: | ---: | ---: |
| `bglstone/almabench` | 1 | 1.436 | 1.485 |
| `bglstone/bague` | 1 | 1.435 | 1.457 |
| `bglstone/boyer-scm` | 5 | 0.740 | 0.754 |
| `bglstone/earley-scm` | 25 | 0.703 | 0.784 |
| `bglstone/leval` | 1 | 0.837 | 0.855 |
| `bglstone/maze` | 10 | 0.726 | 0.752 |
| `bglstone/puzzle` | 2 | 0.706 | 0.719 |
| `bglstone/qsort` | 20 | 0.772 | 0.775 |
| `bglstone/sieve-mem` | 300 | 0.783 | 0.803 |
| `bglstone/sieve` | 600 | 0.789 | 0.791 |
| `bglstone/traverse` | 60 | 0.665 | 0.676 |
| `hopc-benchmarks/basic` | 1000 | 0.994 | 1.025 |
| `hopc-benchmarks/box2d` | 12 | 0.875 | 0.875 |
| `hopc-benchmarks/jpeg` | 2 | 0.981 | 0.994 |
| `hopc-benchmarks/js-of-ocaml` | 8 | 0.907 | 0.923 |
| `hopc-benchmarks/marked` | 400 | 0.668 | 0.671 |
| `hopc-benchmarks/minimatch` | 600 | 0.649 | 0.650 |
| `hopc-benchmarks/minimist` | 200 | 0.863 | 0.866 |
| `hopc-benchmarks/moment-full` | 12 | 0.679 | 0.718 |
| `hopc-benchmarks/moment` | 6 | 0.792 | 0.807 |
| `hopc-benchmarks/navier-stokes` | 20 | 0.844 | 0.861 |
| `hopc-benchmarks/qrcode` | 4 | 0.860 | 0.879 |
| `hopc-benchmarks/rho-simple` | 10000 | 0.713 | 0.729 |
| `hopc-benchmarks/rho` | 2000 | 0.823 | 0.867 |
| `hopc-benchmarks/uuid-tarray` | 1000 | 0.940 | 0.964 |
| `hopc-benchmarks/uuid` | 800 | 0.779 | 0.783 |
| `hopc-benchmarks/z80` | 5 | 0.728 | 0.768 |
| `hopc-benchmarks/js-beautify` | 10 | 0.793 | 0.796 |

All 28 entries stayed below 2 seconds. The largest measured process wall time
in the three repeated runs was 1.463 seconds. Raw samples and source hashes
are in [hopc-timings.json](../../hopc-timings.json).

## Re-importing and licenses

With a local jsbench checkout at the pinned commit:

```sh
python3 import_hopc.py /path/to/jsbench
```

The importer regenerates the 28 standalone files and their manifest, without
requiring network access. After importing, run `npm run format` from
`benchmarks/speculative/` to restore the layout below 200 columns; see
[FORMATTING.md](../../FORMATTING.md). Original copyright and license notices are retained
inside the payloads. The inputs come from multiple projects and retain their
respective licenses; in particular, `z80.js` is GPL-3.0-or-later (the GPLv3 text
is provided in `Z80-COPYING.txt`), while the bundled js-beautify library is MIT.
