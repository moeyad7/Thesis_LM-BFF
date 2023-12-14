#!/bin/bash

# Specify the file name
file_name="log.txt"
output_file="results.csv"
dataset=$1

# Check if the file exists
if [ ! -f "$file_name" ]; then
    echo "File $file_name not found."
    exit 1
fi

# Check if the CSV file exists
if [ ! -f "$output_file" ]; then
    # Add header to the CSV file if it doesn't exist
    echo "f1_test,acc_test,precision_test,recall_test,f1_dev,acc_dev,precision_dev,recall_dev" > "$output_file"
fi

# Read each line in the file
while IFS= read -r line; do
    # Extract desired attributes using grep and awk
    f1_test=$(echo "$line" | grep -oE "'${dataset}_test_eval_f1_macro': [0-9.]+" | awk '{print $2}')
    acc_test=$(echo "$line" | grep -oE "'${dataset}_test_eval_acc': [0-9.]+" | awk '{print $2}')
    precision_test=$(echo "$line" | grep -oE "'${dataset}_test_eval_precision_macro': [0-9.]+" | awk '{print $2}')
    recall_test=$(echo "$line" | grep -oE "'${dataset}_test_eval_recall_macro': [0-9.]+" | awk '{print $2}')

    f1_dev=$(echo "$line" | grep -oE "'${dataset}_dev_eval_f1_macro': [0-9.]+" | awk '{print $2}')
    acc_dev=$(echo "$line" | grep -oE "'${dataset}_dev_eval_acc': [0-9.]+" | awk '{print $2}')
    precision_dev=$(echo "$line" | grep -oE "'${dataset}_dev_eval_precision_macro': [0-9.]+" | awk '{print $2}')
    recall_dev=$(echo "$line" | grep -oE "'${dataset}_dev_eval_recall_macro': [0-9.]+" | awk '{print $2}')

    # Print the extracted attributes
    echo "$f1_test,$acc_test,$precision_test,$recall_test,$f1_dev,$acc_dev,$precision_dev,$recall_dev" >> "$output_file"

done < "$file_name"
echo "Done"