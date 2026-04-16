/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// RUN: %hermes -type-annotation-file=%annotation_file -O -Xhermes-internal-test-methods %s | %FileCheck --match-full-lines %s
// RUN: %hermes -type-annotation-file=%annotation_file -O -emit-binary -out %t.hbc %s && %hermes -type-annotation-file=%annotation_file -Xhermes-internal-test-methods %t.hbc | %FileCheck --match-full-lines %s
// RUN: %shermes -type-annotation-file=%annotation_file -exec %s -Wx,-Xhermes-internal-test-methods | %FileCheck --match-full-lines %s
"use strict";

print("HermesInternal");
// CHECK-LABEL: HermesInternal

var desc = Object.getOwnPropertyDescriptor(this, "HermesInternal");
print(desc.enumerable, desc.writable, desc.configurable);
// CHECK-NEXT: false false false

var desc = Object.getOwnPropertyDescriptor(HermesInternal, "detachArrayBuffer");
print(desc.enumerable, desc.writable, desc.configurable);
// CHECK-NEXT: false false false

try { HermesInternal.asdf = 'asdf'; } catch (e) { print('caught', e.name); }
// CHECK-NEXT: caught TypeError
try {
  delete HermesInternal.detachArrayBuffer;
} catch (e) {
  print('caught', e.name);
}
// CHECK-NEXT: caught TypeError
