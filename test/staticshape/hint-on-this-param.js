/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// A function body range no longer denotes the implicit `this` parameter.
// The body shape hint is unmatched, while the explicit parameter type hint
// still applies normally.

// RUN: %shermes -O0 -dump-ir -annotation-file=%S/hint-on-this-param.json %s 2>&1 | %FileCheck %s --match-full-lines --implicit-check-not=HasStaticShapeInst

function use(p) {
  return p;
}

// CHECK: {{.*}}hint-on-this-param.js:14:17: warning: annotation [shape guard "Vec"] unmatched: target range didn't emit annotation IR
// CHECK: function use(p: any): any
// CHECK: %{{.*}} = TypeOfIsInst (:boolean) %{{.*}}: any, typeOfIs(Number) [ann#0]
