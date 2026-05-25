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

namespace typed_shape_inference {
class Impl;
} // namespace typed_shape_inference

/// Private driver used by the combined local type + typed shape inference pass.
class TypedShapeInferenceRunner {
 public:
  explicit TypedShapeInferenceRunner(Function *F);
  ~TypedShapeInferenceRunner();

  TypedShapeInferenceRunner(const TypedShapeInferenceRunner &) = delete;
  TypedShapeInferenceRunner &operator=(const TypedShapeInferenceRunner &) =
      delete;

  void preIteration();
  bool step();

 private:
  std::unique_ptr<typed_shape_inference::Impl> impl_;
};

} // namespace hermes

#endif // HERMES_LIB_OPTIMIZER_SCALAR_TYPEDSHAPEINFERENCERUNNER_H
