/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#define DEBUG_TYPE "heaploadstoreopts"

#include "hermes/Optimizer/Scalar/HeapLoadStoreOpts.h"
#include "hermes/IR/Analysis.h"
#include "hermes/IR/CFG.h"
#include "hermes/IR/IRBuilder.h"
#include "hermes/IR/Instrs.h"
#include "hermes/Optimizer/PassManager/Pass.h"
#include "hermes/Support/Statistic.h"

#include "llvh/ADT/DenseMap.h"
#include "llvh/ADT/DenseSet.h"
#include "llvh/ADT/Hashing.h"
#include "llvh/ADT/STLExtras.h"
#include "llvh/ADT/SetOperations.h"

using namespace hermes;

STATISTIC(NumHeapLoadElim, "Number of heap loads eliminated");

namespace {

/// Cross-opcode identity for a heap access used as the mirror key.
/// PrSlot is shared by PrLoadInst and PrStoreInst (same object + propIndex +
/// propName); TypedParent is TypedLoadParentInst (object only).
/// LoadParentNoTraps is intentionally not handled.
struct LoadKey {
  enum Class { PrSlot, TypedParent } cls;
  Value *object;
  // PrSlot only: the slot index uniquely identifies the property within the
  // object's static shape, so propName is redundant given object.
  Value *propIndex;

  bool operator==(const LoadKey &O) const {
    return cls == O.cls && object == O.object && propIndex == O.propIndex;
  }
};

struct LoadKeyInfo {
  static inline LoadKey getEmptyKey() {
    return {LoadKey::PrSlot, nullptr, nullptr};
  }
  static inline LoadKey getTombstoneKey() {
    return {LoadKey::PrSlot, reinterpret_cast<Value *>(1), nullptr};
  }
  static unsigned getHashValue(const LoadKey &k) {
    return llvh::hash_combine(static_cast<unsigned>(k.cls), k.object, k.propIndex);
  }
  static bool isEqual(const LoadKey &a, const LoadKey &b) {
    return a == b;
  }
};

using LoadSet = llvh::DenseSet<LoadKey, LoadKeyInfo>;

/// Extract the load-side key for PrLoadInst / TypedLoadParentInst.
static bool keyOfLoad(Instruction *I, LoadKey &out) {
  if (auto *PL = llvh::dyn_cast<PrLoadInst>(I)) {
    out.cls = LoadKey::PrSlot;
    out.object = PL->getObject();
    out.propIndex = PL->getOperand(PrLoadInst::PropIndexIdx);
    return true;
  }
  if (auto *TLP = llvh::dyn_cast<TypedLoadParentInst>(I)) {
    out.cls = LoadKey::TypedParent;
    out.object = TLP->getObject();
    out.propIndex = nullptr;
    return true;
  }
  return false;
}

/// Extract the store-side key for PrStoreInst (store->load source).
static bool keyOfStore(const Instruction *I, LoadKey &out) {
  if (auto *PS = llvh::dyn_cast<PrStoreInst>(I)) {
    out.cls = LoadKey::PrSlot;
    out.object = PS->getObject();
    out.propIndex = PS->getOperand(PrStoreInst::PropIndexIdx);
    return true;
  }
  return false;
}

class FunctionHeapLoadStoreOptimizer {
  Function *const F_;
  std::vector<BasicBlock *> PO_;
  llvh::DenseMap<LoadKey, AllocStackInst *, LoadKeyInfo> loadAllocas_{};
  llvh::DenseMap<BasicBlock *, LoadSet> blockValidLoads_{};

  /// For each LoadKey appearing >= 2 times with a load side, create an alloca
  /// at the entry block (which dominates everything) to mirror its value.
  void createLoadAllocas() {
    struct Info {
      unsigned count = 0;
      bool hasLoad = false;
      Instruction *repLoad = nullptr;
    };
    llvh::DenseMap<LoadKey, Info, LoadKeyInfo> stats;
    for (BasicBlock *BB : PO_) {
      for (Instruction &I : *BB) {
        LoadKey k;
        bool isLoad = keyOfLoad(&I, k);
        bool isStore = !isLoad && keyOfStore(&I, k);
        if (!isLoad && !isStore)
          continue;
        Info &e = stats[k];
        e.count++;
        if (isLoad) {
          e.hasLoad = true;
          e.repLoad = &I;
        }
      }
    }

    IRBuilder builder(F_);
    builder.setInsertionPoint(&*F_->front().begin());
    for (auto &kv : stats) {
      if (kv.second.count >= 2 && kv.second.hasLoad) {
        auto *ASI =
            builder.createAllocStackInst("hls", kv.second.repLoad->getType());
        loadAllocas_.try_emplace(kv.first, ASI);
      }
    }
  }

  /// Delete allocas that were only ever stored to (never read), i.e. did not
  /// enable any load elimination.
  void deleteUnusedAllocas() {
    IRBuilder::InstructionDestroyer destroyer;
    for (auto &kv : loadAllocas_) {
      AllocStackInst *ASI = kv.second;
      bool onlyStores = true;
      for (auto *U : ASI->getUsers()) {
        if (!llvh::isa<StoreStackInst>(U)) {
          onlyStores = false;
          break;
        }
      }
      if (!onlyStores)
        continue;
      for (auto *U : ASI->getUsers())
        destroyer.add(U);
      destroyer.add(ASI);
    }
  }

  /// Available loads at BB entry = intersection of predecessors' outgoing sets.
  /// Conservative empty if a predecessor hasn't been visited yet (loops).
  LoadSet computeEntryValid(BasicBlock *BB) {
    LoadSet res;
    auto preds = predecessors(BB);
    auto it = preds.begin(), e = preds.end();
    if (it == e)
      return res;
    auto first = blockValidLoads_.find(*it);
    if (first == blockValidLoads_.end())
      return res;
    res = first->second;
    for (++it; it != e; ++it) {
      auto cur = blockValidLoads_.find(*it);
      if (cur == blockValidLoads_.end())
        return {};
      llvh::set_intersect(res, cur->second);
    }
    return res;
  }

  bool eliminateLoads(BasicBlock *BB) {
    LoadSet valid = computeEntryValid(BB);
    IRBuilder builder(F_);
    IRBuilder::InstructionDestroyer destroyer;
    bool changed = false;

    for (Instruction &I : *BB) {
      SideEffect se = I.getSideEffect();
      if (se.getWriteHeap()) {
        // Write barrier: a heap write has an arbitrary target, so any available
        // load may be invalidated.
        valid.clear();
        // PrStore is itself a write-heap, but it is also a store->load source:
        // after invalidating the rest, seed its own key.
        if (auto *PS = llvh::dyn_cast<PrStoreInst>(&I)) {
          LoadKey k;
          if (keyOfStore(PS, k)) {
            auto it = loadAllocas_.find(k);
            if (it != loadAllocas_.end()) {
              builder.setInsertionPoint(PS);
              builder.createStoreStackInst(PS->getStoredValue(), it->second);
              valid.insert(k);
            }
          }
        }
        continue;
      }

      LoadKey k;
      if (!keyOfLoad(&I, k))
        continue;
      auto it = loadAllocas_.find(k);
      if (it == loadAllocas_.end())
        continue;
      if (valid.insert(k).second) {
        // First available occurrence: populate the mirror.
        builder.setInsertionPointAfter(&I);
        builder.createStoreStackInst(&I, it->second);
      } else {
        // Redundant: read the mirror instead.
        builder.setInsertionPoint(&I);
        I.replaceAllUsesWith(builder.createLoadStackInst(it->second));
        destroyer.add(&I);
        ++NumHeapLoadElim;
        changed = true;
      }
    }

    blockValidLoads_[BB] = std::move(valid);
    return changed;
  }

 public:
  explicit FunctionHeapLoadStoreOptimizer(Function *F) : F_(F) {
    PO_ = postOrderAnalysis(F);
  }

  bool run() {
    createLoadAllocas();
    bool changed = false;
    for (auto *BB : llvh::reverse(PO_))
      changed |= eliminateLoads(BB);
    deleteUnusedAllocas();
    return changed;
  }
};

} // namespace

bool HeapLoadStoreOpts::runOnFunction(Function *F) {
  return FunctionHeapLoadStoreOptimizer(F).run();
}

Pass *hermes::createHeapLoadStoreOpts() {
  return new HeapLoadStoreOpts();
}

#undef DEBUG_TYPE
