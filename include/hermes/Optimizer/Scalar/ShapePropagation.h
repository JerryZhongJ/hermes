/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#ifndef HERMES_OPTIMIZER_SCALAR_SHAPEPROPAGATION_H
#define HERMES_OPTIMIZER_SCALAR_SHAPEPROPAGATION_H

#include "hermes/Optimizer/PassManager/Pass.h"

namespace hermes {

/// ShapePropagation Pass
///
/// 负责在 IR 中传播 Shape 信息，独立于类型推导。
///
/// 传播规则：
/// - MovInst: 直接继承源操作数的 Shape
/// - PhiInst: 保守交集策略（所有入口必须相同）
///
/// 采用迭代不动点算法，直到不再有变化为止。
class ShapePropagation : public FunctionPass {
 public:
  explicit ShapePropagation() : FunctionPass("ShapePropagation") {}
  ~ShapePropagation() override = default;

  bool runOnFunction(Function *F) override;

 private:
  /// 传播单个指令的 Shape 信息
  /// \return 如果 Shape 发生变化则返回 true
  bool propagateShape(Instruction *inst, Module *M);
};

/// 创建 ShapePropagation Pass 的工厂函数
Pass *createShapePropagation();

} // namespace hermes

#endif // HERMES_OPTIMIZER_SCALAR_SHAPEPROPAGATION_H
