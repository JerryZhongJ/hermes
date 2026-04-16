/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// RUN: %hermes -type-annotation-file=%annotation_file %s | %FileCheck %s --match-full-lines
// RUN: %hermes -type-annotation-file=%annotation_file -O %s | %FileCheck %s --match-full-lines
// RUN: %hermesc -type-annotation-file=%annotation_file %s -emit-binary -out %t.hbc && %hermes -type-annotation-file=%annotation_file %t.hbc | %FileCheck %s --match-full-lines
// RUN: %shermes -type-annotation-file=%annotation_file -exec %s | %FileCheck %s --match-full-lines

print('computed destructuring');
// CHECK-LABEL: computed destructuring

var {['a']: b} = {a: 3};
print(b);
// CHECK-NEXT: 3

var {['a']: b, ...rest} = {a: 30, x:100, y:101};
print(Object.getOwnPropertyNames(rest));
// CHECK-NEXT: x,y
print(b, rest.x, rest.y);
// CHECK-NEXT: 30 100 101

function foo() {
  return 'asdf';
}

var {[foo()]: b, ...rest} = {asdf: 242, x: 9778, y: 37};
print(Object.getOwnPropertyNames(rest));
// CHECK-NEXT: x,y
print(b, rest.x, rest.y);
// CHECK-NEXT: 242 9778 37

try {
  var {} = undefined;
} catch(e) {
  print('caught', e.name);
}
// CHECK-NEXT: caught TypeError

try {
  var {...rest} = undefined;
} catch(e) {
  print('caught', e.name);
}
// CHECK-NEXT: caught TypeError
