/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// RUN: %shermes -type-annotation-file=%annotation_file -O0 -exec %s | %FileCheck --match-full-lines %s
// RUN: %shermes -type-annotation-file=%annotation_file -O -exec %s | %FileCheck --match-full-lines %s

function foo() {
    // Should access global property.
    print(f);
    {
        let f;
        {
            // 'function' should not be promoted past the 'let'.
            function f() {}
        }
    }
}

globalThis.f = 1;
foo();
// CHECK: 1
