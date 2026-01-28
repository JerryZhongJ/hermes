#!/bin/bash
# Test TypeGuard correctness with random annotations using hermes-lit + FileCheck
# Prerequisites:
#   1. Build the project: cmake --build --preset debug
#   2. Generate test files: node tools/gen_typeguard_tests.js
#
# Usage: ./test_type_guard.sh [--count N] [--repeat R] [--max M] [--verbose] [--verify-ir]
#   --count N:  Number of annotations per file (default: 20)
#   --repeat R: Number of annotation variants per JS file (default: 1)
#   --max M:    Maximum number of JS files to test (default: 50)
#   --verbose:  Show detailed output
#   --verify-ir: Only test if InsertTypeGuard pass can pass IRVerifier (not correctness)

# Don't use set -e, we handle errors manually

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BUILD_DIR="$PROJECT_DIR/../static-build-debug"
HERMES_LIT="$BUILD_DIR/bin/hermes-lit"
SHERMES="$BUILD_DIR/bin/shermes"
FILECHECK="$BUILD_DIR/bin/FileCheck"
TEST_DIR="$PROJECT_DIR/test/typeguard"
ANNOTATE_SCRIPT="$SCRIPT_DIR/random_annotate/index.js"

# Default settings
ANNOTATION_COUNT=20
VERBOSE=0
MAX_TESTS=50
REPEAT=1
VERIFY_IR=0

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --count|-n)
            ANNOTATION_COUNT="$2"
            shift 2
            ;;
        --verbose|-v)
            VERBOSE=1
            shift
            ;;
        --max|-m)
            MAX_TESTS="$2"
            shift 2
            ;;
        --repeat|-r)
            REPEAT="$2"
            shift 2
            ;;
        --verify-ir)
            VERIFY_IR=1
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Check dependencies
if [[ ! -x "$HERMES_LIT" ]]; then
    echo "Error: hermes-lit not found at $HERMES_LIT"
    echo "Please build the project first: cmake --build --preset release"
    exit 1
fi

if [[ ! -d "$TEST_DIR" ]]; then
    echo "Error: test/typeguard directory not found at $TEST_DIR"
    echo "Please run: node tools/gen_typeguard_tests.js"
    exit 1
fi

if [[ ! -f "$ANNOTATE_SCRIPT" ]]; then
    echo "Error: random_annotate script not found at $ANNOTATE_SCRIPT"
    exit 1
fi

# Create temp directory
TEMP_DIR=$(mktemp -d)
trap "rm -rf $TEMP_DIR" EXIT

# Create persistent directory for failed tests
FAIL_DIR="/tmp/typeguard_failures_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$FAIL_DIR"

echo "=== InsertTypeGuard Pass Test ==="
if [[ $VERIFY_IR -eq 1 ]]; then
    echo "Mode: IRVerifier only (not testing correctness)"
else
    echo "Mode: Correctness test"
fi
echo "Config: --count $ANNOTATION_COUNT --repeat $REPEAT --max $MAX_TESTS"
echo "Running..."

PASSED=0
FAILED=0
SKIPPED=0

# Files to skip (syntax errors by design, not InsertTypeGuard bugs)
SKIP_FILES=(
    "lazy-error-test"
    "async-generators-throw"
    "const-reassignment"
    "async-generators"
    "lazy-error-irgen"
    "delete-super-prop"
    "private-properties"
)

# Find test files (exclude flow/ directory which requires special parsing)
TEST_FILES=$(find "$TEST_DIR" -name "*.js" -type f -not -path "*/flow/*" | head -n "$MAX_TESTS")

for JS_FILE in $TEST_FILES; do
    BASENAME=$(basename "$JS_FILE" .js)

    # Skip known syntax error files
    SHOULD_SKIP=0
    for SKIP in "${SKIP_FILES[@]}"; do
        if [[ "$BASENAME" == "$SKIP" ]]; then
            SHOULD_SKIP=1
            break
        fi
    done
    if [[ $SHOULD_SKIP -eq 1 ]]; then
        SKIPPED=$((SKIPPED + 1))
        continue
    fi

    for ((R=1; R<=REPEAT; R++)); do
        ANNOTATION_FILE="$TEMP_DIR/${BASENAME}_${R}_annotations.json"

        # Generate random annotations
        node "$ANNOTATE_SCRIPT" "$JS_FILE" --count "$ANNOTATION_COUNT" --output "$ANNOTATION_FILE" >/dev/null 2>&1

        # Check if annotations were generated
        if [[ ! -s "$ANNOTATION_FILE" ]] || ! grep -q '"annotations"' "$ANNOTATION_FILE"; then
            SKIPPED=$((SKIPPED + 1))
            continue
        fi

        # Run test based on mode
        if [[ $VERIFY_IR -eq 1 ]]; then
            # IRVerifier mode: only test if InsertTypeGuard pass can pass IRVerifier
            "$SHERMES" "$JS_FILE" \
                -verify-ir \
                -dump-ir \
                -Xcustom-opt=inserttypeguard \
                -type-annotation-file="$ANNOTATION_FILE" \
                > "$TEMP_DIR/output.txt" 2>&1
            TEST_RESULT=$?
        else
            # Correctness mode: Run hermes-lit with TypeGuard annotation
            "$HERMES_LIT" "$JS_FILE" \
                -D annotation_file="$ANNOTATION_FILE" \
                -D shermes="$SHERMES" \
                -D FileCheck="$FILECHECK" \
                --no-progress-bar > "$TEMP_DIR/output.txt" 2>&1
            TEST_RESULT=$?
        fi

        if [[ $TEST_RESULT -eq 0 ]]; then
            PASSED=$((PASSED + 1))
        else
            FAILED=$((FAILED + 1))

            # Save failed test case to persistent directory
            cp "$JS_FILE" "$FAIL_DIR/${BASENAME}.js"
            cp "$ANNOTATION_FILE" "$FAIL_DIR/${BASENAME}_${R}_annotations.json"
            cp "$TEMP_DIR/output.txt" "$FAIL_DIR/${BASENAME}_${R}_error.txt"

            # Report failure details
            echo ""
            echo "=== FAIL: $BASENAME#$R ==="
            echo "File: $JS_FILE"
            echo "Annotations: $ANNOTATION_FILE"
            ANN_COUNT=$(grep -c '"location"' "$ANNOTATION_FILE" 2>/dev/null || echo "0")
            echo "Annotation count: $ANN_COUNT"
            echo "--- Error output (last 10 lines) ---"
            tail -10 "$TEMP_DIR/output.txt"
            echo "--- Saved to: $FAIL_DIR/${BASENAME}_${R}_* ---"
        fi
    done
done

echo ""
echo "=== Results ==="
echo "Passed: $PASSED"
echo "Failed: $FAILED"
echo "Skipped: $SKIPPED"
echo "Total: $((PASSED + FAILED + SKIPPED))"

if [[ $FAILED -gt 0 ]]; then
    echo ""
    echo "Failed tests saved to: $FAIL_DIR"
    exit 1
fi

# Clean up empty fail directory
rmdir "$FAIL_DIR" 2>/dev/null
exit 0
