/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#ifndef HERMES_SPECULATOR_SPECULATOR_H
#define HERMES_SPECULATOR_SPECULATOR_H

#include "hermes/IR/IR.h"

#include "llvh/ADT/SmallVector.h"

#include <vector>

namespace hermes {

class Speculator {
 public:
  struct SpeculativeOptimization {
    llvh::SmallVector<Instruction *, 4> inputs;
    llvh::SmallVector<Type, 4> speculativeTypes;
    llvh::SmallVector<Instruction *, 8> optimizationSites;
  };

  explicit Speculator(Function *F) : F_(F) {}

  std::vector<SpeculativeOptimization> run();

 private:
  Function *F_;
  llvh::SmallVector<Instruction *, 16> inputs_;
};

} // namespace hermes

#endif // HERMES_SPECULATOR_SPECULATOR_H
