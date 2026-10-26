# Bglstone

Eleven benchmarks imported from
[`manuel-serrano/jsbench/bglstone`](https://github.com/manuel-serrano/jsbench/tree/7c8fc4e58d2a5c7980c207d302b1d1cb18308a5c/bglstone):

`almabench`, `bague`, `boyer-scm`, `earley-scm`, `leval`, `maze`, `puzzle`,
`qsort`, `sieve`, `sieve-mem`, and `traverse`.

Each `.js` retains the old `bglstone-old/` benchmark byte-for-byte,
including its implementation, fixed workload count, logging, and original
copyright notices. The duplicate `bglstone-old/` directory has been removed.
The former outer harness IIFE has been removed by restoring these old files;
library-internal IIFEs are retained.

Timing uses the old top-level harness: initialize `__performance` with a
`Date.now` fallback, record `__start` immediately before calling `main`, and
print `Time: <milliseconds>` after it returns. JavaScript initialization before
that call is outside the timed region.

See [the migration and running instructions](../hopc-benchmarks/README.md).

Matching historical annotations are in `annotations/jelly-old/bglstone/` and
`annotations/coverage-guided-old/bglstone/`, relative to `benchmarks/speculative/`.
