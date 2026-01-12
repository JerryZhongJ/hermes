/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#include "hermes/Optimizer/Scalar/ShapePropagation.h"

#include "hermes/IR/IR.h"
#include "hermes/IR/Instrs.h"

namespace hermes {

bool ShapePropagation::runOnFunction(Function *F) {
  bool changed = false;
  Module *M = F->getParent();

  // 迭代至不动点
  bool localChanged = false;
  do {
    localChanged = false;

    for (BasicBlock &BB : *F) {
      for (Instruction &I : BB) {
        localChanged |= propagateShape(&I, M);
      }
    }

    changed |= localChanged;
  } while (localChanged);

  return changed;
}

bool ShapePropagation::propagateShape(Instruction *inst, Module *M) {
  bool changed = false;

  // LoadParamInst: 从 JSDynamicParam 继承 Shape
  if (auto *loadParam = llvh::dyn_cast<LoadParamInst>(inst)) {
    Value *param = loadParam->getSingleOperand();
    if (const ShapeDescriptor *shape = M->getValueShape(param)) {
      if (!M->hasValueShape(loadParam) || M->getValueShape(loadParam) != shape) {
        M->setValueShape(loadParam, shape);
        changed = true;
      }
    }
    return changed;
  }

  // StoreFrameInst: 将值的 Shape 传播到变量
  if (auto *store = llvh::dyn_cast<StoreFrameInst>(inst)) {
    Value *storedValue = store->getValue();
    Variable *var = store->getVariable();
    if (const ShapeDescriptor *shape = M->getValueShape(storedValue)) {
      if (!M->hasValueShape(var) || M->getValueShape(var) != shape) {
        M->setValueShape(var, shape);
        changed = true;
      }
    }
    return changed;
  }

  // LoadFrameInst: 从变量继承 Shape
  if (auto *load = llvh::dyn_cast<LoadFrameInst>(inst)) {
    Variable *var = load->getLoadVariable();
    if (const ShapeDescriptor *shape = M->getValueShape(var)) {
      if (!M->hasValueShape(load) || M->getValueShape(load) != shape) {
        M->setValueShape(load, shape);
        changed = true;
      }
    }
    return changed;
  }

  // StoreStackInst: 将值的 Shape 传播到 stack 变量
  if (auto *store = llvh::dyn_cast<StoreStackInst>(inst)) {
    Value *storedValue = store->getValue();
    AllocStackInst *stackVar = store->getPtr();
    if (const ShapeDescriptor *shape = M->getValueShape(storedValue)) {
      if (!M->hasValueShape(stackVar) || M->getValueShape(stackVar) != shape) {
        M->setValueShape(stackVar, shape);
        changed = true;
      }
    }
    return changed;
  }

  // LoadStackInst: 从 stack 变量继承 Shape
  if (auto *load = llvh::dyn_cast<LoadStackInst>(inst)) {
    AllocStackInst *stackVar = load->getPtr();
    if (const ShapeDescriptor *shape = M->getValueShape(stackVar)) {
      if (!M->hasValueShape(load) || M->getValueShape(load) != shape) {
        M->setValueShape(load, shape);
        changed = true;
      }
    }
    return changed;
  }

  // MovInst: 直接继承 Shape
  if (auto *mov = llvh::dyn_cast<MovInst>(inst)) {
    Value *src = mov->getSingleOperand();
    if (const ShapeDescriptor *shape = M->getValueShape(src)) {
      if (!M->hasValueShape(mov) || M->getValueShape(mov) != shape) {
        M->setValueShape(mov, shape);
        changed = true;
      }
    }
    return changed;
  }

  // PhiInst: 保守交集（所有入口必须相同）
  if (auto *phi = llvh::dyn_cast<PhiInst>(inst)) {
    const ShapeDescriptor *commonShape = nullptr;
    bool first = true;

    for (unsigned i = 0, e = phi->getNumEntries(); i < e; ++i) {
      Value *inValue = phi->getEntry(i).first;
      const ShapeDescriptor *inShape = M->getValueShape(inValue);

      if (first) {
        commonShape = inShape;
        first = false;
      } else if (commonShape != inShape) {
        // 不同 Shape，无法传播
        commonShape = nullptr;
        break;
      }
    }

    // 如果所有入口 Shape 一致，传播
    if (commonShape) {
      if (!M->hasValueShape(phi) || M->getValueShape(phi) != commonShape) {
        M->setValueShape(phi, commonShape);
        changed = true;
      }
    }

    return changed;
  }

  return false;
}

Pass *createShapePropagation() {
  return new ShapePropagation();
}

} // namespace hermes
