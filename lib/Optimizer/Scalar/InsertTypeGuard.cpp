/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#define DEBUG_TYPE "insert-type-guard"

#include "hermes/Optimizer/Scalar/InsertTypeGuard.h"

#include "hermes/IR/Analysis.h"
#include "hermes/IR/CFG.h"
#include "hermes/IR/IRBuilder.h"
#include "hermes/IR/Instrs.h"
#include "hermes/Support/Statistic.h"

#include "llvh/ADT/DenseMap.h"
#include "llvh/ADT/DenseSet.h"
#include "llvh/Support/Debug.h"

#include <queue>

using namespace hermes;
using llvh::dbgs;

STATISTIC(NumTypeGuardsInserted, "Number of TypeGuard instructions inserted");
STATISTIC(NumFunctionsDuplicated, "Number of functions with duplicated paths");

namespace {

/// Helper class to manage the duplication and insertion process
class TypeGuardInserter {
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
  explicit TypeGuardInserter(Function *F)
      : F_(F), M_(F->getParent()), Builder_(F) {}

  /// Main entry point: perform the type guard insertion
  bool run() {
    // Step 1: Check for unsupported constructs
    if (hasUnsupportedConstruct())
      return false;

    // Step 2: Collect all instructions with type guards
    llvh::SmallVector<std::pair<Instruction *, Type>, 4> guardInsts;
    collectTypeGuardInsts(guardInsts);

    if (guardInsts.empty())
      return false;

    LLVM_DEBUG(
        dbgs() << "InsertTypeGuard: " << F_->getInternalName() << " with "
               << guardInsts.size() << " guards\n");

    // Step 3: Duplicate all instructions and basic blocks
    // Original becomes speculative (stays in place), copy becomes general
    if (!duplicateFunction())
      return false;

    // Step 4: Insert TypeGuard instructions at each guard point
    for (auto &pair : guardInsts) {
      Instruction *guardInst = pair.first;
      Type expectedType = pair.second;

      if (!insertTypeGuardInst(guardInst, expectedType))
        return false;
      ++NumTypeGuardsInserted;
    }

    // Step 5: Delete unreachable blocks (now gen entry parts)
    deleteUnreachableBlocks();

    // Step 6: Handle AllocStackInst dominance issues
    // (must be after deleteUnreachableBlocks, before fixDominanceInvariants)
    hoistAllocStackInsts();

    // Step 7: Fix dominance invariants by inserting PHI nodes
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

  /// Collect all instructions with type guards
  void collectTypeGuardInsts(
      llvh::SmallVectorImpl<std::pair<Instruction *, Type>> &guardInsts) {
    for (auto &BB : *F_) {
      for (auto &I : BB) {
        if (M_->hasTypeGuard(&I)) {
          Type type = M_->getTypeGuard(&I);
          LLVM_DEBUG(
              dbgs() << "  Guard on " << I.getKindStr() << ": " << type
                     << " inst=" << &I << "\n");
          guardInsts.push_back({&I, type});
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
      specBB->setSpeculative(true); // Original = speculative
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

  /// Insert TypeGuard instruction after guardInst in speculative path
  /// guardInst is in spec path (original), find gen version via
  /// specToGenInstMap_
  bool insertTypeGuardInst(Instruction *guardInst, Type expectedType) {
    // guardInst is in spec path (original)
    // Find gen version via reverse mapping
    auto it = specToGenInstMap_.find(guardInst);
    assert(
        it != specToGenInstMap_.end() &&
        "guardInst must be in specToGenInstMap_");
    Instruction *guardInst_gen = it->second;

    BasicBlock *specBB = guardInst->getParent();
    BasicBlock *genBB = guardInst_gen->getParent();
    assert(specBB && genBB && "guardInst must have parent BB");

    // Find the split point: skip all FirstInBlock instructions after guardInst
    // TypeGuard cannot be inserted between FirstInBlock instructions (e.g.,
    // Phi)
    Instruction *splitAfter_spec = guardInst;
    Instruction *splitAfter_gen = guardInst_gen;

    auto specIt = guardInst->getIterator();
    ++specIt;
    while (specIt != specBB->end() &&
           specIt->getSideEffect().getFirstInBlock()) {
      splitAfter_spec = &*specIt;
      ++specIt;
    }

    auto genIt = guardInst_gen->getIterator();
    ++genIt;
    while (genIt != genBB->end() && genIt->getSideEffect().getFirstInBlock()) {
      splitAfter_gen = &*genIt;
      ++genIt;
    }

    // Split both BBs after the (adjusted) split point
    BasicBlock *specBB_continue = splitBlockAfter(specBB, splitAfter_spec);
    BasicBlock *genBB_continue = splitBlockAfter(genBB, splitAfter_gen);

    // Remove the unconditional branch created by split
    if (auto *specTerm = specBB->getTerminator())
      specTerm->eraseFromParent();

    // Insert TypeGuard in spec block: true → spec continuation, false → gen
    // continuation
    Builder_.setInsertionBlock(specBB);
    Builder_.createTypeGuardInst(
        guardInst, expectedType, specBB_continue, genBB_continue);

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
      if (BB.isSpeculative())
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

  /// Check if a BB is on the speculative path
  bool isSpeculativeBB(BasicBlock *BB) {
    return BB->isSpeculative();
  }

  /// Collect broken uses by finding general insts and their uses.
  void collectBrokenUses(
      llvh::DenseMap<
          Instruction *,
          llvh::SmallVector<std::pair<Instruction *, unsigned>, 4>> &brokenUses,
      DominanceInfo &DT) {
    for (auto &BB : *F_) {
      // Skip speculative and unreachable BBs
      if (BB.isSpeculative() || !DT.getNode(&BB))
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

  /// Split a basic block after the given instruction
  /// Returns the new continuation block
  BasicBlock *splitBlockAfter(BasicBlock *BB, Instruction *I) {
    auto it = I->getIterator();
    ++it;

    if (it == BB->end())
      return nullptr;

    // Create a new BB for the continuation, inheriting speculative attribute
    BasicBlock *continueBB = Builder_.createBasicBlock(F_);
    continueBB->setSpeculative(BB->isSpeculative());

    // Move instructions from (I+1) to end into continueBB
    // This includes the terminator, so continueBB will have the same successors
    // as original BB
    Builder_.setInsertionBlock(continueBB);
    while (it != BB->end()) {
      Instruction *inst = &*it;
      ++it; // Increment before moving
      inst->removeFromParent();
      inst->setParent(continueBB);
      continueBB->getInstList().push_back(inst);
    }

    // Add an unconditional branch from BB to continueBB
    Builder_.setInsertionBlock(BB);
    Builder_.createBranchInst(continueBB);

    // Fix all uses of BB in PHI nodes
    // Collect users first to avoid iterator invalidation during update
    llvh::SmallVector<Instruction *, 4> users;
    for (auto it = BB->users_begin(), end = BB->users_end(); it != end; ++it) {
      users.push_back(*it);
    }

    for (Instruction *user : users) {
      if (auto *phi = llvh::dyn_cast<PhiInst>(user)) {
        // Update all PHI entries that reference BB to reference continueBB
        for (unsigned i = 0, e = phi->getNumEntries(); i < e; ++i) {
          auto entry = phi->getEntry(i);
          if (entry.second == BB) {
            phi->updateEntry(i, entry.first, continueBB);
          }
        }
      }
    }

    return continueBB;
  }
};

} // anonymous namespace

bool InsertTypeGuard::runOnFunction(Function *F) {
  TypeGuardInserter inserter(F);
  return inserter.run();
}

Pass *hermes::createInsertTypeGuard() {
  return new InsertTypeGuard();
}
