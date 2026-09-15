/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

// annotation-dryrun: 给 annotator 的 agent 用的编译反馈工具（C++ 侧）。
//
// 流程：parse → 加载标注 → IRGen → 裁剪 pipeline（前半段，跳过 inlining）
//       → 遍历 IR 产出结构化 JSON（stdout）。
//
// 设计要点（见 plans/todo-speculator-md-gentle-zephyr.md）：
// - 不 -dump-ir 文本 diff，直接遍历 IR 数据结构产 JSON。
// - 裁剪 pipeline：只跑反映标注效果的前半段 pass，大文件从 13s 降到 ~1s。
// - 载入失败（①）由 MCP 层解析本工具的 stderr（AnnotationLoader 的 errs()），
//   C++ 侧零额外改动。
// - 标注带来的优化（②）/ shape 阻挡（③）/ 未生效（④）由后续 Stage 在
//  遍历 IR 时按 annotationId 归因。本文件是 Stage 1 骨架 + 基础快照。

#include "../shermes/ParseJSFile.h"

#include "hermes/AST/Context.h"
#include "hermes/AST/TransformAST.h"
#include "hermes/IR/CFG.h"
#include "hermes/IR/IR.h"
#include "hermes/IR/IRVerifier.h"
#include "hermes/IR/Instrs.h"
#include "hermes/IRGen/AnnotationLoader.h"
#include "hermes/IRGen/IRGen.h"
#include "hermes/Optimizer/PassManager/Pipeline.h"
#include "hermes/Optimizer/Scalar/SpeculativeGuardUtils.h"
#include "hermes/Runtime/Libhermes.h"
#include "hermes/Sema/SemContext.h"
#include "hermes/Sema/SemResolve.h"
#include "hermes/SourceMap/SourceMapTranslator.h"
#include "hermes/Support/SourceErrorManager.h"

#include "llvh/Support/Casting.h"
#include "llvh/Support/CommandLine.h"
#include "llvh/Support/InitLLVM.h"
#include "llvh/Support/JSON.h"
#include "llvh/Support/MemoryBuffer.h"
#include "llvh/Support/raw_ostream.h"

#include "../../lib/Optimizer/Scalar/StaticShapeInferenceRunner.h"

#include "llvh/ADT/DenseMap.h"
#include "llvh/ADT/SmallPtrSet.h"
#include "llvh/ADT/SmallVector.h"

#include <algorithm>
#include <map>
#include <set>
#include <string>
#include <vector>

using namespace hermes;
namespace cl = llvh::cl;

namespace {

cl::OptionCategory DryrunCategory("annotation-dryrun Options");

cl::list<std::string> InputFilenames(
    cl::Positional,
    cl::desc("<input files>"),
    cl::cat(DryrunCategory));

cl::opt<std::string> AnnotationFile(
    "annotation-file",
    cl::desc(
        "JSON annotation file (static shapes / type guards / shape guards / shape bindings)"),
    cl::init(""),
    cl::cat(DryrunCategory));

cl::opt<bool> VerifyIR(
    "verify-ir",
    cl::desc("Verify IR before analysis"),
    cl::init(false),
    cl::cat(DryrunCategory));

cl::opt<int> FromLine(
    "from-line",
    cl::desc("1-based start line (inclusive); 0 = no lower bound"),
    cl::init(0),
    cl::cat(DryrunCategory));

cl::opt<int> ToLine(
    "to-line",
    cl::desc("1-based end line (inclusive); 0 = no upper bound"),
    cl::init(0),
    cl::cat(DryrunCategory));

cl::list<std::string> CustomPasses(
    "passes",
    cl::CommaSeparated,
    cl::desc("override the front-half feedback pass list (debug)"),
    cl::cat(DryrunCategory));

// 标注效果反馈 pipeline：让标注产生的 guard 真正生效（type 窄化→FXX、
// shape→PrLoad/PrStore、closure target→call 直连），但不跑
// inlining/cse/scopehoisting（大文件 13s→1s 的主因）。关键：标注的对象常经
// frame（StoreFrame/LoadFrame），必须先 frameloadstoreopts + simplemem2reg +
// scopeelimination 让 shape/窄化穿透到 property 访问，再跑两轮 shape+type
// 推断 + simplify 换快路径。lowerbuiltincallsoptimized 紧跟 insertguard 之后：
// 把 Math.sqrt 等全局 builtin 调用降为 CallBuiltinInst（同时删掉
// TryLoadGlobalProperty+Call），这样后续 type inference 能把它们认作
// numeric、不再误判为 shape blockage。尾部 functionanalysis 让 closure
// target guard 证明的函数身份传播到 call（target 直连，不内联本体），
// coverage 才能把这类 call 记为 optimized。
// 故意不跑 removeuselessspeculativeguards：保留 guard，③ 的 collectKills 才能
// 复用 StaticShapeInference 重新注入 shape、定位 polluting 阻挡（guard 被删
// 则无 edge fact，shape 无法重建）。④ useless 由排除法判定，不靠该 pass。
// pass 名取自 Passes.def；用 runCustomOptimizationPasses 复用现成 API。
static const std::vector<std::string> kFeedbackPasses = {
    "insertguard",
    "simplestackpromotion",
    "lowerbuiltincallsoptimized",
    "frameloadstoreopts",
    "heaploadstoreopts",
    "simplemem2reg",
    "scopeelimination",
    "localtypeandstaticshapeinference",
    "typeinference",
    "instsimplify",
    "dce",
    "simplifycfg",
    "simplestackpromotion",
    "frameloadstoreopts",
    "heaploadstoreopts",
    "localtypeandstaticshapeinference",
    "typeinference",
    "instsimplify",
    // Tail propagation round: without CSE + one more inference sweep the
    // coverage report under-counts guards whose facts only reach their
    // consumers through the later full-pipeline rounds (e.g. entry guards
    // covering reads deep inside loops). Still no RemoveUselessSpeculative
    // Guards: collectKills must see every guard.
    "cse",
    "localtypeandstaticshapeinference",
    "typeinference",
    "instsimplify",
    // Closure target guards: propagate the proven function identity from the
    // guarded UnionNarrowTrusted to its calls (target direct-connect). No
    // inlining follows, so this stays cheap.
    "functionanalysis",
};

std::vector<std::string> getPassList() {
  if (!CustomPasses.empty())
    return std::vector<std::string>(CustomPasses.begin(), CustomPasses.end());
  return kFeedbackPasses;
}

std::shared_ptr<Context> createContext() {
  auto context = std::make_shared<Context>();
  context->setStrictMode(false);
  context->setDebugInfoSetting(DebugInfoSetting::NONE);
  context->setStaticBuiltinOptimization(true);
  return context;
}

ESTree::NodePtr parseJSFiles(
    std::shared_ptr<Context> &context,
    sema::SemContext &semCtx,
    const DeclarationFileListTy &ambientDecls,
    std::vector<std::unique_ptr<llvh::MemoryBuffer>> fileBufs) {
  std::vector<ESTree::ProgramNode *> programs{};
  std::shared_ptr<SourceMapTranslator> sourceMapTranslator = nullptr;

  bool parseError = false;
  for (std::unique_ptr<llvh::MemoryBuffer> &fileBuf : fileBufs) {
    if (ESTree::ProgramNode *parsedAST = parseJSFile(
            context.get(),
            SourceMappingCommentMode::Off,
            StaticBuiltinSetting::AutoDetect,
            context->getSourceErrorManager().addNewSourceBuffer(
                std::move(fileBuf)),
            {},
            sourceMapTranslator)) {
      programs.push_back(parsedAST);
    } else {
      parseError = true;
    }
  }

  if (parseError || programs.empty())
    return nullptr;

  if (sourceMapTranslator)
    context->getSourceErrorManager().setTranslator(sourceMapTranslator);

  ESTree::ProgramNode *parsedAST = programs[0];
  if (programs.size() > 1) {
    ESTree::NodeList &allStmts = parsedAST->_body;
    for (size_t i = 1, e = programs.size(); i < e; ++i)
      allStmts.splice(allStmts.end(), programs[i]->_body);
  }

  parsedAST = llvh::cast<ESTree::ProgramNode>(
      hermes::transformASTForCompilation(*context, parsedAST));
  if (!parsedAST)
    return nullptr;

  if (!sema::resolveAST(*context, semCtx, nullptr, parsedAST, ambientDecls))
    return nullptr;

  return parsedAST;
}

// 把指令的 debug location 解析成 "line:col"。无位置返回空串。
// 列号在 UTF-8 下是字符索引（与 AnnotationLoader 消费侧一致）。
std::string locStr(Instruction *I, SourceErrorManager &sm) {
  SMLoc loc = I->getLocation();
  if (!loc.isValid())
    return "";
  SourceErrorManager::SourceCoords c;
  if (!sm.findBufferLineAndLoc(loc, c))
    return "";
  return std::to_string(c.line) + ":" + std::to_string(c.col);
}

struct Effect {
  std::string location;
  std::string
      instruction; // 原始 IR 指令名（PrLoadInst/BinaryLessThanInst/…）；
                   // category 分类 + 人类渲染全在 MCP 层
  std::string property; // 仅 PrLoad/PrStore 有
};
struct AnnFeedback {
  std::vector<Effect> optimizations; // ②（可多条）
  std::vector<Effect> blockages; // ③（可多条，与 optimizations 并列、非互斥）
  std::vector<Effect> miss;
};

// --- compiler-derived opportunity inventory + coverage (report v2) -------- //
//
// The tool's only job: (1) which generic instructions could be optimized by an
// annotation, and (2) after annotating, are those positions still generic.
// It does NOT model "attempted", which annotations to place, or how they
// combine — that reasoning belongs to the agent.

enum class OppOutcome { NotOptimized, Optimized };

enum class OppKind { Arithmetic, PropertyLoad, PropertyStore, Call };

const char *oppKindLabel(OppKind k) {
  switch (k) {
    case OppKind::Arithmetic:
      return "arithmetic";
    case OppKind::PropertyLoad:
      return "property_load";
    case OppKind::PropertyStore:
      return "property_store";
    case OppKind::Call:
      return "call";
  }
  return "unknown";
}

struct OppRecord {
  OppKind kind;
  std::string location; // "line:col" instruction start point
  std::string property; // named property, empty otherwise
  OppOutcome outcome = OppOutcome::NotOptimized;
  // True when the instruction sits in a bailout (guard-fail) reachable BB:
  // generic copies there are the cold path by design and don't count.
  bool bailout = false;
};

// Is this instruction a generic arithmetic/comparison op that annotations
// could specialize to a fast numeric form (FAdd/FCompare/...)?
bool isGenericArithmetic(Instruction &I) {
  switch (I.getKind()) {
    case ValueKind::BinaryAddInstKind:
    case ValueKind::BinarySubtractInstKind:
    case ValueKind::BinaryMultiplyInstKind:
    case ValueKind::BinaryDivideInstKind:
    case ValueKind::BinaryModuloInstKind:
    case ValueKind::BinaryLessThanInstKind:
    case ValueKind::BinaryLessThanOrEqualInstKind:
    case ValueKind::BinaryGreaterThanInstKind:
    case ValueKind::BinaryGreaterThanOrEqualInstKind:
    case ValueKind::BinaryEqualInstKind:
    case ValueKind::BinaryNotEqualInstKind:
    case ValueKind::BinaryStrictlyEqualInstKind:
    case ValueKind::BinaryStrictlyNotEqualInstKind:
    case ValueKind::UnaryMinusInstKind:
      return true;
    default:
      return false;
  }
}

// Is this instruction a specialized numeric fast-path op (FAdd/FCompare/...)?
bool isSpecializedArithmetic(Instruction &I) {
  return llvh::isa<FBinaryMathInst>(&I) || llvh::isa<FUnaryMathInst>(&I) ||
      llvh::isa<FCompareInst>(&I);
}

// Is this instruction a generic named-property access that annotations could
// specialize to a typed slot access (PrLoad/PrStore)?
bool isGenericPropertyAccess(Instruction &I, OppKind *kind, std::string *prop) {
  if (auto *lp = llvh::dyn_cast<BaseLoadPropertyInst>(&I)) {
    if (auto *n = llvh::dyn_cast<LiteralString>(lp->getProperty())) {
      *kind = OppKind::PropertyLoad;
      *prop = n->getValue().str();
      return true;
    }
  }
  if (auto *sp = llvh::dyn_cast<BaseStorePropertyInst>(&I)) {
    if (auto *n = llvh::dyn_cast<LiteralString>(sp->getProperty())) {
      *kind = OppKind::PropertyStore;
      *prop = n->getValue().str();
      return true;
    }
  }
  return false;
}

bool isSpecializedPropertyAccess(Instruction &I, std::string *prop) {
  if (auto *pl = llvh::dyn_cast<PrLoadInst>(&I)) {
    *prop = pl->getPropName()->getValue().str();
    return true;
  }
  if (auto *ps = llvh::dyn_cast<PrStoreInst>(&I)) {
    *prop = ps->getPropName()->getValue().str();
    return true;
  }
  return false;
}

// Best-effort callee name for a CallInst: the callee operand is usually the
// result of a named-property load (obj.method) or a global load immediately
// before the call. Walk the defining instructions backwards a few positions.
std::string guessCalleeName(CallInst &call) {
  Value *callee = call.getCallee();
  if (auto *I = llvh::dyn_cast<Instruction>(callee)) {
    if (auto *lp = llvh::dyn_cast<BaseLoadPropertyInst>(I)) {
      if (auto *n = llvh::dyn_cast<LiteralString>(lp->getProperty()))
        return n->getValue().str();
    }
    if (auto *tp = llvh::dyn_cast<TryLoadGlobalPropertyInst>(I)) {
      if (auto *n = llvh::dyn_cast<LiteralString>(tp->getProperty()))
        return n->getValue().str();
    }
  }
  return "";
}

// Mark bailout-only BBs per function: BBs reachable from entry ONLY by
// crossing some guard's FAIL edge. Instructions there are the cold/generic
// path by design; coverage judgment only looks at the speculative copies.
//
// Algorithm: walk from the entry over all CFG edges EXCEPT guard fail edges;
// every BB not reached this way has all its entry paths going through a bail,
// i.e. it is bailout-only. (Guard branches: CondBranchInst whose condition is
// a HasStaticShapeInst/TypeOfIsInst/HasClosureTargetInst; true edge =
// speculative, false = bail.)
llvh::DenseSet<const BasicBlock *> collectBailoutBBs(Function &F) {
  // Collect guard fail edges.
  llvh::DenseSet<std::pair<const BasicBlock *, const BasicBlock *>> failEdges;
  for (BasicBlock &BB : F) {
    auto *br = llvh::dyn_cast<CondBranchInst>(BB.getTerminator());
    if (!br || !br->getCondition())
      continue;
    auto *cond = br->getCondition();
    if (!llvh::isa<HasStaticShapeInst>(cond) && !llvh::isa<TypeOfIsInst>(cond) &&
        !llvh::isa<HasClosureTargetInst>(cond))
      continue;
    // InsertGuard layout: true edge = guarded (speculative), false = bail.
    if (br->getFalseDest())
      failEdges.insert({&BB, br->getFalseDest()});
  }
  if (failEdges.empty())
    return {};

  // Reachability from entry avoiding fail edges.
  llvh::DenseSet<const BasicBlock *> speculative;
  std::vector<const BasicBlock *> worklist{&F.front()};
  speculative.insert(&F.front());
  while (!worklist.empty()) {
    const BasicBlock *bb = worklist.back();
    worklist.pop_back();
    auto *term = bb->getTerminator();
    if (!term)
      continue;
    for (unsigned i = 0, e = term->getNumSuccessors(); i != e; ++i) {
      const BasicBlock *succ = term->getSuccessor(i);
      if (failEdges.count({bb, succ}))
        continue; // crossing a bail edge: leaves the speculative domain
      if (speculative.insert(succ).second)
        worklist.push_back(succ);
    }
  }

  llvh::DenseSet<const BasicBlock *> bailout;
  for (BasicBlock &BB : F)
    if (!speculative.count(&BB))
      bailout.insert(&BB);
  return bailout;
}

// One IR scan collecting (location, kind, property) sites by category.
// category: 0 = generic arithmetic, 1 = generic property, 2 = specialized
// arithmetic, 3 = specialized property, 4 = call (generic → direct/inline).
// `bailoutBBs` per-function (empty for the pre-pipeline baseline scan).
std::vector<OppRecord> scanSites(
    Module &M,
    SourceErrorManager &sm,
    const llvh::DenseMap<Function *, llvh::DenseSet<const BasicBlock *>>
        &bailoutBBs) {
  std::vector<OppRecord> out;
  for (Function &F : M.getFunctionList()) {
    auto it = bailoutBBs.find(&F);
    const llvh::DenseSet<const BasicBlock *> empty;
    const auto &bail = it == bailoutBBs.end() ? empty : it->second;
    for (BasicBlock &BB : F)
      for (Instruction &I : BB) {
        std::string loc = locStr(&I, sm);
        if (loc.empty())
          continue;
        bool inBailout = bail.count(&BB) != 0;
        if (isGenericArithmetic(I)) {
          out.push_back(
              {OppKind::Arithmetic, loc, "", OppOutcome::NotOptimized, inBailout});
        } else if (isSpecializedArithmetic(I)) {
          out.push_back(
              {OppKind::Arithmetic, loc, "", OppOutcome::Optimized, inBailout});
        } else if (llvh::isa<CallInst>(&I)) {
          // A plain CallInst with a resolved target is the direct-connect
          // form FunctionAnalysis produces from closure target guards
          // (insertguard's spec-path calls); untargeted stays generic.
          auto &call = llvh::cast<CallInst>(I);
          bool direct = !llvh::isa<EmptySentinel>(call.getTarget());
          out.push_back({OppKind::Call, loc, guessCalleeName(call),
                         direct ? OppOutcome::Optimized
                                : OppOutcome::NotOptimized,
                         inBailout});
        } else if (llvh::isa<CallBuiltinInst>(&I)) {
          // Builtin calls (fbuiltins lowering) are not opportunities at all:
          // neither baseline nor post scan records them.
          continue;
        } else if (llvh::isa<BaseCallInst>(&I)) {
          // Any other call form (native calls, and calls whose target got
          // resolved to a Function by inlining prep) counts as optimized
          // when the target is a known IR Function.
          auto &call = llvh::cast<BaseCallInst>(I);
          bool direct = !llvh::isa<EmptySentinel>(call.getTarget());
          out.push_back({OppKind::Call, loc, "",
                         direct ? OppOutcome::Optimized : OppOutcome::NotOptimized,
                         inBailout});
        } else {
          OppKind kind;
          std::string prop;
          if (isGenericPropertyAccess(I, &kind, &prop)) {
            out.push_back(
                {kind, loc, prop, OppOutcome::NotOptimized, inBailout});
          } else if (isSpecializedPropertyAccess(I, &prop)) {
            // Re-scan generic categories for the matching kind; the
            // specialized instruction itself tells load vs store.
            OppKind k = llvh::isa<PrLoadInst>(&I) ? OppKind::PropertyLoad
                                                  : OppKind::PropertyStore;
            out.push_back({k, loc, prop, OppOutcome::Optimized, inBailout});
          }
        }
      }
  }
  return out;
}

// Build the report's opportunity list: baseline generic sites, each marked by
// what happened to the SPECULATIVE (non-bailout) copies at the same
// (location, kind[, property]) in the post-pipeline scan:
//
//   optimized  — strength reduction: a specialized form exists speculatively,
//                OR elimination: no speculative copy remains at all (CSE
//                merged it into a sibling, folded, inlined). Bailout-path
//                generic copies don't count: the cold path is generic by
//                design and is not what we're optimizing.
//   not-optimized — a generic copy still executes on the speculative path.
std::vector<OppRecord> diffOpportunities(
    const std::vector<OppRecord> &genericSites,
    const std::vector<OppRecord> &postSites) {
  // Per key: does a specialized / generic copy exist OUTSIDE bailout BBs?
  std::set<std::string> specialized, genericSpeculative;
  for (const auto &s : postSites) {
    if (s.bailout)
      continue; // cold path: irrelevant either way
    std::string key = s.location + "|" + oppKindLabel(s.kind);
    if (!s.property.empty())
      key += "|" + s.property;
    if (s.outcome == OppOutcome::Optimized)
      specialized.insert(key);
    else
      genericSpeculative.insert(key);
  }
  std::vector<OppRecord> out;
  std::set<std::string> seen;
  for (const auto &g : genericSites) {
    if (g.outcome == OppOutcome::Optimized)
      continue; // baseline pass: only generic sites are opportunities
    std::string key = g.location + "|" + oppKindLabel(g.kind);
    if (!g.property.empty())
      key += "|" + g.property;
    if (!seen.insert(key).second)
      continue; // InsertGuard duplication: same site twice
    OppRecord rec = g;
    if (specialized.count(key) || !genericSpeculative.count(key))
      // strength reduction, or the speculative copy was eliminated
      rec.outcome = OppOutcome::Optimized;
    out.push_back(rec);
  }
  std::sort(
      out.begin(),
      out.end(),
      [](const OppRecord &a, const OppRecord &b) {
        return a.location < b.location;
      });
  return out;
}

// 跨所有 function 收集每个标注（按 annotationId）的优化 + 阻挡。
// 优化与阻挡是同一标注的并列列表（不互斥）；useless = optimizations 空。
// annotationId 仅内部归因；main 输出时转成标注位置/内容（agent 可识别）。
// shape binding 的反馈主要针对 TrySet，暂不反馈——跳过 ShapeBinding 标注。
bool isReportable(const Annotations &annotations, int ann) {
  const auto *desc = annotations.getAnnotationDescriptor(ann);
  if (!desc)
    return true; // 未知 kind，保守报
  return desc->kind != AnnotationDescriptor::ShapeBinding;
}

std::map<int, AnnFeedback> collectAnnotations(
    Module &M,
    SourceErrorManager &sm,
    const Annotations &annotations) {
  std::map<int, AnnFeedback> anns;
  for (Function &F : M.getFunctionList()) {
    if (F.begin() == F.end())
      continue;
    StaticShapeInferenceRunner runner(&F);
    runner.preIteration();
    while (runner.step())
      ; // 收敛后 collectKills 才反映真实数据流

    // object → 影响它的 anns（供 ③ 把 polluting 的 object 关联到 guard）
    llvh::DenseMap<Instruction *, std::set<int>> objToAnns;

    // 出原始 IR 指令名 + 位置 + 属性（命名属性访问才有 property；计算式
    // obj[expr] 无 LiteralString 属性名 → property 留空）。category 分类 +
    // 渲染由 MCP 层做。
    auto makeEffect = [&](Instruction *C) {
      std::string prop;
      if (auto *pl = llvh::dyn_cast<PrLoadInst>(C))
        prop = pl->getPropName()->getValue().str();
      else if (auto *ps = llvh::dyn_cast<PrStoreInst>(C))
        prop = ps->getPropName()->getValue().str();
      else if (auto *lp = llvh::dyn_cast<BaseLoadPropertyInst>(C)) {
        if (auto *n = llvh::dyn_cast<LiteralString>(lp->getProperty()))
          prop = n->getValue().str();
      } else if (auto *sp = llvh::dyn_cast<BaseStorePropertyInst>(C)) {
        if (auto *n = llvh::dyn_cast<LiteralString>(sp->getProperty()))
          prop = n->getValue().str();
      }
      return Effect{locStr(C, sm), std::string(C->getKindStr()), prop};
    };

    // ② type guards → 窄化后的特化算术（FXX）或免运行时类型检查的 PrStore
    for (BasicBlock &BB : F)
      for (Instruction &I : BB) {
        auto *toi = llvh::dyn_cast<TypeOfIsInst>(&I);
        if (!toi || toi->getAnnotationId() < 0)
          continue;
        int ann = toi->getAnnotationId();
        if (!isReportable(annotations, ann))
          continue;
        anns[ann]; // 确保 entry（即使无优化/阻挡 → 渲染为 useless）
        auto guardType = typeOfIsTypesToIRType(toi->getTypes()->getData());
        if (!guardType)
          continue;
        walkReachableConsumers(toi->getArgument(), [&](Instruction *C) {
          if (!isTypeGuardConsumer(C, *guardType))
            return;
          anns[ann].optimizations.push_back(makeEffect(C));
        });
      }
    // ② shape guards → PrLoad/PrStore（属性快路径）+ 记 objToAnns
    for (BasicBlock &BB : F)
      for (Instruction &I : BB) {
        auto *hss = llvh::dyn_cast<HasStaticShapeInst>(&I);
        if (!hss || hss->getAnnotationId() < 0)
          continue;
        int ann = hss->getAnnotationId();
        if (!isReportable(annotations, ann))
          continue;
        anns[ann];
        Value *arg = hss->getArgument();
        if (auto *argI = llvh::dyn_cast<Instruction>(arg))
          objToAnns[argI].insert(ann);
        walkReachableConsumers(arg, [&](Instruction *C) {
          objToAnns[C].insert(ann);
          if (llvh::isa<PrLoadInst>(C) || llvh::isa<PrStoreInst>(C)) {
            anns[ann].optimizations.push_back(makeEffect(C));
            return;
          }
          if (llvh::isa<BaseLoadPropertyInst>(C) ||
              llvh::isa<BaseStorePropertyInst>(C))
            anns[ann].miss.push_back(makeEffect(C));
        });
      }
    // ② closure target guards → call 直连（FunctionAnalysis 从带
    // closureTarget 的 UnionNarrowTrusted 传播身份，call target 解析为
    // Function）。注意 UNT 的操作数是被检查的值而非 check 结果，与
    // HasClosureTargetInst 无 def-use 边，按 target 函数身份匹配。
    // 只认 callee 是 guarded 值的 call（walkReachableConsumers 的访问者不
    // 携带来源链，单独校验 call->getCallee()）：闭包仅作为参数传入的 call
    // 不归功于本 guard。bailout 路径不扫描。
    std::vector<UnionNarrowTrustedInst *> closureNarrows;
    for (BasicBlock &BB : F)
      for (Instruction &I : BB)
        if (auto *UNT = llvh::dyn_cast<UnionNarrowTrustedInst>(&I);
            UNT && UNT->getClosureTarget())
          closureNarrows.push_back(UNT);
    for (BasicBlock &BB : F)
      for (Instruction &I : BB) {
        auto *hct = llvh::dyn_cast<HasClosureTargetInst>(&I);
        if (!hct || hct->getAnnotationId() < 0)
          continue;
        int ann = hct->getAnnotationId();
        if (!isReportable(annotations, ann))
          continue;
        anns[ann];
        for (UnionNarrowTrustedInst *UNT : closureNarrows) {
          if (UNT->getClosureTarget() != hct->getClosureTarget())
            continue;
          walkReachableConsumers(UNT, [&](Instruction *C) {
            if (auto *call = llvh::dyn_cast<BaseCallInst>(C);
                call && call->getCallee() == UNT &&
                !llvh::isa<EmptySentinel>(call->getTarget()))
              anns[ann].optimizations.push_back(makeEffect(C));
          });
        }
      }
    // ③ polluting 阻挡（复用 StaticShapeInference 真实数据流）
    for (const auto &k : runner.collectKills()) {
      auto it = objToAnns.find(k.object);
      if (it == objToAnns.end())
        continue;
      Effect e = makeEffect(k.polluting);
      for (int ann : it->second)
        anns[ann].blockages.push_back(e);
    }
  }
  // 不在此去重：C++ 只产原始数据（含 InsertGuard spec/generic 双路径带来的
  // 重复）。「一处源码只报一次 / optimized 优先于 miss / blockages 去重」属
  // 于展示前的整理，统一在 MCP 层（dryrun_tool._dedup）做。
  return anns;
}

// Pre-pipeline: shape guards (Has) whose shape has no TrySet binding anywhere
// can never pass. Must run before the pipeline (which may remove/fold guards),
// mirroring InsertGuard::collectTrySetShapes. Returns the annotation ids of
// such guards; the shape name comes from the descriptor at emit time.
std::set<int> collectMissingBindingIds(Module &M) {
  llvh::SmallPtrSet<const StaticShapeDesc *, 8> bound;
  for (Function &F : M.getFunctionList())
    for (BasicBlock &BB : F)
      for (Instruction &I : BB)
        if (auto *tss = llvh::dyn_cast<TrySetStaticShapeInst>(&I))
          bound.insert(tss->getShape()->getData());
  std::set<int> out;
  for (Function &F : M.getFunctionList())
    for (BasicBlock &BB : F)
      for (Instruction &I : BB) {
        auto *hss = llvh::dyn_cast<HasStaticShapeInst>(&I);
        if (!hss || hss->getAnnotationId() < 0)
          continue;
        if (!bound.count(hss->getShape()->getData()))
          out.insert(hss->getAnnotationId());
      }
  return out;
}

} // namespace

int main(int argc, char **argv) {
  llvh::InitLLVM initLLVM(argc, argv);
  cl::HideUnrelatedOptions({&DryrunCategory});
  cl::ParseCommandLineOptions(argc, argv, "Hermes annotation dryrun\n");

  if (InputFilenames.empty()) {
    llvh::errs() << "error: must provide at least one input file\n";
    return 1;
  }

  auto context = createContext();
  DeclarationFileListTy declFileList;
  if (!loadGlobalDefinition(
          *context,
          llvh::MemoryBuffer::getMemBuffer(libhermes),
          declFileList)) {
    return 1;
  }

  std::vector<std::unique_ptr<llvh::MemoryBuffer>> fileBufs;
  for (llvh::StringRef filename : InputFilenames) {
    auto fileBuf = memoryBufferFromFile(filename, "input file", true);
    if (!fileBuf)
      return 1;
    fileBufs.push_back(std::move(fileBuf));
  }

  Module M(context);
  sema::SemContext semCtx(*context);
  ESTree::NodePtr ast =
      parseJSFiles(context, semCtx, declFileList, std::move(fileBufs));
  if (!ast)
    return 1;

  // 标注加载：AnnotationLoader 的 errs() 警告（位置不可解析 / 未知 shape 名 /
  // 属性错误 / JSON 错误）无条件输出到 stderr——① 载入失败由 MCP 层解析它。
  if (!AnnotationFile.empty()) {
    context->getAnnotations().loadFromFile(
        AnnotationFile, context->getSourceErrorManager());
  }

  flow::FlowContext flowContext{};
  generateIRFromESTree(&M, semCtx, flowContext, ast);

  if (VerifyIR && !verifyModule(M, &llvh::errs())) {
    llvh::errs() << "IRGen produced invalid IR\n";
    return 1;
  }

  auto &sm = context->getSourceErrorManager();

  // Report v2 baseline: scan the pre-pipeline IR for generic instructions an
  // annotation could specialize (arithmetic ops, named property accesses).
  llvh::DenseMap<Function *, llvh::DenseSet<const BasicBlock *>> noBailouts;
  auto baselineSites = scanSites(M, sm, noBailouts);

  // Pre-pipeline: find shape guards whose shape has no TrySet binding anywhere
  // (they can never pass). Must run before the pipeline, which may remove/fold
  // the guards. Mirrors InsertGuard::collectTrySetShapes.
  std::set<int> missingBindingIds = collectMissingBindingIds(M);

  // 裁剪 pipeline（前半段，跳过 inlining）。
  if (!runCustomOptimizationPasses(M, getPassList())) {
    llvh::errs() << "error: unknown pass name in feedback pipeline\n";
    return 1;
  }

  auto &annotationLoader = context->getAnnotations();
  annotationLoader.reportMatchStatus(sm);
  auto anns = collectAnnotations(M, sm, annotationLoader);
  // Ensure unbound shape guards (whose Has the pipeline may have removed) still
  // get an entry so their missingBinding is emitted below.
  for (int id : missingBindingIds)
    anns[id];

  // Post-pipeline scan: which baseline positions got optimized on the
  // speculative path? Bailout (guard-fail) BBs are marked first so generic
  // copies there are excluded from the judgment.
  llvh::DenseMap<Function *, llvh::DenseSet<const BasicBlock *>> bailoutBBs;
  for (Function &F : M.getFunctionList())
    bailoutBBs[&F] = collectBailoutBBs(F);
  auto postSites = scanSites(M, sm, bailoutBBs);
  auto opportunities = diffOpportunities(baselineSites, postSites);

  llvh::json::OStream json(llvh::outs());
  json.object([&] {
    json.attribute("schema_version", 3);
    json.attribute("file", InputFilenames[0]);
    unsigned optimized = 0, notOptimized = 0;
    for (const auto &rec : opportunities) {
      if (rec.outcome == OppOutcome::Optimized)
        ++optimized;
      else
        ++notOptimized;
    }
    json.attributeObject("summary", [&] {
      json.attribute("opportunities", (unsigned)opportunities.size());
      json.attribute("optimized", optimized);
      json.attribute("not_optimized", notOptimized);
    });
    json.attributeArray("opportunities", [&] {
      for (const auto &rec : opportunities) {
        json.object([&] {
          json.attribute("kind", oppKindLabel(rec.kind));
          json.attribute("location", rec.location);
          if (!rec.property.empty())
            json.attribute("property", rec.property);
          json.attribute(
              "outcome",
              rec.outcome == OppOutcome::Optimized ? "optimized"
                                                   : "not-optimized");
        });
      }
    });
    json.attributeArray("annotations", [&] {
      for (const auto &kv : anns) {
        const int id = kv.first;
        const AnnFeedback &fb = kv.second;
        const AnnotationDescriptor *desc =
            annotationLoader.getAnnotationDescriptor(id);
        json.object([&] {
          if (desc) {
            json.attribute(
                "range",
                std::to_string(desc->line) + ":" + std::to_string(desc->col) +
                    "-" + std::to_string(desc->endLine) + ":" +
                    std::to_string(desc->endCol));
            json.attribute(
                "kind", std::string(annotationKindLabel(desc->kind)));
            json.attribute("detail", desc->detail);
          }
          auto emitEffects = [&](const char *key,
                                 const std::vector<Effect> &es) {
            json.attributeArray(key, [&] {
              for (const auto &e : es)
                json.object([&] {
                  json.attribute("location", e.location);
                  json.attribute("instruction", e.instruction);
                  if (!e.property.empty())
                    json.attribute("property", e.property);
                });
            });
          };
          emitEffects("optimizations", fb.optimizations);
          emitEffects("blockages", fb.blockages);
          emitEffects("miss", fb.miss);
          if (missingBindingIds.count(id))
            json.attribute(
                "missingBinding", desc ? desc->detail : std::string{});
        });
      }
    });
  });
  llvh::outs() << "\n";
  return 0;
}
