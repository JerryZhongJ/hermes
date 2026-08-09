// RUN: %shermes -O -dump-ir -annotation-file=%S/guard-after.json %s | %FileCheckOrRegen %s --check-prefix=OPT --match-full-lines

function sideCall() {
  return 1;
}
function guardAfter(b) {
  b.y = sideCall();
  return b.y;
}

// A shape hint on a property-store receiver is placed after all operands are
// evaluated but immediately before the store. The sideCall() may conservatively
// kill shape facts, so placing the guard when b is first evaluated would not
// protect the store. IRGen handles this placement automatically; the annotation
// only identifies the receiver expression b.

// Auto-generated content below. Please do not modify manually.

// OPT:function global(): undefined
// OPT-NEXT:%BB0:
// OPT-NEXT:       DeclareGlobalVarInst "sideCall": string
// OPT-NEXT:       DeclareGlobalVarInst "guardAfter": string
// OPT-NEXT:  %2 = CreateFunctionInst (:object) empty: any, empty: any, %sideCall(): functionCode
// OPT-NEXT:       StorePropertyLooseInst %2: object, globalObject: object, "sideCall": string
// OPT-NEXT:  %4 = CreateFunctionInst (:object) empty: any, empty: any, %guardAfter(): functionCode
// OPT-NEXT:       StorePropertyLooseInst %4: object, globalObject: object, "guardAfter": string
// OPT-NEXT:       ReturnInst undefined: undefined
// OPT-NEXT:function_end

// OPT:function sideCall(): number
// OPT-NEXT:%BB0:
// OPT-NEXT:       ReturnInst 1: number
// OPT-NEXT:function_end

// OPT:function guardAfter(b: any): any
// OPT-NEXT:%BB0:
// OPT-NEXT:  %0 = LoadParamInst (:any) %b: any
// OPT-NEXT:  %1 = LoadPropertyInst (:any) globalObject: object, "sideCall": string
// OPT-NEXT:  %2 = CallInst (:any) %1: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined
// OPT-NEXT:  %3 = HasStaticShapeInst (:boolean) %0: any, {y: number}: null [ann#0]
// OPT-NEXT:       CondBranchInst %3: boolean, %BB3, %BB4
// OPT-NEXT:%BB1:
// OPT-NEXT:  %5 = PrLoadInst (:number) %0: any, 0: number, "y": string
// OPT-NEXT:       ReturnInst %5: number
// OPT-NEXT:%BB2:
// OPT-NEXT:  %7 = LoadPropertyInst (:any) %0: any, "y": string
// OPT-NEXT:       ReturnInst %7: any
// OPT-NEXT:%BB3:
// OPT-NEXT:       PrStoreInst %2: any, %0: any, 0: number, "y": string
// OPT-NEXT:        TrySetStaticShapeInst %0: any, {y: number}: null [ann#1]
// OPT-NEXT:  %11 = HasStaticShapeInst (:boolean) %0: any, {y: number}: null [ann#1]
// OPT-NEXT:        CondBranchInst %11: boolean, %BB1, %BB2
// OPT-NEXT:%BB4:
// OPT-NEXT:        StorePropertyLooseInst %2: any, %0: any, "y": string
// OPT-NEXT:        TrySetStaticShapeInst %0: any, {y: number}: null [ann#1]
// OPT-NEXT:        BranchInst %BB2
// OPT-NEXT:function_end
