/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#ifndef HERMES_LIB_OPTIMIZER_SCALAR_TYPEDSHAPEINFERENCERUNNER_H
#define HERMES_LIB_OPTIMIZER_SCALAR_TYPEDSHAPEINFERENCERUNNER_H

#include <memory>

namespace hermes {
class Function;

namespace static_shape_inference {
class Impl;
} // namespace static_shape_inference

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

 private:
  std::unique_ptr<static_shape_inference::Impl> impl_;
};

} // namespace hermes

#endif // HERMES_LIB_OPTIMIZER_SCALAR_TYPEDSHAPEINFERENCERUNNER_H
