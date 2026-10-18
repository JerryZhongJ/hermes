# About annotations (condensed)

Annotations add runtime checks that let the compiler specialize hot JavaScript.
A passing check uses the fast path; a failing check preserves normal
unoptimized behavior. A wrong guard is therefore safe but useless, not a
correctness failure.

## Optimization model

The compiler optimizes speculatively: a guard checks a runtime assumption and,
when it passes, establishes a fact that the compiler can use on the specialized
fast path. That fact removes work the generic path would otherwise perform,
such as dynamic type dispatch, coercion, property lookup, or call dispatch. If
the guard fails, execution takes the normal generic path, so speculation changes
performance but not JavaScript behavior.

Type guards establish facts about values; shape guards establish facts about
object layouts. The facts can be combined to specialize an operation involving
a shaped property, and remain usable only along control-flow paths that
preserve them.

## Running example

The examples below all refer to this source:

```javascript
function Point(x, y) { this.x = x; this.y = y; }
Point.prototype.scale = function(k) { this.x *= k; this.y *= k; };
const opts = { get tag() { return "p"; }, inner: { n: 3 } };
function process(p, k, cb) {
  p.scale(k);
  const r = p.x + opts.inner.n;
  if (cb) cb(r);
  return opts.tag + r;
}
```

## Targets and types

A **target** is the value an annotation describes. Parameter
declarations may also be targets. For a parameter, target its declaration.

A **type** is `any`, one concrete type (`boolean`, `closure`, `null`, `number`,
`string`, or `undefined`), or a union of concrete types. `any` means unknown,
not absent. `closure` identifies one known function and cannot occur in a union.

## Static shapes and bindings

A **static shape** records an object's ordered own properties: their type,
data/accessor kind, descriptor flags, and target function for a `closure`.
Inherited properties are not included; they require a separate prototype shape.

At runtime a static shape maps to a hidden class. It fixes data-property slot
offsets and bypasses inline caches even when all types are `any`. Concrete types
also enable typed operations and checked stores. Define shapes before referring
to them. In the example, shape `Point` has the numeric data properties `x` and
`y`; shape `Opts` has the `any`-typed accessor `tag` and the `any`-typed data
property `inner`; and shape `Inner` has the numeric data property `n`.

A **shape binding** is the only operation that attempts to assign a static
shape. It validates the object, sets its matching hidden class, and automatically
creates its immediate shape guard. This one-time cost can benefit later
consumers in any function; never treat a bare binding itself as a fast-path fact.

The binding target is the expression producing the object, never an enclosing
assignment. If a property write completes construction, target its receiver;
do not bind a receiver that is only read. Thus, bind the `this` receiver of the
final `this.y = y` write to shape `Point`, the outer object literal assigned to
`opts` to shape `Opts`, and the nested `{ n: 3 }` literal to shape `Inner`.

A binding creates a write guard only when its shape has a non-`any` property
(`closure` counts). An all-`any` shape such as `Opts` still gets direct slots
without typed write-guard overhead. Typed writes are checked unless a shape
guard covers the write and the stored type is proven compatible; a mismatch
silently degrades the property to untyped rather than throwing. Use typed
shapes when their optimization benefit justifies this per-write cost.

## Prototype shapes and closure properties

A prototype is another object with its own shape and binding. Its shape begins
with a non-enumerable `constructor` data property of type `any`. A known
function property must be `data`, type `closure`, and identify its target
function. Therefore shape `PointProto` contains a non-enumerable `constructor`
data property of type `any`, followed by a `scale` data property of type
`closure` whose target is the assigned function expression.

For `Cls.prototype.m = function...`, bind the LHS receiver `Cls.prototype`, not
the whole assignment; binding is applied after the method store. For
`Cls.prototype = ...`, bind the object literal. Here, bind `Point.prototype`
to shape `PointProto` after storing `scale`.

A `closure` property is especially valuable because a known property call can
be inlined. This removes dispatch, argument shuffling, and frame setup, while
letting constant folding, CSE, dead-code elimination, and register allocation
cross the former call boundary. A type guard alone cannot enable this property-
call optimization. Prefer `closure` for statically known hot small helpers such
as math/vector operations, getters, and predicate callbacks; look especially
for hot `X.prototype.method = function` patterns in ported/compiled JavaScript.

## Type guards, shape guards, and facts

A **type guard** checks the runtime type of a target value; it does not require
a shape binding or shape guard. In
`function(k) { this.x *= k; this.y *= k; }`, type guard the parameter `k` as
`number`. Together with the `Point` shape's numeric `x` and `y` properties,
this gives each `*=` two numeric operands. Guarding `k` alone is not sufficient.

A union can establish behavior shared by all its types. For
`if (cb) cb(r);`, type guard the parameter `cb` as `null | undefined`. Both
types are falsy, so the compiler can fold away the condition on that path.

A scalar `closure` guard additionally requires the exact target function. At
`cb(r)`, type guard `cb` as `closure` and identify the function expression
assigned to `Point.prototype.scale` as its target. Non-closure guards must not
carry a target function, and `closure` must not appear in a union.

Accessors always have type `any` in a shape, but their result can be guarded at
a use. At `opts.tag + r`, type guard `opts.tag` as `string`; this can select the
string-concatenation path while still calling the getter.

A **shape guard** checks a shape established by a binding; it cannot create one,
so guarding an unbound object always fails. With `prototype shape`, it also
checks that the object's direct prototype carries that shape, so the prototype
must be bound too. Deeper prototype chains are unsupported.

Add `prototype shape` only when guarded code reads a data property—including a
`closure` method—from the direct prototype. Omit it when only own properties
are used. At the `process` parameter declaration, guard `p` as shape `Point`
with prototype shape `PointProto`; this enables direct prototype-slot access
and allows `p.scale(k)` to inline.

Guard facts are local to their function: a callee needs its own guard even if
the caller guarded the corresponding argument. A fact reaches a use only if
every path preserves it. Calls, global-property loads, `in`, and `instanceof`
always remain side-effecting. Unknown generic operations and unknown-shape
property accesses become side-effect-free only with suitable type/shape
knowledge.

Because `p.scale(k)` may mutate `p`, it conservatively kills the earlier fact.
At the later `p.x` read, guard `p` again as shape `Point` with prototype shape
`PointProto`; a later guard can re-establish such a fact.

A shape guard gives direct slots for data properties on the object and, when
specified, its direct prototype; accessors still invoke their getter/setter.
Concrete property types additionally enable typed downstream operations.

Nested objects need independent guards. At `opts.inner.n`, guard `opts` as
shape `Opts`; this makes `inner` a direct-slot read but establishes no facts
about the resulting object. Then guard the whole `opts.inner` expression as
shape `Inner`. Both accesses are to own properties, so neither guard needs a
prototype shape.

Shape checks are cheap: add enough guards to preserve useful facts and let the
compiler remove redundant ones.

## Instruction specialization

An instruction is specialized only when the compiler has enough type and shape
facts for every value that can affect its JavaScript semantics. Facts may come
from guards, constants, or ordinary compiler inference; guarding one operand
does not establish facts about the others.

| Operation | Required facts | Optimization |
| --- | --- | --- |
| Numeric arithmetic or comparison | The unary operand, or both binary operands, are `number` | Use a numeric instruction without generic conversion. |
| String `+`, comparison, or test | Types determine one safe behavior | Specialize the operation or fold the result. |
| Property access | The required object and prototype shape facts reach the access | Use fixed slots; concrete property types also describe loaded values. |
| Property store | The shape and stored-value type are known | Use a typed store or a checked fallback. |
| Direct or property call | A `closure` identifies the exact function; a property call also knows the receiver shape | Call directly and possibly inline. |

For `+`, knowing only that one operand is a string proves concatenation after
primitive conversion but does not prove that converting an unknown object is
side-effect-free. In the example, `opts.tag` is `string` and `r` is numeric
because both inputs to `p.x + opts.inner.n` are numeric properties; together
these facts specialize both additions.

Comparisons likewise need types that select one comparison semantics; loose
equality generally needs stronger facts than strict equality. A test can be
folded when every possible type has the same result: `null | undefined`, for
example, is always falsy.

A concrete property type is usable only with the applicable shape fact.
`Point.x: number` helps arithmetic only where the receiver is known to have
shape `Point`; an `any` property still gets fixed-slot access but supplies no
fact about its value. Nested objects require their own shape facts. An all-`any`
shape gets fixed slots without typed-store checks.

A direct-prototype property needs facts for both the instance and prototype;
deeper chains are unsupported. An accessor can be located directly but still
invokes its getter or setter. An incompatible typed store is checked and
degrades the property to untyped rather than throwing.

Every required fact must still hold at the instruction. A control-flow merge
preserves it only if every incoming path provides it, and calls or other
side-effecting operations may invalidate shape facts. If a fact is missing, the
compiler keeps the generic instruction or takes the fallback path.

## Annotation contents and creation order

Regardless of how annotations are represented or applied, they contain the
following information:

- A static shape has a name and an ordered property list. Each property has a
  name and may specify a type, data/accessor kind, disabled descriptor flags,
  and—for `closure` only—a target function. Type defaults to `any`, kind to
  `data`, and descriptor flags to enabled.
- A shape binding identifies a target expression and the shape assigned to it.
- A shape guard identifies a target expression, its expected shape, and
  optionally its direct prototype's expected shape.
- A type guard identifies a target expression and expected type. It also
  identifies a target function exactly when the type is scalar `closure`.

Source locations must identify the exact semantic expression: a parameter's
declaration, an actual `this` expression, a member receiver rather than its
enclosing assignment, or a function expression rather than the variable that
refers to it. If locations use line and column coordinates, treat the end
position as exclusive and avoid manual column estimation.
