/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#ifndef HERMES_LIB_OPTIMIZER_SCALAR_TYPEDSHAPEINFERENCERUNNER_H
#define HERMES_LIB_OPTIMIZER_SCALAR_TYPEDSHAPEINFERENCERUNNER_H

#include <memory>

#include "llvh/ADT/SmallVector.h"

namespace hermes {
class Function;
class Instruction;

namespace static_shape_inference {
class Impl;
} // namespace static_shape_inference

/// A polluting instruction that killed a Known shape fact during static shape
/// inference, and the object whose fact it killed.
struct ShapeKill {
  Instruction *polluting;
  Instruction *object;
};

/// Private driver used by the combined local type + static shape inference pass.
class StaticShapeInferenceRunner {
 public:
  explicit StaticShapeInferenceRunner(Function *F);
  ~StaticShapeInferenceRunner();

  StaticShapeInferenceRunner(const StaticShapeInferenceRunner &) = delete;
  StaticShapeInferenceRunner &operator=(const StaticShapeInferenceRunner &) =
      delete;

  void preIteration();
  bool step();

  /// After convergence: replay transfer and collect every Known shape fact
  /// each polluting instruction truly killed (polluter + the object whose fact
  /// died). Reuses the real dataflow (join/pollute/propagator) — precise, not
  /// approximate. annotation-dryrun maps each kill to the guard it hurt.
  llvh::SmallVector<ShapeKill, 8> collectKills();

 private:
  std::unique_ptr<static_shape_inference::Impl> impl_;
};

} // namespace hermes

#endif // HERMES_LIB_OPTIMIZER_SCALAR_TYPEDSHAPEINFERENCERUNNER_H
