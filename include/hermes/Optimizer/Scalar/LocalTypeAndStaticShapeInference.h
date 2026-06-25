/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#ifndef HERMES_OPTIMIZER_SCALAR_LOCALTYPEANDTYPEDSHAPEINFERENCE_H
#define HERMES_OPTIMIZER_SCALAR_LOCALTYPEANDTYPEDSHAPEINFERENCE_H

#include "hermes/Optimizer/PassManager/Pass.h"

namespace hermes {

/// Merged pass combining local type inference and static shape inference into a
/// single fixed-point loop, so that type changes and shape changes can trigger
/// each other until convergence.
class LocalTypeAndStaticShapeInference : public FunctionPass {
 public:
  explicit LocalTypeAndStaticShapeInference()
      : FunctionPass("LocalTypeAndStaticShapeInference") {}
  ~LocalTypeAndStaticShapeInference() override = default;

  bool runOnFunction(Function *F) override;
};

} // namespace hermes

#endif // HERMES_OPTIMIZER_SCALAR_LOCALTYPEANDTYPEDSHAPEINFERENCE_H
