# React Native 业务 JavaScript benchmarks

从两个应用的固定提交中提取的 **12 个独立 JS**。每个文件包含业务函数、必要依赖、确定性输入、结果校验和计时；运行时不需要 npm、React Native、后端或外部资源。

按完整、正常排版的 JS 文件计数，规模目标为 **500–1,500 行**，生成器和验证器都强制 **500 行下限、2,000 行硬上限**。当前为 **501–714 行，平均 558 行**，12 个均在目标内，仍靠近目标下沿，尚未达到每个约 1k。较小的入口通过增加相关上游业务流程与实际依赖扩展，新增逻辑均参与执行；没有用空行、注释或重复算法填充。许可证文件单独存放，不计入 JS 行数。

| 文件 | 业务场景 | 完整行数 | 其中业务/依赖 | 循环数 |
| --- | --- | ---: | ---: | ---: |
| [expensify-report-sort.js](expensify-report-sort.js) | 消息排序、线程合并、审核与审批状态 | 602 | 371 | 8 |
| [expensify-formula.js](expensify-formula.js) | 公式解析、循环引用、用户字段与日期 token | 556 | 351 | 24 |
| [expensify-csv-categories.js](expensify-csv-categories.js) | CSV 分类导入与税率规则 | 501 | 273 | 8 |
| [expensify-spreadsheet.js](expensify-spreadsheet.js) | 表格列映射与金额清洗校验 | 544 | 371 | 120 |
| [expensify-attendees.js](expensify-attendees.js) | 参会人、资料表单与违规检查 | 503 | 280 | 24 |
| [mattermost-user-activity.js](mattermost-user-activity.js) | 活动消息合并、过滤与结构校验 | 516 | 353 | 80 |
| [mattermost-markdown-ast.js](mattermost-markdown-ast.js) | Markdown AST 处理 | 714 | 553 | 100 |
| [mattermost-channel-attributes.js](mattermost-channel-attributes.js) | 频道属性与 banner | 541 | 366 | 120 |
| [mattermost-dialog.js](mattermost-dialog.js) | 对话框与表单转换 | 514 | 328 | 120 |
| [mattermost-user-profile.js](mattermost-user-profile.js) | 自定义属性、用户搜索与时区 | 544 | 342 | 8 |
| [mattermost-attachments.js](mattermost-attachments.js) | 附件校验、链接处理与文件分类 | 657 | 463 | 4 |
| [mattermost-playbooks.js](mattermost-playbooks.js) | 任务进度、自定义字段与状态消息 | 502 | 269 | 60 |

## 来源与转换

- Expensify：[Expensify/App](https://github.com/Expensify/App/tree/0eff10433514a9be0faa2a568d5779dc06e05d44)，提交 `0eff10433514a9be0faa2a568d5779dc06e05d44`。
- Mattermost：[mattermost-mobile](https://github.com/mattermost/mattermost-mobile/tree/8a9427f25ad9f16ed333b1865eff9c4b057cb093)，提交 `8a9427f25ad9f16ed333b1865eff9c4b057cb093`。
- Markdown AST 的 Node/Walker 来自应用使用的 `@mattermost/commonmark@0.31.2-0`，只包含其 `lib/node.js`，不包含完整 Markdown parser。

提取器使用 `git show COMMIT:PATH` 读取原始文件，Babel AST 定位函数/常量后截取原代码。esbuild 去除 TypeScript 类型和模块出口，以 `target: es2020`、`minify: false` 输出普通 JS，再用本仓库的校验型 formatter 排版。保留业务算法和实际使用的常量；没有把核心逻辑替换为 mock，也没有运行 React Compiler 或 JSX 转换。

`CONST` 的子集从原 AST 定位、求值后内联；Concierge 账号 ID 使用上游 `src/CONST/runtimeDefaults.ts` 的平台无关默认值。Mattermost 的自动补全分隔符从 General 常量提取，附件使用原 Files 分类表。活动类型数组会与上游逐项校验。Markdown Node 仅移除 ESM 导出，其真实链表、父子节点、getter/setter 和 walker 实现一并保留。

用户属性与 Playbook 模块的原生日志依赖通过 [logging.inc](../../react-native-import/harness/logging.inc) 适配：收集警告/错误消息并纳入结果校验，不加载设备日志组件。Playbook 输入包含未知字段类型，实际执行并校验该警告路径。

| 入口 | 原模块与所选逻辑 | 固定输入 |
| --- | --- | --- |
| `expensify-report-sort` | ReportActionsUtils.ts / 排序、线程合并、相邻消息、代理人、审核与 DEW 审批；消息读取和类型判断依赖 | 10,000 条消息；升降序、重复时间、CREATED 优先、缺失字段、SendMoney/普通线程、旧/新消息格式 |
| `expensify-formula` | Formula.ts / 解析、循环引用、字符串修饰、个人字段、报表类型；FormulaDatetime.ts 的无外部依赖日期工具；getBase62ReportID | 嵌套/转义公式、24 层依赖、有环/无环图、员工字段回退、重叠日期 token、报表标签 |
| `expensify-csv-categories` | ImportCategoriesUtils.ts 全部运行时声明；CurrencyUtils.ts 金额换算；CategoryTaxRulesUtils.ts 除 UI 表格外的规则工具 | 512 行分类；表头、已有 GL code、收据要求、无效金额；税率选择、禁用/删除/默认税率、草稿与旧标签回退 |
| `expensify-spreadsheet` | importSpreadsheetUtils.ts / 列识别、公司卡映射、重复检查、Excel 列名、金额清洗；MoneyRequestUtils.ts 金额校验；escapeRegExp | 80 列；重复表头、保存布局回退、无效索引；货币符号、代码、分组空格、负数和精度 |
| `expensify-attendees` | AttendeeUtils.ts 全部运行时声明；sortAlphabetically.ts；PersonalDetailsUtils.ts 的查询、名称、地址和表单工具 | 512 位参会人；数组/对象、空姓名、资料缺失/补全、分类/发票规则、当前地址选择、草稿覆盖 |
| `mattermost-user-activity` | post_list/index.ts 的活动分组/合并、加入退出过滤、ID 解析和结构校验及其依赖 | 四组 4,096 条消息；删除标记、分隔符、100 条分组限制、去重、用户相关过滤、非法结构 |
| `mattermost-markdown-ast` | markdown/transform.ts 的选定 AST 函数；真实 CommonMark Node/Walker | 构造 24 段文本和 16 个列表项；合并文本、复选框、编号、图片链接、高亮 |
| `mattermost-channel-attributes` | channel_attributes.ts 全部运行时声明及三个常量 | 48 个字段；选择/多选/文本/等级、缺失选项、chips、变更规则、模板 |
| `mattermost-dialog` | dialog_utils.ts、dialog_conversion.ts 全部运行时声明 | 64 个字段；嵌套折叠区、多选、数值、日期、文件 ID 去重、提交转换 |
| `mattermost-user-profile` | user/index.ts 的属性/角色、名称、用户索引、搜索与时区工具；safeParseJSON | 128 个字段和用户；选项 ID/名称、排序、JSON/逗号格式、已删除字段、服务端格式往返、用户名/邮箱搜索 |
| `mattermost-attachments` | message_attachment.ts 全部运行时声明；url/index.ts 纯链接工具；file/index.ts 扩展名、大小和类型工具；Files 常量 | 256 个嵌套附件；非法字段、动作、选项；危险/编码 URL、Markdown 链接提取、图片/视频识别与文件分类 |
| `mattermost-playbooks` | task_filters.ts、progress.ts、items_order.ts、property_fields.ts、types.ts；run.ts 的确定性状态/时间工具；JSON 与多选依赖 | 8 × 128 个任务；双命名格式、隐藏/完成/跳过、指派过滤；32 个自定义字段、无效 JSON、未知类型、调度时间和状态消息 |

[manifest.json](manifest.json) 记录原文件哈希、函数原始行号、输出哈希/行数、循环数、适配器、校验和及工具版本。`business_and_dependency_lines` 是转译排版后的上游业务、依赖和内联常量行数；`harness_and_header_lines` 是输入/驱动、校验、计时、日志适配与头部行数，两者之和为完整行数。完整许可证和来源声明在 [licenses/](licenses/) 下；Mattermost 原 NOTICE 覆盖范围大于本子集。

## 范围与输入

输入和计时驱动是本项目为实验新增的合成数据，使用固定 seed 和固定时间戳，不来自生产账号。业务函数从上游提取；分类、消息、用户等输入用普通对象承载所需字段。这里不测 WatermelonDB getter、Onyx 存储、服务端请求、RN renderer 或原生布局。参会人排序传入固定的字符串比较回调，这是原函数支持的参数。

公式场景测解析、循环依赖、字符串修饰、用户字段和日期 token 工具，不包括完整报表/币种公式求值，也未包含 date-fns 本地化名称。表格场景包含原金额清洗和精度校验，不包括文件读取或 CSV tokenizer。Markdown 场景直接用真实 Node 构建 AST 后执行原应用函数，不测文本到 Markdown AST 的解析。上游 `pullOutImages` 在这个提交中只为链接内图片记录 `linkDestination`；没有按照其旧注释假设它仍会把图片移到根节点。

之前超限的 `expensify-search.js`（完整 Peggy parser）和 `mattermost-markdown.js`（完整 parser 与传递依赖）已移出当前 suite，以公式解析、其他业务流程和 Markdown AST 子集取代。

## 运行

在仓库根目录直接执行任意文件：

```sh
node benchmarks/speculative/suites/react-native/expensify-formula.js

CC=clang /path/to/shermes -O -fstatic-builtins \
  benchmarks/speculative/suites/react-native/expensify-formula.js \
  -o /tmp/expensify-formula
/tmp/expensify-formula
```

现有 runner 可发现全部 12 个：

```sh
python3 benchmarks/speculative/bench.py \
  --only react-native \
  --variant hbc hbc /path/to/hermes \
  --variant sh sh /path/to/shermes \
  --schedule anchor-pairs --anchor hbc --cycles 5 \
  --json /tmp/react-native-hbc-sh.json
```

用 `--only react-native/mattermost-channel-attributes` 等路径选择单个入口。annotation A/B 模式使用 `annotations/VERSION/react-native/` 下的镜像标注文件。Jelly 和 annotate-file 的生成与三方性能测试流程见 [实验说明](../../react-native-import/EXPERIMENT.zh-CN.md)；标注目录分别为 [jelly](../../annotations/jelly/react-native/) 和 [coverage-guided](../../annotations/coverage-guided/react-native/)。标注坐标对应最终 `.js`；manifest 的上游 TS 行号仅用于溯源。

每个入口输出 `Checksum: <整数>` 和一行 `Time: <毫秒>`。计时覆盖循环中的业务操作和轻量结果观察；AST 场景也包括 AST 构建及结果遍历。计时排除库初始化、fixture 生成、前后完整指纹校验及输出。输出指纹为固定的 32 位哈希，另有语义断言和计时结果累加校验；它们是回归检查，不是完整应用正确性的证明。

## 再生成

工具和 npm 依赖放在 suite 外的 [react-native-import/](../../react-native-import/)，不会被当作 benchmark。运行已生成文件不需要这些依赖。Node 22+ 下：

```sh
npm ci --prefix benchmarks/speculative
npm ci --prefix benchmarks/speculative/react-native-import
node benchmarks/speculative/react-native-import/extract.cjs \
  --expensify /path/to/Expensify-App \
  --mattermost /path/to/mattermost-mobile
```

两个 checkout 须包含固定提交；当前工作区内容不影响 `git show` 读取。加 `--check` 只比较文件是否与重新生成结果一致。不足 500 行或超过 2,000 行时生成失败。修改业务选择或 fixture 后，审阅行为差异，再显式使用 `--update-references` 更新冻结指纹；普通生成和只调整循环数都不会重算参考值。

## 验证

12 个入口分别检查 Node、匹配的 Hermes 字节码和 SH `-O -fstatic-builtins` 输出，验证计时行和完整校验和；另检查 `annotation-dryrun` 接受输入、源文件哈希/行数，以及故意损坏结果指纹会在输出时间前失败。可重复执行：

```sh
python3 benchmarks/speculative/react-native-import/validate.py \
  --hermes /path/to/hermes --shermes /path/to/shermes \
  --dryrun /path/to/annotation-dryrun --check-corruption \
  --json /tmp/react-native-validation.json
```

不传引擎路径时仅做 Node 和文件约束检查。验证脚本在临时目录构建，并保存所请求的 JSON 报告。运行时间属于执行检查，不作为正式性能比较。
