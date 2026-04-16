/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// RUN: %hermes -type-annotation-file=%annotation_file -target=HBC -O %s | %FileCheck --match-full-lines %s
// RUN: %hermes -type-annotation-file=%annotation_file -target=HBC -O -emit-binary -out %t.hbc %s && %hermes -type-annotation-file=%annotation_file %t.hbc | %FileCheck --match-full-lines %s
// RUN: %shermes -type-annotation-file=%annotation_file -exec %s | %FileCheck --match-full-lines %s

var x = []
x[0] = 10
Object.preventExtensions(x);
print(Object.isSealed(x));
//CHECK: false
