// RUN: %shermes -O -exec -annotation-file=%S/proto-shape.json %s | %FileCheck %s --match-full-lines
// RUN: %shermes -O -dump-ir -annotation-file=%S/proto-shape.json %s | %FileCheckOrRegen %s --check-prefix=OPT --match-full-lines

// Construction (binding) and use (prototype-shape guard) are split across
// functions: makeProto binds p to Proto; makeChild builds o = Object.create(p)
// (so o's [[Prototype]] truly is Proto) and binds it to Child; read re-establishes
// the shape fact on the parameter via a shape guard + prototype shape, then reads
// an inherited property — exercising the spec path (PrLoad on the prototype).

(function () {
  function Proto() {}

  Proto.prototype.inherited = 42;

  function makeChild() {
    var o = new Proto();
    o.own = 1;
    return o;
  }

  function read(o) {
    return o.inherited;
  }

  // "missing" is absent from Child, absent from the annotated Proto, and absent
  // along the whole prototype chain — the rewrite must still yield undefined.
  function readMissing(o) {
    return o.missing;
  }
  print(read(makeChild()));
  print(readMissing(makeChild()));
})();

// CHECK: 42
// CHECK: undefined

// Auto-generated content below. Please do not modify manually.

// OPT:function global(): undefined
// OPT-NEXT:%BB0:
// OPT-NEXT:  %0 = CreateFunctionInst (:object) empty: any, empty: any, %Proto(): functionCode
// OPT-NEXT:  %1 = LoadPropertyInst (:any) %0: object, "prototype": string
// OPT-NEXT:       StorePropertyLooseInst 42: number, %1: any, "inherited": string
// OPT-NEXT:       TrySetStaticShapeInst %1: any, {constructor: any, inherited: number}: null [ann#4]
// OPT-NEXT:  %4 = TryLoadGlobalPropertyInst (:any) globalObject: object, "print": string
// OPT-NEXT:  %5 = LoadPropertyInst (:any) %0: object, "prototype": string
// OPT-NEXT:  %6 = AllocObjectLiteralInst (:object) %5: any
// OPT-NEXT:       StorePropertyLooseInst 1: number, %6: object, "own": string
// OPT-NEXT:       TrySetStaticShapeInst %6: object, {own: number}: null [ann#5]
// OPT-NEXT:  %9 = HasStaticShapeInst (:boolean) %6: object, {own: number}: null [ann#0]
// OPT-NEXT:        CondBranchInst %9: boolean, %BB7, %BB1
// OPT-NEXT:%BB1:
// OPT-NEXT:  %11 = LoadPropertyInst (:any) %6: object, "inherited": string
// OPT-NEXT:        BranchInst %BB2
// OPT-NEXT:%BB2:
// OPT-NEXT:  %13 = PhiInst (:any) %11: any, %BB1, %36: number, %BB8
// OPT-NEXT:  %14 = CallInst (:any) %4: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, %13: any
// OPT-NEXT:  %15 = TryLoadGlobalPropertyInst (:any) globalObject: object, "print": string
// OPT-NEXT:  %16 = LoadPropertyInst (:any) %0: object, "prototype": string
// OPT-NEXT:  %17 = AllocObjectLiteralInst (:object) %16: any
// OPT-NEXT:        StorePropertyLooseInst 1: number, %17: object, "own": string
// OPT-NEXT:        TrySetStaticShapeInst %17: object, {own: number}: null [ann#5]
// OPT-NEXT:  %20 = HasStaticShapeInst (:boolean) %17: object, {own: number}: null [ann#2]
// OPT-NEXT:        CondBranchInst %20: boolean, %BB5, %BB3
// OPT-NEXT:%BB3:
// OPT-NEXT:  %22 = LoadPropertyInst (:any) %17: object, "missing": string
// OPT-NEXT:        BranchInst %BB4
// OPT-NEXT:%BB4:
// OPT-NEXT:  %24 = PhiInst (:any) %22: any, %BB3, %31: any, %BB6
// OPT-NEXT:  %25 = CallInst (:any) %15: any, empty: any, false: boolean, empty: any, undefined: undefined, undefined: undefined, %24: any
// OPT-NEXT:        ReturnInst undefined: undefined
// OPT-NEXT:%BB5:
// OPT-NEXT:  %27 = TypedLoadParentInst (:object) %17: object
// OPT-NEXT:  %28 = HasStaticShapeInst (:boolean) %27: object, {constructor: any, inherited: number}: null [ann#3]
// OPT-NEXT:        CondBranchInst %28: boolean, %BB6, %BB3
// OPT-NEXT:%BB6:
// OPT-NEXT:  %30 = TypedLoadParentInst (:object) %27: object
// OPT-NEXT:  %31 = LoadPropertyWithReceiverInst (:any) %30: object, "missing": string, %17: object
// OPT-NEXT:        BranchInst %BB4
// OPT-NEXT:%BB7:
// OPT-NEXT:  %33 = TypedLoadParentInst (:object) %6: object
// OPT-NEXT:  %34 = HasStaticShapeInst (:boolean) %33: object, {constructor: any, inherited: number}: null [ann#1]
// OPT-NEXT:        CondBranchInst %34: boolean, %BB8, %BB1
// OPT-NEXT:%BB8:
// OPT-NEXT:  %36 = PrLoadInst (:number) %33: object, 1: number, "inherited": string
// OPT-NEXT:        BranchInst %BB2
// OPT-NEXT:function_end

// OPT:function Proto(): undefined
// OPT-NEXT:%BB0:
// OPT-NEXT:       ReturnInst undefined: undefined
// OPT-NEXT:function_end
