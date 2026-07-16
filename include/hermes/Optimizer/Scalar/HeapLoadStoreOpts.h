/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#ifndef HERMES_OPTIMIZER_SCALAR_HEAPLOADSTOREOPTS_H
#define HERMES_OPTIMIZER_SCALAR_HEAPLOADSTOREOPTS_H

#include "hermes/IR/IR.h"
#include "hermes/Optimizer/PassManager/Pass.h"

namespace hermes {

/// Eliminates redundant heap loads (PrLoad / TypedLoadParent) and forwards
/// PrStore -> PrLoad by mirroring the loaded/stored values into stack allocas.
/// Mem2Reg (which runs immediately after) then promotes those allocas to SSA,
/// folding the redundant loads away.
///
/// This is the heap analogue of FrameLoadStoreOpts, but stricter: a heap write
/// has an arbitrary target (any object/property, the prototype chain), so
/// unlike frame opts -- which can keep non-captured variables valid across a
/// call -- any instruction that may write the heap or execute JS invalidates
/// *all* available loads.
class HeapLoadStoreOpts : public FunctionPass {
 public:
  explicit HeapLoadStoreOpts() : FunctionPass("HeapLoadStoreOpts") {}
  ~HeapLoadStoreOpts() override = default;

  bool runOnFunction(Function *F) override;
};

Pass *createHeapLoadStoreOpts();

} // namespace hermes

#endif // HERMES_OPTIMIZER_SCALAR_HEAPLOADSTOREOPTS_H
