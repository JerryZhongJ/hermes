/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#ifndef HERMES_OPTIMIZER_SCALAR_REMOVEUSELESSSPECULATIVEGUARDS_H
#define HERMES_OPTIMIZER_SCALAR_REMOVEUSELESSSPECULATIVEGUARDS_H

#include "hermes/IR/IR.h"
#include "hermes/Optimizer/PassManager/Pass.h"

namespace hermes {

/// Removes speculative guard / try-set instructions whose result is consumed by
/// no useful downstream instruction, leaving only their runtime-check overhead.
///
/// - Shape guard (HasStaticShapeInst, annotationId >= 0): dropped unless the
///   guarded object reaches a useful shape consumer (PrLoad/PrStore, or a
///   Load/StoreProperty/HasStaticShape with a non-Any objOperandShape).
/// - Number type guard (TypeOfIsInst, annotationId >= 0, pure number): dropped
///   unless the guarded value reaches an FXXX instruction. The use-chain is
///   additionally followed through StoreStack -> AllocStack -> LoadStack.
/// - TrySetStaticShapeInst: dropped when its shape has no non-tryset user.
///
/// Guards are replaced with LiteralTrue so the following SimplifyCFG folds the
/// deopt branch; try-set instructions (which have no uses) are erased directly.
class RemoveUselessSpeculativeGuards : public ModulePass {
 public:
  explicit RemoveUselessSpeculativeGuards()
      : ModulePass("RemoveUselessSpeculativeGuards") {}
  ~RemoveUselessSpeculativeGuards() override = default;

  bool runOnModule(Module *M) override;
};

/// Factory.
Pass *createRemoveUselessSpeculativeGuards();

} // namespace hermes

#endif // HERMES_OPTIMIZER_SCALAR_REMOVEUSELESSSPECULATIVEGUARDS_H
