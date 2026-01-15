/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#ifndef HERMES_OPTIMIZER_SCALAR_STRIPTYPEASSERT_H
#define HERMES_OPTIMIZER_SCALAR_STRIPTYPEASSERT_H

#include "hermes/IR/IR.h"
#include "hermes/Optimizer/PassManager/Pass.h"

namespace hermes {

/// Strips TypeAssertInst instructions from the IR.
/// Run at the end of optimization pipeline after all type-based
/// optimizations. TypeAssert are compile-time hints that don't
/// generate runtime code, but removing simplifies lowering.
class StripTypeAssert : public FunctionPass {
 public:
  explicit StripTypeAssert() : FunctionPass("StripTypeAssert") {}
  ~StripTypeAssert() override = default;

  bool runOnFunction(Function *F) override;
};

Pass *createStripTypeAssert();

} // namespace hermes

#endif // HERMES_OPTIMIZER_SCALAR_STRIPTYPEASSERT_H
