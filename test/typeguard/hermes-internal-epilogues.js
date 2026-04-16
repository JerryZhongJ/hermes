/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// RUN: %hermes -type-annotation-file=%annotation_file -emit-binary -out=%t -O -target=HBC %s && echo "secret" >> %t && %hermes -type-annotation-file=%annotation_file -b %t | %FileCheck --match-full-lines %s

eps = HermesInternal.getEpilogues();
print(eps.length);
// CHECK:1
print(eps[0]);
// CHECK-NEXT:115,101,99,114,101,116,10
