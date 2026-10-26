// Extracted from https://github.com/Expensify/App at 0eff10433514a9be0faa2a568d5779dc06e05d44.
// Workload: expensify-csv-categories. See README.md, manifest.json and licenses/.
// Type/module syntax and formatting adapted; application algorithms retained.
// Copyright (c) 2020 Expensify Inc. MIT License.
const CONST = {
  "DISABLED_MAX_EXPENSE_VALUE": 1e10,
  "POLICY": {
    "EXPENSE_LIMIT_TYPES": { "EXPENSE": "expense", "DAILY": "daily" },
    "EXPENSE_DEFAULT_RULE_TYPE": { "CATEGORY": "category" },
    "RULE_CONDITIONS": { "MATCHES": "matches" },
    "FIELDS": { "CATEGORY": "category" },
  },
  "CSV_IMPORT_COLUMNS": {
    "NAME": "name",
    "GL_CODE": "glCode",
    "ENABLED": "enabled",
    "MAX_AMOUNT_NO_RECEIPT": "maxAmountNoReceipt",
    "MAX_AMOUNT_NO_ITEMIZED_RECEIPT": "maxAmountNoItemizedReceipt",
    "PAYROLL_CODE": "payrollCode",
    "ARE_COMMENTS_REQUIRED": "areCommentsRequired",
    "COMMENT_HINT": "commentHint",
    "MAX_EXPENSE_AMOUNT": "maxExpenseAmount",
    "EXPENSE_LIMIT_TYPE": "expenseLimitType",
  },
  "RED_BRICK_ROAD_PENDING_ACTION": { "DELETE": "delete" },
};
function convertToBackendAmount(amountAsFloat) {
  return Math.round(amountAsFloat * 100);
}
const THOUSANDS_SEPARATED_NUMBER_REGEX = /^\d{1,3}(,\d{3})+(\.\d+)?$/;
function parseCsvNumber(value) {
  return Number(THOUSANDS_SEPARATED_NUMBER_REGEX.test(value) ? value.replaceAll(",", "") : value);
}
function parseCsvReceiptValue(raw) {
  if (raw === void 0) {
    return void 0;
  }
  const trimmed = raw.trim().toLowerCase();
  if (!trimmed || trimmed === "default") {
    return void 0;
  }
  if (trimmed === "required" || trimmed === "always_required") {
    return 0;
  }
  if (trimmed === "not_required") {
    return CONST.DISABLED_MAX_EXPENSE_VALUE;
  }
  const num = parseCsvNumber(trimmed);
  if (Number.isFinite(num) && num >= 0) {
    return convertToBackendAmount(num);
  }
  return void 0;
}
function parseCsvAmountValue(raw) {
  const trimmed = raw?.trim();
  if (!trimmed) {
    return void 0;
  }
  const num = parseCsvNumber(trimmed);
  return Number.isFinite(num) && num >= 0 ? convertToBackendAmount(num) : void 0;
}
function parseCsvExpenseLimitType(raw) {
  const trimmed = raw?.trim().toLowerCase();
  return Object.values(CONST.POLICY.EXPENSE_LIMIT_TYPES).find((type) => type === trimmed);
}
function buildCategoriesFromSpreadsheet(spreadsheet, policyCategories) {
  const { containsHeader = true } = spreadsheet ?? {};
  const columns = Object.values(spreadsheet?.columns ?? {});
  const categoriesNamesColumn = columns.findIndex(
    (column) => column === CONST.CSV_IMPORT_COLUMNS.NAME
  );
  const categoriesGLCodeColumn = columns.findIndex(
    (column) => column === CONST.CSV_IMPORT_COLUMNS.GL_CODE
  );
  const categoriesEnabledColumn = columns.findIndex(
    (column) => column === CONST.CSV_IMPORT_COLUMNS.ENABLED
  );
  const categoriesMaxAmountNoReceiptColumn = columns.findIndex(
    (column) => column === CONST.CSV_IMPORT_COLUMNS.MAX_AMOUNT_NO_RECEIPT
  );
  const categoriesMaxAmountNoItemizedReceiptColumn = columns.findIndex(
    (column) => column === CONST.CSV_IMPORT_COLUMNS.MAX_AMOUNT_NO_ITEMIZED_RECEIPT
  );
  const categoriesPayrollCodeColumn = columns.findIndex(
    (column) => column === CONST.CSV_IMPORT_COLUMNS.PAYROLL_CODE
  );
  const categoriesAreCommentsRequiredColumn = columns.findIndex(
    (column) => column === CONST.CSV_IMPORT_COLUMNS.ARE_COMMENTS_REQUIRED
  );
  const categoriesCommentHintColumn = columns.findIndex(
    (column) => column === CONST.CSV_IMPORT_COLUMNS.COMMENT_HINT
  );
  const categoriesMaxExpenseAmountColumn = columns.findIndex(
    (column) => column === CONST.CSV_IMPORT_COLUMNS.MAX_EXPENSE_AMOUNT
  );
  const categoriesExpenseLimitTypeColumn = columns.findIndex(
    (column) => column === CONST.CSV_IMPORT_COLUMNS.EXPENSE_LIMIT_TYPE
  );
  const categoriesNames = spreadsheet?.data[categoriesNamesColumn].map((name) => name);
  const categoriesEnabled =
    categoriesEnabledColumn !== -1
      ? spreadsheet?.data[categoriesEnabledColumn].map((enabled) => enabled)
      : [];
  const categoriesGLCode =
    categoriesGLCodeColumn !== -1
      ? spreadsheet?.data[categoriesGLCodeColumn].map((glCode) => glCode)
      : [];
  const categoriesMaxAmountNoReceipt =
    categoriesMaxAmountNoReceiptColumn !== -1
      ? spreadsheet?.data[categoriesMaxAmountNoReceiptColumn]
      : [];
  const categoriesMaxAmountNoItemizedReceipt =
    categoriesMaxAmountNoItemizedReceiptColumn !== -1
      ? spreadsheet?.data[categoriesMaxAmountNoItemizedReceiptColumn]
      : [];
  const categoriesPayrollCode =
    categoriesPayrollCodeColumn !== -1 ? spreadsheet?.data[categoriesPayrollCodeColumn] : [];
  const categoriesAreCommentsRequired =
    categoriesAreCommentsRequiredColumn !== -1
      ? spreadsheet?.data[categoriesAreCommentsRequiredColumn]
      : [];
  const categoriesCommentHint =
    categoriesCommentHintColumn !== -1 ? spreadsheet?.data[categoriesCommentHintColumn] : [];
  const categoriesMaxExpenseAmount =
    categoriesMaxExpenseAmountColumn !== -1
      ? spreadsheet?.data[categoriesMaxExpenseAmountColumn]
      : [];
  const categoriesExpenseLimitType =
    categoriesExpenseLimitTypeColumn !== -1
      ? spreadsheet?.data[categoriesExpenseLimitTypeColumn]
      : [];
  return categoriesNames?.slice(containsHeader ? 1 : 0).map((name, index) => {
    const categoryAlreadyExists = policyCategories?.[name];
    const existingGLCodeOrDefault = categoryAlreadyExists?.["GL Code"] ?? "";
    const dataIndex = containsHeader ? index + 1 : index;
    const parsedMaxAmountNoReceipt =
      categoriesMaxAmountNoReceiptColumn !== -1
        ? parseCsvReceiptValue(categoriesMaxAmountNoReceipt?.[dataIndex]?.toString())
        : void 0;
    const parsedMaxAmountNoItemizedReceipt =
      categoriesMaxAmountNoItemizedReceiptColumn !== -1
        ? parseCsvReceiptValue(categoriesMaxAmountNoItemizedReceipt?.[dataIndex]?.toString())
        : void 0;
    const parsedMaxExpenseAmount =
      categoriesMaxExpenseAmountColumn !== -1
        ? parseCsvAmountValue(categoriesMaxExpenseAmount?.[dataIndex]?.toString())
        : void 0;
    const parsedExpenseLimitType =
      categoriesExpenseLimitTypeColumn !== -1
        ? parseCsvExpenseLimitType(categoriesExpenseLimitType?.[dataIndex]?.toString())
        : void 0;
    return {
      name,
      enabled:
        categoriesEnabledColumn !== -1
          ? ["true", "yes"].includes(
              categoriesEnabled?.[dataIndex]?.toString().trim().toLowerCase() ?? ""
            )
          : true,
      // eslint-disable-next-line @typescript-eslint/naming-convention
      "GL Code":
        categoriesGLCodeColumn !== -1
          ? (categoriesGLCode?.[dataIndex] ?? "")
          : existingGLCodeOrDefault,
      ...(parsedMaxAmountNoReceipt !== void 0 && { maxAmountNoReceipt: parsedMaxAmountNoReceipt }),
      ...(parsedMaxAmountNoItemizedReceipt !== void 0 && {
        maxAmountNoItemizedReceipt: parsedMaxAmountNoItemizedReceipt,
      }),
      // eslint-disable-next-line @typescript-eslint/naming-convention
      ...(categoriesPayrollCodeColumn !== -1 && {
        "Payroll Code": categoriesPayrollCode?.[dataIndex] ?? "",
      }),
      ...(categoriesAreCommentsRequiredColumn !== -1 && {
        areCommentsRequired: ["true", "yes"].includes(
          categoriesAreCommentsRequired?.[dataIndex]?.toString().trim().toLowerCase() ?? ""
        ),
      }),
      ...(categoriesCommentHintColumn !== -1 && {
        commentHint: categoriesCommentHint?.[dataIndex] ?? "",
      }),
      ...(parsedMaxExpenseAmount !== void 0 && { maxExpenseAmount: parsedMaxExpenseAmount }),
      ...(parsedExpenseLimitType !== void 0 && { expenseLimitType: parsedExpenseLimitType }),
    };
  });
}
const CATEGORY_TAX_RULE_KEY_PREFIX = "category-tax:";
function isCategoryRuleDraft(form, editingCategoryName) {
  return (
    !!editingCategoryName ||
    form?.ruleType === CONST.POLICY.EXPENSE_DEFAULT_RULE_TYPE.CATEGORY ||
    !!form?.categoriesToMatch?.length
  );
}
function hasUsableTaxRates(policy) {
  return !!policy?.tax?.trackingEnabled && Object.keys(policy?.taxRates?.taxes ?? {}).length > 0;
}
function isSelectableTaxRate(policy, taxID, taxRate, isCategoryRule) {
  return (
    !taxRate.isDisabled &&
    taxRate.pendingAction !== CONST.RED_BRICK_ROAD_PENDING_ACTION.DELETE &&
    !(isCategoryRule && taxID === policy?.taxRates?.defaultExternalID)
  );
}
function getCategoryTaxRuleDraftFromGeneratedValues({ tax, ...values }, policy) {
  const taxRate = tax ? policy?.taxRates?.taxes?.[tax] : void 0;
  const selectableTax =
    tax && taxRate && isSelectableTaxRate(policy, tax, taxRate, true) ? tax : void 0;
  return {
    ...values,
    tax: selectableTax,
    ruleType: CONST.POLICY.EXPENSE_DEFAULT_RULE_TYPE.CATEGORY,
  };
}
function hasSelectableCategoryTaxRate(policy) {
  if (!hasUsableTaxRates(policy)) {
    return false;
  }
  return Object.entries(policy?.taxRates?.taxes ?? {}).some(([taxID, taxRate]) =>
    isSelectableTaxRate(policy, taxID, taxRate, true)
  );
}
function getCategoryTaxRuleKey(categoryName) {
  return `${CATEGORY_TAX_RULE_KEY_PREFIX}${categoryName}`;
}
function isCategoryTaxRuleKey(key) {
  return key.startsWith(CATEGORY_TAX_RULE_KEY_PREFIX);
}
function getRuleCategoryName(rule) {
  return rule.applyWhen?.find(
    ({ condition, field }) =>
      condition === CONST.POLICY.RULE_CONDITIONS.MATCHES && field === CONST.POLICY.FIELDS.CATEGORY
  )?.value;
}
function getCategoryTaxRules(expenseRules) {
  return (expenseRules ?? []).filter(
    (rule) => !!rule.tax?.field_id_TAX?.externalID && !!getRuleCategoryName(rule)
  );
}
function matchesCategoryTaxRule(rule, categoryName) {
  return getRuleCategoryName(rule) === categoryName;
}
function getCategoryTaxRule(expenseRules, categoryName) {
  return getCategoryTaxRules(expenseRules).find((rule) =>
    matchesCategoryTaxRule(rule, categoryName)
  );
}
function categoryHasTaxRule(expenseRules, categoryName) {
  return !!getCategoryTaxRule(expenseRules, categoryName);
}
function getCategoryTaxRuleTaxID(expenseRules, categoryName) {
  return getCategoryTaxRule(expenseRules, categoryName)?.tax?.field_id_TAX?.externalID;
}
function getTaxRateDisplayName(policy, taxID, savedTaxRate) {
  if (!taxID) {
    return "";
  }
  const taxRate = policy?.taxRates?.taxes?.[taxID];
  if (taxRate) {
    return `${taxRate.name} (${taxRate.value})`;
  }
  if (savedTaxRate?.name && savedTaxRate.value) {
    return `${savedTaxRate.name} (${savedTaxRate.value})`;
  }
  return taxID;
}
function getRuleDeletionPendingAction(policy, policyCategories, categoryName, taxID) {
  const isCategoryDeleting =
    !!categoryName &&
    policyCategories?.[categoryName]?.pendingAction === CONST.RED_BRICK_ROAD_PENDING_ACTION.DELETE;
  const isTaxDeleting =
    !!taxID &&
    policy?.taxRates?.taxes?.[taxID]?.pendingAction === CONST.RED_BRICK_ROAD_PENDING_ACTION.DELETE;
  return isCategoryDeleting || isTaxDeleting ? CONST.RED_BRICK_ROAD_PENDING_ACTION.DELETE : void 0;
}
function getCategoryNameFromTaxRuleKey(key) {
  return key.slice(CATEGORY_TAX_RULE_KEY_PREFIX.length);
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
  const keys = [
    "NAME",
    "GL_CODE",
    "ENABLED",
    "MAX_AMOUNT_NO_RECEIPT",
    "MAX_AMOUNT_NO_ITEMIZED_RECEIPT",
    "PAYROLL_CODE",
    "ARE_COMMENTS_REQUIRED",
    "COMMENT_HINT",
    "MAX_EXPENSE_AMOUNT",
    "EXPENSE_LIMIT_TYPE",
  ];
  const numbers = [
    "0",
    "12.50",
    "1,234.56",
    "1,5",
    "-1",
    "",
    "default",
    "always_required",
    "not_required",
  ];
  return Array.from({ length: 8 }, function (_, variant) {
    const selected =
      variant % 3 === 0
        ? keys.filter(function (key) {
            return key !== "GL_CODE";
          })
        : keys;
    const columns = {};
    const data = [];
    const categories = {};
    for (let col = 0; col < selected.length; col++) {
      const key = selected[col];
      columns[String(col)] = CONST.CSV_IMPORT_COLUMNS[key];
      const values = variant % 2 ? [] : [key];
      for (let i = 0; i < 512; i++) {
        const name = "Category " + variant + "-" + i;
        let value;
        if (key === "NAME") value = name;
        else if (key === "GL_CODE" || key === "PAYROLL_CODE") value = String(100 + (i % 64));
        else if (key === "ENABLED" || key === "ARE_COMMENTS_REQUIRED")
          value = ["yes", "true", "FALSE", " no "][i % 4];
        else if (key === "COMMENT_HINT") value = "Describe expense " + i;
        else if (key === "EXPENSE_LIMIT_TYPE")
          value = ["expense", "daily", "other", " DAILY "][i % 4];
        else value = numbers[(i + variant) % numbers.length];
        values.push(value);
        if (i % 3 === 0) categories[name] = { name, "GL Code": "existing-" + i };
      }
      data.push(values);
    }
    const taxes = {
      standard: { name: "Standard", value: "20%" },
      reduced: { name: "Reduced", value: "5%", isDisabled: variant % 2 === 0 },
      deleted: {
        name: "Old rate",
        value: "10%",
        pendingAction: CONST.RED_BRICK_ROAD_PENDING_ACTION.DELETE,
      },
      zero: { name: "Zero", value: "0%" },
    };
    const rules = [];
    for (let i = 0; i < 16; i++) {
      rules.push({
        applyWhen: [
          {
            condition: CONST.POLICY.RULE_CONDITIONS.MATCHES,
            field: CONST.POLICY.FIELDS.CATEGORY,
            value: "Category " + variant + "-" + i,
          },
        ],
        tax: { field_id_TAX: { externalID: ["standard", "reduced", "deleted", "zero"][i % 4] } },
      });
    }
    rules.push(
      { applyWhen: [], tax: {} },
      { applyWhen: [{ field: "merchant", condition: "matches", value: "Other" }] }
    );
    return {
      spreadsheet: { columns, data, containsHeader: variant % 2 === 0 },
      categories,
      rules,
      policy: {
        tax: { trackingEnabled: variant !== 7 },
        taxRates: { taxes, defaultExternalID: "standard" },
      },
    };
  });
}
function rnExecute(fixture) {
  const categories = buildCategoriesFromSpreadsheet(fixture.spreadsheet, fixture.categories);
  const taxDefaults = categories.map(function (category) {
    const key = getCategoryTaxRuleKey(category.name);
    const taxID = getCategoryTaxRuleTaxID(fixture.rules, category.name);
    const draft = getCategoryTaxRuleDraftFromGeneratedValues(
      { categoriesToMatch: [category.name], tax: taxID },
      fixture.policy
    );
    return {
      key,
      category: getCategoryNameFromTaxRuleKey(key),
      isKey: isCategoryTaxRuleKey(key),
      exists: categoryHasTaxRule(fixture.rules, category.name),
      taxID,
      label: getTaxRateDisplayName(fixture.policy, taxID),
      draft,
      isDraft: isCategoryRuleDraft(draft),
      pending: getRuleDeletionPendingAction(
        fixture.policy,
        fixture.categories,
        category.name,
        taxID
      ),
    };
  });
  const selectable = Object.entries(fixture.policy.taxRates.taxes).map(function (entry) {
    return [entry[0], isSelectableTaxRate(fixture.policy, entry[0], entry[1], true)];
  });
  return {
    categories,
    taxDefaults,
    selectable,
    hasRates: hasUsableTaxRates(fixture.policy),
    canAdd: hasSelectableCategoryTaxRate(fixture.policy),
    savedLabel: getTaxRateDisplayName(void 0, "removed", { name: "Saved", value: "7%" }),
  };
}
function rnObserve(result) {
  return result.categories.reduce(
    function (sum, row) {
      return (
        sum + row.name.length + (row.enabled ? 1 : 0) + (row.maxExpenseAmount === void 0 ? 0 : 1)
      );
    },
    result.taxDefaults.reduce(function (n, row) {
      return n + row.label.length + (row.exists ? 1 : 0);
    }, 0)
  );
}
function rnFingerprint(result) {
  rnAssert(result.categories.length === 512, "CSV row count changed");
  rnAssert(
    result.taxDefaults.every(function (row) {
      return row.isKey && row.isDraft;
    }),
    "Invalid imported category rule"
  );
  rnAssert(result.savedLabel === "Saved (7%)", "Saved tax label fallback changed");
  return rnHash(JSON.stringify(result));
}
rnBenchmark([
  { "fingerprint": 1137283171, "observation": 7697 },
  { "fingerprint": 3715263910, "observation": 7696 },
  { "fingerprint": 3778642581, "observation": 7696 },
  { "fingerprint": 3101318093, "observation": 7696 },
  { "fingerprint": 2284374586, "observation": 7697 },
  { "fingerprint": 2403356031, "observation": 7697 },
  { "fingerprint": 800285128, "observation": 7697 },
  { "fingerprint": 195446181, "observation": 7697 },
]);
