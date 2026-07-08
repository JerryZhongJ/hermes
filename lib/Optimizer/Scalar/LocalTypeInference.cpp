/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

//===----------------------------------------------------------------------===//
/// \file
///
/// This optimization performs local (per-function) type inference for
/// instructions that do not have isTyped() == true.
/// It infers types for instructions and function return types within a single
/// function, without inter-procedural analysis.
///
/// Steps:
/// 1. Clear the type information from all instructions in the function. This
/// allows us to expand the types to the smallest valid type for each value
/// instead of starting with types that are too loose prior to the pass and not
/// be able to narrow them properly.
/// 2. Infer the type of every instruction and function return type.
/// Iterate until no more changes are made.
///
/// Unlike the module-level TypeInference pass, this pass does NOT:
/// - Infer parameter types from call sites
/// - Track module-level Variables
/// - Partition functions into groups for cross-function analysis
///
/// The pass never widens types of any value, because it intersects the result
/// types with the types prior to the pass before setting them.
//===----------------------------------------------------------------------===//

#define DEBUG_TYPE "localtypeinference"

#include "LocalTypeInferenceRunner.h"

#include "hermes/FrontEndDefs/MathBuiltinProps.h"
#include "hermes/IR/Analysis.h"
#include "hermes/IR/CFG.h"
#include "hermes/IR/IRBuilder.h"
#include "hermes/IR/Instrs.h"
#include "hermes/Optimizer/Scalar/Utils.h"
#include "hermes/Support/Statistic.h"

#include "llvh/ADT/DenseMap.h"
#include "llvh/ADT/DenseSet.h"
#include "llvh/ADT/SmallPtrSet.h"
#include "llvh/Support/Debug.h"

using namespace hermes;
using llvh::dbgs;
using llvh::SmallPtrSetImpl;

STATISTIC(NumTI, "Number of instructions type inferred");

namespace hermes {
namespace local_type_inference {

/// \return if the given \p type is a BigInt|Object, which used to determine if
/// unary/binary operations may have a BigInt result.
static bool isBigIntOrObject(Type type) {
  return type.canBeBigInt() || type.canBeObject();
}

static Type inferUnaryArith(UnaryOperatorInst *UOI, Type numberResultType) {
  Value *op = UOI->getSingleOperand();

  if (op->getType().isNumberType()) {
    return numberResultType;
  }

  if (op->getType().isBigIntType()) {
    return Type::createBigInt();
  }

  Type mayBeBigInt = isBigIntOrObject(op->getType()) ? Type::createBigInt()
                                                     : Type::createNoType();

  // - ?? => Number|?BigInt. BigInt is only possible if op.Type is
  // BigInt|Object.
  return Type::unionTy(numberResultType, mayBeBigInt);
}

static Type inferUnaryArithDefault(UnaryOperatorInst *UOI) {
  // - Number => Number
  // - BigInt => BigInt
  // - ?? => Number|BigInt
  return inferUnaryArith(UOI, Type::createNumber());
}

static Type inferTilde(UnaryOperatorInst *UOI) {
  // ~ Number => Int32
  // ~ BigInt => BigInt
  // ~ ?? => Int32|BigInt
  return inferUnaryArith(UOI, Type::createInt32());
}

/// Try to infer the type of the value that's stored into \p addr. \p addr is
/// either a stack location or a variable.
static Type inferMemoryLocationType(Value *addr) {
  Type T = addr->getType();

  for (auto *U : addr->getUsers()) {
    Value *storedVal = nullptr;

    switch (U->getKind()) {
      case ValueKind::StoreFrameInstKind: {
        auto *SF = cast<StoreFrameInst>(U);
        storedVal = SF->getValue();
        break;
      }

      case ValueKind::StoreStackInstKind: {
        auto *SS = cast<StoreStackInst>(U);
        storedVal = SS->getValue();
        break;
      }

      // Loads do not change the type of the memory location.
      case ValueKind::LoadFrameInstKind:
      case ValueKind::LoadStackInstKind:
        continue;

      default:
        // Other instructions that may write to alloc stack thwart our analysis.
        return Type::createAnyType();
    }

    if (!storedVal)
      continue;

    Type storedType = storedVal->getType();

    T = Type::unionTy(T, storedType);
  }

  return T;
}

/// Collects all of the values that are used by a tree of PHIs, recursively.
/// Inputs are stored into \p inputs. Visited PHIs are stored into \p visited.
static void collectPHIInputs(
    SmallPtrSetImpl<Value *> &visited,
    SmallPtrSetImpl<Value *> &inputs,
    PhiInst *P) {
  // Return if we already visited this node.
  if (!visited.insert(P).second)
    return;

  // For all operands:
  for (unsigned i = 0, e = P->getNumEntries(); i < e; i++) {
    auto E = P->getEntry(i);

    // Recursively inspect PHI node operands, and insert non-phis into the input
    // list.
    if (auto *PN = llvh::dyn_cast<PhiInst>(E.first)) {
      collectPHIInputs(visited, inputs, PN);
    } else {
      inputs.insert(E.first);
    }
  }
}

static Type inferBinaryArith(
    BinaryOperatorInst *BOI,
    Type numberType = Type::createNumber()) {
  Type LeftTy = BOI->getLeftHandSide()->getType();
  Type RightTy = BOI->getRightHandSide()->getType();

  // Number - Number => Number
  if (LeftTy.isNumberType() && RightTy.isNumberType()) {
    return numberType;
  }

  // BigInt - BigInt => BigInt
  if (LeftTy.isBigIntType() && RightTy.isBigIntType()) {
    return Type::createBigInt();
  }

  Type mayBeBigInt = (isBigIntOrObject(LeftTy) && isBigIntOrObject(RightTy))
      ? Type::createBigInt()
      : Type::createNoType();

  // ?? - ?? => Number|?BigInt. BigInt is only possible if both operands are
  // BigInt|Object due to the no automatic BigInt conversion.
  return Type::unionTy(numberType, mayBeBigInt);
}

static Type inferBinaryBitwise(BinaryOperatorInst *BOI) {
  Type LeftTy = BOI->getLeftHandSide()->getType();
  Type RightTy = BOI->getRightHandSide()->getType();

  Type mayBeBigInt = LeftTy.canBeBigInt() && RightTy.canBeBigInt()
      ? Type::createBigInt()
      : Type::createNoType();

  // ?? - ?? => Int32|?BigInt. BigInt is only possible if both operands can be
  // BigInt due to the no automatic BigInt conversion.
  return Type::unionTy(Type::createInt32(), mayBeBigInt);
}

static Type inferBinaryInst(BinaryOperatorInst *BOI) {
  switch (BOI->getKind()) {
    // The following operations always return a boolean result.
    // They may throw, they may read/write memory, but the result of the
    // operation must be a boolean.
    case ValueKind::BinaryEqualInstKind:
    case ValueKind::BinaryNotEqualInstKind:
    case ValueKind::BinaryStrictlyEqualInstKind:
    case ValueKind::BinaryStrictlyNotEqualInstKind:
    case ValueKind::BinaryLessThanInstKind:
    case ValueKind::BinaryLessThanOrEqualInstKind:
    case ValueKind::BinaryGreaterThanInstKind:
    case ValueKind::BinaryGreaterThanOrEqualInstKind:
    case ValueKind::BinaryInInstKind:
    case ValueKind::BinaryPrivateInInstKind:
    case ValueKind::BinaryInstanceOfInstKind:
      // Notice that the spec says that comparison of NaN should return
      // "Undefined" but all VMs return 'false'. We decided to conform to the
      // current implementation and not to the spec.
      return Type::createBoolean();

    // These arithmetic operations always return a number or bigint:
    // https://262.ecma-international.org/#sec-multiplicative-operators
    case ValueKind::BinaryDivideInstKind:
    case ValueKind::BinaryMultiplyInstKind:
    // https://262.ecma-international.org/#sec-exp-operator
    case ValueKind::BinaryExponentiationInstKind:
    // https://tc39.es/ecma262/#sec-subtraction-operator-minus
    case ValueKind::BinarySubtractInstKind:
    // https://tc39.es/ecma262/#sec-left-shift-operator
    case ValueKind::BinaryLeftShiftInstKind:
    // https://tc39.es/ecma262/#sec-signed-right-shift-operator
    case ValueKind::BinaryRightShiftInstKind:
      return inferBinaryArith(BOI);

    case ValueKind::BinaryModuloInstKind:
      return inferBinaryArith(BOI, Type::createInt32());

    // https://es5.github.io/#x11.7.3
    case ValueKind::BinaryUnsignedRightShiftInstKind:
      return Type::createUint32();

    // The Add operator is special:
    // https://262.ecma-international.org/#sec-addition-operator-plus
    case ValueKind::BinaryAddInstKind: {
      Type LeftTy = BOI->getLeftHandSide()->getType();
      Type RightTy = BOI->getRightHandSide()->getType();
      // String + String -> String. It is enough for one of the operands to be
      // a string to force the result to be a string.
      if (LeftTy.isStringType() || RightTy.isStringType()) {
        return Type::createString();
      }

      // Number + Number -> Number.
      if (LeftTy.isNumberType() && RightTy.isNumberType()) {
        return Type::createNumber();
      }

      // BigInt + BigInt -> BigInt.
      if (LeftTy.isBigIntType() && RightTy.isBigIntType()) {
        return Type::createBigInt();
      }

      // ?BigInt + ?BigInt => ?BigInt. Both operands need to "may be a BigInt"
      // for a possible BigInt result from this operator. This is true because
      // there's no automative BigInt type conversion.
      Type mayBeBigInt = (isBigIntOrObject(LeftTy) && isBigIntOrObject(RightTy))
          ? Type::createBigInt()
          : Type::createNoType();

      // handy alias for number|maybe(BigInt).
      Type numeric = Type::unionTy(Type::createNumber(), mayBeBigInt);

      // If both sides of the binary operand are known and both sides are known
      // to be non-string (and can't be converted to strings) then the result
      // must be of a numeric type.
      if (LeftTy.isPrimitive() && RightTy.isPrimitive() &&
          !LeftTy.canBeString() && !RightTy.canBeString()) {
        return numeric;
      }

      // The plus operator always returns a number, bigint, or a string.
      return Type::unionTy(numeric, Type::createString());
    }

    // https://tc39.es/ecma262/#sec-binary-bitwise-operators
    case ValueKind::BinaryAndInstKind:
    case ValueKind::BinaryOrInstKind:
    case ValueKind::BinaryXorInstKind:
      return inferBinaryBitwise(BOI);

    default:
      LLVM_DEBUG(
          dbgs() << "Unknown binary operator in TypeInference: "
                 << BOI->getOperatorStr() << '\n');
      return Type::createAnyType();
  }
}

/// Actual implementation of local type inference pass.
/// Contains the ability to infer types per-instruction within a single
/// function.
///
/// Prior to inferring the type of the instructions, the result type of
/// each instruction is cleared out (set to "NoType"), and the inference
/// is run from first principles on each of the instructions.
///
/// Each of the "inferXXXInst" functions returns a Type.
/// The only instructions which are allowed to return NoType from their infer
/// implementations are those instructions which have no output.
/// Each of these infer functions for Instructions do NOT themselves have to
/// check if the newly inferred type is _different_ - that will be done
/// by the dispatch function. However, other infer functions that are called
/// directly by \c runOnFunction must return false if they aren't changing the
/// type.
///
/// Importantly, the Phi instruction is handled separately from the usual
/// dispatch mechanism.
class Impl {
  friend class ::hermes::LocalTypeInferenceRunner;

  /// Map from various values to their types prior to the pass.
  /// Store types for Instruction, Parameter, Function return type.
  llvh::DenseMap<Value *, Type> prePassTypes_{};

  std::vector<BasicBlock *> postOrder_;

 public:
  explicit Impl(Function *) {}

 private:
  /// Run type inference on an instruction.
  /// This just does a case-based dispatch.
  /// \return true when another iteration will be required to fully infer the
  ///   type of this instruction (either the type has changed or it hasn't been
  ///   fully resolved yet).
  bool inferInstruction(Instruction *inst) {
    if (inst->isTyped()) {
      // Typed instructions are excluded from TypeInference.
      return false;
    }

    Type originalTy = inst->getType();

    // Handle Phi instructions separately by invoking inferPhi directly.
    // Phi instructions can have a NoType operand (e.g. in a loop) that would
    // be unresolvable due to a cycle if we didn't visit it anyway.
    // If we didn't special-case this, we would have a cycle that would cause
    // an infinite loop due to always returning true from this function (below).
    if (auto *phi = llvh::dyn_cast<PhiInst>(inst)) {
      return inferPhi(phi);
    }

    // If one of the operands hasn't had its type inferred yet,
    // skip it and come back later - we'll be back if anything else gets its
    // type set (which might allow us to infer the type of this instruction).
    for (unsigned int i = 0, e = inst->getNumOperands(); i < e; ++i) {
      Value *operand = inst->getOperand(i);
      if (operand->getType().isNoType()) {
        LLVM_DEBUG(
            dbgs() << llvh::format("Missing type for operand %u of ", i)
                   << inst->getName() << "(" << operand->getKindStr() << ")\n");
        return false;
      }
    }

    Type inferredTy = Type::createAnyType();

    // Attempt inference for the given instruction.
    // It's possible that inference will result in the same type being
    // assigned.
    switch (inst->getKind()) {
#define DEF_VALUE(CLASS, PARENT)                  \
  case ValueKind::CLASS##Kind:                    \
    inferredTy = infer##CLASS(cast<CLASS>(inst)); \
    break;
#define DEF_TAG(NAME, PARENT)                       \
  case ValueKind::NAME##Kind:                       \
    inferredTy = infer##PARENT(cast<PARENT>(inst)); \
    break;
#include "hermes/IR/Instrs.def"
      default:
        llvm_unreachable("Invalid kind");
    }

    // Only return true if the type actually changed.
    inst->setType(inferredTy);
    checkAndSetPrePassType(inst);
    inferredTy = inst->getType();
    bool changed = inferredTy != originalTy;

    // For debugging, only output if things changed.
    if (changed) {
      ++NumTI;
      LLVM_DEBUG(
          dbgs() << "Inferred " << inst->getName() << ": " << inst->getType()
                 << "\n");
    }

    return changed;
  }

  /// Phi instructions are to be treated specially by the inference algorithm,
  /// so we put the logic for handling them directly in this function.
  /// \return true if the type changed or we need another iteration of
  ///   inference.
  bool inferPhi(PhiInst *inst) {
    // Check if the types of all incoming values match and if they do set the
    // value of the PHI to match the incoming values.
    unsigned numEntries = inst->getNumEntries();
    if (numEntries < 1)
      return false;

    llvh::SmallPtrSet<Value *, 8> visited;
    llvh::SmallPtrSet<Value *, 8> values;
    collectPHIInputs(visited, values, inst);

    Type originalTy = inst->getType();

    Type newTy = Type::createNoType();

    // Union all possible incoming values into this phi:
    for (auto *input : values) {
      newTy = Type::unionTy(input->getType(), newTy);
    }

    inst->setType(newTy);
    return newTy != originalTy;
  }

  Type inferSingleOperandInst(SingleOperandInst *inst) {
    hermes_fatal("This is not a concrete instruction");
  }
  Type inferAddEmptyStringInst(AddEmptyStringInst *inst) {
    return *inst->getInherentType();
  }
  Type inferToPropertyKeyInst(ToPropertyKeyInst *inst) {
    Type t = inst->getSingleOperand()->getType();
    if (t.isSymbolType()) {
      return Type::createSymbol();
    }
    if (t.isPrimitive() && !t.canBeSymbol()) {
      return Type::createString();
    }
    return Type::unionTy(Type::createString(), Type::createSymbol());
  }
  Type inferCreatePrivateNameInst(CreatePrivateNameInst *inst) {
    return *inst->getInherentType();
  }
  Type inferAsNumberInst(AsNumberInst *inst) {
    return *inst->getInherentType();
  }
  Type inferAsNumericInst(AsNumericInst *inst) {
    if (inst->getSingleOperand()->getType().isNumberType()) {
      return Type::createNumber();
    }
    if (inst->getSingleOperand()->getType().isBigIntType()) {
      return Type::createBigInt();
    }
    return Type::createNumeric();
  }
  Type inferAsInt32Inst(AsInt32Inst *inst) {
    return *inst->getInherentType();
  }
  Type inferAsUint32Inst(AsUint32Inst *inst) {
    return *inst->getInherentType();
  }
  Type inferLoadStackInst(LoadStackInst *inst) {
    return inst->getSingleOperand()->getType();
  }
  Type inferMovInst(MovInst *inst) {
    Type srcType = inst->getSingleOperand()->getType();
    return srcType;
  }
  Type inferImplicitMovInst(ImplicitMovInst *inst) {
    Type srcType = inst->getSingleOperand()->getType();
    return srcType;
  }
  Type inferCoerceThisNSInst(CoerceThisNSInst *inst) {
    return *inst->getInherentType();
  }
  Type inferUnaryOperatorInst(UnaryOperatorInst *inst) {
    switch (inst->getKind()) {
      case ValueKind::UnaryVoidInstKind: // void
        return Type::createUndefined();
      // https://tc39.es/ecma262/#sec-prefix-increment-operator
      // https://tc39.es/ecma262/#sec-postfix-increment-operator
      case ValueKind::UnaryIncInstKind: // ++
      // https://tc39.es/ecma262/#sec-prefix-decrement-operator
      // https://tc39.es/ecma262/#sec-postfix-decrement-operator
      case ValueKind::UnaryDecInstKind: // --
      // https://tc39.es/ecma262/#sec-unary-minus-operator
      case ValueKind::UnaryMinusInstKind: // -
        return inferUnaryArithDefault(inst);
      // https://tc39.es/ecma262/#sec-bitwise-not-operator
      case ValueKind::UnaryTildeInstKind: // ~
        return inferTilde(inst);
      case ValueKind::UnaryBangInstKind: // !
        return Type::createBoolean();
      default:
        hermes_fatal("Invalid unary operator");
    }
  }
  Type inferDirectEvalInst(DirectEvalInst *inst) {
    return Type::createAnyType();
  }
  Type inferDeclareGlobalVarInst(DeclareGlobalVarInst *inst) {
    return Type::createNoType();
  }
  Type inferLoadFrameInst(LoadFrameInst *inst) {
    Type T = inst->getLoadVariable()->getType();
    return T;
  }
  Type inferLIRLoadConstInst(LIRLoadConstInst *inst) {
    return inst->getSingleOperand()->getType();
  }
  Type inferLoadParamInst(LoadParamInst *inst) {
    // Return the type that has been inferred for the parameter.
    return inst->getParam()->getType();
  }
  Type inferHBCResolveParentEnvironmentInst(
      HBCResolveParentEnvironmentInst *inst) {
    return *inst->getInherentType();
  }
  Type inferLIRGetArgumentsLengthInst(LIRGetArgumentsLengthInst *inst) {
    return Type::createAnyType();
  }
  Type inferHBCReifyArgumentsInst(HBCReifyArgumentsInst *inst) {
    hermes_fatal("This is not a concrete instruction");
  }
  Type inferLIRReifyArgumentsLooseInst(LIRReifyArgumentsLooseInst *inst) {
    // Does not return a value, uses a lazy register instead.
    return Type::createNoType();
  }
  Type inferLIRReifyArgumentsStrictInst(LIRReifyArgumentsStrictInst *inst) {
    // Does not return a value, uses a lazy register instead.
    return Type::createNoType();
  }
  Type inferLIRSpillMovInst(LIRSpillMovInst *inst) {
    return inst->getSingleOperand()->getType();
  }

  Type inferPhiInst(PhiInst *inst) {
    // This is a dummy function that shouldn't be called.
    hermes_fatal("Phis are to be handled specially by inferPhi()");
  }
  Type inferBinaryOperatorInst(BinaryOperatorInst *inst) {
    return inferBinaryInst(inst);
  }
  Type inferStorePropertyWithReceiverInst(StorePropertyWithReceiverInst *inst) {
    return Type::createNoType();
  }
  Type inferStorePropertyLooseInst(StorePropertyLooseInst *inst) {
    return Type::createNoType();
  }
  Type inferStorePropertyStrictInst(StorePropertyStrictInst *inst) {
    return Type::createNoType();
  }
  Type inferTryStoreGlobalPropertyLooseInst(
      TryStoreGlobalPropertyLooseInst *inst) {
    return Type::createNoType();
  }
  Type inferTryStoreGlobalPropertyStrictInst(
      TryStoreGlobalPropertyStrictInst *inst) {
    return Type::createNoType();
  }

  Type inferDefineOwnPropertyInst(DefineOwnPropertyInst *inst) {
    return Type::createNoType();
  }
  Type inferDefineOwnInDenseArrayInst(DefineOwnInDenseArrayInst *inst) {
    return Type::createNoType();
  }
  Type inferStoreOwnPrivateFieldInst(StoreOwnPrivateFieldInst *inst) {
    return Type::createNoType();
  }
  Type inferAddOwnPrivateFieldInst(AddOwnPrivateFieldInst *inst) {
    return Type::createNoType();
  }

  Type inferDefineOwnGetterSetterInst(DefineOwnGetterSetterInst *inst) {
    return Type::createNoType();
  }
  Type inferDeletePropertyLooseInst(DeletePropertyLooseInst *inst) {
    return *inst->getInherentType();
  }
  Type inferDeletePropertyStrictInst(DeletePropertyStrictInst *inst) {
    return *inst->getInherentType();
  }
  Type inferLoadPropertyInst(LoadPropertyInst *inst) {
    auto info = inst->getObjOperandShape();
    switch (info.status) {
      case StaticShapeInfo::KnownStaticShape: {
        if (auto *propStr =
                llvh::dyn_cast<LiteralString>(inst->getProperty())) {
          int idx = info.desc->getPropertyIndex(propStr->getValue());
          if (idx != -1)
            return info.desc->getPropertyType(idx);
        }
        return Type::createAnyType();
      }
      case StaticShapeInfo::NoShape:
        return Type::createNoType();
      case StaticShapeInfo::AnyShapes:
        return Type::createAnyType();
    }
  }
  Type inferLoadPropertyWithReceiverInst(LoadPropertyWithReceiverInst *inst) {
    auto info = inst->getObjOperandShape();
    switch (info.status) {
      case StaticShapeInfo::KnownStaticShape: {
        if (auto *propStr =
                llvh::dyn_cast<LiteralString>(inst->getProperty())) {
          int idx = info.desc->getPropertyIndex(propStr->getValue());
          if (idx != -1)
            return info.desc->getPropertyType(idx);
        }
        return Type::createAnyType();
      }
      case StaticShapeInfo::NoShape:
        return Type::createNoType();
      case StaticShapeInfo::AnyShapes:
        return Type::createAnyType();
    }
  }
  Type inferLoadOwnPrivateFieldInst(LoadOwnPrivateFieldInst *inst) {
    return Type::createAnyType();
  }
  Type inferTryLoadGlobalPropertyInst(TryLoadGlobalPropertyInst *inst) {
    return Type::createAnyType();
  }
  Type inferStoreStackInst(StoreStackInst *inst) {
    return Type::createNoType();
  }
  Type inferStoreFrameInst(StoreFrameInst *inst) {
    return Type::createNoType();
  }
  Type inferAllocStackInst(AllocStackInst *inst) {
    // AllocStackInst is an exceptional case, since as a convenience we have
    // decided that it assumes the type of the allocated value (instead if
    // "pointer to the type of the allocated value"). So, if it is never used,
    // we can't infer anything, ending up with "notype". But we can't allow an
    // instruction with an output to have type "notype". So, if there are no
    // users, just assume the type is "any" as a convenience.
    return inst->hasUsers() ? inferMemoryLocationType(inst)
                            : Type::createAnyType();
  }
  Type inferAllocArrayInst(AllocArrayInst *inst) {
    return *inst->getInherentType();
  }
  Type inferAllocFastArrayInst(AllocFastArrayInst *inst) {
    return *inst->getInherentType();
  }
  Type inferTrySetStaticShapeInst(TrySetStaticShapeInst *inst) {
    return Type::createNoType();
  }
  Type inferGetTemplateObjectInst(GetTemplateObjectInst *inst) {
    return *inst->getInherentType();
  }
  Type inferAllocObjectLiteralInst(AllocObjectLiteralInst *inst) {
    return *inst->getInherentType();
  }
  Type inferAllocTypedObjectInst(AllocTypedObjectInst *inst) {
    hermes_fatal("typed instruction");
  }
  Type inferCreateArgumentsLooseInst(CreateArgumentsLooseInst *inst) {
    return *inst->getInherentType();
  }
  Type inferCreateArgumentsStrictInst(CreateArgumentsStrictInst *inst) {
    return *inst->getInherentType();
  }
  Type inferCatchInst(CatchInst *inst) {
    return Type::createAnyType();
  }
  Type inferDebuggerInst(DebuggerInst *inst) {
    return Type::createNoType();
  }
  Type inferCreateRegExpInst(CreateRegExpInst *inst) {
    return *inst->getInherentType();
  }
  Type inferTryEndInst(TryEndInst *inst) {
    return Type::createNoType();
  }
  Type inferBranchIfBuiltinInst(BranchIfBuiltinInst *inst) {
    return Type::createNoType();
  }
  Type inferGetNewTargetInst(GetNewTargetInst *inst) {
    return inst->getOperand(GetNewTargetInst::GetNewTargetParamIdx)->getType();
  }
  Type inferTypeOfInst(TypeOfInst *inst) {
    return *inst->getInherentType();
  }
  Type inferTypeOfIsInst(TypeOfIsInst *inst) {
    return *inst->getInherentType();
  }
  Type inferHasStaticShapeInst(HasStaticShapeInst *inst) {
    return *inst->getInherentType();
  }
  Type inferThrowIfInst(ThrowIfInst *inst) {
    Type type = inst->getCheckedValue()->getType();
    assert(!type.isNoType() && "input to throwIfEmpty cannot be NoType");

    if (LLVM_UNLIKELY(type.isEmptyType() || type.isUninitType())) {
      // We remove "Empty" and "Uninit" from the possible types of inst,
      // which would result in a "NoType" (i.e. TDZ is always going to throw),
      // so instead we use the last "valid" type we know about.
      // While this might seem "hacky", it eliminates a lot of complexity that
      // would result from having to deal with unreachable code expressed via
      // the type system (T134361858).
      return inst->getSavedResultType();
    }

    return Type::subtractTy(type, Type::createEmpty());
  }
  Type inferThrowIfThisInitializedInst(ThrowIfThisInitializedInst *inst) {
    return Type::createNoType();
  }
  Type inferIteratorBeginInst(IteratorBeginInst *inst) {
    return Type::createAnyType();
  }
  Type inferIteratorNextInst(IteratorNextInst *inst) {
    return Type::createAnyType();
  }
  Type inferIteratorCloseInst(IteratorCloseInst *inst) {
    return Type::createAnyType();
  }
  Type inferCacheNewObjectInst(CacheNewObjectInst *inst) {
    return Type::createNoType();
  }
  Type inferUnreachableInst(UnreachableInst *inst) {
    return Type::createNoType();
  }

  Type inferCreateFunctionInst(CreateFunctionInst *inst) {
    return *inst->getInherentType();
  }
  Type inferCreateGeneratorInst(CreateGeneratorInst *inst) {
    return *inst->getInherentType();
  }

  Type inferCreateClassInst(CreateClassInst *inst) {
    return *inst->getInherentType();
  }

  Type inferTerminatorInst(TerminatorInst *inst) {
    hermes_fatal("This is not a concrete instruction");
  }
  Type inferBranchInst(BranchInst *inst) {
    return Type::createNoType();
  }
  Type inferReturnInst(ReturnInst *inst) {
    return Type::createNoType();
  }
  Type inferThrowInst(ThrowInst *inst) {
    return Type::createNoType();
  }
  Type inferThrowTypeErrorInst(ThrowTypeErrorInst *inst) {
    return Type::createNoType();
  }
  Type inferSwitchInst(SwitchInst *inst) {
    return Type::createNoType();
  }
  Type inferCondBranchInst(CondBranchInst *inst) {
    return Type::createNoType();
  }
  Type inferGetPNamesInst(GetPNamesInst *inst) {
    return Type::createNoType();
  }
  Type inferGetNextPNameInst(GetNextPNameInst *inst) {
    return Type::createNoType();
  }
  Type inferTryStartInst(TryStartInst *inst) {
    return Type::createNoType();
  }
  Type inferHBCCompareBranchInst(HBCCompareBranchInst *inst) {
    return Type::createNoType();
  }
  Type inferHBCCmpBrTypeOfIsInst(HBCCmpBrTypeOfIsInst *inst) {
    return Type::createNoType();
  }
  Type inferSwitchImmInst(BaseSwitchImmInst *inst) {
    hermes_fatal("This is not a concrete instruction");
  }
  Type inferUIntSwitchImmInst(UIntSwitchImmInst *inst) {
    return Type::createNoType();
  }
  Type inferStringSwitchImmInst(StringSwitchImmInst *inst) {
    return Type::createNoType();
  }
  Type inferSaveAndYieldInst(SaveAndYieldInst *inst) {
    return Type::createNoType();
  }

  Type inferCallInst(CallInst *inst) {
    // If the target of this call is known, propagate its return type.
    if (auto *F = llvh::dyn_cast<Function>(inst->getTarget()))
      return F->getReturnType();
    return Type::createAnyType();
  }
  Type inferHBCCallWithArgCountInst(HBCCallWithArgCountInst *inst) {
    // If the target of this call is known, propagate its return type.
    if (auto *F = llvh::dyn_cast<Function>(inst->getTarget()))
      return F->getType();
    return Type::createAnyType();
  }
  Type inferCallBuiltinInst(CallBuiltinInst *inst) {
    // All pure-numeric Math.* builtins return a number.
    if (isPureNumericMathBuiltin(inst->getBuiltinIndex()))
      return Type::createNumber();
    return Type::createAnyType();
  }
  Type inferHBCCallNInst(HBCCallNInst *inst) {
    // unimplemented
    return Type::createAnyType();
  }

  Type inferGetBuiltinClosureInst(GetBuiltinClosureInst *inst) {
    return *inst->getInherentType();
  }
  Type inferResumeGeneratorInst(ResumeGeneratorInst *inst) {
    // Result of ResumeGeneratorInst is whatever the user passes to .next()
    // or .throw() to resume the generator, which we don't yet support
    // understanding the types of.
    return Type::createAnyType();
  }

  Type inferGetParentScopeInst(GetParentScopeInst *inst) {
    return *inst->getInherentType();
  }
  Type inferCreateScopeInst(CreateScopeInst *inst) {
    return *inst->getInherentType();
  }
  Type inferResolveScopeInst(ResolveScopeInst *inst) {
    return *inst->getInherentType();
  }
  Type inferLIRResolveScopeInst(LIRResolveScopeInst *inst) {
    return *inst->getInherentType();
  }
  Type inferGetClosureScopeInst(GetClosureScopeInst *inst) {
    return *inst->getInherentType();
  }

  // These are target dependent instructions:

  Type inferLIRGetGlobalObjectInst(LIRGetGlobalObjectInst *inst) {
    return *inst->getInherentType();
  }
  Type inferHBCCreateFunctionEnvironmentInst(
      HBCCreateFunctionEnvironmentInst *inst) {
    return *inst->getInherentType();
  }
  Type inferLIRGetThisNSInst(LIRGetThisNSInst *inst) {
    return *inst->getInherentType();
  }
  Type inferCreateThisInst(CreateThisInst *inst) {
    return Type::unionTy(Type::createObject(), Type::createUndefined());
  }
  Type inferHBCGetArgumentsPropByValInst(HBCGetArgumentsPropByValInst *inst) {
    hermes_fatal("This is not a concrete instruction");
  }
  Type inferLIRGetArgumentsPropByValLooseInst(
      LIRGetArgumentsPropByValLooseInst *inst) {
    return Type::createAnyType();
  }
  Type inferLIRGetArgumentsPropByValStrictInst(
      LIRGetArgumentsPropByValStrictInst *inst) {
    return Type::createAnyType();
  }
  Type inferGetConstructedObjectInst(GetConstructedObjectInst *inst) {
    return *inst->getInherentType();
  }
  Type inferLIRAllocObjectFromBufferInst(LIRAllocObjectFromBufferInst *inst) {
    return *inst->getInherentType();
  }
  Type inferHBCProfilePointInst(HBCProfilePointInst *inst) {
    return Type::createNoType();
  }
  Type inferLoadParentNoTrapsInst(LoadParentNoTrapsInst *inst) {
    return *inst->getInherentType();
  }
  Type inferPrLoadInst(PrLoadInst *inst) {
    hermes_fatal("typed instruction");
  }
  Type inferPrStoreInst(PrStoreInst *inst) {
    hermes_fatal("typed instruction");
  }
  Type inferFastArrayLoadInst(FastArrayLoadInst *inst) {
    hermes_fatal("typed instruction");
  }
  Type inferFastArrayStoreInst(FastArrayStoreInst *inst) {
    hermes_fatal("typed instruction");
  }
  Type inferFastArrayPushInst(FastArrayPushInst *inst) {
    hermes_fatal("typed instruction");
  }
  Type inferFastArrayAppendInst(FastArrayAppendInst *inst) {
    hermes_fatal("typed instruction");
  }
  Type inferFastArrayLengthInst(FastArrayLengthInst *inst) {
    hermes_fatal("typed instruction");
  }
  Type inferTypedLoadParentInst(TypedLoadParentInst *inst) {
    hermes_fatal("typed instruction");
  }
  Type inferNativeCallInst(NativeCallInst *inst) {
    hermes_fatal("typed instruction");
  }
  Type inferGetNativeRuntimeInst(GetNativeRuntimeInst *inst) {
    hermes_fatal("typed instruction");
  }
  Type inferFUnaryMathInst(FUnaryMathInst *inst) {
    hermes_fatal("typed instruction");
  }
  Type inferFBinaryMathInst(FBinaryMathInst *inst) {
    hermes_fatal("typed instruction");
  }
  Type inferFCompareInst(FCompareInst *inst) {
    hermes_fatal("typed instruction");
  }
  Type inferHBCFCompareBranchInst(HBCFCompareBranchInst *inst) {
    hermes_fatal("typed instruction");
  }
  Type inferStringConcatInst(StringConcatInst *inst) {
    hermes_fatal("typed instruction");
  }
  Type inferHBCStringConcatInst(HBCStringConcatInst *inst) {
    hermes_fatal("typed instruction");
  }
  Type inferLazyCompilationDataInst(LazyCompilationDataInst *inst) {
    hermes_fatal("typed instruction");
  }
  Type inferEvalCompilationDataInst(EvalCompilationDataInst *inst) {
    hermes_fatal("typed instruction");
  }
  Type inferUnionNarrowTrustedInst(UnionNarrowTrustedInst *inst) {
    auto res = Type::intersectTy(
        inst->getSavedResultType(), inst->getSingleOperand()->getType());

    // It may be possible that the input value would be proven to always be
    // empty and this code is unreachable. Similarly to ThrowIf, in that
    // case we simply return something to avoid breaking invariants.
    if (LLVM_UNLIKELY(res.isNoType())) {
      return inst->getSavedResultType();
    }
    return res;
  }
  Type inferCheckedTypeCastInst(CheckedTypeCastInst *inst) {
    Type inputType = inst->getCheckedValue()->getType();
    assert(
        !inputType.isNoType() && "input to CheckedTypeCast cannot be NoType");

    Type resultType =
        Type::intersectTy(inst->getSpecifiedType()->getData(), inputType);

    if (LLVM_UNLIKELY(resultType.isNoType())) {
      // Some checked casts can be proven at compile time to always throw. In
      // that case, the result type of CheckedTypeCastInst would theoretically
      // need to be something that represents an "unreachable" type. Handling
      // this "unreachable" type everywhere would require a lot of complexity.
      // Instead, when we get to that point, we simply return the known type.
      return inst->getSpecifiedType()->getData();
    }

    return resultType;
  }
  Type inferLIRDeadValueInst(LIRDeadValueInst *inst) {
    return inst->getSavedResultType();
  }

  /// Infer the return type of \p F and register it.
  /// Cannot narrow the type of \p F from the type prior to this function being
  /// called.
  /// \return true if the return type was changed.
  bool inferFunctionReturnType(Function *F) {
    Type originalTy = F->getReturnType();
    Type returnTy = originalTy;

    // Inner generator functions may be called with `.return()` with any value
    // of any type.
    if (F->isInnerGenerator()) {
      F->setReturnType(Type::createAnyType());
      checkAndSetPrePassType(F);
      return F->getReturnType() != originalTy;
    }

    for (auto &bbit : *F) {
      if (auto *returnInst =
              llvh::dyn_cast_or_null<ReturnInst>(bbit.getTerminator())) {
        returnTy = Type::unionTy(returnTy, returnInst->getValue()->getType());
      }
    }
    F->setReturnType(returnTy);
    checkAndSetPrePassType(F);
    return F->getReturnType() != originalTy;
  }

  /// Clear every type for instructions and return type in the function.
  /// Store the pre-pass types in prePassTypes_.
  /// Parameters retain their pre-pass types — this pass does not do
  /// inter-procedural parameter inference.
  void clearTypesInFunction(Function *f) {
    // Instructions
    for (auto &bbit : *f) {
      for (auto &it : bbit) {
        Instruction *inst = &it;
        if (inst->isTyped()) {
          // Typed instructions preserve their types in TypeInference.
          // Don't modify them.
          continue;
        }
        llvh::Optional<Type> inherent = inst->getInherentType();
        prePassTypes_.try_emplace(inst, inst->getType());
        // Clear to the inherent type if possible.
        inst->setType(inherent ? *inherent : Type::createNoType());
      }
    }
    // Return type
    prePassTypes_.try_emplace(f, f->getReturnType());
    f->setReturnType(Type::createNoType());
  }

  /// Reset the return type in the function to the pre-pass type, to handle
  /// the cases where the type is notype due to unreachable or non-returning
  /// code.
  ///
  /// \return whether anything changed.
 public:
  bool resetReturnTypeNoTypesToPrePass(Function *F) {
    bool changed = false;
    // Return type
    if (F->getReturnType().isNoType()) {
      auto it = prePassTypes_.find(F);
      assert(it != prePassTypes_.end() && "Missing pre-pass type.");
      F->setReturnType(it->second);
      if (!F->getAttributes(F->getParent()).unreachable) {
        // Don't mark the Function as noReturn if it's unreachable,
        // because the return type can be notype even if there is a return in
        // the Function.
        F->getAttributesRef(F->getParent()).noReturn = true;
      }
      changed |= !F->getReturnType().isNoType();
    }

    return changed;
  }

 private:
  /// Ensure that the type of \p val is not wider than its type prior to the
  /// pass by checking against the pre-pass type and intersecting the type with
  /// it when the pre-pass type is different than \p val's type.
  /// If \p val is a Function, then update its return type instead of its return
  /// type.
  /// \return true when the type of \p val was changed.
  bool checkAndSetPrePassType(Value *val) {
    Type originalTy = val->getType();
    if (auto *func = llvh::dyn_cast<Function>(val)) {
      originalTy = func->getReturnType();
    }
    auto it = prePassTypes_.find(val);
    if (it == prePassTypes_.end()) {
      return false;
    }
    if (it->second != originalTy) {
      Type intersection = Type::intersectTy(it->second, originalTy);
      // Narrow the type to include what we knew before the pass.
      LLVM_DEBUG(
          llvh::errs() << "Intersecting type of " << val->getKindStr()
                       << " from " << val->getType() << " with " << it->second
                       << " to " << intersection << '\n');
      if (auto *func = llvh::dyn_cast<Function>(val)) {
        func->setReturnType(intersection);
      } else {
        val->setType(intersection);
      }
      return true;
    }
    return false;
  }
};

} // namespace local_type_inference

LocalTypeInferenceRunner::LocalTypeInferenceRunner(Function *F)
    : F_(F), impl_(new local_type_inference::Impl(F)) {}

LocalTypeInferenceRunner::~LocalTypeInferenceRunner() = default;

void LocalTypeInferenceRunner::preIteration() {
  LLVM_DEBUG(
      dbgs() << "\nStart Local Type Inference on " << F_->getInternalName()
             << "\n");

  impl_->clearTypesInFunction(F_);
  impl_->postOrder_ = postOrderAnalysis(F_);
}

bool LocalTypeInferenceRunner::step() {
  LLVM_DEBUG(dbgs() << "\nStart LocalTypeInference pass:\n");
  bool changed = false;

  for (auto *bbit : llvh::reverse(impl_->postOrder_)) {
    for (auto &it : *bbit) {
      changed |= impl_->inferInstruction(&it);
    }
  }
  changed |= impl_->inferFunctionReturnType(F_);
  return changed;
}

bool LocalTypeInferenceRunner::interIteration() {
  return impl_->resetReturnTypeNoTypesToPrePass(F_);
}

} // namespace hermes

#undef DEBUG_TYPE
