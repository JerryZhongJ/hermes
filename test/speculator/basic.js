/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// RUN: %speculator -O %s | %FileCheck %s

function foo(x, y) {
  let a = x + y;
  let b = x * y;
  return a < b;
}

// CHECK: "function":"foo"
// CHECK-DAG: "kind":"LoadParamInst"
// CHECK-DAG: "inLoop":false
// CHECK-DAG: "speculativeTypes":["string"]
// CHECK-DAG: "speculativeTypes":["number"]
// CHECK-DAG: "kind":"BinaryAddInst"
// CHECK-DAG: "kind":"BinaryMultiplyInst"
// CHECK-DAG: "kind":"BinaryLessThanInst"
