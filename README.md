# Intro

The AWS SSM Parameter Store is simple and great for AWS config bits,
but it only preserves 100 versions, 0 if the parameter has been
deleted. To enable point-in-time restore, including deleted versions,
we use an s3 bucket with versioning enabled as a backend, with
timestamps in metadata for use with AWS Eventbridge and Lambda. This
project includes all the pieces to both backup and restore SSM Param
paths and keys.

# Quickstart

```
% pip install ssmbak

% ssmbak-stack ssmbak create

% ssmbak-all --do-it

% LAMBDA_NAME=`ssmbak-stack ssmbak lambdaname`

aws ssm put-parameter --name /testoossmbak/deep/yay --value hihi --type String \
  && sleep 1 \
  && IN_BETWEEN=`date -u +"%Y-%m-%dT%H:%M:%S"` \
  && sleep 1 \
  && ssm del test-foo-hee

% aws ssm delete-parameter --name /testoossmbak

% ssmbak preview /testoossmbak 2024-06-05T17:51:00 --recurse

```

In another window: `% aws logs tail --format short /aws/lambda/$LAMBDA_NAME --follow`

Gotchas:
* You need a bunch of permissions to create the stack. Look for such errors if it fails.
* aws logs requires that the awscli is installed and configured.
