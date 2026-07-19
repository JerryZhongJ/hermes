/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#ifndef HERMES_OPTIMIZER_SCALAR_SPECULATIVEGUARDUTILS_H
#define HERMES_OPTIMIZER_SCALAR_SPECULATIVEGUARDUTILS_H

#include "hermes/FrontEndDefs/MathBuiltinProps.h"
#include "hermes/IR/IR.h"
#include "hermes/IR/Instrs.h"

#include "llvh/ADT/SmallPtrSet.h"
#include "llvh/ADT/SmallVector.h"
#include "llvh/Support/Casting.h"

namespace hermes {

/// MovLike: a single-operand instruction that transparently forwards its
/// value at runtime (Mov, ImplicitMov, UnionNarrowTrusted). Shape/type
/// narrowing propagates through these. (AsNumber/CoerceThisNS convert the
/// value, so they are NOT MovLike.)
///
/// asMovLike returns the instruction as SingleOperandInst* (so callers can
/// reach its forwarded operand); isMovLike is the boolean form.
inline SingleOperandInst *asMovLike(Instruction *I) {
  if (llvh::isa<MovInst>(I) || llvh::isa<ImplicitMovInst>(I) ||
      llvh::isa<UnionNarrowTrustedInst>(I))
    return static_cast<SingleOperandInst *>(I);
  return nullptr;
}

inline bool isMovLike(Instruction *I) {
  return asMovLike(I) != nullptr;
}

/// Propagator: MovLike + Phi. Shape/type narrowing propagates through these.
/// Stack relay (StoreStack→AllocStack→LoadStack) is handled separately by
/// walkReachableConsumers / hasGuardDependentConsumer.
inline bool isPropagator(Instruction *I) {
  return isMovLike(I) || llvh::isa<PhiInst>(I);
}

/// A useful consumer of a number type guard: FXXX float families (FAdd/FSub/
/// FMul/FDiv/FMod + FNegate + FCompare) + pure-numeric Math.* CallBuiltin
/// (e.g. Math.floor, whose arguments are consumed as doubles).
inline bool isNumericConsumer(Instruction *I) {
  if (llvh::isa<FBinaryMathInst>(I) || llvh::isa<FUnaryMathInst>(I) ||
      llvh::isa<FCompareInst>(I))
    return true;
  if (auto *CB = llvh::dyn_cast<CallBuiltinInst>(I))
    return isPureNumericMathBuiltin(CB->getBuiltinIndex());
  return false;
}

/// A useful consumer of a shape guard: PrLoad/PrStore (always useful — typed
/// property accesses), or generic Load/StoreProperty/HasStaticShape with a
/// non-Any inferred objOperandShape.
inline bool objectOperandKnownShape(Instruction *I) {
  // PrLoad/PrStore read a typed slot directly; TypedLoadParent reads
  // [[Prototype]] with no proxy/null guard, so it relies on its operand being a
  // static-shape object (the guard's invariant).
  if (llvh::isa<PrLoadInst>(I) || llvh::isa<PrStoreInst>(I) ||
      llvh::isa<TypedLoadParentInst>(I))
    return true;
  StaticShapeInfo shape;
  if (auto *L = llvh::dyn_cast<BaseLoadPropertyInst>(I))
    shape = L->getObjOperandShape();
  else if (auto *S = llvh::dyn_cast<BaseStorePropertyInst>(I))
    shape = S->getObjOperandShape();
  else if (auto *H = llvh::dyn_cast<HasStaticShapeInst>(I))
    shape = H->getObjOperandShape();
  else if (auto *LP = llvh::dyn_cast<LoadParentInst>(I))
    shape = LP->getObjOperandShape();
  else
    return false;
  return shape.status != StaticShapeInfo::AnyShapes;
}

/// Traverse from \p start along propagators (MovLike/Phi + stack relay
/// StoreStack→AllocStack→LoadStack), visiting every reachable instruction.
/// Consumers (non-propagators) are visited but not traversed further.
/// Used by annotation-dryrun to find all guard-dependent consumers.
template <typename Visitor>
void walkReachableConsumers(Value *start, Visitor visit) {
  if (!start->tracksUsers())
    return; // Literals don't track users (getUsers would assert).
  llvh::SmallPtrSet<Value *, 32> visited;
  llvh::SmallVector<Value *, 32> wl;
  for (Instruction *U : start->getUsers())
    wl.push_back(U);
  while (!wl.empty()) {
    Value *v = wl.pop_back_val();
    if (!visited.insert(v).second)
      continue;
    auto *I = llvh::dyn_cast<Instruction>(v);
    if (!I)
      continue;
    visit(I);
    if (isPropagator(I)) {
      for (Instruction *U : I->getUsers())
        wl.push_back(U);
    } else if (auto *store = llvh::dyn_cast<StoreStackInst>(I)) {
      wl.push_back(store->getPtr()); // value spilled to stack → trace slot
    } else if (llvh::isa<LoadStackInst>(I) || llvh::isa<AllocStackInst>(I)) {
      for (Instruction *U : I->getUsers())
        wl.push_back(U);
    }
  }
}

} // namespace hermes

#endif // HERMES_OPTIMIZER_SCALAR_SPECULATIVEGUARDUTILS_H
