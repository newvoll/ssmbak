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
06/13/24 01:43:05   CREATE_IN_PROGRESS  ssmbak  AWS::CloudFormation::Stack  User Initiated
...
06/13/24 01:44:15   CREATE_COMPLETE  ssmbak  AWS::CloudFormation::Stack


% ssmbak-all --do-it
{'name': '/newvoll/ssmbak/bucketname', 'type': 'String', 'operation': 'Update', 'time': datetime.datetime(2024, 6, 12, 18, 44, 47, 979407), 'description': 'So other apps can find this stack'}
{'name': '/newvoll/ssmbak/stackname', 'type': 'String', 'operation': 'Update', 'time': datetime.datetime(2024, 6, 12, 18, 44, 48, 392828), 'description': 'So other apps can find this stack'}

Above was backed-up (might be nothing).


% aws ssm put-parameter --name /testoossmbak/deep/yay --value hihi --type String \
  && sleep 60 \
  && IN_BETWEEN=`date -u +"%Y-%m-%dT%H:%M:%S"` \
  && sleep 60 \
  && aws ssm delete-parameter --name /testoossmbak/deep/yay

Standard        1


% aws ssm get-parameter --name /testoossmbak/deep/yay

An error occurred (ParameterNotFound) when calling the GetParameter operation:


% ssmbak preview /testoossmbak $IN_BETWEEN --recursive
+------------------------+-------+--------+---------------------------+
| Name                   | Value | Type   | Modified                  |
+------------------------+-------+--------+---------------------------+
| /testoossmbak/deep/yay | hihi  | String | 2024-06-13 01:54:26+00:00 |
+------------------------+-------+--------+---------------------------+


% aws ssm get-parameter --name /testoossmbak/deep/yay

An error occurred (ParameterNotFound) when calling the GetParameter operation:


% ssmbak restore /testoossmbak $IN_BETWEEN --recursive
+------------------------+-------+--------+---------------------------+
| Name                   | Value | Type   | Modified                  |
+------------------------+-------+--------+---------------------------+
| /testoossmbak/deep/yay | hihi  | String | 2024-06-13 01:54:26+00:00 |
+------------------------+-------+--------+---------------------------+


% aws ssm get-parameter --name /testoossmbak/deep/yay
PARAMETER       arn:aws:ssm:us-west-2:285043365592:parameter/testoossmbak/deep/yay      text    2024-06-12T18:57:41.497000-07:00        /testoossmbak/deep/yay  String  hihi    1


% LAMBDA_NAME=`ssmbak-stack ssmbak lambdaname`
% aws logs tail --follow --format short /aws/lambda/$LAMBDA_NAME
2024-06-13T01:55:00 START RequestId: 6e3603fd-5a60-54a9-bd94-5d1909c8721d Version: $LATEST
2024-06-13T01:55:00 [INFO]	2024-06-13T01:55:00.754Z	6e3603fd-5a60-54a9-bd94-5d1909c8721d	put_object {'Bucket': 'ssmbak-bucket-dkvp9oegrx2y', 'Key': '/testoossmbak/deep/yay', 'Tagging': 'ssmbakTime=1718243666&ssmbakType=String', 'Body': 'hihi'}
2024-06-13T01:55:00 [INFO]	2024-06-13T01:55:00.931Z	6e3603fd-5a60-54a9-bd94-5d1909c8721d	result: 200
2024-06-13T01:55:00 END RequestId: 6e3603fd-5a60-54a9-bd94-5d1909c8721d
2024-06-13T01:55:00 REPORT RequestId: 6e3603fd-5a60-54a9-bd94-5d1909c8721d	Duration: 516.25 ms	Billed Duration: 517 ms	Memory Size: 128 MB	Max Memory Used: 84 MB
2024-06-13T01:56:44 START RequestId: 195bbad7-7833-5e04-9a9f-e4332c2a68b0 Version: $LATEST
2024-06-13T01:56:44 [INFO]	2024-06-13T01:56:44.353Z	195bbad7-7833-5e04-9a9f-e4332c2a68b0	delete_object {'Bucket': 'ssmbak-bucket-dkvp9oegrx2y', 'Key': '/testoossmbak/deep/yay'}
2024-06-13T01:56:44 [INFO]	2024-06-13T01:56:44.543Z	195bbad7-7833-5e04-9a9f-e4332c2a68b0	result: 204
2024-06-13T01:56:44 END RequestId: 195bbad7-7833-5e04-9a9f-e4332c2a68b0
2024-06-13T01:56:44 REPORT RequestId: 195bbad7-7833-5e04-9a9f-e4332c2a68b0	Duration: 306.48 ms	Billed Duration: 307 ms	Memory Size: 128 MB	Max Memory Used: 85 MB
2024-06-13T01:58:04 START RequestId: 2137b138-c3fc-5c84-b126-efdc97902a13 Version: $LATEST
2024-06-13T01:58:04 [INFO]	2024-06-13T01:58:04.815Z	2137b138-c3fc-5c84-b126-efdc97902a13	put_object {'Bucket': 'ssmbak-bucket-dkvp9oegrx2y', 'Key': '/testoossmbak/deep/yay', 'Tagging': 'ssmbakTime=1718243861&ssmbakType=String', 'Body': 'hihi'}
2024-06-13T01:58:05 [INFO]	2024-06-13T01:58:04.992Z	2137b138-c3fc-5c84-b126-efdc97902a13	result: 200
2024-06-13T01:58:05 END RequestId: 2137b138-c3fc-5c84-b126-efdc97902a13
2024-06-13T01:58:05 REPORT RequestId: 2137b138-c3fc-5c84-b126-efdc97902a13	Duration: 510.30 ms	Billed Duration: 511 ms	Memory Size: 128 MB	Max Memory Used: 85 MB

```

Gotchas:
* You need a bunch of shady permissions to create the stack. Look for such errors if it fails.
* `aws` commands require that the awscli is installed and configured.
