/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#define DEBUG_TYPE "typedshapeinference"

#include "TypedShapeInferenceRunner.h"

#include "hermes/IR/CFG.h"
#include "hermes/IR/Instrs.h"
#include "llvh/ADT/DenseMap.h"
#include "llvh/ADT/DenseSet.h"
#include "llvh/ADT/SmallPtrSet.h"
#include "llvh/ADT/SmallVector.h"
#include "llvh/Support/Debug.h"

using namespace hermes;
using llvh::dbgs;

namespace hermes {
namespace typed_shape_inference {

/// 3 状态标记：仅用于 MovInst/PhiInst 的断言传播。
/// visited=false              → NoShape（未处理）
/// visited=true, typedShape≠nullptr → KnownShape
/// visited=true, typedShape=nullptr → AnyShapes
struct AssertionState {
  bool visited = false;
  const TypedShapeDesc *typedShape = nullptr;
};

/// Step 1 中 compute 规则，判断 Mov/Phi 的断言状态。
/// state 中已包含所有 AssertTypedShape/Mov/Phi，find() 本身即隐含类型判断。
static AssertionState computeAssertionState(
    Instruction *inst,
    const llvh::DenseMap<Instruction *, AssertionState> &state) {
  if (auto *mov = llvh::dyn_cast<MovInst>(inst)) {
    auto *opInst = llvh::dyn_cast<Instruction>(mov->getSingleOperand());
    if (!opInst)
      return {true, nullptr};
    auto it = state.find(opInst);
    if (it == state.end())
      return {true, nullptr};
    if (it->second.visited)
      return {true, it->second.typedShape};
    return {false, nullptr};
  }

  if (auto *phi = llvh::dyn_cast<PhiInst>(inst)) {
    const TypedShapeDesc *typedShape = nullptr;
    bool hasVisited = false;
    for (unsigned i = 0, e = phi->getNumEntries(); i < e; ++i) {
      Value *v = phi->getEntry(i).first;
      auto *vInst = llvh::dyn_cast<Instruction>(v);
      if (!vInst)
        return {true, nullptr};
      auto it = state.find(vInst);
      if (it == state.end())
        return {true, nullptr};
      if (!it->second.visited)
        continue;
      if (!hasVisited)
        typedShape = it->second.typedShape;
      else if (typedShape != it->second.typedShape)
        typedShape = nullptr;

      hasVisited = true;
    }
    if (!hasVisited)
      return {false, nullptr};
    return {true, typedShape};
  }

  llvm_unreachable("Unexpected instruction kind in computeAssertionState");
}

using AssertionSet = llvh::SmallPtrSet<Instruction *, 16>;
using BBAssertionMap = llvh::DenseMap<BasicBlock *, AssertionSet>;

/// 就地取交集：dst = dst ∩ other。原地修改，避免临时分配。
/// \return true if \p dst changed.
inline bool intersectWith(AssertionSet &dst, const AssertionSet &other) {
  bool changed = false;
  llvh::SmallVector<Instruction *, 16> toRemove;
  for (Instruction *inst : dst)
    if (!other.count(inst))
      toRemove.push_back(inst);
  for (Instruction *inst : toRemove) {
    dst.erase(inst);
    changed = true;
  }
  return changed;
}

/// nullptr = BB不在map中 = 全集。
inline AssertionSet *getAssertions(BBAssertionMap &bbMap, BasicBlock *BB) {
  auto it = bbMap.find(BB);
  return it != bbMap.end() ? &it->second : nullptr;
}

inline const AssertionSet *getAssertions(
    const BBAssertionMap &bbMap,
    BasicBlock *BB) {
  auto it = bbMap.find(BB);
  return it != bbMap.end() ? &it->second : nullptr;
}

inline AssertionSet *putAssertions(
    BBAssertionMap &bbMap,
    BasicBlock *BB,
    const AssertionSet &assertions) {
  auto inserted = bbMap.try_emplace(BB, assertions);
  return &inserted.first->second;
}

/// 检查 inst 是否在 bbMap[BB] 中。BB 不在 map → 全集 → 总是 true。
inline bool
isInBBSet(BBAssertionMap &bbMap, BasicBlock *BB, Instruction *inst) {
  auto *s = getAssertions(bbMap, BB);
  return !s || s->count(inst);
}

inline bool
isInBBSet(const BBAssertionMap &bbMap, BasicBlock *BB, Instruction *inst) {
  auto *s = getAssertions(bbMap, BB);
  return !s || s->count(inst);
}

static ObjectOperandShape getObjectOperandShape(Instruction *inst) {
  if (auto *L = llvh::dyn_cast<BaseLoadPropertyInst>(inst))
    return L->getObjOperandShape();
  if (auto *S = llvh::dyn_cast<BaseStorePropertyInst>(inst))
    return S->getObjOperandShape();
  return llvh::cast<IsTypedShapeInst>(inst)->getObjOperandShape();
}

static void setObjectOperandShape(Instruction *inst, ObjectOperandShape shape) {
  if (auto *L = llvh::dyn_cast<BaseLoadPropertyInst>(inst))
    L->setObjOperandShape(shape);
  else if (auto *S = llvh::dyn_cast<BaseStorePropertyInst>(inst))
    S->setObjOperandShape(shape);
  else
    llvh::cast<IsTypedShapeInst>(inst)->setObjOperandShape(shape);
}

class Impl {
  friend class ::hermes::TypedShapeInferenceRunner;

  Function *F_;

  /// 断言指令 → asserted shape（只缩不增）
  llvh::DenseMap<Instruction *, const TypedShapeDesc *> assertions_;

  /// 在最后一个 assertion 后必然有 break-all 的块（只增不减）
  llvh::DenseSet<BasicBlock *> bbBreakAll_;

  /// 块入口/出口处有效且主导的断言。缺失=assertions_（全集）。
  BBAssertionMap validAssertionsAtIn_;
  BBAssertionMap validAssertionsAtOut_;

  /// (LoadProperty/StoreProperty/IsTypedShape, object operand)，提前收集。
  llvh::SmallVector<std::pair<Instruction *, Instruction *>, 64> shapedInsts_;

  /// 保存的原始 ObjectOperandShape（验证用）
  llvh::DenseMap<Instruction *, ObjectOperandShape> savedShapes_;

  /// Check whether there is no break-all instruction before \p use in its
  /// block. If \p start is provided, the scan begins there instead of at the
  /// block entry; this also verifies that \p start appears before \p use.
  bool isBreakAllFreeBefore(Instruction *use, Instruction *start = nullptr)
      const {
    BasicBlock *BB = use->getParent();
    bool scanning = !start;
    for (auto &I : *BB) {
      if (&I == use)
        return scanning;
      if (&I == start)
        scanning = true;
      if (scanning && instBreakAll(&I))
        return false;
    }
    return false;
  }

  /// 获取属性访问/shape检查指令的 object 操作数。不匹配返回 nullptr。
  static Value *getObjectOperand(Instruction *inst) {
    if (auto *L = llvh::dyn_cast<BaseLoadPropertyInst>(inst))
      return L->getObject();
    if (auto *S = llvh::dyn_cast<BaseStorePropertyInst>(inst))
      return S->getObject();
    if (auto *I = llvh::dyn_cast<IsTypedShapeInst>(inst))
      return I->getArgument();
    return nullptr;
  }

  /// 检查 StoreProperty 是否与已知 shape 兼容。
  bool isStoreShapeCompatible(
      BaseStorePropertyInst *store,
      const TypedShapeDesc *shape) const {
    auto *prop = llvh::dyn_cast<LiteralString>(store->getProperty());
    if (!prop)
      return false;

    Identifier name = prop->getValue();
    int idx = shape->getPropertyIndex(name);
    if (idx < 0)
      return false;

    Type expectedType = shape->getPropertyType(idx);
    Type storedType = store->getStoredValue()->getType();
    return storedType.isSubsetOf(expectedType);
  }

  /// 动态判断指令是否会破坏断言链。结合固有 break-all 和 shape 上下文。
  bool instBreakAll(Instruction *inst) const {
    auto se = inst->getSideEffect();
    if (!se.getWriteHeap() && !se.getExecuteJS() && !se.getThrow())
      return false;

    if (auto *load = llvh::dyn_cast<BaseLoadPropertyInst>(inst)) {
      return load->getObjOperandShape().status == ObjectOperandShape::AnyShapes;
    }

    if (auto *store = llvh::dyn_cast<BaseStorePropertyInst>(inst)) {
      switch (store->getObjOperandShape().status) {
        case ObjectOperandShape::KnownTypedShape:
          return !isStoreShapeCompatible(
              store, store->getObjOperandShape().desc);
        case ObjectOperandShape::NoShape:
          return false;
        case ObjectOperandShape::AnyShapes:
          return true;
      }
    }

    return false;
  }

  /// shape 变更后检查是否需要将所在块标为 breakAll。
  void updateBBBreakAll(Instruction *inst) {
    BasicBlock *BB = inst->getParent();
    if (bbBreakAll_.count(BB) || !instBreakAll(inst))
      return;

    auto it = inst->getIterator();
    for (++it; it != BB->end(); ++it) {
      if (assertions_.count(&*it)) {
        return;
      }
    }
    bbBreakAll_.insert(BB);
  }

  /// Check whether \p assertion is valid at the program point immediately
  /// before \p use.
  bool isAssertionValidBefore(Instruction *assertion, Instruction *use) const {
    // Phi incoming values are checked against predecessor OUT sets instead.
    // For non-phi uses, an operand defined in the same block must appear before
    // the use.
    assert(!llvh::isa<PhiInst>(use) && "use must not be a PhiInst");

    if (!assertions_.count(assertion))
      return false;
    BasicBlock *BB = use->getParent();
    auto it = assertion->getIterator();
    auto end = use->getIterator();
    if (assertion->getParent() != BB) {
      if (!isInBBSet(validAssertionsAtIn_, BB, assertion))
        return false;
      it = BB->begin();
    }
    for (; it != end; ++it) {
      if (instBreakAll(&*it))
        return false;
    }
    return true;
  }

  //===------------------------------------------------------------------===//
  // Step 1: 收集最大断言集
  //===------------------------------------------------------------------===//
  void collectAssertions() {
    llvh::DenseMap<Instruction *, AssertionState> state;
    llvh::SmallVector<Instruction *, 32> worklist;

    // 初始化：AssertTypedShape → {true, shape}；Mov/Phi → {false, nullptr}
    for (auto &BB : *F_) {
      for (auto &I : BB) {
        if (auto *AT = llvh::dyn_cast<AssertTypedShapeInst>(&I)) {
          state[&I] = {true, AT->getShape()};
        } else if (llvh::isa<MovInst>(&I) || llvh::isa<PhiInst>(&I)) {
          state[&I] = {false, nullptr};
          worklist.push_back(&I);
        }
      }
    }

    // 工作列表迭代
    while (!worklist.empty()) {
      auto *inst = worklist.pop_back_val();
      AssertionState newState = computeAssertionState(inst, state);
      if (newState.visited == state[inst].visited &&
          newState.typedShape == state[inst].typedShape)
        continue;
      state[inst] = newState;
      for (auto *userInst : inst->getUsers()) {
        if (llvh::isa<MovInst>(userInst) || llvh::isa<PhiInst>(userInst))
          worklist.push_back(userInst);
      }
    }

    // 构建 assertions_
    assertions_.clear();
    for (auto &entry : state) {
      if (entry.second.visited && entry.second.typedShape) {
        assertions_[entry.first] = entry.second.typedShape;
      }
    }

    LLVM_DEBUG(
        dbgs() << "TypedShapeInference: collected " << assertions_.size()
               << " assertions in function " << F_->getInternalName() << "\n");
  }

  //===------------------------------------------------------------------===//
  // Step 2: 保存并重置 objectShape
  //===------------------------------------------------------------------===//
  void saveAndResetShapes() {
    for (auto &BB : *F_) {
      for (auto &I : BB) {
        Value *object = getObjectOperand(&I);
        if (object) {
          auto *objInst = llvh::dyn_cast<Instruction>(object);
          shapedInsts_.emplace_back(&I, objInst);
          savedShapes_[&I] = getObjectOperandShape(&I);
          setObjectOperandShape(&I, ObjectOperandShape::createNoShape());
        }
      }
    }
  }

  //===------------------------------------------------------------------===//
  // Step 3: 初始化 bbBreakAll_
  //===------------------------------------------------------------------===//
  void initBreakAll() {
    // 初始化 bbBreakAll_: 每块从后往前找最后一个 assertion，
    // 若找到且该 assertion 后有 breakAll 指令 → BB ∈ bbBreakAll_
    for (auto &BB : *F_) {
      for (auto &I : llvh::reverse(BB)) {
        if (instBreakAll(&I)) {
          bbBreakAll_.insert(&BB);
          break;
        }
        if (assertions_.count(&I))
          break;
      }
    }

    LLVM_DEBUG(
        dbgs() << "TypedShapeInference: " << bbBreakAll_.size()
               << " break-all BBs\n");
  }

  //===------------------------------------------------------------------===//
  // Step 4: 不动点迭代
  //===------------------------------------------------------------------===//

  // 4a. 更新 Mov/Phi 断言（初始扫描 + 工作队列级联失效）
  bool updateMovPhiAssertions() {
    bool changed = false;
    llvh::SmallVector<Instruction *, 16> worklist;

    for (auto &[inst, shape] : assertions_) {
      if (llvh::isa<AssertTypedShapeInst>(inst))
        continue;

      if (auto *mov = llvh::dyn_cast<MovInst>(inst)) {
        auto *srcI = llvh::dyn_cast<Instruction>(mov->getSingleOperand());
        if (!srcI || !isAssertionValidBefore(srcI, mov))
          worklist.push_back(inst);
      } else if (auto *phi = llvh::dyn_cast<PhiInst>(inst)) {
        for (unsigned i = 0, e = phi->getNumEntries(); i < e; ++i) {
          auto entry = phi->getEntry(i);
          auto *incomingI = llvh::dyn_cast<Instruction>(entry.first);
          if (!incomingI || !assertions_.count(incomingI) ||
              !isInBBSet(validAssertionsAtOut_, entry.second, incomingI)) {
            worklist.push_back(inst);
            break;
          }
        }
      }
    }

    while (!worklist.empty()) {
      auto *inst = worklist.pop_back_val();
      if (!assertions_.count(inst))
        continue;

      assertions_.erase(inst);
      changed = true;

      // 级联：下游 Mov/Phi 也失效
      for (auto *user : inst->getUsers()) {
        if (llvh::isa<PhiInst>(user) || llvh::isa<MovInst>(user))
          worklist.push_back(user);
      }
    }

    LLVM_DEBUG(
        if (changed) dbgs()
        << "TypedShapeInference: removed Mov/Phi assertions in function "
        << F_->getInternalName() << "\n");
    return changed;
  }

  // 4b. 更新 objectShape
  bool updateObjectShapes() {
    bool changed = false;
    for (auto [user, objInst] : shapedInsts_) {
      ObjectOperandShape newShape = ObjectOperandShape::createAnyShapes();

      if (objInst && isAssertionValidBefore(objInst, user))
        newShape =
            ObjectOperandShape::createKnownTypedShape(assertions_[objInst]);

      if (newShape != getObjectOperandShape(user)) {
        setObjectOperandShape(user, newShape);
        changed = true;
        updateBBBreakAll(user);
      }
    }
    return changed;
  }

  // 4c. 前向数据流：工作队列传播 valid assertions
  bool propagateValidAssertions() {
    bool changed = false;
    llvh::SmallVector<BasicBlock *, 16> worklist;

    for (auto &BB : *F_)
      worklist.push_back(&BB);

    while (!worklist.empty()) {
      auto *BB = worklist.pop_back_val();

      // === Meet: IN[B] = IN[B] ∩ OUT[pred(B)] ===
      // Missing map entry means universe. The entry block starts as an
      // explicit empty set and has no predecessors, so it remains fixed.
      auto *in = getAssertions(validAssertionsAtIn_, BB);
      for (auto *pred : predecessors(BB)) {
        auto *predOut = getAssertions(validAssertionsAtOut_, pred);
        if (!predOut)
          continue;
        if (!in) {
          in = putAssertions(validAssertionsAtIn_, BB, *predOut);
          changed = true;
        } else {
          changed |= intersectWith(*in, *predOut);
        }
      }

      // === Transfer: OUT[B] = OUT[B] ∩ transfer(IN[B], B) ===
      AssertionSet transfer;
      bool mergeIn = false;
      if (!bbBreakAll_.count(BB)) {
        mergeIn = true;
        for (auto &I : llvh::reverse(*BB)) {
          if (instBreakAll(&I)) {
            mergeIn = false;
            break;
          }
          if (assertions_.count(&I))
            transfer.insert(&I);
        }
      }
      if (mergeIn && in)
        transfer.insert(in->begin(), in->end());

      bool outChanged = false;
      auto *out = getAssertions(validAssertionsAtOut_, BB);
      if (mergeIn && !in)
        // mergeIn == true && in == universe => out == universe, no change
        ;
      // must be: mergeIn == false || in != universe
      // transfer has merged `in`, if necessary.
      else if (out)
        outChanged = intersectWith(*out, transfer);
      else {
        out = putAssertions(validAssertionsAtOut_, BB, transfer);
        outChanged = true;
      }

      if (outChanged) {
        changed = true;
        for (auto *succ : successors(BB))
          worklist.push_back(succ);
      }
    }
    return changed;
  }

 public:
  explicit Impl(Function *F) : F_(F) {}
};

} // namespace typed_shape_inference

TypedShapeInferenceRunner::TypedShapeInferenceRunner(Function *F)
    : impl_(new typed_shape_inference::Impl(F)) {}

TypedShapeInferenceRunner::~TypedShapeInferenceRunner() = default;

void TypedShapeInferenceRunner::preIteration() {
  impl_->collectAssertions();

  if (impl_->assertions_.empty())
    return;

  impl_->saveAndResetShapes();
  impl_->initBreakAll();

  BasicBlock *entryBB = &*impl_->F_->begin();
  impl_->validAssertionsAtIn_[entryBB] = {};
}

bool TypedShapeInferenceRunner::step() {
  if (impl_->assertions_.empty())
    return false;

  bool changed = false;
  changed |= impl_->updateMovPhiAssertions();
  changed |= impl_->updateObjectShapes();
  changed |= impl_->propagateValidAssertions();

  return changed;
}

} // namespace hermes

#undef DEBUG_TYPE
