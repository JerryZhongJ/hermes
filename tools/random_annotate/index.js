#!/usr/bin/env node
/**
 * Generate random type annotations for a JavaScript file using AST parsing.
 * Usage: node random_annotate.js <js_file> [--count N] [--output annotations.json]
 *
 * Requires: npm install acorn acorn-walk
 */

const fs = require('fs');
const path = require('path');
const acorn = require('acorn');
const walk = require('acorn-walk');

const TYPES = ['number', 'string', 'boolean', 'object', 'null', 'undefined'];

function parseArgs() {
  const args = process.argv.slice(2);
  const options = {
    jsFile: null,
    count: 5,
    output: null,
    seed: null
  };

  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--count' || args[i] === '-n') {
      options.count = parseInt(args[++i]);
    } else if (args[i] === '--output' || args[i] === '-o') {
      options.output = args[++i];
    } else if (args[i] === '--seed' || args[i] === '-s') {
      options.seed = parseInt(args[++i]);
    } else if (!args[i].startsWith('-')) {
      options.jsFile = args[i];
    }
  }

  return options;
}

// Simple seeded random
function seededRandom(seed) {
  let s = seed || Date.now();
  return function() {
    s = (s * 1103515245 + 12345) & 0x7fffffff;
    return s / 0x7fffffff;
  };
}

function findExpressions(content, filename) {
  const expressions = [];

  let ast;
  try {
    ast = acorn.parse(content, {
      ecmaVersion: 'latest',
      sourceType: 'script',
      locations: true,
      allowReturnOutsideFunction: true,
      allowHashBang: true
    });
  } catch (e) {
    // Try as module
    try {
      ast = acorn.parse(content, {
        ecmaVersion: 'latest',
        sourceType: 'module',
        locations: true,
        allowReturnOutsideFunction: true
      });
    } catch (e2) {
      console.error(`Parse error: ${e2.message}`);
      return expressions;
    }
  }

  // Collect annotatable expression nodes
  walk.simple(ast, {
    MemberExpression(node) {
      expressions.push({
        type: 'MemberExpression',
        loc: node.loc,
        text: content.slice(node.start, node.end)
      });
    },
    CallExpression(node) {
      expressions.push({
        type: 'CallExpression',
        loc: node.loc,
        text: content.slice(node.start, node.end)
      });
    },
    BinaryExpression(node) {
      expressions.push({
        type: 'BinaryExpression',
        loc: node.loc,
        text: content.slice(node.start, node.end)
      });
    },
    Identifier(node) {
      // Skip declarations, only include references
      expressions.push({
        type: 'Identifier',
        loc: node.loc,
        text: node.name
      });
    },
    ArrayExpression(node) {
      expressions.push({
        type: 'ArrayExpression',
        loc: node.loc,
        text: content.slice(node.start, node.end)
      });
    }
  });

  return expressions;
}

function generateAnnotations(jsFile, count, seed) {
  const content = fs.readFileSync(jsFile, 'utf-8');
  const filename = path.basename(jsFile);
  const expressions = findExpressions(content, filename);

  if (expressions.length === 0) {
    return { annotations: [] };
  }

  const rand = seededRandom(seed);

  // Shuffle and select
  const shuffled = expressions.slice().sort(() => rand() - 0.5);
  const selected = shuffled.slice(0, Math.min(count, shuffled.length));

  const annotations = selected.map(expr => ({
    comment: `${expr.text.slice(0, 30)}${expr.text.length > 30 ? '...' : ''} at line ${expr.loc.start.line}`,
    location: {
      file: filename,
      start: {
        line: expr.loc.start.line,
        column: expr.loc.start.column + 1  // 1-based
      },
      end: {
        line: expr.loc.end.line,
        column: expr.loc.end.column + 1
      }
    },
    type: TYPES[Math.floor(rand() * TYPES.length)]
  }));

  return { annotations };
}

function main() {
  const options = parseArgs();

  if (!options.jsFile) {
    console.error('Usage: node random_annotate.js <js_file> [--count N] [--output file.json]');
    process.exit(1);
  }

  if (!fs.existsSync(options.jsFile)) {
    console.error(`Error: File not found: ${options.jsFile}`);
    process.exit(1);
  }

  const annotations = generateAnnotations(options.jsFile, options.count, options.seed);
  const outputFile = options.output || options.jsFile.replace('.js', '_annotations.json');

  fs.writeFileSync(outputFile, JSON.stringify(annotations, null, 2));
  console.log(`Generated ${annotations.annotations.length} annotations -> ${outputFile}`);
}

main();
