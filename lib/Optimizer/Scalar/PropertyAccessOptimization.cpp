/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#include "hermes/Optimizer/Scalar/PropertyAccessOptimization.h"

#include "hermes/IR/IR.h"
#include "hermes/IR/IRBuilder.h"
#include "hermes/IR/Instrs.h"

namespace hermes {

bool PropertyAccessOptimization::runOnFunction(Function *F) {
  bool changed = false;

  // 收集需要优化的指令（避免迭代时修改）
  llvh::SmallVector<LoadPropertyInst *, 16> loadInsts;
  llvh::SmallVector<StorePropertyInst *, 16> storeInsts;

  for (BasicBlock &BB : *F) {
    for (Instruction &I : BB) {
      if (auto *LPI = llvh::dyn_cast<LoadPropertyInst>(&I)) {
        loadInsts.push_back(LPI);
      } else if (auto *SPI = llvh::dyn_cast<StorePropertyInst>(&I)) {
        storeInsts.push_back(SPI);
      }
    }
  }

  // 优化 LoadPropertyInst
  for (auto *LPI : loadInsts) {
    changed |= optimizeLoadProperty(LPI);
  }

  // 优化 StorePropertyInst
  for (auto *SPI : storeInsts) {
    changed |= optimizeStoreProperty(SPI);
  }

  return changed;
}

bool PropertyAccessOptimization::optimizeLoadProperty(LoadPropertyInst *LPI) {
  Value *obj = LPI->getObject();
  Type objType = obj->getType();

  // 前提条件 1：类型必须是确定的 Object
  if (!objType.isObjectType()) {
    return false;
  }

  // 前提条件 2：必须有 Shape 信息
  Module *M = LPI->getParent()->getParent()->getParent();
  const ShapeDescriptor *shape = M->getValueShape(obj);
  if (!shape) {
    return false;
  }

  // 前提条件 3：属性必须是字面量
  auto *propLit = llvh::dyn_cast<LiteralString>(LPI->getProperty());
  if (!propLit) {
    return false;
  }

  Identifier propName = propLit->getValue();

  // 在 Shape 中查找槽位
  for (const auto &prop : shape->properties) {
    if (prop.name == propName) {
      // 创建 PrLoadInst 替换
      IRBuilder builder(LPI->getParent()->getParent());
      builder.setInsertionPoint(LPI);

      auto *prLoad = builder.createPrLoadInst(
          obj,
          prop.slot,  // 直接使用 slot 值（size_t）
          propLit,
          LPI->getType()  // 使用 TypeInference 推导的精确类型
      );

      LPI->replaceAllUsesWith(prLoad);
      LPI->eraseFromParent();
      return true;
    }
  }

  return false;
}

bool PropertyAccessOptimization::optimizeStoreProperty(
    StorePropertyInst *SPI) {
  Value *obj = SPI->getObject();
  Type objType = obj->getType();

  // 前提条件 1：类型必须是确定的 Object
  if (!objType.isObjectType()) {
    return false;
  }

  // 前提条件 2：必须有 Shape 信息
  Module *M = SPI->getParent()->getParent()->getParent();
  const ShapeDescriptor *shape = M->getValueShape(obj);
  if (!shape) {
    return false;
  }

  // 前提条件 3：属性必须是字面量
  auto *propLit = llvh::dyn_cast<LiteralString>(SPI->getProperty());
  if (!propLit) {
    return false;
  }

  Identifier propName = propLit->getValue();

  // 在 Shape 中查找槽位
  for (const auto &prop : shape->properties) {
    if (prop.name == propName) {
      // 创建 PrStoreInst 替换
      IRBuilder builder(SPI->getParent()->getParent());
      builder.setInsertionPoint(SPI);

      auto *prStore = builder.createPrStoreInst(
          SPI->getStoredValue(),
          obj,
          prop.slot,  // 直接使用 slot 值（size_t）
          propLit,
          false  // nonPointer: 保守起见设为 false
      );

      // Store 指令没有返回值
      prStore->setType(Type::createNoType());

      SPI->eraseFromParent();
      return true;
    }
  }

  return false;
}

Pass *createPropertyAccessOptimization() {
  return new PropertyAccessOptimization();
}

} // namespace hermes
