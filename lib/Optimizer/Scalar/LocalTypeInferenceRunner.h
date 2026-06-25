/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#ifndef HERMES_LIB_OPTIMIZER_SCALAR_LOCALTYPEINFERENCERUNNER_H
#define HERMES_LIB_OPTIMIZER_SCALAR_LOCALTYPEINFERENCERUNNER_H

#include <memory>

namespace hermes {
class Function;

namespace local_type_inference {
class Impl;
} // namespace local_type_inference

/// Private driver used by the combined local type + static shape inference pass.
class LocalTypeInferenceRunner {
 public:
  explicit LocalTypeInferenceRunner(Function *F);
  ~LocalTypeInferenceRunner();

  LocalTypeInferenceRunner(const LocalTypeInferenceRunner &) = delete;
  LocalTypeInferenceRunner &operator=(const LocalTypeInferenceRunner &) =
      delete;

  void preIteration();
  bool step();
  bool interIteration();

 private:
  Function *F_;
  std::unique_ptr<local_type_inference::Impl> impl_;
};

} // namespace hermes

#endif // HERMES_LIB_OPTIMIZER_SCALAR_LOCALTYPEINFERENCERUNNER_H
