/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// RUN: echo %S/barrier.hints.json | %speculator -O --annotate %s 2>/dev/null | %FileCheck %s

// A StoreProperty to an unshaped object p between the shape hint on o and the
// trailing o.x load invalidates o's assertion, so the load cannot specialize.
// Requires building with -DHERMES_SOURCE_RANGE_IN_IR=ON.

function f(o, p) {
  o.x = 1;
  p.y = 2;
  return o.x;
}

// CHECK: "function":"f"
// CHECK: "loadToPrLoad":0
// CHECK: "storeToPrStore":1
// CHECK: "barriers"
// CHECK: "blocker":"StorePropertyLooseInst"
// CHECK: "assertion":"LoadParamInst"
