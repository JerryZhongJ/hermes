/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#define DEBUG_TYPE "insert-type-guard"

#include "hermes/Optimizer/Scalar/InsertGuard.h"

#include "hermes/IR/Analysis.h"
#include "hermes/IR/CFG.h"
#include "hermes/IR/IRBuilder.h"
#include "hermes/IR/Instrs.h"
#include "hermes/Optimizer/Scalar/Utils.h"
#include "hermes/Support/Statistic.h"
#include "llvh/ADT/DenseMap.h"
#include "llvh/ADT/DenseSet.h"
#include "llvh/ADT/STLExtras.h"
#include "llvh/Support/Debug.h"

#include <queue>
#include <tuple>

using namespace hermes;
using llvh::dbgs;

STATISTIC(NumTypeGuardsInserted, "Number of TypeGuard instructions inserted");
STATISTIC(NumShapeGuardsInserted, "Number of ShapeGuard instructions inserted");
STATISTIC(NumFunctionsDuplicated, "Number of functions with duplicated paths");

namespace {

TypeOfIsTypes getTypeOfIsTypesFromType(const Type &type) {
  TypeOfIsTypes result;
  if (type.canBeNumber())
    result = result.withNumber(true);
  if (type.canBeString())
    result = result.withString(true);
  if (type.canBeBoolean())
    result = result.withBoolean(true);
  if (type.canBeObject())
    result = result.withObject(true).withFunction(true);
  if (type.canBeNull())
    result = result.withNull(true);
  if (type.canBeUndefined())
    result = result.withUndefined(true);
  if (type.canBeBigInt())
    result = result.withBigint(true);
  if (type.canBeSymbol())
    result = result.withSymbol(true);
  return result;
}

/// Helper class to manage the duplication and insertion process
class GuardInserter {
  Function *F_;
  Module *M_;
  IRBuilder Builder_;

  /// Mapping: general (copy) → speculative (original)
  /// Same direction as the old speculativeInstMap_
  llvh::DenseMap<Instruction *, Instruction *> genToSpecInstMap_;
  llvh::DenseMap<BasicBlock *, BasicBlock *> genToSpecBBMap_;

  /// Reverse mapping: speculative (original) → general (copy)
  /// Used when we need to find gen from spec
  llvh::DenseMap<Instruction *, Instruction *> specToGenInstMap_;
  llvh::DenseMap<BasicBlock *, BasicBlock *> specToGenBBMap_;

 public:
  explicit GuardInserter(Function *F)
      : F_(F), M_(F->getParent()), Builder_(F) {}

  /// Main entry point: perform the guard insertion
  bool run() {
    // Step 1: Check for unsupported constructs
    if (hasUnsupportedConstruct()) {
      LLVM_DEBUG(
          dbgs() << "InsertGuard: skipping " << F_->getInternalName()
                 << " (has try-catch)\n");
      return false;
    }

    // Step 2: Collect all instructions with guards
    llvh::SmallVector<std::tuple<Instruction *, Type, int>, 2> typeGuardInsts =
        collectTypeGuardInsts();
    llvh::SmallVector<std::tuple<Instruction *, const TypedShapeDesc *, int>, 2>
        shapeGuardInsts = collectShapeGuardInsts();

    if (typeGuardInsts.empty() && shapeGuardInsts.empty())
      return false;

    LLVM_DEBUG(
        dbgs() << "InsertGuard: " << F_->getInternalName() << " with "
               << typeGuardInsts.size() << " type guards, "
               << shapeGuardInsts.size() << " shape guards\n");

    // Step 4: Duplicate all instructions and basic blocks
    // Original becomes speculative (stays in place), copy becomes general
    if (!duplicateFunction())
      return false;

    // Step 5: Insert shape guards (before type guards to avoid conflicts
    // on the same instruction).
    for (auto &tuple : shapeGuardInsts) {
      Instruction *guardInst = std::get<0>(tuple);
      const TypedShapeDesc *desc = std::get<1>(tuple);
      int annotId = std::get<2>(tuple);
      NumShapeGuardsInserted += insertShapeGuard(guardInst, desc, annotId);
    }

    // Step 6: Insert type guards
    for (auto &tuple : typeGuardInsts) {
      Instruction *guardInst = std::get<0>(tuple);
      auto expectedType = std::get<1>(tuple);
      int annotId = std::get<2>(tuple);
      NumTypeGuardsInserted +=
          insertTypeGuard(guardInst, expectedType, annotId);
    }

    // Step 7: Delete unreachable blocks (now gen entry parts)
    deleteUnreachableBlocks();

    // Step 8: Handle AllocStackInst dominance issues
    // (must be after deleteUnreachableBlocks, before fixDominanceInvariants)
    hoistAllocStackInsts();

    // Step 9: Fix dominance invariants by inserting PHI nodes
    fixDominanceInvariants();

    ++NumFunctionsDuplicated;
    return true;
  }

 private:
  /// Check if function contains unsupported constructs
  bool hasUnsupportedConstruct() {
    for (auto &BB : *F_) {
      for (auto &I : BB) {
        // Try-catch: breaks exception handling structure
        if (llvh::isa<TryStartInst>(&I) || llvh::isa<CatchInst>(&I))
          return true;
        // AllocStackInst is now supported via hoistAllocStackInsts()
      }
    }
    return false;
  }

  bool isInGeneralPath(BasicBlock *BB) {
    return genToSpecBBMap_.find(BB) != genToSpecBBMap_.end();
  }

  /// Collect all instructions with type guards
  llvh::SmallVector<std::tuple<Instruction *, Type, int>, 2>
  collectTypeGuardInsts() {
    llvh::SmallVector<std::tuple<Instruction *, Type, int>, 2> guardInsts;
    for (auto &BB : *F_) {
      for (auto &I : BB) {
        auto type = M_->getTypeGuard(&I);
        if (type.isNoType())
          continue;
        if (!I.hasUsers()) {
          LLVM_DEBUG(
              dbgs() << "  Skipping guard on " << I.getKindStr()
                     << " (no users)\n");
          continue;
        }
        int annotId = M_->getTypeGuardAnnotationId(&I);
        LLVM_DEBUG(
            dbgs() << "  Guard on " << I.getKindStr() << ": " << type
                   << " inst=" << &I
                   << (annotId >= 0 ? " [ann#" + std::to_string(annotId) + "]"
                                    : "")
                   << "\n");
        guardInsts.push_back({&I, type, annotId});
      }
    }
    return guardInsts;
  }

  /// Collect all instructions with shape guards.
  llvh::SmallVector<std::tuple<Instruction *, const TypedShapeDesc *, int>, 2>
  collectShapeGuardInsts() {
    llvh::SmallVector<std::tuple<Instruction *, const TypedShapeDesc *, int>, 2>
        guardInsts;
    for (auto &BB : *F_) {
      for (auto &I : BB) {
        auto *desc = M_->getShapeGuard(&I);
        if (!desc)
          continue;
        // If this instruction also has a type guard, skip shape guard
        // (type guard takes precedence).
        if (!M_->getTypeGuard(&I).isNoType())
          continue;
        if (!I.hasUsers()) {
          LLVM_DEBUG(
              dbgs() << "  Skipping shape guard on " << I.getKindStr()
                     << " (no users)\n");
          continue;
        }
        int annotId = M_->getShapeGuardAnnotationId(&I);
        LLVM_DEBUG(
            dbgs() << "  Shape guard on " << I.getKindStr() << " inst=" << &I
                   << (annotId >= 0 ? " [ann#" + std::to_string(annotId) + "]"
                                    : "")
                   << "\n");
        guardInsts.push_back({&I, desc, annotId});
      }
    }
    return guardInsts;
  }

  /// Duplicate the function: original becomes speculative, copy becomes general
  /// This preserves original block order, so CreateArgumentsInst stays in place
  bool duplicateFunction() {
    // Collect all BBs first to avoid iterator invalidation
    llvh::SmallVector<BasicBlock *, 16> originalBBs;
    for (auto &BB : *F_) {
      originalBBs.push_back(&BB);
    }

    // Step 1: Mark original blocks as speculative, create general copies
    for (BasicBlock *specBB : originalBBs) {
      auto *genBB = Builder_.createBasicBlock(F_); // Copy = general

      // Bidirectional mapping
      genToSpecBBMap_[genBB] = specBB;
      specToGenBBMap_[specBB] = genBB;
    }

    // Step 2: Clone instructions to general path (without operand translation)
    // Just copy instructions with original operands and establish bidirectional
    // mapping.
    for (BasicBlock *specBB : originalBBs) {
      BasicBlock *genBB = specToGenBBMap_[specBB];
      Builder_.setInsertionBlock(genBB);

      for (auto &I : *specBB) {
        // Collect original operands
        llvh::SmallVector<Value *, 4> operands;
        for (unsigned i = 0, e = I.getNumOperands(); i < e; ++i) {
          operands.push_back(I.getOperand(i));
        }

        // Clone with original operands (no translation yet)
        Instruction *genInst = Builder_.cloneInst(&I, operands);

        // Bidirectional mapping
        genToSpecInstMap_[genInst] = &I;
        specToGenInstMap_[&I] = genInst;
      }
    }

    // Step 3: Update all operands in gen instructions
    // Now that all instructions are cloned and mapped, we can safely translate
    // operands.
    for (BasicBlock *specBB : originalBBs) {
      BasicBlock *genBB = specToGenBBMap_[specBB];
      for (auto &genInst : *genBB) {
        for (unsigned i = 0, e = genInst.getNumOperands(); i < e; ++i) {
          Value *op = genInst.getOperand(i);

          if (auto *opInst = llvh::dyn_cast<Instruction>(op)) {
            auto it = specToGenInstMap_.find(opInst);
            assert(
                it != specToGenInstMap_.end() &&
                "Inst operand must be in specToGenInstMap_");
            genInst.setOperand(it->second, i);
          } else if (auto *opBB = llvh::dyn_cast<BasicBlock>(op)) {
            auto it = specToGenBBMap_.find(opBB);
            assert(
                it != specToGenBBMap_.end() &&
                "BB operand must be in specToGenBBMap_");
            genInst.setOperand(it->second, i);
          }
          // Other operands (literals, parameters, etc.) stay unchanged
        }
      }
    }

    LLVM_DEBUG(
        dbgs() << "  Duplicated " << genToSpecInstMap_.size() << " insts\n");
    return true;
  }

  /// Shared logic for block splitting, narrowing, check insertion and CFG
  /// update. The two callbacks are invoked at the correct insertion points.
  void insertGuardImpl(
      Instruction *guardInst,
      Instruction *guardInst_gen,
      llvh::function_ref<Instruction *()> createCheck,
      llvh::function_ref<SingleOperandInst *()> createNarrow) {
    BasicBlock *specBB = guardInst->getParent();
    BasicBlock *genBB = guardInst_gen->getParent();
    assert(specBB && genBB && "guardInst must have parent BB");

    // Find split point: skip all FirstInBlock instructions after guardInst.
    auto splitBefore_spec = guardInst->getIterator();
    ++splitBefore_spec;
    while (splitBefore_spec != specBB->end() &&
           splitBefore_spec->getSideEffect().getFirstInBlock()) {
      ++splitBefore_spec;
    }

    auto splitBefore_gen = guardInst_gen->getIterator();
    ++splitBefore_gen;
    while (splitBefore_gen != genBB->end() &&
           splitBefore_gen->getSideEffect().getFirstInBlock()) {
      ++splitBefore_gen;
    }

    // Split both BBs after the (adjusted) split point.
    BasicBlock *specBB_continue = splitBlockBefore(splitBefore_spec);
    BasicBlock *genBB_continue = splitBlockBefore(splitBefore_gen);

    // In specBB_continue, insert narrowing inst and replace uses.
    Builder_.setInsertionBlock(specBB_continue);
    Builder_.setInsertionPoint(&specBB_continue->front());
    auto *narrowInst = createNarrow();
    guardInst->replaceAllUsesWith(narrowInst);
    narrowInst->setOperand(guardInst, 0);

    // Remove the unconditional branch created by split.
    if (auto *specTerm = specBB->getTerminator())
      specTerm->eraseFromParent();

    // Insert check in specBB: true → spec continuation, false → gen
    // continuation.
    Builder_.setInsertionBlock(specBB);
    auto *checkInst = createCheck();
    auto *cbi = Builder_.createCondBranchInst(
        checkInst, specBB_continue, genBB_continue);
    cbi->setLikelihood(BranchLikelihood::LikelyTrue);

    specToGenBBMap_[specBB_continue] = genBB_continue;
    genToSpecBBMap_[genBB_continue] = specBB_continue;
  }

  /// Insert TypeGuard instruction after guardInst in speculative path
  /// guardInst is in spec path (original), find gen version via
  /// specToGenInstMap_
  bool insertTypeGuard(Instruction *guardInst, Type expectedType, int annotId) {
    // Early exit if the guardInst type is already a subset of expectedType,
    // or if they are disjoint (no intersection).
    Type guardType = guardInst->getType();

    if (guardType.isSubsetOf(expectedType)) {
      LLVM_DEBUG(
          dbgs() << "  Skipping guard: " << guardInst->getKindStr() << " type "
                 << guardType << " is subset of expected " << expectedType
                 << "\n");
      return false;
    }

    if (Type::intersectTy(guardType, expectedType).isNoType()) {
      LLVM_DEBUG(
          dbgs() << "  Skipping guard: " << guardInst->getKindStr() << " type "
                 << guardType << " has no intersection with expected "
                 << expectedType << "\n");
      return false;
    }

    auto it = specToGenInstMap_.find(guardInst);
    assert(
        it != specToGenInstMap_.end() &&
        "guardInst must be in specToGenInstMap_");
    Instruction *guardInst_gen = it->second;

    auto *typeLit = Builder_.getLiteralTypeOfIsTypes(
        getTypeOfIsTypesFromType(expectedType));
    insertGuardImpl(
        guardInst,
        guardInst_gen,
        [&]() { return Builder_.createTypeOfIsInst(guardInst, typeLit); },
        [&]() {
          return Builder_.createUnionNarrowTrustedInst(nullptr, expectedType);
        });
    return true;
  }

  /// Insert ShapeGuard instruction after guardInst in speculative path.
  bool insertShapeGuard(
      Instruction *guardInst,
      const TypedShapeDesc *desc,
      int annotId) {
    auto it = specToGenInstMap_.find(guardInst);
    assert(
        it != specToGenInstMap_.end() &&
        "guardInst must be in specToGenInstMap_");
    Instruction *guardInst_gen = it->second;

    LiteralTypedShape *litShape = M_->getLiteralTypedShape(desc);
    insertGuardImpl(
        guardInst,
        guardInst_gen,
        [&]() { return Builder_.createIsTypedShapeInst(guardInst, litShape); },
        [&]() { return Builder_.createAssertTypedShapeInst(nullptr, desc); });
    return true;
  }

  /// Delete unreachable blocks (now gen entry parts) and fix uses by replacing
  /// them with speculative (original) copies.
  void deleteUnreachableBlocks() {
    // Build dominator tree - unreachable blocks will have no node
    DominanceInfo DT(F_);

    // Collect unreachable blocks
    llvh::SmallVector<BasicBlock *, 8> unreachableBlocks;
    for (auto &BB : *F_) {
      if (!DT.getNode(&BB))
        unreachableBlocks.push_back(&BB);
    }

    LLVM_DEBUG(
        dbgs() << "  Deleted " << unreachableBlocks.size()
               << " unreachable blocks\n");

    // For each unreachable block, fix uses then delete
    for (auto *BB : unreachableBlocks) {
      // Replace all uses of gen instructions with spec copies
      // Use genToSpecInstMap_ to find spec version
      for (auto &I : *BB) {
        auto specIt = genToSpecInstMap_.find(&I);
        if (specIt != genToSpecInstMap_.end())
          I.replaceAllUsesWith(specIt->second);
      }

      // Remove block from PHI nodes
      Value::UseListTy users(BB->getUsers().begin(), BB->getUsers().end());
      for (auto *user : users) {
        if (auto *phi = llvh::dyn_cast<PhiInst>(user))
          phi->removeEntry(BB);
      }

      BB->replaceAllUsesWith(nullptr);
      BB->eraseFromParent();
    }
  }

  bool simplifyPhiInsts() {
    bool changed = false;
    bool localChanged;
    do {
      localChanged = false;
      for (auto &BB : *F_) {
        IRBuilder::InstructionDestroyer destroyer;
        for (auto &I : BB) {
          auto *P = llvh::dyn_cast<PhiInst>(&I);
          if (!P)
            break;

          // The PHI has a single incoming value. Replace all uses of the PHI
          // with the incoming value.
          if (auto *incoming = getSinglePhiValue(P)) {
            localChanged = true;
            P->replaceAllUsesWith(incoming);
            destroyer.add(P);
          }
        }
      }
      changed |= localChanged;
    } while (localChanged);

    return changed;
  }
  /// Fix dominance invariants by inserting PHI nodes
  void fixDominanceInvariants() {
    DominanceInfo DT(F_);

    llvh::DenseMap<DominanceInfoNode *, unsigned> domTreeLevels;
    computeDomTreeLevels(&DT, domTreeLevels);

    // Collect broken uses: key = broken inst, value = vector of <user, opIdx>
    llvh::DenseMap<
        Instruction *,
        llvh::SmallVector<std::pair<Instruction *, unsigned>, 4>>
        brokenUses;
    collectBrokenUses(brokenUses, DT);

    LLVM_DEBUG(
        dbgs() << "  Fixed " << brokenUses.size()
               << " broken dominance relations\n");

    for (auto &pair : brokenUses) {
      fixBrokenInst(pair.first, pair.second, DT, domTreeLevels);
    }
    simplifyPhiInsts();
  }

  /// Handle AllocStackInst dominance issues.
  /// Case 1: generalASI unreachable -> already handled by
  /// deleteUnreachableBlocks Case 2: generalASI reachable but doesn't dominate
  /// some uses -> handled here
  void hoistAllocStackInsts() {
    DominanceInfo DT(F_);

    // Collect ASIs that need processing (avoid modifying while iterating)
    llvh::SmallVector<AllocStackInst *, 4> toProcess;

    // Iterate over general path basic blocks (skip speculative blocks)
    for (auto &BB : *F_) {
      if (!isInGeneralPath(&BB))
        continue;

      for (auto &I : BB) {
        auto *generalASI = llvh::dyn_cast<AllocStackInst>(&I);
        if (!generalASI)
          continue;

        // Find corresponding specASI via map (gen → spec)
        auto specIt = genToSpecInstMap_.find(generalASI);
        if (specIt == genToSpecInstMap_.end())
          continue;

        if (!llvh::isa<AllocStackInst>(specIt->second))
          continue;

        // Check if generalASI dominates all its uses
        bool allDominated = true;
        for (auto *user : generalASI->getUsers()) {
          if (!DT.properlyDominates(generalASI, user)) {
            allDominated = false;
            break;
          }
        }

        if (!allDominated)
          toProcess.push_back(generalASI);
      }
    }

    LLVM_DEBUG(
        dbgs() << "  Hoisting " << toProcess.size() << " AllocStackInsts\n");

    // Process ASIs that need merging
    for (auto *generalASI : toProcess) {
      auto *specASI = llvh::cast<AllocStackInst>(genToSpecInstMap_[generalASI]);

      BasicBlock *generalBB = generalASI->getParent();
      BasicBlock *specBB = specASI->getParent();

      // Find nearest common dominator of the two ASIs
      BasicBlock *targetBB = DT.findNearestCommonDominator(generalBB, specBB);
      if (!targetBB)
        continue;

      // Move specASI to targetBB (skip FirstInBlock instructions)
      for (auto &loc : *targetBB) {
        if (!loc.getSideEffect().getFirstInBlock()) {
          specASI->moveBefore(&loc);
          break;
        }
      }

      // Replace all uses of generalASI with specASI
      generalASI->replaceAllUsesWith(specASI);

      // Delete generalASI
      generalASI->eraseFromParent();
    }
  }

  /// Compute dominator tree levels (DFS traversal)
  void computeDomTreeLevels(
      DominanceInfo *DT,
      llvh::DenseMap<DominanceInfoNode *, unsigned> &domTreeLevels) {
    llvh::SmallVector<DominanceInfoNode *, 32> worklist;
    DominanceInfoNode *root = DT->getRootNode();

    // Root starts at zero
    domTreeLevels[root] = 0;
    worklist.push_back(root);

    // DFS traverse the dominator tree
    while (!worklist.empty()) {
      DominanceInfoNode *node = worklist.pop_back_val();
      unsigned childLevel = domTreeLevels[node] + 1;

      // Assign level to children
      for (auto &child : *node) {
        domTreeLevels[child] = childLevel;
        worklist.push_back(child);
      }
    }
  }

  /// Collect broken uses by finding general insts and their uses.
  void collectBrokenUses(
      llvh::DenseMap<
          Instruction *,
          llvh::SmallVector<std::pair<Instruction *, unsigned>, 4>> &brokenUses,
      DominanceInfo &DT) {
    for (auto &BB : *F_) {
      // Skip speculative and unreachable BBs
      if (!isInGeneralPath(&BB) || !DT.getNode(&BB))
        continue;

      for (auto &I : BB) {
        for (Instruction *userInst : I.getUsers()) {
          if (!userInst)
            continue;

          // PHI: incoming value must dominate incoming block
          if (auto *phi = llvh::dyn_cast<PhiInst>(userInst)) {
            for (unsigned i = 0, e = phi->getNumEntries(); i < e; ++i) {
              auto entry = phi->getEntry(i);
              if (entry.first != &I)
                continue;
              if (!DT.dominates(I.getParent(), entry.second))
                brokenUses[&I].push_back({phi, i});
            }
          } else {
            // Regular: operand must properly dominate user
            if (!DT.getNode(userInst->getParent()))
              continue;

            for (unsigned i = 0, e = userInst->getNumOperands(); i < e; ++i) {
              if (userInst->getOperand(i) != &I)
                continue;
              if (!DT.properlyDominates(&I, userInst))
                brokenUses[&I].push_back({userInst, i});
            }
          }
        }
      }
    }
  }

  /// Compute dominance frontier and insert PHIs for a logical value
  /// (both general inst and its spec inst, like multiple stores to same stack)
  void insertPhisForInst(
      Instruction *generalInst,
      llvh::DenseMap<BasicBlock *, PhiInst *> &phiMap,
      DominanceInfo &DT,
      llvh::DenseMap<DominanceInfoNode *, unsigned> &domTreeLevels) {
    using NodePriorityQueue = std::priority_queue<
        std::pair<DominanceInfoNode *, unsigned>,
        std::vector<std::pair<DominanceInfoNode *, unsigned>>,
        llvh::less_second>;

    NodePriorityQueue PQ;
    llvh::SmallPtrSet<DominanceInfoNode *, 32> visited;
    llvh::SmallPtrSet<BasicBlock *, 16> phiBlocks;
    llvh::SmallVector<DominanceInfoNode *, 32> worklist;

    // Add general inst definition point to PQ
    if (auto *genDefNode = DT.getNode(generalInst->getParent()))
      PQ.push({genDefNode, domTreeLevels[genDefNode]});

    // Also add spec inst definition point to PQ
    auto specIt = genToSpecInstMap_.find(generalInst);
    if (specIt != genToSpecInstMap_.end()) {
      if (auto *specDefNode = DT.getNode(specIt->second->getParent()))
        PQ.push({specDefNode, domTreeLevels[specDefNode]});
    }

    if (PQ.empty())
      return;

    // Compute dominance frontier using Sreedhar-Gao algorithm
    while (!PQ.empty()) {
      DominanceInfoNode *root = PQ.top().first;
      unsigned rootLevel = PQ.top().second;
      PQ.pop();

      // Traverse dominator tree subtree rooted at root
      worklist.clear();
      worklist.push_back(root);

      while (!worklist.empty()) {
        DominanceInfoNode *node = worklist.pop_back_val();
        BasicBlock *BB = node->getBlock();

        // Check each CFG successor
        for (auto *succ : successors(BB)) {
          DominanceInfoNode *succNode = DT.getNode(succ);
          if (!succNode)
            continue;

          // Skip D-edges (dominator tree edges)
          if (succNode->getIDom() == node)
            continue;

          // Only process J-edges with level <= rootLevel
          unsigned succLevel = domTreeLevels[succNode];
          if (succLevel > rootLevel)
            continue;

          // Avoid duplicate visits
          if (!visited.insert(succNode).second)
            continue;

          // succ is on dominance frontier, insert PHI
          if (phiBlocks.insert(succ).second) {
            PQ.push({succNode, succLevel}); // Recursively process new PHI
          }
        }

        // Add dominator tree children to worklist
        for (auto &child : *node) {
          if (!visited.count(child))
            worklist.push_back(child);
        }
      }
    }

    // Create PHI nodes
    createPhisForInst(generalInst, phiBlocks, phiMap, DT);
  }

  /// Create and populate PHI nodes
  void createPhisForInst(
      Instruction *inst,
      llvh::SmallPtrSet<BasicBlock *, 16> &phiBlocks,
      llvh::DenseMap<BasicBlock *, PhiInst *> &phiMap,
      DominanceInfo &DT) {
    // Create PHI nodes
    for (auto *BB : phiBlocks) {
      Builder_.setInsertionPoint(&BB->front());
      auto *phi = Builder_.createPhiInst();
      phi->setType(inst->getType());
      phiMap[BB] = phi;
    }

    // Populate PHI incoming values
    for (auto *BB : phiBlocks) {
      auto *phi = phiMap[BB];

      llvh::SmallVector<BasicBlock *, 4> preds(predecessors(BB));
      llvh::SmallPtrSet<BasicBlock *, 4> processed;

      for (auto *pred : preds) {
        if (!processed.insert(pred).second)
          continue; // Skip duplicate predecessors

        // Get live-out value from predecessor
        Value *val = getLiveOutValue(pred, inst, phiMap, DT);
        phi->addEntry(val, pred);
      }
    }
  }

  /// Find the live-out value of originalInst at BB
  Value *getLiveOutValue(
      BasicBlock *BB,
      Instruction *originalInst,
      llvh::DenseMap<BasicBlock *, PhiInst *> &phiMap,
      DominanceInfo &DT) {
    // Walk up the dominator tree to find the nearest definition
    for (DominanceInfoNode *node = DT.getNode(BB); node;
         node = node->getIDom()) {
      BasicBlock *currBB = node->getBlock();

      // Priority 1: If speculative definition exists in currBB, return it
      auto instIt = genToSpecInstMap_.find(originalInst);
      if (instIt != genToSpecInstMap_.end() &&
          instIt->second->getParent() == currBB)
        return instIt->second;

      // Priority 2: If this is original definition's block, return original
      if (originalInst->getParent() == currBB)
        return originalInst;

      // Priority 3: If currBB has PHI definition, return PHI
      auto phiIt = phiMap.find(currBB);
      if (phiIt != phiMap.end())
        return phiIt->second;
    }

    // Definition not found (unreachable code or parameter)
    return Builder_.getLiteralUndefined();
  }

  /// Find the live-in value of originalInst at BB
  Value *getLiveInValue(
      BasicBlock *BB,
      Instruction *originalInst,
      llvh::DenseMap<BasicBlock *, PhiInst *> &phiMap,
      DominanceInfo &DT) {
    // If BB itself has PHI definition, return PHI
    auto phiIt = phiMap.find(BB);
    if (phiIt != phiMap.end())
      return phiIt->second;

    // Otherwise find live-out value from idom
    auto *node = DT.getNode(BB);
    if (!node) {
      return Builder_.getLiteralUndefined();
    }

    auto *idom = node->getIDom();
    if (!idom) {
      return Builder_.getLiteralUndefined();
    }

    return getLiveOutValue(idom->getBlock(), originalInst, phiMap, DT);
  }

  /// Replace all uses of a single broken instruction
  void replaceUsesOfInst(
      Instruction *generalInst,
      llvh::SmallVector<std::pair<Instruction *, unsigned>, 4> &uses,
      llvh::DenseMap<BasicBlock *, PhiInst *> &phiMap,
      DominanceInfo &DT) {
    for (auto &usePair : uses) {
      Instruction *user = usePair.first;
      unsigned idx = usePair.second;

      Value *replacement;

      if (auto *phi = llvh::dyn_cast<PhiInst>(user)) {
        // PHI special handling: idx is entry index (not operand index!)
        // Use incoming block's live-out value
        auto entry = phi->getEntry(idx);
        BasicBlock *incomingBlock = entry.second;
        replacement = getLiveOutValue(incomingBlock, generalInst, phiMap, DT);
        // Use updateEntry to correctly update value while preserving block
        phi->updateEntry(idx, replacement, incomingBlock);
      } else {
        // Regular instruction: idx is operand index
        replacement =
            getLiveInValue(user->getParent(), generalInst, phiMap, DT);
        user->setOperand(replacement, idx);
      }
    }
  }

  /// Fix dominance violations for a single broken instruction
  void fixBrokenInst(
      Instruction *generalInst,
      llvh::SmallVector<std::pair<Instruction *, unsigned>, 4> &uses,
      DominanceInfo &DT,
      llvh::DenseMap<DominanceInfoNode *, unsigned> &domTreeLevels) {
    llvh::DenseMap<BasicBlock *, PhiInst *> phiMap;
    insertPhisForInst(generalInst, phiMap, DT, domTreeLevels);
    replaceUsesOfInst(generalInst, uses, phiMap, DT);
  }

  /// Split a basic block before the given instruction
  /// Returns the new continuation block
  BasicBlock *splitBlockBefore(BasicBlock::iterator it) {
    assert(
        it->getSideEffect().getFirstInBlock() == false &&
        "Cannot split before FirstInBlock instruction");
    auto BB = it->getParent();
    assert(it != BB->end() && "BB should be splitted before the terminator");

    // Create a new BB for the continuation, inheriting speculative attribute
    BasicBlock *continueBB = Builder_.createBasicBlock(F_);

    // Move instructions from (I+1) to end into continueBB
    // This includes the terminator, so continueBB will have the same successors
    // as original BB
    Builder_.setInsertionBlock(continueBB);
    while (it != BB->end()) {
      Instruction *inst = &*it;
      ++it; // Increment before moving
      Builder_.transferInstructionToCurrentBlock(inst);
    }

    // Add an unconditional branch from BB to continueBB
    Builder_.setInsertionBlock(BB);
    Builder_.createBranchInst(continueBB);

    return continueBB;
  }
};

} // anonymous namespace

bool InsertGuard::runOnFunction(Function *F) {
  GuardInserter inserter(F);
  return inserter.run();
}

Pass *hermes::createInsertGuard() {
  return new InsertGuard();
}
