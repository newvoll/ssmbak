# Intro

The AWS SSM Parameter Store is simple and great for AWS config bits,
but it only preserves 100 versions, 0 if the parameter has been
deleted. To enable point-in-time restore, including deleted versions,
we use an s3 bucket with versioning enabled as a backend, with
timestamps in metadata for use with AWS Eventbridge and Lambda. This
project includes all the pieces to both backup and restore SSM Param
paths and keys.

# Quickstart

% pip install ssmbak

