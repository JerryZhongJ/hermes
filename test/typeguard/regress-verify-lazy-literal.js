/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// RUN: %hermes -type-annotation-file=%annotation_file -lazy -Xg3 %s | %FileCheck --match-full-lines %s
// RUN: %hermes -type-annotation-file=%annotation_file -O %s | %FileCheck --match-full-lines %s
// RUN: %shermes -type-annotation-file=%annotation_file -exec %s | %FileCheck --match-full-lines %s

function main() {
  return {
    a1: 0,
    a2: 0,
    a3: 0,
    a4: 0,
    a5: 0,
    a6: 1,
    a7: 0,
  };
}
print(main().a6);
// CHECK: 1
