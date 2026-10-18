# Bglstone

Eleven benchmarks imported from
[`manuel-serrano/jsbench/bglstone`](https://github.com/manuel-serrano/jsbench/tree/7c8fc4e58d2a5c7980c207d302b1d1cb18308a5c/bglstone):

`almabench`, `bague`, `boyer-scm`, `earley-scm`, `leval`, `maze`, `puzzle`,
`qsort`, `sieve`, `sieve-mem`, and `traverse`.

Each `.js` is a standalone Static Hermes program, with its upstream algorithm
and original copyright notices. Default outer loop counts are calibrated for
runs below two seconds on the validation machine.

See [the migration and running instructions](../hopc-benchmarks/README.md).
