/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// Minimal repro: when a `this` shape hint AND a parameter type hint are both
// present on a function, the parameter stays pinned to the scope frame
// (StoreFrame/LoadFrame) instead of being promoted to a stack slot / register.
// Either hint alone does not trigger it; the two must coexist.
// Expected CHECK lines to be filled in later.

// RUN: %shermes -O0 -dump-ir -annotation-file=%S/hint-on-this-param.json %s
// RUN: %shermes -O -dump-lir -annotation-file=%S/hint-on-this-param.json %s

function Vec(x) {
  this.x = x;
}
Vec.prototype.mul = function(p) {
  if (p === undefined) p = 0;
  this.x *= p;
};
new Vec(1).mul(3);
