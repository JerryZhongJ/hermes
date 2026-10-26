// Extracted from https://github.com/mattermost/mattermost-mobile at 8a9427f25ad9f16ed333b1865eff9c4b057cb093.
// Workload: mattermost-user-profile. See README.md, manifest.json and licenses/.
// Type/module syntax and formatting adapted; application algorithms retained.
// Copyright (c) 2015-present Mattermost, Inc. Apache-2.0.
function safeParseJSON(rawJson) {
  let data = rawJson;
  try {
    if (typeof rawJson == "string") {
      data = JSON.parse(rawJson);
    }
  } catch {}
  return data;
}
const General = { AUTOCOMPLETE_SPLIT_CHARACTERS: [".", "-", "_"] };
const sortCustomProfileAttributes = (a, b) => {
  const orderA = a.sort_order ?? Number.MAX_SAFE_INTEGER;
  const orderB = b.sort_order ?? Number.MAX_SAFE_INTEGER;
  return orderA === orderB ? a.name.localeCompare(b.name) : orderA - orderB;
};
const convertToAttributesMap = (attributesToConvert) => {
  if (!Array.isArray(attributesToConvert)) {
    return attributesToConvert;
  }
  const attributesMap = {};
  attributesToConvert.forEach((attr) => {
    attributesMap[attr.id] = attr;
  });
  return attributesMap;
};
const getDisplayType = (field) => {
  if (
    field.type === "text" &&
    field.attrs?.value_type !== void 0 &&
    field.attrs.value_type !== ""
  ) {
    return field.attrs.value_type;
  }
  return field.type;
};
const getFieldOptions = (field) => {
  if (!field.attrs || (field.type !== "select" && field.type !== "multiselect")) {
    return {};
  }
  const options = field.attrs.options;
  if (!options || !Array.isArray(options)) {
    return {};
  }
  const optionsMap = {};
  options.forEach((option) => {
    if (option.id && option.name) {
      optionsMap[option.id] = option.name;
    }
  });
  return optionsMap;
};
const convertOptionsToDisplayValue = (value, fieldType, optionsMap) => {
  if (!value || !optionsMap) {
    return value;
  }
  if (fieldType === "select") {
    return optionsMap[value] || value;
  }
  if (fieldType === "multiselect") {
    let optionIds = [];
    try {
      const parsed = JSON.parse(value);
      if (Array.isArray(parsed)) {
        optionIds = parsed;
      } else {
        optionIds = value.split(",").map((id) => id.trim());
      }
    } catch {
      optionIds = value.split(",").map((id) => id.trim());
    }
    const optionNames = optionIds
      .map((id) => optionsMap[id] || id)
      .filter((name) => name.trim() !== "");
    return optionNames.join(", ");
  }
  return value;
};
const convertProfileAttributesToCustomAttributes = (
  attributes,
  fields,
  sortFn,
  useDisplayType = false
) => {
  if (!attributes?.length) {
    return [];
  }
  const fieldsMap = /* @__PURE__ */ new Map();
  const fieldOptionsMap = /* @__PURE__ */ new Map();
  fields?.forEach((field) => {
    const customType = useDisplayType ? getDisplayType(field) : field.type;
    fieldsMap.set(field.id, {
      name: field.name,
      type: customType,
      sort_order: field.attrs?.sort_order ?? Number.MAX_SAFE_INTEGER,
      originalField: field,
    });
    if (field.type === "select" || field.type === "multiselect") {
      fieldOptionsMap.set(field.id, getFieldOptions(field));
    }
  });
  const customAttrs = attributes.map((attr) => {
    const field = fieldsMap.get(attr.fieldId);
    let displayValue = attr.value;
    if (field && (field.type === "select" || field.type === "multiselect")) {
      const optionsMap = fieldOptionsMap.get(attr.fieldId);
      if (optionsMap && Object.keys(optionsMap).length > 0) {
        displayValue = convertOptionsToDisplayValue(attr.value, field.type, optionsMap);
      }
    }
    return {
      id: attr.fieldId,
      name: field?.name || attr.fieldId,
      type: field?.type || "text",
      value: displayValue,
      sort_order: field?.sort_order ?? Number.MAX_SAFE_INTEGER,
    };
  });
  return sortFn ? customAttrs.sort(sortFn) : customAttrs;
};
const convertDisplayValueToOptionIds = (displayValue, fieldType, optionsMap) => {
  if (!displayValue || !optionsMap) {
    return displayValue;
  }
  const reverseOptionsMap = {};
  Object.entries(optionsMap).forEach(([id, name]) => {
    reverseOptionsMap[name] = id;
  });
  if (fieldType === "select") {
    return reverseOptionsMap[displayValue] || displayValue;
  }
  if (fieldType === "multiselect") {
    const optionNames = displayValue
      .split(",")
      .map((name) => name.trim())
      .filter((name) => name !== "");
    const optionIds = optionNames.map((name) => reverseOptionsMap[name] || name);
    return JSON.stringify(optionIds);
  }
  return displayValue;
};
const getSelectedOptionIds = (value, fieldType) => {
  if (!value) {
    return [];
  }
  if (fieldType === "select") {
    return [value];
  }
  if (fieldType === "multiselect") {
    try {
      const parsed = safeParseJSON(value);
      if (Array.isArray(parsed)) {
        return parsed;
      }
      return value
        .split(",")
        .map((id) => id.trim())
        .filter((id) => id !== "");
    } catch (error) {
      return value
        .split(",")
        .map((id) => id.trim())
        .filter((id) => id !== "");
    }
  }
  return [];
};
const formatOptionsForSelector = (field) => {
  if (!field.attrs || (field.type !== "select" && field.type !== "multiselect")) {
    return [];
  }
  const options = field.attrs.options;
  if (!options || !Array.isArray(options)) {
    return [];
  }
  return options.map((option) => ({
    text: option.name,
    value: option.id,
  }));
};
const convertValueForServer = (value, fieldType) => {
  if (fieldType !== "multiselect") {
    return value;
  }
  if (!value) {
    return [];
  }
  try {
    const parsed = JSON.parse(value);
    if (Array.isArray(parsed)) {
      return parsed;
    }
  } catch {
    const parsed = value
      .split(",")
      .map((id) => id.trim())
      .filter((id) => id !== "");
    return parsed;
  }
  return [];
};
const convertValueFromServer = (value, fieldType) => {
  if (value === null || value === void 0) {
    return "";
  }
  if (fieldType === "select") {
    return Array.isArray(value) ? value[0] || "" : String(value);
  }
  if (fieldType === "multiselect") {
    if (Array.isArray(value)) {
      try {
        return JSON.stringify(value);
      } catch (error) {
        logError("Error converting value from server to string", error);
        return "";
      }
    }
    return String(value);
  }
  return String(value);
};
const isCustomFieldSamlLinked = (customField) => {
  return Boolean(customField?.attrs?.saml);
};
const haveSameRoles = (previous, next) => {
  if (previous === void 0) {
    return false;
  }
  const toSet = (roles) => new Set(roles.split(" ").filter(Boolean));
  const a = toSet(previous);
  const b = toSet(next);
  return a.size === b.size && [...a].every((role) => b.has(role));
};
function getFullName(user) {
  let firstName;
  let lastName;
  if ("lastName" in user) {
    firstName = user.firstName;
    lastName = user.lastName;
  } else {
    firstName = user.first_name;
    lastName = user.last_name;
  }
  if (firstName && lastName) {
    return `${firstName} ${lastName}`;
  } else if (firstName) {
    return firstName;
  } else if (lastName) {
    return lastName;
  }
  return "";
}
const getUsersByUsername = (users) => {
  const usersByUsername = {};
  for (const user of users) {
    usersByUsername[user.username] = user;
  }
  return usersByUsername;
};
function getSuggestionsSplitBy(term, splitStr) {
  const splitTerm = term.split(splitStr);
  const initialSuggestions = splitTerm.map((st, i) => splitTerm.slice(i).join(splitStr));
  let suggestions = [];
  if (splitStr === " ") {
    suggestions = initialSuggestions;
  } else {
    suggestions = initialSuggestions.reduce((acc, val) => {
      if (acc.length === 0) {
        acc.push(val);
      } else {
        acc.push(splitStr + val, val);
      }
      return acc;
    }, []);
  }
  return suggestions;
}
function getSuggestionsSplitByMultiple(term, splitStrs) {
  const suggestions = splitStrs.reduce((acc, val) => {
    getSuggestionsSplitBy(term, val).forEach((suggestion) => acc.add(suggestion));
    return acc;
  }, /* @__PURE__ */ new Set());
  return [...suggestions];
}
function filterProfilesMatchingTerm(users, term) {
  const lowercasedTerm = term.toLowerCase();
  let trimmedTerm = lowercasedTerm;
  if (trimmedTerm.startsWith("@")) {
    trimmedTerm = trimmedTerm.substring(1);
  }
  return users.filter((user) => {
    if (!user) {
      return false;
    }
    const profileSuggestions = [];
    const usernameSuggestions = getSuggestionsSplitByMultiple(
      (user.username || "").toLowerCase(),
      General.AUTOCOMPLETE_SPLIT_CHARACTERS
    );
    profileSuggestions.push(...usernameSuggestions);
    const first = (user.first_name || "").toLowerCase();
    const last = (user.last_name || "").toLowerCase();
    const full = first + " " + last;
    profileSuggestions.push(first, last, full);
    profileSuggestions.push((user.nickname || "").toLowerCase());
    const email = (user.email || "").toLowerCase();
    profileSuggestions.push(email);
    profileSuggestions.push((user.nickname || "").toLowerCase());
    const split = email.split("@");
    if (split.length > 1) {
      profileSuggestions.push(split[1]);
    }
    return profileSuggestions
      .filter((suggestion) => suggestion !== "")
      .some((suggestion) => suggestion.includes(trimmedTerm));
  });
}
const getUserTimezone = (user) => {
  return getTimezone(user?.timezone);
};
const getTimezone = (timezone) => {
  if (!timezone) {
    return "";
  }
  const { useAutomaticTimezone } = timezone;
  let useAutomatic = useAutomaticTimezone;
  if (typeof useAutomaticTimezone === "string") {
    useAutomatic = useAutomaticTimezone === "true";
  }
  if (useAutomatic) {
    return timezone.automaticTimezone;
  }
  return timezone.manualTimezone;
};
const getTimezoneRegion = (timezone) => {
  if (timezone) {
    const split = timezone.split("/");
    if (split.length > 1) {
      return split.pop().replace(/_/g, " ");
    }
  }
  return timezone;
};
const rnLogs = [];
function logWarning() {
  rnLogs.push(["warning"].concat(Array.from(arguments, String)));
}
function logError() {
  rnLogs.push(["error"].concat(Array.from(arguments, String)));
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
const RN_ITERATIONS = 8;
function rnCreateFixtures() {
  return Array.from({ length: 8 }, function (_, variant) {
    const fields = [];
    const attributes = [];
    for (let i = 0; i < 128; i++) {
      const type = ["text", "select", "multiselect"][i % 3];
      fields.push({
        id: "field-" + i,
        name: "Field " + i,
        type,
        attrs: {
          sort_order: (i * 19) % 128,
          value_type: i % 5 ? "" : "email",
          saml: i % 7 === 0,
          options: [
            { id: "a", name: "Alpha" },
            { id: "b", name: "Beta" },
            { id: "c", name: "Gamma" },
          ],
        },
      });
      attributes.push({
        fieldId: "field-" + i,
        value:
          type === "text"
            ? "Value " + i
            : type === "select"
              ? "b"
              : ["a,b", '["a","c"]', "missing, b", ""][variant % 4],
      });
    }
    attributes.push({ fieldId: "deleted-field", value: "preserved" });
    const users = fields.map(function (_2, i) {
      return {
        id: "user-" + i,
        username: "member." + variant + "_team-" + i,
        first_name: i % 3 ? "Alice" : "Bob",
        last_name: String(i),
        nickname: i % 2 ? "Al" : "",
        email: "member" + i + "@example.com",
        timezone: {
          useAutomaticTimezone: i % 2 ? "true" : false,
          automaticTimezone: "Asia/Tokyo",
          manualTimezone: "America/New_York",
        },
      };
    });
    return { fields, attributes, users, useDisplayType: variant % 2 === 0 };
  });
}
function rnExecute(fixture) {
  rnLogs.length = 0;
  const attributes = convertProfileAttributesToCustomAttributes(
    fixture.attributes,
    fixture.fields,
    sortCustomProfileAttributes,
    fixture.useDisplayType
  );
  const converted = fixture.fields.map(function (field, i) {
    const options = getFieldOptions(field);
    const value = fixture.attributes[i].value;
    const displayed = convertOptionsToDisplayValue(value, field.type, options);
    const ids = convertDisplayValueToOptionIds(displayed, field.type, options);
    return {
      type: getDisplayType(field),
      displayed,
      ids,
      selected: getSelectedOptionIds(ids, field.type),
      server: convertValueForServer(ids, field.type),
      fromServer: convertValueFromServer(
        convertValueForServer(ids, field.type),
        field.type,
        options
      ),
      selector: formatOptionsForSelector(field),
      saml: isCustomFieldSamlLinked(field),
    };
  });
  const usersByName = getUsersByUsername(fixture.users);
  const searches = ["@member", "alice", "team-1", "example.com", "nobody"].map(function (term) {
    return filterProfilesMatchingTerm(fixture.users, term).map(function (user) {
      const timezone = getUserTimezone(user);
      return {
        id: user.id,
        name: getFullName(user),
        region: getTimezoneRegion(timezone),
        known: usersByName[user.username].id === user.id,
      };
    });
  });
  return {
    attributes,
    map: convertToAttributesMap(attributes),
    converted,
    searches,
    logs: rnLogs.slice(),
    sameRoles: haveSameRoles("member admin member", "admin member"),
  };
}
function rnObserve(result) {
  return (
    result.attributes.reduce(function (n, a) {
      return n + a.value.length;
    }, 0) +
    result.converted.reduce(function (n, a) {
      return n + a.displayed.length + a.selected.length + a.selector.length;
    }, 0) +
    result.searches.reduce(function (n, users) {
      return n + users.length;
    }, 0)
  );
}
function rnFingerprint(result) {
  rnAssert(result.sameRoles && Object.keys(result.map).length === 129, "Profile role/map mismatch");
  rnAssert(
    result.searches[0].length === 128 && result.searches[4].length === 0,
    "User search mismatch"
  );
  return rnHash(JSON.stringify(result));
}
rnBenchmark([
  { "fingerprint": 3583323349, "observation": 2737 },
  { "fingerprint": 3245680951, "observation": 2821 },
  { "fingerprint": 92976421, "observation": 2905 },
  { "fingerprint": 3416570499, "observation": 1729 },
  { "fingerprint": 3583323349, "observation": 2737 },
  { "fingerprint": 3245680951, "observation": 2821 },
  { "fingerprint": 92976421, "observation": 2905 },
  { "fingerprint": 3416570499, "observation": 1729 },
]);
