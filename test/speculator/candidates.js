/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// RUN: %speculator -O --candidates %s | %FileCheck %s

// The --candidates mode collects shape hint candidates (an object accessed by
// .x/.y) and type hint candidates (the BinaryAdd over loaded properties).

function f(o) {
  o.x = 1;
  o.y = 2;
  return o.x + o.y;
}

// CHECK: "function":"f"
// CHECK: "name":"x"
// CHECK: "name":"y"
// CHECK: "suggestedShape":"shape_0"
// CHECK: "objectKind":"param"
// CHECK: "speculativeTypes":["number","string"]
