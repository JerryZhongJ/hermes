/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// RUN: %shermes -O -dump-ir -annotation-file=%S/unmatched-after-warning.json %s 2>&1 | %FileCheck %s --implicit-check-not="warning:"

// When a "bind after"/"guard after" range doesn't hit any AST node, the
// unmatched warning points at the after range (not the target range) and names
// it. The after ranges below intentionally miss every visited AST node.

function make() {
  var o = {x: 1};
  return o.x;
}
print(make());

// CHECK: {{.*}}unmatched-after-warning.js:15:1: warning: annotation [shape guard "X"] unmatched: 'guard after' range didn't hit a target AST node
// CHECK: {{.*}}unmatched-after-warning.js:15:1: warning: annotation [shape binding "X"] unmatched: 'bind after' range didn't hit a target AST node
