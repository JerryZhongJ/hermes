// Extracted from https://github.com/mattermost/mattermost-mobile at 8a9427f25ad9f16ed333b1865eff9c4b057cb093.
// Workload: mattermost-markdown-ast. See README.md, manifest.json and licenses/.
// Type/module syntax and formatting adapted; application algorithms retained.
// Copyright (c) 2015-present Mattermost, Inc. Apache-2.0.
"use strict";
function isContainer(node) {
  switch (node._type) {
    case "document":
    case "block_quote":
    case "list":
    case "item":
    case "table":
    case "table_row":
    case "table_cell":
    case "paragraph":
    case "heading":
    case "emph":
    case "strong":
    case "del":
    case "link":
    case "image":
    case "latex_inline":
    case "mention_highlight":
    case "highlight_without_notification":
    case "search_highlight":
    case "custom_inline":
    case "custom_block":
      return true;
    default:
      return false;
  }
}
var resumeAt = function (node, entering) {
  this.current = node;
  this.entering = entering === true;
};
var next = function () {
  var cur = this.current;
  var entering = this.entering;
  if (cur === null) {
    return null;
  }
  var container = isContainer(cur);
  if (entering && container) {
    if (cur._firstChild) {
      this.current = cur._firstChild;
      this.entering = true;
    } else {
      this.entering = false;
    }
  } else if (cur === this.root) {
    this.current = null;
  } else if (cur._next === null) {
    this.current = cur._parent;
    this.entering = false;
  } else {
    this.current = cur._next;
    this.entering = true;
  }
  return { entering, node: cur };
};
var NodeWalker = function (root) {
  return {
    current: root,
    root,
    entering: true,
    next,
    resumeAt,
  };
};
var Node = function (nodeType, sourcepos) {
  this._type = nodeType;
  this._parent = null;
  this._firstChild = null;
  this._lastChild = null;
  this._prev = null;
  this._next = null;
  this._sourcepos = sourcepos;
  this._open = true;
  this._string_content = null;
  this._literal = null;
  this._listData = {};
  this._info = null;
  this._destination = null;
  this._size = null;
  this._title = null;
  this._isFenced = false;
  this._fenceChar = null;
  this._fenceLength = 0;
  this._fenceOffset = null;
  this._level = null;
  this._mentionName = null;
  this._emojiName = null;
  this._hashtag = null;
  this._latexCode = null;
  this._isChecked = false;
  this._alignColumns = [];
  this._isHeading = false;
  this._align = "";
  this._onEnter = null;
  this._onExit = null;
};
var proto = Node.prototype;
Object.defineProperty(proto, "isContainer", {
  get: function () {
    return isContainer(this);
  },
});
Object.defineProperty(proto, "type", {
  get: function () {
    return this._type;
  },
});
Object.defineProperty(proto, "firstChild", {
  get: function () {
    return this._firstChild;
  },
});
Object.defineProperty(proto, "lastChild", {
  get: function () {
    return this._lastChild;
  },
});
Object.defineProperty(proto, "next", {
  get: function () {
    return this._next;
  },
});
Object.defineProperty(proto, "prev", {
  get: function () {
    return this._prev;
  },
});
Object.defineProperty(proto, "parent", {
  get: function () {
    return this._parent;
  },
});
Object.defineProperty(proto, "sourcepos", {
  get: function () {
    return this._sourcepos;
  },
});
Object.defineProperty(proto, "literal", {
  get: function () {
    return this._literal;
  },
  set: function (s) {
    this._literal = s;
  },
});
Object.defineProperty(proto, "destination", {
  get: function () {
    return this._destination;
  },
  set: function (s) {
    this._destination = s;
  },
});
Object.defineProperty(proto, "size", {
  get: function () {
    return this._size;
  },
  set: function (s) {
    this._size = s;
  },
});
Object.defineProperty(proto, "title", {
  get: function () {
    return this._title;
  },
  set: function (s) {
    this._title = s;
  },
});
Object.defineProperty(proto, "info", {
  get: function () {
    return this._info;
  },
  set: function (s) {
    this._info = s;
  },
});
Object.defineProperty(proto, "level", {
  get: function () {
    return this._level;
  },
  set: function (s) {
    this._level = s;
  },
});
Object.defineProperty(proto, "listType", {
  get: function () {
    return this._listData.type;
  },
  set: function (t) {
    this._listData.type = t;
  },
});
Object.defineProperty(proto, "listTight", {
  get: function () {
    return this._listData.tight;
  },
  set: function (t) {
    this._listData.tight = t;
  },
});
Object.defineProperty(proto, "listStart", {
  get: function () {
    return this._listData.start;
  },
  set: function (n) {
    this._listData.start = n;
  },
});
Object.defineProperty(proto, "listDelimiter", {
  get: function () {
    return this._listData.delimiter;
  },
  set: function (delim) {
    this._listData.delimiter = delim;
  },
});
Object.defineProperty(proto, "mentionName", {
  get: function () {
    return this._mentionName;
  },
  set: function (mentionName) {
    this._mentionName = mentionName;
  },
});
Object.defineProperty(proto, "channelName", {
  get: function () {
    return this._channelName;
  },
  set: function (channelName) {
    this._channelName = channelName;
  },
});
Object.defineProperty(proto, "emojiName", {
  get: function () {
    return this._emojiName;
  },
  set: function (emojiName) {
    this._emojiName = emojiName;
  },
});
Object.defineProperty(proto, "hashtag", {
  get: function () {
    return this._hashtag;
  },
  set: function (hashtag) {
    this._hashtag = hashtag;
  },
});
Object.defineProperty(proto, "latexCode", {
  get: function () {
    return this._latexCode;
  },
  set: function (latexCode) {
    this._latexCode = latexCode;
  },
});
Object.defineProperty(proto, "isChecked", {
  get: function () {
    return this._isChecked;
  },
  set: function (isChecked) {
    this._isChecked = isChecked;
  },
});
Object.defineProperty(proto, "alignColumns", {
  get: function () {
    return this._alignColumns;
  },
  set: function (s) {
    this._alignColumns = s;
  },
});
Object.defineProperty(proto, "isHeading", {
  get: function () {
    return this._isHeading;
  },
  set: function (t) {
    this._isHeading = t;
  },
});
Object.defineProperty(proto, "align", {
  get: function () {
    return this._align;
  },
  set: function (s) {
    this._align = s;
  },
});
Object.defineProperty(proto, "onEnter", {
  get: function () {
    return this._onEnter;
  },
  set: function (s) {
    this._onEnter = s;
  },
});
Object.defineProperty(proto, "onExit", {
  get: function () {
    return this._onExit;
  },
  set: function (s) {
    this._onExit = s;
  },
});
Node.prototype.appendChild = function (child) {
  child.unlink();
  child._parent = this;
  if (this._lastChild) {
    this._lastChild._next = child;
    child._prev = this._lastChild;
    this._lastChild = child;
  } else {
    this._firstChild = child;
    this._lastChild = child;
  }
};
Node.prototype.prependChild = function (child) {
  child.unlink();
  child._parent = this;
  if (this._firstChild) {
    this._firstChild._prev = child;
    child._next = this._firstChild;
    this._firstChild = child;
  } else {
    this._firstChild = child;
    this._lastChild = child;
  }
};
Node.prototype.unlink = function () {
  if (this._prev) {
    this._prev._next = this._next;
  } else if (this._parent) {
    this._parent._firstChild = this._next;
  }
  if (this._next) {
    this._next._prev = this._prev;
  } else if (this._parent) {
    this._parent._lastChild = this._prev;
  }
  this._parent = null;
  this._next = null;
  this._prev = null;
};
Node.prototype.insertAfter = function (sibling) {
  sibling.unlink();
  sibling._next = this._next;
  if (sibling._next) {
    sibling._next._prev = sibling;
  }
  sibling._prev = this;
  this._next = sibling;
  sibling._parent = this._parent;
  if (!sibling._next) {
    sibling._parent._lastChild = sibling;
  }
};
Node.prototype.insertBefore = function (sibling) {
  sibling.unlink();
  sibling._prev = this._prev;
  if (sibling._prev) {
    sibling._prev._next = sibling;
  }
  sibling._next = this;
  this._prev = sibling;
  sibling._parent = this._parent;
  if (!sibling._prev) {
    sibling._parent._firstChild = sibling;
  }
};
Node.prototype.walker = function () {
  var walker = new NodeWalker(this);
  return walker;
};
function combineTextNodes(ast) {
  const walker = ast.walker();
  let e;
  while ((e = walker.next())) {
    if (!e.entering) {
      continue;
    }
    const node = e.node;
    if (node.type !== "text") {
      continue;
    }
    while (node._next && node._next.type === "text") {
      const next2 = node._next;
      node.literal += next2.literal;
      node._next = next2._next;
      if (node._next) {
        node._next._prev = node;
      }
      if (node._parent._lastChild === next2) {
        node._parent._lastChild = node;
      }
    }
    walker.resumeAt(node, false);
  }
  return ast;
}
function addListItemIndices(ast) {
  const walker = ast.walker();
  let e;
  while ((e = walker.next())) {
    if (e.entering) {
      const node = e.node;
      if (node.type === "list") {
        let i = node.listStart == null ? 1 : node.listStart;
        for (let child = node.firstChild; child; child = child.next) {
          child.index = i;
          i += 1;
        }
      }
    }
  }
  return ast;
}
function pullOutImages(ast) {
  const walker = ast.walker();
  let e;
  while ((e = walker.next())) {
    if (!e.entering) {
      continue;
    }
    const node = e.node;
    if (node.type === "table") {
      walker.resumeAt(node, false);
      continue;
    }
    if (node.type === "image" && node.parent?.type !== "document") {
      pullOutImage(node);
    }
  }
  return ast;
}
function pullOutImage(image) {
  const parent = image.parent;
  if (parent?.type === "link") {
    image.linkDestination = parent.destination;
  }
}
function getFirstMatch(str, patterns) {
  let firstMatchIndex = -1;
  let firstMatchLength = -1;
  for (const pattern of patterns) {
    let matchResult;
    if (pattern.global || pattern.sticky) {
      const regex = new RegExp(pattern.source, pattern.flags);
      matchResult = regex.exec(str);
    } else {
      matchResult = pattern.exec(str);
    }
    if (!matchResult || matchResult[0] === "") {
      continue;
    }
    if (firstMatchIndex === -1 || matchResult.index < firstMatchIndex) {
      firstMatchIndex = matchResult.index;
      firstMatchLength = matchResult[0].length;
    }
  }
  return {
    index: firstMatchIndex,
    length: firstMatchLength,
  };
}
function highlightTextNode(node, start, end, type) {
  const literal = node.literal;
  node.literal = literal.substring(start, end);
  const highlighted = new Node(type);
  wrapNode(highlighted, node);
  if (start !== 0) {
    const before = new Node("text");
    before.literal = literal.substring(0, start);
    highlighted.insertBefore(before);
  }
  if (end !== literal.length) {
    const after = new Node("text");
    after.literal = literal.substring(end);
    highlighted.insertAfter(after);
  }
  return highlighted;
}
function highlightSearchPatterns(ast, searchPatterns) {
  const walker = ast.walker();
  let e;
  while ((e = walker.next())) {
    if (!e.entering) {
      continue;
    }
    const node = e.node;
    if ((node.type === "text" || node.type === "code") && node.literal) {
      for (const patternPattern of searchPatterns) {
        const { index, length } = getFirstMatch(node.literal, [patternPattern.pattern]);
        if (index === -1) {
          continue;
        }
        const matchNode = highlightTextNode(node, index, index + length, "search_highlight");
        walker.resumeAt(matchNode, false);
      }
    }
  }
  return ast;
}
function wrapNode(wrapper, node) {
  wrapper._parent = node._parent;
  if (node._parent._firstChild === node) {
    node._parent._firstChild = wrapper;
  }
  if (node._parent._lastChild === node) {
    node._parent._lastChild = wrapper;
  }
  wrapper._prev = node._prev;
  node._prev = null;
  if (wrapper._prev) {
    wrapper._prev._next = wrapper;
  }
  wrapper._next = node._next;
  node._next = null;
  if (wrapper._next) {
    wrapper._next._prev = wrapper;
  }
  wrapper._firstChild = node;
  wrapper._lastChild = node;
  node._parent = wrapper;
}
function parseTaskLists(ast) {
  const walker = ast.walker();
  let e;
  while ((e = walker.next())) {
    if (!e.entering) {
      continue;
    }
    const node = e.node;
    if (node.type !== "item") {
      continue;
    }
    if (node.firstChild?.type === "paragraph" && node.firstChild?.firstChild?.type === "text") {
      const paragraphNode = node.firstChild;
      const textNode = node.firstChild.firstChild;
      const literal = textNode.literal ?? "";
      const match = /^ {0,3}\[( |x)\]\s/.exec(literal);
      if (match) {
        const checkbox = new Node("checkbox");
        checkbox.isChecked = match[1] === "x";
        paragraphNode.prependChild(checkbox);
        textNode.literal = literal.substring(match[0].length);
      }
    }
  }
  return ast;
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
const RN_ITERATIONS = 100;
function rnCreateFixtures() {
  return Array.from({ length: 8 }, function (_, variant) {
    return {
      variant,
      paragraphs: Array.from({ length: 24 }, function (_2, i) {
        return "Message " + i + " has release notes and status updates. \u6771\u4EAC " + variant;
      }),
    };
  });
}
function rnText(text) {
  const node = new Node("text");
  node.literal = text;
  return node;
}
function rnExecute(fixture) {
  const root = new Node("document");
  for (let i = 0; i < fixture.paragraphs.length; i++) {
    const paragraph = new Node("paragraph");
    const text = fixture.paragraphs[i];
    paragraph.appendChild(rnText(text.slice(0, 12)));
    paragraph.appendChild(rnText(text.slice(12)));
    if (i % 6 === 0) {
      const image = new Node("image");
      image.destination = "https://example.com/image-" + i;
      const link = new Node("link");
      link.destination = "https://example.com/link-" + i;
      link.appendChild(image);
      paragraph.appendChild(link);
      paragraph.appendChild(rnText(" after image"));
    }
    root.appendChild(paragraph);
  }
  const list = new Node("list");
  list.listStart = fixture.variant % 2 ? 3 : 1;
  for (let i = 0; i < 16; i++) {
    const item = new Node("item");
    const paragraph = new Node("paragraph");
    paragraph.appendChild(rnText((i % 2 ? "[ ] " : "[x] ") + "release task " + i));
    item.appendChild(paragraph);
    list.appendChild(item);
  }
  root.appendChild(list);
  combineTextNodes(root);
  addListItemIndices(root);
  parseTaskLists(root);
  pullOutImages(root);
  highlightSearchPatterns(root, [{ pattern: /release/i }]);
  return root;
}
function rnObserve(ast) {
  const walker = ast.walker();
  let event;
  let count = 0;
  while ((event = walker.next()))
    if (event.entering) count += 1 + (event.node.literal || "").length;
  return count;
}
function rnFingerprint(ast) {
  const rows = [];
  const walker = ast.walker();
  let event;
  let checkboxes = 0;
  let images = 0;
  while ((event = walker.next())) {
    if (!event.entering) continue;
    const node = event.node;
    rnAssert(!node.next || node.next.prev === node, "Broken AST sibling link");
    rnAssert(!node.firstChild || node.firstChild.parent === node, "Broken AST parent link");
    if (node.type === "checkbox") checkboxes++;
    if (node.type === "image") {
      images++;
      rnAssert(node.linkDestination === node.parent.destination, "Linked image destination lost");
    }
    rows.push([
      node.type,
      node.literal,
      node.destination,
      node.linkDestination,
      node.index,
      node.isChecked,
    ]);
  }
  rnAssert(checkboxes === 16 && images === 4, "AST transformation count mismatch");
  return rnHash(JSON.stringify(rows));
}
rnBenchmark([
  { "fingerprint": 1325263141, "observation": 1770 },
  { "fingerprint": 1635001403, "observation": 1770 },
  { "fingerprint": 3238631205, "observation": 1770 },
  { "fingerprint": 793898687, "observation": 1770 },
  { "fingerprint": 3926470669, "observation": 1770 },
  { "fingerprint": 2476303555, "observation": 1770 },
  { "fingerprint": 3373239165, "observation": 1770 },
  { "fingerprint": 3481231343, "observation": 1770 },
]);
