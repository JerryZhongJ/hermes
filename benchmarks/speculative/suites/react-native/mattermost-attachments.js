// Extracted from https://github.com/mattermost/mattermost-mobile at 8a9427f25ad9f16ed333b1865eff9c4b057cb093.
// Workload: mattermost-attachments. See README.md, manifest.json and licenses/.
// Type/module syntax and formatting adapted; application algorithms retained.
// Copyright (c) 2015-present Mattermost, Inc. Apache-2.0.
function isArrayOf(v, check) {
  if (!Array.isArray(v)) {
    return false;
  }
  return v.every(check);
}
function getStatusColors(theme) {
  return {
    good: "#00c100",
    warning: "#dede01",
    danger: theme.errorTextColor,
    default: theme.centerChannelColor,
    primary: theme.buttonBg,
    success: theme.onlineIndicator,
  };
}
function isMessageAttachmentArray(v) {
  return isArrayOf(v, isMessageAttachment);
}
function isPostActionOption(v) {
  if (typeof v !== "object" || !v) {
    return false;
  }
  if ("text" in v && typeof v.text !== "string") {
    return false;
  }
  if ("value" in v && typeof v.value !== "string") {
    return false;
  }
  return true;
}
function isPostAction(v) {
  if (typeof v !== "object" || !v) {
    return false;
  }
  if ("id" in v && typeof v.id !== "string") {
    return false;
  }
  if ("name" in v && typeof v.name !== "string") {
    return false;
  }
  if ("type" in v && typeof v.type !== "string") {
    return false;
  }
  if ("disabled" in v && typeof v.disabled !== "boolean") {
    return false;
  }
  if ("style" in v && typeof v.style !== "string") {
    return false;
  }
  if ("data_source" in v && typeof v.data_source !== "string") {
    return false;
  }
  if ("options" in v && !isArrayOf(v.options, isPostActionOption)) {
    return false;
  }
  if ("default_option" in v && typeof v.default_option !== "string") {
    return false;
  }
  if ("cookie" in v && typeof v.cookie !== "string") {
    return false;
  }
  return true;
}
function isMessageAttachmentField(v) {
  if (typeof v !== "object") {
    return false;
  }
  if (!v) {
    return false;
  }
  if ("title" in v && typeof v.title !== "string") {
    return false;
  }
  if (
    "value" in v &&
    typeof v.value === "object" &&
    v.value &&
    "toString" in v.value &&
    typeof v.value.toString !== "function"
  ) {
    return false;
  }
  if ("short" in v && typeof v.short !== "boolean") {
    return false;
  }
  return true;
}
function isMessageAttachment(v) {
  if (typeof v !== "object" || !v) {
    return false;
  }
  if ("fallback" in v && typeof v.fallback !== "string") {
    return false;
  }
  if ("color" in v && typeof v.color !== "string") {
    return false;
  }
  if ("pretext" in v && typeof v.pretext !== "string") {
    return false;
  }
  if ("author_name" in v && typeof v.author_name !== "string") {
    return false;
  }
  if ("author_link" in v && typeof v.author_link !== "string") {
    return false;
  }
  if ("author_icon" in v && typeof v.author_icon !== "string") {
    return false;
  }
  if ("title" in v && typeof v.title !== "string") {
    return false;
  }
  if ("title_link" in v && typeof v.title_link !== "string") {
    return false;
  }
  if ("text" in v && typeof v.text !== "string") {
    return false;
  }
  if ("image_url" in v && typeof v.image_url !== "string") {
    return false;
  }
  if ("thumb_url" in v && typeof v.thumb_url !== "string") {
    return false;
  }
  if ("footer" in v && typeof v.footer !== "string") {
    return false;
  }
  if ("footer_icon" in v && typeof v.footer_icon !== "string") {
    return false;
  }
  if ("fields" in v && v.fields !== null && !isArrayOf(v.fields, isMessageAttachmentField)) {
    return false;
  }
  if ("actions" in v && !isArrayOf(v.actions, isPostAction)) {
    return false;
  }
  return true;
}
function filterOptions(options) {
  return options?.reduce((acc, option) => {
    let optionText = option.text;
    let optionValue = option.value;
    if (optionText && !optionValue) {
      optionValue = optionText;
    } else if (optionValue && !optionText) {
      optionText = optionValue;
    }
    if (optionText && optionValue) {
      acc.push({ text: optionText, value: optionValue });
    }
    return acc;
  }, []);
}
const testExports = {
  isMessageAttachment,
  isMessageAttachmentField,
  isPostAction,
  isPostActionOption,
};
const Files = {
  AUDIO_TYPES: ["mp3", "wav", "wma", "m4a", "flac", "aac", "ogg"],
  CODE_TYPES: [
    "as",
    "applescript",
    "osascript",
    "scpt",
    "bash",
    "sh",
    "zsh",
    "clj",
    "boot",
    "cl2",
    "cljc",
    "cljs",
    "cljs.hl",
    "cljscm",
    "cljx",
    "hic",
    "coffee",
    "_coffee",
    "cake",
    "cjsx",
    "cson",
    "iced",
    "cpp",
    "c",
    "cc",
    "h",
    "c++",
    "h++",
    "hpp",
    "cs",
    "csharp",
    "css",
    "d",
    "di",
    "dart",
    "delphi",
    "dpr",
    "dfm",
    "pas",
    "pascal",
    "freepascal",
    "lazarus",
    "lpr",
    "lfm",
    "diff",
    "django",
    "jinja",
    "dockerfile",
    "docker",
    "erl",
    "f90",
    "f95",
    "fsharp",
    "fs",
    "gcode",
    "nc",
    "go",
    "groovy",
    "handlebars",
    "hbs",
    "html.hbs",
    "html.handlebars",
    "hs",
    "hx",
    "java",
    "jsp",
    "js",
    "jsx",
    "json",
    "jl",
    "kt",
    "ktm",
    "kts",
    "less",
    "lisp",
    "lua",
    "mk",
    "mak",
    "md",
    "mkdown",
    "mkd",
    "matlab",
    "m",
    "mm",
    "objc",
    "obj-c",
    "ml",
    "perl",
    "pl",
    "php",
    "php3",
    "php4",
    "php5",
    "php6",
    "ps",
    "ps1",
    "pp",
    "py",
    "gyp",
    "r",
    "ruby",
    "rb",
    "gemspec",
    "podspec",
    "thor",
    "irb",
    "rs",
    "scala",
    "scm",
    "sld",
    "scss",
    "st",
    "sql",
    "swift",
    "ts",
    "tex",
    "vbnet",
    "vb",
    "bas",
    "vbs",
    "v",
    "veo",
    "xml",
    "html",
    "xhtml",
    "rss",
    "atom",
    "xsl",
    "plist",
    "yaml",
  ],
  IMAGE_TYPES: ["jpg", "gif", "bmp", "png", "jpeg", "tiff", "tif", "svg", "psd", "xcf"],
  PATCH_TYPES: ["patch"],
  PDF_TYPES: ["pdf"],
  PRESENTATION_TYPES: ["ppt", "pptx", "odp"],
  SPREADSHEET_TYPES: ["xls", "xlsx", "csv", "ods"],
  TEXT_TYPES: ["txt", "rtf"],
  VIDEO_TYPES: ["mp4", "avi", "webm", "mkv", "wmv", "mpg", "mov", "flv", "ogm", "mpeg"],
  WORD_TYPES: ["doc", "docx", "odt"],
  ZIP_TYPES: ["zip"],
};
function extractExtension(filename) {
  const ext = filename.split(".").pop() || "";
  return ext.startsWith(".") ? ext.slice(1).toLowerCase() : ext.toLowerCase();
}
function getFormattedFileSize(bytes) {
  const fileSizes = [
    ["TB", 1024 * 1024 * 1024 * 1024],
    ["GB", 1024 * 1024 * 1024],
    ["MB", 1024 * 1024],
    ["KB", 1024],
  ];
  const size = fileSizes.find((unitAndMinBytes) => {
    const minBytes = unitAndMinBytes[1];
    return bytes > minBytes;
  });
  if (size) {
    return `${Math.floor(bytes / size[1])} ${size[0]}`;
  }
  return `${bytes} B`;
}
function getFileType(file) {
  if (!file || !file.extension) {
    return "other";
  }
  const fileExt = file.extension.toLowerCase();
  const fileTypes = [
    "image",
    "code",
    "pdf",
    "video",
    "audio",
    "spreadsheet",
    "text",
    "word",
    "presentation",
    "patch",
    "zip",
  ];
  return (
    fileTypes.find((fileType) => {
      const constForFileTypeExtList = `${fileType}_types`.toUpperCase();
      const fileTypeExts = Files[constForFileTypeExtList];
      return fileTypeExts.indexOf(fileExt) > -1;
    }) || "other"
  );
}
const ytRegex = new RegExp(
  "(?:http|https):\\/\\/(?:www\\.|m\\.)?(?:(?:youtube\\.com\\/(?:(?:v\\/)|(?:(?:watch|embed\\/watch)(?:\\/|.*v=))|(?:embed\\/)|(?:user\\/[^/]+\\/u\\/[\
0-9]\\/)))|(?:youtu\\.be\\/))([^#&?]*)",
  ""
);
function isValidUrl(url = "") {
  const regex = /^https?:\/\//i;
  return regex.test(url);
}
function isUrlSafe(url) {
  let unescaped;
  try {
    unescaped = decodeURIComponent(url);
  } catch {
    unescaped = unescape(url);
  }
  unescaped = unescaped.replace(/[^\w:]/g, "").toLowerCase();
  return (
    !unescaped.startsWith("javascript:") &&
    !unescaped.startsWith("vbscript:") &&
    !unescaped.startsWith("data:")
  );
}
function stripTrailingSlashes(url = "") {
  return url.replace(/ /g, "").replace(/^\/+/, "").replace(/\/+$/, "");
}
function removeProtocol(url = "") {
  return url.replace(/(^\w+:|^)\/\//, "");
}
function extractFirstLink(text) {
  const pattern =
    /(^|[\s\n]|<br\/?>)((?:https?|ftp):\/\/[-A-Z0-9+\u0026\u2019@#/%?=()~_|!:,.;]*[-A-Z0-9+\u0026@#/%=~()_|])/i;
  let inText = text;
  inText = inText.replace(/`[^`]*`/g, "");
  inText = inText.replace(/!\[[^\]]*]\([^)]*\)/g, "");
  const match = pattern.exec(inText);
  if (match) {
    return match[0].trim();
  }
  return "";
}
function extractStartLink(text) {
  const pattern =
    /^((?:https?|ftp):\/\/[-A-Z0-9+\u0026\u2019@#/%?=()~_|!:,.;]*[-A-Z0-9+\u0026@#/%=~()_|])/i;
  let inText = text;
  inText = inText.replace(/`[^`]*`/g, "");
  inText = inText.replace(/!\[[^\]]*]\([^)]*\)/g, "");
  const match = pattern.exec(inText);
  if (match) {
    return match[0].trim();
  }
  return "";
}
function isYoutubeLink(link) {
  return link.trim().match(ytRegex);
}
function isImageLink(link) {
  let linkWithoutQuery = link;
  if (link.indexOf("?") !== -1) {
    linkWithoutQuery = linkWithoutQuery.split("?")[0];
  }
  for (let i = 0; i < Files.IMAGE_TYPES.length; i++) {
    const imageType = Files.IMAGE_TYPES[i];
    if (linkWithoutQuery.endsWith("." + imageType) || linkWithoutQuery.endsWith("=" + imageType)) {
      return true;
    }
  }
  return false;
}
function normalizeProtocol(url) {
  const index = url.indexOf(":");
  if (index === -1) {
    return url;
  }
  const protocol = url.substring(0, index);
  return protocol.toLowerCase() + url.substring(index);
}
function getShortenedURL(url = "", getLength = 27) {
  if (url.length > 35) {
    const subLength = getLength - 14;
    return url.substring(0, 10) + "..." + url.substring(url.length - subLength, url.length) + "/";
  }
  return url + "/";
}
function getScheme(url) {
  const match = /([a-z0-9+.-]+):/i.exec(url);
  return match && match[1];
}
function getYouTubeVideoId(link) {
  if (!link) {
    return "";
  }
  let match = /youtube\.com\/watch\?\S*\bv=([a-zA-Z0-9_-]{6,11})/g.exec(link);
  if (match) {
    return match[1];
  }
  match = /youtube\.com\/embed\/([a-zA-Z0-9_-]{6,11})/g.exec(link);
  if (match) {
    return match[1];
  }
  match = /youtu.be\/([a-zA-Z0-9_-]{6,11})/g.exec(link);
  if (match) {
    return match[1];
  }
  return "";
}
function safeDecodeURIComponent(v) {
  try {
    return decodeURIComponent(v);
  } catch {
    return v;
  }
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
const RN_ITERATIONS = 4;
function rnCreateFixtures() {
  return Array.from({ length: 8 }, function (_, variant) {
    const attachments = [];
    for (let i = 0; i < 256; i++) {
      const attachment = {
        fallback: "Message " + i,
        color: "#123456",
        pretext: "Fixture",
        author_name: "Author",
        title: "Title " + i,
        title_link: [
          "https://example.com/view/" + i,
          "javascript:alert(1)",
          "https://youtu.be/abcdef12345",
          "HTTP://example.com/image.png?version=2",
          "vbscript:test",
          "data:text/html,test",
          "%6Aavascript%3Aalert(1)",
          "%ZZ",
        ][i % 8],
        text:
          "Body `https://ignored.example/code` ![image](https://ignored.example/image.png) https://example.com/post/" +
          i,
        footer: "Footer",
        files: [
          { name: "preview-" + i + ".PNG", size: 1024 * i },
          {
            name: "report." + ["pdf", "csv", "js", "zip", "unknown", "mp4", "mp3", "docx"][i % 8],
            size: i * 1024 * 1024,
          },
        ],
        fields: [
          { title: "Status", value: "Ready", short: true },
          { title: "Count", value: i },
        ],
        actions: [
          {
            id: "select",
            name: "Choose",
            type: "select",
            disabled: false,
            options: [{ text: "Alpha", value: "a" }, { text: "Only text" }, { value: "b" }, {}],
          },
        ],
      };
      if (variant % 2 && i % 9 === 0) attachment.actions[0].options[0].text = 123;
      if (variant % 3 && i % 11 === 0) attachment.fields[0].short = "invalid";
      if (i % 17 === 0) attachment.fields = null;
      attachments.push(attachment);
    }
    return attachments;
  });
}
function rnExecute(attachments) {
  return {
    colors: getStatusColors({
      errorTextColor: "#ff0000",
      centerChannelColor: "#222222",
      buttonBg: "#336699",
      onlineIndicator: "#00aa00",
    }),
    validArray: isMessageAttachmentArray(attachments),
    rows: attachments.map(function (attachment) {
      const link = normalizeProtocol(attachment.title_link);
      const extracted = extractFirstLink(attachment.text);
      return {
        valid: isMessageAttachment(attachment),
        action: isPostAction(attachment.actions[0]),
        field: isMessageAttachmentField(attachment.fields ? attachment.fields[0] : {}),
        options: filterOptions(attachment.actions[0].options),
        link: {
          safe: isUrlSafe(link),
          valid: isValidUrl(link),
          image: isImageLink(link),
          youtube: Boolean(isYoutubeLink(link)),
          video: getYouTubeVideoId(link),
          scheme: getScheme(link),
          short: getShortenedURL(link),
          withoutProtocol: removeProtocol(link),
          decoded: safeDecodeURIComponent(link),
          trimmed: stripTrailingSlashes(link),
        },
        extracted,
        startLink: extractStartLink(extracted),
        files: attachment.files.map(function (file) {
          const extension = extractExtension(file.name);
          return {
            extension,
            type: getFileType({ extension }),
            size: getFormattedFileSize(file.size),
          };
        }),
      };
    }),
  };
}
function rnObserve(result) {
  return result.rows.reduce(function (n, row) {
    return (
      n + (row.valid ? 1 : 0) + row.options.length + row.extracted.length + (row.link.safe ? 1 : 0)
    );
  }, 0);
}
function rnFingerprint(result) {
  rnAssert(!isMessageAttachment(null) && !isPostActionOption(3), "Invalid attachments accepted");
  rnAssert(!result.rows[1].link.safe && !result.rows[6].link.safe, "Unsafe URL accepted");
  rnAssert(result.rows[2].link.video === "abcdef12345", "Video URL extraction failed");
  rnAssert(
    result.rows[0].extracted === "https://example.com/post/0",
    "Code/image URLs leaked into preview"
  );
  rnAssert(
    result.rows.every(function (row) {
      return row.files[0].type === "image";
    }),
    "Image classification failed"
  );
  return rnHash(JSON.stringify(result));
}
rnBenchmark([
  { "fingerprint": 1475468707, "observation": 8210 },
  { "fingerprint": 1277482422, "observation": 8161 },
  { "fingerprint": 3666240646, "observation": 8188 },
  { "fingerprint": 823277196, "observation": 8181 },
  { "fingerprint": 3666240646, "observation": 8188 },
  { "fingerprint": 1277482422, "observation": 8161 },
  { "fingerprint": 1475468707, "observation": 8210 },
  { "fingerprint": 1277482422, "observation": 8161 },
]);
