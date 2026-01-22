/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

//
//
// RUN: %shermes -type-annotation-file=%annotation_file -exec %s | %FileCheck --match-full-lines %s
// RUN: %shermes -type-annotation-file=%annotation_file -O0 -g3 -exec %s | %FileCheck --match-full-lines %s

print(1);
//CHECK: 1
debugger;
print(2);
//CHECK-NEXT: 2
debugger;
print(3);
//CHECK-NEXT: 3
