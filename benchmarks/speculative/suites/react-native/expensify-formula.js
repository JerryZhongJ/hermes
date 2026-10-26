// Extracted from https://github.com/Expensify/App at 0eff10433514a9be0faa2a568d5779dc06e05d44.
// Workload: expensify-formula. See README.md, manifest.json and licenses/.
// Type/module syntax and formatting adapted; application algorithms retained.
// Copyright (c) 2020 Expensify Inc. MIT License.
const CONST = {
  "REPORT": {
    "TYPE": {
      "EXPENSE": "expense",
      "INVOICE": "invoice",
      "CHAT": "chat",
      "IOU": "iou",
      "TASK": "task",
    },
    "UNSUPPORTED_TYPE": { "BILL": "bill", "PAYCHECK": "paycheck" },
  },
};
function isEmptyObject(obj) {
  return Object.keys(obj ?? {}).length === 0;
}
const FORMULA_PART_TYPES = {
  REPORT: "report",
  FIELD: "field",
  USER: "user",
  FREETEXT: "freetext",
};
function extract(formula, opener = "{", closer = "}") {
  if (!formula || typeof formula !== "string") {
    return [];
  }
  const letters = formula.split("");
  const sections = [];
  let nesting = 0;
  let start = 0;
  for (let i = 0; i < letters.length; i++) {
    if (letters.at(i) === "\\") {
      i++;
      continue;
    }
    if (letters.at(i) === opener) {
      if (nesting === 0) {
        start = i;
      }
      nesting++;
    }
    if (letters.at(i) === closer && nesting > 0) {
      nesting--;
      if (nesting === 0) {
        sections.push(formula.substring(start, i + 1));
      }
    }
  }
  return sections;
}
function parse(formula) {
  if (!formula || typeof formula !== "string") {
    return [];
  }
  const parts = [];
  const formulaParts = extract(formula);
  if (formulaParts.length === 0) {
    if (formula.trim()) {
      parts.push({
        definition: formula,
        type: FORMULA_PART_TYPES.FREETEXT,
        fieldPath: [],
        functions: [],
      });
    }
    return parts;
  }
  let lastIndex = 0;
  for (const part of formulaParts) {
    const partIndex = formula.indexOf(part, lastIndex);
    if (partIndex > lastIndex) {
      const freeText = formula.substring(lastIndex, partIndex);
      if (freeText) {
        parts.push({
          definition: freeText,
          type: FORMULA_PART_TYPES.FREETEXT,
          fieldPath: [],
          functions: [],
        });
      }
    }
    parts.push(parsePart(part));
    lastIndex = partIndex + part.length;
  }
  if (lastIndex < formula.length) {
    const freeText = formula.substring(lastIndex);
    if (freeText) {
      parts.push({
        definition: freeText,
        type: FORMULA_PART_TYPES.FREETEXT,
        fieldPath: [],
        functions: [],
      });
    }
  }
  return parts;
}
function parsePart(definition) {
  const part = {
    definition,
    type: FORMULA_PART_TYPES.FREETEXT,
    fieldPath: [],
    functions: [],
  };
  if (!definition.startsWith("{") || !definition.endsWith("}")) {
    return part;
  }
  const cleanDefinition = definition.slice(1, -1).trim();
  if (!cleanDefinition) {
    return part;
  }
  const segments = cleanDefinition.split("|");
  const fieldSegment = segments.at(0);
  const functions = segments.slice(1);
  const fieldPath = fieldSegment?.split(":");
  const type = fieldPath?.at(0)?.toLowerCase();
  if (type === "report") {
    part.type = FORMULA_PART_TYPES.REPORT;
  } else if (type === "field") {
    part.type = FORMULA_PART_TYPES.FIELD;
  } else if (type === "user") {
    part.type = FORMULA_PART_TYPES.USER;
  }
  part.fieldPath = fieldPath?.slice(1) ?? [];
  part.functions = functions;
  return part;
}
function hasCircularReferences(fieldValue, fieldName, fieldList) {
  const formulaPartDefinitions = extract(fieldValue);
  if (formulaPartDefinitions.length === 0 || isEmptyObject(fieldList)) {
    return false;
  }
  const visitedFields = /* @__PURE__ */ new Set();
  const fieldsByName = new Map(Object.values(fieldList).map((field) => [field.name, field]));
  const hasCircularReferencesRecursive = (currentFieldValue, currentFieldName) => {
    if (visitedFields.has(currentFieldName)) {
      return true;
    }
    visitedFields.add(currentFieldName);
    const currentFormulaPartDefinitions = extract(currentFieldValue);
    for (const formulaPartDefinition of currentFormulaPartDefinitions) {
      const part = parsePart(formulaPartDefinition);
      if (part.type !== FORMULA_PART_TYPES.FIELD) {
        continue;
      }
      const referencedFieldName = part.fieldPath.at(0)?.trim();
      if (!referencedFieldName) {
        continue;
      }
      if (referencedFieldName === fieldName || visitedFields.has(referencedFieldName)) {
        return true;
      }
      const referencedField = fieldsByName.get(referencedFieldName);
      if (referencedField?.defaultValue) {
        if (hasCircularReferencesRecursive(referencedField.defaultValue, referencedFieldName)) {
          return true;
        }
      }
    }
    visitedFields.delete(currentFieldName);
    return false;
  };
  return hasCircularReferencesRecursive(fieldValue, fieldName);
}
function applyFunctions(value, functions) {
  let result = value;
  for (const func of functions) {
    const [functionName, ...args] = func.split(":");
    switch (functionName.toLowerCase()) {
      case "frontpart":
        result = getFrontPart(result);
        break;
      case "substr":
        result = getSubstring(result, args);
        break;
      case "domain":
        result = getDomainName(result);
        break;
      default:
        break;
    }
  }
  return result;
}
function getFrontPart(value) {
  const trimmed = value.trim();
  if (trimmed.includes("@")) {
    return trimmed.split("@").at(0) ?? "";
  }
  return trimmed.split(" ").at(0) ?? "";
}
function getDomainName(value) {
  const trimmed = value.trim();
  if (trimmed.includes("@")) {
    return trimmed.split("@").at(1) ?? "";
  }
  return "";
}
function getSubstring(value, args) {
  const start = parseInt(args.at(0) ?? "", 10) || 0;
  const length = args.at(1) ? parseInt(args.at(1) ?? "", 10) : void 0;
  if (length !== void 0) {
    return value.substring(start, start + length);
  }
  return value.substring(start);
}
function hasFieldReferences(formula) {
  if (!formula?.includes("{field:")) {
    return false;
  }
  const parsed = parse(formula);
  return parsed.some((part) => part.type === FORMULA_PART_TYPES.FIELD);
}
function computePersonalDetailsField(path, personalDetails, policy) {
  const [field] = path;
  if (!personalDetails || !field) {
    return "";
  }
  switch (field.toLowerCase()) {
    case "firstname":
      return personalDetails.firstName || personalDetails.login || "";
    case "lastname":
      return personalDetails.lastName || personalDetails.login || "";
    case "fullname":
      return personalDetails.displayName || personalDetails.login || "";
    case "email":
      return personalDetails.login ?? "";
    // userid/customfield1 returns employeeUserID from policy.employeeList
    case "userid":
    case "customfield1": {
      const email = personalDetails.login;
      const isGlCodesEnabled = policy?.glCodes === true;
      if (!isGlCodesEnabled || !email || !policy?.employeeList) {
        return "";
      }
      return policy.employeeList[email]?.employeeUserID ?? "";
    }
    // payrollid/customfield2 returns employeePayrollID from policy.employeeList
    case "payrollid":
    case "customfield2": {
      const email = personalDetails.login;
      const isGlCodesEnabled = policy?.glCodes === true;
      if (!isGlCodesEnabled || !email || !policy?.employeeList) {
        return "";
      }
      return policy.employeeList[email]?.employeePayrollID ?? "";
    }
    default:
      return "";
  }
}
function formatType(type) {
  if (!type) {
    return "";
  }
  const typeMapping = {
    [CONST.REPORT.TYPE.EXPENSE]: "Expense Report",
    [CONST.REPORT.TYPE.INVOICE]: "Invoice",
    [CONST.REPORT.TYPE.CHAT]: "Chat",
    [CONST.REPORT.UNSUPPORTED_TYPE.BILL]: "Bill",
    [CONST.REPORT.UNSUPPORTED_TYPE.PAYCHECK]: "Paycheck",
    [CONST.REPORT.TYPE.IOU]: "IOU",
    [CONST.REPORT.TYPE.TASK]: "Task",
    trip: "Trip",
  };
  return typeMapping[type.toLowerCase()] || type;
}
function getOrdinalSuffix(day) {
  if (day >= 11 && day <= 13) {
    return "th";
  }
  switch (day % 10) {
    case 1:
      return "st";
    case 2:
      return "nd";
    case 3:
      return "rd";
    default:
      return "th";
  }
}
function calculateISOWeekNumber(date) {
  const target = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()));
  const dayNum = target.getUTCDay() || 7;
  target.setUTCDate(target.getUTCDate() + 4 - dayNum);
  const yearStart = new Date(Date.UTC(target.getUTCFullYear(), 0, 1));
  const weekNum = Math.ceil(((target.getTime() - yearStart.getTime()) / 864e5 + 1) / 7);
  return weekNum;
}
function calculateDayOfYear(date) {
  const year = date.getFullYear();
  const yearStart = new Date(year, 0, 1);
  return Math.floor((date.getTime() - yearStart.getTime()) / (1e3 * 60 * 60 * 24));
}
function getUTCTimeComponents(date) {
  const hours = date.getUTCHours();
  const minutes = date.getUTCMinutes();
  const seconds = date.getUTCSeconds();
  let hours12 = hours;
  if (hours === 0) {
    hours12 = 12;
  } else if (hours > 12) {
    hours12 = hours - 12;
  }
  const meridiem = hours >= 12 ? "pm" : "am";
  const meridiemUpperCase = hours >= 12 ? "PM" : "AM";
  return {
    hours,
    minutes,
    seconds,
    hours12,
    meridiem,
    meridiemUpperCase,
  };
}
function applyTokenReplacement(format, tokens) {
  let result = format;
  const sortedTokens = [...tokens].sort((a, b) => b.token.length - a.token.length);
  const placeholderMap = {};
  for (let i = 0; i < sortedTokens.length; i++) {
    const tokenData = sortedTokens.at(i);
    if (!tokenData) {
      continue;
    }
    const { token, value } = tokenData;
    const placeholder = `###${i.toString().padStart(3, "0")}###`;
    const regex = new RegExp(token.replaceAll(/[.*+?^${}()|[\]\\]/g, "\\$&"), "g");
    if (result.includes(token)) {
      result = result.replaceAll(regex, placeholder);
      placeholderMap[placeholder] = value;
    }
  }
  for (const [placeholder, value] of Object.entries(placeholderMap)) {
    result = result.replaceAll(
      new RegExp(placeholder.replaceAll(/[.*+?^${}()|[\]\\]/g, "\\$&"), "g"),
      value
    );
  }
  return result;
}
function getBase62ReportID(reportID) {
  const alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";
  let result = "";
  let remainder = reportID;
  while (remainder > 0) {
    const currentVal = remainder % 62;
    result = alphabet[currentVal] + result;
    remainder = Math.floor(remainder / 62);
  }
  return `R${result.padStart(11, "0")}`;
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
const RN_ITERATIONS = 24;
function rnCreateFixtures() {
  const fixtures = [];
  for (let variant = 0; variant < 8; variant++) {
    const fields = {};
    for (let i = 0; i < 24; i++) {
      fields["id-" + i] = {
        name: "field" + i,
        defaultValue:
          i === 23 ? (variant % 2 ? "{field:field0}" : "done") : "{field:field" + (i + 1) + "}",
      };
    }
    const formulas = [
      "Trip {report:type} for {user:email|frontPart}",
      "{field:field0} / {report:total|substr:0:5}",
      "Free text without tokens",
      "",
      "  ",
      "Escaped \\{field:ignored} and {field:missing}",
      "{report:{field:nested}} {user:email|domain}",
      "{unknown:x} {} {FIELD:field1|frontPart}",
    ];
    for (let i = 0; i < 24; i++)
      formulas.push("Expense " + i + " {field:field" + i + "|substr:1:4}");
    fixtures.push({
      fields,
      formulas,
      value: variant % 2 ? " alice@example.com " : " Travel report ",
      date: new Date(Date.UTC(2024 + (variant % 3), 0, 11 + variant, 12, 17, 23)),
      user: {
        firstName: "Alice",
        lastName: variant % 2 ? "" : "Wang",
        displayName: "Alice Wang",
        login: "alice@example.com",
      },
      policy: {
        glCodes: variant % 2 === 0,
        employeeList: {
          "alice@example.com": { employeeUserID: "E-42", employeePayrollID: "P-19" },
        },
      },
    });
  }
  return fixtures;
}
function rnExecute(fixture) {
  const time = getUTCTimeComponents(fixture.date);
  const tokens = [
    { token: "yyyy", value: String(fixture.date.getUTCFullYear()) },
    { token: "MM", value: String(fixture.date.getUTCMonth() + 1).padStart(2, "0") },
    { token: "dd", value: String(fixture.date.getUTCDate()).padStart(2, "0") },
    { token: "S", value: getOrdinalSuffix(fixture.date.getUTCDate()) },
    { token: "W", value: String(calculateISOWeekNumber(fixture.date)) },
    { token: "HH", value: String(time.hours).padStart(2, "0") },
    { token: "mm", value: String(time.minutes).padStart(2, "0") },
    { token: "a", value: time.meridiem },
  ];
  const titleDates = ["yyyy-MM-dd HH:mm", "ddS W", "yyyy/yyyy MM", "HH:mm a", ""].map(
    function (format) {
      return applyTokenReplacement(format, tokens);
    }
  );
  const userFields = [
    "firstname",
    "lastname",
    "fullname",
    "email",
    "userid",
    "payrollid",
    "customfield1",
    "customfield2",
    "unknown",
  ].map(function (name) {
    return computePersonalDetailsField([name], fixture.user, fixture.policy);
  });
  const formulas = fixture.formulas.map(function (formula) {
    const parts = parse(formula);
    return {
      parts,
      circular: hasCircularReferences(formula, "field0", fixture.fields),
      fieldReferences: hasFieldReferences(formula),
      transformed: parts.map(function (part) {
        return applyFunctions(fixture.value, part.functions);
      }),
    };
  });
  const reportLabels = [
    "expense",
    "invoice",
    "chat",
    "bill",
    "paycheck",
    "iou",
    "task",
    "trip",
    "unknown",
    void 0,
  ].map(function (type, index) {
    return formatType(type) + " " + getBase62ReportID(1e8 + index);
  });
  const calendarDate = new Date(fixture.date.getUTCFullYear(), 0, fixture.date.getUTCDate(), 12);
  return {
    formulas,
    userFields,
    titleDates,
    time,
    reportLabels,
    dayOfYear: calculateDayOfYear(calendarDate),
  };
}
function rnObserve(result) {
  return result.formulas.reduce(
    function (sum, row) {
      return (
        sum +
        row.parts.length +
        (row.circular ? 1 : 0) +
        row.transformed.reduce(function (n, value) {
          return n + value.length;
        }, 0)
      );
    },
    result.userFields.join("").length +
      result.titleDates.join("").length +
      result.reportLabels.join("").length +
      result.dayOfYear
  );
}
function rnFingerprint(result) {
  return rnHash(JSON.stringify(result));
}
rnBenchmark([
  { "fingerprint": 351457524, "observation": 1040 },
  { "fingerprint": 4152982473, "observation": 1223 },
  { "fingerprint": 1988461601, "observation": 1042 },
  { "fingerprint": 2024364954, "observation": 1225 },
  { "fingerprint": 955365216, "observation": 1044 },
  { "fingerprint": 4080992183, "observation": 1227 },
  { "fingerprint": 1540898991, "observation": 1046 },
  { "fingerprint": 796955818, "observation": 1229 },
]);
