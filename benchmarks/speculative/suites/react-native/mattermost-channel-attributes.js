// Extracted from https://github.com/mattermost/mattermost-mobile at 8a9427f25ad9f16ed333b1865eff9c4b057cb093.
// Workload: mattermost-channel-attributes. See README.md, manifest.json and licenses/.
// Type/module syntax and formatting adapted; application algorithms retained.
// Copyright (c) 2015-present Mattermost, Inc. Apache-2.0.
const DISPLAY_BANNER_TOP = "display_banner_top";
const DISPLAY_BANNER_BOTTOM = "display_banner_bottom";
const CLASSIFICATIONS_FIELD_NAME = "classification";
const NO_BANNER = { hasBanner: false, banner: void 0 };
const EMPTY_RESOLVED = [];
const NO_SORT_ORDER = Number.MAX_SAFE_INTEGER;
const DEFAULT_BANNER_COLOR = "#DDDDDD";
const OPTION_BACKED_TYPES = /* @__PURE__ */ new Set(["select", "multiselect", "rank"]);
function getFieldOptions(field) {
  return field.attrs?.options ?? [];
}
function isPropertyValueSet(raw) {
  if (raw === null || raw === void 0 || raw === "") {
    return false;
  }
  return !(Array.isArray(raw) && raw.length === 0);
}
function isPropertyFieldRequired(field) {
  return field.attrs?.required === true;
}
function getPropertyFieldLabel(field) {
  const displayName = field.attrs?.display_name;
  return displayName || field.name;
}
function getPropertyFieldChangePolicy(field) {
  const policy = field.attrs?.change_policy;
  if (
    policy === "never" ||
    policy === "raise_only" ||
    policy === "lower_only" ||
    policy === "any"
  ) {
    return policy;
  }
  if (field.attrs?.editable === false) {
    return "never";
  }
  return "any";
}
function getOptionRank(field, optionId) {
  const options = getFieldOptions(field);
  const index = options.findIndex((option) => option.id === optionId);
  if (index < 0) {
    return void 0;
  }
  const { rank } = options[index];
  return typeof rank === "number" ? rank : index + 1;
}
function canMoveToOption(field, currentValue, optionId) {
  if (!isPropertyValueSet(currentValue)) {
    return true;
  }
  const policy = getPropertyFieldChangePolicy(field);
  if (policy === "any") {
    return true;
  }
  if (policy === "never") {
    return false;
  }
  const currentId = typeof currentValue === "string" ? currentValue : void 0;
  if (!currentId) {
    return false;
  }
  const currentRank = getOptionRank(field, currentId);
  const nextRank = getOptionRank(field, optionId);
  if (currentRank === void 0 || nextRank === void 0) {
    return false;
  }
  return policy === "raise_only" ? nextRank > currentRank : nextRank < currentRank;
}
function compareChannelAttributeFields(a, b) {
  const rankA = typeof a.attrs?.sort_order === "number" ? a.attrs.sort_order : NO_SORT_ORDER;
  const rankB = typeof b.attrs?.sort_order === "number" ? b.attrs.sort_order : NO_SORT_ORDER;
  if (rankA !== rankB) {
    return rankA - rankB;
  }
  return a.name.localeCompare(b.name, "en");
}
function resolveDisplayValue(field, raw) {
  if (!isPropertyValueSet(raw)) {
    return { displayValue: "", displayValues: [] };
  }
  const options = getFieldOptions(field);
  const optionsBearing = OPTION_BACKED_TYPES.has(field.type);
  if (Array.isArray(raw)) {
    const unresolvedOptionIds = [];
    const displayValues = raw.map((id) => {
      const option2 = options.find((candidate) => candidate.id === id);
      if (option2 === void 0 && optionsBearing) {
        unresolvedOptionIds.push(String(id));
      }
      return { value: option2?.name ?? String(id), color: option2?.color };
    });
    return {
      displayValue: displayValues.map((entry) => entry.value).join(", "),
      displayValues,
      unresolvedOptionIds: unresolvedOptionIds.length > 0 ? unresolvedOptionIds : void 0,
    };
  }
  if (typeof raw !== "string") {
    const value = String(raw);
    return { displayValue: value, displayValues: [{ value }] };
  }
  const option = options.find((candidate) => candidate.id === raw);
  if (option) {
    return {
      option,
      displayValue: option.name,
      displayValues: [{ value: option.name, color: option.color }],
    };
  }
  return {
    displayValue: raw,
    displayValues: [{ value: raw }],
    unresolvedOptionIds: optionsBearing ? [raw] : void 0,
  };
}
function resolveChannelAttributes(fields, values) {
  if (fields.length === 0) {
    return EMPTY_RESOLVED;
  }
  const valueByFieldId = /* @__PURE__ */ new Map();
  for (const value of values) {
    valueByFieldId.set(value.fieldId, value.value);
  }
  return [...fields].sort(compareChannelAttributeFields).map((field) => {
    const rawValue = valueByFieldId.get(field.id);
    return { field, rawValue, ...resolveDisplayValue(field, rawValue) };
  });
}
function selectAttributesForAction(attributes, action) {
  const selected = attributes.filter((attribute) => {
    if (!attribute.displayValue) {
      return false;
    }
    return hasAction(attribute.field, action);
  });
  return selected.length === 0 ? EMPTY_RESOLVED : selected;
}
function selectChannelInfoAttributes(attributes) {
  const listed = attributes.filter((attribute) => {
    return isPropertyValueSet(attribute.rawValue) || isPropertyFieldRequired(attribute.field);
  });
  return listed.length === 0 ? EMPTY_RESOLVED : listed;
}
function flattenChannelAttributesToChips(attributes, testIDPrefix) {
  return attributes.flatMap((attribute) => {
    const label = getPropertyFieldLabel(attribute.field);
    const multiValue = attribute.displayValues.length > 1;
    return attribute.displayValues.map((entry, index) => ({
      key: `${attribute.field.id}-${index}`,
      fieldId: attribute.field.id,
      label,
      value: entry.value,
      color: entry.color,
      testID: multiValue
        ? `${testIDPrefix}.${attribute.field.name}.${index}`
        : `${testIDPrefix}.${attribute.field.name}`,
    }));
  });
}
function groupChannelAttributeChipsByField(items) {
  const groups = [];
  const byFieldId = /* @__PURE__ */ new Map();
  for (const item of items) {
    let group = byFieldId.get(item.fieldId);
    if (!group) {
      group = { fieldId: item.fieldId, label: item.label, items: [] };
      byFieldId.set(item.fieldId, group);
      groups.push(group);
    }
    group.items.push(item);
  }
  return groups;
}
function renderSignature(attribute) {
  const { attrs } = attribute.field;
  const actions = Array.isArray(attrs?.actions) ? attrs.actions.join(",") : "";
  return [
    attribute.field.id,
    attribute.field.name,
    attribute.field.type,
    attribute.displayValue,
    attribute.option?.color ?? "",
    // Multi-valued attributes carry per-value colors, never an option, so
    // an option color change only shows up here.
    attribute.displayValues.map((entry) => entry.color ?? "").join(","),
    attribute.unresolvedOptionIds?.join(",") ?? "",
    actions,
    attrs?.required === true ? "1" : "0",
    attrs?.display_name ?? "",
    typeof attrs?.sort_order === "number" ? String(attrs.sort_order) : "",
  ].join("|");
}
function resolvedAttributesEqual(a, b) {
  if (a.length !== b.length) {
    return false;
  }
  return a.every((attribute, index) => renderSignature(attribute) === renderSignature(b[index]));
}
function channelInfoSignature(attribute) {
  return [
    attribute.field.id,
    attribute.field.name,
    getPropertyFieldLabel(attribute.field),
    attribute.displayValues.map((entry) => `${entry.value}:${entry.color ?? ""}`).join(","),
    isPropertyFieldRequired(attribute.field) ? "1" : "0",
  ].join("|");
}
function channelInfoAttributesEqual(a, b) {
  if (a.length !== b.length) {
    return false;
  }
  return a.every(
    (attribute, index) => channelInfoSignature(attribute) === channelInfoSignature(b[index])
  );
}
function hasAction(field, action) {
  const { actions } = field.attrs ?? {};
  return Array.isArray(actions) && actions.includes(action);
}
function hasBannerAction(field) {
  return hasAction(field, DISPLAY_BANNER_TOP) || hasAction(field, DISPLAY_BANNER_BOTTOM);
}
function hasNoDisplayConfiguration(field) {
  return !Array.isArray(field.attrs?.actions);
}
function deriveChannelAttributeBanner(fields, values, bannerInfo, attributesEnabled = false) {
  const ordered = [...fields].sort(compareChannelAttributeFields);
  const candidates = attributesEnabled
    ? ordered
    : ordered.filter((field) => field.name === CLASSIFICATIONS_FIELD_NAME);
  const designatedFields = candidates.filter(hasBannerAction);
  const fallback =
    designatedFields.length > 0
      ? void 0
      : candidates.find(
          (field) => field.name === CLASSIFICATIONS_FIELD_NAME && hasNoDisplayConfiguration(field)
        );
  if (designatedFields.length === 0 && !fallback) {
    return NO_BANNER;
  }
  const resolvedAttributes = resolveChannelAttributes(ordered, values);
  const templateAttributes = withoutUnresolvedOptions(resolvedAttributes);
  const authoredText = bannerInfo?.text;
  if (fallback) {
    const resolved = resolvedAttributes.find((attribute) => attribute.field.id === fallback.id);
    if (!resolved?.option?.name || resolved.unresolvedOptionIds?.length) {
      return NO_BANNER;
    }
    const text2 = authoredText
      ? renderBannerTemplate(authoredText, templateAttributes)
      : `**${resolved.option.name}**`;
    if (!text2) {
      return NO_BANNER;
    }
    return {
      hasBanner: true,
      banner: {
        enabled: true,
        text: text2,
        background_color: resolved.option.color || DEFAULT_BANNER_COLOR,
      },
    };
  }
  const bannerRequired = designatedFields.some(isPropertyFieldRequired);
  if (authoredText !== void 0 && !bannerInfo?.enabled && !bannerRequired) {
    return NO_BANNER;
  }
  const contributions = designatedFields
    .map((field) => resolvedAttributes.find((attribute) => attribute.field.id === field.id))
    .filter((attribute) =>
      Boolean(attribute?.displayValue && !attribute.unresolvedOptionIds?.length)
    );
  let text;
  if (authoredText !== void 0) {
    text = authoredText ? renderBannerTemplate(authoredText, templateAttributes) : "";
  } else if (contributions.length === 0) {
    return NO_BANNER;
  } else {
    text = contributions.map((attribute) => attribute.displayValue).join(" \xB7 ");
  }
  if (!text.trim()) {
    return NO_BANNER;
  }
  const classificationContribution = contributions.find(
    (attribute) => attribute.field.name === CLASSIFICATIONS_FIELD_NAME
  );
  const classificationColor = classificationContribution?.option?.color;
  const classificationInBanner =
    Boolean(classificationColor) &&
    (authoredText === void 0 || hasAttributeToken(authoredText, CLASSIFICATIONS_FIELD_NAME));
  let backgroundColor;
  if (classificationInBanner && classificationColor) {
    backgroundColor = classificationColor;
  } else {
    const colorContributions = contributions.filter(
      (attribute) => attribute !== classificationContribution
    );
    backgroundColor =
      bannerInfo?.background_color ||
      (colorContributions.length === 1 ? colorContributions[0].option?.color : void 0) ||
      DEFAULT_BANNER_COLOR;
  }
  return {
    hasBanner: true,
    banner: {
      enabled: true,
      text,
      background_color: backgroundColor,
    },
  };
}
function withoutUnresolvedOptions(attributes) {
  if (!attributes.some((attribute) => attribute.unresolvedOptionIds?.length)) {
    return attributes;
  }
  return attributes.map((attribute) =>
    attribute.unresolvedOptionIds?.length
      ? { ...attribute, displayValue: "", displayValues: [] }
      : attribute
  );
}
const SEPARATORS = "\xB7|";
const TOKEN_PATTERN = /\{\{\s*([a-zA-Z0-9_]+)\s*\}\}/g;
function renderNativeBannerText(fields, values, nativeBannerText, attributesEnabled = false) {
  if (!attributesEnabled || !nativeBannerText?.includes("{{")) {
    return nativeBannerText;
  }
  return renderBannerTemplate(nativeBannerText, resolveChannelAttributes(fields, values));
}
function hasAttributeToken(text, fieldName) {
  for (const match of text.matchAll(TOKEN_PATTERN)) {
    if (match[1] === fieldName) {
      return true;
    }
  }
  return false;
}
function renderBannerTemplate(template, attributes) {
  if (!template || !template.includes("{{")) {
    return template;
  }
  const byName = new Map(attributes.map((attribute) => [attribute.field.name, attribute]));
  const substituted = template.replace(TOKEN_PATTERN, (_full, name) => {
    return byName.get(name)?.displayValue ?? "";
  });
  return tidySeparators(substituted);
}
function stripUnresolvedTokens(text) {
  if (!text.includes("{{")) {
    return text;
  }
  const stripped = text.replace(TOKEN_PATTERN, "");
  return tidySeparators(stripped);
}
function tidySeparators(text) {
  const run = new RegExp(`(?:\\s*[${SEPARATORS}]\\s*){2,}`, "g");
  const leading = new RegExp(`^[\\s${SEPARATORS}]+`);
  const trailing = new RegExp(`[\\s${SEPARATORS}]+$`);
  return text
    .replace(run, (match) => ` ${match.trim().charAt(0)} `)
    .replace(leading, "")
    .replace(trailing, "")
    .replace(/\s{2,}/g, " ");
}
const rnPrint = typeof print === "function" ? print : console.log.bind(console);
function rnNow() {
  return typeof performance === "object" && typeof performance.now === "function"
    ? performance.now()
    : Date.now();
}
function rnAssert(condition, message) {
  if (!condition) throw new Error(message);
}
function rnHash(text) {
  let hash = 2166136261;
  for (let i = 0; i < text.length; i++) {
    hash = Math.imul(hash ^ text.charCodeAt(i), 16777619);
  }
  return hash >>> 0;
}
function rnRandom(seed) {
  return function () {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    return seed;
  };
}
function rnValidate(fixtures, references) {
  rnAssert(fixtures.length === references.length, "Fixture count changed");
  let observation = 0;
  for (let i = 0; i < fixtures.length; i++) {
    const result = rnExecute(fixtures[i]);
    const actual = rnFingerprint(result);
    rnAssert(actual === references[i].fingerprint, "Result mismatch in fixture " + i);
    rnAssert(
      rnObserve(result) === references[i].observation,
      "Observation mismatch in fixture " + i
    );
    observation += references[i].observation;
  }
  return observation;
}
function rnCaptureReferences() {
  return rnCreateFixtures().map(function (fixture) {
    const result = rnExecute(fixture);
    return { fingerprint: rnFingerprint(result), observation: rnObserve(result) };
  });
}
function rnBenchmark(references) {
  const fixtures = rnCreateFixtures();
  const expectedPerIteration = rnValidate(fixtures, references);
  let checksum = 0;
  const start = rnNow();
  for (let iteration = 0; iteration < RN_ITERATIONS; iteration++) {
    for (let i = 0; i < fixtures.length; i++) {
      checksum += rnObserve(rnExecute(fixtures[i]));
    }
  }
  const elapsed = rnNow() - start;
  rnAssert(checksum === expectedPerIteration * RN_ITERATIONS, "Timed result checksum mismatch");
  rnValidate(fixtures, references);
  rnAssert(Number.isFinite(elapsed) && elapsed >= 0, "Invalid benchmark timer");
  rnPrint("Checksum: " + checksum);
  rnPrint("Time: " + Math.max(1, elapsed));
}
const RN_ITERATIONS = 120;
function rnCreateFixtures() {
  return Array.from({ length: 8 }, function (_, variant) {
    const fields = [];
    const values = [];
    for (let i = 0; i < 48; i++) {
      const type = ["select", "multiselect", "text", "rank"][i % 4];
      fields.push({
        id: "field-" + i,
        name: i === 0 ? CLASSIFICATIONS_FIELD_NAME : "attribute_" + i,
        type,
        attrs: {
          sort_order: (i * 17) % 48,
          required: i % 7 === 0,
          change_policy: ["any", "never", "raise_only", "lower_only"][i % 4],
          actions: i % 3 ? [DISPLAY_BANNER_TOP, "display_label_header"] : [],
          options: [
            { id: "a", name: "Alpha", color: "#123456", rank: 1 },
            { id: "b", name: "Beta", color: "#654321", rank: 2 },
            { id: "c", name: "Gamma", color: "#abcdef", rank: 3 },
          ],
        },
      });
      const value =
        type === "multiselect"
          ? ["a", variant % 2 ? "deleted" : "b"]
          : type === "text"
            ? "Value " + i
            : i % 6 === 0
              ? ""
              : "b";
      values.push({ fieldId: "field-" + i, value });
    }
    if (variant === 0) delete fields[0].attrs.actions;
    return {
      fields,
      values,
      enabled: variant !== 0,
      banner:
        variant % 2
          ? {
              enabled: variant !== 3,
              text: "{{classification}} \xB7 {{attribute_2}} | {{missing}}",
              background_color: "#111111",
            }
          : void 0,
    };
  });
}
function rnExecute(fixture) {
  const resolved = resolveChannelAttributes(fixture.fields, fixture.values);
  const chips = flattenChannelAttributesToChips(
    selectAttributesForAction(resolved, "display_label_header"),
    "channel"
  );
  return {
    resolved,
    chips,
    groups: groupChannelAttributeChipsByField(chips),
    info: selectChannelInfoAttributes(resolved),
    equal:
      resolvedAttributesEqual(resolved, resolved.slice()) &&
      channelInfoAttributesEqual(resolved, resolved.slice()),
    moves: fixture.fields.map(function (field) {
      return canMoveToOption(field, "b", "c");
    }),
    banner: deriveChannelAttributeBanner(
      fixture.fields,
      fixture.values,
      fixture.banner,
      fixture.enabled
    ),
    native: renderNativeBannerText(
      fixture.fields,
      fixture.values,
      fixture.banner?.text,
      fixture.enabled
    ),
    stripped: stripUnresolvedTokens("{{missing}} \xB7 retained | {{gone}}"),
    containsToken: hasAttributeToken(fixture.banner?.text || "{{attribute_2}}", "attribute_2"),
  };
}
function rnObserve(result) {
  return (
    result.resolved.reduce(function (n, a) {
      return n + a.displayValue.length;
    }, 0) +
    result.chips.length +
    result.groups.length +
    result.info.length +
    (result.banner.hasBanner ? result.banner.banner.text.length : 0)
  );
}
function rnFingerprint(result) {
  rnAssert(
    result.equal && result.stripped === "retained",
    "Attribute equivalence/template mismatch"
  );
  rnAssert(result.containsToken, "Attribute token lookup failed");
  return rnHash(JSON.stringify(result));
}
rnBenchmark([
  { "fingerprint": 1147541427, "observation": 423 },
  { "fingerprint": 1109267072, "observation": 466 },
  { "fingerprint": 584142436, "observation": 731 },
  { "fingerprint": 1109267072, "observation": 466 },
  { "fingerprint": 584142436, "observation": 731 },
  { "fingerprint": 1109267072, "observation": 466 },
  { "fingerprint": 584142436, "observation": 731 },
  { "fingerprint": 1109267072, "observation": 466 },
]);
