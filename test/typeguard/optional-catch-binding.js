/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// RUN: %hermes -type-annotation-file=%annotation_file -O0 %s | %FileCheck --match-full-lines %s
// RUN: %hermes -type-annotation-file=%annotation_file -O %s | %FileCheck --match-full-lines %s
// RUN: %shermes -type-annotation-file=%annotation_file -exec %s | %FileCheck --match-full-lines %s

try {
  throw Error('hello');
} catch {
  print('caught the error');
}
// CHECK: caught the error
