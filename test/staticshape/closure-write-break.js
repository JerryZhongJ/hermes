/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// RUN: %shermes -O -exec -annotation-file=%S/closure-write-break.json %s | %FileCheck %s --match-full-lines

// use() receives an object whose closure slot make() has overwritten with a
// different function. The write guard degrades o's shape, so HasStaticShape
// fails and o.method() takes the slow path -> 99, not the inlined 42.

function methodFunc() {
  return 42;
}

function otherFunc() {
  return 99;
}

function make() {
  var o = {method: methodFunc};
  o.method = otherFunc;
  return o;
}

function use(o) {
  return o.method();
}

print(use(make()));

// CHECK: 99
