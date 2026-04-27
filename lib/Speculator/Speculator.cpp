/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#include "hermes/Speculator/Speculator.h"

#include "hermes/IR/Instrs.h"

#include "llvh/ADT/ArrayRef.h"
#include "llvh/ADT/DenseMap.h"
#include "llvh/ADT/SmallPtrSet.h"
#include "llvh/ADT/SmallVector.h"
#include "llvh/Support/Casting.h"
#include "llvh/Support/Debug.h"

#include <algorithm>

#define DEBUG_TYPE "speculator"

using llvh::cast;
using llvh::isa;

namespace hermes {
namespace {

// --- Helpers for sorted vectors of instructions
// ----------------------------------

llvh::SmallVector<Instruction *, 4> sortedInputs(
    const llvh::SmallPtrSet<Instruction *, 4> &inputSet) {
  llvh::SmallVector<Instruction *, 4> result(inputSet.begin(), inputSet.end());
  llvh::sort(result, [](Instruction *a, Instruction *b) { return a < b; });
  return result;
}

bool sameVectors(
    const llvh::SmallVectorImpl<Instruction *> &a,
    const llvh::SmallVectorImpl<Instruction *> &b) {
  if (a.size() != b.size())
    return false;
  for (size_t i = 0; i < a.size(); i++) {
    if (a[i] != b[i])
      return false;
  }
  return true;
}

// --- Phase 0 helpers
// --------------------------------------------------------------

bool isInput(Instruction *I) {
  return isa<LoadParamInst>(I) || isa<LoadFrameInst>(I) ||
      isa<LoadPropertyInst>(I) || isa<CallInst>(I) || isa<CallBuiltinInst>(I);
}

/// Only propagate input-sets through instructions whose result type is a
/// deterministic function of their operand types.
bool shouldPropagate(Instruction *I) {
  return isa<BinaryOperatorInst>(I) || isa<UnaryOperatorInst>(I) ||
      isa<PhiInst>(I) || isa<MovInst>(I) || isa<ImplicitMovInst>(I) ||
      isa<LIRSpillMovInst>(I) || isa<LoadStackInst>(I) ||
      isa<AsNumberInst>(I) || isa<AsNumericInst>(I) ||
      isa<ToPropertyKeyInst>(I) || isa<UnionNarrowTrustedInst>(I) ||
      isa<CheckedTypeCastInst>(I);
}

// --- Phase 1: forward dataflow
// ---------------------------------------------------

llvh::DenseMap<Instruction *, llvh::SmallPtrSet<Instruction *, 4>>
computeInputSets(Function *F, llvh::ArrayRef<Instruction *> inputs) {
  llvh::DenseMap<Instruction *, llvh::SmallPtrSet<Instruction *, 4>> instInputs;
  llvh::SmallVector<Instruction *, 32> worklist;

  // Seed: each input instruction depends on itself.
  for (Instruction *input : inputs) {
    // Inputs also propagate to their users directly (they are the source
    // of unknown types, so every user of an input depends on it even
    // though the input itself is not a shouldPropagate instruction).
    for (Instruction *user : input->getUsers()) {
      instInputs[user].insert(input);
      worklist.push_back(user);
    }
  }

  while (!worklist.empty()) {
    Instruction *inst = worklist.pop_back_val();

    // Never propagate past non-propagating instructions.
    if (!shouldPropagate(inst))
      continue;

    // Snapshot before map inserts below invalidate references.
    llvh::SmallPtrSet<Instruction *, 4> snapshot = instInputs[inst];

    for (Instruction *user : inst->getUsers()) {
      bool grew = false;
      auto &userSet = instInputs[user];
      for (Instruction *inp : snapshot)
        grew |= userSet.insert(inp).second;
      if (grew)
        worklist.push_back(user);
    }
  }

  return instInputs;
}

// --- Phase 2 helpers: type-based checks
// ------------------------------------------

/// Returns the set of types the instruction could be optimized for.
llvh::SmallVector<Type, 4> getOptimizableTypes(Instruction *I) {
  using VK = ValueKind;
  llvh::SmallVector<Type, 4> types;

  switch (I->getKind()) {
    // ---- Arithmetic binary ops ----
    case VK::BinarySubtractInstKind:
    case VK::BinaryMultiplyInstKind:
    case VK::BinaryDivideInstKind:
    case VK::BinaryModuloInstKind:
    case VK::BinaryExponentiationInstKind:
    case VK::BinaryLeftShiftInstKind:
    case VK::BinaryRightShiftInstKind:
    case VK::BinaryUnsignedRightShiftInstKind:
    case VK::BinaryOrInstKind:
    case VK::BinaryXorInstKind:
    case VK::BinaryAndInstKind:
      types.push_back(Type::createNumber());
      break;

    case VK::BinaryAddInstKind:
      types.push_back(Type::createNumber());
      types.push_back(Type::createString());
      break;

    // ---- Unary arithmetic ----
    case VK::UnaryMinusInstKind:
    case VK::UnaryIncInstKind:
    case VK::UnaryDecInstKind:
      types.push_back(Type::createNumber());
      break;

    case VK::UnaryTildeInstKind:
      types.push_back(Type::createNumber());
      break;

    // ---- Comparisons (all return Boolean; optimization is about fast
    //      comparison when both operands share a primitive type) ----
    case VK::BinaryEqualInstKind:
    case VK::BinaryStrictlyNotEqualInstKind:
      types.push_back(Type::createNumber());
      types.push_back(Type::createBigInt());
      types.push_back(Type::createBoolean());
      types.push_back(Type::createString());
      types.push_back(Type::createSymbol());
      types.push_back(Type::createUndefined());
      types.push_back(Type::createNull());
      break;

    case VK::BinaryLessThanInstKind:
    case VK::BinaryLessThanOrEqualInstKind:
    case VK::BinaryGreaterThanInstKind:
    case VK::BinaryGreaterThanOrEqualInstKind:
      types.push_back(Type::createNumber());
      types.push_back(Type::createString());
      break;

    // ---- Conversions ----
    case VK::AsNumberInstKind:
      types.push_back(Type::createNumber());
      break;

    case VK::AsNumericInstKind:
      types.push_back(Type::createNumber());
      types.push_back(Type::createBigInt());
      break;

    case VK::AddEmptyStringInstKind:
      types.push_back(Type::createString());
      break;

    // ---- TypeOf / TypeOfIs ----
    case VK::TypeOfInstKind:
    case VK::TypeOfIsInstKind:
      types.push_back(Type::createNumber());
      types.push_back(Type::createBigInt());
      types.push_back(Type::createBoolean());
      types.push_back(Type::createString());
      types.push_back(Type::createSymbol());
      types.push_back(Type::createUndefined());
      types.push_back(Type::createNull());
      break;

    // ---- Nullish / Object checks ----
    case VK::UnaryBangInstKind:
    case VK::CoerceThisNSInstKind:
    case VK::CondBranchInstKind:
      types.push_back(
          Type::unionTy(Type::createNull(), Type::createUndefined()));
      types.push_back(Type::createObject());
      break;

    // ---- Object ----
    case VK::GetConstructedObjectInstKind:
      types.push_back(Type::createObject());
      break;

    default:
      break;
  }

  return types;
}

/// Returns true if all of I's operands can be type T.
bool allOperandsCanBeType(Instruction *I, Type T) {
  if (auto *CB = llvh::dyn_cast<CondBranchInst>(I))
    return CB->getCondition()->getType().canBeType(T);
  for (unsigned i = 0; i < I->getNumOperands(); i++)
    if (!I->getOperand(i)->getType().canBeType(T))
      return false;
  return true;
}

using SpecOpt = Speculator::SpeculativeOptimization;

// --- Phase 2: type-condition check
// -------------------------------------------------

llvh::SmallVector<SpecOpt, 32> collectCandidates(
    Function *F,
    const llvh::DenseMap<Instruction *, llvh::SmallPtrSet<Instruction *, 4>>
        &instInputs) {
  llvh::SmallVector<SpecOpt, 32> candidates;

  for (auto &BB : *F) {
    for (auto &I : BB) {
      auto it = instInputs.find(&I);
      if (it == instInputs.end() || it->second.empty())
        continue;

      auto optTypes = getOptimizableTypes(&I);
      if (optTypes.empty())
        continue;

      auto inputs = sortedInputs(it->second);

      for (Type T : optTypes) {
        // BinaryAdd + String: result is String if either operand can be
        // String (String + anything = string concat in JS).
        if (I.getKind() == ValueKind::BinaryAddInstKind && T.isStringType()) {
          auto *BI = llvh::cast<BinaryOperatorInst>(&I);
          if (!BI->getLeftHandSide()->getType().canBeString() &&
              !BI->getRightHandSide()->getType().canBeString()) {
            continue;
          }
        } else {
          // All other cases: every operand must be able to take type T.
          if (!allOperandsCanBeType(&I, T)) {
            continue;
          }
        }

        SpecOpt c;
        c.inputs = inputs;
        c.speculativeTypes.push_back(T);
        c.optimizationSites.push_back(&I);
        candidates.push_back(std::move(c));
      }
    }
  }

  return candidates;
}

// --- Phase 3: group by (inputs, type)
// ---------------------------------------------

llvh::SmallVector<SpecOpt, 16> groupByInputsAndType(
    llvh::SmallVector<SpecOpt, 32> &candidates) {
  llvh::SmallVector<SpecOpt, 16> groups;

  for (auto &c : candidates) {
    Type T = c.speculativeTypes[0];
    SpecOpt *found = nullptr;
    for (auto &g : groups) {
      if (sameVectors(g.inputs, c.inputs) && g.speculativeTypes.size() == 1 &&
          g.speculativeTypes[0] == T) {
        found = &g;
        break;
      }
    }

    if (found) {
      found->optimizationSites.push_back(c.optimizationSites[0]);
    } else {
      groups.push_back(std::move(c));
    }
  }

  return groups;
}

// --- Phase 4: merge groups with same (inputs, sites)
// -----------------------------

std::vector<SpecOpt> mergeByInputsAndSites(
    llvh::SmallVector<SpecOpt, 16> &groups) {
  llvh::sort(groups, [](const SpecOpt &a, const SpecOpt &b) {
    if (a.inputs.size() != b.inputs.size())
      return a.inputs.size() < b.inputs.size();
    for (size_t i = 0; i < a.inputs.size(); i++) {
      if (a.inputs[i] != b.inputs[i])
        return a.inputs[i] < b.inputs[i];
    }
    if (a.optimizationSites.size() != b.optimizationSites.size())
      return a.optimizationSites.size() < b.optimizationSites.size();
    for (size_t i = 0; i < a.optimizationSites.size(); i++) {
      if (a.optimizationSites[i] != b.optimizationSites[i])
        return a.optimizationSites[i] < b.optimizationSites[i];
    }
    return false;
  });

  std::vector<SpecOpt> merged;
  for (auto &opt : groups) {
    if (!merged.empty() && sameVectors(merged.back().inputs, opt.inputs) &&
        sameVectors(merged.back().optimizationSites, opt.optimizationSites)) {
      for (Type T : opt.speculativeTypes) {
        if (!llvh::is_contained(merged.back().speculativeTypes, T))
          merged.back().speculativeTypes.push_back(T);
      }
    } else {
      merged.push_back(std::move(opt));
    }
  }

  return merged;
}

} // anonymous namespace

// --- Public entry point
// ----------------------------------------------------------

std::vector<Speculator::SpeculativeOptimization> Speculator::run() {
  // Phase 0: collect input instructions.
  inputs_.clear();
  for (auto &BB : *F_) {
    for (auto &I : BB) {
      if (isInput(&I))
        inputs_.push_back(&I);
    }
  }

  if (inputs_.empty())
    return {};

  // Phase 1: forward dataflow — which inputs reach each instruction?
  auto instInputs = computeInputSets(F_, inputs_);

  // Phase 2: type-condition check.
  auto candidates = collectCandidates(F_, instInputs);

  auto groups = groupByInputsAndType(candidates);

  // Phase 4: merge groups sharing the same (inputs, sites).
  auto result = mergeByInputsAndSites(groups);
  return result;
}

} // namespace hermes
