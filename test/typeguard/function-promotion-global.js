/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// RUN: %shermes -type-annotation-file=%annotation_file -O0 -exec %s | %FileCheck --match-full-lines %s
// RUN: %shermes -type-annotation-file=%annotation_file -O -exec %s | %FileCheck --match-full-lines %s

foo;
let bar = 1;
{
  function foo() {}
  function bar() {}
}

// globalThis.foo
print(typeof foo);
// CHECK:function

print(foo === globalThis.foo);
// CHECK-NEXT:true

// avoid promoting bar fn
print(typeof bar);
// CHECK-NEXT:number
