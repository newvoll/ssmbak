#!/usr/bin/env bash
# Verification script for README CLI Tutorial
# Runs through tutorial commands and compares actual vs expected output

set -uo pipefail

# Configuration
SLEEP_TIME="${SSMBAK_SLEEP:-120}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test counters
PASS_COUNT=0
FAIL_COUNT=0

# Temporary files for comparison
EXPECTED_FILE=$(mktemp)
ACTUAL_FILE=$(mktemp)

# Cleanup on exit
trap 'rm -f "$EXPECTED_FILE" "$ACTUAL_FILE"' EXIT

echo "====================================="
echo "CLI Tutorial Verification Script"
echo "====================================="
echo "Sleep time: ${SLEEP_TIME}s"
echo ""

# Helper function to compare output
compare_output() {
    local test_name="$1"
    local expected="$2"
    local actual="$3"

    echo "$expected" > "$EXPECTED_FILE"
    echo "$actual" > "$ACTUAL_FILE"

    if diff -q "$EXPECTED_FILE" "$ACTUAL_FILE" > /dev/null 2>&1; then
        echo -e "${GREEN}✓ PASS${NC}: $test_name"
        ((PASS_COUNT++))
    else
        echo -e "${RED}✗ FAIL${NC}: $test_name"
        echo "--- Expected ---"
        echo "$expected"
        echo "--- Actual ---"
        echo "$actual"
        echo "--- Diff ---"
        diff "$EXPECTED_FILE" "$ACTUAL_FILE" || true
        echo ""
        ((FAIL_COUNT++))
    fi
}

# Helper function to check if values match pattern
check_values() {
    local test_name="$1"
    local expected_value="$2"
    shift 2
    local params=("$@")

    local actual=$(aws ssm get-parameters-by-path --path /westyssmbak --recursive \
        | perl -ne '@h=split; print "$h[4] \t\t $h[6]\n";')

    local all_match=true
    for param in "${params[@]}"; do
        if ! echo "$actual" | grep -q "$param.*$expected_value"; then
            all_match=false
            break
        fi
    done

    if $all_match; then
        echo -e "${GREEN}✓ PASS${NC}: $test_name"
        ((PASS_COUNT++))
    else
        echo -e "${RED}✗ FAIL${NC}: $test_name"
        echo "Expected all parameters to have value: $expected_value"
        echo "Actual output:"
        echo "$actual"
        echo ""
        ((FAIL_COUNT++))
    fi
}

echo "Step 1: Creating test parameters..."
aws ssm put-parameter --name /westyssmbak --value initial --type String --overwrite > /dev/null
for i in $(seq 3); do
    aws ssm put-parameter --name /westyssmbak/$i --value initial --type String --overwrite > /dev/null
    aws ssm put-parameter --name /westyssmbak/deeper/$i --value initial --type String --overwrite > /dev/null
done
echo "Created 7 parameters"

echo ""
echo "Step 2: Waiting ${SLEEP_TIME}s for Lambda to process..."
sleep "$SLEEP_TIME"

echo "Step 3: Marking IN_BETWEEN timestamp..."
IN_BETWEEN=$(date -u +"%Y-%m-%dT%H:%M:%S")
echo "IN_BETWEEN=$IN_BETWEEN"

echo ""
echo "Step 4: Waiting another ${SLEEP_TIME}s..."
sleep "$SLEEP_TIME"

echo "Step 5: Verifying all parameters are 'initial'..."
check_values "All params initially 'initial'" "initial" \
    "/westyssmbak/1" "/westyssmbak/2" "/westyssmbak/3" \
    "/westyssmbak/deeper/1" "/westyssmbak/deeper/2" "/westyssmbak/deeper/3"

echo ""
echo "Step 6: Updating parameter #2 to 'UPDATED'..."
aws ssm put-parameter --name /westyssmbak/2 --value UPDATED --type String --overwrite > /dev/null
aws ssm put-parameter --name /westyssmbak/deeper/2 --value UPDATED --type String --overwrite > /dev/null

echo ""
echo "Step 7: Waiting ${SLEEP_TIME}s before marking UPDATED_MARK..."
sleep "$SLEEP_TIME"

echo "Step 8: Marking UPDATED_MARK timestamp..."
UPDATED_MARK=$(date -u +"%Y-%m-%dT%H:%M:%S")
echo "UPDATED_MARK=$UPDATED_MARK"

echo ""
echo "Step 9: Verifying #2 parameters are 'UPDATED'..."
actual=$(aws ssm get-parameters-by-path --path /westyssmbak --recursive \
    | perl -ne '@h=split; print "$h[4] \t\t $h[6]\n";')

if echo "$actual" | grep -q "/westyssmbak/2.*UPDATED" && \
   echo "$actual" | grep -q "/westyssmbak/deeper/2.*UPDATED"; then
    echo -e "${GREEN}✓ PASS${NC}: Parameters #2 updated to 'UPDATED'"
    ((PASS_COUNT++))
else
    echo -e "${RED}✗ FAIL${NC}: Parameters #2 should be 'UPDATED'"
    echo "$actual"
    ((FAIL_COUNT++))
fi

echo ""
echo "Step 10: Testing preview at IN_BETWEEN (should show all 'initial')..."
preview_output=$(poetry run ssmbak -v preview /westyssmbak/ "$IN_BETWEEN" --recursive)
echo "$preview_output"

# Check if preview shows initial values
if echo "$preview_output" | grep -q "initial" && \
   ! echo "$preview_output" | grep -q "UPDATED"; then
    echo -e "${GREEN}✓ PASS${NC}: Preview at IN_BETWEEN shows 'initial' values"
    ((PASS_COUNT++))
else
    echo -e "${RED}✗ FAIL${NC}: Preview at IN_BETWEEN should show only 'initial' values"
    ((FAIL_COUNT++))
fi

echo ""
echo "Step 11: Testing restore to IN_BETWEEN..."
restore_output=$(poetry run ssmbak -v restore /westyssmbak/ "$IN_BETWEEN" --recursive)
echo "$restore_output"

# Verify parameters are restored to initial
sleep 5  # Brief wait for restore to complete
check_values "After restore to IN_BETWEEN, all 'initial'" "initial" \
    "/westyssmbak/1" "/westyssmbak/2" "/westyssmbak/3" \
    "/westyssmbak/deeper/1" "/westyssmbak/deeper/2" "/westyssmbak/deeper/3"

echo ""
echo "Step 12: Testing single parameter restore to UPDATED_MARK..."
preview_single=$(poetry run ssmbak -v preview /westyssmbak/deeper/2 "$UPDATED_MARK")
echo "$preview_single"

if echo "$preview_single" | grep -q "/westyssmbak/deeper/2.*UPDATED"; then
    echo -e "${GREEN}✓ PASS${NC}: Preview shows /westyssmbak/deeper/2 as 'UPDATED'"
    ((PASS_COUNT++))
else
    echo -e "${RED}✗ FAIL${NC}: Preview should show 'UPDATED' for /westyssmbak/deeper/2"
    ((FAIL_COUNT++))
fi

echo ""
echo "Step 13: Restoring single parameter..."
poetry run ssmbak -v restore /westyssmbak/deeper/2 "$UPDATED_MARK" > /dev/null

sleep 5
actual=$(aws ssm get-parameter --name /westyssmbak/deeper/2 --query 'Parameter.Value' --output text)
if [ "$actual" = "UPDATED" ]; then
    echo -e "${GREEN}✓ PASS${NC}: /westyssmbak/deeper/2 restored to 'UPDATED'"
    ((PASS_COUNT++))
else
    echo -e "${RED}✗ FAIL${NC}: /westyssmbak/deeper/2 should be 'UPDATED', got: $actual"
    ((FAIL_COUNT++))
fi

echo ""
echo "Step 14: Marking END_MARK and deleting all parameters..."
END_MARK=$(date -u +"%Y-%m-%dT%H:%M:%S")
echo "END_MARK=$END_MARK"

params_to_delete=$(aws ssm get-parameters-by-path --path /westyssmbak --recursive \
    | perl -ne '@h=split; print "$h[4] ";')
aws ssm delete-parameters --names $params_to_delete > /dev/null

# Also delete the key (not path)
aws ssm delete-parameter --name /westyssmbak > /dev/null || true

echo ""
echo "Step 15: Waiting ${SLEEP_TIME}s for Lambda to process deletions..."
sleep "$SLEEP_TIME"

echo ""
echo "Step 16: Testing preview at END_MARK (should show deleted params recoverable)..."
preview_deleted=$(poetry run ssmbak -v preview /westyssmbak/ "$END_MARK" --recursive)
echo "$preview_deleted"

# Check that preview shows the parameters (they should be recoverable)
param_count=$(echo "$preview_deleted" | grep -c "/westyssmbak/" || true)
if [ "$param_count" -ge 6 ]; then
    echo -e "${GREEN}✓ PASS${NC}: Preview at END_MARK shows recoverable parameters"
    ((PASS_COUNT++))
else
    echo -e "${RED}✗ FAIL${NC}: Preview should show 6 recoverable parameters, found: $param_count"
    ((FAIL_COUNT++))
fi

echo ""
echo "Step 17: Testing path vs key distinction..."
# Recreate /westyssmbak key for this test
aws ssm put-parameter --name /westyssmbak --value initial --type String --overwrite > /dev/null
sleep 10

key_preview=$(poetry run ssmbak -v preview /westyssmbak "$(date -u +"%Y-%m-%dT%H:%M:%S")")
path_preview=$(poetry run ssmbak -v preview /westyssmbak/ "$(date -u +"%Y-%m-%dT%H:%M:%S")")

# Key preview should show just /westyssmbak
if echo "$key_preview" | grep -q "^| /westyssmbak " && \
   ! echo "$key_preview" | grep -q "/westyssmbak/"; then
    echo -e "${GREEN}✓ PASS${NC}: Key /westyssmbak shows only the key"
    ((PASS_COUNT++))
else
    echo -e "${RED}✗ FAIL${NC}: Key preview incorrect"
    echo "$key_preview"
    ((FAIL_COUNT++))
fi

# Path preview should not show /westyssmbak key, only path items
if ! echo "$path_preview" | grep -q "^| /westyssmbak " && \
   echo "$path_preview" | grep -q "/westyssmbak/"; then
    echo -e "${GREEN}✓ PASS${NC}: Path /westyssmbak/ shows only path items"
    ((PASS_COUNT++))
else
    echo -e "${RED}✗ FAIL${NC}: Path preview incorrect"
    echo "$path_preview"
    ((FAIL_COUNT++))
fi

echo ""
echo "====================================="
echo "Test Summary"
echo "====================================="
echo -e "Passed: ${GREEN}${PASS_COUNT}${NC}"
echo -e "Failed: ${RED}${FAIL_COUNT}${NC}"
echo "Total:  $((PASS_COUNT + FAIL_COUNT))"
echo ""

if [ "$FAIL_COUNT" -eq 0 ]; then
    echo -e "${GREEN}All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}Some tests failed.${NC}"
    exit 1
fi
