/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#define DEBUG_TYPE "pinclosureshapeguards"

#include "hermes/IR/IR.h"
#include "hermes/IR/Instrs.h"
#include "hermes/Optimizer/PassManager/Pass.h"
#include "hermes/Optimizer/Scalar/SpeculativeGuardUtils.h"

namespace hermes {

Pass *createPinClosureShapeGuards() {
  // A PrLoad over a closure slot (targetFunc set) drives inlining of its call.
  // Inlining erases the call; DCE then drops the PrLoad (readHeap+idempotent),
  // so RemoveUselessSpeculativeGuards would delete the now-consumerless shape
  // guard and make the inline unconditional. Pin such guards first.
  //
  // The guard's object sits upstream of the PrLoad, possibly several
  // Mov/Phi/stack relays away. Walk forward from the guard's argument toward
  // its consumers — the direction RemoveUselessSpeculativeGuards uses — because
  // walking from the PrLoad would never reach back to an upstream guard.
  class PinClosureShapeGuards : public ModulePass {
   public:
    explicit PinClosureShapeGuards() : ModulePass("PinClosureShapeGuards") {}
    ~PinClosureShapeGuards() override = default;

    bool runOnModule(Module *M) override {
      bool changed = false;
      for (Function &F : *M) {
        for (BasicBlock &BB : F) {
          for (Instruction &I : BB) {
            auto *HTS = llvh::dyn_cast<HasStaticShapeInst>(&I);
            // Only shape guards inserted by InsertGuard carry an annotation id.
            if (!HTS || HTS->getAnnotationId() < 0 || HTS->isPinned())
              continue;
            bool drivesClosureInline = false;
            walkReachableConsumers(HTS->getArgument(), [&](Instruction *U) {
              auto *prLoad = llvh::dyn_cast<PrLoadInst>(U);
              if (prLoad && prLoad->getTargetFunc())
                drivesClosureInline = true;
            });
            if (drivesClosureInline) {
              HTS->setPinned(true);
              changed = true;
            }
          }
        }
      }
      return changed;
    }
  };

  return new PinClosureShapeGuards();
}

} // namespace hermes
