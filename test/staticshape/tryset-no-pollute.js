// RUN: %shermes -O -dump-ir -annotation-file=%S/tryset-no-pollute.json %s | %FileCheckOrRegen %s --check-prefix=OPT --match-full-lines

function crossObject() {
  var a = {x: 1};
  var b = {y: 2};
  return a.x + b.y;
}

// b's TrySet (Any operand shape) writes the heap (switches b's hidden class)
// but must NOT pollute the shape state. a's shape, established by a's own guard,
// survives past b's TrySet, so a.x becomes PrLoad on the guarded edge. Side
// effect (getSideEffectImpl) and pollution (polluting) are distinct concerns —
// a TrySet never kills static shape facts.

// Auto-generated content below. Please do not modify manually.

// OPT:function global(): undefined
// OPT-NEXT:%BB0:
// OPT-NEXT:       DeclareGlobalVarInst "crossObject": string
// OPT-NEXT:  %1 = CreateFunctionInst (:object) empty: any, empty: any, %crossObject(): functionCode
// OPT-NEXT:       StorePropertyLooseInst %1: object, globalObject: object, "crossObject": string
// OPT-NEXT:       ReturnInst undefined: undefined
// OPT-NEXT:function_end

// OPT:function crossObject(): string|number|bigint
// OPT-NEXT:%BB0:
// OPT-NEXT:  %0 = AllocObjectLiteralInst (:object) empty: any, "x": string, 1: number
// OPT-NEXT:       TrySetStaticShapeInst %0: object, {x: number}: null [ann#0]
// OPT-NEXT:  %2 = HasStaticShapeInst (:boolean) %0: object, {x: number}: null [ann#0]
// OPT-NEXT:       CondBranchInst %2: boolean, %BB3, %BB4
// OPT-NEXT:%BB1:
// OPT-NEXT:  %4 = PrLoadInst (:number) %0: object, 0: number, "x": string
// OPT-NEXT:  %5 = PrLoadInst (:number) %13: object, 0: number, "y": string
// OPT-NEXT:  %6 = FAddInst (:number) %4: number, %5: number
// OPT-NEXT:       ReturnInst %6: number
// OPT-NEXT:%BB2:
// OPT-NEXT:  %8 = PhiInst (:object) %17: object, %BB4, %13: object, %BB3
// OPT-NEXT:  %9 = LoadPropertyInst (:any) %0: object, "x": string
// OPT-NEXT:  %10 = LoadPropertyInst (:any) %8: object, "y": string
// OPT-NEXT:  %11 = BinaryAddInst (:string|number|bigint) %9: any, %10: any
// OPT-NEXT:        ReturnInst %11: string|number|bigint
// OPT-NEXT:%BB3:
// OPT-NEXT:  %13 = AllocObjectLiteralInst (:object) empty: any, "y": string, 2: number
// OPT-NEXT:        TrySetStaticShapeInst %13: object, {y: number}: null [ann#1]
// OPT-NEXT:  %15 = HasStaticShapeInst (:boolean) %13: object, {y: number}: null [ann#1]
// OPT-NEXT:        CondBranchInst %15: boolean, %BB1, %BB2
// OPT-NEXT:%BB4:
// OPT-NEXT:  %17 = AllocObjectLiteralInst (:object) empty: any, "y": string, 2: number
// OPT-NEXT:        TrySetStaticShapeInst %17: object, {y: number}: null [ann#1]
// OPT-NEXT:        BranchInst %BB2
// OPT-NEXT:function_end
