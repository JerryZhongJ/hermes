/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// RUN: %shermes -type-annotation-file=%annotation_file -exec --test262  %s | %FileCheck --match-full-lines %s

(function (){
   var fn = function() {
       try { x = 10 } catch (e) { print(e); }
   }
   fn();
   // CHECK: ReferenceError: accessing an uninitialized variable
   const x = 1;
   fn();
   // CHECK-NEXT: TypeError: assignment to constant variable 'x'
})();
