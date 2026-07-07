/*
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#include "hermes/VM/HiddenClass.h"

#include "hermes/VM/HostModel.h"
#include "hermes/VM/JSCallableProxy.h"
#include "hermes/VM/JSObject.h"
#include "hermes/VM/JSProxy.h"
#include "hermes/VM/Runtime.h"

#include "VMRuntimeTestHelpers.h"

#include "gtest/gtest.h"

using namespace hermes::vm;

namespace {

using HiddenClassTest = LargeHeapRuntimeTestFixture;

TEST_F(HiddenClassTest, SmokeTest) {
  GCScope gcScope{runtime, "HiddenClassTest.SmokeTest", 48};

  runtime.collect("test");

  auto aHnd = *runtime.getIdentifierTable().getSymbolHandle(
      runtime, createUTF16Ref(u"a"));
  auto bHnd = *runtime.getIdentifierTable().getSymbolHandle(
      runtime, createUTF16Ref(u"b"));
  auto cHnd = *runtime.getIdentifierTable().getSymbolHandle(
      runtime, createUTF16Ref(u"c"));
  auto dHnd = *runtime.getIdentifierTable().getSymbolHandle(
      runtime, createUTF16Ref(u"d"));

  // We will simulate and verify the following property operations, starting
  // from the same root.
  /// x.a, x.b
  /// y.a, y.b
  /// x.c
  /// y.d
  /// read-only x.b
  /// z.a, z.b, z.c
  /// read-only z.b
  /// all-read-only y twice

  MutableHandle<HiddenClass> x{runtime};
  MutableHandle<HiddenClass> y{runtime};
  MutableHandle<HiddenClass> z{runtime};

  auto rootHnd =
      runtime.makeHandle<HiddenClass>(HiddenClass::createRoot(runtime));

  ASSERT_EQ(0u, rootHnd->getNumProperties());
  ASSERT_FALSE(rootHnd->isDictionary());
  ASSERT_FALSE(rootHnd->isTyped());
  ASSERT_TRUE(rootHnd->isKnownLeaf());

  // x = {}
  x = *rootHnd;
  {
    // x.a
    auto addRes = HiddenClass::addProperty(
        x, runtime, *aHnd, PropertyFlags::defaultNewNamedPropertyFlags());
    ASSERT_RETURNED(addRes);
    ASSERT_EQ(0u, addRes->second);
    ASSERT_NE(*rootHnd, *addRes->first);
    x = *addRes->first;
    ASSERT_FALSE(x->isTyped());
  }
  {
    // x.b
    auto addRes = HiddenClass::addProperty(
        x, runtime, *bHnd, PropertyFlags::defaultNewNamedPropertyFlags());
    ASSERT_RETURNED(addRes);
    ASSERT_EQ(1u, addRes->second);
    ASSERT_NE(*x, *addRes->first);
    x = *addRes->first;
  }
  // y = {}
  y = *rootHnd;
  {
    // y.a
    auto addRes = HiddenClass::addProperty(
        y, runtime, *aHnd, PropertyFlags::defaultNewNamedPropertyFlags());
    ASSERT_RETURNED(addRes);
    ASSERT_EQ(0u, addRes->second);
    y = *addRes->first;
  }
  {
    // y.b
    auto addRes = HiddenClass::addProperty(
        y, runtime, *bHnd, PropertyFlags::defaultNewNamedPropertyFlags());
    ASSERT_RETURNED(addRes);
    ASSERT_EQ(1u, addRes->second);
    y = *addRes->first;
    ASSERT_EQ(*x, *y);
  }
  {
    // x.c
    auto addRes = HiddenClass::addProperty(
        x, runtime, *cHnd, PropertyFlags::defaultNewNamedPropertyFlags());
    ASSERT_RETURNED(addRes);
    ASSERT_EQ(2u, addRes->second);
    ASSERT_NE(*x, *addRes->first);
    x = *addRes->first;
    ASSERT_EQ(3u, x->getNumProperties());
    ASSERT_FALSE(x->isDictionary());
    ASSERT_TRUE(x->isKnownLeaf());
  }
  {
    // y.d
    auto addRes = HiddenClass::addProperty(
        y, runtime, *dHnd, PropertyFlags::defaultNewNamedPropertyFlags());
    ASSERT_RETURNED(addRes);
    ASSERT_EQ(2u, addRes->second);
    y = *addRes->first;
    ASSERT_NE(*x, *y);
    ASSERT_EQ(3u, y->getNumProperties());
    ASSERT_FALSE(y->isDictionary());
    ASSERT_TRUE(y->isKnownLeaf());
  }

  // Find all properties in x.
  NamedPropertyDescriptor desc;
  {
    auto found = HiddenClass::findProperty(x, runtime, *aHnd, desc);
    ASSERT_TRUE(found);
    ASSERT_EQ(0u, desc.slot);
    found = HiddenClass::findProperty(x, runtime, *bHnd, desc);
    ASSERT_TRUE(found);
    ASSERT_EQ(1u, desc.slot);
    found = HiddenClass::findProperty(x, runtime, *cHnd, desc);
    ASSERT_TRUE(found);
    ASSERT_EQ(2u, desc.slot);
    found = HiddenClass::findProperty(x, runtime, *dHnd, desc);
    ASSERT_FALSE(found);
  }

  {
    // Read-only x.b
    auto found = HiddenClass::findProperty(x, runtime, *bHnd, desc);
    ASSERT_TRUE(found);
    ASSERT_EQ(1u, desc.slot);
    ASSERT_TRUE(desc.flags.writable);

    desc.flags.writable = false;
    auto newClz = HiddenClass::updateProperty(x, runtime, *found, desc.flags);
    ASSERT_NE(*x, *newClz);
    ASSERT_EQ(x->getNumProperties(), newClz->getNumProperties());
    ASSERT_FALSE(newClz->isTyped());
    x = *newClz;

    found = HiddenClass::findProperty(x, runtime, *bHnd, desc);
    ASSERT_TRUE(found);
    ASSERT_EQ(1u, desc.slot);
    ASSERT_FALSE(desc.flags.writable);
  }

  // z = {}
  z = *rootHnd;
  {
    // z.a
    auto addRes = HiddenClass::addProperty(
        z, runtime, *aHnd, PropertyFlags::defaultNewNamedPropertyFlags());
    ASSERT_RETURNED(addRes);
    ASSERT_EQ(0u, addRes->second);
    z = *addRes->first;
  }
  {
    // z.b
    auto addRes = HiddenClass::addProperty(
        z, runtime, *bHnd, PropertyFlags::defaultNewNamedPropertyFlags());
    ASSERT_RETURNED(addRes);
    ASSERT_EQ(1u, addRes->second);
    z = *addRes->first;
  }
  {
    // z.c
    auto addRes = HiddenClass::addProperty(
        z, runtime, *cHnd, PropertyFlags::defaultNewNamedPropertyFlags());
    ASSERT_RETURNED(addRes);
    ASSERT_EQ(2u, addRes->second);
    z = *addRes->first;
  }

  {
    // Read-only z.b
    auto found = HiddenClass::findProperty(z, runtime, *bHnd, desc);
    ASSERT_TRUE(found);
    ASSERT_EQ(1u, desc.slot);
    ASSERT_TRUE(desc.flags.writable);

    desc.flags.writable = false;
    auto newClz = HiddenClass::updateProperty(z, runtime, *found, desc.flags);
    ASSERT_NE(*z, *newClz);
    ASSERT_EQ(z->getNumProperties(), newClz->getNumProperties());
    z = *newClz;

    found = HiddenClass::findProperty(z, runtime, *bHnd, desc);
    ASSERT_TRUE(found);
    ASSERT_EQ(1u, desc.slot);
    ASSERT_FALSE(desc.flags.writable);

    ASSERT_EQ(*x, *z);
  }

  auto y1 = HiddenClass::makeAllReadOnly(y, runtime);
  auto y2 = HiddenClass::makeAllReadOnly(y, runtime);
  ASSERT_EQ(*y1, *y2);
  auto y3 = HiddenClass::makeAllReadOnly(y1, runtime);
  ASSERT_EQ(*y1, *y3);

  // Turn x into a dictionary by erasing x.a

  {
    auto found = HiddenClass::findProperty(x, runtime, *aHnd, desc);
    ASSERT_TRUE(found);
    ASSERT_EQ(0u, desc.slot);

    auto x1 = HiddenClass::deleteProperty(x, runtime, *found);
    ASSERT_NE(*x, *x1);
    ASSERT_FALSE(x->isDictionary());
    ASSERT_TRUE(x1->isDictionary());
    ASSERT_FALSE(x1->isTyped());
    ASSERT_EQ(2u, x1->getNumProperties());

    found = HiddenClass::findProperty(x1, runtime, *aHnd, desc);
    ASSERT_FALSE(found);

    x = *x1;
  }

  {
    // x.a (again)
    auto addRes = HiddenClass::addProperty(
        x, runtime, *aHnd, PropertyFlags::defaultNewNamedPropertyFlags());
    ASSERT_RETURNED(addRes);
    ASSERT_EQ(0u, addRes->second);
    ASSERT_EQ(*x, *addRes->first);
    ASSERT_EQ(3u, x->getNumProperties());
  }
}

TEST_F(HiddenClassTest, AccessorsTest) {
  GCScope gcScope{runtime, "HiddenClassTest.SmokeTest", 48};
  runtime.collect("test");
  auto aSym = *runtime.getIdentifierTable().getSymbolHandle(
      runtime, createUTF16Ref(u"a"));
  auto bSym = *runtime.getIdentifierTable().getSymbolHandle(
      runtime, createUTF16Ref(u"b"));
  auto cSym = *runtime.getIdentifierTable().getSymbolHandle(
      runtime, createUTF16Ref(u"c"));
  auto dSym = *runtime.getIdentifierTable().getSymbolHandle(
      runtime, createUTF16Ref(u"d"));
  auto defaultFlags = PropertyFlags::defaultNewNamedPropertyFlags();
  auto accessorFlags = PropertyFlags::defaultNewNamedPropertyFlags();
  accessorFlags.accessor = true;

  // We will simulate and verify the following property operations, starting
  // from the same root.
  /// x.a, x.b, x.c accessor, x.d
  /// y.a accessor, y.b, delete y.a, y.c

  MutableHandle<HiddenClass> x{runtime};
  MutableHandle<HiddenClass> y{runtime};

  auto rootCls =
      runtime.makeHandle<HiddenClass>(HiddenClass::createRoot(runtime));

  ASSERT_FALSE(rootCls->getMayHaveAccessor());

  // x = {}
  x = *rootCls;
  {
    // x.a
    auto addRes = HiddenClass::addProperty(x, runtime, *aSym, defaultFlags);
    x = *addRes->first;
    ASSERT_FALSE(x->getMayHaveAccessor());
  }
  {
    // x.b
    auto addRes = HiddenClass::addProperty(x, runtime, *bSym, defaultFlags);
    x = *addRes->first;
    ASSERT_FALSE(x->getMayHaveAccessor());
  }
  {
    // x.c accessor
    auto addRes = HiddenClass::addProperty(x, runtime, *cSym, accessorFlags);
    x = *addRes->first;
    ASSERT_TRUE(x->getMayHaveAccessor());
  }
  {
    // x.d
    auto addRes = HiddenClass::addProperty(x, runtime, *dSym, defaultFlags);
    x = *addRes->first;
    // Since there may be an accessor in the chain, we must still return
    // true.
    ASSERT_TRUE(x->getMayHaveAccessor());
  }

  // y = {}
  y = *rootCls;
  {
    // y.a
    auto addRes = HiddenClass::addProperty(y, runtime, *aSym, accessorFlags);
    y = *addRes->first;
    ASSERT_TRUE(y->getMayHaveAccessor());
  }
  {
    // y.b
    auto addRes = HiddenClass::addProperty(y, runtime, *bSym, defaultFlags);
    y = *addRes->first;
    ASSERT_TRUE(y->getMayHaveAccessor());
  }
  {
    // delete y.a
    NamedPropertyDescriptor desc;
    auto found = HiddenClass::findProperty(y, runtime, *aSym, desc);
    ASSERT_TRUE(found);
    ASSERT_EQ(0u, desc.slot);
    y = HiddenClass::deleteProperty(y, runtime, *found);
    ASSERT_TRUE(y->getMayHaveAccessor());
  }
  {
    // y.d
    auto addRes = HiddenClass::addProperty(y, runtime, *cSym, defaultFlags);
    y = *addRes->first;
    // Since there may still be an accessor in the chain, we must still return
    // true.
    ASSERT_TRUE(y->getMayHaveAccessor());
  }
}

TEST_F(HiddenClassTest, UpdatePropertyFlagsWithoutTransitionsTest) {
  GCScope gcScope{
      runtime, "HiddenClassTest.UpdatePropertyFlagsWithoutTransitionsTest", 48};

  runtime.collect("test");

  auto aHnd = *runtime.getIdentifierTable().getSymbolHandle(
      runtime, createUTF16Ref(u"a"));
  auto bHnd = *runtime.getIdentifierTable().getSymbolHandle(
      runtime, createUTF16Ref(u"b"));
  auto cHnd = *runtime.getIdentifierTable().getSymbolHandle(
      runtime, createUTF16Ref(u"c"));
  auto dHnd = *runtime.getIdentifierTable().getSymbolHandle(
      runtime, createUTF16Ref(u"d"));

  // Add y.a, y.b, y.c
  MutableHandle<HiddenClass> y{runtime, HiddenClass::createRoot(runtime)};
  {
    // y.a
    auto addRes = HiddenClass::addProperty(
        y, runtime, *aHnd, PropertyFlags::defaultNewNamedPropertyFlags());
    ASSERT_RETURNED(addRes);
    ASSERT_EQ(0u, addRes->second);
    y = *addRes->first;
  }
  {
    // y.b
    auto addRes = HiddenClass::addProperty(
        y, runtime, *bHnd, PropertyFlags::defaultNewNamedPropertyFlags());
    ASSERT_RETURNED(addRes);
    ASSERT_EQ(1u, addRes->second);
    y = *addRes->first;
  }
  {
    // y.c
    auto addRes = HiddenClass::addProperty(
        y, runtime, *cHnd, PropertyFlags::defaultNewNamedPropertyFlags());
    ASSERT_RETURNED(addRes);
    ASSERT_EQ(2u, addRes->second);
    y = *addRes->first;
  }

  NamedPropertyDescriptor desc;

  PropertyFlags clearFlags;
  clearFlags.writable = 1;
  clearFlags.configurable = 1;
  PropertyFlags setFlags;

  ASSERT_FALSE(y->isDictionary());
  // y is not a dictionary so we will get a new hidden class.
  auto yClone = HiddenClass::updatePropertyFlagsWithoutTransitions(
      y, runtime, clearFlags, setFlags, llvh::None);
  ASSERT_NE(*y, *yClone);
  ASSERT_EQ(y->getNumProperties(), yClone->getNumProperties());
  ASSERT_TRUE(yClone->isDictionary());
  // Check each property
  auto found = HiddenClass::findProperty(yClone, runtime, *aHnd, desc);
  ASSERT_TRUE(found);
  ASSERT_EQ(0u, desc.slot);
  ASSERT_FALSE(desc.flags.writable);
  ASSERT_FALSE(desc.flags.configurable);

  found = HiddenClass::findProperty(yClone, runtime, *bHnd, desc);
  ASSERT_TRUE(found);
  ASSERT_EQ(1u, desc.slot);
  ASSERT_FALSE(desc.flags.writable);
  ASSERT_FALSE(desc.flags.configurable);

  found = HiddenClass::findProperty(yClone, runtime, *cHnd, desc);
  ASSERT_TRUE(found);
  ASSERT_EQ(2u, desc.slot);
  ASSERT_FALSE(desc.flags.writable);
  ASSERT_FALSE(desc.flags.configurable);

  // Turn y into a dictionary y3 by deleting y.a
  found = HiddenClass::findProperty(y, runtime, *aHnd, desc);
  ASSERT_TRUE(found);
  ASSERT_EQ(0u, desc.slot);

  auto y3 = HiddenClass::deleteProperty(y, runtime, *found);
  ASSERT_NE(*y, *y3);
  ASSERT_TRUE(y3->isDictionary());
  ASSERT_EQ(2u, y3->getNumProperties());
  // We should not create a new hidden class in this case.
  auto y4 = HiddenClass::updatePropertyFlagsWithoutTransitions(
      y3, runtime, clearFlags, setFlags, llvh::None);
  ASSERT_EQ(*y4, *y3);

  // Only freeze y.a and y.c
  std::vector<SymbolID> propsToFreeze;
  propsToFreeze.push_back(*aHnd);
  propsToFreeze.push_back(*cHnd);
  propsToFreeze.push_back(*dHnd); // This is not in the map yet.
  // Freeze while only create a singleton hidden class.
  auto partlyFrozenSingleton =
      HiddenClass::updatePropertyFlagsWithoutTransitions(
          y,
          runtime,
          clearFlags,
          setFlags,
          llvh::ArrayRef<SymbolID>(propsToFreeze));

  ASSERT_NE(*y, *partlyFrozenSingleton);
  ASSERT_EQ(y->getNumProperties(), partlyFrozenSingleton->getNumProperties());
  ASSERT_TRUE(partlyFrozenSingleton->isDictionary());
  // Check each property
  found =
      HiddenClass::findProperty(partlyFrozenSingleton, runtime, *aHnd, desc);
  ASSERT_TRUE(found);
  ASSERT_EQ(0u, desc.slot);
  ASSERT_FALSE(desc.flags.writable);
  ASSERT_FALSE(desc.flags.configurable);

  found =
      HiddenClass::findProperty(partlyFrozenSingleton, runtime, *bHnd, desc);
  ASSERT_TRUE(found);
  ASSERT_EQ(1u, desc.slot);
  ASSERT_TRUE(desc.flags.writable);
  ASSERT_TRUE(desc.flags.configurable);

  found =
      HiddenClass::findProperty(partlyFrozenSingleton, runtime, *cHnd, desc);
  ASSERT_TRUE(found);
  ASSERT_EQ(2u, desc.slot);
  ASSERT_FALSE(desc.flags.writable);
  ASSERT_FALSE(desc.flags.configurable);

  // We can still add another property to it.
  auto addRes = HiddenClass::addProperty(
      partlyFrozenSingleton,
      runtime,
      *dHnd,
      PropertyFlags::defaultNewNamedPropertyFlags());
  ASSERT_RETURNED(addRes);
  ASSERT_EQ(3u, addRes->second);
  ASSERT_EQ(*addRes->first, *partlyFrozenSingleton);
  ASSERT_EQ(addRes->first->getNumProperties(), 4);
}

TEST_F(HiddenClassTest, ForEachProperty) {
  MutableHandle<HiddenClass> clazz{runtime, HiddenClass::createRoot(runtime)};

  auto aHnd = *runtime.getIdentifierTable().getSymbolHandle(
      runtime, createUTF16Ref(u"a"));
  auto bHnd = *runtime.getIdentifierTable().getSymbolHandle(
      runtime, createUTF16Ref(u"b"));

  {
    // clazz.a
    auto addRes = HiddenClass::addProperty(
        clazz, runtime, *aHnd, PropertyFlags::defaultNewNamedPropertyFlags());
    ASSERT_RETURNED(addRes);
    ASSERT_EQ(0u, addRes->second);
    clazz = *addRes->first;
  }
  {
    // clazz.b
    auto addRes = HiddenClass::addProperty(
        clazz, runtime, *bHnd, PropertyFlags::defaultNewNamedPropertyFlags());
    ASSERT_RETURNED(addRes);
    ASSERT_EQ(1u, addRes->second);
    clazz = *addRes->first;
  }

  std::vector<std::pair<SymbolID, NamedPropertyDescriptor>> expectedProperties{
      {aHnd.get(),
       NamedPropertyDescriptor{
           PropertyFlags::defaultNewNamedPropertyFlags(), 0}},
      {bHnd.get(),
       NamedPropertyDescriptor{
           PropertyFlags::defaultNewNamedPropertyFlags(), 1}}};

  std::vector<std::pair<SymbolID, NamedPropertyDescriptor>> properties;
  HiddenClass::forEachProperty(
      clazz, runtime, [&properties](SymbolID id, NamedPropertyDescriptor desc) {
        properties.emplace_back(id, desc);
      });
  EXPECT_EQ(expectedProperties, properties);

  std::vector<std::pair<SymbolID, NamedPropertyDescriptor>> propertiesNoAlloc;
  HiddenClass::forEachPropertyNoAlloc(
      clazz.get(),
      runtime,
      [&propertiesNoAlloc](SymbolID id, NamedPropertyDescriptor desc) {
        propertiesNoAlloc.emplace_back(id, desc);
      });
  EXPECT_EQ(expectedProperties, propertiesNoAlloc);
}

TEST_F(HiddenClassTest, TypedPropertyTransitions) {
  GCScope gcScope{runtime, "HiddenClassTest.TypedPropertyTransitions", 48};

  auto xHnd = *runtime.getIdentifierTable().getSymbolHandle(
      runtime, createUTF16Ref(u"x"));
  auto yHnd = *runtime.getIdentifierTable().getSymbolHandle(
      runtime, createUTF16Ref(u"y"));

  auto root =
      runtime.makeHandle<HiddenClass>(HiddenClass::createTypedRoot(runtime));
  ASSERT_TRUE(root->isTyped());

  auto defaultFlags = PropertyFlags::defaultNewNamedPropertyFlags();
  auto numberFlags = defaultFlags;
  numberFlags.setPropertyType(PropertyTypeCode::Number);
  auto stringFlags = defaultFlags;
  stringFlags.setPropertyType(PropertyTypeCode::String);

  auto numberAdd = HiddenClass::addProperty(root, runtime, *xHnd, numberFlags);
  ASSERT_RETURNED(numberAdd);
  auto numberClass = numberAdd->first;
  EXPECT_TRUE(numberClass->isTyped());
  EXPECT_EQ(0u, numberAdd->second);

  auto numberAddAgain =
      HiddenClass::addProperty(root, runtime, *xHnd, numberFlags);
  ASSERT_RETURNED(numberAddAgain);
  EXPECT_EQ(*numberClass, *numberAddAgain->first);

  auto stringAdd = HiddenClass::addProperty(root, runtime, *xHnd, stringFlags);
  ASSERT_RETURNED(stringAdd);
  EXPECT_TRUE(stringAdd->first->isTyped());
  EXPECT_NE(*numberClass, *stringAdd->first);

  auto untypedAdd =
      HiddenClass::addProperty(root, runtime, *xHnd, defaultFlags);
  ASSERT_RETURNED(untypedAdd);
  EXPECT_FALSE(untypedAdd->first->isTyped());
  EXPECT_NE(*numberClass, *untypedAdd->first);
  EXPECT_NE(*stringAdd->first, *untypedAdd->first);

  auto addToUntyped =
      HiddenClass::addProperty(untypedAdd->first, runtime, *yHnd, numberFlags);
  ASSERT_RETURNED(addToUntyped);
  EXPECT_FALSE(addToUntyped->first->isTyped());
}

TEST_F(HiddenClassTest, TypedPropertyMapPreservesTypes) {
  GCScope gcScope{
      runtime, "HiddenClassTest.TypedPropertyMapPreservesTypes", 48};

  auto xHnd = *runtime.getIdentifierTable().getSymbolHandle(
      runtime, createUTF16Ref(u"x"));
  auto yHnd = *runtime.getIdentifierTable().getSymbolHandle(
      runtime, createUTF16Ref(u"y"));

  MutableHandle<HiddenClass> clazz{runtime, HiddenClass::createTypedRoot(runtime)};
  auto defaultFlags = PropertyFlags::defaultNewNamedPropertyFlags();
  auto numberFlags = defaultFlags;
  numberFlags.setPropertyType(PropertyTypeCode::Number);
  auto stringFlags = defaultFlags;
  stringFlags.setPropertyType(PropertyTypeCode::String);
  auto booleanFlags = defaultFlags;
  booleanFlags.setPropertyType(PropertyTypeCode::Boolean);

  {
    auto addRes = HiddenClass::addProperty(clazz, runtime, *xHnd, numberFlags);
    ASSERT_RETURNED(addRes);
    clazz = *addRes->first;
  }
  {
    auto addRes = HiddenClass::addProperty(clazz, runtime, *yHnd, stringFlags);
    ASSERT_RETURNED(addRes);
    clazz = *addRes->first;
  }
  ASSERT_TRUE(clazz->isTyped());

  NamedPropertyDescriptor desc;
  auto found = HiddenClass::findProperty(clazz, runtime, *xHnd, desc);
  ASSERT_TRUE(found);
  EXPECT_EQ(0u, desc.slot);
  EXPECT_EQ(PropertyTypeCode::Number, desc.flags.getPropertyType());

  found = HiddenClass::findProperty(clazz, runtime, *yHnd, desc);
  ASSERT_TRUE(found);
  EXPECT_EQ(1u, desc.slot);
  EXPECT_EQ(PropertyTypeCode::String, desc.flags.getPropertyType());

  MutableHandle<HiddenClass> next{runtime, *clazz};
  auto zHnd = *runtime.getIdentifierTable().getSymbolHandle(
      runtime, createUTF16Ref(u"z"));
  auto addRes = HiddenClass::addProperty(next, runtime, *zHnd, booleanFlags);
  ASSERT_RETURNED(addRes);
  next = *addRes->first;
  EXPECT_TRUE(next->isTyped());

  found = HiddenClass::findProperty(next, runtime, *zHnd, desc);
  ASSERT_TRUE(found);
  EXPECT_EQ(2u, desc.slot);
  EXPECT_EQ(PropertyTypeCode::Boolean, desc.flags.getPropertyType());
}

TEST_F(HiddenClassTest, TypedPropertyMapIndexMatchesSlot) {
  GCScope gcScope{
      runtime, "HiddenClassTest.TypedPropertyMapIndexMatchesSlot", 48};

  auto xHnd = *runtime.getIdentifierTable().getSymbolHandle(
      runtime, createUTF16Ref(u"x"));
  auto yHnd = *runtime.getIdentifierTable().getSymbolHandle(
      runtime, createUTF16Ref(u"y"));

  MutableHandle<HiddenClass> clazz{runtime, HiddenClass::createTypedRoot(runtime)};
  auto flags = PropertyFlags::defaultNewNamedPropertyFlags();
  flags.setPropertyType(PropertyTypeCode::Number);
  {
    auto addRes = HiddenClass::addProperty(clazz, runtime, *xHnd, flags);
    ASSERT_RETURNED(addRes);
    clazz = *addRes->first;
  }
  {
    auto addRes = HiddenClass::addProperty(clazz, runtime, *yHnd, flags);
    ASSERT_RETURNED(addRes);
    clazz = *addRes->first;
  }

  ASSERT_TRUE(clazz->isTyped());
  for (SlotIndex slot = 0; slot < clazz->getNumProperties(); ++slot) {
    auto found = HiddenClass::findPropertyBySlot(clazz, runtime, slot);
    ASSERT_TRUE(found);
    EXPECT_EQ(slot, found->second.slot);
    EXPECT_EQ(
        PropertyTypeCode::Number, found->second.flags.getPropertyType());
  }
}

TEST_F(HiddenClassTest, TypedStoreMismatchFallsBackAndStores) {
  GCScope gcScope{
      runtime, "HiddenClassTest.TypedStoreMismatchFallsBackAndStores", 48};

  auto xHnd = *runtime.getIdentifierTable().getSymbolHandle(
      runtime, createUTF16Ref(u"x"));

  auto obj = runtime.makeHandle(JSObject::create(runtime));
  auto root =
      runtime.makeHandle<HiddenClass>(HiddenClass::createTypedRoot(runtime));
  auto flags = PropertyFlags::defaultNewNamedPropertyFlags();
  flags.setPropertyType(PropertyTypeCode::Number);
  auto addRes = HiddenClass::addProperty(root, runtime, *xHnd, flags);
  ASSERT_RETURNED(addRes);
  auto typedClass = addRes->first;
  ASSERT_TRUE(typedClass->isTyped());

  auto initial = SmallHermesValue::encodeNumberValue(1, runtime);
  JSObject::addNewOwnPropertyInSlot(*obj, runtime, *typedClass, 0, initial);
  ASSERT_TRUE(obj->getClass(runtime)->isTyped());

  auto boolValue = runtime.makeHandle(HermesValue::encodeBoolValue(true));
  auto putRes = JSObject::putNamed_RJS(obj, runtime, *xHnd, boolValue);
  ASSERT_RETURNED(putRes);
  EXPECT_TRUE(*putRes);
  EXPECT_FALSE(obj->getClass(runtime)->isTyped());

  NamedPropertyDescriptor desc;
  auto found = JSObject::getOwnNamedDescriptor(obj, runtime, *xHnd, desc);
  ASSERT_TRUE(found);
  EXPECT_EQ(PropertyTypeCode::None, desc.flags.getPropertyType());
  auto stored = JSObject::getNamedSlotValueUnsafe(*obj, runtime, desc);
  EXPECT_TRUE(stored.isBool());
}

TEST_F(HiddenClassTest, TypedFallbackBySlotUsesUpdateTransition) {
  GCScope gcScope{
      runtime, "HiddenClassTest.TypedFallbackBySlotUsesUpdateTransition", 48};

  auto xHnd = *runtime.getIdentifierTable().getSymbolHandle(
      runtime, createUTF16Ref(u"x"));
  auto yHnd = *runtime.getIdentifierTable().getSymbolHandle(
      runtime, createUTF16Ref(u"y"));

  MutableHandle<HiddenClass> typed{runtime, HiddenClass::createTypedRoot(runtime)};
  auto defaultFlags = PropertyFlags::defaultNewNamedPropertyFlags();
  auto numberFlags = defaultFlags;
  numberFlags.setPropertyType(PropertyTypeCode::Number);
  auto stringFlags = defaultFlags;
  stringFlags.setPropertyType(PropertyTypeCode::String);
  {
    auto addRes = HiddenClass::addProperty(typed, runtime, *xHnd, numberFlags);
    ASSERT_RETURNED(addRes);
    typed = *addRes->first;
  }
  {
    auto addRes = HiddenClass::addProperty(typed, runtime, *yHnd, stringFlags);
    ASSERT_RETURNED(addRes);
    typed = *addRes->first;
  }
  ASSERT_TRUE(typed->isTyped());

  auto foundX = HiddenClass::findPropertyBySlot(typed, runtime, 0);
  ASSERT_TRUE(foundX);
  auto flags = foundX->second.flags;
  flags.setPropertyType(PropertyTypeCode::None);
  auto fallbackX = HiddenClass::updatePropertyBySlot(typed, runtime, 0, flags);
  EXPECT_FALSE(fallbackX->isTyped());
  EXPECT_EQ(typed->getNumProperties(), fallbackX->getNumProperties());

  NamedPropertyDescriptor fallbackDesc;
  auto found =
      HiddenClass::findProperty(fallbackX, runtime, *xHnd, fallbackDesc);
  ASSERT_TRUE(found);
  EXPECT_EQ(PropertyTypeCode::None, fallbackDesc.flags.getPropertyType());
  found = HiddenClass::findProperty(fallbackX, runtime, *yHnd, fallbackDesc);
  ASSERT_TRUE(found);
  EXPECT_EQ(PropertyTypeCode::String, fallbackDesc.flags.getPropertyType());

  foundX = HiddenClass::findPropertyBySlot(typed, runtime, 0);
  ASSERT_TRUE(foundX);
  flags = foundX->second.flags;
  flags.setPropertyType(PropertyTypeCode::None);
  auto fallbackXAgain =
      HiddenClass::updatePropertyBySlot(typed, runtime, 0, flags);
  EXPECT_EQ(*fallbackX, *fallbackXAgain);

  auto foundY = HiddenClass::findPropertyBySlot(typed, runtime, 1);
  ASSERT_TRUE(foundY);
  flags = foundY->second.flags;
  flags.setPropertyType(PropertyTypeCode::None);
  auto fallbackY = HiddenClass::updatePropertyBySlot(typed, runtime, 1, flags);
  EXPECT_FALSE(fallbackY->isTyped());
  EXPECT_NE(*fallbackX, *fallbackY);
}

TEST_F(HiddenClassTest, ReservedSlots) {
  auto aHnd = *runtime.getIdentifierTable().getSymbolHandle(
      runtime, createUTF16Ref(u"a"));
  for (unsigned i = 0; i <= InternalProperty::NumAnonymousInternalProperties;
       ++i) {
    Handle<HiddenClass> clazz =
        runtime.getHiddenClassForPrototype(*runtime.getGlobal(), i);
    EXPECT_FALSE(clazz->isDictionary());
    auto addRes = HiddenClass::addProperty(
        clazz, runtime, *aHnd, PropertyFlags::defaultNewNamedPropertyFlags());
    ASSERT_RETURNED(addRes);
    EXPECT_EQ(i, addRes->second);
  }

  // Verify that the saved HiddenClasses for Proxies and HostObjects are
  // different from the equivalent "normal" HiddenClasses.
  EXPECT_NE(
      *runtime.proxyClass,
      *runtime.getHiddenClassForPrototype(
          nullptr, JSObject::numOverlapSlots<JSProxy>()));
  EXPECT_NE(
      *runtime.callableProxyClass,
      *runtime.getHiddenClassForPrototype(
          nullptr, JSObject::numOverlapSlots<JSCallableProxy>()));
  EXPECT_NE(
      *runtime.hostObjectClass,
      *runtime.getHiddenClassForPrototype(
          runtime.objectPrototypeRawPtr,
          JSObject::numOverlapSlots<HostObject>()));
}

} // namespace
