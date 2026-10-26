// Extracted from https://github.com/mattermost/mattermost-mobile at 8a9427f25ad9f16ed333b1865eff9c4b057cb093.
// Workload: mattermost-dialog. See README.md, manifest.json and licenses/.
// Type/module syntax and formatting adapted; application algorithms retained.
// Copyright (c) 2015-present Mattermost, Inc. Apache-2.0.
function isAppSelectOption(value) {
  return typeof value === "object" && value !== null && "value" in value;
}
const DialogDataSources = {
  USERS: "users",
  CHANNELS: "channels",
  DYNAMIC: "dynamic",
};
const DialogElementTypes = {
  TEXT: "text",
  TEXTAREA: "textarea",
  SELECT: "select",
  RADIO: "radio",
  BOOL: "bool",
  FILE: "file",
  DATE: "date",
  DATETIME: "datetime",
  COLLAPSIBLE: "collapsible",
};
const DialogTextSubtypes = {
  NUMBER: "number",
  EMAIL: "email",
  PASSWORD: "password",
  URL: "url",
  TEXTAREA: "textarea",
};
function mapDialogTypeToAppFieldType(dialogType, dataSource) {
  switch (dialogType) {
    case DialogElementTypes.TEXT:
    case DialogElementTypes.TEXTAREA:
      return "text";
    case DialogElementTypes.SELECT:
      if (dataSource === DialogDataSources.USERS) {
        return "user";
      }
      if (dataSource === DialogDataSources.CHANNELS) {
        return "channel";
      }
      if (dataSource === DialogDataSources.DYNAMIC) {
        return "dynamic_select";
      }
      return "static_select";
    case DialogElementTypes.RADIO:
      return "radio";
    case DialogElementTypes.BOOL:
      return "bool";
    case DialogElementTypes.FILE:
      return "file";
    case DialogElementTypes.DATE:
      return "date";
    case DialogElementTypes.DATETIME:
      return "datetime";
    default:
      return "text";
  }
}
function mapAppFieldTypeToDialogType(appFieldType) {
  switch (appFieldType) {
    case "text":
      return DialogElementTypes.TEXT;
    case "static_select":
    case "dynamic_select":
    case "user":
    case "channel":
      return DialogElementTypes.SELECT;
    case "radio":
      return DialogElementTypes.RADIO;
    case "bool":
      return DialogElementTypes.BOOL;
    case "file":
      return DialogElementTypes.FILE;
    case "date":
      return DialogElementTypes.DATE;
    case "datetime":
      return DialogElementTypes.DATETIME;
    default:
      return DialogElementTypes.TEXT;
  }
}
function getDataSourceForAppFieldType(appFieldType) {
  switch (appFieldType) {
    case "user":
      return DialogDataSources.USERS;
    case "channel":
      return DialogDataSources.CHANNELS;
    case "dynamic_select":
      return DialogDataSources.DYNAMIC;
    default:
      return void 0;
  }
}
function createDialogElement(name, type, options) {
  return {
    name,
    type,
    optional: true,
    display_name: name,
    ...options,
  };
}
function createAppField(name, type, options) {
  return {
    name,
    type,
    is_required: false,
    label: name,
    position: 0,
    ...options,
  };
}
function supportsOptions(fieldType) {
  const supportedTypes = [
    DialogElementTypes.SELECT,
    DialogElementTypes.RADIO,
    "static_select",
    "dynamic_select",
    "radio",
    "user",
    "channel",
  ];
  return supportedTypes.includes(fieldType);
}
function supportsDataSource(fieldType) {
  return fieldType === DialogElementTypes.SELECT;
}
function flattenCollapsible(items, isCollapsible, getChildren) {
  return items.flatMap((item) =>
    isCollapsible(item)
      ? flattenCollapsible(getChildren(item) || [], isCollapsible, getChildren)
      : [item]
  );
}
function flattenDialogElements(elements) {
  return flattenCollapsible(
    elements,
    (el) => el.type === DialogElementTypes.COLLAPSIBLE,
    (el) => el.collapsible_config?.elements
  );
}
function flattenAppFields(fields) {
  return flattenCollapsible(
    fields,
    (f) => f.type === "collapsible",
    (f) => f.collapsible_config?.fields
  );
}
function collectFileIds(submission, elements = []) {
  const fileIds = [];
  elements.forEach((element) => {
    if (element.type === "file" && submission[element.name]) {
      fileIds.push(
        ...String(submission[element.name])
          .split(",")
          .map((id) => id.trim())
          .filter(Boolean)
      );
    }
  });
  return [...new Set(fileIds)];
}
function mergeFileFieldValues(accumulated, submission, elements = []) {
  const merged = { ...accumulated };
  elements.forEach((element) => {
    if (element.type === "file" && Object.prototype.hasOwnProperty.call(submission, element.name)) {
      merged[element.name] = submission[element.name];
    }
  });
  return merged;
}
function flattenFileFieldValues(byField) {
  const fileIds = [];
  Object.values(byField).forEach((value) => {
    fileIds.push(
      ...String(value)
        .split(",")
        .map((id) => id.trim())
        .filter(Boolean)
    );
  });
  return [...new Set(fileIds)];
}
function convertAppFormValuesToDialogSubmission(values, elements) {
  const submission = {};
  const errors = [];
  const valueKeys = Object.keys(values);
  if (valueKeys.length === 0) {
    return { submission, errors };
  }
  valueKeys.forEach((fieldName) => {
    const value = values[fieldName];
    const element = elements.find((e) => e.name === fieldName);
    if (!element) {
      errors.push(`Field ${fieldName} not found in dialog elements`);
      return;
    }
    switch (element.type) {
      case DialogElementTypes.TEXT:
      case DialogElementTypes.TEXTAREA:
        if (element.subtype === DialogTextSubtypes.NUMBER) {
          if (value === "" || value === null || value === void 0) {
            break;
          }
          const numValue = Number(value);
          submission[fieldName] = isNaN(numValue) ? String(value) : numValue;
        } else {
          submission[fieldName] = String(value || "");
        }
        break;
      case DialogElementTypes.RADIO:
      case DialogElementTypes.SELECT:
        if (
          element.type === DialogElementTypes.SELECT &&
          element.multiselect &&
          Array.isArray(value)
        ) {
          const extractedValues = value
            .map((option) =>
              isAppSelectOption(option) ? option.value || "" : String(option || "")
            )
            .filter((v) => v !== "");
          submission[fieldName] = extractedValues.join(",");
        } else if (isAppSelectOption(value)) {
          submission[fieldName] = String(value.value || "");
        } else {
          submission[fieldName] = String(value || "");
        }
        break;
      case DialogElementTypes.BOOL:
        submission[fieldName] = Boolean(value);
        break;
      case DialogElementTypes.FILE:
        submission[fieldName] = String(value || "");
        break;
      default:
        submission[fieldName] = String(value || "");
    }
  });
  return { submission, errors };
}
function convertDialogElementToAppField(element) {
  if (element.type === DialogElementTypes.COLLAPSIBLE) {
    return {
      name: element.name,
      type: "collapsible",
      label: element.display_name,
      collapsible_config: {
        fields:
          element.collapsible_config?.elements?.map((e) => convertDialogElementToAppField(e)) || [],
        expanded: !element.collapsible_config?.collapsed,
        bordered: !element.collapsible_config?.borderless,
      },
    };
  }
  const appField = {
    name: element.name,
    type: mapDialogTypeToAppFieldType(element.type, element.data_source),
    is_required: !element.optional,
    label: element.display_name,
    description: element.help_text,
    position: 0,
    // Will be set by caller based on order
  };
  if (element.type === DialogElementTypes.TEXT || element.type === DialogElementTypes.TEXTAREA) {
    appField.max_length = element.max_length;
    appField.min_length = element.min_length;
    if (element.type !== DialogElementTypes.TEXTAREA && element.subtype) {
      appField.subtype = element.subtype;
    }
  }
  if (element.type === DialogElementTypes.RADIO || element.type === DialogElementTypes.SELECT) {
    appField.options = element.options?.map((option) => ({
      label: option.text,
      value: option.value,
    }));
    if (element.type === DialogElementTypes.SELECT && element.multiselect) {
      appField.multiselect = element.multiselect;
    }
  }
  if (element.type === DialogElementTypes.FILE && element.allow_multiple) {
    appField.allow_multiple = true;
  }
  if (element.default) {
    appField.value = element.default;
  }
  if (element.placeholder) {
    appField.hint = element.placeholder;
  }
  if (element.type === DialogElementTypes.DATE || element.type === DialogElementTypes.DATETIME) {
    appField.min_date = element.min_date;
    appField.max_date = element.max_date;
    appField.time_interval = element.time_interval;
    appField.datetime_config = element.datetime_config;
  }
  appField.refresh = element.refresh;
  return appField;
}
function convertDialogToAppForm(config) {
  const convertedFields =
    config.dialog.elements?.map((element, index) => ({
      ...convertDialogElementToAppField(element),
      position: index,
    })) || [];
  const hasRefreshFields = flattenDialogElements(config.dialog.elements || []).some(
    (element) => element.refresh === true
  );
  const sourceUrl = config.dialog.source_url;
  const form = {
    title: config.dialog.title,
    header: config.dialog.introduction_text || void 0,
    fields: convertedFields,
    submit_buttons: void 0,
    // Pass through submit label from dialog config
    submit_label: config.dialog.submit_label || void 0,
    // Set source if sourceUrl is provided or if any fields have refresh enabled (matching webapp behavior)
    source:
      (sourceUrl && sourceUrl.trim()) || hasRefreshFields
        ? {
            path: sourceUrl || "/dialog/refresh",
            expand: {},
          }
        : void 0,
    submit: {
      path: "/dialog/submit",
      expand: {},
    },
  };
  return form;
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
  const types = ["text", "textarea", "select", "radio", "bool", "file", "date", "datetime"];
  return Array.from({ length: 8 }, function (_, variant) {
    const elements = [];
    const values = {};
    for (let i = 0; i < 64; i++) {
      const type = types[(i + variant) % types.length];
      const name = "field-" + i;
      const element = createDialogElement(name, type, {
        display_name: "Field " + i,
        subtype: i % 2 ? "number" : void 0,
        optional: i % 3 !== 0,
        data_source: i % 4 === 0 ? "users" : "",
        max_length: 100,
        min_length: 1,
        refresh: i === 5,
        multiselect: i % 3 === 0,
        options: [
          { text: "Alpha", value: "a" },
          { text: "Beta", value: "b" },
        ],
        min_date: "2026-01-01",
        max_date: "2026-12-31",
        time_interval: 15,
      });
      elements.push(element);
      values[name] =
        type === "select"
          ? element.multiselect
            ? [{ label: "Alpha", value: "a" }, "b"]
            : { value: "a" }
          : type === "bool"
            ? i % 2 === 0
            : type === "file"
              ? " file-a, file-b, file-a "
              : i % 7
                ? String(i * 3)
                : "";
    }
    const nested = createDialogElement("section", "collapsible", {
      collapsible_config: {
        elements: elements.slice(32),
        collapsed: variant % 2 === 0,
        borderless: false,
      },
    });
    return {
      config: {
        dialog: {
          title: "Fixture dialog",
          introduction_text: "Instructions",
          elements: elements.slice(0, 32).concat(nested),
        },
      },
      values,
    };
  });
}
function rnExecute(fixture) {
  const form = convertDialogToAppForm(fixture.config);
  const elements = flattenDialogElements(fixture.config.dialog.elements);
  const submission = convertAppFormValuesToDialogSubmission(fixture.values, elements);
  const files = collectFileIds(submission.submission, elements);
  const merged = mergeFileFieldValues({ earlier: "file-c" }, submission.submission, elements);
  const normalized = flattenAppFields(form.fields).map(function (field) {
    const copy = createAppField(field.name, field.type, field);
    return {
      name: copy.name,
      type: copy.type,
      legacyType: mapAppFieldTypeToDialogType(copy.type),
      dataSource: getDataSourceForAppFieldType(copy.type),
      supportsOptions: supportsOptions(copy.type),
      supportsDataSource: supportsDataSource(mapAppFieldTypeToDialogType(copy.type)),
    };
  });
  return {
    form,
    submission,
    files,
    mergedFiles: flattenFileFieldValues(merged),
    fields: flattenAppFields(form.fields),
    normalized,
    reverseTypes: form.fields.map(function (field) {
      return [mapAppFieldTypeToDialogType(field.type), getDataSourceForAppFieldType(field.type)];
    }),
  };
}
function rnObserve(result) {
  return (
    result.fields.length +
    Object.keys(result.submission.submission).length +
    result.files.length +
    result.mergedFiles.length +
    result.form.fields.length +
    result.normalized.length
  );
}
function rnFingerprint(result) {
  rnAssert(
    result.fields.length === 64 && result.submission.errors.length === 0,
    "Dialog conversion lost fields"
  );
  rnAssert(result.files.length === 2, "File IDs were not deduplicated");
  rnAssert(
    result.normalized.every(function (field) {
      return field.name && field.type && field.legacyType;
    }),
    "Invalid normalized field"
  );
  return rnHash(JSON.stringify(result));
}
rnBenchmark([
  { "fingerprint": 200297285, "observation": 229 },
  { "fingerprint": 4269619273, "observation": 228 },
  { "fingerprint": 1735992765, "observation": 228 },
  { "fingerprint": 2648457104, "observation": 229 },
  { "fingerprint": 4240210044, "observation": 229 },
  { "fingerprint": 2062790938, "observation": 229 },
  { "fingerprint": 3112552525, "observation": 229 },
  { "fingerprint": 3910370676, "observation": 229 },
]);
