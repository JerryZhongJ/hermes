/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#define DEBUG_TYPE "striptypeassert"

#include "hermes/Optimizer/Scalar/StripTypeAssert.h"

#include "hermes/IR/CFG.h"
#include "hermes/IR/IRBuilder.h"
#include "hermes/IR/Instrs.h"
#include "hermes/Support/Statistic.h"

#include "llvh/Support/Debug.h"

using namespace hermes;
using llvh::dbgs;

STATISTIC(NumStripped, "Number of TypeAssert instructions stripped");

bool StripTypeAssert::runOnFunction(Function *F) {
  bool changed = false;
  IRBuilder::InstructionDestroyer destroyer;

  LLVM_DEBUG(
      dbgs() << "StripTypeAssert: processing function "
             << F->getInternalName() << "\n");

  // Iterate over all basic blocks
  for (auto &BB : *F) {
    // Iterate over all instructions
    for (auto it = BB.begin(), e = BB.end(); it != e; /* manual */) {
      Instruction *I = &*it;
      ++it;  // Advance before potential erasure

      if (auto *TAI = llvh::dyn_cast<TypeAssertInst>(I)) {
        Value *input = TAI->getSingleOperand();

        LLVM_DEBUG(
            dbgs() << "  Stripping TypeAssertInst: "
                   << TAI->getType() << "\n");

        // Replace all uses with input
        TAI->replaceAllUsesWith(input);
        destroyer.add(TAI);

        ++NumStripped;
        changed = true;
      }
    }
  }

  return changed;
}

Pass *hermes::createStripTypeAssert() {
  return new StripTypeAssert();
}

#undef DEBUG_TYPE
