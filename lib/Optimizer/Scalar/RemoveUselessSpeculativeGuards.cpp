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
#include "hermes/IRGen/AnnotationLoader.h"
#include "hermes/Optimizer/Scalar/SpeculativeGuardUtils.h"
#include "hermes/Support/Statistic.h"

#include "llvh/ADT/DenseMap.h"
#include "llvh/ADT/STLExtras.h"
#include "llvh/ADT/SmallPtrSet.h"
#include "llvh/ADT/SmallVector.h"
#include "llvh/Support/Debug.h"

using namespace hermes;

using llvh::dbgs;

STATISTIC(NumShapeGuardsRemoved, "Number of useless shape guards removed");
STATISTIC(NumTypeGuardsRemoved, "Number of useless number type guards removed");
STATISTIC(NumTrySetShapeRemoved, "Number of useless try-set-shape removed");

namespace {

/// Starting from \p start, traverse MovLike/Phi instructions (and, when
/// \p followStack is set, the StoreStack -> AllocStack -> LoadStack stack
/// relay) to determine whether a consumer that relies on the guard is
/// reachable. \p exclude is used to skip the guard itself, which is also a
/// user of its operand. Returns true if any guard-dependent consumer exists
/// (in which case the guard cannot be removed). This is only a necessary
/// condition for removing a type guard: a paired UnionNarrowTrustedInst must
/// also be removable, which the caller handles.
bool hasGuardDependentConsumer(
    Value *start,
    Instruction *exclude,
    llvh::function_ref<bool(Instruction *)> relyOnGuard,
    bool followStack) {
  // Literals do not track users; they have no consumers to reach.
  if (!start->tracksUsers())
    return false;
  llvh::SmallPtrSet<Value *, 32> visited;
  llvh::SmallVector<Value *, 32> wl{start};
  while (!wl.empty()) {
    Value *v = wl.pop_back_val();
    if (!visited.insert(v).second)
      continue;
    for (Instruction *user : v->getUsers()) {
      if (user == exclude)
        continue;
      if (isPropagator(user)) {
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
        return true;
    }
  }
  return false;
}

/// Find the single UnionNarrowTrustedInst among the users of \p TOI's argument.
///
/// Tolerates other non-UNT users of the operand (e.g. the deopt-branch
/// ReturnInst that InsertGuard leaves on the original value): only the count of
/// UNT users matters. Returns the unique UNT, or nullptr if there is none or
/// more than one. UNTs already in \p claimed are skipped, so two TypeOfIsInsts
/// cannot both seize the same UNT (which would otherwise double-enqueue it in
/// the destroyer).
UnionNarrowTrustedInst *findPairedNarrow(
    TypeOfIsInst *TOI,
    const llvh::SmallPtrSetImpl<UnionNarrowTrustedInst *> &claimed) {
  Value *arg = TOI->getArgument();
  if (!arg->tracksUsers())
    return nullptr;
  UnionNarrowTrustedInst *unt = nullptr;
  for (Instruction *user : arg->getUsers()) {
    if (user == TOI)
      continue;
    if (auto *cand = llvh::dyn_cast<UnionNarrowTrustedInst>(user)) {
      if (claimed.count(cand))
        continue;
      if (unt)
        return nullptr; // more than one UNT user
      unt = cand;
    }
    // Non-UNT users are tolerated.
  }
  return unt;
}

/// Render a removed guard as "ann#N [kind detail]" for the debug log, using the
/// loaded annotation descriptors. Falls back to a placeholder when the guard
/// was not derived from an annotation (id < 0).
std::string describeAnnotation(const Annotations &ann, int aid) {
  if (aid < 0)
    return "<no-annotation>";
  std::string s = "ann#" + std::to_string(aid);
  if (const AnnotationDescriptor *desc =
          ann.getAnnotationDescriptor(static_cast<unsigned>(aid))) {
    s += " [";
    s += annotationKindLabel(desc->kind);
    s += " ";
    s += desc->detail;
    s += "]";
  }
  return s;
}

} // namespace

bool RemoveUselessSpeculativeGuards::runOnModule(Module *M) {
  IRBuilder builder(M);
  const Annotations &ann = M->getContext().getAnnotations();

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
      // Pinned by PinClosureShapeGuards: drives a closure inline whose PrLoad
      // consumer was DCE'd. Removing it would make the inline unconditional.
      if (HTS->isPinned())
        continue;
      if (hasGuardDependentConsumer(
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
      int aid = HTS->getAnnotationId();
      HTS->replaceAllUsesWith(trueVal);
      destroyer.add(HTS);
      ++NumShapeGuardsRemoved;
      LLVM_DEBUG(
          dbgs() << "\t\tremoved shape guard " << describeAnnotation(ann, aid)
                 << "\n");
      changed = true;
    }

    // A removed type guard must take its paired UnionNarrowTrustedInst with it;
    // otherwise the trusted narrow is left without its guard. Track claimed
    // narrows so two TypeOfIsInsts sharing an operand cannot both grab the same
    // UNT and double-enqueue it.
    llvh::SmallPtrSet<UnionNarrowTrustedInst *, 16> claimedNarrows;
    for (TypeOfIsInst *TOI : typeGuards) {
      // Only the pure-number case is handled; compare TypeOfIsTypes directly.
      if (TOI->getTypes()->getData() != TypeOfIsTypes().withNumber(true))
        continue;
      if (hasGuardDependentConsumer(
              TOI->getArgument(),
              TOI,
              isNumericConsumer,
              /*followStack=*/true))
        continue;

      // The operand must have exactly one paired UNT; otherwise removing only
      // the TypeOfIsInst would leave an unguarded trusted narrow. Per the pass
      // contract, in that case we remove nothing at all.
      UnionNarrowTrustedInst *unt = findPairedNarrow(TOI, claimedNarrows);
      if (!unt)
        continue;

      // The narrow's saved type must be the number the guard checks.
      // InsertGuard pairs always satisfy this; the check guards against
      // oddly-typed narrows.
      if (!unt->getSavedResultType().isNumberType())
        continue;

      claimedNarrows.insert(unt);

      // The narrow is a trusted no-op (its value is the operand), so redirect
      // its downstream users back to the operand; only the type annotation is
      // lost, and hasGuardDependentConsumer verified no FXXX consumes it.
      unt->replaceAllUsesWith(TOI->getArgument());
      destroyer.add(unt);

      int aid = TOI->getAnnotationId();
      TOI->replaceAllUsesWith(trueVal);
      destroyer.add(TOI);
      ++NumTypeGuardsRemoved;
      LLVM_DEBUG(
          dbgs() << "\t\tremoved type guard " << describeAnnotation(ann, aid)
                 << " and its paired UnionNarrowTrustedInst\n");
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
      int aid = TSS->getAnnotationId();
      destroyer.add(TSS); // hasOutput() == false, no uses -> erase directly
      ++NumTrySetShapeRemoved;
      LLVM_DEBUG(
          dbgs() << "\t\tremoved try-set-shape " << describeAnnotation(ann, aid)
                 << "\n");
      changed = true;
    }
  }

  LLVM_DEBUG({
    unsigned total =
        NumShapeGuardsRemoved + NumTypeGuardsRemoved + NumTrySetShapeRemoved;
    dbgs() << "\tRemoveUselessSpeculativeGuards: removed " << total
           << " instruction(s) (" << NumShapeGuardsRemoved << " shape guards, "
           << NumTypeGuardsRemoved << " type guards, " << NumTrySetShapeRemoved
           << " try-set-shape)\n";
  });

  return changed;
}

Pass *hermes::createRemoveUselessSpeculativeGuards() {
  return new RemoveUselessSpeculativeGuards();
}

#undef DEBUG_TYPE
