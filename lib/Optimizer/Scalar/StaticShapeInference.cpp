/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#define DEBUG_TYPE "staticshapeinference"

#include "StaticShapeInferenceRunner.h"

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
namespace static_shape_inference {

/// 3 状态标记：仅用于 MovInst/PhiInst 的事实传播。
/// visited=false              → NoShape（未处理）
/// visited=true, staticShape≠nullptr → KnownShape
/// visited=true, staticShape=nullptr → AnyShapes
struct FactState {
  bool visited = false;
  const StaticShapeDesc *staticShape = nullptr;
};

/// Step 1 中 compute 规则，判断 Mov/Phi 的事实状态。
/// state 中已包含所有 HasStaticShape operand/Mov/Phi，find()
/// 本身即隐含类型判断。
static FactState computeFactState(
    Instruction *inst,
    const llvh::DenseMap<Instruction *, FactState> &state) {
  if (auto *mov = llvh::dyn_cast<MovInst>(inst)) {
    auto *opInst = llvh::dyn_cast<Instruction>(mov->getSingleOperand());
    if (!opInst)
      return {true, nullptr};
    auto it = state.find(opInst);
    if (it == state.end())
      return {true, nullptr};
    if (it->second.visited)
      return {true, it->second.staticShape};
    return {false, nullptr};
  }

  if (auto *phi = llvh::dyn_cast<PhiInst>(inst)) {
    const StaticShapeDesc *staticShape = nullptr;
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
        staticShape = it->second.staticShape;
      else if (staticShape != it->second.staticShape)
        staticShape = nullptr;

      hasVisited = true;
    }
    if (!hasVisited)
      return {false, nullptr};
    return {true, staticShape};
  }

  llvm_unreachable("Unexpected instruction kind in computeFactState");
}

using FactSet = llvh::SmallPtrSet<Instruction *, 16>;
using BBFactMap = llvh::DenseMap<BasicBlock *, FactSet>;

/// 就地取交集：dst = dst ∩ other。原地修改，避免临时分配。
/// \return true if \p dst changed.
inline bool intersectWith(
    FactSet &dst,
    const FactSet &other,
    Instruction *extra = nullptr) {
  bool changed = false;
  llvh::SmallVector<Instruction *, 16> toRemove;
  for (Instruction *inst : dst)
    if (!other.count(inst) && inst != extra)
      toRemove.push_back(inst);
  for (Instruction *inst : toRemove) {
    dst.erase(inst);
    changed = true;
  }
  return changed;
}

/// nullptr = BB不在map中 = 全集。
inline FactSet *getFacts(BBFactMap &bbMap, BasicBlock *BB) {
  auto it = bbMap.find(BB);
  return it != bbMap.end() ? &it->second : nullptr;
}

inline const FactSet *getFacts(
    const BBFactMap &bbMap,
    BasicBlock *BB) {
  auto it = bbMap.find(BB);
  return it != bbMap.end() ? &it->second : nullptr;
}

inline FactSet *putFacts(
    BBFactMap &bbMap,
    BasicBlock *BB,
    const FactSet &facts) {
  auto inserted = bbMap.try_emplace(BB, facts);
  return &inserted.first->second;
}

/// 检查 inst 是否在 bbMap[BB] 中。BB 不在 map → 全集 → 总是 true。
inline bool
isInBBSet(BBFactMap &bbMap, BasicBlock *BB, Instruction *inst) {
  auto *s = getFacts(bbMap, BB);
  return !s || s->count(inst);
}

inline bool
isInBBSet(const BBFactMap &bbMap, BasicBlock *BB, Instruction *inst) {
  auto *s = getFacts(bbMap, BB);
  return !s || s->count(inst);
}

static ObjectOperandShape getObjectOperandShape(Instruction *inst) {
  if (auto *L = llvh::dyn_cast<BaseLoadPropertyInst>(inst))
    return L->getObjOperandShape();
  if (auto *S = llvh::dyn_cast<BaseStorePropertyInst>(inst))
    return S->getObjOperandShape();
  return llvh::cast<HasStaticShapeInst>(inst)->getObjOperandShape();
}

static void setObjectOperandShape(Instruction *inst, ObjectOperandShape shape) {
  if (auto *L = llvh::dyn_cast<BaseLoadPropertyInst>(inst))
    L->setObjOperandShape(shape);
  else if (auto *S = llvh::dyn_cast<BaseStorePropertyInst>(inst))
    S->setObjOperandShape(shape);
  else
    llvh::cast<HasStaticShapeInst>(inst)->setObjOperandShape(shape);
}

class Impl {
  friend class ::hermes::StaticShapeInferenceRunner;

  Function *F_;

  /// fact value → its shape（只缩不增）
  llvh::DenseMap<Instruction *, const StaticShapeDesc *> facts_;

  /// 在最后一个 validate 后必然有 kill-all 的块（只增不减）
  llvh::DenseSet<BasicBlock *> bbKillAll_;

  /// 块入口/出口处有效且主导的事实。缺失=facts_（全集）。
  BBFactMap validFactsAtIn_;
  BBFactMap validFactsAtOut_;

  /// (LoadProperty/StoreProperty/HasStaticShape, object operand)，提前收集。
  llvh::SmallVector<std::pair<Instruction *, Instruction *>, 64> shapedInsts_;

  /// 获取属性访问/shape检查指令的 object 操作数。不匹配返回 nullptr。
  static Value *getObjectOperand(Instruction *inst) {
    if (auto *L = llvh::dyn_cast<BaseLoadPropertyInst>(inst))
      return L->getObject();
    if (auto *S = llvh::dyn_cast<BaseStorePropertyInst>(inst))
      return S->getObject();
    if (auto *I = llvh::dyn_cast<HasStaticShapeInst>(inst))
      return I->getArgument();
    return nullptr;
  }

  /// 检查 StoreProperty 是否与已知 shape 兼容。
  bool isStoreShapeCompatible(
      BaseStorePropertyInst *store,
      const StaticShapeDesc *shape) const {
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

  /// 动态判断指令是否会破坏事实链。只有 heap 写入可能改变对象 shape。
  bool instKillAll(Instruction *inst) const {
    auto se = inst->getSideEffect();
    if (!se.getWriteHeap())
      return false;
    // StoreProperty and PrStore will definitely write heap
    // However, they don't kill facts if the stored value's type
    // is compatible with the expected type in the known shape.
    if (auto *store = llvh::dyn_cast<BaseStorePropertyInst>(inst)) {
      switch (store->getObjOperandShape().status) {
        case ObjectOperandShape::KnownStaticShape:
          return !isStoreShapeCompatible(
              store, store->getObjOperandShape().desc);
        case ObjectOperandShape::NoShape:
          return false;
        case ObjectOperandShape::AnyShapes:
          return true;
      }
    }

    if (auto *store = llvh::dyn_cast<PrStoreInst>(inst))
      return !store->getStoredValue()->getType().isSubsetOf(
          store->getExpectedType());

    return true;
  }

  /// \return whether \p inst is a Mov/Phi fact.
  inline bool isMovPhiFact(Instruction *inst) const {
    return (llvh::isa<MovInst>(inst) || llvh::isa<PhiInst>(inst)) &&
        facts_.count(inst);
  }

  /// \return the fact validated on edge \p pred -> \p succ, or nullptr.
  Instruction *getEdgeValidatedFact(BasicBlock *pred, BasicBlock *succ)
      const {
    auto *condBr = llvh::dyn_cast<CondBranchInst>(pred->getTerminator());
    if (!condBr || condBr->getTrueDest() != succ)
      return nullptr;

    auto *hasStaticShape =
        llvh::dyn_cast<HasStaticShapeInst>(condBr->getCondition());
    if (!hasStaticShape)
      return nullptr;

    auto *fact = llvh::dyn_cast<Instruction>(hasStaticShape->getArgument());

    return fact;
  }

  /// shape 变更后检查是否需要将所在块标为 killAll。
  void updateBBKillAll(Instruction *inst) {
    BasicBlock *BB = inst->getParent();
    if (bbKillAll_.count(BB) || !instKillAll(inst))
      return;

    auto it = inst->getIterator();
    for (++it; it != BB->end(); ++it) {
      if (isMovPhiFact(&*it)) {
        return;
      }
    }
    bbKillAll_.insert(BB);
  }

  /// Check whether \p fact is valid at the program point immediately
  /// before \p use.
  bool isFactValidBefore(Instruction *fact, Instruction *use) const {
    // Phi incoming values are checked against predecessor OUT sets instead.
    // For non-phi uses, an operand defined in the same block must appear before
    // the use.
    assert(!llvh::isa<PhiInst>(use) && "use must not be a PhiInst");

    if (!facts_.count(fact))
      return false;

    BasicBlock *BB = use->getParent();

    auto it = use->getIterator();
    while (it != BB->begin()) {
      --it;
      Instruction *inst = &*it;
      if (instKillAll(inst))
        return false;
      if (inst == fact && isMovPhiFact(inst))
        return true;
    }

    return isInBBSet(validFactsAtIn_, BB, fact);
  }

  //===------------------------------------------------------------------===//
  // Step 1: 收集最大事实集
  //===------------------------------------------------------------------===//
  void collectFacts() {
    llvh::DenseMap<Instruction *, FactState> state;
    llvh::SmallVector<Instruction *, 32> worklist;

    // 初始化：HasStaticShape operand → {true, shape}；Mov/Phi → {false, nullptr}
    for (auto &BB : *F_) {
      for (auto &I : BB) {
        if (auto *HTS = llvh::dyn_cast<HasStaticShapeInst>(&I)) {
          if (auto *opInst = llvh::dyn_cast<Instruction>(HTS->getArgument())) {
            state[opInst] = {true, HTS->getShape()->getData()};
          }
        } else if (llvh::isa<MovInst>(&I) || llvh::isa<PhiInst>(&I)) {
          state.try_emplace(&I, FactState{false, nullptr});
          worklist.push_back(&I);
        }
      }
    }

    // 工作列表迭代
    while (!worklist.empty()) {
      auto *inst = worklist.pop_back_val();
      FactState newState = computeFactState(inst, state);
      if (newState.visited == state[inst].visited &&
          newState.staticShape == state[inst].staticShape)
        continue;
      state[inst] = newState;
      for (auto *userInst : inst->getUsers()) {
        if (llvh::isa<MovInst>(userInst) || llvh::isa<PhiInst>(userInst))
          worklist.push_back(userInst);
      }
    }

    // 构建 facts_
    facts_.clear();
    for (auto &entry : state) {
      if (entry.second.visited && entry.second.staticShape) {
        facts_[entry.first] = entry.second.staticShape;
      }
    }

    LLVM_DEBUG(
        dbgs() << "StaticShapeInference: collected " << facts_.size()
               << " facts in function " << F_->getInternalName() << "\n");
  }

  //===------------------------------------------------------------------===//
  // Step 2: 保存并重置 objectShape
  //===------------------------------------------------------------------===//
  void resetShapes() {
    for (auto &BB : *F_) {
      for (auto &I : BB) {
        Value *object = getObjectOperand(&I);
        if (object) {
          auto *objInst = llvh::dyn_cast<Instruction>(object);
          shapedInsts_.emplace_back(&I, objInst);
          setObjectOperandShape(&I, ObjectOperandShape::createNoShape());
        }
      }
    }
  }

  //===------------------------------------------------------------------===//
  // Step 3: 初始化 bbKillAll_
  //===------------------------------------------------------------------===//
  void initKillAll() {
    // 初始化 bbKillAll_: 每块从后往前找最后一个 validate，
    // 若找到且该 validate 后有 killAll 指令 → BB ∈ bbKillAll_
    for (auto &BB : *F_) {
      for (auto &I : llvh::reverse(BB)) {
        if (instKillAll(&I)) {
          bbKillAll_.insert(&BB);
          break;
        }
        if (isMovPhiFact(&I))
          break;
      }
    }

    LLVM_DEBUG(
        dbgs() << "StaticShapeInference: " << bbKillAll_.size()
               << " kill-all BBs\n");
  }

  //===------------------------------------------------------------------===//
  // Step 4: 不动点迭代
  //===------------------------------------------------------------------===//

  // 4a. 更新 Mov/Phi 事实（初始扫描 + 工作队列级联kill）
  bool updateMovPhiFacts() {
    bool changed = false;
    llvh::SmallVector<Instruction *, 16> worklist;

    for (auto &[inst, shape] : facts_) {
      if (auto *mov = llvh::dyn_cast<MovInst>(inst)) {
        auto *srcI = llvh::dyn_cast<Instruction>(mov->getSingleOperand());
        if (!srcI || !isFactValidBefore(srcI, mov))
          worklist.push_back(inst);
      } else if (auto *phi = llvh::dyn_cast<PhiInst>(inst)) {
        for (unsigned i = 0, e = phi->getNumEntries(); i < e; ++i) {
          auto entry = phi->getEntry(i);
          auto *incomingI = llvh::dyn_cast<Instruction>(entry.first);
          if (!incomingI || !facts_.count(incomingI)) {
            worklist.push_back(inst);
            break;
          }
          if (isInBBSet(validFactsAtOut_, entry.second, incomingI)) {
            continue;
          }
          if (getEdgeValidatedFact(entry.second, phi->getParent()) ==
              incomingI) {
            continue;
          }
          worklist.push_back(inst);
          break;
        }
      }
    }

    while (!worklist.empty()) {
      auto *inst = worklist.pop_back_val();
      if (!facts_.count(inst))
        continue;

      facts_.erase(inst);
      changed = true;

      // 级联：下游 Mov/Phi 也kill
      for (auto *user : inst->getUsers()) {
        if (llvh::isa<PhiInst>(user) || llvh::isa<MovInst>(user))
          worklist.push_back(user);
      }
    }

    LLVM_DEBUG(
        if (changed) dbgs()
        << "StaticShapeInference: removed Mov/Phi facts in function "
        << F_->getInternalName() << "\n");
    return changed;
  }

  // 4b. 更新 objectShape
  bool updateObjectShapes() {
    bool changed = false;
    for (auto [user, objInst] : shapedInsts_) {
      ObjectOperandShape newShape = ObjectOperandShape::createAnyShapes();

      if (objInst && isFactValidBefore(objInst, user))
        newShape =
            ObjectOperandShape::createKnownStaticShape(facts_[objInst]);

      if (newShape != getObjectOperandShape(user)) {
        setObjectOperandShape(user, newShape);
        changed = true;
        updateBBKillAll(user);
      }
    }
    return changed;
  }

  // 4c. 前向数据流：工作队列传播 valid facts
  bool propagateValidFacts() {
    bool changed = false;
    llvh::SmallVector<BasicBlock *, 16> worklist;

    for (auto &BB : *F_)
      worklist.push_back(&BB);

    while (!worklist.empty()) {
      auto *BB = worklist.pop_back_val();

      // === Meet: IN[B] = IN[B] ∩ OUT[pred(B)] ===
      // Missing map entry means universe. The entry block starts as an
      // explicit empty set and has no predecessors, so it remains fixed.
      auto *in = getFacts(validFactsAtIn_, BB);
      for (auto *pred : predecessors(BB)) {
        auto *predOut = getFacts(validFactsAtOut_, pred);
        if (!predOut)
          continue;
        Instruction *edgeFact = getEdgeValidatedFact(pred, BB);
        if (!in) {
          in = putFacts(validFactsAtIn_, BB, *predOut);
          if (edgeFact)
            in->insert(edgeFact);
          changed = true;
        } else {
          changed |= intersectWith(*in, *predOut, edgeFact);
        }
      }

      // === Transfer: OUT[B] = OUT[B] ∩ transfer(IN[B], B) ===
      FactSet transfer;
      bool mergeIn = false;
      if (!bbKillAll_.count(BB)) {
        mergeIn = true;
        for (auto &I : llvh::reverse(*BB)) {
          if (instKillAll(&I)) {
            mergeIn = false;
            break;
          }
          if (isMovPhiFact(&I))
            transfer.insert(&I);
        }
      }
      if (mergeIn && in)
        transfer.insert(in->begin(), in->end());

      bool outChanged = false;
      auto *out = getFacts(validFactsAtOut_, BB);
      if (mergeIn && !in)
        // mergeIn == true && in == universe => out == universe, no change
        ;
      // must be: mergeIn == false || in != universe
      // transfer has merged `in`, if necessary.
      else if (out)
        outChanged = intersectWith(*out, transfer);
      else {
        out = putFacts(validFactsAtOut_, BB, transfer);
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

} // namespace static_shape_inference

StaticShapeInferenceRunner::StaticShapeInferenceRunner(Function *F)
    : impl_(new static_shape_inference::Impl(F)) {}

StaticShapeInferenceRunner::~StaticShapeInferenceRunner() = default;

void StaticShapeInferenceRunner::preIteration() {
  impl_->collectFacts();

  if (impl_->facts_.empty())
    return;

  impl_->resetShapes();
  impl_->initKillAll();

  BasicBlock *entryBB = &*impl_->F_->begin();
  impl_->validFactsAtIn_[entryBB] = {};
}

bool StaticShapeInferenceRunner::step() {
  if (impl_->facts_.empty())
    return false;

  bool changed = false;
  changed |= impl_->updateMovPhiFacts();
  changed |= impl_->updateObjectShapes();
  changed |= impl_->propagateValidFacts();

  return changed;
}

} // namespace hermes

#undef DEBUG_TYPE
