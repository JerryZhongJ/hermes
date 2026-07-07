/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// RUN: %shermes -exec -O0 %s | %FileCheck --match-full-lines %s

// Regression test for a NULL-deref SIGSEGV in IRGen, introduced by the typed
// shape annotation plumbing (commit b234e48856).
//
// A class expression with an instance field causes IRGen to emit a synthesized
// <instance_members_initializer> function via genLegacyInstanceElementsInit.
// That function has no ESTree node, so emitFunctionPrologue is called with
// funcNode == nullptr (see ESTreeIRGen-legacy-class.cpp). tryApplyAnnotation(),
// invoked on the synthesized function's "this" parameter, used to dereference
// node without a null guard and crashed at node->getSourceRange().

const C = class {
  x = 1;
};

// CHECK: 1
print(new C().x);
