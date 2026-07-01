/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#define DEBUG_TYPE "remove-useless-speculative-guards"

#include "hermes/Optimizer/Scalar/RemoveUselessSpeculativeGuards.h"

#include "hermes/IR/IRBuilder.h"
#include "hermes/IR/Instrs.h"
#include "hermes/Support/Statistic.h"

#include "llvh/ADT/DenseMap.h"
#include "llvh/ADT/STLExtras.h"
#include "llvh/ADT/SmallPtrSet.h"
#include "llvh/ADT/SmallVector.h"
#include "llvh/Support/Debug.h"

using namespace hermes;

STATISTIC(NumShapeGuardsRemoved, "Number of useless shape guards removed");
STATISTIC(NumTypeGuardsRemoved, "Number of useless number type guards removed");
STATISTIC(NumTrySetShapeRemoved, "Number of useless try-set-shape removed");

namespace {

/// A MovLike instruction transparently forwards its single operand at runtime
/// (the value's carrier is unchanged; it only renames or annotates a type).
/// Mov is the explicit move; ImplicitMovInst emits no bytecode; and
/// UnionNarrowTrustedInst is a trusted type narrowing with no runtime effect.
/// All three carry mov semantics and must be traversed by the use-chain.
/// (AsNumber/CoerceThisNS and friends convert the value, so they are not
/// MovLike.)
bool isMovLike(Instruction *I) {
  return llvh::isa<MovInst>(I) || llvh::isa<ImplicitMovInst>(I) ||
      llvh::isa<UnionNarrowTrustedInst>(I);
}

/// Starting from \p start, traverse MovLike/Phi instructions (and, when
/// \p followStack is set, the StoreStack -> AllocStack -> LoadStack stack
/// relay) to decide whether a "useful consumer" is reachable. \p exclude is
/// used to skip the guard itself, which is also a user of its operand.
bool canSafelyRemove(
    Value *start,
    Instruction *exclude,
    llvh::function_ref<bool(Instruction *)> relyOnGuard,
    bool followStack) {
  // Literals do not track users; they have no consumers to reach.
  if (!start->tracksUsers())
    return true;
  llvh::SmallPtrSet<Value *, 32> visited;
  llvh::SmallVector<Value *, 32> wl{start};
  while (!wl.empty()) {
    Value *v = wl.pop_back_val();
    if (!visited.insert(v).second)
      continue;
    for (Instruction *user : v->getUsers()) {
      if (user == exclude)
        continue;
      if (isMovLike(user) || llvh::isa<PhiInst>(user)) {
        wl.push_back(user); // transparent relay, keep tracing
        continue;
      }
      if (followStack) {
        if (auto *store = llvh::dyn_cast<StoreStackInst>(user)) {
          wl.push_back(store->getPtr()); // value spilled to stack -> trace slot
          continue;
        }
        if (llvh::isa<LoadStackInst>(user) || llvh::isa<AllocStackInst>(user)) {
          wl.push_back(user); // stack load / the slot itself -> trace its users
          continue;
        }
      }
      if (relyOnGuard(user))
        return false;
    }
  }
  return true;
}

/// Useful-consumer predicate for a shape guard.
bool objectOperandKnownShape(Instruction *I) {
  // PrLoad/PrStore derive directly from Instruction (no objOperandShape); they
  // are typed property accesses and always count as useful consumers.
  if (llvh::isa<PrLoadInst>(I) || llvh::isa<PrStoreInst>(I))
    return true;
  // Generic Load/StoreProperty and HasStaticShape carry an objOperandShape that
  // must be non-Any (i.e. inferred KnownStaticShape) to be a useful consumer.
  StaticShapeInfo shape;
  if (auto *L = llvh::dyn_cast<BaseLoadPropertyInst>(I))
    shape = L->getObjOperandShape();
  else if (auto *S = llvh::dyn_cast<BaseStorePropertyInst>(I))
    shape = S->getObjOperandShape();
  else if (auto *H = llvh::dyn_cast<HasStaticShapeInst>(I))
    shape = H->getObjOperandShape();
  else
    return false;
  return shape.status != StaticShapeInfo::AnyShapes;
}

/// Useful-consumer predicate for a number type guard: the FXXX float families.
bool isFXXX(Instruction *I) {
  // classof uses HERMES_IR_KIND_IN_CLASS, so isa matches the whole family.
  return llvh::isa<FBinaryMathInst>(I) || // FAdd/FSub/FMul/FDiv/FMod
      llvh::isa<FUnaryMathInst>(I) || // FNegate
      llvh::isa<FCompareInst>(I); // FEqual/FNotEqual/F</F<=/F>/F>=
}

} // namespace

bool RemoveUselessSpeculativeGuards::runOnModule(Module *M) {
  IRBuilder builder(M);

  llvh::SmallVector<HasStaticShapeInst *, 16> shapeGuards;
  llvh::SmallVector<TypeOfIsInst *, 16> typeGuards;
  llvh::SmallVector<TrySetStaticShapeInst *, 16> trysets;

  // LiteralStaticShape is a Literal, which does not track users (see
  // Value::tracksUsers), so getUsers() cannot enumerate its users. Instead we
  // count each shape's non-tryset users while scanning; the count is
  // decremented when a shape guard is removed, so a zero count means the shape
  // has no guarding consumer left.
  llvh::DenseMap<LiteralStaticShape *, unsigned> nonTrySetShapeUserCount;

  for (Function &F : *M) {
    for (BasicBlock &BB : F) {
      for (Instruction &I : BB) {
        if (auto *HTS = llvh::dyn_cast<HasStaticShapeInst>(&I)) {
          if (HTS->getAnnotationId() >= 0)
            shapeGuards.push_back(HTS);
        } else if (auto *TOI = llvh::dyn_cast<TypeOfIsInst>(&I)) {
          if (TOI->getAnnotationId() >= 0)
            typeGuards.push_back(TOI);
        }
        if (auto *TSS = llvh::dyn_cast<TrySetStaticShapeInst>(&I))
          trysets.push_back(TSS);

        bool isTrySet = llvh::isa<TrySetStaticShapeInst>(I);
        for (unsigned i = 0, e = I.getNumOperands(); i < e; ++i) {
          auto *shape = llvh::dyn_cast<LiteralStaticShape>(I.getOperand(i));
          if (shape && !isTrySet)
            ++nonTrySetShapeUserCount[shape];
        }
      }
    }
  }

  bool changed = false;
  LiteralBool *trueVal = builder.getLiteralBool(true);

  // Step 1: judge + delete guards. A dedicated destroyer scope makes this
  // "judge-all, then erase-all", keeping inter-guard judgements consistent.
  {
    IRBuilder::InstructionDestroyer destroyer;

    for (HasStaticShapeInst *HTS : shapeGuards) {
      if (!canSafelyRemove(
              HTS->getArgument(),
              HTS,
              objectOperandKnownShape,
              /*followStack=*/false))
        continue;
      // This guard is one non-tryset user of its shape; account for its removal
      // before erasing.
      auto it = nonTrySetShapeUserCount.find(HTS->getShape());
      if (it != nonTrySetShapeUserCount.end() && it->second > 0)
        --it->second;
      HTS->replaceAllUsesWith(trueVal);
      destroyer.add(HTS);
      ++NumShapeGuardsRemoved;
      changed = true;
    }

    for (TypeOfIsInst *TOI : typeGuards) {
      // Only the pure-number case is handled; compare TypeOfIsTypes directly.
      if (TOI->getTypes()->getData() != TypeOfIsTypes().withNumber(true))
        continue;
      if (!canSafelyRemove(
              TOI->getArgument(), TOI, isFXXX, /*followStack=*/true))
        continue;
      TOI->replaceAllUsesWith(trueVal);
      destroyer.add(TOI);
      ++NumTypeGuardsRemoved;
      changed = true;
    }
  } // guards are erased here.

  // Step 2: judge + delete trysets. Useless shape guards are gone and the count
  // is up to date; a zero count means the shape no longer has any non-tryset
  // user (nothing guards it), so the try-set is pure overhead.
  {
    IRBuilder::InstructionDestroyer destroyer;
    for (TrySetStaticShapeInst *TSS : trysets) {
      auto it = nonTrySetShapeUserCount.find(TSS->getShape());
      if (it != nonTrySetShapeUserCount.end() && it->second > 0)
        continue; // still guarded by a non-tryset user, keep it
      destroyer.add(TSS); // hasOutput() == false, no uses -> erase directly
      ++NumTrySetShapeRemoved;
      changed = true;
    }
  }

  return changed;
}

Pass *hermes::createRemoveUselessSpeculativeGuards() {
  return new RemoveUselessSpeculativeGuards();
}
