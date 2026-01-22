/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

//
//
// RUN: %shermes -type-annotation-file=%annotation_file -exec %s | %FileCheck --match-full-lines %s

// The iterator's 'next' method is not a Callable.
// However, that shouldn't matter since the array destructuring is empty
// and so 'next' should never be called.

"use strict";

var o = {
    [Symbol.iterator]:  function() {
        return {
            next: 10,
            return: function() { 
                print("return"); 
                return {done: true};
            }
        }
    }
}

function foo() {
  var [] = o;
}

foo();

// CHECK: return
