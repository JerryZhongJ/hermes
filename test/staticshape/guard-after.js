// RUN: %shermes -O -dump-ir -annotation-file=%S/guard-after.json %s | %FileCheckOrRegen %s --check-prefix=OPT --match-full-lines

function sideCall() {
  return 1;
}
function guardAfter() {
  var b = {y: 2};
  sideCall();
  return b.y;
}

// A shape hint with "guard after" is the only way to re-establish a static
// shape fact after a point where StaticShapeInference must conservatively drop
// it — here, after the cross-function call sideCall() on line 8. b carries a
// shape binding so it obtains the {y:number} shape, but the call may mutate the
// heap so the fact is dropped at the return; the delayed hint guard (guard
// after = the sideCall() expression) re-checks b and its spec edge drives the
// PrLoad on b.y. Unlike a hint that runs right after the target, this one
// survives because the binding's static fact is gone by then.

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

// OPT:function guardAfter(): any
// OPT-NEXT:%BB0:
// OPT-NEXT:  %0 = AllocObjectLiteralInst (:object) empty: any, "y": string, 2: number
// OPT-NEXT:       TrySetStaticShapeInst %0: object, {y: number}: null [ann#1]
// OPT-NEXT:  %2 = HasStaticShapeInst (:boolean) %0: object, {y: number}: null [ann#1]
// OPT-NEXT:       CondBranchInst %2: boolean, %BB3, %BB4
// OPT-NEXT:%BB1:
// OPT-NEXT:  %4 = PrLoadInst (:number) %0: object, 0: number, "y": string
// OPT-NEXT:       ReturnInst %4: number
// OPT-NEXT:%BB2:
// OPT-NEXT:  %6 = LoadPropertyInst (:any) %0: object, "y": string
// OPT-NEXT:       ReturnInst %6: any
// OPT-NEXT:%BB3:
// OPT-NEXT:  %8 = LoadPropertyInst (:any) globalObject: object, "sideCall": string
// OPT-NEXT:  %9 = CallInst (:any) %8: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined
// OPT-NEXT:  %10 = HasStaticShapeInst (:boolean) %0: object, {y: number}: null [ann#0]
// OPT-NEXT:        CondBranchInst %10: boolean, %BB1, %BB2
// OPT-NEXT:%BB4:
// OPT-NEXT:  %12 = LoadPropertyInst (:any) globalObject: object, "sideCall": string
// OPT-NEXT:  %13 = CallInst (:any) %12: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined
// OPT-NEXT:        BranchInst %BB2
// OPT-NEXT:function_end
