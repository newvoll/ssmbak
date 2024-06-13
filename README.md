# Intro

The AWS SSM Parameter Store is simple and great for AWS config bits,
but it only preserves 100 versions, 0 if the parameter has been
deleted. To enable point-in-time restore, including deleted versions
and entire recursive trees, we use an s3 bucket with versioning
enabled as a backend.

Leverages AWS Eventbridge and Lambda. This project includes all the
pieces to both backup and restore SSM Param paths and keys.

A crude cli works, but the library is well-tested.

# CLI Quickstart

```
% pip install ssmbak


% ssmbak-stack ssmbak create  # call it whatever you want instead of ssmbak
06/13/24 01:43:05   CREATE_IN_PROGRESS  ssmbak  AWS::CloudFormation::Stack  User Initiated
...
06/13/24 01:44:15   CREATE_COMPLETE  ssmbak  AWS::CloudFormation::Stack


% ssmbak-all --do-it
{'name': '/newvoll/ssmbak/bucketname', 'type': 'String', 'operation': 'Update', 'time': datetime.datetime(2024, 6, 12, 18, 44, 47, 979407), 'description': 'So other apps can find this stack'}
{'name': '/newvoll/ssmbak/stackname', 'type': 'String', 'operation': 'Update', 'time': datetime.datetime(2024, 6, 12, 18, 44, 48, 392828), 'description': 'So other apps can find this stack'}

Above was backed-up.
```

Those were created by the stack, but the lambda function may not have
been active when they were created.

```
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
```

The stack configures the lambda to write Cloudwatch logs.

```
% LAMBDA_NAME=`ssmbak-stack ssmbak lambdaname`

% aws logs tail --follow --format short /aws/lambda/$LAMBDA_NAME
...
2024-06-13T01:58:04 START RequestId: 2137b138-c3fc-5c84-b126-efdc97902a13 Version: $LATEST
2024-06-13T01:58:04 [INFO]	2024-06-13T01:58:04.815Z	2137b138-c3fc-5c84-b126-efdc97902a13	put_object {'Bucket': 'ssmbak-bucket-dkvp9oegrx2y', 'Key': '/testoossmbak/deep/yay', 'Tagging': 'ssmbakTime=1718243861&ssmbakType=String', 'Body': 'hihi'}
2024-06-13T01:58:05 [INFO]	2024-06-13T01:58:04.992Z	2137b138-c3fc-5c84-b126-efdc97902a13	result: 200
2024-06-13T01:58:05 END RequestId: 2137b138-c3fc-5c84-b126-efdc97902a13
2024-06-13T01:58:05 REPORT RequestId: 2137b138-c3fc-5c84-b126-efdc97902a13	Duration: 510.30 ms	Billed Duration: 511 ms	Memory Size: 128 MB	Max Memory Used: 85 MB
```

## CLI Gotchas:
* You need a bunch of shady permissions to create the stack. Look for such errors if it fails.
* `aws` commands require that the awscli is installed and configured.



# Lib Quickstart

```
% ssmbak-stack ssmbak bucketname
ssmbak-bucket-dkvp9oegrx2y

% python
>>> from ssmbak.restore.actions import Path
>>> from datetime import datetime, timezone
>>> in_between = datetime.strptime("2024-06-13T01:55:26", "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
>>> path = Path("/testoossmbak", in_between, "us-west-2", "ssmbak-bucket-dkvp9oegrx2y", recurse=True)
>>> path.preview()
[{'Name': '/testoossmbak/deep/yay', 'Deleted': True, 'Modified': datetime.datetime(2024, 6, 13, 1, 50, 22, tzinfo=tzutc())}]
>>> path.restore()
```

# General gotchas
* Alarms
* kms key for added security
* No support for advanced ssm params
* probably lose tags if deleted
* testing on aws -- don't use same bucket as running lambda!
  * will set versioning and manipulate/destroy pytest.test_path
