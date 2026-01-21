/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#ifndef HERMES_OPTIMIZER_SCALAR_INSERTTYPEGUARD_H
#define HERMES_OPTIMIZER_SCALAR_INSERTTYPEGUARD_H

#include "hermes/IR/IR.h"
#include "hermes/Optimizer/PassManager/Pass.h"

namespace hermes {

/// InsertTypeGuard Pass - Implements speculative optimization by:
/// 1. Duplicating function instructions into speculative and general paths
/// 2. Inserting TypeGuard instructions at appropriate points
/// 3. Fixing up PHI nodes and control flow
///
/// This pass is based on type annotations stored in Module::typeGuards_.
class InsertTypeGuard : public FunctionPass {
 public:
  explicit InsertTypeGuard() : FunctionPass("InsertTypeGuard") {}
  ~InsertTypeGuard() override = default;

  bool runOnFunction(Function *F) override;
};

Pass *createInsertTypeGuard();

} // namespace hermes

#endif // HERMES_OPTIMIZER_SCALAR_INSERTTYPEGUARD_H
