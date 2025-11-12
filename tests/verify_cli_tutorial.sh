#!/usr/bin/env bash
# Verification script for README CLI Tutorial
# Runs through tutorial commands and compares actual vs expected output

set -uo pipefail

# Configuration
SLEEP_TIME="${SSMBAK_SLEEP:-60}"
SSMBAK_BUCKET="${SSMBAK_BUCKET:-}"

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

# Helper function to print human-readable UTC timestamp
print_timestamp() {
    echo "[$(date -u +"%Y-%m-%d %H:%M:%S UTC")]"
}

# Helper function to show S3 versions for debugging
show_s3_versions() {
    local prefix="$1"
    echo ""
    echo "=== S3 Versions for $prefix ==="
    if [ -z "$SSMBAK_BUCKET" ]; then
        echo "SSMBAK_BUCKET not set, skipping S3 version check"
        return
    fi
    echo "Bucket: $SSMBAK_BUCKET"
    echo "Prefix: $prefix"
    echo "$ aws s3api list-object-versions --bucket $SSMBAK_BUCKET --prefix $prefix --output json"
    local output
    output=$(aws s3api list-object-versions --bucket "$SSMBAK_BUCKET" --prefix "$prefix" --output json 2>&1)
    local exit_code=$?

    echo "Exit code: $exit_code"
    echo "Raw output length: ${#output} bytes"

    if [ "$exit_code" -ne 0 ]; then
        echo "AWS CLI error:"
        echo "$output"
    elif echo "$output" | jq -e . >/dev/null 2>&1; then
        local version_count=$(echo "$output" | jq '(.Versions // []) | length')
        local delete_count=$(echo "$output" | jq '(.DeleteMarkers // []) | length')
        echo "Found: $version_count versions, $delete_count delete markers"

        if [ "$version_count" -gt 0 ] || [ "$delete_count" -gt 0 ]; then
            echo "$output" | jq -r '
                ((.Versions // []) + (.DeleteMarkers // [] | map(. + {IsDeleteMarker: true}))) |
                sort_by(.LastModified) | reverse |
                .[] |
                [
                    .Key,
                    (.VersionId[0:8] // "N/A"),
                    .LastModified,
                    (.IsLatest // false),
                    (if .IsDeleteMarker then "DELETE" else (.Size // 0) end)
                ] | @tsv
            ' | column -t -s $'\t'
        fi
    else
        echo "Invalid JSON response:"
        echo "$output" | head -20
    fi
    echo "=== End S3 Versions ==="
    echo ""
}

# Helper function to retry on failure
# Usage: retry_on_failure "test_name" command_function
# Returns 0 on success, 1 on failure after retry
retry_on_failure() {
    local test_name="$1"
    local test_function="$2"

    if $test_function; then
        return 0
    else
        echo -e "${YELLOW}⚠ Test failed, waiting 120 seconds before retry...${NC}"
        echo "$(print_timestamp) Starting 120s wait for retry"
        sleep 120
        echo "$(print_timestamp) Retrying: $test_name"

        if $test_function; then
            echo -e "${GREEN}✓ Test passed on retry${NC}"
            return 0
        else
            return 1
        fi
    fi
}

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
        return 0
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
        return 1
    fi
}

# Helper function to check if values match pattern
check_values() {
    local test_name="$1"
    local expected_value="$2"
    shift 2
    local params=("$@")

    local actual=$(aws ssm get-parameters-by-path --path /testyssmbak --recursive \
        | perl -ne '@h=split; print "$h[4] \t\t $h[6]\n";')

    # Display the output
    echo "$actual"

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
        return 0
    else
        echo -e "${RED}✗ FAIL${NC}: $test_name"
        echo "Expected all parameters to have value: $expected_value"
        echo ""
        ((FAIL_COUNT++))
        return 1
    fi
}

echo "$(print_timestamp) Step 1: Creating test parameters..."
echo "$ aws ssm put-parameter --name /testyssmbak --value initial --type String --overwrite"
aws ssm put-parameter --name /testyssmbak --value initial --type String --overwrite
for i in $(seq 3); do
    echo "$ aws ssm put-parameter --name /testyssmbak/$i --value initial --type String --overwrite"
    aws ssm put-parameter --name /testyssmbak/$i --value initial --type String --overwrite
    echo "$ aws ssm put-parameter --name /testyssmbak/deeper/$i --value initial --type String --overwrite"
    aws ssm put-parameter --name /testyssmbak/deeper/$i --value initial --type String --overwrite
done
echo "Created 7 parameters"

echo ""
echo "$(print_timestamp) Step 2: Waiting ${SLEEP_TIME}s for Lambda to process..."
sleep "$SLEEP_TIME"

show_s3_versions "testyssmbak"

echo "$(print_timestamp) Step 3: Marking IN_BETWEEN timestamp..."
IN_BETWEEN=$(date -u +"%Y-%m-%dT%H:%M:%S")
echo "IN_BETWEEN=$IN_BETWEEN"

echo ""
echo "$(print_timestamp) Step 4: Waiting another ${SLEEP_TIME}s..."
sleep "$SLEEP_TIME"

echo "$(print_timestamp) Step 5: Verifying all parameters are 'initial'..."
verify_step5() {
    echo "$ aws ssm get-parameters-by-path --path /testyssmbak --recursive"
    check_values "All params initially 'initial'" "initial" \
        "/testyssmbak/1" "/testyssmbak/2" "/testyssmbak/3" \
        "/testyssmbak/deeper/1" "/testyssmbak/deeper/2" "/testyssmbak/deeper/3"
}
retry_on_failure "Step 5 verification" verify_step5

echo ""
echo "$(print_timestamp) Step 6: Updating parameter #2 to 'UPDATED'..."
echo "$ aws ssm put-parameter --name /testyssmbak/2 --value UPDATED --type String --overwrite"
aws ssm put-parameter --name /testyssmbak/2 --value UPDATED --type String --overwrite
echo "$ aws ssm put-parameter --name /testyssmbak/deeper/2 --value UPDATED --type String --overwrite"
aws ssm put-parameter --name /testyssmbak/deeper/2 --value UPDATED --type String --overwrite

echo ""
echo "$(print_timestamp) Step 7: Waiting ${SLEEP_TIME}s before marking UPDATED_MARK..."
sleep "$SLEEP_TIME"

echo "$(print_timestamp) Step 8: Marking UPDATED_MARK timestamp..."
UPDATED_MARK=$(date -u +"%Y-%m-%dT%H:%M:%S")
echo "UPDATED_MARK=$UPDATED_MARK"

echo ""
echo "$(print_timestamp) Step 9: Verifying #2 parameters are 'UPDATED'..."
verify_step9() {
    echo "$ aws ssm get-parameters-by-path --path /testyssmbak --recursive"
    actual=$(aws ssm get-parameters-by-path --path /testyssmbak --recursive \
        | perl -ne '@h=split; print "$h[4] \t\t $h[6]\n";')

    # Display the output
    echo "$actual"

    if echo "$actual" | grep -q "/testyssmbak/2.*UPDATED" && \
       echo "$actual" | grep -q "/testyssmbak/deeper/2.*UPDATED"; then
        echo -e "${GREEN}✓ PASS${NC}: Parameters #2 updated to 'UPDATED'"
        ((PASS_COUNT++))
        return 0
    else
        echo -e "${RED}✗ FAIL${NC}: Parameters #2 should be 'UPDATED'"
        ((FAIL_COUNT++))
        return 1
    fi
}
retry_on_failure "Step 9 verification" verify_step9

echo ""
echo "$(print_timestamp) Step 10: Testing preview at IN_BETWEEN (should show all 'initial')..."
verify_step10() {
    echo "$ poetry run ssmbak -v preview /testyssmbak/ \"$IN_BETWEEN\" --recursive"
    preview_output=$(poetry run ssmbak -v preview /testyssmbak/ "$IN_BETWEEN" --recursive)
    echo "$preview_output"

    # Check if preview shows initial values for all parameters
    # Count lines with "initial" in them (should be at least 6)
    initial_count=$(echo "$preview_output" | grep -c "| initial |" || true)
    # Check that UPDATED doesn't appear
    updated_count=$(echo "$preview_output" | grep -c "| UPDATED |" || true)
    # Check for deleted markers - should be 0
    deleted_count=$(echo "$preview_output" | grep -c "| True" || true)

    if [ "$initial_count" -ge 6 ] && [ "$updated_count" -eq 0 ] && [ "$deleted_count" -eq 0 ]; then
        echo -e "${GREEN}✓ PASS${NC}: Preview at IN_BETWEEN shows 'initial' values for all parameters"
        ((PASS_COUNT++))
        return 0
    else
        echo -e "${RED}✗ FAIL${NC}: Preview at IN_BETWEEN should show only 'initial' values"
        echo "  Found: initial=$initial_count (need >=6), updated=$updated_count (need 0), deleted=$deleted_count (need 0)"
        ((FAIL_COUNT++))
        return 1
    fi
}
if ! retry_on_failure "Step 10 verification" verify_step10; then
    show_s3_versions "testyssmbak"
fi

echo ""
echo "$(print_timestamp) Step 11: Testing restore to IN_BETWEEN..."
echo "$ poetry run ssmbak -v restore /testyssmbak/ \"$IN_BETWEEN\" --recursive"
restore_output=$(poetry run ssmbak -v restore /testyssmbak/ "$IN_BETWEEN" --recursive)
echo "$restore_output"

# Verify parameters are restored to initial
sleep 5  # Brief wait for restore to complete
verify_step11() {
    echo "$ aws ssm get-parameters-by-path --path /testyssmbak --recursive"
    check_values "After restore to IN_BETWEEN, all 'initial'" "initial" \
        "/testyssmbak/1" "/testyssmbak/2" "/testyssmbak/3" \
        "/testyssmbak/deeper/1" "/testyssmbak/deeper/2" "/testyssmbak/deeper/3"
}
retry_on_failure "Step 11 verification" verify_step11

echo ""
echo "$(print_timestamp) Step 12: Testing single parameter restore to UPDATED_MARK..."
verify_step12() {
    echo "$ poetry run ssmbak -v preview /testyssmbak/deeper/2 \"$UPDATED_MARK\""
    preview_single=$(poetry run ssmbak -v preview /testyssmbak/deeper/2 "$UPDATED_MARK")
    echo "$preview_single"

    # Check that the specific parameter shows UPDATED and is not deleted
    if echo "$preview_single" | grep -q "| /testyssmbak/deeper/2 " && \
       echo "$preview_single" | grep -q "| UPDATED |" && \
       ! echo "$preview_single" | grep -q "| True"; then
        echo -e "${GREEN}✓ PASS${NC}: Preview shows /testyssmbak/deeper/2 as 'UPDATED'"
        ((PASS_COUNT++))
        return 0
    else
        echo -e "${RED}✗ FAIL${NC}: Preview should show 'UPDATED' for /testyssmbak/deeper/2 (not deleted)"
        ((FAIL_COUNT++))
        return 1
    fi
}
retry_on_failure "Step 12 verification" verify_step12

echo ""
echo "$(print_timestamp) Step 13: Restoring single parameter..."
echo "$ poetry run ssmbak -v restore /testyssmbak/deeper/2 \"$UPDATED_MARK\""
poetry run ssmbak -v restore /testyssmbak/deeper/2 "$UPDATED_MARK"

sleep 5
verify_step13() {
    echo "$ aws ssm get-parameter --name /testyssmbak/deeper/2 --query 'Parameter.Value' --output text"
    actual=$(aws ssm get-parameter --name /testyssmbak/deeper/2 --query 'Parameter.Value' --output text)

    # Display the output
    echo "$actual"

    if [ "$actual" = "UPDATED" ]; then
        echo -e "${GREEN}✓ PASS${NC}: /testyssmbak/deeper/2 restored to 'UPDATED'"
        ((PASS_COUNT++))
        return 0
    else
        echo -e "${RED}✗ FAIL${NC}: /testyssmbak/deeper/2 should be 'UPDATED', got: $actual"
        ((FAIL_COUNT++))
        return 1
    fi
}
retry_on_failure "Step 13 verification" verify_step13

echo ""
echo "$(print_timestamp) Step 14: Marking END_MARK and deleting all parameters..."
END_MARK=$(date -u +"%Y-%m-%dT%H:%M:%S")
echo "END_MARK=$END_MARK"

echo "$ aws ssm get-parameters-by-path --path /testyssmbak --recursive"
params_to_delete=$(aws ssm get-parameters-by-path --path /testyssmbak --recursive \
    | perl -ne '@h=split; print "$h[4] ";')
echo "$ aws ssm delete-parameters --names $params_to_delete"
aws ssm delete-parameters --names $params_to_delete

# Also delete the key (not path)
echo "$ aws ssm delete-parameter --name /testyssmbak"
aws ssm delete-parameter --name /testyssmbak 2>/dev/null || true

echo ""
echo "$(print_timestamp) Step 15: Waiting ${SLEEP_TIME}s for Lambda to process deletions..."
sleep "$SLEEP_TIME"

echo ""
echo "$(print_timestamp) Step 16: Testing preview at END_MARK (should show deleted params recoverable)..."
verify_step16() {
    echo "$ poetry run ssmbak -v preview /testyssmbak/ \"$END_MARK\" --recursive"
    preview_deleted=$(poetry run ssmbak -v preview /testyssmbak/ "$END_MARK" --recursive)
    echo "$preview_deleted"

    # Check that preview shows the parameters with actual values (recoverable)
    # Count parameters that have the path pattern
    param_count=$(echo "$preview_deleted" | grep -c "/testyssmbak/" || true)
    # Count how many show as deleted (these should be marked recoverable)
    # For deleted params at END_MARK, they should show values from before deletion
    # Check that we have at least 6 parameters and they're not all showing empty values
    non_empty_values=$(echo "$preview_deleted" | grep "/testyssmbak/" | grep -cv "| \+|" || true)

    if [ "$param_count" -ge 6 ] && [ "$non_empty_values" -ge 6 ]; then
        echo -e "${GREEN}✓ PASS${NC}: Preview at END_MARK shows recoverable parameters with values"
        ((PASS_COUNT++))
        return 0
    else
        echo -e "${RED}✗ FAIL${NC}: Preview should show 6 recoverable parameters with values"
        echo "  Found: param_count=$param_count (need >=6), non_empty_values=$non_empty_values (need >=6)"
        ((FAIL_COUNT++))
        return 1
    fi
}
if ! retry_on_failure "Step 16 verification" verify_step16; then
    show_s3_versions "testyssmbak"
fi

echo ""
echo "$(print_timestamp) Step 17: Testing path vs key distinction..."
# Recreate /testyssmbak key for this test
echo "$ aws ssm put-parameter --name /testyssmbak --value initial --type String --overwrite"
aws ssm put-parameter --name /testyssmbak --value initial --type String --overwrite
sleep 10

STEP17_TIME=$(date -u +"%Y-%m-%dT%H:%M:%S")
echo "$ poetry run ssmbak -v preview /testyssmbak \"$STEP17_TIME\""
key_preview=$(poetry run ssmbak -v preview /testyssmbak "$STEP17_TIME")
echo "$key_preview"
echo ""
echo "$ poetry run ssmbak -v preview /testyssmbak/ \"$STEP17_TIME\""
path_preview=$(poetry run ssmbak -v preview /testyssmbak/ "$STEP17_TIME")
echo "$path_preview"

# Key preview should show just /testyssmbak
if echo "$key_preview" | grep -q "^| /testyssmbak " && \
   ! echo "$key_preview" | grep -q "/testyssmbak/"; then
    echo -e "${GREEN}✓ PASS${NC}: Key /testyssmbak shows only the key"
    ((PASS_COUNT++))
else
    echo -e "${RED}✗ FAIL${NC}: Key preview incorrect"
    echo "$key_preview"
    ((FAIL_COUNT++))
fi

# Path preview should not show /testyssmbak key, only path items
if ! echo "$path_preview" | grep -q "^| /testyssmbak " && \
   echo "$path_preview" | grep -q "/testyssmbak/"; then
    echo -e "${GREEN}✓ PASS${NC}: Path /testyssmbak/ shows only path items"
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
