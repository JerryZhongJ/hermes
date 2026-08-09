/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// RUN: %shermes -O -dump-ir -annotation-file=%S/unmatched-after-warning.json %s 2>&1 | %FileCheck %s --implicit-check-not="warning:"

// Legacy "bind after"/"guard after" fields are rejected and the whole
// annotation is skipped instead of silently changing to immediate placement.
// The target itself remains a valid object expression.

function make() {
  var o = {x: 1};
  return o.x;
}
print(make());

// CHECK: warning: shape guard at 15:11: legacy 'guard after' is unsupported; annotation skipped
// CHECK: warning: shape binding at 15:11: legacy 'bind after' is unsupported; annotation skipped
