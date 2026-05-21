/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#ifndef HERMES_OPTIMIZER_SCALAR_INSERTGUARD_H
#define HERMES_OPTIMIZER_SCALAR_INSERTGUARD_H

#include "hermes/IR/IR.h"
#include "hermes/Optimizer/PassManager/Pass.h"

namespace hermes {

/// InsertGuard Pass - Implements speculative optimization by:
/// 1. Duplicating function instructions into speculative and general paths
/// 2. Inserting TypeGuard instructions at appropriate points (type guards)
/// 3. Inserting ShapeGuard instructions at appropriate points (shape guards)
/// 4. Fixing up PHI nodes and control flow
///
/// This pass is based on type annotations stored in Module::typeGuards_
/// and shape annotations stored in Module::shapeGuards_.
class InsertGuard : public FunctionPass {
 public:
  explicit InsertGuard() : FunctionPass("InsertGuard") {}
  ~InsertGuard() override = default;

  bool runOnFunction(Function *F) override;
};

Pass *createInsertGuard();

} // namespace hermes

#endif // HERMES_OPTIMIZER_SCALAR_INSERTGUARD_H
