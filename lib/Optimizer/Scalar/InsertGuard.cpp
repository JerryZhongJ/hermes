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
#include "llvh/ADT/MapVector.h"
#include "llvh/ADT/STLExtras.h"
#include "llvh/Support/Debug.h"

#include <queue>

using namespace hermes;
using llvh::dbgs;

STATISTIC(NumTypeGuardsInserted, "Number of TypeGuard instructions inserted");
STATISTIC(NumShapeGuardsInserted, "Number of ShapeGuard instructions inserted");
STATISTIC(
    NumClosureTargetGuardsInserted,
    "Number of ClosureTargetGuard instructions inserted");
STATISTIC(NumFunctionsDuplicated, "Number of functions with duplicated paths");

namespace {

/// Helper class to manage the duplication and insertion process
class GuardInserter {
  Function *F_;
  IRBuilder Builder_;

  /// Mapping: general (copy) → speculative (original)
  /// Same direction as the old speculativeInstMap_
  llvh::DenseMap<Instruction *, Instruction *> genToSpecInstMap_;
  llvh::DenseMap<BasicBlock *, BasicBlock *> genToSpecBBMap_;

  /// Reverse mapping: speculative (original) → general (copy)
  /// Used when we need to find gen from spec
  llvh::DenseMap<Instruction *, Instruction *> specToGenInstMap_;
  llvh::DenseMap<BasicBlock *, BasicBlock *> specToGenBBMap_;

  llvh::SmallVector<TypeOfIsInst *, 4> collectedTypeChecks_;
  llvh::SmallVector<HasStaticShapeInst *, 4> collectedShapeChecks_;
  llvh::SmallVector<HasClosureTargetInst *, 4> collectedClosureTargetChecks_;

  /// Static shapes that have at least one TrySetStaticShapeInst somewhere in
  /// the module. A Has guard whose shape isn't in this set can never pass (the
  /// shape was never bound), so we skip duplicating a speculative path for it.
  /// Collected once per function from the whole module (see collectTrySetShapes).
  llvh::DenseSet<const StaticShapeDesc *> trySetShapes_;

 public:
  explicit GuardInserter(Function *F) : F_(F), Builder_(F) {}

  /// Main entry point: perform the guard insertion
  bool run() {
    // Step 1: Check for unsupported constructs
    if (hasUnsupportedConstruct()) {
      LLVM_DEBUG(
          dbgs() << "InsertGuard: skipping " << F_->getInternalName()
                 << " (has try-catch)\n");
      return false;
    }

    // Step 2: Collect all instructions with guards.
    collectTrySetShapes();
    collectChecks();

    if (collectedTypeChecks_.empty() && collectedShapeChecks_.empty() &&
        collectedClosureTargetChecks_.empty())
      return false;

    LLVM_DEBUG(
        dbgs() << "InsertGuard: " << F_->getInternalName() << " with "
               << collectedTypeChecks_.size() << " type guards, "
               << collectedShapeChecks_.size() << " shape guards, "
               << collectedClosureTargetChecks_.size()
               << " closure target guards\n");

    // Step 4: Duplicate all instructions and basic blocks
    // Original becomes speculative (stays in place), copy becomes general
    if (!duplicateFunction())
      return false;

    // Step 5: Insert guards. Each guard is removed from its collection before
    // insertion so updates to remaining collected guards never visit it.
    while (!collectedShapeChecks_.empty()) {
      HasStaticShapeInst *checkInst = collectedShapeChecks_.pop_back_val();
      NumShapeGuardsInserted += insertShapeGuard(checkInst);
    }
    while (!collectedClosureTargetChecks_.empty()) {
      HasClosureTargetInst *checkInst =
          collectedClosureTargetChecks_.pop_back_val();
      NumClosureTargetGuardsInserted += insertClosureTargetGuard(checkInst);
    }
    while (!collectedTypeChecks_.empty()) {
      TypeOfIsInst *checkInst = collectedTypeChecks_.pop_back_val();
      NumTypeGuardsInserted += insertTypeGuard(checkInst);
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

  /// Collect every static shape that has at least one TrySetStaticShapeInst in
  /// the module. A Has guard whose shape was never bound can never pass, so we
  /// don't duplicate a speculative path for it (see collectChecks).
  void collectTrySetShapes() {
    for (auto &F : *F_->getParent())
      for (auto &BB : F)
        for (auto &I : BB)
          if (auto *TSS = llvh::dyn_cast<TrySetStaticShapeInst>(&I))
            trySetShapes_.insert(TSS->getShape()->getData());
  }

  /// Collect all annotation check instructions.
  void collectChecks() {
    for (auto &BB : *F_) {
      for (auto &I : BB) {
        if (auto *TOI = llvh::dyn_cast<TypeOfIsInst>(&I)) {
          int annotId = TOI->getAnnotationId();
          if (annotId < 0)
            continue;
          LLVM_DEBUG(
              dbgs() << "  Type guard check inst=" << TOI << " [ann#" << annotId
                     << "]\n");
          collectedTypeChecks_.push_back(TOI);
          continue;
        }

        if (auto *HTS = llvh::dyn_cast<HasStaticShapeInst>(&I)) {
          int annotId = HTS->getAnnotationId();
          if (annotId < 0)
            continue;
          // Skip guards whose shape was never bound (no TrySet anywhere): they
          // can never pass, so duplicating a speculative path is wasted work.
          if (!trySetShapes_.count(HTS->getShape()->getData())) {
            LLVM_DEBUG(
                dbgs() << "  Skipping shape guard [ann#" << annotId
                       << "]: shape has no TrySet binding\n");
            continue;
          }
          LLVM_DEBUG(
              dbgs() << "  Shape guard check inst=" << HTS << " [ann#"
                     << annotId << "]\n");
          collectedShapeChecks_.push_back(HTS);
          continue;
        }

        if (auto *HCT = llvh::dyn_cast<HasClosureTargetInst>(&I)) {
          int annotId = HCT->getAnnotationId();
          if (annotId < 0)
            continue;
          LLVM_DEBUG(
              dbgs() << "  Closure target guard check inst=" << HCT << " [ann#"
                     << annotId << "]\n");
          collectedClosureTargetChecks_.push_back(HCT);
        }
      }
    }
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

  /// Shared logic for block splitting and CFG update.
  BasicBlock *insertGuardImpl(
      Instruction *checkInst,
      Instruction *checkInstGen) {
    BasicBlock *specBB = checkInst->getParent();

    auto splitBefore_spec = checkInst->getIterator();
    ++splitBefore_spec;

    auto splitBefore_gen = checkInstGen->getIterator();
    ++splitBefore_gen;

    // Split both BBs after the check.
    BasicBlock *specBB_continue = splitBlockBefore(splitBefore_spec);
    BasicBlock *genBB_continue = splitBlockBefore(splitBefore_gen);

    // Remove the unconditional branch created by split.
    if (auto *specTerm = specBB->getTerminator())
      specTerm->eraseFromParent();

    // Use the existing check in specBB: true → spec continuation, false → gen
    // continuation.
    Builder_.setInsertionBlock(specBB);
    auto *cbi = Builder_.createCondBranchInst(
        checkInst, specBB_continue, genBB_continue);
    cbi->setLikelihood(BranchLikelihood::LikelyTrue);

    specToGenBBMap_[specBB_continue] = genBB_continue;
    genToSpecBBMap_[genBB_continue] = specBB_continue;

    return specBB_continue;
  }

  /// Create a trusted narrow at the start of a guard's successful continuation
  /// and redirect only uses dominated by that continuation. Uses before the
  /// guard must retain the original value to avoid use-before-def.
  UnionNarrowTrustedInst *insertTrustedNarrow(
      Instruction *checkInst,
      Value *checkedValue,
      BasicBlock *specBBContinue,
      Type narrowedType,
      Function *closureTarget = nullptr) {
    Builder_.setInsertionPoint(&specBBContinue->front());
    auto *narrowInst =
        Builder_.createUnionNarrowTrustedInst(nullptr, narrowedType);
    narrowInst->setClosureTarget(closureTarget);

    auto *checkedInst = llvh::dyn_cast<Instruction>(checkedValue);
    if (checkedInst && &*(--checkInst->getIterator()) == checkedInst) {
      // Fast path: every other use executes after the adjacent guard, so replace
      // them all and then restore the guard's own checked-value operand.
      checkedInst->replaceAllUsesWith(narrowInst);
      for (unsigned i = 0, e = checkInst->getNumOperands(); i < e; ++i) {
        if (checkInst->getOperand(i) == narrowInst)
          checkInst->setOperand(checkedValue, i);
      }
    } else {
      // Slow path: preserve uses between the value and its guard. Redirect only
      // users dominated by the successful continuation to avoid use-before-def.
      DominanceInfo DT(F_);
      llvh::SmallVector<std::pair<Instruction *, unsigned>, 8> toReplace;
      for (auto *userInst : checkedValue->getUsers()) {
        if (!userInst || userInst == checkInst || userInst == narrowInst)
          continue;
        if (!DT.dominates(specBBContinue, userInst->getParent()))
          continue;
        for (unsigned i = 0, e = userInst->getNumOperands(); i < e; ++i) {
          if (userInst->getOperand(i) == checkedValue)
            toReplace.push_back({userInst, i});
        }
      }
      for (auto [userInst, idx] : toReplace)
        userInst->setOperand(narrowInst, idx);
    }

    narrowInst->setOperand(
        checkedValue, UnionNarrowTrustedInst::SingleOperandIdx);
    return narrowInst;
  }

  /// Insert TypeGuard branch for an existing TypeOfIsInst in the speculative
  /// path.
  bool insertTypeGuard(TypeOfIsInst *checkInst) {
    llvh::Optional<Type> expectedType =
        typeOfIsTypesToIRType(checkInst->getTypes()->getData());
    assert(expectedType && "annotated TypeOfIsInst must map to an IR type");

    auto it = specToGenInstMap_.find(checkInst);
    assert(
        it != specToGenInstMap_.end() &&
        "checkInst must be in specToGenInstMap_");
    auto *checkInstGen = llvh::cast<TypeOfIsInst>(it->second);

    BasicBlock *specBBContinue = insertGuardImpl(checkInst, checkInstGen);
    insertTrustedNarrow(
        checkInst,
        checkInst->getArgument(),
        specBBContinue,
        Type::intersectTy(*expectedType, Type::createAnyType()));
    return true;
  }

  /// Insert ClosureTargetGuard and attach its proven function identity to the
  /// trusted object value in the successful continuation.
  bool insertClosureTargetGuard(HasClosureTargetInst *checkInst) {
    auto it = specToGenInstMap_.find(checkInst);
    assert(
        it != specToGenInstMap_.end() &&
        "checkInst must be in specToGenInstMap_");
    auto *checkInstGen = llvh::cast<HasClosureTargetInst>(it->second);

    BasicBlock *specBBContinue = insertGuardImpl(checkInst, checkInstGen);
    insertTrustedNarrow(
        checkInst,
        checkInst->getArgument(),
        specBBContinue,
        Type::createObject(),
        checkInst->getClosureTarget());
    return true;
  }

  /// Insert ShapeGuard branch for an existing HasStaticShapeInst in the
  /// speculative path.
  bool insertShapeGuard(HasStaticShapeInst *checkInst) {
    auto it = specToGenInstMap_.find(checkInst);
    assert(
        it != specToGenInstMap_.end() &&
        "checkInst must be in specToGenInstMap_");
    auto *checkInstGen = llvh::cast<HasStaticShapeInst>(it->second);
    insertGuardImpl(checkInst, checkInstGen);
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

    // Collect broken uses: key = broken inst, value = vector of <user, opIdx>.
    // MapVector (not DenseMap): deterministic iteration order keeps per-block
    // PHI ordering stable across runs.
    llvh::MapVector<
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
      llvh::MapVector<
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
