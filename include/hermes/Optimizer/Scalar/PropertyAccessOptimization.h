/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#ifndef HERMES_OPTIMIZER_SCALAR_PROPERTYACCESSOPTIMIZATION_H
#define HERMES_OPTIMIZER_SCALAR_PROPERTYACCESSOPTIMIZATION_H

#include "hermes/Optimizer/PassManager/Pass.h"

namespace hermes {

// 前向声明
class LoadPropertyInst;
class StorePropertyInst;

/// PropertyAccessOptimization Pass
///
/// 将 LoadPropertyInst 优化为 PrLoadInst，将 StorePropertyInst 优化为 PrStoreInst。
///
/// 优化条件：
/// 1. 对象类型必须是确定的 Object 类型
/// 2. 对象必须有 Shape 信息
/// 3. 属性必须是字面量
/// 4. 属性必须在 Shape 中定义
///
/// 基于 TypeInference 推导的精确类型，生成高效的 PrLoad/PrStore 指令。
class PropertyAccessOptimization : public FunctionPass {
 public:
  explicit PropertyAccessOptimization()
      : FunctionPass("PropertyAccessOptimization") {}
  ~PropertyAccessOptimization() override = default;

  bool runOnFunction(Function *F) override;

 private:
  /// 优化单个 LoadPropertyInst
  /// \return 如果进行了优化则返回 true
  bool optimizeLoadProperty(LoadPropertyInst *LPI);

  /// 优化单个 StorePropertyInst
  /// \return 如果进行了优化则返回 true
  bool optimizeStoreProperty(StorePropertyInst *SPI);
};

/// 创建 PropertyAccessOptimization Pass 的工厂函数
Pass *createPropertyAccessOptimization();

} // namespace hermes

#endif // HERMES_OPTIMIZER_SCALAR_PROPERTYACCESSOPTIMIZATION_H
