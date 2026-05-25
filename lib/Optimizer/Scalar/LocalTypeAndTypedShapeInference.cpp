/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#define DEBUG_TYPE "localtypeandtypedshapeinference"

#include "LocalTypeInferenceRunner.h"
#include "TypedShapeInferenceRunner.h"

#include "hermes/Optimizer/Scalar/LocalTypeAndTypedShapeInference.h"

#include "hermes/IR/IR.h"
#include "llvh/Support/Debug.h"

using namespace hermes;
using llvh::dbgs;

bool LocalTypeAndTypedShapeInference::runOnFunction(Function *F) {
  LLVM_DEBUG(
      dbgs() << "\nStart Local Type and Typed Shape Inference on "
             << F->getInternalName() << "\n");

  LocalTypeInferenceRunner lti(F);
  TypedShapeInferenceRunner tsi(F);

  // Initialize both sides.
  lti.preIteration();
  tsi.preIteration();

  // Phase 1: merged fixed-point loop.
  // LTI and TSI iterate alternately until both converge.
  bool changed;
  do {
    changed = false;
    changed |= lti.step();
    changed |= tsi.step();
  } while (changed);

  // Phase 2: if LTI's return type was reset from NoType, re-converge.
  changed = lti.interIteration();
  while (changed) {
    changed = false;
    changed |= lti.step();
    changed |= tsi.step();
  }

  return true;
}

Pass *hermes::createLocalTypeAndTypedShapeInference() {
  return new LocalTypeAndTypedShapeInference();
}

#undef DEBUG_TYPE
