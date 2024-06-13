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
You'll need the awscli and credentials that can create IAM resources
(to assign minimal permissions to the lambda role).

```
% pip install ssmbak
...

% SSMBAK_STACKNAME=ssmbak  # call it whatever you want

% ssmbak-stack $SSMBAK_STACKNAME create
06/13/24 01:43:05   CREATE_IN_PROGRESS  ssmbak  AWS::CloudFormation::Stack  User Initiated
...
06/13/24 01:44:15   CREATE_COMPLETE  ssmbak  AWS::CloudFormation::Stack
```

Create some params with value `initial` in `testyssmbak/` and `testyssmbak/deeper` to show recursion:
```
% for i in $(seq 3)
do
aws ssm put-parameter --name /testyssmbak/$i --value initial --type String --overwrite
aws ssm put-parameter --name /testyssmbak/deeper/$i --value initial --type String --overwrite
done
Standard        1
Standard        1
Standard        1
Standard        1
Standard        1
Standard        1
```

Sleep a bit to give EventBridge some time to process the event, mark
it (UTC), and sleep some more to give ssmbak some time to back them
up.

```
% sleep 30 && IN_BETWEEN=`date -u +"%Y-%m-%dT%H:%M:%S"` && sleep 30
```

They're all set to `inital`.

```
% aws ssm get-parameters-by-path --path /testyssmbak --recursive | perl -ne '@hee=split; print "$hee[4] \t\t $hee[6]\n";'
/testyssmbak/1 		 initial
/testyssmbak/2 		 initial
/testyssmbak/3 		 initial
/testyssmbak/deeper/1 		 initial
/testyssmbak/deeper/2 		 initial
/testyssmbak/deeper/3 		 initial
```


The lambda is configured to write logs to cloudwatch:

```
% SSMBAK_LAMBDANAME=`ssmbak-stack $SSMBAK_STACKNAME lambdaname`

% aws logs tail --format short /aws/lambda/$SSMBAK_LAMBDANAME
2024-06-13T20:11:07 INIT_START Runtime Version: python:3.10.v36	Runtime Version ARN: arn:aws:lambda:us-west-2::runtime:bbd47e5ef4020932b9374e2ab9f9ed3bac502f27e17a031c35d9fb8935cf1f8c
2024-06-13T20:11:07 START RequestId: d404f4c7-1c53-5e41-a7db-aa2248dee8cd Version: $LATEST
2024-06-13T20:11:10 [INFO]	2024-06-13T20:11:10.776Z	d404f4c7-1c53-5e41-a7db-aa2248dee8cd	put_object {'Bucket': 'ssmbak-bucket-vhvs73zpfvy5', 'Key': '/testyssmbak/3', 'Tagging': 'ssmbakTime=1718309456&ssmbakType=String', 'Body': 'initial'}
2024-06-13T20:11:10 [INFO]	2024-06-13T20:11:10.964Z	d404f4c7-1c53-5e41-a7db-aa2248dee8cd	result: 200
2024-06-13T20:11:11 END RequestId: d404f4c7-1c53-5e41-a7db-aa2248dee8cd
2024-06-13T20:11:11 REPORT RequestId: d404f4c7-1c53-5e41-a7db-aa2248dee8cd	Duration: 3430.49 ms	Billed Duration: 3431 ms	Memory Size: 128 MB	Max Memory Used: 84 MB	Init Duration: 282.28 ms
...
```


Update #2 for path and subpath:

```
% aws ssm put-parameter --name /testyssmbak/2 --value UPDATED --type String --overwrite
Standard        2

% aws ssm put-parameter --name /testyssmbak/deeper/2 --value UPDATED --type String --overwrite
Standard        2
```


Now #2 for each is set to `UPDATED`:

```
% aws ssm get-parameters-by-path --path /testyssmbak --recursive | perl -ne '@hee=split; print "$hee[4] \t\t $hee[6]\n";'
/testyssmbak/1 		 initial
/testyssmbak/2 		 UPDATED
/testyssmbak/3 		 initial
/testyssmbak/deeper/1 		 initial
/testyssmbak/deeper/2 		 UPDATED
/testyssmbak/deeper/3 		 initial
```


When we preview the IN_BETWEEN point-in-time, we see that everything was `initial` at that time.

```
% ssmbak preview /testyssmbak $IN_BETWEEN --recursive
+-----------------------+---------+--------+---------------------------+
| Name                  | Value   | Type   | Modified                  |
+-----------------------+---------+--------+---------------------------+
| /testyssmbak/2        | initial | String | 2024-06-13 20:10:54+00:00 |
| /testyssmbak/3        | initial | String | 2024-06-13 20:10:56+00:00 |
| /testyssmbak/deeper/3 | initial | String | 2024-06-13 20:10:56+00:00 |
| /testyssmbak/1        | initial | String | 2024-06-13 20:10:53+00:00 |
| /testyssmbak/deeper/1 | initial | String | 2024-06-13 20:10:54+00:00 |
| /testyssmbak/deeper/2 | initial | String | 2024-06-13 20:10:55+00:00 |
+-----------------------+---------+--------+---------------------------+
```


Do the restore:

```
% ssmbak restore /testyssmbak $IN_BETWEEN --recursive
+-----------------------+---------+--------+---------------------------+
| Name                  | Value   | Type   | Modified                  |
+-----------------------+---------+--------+---------------------------+
| /testyssmbak/deeper/1 | initial | String | 2024-06-13 20:10:54+00:00 |
| /testyssmbak/deeper/2 | initial | String | 2024-06-13 20:10:55+00:00 |
| /testyssmbak/1        | initial | String | 2024-06-13 20:10:53+00:00 |
| /testyssmbak/deeper/3 | initial | String | 2024-06-13 20:10:56+00:00 |
| /testyssmbak/3        | initial | String | 2024-06-13 20:10:56+00:00 |
| /testyssmbak/2        | initial | String | 2024-06-13 20:10:54+00:00 |
+-----------------------+---------+--------+---------------------------+
```


And now they're all back to `initial`:

```
% aws ssm get-parameters-by-path --path /testyssmbak --recursive | perl -ne '@hee=split; print "$hee[4] \t\t $hee[6]\n";'
/testyssmbak/1 		 initial
/testyssmbak/2 		 initial
/testyssmbak/3 		 initial
/testyssmbak/deeper/1 		 initial
/testyssmbak/deeper/2 		 initial
/testyssmbak/deeper/3 		 initial
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
