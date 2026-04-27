/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#include "../shermes/ParseJSFile.h"

#include "hermes/AST/Context.h"
#include "hermes/AST/TransformAST.h"
#include "hermes/IR/Analysis.h"
#include "hermes/IR/CFG.h"
#include "hermes/IR/IRVerifier.h"
#include "hermes/IR/Instrs.h"
#include "hermes/IRGen/IRGen.h"
#include "hermes/Optimizer/PassManager/Pipeline.h"
#include "hermes/Runtime/Libhermes.h"
#include "hermes/Sema/SemContext.h"
#include "hermes/Sema/SemResolve.h"
#include "hermes/SourceMap/SourceMapTranslator.h"
#include "hermes/Speculator/Speculator.h"
#include "llvh/Support/JSON.h"
#include "hermes/Support/SourceErrorManager.h"

#include "llvh/Support/Casting.h"
#include "llvh/Support/CommandLine.h"
#include "llvh/Support/InitLLVM.h"
#include "llvh/Support/MemoryBuffer.h"
#include "llvh/Support/raw_ostream.h"

using namespace hermes;
using llvh::dyn_cast;
namespace cl = llvh::cl;

namespace {

enum class OptLevel { O0, Og, OMax, OFixedPoint };

cl::OptionCategory SpeculatorCategory("Speculator Options");

cl::list<std::string> InputFilenames(cl::Positional, cl::desc("<input files>"));

cl::opt<OptLevel> OptimizationLevel(
    cl::desc("Choose optimization level:"),
    cl::init(OptLevel::OMax),
    cl::values(
        clEnumValN(OptLevel::O0, "O0", "No optimizations"),
        clEnumValN(OptLevel::Og, "Og", "Debug optimizations"),
        clEnumValN(OptLevel::OMax, "O", "Full optimizations"),
        clEnumValN(OptLevel::OFixedPoint, "O4", "Optimize to fixed point")),
    cl::cat(SpeculatorCategory));

cl::opt<bool> VerifyIR(
    "verify-ir",
    cl::desc("Verify IR before analysis"),
    cl::init(true),
    cl::cat(SpeculatorCategory));

std::shared_ptr<Context> createContext() {
  auto context = std::make_shared<Context>();
  context->setStrictMode(false);
  context->setDebugInfoSetting(DebugInfoSetting::NONE);
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
            context->getSourceErrorManager().addNewSourceBuffer(std::move(fileBuf)),
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

void runOptimizationPipeline(Module &M) {
  switch (OptimizationLevel) {
    case OptLevel::O0:
      runNoOptimizationPasses(M);
      break;
    case OptLevel::Og:
      runDebugOptimizationPasses(M);
      break;
    case OptLevel::OMax:
      runFullOptimizationPasses(M);
      break;
    case OptLevel::OFixedPoint:
      runOptimizationPassesToFixedPoint(M);
      break;
  }
}

std::string typeName(Type T) {
  std::string name;
  bool first = true;
  for (Type elem : T) {
    if (!first) name += '|';
    first = false;
    if (elem.isNumberType())         name += "number";
    else if (elem.isStringType())    name += "string";
    else if (elem.isBigIntType())    name += "bigint";
    else if (elem.isBooleanType())   name += "boolean";
    else if (elem.isNullType())      name += "null";
    else if (elem.isUndefinedType()) name += "undefined";
    else if (elem.isSymbolType())    name += "symbol";
    else if (elem.isObjectType())    name += "object";
    else                             name += "unknown";
  }
  return name;
}

void printInstrJSON(
    llvh::json::OStream &json,
    Instruction *I,
    SourceErrorManager &sm,
    const LoopAnalysis &loops) {
  json.object([&] {
    json.attribute("kind", llvh::json::Value(I->getKindStr()));
    SMLoc loc = I->getLocation();
    if (loc.isValid()) {
      SourceErrorManager::SourceCoords coords;
      if (sm.findBufferLineAndLoc(loc, coords)) {
        std::string source;
        llvh::raw_string_ostream srcOS(source);
        srcOS << sm.getSourceUrl(coords.bufId)
              << ":" << coords.line << ":" << coords.col;
        json.attribute("source", llvh::json::Value(srcOS.str()));
      }
    }
    json.attribute("inLoop", llvh::json::Value(loops.isBlockInLoop(I->getParent())));
  });
}

void printSpeculationJSON(
    llvh::json::OStream &json,
    Function *F,
    const Speculator::SpeculativeOptimization &opt,
    SourceErrorManager &sm,
    const LoopAnalysis &loops) {
  json.object([&] {
    json.attribute("function", llvh::json::Value(F->getInternalNameStr()));

    json.attributeArray("inputs", [&] {
      for (Instruction *I : opt.inputs)
        printInstrJSON(json, I, sm, loops);
    });

    json.attributeArray("speculativeTypes", [&] {
      for (Type T : opt.speculativeTypes)
        json.value(llvh::json::Value(typeName(T)));
    });

    json.attributeArray("optimizationSites", [&] {
      for (Instruction *I : opt.optimizationSites)
        printInstrJSON(json, I, sm, loops);
    });
  });
}

} // namespace

int main(int argc, char **argv) {
  llvh::InitLLVM initLLVM(argc, argv);
  cl::HideUnrelatedOptions({&SpeculatorCategory});
  cl::ParseCommandLineOptions(argc, argv, "Hermes IR speculator\n");

  if (InputFilenames.empty()) {
    llvh::errs() << "error: must provide at least one input file\n";
    return 1;
  }

  auto context = createContext();
  DeclarationFileListTy declFileList;
  if (!loadGlobalDefinition(
          *context, llvh::MemoryBuffer::getMemBuffer(libhermes), declFileList)) {
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

  flow::FlowContext flowContext{};
  generateIRFromESTree(&M, semCtx, flowContext, ast);

  if (VerifyIR && !verifyModule(M, &llvh::errs())) {
    llvh::errs() << "IRGen produced invalid IR\n";
    return 1;
  }

  runOptimizationPipeline(M);

  auto &sm = context->getSourceErrorManager();

  using SpecVec = decltype(Speculator(nullptr).run());
  llvh::SmallVector<std::tuple<Function *, SpecVec, std::unique_ptr<LoopAnalysis>>, 16>
      perFunction;

  for (Function &F : M.getFunctionList()) {
    if (F.begin() == F.end())
      continue;

    auto DI = DominanceInfo(&F);
    auto loops = std::make_unique<LoopAnalysis>(&F, DI);
    auto specs = Speculator(&F).run();

    perFunction.emplace_back(&F, std::move(specs), std::move(loops));
  }

  llvh::json::OStream json(llvh::outs());
  json.array([&] {
    for (auto &[F, specs, loops] : perFunction) {
      for (auto &spec : specs)
        printSpeculationJSON(json, F, spec, sm, *loops);
    }
  });
  llvh::outs() << "\n";
  return 0;
}
